# -*- coding: utf-8 -*-
"""Contrôle en lecture seule le formulaire d'inscription hébergé par Brevo.

Le site envoie ses préférences directement vers ce formulaire public. Créer les
attributs dans le compte Brevo ne suffit pas : le formulaire publié doit aussi
contenir les champs correspondants, sinon l'interface Les Faits promettrait une
personnalisation que Brevo pourrait ignorer.

Ce script ne soumet rien et ne manipule aucun contact. Il télécharge seulement
la page publique, inventorie les champs de formulaire et échoue explicitement
si le contrat attendu n'est plus présent.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Iterable

import requests

from harden_newsletter import FORM_URL

CATEGORIES = (
    "SOCIETE",
    "SCIENCE",
    "ECONOMIE",
    "TECH",
    "SANTE",
    "ENVIRONNEMENT",
)
REQUIRED_FIELDS = frozenset({
    "EMAIL",
    "FREQ",
    "LESFAITS_VERIFICATION",
    *(f"CAT_{category}" for category in CATEGORIES),
})


@dataclass
class FormSnapshot:
    fields: set[str] = field(default_factory=set)
    form_count: int = 0
    methods: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)


class _FormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.snapshot = FormSnapshot()
        self._form_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {str(key).lower(): value for key, value in attrs}
        if tag.lower() == "form":
            self.snapshot.form_count += 1
            self._form_depth += 1
            self.snapshot.methods.append(str(attr.get("method") or "get").lower())
            self.snapshot.actions.append(str(attr.get("action") or ""))
            return
        if self._form_depth and tag.lower() in {"input", "select", "textarea", "button"}:
            name = str(attr.get("name") or "").strip()
            if name:
                self.snapshot.fields.add(name)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "form" and self._form_depth:
            self._form_depth -= 1


def parse_form(html: str) -> FormSnapshot:
    parser = _FormParser()
    parser.feed(html)
    parser.close()
    return parser.snapshot


def validate_snapshot(
    snapshot: FormSnapshot,
    required_fields: Iterable[str] = REQUIRED_FIELDS,
) -> None:
    if snapshot.form_count < 1:
        raise RuntimeError("Le formulaire Brevo public ne contient aucune balise <form>.")
    if "post" not in snapshot.methods:
        raise RuntimeError(
            "Le formulaire Brevo public n'expose aucun formulaire en méthode POST."
        )
    missing = sorted(set(required_fields) - snapshot.fields)
    if missing:
        raise RuntimeError(
            "Le formulaire Brevo publié ne collecte pas tous les champs affichés "
            "sur Les Faits. Champs absents : " + ", ".join(missing)
        )


def audit_form(url: str = FORM_URL, timeout: int = 25) -> FormSnapshot:
    response = requests.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; LesFaits-Newsletter-Audit/3.0)",
            "Accept": "text/html,application/xhtml+xml",
        },
        timeout=timeout,
        allow_redirects=True,
    )
    if not 200 <= response.status_code < 400:
        raise RuntimeError(
            f"Formulaire Brevo inaccessible : HTTP {response.status_code}."
        )
    content_type = str(response.headers.get("content-type") or "").lower()
    if "html" not in content_type and "<form" not in response.text.lower():
        raise RuntimeError(
            f"Réponse Brevo inattendue ({content_type or 'type inconnu'})."
        )
    if len(response.text) < 500:
        raise RuntimeError("Réponse Brevo anormalement courte.")

    snapshot = parse_form(response.text)
    validate_snapshot(snapshot)
    print(
        f"[BREVO FORM] HTTP {response.status_code}; {snapshot.form_count} formulaire(s); "
        f"{len(snapshot.fields)} champ(s); contrat newsletter complet."
    )
    print("[BREVO FORM] Champs contrôlés : " + ", ".join(sorted(REQUIRED_FIELDS)))
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=FORM_URL)
    parser.add_argument("--timeout", type=int, default=25)
    args = parser.parse_args()
    if not 5 <= args.timeout <= 60:
        raise RuntimeError("--timeout doit être compris entre 5 et 60 secondes")
    audit_form(args.url, args.timeout)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[ERREUR FORMULAIRE BREVO] {exc}")
        raise SystemExit(1)
