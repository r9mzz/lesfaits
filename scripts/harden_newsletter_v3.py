#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Passe finale newsletter v4.

Le formulaire Les Faits ne simule plus un succès via ``fetch(..., no-cors)``.
Les pages sont préparées pour une vraie soumission HTML POST directement vers
le formulaire Brevo public, avec l'encodage natif d'un formulaire navigateur.
Brevo affiche ainsi lui-même le résultat réel de l'inscription ou une erreur.

Cette passe conserve également la normalisation v3 : les préférences de
fréquence/rubriques non collectées par le formulaire Brevo ne sont pas montrées
aux nouveaux abonnés et les blocs newsletter article restent dédupliqués.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import harden_newsletter as legacy

ROOT = Path(__file__).resolve().parent.parent
VERSION = "4"
SCRIPT_RE = re.compile(r'/src/newsletter\.js(?:\?[^"\']*)?', re.I)
SCRIPT_SRC = f"/src/newsletter.js?v={VERSION}"
FORM_URL = legacy.FORM_URL
FORM_HOST = legacy.FORM_HOST

FREQ_BLOCK_RE = re.compile(
    r'\s*<div\b[^>]*class=(["\'])[^"\']*\bnl-compact__freq\b[^"\']*\1[^>]*>.*?</div>',
    re.I | re.S,
)
CATS_BLOCK_RE = re.compile(
    r'\s*<div\b[^>]*class=(["\'])[^"\']*\bnl-compact__cats\b[^"\']*\1[^>]*>.*?</div>',
    re.I | re.S,
)
HINT_RE = re.compile(
    r'<p\b(?=[^>]*class=(["\'])[^"\']*\bnl-compact__hint\b[^"\']*\1)'
    r'(?![^>]*data-newsletter-noscript)[^>]*>.*?</p>',
    re.I | re.S,
)
FORM_OPEN_RE = re.compile(r'<form\b(?=[^>]*\bid=(["\'])nl-form\1)[^>]*>', re.I)
CONSENT_INPUT_RE = re.compile(r'<input\b(?=[^>]*\bid=(["\'])nl-consent\1)[^>]*>', re.I)
CANONICAL_HINT = (
    '<p class="nl-compact__hint" id="nl-hint">Éditions du matin et du soir, '
    'uniquement lorsqu’il y a de nouveaux articles. Toutes les rubriques sont incluses.</p>'
)
OLD_ARTICLE_COPY = "Chaque soir, les articles du jour en un email. Gratuit. Sans pub."
NEW_ARTICLE_COPY = (
    "Les nouvelles éditions, matin et soir, en un email par créneau. Gratuit. Sans pub."
)
ARTICLE_NL_BLOCK = (
    '<div class="newsletter-block"><div><div class="newsletter-block__label">NEWSLETTER</div>'
    '<div class="newsletter-block__text"><strong>Le résumé du jour dans votre boîte mail</strong>'
    f'<span>{NEW_ARTICLE_COPY}</span></div></div>'
    '<a class="newsletter-block__btn" href="/#newsletter">S\'abonner →</a></div>'
)
ARTICLE_NL_DUPLICATES_RE = re.compile(
    rf'({re.escape(ARTICLE_NL_BLOCK)})(?:\s*{re.escape(ARTICLE_NL_BLOCK)})+',
    re.S,
)

# Contrat observé sur le formulaire Brevo hébergé : ces quatre champs seulement.
BREVO_POST_FIELDS = frozenset({
    "EMAIL",
    "LESFAITS_VERIFICATION",
    "email_address_check",
    "locale",
})
HIDDEN_FIELDS = (
    ("LESFAITS_VERIFICATION", "1"),
    ("email_address_check", ""),
    ("locale", "fr"),
)


def _dedupe_article_newsletter_blocks(html: str) -> str:
    return ARTICLE_NL_DUPLICATES_RE.sub(r"\1", html)


def _remove_attr(tag: str, name: str) -> str:
    pattern = re.compile(
        rf'\s+{re.escape(name)}(?:\s*=\s*(["\']).*?\1|\s*=\s*[^\s>]+)?',
        re.I | re.S,
    )
    return pattern.sub("", tag)


def _keep_consent_local_only(html: str) -> str:
    """Le consentement reste obligatoire localement mais n'est pas posté à Brevo."""
    def repl(match: re.Match[str]) -> str:
        return _remove_attr(match.group(0), "name")

    return CONSENT_INPUT_RE.sub(repl, html)


def _ensure_native_form(html: str) -> str:
    if 'id="nl-form"' not in html and "id='nl-form'" not in html:
        return html

    def repl(match: re.Match[str]) -> str:
        tag = match.group(0)
        tag = legacy._set_attr(tag, "data-newsletter-version", VERSION)
        tag = legacy._set_attr(tag, "action", FORM_URL)
        tag = legacy._set_attr(tag, "method", "post")
        tag = legacy._set_attr(tag, "enctype", "application/x-www-form-urlencoded")
        return tag

    html = FORM_OPEN_RE.sub(repl, html, count=1)

    opening = FORM_OPEN_RE.search(html)
    if not opening:
        return html

    hidden = []
    for name, value in HIDDEN_FIELDS:
        if not re.search(rf'\bname=(["\']){re.escape(name)}\1', html, re.I):
            hidden.append(
                f'<input type="hidden" name="{name}" value="{value}"/>'
            )
    if hidden:
        insert_at = opening.end()
        html = html[:insert_at] + "\n      " + "\n      ".join(hidden) + html[insert_at:]
    return html


def _ensure_form_action_csp(html: str) -> str:
    if 'id="nl-form"' not in html and "id='nl-form'" not in html:
        return html

    allowed = f"https://{FORM_HOST}"

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
            if name.lower() != "form-action":
                continue
            found = True
            if "'self'" not in values:
                values.insert(0, "'self'")
            if allowed not in values:
                values.append(allowed)
            directives[i] = (name, values)
            break
        if not found:
            directives.append(("form-action", ["'self'", allowed]))

        rendered = "; ".join(
            " ".join([name, *values]).strip() for name, values in directives
        ) + ";"
        return f"{match.group(1)}{match.group(3)}{rendered}{match.group(3)}{match.group(5)}"

    if legacy.CSP_META_RE.search(html):
        return legacy.CSP_META_RE.sub(replace, html, count=1)
    return html


def upgrade_html(html: str) -> str:
    html = html.replace(OLD_ARTICLE_COPY, NEW_ARTICLE_COPY)
    html = _dedupe_article_newsletter_blocks(html)
    html = SCRIPT_RE.sub(SCRIPT_SRC, html)

    if 'id="nl-form"' not in html and "id='nl-form'" not in html:
        return html

    html = FREQ_BLOCK_RE.sub("", html)
    html = CATS_BLOCK_RE.sub("", html)
    html = HINT_RE.sub(CANONICAL_HINT, html, count=1)
    html = re.sub(
        r'data-newsletter-version=(["\'])\d+\1',
        f'data-newsletter-version="{VERSION}"',
        html,
        flags=re.I,
    )
    html = _keep_consent_local_only(html)
    html = _ensure_native_form(html)
    html = _ensure_form_action_csp(html)
    return html


def harden_html(html: str) -> str:
    return upgrade_html(legacy.harden_html(html))


def _csp_allows_native_post(html: str) -> bool:
    csp = legacy.CSP_META_RE.search(html)
    if not csp:
        return False
    content = csp.group(4)
    allowed = f"https://{FORM_HOST}"
    for raw in content.split(";"):
        parts = raw.strip().split()
        if parts and parts[0].lower() == "form-action":
            return allowed in parts[1:]
    return False


def _named_form_fields(html: str) -> set[str]:
    opening = FORM_OPEN_RE.search(html)
    if not opening:
        return set()
    end = html.find("</form>", opening.end())
    if end == -1:
        return set()
    block = html[opening.end():end]
    return {
        match.group(2)
        for match in re.finditer(
            r'<(?:input|select|textarea|button)\b[^>]*\bname=(["\'])([^"\']+)\1',
            block,
            re.I | re.S,
        )
    }


def validate_v3(path: Path, html: str) -> list[str]:
    errors: list[str] = []
    has_form = bool(re.search(r'\bid=(["\'])nl-form\1', html, re.I))
    script_count = len(re.findall(re.escape(SCRIPT_SRC), html, re.I))
    if "</head>" in html and script_count != 1:
        errors.append(f"script newsletter v{VERSION} présent {script_count} fois")
    if OLD_ARTICLE_COPY in html:
        errors.append("ancien rythme uniquement du soir encore affiché")
    if ARTICLE_NL_DUPLICATES_RE.search(html):
        errors.append("bloc newsletter article dupliqué")
    if not has_form:
        return errors

    if f'data-newsletter-version="{VERSION}"' not in html:
        errors.append(f"formulaire non marqué v{VERSION}")
    if re.search(r'\bname=(["\'])FREQ\1', html, re.I):
        errors.append("choix de fréquence non pris en charge encore visible")
    if re.search(r'\bname=(["\'])CAT_[A-Z_]+\1', html, re.I):
        errors.append("choix de rubrique non pris en charge encore visible")
    if "Choisissez vos rubriques" in html or "Aucune sélection" in html:
        errors.append("ancienne promesse de personnalisation encore visible")
    if CANONICAL_HINT not in html:
        errors.append("rythme matin et soir non expliqué")
    if 'data-newsletter-noscript="1"' not in html:
        errors.append("fallback sans JavaScript absent")
    if f'action="{FORM_URL}"' not in html:
        errors.append("action Brevo native absente")
    if not re.search(r'<form\b[^>]*\bmethod=(["\'])post\1', html, re.I):
        errors.append("méthode POST native absente")
    if 'enctype="application/x-www-form-urlencoded"' not in html:
        errors.append("encodage formulaire natif absent")
    for name, _value in HIDDEN_FIELDS:
        if not re.search(rf'\bname=(["\']){re.escape(name)}\1', html, re.I):
            errors.append(f"champ Brevo {name} absent")
    if not _csp_allows_native_post(html):
        errors.append("CSP form-action n'autorise pas Brevo")

    fields = _named_form_fields(html)
    if fields != BREVO_POST_FIELDS:
        missing = sorted(BREVO_POST_FIELDS - fields)
        extra = sorted(fields - BREVO_POST_FIELDS)
        details = []
        if missing:
            details.append("manquants=" + ",".join(missing))
        if extra:
            details.append("inconnus=" + ",".join(extra))
        errors.append("contrat POST Brevo non exact (" + "; ".join(details) + ")")
    return errors


def run(root: Path, *, check_only: bool = False) -> dict[str, int]:
    checked = changed = 0
    failures: list[str] = []
    for path in legacy.html_paths(root):
        original = path.read_text(encoding="utf-8", errors="replace")
        updated = harden_html(original)
        checked += 1
        if not check_only and updated != original:
            path.write_text(updated, encoding="utf-8")
            changed += 1
        current = original if check_only else updated
        for error in validate_v3(path, current):
            failures.append(f"{path.relative_to(root)}: {error}")

    if failures:
        preview = "\n".join(f"  - {line}" for line in failures[:30])
        suffix = "" if len(failures) <= 30 else f"\n  … {len(failures) - 30} autre(s)"
        raise RuntimeError(f"Audit newsletter v{VERSION} en échec:\n{preview}{suffix}")

    print(
        f"[NEWSLETTER V{VERSION}] {checked} page(s) contrôlée(s), "
        f"{changed} page(s) mise(s) à jour."
    )
    return {"checked": checked, "changed": changed}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    run(args.root.resolve(), check_only=args.check)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[ERREUR NEWSLETTER V{VERSION}] {exc}")
        raise SystemExit(1)
