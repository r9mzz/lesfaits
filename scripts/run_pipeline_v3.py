# -*- coding: utf-8 -*-
"""Point d'entrée V3 : qualité rédactionnelle + sélection au niveau du sujet.

Ce wrapper réutilise intégralement ``run_pipeline.py`` puis remplace uniquement
la fonction de sélection finale dans la copie en mémoire de ``pipeline.py``.
Aucun seuil de filtrage, quota de catégorie, garde factuelle ou garde vitrine
n'est abaissé.
"""
from __future__ import annotations

import re
import sys

import run_pipeline as legacy


_original_prepared_pipeline_source = legacy._prepared_pipeline_source


def _patch_subject_level_selection(source: str) -> str:
    pattern = re.compile(
        r"def selectionner_meilleurs\(\n"
        r"(?:.|\n)*?"
        r"^    return selection\n",
        re.MULTILINE,
    )
    matches = list(pattern.finditer(source))
    if len(matches) != 1:
        raise RuntimeError(
            "Fonction selectionner_meilleurs introuvable ou dupliquée : "
            f"{len(matches)} occurrence(s)"
        )

    replacement = '''def selectionner_meilleurs(
    candidats: list[dict],
    nb_max: int = 10,
    quota_cat: int = QUOTA_CATEGORIE,
) -> list[dict]:
    """Sélectionne des SUJETS, pas des articles RSS isolés.

    Tous les candidats ont déjà franchi le filtre éditorial historique. Cette
    étape ne baisse donc aucun seuil : elle regroupe les couvertures du même
    événement, garde le meilleur représentant et utilise la corroboration
    multi-médias uniquement comme critère de CLASSEMENT.
    """
    from editorial_ranking import selectionner_sujets

    selection = selectionner_sujets(
        candidats=candidats,
        nb_max=nb_max,
        quota_cat=quota_cat,
        quotas_par_categorie=QUOTA_PAR_CATEGORIE,
    )
    if selection:
        multi = sum(1 for i in selection if i.get("_corroboration_medias", 1) >= 2)
        forts = sum(1 for i in selection if i.get("_corroboration_medias", 1) >= 3)
        print(
            f"  [SÉLECTION SUJETS] {len(selection)} sujets : "
            f"{multi} multi-sources, dont {forts} couverts par ≥3 médias"
        )
        for item in selection[:10]:
            print(
                "    "
                f"score brut={item.get('_score', '?')} "
                f"+ bonus={item.get('_selection_bonus', 0)} "
                f"({item.get('_corroboration_medias', 1)} média(s)) — "
                f"{item.get('title', '')[:90]}"
            )
    return selection
'''
    return source[: matches[0].start()] + replacement + source[matches[0].end() :]


def _patch_post_generation_cooldown(source: str) -> str:
    """Évite un second fact-check d'un article qui régénère le même slug rejeté.

    Le préfiltre amont compare le titre RSS au slug historique et reste
    volontairement strict. Ce second garde-fou intervient après génération,
    lorsque le slug exact est enfin connu. Il ne bloque qu'une égalité exacte
    avec un rejet récent et ne change aucun seuil éditorial.
    """
    marker = "    art = _extract_json(raw)\n"
    if source.count(marker) != 1:
        raise RuntimeError(
            "Marqueur post-génération introuvable ou dupliqué dans pipeline.py"
        )
    replacement = marker + '''
    # Cooldown exact POST-GÉNÉRATION : le titre RSS peut différer du slug que
    # le rédacteur génère. On contrôle donc aussi le slug final avant de payer
    # le fact-check. C'est ce qui empêche un même slug rejeté de repartir au
    # vérificateur au run suivant sans risquer de masquer une actualité voisine.
    from editorial_ranking import _recent_rejected_slugs
    _slug_final = str(art.get("slug") or "").strip()
    if _slug_final and _slug_final in _recent_rejected_slugs():
        print(f"     [COOLDOWN REJET] slug déjà rejeté récemment : {_slug_final}")
        raise ValueError("HORS_PERIMETRE: slug déjà rejeté récemment")
'''
    return source.replace(marker, replacement, 1)


def _prepared_pipeline_source_v3() -> str:
    source = _original_prepared_pipeline_source()
    source = _patch_subject_level_selection(source)
    source = _patch_post_generation_cooldown(source)
    compile(source, str(legacy.PIPELINE), "exec")
    print("[PRÉVOL V3] classement au niveau du sujet + cooldown post-génération activés")
    return source


legacy._prepared_pipeline_source = _prepared_pipeline_source_v3


if __name__ == "__main__":
    sys.exit(legacy.main())