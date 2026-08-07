#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Newsletter Les Faits — digest Brevo fiable et idempotent.

Principes:
- aucun envoi en double pour un même créneau et une même date ;
- uniquement les articles ajoutés depuis la dernière campagne envoyée ;
- fréquences modernes FREQ=morning|evening|both, avec compatibilité ENVOI_MATIN ;
- exclusions globales ET désabonnements de liste ;
- synchronisation non destructive de la liste de diffusion ;
- vérification des échecs partiels Brevo et des opérations asynchrones ;
- erreur d'envoi = code de sortie non nul, jamais un faux succès.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests

PARIS = ZoneInfo("Europe/Paris")
ROOT = Path(__file__).resolve().parent.parent
SEARCH_JSON = ROOT / "data" / "search.json"
PREVIEW_HTML = ROOT / "newsletter-preview.html"

BREVO_API_BASE = "https://api.brevo.com/v3"
BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")
BREVO_LIST_ID = os.getenv("BREVO_LIST_ID", "")
BREVO_SENDER_EMAIL = os.getenv("BREVO_SENDER_EMAIL", "")
BREVO_SENDER_NAME = os.getenv("BREVO_SENDER_NAME", "Les Faits")
SITE_BASE = "https://lesfaits.info"
DELIVERY_LIST_NAME = "Digest — Envoi du jour"
CAMPAIGN_TAG = "nl-digest-v2"

CATEGORIES = ("societe", "science", "economie", "tech", "sante", "environnement")
CAT_LABELS = {
    "societe": "Société",
    "science": "Science",
    "economie": "Économie",
    "tech": "Tech",
    "sante": "Santé",
    "environnement": "Environnement",
}
CAT_COLORS = {
    "societe": "#78716c",
    "science": "#0891b2",
    "economie": "#ea580c",
    "tech": "#9333ea",
    "sante": "#e11d48",
    "environnement": "#16a34a",
}
MONTHS = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)
WEEKDAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
SUCCESS_CAMPAIGN_STATUSES = {"sent", "queued", "scheduled"}
RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


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
        last: requests.Response | None = None
        for attempt in range(1, self.attempts + 1):
            try:
                response = self.session.request(
                    method,
                    url,
                    params=params,
                    json=payload,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                if attempt == self.attempts:
                    raise RuntimeError(f"Brevo inaccessible: {exc}") from exc
                time.sleep(min(2 ** attempt, 8))
                continue
            last = response
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
        raise RuntimeError(
            f"Brevo {method} {path}: aucune réponse exploitable"
            + (f" ({last.status_code})" if last else "")
        )

    def json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self.request(method, path, **kwargs)
        if not response.content:
            return {}
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(f"Brevo {method} {path}: réponse JSON invalide") from exc
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


def date_longue(now: dt.datetime) -> str:
    local = now.astimezone(PARIS)
    return f"{WEEKDAYS[local.weekday()]} {local.day} {MONTHS[local.month - 1]} {local.year}"


def campaign_name(now: dt.datetime, slot: str) -> str:
    return f"Les Faits | {now.astimezone(PARIS):%Y-%m-%d} | {slot}"


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout


def list_campaigns(client: Brevo, *, status: str | None = None) -> list[dict[str, Any]]:
    campaigns: list[dict[str, Any]] = []
    offset = 0
    while True:
        params: dict[str, Any] = {
            "type": "classic",
            "limit": 100,
            "offset": offset,
            "sort": "desc",
        }
        if status:
            params["status"] = status
        data = client.json("GET", "/emailCampaigns", params=params)
        batch = data.get("campaigns") or []
        if not isinstance(batch, list):
            raise RuntimeError("Brevo campagnes: liste invalide")
        campaigns.extend(x for x in batch if isinstance(x, dict))
        if len(batch) < 100:
            return campaigns
        offset += 100


def find_campaign(client: Brevo, name: str) -> dict[str, Any] | None:
    for campaign in list_campaigns(client):
        if campaign.get("name") == name:
            return campaign
    return None


def latest_sent_campaign_time(client: Brevo) -> dt.datetime | None:
    latest: dt.datetime | None = None
    for campaign in list_campaigns(client, status="sent"):
        if campaign.get("tag") != CAMPAIGN_TAG:
            continue
        sent = parse_iso(campaign.get("sentDate") or campaign.get("scheduledAt"))
        if sent and (latest is None or sent > latest):
            latest = sent
    return latest


def recent_article_slugs(since: dt.datetime | None) -> list[str]:
    if since is None:
        since = dt.datetime.now(PARIS) - dt.timedelta(hours=30)
    since_utc = since.astimezone(dt.timezone.utc).isoformat(timespec="seconds")
    output = _git(
        "log",
        f"--since={since_utc}",
        "--name-only",
        "--diff-filter=A",
        "--pretty=format:",
        "--",
        "articles/",
    )
    slugs: list[str] = []
    for raw in output.splitlines():
        line = raw.strip()
        if not (line.startswith("articles/") and line.endswith(".html")):
            continue
        slug = Path(line).stem
        if slug and slug not in slugs:
            slugs.append(slug)
    return slugs


def load_articles(slugs: list[str]) -> list[dict[str, Any]]:
    if not SEARCH_JSON.exists():
        raise RuntimeError(f"{SEARCH_JSON.relative_to(ROOT)} absent")
    try:
        raw = json.loads(SEARCH_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("data/search.json invalide") from exc
    if not isinstance(raw, list):
        raise RuntimeError("data/search.json doit contenir une liste")
    index = {
        str(item.get("slug") or ""): item
        for item in raw
        if isinstance(item, dict) and item.get("slug")
    }
    articles = [index[slug] for slug in slugs if slug in index]
    missing = [slug for slug in slugs if slug not in index]
    if missing:
        raise RuntimeError(
            f"{len(missing)} nouvel article absent de search.json; envoi annulé pour ne rien perdre"
        )
    return articles


def boolish(value: Any) -> bool:
    if value is True or value == 1:
        return True
    return str(value or "").strip().lower() in {"1", "true", "yes", "oui", "on"}


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
    chosen = tuple(
        cat for cat in CATEGORIES if boolish(attrs.get(f"CAT_{cat.upper()}"))
    )
    return chosen or CATEGORIES


def unsubscribed_from(contact: dict[str, Any], *list_ids: int) -> bool:
    if boolish(contact.get("emailBlacklisted")):
        return True
    raw = contact.get("listUnsubscribed") or []
    try:
        unsubscribed = {int(x) for x in raw}
    except (TypeError, ValueError):
        unsubscribed = set()
    return any(int(list_id) in unsubscribed for list_id in list_ids)


def get_contacts_from_list(client: Brevo, list_id: int) -> list[dict[str, Any]]:
    contacts: list[dict[str, Any]] = []
    offset = 0
    while True:
        data = client.json(
            "GET",
            f"/contacts/lists/{list_id}/contacts",
            params={"limit": 500, "offset": offset, "sort": "asc"},
        )
        batch = data.get("contacts") or []
        if not isinstance(batch, list):
            raise RuntimeError("Brevo contacts: liste invalide")
        contacts.extend(x for x in batch if isinstance(x, dict))
        if len(batch) < 500:
            return contacts
        offset += 500


def ensure_contact_attributes(client: Brevo) -> None:
    required = {"FREQ": "text"}
    required.update({f"CAT_{cat.upper()}": "boolean" for cat in CATEGORIES})

    def read() -> dict[str, str]:
        data = client.json("GET", "/contacts/attributes")
        return {
            str(item.get("name") or "").upper(): str(item.get("type") or "").lower()
            for item in data.get("attributes") or []
            if isinstance(item, dict)
        }

    attrs = read()
    for name, expected_type in required.items():
        if name in attrs:
            continue
        client.request(
            "POST",
            f"/contacts/attributes/normal/{name}",
            expected=(200, 201, 204),
            payload={"type": expected_type},
        )
        print(f"[BREVO] Attribut {name} créé automatiquement ({expected_type}).")

    attrs = read()
    missing = [name for name in required if name not in attrs]
    wrong = [
        f"{name}={attrs[name]}"
        for name, expected in required.items()
        if name in attrs and attrs[name] != expected
    ]
    if missing or wrong:
        detail = []
        if missing:
            detail.append("absents: " + ", ".join(missing))
        if wrong:
            detail.append("types incorrects: " + ", ".join(wrong))
        raise RuntimeError(
            "Configuration Brevo invalide (" + " ; ".join(detail) + "). "
            "FREQ doit être un texte et les CAT_* des booléens."
        )


def get_or_create_delivery_list(client: Brevo, main_list_id: int) -> int:
    offset = 0
    while True:
        data = client.json(
            "GET", "/contacts/lists", params={"limit": 50, "offset": offset, "sort": "desc"}
        )
        lists = data.get("lists") or []
        for item in lists:
            if isinstance(item, dict) and item.get("name") == DELIVERY_LIST_NAME:
                return int(item["id"])
        if len(lists) < 50:
            break
        offset += 50

    main = client.json("GET", f"/contacts/lists/{main_list_id}")
    folder_id = int(main["folderId"])
    created = client.json(
        "POST",
        "/contacts/lists",
        expected=(200, 201),
        payload={"name": DELIVERY_LIST_NAME, "folderId": folder_id},
    )
    list_id = int(created["id"])
    print(f"[BREVO] Liste technique créée: {list_id}")
    return list_id


def wait_process(client: Brevo, process_id: Any, timeout_seconds: int = 90) -> None:
    if not process_id:
        return
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        info = client.json("GET", f"/processes/{int(process_id)}")
        status = str(info.get("status") or "").lower()
        if status == "completed":
            return
        if status in {"failed", "error", "cancelled"}:
            raise RuntimeError(f"Processus Brevo {process_id} terminé en échec ({status})")
        time.sleep(2)
    raise RuntimeError(f"Processus Brevo {process_id} non terminé après {timeout_seconds}s")


def chunks(values: list[str], size: int = 100) -> list[list[str]]:
    return [values[i:i + size] for i in range(0, len(values), size)]


def remove_from_list(client: Brevo, list_id: int, emails: list[str]) -> None:
    for batch in chunks(emails):
        data = client.json(
            "POST",
            f"/contacts/lists/{list_id}/contacts/remove",
            expected=(200, 201, 202, 204),
            payload={"emails": batch},
        )
        wait_process(client, data.get("processId"))
        failed = data.get("failure") or []
        if failed:
            raise RuntimeError(f"Retrait liste incomplet: {len(failed)} échec(s)")


def add_to_list(client: Brevo, list_id: int, emails: list[str]) -> None:
    for batch in chunks(emails):
        data = client.json(
            "POST",
            f"/contacts/lists/{list_id}/contacts/add",
            expected=(200, 201, 202),
            payload={"emails": batch},
        )
        wait_process(client, data.get("processId"))
        failed = data.get("failure") or []
        if failed:
            raise RuntimeError(f"Ajout liste incomplet: {len(failed)} échec(s)")


def sync_delivery_list(
    client: Brevo,
    delivery_list_id: int,
    target_emails: list[str],
) -> None:
    target = {email.lower() for email in target_emails}
    current_contacts = get_contacts_from_list(client, delivery_list_id)

    current_active: set[str] = set()
    protected_unsubscribed: set[str] = set()
    for contact in current_contacts:
        email = str(contact.get("email") or "").strip().lower()
        if not email:
            continue
        if unsubscribed_from(contact, delivery_list_id):
            protected_unsubscribed.add(email)
        else:
            current_active.add(email)

    # Ne jamais retirer les contacts désabonnés de la liste technique :
    # Brevo conserve ainsi leur désabonnement spécifique à cette liste.
    to_remove = sorted(current_active - target)
    to_add = sorted(target - current_active - protected_unsubscribed)

    if to_remove:
        remove_from_list(client, delivery_list_id, to_remove)
    if to_add:
        add_to_list(client, delivery_list_id, to_add)

    # Vérification finale : les actifs doivent être exactement la cible moins
    # les contacts qui ont explicitement refusé cette liste.
    for attempt in range(3):
        final_contacts = get_contacts_from_list(client, delivery_list_id)
        final_active = {
            str(c.get("email") or "").strip().lower()
            for c in final_contacts
            if c.get("email") and not unsubscribed_from(c, delivery_list_id)
        }
        expected = target - protected_unsubscribed
        if final_active == expected:
            print(
                f"[BREVO] Liste de diffusion alignée: {len(final_active)} actif(s), "
                f"{len(protected_unsubscribed)} désabonné(s) conservé(s)"
            )
            return
        time.sleep(2 ** attempt)
    missing = sorted(expected - final_active)
    extra = sorted(final_active - expected)
    raise RuntimeError(
        f"Liste de diffusion incohérente après synchronisation "
        f"(manquants={len(missing)}, excédents={len(extra)})"
    )


def _article_html(article: dict[str, Any], category: str) -> str:
    slug = quote(str(article.get("slug") or ""), safe="-")
    title = html.escape(str(article.get("titre") or "Article sans titre"))
    excerpt = html.escape(str(article.get("excerpt") or "")[:260])
    label = html.escape(CAT_LABELS[category])
    color = CAT_COLORS[category]
    url = (
        f"{SITE_BASE}/articles/{slug}.html?utm_source=newsletter"
        f"&utm_medium=email&utm_campaign=digest"
    )
    return f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
<tr><td style="padding:0 0 28px;">
<div style="font-family:Arial,Helvetica,sans-serif;font-size:10px;font-weight:700;
letter-spacing:2px;color:{color};text-transform:uppercase;margin-bottom:9px;">{label}</div>
<h2 style="font-family:Georgia,Times New Roman,serif;font-size:20px;font-weight:normal;
color:#262422;margin:0 0 9px;line-height:1.4;">{title}</h2>
<p style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#625f5b;
line-height:1.65;margin:0 0 14px;">{excerpt}</p>
<a href="{url}" style="font-family:Arial,Helvetica,sans-serif;font-size:13px;
font-weight:700;color:{color};text-decoration:none;">Lire l’article&nbsp;→</a>
</td></tr>
<tr><td style="border-top:1px solid #e5e1da;height:24px;font-size:0;line-height:0;">&nbsp;</td></tr>
</table>"""


def _section_html(category: str, articles: list[dict[str, Any]]) -> str:
    return "".join(_article_html(article, category) for article in articles)


def build_email(
    articles_by_category: dict[str, list[dict[str, Any]]],
    *,
    now: dt.datetime,
    slot: str,
) -> str:
    conditional: list[str] = []
    all_sections: list[str] = []
    for category in CATEGORIES:
        articles = articles_by_category.get(category) or []
        if not articles:
            continue
        section = _section_html(category, articles)
        conditional.append(
            f"{{% if contact.CAT_{category.upper()} %}}\n{section}\n{{% endif %}}"
        )
        all_sections.append(section)

    has_any = " or ".join(f"contact.CAT_{cat.upper()}" for cat in CATEGORIES)
    content = (
        f"{{% if {has_any} %}}\n{''.join(conditional)}\n"
        f"{{% else %}}\n{''.join(all_sections)}\n{{% endif %}}"
    )
    total = sum(len(items) for items in articles_by_category.values())
    category_count = sum(1 for items in articles_by_category.values() if items)
    greeting = "Bonjour" if slot == "matin" else "Bonsoir"
    intro = (
        "Voici les nouveaux articles publiés depuis votre précédent digest, "
        "classés selon les rubriques que vous avez choisies."
    )
    preview = html.escape(
        f"{total} nouvel{'s' if total > 1 else ''} article{'s' if total > 1 else ''} "
        f"dans votre sélection Les Faits."
    )
    date_text = html.escape(date_longue(now))
    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="x-apple-disable-message-reformatting">
<title>Les Faits — {date_text}</title>
</head>
<body style="margin:0;padding:0;background:#f0ede6;-webkit-text-size-adjust:100%;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">{preview}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
 style="background:#f0ede6;">
<tr><td align="center" style="padding:30px 12px 48px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"
 style="width:100%;max-width:600px;">
<tr><td style="background:#0b0f17;border-radius:10px 10px 0 0;padding:32px 36px 27px;">
<div style="font-family:Georgia,Times New Roman,serif;font-size:31px;line-height:1;color:#fff;">
<span style="font-weight:400;">les</span><span style="font-weight:700;">faits</span>
</div>
<p style="font-family:Arial,Helvetica,sans-serif;font-size:12px;color:#aab2c0;
margin:18px 0 5px;letter-spacing:.04em;">Votre sélection du {date_text}</p>
<p style="font-family:Arial,Helvetica,sans-serif;font-size:10px;color:#7f8998;margin:0;
letter-spacing:.12em;text-transform:uppercase;">{total} article{'s' if total > 1 else ''} ·
{category_count} rubrique{'s' if category_count > 1 else ''}</p>
</td></tr>
<tr><td style="background:#fff;padding:28px 36px 22px;border-bottom:1px solid #e8e3db;">
<p style="font-family:Georgia,Times New Roman,serif;font-size:16px;color:#262422;
line-height:1.7;margin:0;">{greeting},</p>
<p style="font-family:Georgia,Times New Roman,serif;font-size:15px;color:#4a4744;
line-height:1.7;margin:12px 0 0;">{intro}</p>
</td></tr>
<tr><td style="background:#fff;padding:26px 36px 4px;">{content}</td></tr>
<tr><td style="background:#fff;padding:0 36px 34px;text-align:center;">
<a href="{SITE_BASE}/?utm_source=newsletter&utm_medium=email"
style="font-family:Arial,Helvetica,sans-serif;font-size:13px;color:#375a9e;
text-decoration:none;font-weight:700;">Voir tous les articles sur lesfaits.info →</a>
</td></tr>
<tr><td style="background:#0b0f17;border-radius:0 0 10px 10px;padding:22px 30px;">
<p style="font-family:Arial,Helvetica,sans-serif;font-size:11px;color:#9aa3b1;
margin:0 0 9px;line-height:1.55;text-align:center;">
Vous recevez cet email parce que vous avez confirmé votre inscription à Les Faits.
</p>
<p style="font-family:Arial,Helvetica,sans-serif;font-size:11px;margin:0;text-align:center;">
<a href="{{{{ unsubscribe }}}}" style="color:#c7d4f0;text-decoration:underline;">Se désabonner</a>
&nbsp;·&nbsp;
<a href="{SITE_BASE}/confidentialite.html" style="color:#9aa3b1;text-decoration:none;">Vie privée</a>
</p>
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""


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
    if existing:
        status = str(existing.get("status") or "").lower()
        campaign_id = int(existing["id"])
        if status in SUCCESS_CAMPAIGN_STATUSES:
            return campaign_id, status
        if status not in {"draft", ""}:
            raise RuntimeError(
                f"Campagne {campaign_id} déjà présente avec le statut inattendu {status!r}"
            )
        client.request(
            "PUT",
            f"/emailCampaigns/{campaign_id}",
            expected=(200, 204),
            payload={
                "subject": subject,
                "sender": {"name": BREVO_SENDER_NAME, "email": BREVO_SENDER_EMAIL},
                "htmlContent": html_content,
                "recipients": {"listIds": [list_id]},
                "previewText": preview_text,
                "tag": CAMPAIGN_TAG,
            },
        )
        return campaign_id, "draft"

    data = client.json(
        "POST",
        "/emailCampaigns",
        expected=(200, 201),
        payload={
            "name": name,
            "subject": subject,
            "sender": {"name": BREVO_SENDER_NAME, "email": BREVO_SENDER_EMAIL},
            "htmlContent": html_content,
            "recipients": {"listIds": [list_id]},
            "previewText": preview_text,
            "tag": CAMPAIGN_TAG,
            "replyTo": BREVO_SENDER_EMAIL,
        },
    )
    return int(data["id"]), "draft"


def send_and_confirm(client: Brevo, campaign_id: int) -> str:
    client.request(
        "POST",
        f"/emailCampaigns/{campaign_id}/sendNow",
        expected=(200, 201, 202, 204),
    )
    deadline = time.monotonic() + 75
    last = ""
    while time.monotonic() < deadline:
        info = client.json(
            "GET",
            f"/emailCampaigns/{campaign_id}",
            params={"excludeHtmlContent": "true"},
        )
        last = str(info.get("status") or "").lower()
        if last in SUCCESS_CAMPAIGN_STATUSES:
            return last
        if last in {"archive", "cancelled"}:
            break
        time.sleep(3)
    raise RuntimeError(
        f"Campagne {campaign_id} non confirmée après envoi (statut={last or 'inconnu'})"
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
            continue
        if not wants_slot(contact, slot):
            stats["wrong_slot"] += 1
            continue
        if not (set(contact_categories(contact)) & active_categories):
            stats["no_matching_category"] += 1
            continue
        recipients.append(email)
    return sorted(recipients), stats


def validate_environment() -> int:
    missing = [
        name for name, value in (
            ("BREVO_API_KEY", BREVO_API_KEY),
            ("BREVO_LIST_ID", BREVO_LIST_ID),
            ("BREVO_SENDER_EMAIL", BREVO_SENDER_EMAIL),
        )
        if not value
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
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Valider/créer les attributs et la liste technique Brevo sans envoyer.",
    )
    parser.add_argument("--now", help="ISO 8601, uniquement pour les tests/reprises contrôlées")
    args = parser.parse_args(argv)

    now = parse_iso(args.now) if args.now else dt.datetime.now(PARIS)
    if now is None:
        raise RuntimeError("--now doit être une date ISO 8601 valide")

    main_list_id = validate_environment()
    client = Brevo(BREVO_API_KEY)
    ensure_contact_attributes(client)
    if args.check_config:
        delivery_list_id = get_or_create_delivery_list(client, main_list_id)
        print(
            f"[CONFIG NEWSLETTER] Attributs valides, liste principale={main_list_id}, "
            f"liste de diffusion={delivery_list_id}."
        )
        return 0
    if not args.slot:
        parser.error("--slot est obligatoire hors --check-config")

    name = campaign_name(now, args.slot)
    existing = find_campaign(client, name)
    if existing and str(existing.get("status") or "").lower() in SUCCESS_CAMPAIGN_STATUSES:
        print(
            f"[IDEMPOTENCE] {name} existe déjà "
            f"(id={existing.get('id')}, statut={existing.get('status')}) — aucun doublon."
        )
        return 0

    last_sent = latest_sent_campaign_time(client)
    slugs = recent_article_slugs(last_sent)
    articles = load_articles(slugs)
    by_category: dict[str, list[dict[str, Any]]] = {}
    for article in articles:
        category = str(article.get("categorie") or "")
        if category in CATEGORIES:
            by_category.setdefault(category, []).append(article)

    if not by_category:
        print("[NEWSLETTER] Aucun nouvel article éligible depuis le précédent envoi.")
        return 0

    html_content = build_email(by_category, now=now, slot=args.slot)
    PREVIEW_HTML.write_text(html_content, encoding="utf-8")
    print(
        f"[NEWSLETTER] {sum(map(len, by_category.values()))} article(s), "
        f"{len(by_category)} rubrique(s), aperçu: {PREVIEW_HTML.name}"
    )
    if args.dry_run:
        print("[DRY-RUN] Aucun contact modifié, aucune campagne envoyée.")
        return 0

    delivery_list_id = get_or_create_delivery_list(client, main_list_id)
    contacts = get_contacts_from_list(client, main_list_id)
    recipients, stats = build_recipients(
        contacts,
        main_list_id=main_list_id,
        delivery_list_id=delivery_list_id,
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
        print("[NEWSLETTER] Aucun destinataire éligible — aucun envoi.")
        return 0

    sync_delivery_list(client, delivery_list_id, recipients)
    subject = (
        f"Les Faits — votre sélection du {date_longue(now)} "
        f"({'matin' if args.slot == 'matin' else 'soir'})"
    )
    preview_text = (
        f"{sum(map(len, by_category.values()))} nouvel"
        f"{'s' if sum(map(len, by_category.values())) > 1 else ''} article"
        f"{'s' if sum(map(len, by_category.values())) > 1 else ''} dans votre sélection."
    )
    campaign_id, status = upsert_campaign(
        client,
        name=name,
        subject=subject,
        html_content=html_content,
        list_id=delivery_list_id,
        preview_text=preview_text,
    )
    if status in SUCCESS_CAMPAIGN_STATUSES:
        print(f"[IDEMPOTENCE] Campagne {campaign_id} déjà {status} — aucun renvoi.")
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
