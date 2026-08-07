#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Aligne l'indexation des pages article sur ``data/articles.json``.

Le manifeste ``data/articles.json`` alimente l'accueil, les catégories,
l'archive, la recherche et le sitemap. Une vieille page NewsArticle restée sur
disque mais absente de ce manifeste ne doit donc pas rester ``index, follow`` :
elle devient ``noindex, follow`` sans être supprimée, afin de conserver son URL
historique tout en évitant un corpus Google différent du corpus visible.

Les articles actifs ne sont jamais modifiés ici ; une éventuelle incohérence
sur un actif est bloquée par ``check_site_integrity.py`` plutôt que corrigée à
l'aveugle.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARTICLES_DIR = ROOT / "articles"
MANIFEST = ROOT / "data" / "articles.json"
RETIREMENTS = ROOT / "data" / "retirements.json"

NEWS_RE = re.compile(
    r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>.*?'
    r'["\']@type["\']\s*:\s*["\']NewsArticle["\'].*?</script>',
    re.I | re.S,
)
ROBOTS_RE = re.compile(
    r'(<meta\b[^>]*name=["\']robots["\'][^>]*content=["\'])([^"\']*)(["\'][^>]*>)',
    re.I,
)
HEAD_END_RE = re.compile(r'</head\s*>', re.I)


def _load_list(path: Path) -> list[dict]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    if not isinstance(value, list):
        raise RuntimeError(f"{path.relative_to(ROOT)} doit contenir une liste")
    return [item for item in value if isinstance(item, dict)]


def active_slugs() -> set[str]:
    return {
        str(item.get("slug", "")).strip()
        for item in _load_list(MANIFEST)
        if str(item.get("slug", "")).strip()
    }


def retired_slugs() -> set[str]:
    return {
        str(item.get("slug", "")).strip()
        for item in _load_list(RETIREMENTS)
        if str(item.get("slug", "")).strip()
    }


def _is_news_article(html: str) -> bool:
    return bool(NEWS_RE.search(html))


def _robots_content(html: str) -> str | None:
    match = ROBOTS_RE.search(html)
    return match.group(2).strip() if match else None


def _has_noindex(html: str) -> bool:
    content = (_robots_content(html) or "").lower()
    return "noindex" in {token.strip() for token in content.split(",")}


def _set_noindex(html: str) -> str:
    if ROBOTS_RE.search(html):
        return ROBOTS_RE.sub(
            lambda m: m.group(1) + "noindex, follow" + m.group(3),
            html,
            count=1,
        )
    match = HEAD_END_RE.search(html)
    if not match:
        raise RuntimeError("</head> absent")
    tag = '  <meta name="robots" content="noindex, follow"/>\n'
    return html[: match.start()] + tag + html[match.start() :]


def run(*, check: bool = False) -> tuple[int, list[str]]:
    active = active_slugs()
    retired = retired_slugs()
    overlap = active & retired
    if overlap:
        return 0, [
            "slug(s) à la fois actif(s) et retiré(s) : " + ", ".join(sorted(overlap)[:10])
        ]

    changed = 0
    failures: list[str] = []
    for path in sorted(ARTICLES_DIR.glob("*.html")):
        html = path.read_text(encoding="utf-8", errors="replace")
        if not _is_news_article(html):
            continue
        slug = path.stem
        if slug in active:
            continue
        # Les stubs de retraite ne sont normalement plus des NewsArticle. Si
        # une ancienne version complète subsiste, noindex est précisément le
        # comportement sûr attendu.
        if _has_noindex(html):
            continue
        if check:
            failures.append(
                f"{path.relative_to(ROOT)}: NewsArticle hors manifeste encore indexable"
            )
            continue
        try:
            updated = _set_noindex(html)
        except RuntimeError as exc:
            failures.append(f"{path.relative_to(ROOT)}: {exc}")
            continue
        path.write_text(updated, encoding="utf-8")
        changed += 1

    return changed, failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        changed, failures = run(check=args.check)
    except Exception as exc:
        print(f"[CORPUS INDEX FAIL] {exc}", file=sys.stderr)
        return 1
    if failures:
        for failure in failures[:40]:
            print(f"[CORPUS INDEX FAIL] {failure}", file=sys.stderr)
        if len(failures) > 40:
            print(f"[CORPUS INDEX FAIL] +{len(failures)-40} autre(s)", file=sys.stderr)
        return 1
    mode = "vérifié" if args.check else "normalisé"
    print(f"[CORPUS INDEX OK] corpus {mode}; {changed} page(s) corrigée(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
