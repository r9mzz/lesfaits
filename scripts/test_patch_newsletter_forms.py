# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from patch_newsletter_forms import MARKER, SIB_URL, patch_html, patch_site


OLD_PAGE = '''<!doctype html><html><head>
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; connect-src 'self' https://e6ad0381.sibforms.com; form-action 'self';">
</head><body>
<section class="nl-compact" id="newsletter">
<form id="nl-form" novalidate>
<input type="radio" name="FREQ" value="morning"><input type="radio" name="FREQ" value="both" checked>
<input type="email" id="nl-email" name="EMAIL"><button id="nl-btn">S'abonner →</button>
<input type="checkbox" name="CAT_SCIENCE" value="1"><input type="checkbox" id="nl-consent">
<p id="nl-msg"></p>
</form></section>
<script>
(function(){
  var SIB_URL="https://e6ad0381.sibforms.com/serve/test";
  var form=document.getElementById("nl-form"),msgEl=document.getElementById("nl-msg"),btn=document.getElementById("nl-btn");
  form.addEventListener("submit",function(e){e.preventDefault();fetch(SIB_URL,{method:"POST",mode:"no-cors",body:new FormData()}).then(function(){msgEl.textContent="Un email de confirmation vient de vous être envoyé";});});
})();
</script>
</body></html>'''


class NewsletterFormPatchTests(unittest.TestCase):
    def test_replaces_opaque_fetch_with_real_brevo_post(self):
        updated, changed = patch_html(OLD_PAGE)
        self.assertTrue(changed)
        self.assertIn(f'action="{SIB_URL}"', updated)
        self.assertIn('method="post"', updated)
        self.assertIn('target="_blank"', updated)
        self.assertIn(MARKER, updated)
        self.assertIn("form-action 'self' https://e6ad0381.sibforms.com;", updated)
        self.assertNotIn('mode:"no-cors"', updated)
        self.assertNotIn("fetch(SIB_URL", updated)
        self.assertIn('name="LESFAITS_VERIFICATION"', updated)
        self.assertIn('name="email_address_check"', updated)
        self.assertIn('name="locale"', updated)
        self.assertIn("L’inscription ne sera active qu’après validation", updated)

    def test_patch_is_idempotent(self):
        first, _ = patch_html(OLD_PAGE)
        second, changed = patch_html(first)
        self.assertFalse(changed)
        self.assertEqual(first, second)
        self.assertEqual(second.count('name="LESFAITS_VERIFICATION"'), 1)
        self.assertEqual(second.count(MARKER), 1)

    def test_patch_site_handles_root_and_category_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "categories").mkdir()
            (root / "index.html").write_text(OLD_PAGE, encoding="utf-8")
            (root / "categories" / "science.html").write_text(OLD_PAGE, encoding="utf-8")
            (root / "sans-formulaire.html").write_text("<html></html>", encoding="utf-8")
            result = patch_site(root)
            self.assertEqual(result["forms"], 2)
            self.assertEqual(result["changed"], 2)
            self.assertIn(MARKER, (root / "index.html").read_text(encoding="utf-8"))
            self.assertIn(MARKER, (root / "categories" / "science.html").read_text(encoding="utf-8"))
            second = patch_site(root)
            self.assertEqual(second["changed"], 0)

    def test_rejects_duplicate_forms(self):
        duplicated = OLD_PAGE.replace("</body>", '<form id="nl-form"></form></body>')
        with self.assertRaises(ValueError):
            patch_html(duplicated)


if __name__ == "__main__":
    unittest.main(verbosity=2)
