#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audit déterministe du site statique produit par Les Faits.

Le contrôle reste purement local : aucun média tiers n'est appelé. Il vérifie
ce dont Les Faits est directement responsable avant publication : liens/assets
locaux, canonicals, images, IDs, blocs newsletter, sources et cohérence du
corpus entre manifeste, recherche, sitemap, retraits et pages indexables.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

ROOT = Path(__file__).resolve().parent.parent
SITE_BASE = "https://lesfaits.info/"
CORE_STATIC = {
    "index.html", "archive.html", "breves.html", "methode.html",
    "a-propos.html", "contact.html", "corrections.html", "recherche.html",
}
NEWSARTICLE_RE = re.compile(
    r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>.*?'
    r'["\']@type["\']\s*:\s*["\']NewsArticle["\'].*?</script>', re.I | re.S,
)


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.base_href: str | None = None
        self.refs: list[tuple[str, str, str]] = []
        self.ids: list[str] = []
        self.img_alts: list[str | None] = []
        self.canonicals: list[str] = []
        self.newsletter_forms = 0

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = {k.lower(): v for k, v in attrs_list}
        tag = tag.lower()
        if attrs.get("id"):
            self.ids.append(attrs["id"])
        if tag == "base" and attrs.get("href"):
            self.base_href = attrs["href"]
        if tag == "link" and (attrs.get("rel") or "").lower() == "canonical" and attrs.get("href"):
            self.canonicals.append(attrs["href"])
        if tag == "form" and attrs.get("id") == "nl-form":
            self.newsletter_forms += 1
        if tag == "img":
            self.img_alts.append(attrs.get("alt"))
        for attr in ("href", "src"):
            value = attrs.get(attr)
            if value:
                self.refs.append((tag, attr, value))
        if attrs.get("srcset"):
            for candidate in attrs["srcset"].split(","):
                url = candidate.strip().split()[0] if candidate.strip() else ""
                if url:
                    self.refs.append((tag, "srcset", url))


def _pages() -> list[Path]:
    pages = [p for p in ROOT.glob("*.html") if p.is_file()]
    pages.extend(p for p in (ROOT / "categories").glob("*.html") if p.is_file())
    pages.extend(p for p in (ROOT / "articles").glob("*.html") if p.is_file())
    return sorted(set(pages))


def _load_list(path: Path) -> list[dict]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    if not isinstance(value, list):
        raise RuntimeError(f"{path.relative_to(ROOT)} doit contenir une liste")
    return [item for item in value if isinstance(item, dict)]


def _is_external(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https", "mailto", "tel", "data"} or value.startswith("//")


def _resolve_local(page: Path, base_href: str | None, value: str) -> Path | None:
    value = value.strip()
    if not value or value.startswith("#") or value.startswith("javascript:"):
        return None
    if value.startswith("{{") or _is_external(value):
        return None
    rel = page.relative_to(ROOT).as_posix()
    document_url = urljoin(SITE_BASE, rel)
    effective_base = urljoin(document_url, base_href) if base_href else document_url
    resolved = urlparse(urljoin(effective_base, value))
    if resolved.netloc and resolved.netloc != "lesfaits.info":
        return None
    path = unquote(resolved.path)
    if path in {"", "/"}:
        path = "/index.html"
    elif path.endswith("/"):
        path += "index.html"
    return ROOT / path.lstrip("/")


def _expected_canonical(page: Path) -> str:
    rel = page.relative_to(ROOT).as_posix()
    return SITE_BASE if rel == "index.html" else urljoin(SITE_BASE, rel)


def _indexable(html: str) -> bool:
    robots = re.search(r'<meta[^>]+name=["\']robots["\'][^>]*content=["\']([^"\']+)', html, re.I)
    return not (robots and "noindex" in robots.group(1).lower())


def _sources_block(html: str) -> str | None:
    match = re.search(
        r'<(?:section|div)\b[^>]*class=["\'][^"\']*\bsources\b[^"\']*["\'][^>]*>(.*?)</(?:section|div)>',
        html, re.I | re.S,
    )
    return match.group(1) if match else None


def _source_urls(block: str) -> list[str]:
    return re.findall(r'<a\b[^>]*href=["\']([^"\']+)["\']', block, re.I)


def _source_hosts(urls: list[str]) -> set[str]:
    hosts: set[str] = set()
    for url in urls:
        if not url.startswith(("http://", "https://")):
            continue
        host = (urlparse(url).hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        if host:
            hosts.add(host)
    return hosts


def audit_page(page: Path) -> list[str]:
    rel = page.relative_to(ROOT).as_posix()
    html = page.read_text(encoding="utf-8", errors="replace")
    parser = PageParser()
    try:
        parser.feed(html)
    except Exception as exc:
        return [f"{rel}: HTML non analysable ({exc})"]

    failures: list[str] = []
    duplicates = [key for key, count in Counter(parser.ids).items() if count > 1]
    if duplicates:
        failures.append(f"{rel}: id HTML dupliqué(s): {', '.join(duplicates[:8])}")
    if parser.newsletter_forms > 1:
        failures.append(f"{rel}: {parser.newsletter_forms} formulaires #nl-form (doublon newsletter)")
    missing_alt = sum(1 for alt in parser.img_alts if alt is None)
    if missing_alt:
        failures.append(f"{rel}: {missing_alt} image(s) sans attribut alt")

    for tag, attr, value in parser.refs:
        target = _resolve_local(page, parser.base_href, value)
        if target is not None and not target.exists():
            failures.append(f"{rel}: {tag}[{attr}] cassé -> {value}")

    must_have_canonical = rel in CORE_STATIC or rel.startswith("categories/") or rel.startswith("articles/")
    if must_have_canonical and _indexable(html):
        if len(parser.canonicals) != 1:
            failures.append(f"{rel}: canonical attendu une fois, trouvé {len(parser.canonicals)}")
        elif parser.canonicals[0] != _expected_canonical(page):
            failures.append(f"{rel}: canonical={parser.canonicals[0]!r}, attendu {_expected_canonical(page)!r}")

    if rel.startswith("articles/") and _indexable(html):
        block = _sources_block(html)
        if block is None:
            failures.append(f"{rel}: bloc SOURCES absent")
        else:
            listed = len(re.findall(r"<li\b", block, re.I))
            urls = _source_urls(block)
            hosts = _source_hosts(urls)
            declared_match = re.search(r">\s*(\d+)\s+source(?:s)?\s*<", html, re.I)
            if declared_match and int(declared_match.group(1)) != listed:
                failures.append(f"{rel}: {declared_match.group(1)} source(s) annoncée(s), {listed} listée(s)")
            if listed == 0:
                failures.append(f"{rel}: aucune source listée")
            for href in urls:
                if not href.startswith(("http://", "https://")):
                    failures.append(f"{rel}: lien source non HTTP(S) -> {href}")
            distinct_match = re.search(
                r'<strong>Sources\s*:</strong>\s*(\d+)\s+sources?\s+distinctes?', html, re.I,
            )
            if distinct_match and int(distinct_match.group(1)) != len(hosts):
                failures.append(
                    f"{rel}: {distinct_match.group(1)} source(s) distincte(s) annoncée(s), {len(hosts)} domaine(s) réellement cité(s)"
                )
    return failures


def audit_corpus() -> list[str]:
    failures: list[str] = []
    manifest_items = _load_list(ROOT / "data" / "articles.json")
    search_items = _load_list(ROOT / "data" / "search.json")
    retirement_items = _load_list(ROOT / "data" / "retirements.json")

    manifest_list = [str(i.get("slug", "")).strip() for i in manifest_items]
    manifest_list = [s for s in manifest_list if s]
    if len(manifest_list) != len(set(manifest_list)):
        duplicate_slugs = [s for s, n in Counter(manifest_list).items() if n > 1]
        failures.append("data/articles.json: slug(s) dupliqué(s): " + ", ".join(duplicate_slugs[:10]))
    active = set(manifest_list)
    search = {str(i.get("slug", "")).strip() for i in search_items if str(i.get("slug", "")).strip()}
    retired = {str(i.get("slug", "")).strip() for i in retirement_items if str(i.get("slug", "")).strip()}

    overlap = active & retired
    if overlap:
        failures.append("slug(s) actifs et retirés simultanément: " + ", ".join(sorted(overlap)[:10]))

    sitemap_path = ROOT / "sitemap.xml"
    sitemap_text = sitemap_path.read_text(encoding="utf-8", errors="replace") if sitemap_path.exists() else ""
    sitemap_slugs = set(re.findall(r'https://lesfaits\.info/articles/([^/<]+)\.html', sitemap_text, re.I))

    missing_search = active - search
    extra_search = search - active
    missing_sitemap = active - sitemap_slugs
    extra_sitemap = sitemap_slugs - active
    if missing_search:
        failures.append("recherche: article(s) actif(s) absent(s): " + ", ".join(sorted(missing_search)[:10]))
    if extra_search:
        failures.append("recherche: slug(s) hors manifeste: " + ", ".join(sorted(extra_search)[:10]))
    if missing_sitemap:
        failures.append("sitemap: article(s) actif(s) absent(s): " + ", ".join(sorted(missing_sitemap)[:10]))
    if extra_sitemap:
        failures.append("sitemap: article(s) hors manifeste: " + ", ".join(sorted(extra_sitemap)[:10]))

    for slug in sorted(active):
        path = ROOT / "articles" / f"{slug}.html"
        if not path.exists():
            failures.append(f"manifeste: fichier article absent pour {slug}")
            continue
        html = path.read_text(encoding="utf-8", errors="replace")
        if not _indexable(html):
            failures.append(f"manifeste: article actif noindex pour {slug}")

    retirement_by_slug = {
        str(item.get("slug", "")).strip(): item
        for item in retirement_items if str(item.get("slug", "")).strip()
    }
    for slug, item in sorted(retirement_by_slug.items()):
        target = str(item.get("redirect_to", "")).strip()
        path = ROOT / "articles" / f"{slug}.html"
        if slug in search or slug in sitemap_slugs:
            failures.append(f"retrait: {slug} encore présent dans recherche/sitemap")
        if not path.exists():
            failures.append(f"retrait: stub absent pour {slug}")
            continue
        html = path.read_text(encoding="utf-8", errors="replace")
        if _indexable(html):
            failures.append(f"retrait: {slug} encore indexable")
        expected = f"https://lesfaits.info/articles/{target}.html"
        canonical = re.search(r'<link\b[^>]*rel=["\']canonical["\'][^>]*href=["\']([^"\']+)', html, re.I)
        if not canonical or canonical.group(1) != expected:
            failures.append(f"retrait: canonical incorrect pour {slug} -> {target}")

    for path in sorted((ROOT / "articles").glob("*.html")):
        html = path.read_text(encoding="utf-8", errors="replace")
        if NEWSARTICLE_RE.search(html) and path.stem not in active and _indexable(html):
            failures.append(f"corpus: NewsArticle hors manifeste encore indexable: {path.stem}")
    return failures


def run() -> list[str]:
    pages = _pages()
    if not pages:
        return ["aucune page HTML trouvée"]
    failures: list[str] = []
    for page in pages:
        failures.extend(audit_page(page))
    failures.extend(audit_corpus())
    return failures


def main() -> int:
    failures = run()
    if failures:
        for failure in failures[:80]:
            print(f"[INTEGRITY FAIL] {failure}", file=sys.stderr)
        if len(failures) > 80:
            print(f"[INTEGRITY FAIL] +{len(failures) - 80} autre(s)", file=sys.stderr)
        return 1
    print(
        f"[INTEGRITY OK] {len(_pages())} page(s) vérifiée(s) : liens, assets, canonical, images, sources, ids, newsletter et corpus public."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
