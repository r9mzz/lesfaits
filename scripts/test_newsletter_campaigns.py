# -*- coding: utf-8 -*-
from __future__ import annotations

import datetime as dt
import types
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import generer_digest as digest

PARIS = ZoneInfo("Europe/Paris")


class FakeCampaignClient:
    def __init__(self, statuses=None):
        self.requests = []
        self.statuses = list(statuses or [])

    def request(self, method, path, **kwargs):
        self.requests.append((method, path, kwargs))
        return types.SimpleNamespace()

    def json(self, method, path, **kwargs):
        self.requests.append((method, path, kwargs))
        if method == "POST" and path == "/emailCampaigns":
            return {"id": 77}
        if method == "GET" and path.startswith("/emailCampaigns/"):
            status = self.statuses.pop(0) if self.statuses else "sent"
            return {"id": 77, "status": status}
        raise AssertionError(f"appel non prévu: {method} {path}")


class CampaignIdempotenceTests(unittest.TestCase):
    def test_stable_name_depends_on_publication_date_and_slot(self):
        now = dt.datetime(2026, 8, 7, 23, 59, tzinfo=PARIS)
        self.assertEqual(
            digest.campaign_name(now, "soir"),
            "Les Faits | 2026-08-07 | soir",
        )

    def test_already_sent_campaign_is_never_updated_or_resent(self):
        client = FakeCampaignClient()
        with patch.object(digest, "find_campaign", return_value={
            "id": 42,
            "name": "Les Faits | 2026-08-07 | matin",
            "status": "sent",
        }):
            campaign_id, status = digest.upsert_campaign(
                client,
                name="Les Faits | 2026-08-07 | matin",
                subject="Sujet",
                html_content="<html></html>",
                list_id=9,
                preview_text="Aperçu",
            )
        self.assertEqual((campaign_id, status), (42, "sent"))
        self.assertEqual(client.requests, [])

    def test_draft_campaign_is_updated_instead_of_duplicated(self):
        client = FakeCampaignClient()
        with patch.object(digest, "find_campaign", return_value={
            "id": 43,
            "name": "Les Faits | 2026-08-07 | matin",
            "status": "draft",
        }):
            campaign_id, status = digest.upsert_campaign(
                client,
                name="Les Faits | 2026-08-07 | matin",
                subject="Sujet corrigé",
                html_content="<html>corrigé</html>",
                list_id=9,
                preview_text="Aperçu",
            )
        self.assertEqual((campaign_id, status), (43, "draft"))
        self.assertEqual(len(client.requests), 1)
        method, path, kwargs = client.requests[0]
        self.assertEqual((method, path), ("PUT", "/emailCampaigns/43"))
        self.assertEqual(kwargs["payload"]["recipients"], {"listIds": [9]})

    def test_new_campaign_is_created_once(self):
        client = FakeCampaignClient()
        with patch.object(digest, "find_campaign", return_value=None):
            campaign_id, status = digest.upsert_campaign(
                client,
                name="Les Faits | 2026-08-07 | soir",
                subject="Sujet",
                html_content="<html></html>",
                list_id=9,
                preview_text="Aperçu",
            )
        self.assertEqual((campaign_id, status), (77, "draft"))
        self.assertEqual(client.requests[0][0:2], ("POST", "/emailCampaigns"))

    def test_send_waits_for_a_confirmed_brevo_status(self):
        client = FakeCampaignClient(statuses=["draft", "queued"])
        with patch.object(digest.time, "sleep", return_value=None):
            status = digest.send_and_confirm(client, 77)
        self.assertEqual(status, "queued")
        self.assertEqual(client.requests[0][0:2], ("POST", "/emailCampaigns/77/sendNow"))

    def test_latest_sent_time_ignores_other_campaign_tags(self):
        campaigns = [
            {"tag": "autre", "sentDate": "2026-08-07T19:00:00+02:00"},
            {"tag": digest.CAMPAIGN_TAG, "sentDate": "2026-08-07T08:00:00+02:00"},
            {"tag": digest.CAMPAIGN_TAG, "sentDate": "2026-08-07T18:30:00+02:00"},
        ]
        with patch.object(digest, "list_campaigns", return_value=campaigns):
            latest = digest.latest_sent_campaign_time(types.SimpleNamespace())
        self.assertEqual(latest, dt.datetime(2026, 8, 7, 18, 30, tzinfo=PARIS))


class ConfigurationTests(unittest.TestCase):
    def test_wrong_existing_attribute_type_is_rejected(self):
        class Client:
            def json(self, method, path, **kwargs):
                self.assertions = (method, path)
                return {"attributes": [
                    {"name": "FREQ", "type": "boolean"},
                    *[
                        {"name": f"CAT_{cat.upper()}", "type": "boolean"}
                        for cat in digest.CATEGORIES
                    ],
                ]}

            def request(self, *args, **kwargs):
                raise AssertionError("aucun attribut ne doit être créé")

        with self.assertRaisesRegex(RuntimeError, "types incorrects"):
            digest.ensure_contact_attributes(Client())


if __name__ == "__main__":
    unittest.main(verbosity=2)
