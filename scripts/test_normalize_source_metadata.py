#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
from pathlib import Path

import normalize_source_metadata as metadata


HTML = '''<!doctype html><html lang="fr"><body>
<div class="art__meta"><span>3 sources</span></div>
<div class="sources"><h3>SOURCES</h3><ol>
<li><a href="https://www.example.com/a">A</a></li>
<li><a href="https://example.com/b">B</a></li>
<li><a href="https://autre.fr/c">C</a></li>
</ol></div>
<div class="art__pourquoi"><ul><li><strong>Sources :</strong> 0 sources distinctes — les sources listées ci-dessus.</li></ul></div>
</body></html>'''


def main() -> int:
    old_root, old_articles = metadata.ROOT, metadata.ARTICLES_DIR
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            articles = root / "articles"
            articles.mkdir()
            path = articles / "test.html"
            path.write_text(HTML, encoding="utf-8")
            metadata.ROOT = root
            metadata.ARTICLES_DIR = articles

            changed, failures = metadata.run(check=False)
            assert failures == [], failures
            assert changed == 1, changed
            result = path.read_text(encoding="utf-8")
            assert "2 sources distinctes" in result
            assert "0 sources distinctes" not in result

            changed_check, failures_check = metadata.run(check=True)
            assert changed_check == 0, changed_check
            assert failures_check == [], failures_check

        print("test_normalize_source_metadata: OK")
        return 0
    finally:
        metadata.ROOT, metadata.ARTICLES_DIR = old_root, old_articles


if __name__ == "__main__":
    raise SystemExit(main())
