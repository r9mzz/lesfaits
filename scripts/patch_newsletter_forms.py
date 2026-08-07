# -*- coding: utf-8 -*-
"""Fiabilise les formulaires newsletter statiques avant déploiement.

Le site est hébergé sur GitHub Pages : il ne peut pas lire la réponse du
formulaire Brevo à cause de la politique cross-origin. L'ancien JavaScript
utilisait donc ``fetch(..., mode='no-cors')`` et annonçait toujours qu'un email
de confirmation avait été envoyé, même lorsque Brevo refusait la requête.

La correction utilise un vrai POST HTML vers la page Brevo dans un nouvel
onglet. Le lecteur voit ainsi la réponse réelle de Brevo (succès, adresse déjà
inscrite ou erreur), tandis que la page Les Faits reste ouverte. Le script est
idempotent et s'applique aux pages racine et aux catégories reconstruites.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

SIB_URL = (
    "https://e6ad0381.sibforms.com/serve/"
    "MUIFAErfidn3h7DoaZcjIRh-48s1GoiE0vZOe_KG-skCwDznnQ2831i0IkHsSaXfUJ15hBl1CH3ElJVKdGDdXdxHpt6v7iX-hAlyWb0i0M7mtq6UhgJ9JJyCUhNwckwfxW8EUJkF_hkjb4qX8YSntlFraZFiCcgQhZ3PXsPvAcSa9oEyPOgeL1EtAB4akgMS-hz76NcGAUSqOt3L1w=="
)
MARKER = "LF_NEWSLETTER_NATIVE_V2"

FORM_RE = re.compile(r'<form\b[^>]*\bid=["\']nl-form["\'][^>]*>', re.I)
OLD_SCRIPT_RE = re.compile(
    r'<script>\s*\(function\(\)\{\s*var\s+SIB_URL=.*?</script>',
    re.I | re.S,
)
HIDDEN_RE = re.compile(
    r'\s*<input\b[^>]*\bname=["\'](?:LESFAITS_VERIFICATION|email_address_check|locale)["\'][^>]*\s*/?>',
    re.I,
)

HIDDEN_FIELDS = """
      <input type="hidden" name="LESFAITS_VERIFICATION" value="1"/>
      <input type="hidden" name="email_address_check" value=""/>
      <input type="hidden" name="locale" value="fr"/>"""

NEW_SCRIPT = f"""<script>
/* {MARKER} */
(function(){{
  var form=document.getElementById("nl-form");
  if(!form||form.dataset.lfNewsletterReady==="1")return;
  form.dataset.lfNewsletterReady="1";
  var msgEl=document.getElementById("nl-msg");
  var btn=document.getElementById("nl-btn");
  var emailEl=document.getElementById("nl-email");
  var consentEl=document.getElementById("nl-consent");
  form.addEventListener("submit",function(e){{
    if(msgEl){{msgEl.className="nl-compact__msg";msgEl.textContent="";}}
    var email=(emailEl&&emailEl.value||"").trim();
    var valid=/^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$/.test(email);
    if(!valid){{
      e.preventDefault();
      if(msgEl){{msgEl.textContent="Veuillez saisir une adresse email valide.";msgEl.className="nl-compact__msg nl-compact__msg--err";}}
      if(emailEl)emailEl.focus();
      return;
    }}
    if(!consentEl||!consentEl.checked){{
      e.preventDefault();
      if(msgEl){{msgEl.textContent="Veuillez accepter la politique de confidentialité.";msgEl.className="nl-compact__msg nl-compact__msg--err";}}
      if(consentEl)consentEl.focus();
      return;
    }}
    if(msgEl){{
      msgEl.textContent="La page sécurisée Brevo va s’ouvrir pour confirmer la demande. L’inscription ne sera active qu’après validation de l’email reçu.";
      msgEl.className="nl-compact__msg nl-compact__msg--ok";
    }}
    if(btn){{
      btn.disabled=true;
      btn.textContent="Ouverture…";
      window.setTimeout(function(){{btn.disabled=false;btn.textContent="S'abonner →";}},2500);
    }}
  }});
}})();
</script>"""


def _form_tag() -> str:
    return (
        f'<form id="nl-form" action="{SIB_URL}" method="post" '
        'target="_blank" novalidate>'
    )


def patch_html(html: str) -> tuple[str, bool]:
    """Retourne ``(html, modifié)`` et refuse les états ambigus."""
    if 'id="nl-form"' not in html and "id='nl-form'" not in html:
        return html, False

    original = html
    forms = FORM_RE.findall(html)
    if len(forms) != 1:
        raise ValueError(f"page newsletter ambiguë : {len(forms)} formulaire(s) nl-form")

    # Autoriser le vrai POST Brevo dans la CSP. ``connect-src`` reste utile aux
    # autres fonctions du site mais le formulaire n'utilise plus fetch/no-cors.
    html = html.replace(
        "form-action 'self';",
        "form-action 'self' https://e6ad0381.sibforms.com;",
    )
    if "Content-Security-Policy" in html and "form-action" not in html:
        raise ValueError("CSP présente sans directive form-action")

    html = FORM_RE.sub(_form_tag(), html, count=1)
    html = HIDDEN_RE.sub("", html)
    html = html.replace(_form_tag(), _form_tag() + HIDDEN_FIELDS, 1)

    if MARKER not in html:
        html, replaced = OLD_SCRIPT_RE.subn(NEW_SCRIPT, html, count=1)
        if replaced != 1:
            raise ValueError("ancien script newsletter introuvable ou dupliqué")

    validate_html(html)
    return html, html != original


def validate_html(html: str) -> None:
    if html.count('id="nl-form"') != 1:
        raise ValueError("le formulaire newsletter doit être unique")
    required = (
        f'action="{SIB_URL}"', 'method="post"', 'target="_blank"',
        'name="FREQ"', 'name="EMAIL"', 'name="LESFAITS_VERIFICATION"',
        'name="email_address_check"', 'name="locale"', MARKER,
    )
    missing = [value for value in required if value not in html]
    if missing:
        raise ValueError("formulaire incomplet : " + ", ".join(missing))
    forbidden = ('mode:"no-cors"', "mode:'no-cors'", "fetch(SIB_URL")
    present = [value for value in forbidden if value in html]
    if present:
        raise ValueError("ancien faux succès encore présent : " + ", ".join(present))
    if "Content-Security-Policy" in html and (
        "form-action 'self' https://e6ad0381.sibforms.com;" not in html
    ):
        raise ValueError("la CSP bloque encore le POST Brevo")


def candidate_paths(root: Path) -> list[Path]:
    paths = [p for p in root.glob("*.html") if p.is_file()]
    paths += [p for p in (root / "categories").glob("*.html") if p.is_file()]
    return sorted(set(paths))


def patch_site(root: Path) -> dict[str, int]:
    scanned = forms = changed = 0
    for path in candidate_paths(root):
        scanned += 1
        text = path.read_text(encoding="utf-8", errors="strict")
        if 'id="nl-form"' not in text and "id='nl-form'" not in text:
            continue
        forms += 1
        updated, did_change = patch_html(text)
        if did_change:
            path.write_text(updated, encoding="utf-8")
            changed += 1
    if forms == 0:
        raise RuntimeError("aucun formulaire newsletter trouvé dans le site")
    print(
        f"[NEWSLETTER FORM] {forms} formulaire(s) contrôlé(s), "
        f"{changed} page(s) corrigée(s), {scanned} page(s) inspectée(s)."
    )
    return {"scanned": scanned, "forms": forms, "changed": changed}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = patch_site(args.root.resolve())
    if args.check and result["changed"]:
        raise RuntimeError(
            f"{result['changed']} page(s) nécessitaient encore une correction newsletter"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
