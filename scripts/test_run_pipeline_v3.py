# -*- coding: utf-8 -*-
"""Tests déterministes des patches V3 sans appel réseau ni Groq."""
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


def main():
    test_post_generation_cooldown_is_inserted_once()
    test_patch_refuses_ambiguous_marker()
    print("OK — run_pipeline_v3 cooldown")


if __name__ == "__main__":
    main()
