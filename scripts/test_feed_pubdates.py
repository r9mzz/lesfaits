# -*- coding: utf-8 -*-
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

import normalize_feed_pubdates as rss

ARTICLE = '''<!doctype html><html><head>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"NewsArticle","datePublished":"2026-08-05T15:09:41+02:00","dateModified":"2026-08-06T10:00:00+02:00"}</script>
</head><body></body></html>'''


class FeedPubDateTests(unittest.TestCase):
    def _root(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        (root / "articles").mkdir()
        (root / "articles" / "exemple.html").write_text(ARTICLE, encoding="utf-8")
        (root / "feed.xml").write_text(
            '<rss><channel><lastBuildDate>Thu, 13 Aug 2026 08:06:40 +0000</lastBuildDate>'
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
            self.assertIn('<lastBuildDate>Thu, 13 Aug 2026 06:06:40 GMT</lastBuildDate>', text)
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
