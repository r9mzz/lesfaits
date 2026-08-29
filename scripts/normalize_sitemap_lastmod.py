#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Normalise les ``lastmod`` du sitemap après un rebuild du site.

Le générateur historique applique la date du rebuild à tout le corpus. Pour
chaque vraie page article, ce script utilise `dateModified` puis
`datePublished` du JSON-LD NewsArticle ; les anciennes pages sans JSON-LD
peuvent utiliser la date de leur balise `<time datetime>`. Les stubs de
redirection `noindex` sont retirés du sitemap au lieu d'être présentés comme de
vraies pages indexables.

Pour les URL hors ``/articles/`` (accueil, archive, pages statiques et
catégories), le rebuild peut aussi avancer artificiellement ``lastmod`` alors
que le fichier HTML correspondant n'a pas changé. Avant le premier commit
public, la référence est HEAD. Lors d'une seconde normalisation exécutée après
ce commit, la référence devient HEAD~1 afin de comparer au véritable état
public précédent et non au sitemap fraîchement généré.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent

URL_RE = re.compile(
    r"\s*<url><loc>https://lesfaits\.info/articles/([^<]+)\.html</loc>"
    r"<lastmod>([^<]+)</lastmod>(.*?)</url>",
    re.I | re.S,
)
ALL_URL_RE = re.compile(
    r"(<url><loc>(https://lesfaits\.info/[^<]*)</loc><lastmod>)([^<]+)(</lastmod>.*?</url>)",
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

    match = TIME_RE.search(html)
    return (match.group(2) if match else None), False


def _git_show(root: Path, ref: str, path: str) -> str | None:
    proc = subprocess.run(
        ["git", "-C", str(root), "show", f"{ref}:{path}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return proc.stdout if proc.returncode == 0 and proc.stdout else None


def _git_path_unchanged(root: Path, ref: str, rel: str) -> bool | None:
    proc = subprocess.run(
        ["git", "-C", str(root), "diff", "--quiet", ref, "--", rel],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if proc.returncode == 0:
        return True
    if proc.returncode == 1:
        return False
    return None


def _baseline_ref(root: Path) -> str:
    """Choisit l'état public de référence pour les pages hors articles.

    Si sitemap.xml diffère de HEAD, on est avant le commit public et HEAD est
    bien l'état servi précédent. Si le sitemap est déjà commité et HEAD~1
    existe, on est dans la normalisation post-commit : HEAD est alors le
    rebuild courant et il faut comparer au véritable état public précédent.
    """
    if _git_path_unchanged(root, "HEAD", "sitemap.xml") is not True:
        return "HEAD"
    if _git_show(root, "HEAD~1", "sitemap.xml") is not None:
        return "HEAD~1"
    return "HEAD"


def _committed_sitemap(root: Path, ref: str) -> str | None:
    return _git_show(root, ref, "sitemap.xml")


def _page_for_url(root: Path, url: str) -> Path | None:
    parsed = urlparse(url)
    if parsed.netloc.lower() != "lesfaits.info":
        return None
    rel = unquote(parsed.path).lstrip("/") or "index.html"
    if rel.startswith("articles/") or rel.endswith("/") or ".." in Path(rel).parts:
        return None
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _unchanged_from_ref(root: Path, page: Path, ref: str) -> bool | None:
    try:
        rel = page.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None
    return _git_path_unchanged(root, ref, rel)


def _lastmods_by_url(text: str) -> dict[str, str]:
    return {match.group(2): match.group(3) for match in ALL_URL_RE.finditer(text)}


def _restore_unchanged_non_article_lastmods(root: Path, text: str) -> tuple[str, int, int]:
    """Restaure les lastmod du véritable état public précédent."""
    ref = _baseline_ref(root)
    committed = _committed_sitemap(root, ref)
    if not committed:
        return text, 0, 0
    previous = _lastmods_by_url(committed)
    seen = changed = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal seen, changed
        prefix, url, current, suffix = match.groups()
        if urlparse(url).path.startswith("/articles/"):
            return match.group(0)
        page = _page_for_url(root, url)
        if not page:
            return match.group(0)
        seen += 1
        if _unchanged_from_ref(root, page, ref) is not True:
            return match.group(0)
        old = previous.get(url)
        if not old or old == current:
            return match.group(0)
        changed += 1
        return f"{prefix}{old}{suffix}"

    return ALL_URL_RE.sub(replace, text), seen, changed


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
    if seen == 0 and "https://lesfaits.info/articles/" in text:
        raise RuntimeError("Entrées article présentes mais format sitemap non reconnu")
    if missing_slugs:
        raise RuntimeError(
            f"{len(missing_slugs)} vraie(s) page(s) article sans date exploitable : "
            + ", ".join(missing_slugs)
        )

    updated, non_articles, non_article_changed = _restore_unchanged_non_article_lastmods(
        root, updated
    )
    if check and (changed or removed or non_article_changed):
        raise RuntimeError(
            f"sitemap.xml encore non normalisé: {changed} lastmod article à corriger, "
            f"{removed} redirection(s) à retirer, {non_article_changed} lastmod hors article à restaurer"
        )
    if not check and updated != text:
        sitemap.write_text(updated, encoding="utf-8")

    print(
        f"[SITEMAP] {seen} entrée(s) article contrôlée(s), {changed} lastmod article corrigé(s), "
        f"{removed} redirection(s) retirée(s), {len(missing_slugs)} date(s) manquante(s), "
        f"{non_articles} page(s) hors article contrôlée(s), {non_article_changed} lastmod restauré(s)."
    )
    return {
        "articles": seen,
        "changed": changed,
        "removed": removed,
        "missing": len(missing_slugs),
        "non_articles": non_articles,
        "non_article_changed": non_article_changed,
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
