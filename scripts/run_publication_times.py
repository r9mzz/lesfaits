# -*- coding: utf-8 -*-
"""Point d'entrée robuste pour l'horodatage public.

Le script historique sait restaurer une heure déjà persistée dans ``date_iso``.
Ce wrapper couvre aussi le cas transitoire où un ancien article reconstruit a
perdu ce champ dans ``data/articles.json`` alors que son HTML public précédent
porte encore le bon ``datePublished``. Seuls les articles réellement ajoutés ou
modifiés dans le dernier déploiement sont concernés : aucun backfill massif des
anciens articles n'est déclenché.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import stamp_publication_times as legacy


def _touched_article_slugs(site: Path, previous_ref: str) -> set[str]:
    try:
        output = legacy._run_git(
            site,
            "diff", "--name-only", "--diff-filter=AM",
            previous_ref, "HEAD", "--", "articles/*.html",
        )
    except Exception:
        return set()
    return {
        Path(line.strip()).stem
        for line in output.splitlines()
        if line.strip().startswith("articles/") and line.strip().endswith(".html")
    }


def install_legacy_rebuild_recovery(site: Path, previous_ref: str):
    """Marque comme restaurables les dates publiques retrouvées dans l'ancien HTML.

    ``stamp_publication_times`` distingue volontairement les anciens articles
    sans ``date_iso`` afin de ne pas les réécrire en masse. Pour un article qui
    vient réellement d'être reconstruit, cette prudence devient un bug : si son
    dernier état public avait déjà perdu ``date_iso``, l'heure historique lue
    dans le JSON-LD précédent n'était jamais réappliquée au rebuild suivant.
    """
    touched = _touched_article_slugs(Path(site), previous_ref)
    original = legacy._previous_publication_map

    def recovered_map(runtime_site: Path, runtime_ref: str):
        mapping = original(runtime_site, runtime_ref)
        for slug in touched:
            entry = mapping.get(slug)
            if entry and entry.get("date_iso"):
                entry["persisted"] = True
        return mapping

    legacy._previous_publication_map = recovered_map
    return original


def main() -> int:
    probe = argparse.ArgumentParser(add_help=False)
    probe.add_argument("--site-dir", required=True, type=Path)
    probe.add_argument("--previous-ref", default="HEAD~1")
    args, _ = probe.parse_known_args()
    install_legacy_rebuild_recovery(args.site_dir, args.previous_ref)
    return legacy.main()


if __name__ == "__main__":
    raise SystemExit(main())
