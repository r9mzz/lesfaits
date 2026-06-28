"""Injecte JSON-LD (NewsArticle + BreadcrumbList) dans tous les articles sans ld+json."""
import json, re
from pathlib import Path
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent.parent
ARTICLES = ROOT / "articles"
BASE = "https://r9mzz.github.io/lesfaits"

CAT_LABELS = {
    "science": "Science", "economie": "Économie", "tech": "Tech",
    "societe": "Société", "environnement": "Environnement", "sante": "Santé",
}

MOIS = {"janvier":1,"février":2,"mars":3,"avril":4,"mai":5,"juin":6,
        "juillet":7,"août":8,"septembre":9,"octobre":10,"novembre":11,"décembre":12}

def parse_date_iso(date_str):
    m = re.search(r'(\d+)\s+([\wéûôùàâêîèä]+)\s+(\d{4})(?:.*?(\d+)h(\d+))?', date_str, re.I)
    if not m:
        return "2026-06-01T00:00:00+02:00"
    d, mo, y = int(m.group(1)), m.group(2).lower(), int(m.group(3))
    h, mn = (int(m.group(4)), int(m.group(5))) if m.group(4) else (0, 0)
    month = MOIS.get(mo, 1)
    return f"{y:04d}-{month:02d}-{d:02d}T{h:02d}:{mn:02d}:00+02:00"

fixed = 0
for path in sorted(ARTICLES.glob("*.html")):
    html = path.read_text(encoding="utf-8")
    if "application/ld+json" in html:
        continue

    soup = BeautifulSoup(html, "html.parser")

    title_tag = soup.find("title")
    title = title_tag.get_text().replace(" — Les Faits", "").strip() if title_tag else path.stem

    desc_tag = soup.find("meta", attrs={"name": "description"})
    desc = (desc_tag.get("content") or "")[:155] if desc_tag else ""

    url_tag = soup.find("meta", attrs={"property": "og:url"})
    art_url = url_tag.get("content") if url_tag else f"{BASE}/articles/{path.stem}.html"

    img_tag = soup.find("meta", attrs={"property": "og:image"})
    img_url = img_tag.get("content") if img_tag else f"{BASE}/assets/images/og-default.jpg"

    # Catégorie depuis .cat ou article:section
    cat_tag = soup.find("meta", attrs={"property": "article:section"})
    cat_slug = (cat_tag.get("content") or "societe").lower() if cat_tag else "societe"
    cat_label = CAT_LABELS.get(cat_slug, cat_slug.capitalize())

    # Date depuis .art__meta ou .art_meta
    date_el = soup.select_one(".art__meta time") or soup.select_one(".art_meta time") or soup.select_one("time")
    if date_el:
        date_iso = date_el.get("datetime") or parse_date_iso(date_el.get_text())
    else:
        meta_el = soup.select_one(".art__meta") or soup.select_one(".art_meta")
        date_iso = parse_date_iso(meta_el.get_text()) if meta_el else "2026-06-01T00:00:00+02:00"

    # Escape quotes
    title_esc = title.replace('"', '\\"')
    desc_esc = desc.replace('"', '\\"')

    jsonld = f"""<script type="application/ld+json">
{{"@context":"https://schema.org","@graph":[
{{"@type":"NewsArticle","headline":"{title_esc}","description":"{desc_esc}","datePublished":"{date_iso}","dateModified":"{date_iso}","articleSection":"{cat_label}","inLanguage":"fr-FR","isAccessibleForFree":true,"image":{{"@type":"ImageObject","url":"{img_url}","width":1200,"height":630}},"author":{{"@type":"Organization","name":"Les Faits","url":"{BASE}/"}},"publisher":{{"@type":"Organization","name":"Les Faits","url":"{BASE}/","logo":{{"@type":"ImageObject","url":"{BASE}/assets/images/og-default.jpg"}}}},"mainEntityOfPage":{{"@type":"WebPage","@id":"{art_url}"}}}},
{{"@type":"BreadcrumbList","itemListElement":[{{"@type":"ListItem","position":1,"name":"Accueil","item":"{BASE}/"}},{{"@type":"ListItem","position":2,"name":"{cat_label}","item":"{BASE}/categories/{cat_slug}.html"}},{{"@type":"ListItem","position":3,"name":"{title_esc}","item":"{art_url}"}}]}}
]}}
</script>"""

    new_html = html.replace("</head>", jsonld + "\n</head>", 1)
    path.write_text(new_html, encoding="utf-8")
    fixed += 1
    print(f"  OK {path.name}")

print(f"\nTermine -- {fixed} articles injectes")
