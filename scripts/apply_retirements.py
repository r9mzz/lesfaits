# -*- coding: utf-8 -*-
"""Consolide les articles retirés ou doublons sans casser leurs anciennes URL.

La liste de vérité est ``data/retirements.json``. Pour chaque entrée :
- le slug est retiré des index de contenu ;
- l'ancienne page devient un stub ``noindex`` avec canonical et redirection ;
- le motif reste lisible sans JavaScript pour une transparence éditoriale.

Le script est idempotent et ne supprime jamais la page cible.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RETIREMENTS = ROOT / "data" / "retirements.json"


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def _write_json_if_changed(path: Path, data) -> bool:
    content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    if old == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def _validate(entries: list[dict], known_slugs: set[str]) -> None:
    retired = {str(e.get("slug", "")) for e in entries}
    if "" in retired:
        raise ValueError("Une entrée de retrait ne contient pas de slug")
    if len(retired) != len(entries):
        raise ValueError("Un slug figure plusieurs fois dans retirements.json")

    redirects = {str(e["slug"]): str(e.get("redirect_to", "")) for e in entries}
    for slug, target in redirects.items():
        if not target:
            raise ValueError(f"{slug}: redirect_to manquant")
        if slug == target:
            raise ValueError(f"{slug}: redirection vers lui-même")
        if target in retired:
            raise ValueError(f"{slug}: la cible {target} est elle-même retirée")
        target_html = ROOT / "articles" / f"{target}.html"
        if target not in known_slugs and not target_html.exists():
            raise ValueError(f"{slug}: cible introuvable {target}")


def _stub(slug: str, target: str, target_title: str, reason: str, date: str) -> str:
    target_url = f"/articles/{target}.html"
    title = f"Article consolidé — {target_title or 'Les Faits'}"
    safe_title = html.escape(title, quote=True)
    safe_target_title = html.escape(target_title or "l’article consolidé")
    safe_reason = html.escape(reason)
    safe_date = html.escape(date)
    js_target = json.dumps(target_url, ensure_ascii=False).replace("</", "<\\/")
    return f'''<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <meta name="robots" content="noindex, follow"/>
  <meta name="description" content="Cet article a été consolidé avec une version plus complète sur Les Faits."/>
  <link rel="canonical" href="https://lesfaits.info{target_url}"/>
  <meta http-equiv="refresh" content="2;url={target_url}"/>
  <title>{safe_title}</title>
  <base href="/"/>
  <link rel="stylesheet" href="/src/style.css?v=2"/>
  <script>window.location.replace({js_target});</script>
</head>
<body>
  <main style="max-width:680px;margin:100px auto;padding:0 24px;line-height:1.7">
    <p style="font-size:.8rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)">Mise à jour éditoriale</p>
    <h1 style="font-size:2rem;line-height:1.2">Cet article a été consolidé</h1>
    <p>Deux publications couvraient le même événement. Pour éviter les doublons, cette page renvoie désormais vers la version retenue :</p>
    <p><a href="{target_url}" style="font-weight:700;color:var(--blue)">{safe_target_title} →</a></p>
    <p style="color:var(--muted);font-size:.9rem"><strong>Motif :</strong> {safe_reason}<br/><strong>Date :</strong> {safe_date}</p>
  </main>
</body>
</html>
'''


def apply_retirements(root: Path | None = None) -> dict:
    global ROOT, RETIREMENTS
    if root is not None:
        ROOT = Path(root).resolve()
        RETIREMENTS = ROOT / "data" / "retirements.json"

    entries = _load_json(RETIREMENTS, [])
    if not isinstance(entries, list):
        raise ValueError("retirements.json doit contenir une liste")
    if not entries:
        return {"entries": 0, "changed": False, "stubs": 0, "removed_from_indexes": 0}

    articles_path = ROOT / "data" / "articles.json"
    articles = _load_json(articles_path, [])
    if not isinstance(articles, list):
        raise ValueError("data/articles.json doit contenir une liste")
    by_slug = {str(item.get("slug", "")): item for item in articles}
    _validate(entries, set(by_slug))

    retired = {str(entry["slug"]) for entry in entries}
    changed = False
    removed_count = 0

    for data_name in ("articles.json", "search.json"):
        path = ROOT / "data" / data_name
        if not path.exists():
            continue
        data = _load_json(path, [])
        if not isinstance(data, list):
            continue
        filtered = [item for item in data if str(item.get("slug", "")) not in retired]
        removed_count += len(data) - len(filtered)
        changed = _write_json_if_changed(path, filtered) or changed

    pending = ROOT / "data" / "pending_x_posts.txt"
    if pending.exists():
        lines = [line.strip() for line in pending.read_text(encoding="utf-8").splitlines() if line.strip()]
        filtered_lines = [line for line in lines if line not in retired]
        content = "\n".join(filtered_lines) + ("\n" if filtered_lines else "")
        if pending.read_text(encoding="utf-8") != content:
            pending.write_text(content, encoding="utf-8")
            changed = True

    stubs = 0
    for entry in entries:
        slug = str(entry["slug"])
        target = str(entry["redirect_to"])
        target_meta = by_slug.get(target, {})
        target_title = str(target_meta.get("titre") or target.replace("-", " ").capitalize())
        desired = _stub(
            slug, target, target_title,
            str(entry.get("reason") or "Contenu consolidé avec une version plus complète."),
            str(entry.get("date") or ""),
        )
        path = ROOT / "articles" / f"{slug}.html"
        old = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        if old != desired:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(desired, encoding="utf-8")
            changed = True
            stubs += 1
            print(f"[CONSOLIDATION] {slug} → {target}")

    print(
        f"[CONSOLIDATION] {len(entries)} retrait(s), {removed_count} entrée(s) "
        f"retirée(s) des index, {stubs} stub(s) actualisé(s)."
    )
    return {
        "entries": len(entries), "changed": changed, "stubs": stubs,
        "removed_from_indexes": removed_count,
    }


if __name__ == "__main__":
    apply_retirements()
