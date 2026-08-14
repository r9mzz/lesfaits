#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compatibilité Brevo pour les comptes qui refusent l'option ``tag``.

Le moteur historique conserve les tags lorsqu'ils sont autorisés. Si Brevo
refuse *explicitement* cette seule option lors de la création/mise à jour d'une
campagne, on rejoue l'opération sans ``tag``. L'idempotence des déploiements
publics reste assurée par le nom de campagne qui contient le SHA du déploiement.
Aucune autre erreur Brevo n'est masquée ou rejouée.
"""
from __future__ import annotations

from typing import Any, Callable

import generer_digest as digest
import run_newsletter

_TAG_CAPABILITY_MARKER = "not allowed to avail tag option for your campaign"


def _upsert_without_tag(
    client: digest.Brevo,
    *,
    name: str,
    subject: str,
    html_content: str,
    list_id: int,
    preview_text: str,
) -> tuple[int, str]:
    existing = digest.find_campaign(client, name)
    if existing:
        status = str(existing.get("status") or "").lower()
        campaign_id = int(existing["id"])
        if status in digest.SUCCESS_CAMPAIGN_STATUSES:
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
                "sender": {"name": digest.BREVO_SENDER_NAME, "email": digest.BREVO_SENDER_EMAIL},
                "htmlContent": html_content,
                "recipients": {"listIds": [list_id]},
                "previewText": preview_text,
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
            "sender": {"name": digest.BREVO_SENDER_NAME, "email": digest.BREVO_SENDER_EMAIL},
            "htmlContent": html_content,
            "recipients": {"listIds": [list_id]},
            "previewText": preview_text,
            "replyTo": digest.BREVO_SENDER_EMAIL,
        },
    )
    return int(data["id"]), "draft"


def _tag_compatible_upsert(
    original: Callable[..., tuple[int, str]],
) -> Callable[..., tuple[int, str]]:
    def wrapped(client: digest.Brevo, **kwargs: Any) -> tuple[int, str]:
        try:
            return original(client, **kwargs)
        except RuntimeError as exc:
            if _TAG_CAPABILITY_MARKER not in str(exc).lower():
                raise
            print(
                "[BREVO] Option tag indisponible pour ce compte ; "
                "nouvelle tentative sans tag."
            )
            return _upsert_without_tag(client, **kwargs)

    return wrapped


def main(argv: list[str] | None = None) -> int:
    original = digest.upsert_campaign
    digest.upsert_campaign = _tag_compatible_upsert(original)
    try:
        return run_newsletter.main(argv)
    finally:
        digest.upsert_campaign = original


if __name__ == "__main__":
    raise SystemExit(main())
