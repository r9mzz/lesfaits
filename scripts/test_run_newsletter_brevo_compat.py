#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from unittest import mock

import run_newsletter_brevo_compat as compat


class FakeClient:
    def __init__(self) -> None:
        self.calls = []

    def json(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return {"id": 321}

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return object()


class BrevoTagCompatibilityTests(unittest.TestCase):
    def kwargs(self):
        return {
            "name": "Les Faits | 2026-08-14 | soir | 683eea3972d4",
            "subject": "Sujet",
            "html_content": "<p>Digest</p>",
            "list_id": 12,
            "preview_text": "Aperçu",
        }

    def test_exact_tag_capability_error_retries_without_tag(self):
        client = FakeClient()
        original = mock.Mock(
            side_effect=RuntimeError(
                'Brevo POST /emailCampaigns: HTTP 405 — '
                '{"message":"You are not allowed to avail tag option for your campaign"}'
            )
        )
        with mock.patch.object(compat.digest, "find_campaign", return_value=None):
            result = compat._tag_compatible_upsert(original)(client, **self.kwargs())
        self.assertEqual(result, (321, "draft"))
        self.assertEqual(original.call_count, 1)
        payload = client.calls[-1][2]["payload"]
        self.assertNotIn("tag", payload)
        self.assertIn("683eea3972d4", payload["name"])

    def test_unrelated_brevo_error_is_never_retried(self):
        client = FakeClient()
        original = mock.Mock(
            side_effect=RuntimeError("Brevo POST /emailCampaigns: HTTP 405 — sender forbidden")
        )
        with self.assertRaisesRegex(RuntimeError, "sender forbidden"):
            compat._tag_compatible_upsert(original)(client, **self.kwargs())
        self.assertEqual(client.calls, [])

    def test_existing_draft_is_updated_without_tag_after_capability_error(self):
        client = FakeClient()
        original = mock.Mock(
            side_effect=RuntimeError(
                "You are not allowed to avail tag option for your campaign"
            )
        )
        with mock.patch.object(
            compat.digest,
            "find_campaign",
            return_value={"id": 99, "status": "draft"},
        ):
            result = compat._tag_compatible_upsert(original)(client, **self.kwargs())
        self.assertEqual(result, (99, "draft"))
        method, path, details = client.calls[-1]
        self.assertEqual((method, path), ("PUT", "/emailCampaigns/99"))
        self.assertNotIn("tag", details["payload"])

    def test_sent_campaign_stays_idempotent_in_fallback(self):
        client = FakeClient()
        original = mock.Mock(
            side_effect=RuntimeError(
                "You are not allowed to avail tag option for your campaign"
            )
        )
        with mock.patch.object(
            compat.digest,
            "find_campaign",
            return_value={"id": 77, "status": "sent"},
        ):
            result = compat._tag_compatible_upsert(original)(client, **self.kwargs())
        self.assertEqual(result, (77, "sent"))
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
