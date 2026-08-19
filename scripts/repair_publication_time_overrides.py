#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Répare les rares heures publiques perdues par les rebuilds historiques.

Ce registre est volontairement minuscule et fondé sur un fait observable dans
le dépôt public : le commit qui a *créé* l'article est l'instant canonique de
mise en ligne. Il sert uniquement lorsqu'un ancien rebuild a déjà perdu cette
heure dans ``data/articles.json`` et dans le HTML précédent, cas que la
restauration HEAD~1 ne peut plus résoudre.
"""
from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import json
import re
from pathlib import Path
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")

# Premier ajout public : lesfaits-site@683eea3972d49af8fb941ab6efd3fa461da0180b
# GitHub : 2026-08-14T15:40:11+02:00.
OVERRIDES = {
    "inflation-france-juillet-2026": "2026-08-14T15:40:11+02:00",
}

MONTHS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]
TIME_RE = re.compile(r"<time\b[^>]*>.*?</time>", re.I | re.S)
JSONLD_RE = re.compile(
    r"(<script\b[^>]*type=([\"'])application/ld\+json\2[^>]*>)(.*?)(</script>)",
    re.I | re.S,
)
PUBDATE_RE = re.compile(r"(<pubDate>)(.*?)(</pubDate>)", re.I | re.S)
ITEM_RE = re.compile(r"(<item>.*?</item>)", re.I | re.S)


def _display(iso: str) -> str:
    value = dt.datetime.fromisoformat(iso).astimezone(PARIS)
    return f"{value.day} {MONTHS[value.month - 1]} {value.year}, {value.strftime('%Hh%M')}"


def _rfc2822(iso: str) -> str:
    value = dt.datetime.fromisoformat(iso).astimezone(dt.timezone.utc)
    return email.utils.format_datetime(value, usegmt=True)


def _patch_json_index(path: Path, slug: str, display: str, iso: str) -> bool:
    if not path.exists():
        return False
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise RuntimeError(f"{path}: index JSON invalide")
    changed = False
    found = False
    for item in data:
        if str(item.get("slug") or "") != slug:
            continue
        found = True
        if item.get("date") != display:
            item["date"] = display
            changed = True
        if item.get("date_iso") != iso:
            item["date_iso"] = iso
            changed = True
    if not found:
        raise RuntimeError(f"{path}: slug canonique absent: {slug}")
    if changed:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed


def _patch_article(path: Path, display: str, iso: str) -> bool:
    text = path.read_text(encoding="utf-8", errors="replace")
    updated = TIME_RE.sub(f'<time datetime="{iso}">{display}</time>', text, count=1)

    def repl(match: re.Match[str]) -> str:
        try:
            data = json.loads(match.group(3))
        except json.JSONDecodeError:
            return match.group(0)
        if not isinstance(data, dict) or data.get("@type") != "NewsArticle":
            return match.group(0)
        data["datePublished"] = iso
        modified = str(data.get("dateModified") or "")
        try:
            modified_dt = dt.datetime.fromisoformat(modified.replace("Z", "+00:00"))
            published_dt = dt.datetime.fromisoformat(iso)
        except ValueError:
            modified_dt = None
            published_dt = dt.datetime.fromisoformat(iso)
        if modified_dt is None or modified_dt < published_dt:
            data["dateModified"] = iso
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        return f"{match.group(1)}{payload}{match.group(4)}"

    updated = JSONLD_RE.sub(repl, updated)
    if updated != text:
        path.write_text(updated, encoding="utf-8")
        return True
    return False


def _patch_cards(root: Path, slug: str, display: str) -> int:
    changed = 0
    anchor_re = re.compile(
        rf"(<a\b[^>]*href=([\"'])[^\"']*articles/{re.escape(slug)}\.html\2[^>]*>.*?</a>)",
        re.I | re.S,
    )
    date_re = re.compile(
        r"\b\d{1,2}\s+(?:janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+\d{4},\s+\d{2}h\d{2}\b",
        re.I,
    )
    paths = [p for p in root.glob("*.html") if p.is_file()]
    paths += [p for p in (root / "categories").glob("*.html") if p.is_file()]
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        updated = anchor_re.sub(lambda m: date_re.sub(display, m.group(1), count=1), text)
        if updated != text:
            path.write_text(updated, encoding="utf-8")
            changed += 1
    return changed


def _patch_feed(path: Path, slug: str, iso: str) -> bool:
    text = path.read_text(encoding="utf-8")
    expected = _rfc2822(iso)
    changed = False

    def repl(match: re.Match[str]) -> str:
        nonlocal changed
        block = match.group(1)
        if f"/articles/{slug}.html" not in block:
            return block
        pub = PUBDATE_RE.search(block)
        if not pub:
            raise RuntimeError(f"feed.xml: pubDate absent pour {slug}")
        if pub.group(2).strip() == expected:
            return block
        changed = True
        return PUBDATE_RE.sub(lambda m: f"{m.group(1)}{expected}{m.group(3)}", block, count=1)

    updated = ITEM_RE.sub(repl, text)
    if changed:
        path.write_text(updated, encoding="utf-8")
    return changed


def apply(root: Path, *, check: bool = False) -> dict[str, int]:
    root = Path(root).resolve()
    changed = 0
    for slug, iso in OVERRIDES.items():
        display = _display(iso)
        article = root / "articles" / f"{slug}.html"
        if not article.exists():
            raise RuntimeError(f"article canonique absent: {slug}")
        if not check:
            changed += int(_patch_json_index(root / "data" / "articles.json", slug, display, iso))
            changed += int(_patch_json_index(root / "data" / "search.json", slug, display, iso))
            changed += int(_patch_article(article, display, iso))
            changed += _patch_cards(root, slug, display)
            changed += int(_patch_feed(root / "feed.xml", slug, iso))

        article_text = article.read_text(encoding="utf-8", errors="replace")
        if f'<time datetime="{iso}">{display}</time>' not in article_text:
            raise RuntimeError(f"{slug}: balise time non canonique")
        if f'"datePublished":"{iso}"' not in article_text:
            raise RuntimeError(f"{slug}: JSON-LD datePublished non canonique")
        for index_name in ("articles.json", "search.json"):
            data = json.loads((root / "data" / index_name).read_text(encoding="utf-8"))
            item = next((x for x in data if x.get("slug") == slug), None)
            if not item or item.get("date") != display or item.get("date_iso") != iso:
                raise RuntimeError(f"{slug}: {index_name} non canonique")
        feed = (root / "feed.xml").read_text(encoding="utf-8")
        item_match = next((m.group(1) for m in ITEM_RE.finditer(feed) if f"/articles/{slug}.html" in m.group(1)), "")
        if _rfc2822(iso) not in item_match:
            raise RuntimeError(f"{slug}: pubDate RSS non canonique")

    print(f"[HEURE CANONIQUE] {len(OVERRIDES)} article(s) contrôlé(s), {changed} fichier(s) corrigé(s).")
    return {"overrides": len(OVERRIDES), "changed": changed}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    apply(args.root, check=args.check)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
