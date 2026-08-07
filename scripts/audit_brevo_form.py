# -*- coding: utf-8 -*-
"""Contrôle en lecture seule le formulaire d'inscription hébergé par Brevo.

Le formulaire public Les Faits transmet uniquement les champs dont le contrat
Brevo est vérifié. Ce script ne soumet rien et ne manipule aucun contact : il
télécharge seulement la page publique, inventorie les formulaires/champs et
vérifie aussi que la cible POST réellement publiée par Brevo correspond à
l'URL utilisée par Les Faits.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Iterable
from urllib.parse import urljoin, urlparse

import requests

from harden_newsletter import FORM_URL

REQUIRED_FIELDS = frozenset({
    "EMAIL",
    "LESFAITS_VERIFICATION",
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


def _same_form_endpoint(left: str, right: str) -> bool:
    """Compare l'origine et le chemin d'une cible, sans dépendre d'un querystring."""
    a = urlparse(left)
    b = urlparse(right)
    return (
        a.scheme.lower() == b.scheme.lower() == "https"
        and a.netloc.lower() == b.netloc.lower()
        and a.path.rstrip("/") == b.path.rstrip("/")
    )


def resolved_post_actions(snapshot: FormSnapshot, base_url: str = FORM_URL) -> list[str]:
    actions: list[str] = []
    for method, action in zip(snapshot.methods, snapshot.actions):
        if method != "post":
            continue
        actions.append(urljoin(base_url, action or base_url))
    return actions


def validate_snapshot(
    snapshot: FormSnapshot,
    required_fields: Iterable[str] = REQUIRED_FIELDS,
    base_url: str = FORM_URL,
) -> None:
    if snapshot.form_count < 1:
        raise RuntimeError("Le formulaire Brevo public ne contient aucune balise <form>.")

    post_actions = resolved_post_actions(snapshot, base_url)
    if not post_actions:
        raise RuntimeError(
            "Le formulaire Brevo public n'expose aucun formulaire en méthode POST."
        )

    if not any(_same_form_endpoint(action, base_url) for action in post_actions):
        raise RuntimeError(
            "La cible POST publiée par Brevo ne correspond plus à l'URL utilisée "
            "par Les Faits. Cible(s) observée(s) : " + ", ".join(post_actions)
        )

    missing = sorted(set(required_fields) - snapshot.fields)
    if missing:
        raise RuntimeError(
            "Le formulaire Brevo publié ne collecte plus les données minimales "
            "utilisées par Les Faits. Champs absents : " + ", ".join(missing)
        )


def audit_form(url: str = FORM_URL, timeout: int = 25) -> FormSnapshot:
    response = requests.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; LesFaits-Newsletter-Audit/4.0)",
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
    validate_snapshot(snapshot, base_url=response.url)
    actions = resolved_post_actions(snapshot, response.url)
    print(
        f"[BREVO FORM] HTTP {response.status_code}; {snapshot.form_count} formulaire(s); "
        f"{len(snapshot.fields)} champ(s); contrat minimal complet."
    )
    print("[BREVO FORM] Champs publiés : " + ", ".join(sorted(snapshot.fields)))
    print("[BREVO FORM] Cible(s) POST : " + ", ".join(actions))
    print("[BREVO FORM] Aucun formulaire soumis; audit GET uniquement.")
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
