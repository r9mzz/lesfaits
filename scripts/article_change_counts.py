# -*- coding: utf-8 -*-
"""Compte les vrais ajouts, modifications et retraits d'articles HTML dans Git."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def count_article_changes(repo: Path, *, cached: bool = True, base: str | None = None, head: str | None = None) -> dict[str, int]:
    repo = Path(repo).resolve()
    command = ["git", "-C", str(repo), "diff", "--name-status", "--diff-filter=AMD"]
    if cached:
        command.append("--cached")
    elif base and head:
        command.extend([base, head])
    elif base:
        command.append(base)
    command.extend(["--", "articles/"])
    output = subprocess.run(
        command,
        check=True,
        text=True,
        capture_output=True,
    ).stdout

    counts = {"added": 0, "modified": 0, "deleted": 0}
    status_map = {"A": "added", "M": "modified", "D": "deleted"}
    for raw in output.splitlines():
        parts = raw.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0][:1]
        path = parts[-1]
        if status in status_map and path.startswith("articles/") and path.endswith(".html"):
            counts[status_map[status]] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--cached", action="store_true")
    parser.add_argument("--base")
    parser.add_argument("--head")
    parser.add_argument("--shell", action="store_true")
    args = parser.parse_args()

    cached = args.cached or not (args.base or args.head)
    counts = count_article_changes(
        args.repo,
        cached=cached,
        base=args.base,
        head=args.head,
    )
    if args.shell:
        print(f"NB_NEW={counts['added']}")
        print(f"NB_MOD={counts['modified']}")
        print(f"NB_DEL={counts['deleted']}")
    else:
        print(json.dumps(counts, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
