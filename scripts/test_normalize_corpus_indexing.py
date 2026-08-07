#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import normalize_corpus_indexing as corpus


NEWS = '''<!doctype html><html><head>
<meta name="robots" content="index, follow"/>
<script type="application/ld+json">{"@type":"NewsArticle","headline":"Test"}</script>
</head><body>Test</body></html>'''


def main() -> int:
    old = (corpus.ROOT, corpus.ARTICLES_DIR, corpus.MANIFEST, corpus.RETIREMENTS)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            articles = root / "articles"
            data = root / "data"
            articles.mkdir()
            data.mkdir()
            (articles / "active.html").write_text(NEWS, encoding="utf-8")
            (articles / "orphan.html").write_text(NEWS, encoding="utf-8")
            (data / "articles.json").write_text(
                json.dumps([{"slug": "active"}]), encoding="utf-8"
            )
            (data / "retirements.json").write_text("[]", encoding="utf-8")

            corpus.ROOT = root
            corpus.ARTICLES_DIR = articles
            corpus.MANIFEST = data / "articles.json"
            corpus.RETIREMENTS = data / "retirements.json"

            changed, failures = corpus.run(check=False)
            assert failures == [], failures
            assert changed == 1, changed
            active = (articles / "active.html").read_text(encoding="utf-8")
            orphan = (articles / "orphan.html").read_text(encoding="utf-8")
            assert 'content="index, follow"' in active
            assert 'content="noindex, follow"' in orphan

            changed_check, failures_check = corpus.run(check=True)
            assert changed_check == 0, changed_check
            assert failures_check == [], failures_check

        print("test_normalize_corpus_indexing: OK")
        return 0
    finally:
        corpus.ROOT, corpus.ARTICLES_DIR, corpus.MANIFEST, corpus.RETIREMENTS = old


if __name__ == "__main__":
    raise SystemExit(main())
