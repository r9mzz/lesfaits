#!/usr/bin/env python3
"""
generer_digest.py — Résumé quotidien des Faits via l'API Brevo (Campaigns).

- Lit les articles ajoutés dans les 27 dernières heures (git log)
- Génère un email HTML avec titre + extrait + lien pour chaque article
- Crée une campagne Brevo et l'envoie immédiatement à la liste d'abonnés
- Si 0 article : ne fait rien (exit 0)

Variables d'environnement (secrets GitHub) :
  BREVO_API_KEY      — Clé API Brevo
  BREVO_LIST_ID      — ID entier de la liste d'abonnés (ex : "3")
  BREVO_SENDER_EMAIL — Adresse expéditeur vérifiée dans Brevo
"""

import sys
import os
import json
import subprocess
import datetime

import requests

# ── Configuration ──────────────────────────────────────────────────────────
BREVO_API_KEY      = os.environ.get("BREVO_API_KEY", "")
BREVO_LIST_ID      = os.environ.get("BREVO_LIST_ID", "")
BREVO_SENDER_EMAIL = os.environ.get("BREVO_SENDER_EMAIL", "")
BREVO_SENDER_NAME  = "Les Faits"
SITE_BASE          = "https://lesfaits.info"
DATA_SEARCH        = "data/search.json"
BREVO_API_BASE     = "https://api.brevo.com/v3"

HEADERS = {
    "accept": "application/json",
    "content-type": "application/json",
    "api-key": BREVO_API_KEY,
}

MOIS_FR = {
    "01": "janvier", "02": "février", "03": "mars",    "04": "avril",
    "05": "mai",     "06": "juin",    "07": "juillet",  "08": "août",
    "09": "septembre","10": "octobre","11": "novembre", "12": "décembre",
}

JOURS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]

CAT_COLORS = {
    "societe":       "#4A6B8E",
    "science":       "#3E7259",
    "economie":      "#7A6B3E",
    "tech":          "#4A4E8E",
    "sante":         "#8E4A4A",
    "environnement": "#3E7A5B",
}
CAT_LABELS = {
    "societe": "SOCIÉTÉ", "science": "SCIENCE", "economie": "ÉCONOMIE",
    "tech": "TECH",       "sante": "SANTÉ",     "environnement": "ENVIRONNEMENT",
}


# ── Helpers ─────────────────────────────────────────────────────────────────

def date_longue() -> str:
    t = datetime.date.today()
    return f"{JOURS_FR[t.weekday()]} {t.day} {MOIS_FR[t.strftime('%m')]} {t.year}"


def trouver_slugs_recents() -> list:
    """Slugs des articles ajoutés dans les 27 dernières heures (git log)."""
    r = subprocess.run(
        ["git", "log", "--since=27 hours ago", "--name-only",
         "--diff-filter=A", "--pretty=format:", "--", "articles/"],
        capture_output=True, text=True
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
    """Retourne les métadonnées (depuis search.json) pour les slugs donnés."""
    if not slugs or not os.path.exists(DATA_SEARCH):
        return []
    with open(DATA_SEARCH, encoding="utf-8") as f:
        index = {a["slug"]: a for a in json.load(f)}
    return [index[s] for s in slugs if s in index]


# ── Génération de l'email ───────────────────────────────────────────────────

def _bloc_article(art: dict) -> str:
    slug      = art["slug"]
    titre     = art["titre"]
    excerpt   = art.get("excerpt", "")
    cat       = art.get("categorie", "")
    couleur   = CAT_COLORS.get(cat, "#6C85BD")
    label     = CAT_LABELS.get(cat, cat.upper())
    url       = f"{SITE_BASE}/articles/{slug}.html"

    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"'
        ' style="border-bottom:1px solid #D0CCC3;">'
        "<tr><td style=\"padding:22px 0;\">"
        f"<span style=\"display:inline-block;background:{couleur};color:#fff;"
        "font-family:Arial,Helvetica,sans-serif;font-size:10px;font-weight:700;"
        f"letter-spacing:1px;padding:3px 10px;border-radius:3px;margin-bottom:12px;\">{label}</span>"
        f"<h2 style=\"font-family:Georgia,'Times New Roman',serif;font-size:20px;"
        f"color:#3A3835;margin:0 0 10px;line-height:1.4;\">{titre}</h2>"
        f"<p style=\"font-family:Arial,Helvetica,sans-serif;font-size:14px;"
        f"color:#696660;line-height:1.65;margin:0 0 16px;\">{excerpt}</p>"
        f"<a href=\"{url}\" style=\"display:inline-block;background:#6C85BD;color:#fff;"
        "font-family:Arial,Helvetica,sans-serif;font-size:13px;font-weight:700;"
        "padding:9px 20px;border-radius:4px;text-decoration:none;\">Lire l'article &rarr;</a>"
        "</td></tr></table>"
    )


def generer_email_html(articles: list, date_long: str) -> str:
    """Retourne l'HTML complet de l'email (inline CSS, compatible Outlook/Gmail)."""
    nb = len(articles)
    compte = f"{nb} article" + ("s" if nb > 1 else "")
    articles_html = "\n".join(_bloc_article(a) for a in articles)

    # NOTE : {unsubscribe} est une variable Brevo — ne pas modifier.
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<meta name="x-apple-disable-message-reformatting"/>
<title>Les Faits &mdash; {date_long}</title>
</head>
<body style="margin:0;padding:0;background:#F0EDE6;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#F0EDE6;">
<tr><td align="center" style="padding:32px 16px;">
  <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="max-width:600px;width:100%;">

    <!-- En-tête -->
    <tr>
      <td style="background:#3A3835;border-radius:8px 8px 0 0;padding:28px 32px;text-align:center;">
        <div style="margin-bottom:8px;">
          <span style="font-family:Arial,Helvetica,sans-serif;font-size:34px;font-weight:300;color:#F0EDE6;letter-spacing:-1px;">les</span>
          <span style="font-family:Arial,Helvetica,sans-serif;font-size:34px;font-weight:700;color:#6C85BD;letter-spacing:-1px;">&nbsp;faits</span>
        </div>
        <p style="font-family:Arial,Helvetica,sans-serif;font-size:13px;color:#9AA5BD;margin:0;">
          R&eacute;sum&eacute; du {date_long} &mdash; {compte}
        </p>
      </td>
    </tr>

    <!-- Corps -->
    <tr>
      <td style="background:#FAF9F6;padding:24px 32px 12px;">
        {articles_html}
        <p style="font-family:Arial,Helvetica,sans-serif;font-size:13px;color:#9AA5BD;text-align:center;margin:24px 0 4px;">
          <a href="{SITE_BASE}" style="color:#6C85BD;text-decoration:none;">Voir tous les articles sur lesfaits.info &rarr;</a>
        </p>
      </td>
    </tr>

    <!-- Pied de page -->
    <tr>
      <td style="background:#3A3835;border-radius:0 0 8px 8px;padding:20px 32px;text-align:center;">
        <p style="font-family:Arial,Helvetica,sans-serif;font-size:11px;color:#9AA5BD;margin:0 0 6px;line-height:1.5;">
          Vous recevez cet email car vous vous &ecirc;tes abonn&eacute; au r&eacute;sum&eacute; quotidien de
          <a href="{SITE_BASE}" style="color:#6C85BD;">Les Faits</a>.
        </p>
        <p style="font-family:Arial,Helvetica,sans-serif;font-size:11px;color:#9AA5BD;margin:0;">
          <a href="{{unsubscribe}}" style="color:#6C85BD;">Se d&eacute;sabonner</a>
          &nbsp;&middot;&nbsp;
          <a href="{SITE_BASE}/confidentialite.html" style="color:#6C85BD;">Vie priv&eacute;e</a>
        </p>
      </td>
    </tr>

  </table>
</td></tr>
</table>
</body>
</html>"""


# ── Brevo API ───────────────────────────────────────────────────────────────

def creer_campagne(subject: str, html_content: str, date_long: str) -> int:
    """Crée la campagne Brevo et retourne son ID."""
    payload = {
        "name":        f"Les Faits — {date_long}",
        "subject":     subject,
        "sender":      {"name": BREVO_SENDER_NAME, "email": BREVO_SENDER_EMAIL},
        "type":        "classic",
        "htmlContent": html_content,
        "recipients":  {"listIds": [int(BREVO_LIST_ID)]},
    }
    r = requests.post(f"{BREVO_API_BASE}/emailCampaigns", json=payload, headers=HEADERS, timeout=15)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Erreur création campagne Brevo {r.status_code} : {r.text[:300]}")
    cid = r.json()["id"]
    print(f"  [BREVO] Campagne créée — id={cid}")
    return cid


def envoyer_campagne(campaign_id: int) -> dict:
    """Envoie la campagne immédiatement. Retourne la réponse JSON."""
    r = requests.post(
        f"{BREVO_API_BASE}/emailCampaigns/{campaign_id}/sendNow",
        headers=HEADERS, timeout=15
    )
    if r.status_code not in (200, 201, 204):
        raise RuntimeError(f"Erreur envoi campagne {campaign_id} — {r.status_code} : {r.text[:300]}")
    return r.json() if r.content else {}


def compter_abonnes() -> int:
    """Retourne le nombre de contacts actifs dans la liste."""
    try:
        r = requests.get(
            f"{BREVO_API_BASE}/contacts/lists/{BREVO_LIST_ID}",
            headers=HEADERS, timeout=10
        )
        if r.status_code == 200:
            return r.json().get("uniqueSubscribers", 0)
    except Exception:
        pass
    return -1


# ── Point d'entrée ──────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("  DIGEST — Génération newsletter quotidienne")
    print("=" * 60)

    for var, val in [("BREVO_API_KEY", BREVO_API_KEY), ("BREVO_LIST_ID", BREVO_LIST_ID),
                     ("BREVO_SENDER_EMAIL", BREVO_SENDER_EMAIL)]:
        if not val:
            print(f"  [ERREUR] Variable d'environnement manquante : {var}")
            sys.exit(1)

    # 1. Articles des dernières 27h
    slugs = trouver_slugs_recents()
    print(f"  Articles récents (27h) : {len(slugs)}")

    if not slugs:
        print("  Aucun article publié dans les dernières 27h — envoi ignoré.")
        print("=" * 60)
        return

    articles = charger_articles(slugs)
    if not articles:
        print("  Slugs trouvés mais absents de search.json — envoi ignoré.")
        print("=" * 60)
        return

    print(f"  Articles à inclure : {len(articles)}")
    for a in articles:
        print(f"    · [{a.get('categorie','?').upper()}] {a['titre'][:60]}")

    # 2. Génération email
    date_long   = date_longue()
    nb          = len(articles)
    compte      = f"{nb} article" + ("s" if nb > 1 else "")
    subject     = f"Les Faits du {date_long} — {compte}"
    html_email  = generer_email_html(articles, date_long)

    # 3. Nombre d'abonnés (informatif)
    nb_abonnes = compter_abonnes()
    if nb_abonnes >= 0:
        print(f"  Abonnés actifs dans la liste : {nb_abonnes}")
        if nb_abonnes == 0:
            print("  Liste vide — envoi ignoré (aucun abonné).")
            return

    # 4. Création + envoi campagne
    print(f"  Sujet : {subject}")
    try:
        cid = creer_campagne(subject, html_email, date_long)
        envoyer_campagne(cid)
        print(f"  [OK] Digest envoyé — campagne id={cid}, liste={BREVO_LIST_ID}")
    except Exception as exc:
        print(f"  [ERREUR] {exc}")
        sys.exit(1)

    print("=" * 60)


if __name__ == "__main__":
    main()
