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
import verification as verification_module


_original_prepared_pipeline_source = legacy._prepared_pipeline_source


def _patch_verification_evidence_scope() -> None:
    """Restreint le contrôle « stade de recherche » aux études qui en ont un.

    Retour du run du 14/08 : une enquête démographique descriptive CSF-2023 a
    été rejetée trois fois parce que le fact-checker exigeait une « phase » ou
    un « stade de recherche ». Cette exigence a du sens pour un essai médical,
    préclinique ou une étude d'efficacité, pas pour une enquête de population.

    On ne désactive aucun contrôle de preuve : une enquête doit toujours donner
    sa population, sa période, son échantillon et ses limites méthodologiques.
    Le patch ne retire que le faux critère de phase/stade lorsqu'il n'existe pas
    par nature.
    """
    old = (
        '- niveau_preuve_insuffisant : article médical ou scientifique qui présente un résultat d\'essai comme une efficacité acquise. '
        'Est un problème si l\'une de ces conditions est vraie : (a) le stade de la recherche (phase 1/1b/2/3, préclinique, étude observationnelle) '
        'n\'apparaît NI dans le résumé NI à côté du résultat principal alors que la source le précise ;'
    )
    new = (
        '- niveau_preuve_insuffisant : article médical ou scientifique qui présente un résultat expérimental ou d\'efficacité avec un niveau de preuve plus fort que celui des sources. '
        'Est un problème si l\'une de ces conditions est vraie : (a) POUR UN ESSAI, UNE ÉTUDE CLINIQUE, PRÉCLINIQUE OU D\'EFFICACITÉ, le stade de la recherche '
        '(phase 1/1b/2/3, préclinique, observationnelle) n\'apparaît NI dans le résumé NI à côté du résultat principal alors que la source le précise. '
        'NE PAS appliquer ce critère de « stade/phase » à une enquête descriptive, démographique, sociologique ou statistique qui n\'a pas de phase par nature ; '
        'dans ce cas, contrôler à la place la population étudiée, la période, la taille/constitution de l\'échantillon et les limites méthodologiques ;'
    )
    prompt = verification_module.PROMPT_DETECTION
    if prompt.count(old) != 1:
        raise RuntimeError(
            "Règle niveau_preuve_insuffisant introuvable ou dupliquée dans PROMPT_DETECTION"
        )
    verification_module.PROMPT_DETECTION = prompt.replace(old, new, 1)


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
    _patch_verification_evidence_scope()
    sys.exit(legacy.main())
