# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest

from audit_brevo_form import REQUIRED_FIELDS, parse_form, validate_snapshot


VALID_FORM = '''<!doctype html><html><body>
<form action="/serve/test" method="post">
  <input name="EMAIL" type="email">
  <select name="FREQ"><option value="both">Les deux</option></select>
  <input name="LESFAITS_VERIFICATION" type="hidden" value="1">
  <input name="CAT_SOCIETE" type="checkbox">
  <input name="CAT_SCIENCE" type="checkbox">
  <input name="CAT_ECONOMIE" type="checkbox">
  <input name="CAT_TECH" type="checkbox">
  <input name="CAT_SANTE" type="checkbox">
  <input name="CAT_ENVIRONNEMENT" type="checkbox">
  <button name="submit" type="submit">Valider</button>
</form>
</body></html>'''


class HostedBrevoFormTests(unittest.TestCase):
    def test_parser_collects_only_named_fields_inside_forms(self):
        html = '<input name="OUTSIDE">' + VALID_FORM
        snapshot = parse_form(html)
        self.assertEqual(snapshot.form_count, 1)
        self.assertIn("post", snapshot.methods)
        self.assertTrue(REQUIRED_FIELDS <= snapshot.fields)
        self.assertNotIn("OUTSIDE", snapshot.fields)

    def test_complete_contract_is_accepted(self):
        validate_snapshot(parse_form(VALID_FORM))

    def test_missing_preference_field_is_rejected(self):
        broken = VALID_FORM.replace('name="CAT_SANTE"', 'name="CAT_SANTE_ABSENT"')
        with self.assertRaisesRegex(RuntimeError, "CAT_SANTE"):
            validate_snapshot(parse_form(broken))

    def test_get_only_form_is_rejected(self):
        broken = VALID_FORM.replace('method="post"', 'method="get"')
        with self.assertRaisesRegex(RuntimeError, "méthode POST"):
            validate_snapshot(parse_form(broken))

    def test_page_without_form_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "aucune balise"):
            validate_snapshot(parse_form("<html><body>maintenance</body></html>"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
