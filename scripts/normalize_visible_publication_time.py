#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Aligne l'heure humaine affichée avec ``NewsArticle.datePublished``.

Le JSON-LD est déjà la source de vérité machine du site. Pour les articles qui
possèdent une date+heure exacte avec fuseau, la balise ``<time>`` doit exposer
la même valeur dans son attribut ``datetime`` ET dans son texte visible.

Les archives dont le JSON-LD ne contient qu'un ``YYYY-MM-DD`` sont ignorées :
leur éventuelle heure humaine historique n'est pas assez fiable pour être
reconstruite et aucune heure n'est inventée.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import normalize_publication_metadata as publication

ROOT = Path(__file__).resolve().parent.parent
ARTICLES_DIR = ROOT / "articles"

MONTHS_FR = (
    "",
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

TIME_TAG_RE = re.compile(
    r'(<time\b[^>]*\bdatetime=")([^"]*)("[^>]*>)([^<]*)(</time>)',
    re.I,
)


def _visible_fr(value) -> str:
    return (
        f"{value.day} {MONTHS_FR[value.month]} {value.year}, "
        f"{value.hour:02d}h{value.minute:02d}"
    )


def normalize_file(
    path: Path,
    meta: publication.ArticleDates,
    *,
    check: bool,
) -> tuple[int, list[str]]:
    if meta.published_exact is None:
        return 0, []

    html = path.read_text(encoding="utf-8", errors="replace")
    match = TIME_TAG_RE.search(html)
    if not match:
        return 0, [
            f"{path.relative_to(ROOT)}: <time datetime> simple absent pour un article horodaté"
        ]

    expected_datetime = publication._iso(meta.published_exact)
    expected_visible = _visible_fr(meta.published_exact)
    current_datetime = match.group(2).strip()
    current_visible = match.group(4).strip()

    if current_datetime == expected_datetime and current_visible == expected_visible:
        return 0, []

    if check:
        return 0, [
            f"{path.relative_to(ROOT)}: time={current_datetime!r}/{current_visible!r}, "
            f"attendu {expected_datetime!r}/{expected_visible!r}"
        ]

    replacement = (
        match.group(1)
        + expected_datetime
        + match.group(3)
        + expected_visible
        + match.group(5)
    )
    updated = html[: match.start()] + replacement + html[match.end() :]
    path.write_text(updated, encoding="utf-8")
    return 1, []


def run(*, check: bool = False) -> tuple[int, list[str]]:
    # publication.ROOT/ARTICLES_DIR peuvent être redirigés par les tests.
    global ROOT, ARTICLES_DIR
    ROOT = publication.ROOT
    ARTICLES_DIR = publication.ARTICLES_DIR

    changed = 0
    failures: list[str] = []
    for slug, meta in publication.collect_dates().items():
        path = ARTICLES_DIR / f"{slug}.html"
        count, errors = normalize_file(path, meta, check=check)
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
        print(f"[VISIBLE TIME FAIL] {exc}", file=sys.stderr)
        return 1
    if failures:
        for failure in failures[:40]:
            print(f"[VISIBLE TIME FAIL] {failure}", file=sys.stderr)
        if len(failures) > 40:
            print(f"[VISIBLE TIME FAIL] +{len(failures)-40} autre(s)", file=sys.stderr)
        return 1
    mode = "vérifiées" if args.check else "normalisées"
    print(f"[VISIBLE TIME OK] heures visibles {mode}; {changed} correction(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
