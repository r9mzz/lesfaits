#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Normalise les `pubDate` RSS avec la vraie `datePublished` des articles.

Le générateur historique utilisait l'heure du rebuild pour chaque entrée, ce qui
faisait remonter artificiellement tout le flux à chaque déploiement. La source
de vérité est le JSON-LD NewsArticle de la page publique.
"""
from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ITEM_RE = re.compile(r"(<item>.*?</item>)", re.I | re.S)
LINK_RE = re.compile(
    r"<link>https://lesfaits\.info/articles/([^<]+)\.html</link>", re.I
)
PUBDATE_RE = re.compile(r"(<pubDate>)(.*?)(</pubDate>)", re.I | re.S)
JSON_LD_RE = re.compile(
    r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.S,
)


def _parse_iso(value: object) -> dt.datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def article_published_at(path: Path) -> dt.datetime | None:
    html = path.read_text(encoding="utf-8", errors="replace")
    for block in JSON_LD_RE.findall(html):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        objects = data if isinstance(data, list) else [data]
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            kinds = obj.get("@type")
            if isinstance(kinds, str):
                kinds = [kinds]
            if not isinstance(kinds, list) or not any(
                str(kind).lower() in {"newsarticle", "article"} for kind in kinds
            ):
                continue
            parsed = _parse_iso(obj.get("datePublished"))
            if parsed:
                return parsed
    return None


def rfc2822(value: dt.datetime) -> str:
    return email.utils.format_datetime(value.astimezone(dt.timezone.utc), usegmt=True)


def normalize(root: Path = ROOT, *, check: bool = False) -> dict[str, int]:
    feed = root / "feed.xml"
    articles = root / "articles"
    text = feed.read_text(encoding="utf-8")
    seen = changed = 0
    missing: list[str] = []

    def replace_item(match: re.Match[str]) -> str:
        nonlocal seen, changed
        block = match.group(1)
        link = LINK_RE.search(block)
        if not link:
            return block
        seen += 1
        slug = link.group(1)
        article = articles / f"{slug}.html"
        published = article_published_at(article) if article.exists() else None
        if not published:
            missing.append(slug)
            return block
        expected = rfc2822(published)
        pub = PUBDATE_RE.search(block)
        if not pub:
            missing.append(slug + " (pubDate absent)")
            return block
        current = pub.group(2).strip()
        if current == expected:
            return block
        changed += 1
        return PUBDATE_RE.sub(
            lambda m: f"{m.group(1)}{expected}{m.group(3)}", block, count=1
        )

    updated = ITEM_RE.sub(replace_item, text)
    if seen == 0 and "https://lesfaits.info/articles/" in text:
        raise RuntimeError("Entrées RSS article présentes mais format non reconnu")
    if missing:
        raise RuntimeError(
            f"{len(missing)} entrée(s) RSS sans datePublished exploitable : "
            + ", ".join(missing)
        )
    if check and changed:
        raise RuntimeError(f"feed.xml contient encore {changed} pubDate artificielle(s)")
    if not check and updated != text:
        feed.write_text(updated, encoding="utf-8")

    print(f"[RSS] {seen} entrée(s) contrôlée(s), {changed} pubDate corrigée(s).")
    return {"items": seen, "changed": changed, "missing": len(missing)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    normalize(args.root.resolve(), check=args.check)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
