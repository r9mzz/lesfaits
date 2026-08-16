#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Vérifie que le feed versionné reflète les vraies dates de publication."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from normalize_feed_pubdates import normalize


def main() -> int:
    result = normalize(ROOT, check=True)
    if result["items"] <= 0:
        raise AssertionError("Aucune entrée article vérifiée dans feed.xml")
    print(
        f"OK — feed versionné aligné sur les datePublished de "
        f"{result['items']} article(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
