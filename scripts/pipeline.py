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
from zoneinfo import ZoneInfo
from pathlib import Path
from xml.etree import ElementTree as ET
from urllib.parse import urlparse
import urllib.parse

from groq import Groq
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Vérification éditoriale 3 passes (Anthropic) — inactive sans ANTHROPIC_API_KEY
from verification import verifier_article, ANTHROPIC_KEY as _ANTHROPIC_KEY
from html import escape as _esc

def _esc_json(s: str) -> str:
    """Échappement sûr pour insertion dans un bloc <script type=application/ld+json>."""
    return json.dumps(s or "")[1:-1].replace("</", "<\\/")

def _esc_js(s: str) -> str:
    """Échappement sûr pour insertion dans une chaîne JS entre apostrophes."""
    return (s or "").replace("\\", "\\\\").replace("'", "\\'").replace("</", "<\\/")


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

# ── URL de base du site public ─────────────────────────────────────────────────
BASE_URL = "https://lesfaits.info"

GROQ_KEY       = os.getenv("GROQ_API_KEY", "")
GROQ_KEY2      = os.getenv("GROQ_API_KEY_2", "")
GROQ_KEY3      = os.getenv("GROQ_API_KEY_3", "")
PEXELS_KEY     = os.getenv("PEXELS_API_KEY", "")
PIXABAY_KEY    = os.getenv("PIXABAY_API_KEY", "")

# ══════════════════════════════════════════════════════════════════════════════
# SOURCES RSS — retournent du texte propre, pas de JavaScript
# ══════════════════════════════════════════════════════════════════════════════

RSS_SOURCES = [
    # Le Monde — rubriques thématiques
    {"name": "Le Monde Science",     "url": "https://www.lemonde.fr/sciences/rss_full.xml"},
    {"name": "Le Monde Planète",     "url": "https://www.lemonde.fr/planete/rss_full.xml"},
    {"name": "Le Monde Santé",       "url": "https://www.lemonde.fr/sante/rss_full.xml"},
    {"name": "Le Monde Economie",    "url": "https://www.lemonde.fr/economie/rss_full.xml"},
    {"name": "Le Monde Société",     "url": "https://www.lemonde.fr/societe/rss_full.xml"},
    {"name": "Le Monde Pixel",       "url": "https://www.lemonde.fr/pixels/rss_full.xml"},
    # Libération
    {"name": "Libération",           "url": "https://www.liberation.fr/arc/outboundfeeds/rss/?outputType=xml"},
    # France Info
    {"name": "France Info",          "url": "https://www.francetvinfo.fr/titres.rss"},
    # Sciences et Avenir
    {"name": "Sciences et Avenir",   "url": "https://www.sciencesetavenir.fr/rss.xml"},
    # Le Figaro
    {"name": "Le Figaro Société",    "url": "https://www.lefigaro.fr/rss/figaro_societe.xml"},
    # Institutions françaises
    {"name": "Vie Publique",         "url": "https://www.vie-publique.fr/rss.xml"},
    # Science internationale
    {"name": "Futura Sciences",      "url": "https://www.futura-sciences.com/rss/actualites.xml"},
    {"name": "CNRS Actualités",      "url": "https://lejournal.cnrs.fr/rss"},
    # Santé publique
    {"name": "INSERM Actualités",    "url": "https://www.inserm.fr/feed/"},
    # Environnement
    {"name": "Reporterre",           "url": "https://reporterre.net/spip.php?page=backend"},
]

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}


# Éditeurs de presse protégés par les droits voisins (art. L218-1 CPI) :
# on ne scrape JAMAIS leur contenu intégral — seul le titre + la description
# courte du flux RSS public sont utilisés comme matière première.
_PRESSE_PROTEGEE = (
    "lemonde.fr", "liberation.fr", "lefigaro.fr", "leparisien.fr",
    "francetvinfo.fr", "franceinfo.fr", "sciencesetavenir.fr",
    "futura-sciences.com", "reporterre.net", "lepoint.fr", "lexpress.fr",
    "nouvelobs.com", "20minutes.fr", "bfmtv.com", "nicematin.com",
    "ouest-france.fr", "sudouest.fr", "lavoixdunord.fr", "letelegramme.fr",
    "ft.com",
)


def _est_presse_protegee(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return any(host == d or host.endswith("." + d) for d in _PRESSE_PROTEGEE)


# Domaines exclus des sources citables pour raison éditoriale (pas légale) :
# réseaux sociaux (pas de source originale vérifiable) et agrégateurs purs
# (MSN, Orange Actu, Google News republlient sans être la source primaire).
_SOURCES_EXCLUES = (
    "linkedin.com", "facebook.com", "twitter.com", "x.com",
    "instagram.com", "reddit.com", "youtube.com", "tiktok.com", "threads.net",
    "msn.com", "actu.orange.fr", "news.google.com", "flipboard.com",
)


def _est_source_exclue(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return any(host == d or host.endswith("." + d) for d in _SOURCES_EXCLUES)


# Table hostname→nom lisible pour le bloc SOURCES affiché aux lecteurs.
# Couvre les ~50 domaines les plus fréquents du corpus ; fallback sur le
# hostname nettoyé pour tout le reste.
_MEDIA_NOMS: dict[str, str] = {
    # Presse nationale française
    "lemonde.fr":            "Le Monde",
    "lefigaro.fr":           "Le Figaro",
    "leparisien.fr":         "Le Parisien",
    "liberation.fr":         "Libération",
    "lepoint.fr":            "Le Point",
    "lexpress.fr":           "L'Express",
    "nouvelobs.com":         "Le Nouvel Obs",
    "la-croix.com":          "La Croix",
    "mediapart.fr":          "Mediapart",
    "lopinion.fr":           "L'Opinion",
    "lesechos.fr":           "Les Échos",
    "ledevoir.com":          "Le Devoir",
    # Presse régionale / gratuits
    "20minutes.fr":          "20 Minutes",
    "ouest-france.fr":       "Ouest-France",
    "sudouest.fr":           "Sud Ouest",
    "lavoixdunord.fr":       "La Voix du Nord",
    "letelegramme.fr":       "Le Télégramme",
    "nicematin.com":         "Nice-Matin",
    "actu.fr":               "Actu.fr",
    # TV / Radio
    "franceinfo.fr":         "France Info",
    "francetvinfo.fr":       "France TV Info",
    "france24.com":          "France 24",
    "bfmtv.com":             "BFM TV",
    "rtl.fr":                "RTL",
    "rfi.fr":                "RFI",
    "rtbf.be":               "RTBF",
    "rts.ch":                "RTS",
    "tf1info.fr":            "TF1 Info",
    # Presse internationale
    "ft.com":                "Financial Times",
    "bbc.com":               "BBC",
    "bbc.co.uk":             "BBC",
    "theguardian.com":       "The Guardian",
    "nytimes.com":           "New York Times",
    "reuters.com":           "Reuters",
    "afp.com":               "AFP",
    "apnews.com":            "AP News",
    "euronews.com":          "Euronews",
    # Science / Tech
    "futura-sciences.com":   "Futura Sciences",
    "sciencesetavenir.fr":   "Sciences et Avenir",
    "science-et-vie.com":    "Science et Vie",
    "numerama.com":          "Numerama",
    "lesnumeriques.com":     "Les Numériques",
    "generation-nt.com":     "Generation NT",
    "techno-science.net":    "Techno-Science",
    "trustmyscience.com":    "Trust My Science",
    "maxisciences.com":      "Maxisciences",
    "notebookcheck.biz":     "NotebookCheck",
    "futurism.com":          "Futurism",
    "nationalgeographic.fr": "National Geographic",
    "geo.fr":                "Géo",
    # Institutionnel / référence
    "wikipedia.org":         "Wikipédia",
    "wikimedia.org":         "Wikimedia",
    "inserm.fr":             "Inserm",
    "cnrs.fr":               "CNRS",
    "vie-publique.fr":       "Vie Publique",
    "sante.gouv.fr":         "Ministère de la Santé",
    "pubmed.ncbi.nlm.nih.gov": "PubMed",
    # Santé / Conso
    "doctissimo.fr":         "Doctissimo",
    "topsante.com":          "Top Santé",
    # Finance / Éco
    "boursorama.com":        "Boursorama",
    "jeanmarcmorandini.com": "JM Morandini",
    "zdnet.fr":              "ZDNet",
    "reporterre.net":        "Reporterre",
}


def _media_name_from_url(url: str, title_hint: str = "") -> str:
    """Retourne le nom lisible du média depuis son URL.
    Priorité :
      1. Table _MEDIA_NOMS (lookup exact ou domaine racine)
      2. Suffixe extrait du titre DDG (pattern "Titre — Nom du Média")
      3. Fallback hostname nettoyé (stem, tirets→espaces, acronymes ≤3 car.)
    """
    try:
        host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""
    # 1. Lookup direct
    if host in _MEDIA_NOMS:
        return _MEDIA_NOMS[host]
    # Lookup sur le domaine racine (ex. fr.euronews.com → euronews.com)
    parts = host.split(".")
    if len(parts) >= 2:
        root = ".".join(parts[-2:])
        if root in _MEDIA_NOMS:
            return _MEDIA_NOMS[root]
    # 2. Extraction depuis le titre DDG ("Titre de l'article — Nom du Média")
    if title_hint:
        for sep in (" — ", " | ", " – ", " - "):
            if sep in title_hint:
                suffix = title_hint.rsplit(sep, 1)[-1].strip()
                # Valide si court, sans point (pas une URL) et sans "..."
                if 2 < len(suffix) < 45 and "." not in suffix and "..." not in suffix:
                    return suffix
    # 3. Fallback : stem du domaine racine, tirets→espaces, capitalize
    stem = parts[-2] if len(parts) >= 2 else host
    # Rejeter les TLDs purs (com, fr, net, org…) qui donnent des noms absurdes
    _TLDS = {"com", "fr", "net", "org", "info", "be", "ch", "eu", "gov", "edu", "io"}
    if stem in _TLDS:
        return host  # retourner le hostname complet en dernier recours
    words = stem.replace("-", " ").split()
    name = " ".join(w.upper() if len(w) <= 3 else w.capitalize() for w in words)
    return name or host


def fetch_full_content(url: str) -> str:
    """Scrape le contenu complet d'un article depuis son URL.
    Refuse les éditeurs de presse protégés (droits voisins)."""
    if _est_presse_protegee(url):
        return ""
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


def duckduckgo_search(query: str, max_results: int = 8) -> list[dict]:
    """Recherche DuckDuckGo via la librairie duckduckgo-search (endpoint API, pas scraping HTML)."""
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return []

    seen = set()
    results = []

    queries = [
        query,
        query + " rapport statistiques données officielles",
        query + " site:gouv.fr OR site:inserm.fr OR site:insee.fr OR site:who.int",
    ]

    for q in queries:
        try:
            with DDGS() as ddgs:
                for r in ddgs.text(q, max_results=10, region="fr-fr"):
                    url = r.get("href", "")
                    if not url or url in seen:
                        continue
                    if len(urlparse(url).path.rstrip("/")) <= 5:
                        continue
                    seen.add(url)
                    results.append({
                        "title":   r.get("title", ""),
                        "url":     url,
                        "snippet": r.get("body", ""),
                    })
        except Exception:
            pass
        if len(results) >= max_results:
            break

    return results[:max_results]


def pubmed_search(query_en: str, max_results: int = 4, min_year: int = 2022) -> list[dict]:
    """Recherche PubMed — uniquement articles récents (>= min_year), URLs garanties réelles."""
    try:
        r = requests.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            params={"db": "pubmed", "term": query_en, "retmax": max_results + 4,
                    "retmode": "json", "sort": "relevance",
                    "datetype": "pdat", "mindate": str(min_year), "maxdate": "3000"},
            headers=HEADERS, timeout=10
        )
        ids = r.json()["esearchresult"]["idlist"]
        results = []
        for pmid in ids:
            if len(results) >= max_results:
                break
            s = requests.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
                params={"db": "pubmed", "id": pmid, "retmode": "json"},
                headers=HEADERS, timeout=10
            )
            d = s.json()["result"].get(pmid, {})
            title = d.get("title", "")
            year = int(d.get("pubdate", "0")[:4] or 0)
            if title and year >= min_year:
                results.append({
                    "title":   title[:100],
                    "url":     f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    "snippet": f"{d.get('fulljournalname','')} ({year})",
                })
            time.sleep(0.35)
        return results
    except Exception:
        return []


def fetch_rss(source: dict) -> list[dict]:
    """Parse un flux RSS et retourne les items avec leur contenu texte."""
    try:
        # Header Accept explicite : certains serveurs (ex : inserm.fr) renvoient
        # 415 Unsupported Media Type quand la requête n'annonce pas les types
        # de flux attendus.
        rss_headers = {**HEADERS,
                       "Accept": "application/rss+xml, application/atom+xml, "
                                 "application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5"}
        try:
            r = requests.get(source["url"], headers=rss_headers, timeout=12)
            r.raise_for_status()
        except requests.HTTPError:
            # Second essai avec un User-Agent de lecteur de flux : certains WAF
            # bloquent les UA navigateur sur les endpoints /feed/.
            r = requests.get(source["url"],
                             headers={"User-Agent": "FactuelBot/1.0 (+https://lesfaits.fr) RSS reader",
                                      "Accept": rss_headers["Accept"]},
                             timeout=12)
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

            # Droits voisins : pour la presse protégée, on se limite à un court
            # extrait (titre + début de description), jamais le texte intégral
            # même s'il figure dans le flux (content:encoded).
            max_len = 1200 if _est_presse_protegee(link) else 6000
            items.append({
                "id":          hashlib.md5(link.encode()).hexdigest()[:14],
                "title":       title,
                "url":         link,
                "content":     (title + " " + content_clean)[:max_len],
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
    # Formats chroniques / lifestyle sans valeur informationnelle
    "de la semaine", "photo de la semaine", "plante de la semaine",
    "recette de", "le guide pour", "nos conseils pour",
    "top 10", "top 5", "sélection ", "notre sélection",
    "le goût musical", "les carnets de",
]

# Patterns de titres à faible valeur éditoriale (malus fort)
_TITRE_MALUS = [
    "guide ", "comment ", "pourquoi ", "où ", "quand ",
    "nos astuces", "tout savoir", "on vous explique",
]

# Contenu commercial déguisé en article : prix précis + enseigne de vente
_COMMERCE_RE = re.compile(
    r"(?:à partir de|dès|seulement|au prix de)\s*\d+[.,]?\d*\s*€"
    r"|\d+[.,]\d{2}\s*€\s*(?:chez|sur)\b"
    r"|chez\s+(?:cdiscount|amazon|aliexpress|rakuten|darty|boulanger|leclerc|carrefour)"
    r"|(?:cdiscount|aliexpress|rakuten)\b"
    # Bons plans / promos déguisés en article (ex: "le Dell 16 perd 350 euros").
    # Motifs volontairement étroits : "promotion" seul ou "moins cher" seul
    # apparaissent dans de vrais articles (promotion sociale, essence moins
    # chère) — on ne matche que le vocabulaire marketing sans ambiguïté.
    r"|bons? plans?\b|\bpromos?\b|\ben promo\b|ventes? flash|prix cassés?"
    r"|meilleures? offres?|\d+\s*%\s*de\s*r[ée]duction|offre à saisir"
    r"|perd\s+\d+\s*(?:euros|€)"
    r"|rapport qualité[- ]prix|code promo",
    re.IGNORECASE,
)

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
    "sante": [
        "santé", "hôpital", "hopita", "maladie", "cancer", "vaccin", "épidémie",
        "virus", "bactérie", "traitement", "médicament", "patient", "médecin",
        "chirurgie", "obésité", "diabète", "alzheimer", "démence", "cardiaque",
        "avc", "dépression", "psychiatr", "inserm", " oms ", "sommeil",
        "nutrition", "hypertension", "allergie", "grippe", "sida", "tumeur",
        "greffe", "urgences", "infirmi", "clinique", "symptôme", "diagnostic",
        "thérapie", "immunothérapie", "antibiotique", "asthme", "cholestérol",
        "sanitaire",
    ],
    "science": [
        "exoplanète", "planète", "astronomie", "astrophysique", "espace",
        "nasa", " esa ", "télescope", "galaxie", "astéroïde", "comète", "mars ",
        "lune ", "satellite", "fusée", "spatial", "cosmos", "orbite",
        "archéologie", "fossile", "dinosaure", "paléontolog", " adn ", "génome",
        "génétique", "neurone", "physique", "quantique", "chimie", "biologie",
        "espèce ", "cnrs", "étude ", "chercheurs", "scientifique", "laboratoire",
        "mathémati", "expérience ", "revue nature", "peer-review", "microbiote",
        "évolution ", "cellule", "molécule", "particule", "gravitation",
        "protéine", "rupestre", "préhistor", "séisme", "volcan", "supernova",
        "étoile", "milliards d'années", "géolog",
    ],
    "tech": [
        "smartphone", "iphone", "android", "ordinateur", "processeur", "puce",
        "semi-conducteur", "intelligence artificielle", " ia ", "chatgpt",
        "openai", "google", "apple", "microsoft", "meta ", "réseau social",
        "réseaux sociaux", "application", "logiciel", "cyberattaque", "hacker",
        "piratage", "données personnelles", "jeu vidéo", "jeux vidéo", "console",
        "xbox", "playstation", "nintendo", "robot", "drone", " 5g ", " 6g ",
        "startup", "start-up", "algorithme", "numérique", "internet", "wifi",
        "bluetooth", "cloud", "serveur", "streaming", "tiktok", "instagram",
        "bitcoin", "crypto", "blockchain", "informatique", "écran ", "batterie ",
        "centre de données", "centres de données", "data center", "cybersécurité",
        "logiciel espion", "surveillance numérique",
    ],
    "economie": [
        "économie", "inflation", " pib ", "croissance", "chômage", "emploi",
        "salaire", "smic", "budget", "déficit", "dette ", "impôt", "taxe",
        "bourse", "marché financier", "banque", " bce ", " fed ", "taux d'intérêt",
        "entreprise", "licenciement", "levée de fonds", "investissement",
        "commerce", "export", "industrie", "usine", "immobilier", "consommation",
        "pouvoir d'achat", "récession", "actionnaire", "fusion-acquisition",
        "faillite", "milliard", "chiffre d'affaires",
    ],
    "environnement": [
        "climat", "réchauffement", "canicule", "sécheresse", "inondation",
        "ouragan", "cyclone", " co2 ", "carbone", "émission", "biodiversité",
        "espèce menacée", "pollution", "plastique", "recyclage", "renouvelable",
        "solaire", "éolien", "forêt", "océan", "glacier", "banquise", "météo",
        "environnement", "écolog", "pesticide", "nappe phréatique", "incendie",
        "déforestation", "vague de chaleur", "montée des eaux", "permafrost",
    ],
    "societe": [
        "société", "justice", "procès", "tribunal", "police", "gendarmerie",
        "crime", "agression", "école", "éducation", "université", "logement",
        "pauvreté", "inégalité", "immigration", "retraite", "manifestation",
        "grève", "gouvernement", "ministre", "élection", "parlement", "loi ",
        "sénat", "assemblée", "maire", "démographie", "population", "banlieue",
        "prison", "attentat", "laïcité", "discrimination", "violences",
        "harcèlement", "féminicide", "syndicat", "référendum", "constitution",
        "politique", "historien", "patrimoine", "sans-papiers",
    ],
}

# Ordre de priorité en cas d'égalité de score : du plus spécifique au plus
# générique — "societe" est le fourre-tout, il ne gagne jamais une égalité.
_CAT_PRIORITE = ["sante", "science", "tech", "environnement", "economie", "societe"]

# Quota max par catégorie dans un cycle de génération
QUOTA_CATEGORIE = 3


def detect_category(text: str) -> str:
    """Classement déterministe par lexique pondéré : un mot-clé trouvé dans le
    titre (≈120 premiers caractères) pèse 3, dans le corps 1. En cas d'égalité,
    _CAT_PRIORITE départage du plus spécifique au plus générique."""
    text_l = text.lower()
    head   = text_l[:120]
    scores = {}
    for cat, kws in CATEGORIES_MAP.items():
        s = 0
        for kw in kws:
            if kw in head:
                s += 3
            elif kw in text_l:
                s += 1
        scores[cat] = s
    best = max(_CAT_PRIORITE, key=lambda c: scores[c])
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

    # Contenu commercial déguisé : prix + enseigne = article promotionnel
    if _COMMERCE_RE.search(text[:800]):
        return -1, ["Contenu commercial (prix/enseigne détectés)"]

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

    # ── PÉNALITÉ FORMAT CHRONIQUE / LIFESTYLE ───────────────────────────────
    title_lower = item["title"].lower()
    if any(p in title_lower for p in _TITRE_MALUS):
        score -= 20
        reasons.append("-20 titre format guide/conseil")

    # ── PÉNALITÉ RÉCURRENCE ──────────────────────────────────────────────────
    # Comparer les mots significatifs du titre avec les topics déjà publiés
    title_words = set(w for w in item["title"].lower().split() if len(w) > 5)
    for topic in published_topics:
        topic_words = set(w for w in topic.lower().split() if len(w) > 5)
        shared = title_words & topic_words
        overlap = len(shared)
        # Un seul mot commun suffit au rejet s'il est long donc très spécifique
        # (ex: "eutrophisation", "guanabara", "immunothérapie", "sublinguale") —
        # c'est le cas de tous les doublons passés au travers de l'ancien seuil.
        rare_match = overlap == 1 and max(len(w) for w in shared) >= 9
        if overlap >= 2 or rare_match:
            score -= 500  # rejet quasi-certain : même sujet déjà publié
            reasons.append(f"-500 sujet très redondant (overlap: {overlap}, mots: {sorted(shared)[:3]} avec '{topic[:40]}')")
            break
        elif overlap == 1:
            score -= 60
            reasons.append(f"-60 sujet proche (1 mot commun avec '{topic[:40]}')")
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
    selection = []
    compteur  = {}

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
    "Phrase 1 : le fait principal avec chiffres ou acteurs précis, REFORMULÉ avec un vocabulaire et une syntaxe DIFFÉRENTS de ceux utilisés dans 'faits' — jamais la même phrase ni les mêmes tournures (2 lignes min).",
    "Phrase 2 : contexte essentiel, qui/quand/comment, avec des mots différents de la section 'contexte' (2 lignes min).",
    "Phrase 3 : nuance, limite ou débat en cours (2 lignes min)."
  ],
  "corps": {
    "faits": "MINIMUM 300 mots. UNIQUEMENT l'actualité immédiate et ses données du jour : chiffres précis, dates, acteurs nommés, données quantitatives, résultats d'études récents, déclarations exactes avec attribution. NE JAMAIS inclure d'historique, d'évolution sur plusieurs années ni de comparaisons internationales — cela va exclusivement dans 'contexte'. NE PAS répéter le résumé mot pour mot ni avec les mêmes tournures — commencer directement par des faits NOUVEAUX ou plus détaillés non mentionnés dans le résumé. Attribuer chaque donnée à son institution avec 'Selon [Institution]' ou 'D'après [Institution]'. JAMAIS d'URL dans le texte — les URLs vont uniquement dans le tableau sources. Utiliser plusieurs paragraphes.",
    "contexte": "MINIMUM 200 mots. UNIQUEMENT de l'historique et de la mise en perspective : évolutions sur 5-10 ans, comparaisons internationales ou régionales, cadre réglementaire ou scientifique. NE JAMAIS reprendre les faits déjà énoncés dans 'faits' — les mettre en perspective, pas les répéter. Chiffres comparatifs obligatoires.",
    "nuances": "MINIMUM 150 mots. Limites méthodologiques des études citées, points de désaccord entre experts, ce que les données ne permettent pas de conclure, précautions d'interprétation."
  },
  "sources": [
    {"institution": "Nom exact institution", "titre": "Titre exact publication ou rapport", "date": "Date précise", "url": "URL FOURNIE DANS LES SOURCES SUPPLÉMENTAIRES UNIQUEMENT — si aucune URL n'a été fournie pour cette institution, mets null"}
  ],
  "categorie": "science|economie|societe|tech|environnement|sante",
  "nb_sources": 4,
  "positions": {
    "verifie": true,
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
8. Sources préférées : institutions officielles (INSEE, CNRS, INSERM, Eurostat, OMS, gouvernement), journaux de référence, publications peer-reviewed — MAIS uniquement si leur URL figure dans SOURCES DISPONIBLES. RÈGLE D'ATTRIBUTION : n'écris "Selon [Institution]" que si le fait attribué figure LITTÉRALEMENT dans l'extrait CONTENU fourni pour cette institution. Ne pas inventer, ne pas extrapoler depuis la mémoire d'entraînement. Si une institution que tu connais n'est pas dans la liste SOURCES DISPONIBLES, ne la cite JAMAIS dans le texte.
9. Slug en français kebab-case, descriptif, max 65 caractères
10. positions : génère ce bloc UNIQUEMENT si le sujet contient un véritable désaccord entre deux parties identifiables qui contestent ou défendent activement une même décision ou proposition — chacune avec une position EXPLICITEMENT attestée dans les sources (déclaration citée, vote enregistré, communiqué officiel). Critère opérationnel : deux camps avec des positions opposées ET défendables toutes les deux. INTERDIT si : acte institutionnel unilatéral sans opposition tracée (sanction disciplinaire, excommunication, condamnation judiciaire, décision administrative), décision technique, bilan statistique, découverte scientifique. Dans tous ces cas : verifie=false, acteurs=[]. Ne jamais inventer ou déduire une position. position = 0 (totalement favorable/consensuel) à 100 (totalement critique/opposé).
11. Le résumé ('resume') et le corps ('faits') ne doivent JAMAIS contenir de phrases identiques ou quasi identiques (mêmes mots, même structure) : le résumé est une synthèse reformulée, pas un copier-coller déguisé du corps.
12. Séparation stricte des registres : 'faits' = actualité immédiate uniquement (le fait du jour). 'contexte' = historique, évolution passée, comparaisons uniquement. Ne jamais mettre du contexte historique dans 'faits', ni redire les faits du jour dans 'contexte'.
13. Chaque source citée dans le texte doit apporter un élément NOUVEAU (chiffre, angle, nuance). Ne JAMAIS répéter la même information sous plusieurs attributions successives. Maximum 3 attributions « Selon X » par section. RÈGLE DE SYNTHÈSE : quand plusieurs sources rapportent le même fait de façon identique ou quasi identique, les fusionner en UNE SEULE phrase de synthèse avec attribution groupée en fin de phrase. N'utiliser des attributions séparées que si les sources apportent des informations DIFFÉRENTES.
    MAUVAIS (interdit) : « Selon Le Monde, le Vatican a excommunié six évêques. D'après Radio Lac, le Vatican a confirmé l'excommunication de ces six évêques. Selon France 24, le Vatican a confirmé l'excommunication de six évêques. »
    BON (attendu) : « Le Vatican a confirmé l'excommunication de six évêques de la Fraternité Saint-Pie X, actant le schisme de ce mouvement avec Rome (Le Monde, France 24, Radio Lac). »
14. ACTUALITÉ UNIQUEMENT : le sujet doit reposer sur un événement daté des dernières 48 heures (étude publiée, décision officielle, annonce, vote, incident). Un sujet intemporel ou encyclopédique sans événement déclencheur récent (ex: « la théorie de l'évolution », « le coucou, un oiseau stratège ») = réponds HORS_PERIMETRE.
15. CADRAGES EMPRUNTÉS INTERDITS : ne jamais reprendre mot pour mot un jugement de valeur ou un cadrage éditorial présent dans une source (ex : "crise sans précédent", "modèle à bout de souffle", "tournant historique") comme s'il s'agissait d'un fait neutre. Si un tel cadrage est pertinent, l'attribuer explicitement : « Selon [Source], il s'agit d'une crise sans précédent. » Ne jamais présenter l'angle éditorial d'une source comme l'angle factuel de l'article.
16. PAS D'EXTRAPOLATION NON SOURCÉE : n'écris jamais de projection ou de conséquence future ("cette mesure pourrait entraîner", "cela risque de", "on pourrait s'attendre à") sauf si une source listée formule explicitement cette projection. Si la conséquence n'est pas dans les extraits CONTENU, ne la mentionne pas.
17. RÉSULTATS INCERTAINS : si une étude est préliminaire, non encore répliquée, ou issue d'un seul chercheur, indique explicitement ce statut ("une étude préliminaire suggère que...", "selon une première analyse, non encore répliquée..."). Ne jamais présenter un résultat d'étude unique comme un fait établi. Le mot "prouve" ou "démontre définitivement" est interdit sauf citation directe attribuée.
18. SECTIONS DENSES, PAS VAGUES : chaque phrase de 'contexte' et 'nuances' doit apporter un fait précis et sourcé (chiffre, date, acteur, étude). Les formulations génériques sans contenu factuel sont interdites : "il est difficile de prévoir les conséquences", "la situation reste complexe", "les experts sont partagés" — supprimer ou remplacer par un fait réel tiré des sources.
19. nb_sources EXACT : le champ "nb_sources" doit correspondre exactement au nombre de sources DISTINCTES effectivement citées dans le texte final (chaque URL du tableau sources comptée une fois, même si citée plusieurs fois dans le corps). Pas de sources fantômes, pas de double-comptage.
20. LÉGAL : ne jamais qualifier quelqu'un de "coupable", "l'assassin", "le violeur" avant condamnation définitive — utiliser "mis en examen", "soupçonné de", "présumé". Ne jamais identifier un mineur par son nom dans une affaire pénale. Si le sujet implique une affaire judiciaire en cours, présenter les faits comme allégations de l'accusation, pas comme faits établis."""

# ──────────────────────────────────────────────────────────────────────────────
# PROMPTS DOSSIER (portrait neutre ou exploration scientifique hypothétique)
# Format JSON identique à ACTU ; champs faits/contexte/nuances réinterprétés.
# ──────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT_DOSSIER_PORTRAIT = """Tu es l'IA rédactrice de Les Faits, journal numérique français indépendant.
Ligne éditoriale absolue : "Juste les faits. Aucun parti pris."

Tu rédiges un DOSSIER PORTRAIT — présentation factuelle et neutre d'une personne publique
non-politique (scientifique, entrepreneur, artiste, sportif, explorateur, chercheur…).
Ton rôle : présenter les faits vérifiables sur cette personne, sans jugement ni glorification.

RÉPONDS UNIQUEMENT EN JSON VALIDE, sans texte avant ou après, sans bloc ```json.

Format obligatoire (identique à ACTU) :
{
  "titre": "Prénom Nom : courte description factuelle, 8 à 14 mots",
  "slug": "prenom-nom-role-court-max-65-chars",
  "image_keyword": "3 mots EN ANGLAIS — lieu ou objet lié à son domaine, jamais de visages ni personnes",
  "resume": [
    "Phrase 1 : qui est cette personne, son rôle et ce qui la distingue (données factuelles).",
    "Phrase 2 : réalisations principales, avec chiffres ou dates précises si disponibles.",
    "Phrase 3 : contexte ou enjeux actuels liés à son domaine."
  ],
  "corps": {
    "faits": "MINIMUM 300 mots. PRÉSENTATION : identité publique, formation, parcours vérifiable. Chaque affirmation attribuée à une source. Aucune anecdote non sourcée. Aucune biographie inventée.",
    "contexte": "MINIMUM 200 mots. DÉVELOPPEMENT : travaux, réalisations, impact mesurable, reconnaissance. Chiffres et dates obligatoires. Comparaisons factuelles si sourcées.",
    "nuances": "MINIMUM 150 mots. LIMITES ET INCERTITUDES : ce que les sources ne permettent pas de confirmer, critiques légitimes du travail (non de la personne), questions ouvertes dans son domaine."
  },
  "sources": [...],
  "categorie": "science|economie|societe|tech|environnement|sante",
  "nb_sources": 4,
  "positions": {"verifie": false, "label_gauche": "", "label_droite": "", "acteurs": []}
}

RÈGLES ABSOLUES :
1. MINIMUM 4 sources distinctes et citables. Si impossible : réponds uniquement HORS_PERIMETRE.
2. Chaque affirmation sur la personne DOIT être attribuée à une source listée.
3. Corps total : minimum 700 mots combinés.
4. Aucun adjectif évaluatif (brillant, remarquable, visionnaire, exceptionnel...) sans source directe.
5. Aucune opinion. Aucun parti pris. Les faits uniquement.
6. NE PAS écrire de portrait polémique : si la personne est associée à un débat politique, idéologique ou religieux, réponds HORS_PERIMETRE.
7. CADRAGES EMPRUNTÉS INTERDITS : ne jamais reprendre le cadrage éditorial d'une source comme fait neutre.
8. SOURCES : n'écris "Selon [Institution]" que si le fait figure LITTÉRALEMENT dans l'extrait CONTENU fourni.
9. positions : toujours verifie=false pour un portrait (pas de débat binaire).
10. LÉGAL : ne jamais mentionner d'affaires judiciaires en cours, de mises en examen, de suspicions non confirmées."""

SYSTEM_PROMPT_DOSSIER_SCIENCE = """Tu es l'IA rédactrice de Les Faits, journal numérique français indépendant.
Ligne éditoriale absolue : "Juste les faits. Aucun parti pris."

Tu rédiges un DOSSIER EXPLORATION SCIENTIFIQUE — présentation rigoureuse d'une hypothèse,
d'une piste de recherche ou d'une découverte récente, avec toutes les incertitudes explicites.
Jamais d'affirmations définitives sur des résultats non répliqués.

RÉPONDS UNIQUEMENT EN JSON VALIDE, sans texte avant ou après, sans bloc ```json.

Format obligatoire (identique à ACTU) :
{
  "titre": "Titre factuel décrivant l'hypothèse, 10 à 15 mots — jamais de certitude implicite",
  "slug": "slug-kebab-case-descriptif-max-65-chars",
  "image_keyword": "3 mots EN ANGLAIS — objet ou phénomène scientifique, jamais de visages ni personnes",
  "resume": [
    "Phrase 1 : quelle est l'hypothèse ou la découverte (avec marqueur d'incertitude explicite : 'suggère', 'pourrait', 'explore').",
    "Phrase 2 : contexte scientifique existant, état de l'art bref.",
    "Phrase 3 : ce qui reste à prouver ou les limites méthodologiques connues."
  ],
  "corps": {
    "faits": "MINIMUM 300 mots. L'HYPOTHÈSE : description précise de ce qui a été observé ou proposé. Marqueurs d'incertitude obligatoires ('suggère que', 'selon une étude préliminaire', 'les chercheurs estiment'). Jamais de certitude assertive sur un résultat non répliqué.",
    "contexte": "MINIMUM 200 mots. ÉTAT DE L'ART : recherches existantes, cadre théorique, études connexes avec dates et institutions. Comparaisons chiffrées si disponibles.",
    "nuances": "MINIMUM 150 mots. LIMITES ET CONTROVERSES : taille d'échantillon, limites méthodologiques, experts en désaccord, ce que l'étude ne permet pas de conclure, réplications nécessaires."
  },
  "sources": [...],
  "categorie": "science|tech|environnement|sante",
  "nb_sources": 4,
  "positions": {"verifie": false, "label_gauche": "", "label_droite": "", "acteurs": []}
}

RÈGLES ABSOLUES :
1. MINIMUM 4 sources distinctes et citables. Si impossible : réponds uniquement HORS_PERIMETRE.
2. JAMAIS "prouve que", "démontre que", "confirme définitivement", "il est désormais certain", "révolutionne", "va transformer" — toujours des marqueurs d'incertitude : "suggère", "laisse penser", "indique", "selon une étude préliminaire".
3. Corps total : minimum 700 mots combinés.
4. Chaque fait attribué à son institution avec "Selon [Institution]", uniquement si présent dans les extraits CONTENU.
5. Aucun adjectif évaluatif sans source.
6. PAS D'EXTRAPOLATION : n'écris jamais de conséquence future non sourcée.
7. SOURCES : n'écris "Selon [Institution]" que si le fait figure LITTÉRALEMENT dans l'extrait CONTENU fourni.
8. nb_sources EXACT : compte uniquement les sources distinctes réellement citées dans le texte.
9. LÉGAL : aucun nom de chercheur présenté comme fraudeur ou incompétent sans source directe.
10. Si les sources ne fournissent pas assez de faits précis pour 700 mots sans inventer : réponds HORS_PERIMETRE."""


# ══════════════════════════════════════════════════════════════════════════════
# GARDE-FOUS DÉTERMINISTES (sans LLM) — attributions fantômes & santé
# ══════════════════════════════════════════════════════════════════════════════

_ATTRIB_RE = re.compile(r"(?:Selon|D['’]après)\s+([^,;.]{2,70})[,;.]")
_ATTRIB_VAGUE = (
    "les experts", "des experts", "certains experts", "les sources",
    "des études", "les études", "certaines études", "les chercheurs",
    "des chercheurs", "les spécialistes", "les scientifiques",
    "les observateurs", "les analystes", "les données disponibles",
    "les informations disponibles",
)
# Renvois génériques à un document décrit dans le texte — tolérés
_ATTRIB_GENERIQUE = (
    "le décret", "la loi", "le rapport", "l'étude", "l’étude", "l'enquête",
    "l’enquête", "le communiqué", "les résultats", "le texte", "la tribune",
    "le projet de loi", "le vote", "les données de l'étude", "les données de l’étude",
)


def _norm_attrib(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower().strip()
    s = re.sub(r"^(le |la |les |l'|un |une |des |du |de la |de |d')+", "", s)
    return re.sub(r"[^a-z0-9 ]", " ", s).strip()


def strip_attributions_invalides(art: dict) -> dict:
    """Supprime déterministiquement les préfixes 'Selon X, ' / 'D'après X, '
    invalides du texte (X absent des sources vérifiées).
    Utilisé comme récupération après la relance Groq échouée — l'article
    est ensuite passé à Anthropic qui juge la qualité finale."""
    corpus = art.get("corps", {}) or {}
    norm_sources = [_norm_attrib(s.get("institution", "")) for s in art.get("sources", [])]
    norm_sources = [ns for ns in norm_sources if ns]

    def _is_valid(target: str) -> bool:
        tl = target.lower()
        if any(v in tl for v in _ATTRIB_VAGUE):
            return False
        if any(tl.startswith(g) for g in _ATTRIB_GENERIQUE):
            return True
        tn = _norm_attrib(target)
        if not tn:
            return True
        mots_t = {w for w in tn.split() if len(w) > 3}
        tn_ns = tn.replace(" ", "")
        return any(
            tn in ns or ns in tn
            or tn_ns == ns.replace(" ", "")
            or (mots_t & {w for w in ns.split() if len(w) > 3})
            for ns in norm_sources
        )

    def _clean(texte: str) -> str:
        def sub(m):
            target = m.group(1).strip()
            if _is_valid(target):
                return m.group(0)
            # Supprimer "Selon X," — ce qui suit le match (espace + mot) reste intact
            return ""
        result = _ATTRIB_RE.sub(sub, texte)
        # Nettoyage : espaces multiples → espace simple, capitalisation après ponctuation
        result = re.sub(r"  +", " ", result).strip()
        result = re.sub(r"(?<=\. )([a-zàâéèêëîïôùûçæœ])", lambda m: m.group(1).upper(), result)
        if result:
            result = result[0].upper() + result[1:]
        return result

    art = dict(art)
    corps = dict(corpus)
    for field in ("faits", "contexte", "nuances"):
        if field in corps and corps[field]:
            corps[field] = _clean(corps[field])
    # Résumé (liste ou str)
    resume = art.get("resume")
    if isinstance(resume, list):
        art["resume"] = [_clean(r) if isinstance(r, str) else r for r in resume]
    elif isinstance(resume, str):
        art["resume"] = _clean(resume)
    art["corps"] = corps
    return art


def attributions_fantomes(art: dict) -> list[str]:
    """Attributions « Selon X / D'après X » du corps qui ne correspondent à
    aucune source de la liste officielle, + formules vagues interdites."""
    corps = art.get("corps", {}) or {}
    texte = " ".join([
        " ".join(art.get("resume", []) if isinstance(art.get("resume"), list) else [art.get("resume", "") or ""]),
        corps.get("faits", ""), corps.get("contexte", ""), corps.get("nuances", ""),
    ])
    norm_sources = [_norm_attrib(s.get("institution", "")) for s in art.get("sources", [])]
    norm_sources = [ns for ns in norm_sources if ns]

    violations = []
    for m in _ATTRIB_RE.finditer(texte):
        target = m.group(1).strip()
        tl = target.lower()
        if any(v in tl for v in _ATTRIB_VAGUE):
            violations.append(target)
            continue
        if any(tl.startswith(g) for g in _ATTRIB_GENERIQUE):
            continue
        tn = _norm_attrib(target)
        if not tn:
            continue
        mots_t = {w for w in tn.split() if len(w) > 3}
        tn_ns = tn.replace(" ", "")
        ok = any(
            tn in ns or ns in tn
            or tn_ns == ns.replace(" ", "")   # ex. "franceinfo" == "france info"
            or (mots_t & {w for w in ns.split() if len(w) > 3})
            for ns in norm_sources
        )
        if not ok:
            violations.append(target)

    # dédoublonner en conservant l'ordre
    vus, out = set(), []
    for v in violations:
        k = _norm_attrib(v)
        if k not in vus:
            vus.add(k)
            out.append(v)
    return out


def resume_repete_corps(art: dict) -> list[str]:
    """Détecte les phrases du résumé quasi identiques (périphrase) aux premières
    phrases du corps 'faits' — signe que le résumé n'a pas été reformulé."""
    import difflib
    resume = art.get("resume", [])
    if isinstance(resume, str):
        resume = [resume]
    faits = (art.get("corps", {}) or {}).get("faits", "") or ""
    faits_phrases = [p.strip() for p in re.split(r"(?<=[.!?])\s+", faits) if len(p.strip()) > 20][:6]

    violations = []
    for r in resume:
        r = (r or "").strip()
        if len(r) < 20:
            continue
        for f in faits_phrases:
            ratio = difflib.SequenceMatcher(None, r.lower(), f.lower()).ratio()
            if ratio > 0.55:
                violations.append(r[:90])
                break
    return violations


_ATTRIB_PREFIX_RE = re.compile(r"^(?:Selon|D['’]après)\s+[^,]{2,50},\s*", re.IGNORECASE)


def faits_repetitifs(art: dict) -> list[str]:
    """Détecte, dans une même section du corps, des phrases qui répètent la même
    information sous des attributions différentes (« Selon X… D'après Y… » qui
    disent la même chose). Compare les phrases APRÈS retrait du préfixe
    d'attribution — c'est le contenu qui compte, pas la source citée."""
    import difflib
    violations = []
    corps = art.get("corps", {}) or {}
    for section in ("faits", "contexte", "nuances"):
        texte = corps.get(section, "") or ""
        phrases = [p.strip() for p in re.split(r"(?<=[.!?])\s+", texte) if len(p.strip()) > 40]
        # Corps de phrase sans le préfixe d'attribution
        noyaux = [(_ATTRIB_PREFIX_RE.sub("", p), p) for p in phrases]
        for i in range(len(noyaux)):
            for j in range(i + 1, len(noyaux)):
                ratio = difflib.SequenceMatcher(None, noyaux[i][0].lower(), noyaux[j][0].lower()).ratio()
                if ratio > 0.62:
                    violations.append(f"[{section}] « {noyaux[i][1][:70]}… » ≈ « {noyaux[j][1][:70]}… »")
        if len(violations) >= 4:
            break
    return violations


# ══════════════════════════════════════════════════════════════════════════════
# DÉTECTION DÉTERMINISTE DE SUJETS À REJETER (avant appel LLM)
# Critères codés en dur — ne dépendent pas du jugement du modèle.
# Complémentaires au flag sujet_sensible du fact-checker (belt-and-suspenders).
# ══════════════════════════════════════════════════════════════════════════════

# Situation sanitaire ou sécuritaire activement en cours
_SITUATION_ACTIVE_RE = re.compile(
    r"\b(?:en cours|en isolement|toujours hospitalis|reste hospitalis|"
    r"encore en soins intensifs|contacts? (?:identifi[ée]s?|suivis?|surveill[ée]s?) non encore test|"
    r"bilan (?:non encore|pas encore) (?:connu|[ée]tabli|d[ée]finitif)|"
    r"situation (?:non encore|toujours) (?:r[ée]solu|[ée]tablie?|clos)|"
    r"enqu[eê]te (?:en cours|ouverte|judiciaire)|information judiciaire|"
    r"garde [àa] vue|port[ée]e? disparu|personne recherch[ée]|"
    r"cas suspects? en attente|zone de confinement|cordon sanitaire)\b",
    re.IGNORECASE,
)

# Domaine sensible par nature (santé épidémique active, sécurité, judiciaire)
_DOMAINE_SENSIBLE_RE = re.compile(
    r"\b(?:ebola|marburg|lassa|h5n1|grippe aviaire|variole|rougeole|"
    r"m[ée]ningite|choléra|cholera|botulisme|listeria|"
    r"terrorisme|attentat|prise d.otage|enlèvement|"
    r"mis en examen|garde [àa] vue|perquisition|mandat d.arr[eê]t)\b",
    re.IGNORECASE,
)

# Mineur impliqué
_MINEUR_RE = re.compile(
    r"\b(?:mineur|enfant (?:victime|concern|impliqu|d[ée]c[ée]d|bless)|"
    r"adolescent (?:victim|mis en|concern|d[ée]c[ée]d)|"
    r"(?:coll[ée]gien|lyc[ée]en|[ée]l[èe]ve)[^.]{0,30}(?:victim|bless|tu[ée]|agress))\b",
    re.IGNORECASE,
)


def _est_rejete_sensible_deterministe(art: dict) -> tuple[bool, str]:
    """Détection déterministe (sans LLM) des articles à rejeter définitivement.
    Retourne (True, raison) si l'article doit être rejeté, (False, '') sinon.
    Appelé AVANT verifier_article pour éviter des appels API inutiles."""
    corps = art.get("corps", {}) or {}
    texte = " ".join([
        art.get("titre", ""),
        " ".join(art.get("resume", []) if isinstance(art.get("resume"), list) else []),
        corps.get("faits", ""), corps.get("contexte", ""), corps.get("nuances", ""),
    ])

    if _MINEUR_RE.search(texte):
        return True, "mineur impliqué détecté"

    domaine = _DOMAINE_SENSIBLE_RE.search(texte)
    actif   = _SITUATION_ACTIVE_RE.search(texte)
    if domaine and actif:
        return True, (
            f"domaine sensible ({domaine.group()!r}) + "
            f"situation active ({actif.group()!r})"
        )

    return False, ""


_SANTE_SENSIBLE_RE = re.compile(
    r"ebola|épidémie|epidemie|pandémie|pandemie|virus|vaccin|méningite|"
    r"choléra|cholera|variole|rougeole|grippe aviaire|h5n1|listeria|"
    r"salmonell|botulisme|rage\b|tuberculose|alerte sanitaire|rappel de produit",
    re.IGNORECASE,
)
_SOURCES_SANTE_OFFICIELLES = (
    "inserm", "oms", "organisation mondiale de la santé", "santé publique france",
    "sante publique france", "ministère de la santé", "ministere de la sante",
    "has", "haute autorité de santé", "anses", "ansm", "institut pasteur",
    "pasteur", "ars", "ecdc", "who", "pubmed", "agence régionale de santé",
)


# ══════════════════════════════════════════════════════════════════════════════
# CLASSIFICATION DOSSIER (déterministe — zéro LLM pour cette décision)
# Appliquée sur le titre + snippet RSS, avant tout appel Groq.
# ══════════════════════════════════════════════════════════════════════════════

# Signaux de portrait dans le titre
_PORTRAIT_TITRE_RE = re.compile(
    r"\bportrait\b|\binterview\b|\brendez-vous\b|\brencontre avec\b|"
    r"\bparcours de\b|\bbiograph\b|\bqui est\b|\bprofil de\b",
    re.IGNORECASE,
)
# Prénom (≥3 chars) espace Nom + virgule — structure typique de portrait
# "Anne Chopinet," "François Petit," "Jean-Luc Mélenchon,"
# "Marine Le Pen," "Charles de Gaulle," "Simone de Beauvoir,"
# {2,} sur le prénom exclut "Le", "La", "Du" en début de titre (2 chars)
_NOM_VIRGULE_RE = re.compile(
    r"[A-ZÀ-ÜÉÈÊËÎÏÔÙÛÇÆŒ][a-zà-üéèêëîïôùûçæœ\-]{2,}"
    r"(?:-[A-ZÀ-ÜÉÈÊËÎÏÔÙÛÇÆŒ][a-zà-üéèêëîïôùûçæœ]+)?"
    r"\s+"
    r"(?:[Dd][eu]\s+|[Ll][ae]\s+|[Dd]es\s+|[Dd][‘’]\s*)?"
    r"[A-ZÀ-ÜÉÈÊËÎÏÔÙÛÇÆŒ][a-zà-üéèêëîïôùûçæœ\-]+,",
    re.UNICODE,
)

# Signaux hypothétiques scientifiques (titre ou snippet)
_SCIENCE_HYPO_RE = re.compile(
    r"\bet si\b|\bpourrait\b|\bpermettrait\b|\bvers une?\b|\bpiste\b|"
    r"\bhypothèse\b|\bexplore\b|\bdécouvert[e]?s?\b|\bchercheurs?\b|"
    r"\bnouvelle étude\b|\bnouvelle espèce\b|\bsuggère\b|\bindiqu[e]\b|"
    r"\bà l'étude\b|\ben cours d'étude\b|\bune piste\b|\bon pourrait\b",
    re.IGNORECASE,
)

# Liste A — rôles politiques/religieux → portrait automatiquement REJETÉ
_LISTE_A_RE = re.compile(
    r"\b(?:ministr[e]?s?|député[e]?s?|sénateur|sénatrice|"
    r"maire|maires|président[e]? de (?:parti|région|conseil|groupe)|"
    r"eurodéputé[e]?s?|candidat[e]?s?|tête de liste|"
    r"porte-parole (?:du|de la|des) (?:gouvernement|parti|groupe)|"
    r"syndicaliste|secrétaire général[e]? (?:de |du |d'une )?(?:syndicat|cgt|cfdt|fo\b|cftc|unsa)|"
    r"imam|prêtre|évêque|pasteur|rabbin|cardinal|archevêque|diacre|mufti|"
    r"militant[e]?s? (?:politique|du|de la|pour le|contre le))\b",
    re.IGNORECASE,
)

# Liste B — sujets clivants → portrait ou article REJETÉ si présent
_LISTE_B_RE = re.compile(
    r"\b(?:immigration clandestine|sans-papiers|migrants? irréguliers?|"
    r"islamisme|islamophobie|laïcité (?:menacée|bafouée|en crise)|"
    r"avortement|ivg\b|interruption volontaire de grossesse|"
    r"euthanasie|suicide assisté|fin de vie (?:légalis|dépénalis)|"
    r"pma\b|gpa\b|gestation pour autrui|procréation médicalement assistée|"
    r"transgenre|identité de genre|théorie du genre|"
    r"wokisme|cancel culture|décoloniali|"
    r"extrême[- ]droite|extrême[- ]gauche|"
    r"rassemblement national\b|front national\b|\brn\b|\bfn\b(?! [a-z])|"
    r"la france insoumise|\blfi\b|"
    r"milite (?:pour|contre)|militer (?:pour|contre)|"
    r"manifestation contre (?:le|la|les|l')|grève générale)\b",
    re.IGNORECASE,
)

# Formulations assertives interdites dans un dossier science (garde-fou post-génération)
_ASSERTIF_SCIENCE_RE = re.compile(
    r"\bprouve(?: définitivement)? que\b|"
    r"\bdémontre définitivement\b|"
    r"\bconfirme définitivement\b|"
    r"\bil est désormais certain\b|"
    r"\bva révolutionner\b|va transformer (?:notre|le|la|les)\b|"
    r"\bchangera tout\b|"
    r"\b(?:révolution[ne]|boulevers)[ae]r[a]?\b(?=.*(?:médecine|science|technologie|domaine))",
    re.IGNORECASE,
)

# Lifestyle/listicle : rejeté dès le filtre éditorial, mais détection explicite
# pour log clair dans classifier_type_article
_LISTICLE_RE = re.compile(
    r"^\d+\s+(?:façons?|conseils?|astuces?|raisons?|idées?)|"
    r"\btop \d+\b|\bguide (?:complet|ultime|pour)\b|"
    r"\btout savoir sur\b|\bce qu'il faut savoir\b|"
    r"\bsommaire de\b|\bà retenir de\b|\ben bref\b",
    re.IGNORECASE,
)


def classifier_type_article(title: str, snippet: str) -> str:
    """Classifie un article AVANT génération (déterministe, zéro LLM).

    Retourne :
      "actu"             → pipeline ACTU standard
      "dossier_portrait" → portrait neutre d'une personne non-politique
      "dossier_science"  → exploration scientifique hypothétique
      "rejete"           → listicle, lifestyle, portrait polémique
    """
    texte = (title + " " + snippet).lower()
    texte_raw = title + " " + snippet  # pour les regexes sensibles à la casse

    # Rejet listicle/lifestyle immédiat
    if _LISTICLE_RE.search(title):
        return "rejete"

    # Détection portrait (titre en priorité)
    is_portrait = (
        _PORTRAIT_TITRE_RE.search(title)
        or _NOM_VIRGULE_RE.search(title)
    )
    if is_portrait:
        # Vérifier Liste A : rôle exclu → rejet
        if _LISTE_A_RE.search(texte_raw):
            return "rejete"
        # Vérifier Liste B : sujet clivant dans titre+snippet → rejet
        if _LISTE_B_RE.search(texte_raw):
            return "rejete"
        return "dossier_portrait"

    # Détection science hypothétique (titre + début snippet)
    if _SCIENCE_HYPO_RE.search(title) or _SCIENCE_HYPO_RE.search(snippet[:500]):
        # Liste B s'applique aussi ici
        if _LISTE_B_RE.search(texte_raw):
            return "rejete"
        return "dossier_science"

    return "actu"


def _select_prompt(article_type: str) -> str:
    """Retourne le SYSTEM_PROMPT adapté au type d'article."""
    if article_type == "dossier_portrait":
        return SYSTEM_PROMPT_DOSSIER_PORTRAIT
    if article_type == "dossier_science":
        return SYSTEM_PROMPT_DOSSIER_SCIENCE
    return SYSTEM_PROMPT


def sujet_sante_sans_source_officielle(art: dict) -> bool:
    """True si l'article touche un sujet sanitaire sensible (épidémies,
    vaccins, alertes) SANS aucune source institutionnelle de santé —
    dans ce cas il part en modération humaine, jamais en publication auto."""
    texte = (art.get("titre", "") + " " + json.dumps(art.get("corps", {}), ensure_ascii=False)).lower()
    if not _SANTE_SENSIBLE_RE.search(texte):
        return False
    for s in art.get("sources", []):
        blob = ((s.get("institution") or "") + " " + (s.get("url") or "")).lower()
        if any(off in blob for off in _SOURCES_SANTE_OFFICIELLES) or ".gouv.fr" in blob:
            return False
    return True


def _anthropic_generate_call(messages: list, max_tokens: int = 4500) -> str:
    """Fallback de génération quand toutes les clés Groq sont en rate limit.
    Utilise Haiku (rapide, peu coûteux) via la même clé ANTHROPIC_API_KEY que
    la vérification — mieux vaut un article généré par Haiku qu'un sujet
    abandonné faute de quota Groq."""
    system_msg = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    user_msgs  = [m for m in messages if m["role"] != "system"]
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": _ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": max_tokens,
            "system": system_msg,
            "messages": user_msgs,
        },
        timeout=180,
    )
    r.raise_for_status()
    data = r.json()
    u = data.get("usage", {})
    print(f"     [TOKENS ANTHROPIC] prompt={u.get('input_tokens', '?')} "
          f"completion={u.get('output_tokens', '?')}", flush=True)
    return data["content"][0]["text"].strip()


def _groq_call(api_key: str, messages: list, max_tokens: int = 4500) -> str:
    """Appelle Groq avec la clé donnée. Lève une exception en cas d'erreur."""
    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=max_tokens,
        temperature=0.1,
        messages=messages,
    )
    u = response.usage
    if u:
        print(f"     [TOKENS] prompt={u.prompt_tokens} completion={u.completion_tokens} "
              f"total={u.total_tokens}", flush=True)
    return response.choices[0].message.content.strip()


def generate(content: str, category_hint: str, extra_sources: list[dict] | None = None,
             rss_url: str | None = None, retry_feedback: list[str] | None = None,
             repetition_feedback: list[str] | None = None,
             intra_feedback: list[str] | None = None,
             article_type: str = "actu",
             previous_article: dict | None = None) -> dict:

    # Construire la liste des URLs réelles disponibles (DuckDuckGo + flux RSS)
    real_sources: list[dict] = []
    if rss_url:
        real_sources.append({"title": "Source RSS originale", "url": rss_url, "snippet": ""})
    if extra_sources:
        real_sources.extend(extra_sources)

    real_urls = {s["url"] for s in real_sources}

    # Relance (retry_feedback / repetition_feedback) : le modèle corrige un
    # article déjà écrit, il n'a pas besoin de ré-analyser tout le contenu
    # source en détail — seulement de savoir quels noms sont autorisés.
    # Renvoyer les CONTENU complets à chaque relance (jusqu'à 4 appels par
    # article) multipliait le coût par ~4 et épuisait le quota Groq quotidien
    # après 2-3 articles à peine.
    is_retry = bool(retry_feedback or repetition_feedback or intra_feedback)
    snippet_len = 200 if is_retry else 950

    # 950 chars ≈ 2-3 paragraphes — assez pour ancrer des faits précis sans
    # dépasser le budget Groq (1500 chars × 8 sources dépassait 200k tokens/clé).
    sources_block = ""
    # Noms lisibles dérivés des URLs — utilisés dans le prompt ET dans les règles d'attribution
    source_noms: list[str] = []
    if real_sources:
        sources_block = "\n\nSOURCES DISPONIBLES — LISTE FERMÉE :\n"
        sources_block += (
            "RÈGLE ABSOLUE : pour tout « Selon X » ou « D'après X » dans le texte, "
            "X doit être EXACTEMENT l'une des valeurs NOM_SOURCE listées ci-dessous. "
            "Interdit : utiliser 'SOURCE 1', 'SOURCE 2', un nom de domaine, "
            "un média mentionné À L'INTÉRIEUR d'un extrait, ou tout nom connu par ailleurs.\n\n"
        )
        for i, s in enumerate(real_sources, 1):
            snippet  = s.get("snippet") or ""
            nom      = _media_name_from_url(s["url"], s.get("title", "")) or s.get("title", "Source")
            source_noms.append(nom)
            sources_block += f"--- SOURCE {i} ---\n"
            sources_block += f"NOM_SOURCE : {nom}\n"
            sources_block += f"URL        : {s['url']}\n"
            if snippet:
                sources_block += f"CONTENU    :\n{snippet[:snippet_len]}\n"
            else:
                sources_block += "CONTENU    : (pas de contenu disponible)\n"
            sources_block += f"--- FIN SOURCE {i} ({nom}) ---\n\n"

    noms_autorises = " | ".join(f'"{n}"' for n in source_noms) if source_noms else "(aucune)"

    # Règle d'attribution en TÊTE du message (avant le contenu) pour maximiser
    # l'attention du modèle sur cette contrainte — puis rappel bref à la fin.
    attrib_header = (
        f"⚠ AVANT DE LIRE LE CONTENU — RÈGLE D'ATTRIBUTION ABSOLUE :\n"
        f"Les seuls noms utilisables dans « Selon X » ou « D'après X » sont : {noms_autorises}.\n"
        f"INTERDIT : utiliser 'SOURCE 1/2/3', un nom de domaine, un média vu À L'INTÉRIEUR "
        f"d'un extrait, ou tout média connu par ailleurs mais absent de la liste ci-dessus.\n\n"
    )

    content_len = 1500 if is_retry else 7000

    # Relance avec article précédent : le modèle CORRIGE l'article existant au
    # lieu de tout réécrire depuis des sources tronquées — sans ce bloc, les
    # extraits raccourcis (200 chars) déclenchaient la règle HORS_PERIMETRE
    # ("pas assez de faits pour 700 mots") ou poussaient à inventer.
    article_precedent_block = ""
    if is_retry and previous_article:
        article_precedent_block = (
            "\n\nARTICLE PRÉCÉDENT (ta réponse à corriger) :\n"
            + json.dumps(previous_article, ensure_ascii=False)
            + "\n\nConserve tout ce qui est valide dans cet article ; ne modifie "
            "QUE ce que la CORRECTION OBLIGATOIRE ci-dessous exige. Renvoie "
            "l'article complet corrigé au même format JSON.\n"
        )

    regle_5 = (
        "" if (is_retry and previous_article) else
        "5. Si les extraits disponibles ne fournissent pas assez de faits précis pour 700 mots sans inventer, "
        "réponds uniquement HORS_PERIMETRE.\n"
    )
    instruction_finale = (
        "Corrige maintenant l'article ci-dessus." if (is_retry and previous_article)
        else "Rédige maintenant l'article complet."
    )

    user_msg = (
        f"{attrib_header}"
        f"Catégorie probable : {category_hint}\n\n"
        f"CONTENU SOURCE PRINCIPAL :\n{content[:content_len]}"
        f"{sources_block}"
        f"{article_precedent_block}"
        f"RAPPEL ATTRIBUTION :\n"
        f"1. Le champ 'sources' ne doit contenir QUE des entrées dont l'URL figure dans les SOURCES ci-dessus.\n"
        f"2. Noms autorisés pour « Selon X » : {noms_autorises}. Aucun autre.\n"
        f"3. N'attribue un fait à une source QUE si ce fait est explicitement présent dans son extrait CONTENU.\n"
        f"   Si une information n'est dans aucun extrait, présente-la sans attribution ou omets-la.\n"
        f"4. JAMAIS « selon les experts », « des études montrent », « les scientifiques estiment » sans source précise.\n"
        f"{regle_5}"
        f"{instruction_finale}"
    )

    if retry_feedback:
        user_msg += (
            "\n\nCORRECTION OBLIGATOIRE — ta précédente réponse attribuait des informations à des "
            "sources ABSENTES de la liste autorisée : « " + " » ; « ".join(retry_feedback[:8]) + " ». "
            f"Noms autorisés (NOM_SOURCE uniquement) : {noms_autorises}. "
            "Réécris l'article en n'attribuant chaque affirmation QU'À ces noms exacts, "
            "ou supprime les affirmations concernées."
        )

    if repetition_feedback:
        user_msg += (
            "\n\nCORRECTION OBLIGATOIRE — dans ta précédente réponse, ces phrases du résumé "
            "étaient une quasi-répétition du corps 'faits' au lieu d'une reformulation : « "
            + " » ; « ".join(repetition_feedback[:5]) + " ». "
            "Réécris le champ 'resume' avec un vocabulaire et une syntaxe entièrement différents "
            "de ceux du corps — une synthèse, jamais un copier-coller déguisé."
        )

    if intra_feedback:
        user_msg += (
            "\n\nCORRECTION OBLIGATOIRE — ta précédente réponse répétait la même information "
            "plusieurs fois dans le corps (sous des formulations ou attributions différentes) : « "
            + " » ; « ".join(intra_feedback[:5]) + " ». "
            "Fusionne chaque information répétée en une seule mention et remplace les passages "
            "en doublon par des faits distincts issus des sources autorisées."
        )

    messages = [
        {"role": "system", "content": _select_prompt(article_type)},
        {"role": "user",   "content": user_msg},
    ]

    raw = None
    _all_keys = [(GROQ_KEY, "clé 1"), (GROQ_KEY2, "clé 2"), (GROQ_KEY3, "clé 3")]
    keys_to_try = [(k, l) for k, l in _all_keys if k]
    MAX_RETRY_CYCLES = 3  # cycles complets sur toutes les clés avant abandon
    RETRY_WAIT = 62       # secondes d'attente entre deux cycles (fenêtre rate-limit Groq = 60s)
    for cycle in range(MAX_RETRY_CYCLES):
        for key, label in keys_to_try:
            try:
                raw = _groq_call(key, messages)
                break
            except Exception as e:
                err = str(e)
                if "429" in err or "rate_limit" in err.lower():
                    idx = keys_to_try.index((key, label))
                    if idx < len(keys_to_try) - 1:
                        next_label = keys_to_try[idx + 1][1]
                        print(f"     [GROQ] Rate limit sur {label} — bascule sur {next_label}")
                    else:
                        if cycle < MAX_RETRY_CYCLES - 1:
                            print(f"     [GROQ] Toutes les clés en rate limit — attente {RETRY_WAIT}s (cycle {cycle+1}/{MAX_RETRY_CYCLES})")
                            time.sleep(RETRY_WAIT)
                        else:
                            print(f"     [ERREUR GROQ] Rate limit atteint sur toutes les clés après {MAX_RETRY_CYCLES} cycles")
                else:
                    raise
        if raw is not None:
            break
    if raw is None:
        # Toutes les clés Groq épuisées : fallback Anthropic plutôt que
        # d'abandonner les sujets restants du créneau.
        if _ANTHROPIC_KEY:
            print("     [FALLBACK] Quota Groq épuisé — génération via Anthropic (Haiku)")
            raw = _anthropic_generate_call(messages)
        else:
            raise RuntimeError("Aucune clé Groq disponible (rate limit) et pas de clé Anthropic")

    if "HORS_PERIMETRE" in raw[:60]:
        raise ValueError(raw[:80])

    # Extraire le JSON robustement (le modèle peut ajouter du texte avant/après)
    def _extract_json(text):
        m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if m:
            candidate = re.sub(r',\s*([\}\]])', r'\1', m.group(1))
            return json.loads(candidate)
        start = text.find('{')
        if start == -1:
            raise ValueError("Pas de JSON dans la réponse")
        candidate = re.sub(r',\s*([\}\]])', r'\1', text[start:])
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            for i in range(len(candidate) - 1, 0, -1):
                if candidate[i] == '}':
                    try:
                        return json.loads(candidate[:i + 1])
                    except Exception:
                        continue
            raise ValueError("JSON non réparable")

    art = _extract_json(raw)

    # Supprimer toute source dont l'URL n'est pas dans la liste réelle,
    # et écraser le nom avec celui de la source authoritative (évite les mismatches nom↔URL).
    real_title_by_url = {s["url"]: _media_name_from_url(s["url"], s.get("title", ""))
                        for s in real_sources}
    if "sources" in art:
        verified = []
        for src in art["sources"]:
            if not isinstance(src, dict):
                continue
            url = src.get("url") or ""
            path = urlparse(url).path.rstrip("/") if url else ""
            if url in real_urls and len(path) > 3:
                src = dict(src)
                src["institution"] = real_title_by_url.get(url, src.get("institution", ""))
                verified.append(src)
        art["sources"] = verified
        art["nb_sources"] = len(verified)

    return art


# ══════════════════════════════════════════════════════════════════════════════
# GÉNÉRATION HTML ARTICLE
# ══════════════════════════════════════════════════════════════════════════════

def build_spectrum_html(positions: dict) -> str:
    """Génère le bloc HTML spectrum — uniquement si verifie=true et acteurs présents."""
    if not positions or not positions.get("verifie") or not positions.get("acteurs"):
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
        f'<span class="spectrum__legend-name">{_esc(a["nom"])}</span>'
        f'<span class="spectrum__legend-sub">{_esc(a.get("detail",""))}</span>'
        f'</div>'
        for i, a in enumerate(acteurs)
    )
    return f"""<div class="spectrum">
  <div class="spectrum__title">POSITIONS DES ACTEURS</div>
  <div class="spectrum__labels"><span>{label_g}</span><span>{label_d}</span></div>
  <div class="spectrum__track">{markers}</div>
  <div class="spectrum__legend">{legend_items}</div>
</div>"""


def _typo_fr(text: str) -> str:
    """Normalise la typographie française : apostrophes, guillemets, ellipses."""
    import re
    # Apostrophe droite → typographique (entre deux caractères non-espaces)
    text = re.sub(r"(?<=[^\s])'(?=[^\s])", "’", text)
    # Guillemets droits " ... " → « ... » avec espaces insécables
    text = re.sub(r'"([^"]+)"', r"« \1 »", text)
    # Trois points → ellipse
    text = text.replace("...", "…")
    return text


def _slug_ascii(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _generate_fallback_image(title: str, category: str, slug: str, dest: str) -> None:
    """Génère une infographie typographique 1200x630 avec Pillow."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return

    CAT_COLORS = {
        "societe": "#1a1a2e", "science": "#0f3460", "economie": "#1b262c",
        "tech": "#16213e", "sante": "#1a2f1a", "environnement": "#1a2f1a",
    }
    bg_color   = CAT_COLORS.get(category.lower(), "#111111")
    blue       = "#2563eb"
    W, H       = 1200, 630

    img  = Image.new("RGB", (W, H), bg_color)
    draw = ImageDraw.Draw(img)

    # Bande colorée en haut
    draw.rectangle([(0, 0), (W, 40)], fill=blue)

    # Polices — essaie DejaVuSans (toujours dispo dans Pillow)
    def _font(size, bold=False):
        try:
            name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
            return ImageFont.truetype(name, size)
        except Exception:
            return ImageFont.load_default()

    font_logo  = _font(26, bold=True)
    font_cat   = _font(15)
    font_title = _font(42, bold=True)
    font_sub   = _font(14)

    # Logo
    draw.text((32, 8), "lesfaits", font=font_logo, fill="white")

    # Catégorie
    cat_label = {"societe":"SOCIÉTÉ","science":"SCIENCE","economie":"ÉCONOMIE",
                 "tech":"TECH","sante":"SANTÉ","environnement":"ENVIRONNEMENT"}.get(category.lower(), category.upper())
    draw.text((32, 70), cat_label, font=font_cat, fill=blue)

    # Titre avec wrap manuel
    max_w = W - 80
    words  = title.split()
    lines  = []
    current = ""
    for word in words:
        test = (current + " " + word).strip()
        bbox = draw.textbbox((0, 0), test, font=font_title)
        if bbox[2] - bbox[0] > max_w and current:
            lines.append(current)
            current = word
        else:
            current = test
    if current:
        lines.append(current)

    if len(lines) > 2:
        lines = lines[:2]
        lines[1] = lines[1][:40].rstrip() + "…"

    y_title = 120
    for line in lines:
        draw.text((32, y_title), line, font=font_title, fill="white")
        bbox = draw.textbbox((0, 0), line, font=font_title)
        y_title += (bbox[3] - bbox[1]) + 12

    # Ligne horizontale
    draw.rectangle([(32, 520), (W - 32, 522)], fill=blue)

    # Textes bas
    from datetime import date as _date
    today = _date.today()
    MOIS_FR = ["","janvier","février","mars","avril","mai","juin","juillet","août","septembre","octobre","novembre","décembre"]
    date_str = f"{today.day} {MOIS_FR[today.month]} {today.year}"
    draw.text((32, 540), "Rédigé par IA · Les Faits", font=font_sub, fill="#888888")
    bbox_date = draw.textbbox((0, 0), date_str, font=font_sub)
    draw.text((W - 32 - (bbox_date[2] - bbox_date[0]), 540), date_str, font=font_sub, fill="#888888")

    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    img.save(dest, "JPEG", quality=90)


# ── Classification des sources ───────────────────────────────────────────────

_SOURCE_DOMAINS = {
    "government": [
        ".gouv.fr", ".gov", ".europa.eu", "elysee.fr", "assemblee-nationale.fr",
        "senat.fr", "gouvernement.fr", "who.int", "un.org", "conseil-etat.fr",
        "vie-publique.fr", "legifrance.gouv.fr",
    ],
    "institutional": [
        "wikipedia.org", "wikimedia.org", "commons.wikimedia.org",
        "insee.fr", "banque-france.fr", "has-sante.fr", "anses.fr",
        "meteofrance.fr", "ined.fr", "cnrs.fr", "inserm.fr",
        "nasa.gov", "esa.int", "cern.ch", "pasteur.fr",
    ],
    "press_agency": ["reuters.com", "afp.com", "apnews.com"],
    "media": [
        "lemonde.fr", "lefigaro.fr", "leparisien.fr", "liberation.fr",
        "bbc.com", "theguardian.com", "nytimes.com", "francetvinfo.fr",
        "franceinfo.fr", "rtl.fr", "bfmtv.com", "20minutes.fr",
        "lepoint.fr", "lexpress.fr", "nouvelobs.com", "mediapart.fr",
    ],
}


def classify_source(url: str) -> str:
    """Retourne le type de source : government / institutional / press_agency / media / other."""
    if not url:
        return "other"
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return "other"
    # Vérification dans l'ordre : press/media/institutional avant government
    # pour que les domaines spécifiques priment sur les wildcards TLD (.gov, .gouv.fr)
    priority = ["press_agency", "media", "institutional", "government"]
    for stype in priority:
        domains = _SOURCE_DOMAINS.get(stype, [])
        if any(host == d.lstrip(".") or host.endswith(d) for d in domains):
            return stype
    return "other"


def _extract_image_from_source(url: str, source_type: str, dest: str) -> bool:
    """
    Tente d'extraire une image depuis une source gouvernementale ou institutionnelle.
    Retourne True si une image a été téléchargée avec succès.
    """
    hdrs = {"User-Agent": "LesFaits/1.1 (lesfaits.contact@gmail.com)"}

    # Wikipedia → API REST propre, pas de scraping HTML
    if "wikipedia.org" in url:
        try:
            parsed = urlparse(url)
            lang = parsed.hostname.split(".")[0]  # "fr" ou "en"
            title = parsed.path.rstrip("/").rsplit("/", 1)[-1]
            api = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"
            r = requests.get(api, timeout=10, headers=hdrs)
            if r.status_code == 200:
                data = r.json()
                img_url = (data.get("originalimage") or data.get("thumbnail") or {}).get("source", "")
                if img_url:
                    ir = requests.get(img_url, timeout=15, headers=hdrs)
                    if ir.status_code == 200 and len(ir.content) > 50_000:
                        open(dest, "wb").write(ir.content)
                        print(f"  [SOURCE] Image Wikipedia : {url}")
                        return True
        except Exception:
            pass
        return False

    # Gouvernement / institutionnel → scraping og:image
    if source_type in ("government", "institutional"):
        try:
            r = requests.get(url, timeout=12, headers=hdrs)
            if r.status_code != 200:
                return False
            soup = BeautifulSoup(r.text, "html.parser")

            img_url = ""

            # 1. og:image — priorité maximale
            og = soup.find("meta", property="og:image")
            if og:
                img_url = og.get("content", "")

            # 2. Première <img> dans <article> ou <main> de largeur ≥ 600
            if not img_url:
                for container in soup.select("article, main, [role='main']"):
                    for img in container.find_all("img"):
                        src = img.get("src", "")
                        try:
                            w = int(img.get("width", 0))
                        except (ValueError, TypeError):
                            w = 0
                        if src and w >= 600:
                            img_url = src
                            break
                    if img_url:
                        break

            # 3. Première <figure> img
            if not img_url:
                fig = soup.select_one("figure img")
                if fig:
                    img_url = fig.get("src", "")

            if not img_url:
                return False

            # URL relative → absolue
            if img_url.startswith("//"):
                img_url = "https:" + img_url
            elif img_url.startswith("/"):
                p = urlparse(url)
                img_url = f"{p.scheme}://{p.hostname}{img_url}"

            ir = requests.get(img_url, timeout=15, headers=hdrs)
            if ir.status_code == 200 and len(ir.content) > 50_000:
                open(dest, "wb").write(ir.content)
                print(f"  [SOURCE] Image {source_type} : {urlparse(url).hostname}")
                return True
        except Exception:
            pass

    return False


def extract_visual_keywords(title: str, summary: str, category: str) -> str:
    """
    Utilise Groq (llama-3.3-70b) pour extraire 3 mots-clés visuels en anglais.
    Retourne une chaîne de mots séparés par des espaces, ex: "heat wave france summer"
    Fallback sur le titre nettoyé si Groq indisponible.
    """
    key = GROQ_KEY or GROQ_KEY2
    if not key:
        # Fallback sans IA : nettoyer le titre
        stopwords = {"le","la","les","de","du","en","un","une","et","pour","sur","par",
                     "au","aux","ce","qui","que","dans","est","son","ses","leur","leurs"}
        words = [w for w in title.lower().split() if w not in stopwords][:4]
        return " ".join(words)
    try:
        messages = [{
            "role": "user",
            "content": (
                f"Article: {title}\n"
                f"Summary: {summary[:200]}\n"
                f"Category: {category}\n\n"
                "Extract 3-4 English keywords to search for a relevant stock photo illustration. "
                "Prefer concrete visual subjects (place, object, event, scene). "
                "Avoid abstract concepts. "
                "Reply with ONLY the keywords separated by spaces, nothing else."
            )
        }]
        result = _groq_call(key, messages, max_tokens=30)
        # Nettoyer la réponse (parfois entre guillemets ou avec ponctuation)
        clean = re.sub(r'[^\w\s]', '', result).strip().lower()
        return clean[:80] if clean else title
    except Exception:
        return title


# Photos Pexels déjà utilisées dans ce run (évite les doublons visuels)
_USED_PEXELS_IDS: set[int] = set()
# URLs Wikimedia déjà utilisées dans ce run
_USED_WIKIMEDIA_URLS: set[str] = set()
# Hash MD5 de toutes les images existantes — comparaison par contenu, cross-run
_USED_IMAGE_HASHES: set[str] = set()


def _img_hash(data: bytes) -> str:
    import hashlib
    return hashlib.md5(data).hexdigest()


def _init_used_images():
    """Charge le hash MD5 de toutes les images existantes pour bloquer les doublons."""
    import hashlib
    img_dir = ROOT / "assets" / "images"
    if not img_dir.exists():
        return
    for f in [*img_dir.glob("*.jpg"), *img_dir.glob("*.png"), *img_dir.glob("*.webp")]:
        try:
            _USED_IMAGE_HASHES.add(hashlib.md5(f.read_bytes()).hexdigest())
        except Exception:
            pass
    print(f"  [images] {len(_USED_IMAGE_HASHES)} hashes chargés (anti-doublon)")


def _optimize_image_file(path, max_width: int = 1200, quality: int = 82) -> None:
    """Redimensionne à max_width et recompresse en JPEG q82 si ça fait gagner
    du poids — les héros s'affichent à 1140px max, inutile de servir du 4K.
    Ne touche pas au fichier si l'optimisation ne réduit pas sa taille."""
    try:
        from PIL import Image
        import io as _io
        p = str(path)
        avant = os.path.getsize(p)
        img = Image.open(p)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        if img.width > max_width:
            ratio = max_width / img.width
            img = img.resize((max_width, int(img.height * ratio)), Image.LANCZOS)
        buf = _io.BytesIO()
        img.save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
        if buf.tell() < avant:
            with open(p, "wb") as f:
                f.write(buf.getvalue())
    except Exception as e:
        print(f"  [WARN] optimisation image {path}: {e}")


def _download_hero(
    keyword: str,
    slug: str,
    dest: str,
    sources: list | None = None,
    title: str = "",
    summary: str = "",
    category: str = "societe",
) -> tuple[str, str]:
    """
    Cherche une image hero dans l'ordre de priorité :
    0. Sources de l'article (gov/institutionnel/Wikipedia)
    1. Wikimedia Commons
    2. Openverse
    3. Pexels
    4. Pixabay
    5. Pillow fallback

    Retourne (source_type, credit) ex: ("wikimedia", "Wikimedia Commons")
    """
    import urllib.parse
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    hdrs = {"User-Agent": "LesFaits/1.1 (lesfaits.contact@gmail.com)"}

    # Noms de fichier suspects
    _BAD = (
        "map", "flag", "logo", "icon", "diagram", "chart", "graph", "coat",
        "blason", "carte", "drapeau", "schema", "plan_", "seal_", "emblem",
        "stamp", "badge", "symbol", "sign_", "portrait_", "headshot",
    )

    def _is_bad(url: str, w: int, h: int) -> bool:
        fname = url.rsplit("/", 1)[-1].lower()
        if any(b in fname for b in _BAD):
            return True
        if w > 0 and h > 0 and (h / w > 1.4 or w / h < 0.5):
            return True
        return False

    def _save(data: bytes, source_type: str, credit: str) -> tuple[str, str] | None:
        h = _img_hash(data)
        if h in _USED_IMAGE_HASHES:
            print(f"  [SKIP-DUP] {slug} → image identique déjà utilisée ({source_type})")
            return None
        with open(dest, "wb") as _f:
            _f.write(data)
        _optimize_image_file(dest)
        _USED_IMAGE_HASHES.add(h)
        print(f"  [OK] {slug} → {credit} ({source_type})")
        return source_type, credit

    # ── 0. Sources de l'article ──────────────────────────────────────────────
    for src in (sources or []):
        url = src.get("url") or "" if isinstance(src, dict) else str(src)
        if not url:
            continue
        stype = classify_source(url)
        if stype in ("press_agency", "media"):
            print(f"  [SKIP] {urlparse(url).hostname} — droits non libres")
            continue
        if _extract_image_from_source(url, stype, dest):
            with open(dest, "rb") as _f:
                h = _img_hash(_f.read())
            if h in _USED_IMAGE_HASHES:
                os.remove(dest)
                print(f"  [SKIP-DUP] {slug} → image source identique à une existante")
                continue
            _optimize_image_file(dest)
            _USED_IMAGE_HASHES.add(h)
            host = urlparse(url).hostname or url
            return stype, host

    # Mots-clés visuels en anglais via IA
    vis_kw = extract_visual_keywords(title or keyword, summary, category)

    # ── 1. Wikimedia Commons ─────────────────────────────────────────────────
    try:
        params = urllib.parse.urlencode({
            "action": "query", "format": "json", "generator": "search",
            "gsrnamespace": "6", "gsrsearch": vis_kw, "gsrlimit": "20",
            "prop": "imageinfo", "iiprop": "url|size|mime", "iiurlwidth": "1200"
        })
        r = requests.get(f"https://commons.wikimedia.org/w/api.php?{params}", timeout=5, headers=hdrs)
        pages = sorted(
            r.json().get("query", {}).get("pages", {}).values(),
            key=lambda p: -(p.get("imageinfo", [{}])[0].get("width", 0))
        )
        for page in pages:
            ii = page.get("imageinfo", [{}])[0]
            if ii.get("mime", "") not in ("image/jpeg", "image/png", "image/webp"):
                continue
            img_url = ii.get("thumburl") or ii.get("url", "")
            if not img_url:
                continue
            w = ii.get("thumbwidth") or ii.get("width", 0)
            h = ii.get("thumbheight") or ii.get("height", 0)
            if w < 600 or h < 300 or _is_bad(img_url, w, h):
                continue
            if img_url in _USED_WIKIMEDIA_URLS:
                continue
            ir = requests.get(img_url, timeout=5, headers=hdrs)
            if ir.status_code == 200 and len(ir.content) > 20_000:
                result = _save(ir.content, "wikimedia", "Wikimedia Commons")
                if result:
                    _USED_WIKIMEDIA_URLS.add(img_url)
                    return result
    except Exception:
        pass

    # ── 2. Pexels — fallback si Wikimedia ne trouve rien ─────────────────────
    if PEXELS_KEY:
        try:
            r = requests.get(
                "https://api.pexels.com/v1/search",
                params={"query": vis_kw, "orientation": "landscape",
                        "per_page": 5, "size": "large"},
                headers={"Authorization": PEXELS_KEY},
                timeout=5,
            )
            if r.status_code == 200:
                for photo in r.json().get("photos", []):
                    photo_id = photo.get("id", 0)
                    if photo_id in _USED_PEXELS_IDS:
                        continue
                    img_url = photo.get("src", {}).get("large2x", "")
                    if not img_url:
                        continue
                    ir = requests.get(img_url, timeout=5, headers=hdrs)
                    if ir.status_code == 200 and len(ir.content) > 20_000:
                        photographer = photo.get("photographer", "Pexels")
                        result = _save(ir.content, "pexels", f"Pexels / {photographer}")
                        if result:
                            _USED_PEXELS_IDS.add(photo_id)
                            return result
        except Exception:
            pass

    # ── 3. Fallback ultime : og-default.jpg ──────────────────────────────────
    print(f"  [FALLBACK] {slug} → og-default.jpg")
    default_src = ROOT / "assets" / "images" / "og-default.jpg"
    if default_src.exists():
        import shutil
        shutil.copy2(default_src, dest)
    return "default", "Les Faits"


# ── Constantes UI partagées ──────────────────────────────────────────────────
_NAV_LINKS = (
    '<a href="/categories/societe.html">Société</a>\n'
    '<a href="/categories/science.html">Science</a>\n'
    '<a href="/categories/economie.html">Économie</a>\n'
    '<a href="/categories/tech.html">Tech</a>\n'
    '<a href="/categories/sante.html">Santé</a>\n'
    '<a href="/categories/environnement.html">Environnement</a>\n'
    '<a href="favoris.html">Favoris</a>\n'
    '<a href="/archive.html">Tous les articles</a>\n'
    '<a href="/methode.html">Comment on travaille</a>\n'
    '<a href="/a-propos.html">À propos &amp; réseaux</a>\n'
    '<a href="/#newsletter" class="nav-cta">S\'abonner à la newsletter</a>'
)
_BURGER_JS = (
    "function toggleMenu(){"
    "var b=document.getElementById('burger'),"
    "m=document.getElementById('nav-mobile'),"
    "o=document.getElementById('nav-overlay');"
    "b.classList.toggle('open');m.classList.toggle('open');o.classList.toggle('open');}"
    "\nfunction closeMenu(){"
    "document.getElementById('burger').classList.remove('open');"
    "document.getElementById('nav-mobile').classList.remove('open');"
    "document.getElementById('nav-overlay').classList.remove('open');}"
    "\ndocument.querySelectorAll('.nav-mobile a').forEach(function(a){"
    "a.addEventListener('click',closeMenu);});"
    "\ndocument.addEventListener('keydown',function(e){if(e.key==='Escape')closeMenu();});"
    # Dropdown catégories desktop
    "\ndocument.addEventListener('DOMContentLoaded',function(){"
    "var btn=document.getElementById('nav-cats-btn');"
    "var dd=document.getElementById('nav-cats-dd');"
    "if(!btn||!dd)return;"
    "btn.addEventListener('click',function(e){"
    "e.stopPropagation();"
    "var open=dd.classList.toggle('open');"
    "btn.classList.toggle('open',open);"
    "btn.setAttribute('aria-expanded',open?'true':'false');});"
    "document.addEventListener('click',function(){"
    "dd.classList.remove('open');btn.classList.remove('open');btn.setAttribute('aria-expanded','false');});"
    "document.addEventListener('keydown',function(e){"
    "if(e.key==='Escape'){dd.classList.remove('open');btn.classList.remove('open');btn.setAttribute('aria-expanded','false');}});});"
)
BURGER_HTML = (
    '<div class="nav-overlay" id="nav-overlay" onclick="closeMenu()"></div>\n'
    '<nav class="nav-mobile" id="nav-mobile">\n'
    + _NAV_LINKS + '\n</nav>\n'
    '<script>\n' + _BURGER_JS + '\n</script>'
)
BURGER_BTN = (
    '<button class="burger" id="burger" aria-label="Menu" onclick="toggleMenu()">'
    '<span></span><span></span><span></span></button>'
)

_ICO_GRID  = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>'
_ICO_LIST  = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><line x1="9" y1="6" x2="20" y2="6"/><line x1="9" y1="12" x2="20" y2="12"/><line x1="9" y1="18" x2="20" y2="18"/><circle cx="4" cy="6" r="1.5" fill="currentColor" stroke="none"/><circle cx="4" cy="12" r="1.5" fill="currentColor" stroke="none"/><circle cx="4" cy="18" r="1.5" fill="currentColor" stroke="none"/></svg>'
_ICO_INSTA = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><rect x="2" y="2" width="20" height="20" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.5" cy="6.5" r="1.2" fill="currentColor" stroke="none"/></svg>'
_ICO_SPARK = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/><path d="M20 3v4m2-2h-4"/></svg>'
_ICO_MAIL  = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M2 7l10 7 10-7"/></svg>'

HEADER_NAV_DESKTOP = (
    '<nav class="nav-expand-group" aria-label="Navigation principale">\n'
    '      <div class="nav-cats-wrap">\n'
    '        <button class="nav-expand-item" id="nav-cats-btn" aria-label="Catégories" aria-haspopup="true" aria-expanded="false">'
    + _ICO_GRID +
    '<span class="nav-expand-label">Catégories</span></button>\n'
    '        <div class="nav-cats-dd" id="nav-cats-dd" role="menu">\n'
    '          <a class="cat-dd-item" href="/categories/societe.html" role="menuitem"><span class="cat-dd-dot" style="background:#78716c"></span>Société</a>\n'
    '          <a class="cat-dd-item" href="/categories/science.html" role="menuitem"><span class="cat-dd-dot" style="background:#06b6d4"></span>Science</a>\n'
    '          <a class="cat-dd-item" href="/categories/economie.html" role="menuitem"><span class="cat-dd-dot" style="background:#f97316"></span>Économie</a>\n'
    '          <a class="cat-dd-item" href="/categories/tech.html" role="menuitem"><span class="cat-dd-dot" style="background:#a855f7"></span>Tech</a>\n'
    '          <a class="cat-dd-item" href="/categories/sante.html" role="menuitem"><span class="cat-dd-dot" style="background:#f43f5e"></span>Santé</a>\n'
    '          <a class="cat-dd-item" href="/categories/environnement.html" role="menuitem"><span class="cat-dd-dot" style="background:#22c55e"></span>Environnement</a>\n'
    '        </div>\n'
    '      </div>\n'
    '      <a class="nav-expand-item" href="/archive.html" aria-label="Tous les articles">'
    + _ICO_LIST +
    '<span class="nav-expand-label">Tous les articles</span></a>\n'
    '      <a class="nav-expand-item" href="/a-propos.html" aria-label="Réseaux">'
    + _ICO_INSTA +
    '<span class="nav-expand-label">Réseaux</span></a>\n'
    '      <a class="nav-expand-item" href="/methode.html" aria-label="Notre méthode">'
    + _ICO_SPARK +
    '<span class="nav-expand-label">Notre méthode</span></a>\n'
    '      <a class="nav-expand-item" href="/#newsletter" aria-label="Newsletter">'
    + _ICO_MAIL +
    '<span class="nav-expand-label">Newsletter</span></a>\n'
    '    </nav>'
)

DARK_TOGGLE = '<button class="dark-toggle" id="dark-toggle" aria-label="Mode sombre" title="Mode sombre">🌙</button>'

# Script injecté dans <head> pour éviter le flash (FOUC)
_DARK_INIT_HEAD = """<script>
(function(){var s=localStorage.getItem('theme'),d=s==='dark'||(s===null&&window.matchMedia('(prefers-color-scheme:dark)').matches);document.documentElement.setAttribute('data-theme',d?'dark':'light');})();
</script>"""

# Analytics Umami
_ANALYTICS_JS = '<script defer src="https://cloud.umami.is/script.js" data-website-id="8d68a78f-97ae-4c95-a955-5d3df758f7e2"></script>'

# Favicon + manifest — doivent être présents dans TOUS les templates de page
FAVICON_LINKS = (
    '<link rel="icon" type="image/svg+xml" href="/favicon.svg"/>\n'
    '  <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png"/>\n'
    '  <link rel="icon" type="image/png" sizes="16x16" href="/favicon-16x16.png"/>\n'
    '  <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png"/>\n'
    '  <link rel="shortcut icon" href="/favicon.ico"/>\n'
    '  <link rel="manifest" href="/manifest.json"/>'
)

# CSP — GitHub Pages ne permet pas d'en-têtes HTTP custom, donc balise meta.
# 'unsafe-inline' requis (dark-mode toggle, burger menu, styles inline dans
# les gabarits) mais bloque toute source de script/style externe non listée.
CSP_META = (
    '<meta http-equiv="Content-Security-Policy" content="default-src \'self\'; '
    'script-src \'self\' \'unsafe-inline\' https://cloud.umami.is; '
    'style-src \'self\' \'unsafe-inline\'; '
    'img-src \'self\' data: https:; '
    'connect-src \'self\' https://cloud.umami.is https://api.web3forms.com https://api.brevo.com; '
    'base-uri \'self\'; '
    'form-action \'self\'; '
    'frame-ancestors \'none\';"/>'
)

# Placeholder remplacé par le secret BREVO_CONTACTS_KEY au moment du déploiement
# (voir deploy.yml — step "Injecter la clé Brevo dans l'HTML")
BREVO_CONTACTS_KEY = "__BREVO_CONTACTS_KEY__"
BREVO_LIST_ID_NL   = 3
# ID du template "double opt-in" créé dans Brevo (Campagnes → Templates).
# Le contact n'est ajouté à la liste qu'après clic sur le lien de confirmation.
BREVO_DOI_TEMPLATE_ID = 3  # Template DOI par défaut Brevo — le seul accepté par
                           # l'API doubleOptinConfirmation (un template créé via
                           # l'éditeur classique est refusé : "An active DOI
                           # template does not exist", même marqué doiTemplate)
BREVO_DOI_REDIRECT    = "https://lesfaits.info/confirmation.html"

# Bloc newsletter injecté dans index.html (avant le footer)
def _build_newsletter_section() -> str:
    return f"""
<section class="nl-compact" id="newsletter" aria-label="S'abonner à la newsletter">
  <div class="nl-compact__inner">
    <div class="nl-compact__head">
      <span class="nl-compact__label">NEWSLETTER</span>
      <span class="nl-compact__title">Le résumé du jour dans votre boîte mail</span>
    </div>
    <form id="nl-form" novalidate>
      <div class="nl-compact__freq" role="group" aria-label="Fréquence de réception">
        <label class="nl-compact__freq-opt"><input type="radio" name="FREQ" value="morning"/> Matin (~7h)</label>
        <label class="nl-compact__freq-opt"><input type="radio" name="FREQ" value="evening"/> Soir (~18h)</label>
        <label class="nl-compact__freq-opt"><input type="radio" name="FREQ" value="both" checked/> Les deux</label>
      </div>
      <div class="nl-compact__row">
        <input type="email" id="nl-email" name="email" class="nl-compact__input" placeholder="vous@exemple.fr" required autocomplete="email" aria-required="true"/>
        <button type="submit" class="nl-compact__btn" id="nl-btn">S'abonner →</button>
      </div>
      <div class="nl-compact__cats" role="group" aria-label="Rubriques">
        <label class="nl-compact__cat"><input type="checkbox" name="CAT_SOCIETE" value="1"/> Société</label>
        <label class="nl-compact__cat"><input type="checkbox" name="CAT_SCIENCE" value="1"/> Science</label>
        <label class="nl-compact__cat"><input type="checkbox" name="CAT_ECONOMIE" value="1"/> Économie</label>
        <label class="nl-compact__cat"><input type="checkbox" name="CAT_TECH" value="1"/> Tech</label>
        <label class="nl-compact__cat"><input type="checkbox" name="CAT_SANTE" value="1"/> Santé</label>
        <label class="nl-compact__cat"><input type="checkbox" name="CAT_ENVIRONNEMENT" value="1"/> Environnement</label>
      </div>
      <p class="nl-compact__hint">Aucune sélection = toutes les rubriques</p>
      <label class="nl-compact__consent">
        <input type="checkbox" id="nl-consent" required aria-required="true"/>
        <span>J'accepte la <a href="confidentialite.html">politique de confidentialité</a>. Désabonnement en un clic.</span>
      </label>
      <p class="nl-compact__msg" id="nl-msg" role="alert" aria-live="polite"></p>
    </form>
  </div>
</section>
<script>
(function(){{
  var BREVO_KEY="{BREVO_CONTACTS_KEY}",BREVO_LIST={BREVO_LIST_ID_NL},BREVO_API="https://api.brevo.com/v3/contacts/doubleOptinConfirmation",BREVO_DOI_TPL={BREVO_DOI_TEMPLATE_ID},BREVO_DOI_URL="{BREVO_DOI_REDIRECT}";
  var form=document.getElementById("nl-form"),msgEl=document.getElementById("nl-msg"),btn=document.getElementById("nl-btn");
  if(!form)return;
  form.addEventListener("submit",function(e){{
    e.preventDefault();
    msgEl.className="nl-compact__msg";msgEl.textContent="";
    var email=(document.getElementById("nl-email").value||"").trim();
    var consent=document.getElementById("nl-consent").checked;
    if(!email||!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)){{msgEl.textContent="Veuillez saisir une adresse email valide.";msgEl.className="nl-compact__msg nl-compact__msg--err";return;}}
    if(!consent){{msgEl.textContent="Veuillez accepter les conditions.";msgEl.className="nl-compact__msg nl-compact__msg--err";return;}}
    var attrs={{}};
    ["CAT_SOCIETE","CAT_SCIENCE","CAT_ECONOMIE","CAT_TECH","CAT_SANTE","CAT_ENVIRONNEMENT"].forEach(function(k){{var cb=form.querySelector('input[name="'+k+'"]');attrs[k]=cb?cb.checked:false;}});
    var freqEl=form.querySelector('input[name="FREQ"]:checked');attrs["FREQ"]=freqEl?freqEl.value:"both";
    btn.disabled=true;btn.textContent="Envoi…";
    fetch(BREVO_API,{{method:"POST",headers:{{"accept":"application/json","content-type":"application/json","api-key":BREVO_KEY}},body:JSON.stringify({{email:email,includeListIds:[BREVO_LIST],attributes:attrs,templateId:BREVO_DOI_TPL,redirectionUrl:BREVO_DOI_URL}})}})
    .then(function(r){{
      if(r.status===201||r.status===200||r.status===204){{msgEl.textContent="Un email de confirmation vient de vous être envoyé — cliquez sur le lien pour valider votre inscription (vérifiez vos spams).";msgEl.className="nl-compact__msg nl-compact__msg--ok";form.reset();}}
      else if(r.status===400){{return r.json().then(function(d){{if(d&&d.code==="duplicate_parameter"){{msgEl.textContent="Déjà inscrit !";msgEl.className="nl-compact__msg nl-compact__msg--ok";}}else{{throw new Error(d&&d.message);}}}})}}
      else{{throw new Error("Erreur "+r.status);}}
    }})
    .catch(function(err){{msgEl.textContent="Erreur. Réessayez dans un instant.";msgEl.className="nl-compact__msg nl-compact__msg--err";}})
    .finally(function(){{btn.disabled=false;btn.textContent="S'abonner →";}});
  }});
}})();
</script>"""




BRAND_ICON = (
    '<svg class="brand__icon" width="26" height="26" viewBox="0 0 200 200" '
    'aria-hidden="true" focusable="false">'
    '<rect width="200" height="200" rx="28" fill="#141416"/>'
    '<circle cx="100" cy="100" r="72" fill="none" stroke="#6C85BD" stroke-width="4"/>'
    '<circle cx="28" cy="100" r="7" fill="#6C85BD"/>'
    '<circle cx="172" cy="100" r="7" fill="#6C85BD"/>'
    '<text x="84" y="132" font-family="Georgia,\'Times New Roman\',serif" font-size="92" '
    'font-weight="700" fill="#F1EFE8" text-anchor="middle">l</text>'
    '<text x="128" y="132" font-family="Georgia,\'Times New Roman\',serif" font-size="92" '
    'font-weight="700" fill="#6C85BD" text-anchor="middle">f</text>'
    '</svg>'
)

# Script complet injecté avant </body> (bouton + toggle)
_DARK_MODE_JS = """<script>
(function(){
  var btn=document.getElementById('dark-toggle');
  var dark=document.documentElement.getAttribute('data-theme')==='dark';
  if(btn){btn.textContent=dark?'☀️':'🌙';btn.setAttribute('aria-label',dark?'Passer en mode clair':'Passer en mode sombre');}
  if(btn) btn.addEventListener('click',function(){
    var d=document.documentElement.getAttribute('data-theme')==='dark';
    document.documentElement.setAttribute('data-theme',d?'light':'dark');
    localStorage.setItem('theme',d?'light':'dark');
    btn.textContent=d?'🌙':'☀️';btn.setAttribute('aria-label',d?'Passer en mode sombre':'Passer en mode clair');
  });
})();
</script>"""

def _build_footer(year: int = None) -> str:
    y = year or datetime.now().year
    return f"""<footer class="footer" role="contentinfo" aria-label="Pied de page">
  <div class="footer__inner">
    <div class="footer__brand">
      <div class="brand__logotype"><span class="fact">les</span><span class="uel">faits</span></div>
      <p>Journal numérique français rédigé par IA. Sans publicité. Sans actionnaires.</p>
      <p style="font-size:10px;color:var(--muted);margin-top:8px">Aucune publicité · Aucun actionnaire · Aucun cookie de tracking</p>
    </div>
    <div class="footer__col"><h4>RUBRIQUES</h4>
      <a href="/categories/societe.html">Société</a>
      <a href="/categories/science.html">Science</a>
      <a href="/categories/economie.html">Économie</a>
      <a href="/categories/tech.html">Tech</a>
      <a href="/categories/sante.html">Santé</a>
      <a href="/categories/environnement.html">Environnement</a>
    </div>
    <div class="footer__col"><h4>JOURNAL</h4>
      <a href="/methode.html">Comment on travaille</a>
      <a href="/a-propos.html">À propos &amp; réseaux</a>
      <a href="/corrections.html">Corrections publiques</a>
      <a href="/archive.html">Tous les articles</a>
      <a href="feed.xml" class="footer__rss">Flux RSS</a>
      <a href="/#newsletter">Newsletter</a>
    </div>
    <div class="footer__col"><h4>LÉGAL</h4>
      <a href="/mentions-legales.html">Mentions légales</a>
      <a href="/confidentialite.html">Confidentialité</a>
      <a href="/cgu.html">CGU</a>
    </div>
    <div class="footer__col"><h4>CONTACT</h4>
      <a href="/contact.html">Nous écrire</a>
      <a href="contact.html#erreur">Signaler une erreur</a>
    </div>
  </div>
  <div class="footer__bottom">
    <span>© {y} Les Faits · <a href="https://creativecommons.org/licenses/by-nc-nd/4.0/deed.fr" rel="noopener noreferrer external" target="_blank" style="color:inherit">CC BY-NC-ND 4.0</a></span>
    <span>Protocole éditorial v1.1</span>
  </div>
</footer>"""

def _sanitize_image_keyword(kw: str, fallback: str = "") -> str:
    """Keyword propre pour recherche image : sans accents, sans virgules, max 5 mots."""
    import unicodedata
    kw = unicodedata.normalize("NFD", kw)
    kw = "".join(c for c in kw if unicodedata.category(c) != "Mn")
    kw = kw.replace(",", " ").replace(";", " ")
    kw = re.sub(r"\s+", " ", kw).strip()
    words = kw.split()[:5]
    result = " ".join(words)
    return result if len(result) > 3 else (fallback or "france news")


def _paris_iso_now() -> str:
    """Horodatage ISO 8601 avec le vrai offset Paris (+01:00 CET / +02:00 CEST) —
    évite le décalage d'1h l'hiver qu'un offset codé en dur produirait."""
    iso = datetime.now(ZoneInfo("Europe/Paris")).strftime("%Y-%m-%dT%H:%M:%S%z")
    return f"{iso[:-2]}:{iso[-2:]}"


def build_article_html(art: dict, date_pub: str) -> str:
    resume_txt = " ".join(art["resume"]) if isinstance(art.get("resume"), list) else art.get("resume", "")
    slug      = art.get("slug", "")
    safe_slug = _slug_ascii(slug)
    cat       = art.get("categorie", "")

    # Normalisation typographique française sur tous les champs texte
    art["titre"]              = _typo_fr(art.get("titre", ""))
    resume_txt                = _typo_fr(resume_txt)
    art["corps"]["faits"]     = _typo_fr(art["corps"].get("faits", ""))
    art["corps"]["contexte"]  = _typo_fr(art["corps"].get("contexte", ""))
    art["corps"]["nuances"]   = _typo_fr(art["corps"].get("nuances", ""))

    # Description SEO : coupe à la dernière phrase complète ≤ 155 chars
    def _seo_desc(text: str, limit: int = 155) -> str:
        if len(text) <= limit:
            return text
        chunk = text[:limit]
        # Couper à la dernière fin de phrase
        for sep in (". ", "! ", "? "):
            idx = chunk.rfind(sep)
            if idx > 60:
                return chunk[:idx + 1]
        # Fallback : couper au dernier espace
        idx = chunk.rfind(" ")
        return (chunk[:idx] + "…") if idx > 60 else chunk[:limit]
    desc_seo = _seo_desc(resume_txt)

    # Image hero
    local_img_path = f"assets/images/{safe_slug}.jpg"
    img_source_type, img_credit = "pillow", "Les Faits"
    if not os.path.exists(local_img_path):
        kw = _sanitize_image_keyword(art.get("image_keyword", ""), fallback=safe_slug)
        img_source_type, img_credit = _download_hero(
            kw, slug, local_img_path,
            sources=art.get("sources", []),
            title=art.get("titre", ""),
            summary=" ".join(art.get("resume", [])) if isinstance(art.get("resume"), list) else art.get("resume", ""),
            category=cat,
        )
    hero_src = local_img_path if os.path.exists(local_img_path) else ""
    hero_img = (
        f'<!-- Image source: {img_credit} | Type: {img_source_type} -->\n'
        f'<figure class="article__hero" data-img-source="{img_source_type}" data-img-credit="{img_credit}" style="margin-bottom:28px">'
        f'<img class="art__hero" src="{hero_src}" alt="Illustration : {_esc(art["titre"])}" loading="eager" fetchpriority="high" style="aspect-ratio:16/9;object-fit:cover"/>'
        f'</figure>'
    ) if hero_src else ""

    # Sources
    def _source_link(s):
        url = s.get("url") or ""
        path = urlparse(url).path.rstrip("/") if url else ""
        if url and len(path) > 3:
            return f' · <a href="{_esc(url)}" target="_blank" rel="noopener noreferrer external" aria-label="{_esc(s.get("institution","Source"))} (ouvre dans un nouvel onglet)">Lire la source →</a>'
        return ""

    verified_sources = [s for s in art.get("sources", []) if s.get("url") and len(urlparse(s["url"]).path.rstrip("/")) > 3]
    def _source_date(s):
        # Masquer le champ date quand il est absent (évite d'afficher "None")
        d = s.get("date")
        return f' · {_esc(str(d))}' if d and str(d).strip().lower() not in ("none", "null", "") else ""

    if verified_sources:
        sources_li = "\n".join(
            f'<li><cite>{_esc(s["institution"])}</cite> · <em>{_esc(s["titre"])}</em>{_source_date(s)}{_source_link(s)}</li>'
            for s in verified_sources
        )
        sources_html = f'<section class="sources" aria-label="Sources"><h3>SOURCES</h3><ol>{sources_li}</ol></section>'
    else:
        sources_html = '<section class="sources sources--unverified" aria-label="Sources"><p style="color:#999;font-style:italic;font-size:.85rem;margin:0">Sources citées dans le texte — URLs non vérifiées directement.</p></section>'

    nb_src = len(verified_sources)

    # Temps de lecture
    body_text = art["corps"]["faits"] + " " + art["corps"]["contexte"] + " " + art["corps"]["nuances"]
    word_count = len(body_text.split())
    reading_time = max(1, round(word_count / 200))

    faits    = _esc(art["corps"]["faits"]).replace("\n", "</p><p>")
    contexte = _esc(art["corps"]["contexte"]).replace("\n", "</p><p>")
    nuances  = _esc(art["corps"]["nuances"]).replace("\n", "</p><p>")

    # Articles liés — 1 par catégorie différente de l'article courant
    related_html = ""
    try:
        all_arts = load_index()
        other = [a for a in all_arts if a.get("categorie") != cat and a["slug"] != slug]
        seen_cats: set = set()
        related: list = []
        for a in other:
            if a["categorie"] not in seen_cats:
                related.append(a)
                seen_cats.add(a["categorie"])
            if len(related) == 3:
                break
        if len(related) < 3:
            same = [a for a in all_arts if a.get("categorie") == cat and a["slug"] != slug]
            related += same[:3 - len(related)]
        if related:
            cards = "\n".join(
                f'<a class="art__related-card" href="articles/{a["slug"]}.html">'
                f'<img src="assets/images/{a["slug"]}.jpg" alt="{a["titre"]}" loading="lazy" style="width:calc(100% + 32px);margin:-14px -16px 12px;height:110px;object-fit:cover;display:block;border-radius:var(--radius) var(--radius) 0 0">'
                f'<span class="cat cat--{a["categorie"]}">{_cat_up(a["categorie"])}</span>'
                f'<div class="title-sm">{a["titre"]}</div>'
                f'<div style="font-size:10px;color:var(--muted);margin-top:6px">{a["date"]}</div>'
                f'</a>'
                for a in related
            )
            related_html = f'<div class="art__related"><div class="art__related-title">À LIRE AUSSI</div><div class="art__related-grid">{cards}</div></div>'
    except Exception:
        pass

    # Share buttons JS
    art_url = f"{BASE_URL}/articles/{slug}.html"
    art_titre_js = _esc_js(art['titre'])
    share_js = f"""<script>
function shareArticle(){{
  if(navigator.share){{
    navigator.share({{title:'{art_titre_js}',url:'{art_url}'}}).catch(function(){{}});
  }}
}}
function copyLink(){{
  navigator.clipboard.writeText('{art_url}').then(function(){{
    var btn=document.getElementById('copy-btn');
    btn.textContent='✓ Copié !';setTimeout(function(){{btn.textContent='Copier le lien';}},2000);
  }});
}}
// Barre de progression lecture
(function(){{
  var bar=document.getElementById('read-progress');
  if(!bar)return;
  window.addEventListener('scroll',function(){{
    var h=document.documentElement,b=document.body;
    var st=h.scrollTop||b.scrollTop;
    var sh=(h.scrollHeight||b.scrollHeight)-h.clientHeight;
    bar.style.width=sh>0?(st/sh*100)+'%':'0%';
  }},{{passive:true}});
}})();
// Favoris
(function(){{
  var btn=document.getElementById('fav-btn');
  if(!btn)return;
  var favs=JSON.parse(localStorage.getItem('lesfaits_favs')||'[]');
  var slug='{slug}';
  if(favs.indexOf(slug)>-1){{btn.classList.add('active');btn.setAttribute('aria-pressed','true');btn.textContent='Favori';}}
  btn.addEventListener('click',function(){{
    var f=JSON.parse(localStorage.getItem('lesfaits_favs')||'[]');
    var idx=f.indexOf(slug);
    if(idx>-1){{f.splice(idx,1);btn.classList.remove('active');btn.setAttribute('aria-pressed','false');btn.textContent='Favoris';}}
    else{{f.push(slug);btn.classList.add('active');btn.setAttribute('aria-pressed','true');btn.textContent='Favori';}}
    localStorage.setItem('lesfaits_favs',JSON.stringify(f));
  }});
}})();
</script>"""

    share_html = f"""<div class="art__share">
  <span class="art__share-label">Partager</span>
  <button class="share-btn share-btn--native" onclick="shareArticle()" style="display:{'none' if True else 'none'}" id="native-share">↗ Partager</button>
  <a class="share-btn" href="https://twitter.com/intent/tweet?url={art_url}&text={urllib.parse.quote(art['titre'])}" target="_blank" rel="noopener noreferrer external">𝕏 Twitter</a>
  <a class="share-btn" href="https://www.linkedin.com/sharing/share-offsite/?url={art_url}" target="_blank" rel="noopener noreferrer external">in LinkedIn</a>
  <a class="share-btn" href="https://api.whatsapp.com/send?text={urllib.parse.quote(art['titre'])}%20{art_url}" target="_blank" rel="noopener noreferrer external">WhatsApp</a>
  <button class="share-btn" onclick="copyLink()" id="copy-btn">Copier le lien</button>
  <button class="fav-btn" id="fav-btn" aria-pressed="false">Favoris</button>
</div>
<script>if(navigator.share)document.getElementById('native-share').style.display='inline-flex';</script>"""

    verify_html = (
        f'<div class="art__verify">'
        f'<span class="art__verify-item">✓ {nb_src} source{"s" if nb_src > 1 else ""} vérifiée{"s" if nb_src > 1 else ""}</span>'
        f'<span class="art__verify-item">✓ Sources concordantes</span>'
        f'<span class="art__verify-item">✓ Protocole éditorial v1.1</span>'
        f'</div>'
    ) if nb_src > 0 else ""

    return f"""<!DOCTYPE html>
<html lang="fr" data-theme="">
<head>
  <meta charset="UTF-8"/>
  {CSP_META}
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <meta name="description" content="{_esc(desc_seo)}"/>
  <meta name="robots" content="index, follow, max-snippet:-1, max-image-preview:large, max-video-preview:-1"/>
  <meta name="author" content="Les Faits — IA éditoriale"/>
  <meta property="og:title" content="{_esc(art['titre'])} — Les Faits"/>
  <meta property="og:description" content="{_esc(desc_seo)}"/>
  <meta property="og:type" content="article"/>
  <meta property="og:url" content="{art_url}"/>
  {f'<meta property="og:image" content="{BASE_URL}/{hero_src}"/><meta property="og:image:width" content="1200"/><meta property="og:image:height" content="630"/><meta property="og:image:type" content="image/jpeg"/>' if hero_src else ''}
  <meta property="article:section" content="{cat}"/>
  <link rel="canonical" href="{art_url}"/>
  <meta name="twitter:card" content="summary_large_image"/>
  <meta name="twitter:title" content="{_esc(art['titre'])} — Les Faits"/>
  <meta name="twitter:description" content="{_esc(desc_seo)}"/>
  <meta name="twitter:image" content="{f'{BASE_URL}/{hero_src}' if hero_src else f'{BASE_URL}/assets/images/og-default.jpg'}"/>
  <link rel="alternate" type="application/rss+xml" title="Les Faits — RSS" href="/feed.xml"/>
  <link rel="icon" type="image/svg+xml" href="/favicon.svg"/>
  <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png"/>
  <link rel="icon" type="image/png" sizes="16x16" href="/favicon-16x16.png"/>
  <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png"/>
  <link rel="shortcut icon" href="/favicon.ico"/>
  <link rel="manifest" href="/manifest.json"/>
  <title>{_esc(art['titre'])} — Les Faits</title>
  <script type="application/ld+json">{{"@context":"https://schema.org","@type":"NewsArticle","headline":"{_esc_json(art['titre'])}","description":"{_esc_json(desc_seo)}","datePublished":"{_paris_iso_now()}","dateModified":"{_paris_iso_now()}","articleSection":"{cat}","inLanguage":"fr","isAccessibleForFree":true,"image":{{"@type":"ImageObject","url":"{BASE_URL}/{hero_src}","width":1200,"height":630}},"author":{{"@type":"Organization","name":"Les Faits"}},"publisher":{{"@type":"Organization","name":"Les Faits","@id":"{BASE_URL}/#org","logo":{{"@type":"ImageObject","url":"{BASE_URL}/assets/images/og-default.jpg"}}}},"mainEntityOfPage":{{"@type":"WebPage","@id":"{art_url}"}}}}</script>
  <script type="application/ld+json">{{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[{{"@type":"ListItem","position":1,"name":"Accueil","item":"{BASE_URL}/"}},{{"@type":"ListItem","position":2,"name":"{CAT_LABELS.get(cat, cat)}","item":"{BASE_URL}/categories/{cat}.html"}},{{"@type":"ListItem","position":3,"name":"{_esc_json(art['titre'])}"}}]}}</script>
  <base href="/"/>
  <link rel="stylesheet" href="/src/style.css"/>
  {_DARK_INIT_HEAD}
</head>
<body>
{BURGER_HTML}
<header class="header">
  <div class="header__inner">
    <a href="index.html" class="brand">
      <div class="brand__logotype"><span class="fact">les</span><span class="uel">faits</span></div>
    </a>
    <div class="header__search">
      <input type="search" class="header__search-input" placeholder="Rechercher…" autocomplete="off" onkeydown="if(event.key==='Enter'&&this.value.trim())window.location=(document.querySelector('base').href)+'recherche.html?q='+encodeURIComponent(this.value.trim())"/>
    </div>
    {HEADER_NAV_DESKTOP}
    {DARK_TOGGLE}
    {BURGER_BTN}
  </div>
</header>
<div id="read-progress"></div>
<main>
<div class="art">
  <a class="art__back" href="index.html">← Retour à l'accueil</a>
  <span class="art__cat cat--{cat}">{_cat_up(cat)}</span>
  <h1 class="art__title">{_esc(art['titre'])}</h1>
  <div class="art__meta">
    {f'<span style="color:var(--blue);font-weight:600">{nb_src} source{"s" if nb_src > 1 else ""}</span><span class="meta__sep" aria-hidden="true">·</span>' if nb_src > 0 else ''}
    <time datetime="{datetime.now().strftime('%Y-%m-%d')}">{date_pub}</time>
    <span class="meta__sep" aria-hidden="true">·</span>
    <span class="art__reading-time">Lecture : {reading_time} min</span>
  </div>
  <div class="art__ai-badge" role="note">🤖 Contenu rédigé par intelligence artificielle — <a href="methode.html" style="color:inherit;text-decoration:underline">notre méthode</a></div>
  {verify_html}
  <div class="art__rule"></div>
  {hero_img}
  <p class="art__resume">{_esc(resume_txt)}</p>
  <h2 class="art__h2">Les faits</h2><p>{faits}</p>
  <h2 class="art__h2">Contexte</h2><p>{contexte}</p>
  <h2 class="art__h2">Débats et nuances</h2><p>{nuances}</p>
  {build_spectrum_html(art.get("positions", {}))}
  {share_html}
  {sources_html}
  {related_html}
  <p class="art__badge">Généré par IA · Protocole Les Faits v1.1 · {date_pub}</p>
  <a class="contest-btn" href="contact.html?article={slug}#erreur">Signaler une erreur sur cet article</a>
</div>
</main>
<button class="back-to-top" id="btt" aria-label="Retour en haut" title="Retour en haut">↑</button>
{_build_footer()}
{share_js}
<script>
(function(){{
  var btn=document.getElementById('btt');
  window.addEventListener('scroll',function(){{
    btn.classList.toggle('visible',window.scrollY>300);
  }},{{passive:true}});
  btn.addEventListener('click',function(){{window.scrollTo({{top:0,behavior:'smooth'}});}});
}})();
</script>
{_DARK_MODE_JS}
{_ANALYTICS_JS}
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════════
# RECONSTRUCTION INDEX.HTML
# ══════════════════════════════════════════════════════════════════════════════

def rebuild_articles_related(articles: list):
    """Met à jour le bloc 'À lire aussi' de chaque article avec des thèmes croisés."""
    arts_by_slug = {a["slug"]: a for a in articles}
    updated = 0
    for art in articles:
        slug = art["slug"]
        cat  = art.get("categorie", "")
        path = ROOT / "articles" / f"{slug}.html"
        if not path.exists():
            continue
        # Sélectionner 3 articles de catégories différentes
        other = [a for a in articles if a.get("categorie") != cat and a["slug"] != slug]
        seen_cats: set = set()
        related: list = []
        for a in other:
            if a["categorie"] not in seen_cats:
                related.append(a)
                seen_cats.add(a["categorie"])
            if len(related) == 3:
                break
        if len(related) < 3:
            same = [a for a in articles if a.get("categorie") == cat and a["slug"] != slug]
            related += same[:3 - len(related)]
        if not related:
            continue
        cards = "".join(
            f'<a class="art__related-card" href="articles/{a["slug"]}.html">'
            f'<img src="assets/images/{a["slug"]}.jpg" alt="{_esc(a["titre"])}" width="400" height="110" loading="lazy" style="width:calc(100% + 32px);margin:-14px -16px 12px;height:110px;object-fit:cover;display:block;border-radius:var(--radius) var(--radius) 0 0">'
            f'<span class="cat cat--{a["categorie"]}">{_cat_up(a["categorie"])}</span>'
            f'<div class="title-sm">{_esc(a["titre"])}</div>'
            f'<div style="font-size:10px;color:var(--muted);margin-top:6px">{a["date"]}</div>'
            f'</a>'
            for a in related
        )
        new_block = (
            f'<div class="art__related">'
            f'<div class="art__related-title">À LIRE AUSSI</div>'
            f'<div class="art__related-grid">{cards}</div>'
            f'</div>'
        )
        html = path.read_text(encoding="utf-8")
        # Remplacement robuste par comptage des divs imbriqués
        marker = '<div class="art__related">'
        start = html.find(marker)
        if start < 0:
            continue
        depth, i, end = 0, start, -1
        while i < len(html):
            if html[i:i+4] == '<div':
                depth += 1; i += 4
            elif html[i:i+6] == '</div>':
                depth -= 1
                if depth == 0:
                    end = i + 6; break
                i += 6
            else:
                i += 1
        if end < 0:
            continue
        new_html = html[:start] + new_block + html[end:]
        if new_html != html:
            path.write_text(new_html, encoding="utf-8")
            updated += 1
    print(f"  ✓ {updated} articles mis à jour (À lire aussi cross-catégorie)")


def rebuild_index():
    """Relit articles.json et reconstruit la section À LA UNE de index.html."""
    articles = load_index()
    if not articles:
        return

    # Génération des cards "side" (articles 1-3)
    def side_card(a):
        return f"""<a class="une__side-item" href="articles/{a['slug']}.html" style="display:grid;grid-template-columns:64px 1fr;gap:14px;align-items:center">
          <img src="assets/images/{a['slug']}.jpg" alt="{_esc(a['titre'])}" loading="lazy" style="width:64px;height:64px;object-fit:cover;border-radius:4px;display:block">
          <div>
          <span class="cat cat--{a['categorie']}">{_cat_up(a['categorie'])}</span>
          <h3 class="title-md">{_esc(a['titre'])}</h3>
          <div class="meta"><span class="meta__src">{a['nb_sources']} sources</span>
          <span class="meta__sep">·</span><span>{a['date']}</span></div>
          </div>
        </a>"""

    def mini_card(a):
        return f"""<a class="card3" href="articles/{a['slug']}.html">
          <img class="card3__img" src="assets/images/{a['slug']}.jpg" alt="{_esc(a['titre'])}" loading="lazy">
          <div class="card3__body">
            <span class="cat cat--{a['categorie']}">{_cat_up(a['categorie'])}</span>
            <h3 class="title-sm">{_esc(a['titre'])}</h3>
            <div class="meta" style="margin-top:10px">
              <span class="meta__src">{a['nb_sources']} sources</span>
              <span class="meta__sep">·</span><span>{a['date']}</span>
            </div>
          </div>
        </a>"""

    def list_card(i, a):
        return f"""<a class="list-item" href="articles/{a['slug']}.html">
          <span class="list-item__num">0{i+1}</span>
          <div><span class="cat cat--{a['categorie']}">{_cat_up(a['categorie'])}</span>
          <h3 class="title-sm">{_esc(a['titre'])}</h3>
          <div class="meta" style="margin-top:6px">
            <span class="meta__src">{a['nb_sources']} sources</span>
            <span class="meta__sep">·</span><span>{a['date']}</span>
          </div></div>
        </a>"""

    def _pick_diverse(pool: list, n: int, exclude_slugs: set, force_diversity: bool = True) -> list:
        """Prend les n articles les plus récents, puis diversifie si possible.

        Si force_diversity=False (ex: grille "Derniers articles"), on ne sacrifie
        jamais la fraîcheur pour la diversité — mieux vaut montrer les n articles
        les plus récents, même si un thème est sur-représenté, que de remplacer un
        article récent par un plus ancien juste pour varier les catégories.
        """
        avail = [a for a in pool if a["slug"] not in exclude_slugs]
        # Sélection de base : les n plus récents
        chosen = avail[:n]
        if not force_diversity or len(chosen) < 2:
            return chosen
        # Thèmes présents vs manquants
        all_cats = {"societe", "science", "economie", "tech", "sante", "environnement"}
        present = {a["categorie"] for a in chosen}
        missing = all_cats - present
        for cat in missing:
            # Trouver le plus récent article de ce thème hors sélection
            candidate = next((a for a in avail if a["categorie"] == cat and a not in chosen), None)
            if candidate is None:
                continue  # aucun article pour ce thème → on ne force rien
            # Trouver le doublon le plus ancien dans chosen (thème déjà représenté 2+ fois)
            cat_counts = {}
            for a in chosen:
                cat_counts[a["categorie"]] = cat_counts.get(a["categorie"], 0) + 1
            # Chercher un article à remplacer : thème sur-représenté, le moins récent
            to_replace = None
            for a in reversed(chosen):  # reversed = du plus ancien au plus récent
                if cat_counts.get(a["categorie"], 0) > 1:
                    to_replace = a
                    break
            if to_replace:
                idx = chosen.index(to_replace)
                chosen[idx] = candidate
                # Mettre à jour le compte
                cat_counts[to_replace["categorie"]] -= 1
        return chosen

    main_art  = articles[0]
    used_une  = {main_art["slug"]}
    # Side : 3 articles diversifiés (catégories différentes du main et entre eux)
    side_arts = _pick_diverse(articles[1:], 3, used_une)
    used_une.update(a["slug"] for a in side_arts)
    # Grille "Derniers articles" : hero + side_arts exclus — corpus vérifié (88+ articles)
    used_grid = {main_art["slug"]}
    used_grid.update(a["slug"] for a in side_arts)
    grid_arts = _pick_diverse(articles, 6, used_grid, force_diversity=False)
    used_grid.update(a["slug"] for a in grid_arts)
    # Liste "À lire aussi" : 6 articles diversifiés, excluant la grille (pas la une)
    list_arts = _pick_diverse(articles, 6, used_grid)

    side_html  = "\n".join(side_card(a) for a in side_arts) if side_arts else ""
    grid_html  = "\n".join(mini_card(a) for a in grid_arts) if grid_arts else ""
    list_html  = "\n".join(list_card(i, a) for i, a in enumerate(list_arts))

    index_path = ROOT / "index.html"
    html = build_index_html(main_art, side_html, grid_html, list_html)
    index_path.write_text(html, encoding="utf-8")
    print(f"  ✓ index.html reconstruit ({len(articles)} articles)")
    build_category_pages()
    build_archive_page()
    build_favoris_page()
    build_search_json(articles)
    build_feed_xml(articles)
    build_sitemap(articles)
    rebuild_articles_related(articles)


def build_index_html(main, side_html, grid_html, list_html):
    resume = " ".join(main["resume"]) if isinstance(main.get("resume"), list) else main.get("resume", "")
    # La une doit accrocher, pas noyer : on coupe à la fin de phrase la plus
    # proche sous ~260 caractères au lieu d'afficher le résumé complet en pavé.
    if len(resume) > 300:
        coupe = resume[:300]
        fin = max(coupe.rfind(". "), coupe.rfind("! "), coupe.rfind("? "))
        resume = (coupe[:fin + 1] if fin > 120 else coupe.rstrip() + "…")

    return f"""<!DOCTYPE html>
<html lang="fr" data-theme="">
<head>
  <meta charset="UTF-8"/>
  {CSP_META}
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <meta name="description" content="Les Faits — Journal numérique français rédigé par IA. Juste les faits. Aucun parti pris."/>
  <meta property="og:title" content="Les Faits — Juste les faits. Aucun parti pris."/>
  <meta property="og:description" content="Journal numérique français rédigé par IA. Sans publicité. Sans actionnaires."/>
  <meta property="og:type" content="website"/>
  <meta property="og:url" content="https://lesfaits.info/"/>
  <meta property="og:image" content="https://lesfaits.info/assets/images/og-home.jpg"/>
  <meta property="og:image:width" content="1200"/>
  <meta property="og:image:height" content="630"/>
  <meta name="twitter:card" content="summary_large_image"/>
  <meta name="twitter:title" content="Les Faits — Juste les faits. Aucun parti pris."/>
  <meta name="twitter:description" content="Journal numérique français rédigé par IA. Sans publicité. Sans actionnaires."/>
  <meta name="twitter:image" content="https://lesfaits.info/assets/images/og-home.jpg"/>
  <link rel="canonical" href="https://lesfaits.info/"/>
  <link rel="alternate" type="application/rss+xml" title="Les Faits — RSS" href="/feed.xml"/>
  <title>Les Faits — Juste les faits. Aucun parti pris.</title>
  <base href="/"/>
  <link rel="stylesheet" href="/src/style.css"/>
  {FAVICON_LINKS}
  {_DARK_INIT_HEAD}
</head>
<body>
{BURGER_HTML}
<header class="header">
  <div class="header__inner">
    <a href="index.html" class="brand">
      {BRAND_ICON}<div class="brand__logotype"><span class="fact">les</span><span class="uel">faits</span></div>
    </a>
    <div class="header__search">
      <input type="search" class="header__search-input" placeholder="Rechercher…" autocomplete="off" onkeydown="if(event.key==='Enter'&&this.value.trim())window.location=(document.querySelector('base').href)+'recherche.html?q='+encodeURIComponent(this.value.trim())"/>
    </div>
    {HEADER_NAV_DESKTOP}
    {DARK_TOGGLE}
    {BURGER_BTN}
  </div>
</header>
<div class="manifeste">
  <div class="manifeste__inner">
    <div class="manifeste__headline">100&nbsp;% IA.<br><span>0&nbsp;% parti pris.</span></div>
    <div class="manifeste__pillars">
      <div class="manifeste__pillar"><div class="manifeste__text"><strong>Rédigé par IA, sans filtre humain</strong><span>Aucun journaliste ne rédige ni n'oriente le contenu. L'IA applique le même protocole pour chaque sujet, sans exception.</span></div></div>
      <div class="manifeste__pillar"><div class="manifeste__text"><strong>Zéro influence</strong><span>Pas d'actionnaires, pas de publicité, pas de ligne politique. Les faits bruts, leurs sources, leurs contradictions.</span></div></div>
      <div class="manifeste__pillar"><div class="manifeste__text"><strong>Méthode publique</strong><span>Protocole éditorial ouvert. Minimum 3 sources par article. Corrections publiques et tracées.</span></div></div>
    </div>
  </div>
</div>
<div class="wrap">
  <div class="une">
    <div class="une__label">À LA UNE</div>
    <div style="height:2px;background:var(--blue);margin-bottom:1px"></div>
    <div class="une__grid">
      <a class="une__main" href="articles/{main['slug']}.html">
        <img src="assets/images/{main['slug']}.jpg" alt="{main['titre']}" loading="eager" style="width:calc(100% + 72px);margin:-32px -36px 20px;height:240px;object-fit:cover;display:block">
        <span class="cat cat--{main['categorie']}">{_cat_up(main['categorie'])}</span>
        <h2 class="title-xl">{main['titre']}</h2>
        <p class="excerpt">{resume}</p>
        <div class="meta">
          <span class="meta__src">{main['nb_sources']} sources</span>
          <span class="meta__sep">·</span><span>{main['date']}</span>
          <span class="meta__sep">·</span><span>Protocole v1.1</span>
          <span class="meta__push"></span>
        </div>
        <p class="ai-badge">Rédigé par IA · Protocole Les Faits v1.1</p>
      </a>
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

{_build_newsletter_section()}

{_build_footer()}
{_DARK_MODE_JS}
{_ANALYTICS_JS}
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

# Affichage MAJUSCULES avec accents (les slugs n'en ont pas : SOCIETE ≠ SOCIÉTÉ)
CAT_UPPER = {c: l.upper() for c, l in CAT_LABELS.items()}


def _cat_up(c: str) -> str:
    return CAT_UPPER.get(c, c.upper())

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


def build_sitemap(articles: list):
    """Génère sitemap.xml dynamique avec tous les articles."""
    today = datetime.now().strftime("%Y-%m-%d")
    static_urls = [
        (f"{BASE_URL}/", "1.0", "daily"),
        (f"{BASE_URL}/archive.html", "0.8", "daily"),
        (f"{BASE_URL}/methode.html", "0.6", "monthly"),
        (f"{BASE_URL}/a-propos.html", "0.5", "monthly"),
        (f"{BASE_URL}/mentions-legales.html", "0.3", "yearly"),
        (f"{BASE_URL}/cgu.html", "0.3", "yearly"),
        (f"{BASE_URL}/confidentialite.html", "0.3", "yearly"),
        (f"{BASE_URL}/contact.html", "0.4", "monthly"),
        (f"{BASE_URL}/corrections.html", "0.4", "weekly"),
        (f"{BASE_URL}/recherche.html", "0.3", "monthly"),
    ]
    for cat in ("societe", "science", "economie", "tech", "sante", "environnement"):
        static_urls.append((f"{BASE_URL}/categories/{cat}.html", "0.7", "daily"))

    urls = "\n".join(
        f"  <url><loc>{loc}</loc><lastmod>{today}</lastmod><changefreq>{freq}</changefreq><priority>{prio}</priority></url>"
        for loc, prio, freq in static_urls
    )
    art_urls = "\n".join(
        f"  <url><loc>{BASE_URL}/articles/{a['slug']}.html</loc><lastmod>{today}</lastmod><changefreq>monthly</changefreq><priority>0.9</priority></url>"
        for a in articles
    )
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
{urls}
{art_urls}
</urlset>"""
    (ROOT / "sitemap.xml").write_text(xml, encoding="utf-8")
    # Mettre à jour robots.txt
    (ROOT / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\n\nSitemap: {BASE_URL}/sitemap.xml\n",
        encoding="utf-8"
    )
    print(f"  ✓ sitemap.xml généré ({len(articles)} articles) + robots.txt")


def build_feed_xml(articles: list):
    """Génère feed.xml (RSS 2.0) pour les 20 derniers articles."""
    base = BASE_URL
    now  = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000")

    def escape(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    items = []
    for a in articles[:20]:
        slug    = a["slug"]
        titre   = escape(a["titre"])
        resume  = escape(" ".join(a["resume"]) if isinstance(a.get("resume"), list) else a.get("resume", ""))
        cat     = escape(a.get("categorie", ""))
        url     = f"{base}/articles/{slug}.html"
        img     = f"{base}/assets/images/{slug}.jpg"
        # date RFC-822 approximative (on utilise now pour les anciens articles sans timezone)
        items.append(f"""  <item>
    <title>{titre}</title>
    <link>{url}</link>
    <guid isPermaLink="true">{url}</guid>
    <description>{resume}</description>
    <category>{cat}</category>
    <enclosure url="{img}" type="image/jpeg" length="0"/>
    <pubDate>{now}</pubDate>
  </item>""")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
  <title>Les Faits</title>
  <link>{base}/</link>
  <description>Journal numérique français rédigé par IA. Juste les faits. Aucun parti pris.</description>
  <language>fr</language>
  <lastBuildDate>{now}</lastBuildDate>
  <atom:link href="{base}/feed.xml" rel="self" type="application/rss+xml"/>
  <image>
    <url>{base}/assets/images/og-default.jpg</url>
    <title>Les Faits</title>
    <link>{base}/</link>
  </image>
{chr(10).join(items)}
</channel>
</rss>"""
    (ROOT / "feed.xml").write_text(xml, encoding="utf-8")
    print(f"  ✓ feed.xml généré ({min(len(articles),20)} items)")


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
        <a class="card3" href="articles/{a['slug']}.html">
          <img class="card3__img" src="assets/images/{a['slug']}.jpg" alt="{_esc(a['titre'])}" loading="lazy">
          <div class="card3__body">
            <span class="cat cat--{cat}">{label.upper()}</span>
            <h3 class="title-sm">{_esc(a['titre'])}</h3>
            <div class="meta" style="margin-top:10px">
              <span class="meta__src">{a['nb_sources']} sources</span>
              <span class="meta__sep">·</span><span>{a['date']}</span>
            </div>
          </div>
        </a>""" for a in arts)
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
          <a href="/" style="display:inline-block;padding:10px 24px;background:var(--blue);
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
<html lang="fr" data-theme="">
<head>
  <meta charset="UTF-8"/>
  {CSP_META}
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <meta name="description" content="Les Faits — Rubrique {label}. Juste les faits. Aucun parti pris."/>
  <link rel="alternate" type="application/rss+xml" title="Les Faits — RSS" href="/feed.xml"/>
  <title>{label} — Les Faits</title>
  <base href="/"/>
  <link rel="stylesheet" href="/src/style.css"/>
  {FAVICON_LINKS}
  {_DARK_INIT_HEAD}
</head>
<body>
{BURGER_HTML}
<header class="header">
  <div class="header__inner">
    <a href="index.html" class="brand">
      {BRAND_ICON}<div class="brand__logotype"><span class="fact">les</span><span class="uel">faits</span></div>
    </a>
    <div class="header__search">
      <input type="search" class="header__search-input" placeholder="Rechercher…" autocomplete="off" onkeydown="if(event.key==='Enter'&&this.value.trim())window.location=(document.querySelector('base').href)+'recherche.html?q='+encodeURIComponent(this.value.trim())"/>
    </div>
    {HEADER_NAV_DESKTOP}
    {DARK_TOGGLE}
    {BURGER_BTN}
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

{_build_newsletter_section()}

{_build_footer()}
{_DARK_MODE_JS}
{_ANALYTICS_JS}
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


def build_archive_page():
    """Génère archive.html — liste complète des articles groupés par mois."""
    articles = load_index()
    if not articles:
        return

    CAT_LABELS = {
        "science": "Science", "economie": "Économie", "tech": "Tech",
        "sante": "Santé", "environnement": "Environnement", "societe": "Société",
    }

    # Grouper par mois (clé : "juin 2026")
    from collections import defaultdict
    par_mois = defaultdict(list)
    for a in articles:
        parts = a.get("date", "").split()
        key = f"{parts[1]} {parts[2].rstrip(',')}" if len(parts) >= 3 else "Inconnu"
        par_mois[key].append(a)

    # Ordre chronologique inverse des mois
    def _mois_sort(k):
        MOIS = ["janvier","février","mars","avril","mai","juin",
                "juillet","août","septembre","octobre","novembre","décembre"]
        parts = k.split()
        try:
            return int(parts[1]) * 100 + (MOIS.index(parts[0]) + 1)
        except Exception:
            return 0

    mois_tries = sorted(par_mois.keys(), key=_mois_sort, reverse=True)

    sections = ""
    for mois in mois_tries:
        arts = par_mois[mois]
        rows = ""
        for a in arts:
            cat = a.get("categorie", "societe")
            label = CAT_LABELS.get(cat, cat.capitalize())
            resume = a.get("resume", "")
            if isinstance(resume, list):
                resume = resume[0] if resume else ""
            img_src = f"assets/images/{a['slug']}.jpg"
            rows += f"""
    <a class="archive-row" href="articles/{a['slug']}.html" style="display:grid;grid-template-columns:80px 1fr;gap:12px 20px;padding:16px 0;border-bottom:1px solid var(--border);align-items:start;text-decoration:none;color:inherit">
      <img src="{img_src}" alt="{_esc(a['titre'])}" style="width:80px;height:54px;object-fit:cover;border-radius:4px;background:var(--light)" loading="lazy" onerror="this.style.display='none'"/>
      <div>
        <span class="cat cat--{cat}" style="display:inline-block;font-size:10px;font-weight:700;letter-spacing:.06em;margin-bottom:4px">{label.upper()}</span>
        <div style="font-weight:600;color:var(--ink);line-height:1.4;font-size:1rem">{_esc(a['titre'])}</div>
        <p style="margin:4px 0 0;font-size:.85rem;color:var(--muted);line-height:1.5">{_esc(resume[:120])}{'…' if len(resume)>120 else ''}</p>
        <span style="font-size:.75rem;color:var(--muted);margin-top:4px;display:block">{a.get('date','').split(',')[0]} · {a.get('nb_sources',0)} sources</span>
      </div>
    </a>"""

        sections += f"""
  <section style="margin-bottom:48px">
    <h2 style="font-size:.75rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--blue);padding-bottom:8px;margin-bottom:0">{mois.capitalize()} · {len(arts)} article{"s" if len(arts)>1 else ""}</h2>
    {rows}
  </section>"""

    html = f"""<!DOCTYPE html>
<html lang="fr" data-theme="">
<head>
  <meta charset="UTF-8"/>
  {CSP_META}
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <meta name="description" content="Tous les articles publiés par Les Faits — journal numérique français rédigé par IA."/>
  <meta property="og:title" content="Tous les articles — Les Faits"/>
  <meta property="og:description" content="Tous les articles publiés par Les Faits — journal numérique français rédigé par IA."/>
  <meta property="og:type" content="website"/>
  <meta property="og:url" content="https://lesfaits.info/archive.html"/>
  <meta property="og:image" content="https://lesfaits.info/assets/images/og-default.jpg"/>
  <meta name="twitter:card" content="summary_large_image"/>
  <meta name="twitter:image" content="https://lesfaits.info/assets/images/og-default.jpg"/>
  <link rel="canonical" href="https://lesfaits.info/archive.html"/>
  <title>Tous les articles — Les Faits</title>
  <base href="/"/>
  <link rel="stylesheet" href="/src/style.css"/>
  {FAVICON_LINKS}
  <script>(function(){{var s=localStorage.getItem('theme'),d=s==='dark'||(s===null&&window.matchMedia('(prefers-color-scheme:dark)').matches);document.documentElement.setAttribute('data-theme',d?'dark':'light');}})();</script>
</head>
<body>
{BURGER_HTML}
<header class="header">
  <div class="header__inner">
    <a href="index.html" class="brand">{BRAND_ICON}<div class="brand__logotype"><span class="fact">les</span><span class="uel">faits</span></div></a>
    <div class="header__search">
      <input type="search" class="header__search-input" placeholder="Rechercher…" autocomplete="off" onkeydown="if(event.key==='Enter'&&this.value.trim())window.location=(document.querySelector('base').href)+'recherche.html?q='+encodeURIComponent(this.value.trim())"/>
    </div>
    {HEADER_NAV_DESKTOP}
    <button class="dark-toggle" id="dark-toggle" aria-label="Mode sombre" title="Mode sombre">🌙</button>
    <button class="burger" id="burger" aria-label="Menu" onclick="toggleMenu()"><span></span><span></span><span></span></button>
  </div>
</header>

<main class="wrap" style="max-width:860px;margin:48px auto;padding:0 20px 80px">
  <nav aria-label="Fil d'Ariane" style="font-size:13px;color:var(--muted);margin-bottom:32px">
    <a href="index.html" style="color:var(--muted)">Accueil</a>
    <span style="margin:0 6px">›</span>
    <span>Tous les articles</span>
  </nav>
  <h1 style="font-family:var(--font-serif,Georgia,serif);font-size:2rem;margin-bottom:4px">Tous les articles</h1>
  <p style="color:var(--muted);font-size:14px;margin-bottom:48px">{len(articles)} articles publiés</p>
  {sections}
  <div style="text-align:center;margin-top:8px">
    <button id="archive-more" type="button" style="display:none;padding:12px 32px;background:var(--blue);color:#fff;border:none;border-radius:4px;font-weight:600;font-size:.95rem;cursor:pointer">Voir plus d'articles</button>
  </div>
  <script>
  (function(){{
    var PAGE=40, rows=Array.prototype.slice.call(document.querySelectorAll('.archive-row')), shown=PAGE;
    var btn=document.getElementById('archive-more');
    function apply(){{
      rows.forEach(function(r,i){{r.style.display=i<shown?'grid':'none';}});
      document.querySelectorAll('main section').forEach(function(s){{
        var srows=s.querySelectorAll('.archive-row'),vis=false;
        for(var k=0;k<srows.length;k++){{if(srows[k].style.display!=='none'){{vis=true;break;}}}}
        s.style.display=vis?'':'none';
      }});
      btn.style.display=shown<rows.length?'inline-block':'none';
      if(shown<rows.length)btn.textContent='Voir plus d'articles ('+(rows.length-shown)+' restants)';
    }}
    if(rows.length>PAGE){{btn.addEventListener('click',function(){{shown+=PAGE;apply();}});apply();}}
  }})();
  </script>
</main>

{_build_newsletter_section()}

{_build_footer()}
{_DARK_MODE_JS}
{_ANALYTICS_JS}
</body>
</html>"""

    ROOT = Path(__file__).parent.parent
    (ROOT / "archive.html").write_text(html, encoding="utf-8")
    print(f"  ✓ archive.html mis à jour ({len(articles)} articles)")

def build_favoris_page():
    """Génère favoris.html — les favoris étant stockés en localStorage (par
    navigateur, sans compte utilisateur), la page ne peut pas être pré-rendue
    côté serveur : elle charge data/articles.json et filtre côté client."""
    CAT_UPPER_JS = json.dumps(CAT_UPPER, ensure_ascii=False)
    html = f"""<!DOCTYPE html>
<html lang="fr" data-theme="">
<head>
  <meta charset="UTF-8"/>
  {CSP_META}
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <meta name="description" content="Vos articles favoris sur Les Faits — sauvegardés localement dans votre navigateur."/>
  <meta name="robots" content="noindex,follow"/>
  <meta property="og:title" content="Mes favoris — Les Faits"/>
  <meta property="og:description" content="Vos articles favoris sur Les Faits."/>
  <meta property="og:type" content="website"/>
  <meta property="og:url" content="https://lesfaits.info/favoris.html"/>
  <meta property="og:image" content="https://lesfaits.info/assets/images/og-default.jpg"/>
  <meta name="twitter:card" content="summary_large_image"/>
  <meta name="twitter:image" content="https://lesfaits.info/assets/images/og-default.jpg"/>
  <link rel="canonical" href="https://lesfaits.info/favoris.html"/>
  <title>Mes favoris — Les Faits</title>
  <base href="/"/>
  <link rel="stylesheet" href="/src/style.css"/>
  {FAVICON_LINKS}
  {_DARK_INIT_HEAD}
</head>
<body>
{BURGER_HTML}
<header class="header">
  <div class="header__inner">
    <a href="index.html" class="brand">{BRAND_ICON}<div class="brand__logotype"><span class="fact">les</span><span class="uel">faits</span></div></a>
    <div class="header__search">
      <input type="search" class="header__search-input" placeholder="Rechercher…" autocomplete="off" onkeydown="if(event.key==='Enter'&&this.value.trim())window.location=(document.querySelector('base').href)+'recherche.html?q='+encodeURIComponent(this.value.trim())"/>
    </div>
    {HEADER_NAV_DESKTOP}
    {DARK_TOGGLE}
    {BURGER_BTN}
  </div>
</header>

<main class="wrap" style="max-width:860px;margin:48px auto;padding:0 20px 80px">
  <nav aria-label="Fil d'Ariane" style="font-size:13px;color:var(--muted);margin-bottom:32px">
    <a href="index.html" style="color:var(--muted)">Accueil</a>
    <span style="margin:0 6px">›</span>
    <span>Mes favoris</span>
  </nav>
  <h1 style="font-family:var(--font-serif,Georgia,serif);font-size:2rem;margin-bottom:4px">Mes favoris</h1>
  <p id="favoris-count" style="color:var(--muted);font-size:14px;margin-bottom:48px">Chargement…</p>
  <div id="favoris-list"></div>
  <div id="favoris-empty" style="display:none;text-align:center;padding:48px 0;color:var(--muted)">
    <p style="font-size:1rem;margin-bottom:8px">Vous n'avez encore aucun favori.</p>
    <p style="font-size:.9rem">Cliquez sur Favoris en bas d'un article pour l'ajouter ici — vos favoris sont enregistrés dans ce navigateur.</p>
  </div>
</main>

{_build_footer()}
{_DARK_MODE_JS}
{_ANALYTICS_JS}
<script>
(function(){{
  var favs = JSON.parse(localStorage.getItem('lesfaits_favs')||'[]');
  var countEl = document.getElementById('favoris-count');
  var listEl = document.getElementById('favoris-list');
  var emptyEl = document.getElementById('favoris-empty');
  if(!favs.length){{
    countEl.textContent = '0 article enregistré';
    emptyEl.style.display = 'block';
    return;
  }}
  fetch('data/articles.json').then(function(r){{return r.json();}}).then(function(articles){{
    var bySlug = {{}};
    articles.forEach(function(a){{bySlug[a.slug]=a;}});
    var found = favs.map(function(s){{return bySlug[s];}}).filter(Boolean);
    countEl.textContent = found.length + ' article' + (found.length>1?'s':'') + ' enregistré' + (found.length>1?'s':'');
    if(!found.length){{emptyEl.style.display='block';return;}}
    listEl.innerHTML = found.map(function(a){{
      var resume = Array.isArray(a.resume) ? (a.resume[0]||'') : (a.resume||'');
      var img = 'assets/images/'+a.slug+'.jpg';
      return '<a class="archive-row" href="articles/'+a.slug+'.html" style="display:grid;grid-template-columns:80px 1fr;gap:12px 20px;padding:16px 0;border-bottom:1px solid var(--border);align-items:start;text-decoration:none;color:inherit">'
        +'<img src="'+img+'" alt="" style="width:80px;height:54px;object-fit:cover;border-radius:4px;background:var(--light)" loading="lazy" onerror="this.style.display=\\'none\\'"/>'
        +'<div><span class="cat cat--'+a.categorie+'" style="display:inline-block;font-size:10px;font-weight:700;letter-spacing:.06em;margin-bottom:4px">'+_cat_up_js(a.categorie)+'</span>'
        +'<div style="font-weight:600;color:var(--ink);line-height:1.4;font-size:1rem">'+escapeHtml(a.titre)+'</div>'
        +'<p style="margin:4px 0 0;font-size:.85rem;color:var(--muted);line-height:1.5">'+escapeHtml(resume.slice(0,120))+(resume.length>120?'…':'')+'</p>'
        +'<span style="font-size:.75rem;color:var(--muted);margin-top:4px;display:block">'+(a.date||'').split(',')[0]+' · '+(a.nb_sources||0)+' sources</span>'
        +'</div></a>';
    }}).join('');
  }});
  function escapeHtml(s){{return String(s).replace(/[&<>"']/g,function(c){{return {{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c];}});}}
  function _cat_up_js(c){{var m={CAT_UPPER_JS};return (m[c]||c).toUpperCase();}}
}})();
</script>
</body>
</html>"""
    ROOT = Path(__file__).parent.parent
    (ROOT / "favoris.html").write_text(html, encoding="utf-8")
    print("  ✓ favoris.html généré")


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
        # Suivi fiabilité : conforme_du_premier_coup / corrige_automatiquement /
        # non_verifie / erreur_verification (jamais a_corriger_manuellement ici)
        "statut_verification": art.get("statut_verification", "non_verifie"),
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

    # Classification déterministe ACTU / DOSSIER / REJETE (avant tout appel Groq)
    article_type = classifier_type_article(item["title"], item.get("content", ""))
    if article_type == "rejete":
        print(f"  [REJET DOSSIER] Listicle, lifestyle ou portrait polémique détecté : {item['title'][:55]}")
        return False

    # Scraping du contenu complet
    full_content = ""
    if item.get("url"):
        full_content = fetch_full_content(item["url"])
    content = full_content if len(full_content) > 500 else item["content"]

    # Recherche de sources corroborantes : DuckDuckGo + PubMed
    extra = duckduckgo_search(item["title"] + " " + cat, max_results=8)
    pubmed = pubmed_search(item["title"], max_results=4)
    # Fusionner sans doublons
    seen_urls = {s["url"] for s in extra}
    for p in pubmed:
        if p["url"] not in seen_urls:
            extra.append(p)
            seen_urls.add(p["url"])

    # Enrichissement : remplacer les snippets DDG (~200 car.) par le contenu
    # complet scrapé pour les sources non protégées par droits voisins.
    for src in extra:
        if not _est_presse_protegee(src["url"]):
            full = fetch_full_content(src["url"])
            if len(full) > 500:
                src["snippet"] = full[:8000]

    # Bloquer si moins de 5 sources réelles trouvées AVANT même de générer.
    # Seuil relevé de 3 à 5 : avec seulement 3-4 sources, le correcteur (passe 3
    # du fact-checker Anthropic) manque de matière pour remplacer une redondance
    # par un fait distinct sans inventer de cadrage — ce qui déclenchait de
    # nouveaux signalements (jugement de valeur, cadrage emprunté) à chaque
    # tentative de correction. Plus de sources en amont = marge réelle pour
    # une correction qui enrichit au lieu d'éditorialiser.
    specific_sources = [s for s in extra
                        if len(urlparse(s["url"]).path.rstrip("/")) > 5
                        and not _est_source_exclue(s["url"])]
    if len(specific_sources) < 5:
        print(f"  [REJET] Seulement {len(specific_sources)} source(s) — minimum 5 requis (DDG+PubMed)")
        return False

    type_label = {"actu": "ACTU", "dossier_portrait": "DOSSIER/portrait",
                  "dossier_science": "DOSSIER/science"}.get(article_type, article_type)
    print(f"  → Génération [{type_label}] : {item['title'][:50]} [{len(specific_sources)} sources réelles]")

    if dry_run:
        print(f"     (dry-run)")
        return False

    try:
        art = generate(content, cat, extra_sources=extra, rss_url=item.get("url"),
                       article_type=article_type)

        # Compteur de relances Groq pour cet article — sert de circuit-breaker
        # (voir rejet précoce plus bas).
        nb_garde_retries = 0

        # ── Garde-fous 1/3/4 : une SEULE relance corrective combinée ──────────
        # Les trois contrôles (attributions fantômes, résumé qui paraphrase le
        # corps, répétitions intra-article) sont déterministes et indépendants :
        # les évaluer d'abord tous puis relancer une seule fois avec les retours
        # combinés coûte 1 appel Groq au lieu de 3 — les relances en cascade
        # épuisaient le quota des 3 clés dès le 5e sujet du créneau.
        fantomes    = attributions_fantomes(art)
        repetitions = resume_repete_corps(art)
        intra       = faits_repetitifs(art)
        if fantomes or repetitions or intra:
            details = []
            if fantomes:
                details.append(f"{len(fantomes)} attribution(s) hors sources")
            if repetitions:
                details.append(f"{len(repetitions)} phrase(s) du résumé quasi identiques au corps")
            if intra:
                details.append(f"{len(intra)} répétition(s) intra-article")
            print(f"     [GARDE] {' + '.join(details)} — relance corrective unique…")
            art = generate(content, cat, extra_sources=extra, rss_url=item.get("url"),
                           retry_feedback=fantomes or None,
                           repetition_feedback=repetitions or None,
                           intra_feedback=intra or None,
                           article_type=article_type,
                           previous_article=art)
            if not isinstance(art, dict):
                art = {}
            if fantomes:
                nb_garde_retries += 1
            # Re-vérifier les attributions après TOUTE relance : une relance
            # déclenchée par un défaut de style peut introduire de nouvelles
            # attributions hors sources.
            fantomes = attributions_fantomes(art)
            if fantomes:
                # Récupération déterministe : supprimer les attributions invalides
                # plutôt que rejeter — Anthropic jugera la qualité finale.
                art_stripped = strip_attributions_invalides(art)
                fantomes_post_strip = attributions_fantomes(art_stripped)
                if not fantomes_post_strip:
                    art = art_stripped
                    print(f"     [RÉCUPÉRATION] {len(fantomes)} attribution(s) non sourcée(s) "
                          f"supprimées du texte — passage à Anthropic")
                else:
                    print(f"     [REJET QUALITÉ] Attributions toujours hors sources après relance "
                          f"({', '.join(fantomes[:3])}…) — rejet définitif")
                    return False
            # Défauts de style (non bloquants) : simple avertissement si persistants,
            # Anthropic jugera la qualité finale.
            if resume_repete_corps(art):
                print(f"     [AVERTISSEMENT] Résumé toujours proche du corps après relance — passé à Anthropic")
            if faits_repetitifs(art):
                print(f"     [AVERTISSEMENT] Répétitions intra-article persistantes après relance — passé à Anthropic")

        # ── Garde-fou Dossier Science : formulations assertives interdites ─────
        if article_type == "dossier_science":
            corps_texte = " ".join(art.get("corps", {}).values())
            assertif = _ASSERTIF_SCIENCE_RE.search(corps_texte)
            if assertif:
                print(f"     [REJET DOSSIER] Formulation assertive dans dossier science : "
                      f"'{assertif.group()[:60]}' — rejet définitif")
                return False

        # ── Garde-fou Dossier Portrait : Liste B dans le texte généré ─────────
        if article_type == "dossier_portrait":
            corps_texte = " ".join(art.get("corps", {}).values())
            liste_b = _LISTE_B_RE.search(corps_texte)
            if liste_b:
                print(f"     [REJET DOSSIER] Sujet clivant (Liste B) dans portrait généré : "
                      f"'{liste_b.group()[:60]}' — rejet définitif")
                return False

        # ── Circuit-breaker budget : rejet précoce si ≥ 2 relances de garde-fou ──
        # Un article qui a déclenché 2+ relances Groq est fragile structurellement
        # (mauvais sourcing ou génération instable). Continuer avec les 5 appels
        # Anthropic de vérification sur un tel article gaspille le quota du créneau
        # au détriment des sujets suivants — surtout si le 1er sujet est mal sourcé
        # par hasard et que les 9 suivants sont valides. Rejet propre = budget
        # équitablement réparti entre tous les sujets sélectionnés.
        if nb_garde_retries >= 2:
            print(f"     [REJET PRÉCOCE] {nb_garde_retries} relances garde-fou — article fragile, "
                  f"quota Anthropic préservé pour les sujets suivants")
            return False

        # ── Garde-fou 2a : check déterministe avant appels LLM coûteux ──────
        rejete, raison_det = _est_rejete_sensible_deterministe(art)
        if rejete:
            print(f"     [REJET SENSIBLE] {raison_det} — rejet définitif (déterministe)")
            return False

        # ── Garde-fou 2b : sujet sanitaire sensible sans source officielle ──
        if sujet_sante_sans_source_officielle(art):
            print(f"     [REJET SENSIBLE] Sujet santé sensible sans source officielle — rejet définitif")
            return False

        total_chars = sum(len(art["corps"].get(k, "")) for k in ["faits", "contexte", "nuances"])

        if len(art.get("sources", [])) < 3:
            print(f"     [REJET] Seulement {len(art.get('sources',[]))} source(s) après vérification — min 3")
            return False
        if total_chars < 600:
            print(f"     [REJET] Corps trop court ({total_chars} chars)")
            return False

        # ── Passes 2/3 : fact-check + correction automatique (Anthropic) ──
        art, statut_verif = verifier_article(art, article_type=article_type)
        if statut_verif in ("rejete_sensible", "rejete_qualite"):
            # Messages déjà affichés dans verifier_article
            return False
        art["statut_verification"] = statut_verif

        # La catégorie publiée est TOUJOURS celle du classifieur déterministe
        # (detect_category, lexique v2) — jamais celle choisie par le LLM, dont
        # la liste autorisée dans le prompt était incomplète (pas de "sante")
        # et dont le choix contredisait régulièrement le lexique.
        art["categorie"] = cat

        # Le badge public reflète le nombre de sources réellement citées
        # APRÈS correction, jamais le nombre fourni en entrée
        art["nb_sources"] = len(art.get("sources", []))

        try:
            html = build_article_html(art, date_pub)
        except Exception as _html_err:
            import traceback as _tb3
            print(f"     [DEBUG strftime] TRACEBACK COMPLET:")
            print(_tb3.format_exc())
            raise

        # Fix 1 — sync nb_sources avec les vrais <li> rendus dans le HTML
        sources_block = re.search(r'<(?:div|section) class="sources[^"]*".*?</(?:div|section)>', html, re.DOTALL)
        real_nb = len(re.findall(r'<li>', sources_block.group())) if sources_block else 0
        if real_nb != art.get("nb_sources", 0):
            # Patcher le HTML inline pour que le chiffre affiché soit juste
            html = re.sub(
                rf'\b{art["nb_sources"]}\s+sources?\s+vérifi',
                f'{real_nb} sources vérifi', html
            )
            html = re.sub(
                rf'<span[^>]*>\s*{art["nb_sources"]}\s+sources?\s*</span>',
                f'<span style="color:var(--blue);font-weight:600">{real_nb} sources</span>',
                html
            )
            art["nb_sources"] = real_nb

        (ARTICLES / f"{art['slug']}.html").write_text(html, encoding="utf-8")
        save_to_index(art, date_pub)
        new_pub.add(item["id"])
        print(f"     ✓ {art['slug']}.html ({art['nb_sources']} src, {total_chars} chars)")
        return True

    except ValueError as e:
        print(f"     [REJET] {e}")
    except json.JSONDecodeError:
        print(f"     [ERREUR JSON] Réponse Groq non parseable")
    except Exception as e:
        import traceback as _tb
        err = str(e)
        if "401" in err or "invalid_api_key" in err.lower() or "authentication" in err.lower():
            print(f"     [ERREUR GROQ] Clé API invalide ou expirée — vérifier GROQ_API_KEY dans les secrets GitHub")
        elif "429" in err or "rate_limit" in err.lower():
            print(f"     [ERREUR GROQ] Rate limit atteint — quota journalier/mensuel Groq épuisé")
        elif "model" in err.lower() and ("not found" in err.lower() or "deprecated" in err.lower()):
            print(f"     [ERREUR GROQ] Modèle llama-3.3-70b-versatile indisponible : {err}")
        else:
            import traceback as _tb2
            tb_str = _tb2.format_exc()
            print(f"     [ERREUR] {type(e).__name__}: {err}")
            print(tb_str)
    return False


def run(dry_run=False, text_input=None, nb_max=10):
    published = load_published()
    new_pub   = set()
    MOIS = ["janvier","février","mars","avril","mai","juin",
            "juillet","août","septembre","octobre","novembre","décembre"]
    now      = datetime.now()
    # Heure réelle de génération (Paris, via TZ=Europe/Paris du runner) — pas
    # un créneau fixe 07h00/18h00, qui mentait sur l'heure de publication
    # effective quand un run était retardé ou ralenti par les rate limits.
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
        # Fenêtre anti-doublon : ~14 jours d'articles (10/jour max × 14)
        published_topics = {a.get("titre", "") for a in load_index()[:140]}
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
        # Classifier les candidats avant affichage (sans Groq, purement déterministe)
        for c in tous_candidats:
            c["_type"] = classifier_type_article(c["title"], c.get("content", ""))

        print(f"{'─'*78}")
        print(f"  {'SCORE':>5}  {'TYPE':<18}  {'CATÉGORIE':<12}  TITRE")
        print(f"{'─'*78}")
        for c in tous_candidats[:20]:
            t = {"actu": "ACTU", "dossier_portrait": "DOSSIER/portrait",
                 "dossier_science": "DOSSIER/science", "rejete": "REJETÉ"}.get(c["_type"], c["_type"])
            print(f"  {c['_score']:>5}  {t:<18}  {c.get('_cat','?'):<12}  {c['title'][:40]}")
        print(f"{'─'*78}")

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

    _init_used_images()

    if not GROQ_KEY:
        print("ERREUR : GROQ_API_KEY manquant dans .env / secrets GitHub")
        exit(1)
    active_keys = sum(1 for k in (GROQ_KEY2, GROQ_KEY3) if k)
    if active_keys:
        print(f"[INFO] {active_keys} clé(s) Groq de secours détectée(s) — bascule automatique si rate limit")

    run(dry_run=args.dry_run, text_input=args.text)

