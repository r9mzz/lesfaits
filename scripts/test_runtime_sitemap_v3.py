#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Régression : le runtime V3 doit normaliser le sitemap après le dernier rebuild."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "scripts" / "run_pipeline_v3.py"


def test_runtime_normalizes_sitemap_after_legacy_and_skips_dry_run() -> None:
    source = RUNTIME.read_text(encoding="utf-8")
    main = source[source.index('if __name__ == "__main__":'):]

    legacy_pos = main.index("_exit_code = legacy.main()")
    guard_pos = main.index('if "--dry-run" not in sys.argv[1:]:')
    feed_pos = main.index("_normalize_feed_after_runtime()", guard_pos)
    sitemap_pos = main.index("_normalize_sitemap_after_runtime()", guard_pos)
    newsletter_pos = main.index("_normalize_newsletter_after_runtime()", guard_pos)
    exit_pos = main.index("sys.exit(_exit_code)")

    assert legacy_pos < guard_pos < feed_pos < sitemap_pos < newsletter_pos < exit_pos
    assert "from normalize_sitemap_lastmod import normalize as normalize_sitemap" in source
    assert '"test_runtime_sitemap_v3.py"' in source


if __name__ == "__main__":
    test_runtime_normalizes_sitemap_after_legacy_and_skips_dry_run()
    print("OK — normalisation sitemap verrouillée dans le runtime V3")
