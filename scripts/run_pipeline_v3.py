# -*- coding: utf-8 -*-
"""Point d'entrée V3 : qualité rédactionnelle sans second cerveau de sélection.

Ce wrapper réutilise ``run_pipeline.py`` et laisse désormais ``pipeline.py``
exécuter sa propre sélection finale. C'est essentiel : la sélection native
porte les corrections les plus récentes (signal exact de veille, un seul sujet
par grappe dans un run, déclassements mesurés). La remplacer ici par un second
clustering de titres recréait une doctrine concurrente et pouvait annuler ces
correctifs au runtime.

V3 ne conserve que les adaptations qui ne redéfinissent pas le classement :
- portée correcte du contrôle de niveau de preuve ;
- cooldown exact post-génération sur un slug déjà rejeté récemment ;
- intégrité des sources des brèves qui utilisent des notes numérotées.

Aucun seuil éditorial, quota, garde factuelle ou garde vitrine n'est abaissé.
"""
from __future__ import annotations

import sys

import run_pipeline as legacy


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
    import verification as verification_module

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


def _patch_breve_source_integrity(source: str) -> str:
    """Refuse une brève à notes numérotées qui affiche des sources inutilisées.

    Une brève native peut légitimement attribuer ses sources en prose et ne
    contenir aucune note [n]. En revanche, quand des notes numérotées existent,
    la liste SOURCES doit correspondre exactement aux sources effectivement
    appelées. Le 14/08, une brève inflation affichait quatre sources alors que
    seules les notes [1] et [3] apparaissaient : le compteur et la hiérarchie
    de sourcing donnaient alors une impression de preuve supérieure au texte.

    Ce garde-fou ne demande aucune nouvelle source et n'abaisse aucun seuil :
    il refuse seulement un état incohérent déjà objectivement observable.
    """
    marker = '''        _showcase_ok, _showcase_reasons = validate_generated_article(art, article_type)\n        if not _showcase_ok:\n'''
    if source.count(marker) != 1:
        raise RuntimeError(
            "Marqueur garde vitrine introuvable ou dupliqué dans pipeline préparé"
        )
    replacement = '''        _showcase_ok, _showcase_reasons = validate_generated_article(art, article_type)
        if article_type == "breve":
            _brief_body = art.get("corps") or {}
            _brief_text = " ".join(
                [str(x) for x in (art.get("resume") or [])]
                + [str(_brief_body.get("faits") or "")]
            )
            _brief_citations = [int(n) for n in re.findall(r"\\[(\\d+)\\]", _brief_text)]
            if _brief_citations:
                _brief_expected = set(range(1, len(art.get("sources") or []) + 1))
                _brief_cited = set(_brief_citations)
                if _brief_cited != _brief_expected:
                    _brief_missing = sorted(_brief_expected - _brief_cited)
                    _showcase_ok = False
                    _showcase_reasons.append(
                        "brève avec notes : sources listées mais non citées dans le texte : "
                        + str(_brief_missing[:6])
                    )
        if not _showcase_ok:
'''
    return source.replace(marker, replacement, 1)


def _prepared_pipeline_source_v3() -> str:
    source = _original_prepared_pipeline_source()
    # IMPORTANT : ne jamais remplacer selectionner_meilleurs ici. Le classement
    # canonique vit dans pipeline.py et doit rester identique entre le code lu,
    # les tests et le cron réellement exécuté.
    source = _patch_post_generation_cooldown(source)
    source = _patch_breve_source_integrity(source)
    compile(source, str(legacy.PIPELINE), "exec")
    print(
        "[PRÉVOL V3] sélection native pipeline.py + cooldown post-génération "
        "+ intégrité sources brèves activés"
    )
    return source


legacy._prepared_pipeline_source = _prepared_pipeline_source_v3


if __name__ == "__main__":
    _patch_verification_evidence_scope()
    sys.exit(legacy.main())
