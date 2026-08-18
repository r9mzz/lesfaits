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
- intégrité des sources des brèves qui utilisent des notes numérotées ;
- extension conservatrice du sourcing vers davantage de sources primaires et
  de rédactions internationales de référence ;
- cohérence runtime du plancher conditionnel de « Débats et nuances » ;
- restauration des vraies dates de publication RSS après le dernier rebuild ;
- restauration des vrais ``lastmod`` article du sitemap après le dernier rebuild ;
- normalisation newsletter v6 après toute reconstruction réellement exécutée.

L'arrêt avant génération quand le juge n'a trouvé aucune source traitant le
sujet précis vit maintenant NATIVEMENT dans pipeline.py (15/08) — l'ancien
patch par marqueur ici a été retiré : il dupliquait le comportement en le
couplant à une chaîne de caractères exacte, invisible au merge git, et a
cassé `main` le jour même où un autre commit a reformulé ce message.

Avant chaque vrai run, V3 rejoue aussi les tests déterministes de ses propres
adaptations. Ainsi le code exécuté en production ne dépend pas seulement d'une
CI passée : les garde-fous qui transforment réellement ``pipeline.py`` sont
revérifiés dans le même checkout, juste avant le lancement.

Aucun seuil éditorial, quota, garde factuelle ou garde vitrine n'est abaissé.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Groq a arrêté llama-3.3-70b-versatile le 16/08/2026 sur les offres free et
# developer. Le runner de production passe toujours par ce point d'entrée V3 :
# on force donc ici le remplaçant officiel avant que ``pipeline.py`` ne soit
# exécuté. Une valeur explicite NON VIDE fournie par l'environnement reste
# prioritaire pour permettre un test A/B ou une migration future sans changer
# le code. GitHub Actions exporte toutefois les expressions vides comme une
# variable présente avec valeur "" : ``setdefault`` ne la remplaçait pas et
# réactivait alors le modèle retiré. On traite donc vide/blanc comme absent.
if not os.environ.get("GROQ_MODEL_OVERRIDE", "").strip():
    os.environ["GROQ_MODEL_OVERRIDE"] = "openai/gpt-oss-120b"

import run_pipeline as legacy
from trusted_source_expansion import patch_pipeline_source as _patch_trusted_sources


_original_prepared_pipeline_source = legacy._prepared_pipeline_source
_RUNTIME_REGRESSION_TESTS = (
    "test_run_pipeline_v3.py",
    "test_trusted_source_expansion.py",
    "test_verification_scope.py",
    "test_pertinence_bloquant.py",
    "test_runtime_feed_pubdates_v3.py",
    "test_runtime_sitemap_v3.py",
    "test_runtime_newsletter_v3.py",
    "test_runtime_groq_model_v3.py",
)


def _run_runtime_regressions() -> None:
    """Rejoue les garde-fous V3 dans le checkout exact qui va produire."""
    scripts_dir = Path(__file__).resolve().parent
    for test_name in _RUNTIME_REGRESSION_TESTS:
        test_path = scripts_dir / test_name
        if not test_path.exists():
            raise RuntimeError(f"Prévol V3 incomplet : test absent {test_name}")
        subprocess.run(
            [sys.executable, str(test_path)],
            cwd=str(scripts_dir),
            check=True,
        )
    print(
        "[PRÉVOL V3] garde-fous runtime revérifiés : "
        + ", ".join(_RUNTIME_REGRESSION_TESTS)
    )


def _patch_verification_evidence_scope() -> None:
    """Restreint le contrôle « stade de recherche » aux études qui en ont un."""
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


def _patch_conditional_nuances_runtime() -> None:
    """Aligne le wrapper vitrine sur la règle « nuances seulement si sourcées »."""
    old = (
        "- Le corps doit contenir au minimum 420 mots de faits, 180 mots de contexte et\n"
        "  130 mots de nuances, en plusieurs paragraphes. Si la matière ne permet pas\n"
        "  trois sections substantielles et réellement différentes, réponds uniquement\n"
        "  HORS_PERIMETRE au lieu de remplir ou d'étirer le texte.\n"
        "- Les trois intertitres éditoriaux sont obligatoires, spécifiques au sujet et\n"
        "  ancrés dans leur section. « Les faits », « Contexte », « À retenir » ou tout\n"
        "  autre libellé générique sont interdits.\n"
        "- L'angle_reponse doit être une vraie question de lecteur, précise et non\n"
        "  interchangeable. Le résumé doit comporter exactement trois phrases : fait,\n"
        "  enjeu, puis limite ou incertitude.\n"
    )
    new = (
        "- Le corps doit contenir au minimum 420 mots de faits et 180 mots de contexte.\n"
        "  Le minimum TOTAL de 760 mots reste obligatoire. « Nuances » contient au moins\n"
        "  130 mots et plusieurs paragraphes UNIQUEMENT si les sources attestent une\n"
        "  limite, une incertitude ou un désaccord ; sinon elle reste VIDE et la profondeur\n"
        "  manquante doit venir des faits/contexte, jamais de remplissage inventé.\n"
        "- Les intertitres des sections NON VIDES sont obligatoires, spécifiques au sujet\n"
        "  et ancrés dans leur section. Aucun intertitre de nuances n'est exigé lorsque\n"
        "  cette section est vide. « Les faits », « Contexte », « À retenir » ou tout\n"
        "  autre libellé générique sont interdits.\n"
        "- L'angle_reponse doit être une vraie question de lecteur, précise et non\n"
        "  interchangeable. Le résumé doit comporter exactement trois phrases : fait,\n"
        "  enjeu, puis limite/incertitude SI elle est sourcée ; sinon une précision\n"
        "  factuelle utile, sans fabriquer une réserve.\n"
    )
    if legacy.EDITORIAL_ADDENDUM.count(old) != 1:
        raise RuntimeError(
            "Doctrine vitrine des nuances introuvable ou dupliquée dans EDITORIAL_ADDENDUM"
        )
    legacy.EDITORIAL_ADDENDUM = legacy.EDITORIAL_ADDENDUM.replace(old, new, 1)

    import showcase_quality as showcase

    if getattr(showcase.validate_generated_article, "_nuances_conditionnelles", False):
        return
    original = showcase.validate_generated_article
    nuance_only_prefixes = (
        "nuances trop court",
        "nuances insuffisamment aéré",
        "nuances trop proches du reste",
        "intertitre nuances absent",
        "section nuances sans citation numérotée",
    )

    def validate_generated_article(art: dict, article_type: str):
        ok, reasons = original(art, article_type)
        if article_type != "actu":
            return ok, reasons
        nuances = str(((art.get("corps") or {}).get("nuances") or "")).strip()
        if nuances:
            return ok, reasons
        filtered = [reason for reason in reasons if not reason.startswith(nuance_only_prefixes)]
        return not filtered, filtered

    validate_generated_article._nuances_conditionnelles = True
    showcase.validate_generated_article = validate_generated_article


def _patch_post_generation_cooldown(source: str) -> str:
    marker = "    art = _extract_json(raw)\n"
    if source.count(marker) != 1:
        raise RuntimeError("Marqueur post-génération introuvable ou dupliqué dans pipeline.py")
    replacement = marker + '''
    from editorial_ranking import _recent_rejected_slugs
    _slug_final = str(art.get("slug") or "").strip()
    if _slug_final and _slug_final in _recent_rejected_slugs():
        print(f"     [COOLDOWN REJET] slug déjà rejeté récemment : {_slug_final}")
        raise ValueError("HORS_PERIMETRE: slug déjà rejeté récemment")
'''
    return source.replace(marker, replacement, 1)


def _patch_breve_source_integrity(source: str) -> str:
    marker = '''        _showcase_ok, _showcase_reasons = validate_generated_article(art, article_type)\n        if not _showcase_ok:\n'''
    if source.count(marker) != 1:
        raise RuntimeError("Marqueur garde vitrine introuvable ou dupliqué dans pipeline préparé")
    replacement = '''        _showcase_ok, _showcase_reasons = validate_generated_article(art, article_type)
        if article_type == "breve":
            _brief_body = art.get("corps") or {}
            _brief_text = " ".join([str(x) for x in (art.get("resume") or [])] + [str(_brief_body.get("faits") or "")])
            _brief_citations = [int(n) for n in re.findall(r"\\[(\\d+)\\]", _brief_text)]
            if _brief_citations:
                _brief_expected = set(range(1, len(art.get("sources") or []) + 1))
                _brief_cited = set(_brief_citations)
                if _brief_cited != _brief_expected:
                    _brief_missing = sorted(_brief_expected - _brief_cited)
                    _showcase_ok = False
                    _showcase_reasons.append("brève avec notes : sources listées mais non citées dans le texte : " + str(_brief_missing[:6]))
        if not _showcase_ok:
'''
    return source.replace(marker, replacement, 1)


def _normalize_feed_after_runtime() -> dict[str, int]:
    """Restaure les vraies ``pubDate`` RSS après le dernier rebuild du runtime.

    Le générateur historique date chaque entrée RSS avec l'heure du rebuild.
    Sans cette étape, même un run technique à zéro article fait remonter tout le
    corpus comme s'il venait d'être publié. La source de vérité reste le
    ``datePublished`` JSON-LD de chaque article ; ``lastBuildDate`` garde, lui,
    l'instant réel du rebuild. La normalisation se fait avant la sauvegarde du
    checkout, comme les autres réparations runtime V3.
    """
    from normalize_feed_pubdates import normalize as normalize_feed

    root = Path(__file__).resolve().parent.parent
    result = normalize_feed(root)
    print(
        f"[RUNTIME V3] dates RSS normalisées avant sauvegarde : "
        f"{result['changed']} pubDate corrigée(s)"
    )
    return result


def _normalize_sitemap_after_runtime() -> dict[str, int]:
    """Restaure les vrais ``lastmod`` article après le dernier rebuild.

    Le générateur historique applique la date du rebuild à toutes les entrées
    article du sitemap, y compris lorsqu'aucun article n'a changé. On réutilise
    donc le normaliseur canonique juste avant la sauvegarde afin que chaque
    article conserve la date portée par ses métadonnées publiées.
    """
    from normalize_sitemap_lastmod import normalize as normalize_sitemap

    root = Path(__file__).resolve().parent.parent
    result = normalize_sitemap(root)
    print(
        f"[RUNTIME V3] lastmod sitemap normalisés avant sauvegarde : "
        f"{result['changed']} date(s) corrigée(s), {result['removed']} redirection(s) retirée(s)"
    )
    return result


def _normalize_newsletter_after_runtime() -> dict[str, int]:
    """Normalise la vitrine après le dernier rebuild du runtime, avant le commit.

    ``pipeline.py`` contient encore le gabarit historique de newsletter. Les
    workflows de réparation le remettaient en v6 APRES le push, créant une
    régression temporaire et un second commit même lorsqu'aucun article n'avait
    été publié. Ici on réutilise la normalisation canonique existante dans le
    même processus, une fois que tous les rebuilds de ``legacy.main`` sont finis.
    """
    from harden_newsletter_v3 import run as normalize_newsletter

    root = Path(__file__).resolve().parent.parent
    result = normalize_newsletter(root)
    print(
        f"[RUNTIME V3] newsletter v6 normalisée avant sauvegarde : "
        f"{result['changed']} page(s) corrigée(s)"
    )
    return result


def _prepared_pipeline_source_v3() -> str:
    source = _original_prepared_pipeline_source()
    source = _patch_post_generation_cooldown(source)
    source = _patch_breve_source_integrity(source)
    source = _patch_trusted_sources(source)
    compile(source, str(legacy.PIPELINE), "exec")
    print("[PRÉVOL V3] sélection native pipeline.py + cooldown post-génération + intégrité sources brèves + sourcing fiable étendu")
    return source


legacy._prepared_pipeline_source = _prepared_pipeline_source_v3


if __name__ == "__main__":
    _run_runtime_regressions()
    _patch_verification_evidence_scope()
    _patch_conditional_nuances_runtime()
    _exit_code = legacy.main()
    if "--dry-run" not in sys.argv[1:]:
        _normalize_feed_after_runtime()
        # La newsletter doit être normalisée AVANT le sitemap : le rebuild
        # historique peut modifier temporairement ces HTML, puis ce passage les
        # remet exactement à leur état canonique. Le sitemap peut alors décider
        # correctement si une page hors article a réellement changé depuis HEAD.
        _normalize_newsletter_after_runtime()
        _normalize_sitemap_after_runtime()
    sys.exit(_exit_code)
