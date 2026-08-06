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

from stamp_publication_times import stamp_publication_times  # noqa: E402

PARIS = ZoneInfo("Europe/Paris")


def article_html(slug: str, title: str, display: str, iso: str, related: str = "") -> str:
    return f'''<!doctype html><html><head>
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"NewsArticle","headline":"{title}","datePublished":"{iso}","dateModified":"{iso}"}}</script>
</head><body><h1>{title}</h1><time datetime="{iso[:10]}">{display}</time>{related}</body></html>'''


def feed_xml(items: list[tuple[str, str]]) -> str:
    rows = "".join(
        f"<item><title>{slug}</title><link>https://lesfaits.info/articles/{slug}.html</link>"
        f"<pubDate>{pub}</pubDate></item>"
        for slug, pub in items
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0"><channel><title>Les Faits</title>'
        '<lastBuildDate>Wed, 05 Aug 2026 16:00:00 GMT</lastBuildDate>'
        f'{rows}</channel></rss>'
    )


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True,
        text=True, capture_output=True,
    ).stdout.strip()


class PublicationTimeTests(unittest.TestCase):
    def test_preserves_old_time_and_stamps_only_new_article(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp)
            (site / "articles").mkdir()
            (site / "categories").mkdir()
            (site / "data").mkdir()
            git(site, "init")
            git(site, "config", "user.name", "Test")
            git(site, "config", "user.email", "test@example.com")

            old_display = "5 août 2026, 18h03"
            old_iso = "2026-08-05T18:03:00+02:00"
            old_entry = {
                "slug": "ancien", "titre": "Ancien article", "categorie": "science",
                "nb_sources": 6, "date": old_display, "date_iso": old_iso,
                "resume": ["Résumé"],
            }
            (site / "data" / "articles.json").write_text(
                json.dumps([old_entry], ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (site / "data" / "search.json").write_text(
                json.dumps([old_entry], ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (site / "articles" / "ancien.html").write_text(
                article_html("ancien", "Ancien article", old_display, old_iso), encoding="utf-8"
            )
            (site / "index.html").write_text(
                f'<a href="articles/ancien.html"><span>{old_display}</span></a>', encoding="utf-8"
            )
            (site / "feed.xml").write_text(
                feed_xml([("ancien", "Wed, 05 Aug 2026 16:03:00 GMT")]), encoding="utf-8"
            )
            git(site, "add", "-A")
            git(site, "commit", "-m", "publication précédente")

            generation_old = "5 août 2026, 15h09"
            generation_old_iso = "2026-08-05T15:09:41+02:00"
            generation_new = "6 août 2026, 15h11"
            generation_new_iso = "2026-08-06T15:11:20+02:00"
            current = [
                {**old_entry, "date": generation_old, "date_iso": generation_old_iso},
                {
                    "slug": "nouveau", "titre": "Nouvel article", "categorie": "sante",
                    "nb_sources": 7, "date": generation_new,
                    "date_iso": generation_new_iso, "resume": ["Nouveau résumé"],
                },
            ]
            (site / "data" / "articles.json").write_text(
                json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (site / "data" / "search.json").write_text(
                json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            related = f'<a href="articles/nouveau.html"><span>{generation_new}</span></a>'
            (site / "articles" / "ancien.html").write_text(
                article_html("ancien", "Ancien article", generation_old, generation_old_iso, related),
                encoding="utf-8",
            )
            (site / "articles" / "nouveau.html").write_text(
                article_html("nouveau", "Nouvel article", generation_new, generation_new_iso),
                encoding="utf-8",
            )
            (site / "index.html").write_text(
                f'<a href="articles/ancien.html"><span>{generation_old}</span></a>'
                f'<a href="articles/nouveau.html"><span>{generation_new}</span></a>',
                encoding="utf-8",
            )
            (site / "categories" / "sante.html").write_text(
                f'<a href="articles/nouveau.html"><span>{generation_new}</span></a>',
                encoding="utf-8",
            )
            (site / "feed.xml").write_text(
                feed_xml([
                    ("ancien", "Thu, 06 Aug 2026 13:00:00 GMT"),
                    ("nouveau", "Thu, 06 Aug 2026 13:00:00 GMT"),
                ]),
                encoding="utf-8",
            )
            git(site, "add", "-A")
            git(site, "commit", "-m", "déploiement brut")

            deployed = datetime(2026, 8, 6, 18, 7, 12, tzinfo=PARIS)
            result = stamp_publication_times(site, "HEAD~1", deployed)
            self.assertEqual(result["new"], 1)
            self.assertEqual(result["new_slugs"], ["nouveau"])

            data = json.loads((site / "data" / "articles.json").read_text(encoding="utf-8"))
            by_slug = {item["slug"]: item for item in data}
            self.assertEqual(by_slug["ancien"]["date"], old_display)
            self.assertEqual(by_slug["ancien"]["date_iso"], old_iso)
            self.assertEqual(by_slug["nouveau"]["date"], "6 août 2026, 18h07")
            self.assertEqual(by_slug["nouveau"]["date_iso"], "2026-08-06T18:07:12+02:00")

            old_html = (site / "articles" / "ancien.html").read_text(encoding="utf-8")
            new_html = (site / "articles" / "nouveau.html").read_text(encoding="utf-8")
            self.assertIn(f'<time datetime="{old_iso}">{old_display}</time>', old_html)
            self.assertIn('"datePublished":"2026-08-05T18:03:00+02:00"', old_html)
            self.assertIn('<time datetime="2026-08-06T18:07:12+02:00">6 août 2026, 18h07</time>', new_html)
            self.assertIn('"datePublished":"2026-08-06T18:07:12+02:00"', new_html)

            index = (site / "index.html").read_text(encoding="utf-8")
            category = (site / "categories" / "sante.html").read_text(encoding="utf-8")
            self.assertIn(old_display, index)
            self.assertIn("6 août 2026, 18h07", index)
            self.assertIn("6 août 2026, 18h07", category)
            self.assertNotIn(generation_new, index + category)

            feed = (site / "feed.xml").read_text(encoding="utf-8")
            self.assertIn("Wed, 05 Aug 2026 16:03:00 GMT", feed)
            self.assertIn("Thu, 06 Aug 2026 16:07:12 GMT", feed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
