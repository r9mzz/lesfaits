#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Remplace les lastmod artificiels des articles par leur dateModified réelle.

Le générateur historique met la date du rebuild sur toutes les URL du sitemap.
Pour les pages article, on utilise plutôt le JSON-LD NewsArticle déjà publié :
`dateModified` en priorité, puis `datePublished` en secours. Ainsi un rebuild
sans changement éditorial ne fait plus croire aux moteurs que tout le corpus a
été modifié aujourd'hui.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITEMAP = ROOT / "sitemap.xml"
ARTICLES = ROOT / "articles"

URL_RE = re.compile(
    r"(<url><loc>https://lesfaits\.info/articles/([^<]+)\.html</loc><lastmod>)([^<]+)(</lastmod>)"
)
JSON_LD_RE = re.compile(
    r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.S,
)


def _iso_date(value: object) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        m = re.match(r"^(\d{4}-\d{2}-\d{2})", raw)
        return m.group(1) if m else None
    return parsed.date().isoformat()


def article_lastmod(path: Path) -> str | None:
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
            return _iso_date(obj.get("dateModified")) or _iso_date(obj.get("datePublished"))
    return None


def normalize(root: Path = ROOT, *, check: bool = False) -> dict[str, int]:
    sitemap = root / "sitemap.xml"
    articles_dir = root / "articles"
    text = sitemap.read_text(encoding="utf-8")
    seen = changed = missing = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal seen, changed, missing
        seen += 1
        slug = match.group(2)
        article = articles_dir / f"{slug}.html"
        real = article_lastmod(article) if article.exists() else None
        if not real:
            missing += 1
            return match.group(0)
        current = match.group(3)
        if current != real:
            changed += 1
            return f"{match.group(1)}{real}{match.group(4)}"
        return match.group(0)

    updated = URL_RE.sub(replace, text)
    if seen == 0:
        raise RuntimeError("Aucune URL article trouvée dans sitemap.xml")
    if missing:
        raise RuntimeError(
            f"{missing} article(s) du sitemap sans dateModified/datePublished exploitable"
        )
    if check and changed:
        raise RuntimeError(f"sitemap.xml contient encore {changed} lastmod article artificiel(s)")
    if not check and updated != text:
        sitemap.write_text(updated, encoding="utf-8")

    print(
        f"[SITEMAP] {seen} article(s) contrôlé(s), {changed} lastmod corrigé(s), "
        f"{missing} date(s) manquante(s)."
    )
    return {"articles": seen, "changed": changed, "missing": missing}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    normalize(args.root.resolve(), check=args.check)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
