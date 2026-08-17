#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Régression: le sitemap versionné doit déjà être normalisé.

Ce test protège l'état réellement publié, pas seulement la fonction de
normalisation. Il échoue si un rebuild a laissé des lastmod d'articles
artificiellement alignés sur la date du rebuild ou si une redirection noindex
reste indexée.
"""
from __future__ import annotations

from normalize_sitemap_lastmod import ROOT, normalize


def main() -> int:
    result = normalize(ROOT, check=True)
    assert result["changed"] == 0, result
    assert result["removed"] == 0, result
    assert result["missing"] == 0, result
    print("OK: sitemap.xml versionné est déjà normalisé")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
