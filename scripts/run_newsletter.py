# -*- coding: utf-8 -*-
"""Point d'entrée sûr pour la newsletter.

Le mode ``--dry-run`` ne contacte jamais Brevo et ne crée aucun attribut : il
lit seulement le dépôt, construit l'aperçu HTML et s'arrête. Les envois réels
sont délégués au moteur idempotent ``generer_digest``.

La migration vers le moteur v2 conserve aussi la date du dernier digest envoyé
par l'ancien moteur (tag ``nl-digest``), afin que le premier run v2 ne renvoie
pas une seconde fois des articles déjà reçus.

Quand le workflow fournit ``--slugs-file`` et ``--deployment-id``, la matière
vient exclusivement des fichiers article réellement AJOUTÉS par le commit de
déploiement public. Cela évite qu'un retard GitHub fasse oublier un article
généré avant un ancien digest mais publié seulement plusieurs heures plus tard.
L'identifiant du déploiement entre aussi dans le nom de campagne : une relance
du même commit est idempotente, tandis que deux vrais déploiements le même jour
peuvent chacun envoyer leur propre lot.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import generer_digest as digest

PARIS = ZoneInfo("Europe/Paris")
LEGACY_CAMPAIGN_TAGS = frozenset({digest.CAMPAIGN_TAG, "nl-digest"})
DEPLOYMENT_ID_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")
SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,198}[a-z0-9])?$")


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


def read_deployment_slugs(path: str | Path) -> list[str]:
    """Lit une liste fermée de slugs issue d'un commit public.

    Les chemins, extensions, doublons et caractères ambigus sont refusés : le
    fichier est une frontière de confiance entre GitHub Actions et le moteur
    d'envoi, pas une simple suggestion de recherche.
    """
    source = Path(path)
    if not source.is_absolute():
        source = (digest.ROOT / source).resolve()
    if not source.exists():
        raise RuntimeError(f"Fichier de lot newsletter absent : {source}")

    slugs: list[str] = []
    for number, raw in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        slug = raw.strip()
        if not slug or slug.startswith("#"):
            continue
        if not SLUG_RE.fullmatch(slug):
            raise RuntimeError(f"Slug de déploiement invalide ligne {number}: {slug!r}")
        if slug not in slugs:
            slugs.append(slug)
    return slugs


def _search_index() -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(digest.SEARCH_JSON.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError("data/search.json absent") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("data/search.json invalide") from exc
    if not isinstance(data, list):
        raise RuntimeError("data/search.json doit contenir une liste")
    return {
        str(item.get("slug") or ""): item
        for item in data
        if isinstance(item, dict) and item.get("slug")
    }


def _is_redirect_stub(slug: str) -> bool:
    path = digest.ROOT / "articles" / f"{slug}.html"
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="replace").lower()
    return "noindex" in text and (
        "http-equiv=\"refresh\"" in text
        or "http-equiv='refresh'" in text
        or "consolid" in text
        or "redirection" in text
    )


def articles_for_deployment(slugs: list[str]) -> list[dict[str, Any]]:
    """Charge le lot exact et ignore seulement les redirections déclarées."""
    index = _search_index()
    articles: list[dict[str, Any]] = []
    missing: list[str] = []
    redirects: list[str] = []
    for slug in slugs:
        item = index.get(slug)
        if item is not None:
            articles.append(item)
        elif _is_redirect_stub(slug):
            redirects.append(slug)
        else:
            missing.append(slug)
    if redirects:
        print(
            "[LOT PUBLIC] Redirection(s) exclue(s) du digest : "
            + ", ".join(redirects)
        )
    if missing:
        raise RuntimeError(
            "Article(s) ajouté(s) au site mais absent(s) de search.json : "
            + ", ".join(missing)
        )
    return articles


def build_local_preview(
    slot: str,
    now: dt.datetime | None = None,
    slugs_file: str | Path | None = None,
) -> dict[str, int]:
    now = (now or dt.datetime.now(PARIS)).astimezone(PARIS)
    if slugs_file is not None:
        slugs = read_deployment_slugs(slugs_file)
        articles = articles_for_deployment(slugs)
    else:
        since = now - dt.timedelta(hours=30)
        slugs = digest.recent_article_slugs(since)
        articles = digest.load_articles(slugs)

    by_category: dict[str, list[dict]] = {}
    for article in articles:
        category = str(article.get("categorie") or "")
        if category in digest.CATEGORIES:
            by_category.setdefault(category, []).append(article)
    if not by_category:
        print("[DRY-RUN NEWSLETTER] Aucun article éligible dans le lot contrôlé.")
        return {"articles": 0, "categories": 0}
    html = digest.build_email(by_category, now=now, slot=slot)
    digest.PREVIEW_HTML.write_text(html, encoding="utf-8")
    count = sum(len(items) for items in by_category.values())
    print(
        f"[DRY-RUN NEWSLETTER] {count} article(s), {len(by_category)} rubrique(s), "
        f"aperçu={_preview_display_path()}. Aucun appel Brevo."
    )
    return {"articles": count, "categories": len(by_category)}


def deployment_campaign_name(original, deployment_id: str):
    short = deployment_id.lower()[:12]

    def build(run_now: dt.datetime, slot: str) -> str:
        return f"{original(run_now, slot)} | {short}"

    return build


def _legacy_campaign_matches_deployment(
    campaign: dict[str, Any] | None,
    published_at: dt.datetime,
) -> bool:
    if not campaign:
        return False
    status = str(campaign.get("status") or "").lower()
    if status not in digest.SUCCESS_CAMPAIGN_STATUSES:
        return False
    timestamp = digest.parse_iso(
        campaign.get("sentDate")
        or campaign.get("scheduledAt")
        or campaign.get("createdAt")
    )
    # Le digest part après le commit public. Une petite tolérance absorbe la
    # précision des horloges sans confondre un autre déploiement plus tard.
    return bool(timestamp and timestamp >= published_at - dt.timedelta(seconds=30))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slot", choices=("matin", "soir"), default="matin")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check-config", action="store_true")
    parser.add_argument("--now")
    parser.add_argument(
        "--slugs-file",
        help="Liste exacte des slugs ajoutés par le déploiement public.",
    )
    parser.add_argument(
        "--deployment-id",
        help="SHA du commit public, utilisé comme clé d'idempotence.",
    )
    args = parser.parse_args(argv)

    now = digest.parse_iso(args.now) if args.now else dt.datetime.now(PARIS)
    if now is None:
        raise RuntimeError("--now doit être une date ISO 8601 valide")
    if args.deployment_id and not DEPLOYMENT_ID_RE.fullmatch(args.deployment_id):
        raise RuntimeError("--deployment-id doit être un identifiant Git hexadécimal")
    if args.slugs_file and not args.dry_run and not args.deployment_id:
        raise RuntimeError("--deployment-id est obligatoire avec un lot public réel")

    if args.dry_run:
        build_local_preview(args.slot, now, args.slugs_file)
        return 0

    delegated = ["--slot", args.slot]
    if args.check_config:
        delegated.append("--check-config")
    if args.now:
        delegated.extend(["--now", args.now])

    exact_slugs = read_deployment_slugs(args.slugs_file) if args.slugs_file else None
    # Valider le lot AVANT le premier appel Brevo : une incohérence de publication
    # doit échouer sans toucher aux contacts ni aux campagnes. Les redirections
    # de consolidation sont retirées de la liste transmise au moteur historique.
    if exact_slugs is not None:
        deployment_articles = articles_for_deployment(exact_slugs)
        exact_slugs = [str(article["slug"]) for article in deployment_articles]

    original_latest = digest.latest_sent_campaign_time
    original_recent = digest.recent_article_slugs
    original_name = digest.campaign_name
    original_find = digest.find_campaign

    digest.latest_sent_campaign_time = latest_sent_campaign_time_compatible
    if exact_slugs is not None:
        digest.recent_article_slugs = lambda _since: list(exact_slugs)

    if args.deployment_id:
        primary_name = f"{original_name(now, args.slot)} | {args.deployment_id.lower()[:12]}"
        legacy_name = original_name(now, args.slot)
        digest.campaign_name = deployment_campaign_name(original_name, args.deployment_id)

        def find_compatible(client, name: str):
            exact = original_find(client, name)
            if exact is not None or name != primary_name:
                return exact
            legacy = original_find(client, legacy_name)
            return legacy if _legacy_campaign_matches_deployment(legacy, now) else None

        digest.find_campaign = find_compatible

    try:
        return digest.main(delegated)
    finally:
        digest.latest_sent_campaign_time = original_latest
        digest.recent_article_slugs = original_recent
        digest.campaign_name = original_name
        digest.find_campaign = original_find


if __name__ == "__main__":
    raise SystemExit(main())
