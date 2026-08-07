# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import harden_newsletter_v3 as v3


OLD_PAGE = '''<!doctype html><html><head>
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self'; connect-src 'self' https://e6ad0381.sibforms.com; base-uri 'self';">
<script src="/src/newsletter.js?v=2" defer></script>
</head><body>
<section class="nl-compact" id="newsletter">
<form id="nl-form" data-newsletter-version="2" novalidate>
<div class="nl-compact__freq" role="group"><label><input name="FREQ" value="both" checked>Les deux</label></div>
<input type="email" id="nl-email" name="EMAIL">
<div class="nl-compact__cats" role="group">
<label><input name="CAT_SANTE" value="1">Santé</label>
<label><input name="CAT_TECH" value="1">Tech</label>
</div>
<p class="nl-compact__hint" id="nl-hint">Choisissez vos rubriques, ou laissez tout décoché pour tout recevoir.</p>
<input type="checkbox" id="nl-consent" name="CONSENT" required>
<p class="nl-compact__msg" id="nl-msg"></p>
</form>
<noscript><p class="nl-compact__hint" data-newsletter-noscript="1">Ouvrir Brevo</p></noscript>
</section>
</body></html>'''


class NewsletterV3Tests(unittest.TestCase):
    def test_upgrade_removes_unsupported_preferences(self):
        updated = v3.upgrade_html(OLD_PAGE)
        self.assertNotIn('name="FREQ"', updated)
        self.assertNotIn('name="CAT_SANTE"', updated)
        self.assertNotIn('name="CAT_TECH"', updated)
        self.assertNotIn("Choisissez vos rubriques", updated)
        self.assertIn(v3.CANONICAL_HINT, updated)
        self.assertIn('data-newsletter-version="3"', updated)
        self.assertEqual(updated.count('/src/newsletter.js?v=3'), 1)
        self.assertIn('data-newsletter-noscript="1"', updated)

    def test_upgrade_is_idempotent(self):
        once = v3.upgrade_html(OLD_PAGE)
        twice = v3.upgrade_html(once)
        self.assertEqual(once, twice)
        self.assertEqual(v3.validate_v3(Path("index.html"), twice), [])

    def test_directory_run_and_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.html").write_text(OLD_PAGE, encoding="utf-8")
            result = v3.run(root)
            self.assertEqual(result["changed"], 1)
            result2 = v3.run(root)
            self.assertEqual(result2["changed"], 0)
            v3.run(root, check_only=True)

    def test_validation_rejects_a_reintroduced_choice(self):
        updated = v3.upgrade_html(OLD_PAGE).replace(
            v3.CANONICAL_HINT,
            '<input name="FREQ" value="both">' + v3.CANONICAL_HINT,
        )
        errors = v3.validate_v3(Path("index.html"), updated)
        self.assertTrue(any("fréquence" in error for error in errors))


if __name__ == "__main__":
    unittest.main(verbosity=2)
