#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
from pathlib import Path

import normalize_publication_metadata as publication
import normalize_visible_publication_time as visible


MODERN = '''<!doctype html><html><head>
<script type="application/ld+json">{"@type":"NewsArticle","headline":"Test","datePublished":"2026-07-25T14:09:17+02:00","dateModified":"2026-07-25T14:09:17+02:00"}</script>
</head><body><time datetime="2026-07-25T14:09:17+02:00">25 juillet 2026, 14h08</time></body></html>'''

LEGACY = '''<!doctype html><html><head>
<script type="application/ld+json">{"@type":"NewsArticle","headline":"Archive","datePublished":"2026-06-26","dateModified":"2026-06-26"}</script>
</head><body><time datetime="2026-06-26">26 juin 2026, 19h42</time></body></html>'''


def main() -> int:
    old = (publication.ROOT, publication.ARTICLES_DIR)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            articles = root / "articles"
            articles.mkdir()
            modern = articles / "modern.html"
            legacy = articles / "legacy.html"
            modern.write_text(MODERN, encoding="utf-8")
            legacy.write_text(LEGACY, encoding="utf-8")

            publication.ROOT = root
            publication.ARTICLES_DIR = articles

            changed, failures = visible.run(check=False)
            assert failures == [], failures
            assert changed == 1, changed

            modern_html = modern.read_text(encoding="utf-8")
            legacy_html = legacy.read_text(encoding="utf-8")
            assert (
                '<time datetime="2026-07-25T14:09:17+02:00">25 juillet 2026, 14h09</time>'
                in modern_html
            )
            # L'heure d'une archive date-only n'est jamais reconstruite.
            assert "26 juin 2026, 19h42" in legacy_html

            changed_check, failures_check = visible.run(check=True)
            assert changed_check == 0, changed_check
            assert failures_check == [], failures_check

        print("test_normalize_visible_publication_time: OK")
        return 0
    finally:
        publication.ROOT, publication.ARTICLES_DIR = old


if __name__ == "__main__":
    raise SystemExit(main())
