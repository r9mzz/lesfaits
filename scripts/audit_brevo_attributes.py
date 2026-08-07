#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audit en lecture seule des attributs Brevo utilisés par la newsletter.

Ne lit aucun contact et ne modifie rien. Le script ne journalise jamais la clé
API ; il affiche seulement le nom et le type des attributs explicitement
attendus par Les Faits.
"""
from __future__ import annotations

import os
import sys

import requests

NAMES = (
    "LESFAITS_VERIFICATION",
    "FREQ",
    "CAT_SOCIETE",
    "CAT_SCIENCE",
    "CAT_ECONOMIE",
    "CAT_TECH",
    "CAT_SANTE",
    "CAT_ENVIRONNEMENT",
)


def main() -> int:
    api_key = os.environ.get("BREVO_API_KEY", "").strip()
    if not api_key:
        print("[BREVO ATTR] audit ignoré : BREVO_API_KEY indisponible dans ce contexte.")
        return 0

    response = requests.get(
        "https://api.brevo.com/v3/contacts/attributes",
        headers={"api-key": api_key, "Accept": "application/json"},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    attrs = {
        str(item.get("name") or "").upper(): str(item.get("type") or "").lower()
        for item in payload.get("attributes", [])
        if str(item.get("name") or "").upper() in NAMES
    }
    missing = [name for name in NAMES if name not in attrs]
    for name in NAMES:
        print(f"[BREVO ATTR] {name}={attrs.get(name, 'ABSENT')}")
    if missing:
        print("[BREVO ATTR] attribut(s) absent(s) : " + ", ".join(missing))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[BREVO ATTR] échec lecture seule : {exc}", file=sys.stderr)
        raise SystemExit(1)
