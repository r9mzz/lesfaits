# -*- coding: utf-8 -*-
"""Point d'entrée sûr pour la newsletter.

Le mode ``--dry-run`` ne contacte jamais Brevo et ne crée aucun attribut : il
lit seulement le dépôt, construit l'aperçu HTML et s'arrête. Les envois réels
sont délégués au moteur idempotent ``generer_digest``.

La migration vers le moteur v2 conserve aussi la date du dernier digest envoyé
par l'ancien moteur (tag ``nl-digest``), afin que le premier run v2 ne renvoie
pas une seconde fois des articles déjà reçus.
"""
from __future__ import annotations

import argparse
import datetime as dt
from zoneinfo import ZoneInfo

import generer_digest as digest

PARIS = ZoneInfo("Europe/Paris")
LEGACY_CAMPAIGN_TAGS = frozenset({digest.CAMPAIGN_TAG, "nl-digest"})


def _preview_display_path() -> object:
    """Retourne un chemin lisible, même si les tests utilisent un dossier temporaire."""
    try:
        return digest.PREVIEW_HTML.relative_to(digest.ROOT)
    except ValueError:
        return digest.PREVIEW_HTML


def latest_sent_campaign_time_compatible(client) -> dt.datetime | None:
    """Dernier envoi v2 ou ancien, pour une transition sans doublon."""
    latest: dt.datetime | None = None
    for campaign in digest.list_campaigns(client, status="sent"):
        if campaign.get("tag") not in LEGACY_CAMPAIGN_TAGS:
            continue
        sent = digest.parse_iso(campaign.get("sentDate") or campaign.get("scheduledAt"))
        if sent and (latest is None or sent > latest):
            latest = sent
    return latest


def build_local_preview(slot: str, now: dt.datetime | None = None) -> dict[str, int]:
    now = (now or dt.datetime.now(PARIS)).astimezone(PARIS)
    slugs = digest.recent_article_slugs(None)
    articles = digest.load_articles(slugs)
    by_category: dict[str, list[dict]] = {}
    for article in articles:
        category = str(article.get("categorie") or "")
        if category in digest.CATEGORIES:
            by_category.setdefault(category, []).append(article)
    if not by_category:
        print("[DRY-RUN NEWSLETTER] Aucun article éligible sur les 30 dernières heures.")
        return {"articles": 0, "categories": 0}
    html = digest.build_email(by_category, now=now, slot=slot)
    digest.PREVIEW_HTML.write_text(html, encoding="utf-8")
    count = sum(len(items) for items in by_category.values())
    print(
        f"[DRY-RUN NEWSLETTER] {count} article(s), {len(by_category)} rubrique(s), "
        f"aperçu={_preview_display_path()}. Aucun appel Brevo."
    )
    return {"articles": count, "categories": len(by_category)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slot", choices=("matin", "soir"), default="matin")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check-config", action="store_true")
    parser.add_argument("--now")
    args = parser.parse_args(argv)

    now = digest.parse_iso(args.now) if args.now else dt.datetime.now(PARIS)
    if now is None:
        raise RuntimeError("--now doit être une date ISO 8601 valide")

    if args.dry_run:
        build_local_preview(args.slot, now)
        return 0

    delegated = ["--slot", args.slot]
    if args.check_config:
        delegated.append("--check-config")
    if args.now:
        delegated.extend(["--now", args.now])

    # Le moteur lit ce symbole global au moment de construire la fenêtre de
    # collecte. On le remplace seulement pendant cet appel, puis on restaure la
    # fonction d'origine pour éviter tout effet de bord dans les tests/imports.
    original = digest.latest_sent_campaign_time
    digest.latest_sent_campaign_time = latest_sent_campaign_time_compatible
    try:
        return digest.main(delegated)
    finally:
        digest.latest_sent_campaign_time = original


if __name__ == "__main__":
    raise SystemExit(main())
