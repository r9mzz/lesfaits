#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

import generer_digest as digest  # noqa: E402
import harden_newsletter as hardener  # noqa: E402

PARIS = ZoneInfo("Europe/Paris")


class FakeBrevo:
    def __init__(self):
        self.contacts = {
            9: [
                {"email": "stale@example.fr", "listUnsubscribed": []},
                {"email": "keep@example.fr", "listUnsubscribed": []},
                {"email": "refus@example.fr", "listUnsubscribed": [9]},
            ]
        }
        self.next_process = 1
        self.attributes = []
        self.created_attributes = []

    def json(self, method, path, *, expected=(200,), params=None, payload=None):
        if method == "GET" and path == "/contacts/attributes":
            return {"attributes": list(self.attributes)}
        if method == "GET" and path.startswith("/contacts/lists/") and path.endswith("/contacts"):
            list_id = int(path.split("/")[3])
            return {"contacts": list(self.contacts.get(list_id, []))}
        if method == "GET" and path.startswith("/processes/"):
            return {"status": "completed"}
        if method == "POST" and path.endswith("/contacts/remove"):
            list_id = int(path.split("/")[3])
            emails = {x.lower() for x in (payload or {}).get("emails", [])}
            self.contacts[list_id] = [
                c for c in self.contacts.get(list_id, [])
                if str(c.get("email") or "").lower() not in emails
            ]
            process_id = self.next_process
            self.next_process += 1
            return {"processId": process_id, "success": list(emails), "failure": []}
        if method == "POST" and path.endswith("/contacts/add"):
            list_id = int(path.split("/")[3])
            existing = {
                str(c.get("email") or "").lower()
                for c in self.contacts.get(list_id, [])
            }
            added = []
            for email in (payload or {}).get("emails", []):
                low = email.lower()
                if low not in existing:
                    self.contacts.setdefault(list_id, []).append(
                        {"email": low, "listUnsubscribed": []}
                    )
                    existing.add(low)
                    added.append(low)
            return {"success": added, "failure": []}
        raise AssertionError(f"appel fake non prévu: {method} {path}")

    def request(self, method, path, *, expected=(200,), params=None, payload=None):
        if method == "POST" and path.startswith("/contacts/attributes/normal/"):
            name = path.rsplit("/", 1)[-1]
            kind = (payload or {}).get("type")
            self.attributes.append({"name": name, "type": kind})
            self.created_attributes.append((name, kind))
            return object()
        raise AssertionError(f"request fake non prévu: {method} {path}")


class FrequencyTests(unittest.TestCase):
    def test_modern_frequency_values(self):
        both = {"attributes": {"FREQ": "both"}}
        morning = {"attributes": {"FREQ": "morning"}}
        evening = {"attributes": {"FREQ": "evening"}}
        self.assertTrue(digest.wants_slot(both, "matin"))
        self.assertTrue(digest.wants_slot(both, "soir"))
        self.assertTrue(digest.wants_slot(morning, "matin"))
        self.assertFalse(digest.wants_slot(morning, "soir"))
        self.assertFalse(digest.wants_slot(evening, "matin"))
        self.assertTrue(digest.wants_slot(evening, "soir"))

    def test_legacy_and_missing_frequency(self):
        self.assertEqual(digest.frequency({"attributes": {"ENVOI_MATIN": True}}), "morning")
        self.assertEqual(digest.frequency({"attributes": {"ENVOI_MATIN": False}}), "evening")
        self.assertEqual(digest.frequency({"attributes": {}}), "both")

    def test_categories_default_to_all(self):
        self.assertEqual(set(digest.contact_categories({"attributes": {}})), set(digest.CATEGORIES))
        contact = {"attributes": {"CAT_SANTE": True, "CAT_TECH": "1"}}
        self.assertEqual(set(digest.contact_categories(contact)), {"sante", "tech"})


class RecipientTests(unittest.TestCase):
    def test_global_and_list_unsubscribes_are_excluded(self):
        contacts = [
            {"email": "ok@example.fr", "attributes": {"FREQ": "both"}},
            {"email": "black@example.fr", "emailBlacklisted": True, "attributes": {}},
            {"email": "main@example.fr", "listUnsubscribed": [3], "attributes": {}},
            {"email": "delivery@example.fr", "listUnsubscribed": [9], "attributes": {}},
            {"email": "evening@example.fr", "attributes": {"FREQ": "evening"}},
            {"email": "science@example.fr", "attributes": {"CAT_SCIENCE": True}},
        ]
        recipients, stats = digest.build_recipients(
            contacts,
            main_list_id=3,
            delivery_list_id=9,
            slot="matin",
            active_categories={"sante"},
        )
        self.assertEqual(recipients, ["ok@example.fr"])
        self.assertEqual(stats["blacklisted_or_unsubscribed"], 3)
        self.assertEqual(stats["wrong_slot"], 1)
        self.assertEqual(stats["no_matching_category"], 1)

    def test_delivery_list_sync_is_non_destructive(self):
        fake = FakeBrevo()
        digest.sync_delivery_list(fake, 9, ["keep@example.fr", "new@example.fr"])
        emails = {c["email"] for c in fake.contacts[9]}
        self.assertEqual(emails, {"keep@example.fr", "new@example.fr", "refus@example.fr"})
        refused = next(c for c in fake.contacts[9] if c["email"] == "refus@example.fr")
        self.assertEqual(refused["listUnsubscribed"], [9])

    def test_required_attributes_are_created_for_legacy_contacts(self):
        fake = FakeBrevo()
        digest.ensure_contact_attributes(fake)
        created = dict(fake.created_attributes)
        self.assertEqual(created["FREQ"], "text")
        for category in digest.CATEGORIES:
            self.assertEqual(created[f"CAT_{category.upper()}"], "boolean")


class EmailTests(unittest.TestCase):
    def test_dynamic_content_is_escaped_and_unsubscribe_kept(self):
        article = {
            "slug": "test",
            "titre": '<script>alert("x")</script>',
            "excerpt": "A & B < C",
            "categorie": "tech",
        }
        rendered = digest.build_email(
            {"tech": [article]},
            now=dt.datetime(2026, 8, 7, 8, 0, tzinfo=PARIS),
            slot="matin",
        )
        self.assertNotIn('<script>alert("x")</script>', rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn("A &amp; B &lt; C", rendered)
        self.assertIn("{{ unsubscribe }}", rendered)
        self.assertIn("utm_source=newsletter", rendered)


class HardenerTests(unittest.TestCase):
    OLD = """<!doctype html><html><head>
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self' 'unsafe-inline'; base-uri 'self';">
</head><body>
<section class="nl-compact" id="newsletter">
<form id="nl-form" novalidate>
<label><input type="radio" name="FREQ" value="morning"> Matin (~7h)</label>
<input type="email" id="nl-email" name="EMAIL">
<p class="nl-compact__hint">Aucune sélection = toutes les rubriques.</p>
<input type="checkbox" id="nl-consent">
<p class="nl-compact__msg" id="nl-msg"></p>
</form>
</section>
<script>(function(){var SIB_URL="https://sib.example";var form=document.getElementById("nl-form");
var data=new FormData();data.append("LESFAITS_VERIFICATION","1");
msgEl.textContent="Un email de confirmation vient de vous être envoyé";})();</script>
</body></html>"""

    def test_hardening_is_idempotent(self):
        once = hardener.harden_html(self.OLD)
        twice = hardener.harden_html(once)
        self.assertEqual(once, twice)
        self.assertNotIn("SIB_URL=", once)
        self.assertNotIn("Un email de confirmation vient de vous être envoyé", once)
        self.assertEqual(once.count("/src/newsletter.js?v=2"), 1)
        self.assertIn("data-newsletter-version=\"2\"", once)
        self.assertIn("connect-src 'self' https://e6ad0381.sibforms.com", once)
        self.assertIn('data-newsletter-noscript="1"', once)
        self.assertIn("Édition du matin", once)

    def test_directory_run_and_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.html").write_text(self.OLD, encoding="utf-8")
            result = hardener.run(root)
            self.assertEqual(result["changed"], 1)
            result2 = hardener.run(root)
            self.assertEqual(result2["changed"], 0)
            hardener.run(root, check_only=True)


class JavascriptContractTests(unittest.TestCase):
    def test_browser_script_keeps_brevo_response_out_of_the_reader_tab(self):
        script = (ROOT / "src" / "newsletter.js").read_text(encoding="utf-8")
        self.assertNotIn("Ouverture…", script)
        self.assertNotIn("Transmission sécurisée vers Brevo", script)
        self.assertNotIn("Un email de confirmation vient de vous être envoyé", script)
        self.assertNotIn('mode: "no-cors"', script)
        self.assertNotIn("fetch(FORM_URL", script)
        self.assertIn('form.setAttribute("action", FORM_URL)', script)
        self.assertIn('form.setAttribute("method", "post")', script)
        self.assertIn('form.setAttribute("target", FRAME_NAME)', script)
        self.assertIn('frame.hidden = true', script)
        self.assertIn("Demande envoyée ✓ Vous restez sur Les Faits.", script)

    def test_browser_script_persists_real_preference_values(self):
        script = (ROOT / "src" / "newsletter.js").read_text(encoding="utf-8")
        self.assertIn("CATEGORY_FIELDS", script)
        self.assertIn("CAT_SOCIETE", script)
        self.assertIn('input[name="LF_FREQ"]:checked', script)
        self.assertIn('ensureHidden(form, "FREQ", readFrequency(form))', script)
        self.assertIn('ensureHidden(form, name, categoryChecked(form, name) ? "1" : "0")', script)
        self.assertIn("localStorage", script)
        self.assertIn('consent.removeAttribute("name")', script)


if __name__ == "__main__":
    unittest.main(verbosity=2)
