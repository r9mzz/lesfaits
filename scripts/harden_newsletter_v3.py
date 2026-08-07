#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Passe finale newsletter v3.

Le formulaire Brevo public ne collecte actuellement que l'adresse et le
marqueur d'inscription. Cette passe conserve le durcissement historique, puis
retire des pages les choix de fréquence/rubriques qui n'étaient pas enregistrés.
Les contacts possédant déjà des préférences explicites continuent d'être gérés
par le moteur d'envoi ; les nouvelles inscriptions reçoivent par défaut les
éditions du matin et du soir avec toutes les rubriques.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import harden_newsletter as legacy

ROOT = Path(__file__).resolve().parent.parent
SCRIPT_V2_RE = re.compile(
    r'/src/newsletter\.js(?:\?v=2|\?[^"\']*)?', re.I
)
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
CANONICAL_HINT = (
    '<p class="nl-compact__hint" id="nl-hint">Éditions du matin et du soir, '
    'uniquement lorsqu’il y a de nouveaux articles. Toutes les rubriques sont incluses.</p>'
)
OLD_ARTICLE_COPY = (
    "Chaque soir, les articles du jour en un email. Gratuit. Sans pub."
)
NEW_ARTICLE_COPY = (
    "Les nouvelles éditions, matin et soir, en un email par créneau. Gratuit. Sans pub."
)


def upgrade_html(html: str) -> str:
    html = html.replace(OLD_ARTICLE_COPY, NEW_ARTICLE_COPY)
    if 'id="nl-form"' not in html and "id='nl-form'" not in html:
        return html.replace("/src/newsletter.js?v=2", "/src/newsletter.js?v=3")

    html = FREQ_BLOCK_RE.sub("", html)
    html = CATS_BLOCK_RE.sub("", html)
    html = HINT_RE.sub(CANONICAL_HINT, html, count=1)
    html = re.sub(
        r'data-newsletter-version=(["\'])2\1',
        'data-newsletter-version="3"',
        html,
        flags=re.I,
    )
    html = SCRIPT_V2_RE.sub("/src/newsletter.js?v=3", html)
    return html


def harden_html(html: str) -> str:
    return upgrade_html(legacy.harden_html(html))


def validate_v3(path: Path, html: str) -> list[str]:
    errors: list[str] = []
    has_form = bool(re.search(r'\bid=(["\'])nl-form\1', html, re.I))
    script_count = len(re.findall(r'/src/newsletter\.js\?v=3', html, re.I))
    if "</head>" in html and script_count != 1:
        errors.append(f"script newsletter v3 présent {script_count} fois")
    if OLD_ARTICLE_COPY in html:
        errors.append("ancien rythme uniquement du soir encore affiché")
    if not has_form:
        return errors

    if 'data-newsletter-version="3"' not in html:
        errors.append("formulaire non marqué v3")
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
        raise RuntimeError(f"Audit newsletter v3 en échec:\n{preview}{suffix}")

    print(
        f"[NEWSLETTER V3] {checked} page(s) contrôlée(s), "
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
        print(f"[ERREUR NEWSLETTER V3] {exc}")
        raise SystemExit(1)
