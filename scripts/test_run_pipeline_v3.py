# -*- coding: utf-8 -*-
"""Tests déterministes des adaptations V3 sans appel réseau ni Groq."""
import run_pipeline_v3 as v3
from run_pipeline_v3 import _patch_post_generation_cooldown


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


def test_v3_preserves_native_subject_selection():
    """V3 ne doit plus écraser ``selectionner_meilleurs`` de pipeline.py.

    Régression du 14/08 : la sélection native avait reçu le signal exact de
    veille et la règle « un événement par run », mais V3 remplaçait ensuite la
    fonction entière par l'ancien clustering de titres. Le code relu et le code
    réellement exécuté divergeaient silencieusement.
    """
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
'''
    original = v3._original_prepared_pipeline_source
    try:
        v3._original_prepared_pipeline_source = lambda: source
        patched = v3._prepared_pipeline_source_v3()
    finally:
        v3._original_prepared_pipeline_source = original

    assert "SIGNAL_VEILLE_CANONIQUE" in patched
    assert patched.count("def selectionner_meilleurs") == 1
    assert "selectionner_sujets" not in patched
    assert "[COOLDOWN REJET]" in patched


def main():
    test_post_generation_cooldown_is_inserted_once()
    test_patch_refuses_ambiguous_marker()
    test_v3_preserves_native_subject_selection()
    print("OK — V3 conserve la sélection native et le cooldown exact")


if __name__ == "__main__":
    main()
