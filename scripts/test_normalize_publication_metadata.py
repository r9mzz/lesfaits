#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
from pathlib import Path

import normalize_publication_metadata as metadata


ARTICLE = '''<!doctype html>
<html lang="fr"><head>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"NewsArticle","headline":"Test","datePublished":"2026-08-05T15:09:41+02:00","dateModified":"2026-08-06T10:11:12+02:00"}</script>
</head><body><time datetime="2026-08-05">5 août 2026, 15h09</time></body></html>
'''

LEGACY_ARTICLE = '''<!doctype html>
<html lang="fr"><head>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"NewsArticle","headline":"Archive","datePublished":"2026-06-26","dateModified":"2026-06-26"}</script>
</head><body><time datetime="2026-06-26">26 juin 2026, 19h42</time></body></html>
'''

SITEMAP = '''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://lesfaits.info/articles/test-article.html</loc><lastmod>2026-08-07</lastmod><changefreq>monthly</changefreq><priority>0.9</priority></url>
  <url><loc>https://lesfaits.info/articles/legacy-article.html</loc><lastmod>2026-08-07</lastmod><changefreq>monthly</changefreq><priority>0.9</priority></url>
</urlset>
'''

FEED = '''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <lastBuildDate>Fri, 07 Aug 2026 17:09:41 +0000</lastBuildDate>
  <item>
    <title>Test</title>
    <link>https://lesfaits.info/articles/test-article.html</link>
    <pubDate>Fri, 07 Aug 2026 17:09:41 +0000</pubDate>
  </item>
  <item>
    <title>Archive</title>
    <link>https://lesfaits.info/articles/legacy-article.html</link>
    <pubDate>Fri, 26 Jun 2026 17:42:00 GMT</pubDate>
  </item>
</channel></rss>
'''


def main() -> int:
    old = (metadata.ROOT, metadata.ARTICLES_DIR, metadata.SITEMAP, metadata.FEED)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            articles = root / "articles"
            articles.mkdir()
            (articles / "test-article.html").write_text(ARTICLE, encoding="utf-8")
            (articles / "legacy-article.html").write_text(LEGACY_ARTICLE, encoding="utf-8")
            (articles / "redirect.html").write_text(
                '<meta name="robots" content="noindex"><p>Redirection</p>',
                encoding="utf-8",
            )
            (root / "sitemap.xml").write_text(SITEMAP, encoding="utf-8")
            (root / "feed.xml").write_text(FEED, encoding="utf-8")

            metadata.ROOT = root
            metadata.ARTICLES_DIR = articles
            metadata.SITEMAP = root / "sitemap.xml"
            metadata.FEED = root / "feed.xml"

            changed, failures = metadata.run(check=False)
            assert failures == [], failures
            assert changed == 4, changed

            html = (articles / "test-article.html").read_text(encoding="utf-8")
            legacy_html = (articles / "legacy-article.html").read_text(encoding="utf-8")
            sitemap = (root / "sitemap.xml").read_text(encoding="utf-8")
            feed = (root / "feed.xml").read_text(encoding="utf-8")

            assert 'datetime="2026-08-05T15:09:41+02:00"' in html
            assert 'datetime="2026-06-26"' in legacy_html
            assert 'datetime="2026-06-26T00:00:00' not in legacy_html
            assert '<lastmod>2026-08-06</lastmod>' in sitemap
            assert '<lastmod>2026-06-26</lastmod>' in sitemap
            assert '<pubDate>Wed, 05 Aug 2026 13:09:41 GMT</pubDate>' in feed
            assert '<pubDate>Fri, 26 Jun 2026 17:42:00 GMT</pubDate>' in feed
            assert '<lastBuildDate>Fri, 07 Aug 2026 17:09:41 +0000</lastBuildDate>' in feed

            changed_check, failures_check = metadata.run(check=True)
            assert changed_check == 0, changed_check
            assert failures_check == [], failures_check

        print("test_normalize_publication_metadata: OK")
        return 0
    finally:
        metadata.ROOT, metadata.ARTICLES_DIR, metadata.SITEMAP, metadata.FEED = old


if __name__ == "__main__":
    raise SystemExit(main())
