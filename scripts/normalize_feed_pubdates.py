#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Normalise les dates du RSS à partir des vraies métadonnées de publication.

Le générateur historique utilisait l'heure du rebuild pour chaque ``pubDate``,
ce qui faisait remonter artificiellement tout le flux à chaque déploiement. La
source de vérité ordinaire des articles est le JSON-LD NewsArticle de la page
publique. Les rares heures publiques historiquement perdues sont réparées avant
la normalisation via ``repair_publication_time_overrides``.

``lastBuildDate`` n'est avancé que lorsque l'ensemble des articles publiés a
réellement changé depuis ``HEAD`` : ajout, retrait ou renommage. Une simple
réécriture technique d'un HTML article existant pendant un rebuild ne constitue
pas une publication et ne doit donc pas rafraîchir le flux. Sur un run à zéro
article, la valeur est restaurée depuis le ``feed.xml`` de ``HEAD``. Hors d'un
checkout Git exploitable, on conserve le comportement historique et on met
``lastBuildDate`` à jour.
"""
from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import json
import re
import subprocess
from pathlib import Path

import repair_publication_time_overrides as canonical_times

ROOT = Path(__file__).resolve().parent.parent

ITEM_RE = re.compile(r"(<item>.*?</item>)", re.I | re.S)
LINK_RE = re.compile(
    r"<link>https://lesfaits\.info/articles/([^<]+)\.html</link>", re.I
)
PUBDATE_RE = re.compile(r"(<pubDate>)(.*?)(</pubDate>)", re.I | re.S)
LAST_BUILD_RE = re.compile(
    r"(<lastBuildDate>)(.*?)(</lastBuildDate>)", re.I | re.S
)
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


def _articles_changed_since_head(root: Path) -> bool | None:
    """Détecte une vraie variation de l'ensemble ``articles/*.html``.

    Un rebuild peut marquer des articles existants ``M`` dans le worktree sans
    créer, retirer ni renommer aucune publication. Ce bruit ne doit pas avancer
    ``lastBuildDate``. Les statuts qui changent l'ensemble publié (``??``, A, D,
    R ou C) restent en revanche significatifs. Un état Git inexploitable renvoie
    ``None`` pour conserver le repli historique du caller.
    """
    try:
        proc = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "--",
                "articles/",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None

    for line in proc.stdout.splitlines():
        if len(line) < 3:
            continue
        status = line[:2]
        # Fichier nouveau non suivi.
        if status == "??":
            return True
        # Ajout / retrait / renommage / copie dans l'index ou le worktree.
        # Les simples M (rebuild technique d'un fichier déjà publié) sont
        # volontairement ignorés : ils ne changent pas l'ensemble des URLs RSS.
        if any(flag in status for flag in ("A", "D", "R", "C")):
            return True
    return False


def _head_last_build_date(root: Path) -> str | None:
    """Lit le ``lastBuildDate`` réellement versionné dans ``HEAD:feed.xml``."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "show", "HEAD:feed.xml"],
            text=True,
            capture_output=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    match = LAST_BUILD_RE.search(proc.stdout)
    if not match:
        return None
    value = match.group(2).strip()
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed is None or parsed.utcoffset() != dt.timedelta(0):
        return None
    return value


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


def normalize(
    root: Path = ROOT,
    *,
    check: bool = False,
    build_time: dt.datetime | None = None,
    update_last_build: bool | None = None,
) -> dict[str, int]:
    if not check:
        canonical_times.apply(root)

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

    last_build = LAST_BUILD_RE.search(updated)
    if not last_build:
        raise RuntimeError("feed.xml ne contient pas de lastBuildDate")

    build_changed = 0
    current_build = last_build.group(2).strip()
    try:
        parsed_build = email.utils.parsedate_to_datetime(current_build)
    except (TypeError, ValueError):
        parsed_build = None

    if check:
        if parsed_build is None or parsed_build.utcoffset() != dt.timedelta(0):
            raise RuntimeError("lastBuildDate n'est pas une date UTC RFC 2822 valide")
    else:
        if update_last_build is None:
            git_change = _articles_changed_since_head(root)
            update_last_build = True if git_change is None else git_change

        if update_last_build:
            instant = build_time or dt.datetime.now(dt.timezone.utc)
            if instant.tzinfo is None:
                instant = instant.replace(tzinfo=dt.timezone.utc)
            expected_build = rfc2822(instant)
            if current_build != expected_build:
                build_changed = 1
                updated = LAST_BUILD_RE.sub(
                    lambda m: f"{m.group(1)}{expected_build}{m.group(3)}",
                    updated,
                    count=1,
                )
        else:
            head_build = _head_last_build_date(root)
            if head_build is not None:
                if current_build != head_build:
                    build_changed = 1
                    updated = LAST_BUILD_RE.sub(
                        lambda m: f"{m.group(1)}{head_build}{m.group(3)}",
                        updated,
                        count=1,
                    )
            elif parsed_build is None or parsed_build.utcoffset() != dt.timedelta(0):
                raise RuntimeError("lastBuildDate n'est pas une date UTC RFC 2822 valide")

    if check and changed:
        raise RuntimeError(f"feed.xml contient encore {changed} pubDate artificielle(s)")
    if not check and updated != text:
        feed.write_text(updated, encoding="utf-8")

    print(
        f"[RSS] {seen} entrée(s) contrôlée(s), {changed} pubDate corrigée(s), "
        f"{build_changed} lastBuildDate corrigée(s)."
    )
    return {
        "items": seen,
        "changed": changed,
        "build_changed": build_changed,
        "missing": len(missing),
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
