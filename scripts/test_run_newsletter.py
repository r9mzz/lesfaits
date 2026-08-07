# -*- coding: utf-8 -*-
from __future__ import annotations

import datetime as dt
import json
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

    def test_deployment_slugs_are_deduplicated_and_strict(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "slugs.txt"
            path.write_text("article-a\narticle-b\narticle-a\n# note\n", encoding="utf-8")
            self.assertEqual(
                run_newsletter.read_deployment_slugs(path),
                ["article-a", "article-b"],
            )
            path.write_text("articles/article-a.html\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "Slug de déploiement invalide"):
                run_newsletter.read_deployment_slugs(path)

    def test_exact_public_batch_ignores_a_declared_redirect(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "articles").mkdir()
            (root / "data" / "search.json").write_text(
                json.dumps([{
                    "slug": "article-a",
                    "titre": "Article A",
                    "excerpt": "Résumé",
                    "categorie": "science",
                }]),
                encoding="utf-8",
            )
            (root / "articles" / "ancienne-url.html").write_text(
                '<meta name="robots" content="noindex"><meta http-equiv="refresh" content="0;url=/articles/article-a.html">',
                encoding="utf-8",
            )
            with patch.object(digest, "ROOT", root), \
                 patch.object(digest, "SEARCH_JSON", root / "data" / "search.json"):
                articles = run_newsletter.articles_for_deployment(
                    ["article-a", "ancienne-url"]
                )
            self.assertEqual([a["slug"] for a in articles], ["article-a"])

    def test_exact_public_batch_rejects_an_unindexed_real_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "articles").mkdir()
            (root / "data" / "search.json").write_text("[]", encoding="utf-8")
            (root / "articles" / "article-perdu.html").write_text(
                "<html><title>Article réel</title></html>", encoding="utf-8"
            )
            with patch.object(digest, "ROOT", root), \
                 patch.object(digest, "SEARCH_JSON", root / "data" / "search.json"):
                with self.assertRaisesRegex(RuntimeError, "absent\(s\) de search.json"):
                    run_newsletter.articles_for_deployment(["article-perdu"])

    def test_live_batch_uses_exact_slugs_and_deployment_campaign_name(self):
        now = "2026-08-07T18:03:00+02:00"
        deployment = "abcdef0123456789abcdef0123456789abcdef01"
        original_recent = digest.recent_article_slugs
        original_name = digest.campaign_name
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "slugs.txt"
            path.write_text("article-a\nancienne-url\n", encoding="utf-8")

            def fake_main(args):
                self.assertEqual(digest.recent_article_slugs(None), ["article-a"])
                self.assertEqual(
                    digest.campaign_name(dt.datetime.fromisoformat(now), "soir"),
                    "Les Faits | 2026-08-07 | soir | abcdef012345",
                )
                self.assertEqual(args, ["--slot", "soir", "--now", now])
                return 0

            with patch.object(
                run_newsletter,
                "articles_for_deployment",
                return_value=[{"slug": "article-a"}],
            ), patch.object(digest, "main", side_effect=fake_main):
                self.assertEqual(
                    run_newsletter.main([
                        "--slot", "soir",
                        "--now", now,
                        "--slugs-file", str(path),
                        "--deployment-id", deployment,
                    ]),
                    0,
                )
        self.assertIs(digest.recent_article_slugs, original_recent)
        self.assertIs(digest.campaign_name, original_name)

    def test_live_public_batch_requires_deployment_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "slugs.txt"
            path.write_text("article-a\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "deployment-id est obligatoire"):
                run_newsletter.main([
                    "--slot", "matin",
                    "--slugs-file", str(path),
                ])

    def test_legacy_campaign_alias_only_matches_the_same_deployment_time(self):
        published = dt.datetime(2026, 8, 7, 18, 0, tzinfo=PARIS)
        same = {
            "status": "sent",
            "sentDate": "2026-08-07T18:00:20+02:00",
        }
        older = {
            "status": "sent",
            "sentDate": "2026-08-07T17:40:00+02:00",
        }
        self.assertTrue(run_newsletter._legacy_campaign_matches_deployment(same, published))
        self.assertFalse(run_newsletter._legacy_campaign_matches_deployment(older, published))


if __name__ == "__main__":
    unittest.main(verbosity=2)
