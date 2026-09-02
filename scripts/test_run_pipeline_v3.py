# -*- coding: utf-8 -*-
"""Tests déterministes des adaptations V3 sans appel réseau ni Groq."""
import os

# Ce fichier est rejoué depuis le runtime de production avec les vraies variables
# fournisseur héritées. Il doit rester strictement déterministe : le prévol réseau
# réel a déjà été exécuté par le processus parent avant le lancement des tests.
os.environ["LLM_SKIP_ACCESS_PROBE"] = "1"

import run_pipeline_v3 as v3
from run_pipeline_v3 import (
    _patch_breve_source_integrity,
    _patch_conditional_nuances_runtime,
    _patch_post_generation_cooldown,
)


def test_runtime_regression_import_never_probes_provider():
    assert os.environ.get("LLM_SKIP_ACCESS_PROBE") == "1"


def test_post_generation_cooldown_is_inserted_once():
    source = '''def generate():
    art = _extract_json(raw)
    return art
'''
    patched = _patch_post_generation_cooldown(source)
    assert patched.count("[COOLDOWN REJET]") == 1
    assert '_slug_final in _recent_rejected_slugs()' in patched
    assert 'HORS_PERIMETRE: slug déjà rejeté récemment' in patched
    compile(patched, "synthetic_pipeline.py", "exec")


def test_patch_refuses_ambiguous_marker():
    source = '''def a():
    art = _extract_json(raw)
def b():
    art = _extract_json(raw)
'''
    try:
        _patch_post_generation_cooldown(source)
    except RuntimeError:
        return
    raise AssertionError("Un marqueur dupliqué doit faire échouer le prévol")


def test_breve_with_numbered_notes_must_use_every_listed_source():
    source = '''def save(art, article_type):
        _showcase_ok, _showcase_reasons = validate_generated_article(art, article_type)
        if not _showcase_ok:
            return False
        return True
'''
    patched = _patch_breve_source_integrity(source)
    assert "brève avec notes : sources listées mais non citées" in patched
    assert "_brief_cited != _brief_expected" in patched
    compile(patched, "synthetic_showcase_guard.py", "exec")

    namespace = {
        "re": __import__("re"),
        "validate_generated_article": lambda art, article_type: (True, []),
    }
    exec(patched, namespace)
    art = {
        "resume": ["Inflation confirmée [1]."],
        "corps": {"faits": "La hausse atteint un nouveau niveau [3]."},
        "sources": [{}, {}, {}, {}],
    }
    assert namespace["save"](art, "breve") is False, (
        "Une brève qui liste quatre sources mais n'appelle que [1] et [3] doit être refusée"
    )


def test_native_breve_without_numbered_notes_remains_allowed():
    source = '''def save(art, article_type):
        _showcase_ok, _showcase_reasons = validate_generated_article(art, article_type)
        if not _showcase_ok:
            return False
        return True
'''
    patched = _patch_breve_source_integrity(source)
    namespace = {
        "re": __import__("re"),
        "validate_generated_article": lambda art, article_type: (True, []),
    }
    exec(patched, namespace)
    art = {
        "resume": ["Selon l'Insee, l'inflation accélère en juillet."],
        "corps": {"faits": "Reuters et France Info détaillent la même publication."},
        "sources": [{}, {}, {}],
    }
    assert namespace["save"](art, "breve") is True, (
        "Une brève native attribuée en prose ne doit pas être forcée au format [n]"
    )


def test_conditional_nuances_align_prompt_and_showcase_without_lowering_other_gates():
    """Une section vide est admise, mais aucun autre défaut vitrine ne disparaît."""
    import showcase_quality as showcase

    original_addendum = v3.legacy.EDITORIAL_ADDENDUM
    original_validate = showcase.validate_generated_article
    try:
        # Simule exactement les refus que l'ancienne grille émet pour une
        # section nuances vide, plus un défaut indépendant qui doit survivre.
        def fake_validate(art, article_type):
            return False, [
                "nuances trop court (0 mots, minimum vitrine 130)",
                "nuances insuffisamment aéré (0 paragraphe(s))",
                "nuances trop proches du reste (0% de matière nouvelle)",
                "intertitre nuances absent, générique ou non ancré dans la section",
                "section nuances sans citation numérotée",
                "total trop court (700 mots, minimum vitrine 760)",
            ]

        showcase.validate_generated_article = fake_validate
        _patch_conditional_nuances_runtime()

        assert "Le minimum TOTAL de 760 mots reste obligatoire" in v3.legacy.EDITORIAL_ADDENDUM
        assert "sinon elle reste VIDE" in v3.legacy.EDITORIAL_ADDENDUM
        assert "130 mots de nuances" not in v3.legacy.EDITORIAL_ADDENDUM

        ok, reasons = showcase.validate_generated_article(
            {"corps": {"nuances": ""}}, "actu"
        )
        assert ok is False
        assert reasons == ["total trop court (700 mots, minimum vitrine 760)"], reasons

        # Si les nuances existent, les contrôles propres à la section restent
        # entièrement actifs : aucune baisse de garde pour un texte présent.
        ok, reasons = showcase.validate_generated_article(
            {"corps": {"nuances": "Une réserve sourcée existe."}}, "actu"
        )
        assert ok is False
        assert any(r.startswith("nuances trop court") for r in reasons)
    finally:
        v3.legacy.EDITORIAL_ADDENDUM = original_addendum
        showcase.validate_generated_article = original_validate


def test_v3_preserves_native_subject_selection():
    """V3 ne doit plus écraser ``selectionner_meilleurs`` de pipeline.py."""
    source = '''
QUOTA_CATEGORIE = 6

def selectionner_meilleurs(candidats, nb_max=10, quota_cat=QUOTA_CATEGORIE):
    # SIGNAL_VEILLE_CANONIQUE
    grappes_vues = set()
    selection = []
    for item in candidats:
        grappe = (item.get("_veille") or {}).get("grappe")
        if grappe and grappe in grappes_vues:
            continue
        selection.append(item)
        if grappe:
            grappes_vues.add(grappe)
    return selection


def _extract_json(raw):
    return {"slug": "test"}


def generer():
    raw = "{}"
    art = _extract_json(raw)
    return art


def save(art, article_type):
        _showcase_ok, _showcase_reasons = validate_generated_article(art, article_type)
        if not _showcase_ok:
            return False
        return True
'''
    original = v3._original_prepared_pipeline_source
    original_sources = v3._patch_trusted_sources
    try:
        v3._original_prepared_pipeline_source = lambda: source
        # Le sourcing étendu possède son propre test structurel ; ici on isole
        # la propriété « V3 ne remplace jamais la sélection native ».
        v3._patch_trusted_sources = lambda text: text
        patched = v3._prepared_pipeline_source_v3()
    finally:
        v3._original_prepared_pipeline_source = original
        v3._patch_trusted_sources = original_sources

    assert "SIGNAL_VEILLE_CANONIQUE" in patched
    assert patched.count("def selectionner_meilleurs") == 1
    assert "selectionner_sujets" not in patched
    assert "[COOLDOWN REJET]" in patched
    assert "_brief_cited != _brief_expected" in patched


def main():
    test_runtime_regression_import_never_probes_provider()
    test_post_generation_cooldown_is_inserted_once()
    test_patch_refuses_ambiguous_marker()
    test_breve_with_numbered_notes_must_use_every_listed_source()
    test_native_breve_without_numbered_notes_remains_allowed()
    test_conditional_nuances_align_prompt_and_showcase_without_lowering_other_gates()
    test_v3_preserves_native_subject_selection()
    print("OK — V3 sélection native, cooldown, sources brèves, nuances conditionnelles et import hors réseau")


if __name__ == "__main__":
    main()
