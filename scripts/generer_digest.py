#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Newsletter Les Faits — audience Brevo fiable, vérifiée et idempotente."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from newsletter_template import CATEGORIES, PARIS, build_email, date_longue

ROOT = Path(__file__).resolve().parent.parent
SEARCH_JSON = ROOT / "data" / "search.json"
PREVIEW_HTML = ROOT / "newsletter-preview.html"
BREVO_API_BASE = "https://api.brevo.com/v3"
BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")
BREVO_LIST_ID = os.getenv("BREVO_LIST_ID", "")
BREVO_SENDER_EMAIL = os.getenv("BREVO_SENDER_EMAIL", "")
BREVO_SENDER_NAME = os.getenv("BREVO_SENDER_NAME", "Les Faits")
DELIVERY_LIST_NAME = "Digest — Envoi du jour"
CAMPAIGN_TAG = "nl-digest-v2"
LEGACY_CAMPAIGN_TAGS = {"nl-digest"}
SUCCESS_STATUSES = {"sent", "queued", "scheduled"}
RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


@dataclass
class Brevo:
    api_key: str
    attempts: int = 4
    timeout: int = 25

    def __post_init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "accept": "application/json",
            "content-type": "application/json",
            "api-key": self.api_key,
            "user-agent": "LesFaits-Newsletter/2.0",
        })

    def request(
        self,
        method: str,
        path: str,
        *,
        expected: tuple[int, ...] = (200,),
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> requests.Response:
        url = BREVO_API_BASE + path
        for attempt in range(1, self.attempts + 1):
            try:
                response = self.session.request(
                    method, url, params=params, json=payload, timeout=self.timeout
                )
            except requests.RequestException as exc:
                if attempt == self.attempts:
                    raise RuntimeError(f"Brevo inaccessible: {exc}") from exc
                time.sleep(min(2 ** attempt, 8))
                continue
            if response.status_code in expected:
                return response
            if response.status_code not in RETRYABLE_STATUS or attempt == self.attempts:
                body = response.text[:500].replace("\n", " ")
                raise RuntimeError(
                    f"Brevo {method} {path}: HTTP {response.status_code} — {body}"
                )
            retry_after = response.headers.get("retry-after")
            try:
                delay = float(retry_after) if retry_after else min(2 ** attempt, 10)
            except ValueError:
                delay = min(2 ** attempt, 10)
            time.sleep(max(1, delay))
        raise RuntimeError(f"Brevo {method} {path}: échec après {self.attempts} essais")

    def json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self.request(method, path, **kwargs)
        if not response.content:
            return {}
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(f"Brevo {method} {path}: JSON invalide") from exc
        if not isinstance(data, dict):
            raise RuntimeError(f"Brevo {method} {path}: objet JSON attendu")
        return data


def parse_iso(value: Any) -> dt.datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(PARIS)


def campaign_name(now: dt.datetime, slot: str) -> str:
    return f"Les Faits | {now.astimezone(PARIS):%Y-%m-%d} | {slot}"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=True, text=True, capture_output=True,
    ).stdout


def list_campaigns(client: Brevo, *, status: str | None = None) -> list[dict[str, Any]]:
    campaigns: list[dict[str, Any]] = []
    offset = 0
    while True:
        params: dict[str, Any] = {
            "type": "classic", "limit": 100, "offset": offset, "sort": "desc"
        }
        if status:
            params["status"] = status
        data = client.json("GET", "/emailCampaigns", params=params)
        batch = data.get("campaigns") or []
        if not isinstance(batch, list):
            raise RuntimeError("Brevo campagnes: liste invalide")
        campaigns.extend(item for item in batch if isinstance(item, dict))
        if len(batch) < 100:
            return campaigns
        offset += 100


def find_campaign(client: Brevo, name: str) -> dict[str, Any] | None:
    return next(
        (campaign for campaign in list_campaigns(client) if campaign.get("name") == name),
        None,
    )


def latest_sent_campaign_time(client: Brevo) -> dt.datetime | None:
    accepted_tags = {CAMPAIGN_TAG, *LEGACY_CAMPAIGN_TAGS}
    dates = [
        parsed
        for campaign in list_campaigns(client, status="sent")
        if campaign.get("tag") in accepted_tags
        for parsed in [parse_iso(campaign.get("sentDate") or campaign.get("scheduledAt"))]
        if parsed
    ]
    return max(dates) if dates else None


def recent_article_slugs(since: dt.datetime | None) -> list[str]:
    since = since or (dt.datetime.now(PARIS) - dt.timedelta(hours=30))
    output = _git(
        "log",
        f"--since={since.astimezone(dt.timezone.utc).isoformat(timespec='seconds')}",
        "--name-only", "--diff-filter=A", "--pretty=format:", "--", "articles/",
    )
    slugs: list[str] = []
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("articles/") and line.endswith(".html"):
            slug = Path(line).stem
            if slug and slug not in slugs:
                slugs.append(slug)
    return slugs


def load_articles(slugs: list[str]) -> list[dict[str, Any]]:
    if not SEARCH_JSON.exists():
        raise RuntimeError("data/search.json absent")
    try:
        raw = json.loads(SEARCH_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("data/search.json invalide") from exc
    if not isinstance(raw, list):
        raise RuntimeError("data/search.json doit contenir une liste")
    index = {
        str(item.get("slug") or ""): item
        for item in raw if isinstance(item, dict) and item.get("slug")
    }
    missing = [slug for slug in slugs if slug not in index]
    if missing:
        raise RuntimeError(
            f"{len(missing)} nouvel article absent de search.json; envoi annulé"
        )
    return [index[slug] for slug in slugs]


def boolish(value: Any) -> bool:
    return value is True or value == 1 or str(value or "").strip().lower() in {
        "1", "true", "yes", "oui", "on",
    }


def frequency(contact: dict[str, Any]) -> str:
    attrs = contact.get("attributes") or {}
    raw = str(attrs.get("FREQ") or "").strip().lower()
    aliases = {
        "morning": "morning", "matin": "morning", "am": "morning",
        "evening": "evening", "soir": "evening", "pm": "evening",
        "both": "both", "les deux": "both", "deux": "both", "all": "both",
    }
    if raw in aliases:
        return aliases[raw]
    legacy = attrs.get("ENVOI_MATIN")
    if legacy is True or boolish(legacy):
        return "morning"
    if legacy is False or str(legacy).strip().lower() in {"0", "false", "no", "non", "off"}:
        return "evening"
    return "both"


def wants_slot(contact: dict[str, Any], slot: str) -> bool:
    freq = frequency(contact)
    return freq == "both" or (slot == "matin" and freq == "morning") or (
        slot == "soir" and freq == "evening"
    )


def contact_categories(contact: dict[str, Any]) -> tuple[str, ...]:
    attrs = contact.get("attributes") or {}
    selected = tuple(
        category for category in CATEGORIES
        if boolish(attrs.get(f"CAT_{category.upper()}"))
    )
    return selected or CATEGORIES


def unsubscribed_from(contact: dict[str, Any], *list_ids: int) -> bool:
    if boolish(contact.get("emailBlacklisted")):
        return True
    try:
        unsubscribed = {int(value) for value in (contact.get("listUnsubscribed") or [])}
    except (TypeError, ValueError):
        unsubscribed = set()
    return any(int(list_id) in unsubscribed for list_id in list_ids)


def get_contacts_from_list(client: Brevo, list_id: int) -> list[dict[str, Any]]:
    contacts: list[dict[str, Any]] = []
    offset = 0
    while True:
        data = client.json(
            "GET", f"/contacts/lists/{list_id}/contacts",
            params={"limit": 500, "offset": offset, "sort": "asc"},
        )
        batch = data.get("contacts") or []
        if not isinstance(batch, list):
            raise RuntimeError("Brevo contacts: liste invalide")
        contacts.extend(item for item in batch if isinstance(item, dict))
        if len(batch) < 500:
            return contacts
        offset += 500


def ensure_contact_attributes(client: Brevo, *, create_missing: bool = True) -> None:
    required = {"FREQ": "text", **{
        f"CAT_{category.upper()}": "boolean" for category in CATEGORIES
    }}

    def read() -> dict[str, str]:
        data = client.json("GET", "/contacts/attributes")
        return {
            str(item.get("name") or "").upper(): str(item.get("type") or "").lower()
            for item in (data.get("attributes") or []) if isinstance(item, dict)
        }

    attributes = read()
    for name, expected_type in required.items():
        if name in attributes or not create_missing:
            continue
        client.request(
            "POST", f"/contacts/attributes/normal/{name}",
            expected=(200, 201, 204), payload={"type": expected_type},
        )
        print(f"[BREVO] Attribut {name} créé ({expected_type}).")

    attributes = read()
    missing = [name for name in required if name not in attributes]
    wrong = [
        f"{name}={attributes[name]}" for name, expected in required.items()
        if name in attributes and attributes[name] != expected
    ]
    if missing or wrong:
        details = []
        if missing:
            details.append("absents: " + ", ".join(missing))
        if wrong:
            details.append("types incorrects: " + ", ".join(wrong))
        raise RuntimeError("Configuration Brevo invalide (" + " ; ".join(details) + ")")


def get_or_create_delivery_list(client: Brevo, main_list_id: int) -> int:
    offset = 0
    while True:
        data = client.json(
            "GET", "/contacts/lists",
            params={"limit": 50, "offset": offset, "sort": "desc"},
        )
        batch = data.get("lists") or []
        for item in batch:
            if isinstance(item, dict) and item.get("name") == DELIVERY_LIST_NAME:
                return int(item["id"])
        if len(batch) < 50:
            break
        offset += 50
    main = client.json("GET", f"/contacts/lists/{main_list_id}")
    created = client.json(
        "POST", "/contacts/lists", expected=(200, 201),
        payload={"name": DELIVERY_LIST_NAME, "folderId": int(main["folderId"])},
    )
    list_id = int(created["id"])
    print(f"[BREVO] Liste technique créée: {list_id}.")
    return list_id


def wait_process(client: Brevo, process_id: Any, timeout_seconds: int = 90) -> None:
    if not process_id:
        return
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        status = str(
            client.json("GET", f"/processes/{int(process_id)}").get("status") or ""
        ).lower()
        if status == "completed":
            return
        if status in {"failed", "error", "cancelled"}:
            raise RuntimeError(f"Processus Brevo {process_id} en échec ({status})")
        time.sleep(2)
    raise RuntimeError(f"Processus Brevo {process_id} non terminé après {timeout_seconds}s")


def chunks(values: list[str], size: int = 100) -> list[list[str]]:
    return [values[index:index + size] for index in range(0, len(values), size)]


def mutate_list(
    client: Brevo, list_id: int, emails: list[str], operation: str
) -> None:
    for batch in chunks(emails):
        data = client.json(
            "POST", f"/contacts/lists/{list_id}/contacts/{operation}",
            expected=(200, 201, 202, 204), payload={"emails": batch},
        )
        wait_process(client, data.get("processId"))
        failures = data.get("failure") or []
        if failures:
            raise RuntimeError(
                f"{operation}: {len(failures)} contact(s) en échec"
            )


def remove_from_list(client: Brevo, list_id: int, emails: list[str]) -> None:
    mutate_list(client, list_id, emails, "remove")


def add_to_list(client: Brevo, list_id: int, emails: list[str]) -> None:
    mutate_list(client, list_id, emails, "add")


def sync_delivery_list(client: Brevo, list_id: int, target_emails: list[str]) -> None:
    target = {email.lower() for email in target_emails}
    current = get_contacts_from_list(client, list_id)
    protected = {
        str(contact.get("email") or "").strip().lower()
        for contact in current
        if contact.get("email") and unsubscribed_from(contact, list_id)
    }
    active = {
        str(contact.get("email") or "").strip().lower()
        for contact in current
        if contact.get("email") and not unsubscribed_from(contact, list_id)
    }
    to_remove = sorted(active - target)
    to_add = sorted(target - active - protected)
    if to_remove:
        remove_from_list(client, list_id, to_remove)
    if to_add:
        add_to_list(client, list_id, to_add)

    expected = target - protected
    for attempt in range(3):
        final = get_contacts_from_list(client, list_id)
        final_active = {
            str(contact.get("email") or "").strip().lower()
            for contact in final
            if contact.get("email") and not unsubscribed_from(contact, list_id)
        }
        if final_active == expected:
            print(
                f"[BREVO] Audience alignée: {len(final_active)} actif(s), "
                f"{len(protected)} désabonné(s) préservé(s)."
            )
            return
        time.sleep(2 ** attempt)
    raise RuntimeError(
        f"Audience incohérente (manquants={len(expected-final_active)}, "
        f"excédents={len(final_active-expected)})"
    )


def build_recipients(
    contacts: list[dict[str, Any]],
    *,
    main_list_id: int,
    delivery_list_id: int,
    slot: str,
    active_categories: set[str],
) -> tuple[list[str], dict[str, int]]:
    recipients: list[str] = []
    stats = {
        "blacklisted_or_unsubscribed": 0,
        "wrong_slot": 0,
        "no_matching_category": 0,
        "invalid_email": 0,
    }
    seen: set[str] = set()
    for contact in contacts:
        email = str(contact.get("email") or "").strip().lower()
        if not email or "@" not in email:
            stats["invalid_email"] += 1
            continue
        if email in seen:
            continue
        seen.add(email)
        if unsubscribed_from(contact, main_list_id, delivery_list_id):
            stats["blacklisted_or_unsubscribed"] += 1
        elif not wants_slot(contact, slot):
            stats["wrong_slot"] += 1
        elif not (set(contact_categories(contact)) & active_categories):
            stats["no_matching_category"] += 1
        else:
            recipients.append(email)
    return sorted(recipients), stats


def upsert_campaign(
    client: Brevo,
    *,
    name: str,
    subject: str,
    html_content: str,
    list_id: int,
    preview_text: str,
) -> tuple[int, str]:
    existing = find_campaign(client, name)
    payload = {
        "subject": subject,
        "sender": {"name": BREVO_SENDER_NAME, "email": BREVO_SENDER_EMAIL},
        "htmlContent": html_content,
        "recipients": {"listIds": [list_id]},
        "previewText": preview_text,
        "tag": CAMPAIGN_TAG,
        "replyTo": BREVO_SENDER_EMAIL,
    }
    if existing:
        campaign_id = int(existing["id"])
        status = str(existing.get("status") or "").lower()
        if status in SUCCESS_STATUSES:
            return campaign_id, status
        if status not in {"", "draft"}:
            raise RuntimeError(
                f"Campagne {campaign_id} dans un état inattendu: {status!r}"
            )
        client.request(
            "PUT", f"/emailCampaigns/{campaign_id}",
            expected=(200, 204), payload=payload,
        )
        return campaign_id, "draft"
    payload["name"] = name
    created = client.json(
        "POST", "/emailCampaigns", expected=(200, 201), payload=payload
    )
    return int(created["id"]), "draft"


def send_and_confirm(client: Brevo, campaign_id: int) -> str:
    client.request(
        "POST", f"/emailCampaigns/{campaign_id}/sendNow",
        expected=(200, 201, 202, 204),
    )
    deadline = time.monotonic() + 75
    last = ""
    while time.monotonic() < deadline:
        info = client.json(
            "GET", f"/emailCampaigns/{campaign_id}",
            params={"excludeHtmlContent": "true"},
        )
        last = str(info.get("status") or "").lower()
        if last in SUCCESS_STATUSES:
            return last
        if last in {"archive", "cancelled"}:
            break
        time.sleep(3)
    raise RuntimeError(
        f"Campagne {campaign_id} non confirmée (statut={last or 'inconnu'})"
    )


def validate_environment() -> int:
    missing = [
        name for name, value in (
            ("BREVO_API_KEY", BREVO_API_KEY),
            ("BREVO_LIST_ID", BREVO_LIST_ID),
            ("BREVO_SENDER_EMAIL", BREVO_SENDER_EMAIL),
        ) if not value
    ]
    if missing:
        raise RuntimeError("Secrets newsletter absents: " + ", ".join(missing))
    try:
        list_id = int(BREVO_LIST_ID)
    except ValueError as exc:
        raise RuntimeError("BREVO_LIST_ID doit être un entier") from exc
    if "@" not in BREVO_SENDER_EMAIL:
        raise RuntimeError("BREVO_SENDER_EMAIL invalide")
    return list_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slot", choices=("matin", "soir"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check-config", action="store_true")
    parser.add_argument("--now", help="Date ISO 8601 du déploiement public")
    args = parser.parse_args(argv)

    now = parse_iso(args.now) if args.now else dt.datetime.now(PARIS)
    if not now:
        raise RuntimeError("--now doit être une date ISO 8601 valide")
    main_list_id = validate_environment()
    client = Brevo(BREVO_API_KEY)
    ensure_contact_attributes(
        client, create_missing=(args.check_config or not args.dry_run)
    )
    if args.check_config:
        delivery_id = get_or_create_delivery_list(client, main_list_id)
        print(
            f"[CONFIG NEWSLETTER] liste principale={main_list_id}, "
            f"liste de diffusion={delivery_id}, attributs valides."
        )
        return 0
    if not args.slot:
        parser.error("--slot est obligatoire hors --check-config")

    name = campaign_name(now, args.slot)
    existing = find_campaign(client, name)
    if existing and str(existing.get("status") or "").lower() in SUCCESS_STATUSES:
        print(f"[IDEMPOTENCE] {name} déjà envoyé ou programmé — aucun doublon.")
        return 0

    articles = load_articles(recent_article_slugs(latest_sent_campaign_time(client)))
    by_category: dict[str, list[dict[str, Any]]] = {}
    for article in articles:
        category = str(article.get("categorie") or "")
        if category in CATEGORIES:
            by_category.setdefault(category, []).append(article)
    if not by_category:
        print("[NEWSLETTER] Aucun nouvel article éligible depuis le dernier digest.")
        return 0

    html_content = build_email(by_category, now=now, slot=args.slot)
    PREVIEW_HTML.write_text(html_content, encoding="utf-8")
    article_count = sum(map(len, by_category.values()))
    print(
        f"[NEWSLETTER] {article_count} article(s), {len(by_category)} rubrique(s), "
        f"aperçu={PREVIEW_HTML.name}."
    )
    if args.dry_run:
        print("[DRY-RUN] Aucun contact ni campagne modifié.")
        return 0

    delivery_id = get_or_create_delivery_list(client, main_list_id)
    contacts = get_contacts_from_list(client, main_list_id)
    recipients, stats = build_recipients(
        contacts,
        main_list_id=main_list_id,
        delivery_list_id=delivery_id,
        slot=args.slot,
        active_categories=set(by_category),
    )
    print(
        f"[CONTACTS] {len(contacts)} total, {len(recipients)} destinataire(s), "
        f"{stats['blacklisted_or_unsubscribed']} désabonné(s), "
        f"{stats['wrong_slot']} autre créneau, "
        f"{stats['no_matching_category']} sans rubrique active."
    )
    if not recipients:
        print("[NEWSLETTER] Aucun destinataire éligible.")
        return 0

    sync_delivery_list(client, delivery_id, recipients)
    article_label = "nouvel article" if article_count == 1 else "nouveaux articles"
    campaign_id, status = upsert_campaign(
        client,
        name=name,
        subject=(
            f"Les Faits — votre sélection du {date_longue(now)} "
            f"({args.slot})"
        ),
        html_content=html_content,
        list_id=delivery_id,
        preview_text=f"{article_count} {article_label} dans votre sélection.",
    )
    if status in SUCCESS_STATUSES:
        print(f"[IDEMPOTENCE] Campagne {campaign_id} déjà {status}.")
        return 0
    final_status = send_and_confirm(client, campaign_id)
    print(
        f"[SUCCÈS] Campagne {campaign_id} {final_status}, "
        f"{len(recipients)} destinataire(s)."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[ERREUR NEWSLETTER] {exc}", file=sys.stderr)
        raise SystemExit(1)
