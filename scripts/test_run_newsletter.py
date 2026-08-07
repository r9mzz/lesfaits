# -*- coding: utf-8 -*-
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import generer_digest as digest
import run_newsletter

PARIS = ZoneInfo("Europe/Paris")


class NewsletterRunnerTests(unittest.TestCase):
    def test_dry_run_builds_preview_without_brevo(self):
        now = dt.datetime(2026, 8, 7, 8, 5, tzinfo=PARIS)
        articles = [{
            "slug": "article-test",
            "titre": "Un article de test",
            "excerpt": "Résumé de test",
            "categorie": "science",
        }]
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(digest, "recent_article_slugs", return_value=["article-test"]), \
             patch.object(digest, "load_articles", return_value=articles), \
             patch.object(digest, "PREVIEW_HTML", Path(tmp) / "newsletter-preview.html"), \
             patch.object(digest, "Brevo", side_effect=AssertionError("Brevo appelé en dry-run")):
            result = run_newsletter.build_local_preview("matin", now)
            self.assertEqual(result, {"articles": 1, "categories": 1})
            preview = (Path(tmp) / "newsletter-preview.html").read_text(encoding="utf-8")
            self.assertIn("Un article de test", preview)

    def test_cli_dry_run_does_not_require_secrets(self):
        with patch.object(run_newsletter, "build_local_preview", return_value={"articles": 0, "categories": 0}) as build:
            self.assertEqual(
                run_newsletter.main(["--slot", "soir", "--dry-run", "--now", "2026-08-07T20:30:00+02:00"]),
                0,
            )
        build.assert_called_once()
        self.assertEqual(build.call_args.args[0], "soir")

    def test_migration_uses_latest_legacy_or_v2_campaign(self):
        campaigns = [
            {
                "tag": "nl-digest",
                "sentDate": "2026-08-06T08:00:00+02:00",
            },
            {
                "tag": digest.CAMPAIGN_TAG,
                "sentDate": "2026-08-06T20:30:00+02:00",
            },
            {
                "tag": "unrelated-campaign",
                "sentDate": "2026-08-07T01:00:00+02:00",
            },
        ]
        with patch.object(digest, "list_campaigns", return_value=campaigns):
            latest = run_newsletter.latest_sent_campaign_time_compatible(object())
        self.assertEqual(latest, dt.datetime(2026, 8, 6, 20, 30, tzinfo=PARIS))

    def test_real_run_temporarily_installs_legacy_compatible_lookup(self):
        original = digest.latest_sent_campaign_time

        def fake_main(args):
            self.assertIs(
                digest.latest_sent_campaign_time,
                run_newsletter.latest_sent_campaign_time_compatible,
            )
            self.assertEqual(args[:2], ["--slot", "matin"])
            return 0

        with patch.object(digest, "main", side_effect=fake_main):
            self.assertEqual(
                run_newsletter.main(["--slot", "matin", "--now", "2026-08-07T08:00:00+02:00"]),
                0,
            )
        self.assertIs(digest.latest_sent_campaign_time, original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
