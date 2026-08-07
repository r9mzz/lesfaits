# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import harden_newsletter_v3 as v3


OLD_PAGE = '''<!doctype html><html><head>
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self'; connect-src 'self' https://e6ad0381.sibforms.com; base-uri 'self'; form-action 'self';">
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


class NewsletterV4Tests(unittest.TestCase):
    def test_upgrade_removes_unsupported_preferences_and_uses_native_brevo_post(self):
        updated = v3.upgrade_html(OLD_PAGE)
        self.assertNotIn('name="FREQ"', updated)
        self.assertNotIn('name="CAT_SANTE"', updated)
        self.assertNotIn('name="CAT_TECH"', updated)
        self.assertNotIn("Choisissez vos rubriques", updated)
        self.assertIn(v3.CANONICAL_HINT, updated)
        self.assertIn('data-newsletter-version="4"', updated)
        self.assertEqual(updated.count('/src/newsletter.js?v=4'), 1)
        self.assertIn('data-newsletter-noscript="1"', updated)
        self.assertIn(f'action="{v3.FORM_URL}"', updated)
        self.assertIn('method="post"', updated)
        self.assertIn('enctype="application/x-www-form-urlencoded"', updated)
        self.assertIn('name="LESFAITS_VERIFICATION" value="1"', updated)
        self.assertIn('name="email_address_check" value=""', updated)
        self.assertIn('name="locale" value="fr"', updated)
        self.assertTrue(v3._csp_allows_native_post(updated))

    def test_upgrade_is_idempotent(self):
        once = v3.upgrade_html(OLD_PAGE)
        twice = v3.upgrade_html(once)
        self.assertEqual(once, twice)
        self.assertEqual(v3.validate_v3(Path("index.html"), twice), [])

    def test_deduplicates_consecutive_article_blocks_after_copy_upgrade(self):
        old_block = v3.ARTICLE_NL_BLOCK.replace(v3.NEW_ARTICLE_COPY, v3.OLD_ARTICLE_COPY)
        page = (
            '<html><head><script src="/src/newsletter.js?v=3" defer></script></head><body>'
            + old_block + '\n' + v3.ARTICLE_NL_BLOCK + '<div class="art__related">x</div>'
            + '</body></html>'
        )
        updated = v3.upgrade_html(page)
        self.assertEqual(updated.count(v3.ARTICLE_NL_BLOCK), 1)
        self.assertNotIn(v3.OLD_ARTICLE_COPY, updated)
        self.assertIn('/src/newsletter.js?v=4', updated)
        self.assertEqual(v3.validate_v3(Path("articles/test.html"), updated), [])

    def test_validation_rejects_duplicate_article_blocks(self):
        page = (
            '<html><head><script src="/src/newsletter.js?v=4" defer></script></head><body>'
            + v3.ARTICLE_NL_BLOCK + '\n' + v3.ARTICLE_NL_BLOCK
            + '</body></html>'
        )
        errors = v3.validate_v3(Path("articles/test.html"), page)
        self.assertTrue(any("dupliqué" in error for error in errors))

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

    def test_validation_rejects_missing_native_action_or_csp_permission(self):
        updated = v3.upgrade_html(OLD_PAGE)
        broken_action = updated.replace(f'action="{v3.FORM_URL}"', 'action="/"')
        self.assertTrue(
            any("action Brevo" in error for error in v3.validate_v3(Path("index.html"), broken_action))
        )
        broken_csp = updated.replace(f" https://{v3.FORM_HOST}", "", 1)
        self.assertTrue(
            any("CSP form-action" in error for error in v3.validate_v3(Path("index.html"), broken_csp))
        )

    def test_browser_script_has_no_opaque_no_cors_success_path(self):
        script = (Path(__file__).resolve().parent.parent / "src" / "newsletter.js").read_text(
            encoding="utf-8"
        )
        self.assertNotIn('mode: "no-cors"', script)
        self.assertNotIn("fetch(FORM_URL", script)
        self.assertIn('form.setAttribute("action", FORM_URL)', script)
        self.assertIn('form.setAttribute("method", "post")', script)
        self.assertIn("Aucun preventDefault", script)


if __name__ == "__main__":
    unittest.main(verbosity=2)
