# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import normalize_sitemap_lastmod as sm


ARTICLE = '''<!doctype html><html><head>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"NewsArticle","datePublished":"2026-08-05T15:09:41+02:00","dateModified":"2026-08-06T10:00:00+02:00"}</script>
</head><body><time datetime="2026-08-05">5 août 2026</time></body></html>'''


class SitemapLastmodTests(unittest.TestCase):
    def _root(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        (root / "articles").mkdir()
        (root / "articles" / "exemple.html").write_text(ARTICLE, encoding="utf-8")
        (root / "sitemap.xml").write_text(
            '<?xml version="1.0"?><urlset>'
            '<url><loc>https://lesfaits.info/</loc><lastmod>2026-08-08</lastmod></url>'
            '<url><loc>https://lesfaits.info/articles/exemple.html</loc><lastmod>2026-08-08</lastmod><changefreq>monthly</changefreq></url>'
            '</urlset>',
            encoding="utf-8",
        )
        return tmp, root

    def test_uses_date_modified_and_keeps_static_urls(self):
        tmp, root = self._root()
        try:
            result = sm.normalize(root)
            text = (root / "sitemap.xml").read_text(encoding="utf-8")
            self.assertEqual(result["changed"], 1)
            self.assertIn(
                '<loc>https://lesfaits.info/articles/exemple.html</loc><lastmod>2026-08-06</lastmod>',
                text,
            )
            self.assertIn('<loc>https://lesfaits.info/</loc><lastmod>2026-08-08</lastmod>', text)
            sm.normalize(root, check=True)
        finally:
            tmp.cleanup()

    def test_falls_back_to_date_published(self):
        tmp, root = self._root()
        try:
            article = ARTICLE.replace(',"dateModified":"2026-08-06T10:00:00+02:00"', '')
            (root / "articles" / "exemple.html").write_text(article, encoding="utf-8")
            sm.normalize(root)
            text = (root / "sitemap.xml").read_text(encoding="utf-8")
            self.assertIn('<lastmod>2026-08-05</lastmod>', text)
        finally:
            tmp.cleanup()

    def test_legacy_real_article_falls_back_to_visible_time(self):
        tmp, root = self._root()
        try:
            legacy = '<html><body><time datetime="2026-07-31">31 juillet 2026</time></body></html>'
            (root / "articles" / "exemple.html").write_text(legacy, encoding="utf-8")
            sm.normalize(root)
            text = (root / "sitemap.xml").read_text(encoding="utf-8")
            self.assertIn('<lastmod>2026-07-31</lastmod>', text)
        finally:
            tmp.cleanup()

    def test_noindex_redirect_is_removed_from_sitemap(self):
        tmp, root = self._root()
        try:
            redirect = '''<html><head><meta name="robots" content="noindex, follow">
<meta http-equiv="refresh" content="0;url=/articles/canonique.html"></head><body>Redirection</body></html>'''
            (root / "articles" / "exemple.html").write_text(redirect, encoding="utf-8")
            result = sm.normalize(root)
            text = (root / "sitemap.xml").read_text(encoding="utf-8")
            self.assertEqual(result["removed"], 1)
            self.assertNotIn('/articles/exemple.html', text)
            sm.normalize(root, check=True)
        finally:
            tmp.cleanup()

    def test_missing_real_article_date_fails_closed_with_slug(self):
        tmp, root = self._root()
        try:
            (root / "articles" / "exemple.html").write_text('<html><body>vraie page sans date</body></html>', encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "exemple"):
                sm.normalize(root)
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=2)
