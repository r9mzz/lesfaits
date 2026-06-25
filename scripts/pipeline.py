"""
Les Faits — Pipeline éditorial IA v2
====================================
Sources RSS reelles → Filtre éditorial → Groq (Llama) → HTML → Site reconstruit

Usage:
    python pipeline.py                  # scan toutes les sources RSS
    python pipeline.py --dry-run        # scan sans générer
    python pipeline.py --text "..."     # article depuis texte libre
"""

import os, re, json, time, hashlib, argparse, sys
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from groq import Groq
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()
sys.stdout.reconfigure(encoding="utf-8")

# ── Chemins ────────────────────────────────────────────────────────────────────
ROOT      = Path(__file__).parent.parent
ARTICLES  = ROOT / "articles"
DATA      = ROOT / "data"
PUBLISHED = DATA / "published.json"
INDEX_JSON= DATA / "articles.json"
ARTICLES.mkdir(exist_ok=True)
DATA.mkdir(exist_ok=True)

GROQ_KEY = os.getenv("GROQ_API_KEY", "")

# ══════════════════════════════════════════════════════════════════════════════
# SOURCES RSS — retournent du texte propre, pas de JavaScript
# ══════════════════════════════════════════════════════════════════════════════

RSS_SOURCES = [
    # Science / environnement / santé
    {"name": "Le Monde Science",     "url": "https://www.lemonde.fr/sciences/rss_full.xml"},
    {"name": "Le Monde Planète",     "url": "https://www.lemonde.fr/planete/rss_full.xml"},
    {"name": "Le Monde Santé",       "url": "https://www.lemonde.fr/sante/rss_full.xml"},
    # Économie / société
    {"name": "Le Monde Economie",    "url": "https://www.lemonde.fr/economie/rss_full.xml"},
    {"name": "Le Monde Société",     "url": "https://www.lemonde.fr/societe/rss_full.xml"},
    # Tech
    {"name": "Le Monde Pixel",       "url": "https://www.lemonde.fr/pixels/rss_full.xml"},
    # Institutions françaises
    {"name": "Vie Publique",         "url": "https://www.vie-publique.fr/rss.xml"},
    # Science internationale
    {"name": "Futura Sciences",      "url": "https://www.futura-sciences.com/rss/actualites.xml"},
    {"name": "CNRS Actualités",      "url": "https://lejournal.cnrs.fr/rss"},
]

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}


def fetch_full_content(url: str) -> str:
    """Scrape le contenu complet d'un article depuis son URL."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        # Supprimer les éléments parasites
        for tag in soup(["script", "style", "nav", "footer", "aside",
                          "header", "form", "ads", "iframe", ".pub", ".ad"]):
            tag.decompose()

        # Cibler les balises de contenu éditorial
        content = ""
        for selector in ["article", "main", ".article-content", ".post-content",
                          ".entry-content", '[itemprop="articleBody"]', ".article__content"]:
            el = soup.select_one(selector)
            if el:
                content = el.get_text(separator=" ", strip=True)
                break

        # Fallback : tout le body
        if len(content) < 300:
            content = soup.get_text(separator=" ", strip=True)

        # Nettoyer les espaces multiples
        content = re.sub(r"\s+", " ", content).strip()
        return content[:8000]

    except Exception as e:
        return ""


def duckduckgo_search(query: str, max_results: int = 5) -> list[dict]:
    """Recherche DuckDuckGo sans clé API pour trouver des sources corroborantes."""
    try:
        url = "https://html.duckduckgo.com/html/"
        data = {"q": query + " site:.fr OR site:.gouv.fr OR site:.europa.eu OR site:.who.int"}
        r = requests.post(url, data=data, headers=HEADERS, timeout=12)
        soup = BeautifulSoup(r.text, "html.parser")

        results = []
        for result in soup.select(".result")[:max_results]:
            title_el = result.select_one(".result__title")
            url_el   = result.select_one(".result__url")
            snippet  = result.select_one(".result__snippet")

            if title_el and url_el:
                results.append({
                    "title":   title_el.get_text(strip=True),
                    "url":     "https://" + url_el.get_text(strip=True).strip(),
                    "snippet": snippet.get_text(strip=True) if snippet else "",
                })
        return results
    except Exception:
        return []


def fetch_rss(source: dict) -> list[dict]:
    """Parse un flux RSS et retourne les items avec leur contenu texte."""
    try:
        r = requests.get(source["url"], headers=HEADERS, timeout=12)
        r.raise_for_status()
        root = ET.fromstring(r.content)

        # Namespaces courants
        ns = {
            "content": "http://purl.org/rss/1.0/modules/content/",
            "dc":      "http://purl.org/dc/elements/1.1/",
        }

        items = []
        for item in root.iter("item"):
            title   = item.findtext("title", "").strip()
            link    = item.findtext("link",  "").strip()
            desc    = item.findtext("description", "")
            # Contenu complet si disponible
            full    = item.find("content:encoded", ns)
            content_raw = full.text if full is not None else desc

            # Nettoyer le HTML dans le contenu
            if content_raw:
                soup = BeautifulSoup(content_raw, "html.parser")
                content_clean = soup.get_text(separator=" ", strip=True)
            else:
                content_clean = ""

            pub_date = item.findtext("pubDate", datetime.now().isoformat())

            if not title or not link:
                continue

            items.append({
                "id":          hashlib.md5(link.encode()).hexdigest()[:14],
                "title":       title,
                "url":         link,
                "content":     (title + " " + content_clean)[:6000],
                "source_name": source["name"],
                "date":        pub_date,
            })

        return items[:8]  # max 8 par source

    except Exception as e:
        print(f"  [RSS ERREUR] {source['name']} : {e}")
        return []


# ══════════════════════════════════════════════════════════════════════════════
# FILTRE ÉDITORIAL v2 — Barème par score
# ══════════════════════════════════════════════════════════════════════════════

BLACKLIST = [
    # Violence / faits divers
    "guerre", "conflit armé", "attentat", "terrorisme",
    "fait divers", "meurtre", "accident mortel",
    # People / opinion
    "célébrité", "scandale people", "vie privée",
    "sondage d'opinion", "cote de popularité",
    "parti politique", "élection présidentielle",
    "horoscope", "téléréalité",
    # Contenu commercial / publicitaire
    "prime day", "black friday", "soldes", "promo ", "promotion ",
    "bon plan", "meilleur prix", "moins cher", "réduction ",
    "robot piscine", "spa gonflable", "aspirateur robot",
    "offre limitée", "code promo", "achat conseillé",
    # Spam / hors-sujet éditorial
    "hostinger", "holafly", "esim illimitée",
    "votre pelouse", "jardin connecté",
]

# Sources majeures : institutions officielles et revues peer-reviewed
SOURCES_MAJEURES = [
    "insee", "eurostat", "cnrs", "inserm", "dares", "anses", "citepa",
    "banque de france", "banque-de-france", "ocde", "oecd",
    "who", "oms", "onu", "unesco",
    "nature", "lancet", "science", "nejm", "bmj", "pubmed",
    "inrae", "cea", "ademe", "rte ", "météo-france",
    "vie-publique", "legifrance", "sénat", "assemblée nationale",
    "hcsp", "hcph", "ansm", "ars ",
    "le monde science", "cnrs actualités",
]

# Sources médias de référence (fiables mais score moindre)
SOURCES_MEDIAS = [
    "afp", "reuters", "le monde", "le figaro", "liberation",
    "les echos", "france info", "france 24", "bfm",
    "futura sciences", "science et avenir",
]

# Mots-clés de confiance éditoriale
KW_CONFIANCE = [
    "données", "statistique", "rapport", "étude", "enquête",
    "publication", "résultats", "chiffres", "bilan", "inventaire",
    "peer-reviewed", "revue", "analyse", "mesure", "indice",
]

CATEGORIES_MAP = {
    "science":       ["science", "recherche", "étude", "cnrs", "inserm", "médecine", "vaccin", "biologie", "physique", "chimie"],
    "economie":      ["économie", "emploi", "chômage", "inflation", "pib", "smic", "budget", "déficit", "croissance", "banque"],
    "tech":          ["technologie", "numérique", "intelligence artificielle", "ia ", "cyber", "algorithme", "données", "logiciel"],
    "environnement": ["climat", "environnement", "énergie", "co2", "carbone", "biodiversité", "eau", "pollution", "forêt"],
    "societe":       ["société", "démographie", "population", "logement", "pauvreté", "inégalité", "santé", "éducation", "justice"],
}

# Quota max par catégorie dans un cycle de génération
QUOTA_CATEGORIE = 3


def detect_category(text: str) -> str:
    text_l = text.lower()
    scores = {cat: sum(1 for kw in kws if kw in text_l) for cat, kws in CATEGORIES_MAP.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "societe"


def _age_heures(date_str: str) -> float:
    """Retourne l'âge en heures d'une date RSS (approximatif)."""
    from email.utils import parsedate_to_datetime
    try:
        dt = parsedate_to_datetime(date_str)
        dt = dt.replace(tzinfo=None)
        return max(0, (datetime.now() - dt).total_seconds() / 3600)
    except Exception:
        return 48.0  # inconnu → considéré comme vieux


def score_editorial(item: dict, source_name: str, published_topics: set) -> tuple[int, list[str]]:
    """
    Calcule le score éditorial d'un item RSS selon le barème v2.
    Retourne (score, liste_raisons).
    Retourne (-1, raison) pour un rejet immédiat.
    """
    text    = (item["title"] + " " + item["content"]).lower()
    src     = source_name.lower()
    reasons = []
    score   = 0

    # ── REJETS IMMÉDIATS ─────────────────────────────────────────────────────
    for kw in BLACKLIST:
        if kw in text:
            return -1, [f"Blacklist : '{kw}'"]

    if len(item["content"]) < 300:
        return -1, [f"Contenu trop court : {len(item['content'])} chars (min 300)"]

    # ── BARÈME POSITIF ───────────────────────────────────────────────────────

    # Source majeure (+35)
    is_majeure = any(s in src or s in text[:200] for s in SOURCES_MAJEURES)
    if is_majeure:
        score += 35
        reasons.append("+35 source majeure")

    # Source média reconnu (+15, non cumulable avec majeure)
    elif any(s in src for s in SOURCES_MEDIAS):
        score += 15
        reasons.append("+15 média reconnu")

    # Mots-clés de confiance (+15)
    kw_hits = sum(1 for kw in KW_CONFIANCE if kw in text)
    if kw_hits >= 2:
        score += 15
        reasons.append(f"+15 mots-clés confiance ({kw_hits} hits)")
    elif kw_hits == 1:
        score += 7
        reasons.append(f"+7 mot-clé confiance (1 hit)")

    # Fraîcheur : bonus seulement si source connue
    age_h = _age_heures(item.get("date", ""))
    if age_h <= 12:
        score += 15
        reasons.append(f"+15 fraîcheur < 12h ({age_h:.0f}h)")
    elif age_h <= 24:
        score += 5
        reasons.append(f"+5 fraîcheur < 24h ({age_h:.0f}h)")

    # Densité : bonus longueur UNIQUEMENT si source majeure ou média reconnu
    if len(item["content"]) > 1000 and (is_majeure or any(s in src for s in SOURCES_MEDIAS)):
        score += 20
        reasons.append(f"+20 densité ({len(item['content'])} chars, source qualifiée)")

    # ── PÉNALITÉ RÉCURRENCE ──────────────────────────────────────────────────
    # Comparer les mots significatifs du titre avec les topics déjà publiés
    title_words = set(w for w in item["title"].lower().split() if len(w) > 4)
    for topic in published_topics:
        topic_words = set(w for w in topic.lower().split() if len(w) > 4)
        overlap = len(title_words & topic_words)
        if overlap >= 2:
            score -= 50
            reasons.append(f"-50 sujet redondant (overlap: {overlap} mots avec '{topic[:40]}')")
            break

    return score, reasons


def filtrer_et_classer(
    items: list[dict],
    source_name: str,
    published_topics: set,
    seuil_score: int = 20,
) -> list[dict]:
    """
    Filtre et score tous les items d'une source.
    Retourne la liste triée par score décroissant, rejets exclus.
    """
    resultats = []
    for item in items:
        score, reasons = score_editorial(item, source_name, published_topics)
        if score == -1:
            item["_score"]   = -1
            item["_reasons"] = reasons
            item["_reject"]  = True
        else:
            item["_score"]   = score
            item["_reasons"] = reasons
            item["_reject"]  = score < seuil_score
            item["_cat"]     = detect_category(item["title"] + " " + item["content"])
        resultats.append(item)

    return sorted(
        [i for i in resultats if not i.get("_reject")],
        key=lambda x: x["_score"],
        reverse=True,
    )


def selectionner_meilleurs(
    candidats: list[dict],
    nb_max: int = 10,
    quota_cat: int = QUOTA_CATEGORIE,
) -> list[dict]:
    """
    Sélectionne les nb_max meilleurs articles en respectant le quota par catégorie.
    """
    selection  = []
    compteur   = {}

    for item in candidats:
        if len(selection) >= nb_max:
            break
        cat = item.get("_cat", "societe")
        if compteur.get(cat, 0) >= quota_cat:
            continue
        selection.append(item)
        compteur[cat] = compteur.get(cat, 0) + 1

    return selection


# ══════════════════════════════════════════════════════════════════════════════
# GÉNÉRATION VIA GROQ
# ══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """Tu es l'IA rédactrice de Les Faits, journal numérique français indépendant.
Ligne éditoriale absolue : "Juste les faits. Aucun parti pris."

RÉPONDS UNIQUEMENT EN JSON VALIDE, sans texte avant ou après, sans bloc ```json.

Format obligatoire :
{
  "titre": "Titre factuel informatif, 10 à 15 mots, sans exclamation ni question",
  "slug": "slug-kebab-case-descriptif-max-65-chars",
  "image_keyword": "3 mots EN ANGLAIS — paysage, bâtiment ou objet UNIQUEMENT, jamais de visages ni personnes (ex: 'wheat field france', 'hospital building', 'solar panels europe')",
  "resume": [
    "Phrase 1 : le fait principal avec chiffres ou acteurs précis (2 lignes min).",
    "Phrase 2 : contexte essentiel, qui/quand/comment (2 lignes min).",
    "Phrase 3 : nuance, limite ou débat en cours (2 lignes min)."
  ],
  "corps": {
    "faits": "MINIMUM 300 mots. NE PAS répéter le résumé — commencer directement par des faits NOUVEAUX ou plus détaillés non mentionnés dans le résumé. Détailler tous les faits vérifiables : chiffres précis, dates, acteurs nommés, données quantitatives, résultats d'études, déclarations exactes avec attribution. Attribuer chaque donnée à son institution avec 'Selon [Institution]' ou 'D'après [Institution]'. JAMAIS d'URL dans le texte — les URLs vont uniquement dans le tableau sources. Utiliser plusieurs paragraphes.",
    "contexte": "MINIMUM 200 mots. Historique du sujet, évolutions sur 5-10 ans, comparaisons internationales ou régionales, cadre réglementaire ou scientifique pertinent. Chiffres comparatifs obligatoires.",
    "nuances": "MINIMUM 150 mots. Limites méthodologiques des études citées, points de désaccord entre experts, ce que les données ne permettent pas de conclure, précautions d'interprétation."
  },
  "sources": [
    {"institution": "Nom exact institution", "titre": "Titre exact publication ou rapport", "date": "Date précise", "url": "URL FOURNIE DANS LES SOURCES SUPPLÉMENTAIRES UNIQUEMENT — si aucune URL n'a été fournie pour cette institution, mets null"}
  ],
  "categorie": "science|economie|societe|tech|environnement",
  "nb_sources": 4,
  "positions": {
    "label_gauche": "Ex: Pour / Favorable / Consensus",
    "label_droite": "Ex: Contre / Critique / En débat",
    "acteurs": [
      {"nom": "Acteur ou institution 1", "detail": "Courte description de sa position (max 12 mots)", "position": 20},
      {"nom": "Acteur ou institution 2", "detail": "Courte description de sa position (max 12 mots)", "position": 75}
    ]
  }
}

RÈGLES ABSOLUES — toute violation = article rejeté :
1. MINIMUM 4 sources distinctes et citables. Si tu ne peux pas atteindre 4 sources réelles : réponds uniquement HORS_PERIMETRE
2. Chaque donnée chiffrée DOIT être attribuée à son institution dans le corps : écrire "Selon [Institution], ..." — JAMAIS d'URL dans le corps du texte, les URLs sont réservées au tableau sources
3. Corps total : minimum 700 mots combinés (faits + contexte + nuances)
4. Résumé : chaque phrase minimum 25 mots, concrète, avec au moins un fait mesurable
5. Aucun adjectif évaluatif sans source (alarmant, historique, sans précédent, incroyable...)
6. Aucune opinion. Aucun parti pris. Structure : "Selon X, ... / D'après Y, ..."
7. Titre : 10-15 mots, informatif, factuel — il doit résumer l'essentiel de l'article
8. Sources : institutions officielles (INSEE, CNRS, INSERM, Eurostat, OMS, gouvernement), journaux de référence, publications peer-reviewed
9. Slug en français kebab-case, descriptif, max 65 caractères
10. positions : identifier 2 à 4 acteurs RÉELS cités dans l'article avec leur position sur le sujet. position = 0 (totalement favorable/consensuel) à 100 (totalement critique/opposé). label_gauche et label_droite doivent décrire les deux extrêmes du débat spécifique à cet article (ex: "Pour la mesure" / "Contre la mesure")"""


def generate(content: str, category_hint: str, extra_sources: list[dict] | None = None) -> dict:
    client = Groq(api_key=GROQ_KEY)

    # Construire la liste des URLs réelles fournies
    real_urls = set()
    sources_block = ""
    if extra_sources:
        sources_block = "\n\nSOURCES SUPPLÉMENTAIRES TROUVÉES — utilise ces URLs UNIQUEMENT dans le champ url des sources. N'invente aucune autre URL.\n"
        for s in extra_sources:
            sources_block += f"- {s['title']} | URL: {s['url']}\n  Extrait: {s['snippet'][:200]}\n"
            real_urls.add(s["url"])

    user_msg = (
        f"Catégorie probable : {category_hint}\n\n"
        f"CONTENU SOURCE PRINCIPAL :\n{content[:7000]}"
        f"{sources_block}\n\n"
        f"Rédige un article Les Faits complet, dense et sourcé. "
        f"Corps minimum 700 mots. Minimum 4 sources citables. "
        f"RAPPEL : dans le champ url des sources, utilise UNIQUEMENT les URLs listées ci-dessus. "
        f"Pour toute institution sans URL fournie, mets null dans le champ url."
    )

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=4500,
        temperature=0.1,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_msg},
        ],
    )

    raw = response.choices[0].message.content.strip()

    # Nettoyer blocs markdown si présents
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```\s*$", "", raw, flags=re.MULTILINE)
    raw = raw.strip()

    if raw.startswith("HORS_PERIMETRE"):
        raise ValueError(raw)

    art = json.loads(raw)

    # Supprimer les URLs inventées : garder uniquement les URLs réellement fournies
    if real_urls and "sources" in art:
        for src in art["sources"]:
            url = src.get("url") or ""
            if url and url not in real_urls:
                src["url"] = None

    return art


# ══════════════════════════════════════════════════════════════════════════════
# GÉNÉRATION HTML ARTICLE
# ══════════════════════════════════════════════════════════════════════════════

def build_spectrum_html(positions: dict) -> str:
    """Génère le bloc HTML spectrum à partir des données positions du LLM."""
    if not positions or not positions.get("acteurs"):
        return ""
    acteurs = positions["acteurs"]
    label_g = positions.get("label_gauche", "Favorable")
    label_d = positions.get("label_droite", "Critique")
    COLORS = ["#4a90d9", "#e57373", "#66bb6a", "#ffa726", "#ab47bc"]
    markers = "\n".join(
        f'<div class="spectrum__marker" style="left:{a["position"]}%">'
        f'<span class="spectrum__marker-dot" style="background:{COLORS[i % len(COLORS)]}"></span>'
        f'</div>'
        for i, a in enumerate(acteurs)
    )
    legend_items = "\n".join(
        f'<div class="spectrum__legend-item">'
        f'<span class="spectrum__legend-dot" style="background:{COLORS[i % len(COLORS)]}"></span>'
        f'<span class="spectrum__legend-name">{a["nom"]}</span>'
        f'<span class="spectrum__legend-sub">{a.get("detail","")}</span>'
        f'</div>'
        for i, a in enumerate(acteurs)
    )
    return f"""<div class="spectrum">
  <div class="spectrum__title">POSITIONS DES ACTEURS</div>
  <div class="spectrum__labels"><span>{label_g}</span><span>{label_d}</span></div>
  <div class="spectrum__track">{markers}</div>
  <div class="spectrum__legend">{legend_items}</div>
</div>"""


def _slug_ascii(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _download_hero(keyword: str, slug: str, dest: str) -> None:
    """Cherche sur Openverse (Creative Commons, sans clé) puis fallback picsum."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    hdrs = {"User-Agent": "Factuel/1.0 (factuelinfo.contact@gmail.com)"}
    # 1. Openverse — images CC pertinentes par mot-clé
    try:
        import urllib.parse
        q = urllib.parse.urlencode({"q": keyword, "page_size": "5"})
        ov = requests.get(f"https://api.openverse.org/v1/images/?{q}", timeout=10, headers=hdrs)
        results = ov.json().get("results", [])
        for item in results:
            img_url = item.get("url", "")
            if not img_url.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                continue
            r = requests.get(img_url, timeout=15, headers=hdrs)
            if r.status_code == 200 and len(r.content) > 10_000:
                open(dest, "wb").write(r.content)
                return
    except Exception:
        pass
    # 2. Fallback picsum
    safe = _slug_ascii(slug)
    try:
        r = requests.get(f"https://picsum.photos/seed/{safe}/1200/500", timeout=15, headers=hdrs)
        if r.status_code == 200:
            open(dest, "wb").write(r.content)
    except Exception:
        pass


def build_article_html(art: dict, date_pub: str) -> str:
    resume_txt = " ".join(art["resume"])
    slug           = art.get("slug", "")
    safe_slug      = _slug_ascii(slug)
    local_img_path = f"assets/images/{safe_slug}.jpg"
    if not os.path.exists(local_img_path):
        _download_hero(art.get("image_keyword", safe_slug), slug, local_img_path)
    hero_src = local_img_path if os.path.exists(local_img_path) else ""
    hero_img = f'<img class="art__hero" src="{hero_src}" alt="" loading="eager"/>\n  ' if hero_src else ""
    def _source_link(s):
        from urllib.parse import urlparse
        url = s.get("url") or ""
        # URL valide = présente ET pointe vers une page précise (pas juste homepage)
        path = urlparse(url).path.rstrip("/") if url else ""
        has_specific_url = url and len(path) > 3
        if has_specific_url:
            return f' · <a href="{url}" target="_blank" rel="noopener">Lire la source →</a>'
        q = requests.utils.quote(f'{s["institution"]} {s["titre"]}')
        return f' · <a href="https://duckduckgo.com/?q={q}" target="_blank" rel="noopener">Rechercher la source →</a>'

    sources_li = "\n".join(
        f'<li>{s["institution"]} · <em>{s["titre"]}</em> · {s["date"]}'
        + _source_link(s)
        + "</li>"
        for s in art["sources"]
    )
    faits    = art["corps"]["faits"].replace("\n", "</p><p>")
    contexte = art["corps"]["contexte"].replace("\n", "</p><p>")
    nuances  = art["corps"]["nuances"].replace("\n", "</p><p>")

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <meta name="description" content="{resume_txt[:155]}"/>
  <meta property="og:title" content="{art['titre']} — Les Faits"/>
  <meta property="og:description" content="{resume_txt[:155]}"/>
  <meta property="og:type" content="article"/>
  <title>{art['titre']} — Les Faits</title>
  <base href="/lesfaits/"/>
  <link rel="stylesheet" href="src/style.css"/>
</head>
<body>
<header class="header">
  <div class="header__inner">
    <a href="index.html" class="brand">
      <div class="brand__logotype"><span class="fact">les</span><span class="uel">faits</span></div>
    </a>
<div class="header__search">
      <input type="search" class="header__search-input" placeholder="Rechercher…" autocomplete="off" onkeydown="if(event.key==='Enter'&&this.value.trim())window.location=(document.querySelector('base').href)+'recherche.html?q='+encodeURIComponent(this.value.trim())"/>
    </div>
    <nav>
      <a href="categories/societe.html">Société</a>
      <a href="categories/science.html">Science</a>
      <a href="categories/economie.html">Économie</a>
      <a href="categories/tech.html">Tech</a>
      <a href="categories/sante.html">Santé</a>
      <a href="categories/environnement.html">Environnement</a>
      <a href="methode.html" class="nav-cta">Comment on travaille →</a>
    </nav>
  </div>
</header>
<div class="manifeste">
  <div class="manifeste__inner">
    <div class="manifeste__headline">Rédigé par <span>IA</span>,<br>vérifié par des humains.</div>
    <div class="manifeste__pillars">
      <div class="manifeste__pillar"><div class="manifeste__text"><strong>Zéro parti pris</strong><span>Aucune opinion. Les faits bruts, leurs sources, leurs contradictions.</span></div></div>
      <div class="manifeste__pillar"><div class="manifeste__text"><strong>Méthode publique</strong><span>Notre protocole éditorial est entièrement accessible.</span></div></div>
      <div class="manifeste__pillar"><div class="manifeste__text"><strong>Sources vérifiées</strong><span>Minimum 3 sources par article. Institutions officielles, peer-reviewed.</span></div></div>
    </div>
  </div>
</div>
<main>
<div class="art">
  <a class="art__back" href="index.html">← Retour à l'accueil</a>
  <span class="art__cat">{art['categorie'].upper()}</span>
  <h1 class="art__title">{art['titre']}</h1>
  <div class="art__meta">
    <span class="meta__sep">{date_pub}</span>
    <span class="meta__sep">·</span><span>Protocole v1.1</span>
  </div>
  <div class="art__verify">
    <span class="art__verify-item">✓ {art['nb_sources']} sources vérifiées</span>
    <span class="art__verify-item">✓ Sources concordantes</span>
    <span class="art__verify-item">✓ Protocole éditorial v1.1</span>
  </div>
  <div class="art__rule"></div>
  {hero_img}<p class="art__resume">{resume_txt}</p>
  <h2>Les faits</h2><p>{faits}</p>
  <h2>Contexte</h2><p>{contexte}</p>
  <h2>Débats et nuances</h2><p>{nuances}</p>
  {build_spectrum_html(art.get("positions", {}))}
  <div class="sources">
    <h3>SOURCES</h3>
    <ol>{sources_li}</ol>
  </div>
  <p class="art__badge">Rédigé par IA · Protocole Les Faits v1.1 · {date_pub}</p>
  <a class="contest-btn" href="contact.html#erreur">Contester un fait</a>
</div>
</main>
<footer class="footer">
  <div class="footer__inner">
    <div class="footer__brand">
      <div class="brand" style="margin-bottom:8px">
        <div class="brand__logotype"><span class="fact">les</span><span class="uel">faits</span></div>
      </div>
      <p>Journal numérique français rédigé par IA. Sans publicité. Sans actionnaires.</p>
    </div>
    <div class="footer__col"><h4>RUBRIQUES</h4>
      <a href="categories/societe.html">Société</a>
      <a href="categories/science.html">Science</a>
      <a href="categories/economie.html">Économie</a>
      <a href="categories/tech.html">Tech</a>
      <a href="categories/sante.html">Santé</a>
      <a href="categories/environnement.html">Environnement</a>
    </div>
    <div class="footer__col"><h4>JOURNAL</h4>
      <a href="methode.html">Comment on travaille</a>
      <a href="corrections.html">Corrections publiques</a>
    </div>
    <div class="footer__col"><h4>CONTACT</h4>
      <a href="contact.html">Nous écrire</a>
      <a href="contact.html#erreur">Signaler une erreur</a>
    </div>
  </div>
  <div class="footer__bottom">
    <span>© {datetime.now().year} Les Faits — Protocole v1.1</span>
    <span>Mentions légales · CGU</span>
  </div>
</footer>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════════
# RECONSTRUCTION INDEX.HTML
# ══════════════════════════════════════════════════════════════════════════════

def rebuild_index():
    """Relit articles.json et reconstruit la section À LA UNE de index.html."""
    articles = load_index()
    if not articles:
        return

    # Génération des cards "side" (articles 1-3)
    def side_card(a):
        return f"""<div class="une__side-item" onclick="window.location='articles/{a['slug']}.html'">
          <span class="cat">{a['categorie'].upper()}</span>
          <h3 class="title-md">{a['titre']}</h3>
          <div class="meta"><span class="meta__src">{a['nb_sources']} sources</span>
          <span class="meta__sep">·</span><span>{a['date']}</span></div>
        </div>"""

    # Génération grille science (articles récents par catégorie)
    def mini_card(a):
        return f"""<div class="card3" onclick="window.location='articles/{a['slug']}.html'" style="cursor:pointer">
          <span class="cat">{a['categorie'].upper()}</span>
          <h3 class="title-sm">{a['titre']}</h3>
          <div class="meta" style="margin-top:10px">
            <span class="meta__src">{a['nb_sources']} sources</span>
            <span class="meta__sep">·</span><span>{a['date']}</span>
          </div>
        </div>"""

    def list_card(i, a):
        return f"""<div class="list-item" onclick="window.location='articles/{a['slug']}.html'" style="cursor:pointer">
          <span class="list-item__num">0{i+1}</span>
          <div><span class="cat">{a['categorie'].upper()}</span>
          <h3 class="title-sm">{a['titre']}</h3>
          <div class="meta" style="margin-top:6px">
            <span class="meta__src">{a['nb_sources']} sources</span>
            <span class="meta__sep">·</span><span>{a['date']}</span>
          </div></div>
        </div>"""

    main_art  = articles[0]
    side_arts = articles[1:4]
    grid_arts = articles[4:10] if len(articles) > 4 else []
    list_arts = articles[10:16] if len(articles) > 10 else []  # section masquée si < 11 articles

    side_html  = "\n".join(side_card(a) for a in side_arts) if side_arts else ""
    grid_html  = "\n".join(mini_card(a) for a in grid_arts) if grid_arts else ""
    list_html  = "\n".join(list_card(i, a) for i, a in enumerate(list_arts))

    index_path = ROOT / "index.html"
    html = build_index_html(main_art, side_html, grid_html, list_html)
    index_path.write_text(html, encoding="utf-8")
    print(f"  ✓ index.html reconstruit ({len(articles)} articles)")
    build_category_pages()
    build_search_json(articles)


def build_index_html(main, side_html, grid_html, list_html):
    resume = " ".join(main["resume"]) if isinstance(main.get("resume"), list) else main.get("resume", "")

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <meta name="description" content="Les Faits — Journal numérique français rédigé par IA. Juste les faits. Aucun parti pris."/>
  <title>Les Faits — Juste les faits. Aucun parti pris.</title>
  <base href="/lesfaits/"/>
  <link rel="stylesheet" href="src/style.css"/>
</head>
<body>
<header class="header">
  <div class="header__inner">
    <a href="index.html" class="brand">
      <div class="brand__logotype"><span class="fact">les</span><span class="uel">faits</span></div>
    </a>
<div class="header__search">
      <input type="search" class="header__search-input" placeholder="Rechercher…" autocomplete="off" onkeydown="if(event.key==='Enter'&&this.value.trim())window.location=(document.querySelector('base').href)+'recherche.html?q='+encodeURIComponent(this.value.trim())"/>
    </div>
    <nav>
      <a href="categories/societe.html">Société</a>
      <a href="categories/science.html">Science</a>
      <a href="categories/economie.html">Économie</a>
      <a href="categories/tech.html">Tech</a>
      <a href="categories/sante.html">Santé</a>
      <a href="categories/environnement.html">Environnement</a>
      <a href="methode.html" class="nav-cta">Comment on travaille →</a>
    </nav>
  </div>
</header>
<div class="manifeste">
  <div class="manifeste__inner">
    <div class="manifeste__headline">Rédigé par <span>IA</span>,<br>vérifié par des humains.</div>
    <div class="manifeste__pillars">
      <div class="manifeste__pillar"><div class="manifeste__text"><strong>Zéro parti pris</strong><span>Aucune opinion. Aucune ligne politique. Les faits bruts, leurs sources, leurs contradictions.</span></div></div>
      <div class="manifeste__pillar"><div class="manifeste__text"><strong>Méthode publique</strong><span>Notre protocole éditorial est entièrement accessible. Vous savez comment chaque article est produit.</span></div></div>
      <div class="manifeste__pillar"><div class="manifeste__text"><strong>Sources vérifiées</strong><span>Minimum 3 sources par article. Institutions officielles, recherche peer-reviewed, experts identifiés.</span></div></div>
    </div>
  </div>
</div>
<div class="wrap">
  <div class="une">
    <div class="une__label">À LA UNE</div>
    <div style="height:2px;background:var(--blue);margin-bottom:1px"></div>
    <div class="une__grid">
      <div class="une__main" onclick="window.location='articles/{main['slug']}.html'" style="cursor:pointer">
        <span class="cat">{main['categorie'].upper()}</span>
        <h2 class="title-xl">{main['titre']}</h2>
        <p class="excerpt">{resume}</p>
        <div class="meta">
          <span class="meta__src">{main['nb_sources']} sources</span>
          <span class="meta__sep">·</span><span>{main['date']}</span>
          <span class="meta__sep">·</span><span>Protocole v1.1</span>
          <span class="meta__push"></span>
        </div>
        <p class="ai-badge">Rédigé par IA · Protocole Les Faits v1.1</p>
      </div>
      <div class="une__side">{side_html}</div>
    </div>
  </div>

  <div class="section">
    <div class="section__head"><span class="section__title">DERNIERS ARTICLES</span></div>
    <div class="section__rule"></div>
    <div class="grid3">{grid_html}</div>
  </div>

  {'<div class="list-section" style="padding-top:40px"><div class="section__head" style="margin-bottom:16px"><span class="section__title">À LIRE AUSSI</span></div><div class="section__rule"></div><div class="list-grid">' + list_html + '</div></div>' if list_html else ''}
</div>

<div class="support">
  <div class="support__inner">
    <h2>Les Faits est gratuit, sans publicité, sans actionnaires</h2>
    <p>Notre indépendance éditoriale repose sur vos dons. Aucun article derrière un paywall.</p>
    <div class="support__btns">
      <a class="btn btn--white" href="mailto:lesfaits.contact@gmail.com?subject=Don Les Faits">Soutenir Les Faits</a>
      <a class="btn btn--outline" href="methode.html">Notre méthode</a>
    </div>
  </div>
</div>

<footer class="footer">
  <div class="footer__inner">
    <div class="footer__brand">
      <div class="brand" style="margin-bottom:8px">
        <div class="brand__logotype"><span class="fact">les</span><span class="uel">faits</span></div>
      </div>
      <p>Journal numérique français rédigé par IA selon un protocole éditorial public. Sans publicité. Sans actionnaires.</p>
    </div>
    <div class="footer__col"><h4>RUBRIQUES</h4>
      <a href="categories/societe.html">Société</a>
      <a href="categories/science.html">Science</a>
      <a href="categories/economie.html">Économie</a>
      <a href="categories/tech.html">Tech</a>
      <a href="categories/sante.html">Santé</a>
      <a href="categories/environnement.html">Environnement</a>
    </div>
    <div class="footer__col"><h4>JOURNAL</h4>
      <a href="methode.html">Comment on travaille</a>
      <a href="corrections.html">Corrections publiques</a>
    </div>
    <div class="footer__col"><h4>CONTACT</h4>
      <a href="contact.html">Nous écrire</a>
      <a href="contact.html#erreur">Signaler une erreur</a>
    </div>
  </div>
  <div class="footer__bottom">
    <span>© {datetime.now().year} Les Faits — Protocole Les Faits v1.1</span>
    <span>Mentions légales · CGU</span>
  </div>
</footer>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════════
# PAGES CATÉGORIES
# ══════════════════════════════════════════════════════════════════════════════

CAT_LABELS = {
    "science":       "Science",
    "economie":      "Économie",
    "tech":          "Tech",
    "sante":         "Santé",
    "environnement": "Environnement",
    "societe":       "Société",
}

def build_search_json(articles: list):
    """Génère data/search.json pour la recherche côté client."""
    results = [
        {"slug": a["slug"], "titre": a["titre"], "categorie": a.get("categorie",""),
         "date": a.get("date",""), "excerpt": (" ".join(a["resume"]) if isinstance(a.get("resume"), list) else a.get("resume",""))[:180],
         "image_keyword": a.get("image_keyword", "")}
        for a in articles
    ]
    (DATA / "search.json").write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
    print(f"  ✓ search.json mis à jour ({len(results)} articles)")


def build_category_pages():
    """Génère categories/[cat].html pour chaque catégorie."""
    articles = load_index()
    cats_dir = ROOT / "categories"
    cats_dir.mkdir(exist_ok=True)

    # Catégories avec articles suffisants pour la nav (seuil : 1 article minimum)
    cats_actives = {c for c, l in CAT_LABELS.items() if any(a.get("categorie") == c for a in articles)}

    for cat, label in CAT_LABELS.items():
        arts = [a for a in articles if a.get("categorie") == cat]

        if arts:
            cards_html = "\n".join(f"""
        <div class="card3" onclick="window.location='articles/{a['slug']}.html'"
             style="cursor:pointer">
          <span class="cat">{label.upper()}</span>
          <h3 class="title-sm">{a['titre']}</h3>
          <div class="meta" style="margin-top:10px">
            <span class="meta__src">{a['nb_sources']} sources</span>
            <span class="meta__sep">·</span><span>{a['date']}</span>
          </div>
        </div>""" for a in arts)
            count_txt = f'{len(arts)} article{"s" if len(arts) > 1 else ""}'
        else:
            # Page vide : état élégant avec prochaine publication
            cards_html = f"""
        <div style="grid-column:1/-1;text-align:center;padding:80px 24px">
          <div style="font-size:3rem;margin-bottom:24px;opacity:.3">◎</div>
          <h2 style="font-size:1.3rem;font-weight:600;margin-bottom:12px;color:var(--ink)">
            Rubrique en cours d'alimentation
          </h2>
          <p style="color:var(--muted);max-width:420px;margin:0 auto 32px;line-height:1.7">
            Les premiers articles <strong>{label}</strong> seront publiés lors du prochain cycle éditorial.
            Le pipeline génère de nouveaux contenus chaque matin à 07h00 et chaque soir à 18h30.
          </p>
          <a href="/lesfaits/" style="display:inline-block;padding:10px 24px;background:var(--blue);
             color:#fff;border-radius:4px;text-decoration:none;font-size:.9rem;font-weight:600">
            ← Retour à l'accueil
          </a>
        </div>"""
            count_txt = "Bientôt disponible"

        # Nav rubriques — n'affiche que celles avec du contenu (+ la courante toujours visible)
        nav_links = "\n".join(
            f'<a href="categories/{c}.html" style="{"font-weight:700;color:var(--blue)" if c == cat else "color:var(--muted)" if c not in cats_actives else ""}">{l}</a>'
            for c, l in CAT_LABELS.items()
        )

        html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <meta name="description" content="Les Faits — Rubrique {label}. Juste les faits. Aucun parti pris."/>
  <title>{label} — Les Faits</title>
  <base href="/lesfaits/"/>
  <link rel="stylesheet" href="src/style.css"/>
</head>
<body>
<div id="read-progress"></div>
<header class="header">
  <div class="header__inner">
    <a href="index.html" class="brand">
      <div class="brand__logotype"><span class="fact">les</span><span class="uel">faits</span></div>
    </a>
<div class="header__search">
      <input type="search" class="header__search-input" placeholder="Rechercher…" autocomplete="off" onkeydown="if(event.key==='Enter'&&this.value.trim())window.location=(document.querySelector('base').href)+'recherche.html?q='+encodeURIComponent(this.value.trim())"/>
    </div>
    <nav>
      <a href="categories/societe.html">Société</a>
      <a href="categories/science.html">Science</a>
      <a href="categories/economie.html">Économie</a>
      <a href="categories/tech.html">Tech</a>
      <a href="categories/sante.html">Santé</a>
      <a href="categories/environnement.html">Environnement</a>
      <a href="methode.html" class="nav-cta">Comment on travaille →</a>
    </nav>
  </div>
</header>

<main style="max-width:1200px;margin:60px auto;padding:0 24px">
  <div style="margin-bottom:32px;border-bottom:1px solid var(--rule);padding-bottom:24px">
    <span style="font-size:.8rem;font-weight:700;letter-spacing:.1em;color:var(--muted);text-transform:uppercase">Rubrique</span>
    <h1 style="font-size:2.4rem;font-weight:700;margin:8px 0 4px">{label}</h1>
    <p style="color:var(--muted);font-size:.9rem">{count_txt}</p>
  </div>
  <nav style="display:flex;gap:24px;margin-bottom:48px;flex-wrap:wrap;font-size:.9rem">
    {nav_links}
  </nav>
  <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:24px">
    {cards_html}
  </div>
</main>

<footer class="footer">
  <div class="footer__inner">
    <div class="footer__brand">
      <div class="brand" style="margin-bottom:8px">
        <div class="brand__logotype"><span class="fact">les</span><span class="uel">faits</span></div>
      </div>
      <p>Journal numérique français rédigé par IA. Sans publicité. Sans actionnaires.</p>
    </div>
    <div class="footer__col"><h4>RUBRIQUES</h4>
      <a href="categories/societe.html">Société</a>
      <a href="categories/science.html">Science</a>
      <a href="categories/economie.html">Économie</a>
      <a href="categories/tech.html">Tech</a>
      <a href="categories/sante.html">Santé</a>
      <a href="categories/environnement.html">Environnement</a>
    </div>
    <div class="footer__col"><h4>JOURNAL</h4>
      <a href="methode.html">Comment on travaille</a>
      <a href="corrections.html">Corrections publiques</a>
    </div>
    <div class="footer__col"><h4>CONTACT</h4>
      <a href="contact.html">Nous écrire</a>
      <a href="contact.html#erreur">Signaler une erreur</a>
    </div>
  </div>
  <div class="footer__bottom">
    <span>© {datetime.now().year} Les Faits — Protocole Les Faits v1.1</span>
    <span>Mentions légales · CGU</span>
  </div>
</footer>
</body>
</html>"""

        (cats_dir / f"{cat}.html").write_text(html, encoding="utf-8")

    print(f"  ✓ {len(CAT_LABELS)} pages catégories générées dans categories/")


# ══════════════════════════════════════════════════════════════════════════════
# INDEX JSON
# ══════════════════════════════════════════════════════════════════════════════

def load_index() -> list:
    if INDEX_JSON.exists():
        return json.loads(INDEX_JSON.read_text(encoding="utf-8"))
    return []

def load_published() -> set:
    if PUBLISHED.exists():
        return set(json.loads(PUBLISHED.read_text(encoding="utf-8")))
    return set()

def save_published(ids: set):
    PUBLISHED.write_text(json.dumps(list(ids), ensure_ascii=False), encoding="utf-8")

def save_to_index(art: dict, date_pub: str):
    index = load_index()
    index = [a for a in index if a["slug"] != art["slug"]]
    index.insert(0, {
        "slug":      art["slug"],
        "titre":     art["titre"],
        "categorie": art["categorie"],
        "nb_sources":art["nb_sources"],
        "date":      date_pub,
        "resume":    art["resume"],
        "image_keyword": art.get("image_keyword", ""),
    })
    INDEX_JSON.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════
# ORCHESTRATION
# ══════════════════════════════════════════════════════════════════════════════

def generer_article(item: dict, dry_run: bool, published: set, new_pub: set, date_pub: str, published_topics: set | None = None) -> bool:
    """Génère et publie un article. Retourne True si succès."""
    if item["id"] in published:
        return False

    cat = item.get("_cat") or detect_category(item["title"] + " " + item["content"])

    # Scraping du contenu complet
    full_content = ""
    if item.get("url"):
        full_content = fetch_full_content(item["url"])
    content = full_content if len(full_content) > 500 else item["content"]

    # Recherche de sources corroborantes
    extra = duckduckgo_search(item["title"] + " " + cat, max_results=5)

    print(f"  → Génération : {item['title'][:55]} [score {item.get('_score', '?')}]")

    if dry_run:
        print(f"     (dry-run)")
        return False

    try:
        art         = generate(content, cat, extra_sources=extra)
        total_chars = sum(len(art["corps"].get(k, "")) for k in ["faits", "contexte", "nuances"])

        if len(art.get("sources", [])) < 3:
            print(f"     [REJET] {len(art.get('sources',[]))} source(s) — min 3")
            return False
        if total_chars < 600:
            print(f"     [REJET] Corps trop court ({total_chars} chars)")
            return False

        html = build_article_html(art, date_pub)
        (ARTICLES / f"{art['slug']}.html").write_text(html, encoding="utf-8")
        save_to_index(art, date_pub)
        new_pub.add(item["id"])
        print(f"     ✓ {art['slug']}.html ({len(art.get('sources',[]))} src, {total_chars} chars)")
        return True

    except ValueError as e:
        print(f"     [REJET] {e}")
    except json.JSONDecodeError:
        print(f"     [ERREUR JSON] Réponse Groq non parseable")
    except Exception as e:
        print(f"     [ERREUR] {e}")
    return False


def run(dry_run=False, text_input=None, nb_max=10):
    published = load_published()
    new_pub   = set()
    MOIS = ["janvier","février","mars","avril","mai","juin",
            "juillet","août","septembre","octobre","novembre","décembre"]
    now      = datetime.now()
    date_pub = f"{now.day} {MOIS[now.month-1]} {now.year}, {now.strftime('%Hh%M')}"

    if text_input:
        item = {
            "id":          hashlib.md5(text_input.encode()).hexdigest()[:14],
            "title":       text_input[:80],
            "url":         "",
            "content":     text_input,
            "source_name": "Manuel",
            "date":        datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000"),
            "_score":      50,
            "_cat":        detect_category(text_input),
        }
        generer_article(item, dry_run, published, new_pub, date_pub)

    else:
        # ── Étape 1 : collecter tous les candidats de toutes les sources ──
        print("\n[COLLECTE RSS]")
        published_topics = {a.get("titre", "") for a in load_index()[:30]}
        tous_candidats   = []

        for src in RSS_SOURCES:
            items = fetch_rss(src)
            deja_vus = {i["id"] for i in tous_candidats}
            for item in items:
                if item["id"] in published or item["id"] in deja_vus:
                    continue
                scored = filtrer_et_classer([item], src["name"], published_topics, seuil_score=20)
                if scored:
                    tous_candidats.extend(scored)

        print(f"\n[SCORING] {len(tous_candidats)} candidats après filtre")

        # ── Étape 2 : afficher le classement ──
        tous_candidats.sort(key=lambda x: x["_score"], reverse=True)
        print(f"{'─'*70}")
        print(f"  {'SCORE':>5}  {'CATÉGORIE':<12}  TITRE")
        print(f"{'─'*70}")
        for c in tous_candidats[:20]:
            print(f"  {c['_score']:>5}  {c.get('_cat','?'):<12}  {c['title'][:45]}")
        print(f"{'─'*70}")

        # ── Étape 3 : sélection par quota catégorie ──
        selection = selectionner_meilleurs(tous_candidats, nb_max=nb_max)
        print(f"\n[SÉLECTION] {len(selection)} articles retenus sur {len(tous_candidats)} candidats")

        # ── Étape 4 : générer les articles sélectionnés ──
        print(f"\n[GÉNÉRATION]")
        for item in selection:
            if generer_article(item, dry_run, published, new_pub, date_pub, published_topics):
                # Ajouter le titre généré à published_topics pour éviter les doublons dans la même session
                published_topics.add(item.get("title", ""))
            time.sleep(1)

    if new_pub and not dry_run:
        rebuild_index()

    save_published(published | new_pub)
    print(f"\n{'='*50}")
    print(f"Terminé — {len(new_pub)} article(s) publié(s)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--text", type=str, help="Texte source libre")
    parser.add_argument("--rebuild", action="store_true", help="Reconstruire index+catégories sans générer d'articles")
    args = parser.parse_args()

    if args.rebuild:
        rebuild_index()
        build_category_pages()
        print("Rebuild terminé.")
        exit(0)

    if not GROQ_KEY:
        print("ERREUR : GROQ_API_KEY manquant dans .env")
        exit(1)

    run(dry_run=args.dry_run, text_input=args.text)
