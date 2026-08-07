#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Durcit et normalise le formulaire newsletter dans toutes les pages HTML.

Le site utilise une navigation douce : un visiteur peut arriver sur un article
puis ouvrir l'accueil sans recharger les scripts du document. Le gestionnaire
newsletter doit donc être chargé sur toutes les pages, alors que le formulaire
n'est présent que sur certaines d'entre elles.

Ce script est volontairement idempotent. Il :
- retire l'ancien JS inline qui annonçait un succès malgré une réponse opaque ;
- charge le gestionnaire unique /src/newsletter.js ;
- normalise les attributs d'accessibilité du formulaire ;
- garde un lien utilisable sans JavaScript ;
- autorise explicitement le domaine Brevo dans la CSP des pages concernées ;
- refuse silencieusement aucune anomalie : le mode --check échoue si une page
  newsletter reste dans un état incohérent.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
FORM_URL = (
    "https://e6ad0381.sibforms.com/serve/"
    "MUIFAErfidn3h7DoaZcjIRh-48s1GoiE0vZOe_KG-skCwDznnQ2831i0IkHsSaXfUJ15hBl1CH3ElJVKdGDdXdxHpt6v7iX-hAlyWb0i0M7mtq6UhgJ9JJyCUhNwckwfxW8EUJkF_hkjb4qX8YSntlFraZFiCcgQhZ3PXsPvAcSa9oEyPOgeL1EtAB4akgMS-hz76NcGAUSqOt3L1w=="
)
FORM_HOST = urlparse(FORM_URL).netloc
SCRIPT_SRC = "/src/newsletter.js?v=2"
SCRIPT_TAG = f'<script src="{SCRIPT_SRC}" defer></script>'
NOSCRIPT = (
    '<noscript><p class="nl-compact__hint" data-newsletter-noscript="1">'
    f'JavaScript est désactivé. <a href="{FORM_URL}" rel="noopener noreferrer">'
    'Ouvrir le formulaire sécurisé Brevo</a>.</p></noscript>'
)

SCRIPT_BLOCK_RE = re.compile(r"<script\b[^>]*>.*?</script\s*>", re.I | re.S)
CSP_META_RE = re.compile(
    r'(<meta\b[^>]*http-equiv=(["\'])Content-Security-Policy\2[^>]*content=)'
    r'(["\'])(.*?)\3([^>]*>)',
    re.I | re.S,
)
FORM_OPEN_RE = re.compile(r'<form\b(?=[^>]*\bid=(["\'])nl-form\1)[^>]*>', re.I)
EMAIL_INPUT_RE = re.compile(r'<input\b(?=[^>]*\bid=(["\'])nl-email\1)[^>]*>', re.I)
CONSENT_INPUT_RE = re.compile(r'<input\b(?=[^>]*\bid=(["\'])nl-consent\1)[^>]*>', re.I)
MESSAGE_RE = re.compile(r'<p\b(?=[^>]*\bid=(["\'])nl-msg\1)[^>]*>', re.I)


def _set_attr(tag: str, name: str, value: str | None = None) -> str:
    """Ajoute ou remplace un attribut HTML simple dans une balise ouvrante."""
    pattern = re.compile(rf'\s+{re.escape(name)}(?:\s*=\s*(["\']).*?\1)?', re.I | re.S)
    rendered = f' {name}' if value is None else f' {name}="{value}"'
    if pattern.search(tag):
        return pattern.sub(rendered, tag, count=1)
    closing = "/>" if tag.rstrip().endswith("/>") else ">"
    pos = tag.rfind(closing)
    if pos == -1:
        return tag
    return tag[:pos] + rendered + tag[pos:]


def _remove_old_inline_newsletter_js(html: str) -> str:
    def replace(match: re.Match[str]) -> str:
        block = match.group(0)
        markers = (
            "SIB_URL=" in block
            and "LESFAITS_VERIFICATION" in block
            and ("nl-form" in block or "nl-email" in block)
        )
        return "" if markers else block

    return SCRIPT_BLOCK_RE.sub(replace, html)


def _ensure_single_external_script(html: str) -> str:
    # Supprime les anciennes versions et les doublons avant d'insérer la version
    # canonique une seule fois.
    html = re.sub(
        r'\s*<script\b[^>]*src=(["\'])/src/newsletter\.js(?:\?[^"\']*)?\1[^>]*>\s*</script\s*>\s*',
        "\n",
        html,
        flags=re.I,
    )
    if "</head>" in html:
        before, after = html.split("</head>", 1)
        return before.rstrip() + f"\n  {SCRIPT_TAG}\n</head>" + after
    return html


def _ensure_csp(html: str) -> str:
    if 'id="nl-form"' not in html and "id='nl-form'" not in html:
        return html

    def replace(match: re.Match[str]) -> str:
        content = re.sub(r"\s+", " ", match.group(4)).strip()
        directives: list[tuple[str, list[str]]] = []
        for raw in content.split(";"):
            raw = raw.strip()
            if not raw:
                continue
            parts = raw.split()
            directives.append((parts[0], parts[1:]))

        found = False
        for i, (name, values) in enumerate(directives):
            if name.lower() != "connect-src":
                continue
            found = True
            if f"https://{FORM_HOST}" not in values:
                values.append(f"https://{FORM_HOST}")
            directives[i] = (name, values)
            break
        if not found:
            insert_at = next(
                (i for i, (name, _) in enumerate(directives)
                 if name.lower() in {"base-uri", "form-action", "frame-ancestors"}),
                len(directives),
            )
            directives.insert(insert_at, ("connect-src", ["'self'", f"https://{FORM_HOST}"]))

        rendered = "; ".join(
            " ".join([name, *values]).strip() for name, values in directives
        ) + ";"
        return f"{match.group(1)}{match.group(3)}{rendered}{match.group(3)}{match.group(5)}"

    if CSP_META_RE.search(html):
        return CSP_META_RE.sub(replace, html, count=1)
    # Une page avec formulaire mais sans CSP ne reçoit pas une politique partielle
    # improvisée : la validation signalera le manque pour correction manuelle.
    return html


def _enhance_form(html: str) -> str:
    if 'id="nl-form"' not in html and "id='nl-form'" not in html:
        return html

    def form_repl(match: re.Match[str]) -> str:
        tag = match.group(0)
        tag = _set_attr(tag, "data-newsletter-version", "2")
        tag = _set_attr(tag, "aria-label", "Inscription à la newsletter Les Faits")
        tag = _set_attr(tag, "novalidate")
        return tag

    def email_repl(match: re.Match[str]) -> str:
        tag = match.group(0)
        attrs = {
            "name": "EMAIL",
            "type": "email",
            "autocomplete": "email",
            "inputmode": "email",
            "autocapitalize": "none",
            "spellcheck": "false",
            "aria-label": "Adresse email",
            "aria-describedby": "nl-msg nl-hint",
            "required": None,
        }
        for name, value in attrs.items():
            tag = _set_attr(tag, name, value)
        return tag

    def consent_repl(match: re.Match[str]) -> str:
        tag = match.group(0)
        tag = _set_attr(tag, "name", "CONSENT")
        tag = _set_attr(tag, "required")
        tag = _set_attr(tag, "aria-required", "true")
        return tag

    def message_repl(match: re.Match[str]) -> str:
        tag = match.group(0)
        tag = _set_attr(tag, "role", "status")
        tag = _set_attr(tag, "aria-live", "polite")
        tag = _set_attr(tag, "aria-atomic", "true")
        return tag

    html = FORM_OPEN_RE.sub(form_repl, html)
    html = EMAIL_INPUT_RE.sub(email_repl, html)
    html = CONSENT_INPUT_RE.sub(consent_repl, html)
    html = MESSAGE_RE.sub(message_repl, html)

    html = re.sub(r"Matin\s*\(~?\s*(?:7|8)h(?:00)?\s*\)", "Édition du matin", html)
    html = re.sub(r"Soir\s*\(~?\s*(?:18|20)h(?:30)?\s*\)", "Édition du soir", html)
    html = html.replace(
        '<p class="nl-compact__hint">Aucune sélection = toutes les rubriques.</p>',
        '<p class="nl-compact__hint" id="nl-hint">Choisissez vos rubriques, '
        'ou laissez tout décoché pour tout recevoir.</p>',
    )
    html = html.replace(
        "<span>J'accepte de recevoir la newsletter et la "
        '<a href="confidentialite.html">politique de confidentialité</a>.</span>',
        "<span>J’accepte de recevoir la newsletter Les Faits. "
        '<a href="/confidentialite.html">Politique de confidentialité</a>. '
        "Désabonnement possible à tout moment.</span>",
    )

    # Un unique fallback juste après le formulaire. Le formulaire Brevo hébergé
    # reste utile si JS est coupé ; il n'est jamais embarqué en iframe.
    section_start = html.find('<section class="nl-compact"')
    if section_start != -1:
        section_end = html.find("</section>", section_start)
        if section_end != -1:
            block = html[section_start:section_end]
            if 'data-newsletter-noscript="1"' not in block:
                form_end = html.find("</form>", section_start, section_end)
                if form_end != -1:
                    insert_at = form_end + len("</form>")
                    html = html[:insert_at] + "\n      " + NOSCRIPT + html[insert_at:]
    return html


def harden_html(text: str) -> str:
    text = _remove_old_inline_newsletter_js(text)
    text = _enhance_form(text)
    text = _ensure_csp(text)
    text = _ensure_single_external_script(text)
    return text


def html_paths(root: Path) -> list[Path]:
    ignored = {".git", ".venv", "venv", "node_modules"}
    paths: list[Path] = []
    for path in root.rglob("*.html"):
        if any(part in ignored for part in path.parts):
            continue
        if path.name == "newsletter-preview.html":
            continue
        paths.append(path)
    return sorted(paths)


def validate_page(path: Path, html: str) -> list[str]:
    errors: list[str] = []
    script_count = len(re.findall(r'/src/newsletter\.js(?:\?[^"\']*)?', html, re.I))
    if "</head>" in html and script_count != 1:
        errors.append(f"script newsletter présent {script_count} fois")
    for block in SCRIPT_BLOCK_RE.findall(html):
        if "SIB_URL=" in block and "LESFAITS_VERIFICATION" in block:
            errors.append("ancien gestionnaire inline encore présent")
            break

    has_form = bool(re.search(r'\bid=(["\'])nl-form\1', html, re.I))
    if has_form:
        if 'data-newsletter-version="2"' not in html:
            errors.append("formulaire non normalisé")
        if 'data-newsletter-noscript="1"' not in html:
            errors.append("fallback sans JavaScript absent")
        if f"https://{FORM_HOST}" not in html:
            errors.append("domaine Brevo absent")
        csp = CSP_META_RE.search(html)
        if not csp or f"https://{FORM_HOST}" not in csp.group(4):
            errors.append("CSP connect-src Brevo absente")
        if "Un email de confirmation vient de vous être envoyé" in html:
            errors.append("ancien faux message de succès encore présent")
    return errors


def run(root: Path, *, check_only: bool = False) -> dict[str, int]:
    changed = 0
    checked = 0
    failures: list[str] = []
    for path in html_paths(root):
        original = path.read_text(encoding="utf-8", errors="replace")
        updated = harden_html(original)
        checked += 1
        if not check_only and updated != original:
            path.write_text(updated, encoding="utf-8")
            changed += 1
        current = original if check_only else updated
        for error in validate_page(path, current):
            failures.append(f"{path.relative_to(root)}: {error}")

    if failures:
        preview = "\n".join(f"  - {line}" for line in failures[:30])
        suffix = "" if len(failures) <= 30 else f"\n  … {len(failures) - 30} autre(s)"
        raise RuntimeError(f"Audit newsletter en échec:\n{preview}{suffix}")

    print(
        f"[NEWSLETTER HTML] {checked} page(s) contrôlée(s), "
        f"{changed} page(s) mise(s) à jour."
    )
    return {"checked": checked, "changed": changed}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    run(args.root.resolve(), check_only=args.check)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[ERREUR NEWSLETTER HTML] {exc}", file=sys.stderr)
        raise SystemExit(1)
