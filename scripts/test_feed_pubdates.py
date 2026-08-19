# -*- coding: utf-8 -*-
from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

import normalize_feed_pubdates as rss

ARTICLE = '''<!doctype html><html><head>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"NewsArticle","datePublished":"2026-08-05T15:09:41+02:00","dateModified":"2026-08-06T10:00:00+02:00"}</script>
</head><body></body></html>'''

INFLATION_WRONG = '''<!doctype html><html><head>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"NewsArticle","datePublished":"2026-08-14T13:57:51+02:00","dateModified":"2026-08-14T13:57:51+02:00"}</script>
</head><body><time datetime="2026-08-14">14 août 2026, 13h57</time></body></html>'''


class FeedPubDateTests(unittest.TestCase):
    def _root(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        (root / "articles").mkdir()
        (root / "data").mkdir()
        (root / "categories").mkdir()
        (root / "articles" / "exemple.html").write_text(ARTICLE, encoding="utf-8")
        (root / "articles" / "inflation-france-juillet-2026.html").write_text(
            INFLATION_WRONG, encoding="utf-8"
        )
        index = [
            {"slug": "exemple", "date": "5 août 2026, 15h09"},
            {"slug": "inflation-france-juillet-2026", "date": "14 août 2026, 13h57"},
        ]
        for name in ("articles.json", "search.json"):
            (root / "data" / name).write_text(
                json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        card = '<a href="articles/inflation-france-juillet-2026.html"><span>14 août 2026, 13h57</span></a>'
        (root / "index.html").write_text(card, encoding="utf-8")
        (root / "categories" / "economie.html").write_text(card, encoding="utf-8")
        (root / "feed.xml").write_text(
            '<rss><channel><lastBuildDate>Thu, 13 Aug 2026 08:06:40 +0000</lastBuildDate>'
            '<item><title>Inflation</title><link>https://lesfaits.info/articles/inflation-france-juillet-2026.html</link>'
            '<pubDate>Fri, 14 Aug 2026 11:57:51 GMT</pubDate></item>'
            '<item><title>X</title><link>https://lesfaits.info/articles/exemple.html</link>'
            '<pubDate>Sat, 08 Aug 2026 19:08:27 +0000</pubDate></item></channel></rss>',
            encoding="utf-8",
        )
        return tmp, root

    def test_restores_article_pubdate_and_rewrites_build_date_in_utc(self):
        tmp, root = self._root()
        try:
            build_time = dt.datetime(2026, 8, 13, 6, 6, 40, tzinfo=dt.timezone.utc)
            result = rss.normalize(root, build_time=build_time)
            text = (root / "feed.xml").read_text(encoding="utf-8")
            self.assertEqual(result["changed"], 1)
            self.assertEqual(result["build_changed"], 1)
            self.assertIn('<pubDate>Wed, 05 Aug 2026 13:09:41 GMT</pubDate>', text)
            self.assertIn('<pubDate>Fri, 14 Aug 2026 13:40:11 GMT</pubDate>', text)
            self.assertIn('<lastBuildDate>Thu, 13 Aug 2026 06:06:40 GMT</lastBuildDate>', text)

            inflation = (root / "articles" / "inflation-france-juillet-2026.html").read_text(encoding="utf-8")
            self.assertIn('<time datetime="2026-08-14T15:40:11+02:00">14 août 2026, 15h40</time>', inflation)
            self.assertIn('"datePublished":"2026-08-14T15:40:11+02:00"', inflation)
            self.assertIn('"dateModified":"2026-08-14T15:40:11+02:00"', inflation)
            for name in ("articles.json", "search.json"):
                data = json.loads((root / "data" / name).read_text(encoding="utf-8"))
                item = next(x for x in data if x["slug"] == "inflation-france-juillet-2026")
                self.assertEqual(item["date"], "14 août 2026, 15h40")
                self.assertEqual(item["date_iso"], "2026-08-14T15:40:11+02:00")
            self.assertIn("14 août 2026, 15h40", (root / "index.html").read_text(encoding="utf-8"))
            self.assertIn("14 août 2026, 15h40", (root / "categories" / "economie.html").read_text(encoding="utf-8"))
            rss.normalize(root, check=True)
        finally:
            tmp.cleanup()

    def test_missing_date_fails_closed(self):
        tmp, root = self._root()
        try:
            (root / "articles" / "exemple.html").write_text('<html></html>', encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "exemple"):
                rss.normalize(root)
        finally:
            tmp.cleanup()

    def test_missing_last_build_date_fails_closed(self):
        tmp, root = self._root()
        try:
            path = root / "feed.xml"
            path.write_text(path.read_text(encoding="utf-8").replace(
                '<lastBuildDate>Thu, 13 Aug 2026 08:06:40 +0000</lastBuildDate>',
                ''
            ), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "lastBuildDate"):
                rss.normalize(root)
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=2)
