#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Normalise la newsletter v6.

Objectifs :
- restaurer Matin / Soir / Les deux et les six rubriques ;
- conserver un POST HTML natif vers Brevo, sans clé API dans le navigateur ;
- envoyer la réponse technique Brevo dans une iframe cachée afin que le lecteur
  reste sur Les Faits au lieu d'atterrir sur une page JSON ;
- garder le consentement local obligatoire et les blocs article dédupliqués ;
- aligner systématiquement le cache-busting HTML sur la version du script navigateur.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import harden_newsletter as legacy

ROOT = Path(__file__).resolve().parent.parent
VERSION = "6"
SCRIPT_RE = re.compile(r'/src/newsletter\.js(?:\?[^"\']*)?', re.I)
SCRIPT_SRC = f"/src/newsletter.js?v={VERSION}"
FORM_URL = legacy.FORM_URL
FORM_HOST = legacy.FORM_HOST
FRAME_NAME = "lf-newsletter-sink"

FORM_OPEN_RE = re.compile(r'<form\b(?=[^>]*\bid=(["\'])nl-form\1)[^>]*>', re.I)
ROW_RE = re.compile(
    r'<div\b[^>]*class=(["\'])[^"\']*\bnl-compact__row\b[^"\']*\1[^>]*>',
    re.I,
)
CONSENT_LABEL_RE = re.compile(
    r'<label\b[^>]*class=(["\'])[^"\']*\bnl-compact__consent\b[^"\']*\1[^>]*>',
    re.I,
)
CONSENT_INPUT_RE = re.compile(r'<input\b(?=[^>]*\bid=(["\'])nl-consent\1)[^>]*>', re.I)
MESSAGE_RE = re.compile(r'<p\b(?=[^>]*\bid=(["\'])nl-msg\1)[^>]*>', re.I)
FREQ_BLOCK_RE = re.compile(
    r'\s*<div\b[^>]*class=(["\'])[^"\']*\bnl-compact__freq\b[^"\']*\1[^>]*>.*?</div>',
    re.I | re.S,
)
CATS_BLOCK_RE = re.compile(
    r'\s*<div\b[^>]*class=(["\'])[^"\']*\bnl-compact__cats\b[^"\']*\1[^>]*>.*?</div>',
    re.I | re.S,
)
HINT_RE = re.compile(
    r'\s*<p\b(?=[^>]*class=(["\'])[^"\']*\bnl-compact__hint\b[^"\']*\1)'
    r'(?![^>]*data-newsletter-noscript)[^>]*>.*?</p>',
    re.I | re.S,
)
SINK_RE = re.compile(
    rf'<iframe\b(?=[^>]*\bname=(["\']){re.escape(FRAME_NAME)}\1)[^>]*>\s*</iframe>',
    re.I | re.S,
)

FREQ_BLOCK = '''<div class="nl-compact__freq" role="group" aria-label="Fréquence de réception">
        <label class="nl-compact__freq-opt"><input type="radio" name="LF_FREQ" value="morning"/> Matin (~7h)</label>
        <label class="nl-compact__freq-opt"><input type="radio" name="LF_FREQ" value="evening"/> Soir (~18h)</label>
        <label class="nl-compact__freq-opt"><input type="radio" name="LF_FREQ" value="both" checked/> Les deux</label>
      </div>'''

CATS_BLOCK = '''<div class="nl-compact__cats" role="group" aria-label="Rubriques à recevoir">
        <label class="nl-compact__cat nl-cat--societe"><input type="checkbox" data-brevo-name="CAT_SOCIETE" value="1"/><span class="nl-cat__dot" aria-hidden="true"></span>Société</label>
        <label class="nl-compact__cat nl-cat--science"><input type="checkbox" data-brevo-name="CAT_SCIENCE" value="1"/><span class="nl-cat__dot" aria-hidden="true"></span>Science</label>
        <label class="nl-compact__cat nl-cat--economie"><input type="checkbox" data-brevo-name="CAT_ECONOMIE" value="1"/><span class="nl-cat__dot" aria-hidden="true"></span>Économie</label>
        <label class="nl-compact__cat nl-cat--tech"><input type="checkbox" data-brevo-name="CAT_TECH" value="1"/><span class="nl-cat__dot" aria-hidden="true"></span>Tech</label>
        <label class="nl-compact__cat nl-cat--sante"><input type="checkbox" data-brevo-name="CAT_SANTE" value="1"/><span class="nl-cat__dot" aria-hidden="true"></span>Santé</label>
        <label class="nl-compact__cat nl-cat--environnement"><input type="checkbox" data-brevo-name="CAT_ENVIRONNEMENT" value="1"/><span class="nl-cat__dot" aria-hidden="true"></span>Environnement</label>
      </div>'''

CANONICAL_HINT = (
    '<p class="nl-compact__hint" id="nl-hint">Choisissez vos rubriques. '
    'Aucune sélection = toutes les rubriques.</p>'
)
SINK_HTML = (
    f'<iframe name="{FRAME_NAME}" title="Réponse d\'inscription newsletter" '
    'hidden aria-hidden="true"></iframe>'
)

CATEGORY_FIELDS = (
    "CAT_SOCIETE",
    "CAT_SCIENCE",
    "CAT_ECONOMIE",
    "CAT_TECH",
    "CAT_SANTE",
    "CAT_ENVIRONNEMENT",
)
BREVO_POST_FIELDS = frozenset({
    "EMAIL",
    "LESFAITS_VERIFICATION",
    "email_address_check",
    "locale",
    "FREQ",
    *CATEGORY_FIELDS,
})
HIDDEN_FIELDS = (
    ("LESFAITS_VERIFICATION", "1"),
    ("email_address_check", ""),
    ("locale", "fr"),
    ("FREQ", "both"),
    *((name, "0") for name in CATEGORY_FIELDS),
)

OLD_ARTICLE_COPY = "Chaque soir, les articles du jour en un email. Gratuit. Sans pub."
NEW_ARTICLE_COPY = "Les nouvelles éditions, matin et soir, en un email par créneau. Gratuit. Sans pub."
ARTICLE_NL_BLOCK = (
    '<div class="newsletter-block"><div><div class="newsletter-block__label">NEWSLETTER</div>'
    '<div class="newsletter-block__text"><strong>Le résumé du jour dans votre boîte mail</strong>'
    f'<span>{NEW_ARTICLE_COPY}</span></div></div>'
    '<a class="newsletter-block__btn" href="/#newsletter">S\'abonner →</a></div>'
)
ARTICLE_NL_DUPLICATES_RE = re.compile(
    rf'({re.escape(ARTICLE_NL_BLOCK)})(?:\s*{re.escape(ARTICLE_NL_BLOCK)})+', re.S
)


def _dedupe_article_newsletter_blocks(html: str) -> str:
    return ARTICLE_NL_DUPLICATES_RE.sub(r"\1", html)


def _remove_attr(tag: str, name: str) -> str:
    pattern = re.compile(
        rf'\s+{re.escape(name)}(?:\s*=\s*(["\']).*?\1|\s*=\s*[^\s>]+)?',
        re.I | re.S,
    )
    return pattern.sub("", tag)


def _local_consent(html: str) -> str:
    return CONSENT_INPUT_RE.sub(lambda m: _remove_attr(m.group(0), "name"), html)


def _preferences_are_canonical(html: str) -> bool:
    freq_ok = all(
        f'name="LF_FREQ" value="{value}"' in html
        for value in ("morning", "evening", "both")
    )
    cats_ok = all(f'data-brevo-name="{name}"' in html for name in CATEGORY_FIELDS)
    return freq_ok and cats_ok and CANONICAL_HINT in html


def _ensure_preferences_ui(html: str) -> str:
    if _preferences_are_canonical(html):
        return html

    html = FREQ_BLOCK_RE.sub("", html)
    html = CATS_BLOCK_RE.sub("", html)
    html = HINT_RE.sub("", html, count=1)

    opening = FORM_OPEN_RE.search(html)
    if not opening:
        return html

    row = ROW_RE.search(html, opening.end())
    if row:
        pos = row.start()
        html = html[:pos] + "      " + FREQ_BLOCK + "\n      " + html[pos:]
    else:
        pos = opening.end()
        html = html[:pos] + "\n      " + FREQ_BLOCK + html[pos:]

    opening = FORM_OPEN_RE.search(html)
    consent_label = CONSENT_LABEL_RE.search(html, opening.end() if opening else 0)
    message = MESSAGE_RE.search(html, opening.end() if opening else 0)
    form_end = html.find("</form>", opening.end() if opening else 0)
    if consent_label:
        pos = consent_label.start()
    elif message:
        pos = message.start()
    elif form_end != -1:
        pos = form_end
    else:
        return html
    payload = "      " + CATS_BLOCK + "\n      " + CANONICAL_HINT + "\n      "
    return html[:pos] + payload + html[pos:]


def _remove_hidden_field(html: str, name: str) -> str:
    pattern = re.compile(
        rf'<input\b(?=[^>]*\btype=(["\'])hidden\1)(?=[^>]*\bname=(["\']){re.escape(name)}\2)[^>]*?/?>\s*',
        re.I | re.S,
    )
    return pattern.sub("", html)


def _ensure_native_form(html: str) -> str:
    if not FORM_OPEN_RE.search(html):
        return html

    for name, _ in HIDDEN_FIELDS:
        html = _remove_hidden_field(html, name)

    def repl(match: re.Match[str]) -> str:
        tag = match.group(0)
        tag = legacy._set_attr(tag, "data-newsletter-version", VERSION)
        tag = legacy._set_attr(tag, "action", FORM_URL)
        tag = legacy._set_attr(tag, "method", "post")
        tag = legacy._set_attr(tag, "enctype", "application/x-www-form-urlencoded")
        tag = legacy._set_attr(tag, "target", FRAME_NAME)
        return tag

    html = FORM_OPEN_RE.sub(repl, html, count=1)
    opening = FORM_OPEN_RE.search(html)
    if not opening:
        return html

    hidden = "\n      ".join(
        f'<input type="hidden" name="{name}" value="{value}"/>'
        for name, value in HIDDEN_FIELDS
    )
    html = html[:opening.end()] + "\n      " + hidden + "\n      " + html[opening.end():].lstrip()

    sinks = list(SINK_RE.finditer(html))
    if len(sinks) != 1:
        html = SINK_RE.sub("", html)
        opening = FORM_OPEN_RE.search(html)
        form_end = html.find("</form>", opening.end() if opening else 0)
        if form_end != -1:
            insert_at = form_end + len("</form>")
            html = html[:insert_at] + "\n      " + SINK_HTML + html[insert_at:]
    return html


def _ensure_brevo_csp(html: str) -> str:
    """Autorise le POST et le chargement de sa réponse dans l'iframe cachée."""
    if not FORM_OPEN_RE.search(html):
        return html
    allowed = f"https://{FORM_HOST}"

    def replace(match: re.Match[str]) -> str:
        directives: list[tuple[str, list[str]]] = []
        for raw in re.sub(r"\s+", " ", match.group(4)).strip().split(";"):
            parts = raw.strip().split()
            if parts:
                directives.append((parts[0], parts[1:]))

        for wanted, include_self in (("form-action", True), ("frame-src", True)):
            found = False
            for i, (name, values) in enumerate(directives):
                if name.lower() != wanted:
                    continue
                found = True
                if include_self and "'self'" not in values:
                    values.insert(0, "'self'")
                if allowed not in values:
                    values.append(allowed)
                directives[i] = (name, values)
                break
            if not found:
                values = ["'self'", allowed] if include_self else [allowed]
                directives.append((wanted, values))

        rendered = "; ".join(" ".join([name, *values]) for name, values in directives) + ";"
        return f"{match.group(1)}{match.group(3)}{rendered}{match.group(3)}{match.group(5)}"

    if legacy.CSP_META_RE.search(html):
        return legacy.CSP_META_RE.sub(replace, html, count=1)
    return html


def upgrade_html(html: str) -> str:
    html = html.replace(OLD_ARTICLE_COPY, NEW_ARTICLE_COPY)
    html = _dedupe_article_newsletter_blocks(html)
    html = SCRIPT_RE.sub(SCRIPT_SRC, html)
    if not FORM_OPEN_RE.search(html):
        return html
    html = _local_consent(html)
    html = _ensure_preferences_ui(html)
    html = _ensure_native_form(html)
    html = _ensure_brevo_csp(html)
    return html


def harden_html(html: str) -> str:
    if f'data-newsletter-version="{VERSION}"' in html and SCRIPT_SRC in html:
        return upgrade_html(html)
    return upgrade_html(legacy.harden_html(html))


def _csp_allows_directive(html: str, directive: str) -> bool:
    csp = legacy.CSP_META_RE.search(html)
    if not csp:
        return False
    allowed = f"https://{FORM_HOST}"
    for raw in csp.group(4).split(";"):
        parts = raw.strip().split()
        if parts and parts[0].lower() == directive.lower():
            return allowed in parts[1:]
    return False


def _csp_allows_native_post(html: str) -> bool:
    return _csp_allows_directive(html, "form-action")


def _csp_allows_hidden_response(html: str) -> bool:
    return _csp_allows_directive(html, "frame-src")


def _named_form_fields(html: str) -> set[str]:
    opening = FORM_OPEN_RE.search(html)
    if not opening:
        return set()
    end = html.find("</form>", opening.end())
    if end == -1:
        return set()
    block = html[opening.end():end]
    names = {
        m.group(2)
        for m in re.finditer(
            r'<(?:input|select|textarea|button)\b[^>]*\bname=(["\'])([^"\']+)\1',
            block,
            re.I | re.S,
        )
    }
    return {name for name in names if not name.startswith("LF_")}


def validate_v3(path: Path, html: str) -> list[str]:
    errors: list[str] = []
    has_form = bool(FORM_OPEN_RE.search(html))
    script_count = len(re.findall(re.escape(SCRIPT_SRC), html, re.I))
    if "</head>" in html and script_count != 1:
        errors.append(f"script newsletter v{VERSION} présent {script_count} fois")
    if OLD_ARTICLE_COPY in html:
        errors.append("ancien rythme uniquement du soir encore affiché")
    if ARTICLE_NL_DUPLICATES_RE.search(html):
        errors.append("bloc newsletter article dupliqué")
    if not has_form:
        return errors

    required_fragments = (
        f'data-newsletter-version="{VERSION}"',
        'name="LF_FREQ" value="morning"',
        'name="LF_FREQ" value="evening"',
        'name="LF_FREQ" value="both"',
        CANONICAL_HINT,
        f'target="{FRAME_NAME}"',
        f'name="{FRAME_NAME}"',
        'data-newsletter-noscript="1"',
        f'action="{FORM_URL}"',
        'method="post"',
        'enctype="application/x-www-form-urlencoded"',
    )
    for fragment in required_fragments:
        if fragment not in html:
            errors.append(f"élément newsletter v{VERSION} absent : " + fragment[:80])
    for name in CATEGORY_FIELDS:
        if f'data-brevo-name="{name}"' not in html:
            errors.append(f"rubrique {name} absente")
    if re.search(r'<input\b(?=[^>]*\bid=(["\'])nl-consent\1)(?=[^>]*\bname=)[^>]*>', html, re.I):
        errors.append("consentement envoyé comme attribut Brevo")
    if not _csp_allows_native_post(html):
        errors.append("CSP form-action n'autorise pas Brevo")
    if not _csp_allows_hidden_response(html):
        errors.append("CSP frame-src n'autorise pas la réponse Brevo cachée")

    fields = _named_form_fields(html)
    if fields != BREVO_POST_FIELDS:
        missing = sorted(BREVO_POST_FIELDS - fields)
        extra = sorted(fields - BREVO_POST_FIELDS)
        details = []
        if missing:
            details.append("manquants=" + ",".join(missing))
        if extra:
            details.append("inconnus=" + ",".join(extra))
        errors.append("contrat POST newsletter non exact (" + "; ".join(details) + ")")
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
    print(f"[NEWSLETTER V{VERSION}] {checked} page(s) contrôlée(s), {changed} page(s) mise(s) à jour.")
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
