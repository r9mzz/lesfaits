# -*- coding: utf-8 -*-
"""Répare les NewsArticle dont dateModified précède datePublished.

La réparation est volontairement conservatrice : elle ne touche qu'au JSON-LD
NewsArticle et ne modifie dateModified que lorsqu'il est absent, invalide ou
strictement antérieur à datePublished. Dans ce cas, dateModified est aligné sur
datePublished ; une dateModified postérieure reste intacte.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

JSONLD_RE = re.compile(
    r"(<script\b[^>]*type=([\"'])application/ld\+json\2[^>]*>)(.*?)(</script>)",
    re.I | re.S,
)


def _parse(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def repair_html(html: str) -> tuple[str, int]:
    repaired = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal repaired
        try:
            data = json.loads(match.group(3))
        except json.JSONDecodeError:
            return match.group(0)
        if not isinstance(data, dict) or data.get("@type") != "NewsArticle":
            return match.group(0)

        published = _parse(data.get("datePublished"))
        modified = _parse(data.get("dateModified"))
        if not published:
            return match.group(0)
        if modified is not None and modified >= published:
            return match.group(0)

        data["dateModified"] = str(data.get("datePublished"))
        rendered = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        repaired += 1
        return f"{match.group(1)}{rendered}{match.group(4)}"

    return JSONLD_RE.sub(repl, html), repaired


def run(site_dir: Path, *, check: bool = False) -> tuple[int, list[str]]:
    articles_dir = Path(site_dir) / "articles"
    changed = 0
    errors: list[str] = []
    for path in sorted(articles_dir.glob("*.html")):
        original = path.read_text(encoding="utf-8", errors="replace")
        updated, repaired = repair_html(original)
        if repaired:
            if check:
                errors.append(f"{path.name}: dateModified antérieur ou invalide")
            else:
                path.write_text(updated, encoding="utf-8")
                changed += 1
    return changed, errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site-dir", required=True, type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    changed, errors = run(args.site_dir, check=args.check)
    if errors:
        for error in errors:
            print(f"[DATE MODIFIED FAIL] {error}")
        return 1
    print(f"[DATE MODIFIED] {changed} article(s) réparé(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
