#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rendu HTML du digest Les Faits, compatible clients email."""
from __future__ import annotations

import datetime as dt
import html
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")
SITE_BASE = "https://lesfaits.info"
CATEGORIES = ("societe", "science", "economie", "tech", "sante", "environnement")
CAT_LABELS = {
    "societe": "Société",
    "science": "Science",
    "economie": "Économie",
    "tech": "Tech",
    "sante": "Santé",
    "environnement": "Environnement",
}
CAT_COLORS = {
    "societe": "#78716c",
    "science": "#0891b2",
    "economie": "#ea580c",
    "tech": "#9333ea",
    "sante": "#e11d48",
    "environnement": "#16a34a",
}
MONTHS = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)
WEEKDAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")


def date_longue(now: dt.datetime) -> str:
    local = now.astimezone(PARIS)
    return f"{WEEKDAYS[local.weekday()]} {local.day} {MONTHS[local.month - 1]} {local.year}"


def _article_html(article: dict[str, Any], category: str) -> str:
    slug = quote(str(article.get("slug") or ""), safe="-")
    title = html.escape(str(article.get("titre") or "Article sans titre"))
    excerpt = html.escape(str(article.get("excerpt") or "").strip()[:260])
    label = html.escape(CAT_LABELS[category])
    color = CAT_COLORS[category]
    url = (
        f"{SITE_BASE}/articles/{slug}.html"
        "?utm_source=newsletter&utm_medium=email&utm_campaign=digest"
    )
    excerpt_block = (
        f'<p style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#625f5b;'
        f'line-height:1.65;margin:0 0 14px;">{excerpt}</p>'
        if excerpt else ""
    )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        '<tr><td style="padding:0 0 28px;">'
        f'<div style="font-family:Arial,Helvetica,sans-serif;font-size:10px;font-weight:700;'
        f'letter-spacing:2px;color:{color};text-transform:uppercase;margin-bottom:9px;">'
        f'{label}</div>'
        f'<h2 style="font-family:Georgia,Times New Roman,serif;font-size:20px;font-weight:normal;'
        f'color:#262422;margin:0 0 9px;line-height:1.4;">{title}</h2>'
        f'{excerpt_block}'
        f'<a href="{url}" style="font-family:Arial,Helvetica,sans-serif;font-size:13px;'
        f'font-weight:700;color:{color};text-decoration:none;">Lire l’article&nbsp;→</a>'
        '</td></tr><tr><td style="border-top:1px solid #e5e1da;height:24px;'
        'font-size:0;line-height:0;">&nbsp;</td></tr></table>'
    )


def _section_html(category: str, articles: list[dict[str, Any]]) -> str:
    return "".join(_article_html(article, category) for article in articles)


def build_email(
    articles_by_category: dict[str, list[dict[str, Any]]],
    *,
    now: dt.datetime,
    slot: str,
) -> str:
    conditional: list[str] = []
    complete: list[str] = []
    for category in CATEGORIES:
        articles = articles_by_category.get(category) or []
        if not articles:
            continue
        section = _section_html(category, articles)
        conditional.append(
            f"{{% if contact.CAT_{category.upper()} %}}\n{section}\n{{% endif %}}"
        )
        complete.append(section)

    has_any = " or ".join(f"contact.CAT_{category.upper()}" for category in CATEGORIES)
    content = (
        f"{{% if {has_any} %}}\n{''.join(conditional)}\n"
        f"{{% else %}}\n{''.join(complete)}\n{{% endif %}}"
    )
    total = sum(len(items) for items in articles_by_category.values())
    categories_count = sum(bool(items) for items in articles_by_category.values())
    article_label = "nouvel article" if total == 1 else "nouveaux articles"
    preview = html.escape(f"{total} {article_label} dans votre sélection Les Faits.")
    date_text = html.escape(date_longue(now))
    greeting = "Bonjour" if slot == "matin" else "Bonsoir"

    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="x-apple-disable-message-reformatting">
<title>Les Faits — {date_text}</title>
</head>
<body style="margin:0;padding:0;background:#f0ede6;-webkit-text-size-adjust:100%;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">{preview}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
 style="background:#f0ede6;">
<tr><td align="center" style="padding:30px 12px 48px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"
 style="width:100%;max-width:600px;">
<tr><td style="background:#0b0f17;border-radius:10px 10px 0 0;padding:32px 36px 27px;">
<div style="font-family:Georgia,Times New Roman,serif;font-size:31px;line-height:1;color:#fff;">
<span style="font-weight:400;">les</span><span style="font-weight:700;">faits</span>
</div>
<p style="font-family:Arial,Helvetica,sans-serif;font-size:12px;color:#aab2c0;
margin:18px 0 5px;letter-spacing:.04em;">Votre sélection du {date_text}</p>
<p style="font-family:Arial,Helvetica,sans-serif;font-size:10px;color:#7f8998;margin:0;
letter-spacing:.12em;text-transform:uppercase;">{total} article{'s' if total != 1 else ''} ·
{categories_count} rubrique{'s' if categories_count != 1 else ''}</p>
</td></tr>
<tr><td style="background:#fff;padding:28px 36px 22px;border-bottom:1px solid #e8e3db;">
<p style="font-family:Georgia,Times New Roman,serif;font-size:16px;color:#262422;
line-height:1.7;margin:0;">{greeting},</p>
<p style="font-family:Georgia,Times New Roman,serif;font-size:15px;color:#4a4744;
line-height:1.7;margin:12px 0 0;">Voici les nouveaux articles publiés depuis votre
précédent digest, classés selon les rubriques que vous avez choisies.</p>
</td></tr>
<tr><td style="background:#fff;padding:26px 36px 4px;">{content}</td></tr>
<tr><td style="background:#fff;padding:0 36px 34px;text-align:center;">
<a href="{SITE_BASE}/?utm_source=newsletter&utm_medium=email"
style="font-family:Arial,Helvetica,sans-serif;font-size:13px;color:#375a9e;
text-decoration:none;font-weight:700;">Voir tous les articles sur lesfaits.info →</a>
</td></tr>
<tr><td style="background:#0b0f17;border-radius:0 0 10px 10px;padding:22px 30px;">
<p style="font-family:Arial,Helvetica,sans-serif;font-size:11px;color:#9aa3b1;
margin:0 0 9px;line-height:1.55;text-align:center;">Vous recevez cet email parce
que vous avez confirmé votre inscription à Les Faits.</p>
<p style="font-family:Arial,Helvetica,sans-serif;font-size:11px;margin:0;text-align:center;">
<a href="{{{{ unsubscribe }}}}" style="color:#c7d4f0;text-decoration:underline;">Se désabonner</a>
&nbsp;·&nbsp;
<a href="{SITE_BASE}/confidentialite.html" style="color:#9aa3b1;text-decoration:none;">Vie privée</a>
</p>
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""
