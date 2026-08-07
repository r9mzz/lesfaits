#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Réaligne les compteurs de sources affichés par les anciens templates.

Certaines pages legacy ont conservé un bloc SOURCES correct mais une ligne
"Pourquoi cet article" figée à "0 sources distinctes". Le nombre est dérivé
uniquement des domaines HTTP(S) réellement présents dans le bloc SOURCES ;
aucune source n'est ajoutée, supprimée ou inventée.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
ARTICLES_DIR = ROOT / "articles"

SOURCES_RE = re.compile(
    r'<(?:section|div)\b[^>]*class=["\'][^"\']*\bsources\b[^"\']*["\'][^>]*>'
    r'(.*?)</(?:section|div)>',
    re.I | re.S,
)
HREF_RE = re.compile(r'<a\b[^>]*href=["\']([^"\']+)["\']', re.I)
DISTINCT_RE = re.compile(
    r'(<strong>Sources\s*:</strong>\s*)(\d+)\s+sources?\s+distinctes?',
    re.I,
)


def _hosts(block: str) -> set[str]:
    hosts: set[str] = set()
    for url in HREF_RE.findall(block):
        if not url.startswith(("http://", "https://")):
            continue
        host = (urlparse(url).hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        if host:
            hosts.add(host)
    return hosts


def normalize_file(path: Path, *, check: bool) -> tuple[int, list[str]]:
    html = path.read_text(encoding="utf-8", errors="replace")
    source_match = SOURCES_RE.search(html)
    distinct_match = DISTINCT_RE.search(html)
    if not source_match or not distinct_match:
        return 0, []

    expected = len(_hosts(source_match.group(1)))
    current = int(distinct_match.group(2))
    if current == expected:
        return 0, []
    if check:
        return 0, [
            f"{path.relative_to(ROOT)}: {current} source(s) distincte(s) affichée(s), "
            f"{expected} domaine(s) réellement cité(s)"
        ]

    label = "source distincte" if expected == 1 else "sources distinctes"
    replacement = distinct_match.group(1) + f"{expected} {label}"
    html = html[: distinct_match.start()] + replacement + html[distinct_match.end() :]
    path.write_text(html, encoding="utf-8")
    return 1, []


def run(*, check: bool = False) -> tuple[int, list[str]]:
    changed = 0
    failures: list[str] = []
    for path in sorted(ARTICLES_DIR.glob("*.html")):
        count, errors = normalize_file(path, check=check)
        changed += count
        failures.extend(errors)
    return changed, failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    changed, failures = run(check=args.check)
    if failures:
        for failure in failures[:30]:
            print(f"[SOURCE METADATA FAIL] {failure}", file=sys.stderr)
        if len(failures) > 30:
            print(
                f"[SOURCE METADATA FAIL] +{len(failures)-30} autre(s)",
                file=sys.stderr,
            )
        return 1
    mode = "vérifiées" if args.check else "normalisées"
    print(f"[SOURCE METADATA OK] sources {mode}; {changed} correction(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
