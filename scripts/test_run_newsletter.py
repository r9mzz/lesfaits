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


if __name__ == "__main__":
    unittest.main(verbosity=2)
