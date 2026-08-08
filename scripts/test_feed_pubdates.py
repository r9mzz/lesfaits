# -*- coding: utf-8 -*-
from __future__ import annotations

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
            '<rss><channel><lastBuildDate>Sat, 08 Aug 2026 19:08:27 +0000</lastBuildDate>'
            '<item><title>X</title><link>https://lesfaits.info/articles/exemple.html</link>'
            '<pubDate>Sat, 08 Aug 2026 19:08:27 +0000</pubDate></item></channel></rss>',
            encoding="utf-8",
        )
        return tmp, root

    def test_restores_article_pubdate_and_keeps_build_date(self):
        tmp, root = self._root()
        try:
            result = rss.normalize(root)
            text = (root / "feed.xml").read_text(encoding="utf-8")
            self.assertEqual(result["changed"], 1)
            self.assertIn('<pubDate>Wed, 05 Aug 2026 13:09:41 GMT</pubDate>', text)
            self.assertIn('<lastBuildDate>Sat, 08 Aug 2026 19:08:27 +0000</lastBuildDate>', text)
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
