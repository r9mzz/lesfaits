#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Normalise les lastmod article du sitemap à partir des métadonnées publiées.

Le générateur historique applique la date du rebuild à tout le corpus. Pour
chaque vraie page article, ce script utilise `dateModified` puis
`datePublished` du JSON-LD NewsArticle ; les anciennes pages sans JSON-LD
peuvent utiliser la date de leur balise `<time datetime>`. Les stubs de
redirection `noindex` sont retirés du sitemap au lieu d'être présentés comme de
vraies pages indexables.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Capture l'entrée complète afin de pouvoir supprimer proprement une redirection.
URL_RE = re.compile(
    r"\s*<url><loc>https://lesfaits\.info/articles/([^<]+)\.html</loc>"
    r"<lastmod>([^<]+)</lastmod>(.*?)</url>",
    re.I | re.S,
)
JSON_LD_RE = re.compile(
    r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.S,
)
TIME_RE = re.compile(
    r'<time\b[^>]*\bdatetime=(["\'])(\d{4}-\d{2}-\d{2})(?:T[^"\']*)?\1',
    re.I,
)
NOINDEX_RE = re.compile(r'<meta\b[^>]*\bname=(["\'])robots\1[^>]*\bcontent=(["\'])[^"\']*noindex', re.I)
REDIRECT_RE = re.compile(
    r'http-equiv=(["\'])refresh\1|window\.location(?:\.replace)?\s*\(|\bredirection\b|\bconsolid',
    re.I,
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


def article_metadata(path: Path) -> tuple[str | None, bool]:
    """Retourne `(lastmod, est_redirection_noindex)` pour une page article."""
    html = path.read_text(encoding="utf-8", errors="replace")
    is_redirect = bool(NOINDEX_RE.search(html) and REDIRECT_RE.search(html))
    if is_redirect:
        return None, True

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
            date = _iso_date(obj.get("dateModified")) or _iso_date(obj.get("datePublished"))
            if date:
                return date, False

    # Compatibilité avec quelques anciennes vraies pages publiées avant le JSON-LD.
    match = TIME_RE.search(html)
    return (match.group(2) if match else None), False


def normalize(root: Path = ROOT, *, check: bool = False) -> dict[str, int]:
    sitemap = root / "sitemap.xml"
    articles_dir = root / "articles"
    text = sitemap.read_text(encoding="utf-8")
    seen = changed = removed = 0
    missing_slugs: list[str] = []

    def replace(match: re.Match[str]) -> str:
        nonlocal seen, changed, removed
        seen += 1
        slug, current, tail = match.group(1), match.group(2), match.group(3)
        article = articles_dir / f"{slug}.html"
        if not article.exists():
            missing_slugs.append(slug + " (fichier absent)")
            return match.group(0)

        real, is_redirect = article_metadata(article)
        if is_redirect:
            removed += 1
            return ""
        if not real:
            missing_slugs.append(slug)
            return match.group(0)
        if current == real:
            return match.group(0)

        changed += 1
        leading = "\n  " if match.group(0).startswith("\n") else ""
        return (
            f"{leading}<url><loc>https://lesfaits.info/articles/{slug}.html</loc>"
            f"<lastmod>{real}</lastmod>{tail}</url>"
        )

    updated = URL_RE.sub(replace, text)
    # Si le sitemap contient encore une URL /articles/ mais que la regexp n'en
    # reconnaît aucune, c'est un changement de format qu'il faut bloquer. En
    # revanche un sitemap sans aucun article est valide (par exemple après le
    # retrait du seul stub de redirection dans un test ou un corpus vide).
    if seen == 0 and "https://lesfaits.info/articles/" in text:
        raise RuntimeError("Entrées article présentes mais format sitemap non reconnu")
    if missing_slugs:
        raise RuntimeError(
            f"{len(missing_slugs)} vraie(s) page(s) article sans date exploitable : "
            + ", ".join(missing_slugs)
        )
    if check and (changed or removed):
        raise RuntimeError(
            f"sitemap.xml encore non normalisé: {changed} lastmod à corriger, "
            f"{removed} redirection(s) à retirer"
        )
    if not check and updated != text:
        sitemap.write_text(updated, encoding="utf-8")

    print(
        f"[SITEMAP] {seen} entrée(s) article contrôlée(s), {changed} lastmod corrigé(s), "
        f"{removed} redirection(s) retirée(s), {len(missing_slugs)} date(s) manquante(s)."
    )
    return {
        "articles": seen,
        "changed": changed,
        "removed": removed,
        "missing": len(missing_slugs),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    normalize(args.root.resolve(), check=args.check)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
