#!/usr/bin/env python3
"""
generer_digest.py — Newsletter personnalisée Les Faits (Brevo transactionnel).

Chaque abonné reçoit un email sur-mesure :
  - uniquement les articles des rubriques qu'il a sélectionnées
  - si aucune préférence définie → toutes les rubriques

Fonctionnement :
  1. Récupère les articles des 27 dernières heures (git log)
  2. Récupère tous les contacts de la liste avec leurs attributs Brevo
  3. Crée un template Brevo temporaire (blocs conditionnels {% if %})
  4. Envoie un email transactionnel par contact (Brevo résout les conditions)
  5. Supprime le template temporaire

Variables d'environnement (secrets GitHub) :
  BREVO_API_KEY      — Clé API Brevo (v3)
  BREVO_LIST_ID      — ID entier de la liste principale (ex : "3")
  BREVO_SENDER_EMAIL — Adresse expéditeur vérifiée dans Brevo

Attributs contact Brevo requis (booléens) :
  CAT_SOCIETE · CAT_SCIENCE · CAT_ECONOMIE
  CAT_TECH    · CAT_SANTE   · CAT_ENVIRONNEMENT
"""

import sys
import os
import json
import subprocess
import datetime
import time
import argparse

import requests

# ── Configuration ──────────────────────────────────────────────────────────────
BREVO_API_KEY      = os.environ.get("BREVO_API_KEY", "")
BREVO_LIST_ID      = os.environ.get("BREVO_LIST_ID", "")
BREVO_SENDER_EMAIL = os.environ.get("BREVO_SENDER_EMAIL", "")
BREVO_SENDER_NAME  = "Les Faits"
SITE_BASE          = "https://lesfaits.info"
DATA_SEARCH        = "data/search.json"
BREVO_API_BASE     = "https://api.brevo.com/v3"

HEADERS = {
    "accept":       "application/json",
    "content-type": "application/json",
    "api-key":      BREVO_API_KEY,
}

CATEGORIES = ["societe", "science", "economie", "tech", "sante", "environnement"]

CAT_LABELS = {
    "societe":       "Société",
    "science":       "Science",
    "economie":      "Économie",
    "tech":          "Tech",
    "sante":         "Santé",
    "environnement": "Environnement",
}
CAT_COLORS = {
    "societe":       "#78716c",
    "science":       "#06b6d4",
    "economie":      "#f97316",
    "tech":          "#a855f7",
    "sante":         "#f43f5e",
    "environnement": "#22c55e",
}
MOIS_FR  = {
    "01": "janvier",   "02": "février",  "03": "mars",
    "04": "avril",     "05": "mai",      "06": "juin",
    "07": "juillet",   "08": "août",     "09": "septembre",
    "10": "octobre",   "11": "novembre", "12": "décembre",
}
JOURS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


# ── Utilitaires ────────────────────────────────────────────────────────────────

def date_longue() -> str:
    t = datetime.date.today()
    return f"{JOURS_FR[t.weekday()]} {t.day} {MOIS_FR[t.strftime('%m')]} {t.year}"


def trouver_slugs_recents() -> list:
    r = subprocess.run(
        ["git", "log", "--since=27 hours ago", "--name-only",
         "--diff-filter=A", "--pretty=format:", "--", "articles/"],
        capture_output=True, text=True,
    )
    slugs = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if line.startswith("articles/") and line.endswith(".html"):
            slug = line[len("articles/"):-len(".html")]
            if slug and slug not in slugs:
                slugs.append(slug)
    return slugs


def charger_articles(slugs: list) -> list:
    if not slugs or not os.path.exists(DATA_SEARCH):
        return []
    with open(DATA_SEARCH, encoding="utf-8") as f:
        index = {a["slug"]: a for a in json.load(f)}
    return [index[s] for s in slugs if s in index]


# ── Brevo : contacts ───────────────────────────────────────────────────────────

def get_contacts() -> list:
    """Récupère tous les contacts actifs de la liste avec leurs attributs."""
    contacts, offset = [], 0
    while True:
        r = requests.get(
            f"{BREVO_API_BASE}/contacts",
            params={"listIds": BREVO_LIST_ID, "limit": 500, "offset": offset},
            headers=HEADERS,
            timeout=20,
        )
        if r.status_code != 200:
            raise RuntimeError(f"Contacts Brevo {r.status_code}: {r.text[:200]}")
        data  = r.json()
        batch = data.get("contacts", [])
        contacts.extend(batch)
        if len(batch) < 500:
            break
        offset += 500
    return contacts


def contact_a_des_prefs(contact: dict) -> bool:
    """Vrai si au moins un attribut CAT_* est explicitement True."""
    attrs = contact.get("attributes", {})
    return any(attrs.get(f"CAT_{cat.upper()}") is True for cat in CATEGORIES)


def cats_du_contact(contact: dict) -> list:
    """Rubriques sélectionnées. Retourne toutes si aucune préférence."""
    attrs = contact.get("attributes", {})
    cats  = [cat for cat in CATEGORIES if attrs.get(f"CAT_{cat.upper()}") is True]
    return cats if cats else CATEGORIES


# ── Génération HTML ────────────────────────────────────────────────────────────

def _article_html(art: dict, couleur: str, label: str) -> str:
    slug    = art["slug"]
    titre   = art["titre"]
    excerpt = (art.get("excerpt") or "")[:220]
    url     = f"{SITE_BASE}/articles/{slug}.html"
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f'<tr><td style="padding:0 0 32px;">'
        # Catégorie
        f'<div style="font-family:Arial,Helvetica,sans-serif;font-size:10px;font-weight:700;'
        f'letter-spacing:2.5px;color:{couleur};text-transform:uppercase;margin-bottom:10px;">{label}</div>'
        # Titre
        f'<h2 style="font-family:Georgia,\'Times New Roman\',serif;font-size:20px;font-weight:normal;'
        f'color:#3A3835;margin:0 0 10px;line-height:1.42;">{titre}</h2>'
        # Extrait
        f'<p style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#6B6762;'
        f'line-height:1.68;margin:0 0 16px;">{excerpt}</p>'
        # Lien
        f'<a href="{url}" style="font-family:Arial,Helvetica,sans-serif;font-size:13px;'
        f'font-weight:700;color:{couleur};text-decoration:none;">Lire l\'article&nbsp;→</a>'
        f'</td></tr>'
        f'<tr><td style="border-bottom:1px solid #E5E1DA;margin-bottom:28px;">&nbsp;</td></tr>'
        f'</table>'
    )


def _section_cat(cat: str, arts: list) -> str:
    couleur = CAT_COLORS[cat]
    label   = CAT_LABELS[cat]
    return "\n".join(_article_html(a, couleur, label) for a in arts)


def generer_template_html(articles_par_cat: dict, date_long: str, slot: str = "matin") -> str:
    """
    Template Brevo avec blocs conditionnels {% if contact.CAT_X %}.

    Structure :
    - Si l'abonné a des préférences → seules ses rubriques s'affichent
    - Sinon ({% else %}) → toutes les rubriques s'affichent

    La syntaxe {% if %} / {% else %} / {% endif %} est native à Brevo
    et est résolue par contact au moment de l'envoi transactionnel.
    """
    # Sections conditionnelles (pour abonnés avec préférences)
    cond_parts = []
    for cat in CATEGORIES:
        arts = articles_par_cat.get(cat, [])
        if not arts:
            continue
        attr = f"CAT_{cat.upper()}"
        cond_parts.append(
            f"{{% if contact.{attr} %}}\n{_section_cat(cat, arts)}\n{{% endif %}}"
        )
    cond_html = "\n".join(cond_parts)

    # Sections complètes (pour abonnés sans préférences)
    all_html = "\n".join(
        _section_cat(cat, arts)
        for cat in CATEGORIES
        for arts in [articles_par_cat.get(cat, [])]
        if arts
    )

    # Condition globale : a-t-il au moins un CAT_* ?
    has_any = " or ".join(f"contact.CAT_{cat.upper()}" for cat in CATEGORIES)

    content_html = f"""
    {{% if {has_any} %}}
    {cond_html}
    {{% else %}}
    {all_html}
    {{% endif %}}
    """

    nb_cats = len([c for c in CATEGORIES if articles_par_cat.get(c)])
    nb_arts = sum(len(v) for v in articles_par_cat.values())
    resume  = f"{nb_arts} article{'s' if nb_arts > 1 else ''}"

    salutation  = "Bonjour" if slot == "matin" else "Bonsoir"
    intro_texte = (
        "Bonne journée en perspective. Voici ce que l'actualité a retenu ce matin — "
        "triés selon vos rubriques, résumés avec soin. À lire avec votre café."
        if slot == "matin" else
        "L'actualité ne manque pas d'intérêt aujourd'hui. Voici ce que Les Faits a "
        "retenu pour vous ce soir — selon les rubriques que vous suivez. Bonne lecture."
    )

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<meta name="x-apple-disable-message-reformatting"/>
<title>Les Faits — {date_long}</title>
</head>
<body style="margin:0;padding:0;background:#F0EDE6;-webkit-text-size-adjust:100%;">
<!--[if mso]><center><table width="600"><tr><td><![endif]-->
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
       style="background:#F0EDE6;min-height:100%;">
<tr><td align="center" style="padding:40px 16px 56px;">

  <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"
         style="max-width:600px;width:100%;">

    <!-- ░░ EN-TÊTE ░░ -->
    <tr>
      <td style="background:#3A3835;border-radius:8px 8px 0 0;padding:36px 40px 30px;">
        <!-- Logo texte -->
        <div style="margin-bottom:20px;">
          <span style="font-family:Arial,Helvetica,sans-serif;font-size:30px;font-weight:300;
                       color:#F0EDE6;letter-spacing:-0.5px;">les&nbsp;</span><span
               style="font-family:Arial,Helvetica,sans-serif;font-size:30px;font-weight:700;
                       color:#6C85BD;letter-spacing:-0.5px;">faits</span>
        </div>
        <!-- Date + résumé -->
        <p style="font-family:Georgia,'Times New Roman',serif;font-size:16px;color:#B0A99F;
                  line-height:1.5;margin:0 0 6px;">
          Votre sélection du {date_long}
        </p>
        <p style="font-family:Arial,Helvetica,sans-serif;font-size:11px;color:#706A64;
                  margin:0;letter-spacing:0.5px;text-transform:uppercase;">
          {resume} · {nb_cats} rubrique{'s' if nb_cats > 1 else ''}
        </p>
      </td>
    </tr>

    <!-- ░░ INTRO ░░ -->
    <tr>
      <td style="background:#FAF9F6;padding:32px 40px 24px;border-bottom:1px solid #E8E3DB;">
        <p style="font-family:Georgia,'Times New Roman',serif;font-size:16px;color:#3A3835;
                  line-height:1.75;margin:0;">
          {salutation},
        </p>
        <p style="font-family:Georgia,'Times New Roman',serif;font-size:15px;color:#4A4744;
                  line-height:1.75;margin:14px 0 0;">
          {intro_texte}
        </p>
      </td>
    </tr>

    <!-- ░░ ARTICLES ░░ -->
    <tr>
      <td style="background:#FAF9F6;padding:28px 40px 4px;">
        {content_html}
      </td>
    </tr>

    <!-- ░░ LIEN SITE ░░ -->
    <tr>
      <td style="background:#FAF9F6;padding:8px 40px 36px;text-align:center;">
        <a href="{SITE_BASE}"
           style="font-family:Arial,Helvetica,sans-serif;font-size:13px;color:#6C85BD;
                  text-decoration:none;font-weight:600;">
          Voir toute l'actualité sur lesfaits.info →
        </a>
      </td>
    </tr>

    <!-- ░░ PIED DE PAGE ░░ -->
    <tr>
      <td style="background:#3A3835;border-radius:0 0 8px 8px;padding:24px 40px;">
        <p style="font-family:Arial,Helvetica,sans-serif;font-size:11px;color:#706A64;
                  margin:0 0 10px;line-height:1.6;text-align:center;">
          Vous recevez ce résumé parce que vous vous êtes abonné·e à
          <a href="{SITE_BASE}" style="color:#9AA5BD;text-decoration:none;">Les Faits</a>.
        </p>
        <p style="font-family:Arial,Helvetica,sans-serif;font-size:11px;margin:0;text-align:center;">
          <a href="{{{{ unsubscribe }}}}" style="color:#6C85BD;text-decoration:none;">Se désabonner</a>
          &nbsp;·&nbsp;
          <a href="{SITE_BASE}/confidentialite.html" style="color:#706A64;text-decoration:none;">Vie privée</a>
        </p>
      </td>
    </tr>

  </table>
</td></tr>
</table>
<!--[if mso]></td></tr></table></center><![endif]-->
</body>
</html>"""


# ── Brevo : template ──────────────────────────────────────────────────────────

def creer_template(html_content: str, date_long: str) -> int:
    """Crée un template Brevo temporaire et retourne son ID."""
    payload = {
        "tag":          "nl-digest-temp",
        "sender":       {"name": BREVO_SENDER_NAME, "email": BREVO_SENDER_EMAIL},
        "templateName": f"Digest {date_long} (auto)",
        "subject":      f"Les Faits du {date_long} — votre sélection",
        "htmlContent":  html_content,
        "isActive":     True,
    }
    r = requests.post(
        f"{BREVO_API_BASE}/smtp/templates",
        json=payload, headers=HEADERS, timeout=20,
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Création template {r.status_code}: {r.text[:300]}")
    tid = r.json()["id"]
    print(f"  [BREVO] Template créé — id={tid}")
    return tid


def supprimer_template(template_id: int) -> None:
    """Supprime le template temporaire après l'envoi."""
    try:
        requests.delete(
            f"{BREVO_API_BASE}/smtp/templates/{template_id}",
            headers=HEADERS, timeout=10,
        )
        print(f"  [BREVO] Template {template_id} supprimé")
    except Exception as e:
        print(f"  [WARN] Suppression template: {e}")


# ── Brevo : envoi transactionnel ───────────────────────────────────────────────

def envoyer_email(template_id: int, email: str) -> bool:
    """Envoie l'email transactionnel à un contact via le template.

    En plus du lien {{ unsubscribe }} dans le corps HTML (qui dépend d'un
    réglage compte Brevo — Expéditeurs, domaines & IP dédiées > Désabonnement
    — pour rediriger vers /desabonnement.html), on ajoute l'en-tête
    List-Unsubscribe (RFC 8058) : Gmail/Outlook/Yahoo affichent alors un
    bouton "Se désabonner" natif à côté de l'expéditeur, indépendant du lien
    dans le corps du mail et bien plus fiable — Brevo résout {{ unsubscribe }}
    dans les en-têtes personnalisés de la même façon que dans le HTML.
    """
    payload = {
        "templateId": template_id,
        "to":         [{"email": email}],
        "headers": {
            "List-Unsubscribe": "<{{ unsubscribe }}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        },
    }
    r = requests.post(
        f"{BREVO_API_BASE}/smtp/email",
        json=payload, headers=HEADERS, timeout=15,
    )
    if r.status_code not in (200, 201, 202):
        print(f"    [WARN] Échec envoi à {email}: {r.status_code} — {r.text[:100]}")
        return False
    return True


# ── Point d'entrée ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slot", choices=["matin", "soir"], default="matin",
                        help="Créneau d'envoi : matin (ENVOI_MATIN=True) ou soir (ENVOI_MATIN=False)")
    args = parser.parse_args()
    slot = args.slot

    print("=" * 62)
    print(f"  Les Faits — Digest {slot.upper()}")
    print("=" * 62)

    # Vérification des variables d'environnement
    manquantes = [v for v, val in [
        ("BREVO_API_KEY",      BREVO_API_KEY),
        ("BREVO_LIST_ID",      BREVO_LIST_ID),
        ("BREVO_SENDER_EMAIL", BREVO_SENDER_EMAIL),
    ] if not val]
    if manquantes:
        for v in manquantes:
            print(f"  [ERREUR] Variable manquante : {v}")
        sys.exit(1)

    # 1. Articles récents
    slugs = trouver_slugs_recents()
    print(f"\n  Articles (27h) : {len(slugs)}")
    if not slugs:
        print("  Aucun article publié — envoi annulé.\n" + "=" * 62)
        return

    articles = charger_articles(slugs)
    if not articles:
        print("  Slugs introuvables dans search.json — envoi annulé.\n" + "=" * 62)
        return

    # Grouper par rubrique
    articles_par_cat: dict = {}
    for a in articles:
        cat = a.get("categorie", "")
        if cat in CATEGORIES:
            articles_par_cat.setdefault(cat, []).append(a)

    for cat, arts in articles_par_cat.items():
        for a in arts:
            print(f"    · [{CAT_LABELS[cat]}] {a['titre'][:55]}")

    if not articles_par_cat:
        print("  Aucune rubrique reconnue — envoi annulé.\n" + "=" * 62)
        return

    # 2. Contacts filtrés par slot
    print("\n  Chargement des abonnés...")
    contacts = get_contacts()
    # matin → ENVOI_MATIN is True ; soir → ENVOI_MATIN is False ou non défini
    def veux_ce_slot(c: dict) -> bool:
        val = c.get("attributes", {}).get("ENVOI_MATIN")
        if slot == "matin":
            return val is True
        else:
            return val is not True  # False, None, ou absent → soir par défaut
    actifs = [c for c in contacts if c.get("email") and veux_ce_slot(c)]
    print(f"  Abonnés slot={slot} : {len(actifs)}")
    if not actifs:
        print("  Liste vide — envoi annulé.\n" + "=" * 62)
        return

    # 3. Template HTML
    date_long    = date_longue()
    html_content = generer_template_html(articles_par_cat, date_long, slot)

    # 4. Création du template Brevo
    print("\n  Création du template Brevo...")
    template_id = creer_template(html_content, date_long)

    # 5. Envoi par contact
    print(f"\n  Envoi à {len(actifs)} abonné(s)...")
    envoyes = ignores = erreurs = 0

    try:
        for contact in actifs:
            email = contact["email"]

            # Vérifier qu'au moins une rubrique de l'abonné est active aujourd'hui
            cats_contact = cats_du_contact(contact)
            has_articles = any(cat in articles_par_cat for cat in cats_contact)
            if not has_articles:
                ignores += 1
                continue

            ok = envoyer_email(template_id, email)
            if ok:
                envoyes += 1
                print(f"    ✓ {email}")
            else:
                erreurs += 1

            # Pause légère pour ne pas saturer l'API (50 req/s max Brevo)
            if (envoyes + erreurs) % 40 == 0:
                time.sleep(1)

    finally:
        supprimer_template(template_id)

    print(f"\n  ── Résultat ──────────────────────────────────────────")
    print(f"  Envoyés  : {envoyes}")
    if ignores:
        print(f"  Ignorés  : {ignores}  (rubriques sans articles aujourd'hui)")
    if erreurs:
        print(f"  Erreurs  : {erreurs}")
    print("=" * 62)


if __name__ == "__main__":
    main()
