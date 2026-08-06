# -*- coding: utf-8 -*-
"""Horodate les articles avec l'heure réelle du déploiement public.

Le dépôt source enregistre l'heure de génération. Le dépôt public est la vérité
sur l'heure d'apparition réelle : après chaque déploiement, ce script restaure
les heures déjà publiées depuis le commit public précédent et attribue aux seuls
nouveaux articles l'heure du commit de déploiement.

Il met à jour de façon cohérente :
- data/articles.json et data/search.json ;
- la balise <time> et le JSON-LD NewsArticle de chaque article ;
- les cartes qui affichent la date dans les pages HTML ;
- les pubDate du flux RSS.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

PARIS = ZoneInfo("Europe/Paris")
MONTHS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]
DATE_RE = re.compile(
    r"\b\d{1,2}\s+(?:janvier|février|mars|avril|mai|juin|juillet|août|"
    r"septembre|octobre|novembre|décembre)\s+\d{4},\s+\d{2}h\d{2}\b",
    re.I,
)
TIME_RE = re.compile(r"<time\b[^>]*datetime=([\"'])[^\"']*\1[^>]*>.*?</time>", re.I | re.S)
JSONLD_RE = re.compile(
    r"(<script\b[^>]*type=([\"'])application/ld\+json\2[^>]*>)(.*?)(</script>)",
    re.I | re.S,
)


def _run_git(site: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", "-C", str(site), *args],
        check=check,
        text=True,
        capture_output=True,
    )
    return proc.stdout


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _previous_json(site: Path, ref: str, path: str, default):
    try:
        raw = _run_git(site, "show", f"{ref}:{path}")
        return json.loads(raw)
    except Exception:
        return default


def _previous_text(site: Path, ref: str, path: str) -> str:
    try:
        return _run_git(site, "show", f"{ref}:{path}")
    except Exception:
        return ""


def _parse_datetime(value: str | None) -> datetime | None:
    value = str(value or "").strip()
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=PARIS)
    return dt.astimezone(PARIS)


def _display_date(dt: datetime) -> str:
    dt = dt.astimezone(PARIS)
    return f"{dt.day} {MONTHS[dt.month - 1]} {dt.year}, {dt.strftime('%Hh%M')}"


def _iso_date(dt: datetime) -> str:
    return dt.astimezone(PARIS).isoformat(timespec="seconds")


def _extract_news_date(html: str) -> str:
    for match in JSONLD_RE.finditer(html or ""):
        try:
            data = json.loads(match.group(3))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "NewsArticle":
            return str(data.get("datePublished") or "")
    return ""


def _extract_visible_date(html: str) -> str:
    match = TIME_RE.search(html or "")
    if not match:
        return ""
    text = re.sub(r"<[^>]+>", "", match.group(0))
    return re.sub(r"\s+", " ", text).strip()


def _added_article_slugs(site: Path, previous_ref: str) -> set[str]:
    try:
        output = _run_git(
            site, "diff", "--name-only", "--diff-filter=A",
            previous_ref, "HEAD", "--", "articles/*.html",
        )
    except Exception:
        return set()
    return {
        Path(line.strip()).stem
        for line in output.splitlines()
        if line.strip().startswith("articles/") and line.strip().endswith(".html")
    }


def _previous_publication_map(site: Path, previous_ref: str) -> dict[str, dict[str, str]]:
    previous = _previous_json(site, previous_ref, "data/articles.json", [])
    result: dict[str, dict[str, str]] = {}
    for item in previous if isinstance(previous, list) else []:
        slug = str(item.get("slug") or "")
        if not slug:
            continue
        display = str(item.get("date") or "")
        iso = str(item.get("date_iso") or "")
        if not iso:
            html = _previous_text(site, previous_ref, f"articles/{slug}.html")
            iso = _extract_news_date(html)
            display = display or _extract_visible_date(html)
        result[slug] = {"date": display, "date_iso": iso}
    return result


def _patch_news_article(html: str, display: str, iso: str, *, is_new: bool) -> str:
    replacement = f'<time datetime="{iso}">{display}</time>'
    if TIME_RE.search(html):
        html = TIME_RE.sub(replacement, html, count=1)

    def update_jsonld(match: re.Match[str]) -> str:
        raw = match.group(3)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return match.group(0)
        if not isinstance(data, dict) or data.get("@type") != "NewsArticle":
            return match.group(0)
        data["datePublished"] = iso
        if is_new or not data.get("dateModified"):
            data["dateModified"] = iso
        rendered = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        return f"{match.group(1)}{rendered}{match.group(4)}"

    return JSONLD_RE.sub(update_jsonld, html)


def _patch_card_dates(html: str, slug: str, old_display: str, new_display: str) -> str:
    if not old_display or old_display == new_display:
        return html
    anchor_re = re.compile(
        rf"(<a\b[^>]*href=([\"'])[^\"']*articles/{re.escape(slug)}\.html\2[^>]*>.*?</a>)",
        re.I | re.S,
    )

    def repl(match: re.Match[str]) -> str:
        block = match.group(1)
        if old_display in block:
            return block.replace(old_display, new_display)
        return DATE_RE.sub(new_display, block, count=1)

    return anchor_re.sub(repl, html)


def _patch_json_index(path: Path, dates: dict[str, dict[str, str]]) -> bool:
    data = _load_json(path, [])
    if not isinstance(data, list):
        return False
    changed = False
    for item in data:
        slug = str(item.get("slug") or "")
        target = dates.get(slug)
        if not target:
            continue
        if item.get("date") != target["date"]:
            item["date"] = target["date"]
            changed = True
        if item.get("date_iso") != target["date_iso"]:
            item["date_iso"] = target["date_iso"]
            changed = True
    if changed:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed


def _patch_feed(site: Path, dates: dict[str, dict[str, str]], build_dt: datetime) -> bool:
    path = site / "feed.xml"
    if not path.exists():
        return False
    try:
        tree = ET.parse(path)
    except ET.ParseError:
        return False
    root = tree.getroot()
    changed = False
    channel = root.find("channel")
    if channel is None:
        return False
    last_build = channel.find("lastBuildDate")
    build_rfc = format_datetime(build_dt.astimezone(timezone.utc), usegmt=True)
    if last_build is not None and last_build.text != build_rfc:
        last_build.text = build_rfc
        changed = True
    for item in channel.findall("item"):
        link = item.findtext("link") or ""
        slug = Path(urlparse(link).path).stem
        target = dates.get(slug)
        if not target:
            continue
        dt = _parse_datetime(target["date_iso"])
        if not dt:
            continue
        expected = format_datetime(dt.astimezone(timezone.utc), usegmt=True)
        pub = item.find("pubDate")
        if pub is not None and pub.text != expected:
            pub.text = expected
            changed = True
    if changed:
        ET.indent(tree, space="  ")
        tree.write(path, encoding="utf-8", xml_declaration=True)
    return changed


def stamp_publication_times(
    site_dir: Path,
    previous_ref: str = "HEAD~1",
    published_at: datetime | None = None,
) -> dict:
    site = Path(site_dir).resolve()
    deploy_dt = (published_at or datetime.now(PARIS)).astimezone(PARIS)
    current_path = site / "data" / "articles.json"
    current = _load_json(current_path, [])
    if not isinstance(current, list):
        raise ValueError("data/articles.json doit contenir une liste")

    previous = _previous_publication_map(site, previous_ref)
    added = _added_article_slugs(site, previous_ref)
    old_display = {str(a.get("slug") or ""): str(a.get("date") or "") for a in current}
    dates: dict[str, dict[str, str]] = {}
    new_publications: list[str] = []

    for item in current:
        slug = str(item.get("slug") or "")
        if not slug:
            continue
        preserved = previous.get(slug)
        preserved_dt = _parse_datetime((preserved or {}).get("date_iso"))
        if preserved and preserved_dt:
            iso = _iso_date(preserved_dt)
            display = preserved.get("date") or _display_date(preserved_dt)
        elif slug in added:
            iso = _iso_date(deploy_dt)
            display = _display_date(deploy_dt)
            new_publications.append(slug)
        else:
            article_html = (site / "articles" / f"{slug}.html")
            html = article_html.read_text(encoding="utf-8", errors="replace") if article_html.exists() else ""
            current_dt = _parse_datetime(item.get("date_iso") or _extract_news_date(html))
            current_dt = current_dt or deploy_dt
            iso = _iso_date(current_dt)
            display = str(item.get("date") or _extract_visible_date(html) or _display_date(current_dt))
        dates[slug] = {"date": display, "date_iso": iso}

    changed_files = 0
    if _patch_json_index(current_path, dates):
        changed_files += 1
    if _patch_json_index(site / "data" / "search.json", dates):
        changed_files += 1

    for slug, target in dates.items():
        path = site / "articles" / f"{slug}.html"
        if not path.exists():
            continue
        original = path.read_text(encoding="utf-8", errors="replace")
        updated = _patch_news_article(
            original, target["date"], target["date_iso"], is_new=slug in new_publications
        )
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            changed_files += 1

    html_paths = [
        *(p for p in site.glob("*.html") if p.is_file()),
        *(p for p in (site / "categories").glob("*.html") if p.is_file()),
        *(p for p in (site / "articles").glob("*.html") if p.is_file()),
    ]
    for path in html_paths:
        original = path.read_text(encoding="utf-8", errors="replace")
        updated = original
        for slug, target in dates.items():
            updated = _patch_card_dates(updated, slug, old_display.get(slug, ""), target["date"])
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            changed_files += 1

    if _patch_feed(site, dates, deploy_dt):
        changed_files += 1

    validate_publication_times(site, dates, set(new_publications))
    print(
        f"[HORODATAGE] {len(new_publications)} nouvelle(s) publication(s), "
        f"{len(previous)} horaire(s) préservé(s), {changed_files} fichier(s) modifié(s)."
    )
    if new_publications:
        print("[HORODATAGE] Nouveaux slugs : " + ", ".join(sorted(new_publications)))
    return {
        "new": len(new_publications),
        "new_slugs": sorted(new_publications),
        "preserved": len(previous),
        "changed_files": changed_files,
    }


def validate_publication_times(
    site: Path,
    dates: dict[str, dict[str, str]] | None = None,
    required_slugs: set[str] | None = None,
) -> None:
    site = Path(site)
    articles = _load_json(site / "data" / "articles.json", [])
    if not isinstance(articles, list):
        raise AssertionError("data/articles.json illisible")
    by_slug = {str(a.get("slug") or ""): a for a in articles}
    dates = dates or {
        slug: {"date": str(a.get("date") or ""), "date_iso": str(a.get("date_iso") or "")}
        for slug, a in by_slug.items()
    }
    required = required_slugs or set()
    for slug in required:
        target = dates.get(slug)
        if not target or not _parse_datetime(target.get("date_iso")):
            raise AssertionError(f"{slug}: date_iso absente ou invalide")
        html_path = site / "articles" / f"{slug}.html"
        html = html_path.read_text(encoding="utf-8", errors="replace")
        if target["date"] not in html or target["date_iso"] not in html:
            raise AssertionError(f"{slug}: HTML non aligné sur l'heure publique")
        if _extract_news_date(html) != target["date_iso"]:
            raise AssertionError(f"{slug}: JSON-LD datePublished incohérent")


def _parse_cli_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = _parse_datetime(value)
    if not dt:
        raise argparse.ArgumentTypeError("date ISO 8601 invalide")
    return dt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site-dir", required=True, type=Path)
    parser.add_argument("--previous-ref", default="HEAD~1")
    parser.add_argument("--published-at", type=_parse_cli_datetime)
    args = parser.parse_args()
    stamp_publication_times(args.site_dir, args.previous_ref, args.published_at)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
