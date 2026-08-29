# -*- coding: utf-8 -*-
from __future__ import annotations

import subprocess
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

    def _init_git(self, root: Path) -> None:
        subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "Regression Test"], cwd=root, check=True)

    def _commit(self, root: Path, message: str) -> None:
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "-m", message], cwd=root, check=True, capture_output=True)

    def test_uses_date_modified_and_keeps_static_urls_outside_git(self):
        tmp, root = self._root()
        try:
            result = sm.normalize(root)
            text = (root / "sitemap.xml").read_text(encoding="utf-8")
            self.assertEqual(result["changed"], 1)
            self.assertEqual(result["non_article_changed"], 0)
            self.assertIn(
                '<loc>https://lesfaits.info/articles/exemple.html</loc><lastmod>2026-08-06</lastmod>',
                text,
            )
            self.assertIn('<loc>https://lesfaits.info/</loc><lastmod>2026-08-08</lastmod>', text)
            sm.normalize(root, check=True)
        finally:
            tmp.cleanup()

    def test_zero_article_rebuild_restores_unchanged_non_article_lastmod(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        try:
            (root / "articles").mkdir()
            (root / "categories").mkdir()
            (root / "articles" / "exemple.html").write_text(ARTICLE, encoding="utf-8")
            (root / "index.html").write_text("accueil stable", encoding="utf-8")
            (root / "archive.html").write_text("archive avant", encoding="utf-8")
            (root / "categories" / "science.html").write_text("science stable", encoding="utf-8")
            initial = (
                '<?xml version="1.0"?><urlset>'
                '<url><loc>https://lesfaits.info/</loc><lastmod>2026-08-17</lastmod></url>'
                '<url><loc>https://lesfaits.info/archive.html</loc><lastmod>2026-08-17</lastmod></url>'
                '<url><loc>https://lesfaits.info/categories/science.html</loc><lastmod>2026-08-17</lastmod></url>'
                '<url><loc>https://lesfaits.info/articles/exemple.html</loc><lastmod>2026-08-06</lastmod><changefreq>monthly</changefreq></url>'
                '</urlset>'
            )
            (root / "sitemap.xml").write_text(initial, encoding="utf-8")
            self._init_git(root)
            self._commit(root, "baseline")

            rebuilt = initial.replace("2026-08-17", "2026-08-18")
            (root / "sitemap.xml").write_text(rebuilt, encoding="utf-8")
            (root / "archive.html").write_text("archive réellement modifiée", encoding="utf-8")

            result = sm.normalize(root)
            text = (root / "sitemap.xml").read_text(encoding="utf-8")
            self.assertEqual(result["non_article_changed"], 2)
            self.assertIn('<loc>https://lesfaits.info/</loc><lastmod>2026-08-17</lastmod>', text)
            self.assertIn('<loc>https://lesfaits.info/categories/science.html</loc><lastmod>2026-08-17</lastmod>', text)
            self.assertIn('<loc>https://lesfaits.info/archive.html</loc><lastmod>2026-08-18</lastmod>', text)
        finally:
            tmp.cleanup()

    def test_post_commit_normalization_uses_previous_public_commit(self):
        """Après le commit du rebuild, HEAD ne doit pas devenir sa propre référence."""
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        try:
            (root / "articles").mkdir()
            (root / "categories").mkdir()
            (root / "articles" / "exemple.html").write_text(ARTICLE, encoding="utf-8")
            (root / "categories" / "science.html").write_text("science stable", encoding="utf-8")
            initial = (
                '<?xml version="1.0"?><urlset>'
                '<url><loc>https://lesfaits.info/categories/science.html</loc><lastmod>2026-08-20</lastmod></url>'
                '<url><loc>https://lesfaits.info/articles/exemple.html</loc><lastmod>2026-08-06</lastmod><changefreq>monthly</changefreq></url>'
                '</urlset>'
            )
            (root / "sitemap.xml").write_text(initial, encoding="utf-8")
            self._init_git(root)
            self._commit(root, "public précédent")

            rebuilt = initial.replace("2026-08-20", "2026-08-29")
            (root / "sitemap.xml").write_text(rebuilt, encoding="utf-8")
            self._commit(root, "publication automatique")

            result = sm.normalize(root)
            text = (root / "sitemap.xml").read_text(encoding="utf-8")
            self.assertEqual(result["non_article_changed"], 1)
            self.assertIn('<loc>https://lesfaits.info/categories/science.html</loc><lastmod>2026-08-20</lastmod>', text)
        finally:
            tmp.cleanup()

    def test_post_commit_keeps_lastmod_when_page_really_changed(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        try:
            (root / "articles").mkdir()
            (root / "categories").mkdir()
            (root / "articles" / "exemple.html").write_text(ARTICLE, encoding="utf-8")
            (root / "categories" / "science.html").write_text("ancienne science", encoding="utf-8")
            initial = (
                '<?xml version="1.0"?><urlset>'
                '<url><loc>https://lesfaits.info/categories/science.html</loc><lastmod>2026-08-20</lastmod></url>'
                '<url><loc>https://lesfaits.info/articles/exemple.html</loc><lastmod>2026-08-06</lastmod><changefreq>monthly</changefreq></url>'
                '</urlset>'
            )
            (root / "sitemap.xml").write_text(initial, encoding="utf-8")
            self._init_git(root)
            self._commit(root, "public précédent")

            (root / "categories" / "science.html").write_text("science réellement modifiée", encoding="utf-8")
            (root / "sitemap.xml").write_text(initial.replace("2026-08-20", "2026-08-29"), encoding="utf-8")
            self._commit(root, "publication automatique")

            result = sm.normalize(root)
            text = (root / "sitemap.xml").read_text(encoding="utf-8")
            self.assertEqual(result["non_article_changed"], 0)
            self.assertIn('<loc>https://lesfaits.info/categories/science.html</loc><lastmod>2026-08-29</lastmod>', text)
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
