# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

import stamp_publication_times as legacy  # noqa: E402
from run_publication_times import install_legacy_rebuild_recovery  # noqa: E402

PARIS = ZoneInfo("Europe/Paris")


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def article_html(title: str, display: str, iso: str) -> str:
    return (
        '<!doctype html><html><head>'
        '<script type="application/ld+json">'
        f'{{"@context":"https://schema.org","@type":"NewsArticle",'
        f'"headline":"{title}","datePublished":"{iso}","dateModified":"{iso}"}}'
        '</script></head><body>'
        f'<h1>{title}</h1><time datetime="{iso}">{display}</time>'
        '</body></html>'
    )


def feed_xml(slug: str, pubdate: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0"><channel><title>Les Faits</title>'
        '<lastBuildDate>Tue, 18 Aug 2026 16:00:00 GMT</lastBuildDate>'
        f'<item><title>{slug}</title>'
        f'<link>https://lesfaits.info/articles/{slug}.html</link>'
        f'<pubDate>{pubdate}</pubDate></item></channel></rss>'
    )


class LegacyRebuildPublicationTimeTests(unittest.TestCase):
    def test_restores_previous_html_time_when_date_iso_was_lost(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp)
            (site / "articles").mkdir()
            (site / "categories").mkdir()
            (site / "data").mkdir()
            git(site, "init")
            git(site, "config", "user.name", "Test")
            git(site, "config", "user.email", "test@example.com")

            slug = "article-legacy"
            old_display = "14 août 2026, 13h57"
            old_iso = "2026-08-14T13:57:51+02:00"
            entry = {
                "slug": slug,
                "titre": "Article legacy",
                "categorie": "economie",
                "nb_sources": 4,
                "date": old_display,
                "resume": ["Résumé"],
            }
            # État public précédent déjà dégradé : date_iso absente de l'index,
            # mais l'heure publique correcte subsiste encore dans le JSON-LD.
            (site / "data" / "articles.json").write_text(
                json.dumps([entry], ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (site / "data" / "search.json").write_text(
                json.dumps([entry], ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (site / "articles" / f"{slug}.html").write_text(
                article_html("Article legacy", old_display, old_iso), encoding="utf-8"
            )
            (site / "index.html").write_text(
                f'<a href="articles/{slug}.html"><span>{old_display}</span></a>', encoding="utf-8"
            )
            (site / "feed.xml").write_text(
                feed_xml(slug, "Fri, 14 Aug 2026 11:57:51 GMT"), encoding="utf-8"
            )
            git(site, "add", "-A")
            git(site, "commit", "-m", "état public précédent")

            rebuilt_display = "18 août 2026, 18h00"
            rebuilt_iso = "2026-08-18T18:00:00+02:00"
            rebuilt_entry = {**entry, "date": rebuilt_display}
            (site / "data" / "articles.json").write_text(
                json.dumps([rebuilt_entry], ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (site / "data" / "search.json").write_text(
                json.dumps([rebuilt_entry], ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (site / "articles" / f"{slug}.html").write_text(
                article_html("Article legacy", rebuilt_display, rebuilt_iso), encoding="utf-8"
            )
            (site / "index.html").write_text(
                f'<a href="articles/{slug}.html"><span>{rebuilt_display}</span></a>', encoding="utf-8"
            )
            (site / "feed.xml").write_text(
                feed_xml(slug, "Tue, 18 Aug 2026 16:00:00 GMT"), encoding="utf-8"
            )
            git(site, "add", "-A")
            git(site, "commit", "-m", "rebuild sans nouvel article")

            original_map = install_legacy_rebuild_recovery(site, "HEAD~1")
            try:
                result = legacy.stamp_publication_times(
                    site,
                    "HEAD~1",
                    datetime(2026, 8, 18, 18, 17, 13, tzinfo=PARIS),
                )
            finally:
                legacy._previous_publication_map = original_map

            self.assertEqual(result["new"], 0)
            data = json.loads((site / "data" / "articles.json").read_text(encoding="utf-8"))
            self.assertEqual(data[0]["date"], old_display)
            self.assertEqual(data[0]["date_iso"], old_iso)

            html = (site / "articles" / f"{slug}.html").read_text(encoding="utf-8")
            self.assertIn(f'<time datetime="{old_iso}">{old_display}</time>', html)
            self.assertIn(f'"datePublished":"{old_iso}"', html)
            # Le rebuild est une vraie modification : dateModified peut rester
            # à l'heure du rebuild. Seule datePublished doit être restaurée.
            self.assertIn(f'"dateModified":"{rebuilt_iso}"', html)

            feed = (site / "feed.xml").read_text(encoding="utf-8")
            self.assertIn("Fri, 14 Aug 2026 11:57:51 GMT", feed)
            index = (site / "index.html").read_text(encoding="utf-8")
            self.assertIn(old_display, index)
            self.assertNotIn(rebuilt_display, index)


if __name__ == "__main__":
    unittest.main(verbosity=2)
