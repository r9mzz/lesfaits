#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audit déterministe du site statique produit par Les Faits.

Le contrôle reste purement local : aucun lien externe n'est appelé, ce qui
évite de rendre un déploiement dépendant d'un média tiers momentanément lent.
Il vérifie en revanche que toute la structure dont Les Faits est responsable
est cohérente avant publication.
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

ROOT = Path(__file__).resolve().parent.parent
SITE_BASE = "https://lesfaits.info/"
VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}
CORE_STATIC = {
    "index.html", "archive.html", "breves.html", "methode.html",
    "a-propos.html", "contact.html", "corrections.html", "recherche.html",
}


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.base_href: str | None = None
        self.refs: list[tuple[str, str, str]] = []
        self.ids: list[str] = []
        self.img_alts: list[str | None] = []
        self.canonicals: list[str] = []
        self.newsletter_forms = 0
        self.source_links: list[str] = []
        self._source_depth = 0
        self._stack: list[tuple[str, bool]] = []

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = {k.lower(): v for k, v in attrs_list}
        tag = tag.lower()
        classes = set((attrs.get("class") or "").split())
        enters_sources = tag == "section" and "sources" in classes

        if self._source_depth and tag not in VOID_TAGS:
            self._source_depth += 1
        if enters_sources:
            self._source_depth = 1

        if tag not in VOID_TAGS:
            self._stack.append((tag, enters_sources))

        value_id = attrs.get("id")
        if value_id:
            self.ids.append(value_id)
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
                if self._source_depth and tag == "a" and attr == "href":
                    self.source_links.append(value)
        if attrs.get("srcset"):
            for candidate in attrs["srcset"].split(","):
                url = candidate.strip().split()[0] if candidate.strip() else ""
                if url:
                    self.refs.append((tag, "srcset", url))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if not self._stack:
            return
        # Le HTML généré est normalement bien imbriqué. En cas de fermeture
        # imparfaite, remonter jusqu'au tag correspondant sans planter l'audit.
        idx = next((i for i in range(len(self._stack) - 1, -1, -1) if self._stack[i][0] == tag), None)
        if idx is None:
            return
        removed = self._stack[idx:]
        del self._stack[idx:]
        if self._source_depth:
            for removed_tag, entered_sources in reversed(removed):
                if entered_sources:
                    self._source_depth = 0
                    break
                if removed_tag not in VOID_TAGS:
                    self._source_depth = max(0, self._source_depth - 1)


def _pages() -> list[Path]:
    pages = [p for p in ROOT.glob("*.html") if p.is_file()]
    pages.extend(p for p in (ROOT / "categories").glob("*.html") if p.is_file())
    pages.extend(p for p in (ROOT / "articles").glob("*.html") if p.is_file())
    return sorted(set(pages))


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
        if target is None:
            continue
        # Les href purement applicatifs peuvent viser une route avec query ; le
        # fichier sous-jacent doit tout de même exister.
        if not target.exists():
            failures.append(f"{rel}: {tag}[{attr}] cassé -> {value}")

    must_have_canonical = rel in CORE_STATIC or rel.startswith("categories/") or rel.startswith("articles/")
    if must_have_canonical and _indexable(html):
        if len(parser.canonicals) != 1:
            failures.append(f"{rel}: canonical attendu une fois, trouvé {len(parser.canonicals)}")
        elif parser.canonicals[0] != _expected_canonical(page):
            failures.append(
                f"{rel}: canonical={parser.canonicals[0]!r}, attendu {_expected_canonical(page)!r}"
            )

    if rel.startswith("articles/") and _indexable(html):
        source_section = re.search(
            r'<section\b[^>]*class=["\'][^"\']*\bsources\b[^"\']*["\'][^>]*>(.*?)</section>',
            html,
            re.I | re.S,
        )
        if not source_section:
            failures.append(f"{rel}: section SOURCES absente")
        else:
            listed = len(re.findall(r"<li\b", source_section.group(1), re.I))
            declared_match = re.search(r">\s*(\d+)\s+source(?:s)?\s*<", html, re.I)
            if declared_match and int(declared_match.group(1)) != listed:
                failures.append(
                    f"{rel}: {declared_match.group(1)} source(s) annoncée(s), {listed} listée(s)"
                )
            if listed == 0:
                failures.append(f"{rel}: aucune source listée")
            for href in parser.source_links:
                if not href.startswith(("http://", "https://")):
                    failures.append(f"{rel}: lien source non HTTP(S) -> {href}")

    return failures


def run() -> list[str]:
    failures: list[str] = []
    pages = _pages()
    if not pages:
        return ["aucune page HTML trouvée"]
    for page in pages:
        failures.extend(audit_page(page))
    return failures


def main() -> int:
    failures = run()
    if failures:
        for failure in failures[:80]:
            print(f"[INTEGRITY FAIL] {failure}", file=sys.stderr)
        if len(failures) > 80:
            print(f"[INTEGRITY FAIL] +{len(failures) - 80} autre(s)", file=sys.stderr)
        return 1
    print(f"[INTEGRITY OK] {len(_pages())} page(s) vérifiée(s) : liens, assets, canonical, images, sources, ids et newsletter.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
