#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Régression : le runtime V3 doit finir en newsletter v6 avant le push."""
from __future__ import annotations

from pathlib import Path

from harden_newsletter_v3 import SCRIPT_SRC, harden_html, validate_v3

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "scripts" / "run_pipeline_v3.py"


def _stale_runtime_html() -> str:
    return '''<!doctype html>
<html><head>
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; form-action 'self';"/>
<script src="/src/newsletter.js?v=5" defer></script>
</head><body>
<section class="nl-compact" id="newsletter">
<form id="nl-form" novalidate>
  <div class="nl-compact__freq" role="group">
    <label><input type="radio" name="FREQ" value="morning"/> Matin</label>
    <label><input type="radio" name="FREQ" value="evening"/> Soir</label>
    <label><input type="radio" name="FREQ" value="both" checked/> Les deux</label>
  </div>
  <div class="nl-compact__row"><input id="nl-email" name="EMAIL" type="email"/></div>
  <div class="nl-compact__cats">
    <label><input type="checkbox" name="CAT_SOCIETE"/></label>
    <label><input type="checkbox" name="CAT_SCIENCE"/></label>
    <label><input type="checkbox" name="CAT_ECONOMIE"/></label>
    <label><input type="checkbox" name="CAT_TECH"/></label>
    <label><input type="checkbox" name="CAT_SANTE"/></label>
    <label><input type="checkbox" name="CAT_ENVIRONNEMENT"/></label>
  </div>
  <p class="nl-compact__hint">ancienne aide</p>
  <label class="nl-compact__consent"><input id="nl-consent" type="checkbox" name="CONSENT" required/></label>
  <p id="nl-msg"></p>
</form>
</section>
</body></html>'''


def test_hardener_repairs_runtime_output() -> None:
    upgraded = harden_html(_stale_runtime_html())
    assert SCRIPT_SRC in upgraded
    assert 'data-newsletter-version="6"' in upgraded
    assert 'name="LF_FREQ" value="both"' in upgraded
    assert 'data-brevo-name="CAT_SOCIETE"' in upgraded
    assert 'target="lf-newsletter-sink"' in upgraded
    assert 'name="CONSENT"' not in upgraded
    assert validate_v3(Path("index.html"), upgraded) == []
    assert harden_html(upgraded) == upgraded


def test_runtime_calls_normalizer_after_legacy_and_skips_dry_run() -> None:
    source = RUNTIME.read_text(encoding="utf-8")
    main = source[source.index('if __name__ == "__main__":'):]
    legacy_pos = main.index("_exit_code = legacy.main()")
    guard_pos = main.index('if "--dry-run" not in sys.argv[1:]:')
    normalize_pos = main.index("_normalize_newsletter_after_runtime()", guard_pos)
    exit_pos = main.index("sys.exit(_exit_code)")
    assert legacy_pos < guard_pos < normalize_pos < exit_pos
    assert 'from harden_newsletter_v3 import run as normalize_newsletter' in source
    assert '"test_runtime_newsletter_v3.py"' in source


if __name__ == "__main__":
    test_hardener_repairs_runtime_output()
    test_runtime_calls_normalizer_after_legacy_and_skips_dry_run()
    print("OK — normalisation newsletter v6 verrouillée dans le runtime V3")
