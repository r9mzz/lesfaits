# -*- coding: utf-8 -*-
"""Tests déterministes du sourcing fiable étendu, sans réseau."""
from __future__ import annotations

from trusted_source_expansion import (
    EXTRA_CATEGORY_AXES,
    EXTRA_PRIMARY_DOMAINS,
    EXTRA_SECONDARY_DOMAINS,
    EXTRA_UNIVERSAL_AXES,
    patch_pipeline_source,
)


SYNTHETIC = '''
_DOMAINES_PRIMAIRES = ("insee.fr",)
_DOMAINES_SECONDAIRES = ("reuters.com",)


def qualite_source(url: str) -> str:
    return "x"

_AXES_UNIVERSELS = (("générique", ""),)
_AXES_PAR_CATEGORIE = {"sante": (("santé officielle", "site:who.int"),)}


def _requetes_recherche(query: str, categorie: str = "") -> list[tuple[str, str]]:
    return []


def duckduckgo_search(query: str, max_results: int = 8, categorie: str = "") -> list[dict]:
    class DDGS:
        def text(self, *args, **kwargs):
            return []
    ddgs = DDGS()
    q = query
    for r in ddgs.text(q, max_results=10, region="fr-fr"):
        pass
    return []
'''


def test_policy_is_large_but_whitelisted():
    assert len(EXTRA_PRIMARY_DOMAINS) >= 30
    assert len(EXTRA_SECONDARY_DOMAINS) >= 10
    assert len(EXTRA_UNIVERSAL_AXES) >= 3
    assert set(("sante", "science", "environnement", "economie", "societe", "tech")) <= set(EXTRA_CATEGORY_AXES)
    # Les réseaux sociaux/agrégateurs ne doivent jamais devenir fiables par ce module.
    forbidden = {"facebook.com", "x.com", "reddit.com", "news.google.com", "msn.com"}
    assert forbidden.isdisjoint(EXTRA_PRIMARY_DOMAINS)
    assert forbidden.isdisjoint(EXTRA_SECONDARY_DOMAINS)


def test_patch_extends_without_lowering_any_threshold():
    patched = patch_pipeline_source(SYNTHETIC)
    assert "EXTRA_PRIMARY_DOMAINS" in patched
    assert "EXTRA_SECONDARY_DOMAINS" in patched
    assert "EXTRA_UNIVERSAL_AXES" in patched
    assert "EXTRA_CATEGORY_AXES" in patched
    assert 'max_results: int = 24' in patched
    assert 'max_results=16' in patched
    # Le patch n'introduit aucun changement de seuil éditorial ou de publication.
    lowered_markers = ("seuil_score =", "MIN_SOURCES =", "MIN_WORDS =", "QUOTA_ARTICLES_LONGS =")
    assert not any(marker in patched for marker in lowered_markers)
    compile(patched, "synthetic_trusted_sources.py", "exec")


def test_patch_fails_closed_if_pipeline_structure_changes():
    try:
        patch_pipeline_source("def qualite_source(url):\n    return 'x'\n")
    except RuntimeError:
        return
    raise AssertionError("Le prévol doit échouer si les marqueurs de sourcing disparaissent")


def main() -> None:
    test_policy_is_large_but_whitelisted()
    test_patch_extends_without_lowering_any_threshold()
    test_patch_fails_closed_if_pipeline_structure_changes()
    print("OK — sourcing fiable étendu")


if __name__ == "__main__":
    main()
