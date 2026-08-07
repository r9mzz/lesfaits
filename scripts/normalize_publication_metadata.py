#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Normalise les métadonnées temporelles réellement dérivées des articles.

Le JSON-LD ``NewsArticle`` est la source de vérité pour les dates. Les anciens
articles qui n'ont conservé qu'un YYYY-MM-DD restent volontairement date-only :
aucune heure n'est inventée. Pour les articles qui disposent d'un horodatage
exact, la balise ``<time>`` est alignée à la fois dans son attribut ``datetime``
et dans son libellé visible afin qu'une ancienne minute de génération ne reste
pas affichée à côté de l'heure publique réelle.

Le sitemap est un index sélectif du corpus ; on corrige les entrées qui existent
sans réinscrire ici les fichiers historiques que le manifeste éditorial a déjà
écartés.
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
    re.I | re.S,
)
TIME_ELEMENT_RE = re.compile(
    r'(<time\b[^>]*\bdatetime=")([^"]*)("[^>]*>)(.*?)(</time>)',
    re.I | re.S,
)
ART_META_RE = re.compile(
    r'(<div\b[^>]*class=["\'][^"\']*\bart__meta\b[^"\']*["\'][^>]*>)(.*?)(</div>)',
    re.I | re.S,
)
LEGACY_DATE_SPAN_RE = re.compile(
    r'(<span\b[^>]*class=["\'][^"\']*\bmeta__sep\b[^"\']*["\'][^>]*>\s*·\s*</span>\s*)'
    r'<span>([^<]*\b\d{4}\b[^<]*)</span>',
    re.I,
)
ITEM_RE = re.compile(r"(<item>.*?</item>)", re.I | re.S)
LINK_RE = re.compile(r"<link>\s*([^<]+?)\s*</link>", re.I)
PUBDATE_RE = re.compile(r"(<pubDate>)[^<]*(</pubDate>)", re.I)
DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

FRENCH_MONTHS = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)


@dataclass(frozen=True)
class ArticleDates:
    slug: str
    published_date: dt.date
    published_exact: dt.datetime | None
    modified_date: dt.date


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
    return kind == "NewsArticle" or (
        isinstance(kind, list) and "NewsArticle" in kind
    )


def _parse_temporal(
    value: Any, *, path: Path, field: str
) -> tuple[dt.date, dt.datetime | None]:
    raw = str(value or "").strip()
    if not raw:
        raise RuntimeError(f"{path.relative_to(ROOT)}: {field} absent")
    if DATE_ONLY_RE.fullmatch(raw):
        try:
            return dt.date.fromisoformat(raw), None
        except ValueError as exc:
            raise RuntimeError(
                f"{path.relative_to(ROOT)}: {field} date invalide ({raw!r})"
            ) from exc
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError(
            f"{path.relative_to(ROOT)}: {field} ISO invalide ({raw!r})"
        ) from exc
    if parsed.tzinfo is None:
        raise RuntimeError(
            f"{path.relative_to(ROOT)}: {field} datetime sans fuseau ({raw!r})"
        )
    return parsed.date(), parsed


def article_dates(path: Path) -> ArticleDates | None:
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
            pub_date, pub_exact = _parse_temporal(
                node.get("datePublished"), path=path, field="datePublished"
            )
            mod_date, _ = _parse_temporal(
                node.get("dateModified") or node.get("datePublished"),
                path=path,
                field="dateModified",
            )
            return ArticleDates(path.stem, pub_date, pub_exact, mod_date)
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


def _visible_datetime(value: dt.datetime) -> str:
    """Retourne le libellé éditorial français à la minute près."""
    return (
        f"{value.day} {FRENCH_MONTHS[value.month - 1]} {value.year}, "
        f"{value.hour:02d}h{value.minute:02d}"
    )


def _slug_from_article_url(url: str) -> str | None:
    if not url.startswith(BASE_ARTICLE_URL):
        return None
    name = Path(unquote(urlparse(url).path)).name
    return Path(name).stem if name.endswith(".html") else None


def _inject_legacy_time(
    html: str, expected: str, visible_text: str | None = None
) -> str | None:
    block = ART_META_RE.search(html)
    if not block:
        return None
    body = block.group(2)
    date_span = LEGACY_DATE_SPAN_RE.search(body)
    if not date_span:
        return None
    label = visible_text if visible_text is not None else date_span.group(2)
    replacement = (
        date_span.group(1)
        + f'<time datetime="{expected}">'
        + label
        + "</time>"
    )
    new_body = body[: date_span.start()] + replacement + body[date_span.end() :]
    return html[: block.start(2)] + new_body + html[block.end(2) :]


def _publication_time_element(html: str) -> tuple[re.Match[str], re.Match[str]] | None:
    block = ART_META_RE.search(html)
    if not block:
        return None
    time_match = TIME_ELEMENT_RE.search(block.group(2))
    if not time_match:
        return None
    return block, time_match


def _replace_publication_time(
    html: str,
    block: re.Match[str],
    time_match: re.Match[str],
    *,
    expected_datetime: str,
    expected_text: str | None,
) -> str:
    body = block.group(2)
    text = time_match.group(4) if expected_text is None else expected_text
    replacement = (
        time_match.group(1)
        + expected_datetime
        + time_match.group(3)
        + text
        + time_match.group(5)
    )
    new_body = body[: time_match.start()] + replacement + body[time_match.end() :]
    return html[: block.start(2)] + new_body + html[block.end(2) :]


def normalize_article_times(
    dates: dict[str, ArticleDates], *, check: bool
) -> tuple[int, list[str]]:
    changed = 0
    failures: list[str] = []
    for slug, meta in dates.items():
        path = ARTICLES_DIR / f"{slug}.html"
        html = path.read_text(encoding="utf-8", errors="replace")
        expected_datetime = (
            _iso(meta.published_exact)
            if meta.published_exact is not None
            else meta.published_date.isoformat()
        )
        expected_text = (
            _visible_datetime(meta.published_exact)
            if meta.published_exact is not None
            else None
        )

        found = _publication_time_element(html)
        if found is None:
            if check:
                failures.append(f"{path.relative_to(ROOT)}: balise <time datetime> absente")
                continue
            injected = _inject_legacy_time(html, expected_datetime, expected_text)
            if injected is None:
                failures.append(
                    f"{path.relative_to(ROOT)}: <time> absent et date visible introuvable"
                )
                continue
            path.write_text(injected, encoding="utf-8")
            changed += 1
            continue

        block, time_match = found
        current_datetime = time_match.group(2).strip()
        current_text = time_match.group(4).strip()

        if meta.published_exact is not None:
            datetime_ok = current_datetime == expected_datetime
            text_ok = current_text == expected_text
            if datetime_ok and text_ok:
                continue
            if check:
                if not datetime_ok:
                    failures.append(
                        f"{path.relative_to(ROOT)}: datetime={current_datetime!r}, "
                        f"attendu {expected_datetime!r}"
                    )
                if not text_ok:
                    failures.append(
                        f"{path.relative_to(ROOT)}: heure visible={current_text!r}, "
                        f"attendue {expected_text!r}"
                    )
                continue
            updated = _replace_publication_time(
                html,
                block,
                time_match,
                expected_datetime=expected_datetime,
                expected_text=expected_text,
            )
            path.write_text(updated, encoding="utf-8")
            changed += 1
            continue

        current_date = (
            current_datetime[:10] if len(current_datetime) >= 10 else current_datetime
        )
        if current_date == expected_datetime:
            continue
        if check:
            failures.append(
                f"{path.relative_to(ROOT)}: date datetime={current_datetime!r}, "
                f"attendu {expected_datetime!r}"
            )
            continue
        updated = _replace_publication_time(
            html,
            block,
            time_match,
            expected_datetime=expected_datetime,
            expected_text=None,
        )
        path.write_text(updated, encoding="utf-8")
        changed += 1
    return changed, failures


def normalize_sitemap(
    dates: dict[str, ArticleDates], *, check: bool
) -> tuple[int, list[str]]:
    if not SITEMAP.exists():
        return 0, ["sitemap.xml absent"]
    xml = SITEMAP.read_text(encoding="utf-8", errors="replace")
    changed = 0
    failures: list[str] = []
    for slug, meta in dates.items():
        url = re.escape(f"{BASE_ARTICLE_URL}{slug}.html")
        rx = re.compile(
            rf"(<url><loc>{url}</loc><lastmod>)([^<]+)(</lastmod>)", re.I
        )
        match = rx.search(xml)
        # Le sitemap est construit depuis data/articles.json, pas depuis tous
        # les fichiers historiques encore présents sur disque. Sa couverture
        # exacte est vérifiée séparément par check_site_integrity.py.
        if not match:
            continue
        expected = meta.modified_date.isoformat()
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


def normalize_feed(
    dates: dict[str, ArticleDates], *, check: bool
) -> tuple[int, list[str]]:
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
        if meta.published_exact is None:
            return block
        expected = _rfc2822_utc(meta.published_exact)
        current = block[
            pub_match.start(1) + len(pub_match.group(1)):pub_match.start(2)
        ].strip()
        if current == expected:
            return block
        if check:
            failures.append(
                f"feed.xml: {slug} pubDate={current!r}, attendu {expected!r}"
            )
            return block
        changed += 1
        return PUBDATE_RE.sub(
            lambda m: m.group(1) + expected + m.group(2), block, count=1
        )

    updated = ITEM_RE.sub(replace_item, xml)
    if changed and not check:
        FEED.write_text(updated, encoding="utf-8")
    return changed, failures


def run(*, check: bool = False) -> tuple[int, list[str]]:
    dates = collect_dates()
    changed = 0
    failures: list[str] = []
    for fn in (normalize_article_times, normalize_sitemap, normalize_feed):
        count, errors = fn(dates, check=check)
        changed += count
        failures.extend(errors)
    return changed, failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
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
