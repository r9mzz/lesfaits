# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest

from audit_brevo_form import REQUIRED_FIELDS, parse_form, validate_snapshot


VALID_FORM = '''<!doctype html><html><body>
<input name="OUTSIDE">
<form action="/serve/test" method="post">
  <input name="EMAIL" type="email">
  <input name="LESFAITS_VERIFICATION" type="hidden" value="1">
  <input name="email_address_check" type="text" value="">
  <input name="locale" type="hidden" value="fr">
  <button name="submit" type="submit">Valider</button>
</form>
</body></html>'''


class HostedBrevoFormTests(unittest.TestCase):
    def test_parser_collects_only_named_fields_inside_forms(self):
        snapshot = parse_form(VALID_FORM)
        self.assertEqual(snapshot.form_count, 1)
        self.assertIn("post", snapshot.methods)
        self.assertTrue(REQUIRED_FIELDS <= snapshot.fields)
        self.assertNotIn("OUTSIDE", snapshot.fields)

    def test_complete_minimal_contract_is_accepted(self):
        validate_snapshot(parse_form(VALID_FORM))

    def test_missing_email_is_rejected(self):
        broken = VALID_FORM.replace('name="EMAIL"', 'name="EMAIL_ABSENT"')
        with self.assertRaisesRegex(RuntimeError, "EMAIL"):
            validate_snapshot(parse_form(broken))

    def test_missing_verification_marker_is_rejected(self):
        broken = VALID_FORM.replace(
            'name="LESFAITS_VERIFICATION"',
            'name="VERIFICATION_ABSENTE"',
        )
        with self.assertRaisesRegex(RuntimeError, "LESFAITS_VERIFICATION"):
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
