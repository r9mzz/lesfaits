#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Normalise les métadonnées temporelles dérivées des articles.

Le JSON-LD ``NewsArticle`` est la source de vérité temporelle du dépôt :
- ``datePublished`` alimente l'attribut ``datetime`` du <time> visible ;
- ``dateModified`` (ou ``datePublished`` à défaut) alimente le ``lastmod``
  article du sitemap ;
- ``datePublished`` alimente le ``pubDate`` RSS.

Cette étape évite qu'un simple rebuild fasse croire que tous les anciens
articles viennent d'être publiés/modifiés. Le correcteur post-déploiement peut
ensuite continuer à aligner les *nouveaux* articles sur l'heure publique réelle
sans avoir à réparer tout le corpus.
"""
from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
ARTICLES_DIR = ROOT / "articles"
SITEMAP = ROOT / "sitemap.xml"
FEED = ROOT / "feed.xml"
BASE_ARTICLE_URL = "https://lesfaits.info/articles/"

JSONLD_RE = re.compile(
    r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
TIME_RE = re.compile(r'(<time\b[^>]*\bdatetime=")[^"]*(")', re.IGNORECASE)
ITEM_RE = re.compile(r"(<item>.*?</item>)", re.IGNORECASE | re.DOTALL)
LINK_RE = re.compile(r"<link>\s*([^<]+?)\s*</link>", re.IGNORECASE)
PUBDATE_RE = re.compile(r"(<pubDate>)[^<]*(</pubDate>)", re.IGNORECASE)


@dataclass(frozen=True)
class ArticleDates:
    slug: str
    published: dt.datetime
    modified: dt.datetime


def _walk_json(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        graph = value.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                yield from _walk_json(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_json(item)


def _is_news_article(node: dict[str, Any]) -> bool:
    kind = node.get("@type")
    if isinstance(kind, str):
        return kind == "NewsArticle"
    if isinstance(kind, list):
        return "NewsArticle" in kind
    return False


def _parse_iso(value: Any, *, path: Path, field: str) -> dt.datetime:
    raw = str(value or "").strip()
    if not raw:
        raise RuntimeError(f"{path.relative_to(ROOT)}: {field} absent")
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError(
            f"{path.relative_to(ROOT)}: {field} ISO invalide ({raw!r})"
        ) from exc
    if parsed.tzinfo is None:
        raise RuntimeError(
            f"{path.relative_to(ROOT)}: {field} doit inclure un fuseau ({raw!r})"
        )
    return parsed


def article_dates(path: Path) -> ArticleDates | None:
    """Lit les dates NewsArticle ; retourne None pour les stubs/noindex."""
    html = path.read_text(encoding="utf-8", errors="replace")
    for raw in JSONLD_RE.findall(html):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"{path.relative_to(ROOT)}: JSON-LD invalide"
            ) from exc
        for node in _walk_json(payload):
            if not _is_news_article(node):
                continue
            published = _parse_iso(node.get("datePublished"), path=path, field="datePublished")
            modified_raw = node.get("dateModified") or node.get("datePublished")
            modified = _parse_iso(modified_raw, path=path, field="dateModified")
            return ArticleDates(path.stem, published, modified)
    return None


def collect_dates() -> dict[str, ArticleDates]:
    dates: dict[str, ArticleDates] = {}
    for path in sorted(ARTICLES_DIR.glob("*.html")):
        meta = article_dates(path)
        if meta is not None:
            dates[meta.slug] = meta
    if not dates:
        raise RuntimeError("Aucun NewsArticle exploitable trouvé dans articles/")
    return dates


def _iso(value: dt.datetime) -> str:
    return value.isoformat(timespec="seconds")


def _rfc2822_utc(value: dt.datetime) -> str:
    return email.utils.format_datetime(value.astimezone(dt.timezone.utc), usegmt=True)


def _slug_from_article_url(url: str) -> str | None:
    if not url.startswith(BASE_ARTICLE_URL):
        return None
    parsed = urlparse(url)
    name = Path(unquote(parsed.path)).name
    return Path(name).stem if name.endswith(".html") else None


def normalize_article_times(dates: dict[str, ArticleDates], *, check: bool) -> tuple[int, list[str]]:
    changed = 0
    failures: list[str] = []
    for slug, meta in dates.items():
        path = ARTICLES_DIR / f"{slug}.html"
        html = path.read_text(encoding="utf-8", errors="replace")
        match = TIME_RE.search(html)
        expected = _iso(meta.published)
        if not match:
            failures.append(f"{path.relative_to(ROOT)}: balise <time datetime> absente")
            continue
        current_match = re.search(r'<time\b[^>]*\bdatetime="([^"]*)"', match.group(0), re.I)
        current = current_match.group(1) if current_match else ""
        if current == expected:
            continue
        if check:
            failures.append(
                f"{path.relative_to(ROOT)}: datetime={current!r}, attendu {expected!r}"
            )
            continue
        html = TIME_RE.sub(lambda m: m.group(1) + expected + m.group(2), html, count=1)
        path.write_text(html, encoding="utf-8")
        changed += 1
    return changed, failures


def normalize_sitemap(dates: dict[str, ArticleDates], *, check: bool) -> tuple[int, list[str]]:
    if not SITEMAP.exists():
        return 0, ["sitemap.xml absent"]
    xml = SITEMAP.read_text(encoding="utf-8", errors="replace")
    changed = 0
    failures: list[str] = []

    for slug, meta in dates.items():
        url = re.escape(f"{BASE_ARTICLE_URL}{slug}.html")
        rx = re.compile(
            rf"(<url><loc>{url}</loc><lastmod>)([^<]+)(</lastmod>)",
            re.IGNORECASE,
        )
        match = rx.search(xml)
        if not match:
            failures.append(f"sitemap.xml: URL article absente pour {slug}")
            continue
        expected = meta.modified.date().isoformat()
        current = match.group(2).strip()
        if current == expected:
            continue
        if check:
            failures.append(
                f"sitemap.xml: {slug} lastmod={current!r}, attendu {expected!r}"
            )
            continue
        xml = rx.sub(lambda m: m.group(1) + expected + m.group(3), xml, count=1)
        changed += 1

    if changed and not check:
        SITEMAP.write_text(xml, encoding="utf-8")
    return changed, failures


def normalize_feed(dates: dict[str, ArticleDates], *, check: bool) -> tuple[int, list[str]]:
    if not FEED.exists():
        return 0, ["feed.xml absent"]
    xml = FEED.read_text(encoding="utf-8", errors="replace")
    changed = 0
    failures: list[str] = []

    def replace_item(match: re.Match[str]) -> str:
        nonlocal changed
        block = match.group(1)
        link_match = LINK_RE.search(block)
        if not link_match:
            failures.append("feed.xml: item sans <link>")
            return block
        slug = _slug_from_article_url(link_match.group(1).strip())
        if slug is None:
            return block
        meta = dates.get(slug)
        if meta is None:
            failures.append(f"feed.xml: article {slug} sans NewsArticle correspondant")
            return block
        pub_match = PUBDATE_RE.search(block)
        if not pub_match:
            failures.append(f"feed.xml: {slug} sans <pubDate>")
            return block
        expected = _rfc2822_utc(meta.published)
        current = block[pub_match.start(1) + len(pub_match.group(1)):pub_match.start(2)].strip()
        if current == expected:
            return block
        if check:
            failures.append(f"feed.xml: {slug} pubDate={current!r}, attendu {expected!r}")
            return block
        changed += 1
        return PUBDATE_RE.sub(lambda m: m.group(1) + expected + m.group(2), block, count=1)

    updated = ITEM_RE.sub(replace_item, xml)
    if changed and not check:
        FEED.write_text(updated, encoding="utf-8")
    return changed, failures


def run(*, check: bool = False) -> tuple[int, list[str]]:
    dates = collect_dates()
    total_changed = 0
    failures: list[str] = []
    for normalizer in (normalize_article_times, normalize_sitemap, normalize_feed):
        changed, errors = normalizer(dates, check=check)
        total_changed += changed
        failures.extend(errors)
    return total_changed, failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Vérifie sans modifier ; échoue si une incohérence est détectée.",
    )
    args = parser.parse_args(argv)

    try:
        changed, failures = run(check=args.check)
    except Exception as exc:
        print(f"[PUBLICATION METADATA FAIL] {exc}", file=sys.stderr)
        return 1

    if failures:
        for failure in failures[:30]:
            print(f"[PUBLICATION METADATA FAIL] {failure}", file=sys.stderr)
        if len(failures) > 30:
            print(
                f"[PUBLICATION METADATA FAIL] +{len(failures) - 30} autre(s)",
                file=sys.stderr,
            )
        return 1

    mode = "vérifiées" if args.check else "normalisées"
    print(
        f"[PUBLICATION METADATA OK] {len(collect_dates())} article(s) {mode}; "
        f"{changed} correction(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
