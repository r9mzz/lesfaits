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
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from xml.etree import ElementTree as ET
from urllib.parse import urlparse
import urllib.parse

from groq import Groq
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Vérification éditoriale 3 passes (Groq Llama 3.3) — inactive sans clé Groq
from verification import verifier_article
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

# Modèle de génération — extrait en constante (21/07) pour permettre un test
# comparatif A/B sans dupliquer le pipeline (voir scripts/test_model_compare.py).
# Le comportement par défaut est strictement inchangé.
GROQ_MODEL     = os.getenv("GROQ_MODEL_OVERRIDE", "") or "llama-3.3-70b-versatile"
GROQ_KEY       = os.getenv("GROQ_API_KEY", "")
# Liste dynamique (23/07, Nahil : 23 clés après nettoyage à 1 clé/compte) :
# GROQ_API_KEY_2 à GROQ_API_KEY_N, N ajustable sans toucher au code — il suffit d'ajouter le
# secret GitHub correspondant et de l'exposer dans pipeline.yml. Remplace les
# 7 variables séparées GROQ_KEY2..GROQ_KEY7 codées en dur (devenu intenable
# au-delà de quelques clés).
GROQ_KEYS_SECONDAIRES = [
    v for i in range(2, 41)
    if (v := os.getenv(f"GROQ_API_KEY_{i}", ""))
]
GROQ_ALL_KEYS: list[tuple[str, str]] = (
    ([(GROQ_KEY, "clé 1")] if GROQ_KEY else [])
    + [(k, f"clé {i+2}") for i, k in enumerate(GROQ_KEYS_SECONDAIRES)]
)
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
    # Idées (entretiens/décryptages) et Décodeurs (data-journalisme factuel) :
    # rubriques structurellement alignées avec l'angle éditorial de Les Faits
    # (analyse à charge factuelle précise) mais absentes jusqu'ici du flux —
    # constat 26/07, Nahil : le flux généraliste Monde/Parisien est surtout
    # composé de guerre/sport-spectacle/fait-divers/people, hors périmètre
    # par choix éditorial ; ces deux rubriques sont le contenu qui correspond
    # réellement à ce qu'on publie.
    {"name": "Le Monde Idées",       "url": "https://www.lemonde.fr/idees/rss_full.xml"},
    {"name": "Le Monde Décodeurs",   "url": "https://www.lemonde.fr/les-decodeurs/rss_full.xml"},
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
    # Sécurité sanitaire
    {"name": "ANSES",                "url": "https://www.anses.fr/fr/flux-actualites.rss"},
    # ── Ajouts du 19/07 (Nahil : besoin de plus de matière) ──
    # fetch_rss ignore déjà silencieusement un flux mort (voir gestion 415/406
    # existante) — un flux qui ne répond pas ne casse rien, il rapporte juste
    # 0 sujet. Confiance haute (format standard, documenté) sauf mention contraire.
    {"name": "The Conversation France", "url": "https://theconversation.com/fr/articles.atom"},
    {"name": "RFI",                  "url": "https://www.rfi.fr/fr/rss"},
    {"name": "Numerama",             "url": "https://www.numerama.com/feed/"},
    {"name": "Novethic",             "url": "https://www.novethic.fr/rss/toute-l-actualite.xml"},
    # Institutionnels à forte valeur (source PRIMAIRE directe) mais URL non
    # vérifiable depuis cet environnement (réseau restreint) — à confirmer
    # dans les logs du prochain run réel (GitHub Actions) : chercher
    # "[COLLECTE RSS]" et le nombre d'items par flux.
    {"name": "Légifrance JORF",      "url": "https://www.legifrance.gouv.fr/rss/jorf.xml"},
    {"name": "Santé Publique France", "url": "https://www.santepubliquefrance.fr/rss"},
    {"name": "INSEE Informations rapides", "url": "https://www.insee.fr/fr/rss"},
    # ── Deuxième vague (19/07, suite) : couvrir les domaines déjà en liste
    # blanche primaire/secondaire mais qui n'avaient encore AUCUN flux RSS
    # configuré — le levier le plus direct pour plus de matière sans rien
    # assouplir. Mêmes réserves de confiance qu'au-dessus (réseau sandbox
    # bloqué, à confirmer au run réel via "[COLLECTE RSS]").
    # -- Presse déjà secondaire, RSS manquant --
    {"name": "Les Échos",            "url": "https://www.lesechos.fr/rss/rss_une.xml"},
    # ancienne URL "www.leparisien.fr/rss.xml" en 404 depuis leur migration
    # d'infra RSS vers un sous-domaine dédié (constat 26/07) — nouveau flux
    # général confirmé par recherche externe (feeds.leparisien.fr/leparisien/rss).
    {"name": "Le Parisien",          "url": "https://feeds.leparisien.fr/leparisien/rss"},
    {"name": "L'Express",            "url": "https://www.lexpress.fr/arc/outboundfeeds/rss/?outputType=xml"},
    {"name": "Ouest-France",         "url": "https://www.ouest-france.fr/rss-en-continu.xml"},
    {"name": "La Croix",             "url": "https://www.la-croix.com/rss.xml"},
    {"name": "France 24",            "url": "https://www.france24.com/fr/rss"},
    {"name": "Mediapart",            "url": "https://www.mediapart.fr/articles/feed"},
    {"name": "20 Minutes",           "url": "https://www.20minutes.fr/rss/une.xml"},
    # -- Institutions déjà primaires, RSS manquant --
    {"name": "ADEME",                "url": "https://www.ademe.fr/rss/"},
    {"name": "CEA",                  "url": "https://www.cea.fr/rss"},
    {"name": "INRAE",                "url": "https://www.inrae.fr/rss.xml"},
    {"name": "Cour des comptes",     "url": "https://www.ccomptes.fr/fr/rss.xml"},
    {"name": "Sénat",                "url": "https://www.senat.fr/rss/actualites.xml"},
    {"name": "Assemblée nationale",  "url": "https://www.assemblee-nationale.fr/dyn/rss/rss_dossiers_legislatifs.xml"},
    {"name": "Banque de France",     "url": "https://www.banque-france.fr/rss.xml"},
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


# Domaines JAMAIS citables comme source journalistique : marchands (fiches
# produit — un livre vendu chez 3 libraires est UNE œuvre, pas 3 sources),
# réseaux sociaux, plateformes d'avis. Le run du 15/07 a publié un article
# citant « Selon Amazon » / « Selon Fnac » / « Selon Payot » — trois fiches
# du même livre comptées comme trois sources distinctes.
_DOMAINES_NON_CITABLES_RE = re.compile(
    r"(?:^|\.)(?:"
    r"amazon\.[a-z.]+|fnac\.(?:com|ch|be)|payot\.ch|cultura\.com|decitre\.fr|"
    r"furet\.com|momox-shop\.fr|rakuten\.(?:com|fr)|cdiscount\.com|ebay\.[a-z.]+|"
    r"leboncoin\.fr|aliexpress\.[a-z.]+|temu\.com|etsy\.com|"
    r"babelio\.com|goodreads\.com|booknode\.com|senscritique\.com|"
    r"facebook\.com|instagram\.com|tiktok\.com|x\.com|twitter\.com|"
    r"pinterest\.[a-z.]+|linkedin\.com|reddit\.com|quora\.com|"
    r"tripadvisor\.[a-z.]+|booking\.com|airbnb\.[a-z.]+|"
    r"lisez\.com|editions-[a-z]+\.(?:fr|com)|hachette\.fr|placedeslibraires\.fr"
    r")$",
    re.IGNORECASE,
)


def _est_source_citables(url: str) -> bool:
    """False si le domaine est marchand/social/avis — jamais citable comme source."""
    host = (urlparse(url).hostname or "").lower()
    return not _DOMAINES_NON_CITABLES_RE.search(host)


# ── Hiérarchie de qualité des sources (liste BLANCHE, pas noire) ─────────────
# primaire   : institutions, gouvernements, revues à comité de lecture —
#              elles PRODUISENT la donnée.
# secondaire : agences de presse et médias de référence — ils VÉRIFIENT.
# tertiaire  : tout le reste (vulgarisation, Wikipédia, blogs) — utilisable
#              en contexte, jamais comme preuve.
# interdite  : marchands/réseaux sociaux (voir _DOMAINES_NON_CITABLES_RE).
_DOMAINES_PRIMAIRES = (
    ".gouv.fr", ".gov", ".europa.eu", ".int", "elysee.fr",
    "assemblee-nationale.fr", "senat.fr", "vie-publique.fr",
    "insee.fr", "banque-france.fr", "has-sante.fr", "anses.fr", "ansm.sante.fr",
    "meteofrance.fr", "ined.fr", "cnrs.fr", "inserm.fr", "inrae.fr",
    "cea.fr", "ademe.fr", "pasteur.fr", "santepubliquefrance.fr",
    "nasa.gov", "esa.int", "cern.ch", "cnes.fr",
    "nature.com", "science.org", "thelancet.com", "nejm.org", "bmj.com",
    "ncbi.nlm.nih.gov", "pubmed.gov", "cell.com", "pnas.org",
    "courdecassation.fr", "conseil-etat.fr", "ccomptes.fr",
)
_DOMAINES_SECONDAIRES = (
    "afp.com", "reuters.com", "apnews.com",
    "lemonde.fr", "lefigaro.fr", "liberation.fr", "lesechos.fr",
    "leparisien.fr", "lepoint.fr", "lexpress.fr", "nouvelobs.com",
    "mediapart.fr", "la-croix.com", "ouest-france.fr", "sudouest.fr", "20minutes.fr",
    "francetvinfo.fr", "franceinfo.fr", "france24.com", "rfi.fr",
    "radiofrance.fr", "europe1.fr",
    "bbc.com", "theguardian.com", "nytimes.com", "washingtonpost.com",
    "letemps.ch", "rts.ch", "lesoir.be", "rtbf.be",
    "theconversation.com", "sciencesetavenir.fr", "pourlascience.fr",
    "numerama.com", "novethic.fr",
)


def qualite_source(url: str) -> str:
    """Classe une URL : primaire / secondaire / tertiaire / interdite."""
    if not url:
        return "tertiaire"
    host = (urlparse(url).hostname or "").lower()
    if _DOMAINES_NON_CITABLES_RE.search(host):
        return "interdite"
    for d in _DOMAINES_PRIMAIRES:
        if host == d.lstrip(".") or host.endswith(d):
            return "primaire"
    for d in _DOMAINES_SECONDAIRES:
        if host == d or host.endswith("." + d):
            return "secondaire"
    return "tertiaire"


def bilan_qualite_sources(sources: list) -> dict:
    """Compte les sources par niveau de qualité (domaines distincts uniquement)."""
    domaines_vus = {"primaire": set(), "secondaire": set(), "tertiaire": set()}
    for s in sources or []:
        url = (s.get("url") if isinstance(s, dict) else str(s)) or ""
        q = qualite_source(url)
        if q == "interdite":
            continue
        host = (urlparse(url).hostname or "").lower().removeprefix("www.")
        if host:
            domaines_vus[q].add(host)
    return {k: len(v) for k, v in domaines_vus.items()}


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
    seen_titles = set()
    results = []

    def _titre_norm(t: str) -> str:
        import unicodedata
        t = unicodedata.normalize("NFD", t.lower())
        t = "".join(c for c in t if unicodedata.category(c) != "Mn")
        mots = re.findall(r"[a-z0-9]{3,}", t)
        return " ".join(sorted(mots)[:8])

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
                    if not _est_source_citables(url):
                        continue
                    # Même œuvre/dépêche sur plusieurs sites = UNE source :
                    # dédupliquer sur le titre normalisé, pas seulement l'URL
                    tn = _titre_norm(r.get("title", ""))
                    if tn and tn in seen_titles:
                        continue
                    seen.add(url)
                    if tn:
                        seen_titles.add(tn)
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
        # Chaque serveur a ses manies : inserm.fr renvoie 415 sans Accept
        # explicite, theconversation.com renvoie 406 si l'Accept ne lui plaît
        # pas, d'autres WAF filtrent sur le User-Agent. Échelle d'essais du
        # plus spécifique au plus permissif.
        accept_rss = ("application/rss+xml, application/atom+xml, "
                      "application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5")
        tentatives = [
            {**HEADERS, "Accept": accept_rss},
            {**HEADERS, "Accept": "*/*"},
            {"User-Agent": "FactuelBot/1.0 (+https://lesfaits.info) RSS reader",
             "Accept": accept_rss},
        ]
        r = None
        derniere = None
        for hdrs in tentatives:
            try:
                r = requests.get(source["url"], headers=hdrs, timeout=12)
                r.raise_for_status()
                break
            except requests.HTTPError as e:
                derniere = e
                r = None
        if r is None:
            raise derniere

        try:
            root = ET.fromstring(r.content)
        except ET.ParseError:
            # Flux mal formé (entité invalide, caractère de contrôle, HTML
            # d'erreur mélangé au XML — cas ANSES) : reparse en mode récupération.
            from lxml import etree as _lxml_etree
            root = _lxml_etree.fromstring(
                r.content, parser=_lxml_etree.XMLParser(recover=True, encoding=r.encoding or "utf-8"))
            if root is None:
                raise ValueError("flux irrécupérable même en mode recover")

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

# TEST 26-28/07 (Nahil, 2 jours) : guerre/faits-divers/politique retirés du
# rejet immédiat pour voir si le prompt strict (charte règles 1-15 +
# garde-fous) suffit à les traiter avec neutralité factuelle sans prendre
# parti, plutôt que de les exclure a priori. La vérification LLM
# (sujet_sensible : mineur impliqué, affaire judiciaire en cours,
# diffamation) continue de s'appliquer indépendamment et rejette toujours
# ce qui l'exige — ce test ne touche qu'au filtre de sujet, pas aux
# garde-fous de sécurité légale. Si le test n'est pas concluant, remettre
# ces mots-clés dans BLACKLIST ci-dessous.
_BLACKLIST_SUSPENDUE_TEST_2607 = [
    "guerre", "conflit armé", "attentat", "terrorisme",
    "fait divers", "meurtre", "accident mortel",
    "sondage d'opinion", "cote de popularité",
    "parti politique", "élection présidentielle",
]

BLACKLIST = [
    # People / opinion
    "célébrité", "scandale people", "vie privée",
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
    r"(?:à partir de|dès|seulement|au prix de|(?:à\s+)?moins de)\s*\d+[.,]?\d*\s*€"
    r"|\d+[.,]\d{2}\s*€\s*(?:chez|sur)\b"
    r"|chez\s+(?:cdiscount|amazon|aliexpress|rakuten|darty|boulanger|leclerc|carrefour|lidl|aldi|action)"
    r"|(?:cdiscount|aliexpress|rakuten)\b"
    r"|^\d+\s+\w+.{0,40}\b(?:lidl|aldi|action|cdiscount|amazon)\b"
    # Bons plans / promos déguisés en article (ex: "le Dell 16 perd 350 euros").
    # Motifs volontairement étroits : "promotion" seul ou "moins cher" seul
    # apparaissent dans de vrais articles (promotion sociale, essence moins
    # chère) — on ne matche que le vocabulaire marketing sans ambiguïté.
    r"|bons? plans?\b|\bpromos?\b|\ben promo\b|ventes? flash|prix cassés?"
    r"|meilleures? offres?|\d+\s*%\s*de\s*r[ée]duction|offre à saisir"
    r"|perd\s+\d+\s*(?:euros|€)"
    # "le Dell 16 Plus chute de 900 €" : même famille que "perd X euros"
    r"|chute\s+de\s+\d+\s*(?:euros|€)|baisse\s+de\s+\d+\s*(?:euros|€)"
    r"|passe\s+(?:à|sous)\s+\d+[.,]?\d*\s*(?:euros|€)"
    r"|rapport qualité[- ]prix|code promo",
    re.IGNORECASE,
)

# Sujets sport-spectacle / lifestyle sans valeur informationnelle vérifiable :
# commentaire de match, mercato, mode, tendances… Le malus (pas un rejet) laisse
# passer un vrai sujet (économie du sport, santé et sport) qui scorerait par
# ailleurs, mais élimine les comptes-rendus et papiers d'ambiance.
_SPORT_LIFESTYLE_RE = re.compile(
    r"\bmercato\b|\btransfert(?:s)? de .{0,30}(?:joueur|club)|équipe de france\b"
    r"|\bbleus?\b.{0,40}\b(?:match|victoire|défaite|qualifi)"
    r"|\b(?:match|mi-temps|penalty|buteur|sélectionneur)\b"
    r"|surpuissant|décisif face à|homme du match"
    r"|\blook\b|\btendance mode\b|\bstreet ?style\b|dress ?code"
    r"|\btouristes?\b.{0,40}\b(?:mode|style|look|chapeau)"
    r"|il ou elle porte|comment s'habiller",
    re.IGNORECASE,
)

# Institutions productrices de données — pour le bonus substance du barème.
# Liste volontairement plus étroite que SOURCES_MAJEURES (qui contient des
# mots ambigus comme "science" ou "nature" matchant n'importe quel texte).
_INSTITUTIONS_RE = re.compile(
    r"\b(?:insee|inserm|cnrs|inrae|anses|ademe|ansm|drees|dares|ined|citepa"
    r"|ocde|oms|onu|unesco|unicef|eurostat|giec|noaa|nasa|esa"
    r"|météo[- ]france|santé publique france|cour des comptes"
    r"|haute autorité de santé|assemblée nationale|sénat|commission européenne"
    r"|banque de france|agence internationale de l'énergie)\b",
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
# Société : plafond légèrement réduit — catégorie fourre-tout où atterrissent
# les papiers d'ambiance ; 3 max par créneau (relevé de 2 le 13/07 après une
# matinée où seulement 9 candidats au total ont passé le filtre RSS et où
# 3 sujets société solides ont été écartés par le quota alors que les autres
# catégories n'avaient qu'un candidat chacune).
QUOTA_PAR_CATEGORIE = {"societe": 3}


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

    # ── BONUS MOTS SOURCE : richesse du contenu brut disponible ─────────────
    # Plus la source est longue, plus l'article généré aura matière à atteindre
    # les seuils de longueur — bonus progressif par tranches.
    _mots_src = len(item["content"].split())
    if _mots_src >= 600:
        score += 15
        reasons.append(f"+15 source riche ≥ 600 mots ({_mots_src} mots)")
    elif _mots_src >= 400:
        score += 10
        reasons.append(f"+10 source moyenne ≥ 400 mots ({_mots_src} mots)")
    elif _mots_src >= 200:
        score += 5
        reasons.append(f"+5 source courte ≥ 200 mots ({_mots_src} mots)")

    # ── BONUS SUBSTANCE : des chiffres ET une institution nommée ────────────
    # C'est le critère qui manquait au barème : un papier d'ambiance long et
    # frais d'un média reconnu scorait mieux qu'une vraie donnée publiée par
    # une institution. Chiffres + source institutionnelle nommée dans le corps
    # = matière factuelle vérifiable.
    debut = text[:1500]
    nb_chiffres = len(re.findall(
        r"\b\d[\d\s,.]*\s*(?:%|millions?|milliards?|€|euros|habitants|tonnes|"
        r"cas\b|décès|hectares|années|km²?|degrés)", debut))
    a_institution = bool(_INSTITUTIONS_RE.search(debut))
    if nb_chiffres >= 2 and a_institution:
        score += 25
        reasons.append(f"+25 substance (chiffres × institution nommée)")
    elif nb_chiffres >= 2:
        score += 10
        reasons.append(f"+10 substance (données chiffrées)")

    # ── MALUS SPORT-SPECTACLE / LIFESTYLE ────────────────────────────────────
    if _SPORT_LIFESTYLE_RE.search(item["title"]):
        score -= 40
        reasons.append("-40 sport-spectacle/lifestyle (titre)")
    elif _SPORT_LIFESTYLE_RE.search(text[:800]):
        score -= 25
        reasons.append("-25 sport-spectacle/lifestyle (contenu)")

    # ── PÉNALITÉ FORMAT CHRONIQUE / LIFESTYLE ───────────────────────────────
    title_lower = item["title"].lower()
    if any(p in title_lower for p in _TITRE_MALUS):
        score -= 20
        reasons.append("-20 titre format guide/conseil")

    # ── PÉNALITÉ RÉCURRENCE ──────────────────────────────────────────────────
    # Comparer les mots significatifs du titre avec les topics déjà publiés.
    # Normalisation par préfixe (8 car., accents retirés) plutôt que mot exact :
    # "néandertaliens" et "néandertalien" (singulier/pluriel, variantes de
    # source) ne partageaient aucun mot identique et laissaient passer un vrai
    # doublon (constat 26/07 — deux articles sur la même découverte de carie
    # néandertalienne, publiés à 5 h d'intervalle).
    def _norm_words(s: str) -> set[str]:
        import unicodedata
        s = unicodedata.normalize("NFD", s)
        s = "".join(c for c in s if unicodedata.category(c) != "Mn")
        return set(w[:8] for w in s.lower().split() if len(w) > 5)

    title_words = _norm_words(item["title"])
    for topic in published_topics:
        topic_words = _norm_words(topic)
        shared = title_words & topic_words
        overlap = len(shared)
        # Un seul mot commun suffit au rejet s'il est long donc très spécifique
        # (ex: "eutrophisation", "guanabara", "immunothérapie", "sublinguale") —
        # c'est le cas de tous les doublons passés au travers de l'ancien seuil.
        rare_match = overlap == 1 and max(len(w) for w in shared) >= 8
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
        if compteur.get(cat, 0) >= QUOTA_PAR_CATEGORIE.get(cat, quota_cat):
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
    "Phrase 1 : ANNONCE le fait principal (qui, quoi) en une accroche synthétique — un SEUL chiffre-clé maximum. Ne livre PAS ici tout le détail chiffré : le décompte complet, les montants, les pourcentages détaillés vont dans 'faits'. Le résumé donne envie de lire 'faits', il ne le remplace pas. Vocabulaire et syntaxe DIFFÉRENTS de 'faits'.",
    "Phrase 2 : l'enjeu essentiel (qui/quand/pourquoi ça compte), avec des mots différents de la section 'contexte' (2 lignes min).",
    "Phrase 3 : nuance, limite ou débat en cours (2 lignes min)."
  ],
  "corps": {
    "faits": "MINIMUM 300 mots. C'est ICI que vit le détail complet, PAS dans le résumé : l'actualité immédiate et TOUTES ses données du jour — chiffres précis, décompositions, montants, dates, acteurs nommés, résultats quantitatifs, déclarations exactes avec attribution. RÈGLE ANTI-REDONDANCE : chaque phrase doit apporter une donnée que le résumé n'a PAS déjà donnée. Si 'faits' ne fait que reformuler le résumé, l'article échoue — développe, chiffre, détaille au-delà de l'accroche. NE JAMAIS inclure d'historique, d'évolution sur plusieurs années ni de comparaisons internationales — cela va exclusivement dans 'contexte'. Attribuer chaque donnée à son institution avec 'Selon [Institution]' ou 'D'après [Institution]'. JAMAIS d'URL dans le texte. Utiliser plusieurs paragraphes.",
    "contexte": "MINIMUM 200 mots. UNIQUEMENT de l'historique et de la mise en perspective DIRECTEMENT liés au sujet PRÉCIS de l'article — pas au thème général. RESTE CENTRÉ : n'élargis pas à des sujets connexes (budget global de l'État, modèle économique d'ensemble, politique générale du secteur) sauf s'ils sont INDISPENSABLES pour comprendre CE fait précis. Mieux vaut un contexte court et pertinent qu'un contexte large et dilué. Évolutions sur 5-10 ans, comparaisons, cadre réglementaire ou scientifique du sujet exact. NE JAMAIS reprendre les faits déjà énoncés dans 'faits'. Chiffres comparatifs obligatoires.",
    "nuances": "MINIMUM 150 mots. RÔLE EXCLUSIF — répondre à : « Qu'est-ce qu'un lecteur devrait savoir avant de tirer une conclusion ? ». UNIQUEMENT des informations NOUVELLES : limites, incertitudes, désaccords, points non encore établis, positions des acteurs. TOUTE projection ou hypothèse future ('pourrait être réduit', 'devrait augmenter', 'risque de') doit être ATTRIBUÉE PRÉCISÉMENT à qui l'énonce (annonce officielle, responsable nommé, rapport daté) — sinon RETIRE-la, ne l'invente jamais. INTERDIT de répéter, reformuler ou résumer un fait déjà présenté dans 'faits' ou 'contexte'. Limites méthodologiques, désaccords entre experts, ce que les données ne permettent pas de conclure."
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
3. Corps total : minimum 500 mots combinés (faits + contexte + nuances)
4. Résumé : chaque phrase minimum 25 mots, concrète, avec au moins un fait mesurable. INTERDIT de commencer par une phrase générique du type "Ce sujet est un défi", "Cette découverte pourrait changer", "Il est essentiel de comprendre", "s'inscrit dans une dynamique" — entrer DIRECTEMENT dans le fait principal avec chiffres ou acteurs.
5. Aucun adjectif évaluatif sans source (alarmant, historique, sans précédent, incroyable...)
6. Aucune opinion. Aucun parti pris. Structure : "Selon X, ... / D'après Y, ..."
7. Titre : 10-15 mots, informatif, factuel — il doit résumer l'essentiel de l'article
8. Sources préférées : institutions officielles (INSEE, CNRS, INSERM, Eurostat, OMS, gouvernement), journaux de référence, publications peer-reviewed — MAIS uniquement si leur URL figure dans SOURCES DISPONIBLES. RÈGLE D'ATTRIBUTION : n'écris "Selon [Institution]" que si le fait attribué figure LITTÉRALEMENT dans l'extrait CONTENU fourni pour cette institution. Ne pas inventer, ne pas extrapoler depuis la mémoire d'entraînement. Si une institution que tu connais n'est pas dans la liste SOURCES DISPONIBLES, ne la cite JAMAIS dans le texte.
9. Slug en français kebab-case, descriptif, max 65 caractères
10. positions : génère ce bloc UNIQUEMENT si le sujet contient un véritable désaccord entre deux parties identifiables qui contestent ou défendent activement une même décision ou proposition — chacune avec une position EXPLICITEMENT attestée dans les sources (déclaration citée, vote enregistré, communiqué officiel). Critère opérationnel : deux camps avec des positions opposées ET défendables toutes les deux. INTERDIT si : acte institutionnel unilatéral sans opposition tracée (sanction disciplinaire, excommunication, condamnation judiciaire, décision administrative), décision technique, bilan statistique, découverte scientifique. Dans tous ces cas : verifie=false, acteurs=[]. Ne jamais inventer ou déduire une position. position = 0 (totalement favorable/consensuel) à 100 (totalement critique/opposé).
11. Le résumé ('resume') et le corps ('faits') ne doivent JAMAIS contenir de phrases identiques ou quasi identiques (mêmes mots, même structure) : le résumé est une synthèse reformulée, pas un copier-coller déguisé du corps.
12. Séparation stricte des registres : 'faits' = actualité immédiate uniquement (le fait du jour). 'contexte' = historique, évolution passée, comparaisons uniquement. Ne jamais mettre du contexte historique dans 'faits', ni redire les faits du jour dans 'contexte'.
13. FUSION DES SOURCES OBLIGATOIRE : si plusieurs sources rapportent exactement la même information (même fait, même chiffre, même résultat), les fusionner en UNE SEULE phrase avec attribution groupée — ex : "Selon Pressesante, Doctissimo et Futura Sciences, [fait]". INTERDIT d'écrire une phrase par source pour le même fait. Une nouvelle source ne justifie une phrase propre que si elle apporte une information DIFFÉRENTE.
14. UNE IDÉE = UNE SEULE APPARITION dans tout l'article. Avant de valider chaque phrase, vérifier qu'elle n'a pas déjà été dite dans une section précédente. Si une idée a été mentionnée dans 'faits', elle n'est JAMAIS reformulée dans 'contexte' ni dans 'nuances'.
15. CONTRÔLE QUALITÉ AVANT SOUMISSION — avant de finaliser le JSON, vérifier explicitement :
    a) Chaque section remplit-elle UNIQUEMENT son rôle (faits=actualité, contexte=historique/mise en perspective, nuances=limites/incertitudes) ?
    b) Une même idée apparaît-elle plusieurs fois ? Si oui, supprimer toutes les occurrences sauf la première.
    c) Chaque paragraphe apporte-t-il au moins une information nouvelle non dite avant ?
    d) La section 'nuances' contient-elle uniquement des limites, incertitudes, désaccords — AUCUN fait déjà présenté ?
    e) Plusieurs sources disent-elles la même chose ? Si oui, les fusionner.
    f) Une phrase peut-elle être supprimée sans perte d'information ? Si oui, la supprimer.
    Si l'un de ces contrôles échoue, corriger AVANT de soumettre le JSON.
13. Chaque source citée dans le texte doit apporter un élément NOUVEAU (chiffre, angle, nuance). Ne JAMAIS répéter la même information sous plusieurs attributions successives. Maximum 3 attributions « Selon X » par section. RÈGLE DE SYNTHÈSE : quand plusieurs sources rapportent le même fait de façon identique ou quasi identique, les fusionner en UNE SEULE phrase de synthèse avec attribution groupée en fin de phrase. N'utiliser des attributions séparées que si les sources apportent des informations DIFFÉRENTES.
    MAUVAIS (interdit) : « Selon Le Monde, le Vatican a excommunié six évêques. D'après Radio Lac, le Vatican a confirmé l'excommunication de ces six évêques. Selon France 24, le Vatican a confirmé l'excommunication de six évêques. »
    BON (attendu) : « Le Vatican a confirmé l'excommunication de six évêques de la Fraternité Saint-Pie X, actant le schisme de ce mouvement avec Rome (Le Monde, France 24, Radio Lac). »
14. ACTUALITÉ UNIQUEMENT : le sujet doit reposer sur un événement daté des dernières 48 heures (étude publiée, décision officielle, annonce, vote, incident). Un sujet intemporel ou encyclopédique sans événement déclencheur récent (ex: « la théorie de l'évolution », « le coucou, un oiseau stratège ») = réponds HORS_PERIMETRE.
15. CADRAGES EMPRUNTÉS INTERDITS : ne jamais reprendre mot pour mot un jugement de valeur ou un cadrage éditorial présent dans une source (ex : "crise sans précédent", "modèle à bout de souffle", "tournant historique") comme s'il s'agissait d'un fait neutre. Si un tel cadrage est pertinent, l'attribuer explicitement : « Selon [Source], il s'agit d'une crise sans précédent. » Ne jamais présenter l'angle éditorial d'une source comme l'angle factuel de l'article.
16. PAS D'EXTRAPOLATION NON SOURCÉE : n'écris jamais de projection ou de conséquence future ("cette mesure pourrait entraîner", "cela risque de", "on pourrait s'attendre à") sauf si une source listée formule explicitement cette projection. Si la conséquence n'est pas dans les extraits CONTENU, ne la mentionne pas.
17. RÉSULTATS INCERTAINS : si une étude est préliminaire, non encore répliquée, ou issue d'un seul chercheur, indique explicitement ce statut ("une étude préliminaire suggère que...", "selon une première analyse, non encore répliquée..."). Ne jamais présenter un résultat d'étude unique comme un fait établi. Le mot "prouve" ou "démontre définitivement" est interdit sauf citation directe attribuée.
18. SECTIONS DENSES, PAS VAGUES : chaque phrase de 'contexte' et 'nuances' doit apporter un fait précis et sourcé (chiffre, date, acteur, étude). Les formulations génériques sans contenu factuel sont interdites : "il est difficile de prévoir les conséquences", "la situation reste complexe", "les experts sont partagés" — supprimer ou remplacer par un fait réel tiré des sources.
19. nb_sources EXACT : le champ "nb_sources" doit correspondre exactement au nombre de sources DISTINCTES effectivement citées dans le texte final (chaque URL du tableau sources comptée une fois, même si citée plusieurs fois dans le corps). Pas de sources fantômes, pas de double-comptage.
20. LÉGAL : ne jamais qualifier quelqu'un de "coupable", "l'assassin", "le violeur" avant condamnation définitive — utiliser "mis en examen", "soupçonné de", "présumé". Ne jamais identifier un mineur par son nom dans une affaire pénale. Si le sujet implique une affaire judiciaire en cours, présenter les faits comme allégations de l'accusation, pas comme faits établis.
21. UNE IDÉE = UNE SEULE APPARITION dans tout l'article (résumé + faits + contexte + nuances confondus). Avant de rendre ta réponse, relis chaque phrase : si elle n'apporte AUCUNE information nouvelle par rapport à ce qui précède (même reformulée, même avec une attribution différente), supprime-la ou fusionne-la avec la première occurrence.
22. RÔLE STRICT DES SECTIONS : résumé = présentation rapide du sujet ; 'faits' = uniquement les faits principaux du jour ; 'contexte' = uniquement les éléments qui permettent de COMPRENDRE les faits, sans les répéter ; 'nuances' = uniquement ce qu'un lecteur devrait savoir avant de tirer une conclusion (limites, désaccords, incertitudes, points non établis). Aucun contenu d'une section ne doit pouvoir être déplacé dans une autre.
23. TRIBUNE / PRISE DE POSITION : si la source principale est une tribune, chronique, interview ou essai d'opinion, TOUT l'article doit faire comprendre qu'il s'agit des analyses et propositions de son auteur, pas de faits établis. Utiliser systématiquement des verbes d'opinion ("estime", "plaide pour", "propose", "juge", "défend l'idée que") et le signaler dès le titre ou le résumé (ex : "Selon l'économiste X…"). Ne jamais transformer un argument d'auteur en constat factuel."""

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
    "nuances": "MINIMUM 150 mots. RÔLE EXCLUSIF de cette section — répondre à la question : « Qu'est-ce qu'un lecteur devrait savoir avant de tirer une conclusion ? ». UNIQUEMENT des informations NOUVELLES : limites, incertitudes, désaccords, points non encore établis. INTERDIT de répéter, reformuler ou résumer un fait déjà présenté dans 'faits' ou 'contexte' — si une phrase n'apporte rien de neuf par rapport aux sections précédentes, elle n'a pas sa place ici. LIMITES ET INCERTITUDES : ce que les sources ne permettent pas de confirmer, critiques légitimes du travail (non de la personne), questions ouvertes dans son domaine."
  },
  "sources": [...],
  "categorie": "science|economie|societe|tech|environnement|sante",
  "nb_sources": 4,
  "positions": {"verifie": false, "label_gauche": "", "label_droite": "", "acteurs": []}
}

RÈGLES ABSOLUES :
1. MINIMUM 4 sources distinctes et citables. Si impossible : réponds uniquement HORS_PERIMETRE.
2. Chaque affirmation sur la personne DOIT être attribuée à une source listée.
3. Corps total : minimum 500 mots combinés.
4. Aucun adjectif évaluatif (brillant, remarquable, visionnaire, exceptionnel...) sans source directe.
5. Aucune opinion. Aucun parti pris. Les faits uniquement.
6. NE PAS écrire de portrait polémique : si la personne est associée à un débat politique, idéologique ou religieux, réponds HORS_PERIMETRE.
7. CADRAGES EMPRUNTÉS INTERDITS : ne jamais reprendre le cadrage éditorial d'une source comme fait neutre.
8. SOURCES : n'écris "Selon [Institution]" que si le fait figure LITTÉRALEMENT dans l'extrait CONTENU fourni.
9. positions : toujours verifie=false pour un portrait (pas de débat binaire).
10. LÉGAL : ne jamais mentionner d'affaires judiciaires en cours, de mises en examen, de suspicions non confirmées.
11. FUSION DES SOURCES OBLIGATOIRE : si plusieurs sources rapportent la même information, les fusionner en UNE phrase. Une source ne justifie une phrase propre que si elle apporte une information DIFFÉRENTE.
12. UNE IDÉE = UNE SEULE APPARITION. Une information présente dans 'faits' n'est JAMAIS reformulée dans 'contexte' ni dans 'nuances'.
13. 'nuances' = UNIQUEMENT limites, incertitudes, désaccords — JAMAIS un fait déjà dit."""

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
    "nuances": "MINIMUM 150 mots. RÔLE EXCLUSIF de cette section — répondre à la question : « Qu'est-ce qu'un lecteur devrait savoir avant de tirer une conclusion ? ». UNIQUEMENT des informations NOUVELLES : limites, incertitudes, désaccords, points non encore établis. INTERDIT de répéter, reformuler ou résumer un fait déjà présenté dans 'faits' ou 'contexte' — si une phrase n'apporte rien de neuf par rapport aux sections précédentes, elle n'a pas sa place ici. LIMITES ET CONTROVERSES : taille d'échantillon, limites méthodologiques, experts en désaccord, ce que l'étude ne permet pas de conclure, réplications nécessaires."
  },
  "sources": [...],
  "categorie": "science|tech|environnement|sante",
  "nb_sources": 4,
  "positions": {"verifie": false, "label_gauche": "", "label_droite": "", "acteurs": []}
}

RÈGLES ABSOLUES :
1. MINIMUM 4 sources distinctes et citables. Si impossible : réponds uniquement HORS_PERIMETRE.
2. JAMAIS "prouve que", "démontre que", "confirme définitivement", "il est désormais certain", "révolutionne", "va transformer" — toujours des marqueurs d'incertitude : "suggère", "laisse penser", "indique", "selon une étude préliminaire".
3. Corps total : minimum 500 mots combinés.
4. Chaque fait attribué à son institution avec "Selon [Institution]", uniquement si présent dans les extraits CONTENU.
5. FUSION DES SOURCES OBLIGATOIRE : si plusieurs sources rapportent la même information, les fusionner en UNE phrase avec attribution groupée. Une source ne justifie une phrase propre que si elle apporte une information DIFFÉRENTE.
6. UNE IDÉE = UNE SEULE APPARITION dans tout l'article. Un fait présent dans 'faits' n'est JAMAIS reformulé dans 'contexte' ni dans 'nuances'.
7. 'nuances' = UNIQUEMENT limites méthodologiques, désaccords entre experts, ce que les données ne permettent pas de conclure — JAMAIS un résultat déjà présenté dans 'faits'.
5. Aucun adjectif évaluatif sans source.
6. PAS D'EXTRAPOLATION : n'écris jamais de conséquence future non sourcée.
7. SOURCES : n'écris "Selon [Institution]" que si le fait figure LITTÉRALEMENT dans l'extrait CONTENU fourni.
8. nb_sources EXACT : compte uniquement les sources distinctes réellement citées dans le texte.
9. LÉGAL : aucun nom de chercheur présenté comme fraudeur ou incompétent sans source directe.
10. Si les sources ne fournissent pas assez de faits précis pour 500 mots sans inventer : réponds HORS_PERIMETRE."""


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

    # Répétition INTERNE au résumé : deux phrases du chapeau qui disent la
    # même chose (vu le 11/07 : « La mesure est saluée par les syndicats… »
    # présent quasi mot pour mot dans les phrases 2 et 3). Comparaison au
    # niveau phrase, toutes entrées du résumé confondues.
    phrases_resume = []
    for r in resume:
        for ph in re.split(r"(?<=[.!?])\s+", (r or "").strip()):
            ph = ph.strip()
            if len(ph) > 40:
                phrases_resume.append(ph)
    def _ngrams5(t):
        mots = re.findall(r"\w+", t.lower())
        return {" ".join(mots[k:k + 5]) for k in range(len(mots) - 4)}
    for i in range(len(phrases_resume)):
        for j in range(i + 1, len(phrases_resume)):
            # Une phrase répétée est souvent enchâssée dans une phrase plus
            # longue — le ratio global la rate. 3+ séquences de 5 mots en
            # commun = même contenu recyclé (un résumé sain en partage 0-1).
            communs = _ngrams5(phrases_resume[i]) & _ngrams5(phrases_resume[j])
            if len(communs) >= 3:
                violations.append(f"répétition interne au résumé : « {phrases_resume[j][:80]}… »")
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

    # Répétition ENTRE sections : un fait de 'faits' qui revient dans
    # 'contexte' ou 'nuances' (règle éditoriale : une idée = une seule
    # apparition dans tout l'article ; 'nuances' ne doit contenir que du
    # nouveau). Détection par 5-grammes de mots partagés, robuste aux
    # reformulations partielles et aux attributions différentes.
    def _ngrams5(t):
        mots = re.findall(r"\w+", t.lower())
        return {" ".join(mots[k:k + 5]) for k in range(len(mots) - 4)}
    phrases_par_section = {}
    for section in ("faits", "contexte", "nuances"):
        texte = corps.get(section, "") or ""
        phrases_par_section[section] = [
            _ATTRIB_PREFIX_RE.sub("", p.strip())
            for p in re.split(r"(?<=[.!?])\s+", texte) if len(p.strip()) > 40
        ]
    paires = [("faits", "contexte"), ("faits", "nuances"), ("contexte", "nuances")]
    for sec_a, sec_b in paires:
        if len(violations) >= 6:
            break
        for pa in phrases_par_section[sec_a]:
            for pb in phrases_par_section[sec_b]:
                if len(_ngrams5(pa) & _ngrams5(pb)) >= 3:
                    violations.append(
                        f"[{sec_a}→{sec_b}] fait répété entre sections : « {pb[:70]}… »")
                    break
    return violations


def _mots_totaux(art: dict) -> int:
    """Compte de mots faisant foi pour le plancher éditorial (500 cible /
    400 plancher) ET pour le badge public — chapeau + faits + contexte +
    nuances. Le chapeau compte depuis le 18/07 (décision Nahil) : tant que
    resume_repete_corps + la réparation des doublons empêchent un chapeau
    redondant avec le corps, le compter ne récompense plus l'auto-résumé,
    et ça aligne le chiffre affiché sur ce qu'un lecteur mesure en
    copiant l'article (écart 320 affiché / 417 réels sur l'article
    douleurs-chroniques, qui a motivé ce changement)."""
    corps = art.get("corps") or {}
    mots = sum(len(str(corps.get(k, "") or "").split()) for k in ("faits", "contexte", "nuances"))
    resume = art.get("resume") or []
    if isinstance(resume, str):
        resume = [resume]
    mots += sum(len(str(r or "").split()) for r in resume)
    return mots


def _supprimer_phrases_dupliquees(art: dict) -> int:
    """Réparation déterministe post-correction : supprime, dans le corps,
    toute phrase quasi identique à une phrase déjà conservée plus haut dans
    l'article (ordre de lecture : résumé → faits → contexte → nuances). La
    PREMIÈRE occurrence est toujours gardée ; c'est la copie qui saute.
    Mêmes critères de similarité que les détecteurs (faits_repetitifs /
    resume_repete_corps) pour que ce que l'un détecte, l'autre le répare.
    Retourne le nombre de phrases supprimées. Ne touche jamais au résumé."""
    import difflib
    corps = art.get("corps", {}) or {}

    def _ngrams5(t):
        mots = re.findall(r"\w+", t.lower())
        return {" ".join(mots[k:k + 5]) for k in range(len(mots) - 4)}

    # Référentiel initial : les phrases du résumé (jamais modifiées ici)
    resume = art.get("resume") or []
    if isinstance(resume, str):
        resume = [resume]
    gardees = []  # (noyau, ngrams) des phrases conservées
    for r in resume:
        for p in re.split(r"(?<=[.!?])\s+", str(r or "")):
            if len(p.strip()) > 40:
                noyau = _ATTRIB_PREFIX_RE.sub("", p.strip())
                gardees.append((noyau, _ngrams5(noyau)))

    n_supp = 0
    for section in ("faits", "contexte", "nuances"):
        texte = corps.get(section, "") or ""
        phrases = [p.strip() for p in re.split(r"(?<=[.!?])\s+", texte) if p.strip()]
        conservees = []
        for p in phrases:
            if len(p) <= 40:
                conservees.append(p)
                continue
            noyau = _ATTRIB_PREFIX_RE.sub("", p)
            ng = _ngrams5(noyau)
            doublon = any(
                len(ng & ng_g) >= 3
                or difflib.SequenceMatcher(None, noyau.lower(), n_g.lower()).ratio() > 0.62
                for n_g, ng_g in gardees
            )
            if doublon:
                n_supp += 1
            else:
                conservees.append(p)
                gardees.append((noyau, ng))
        corps[section] = " ".join(conservees)
    art["corps"] = corps
    return n_supp


_ATTRIB_DEBUT_RE = re.compile(r"^\s*[«\"]?\s*(?:Selon|D['’]après)\b", re.IGNORECASE)

# Au-delà de ce total, l'article devient une litanie de « Selon X » — le
# corpus publié plafonnait à 26 occurrences par article (médiane : 10).
MAX_ATTRIBUTIONS_SELON = 7


def attributions_trop_repetitives(art: dict) -> list[str]:
    """Détecte le tic de style « Selon X » : deux phrases consécutives qui
    commencent par Selon/D'après, ou densité globale excessive. Défaut de
    style non bloquant — corrigé via la relance combinée."""
    corps = art.get("corps", {}) or {}
    textes = [str(corps.get(s, "") or "") for s in ("faits", "contexte", "nuances")]
    resume = art.get("resume")
    if isinstance(resume, list):
        textes.append(" ".join(str(p) for p in resume))

    feedback = []
    total = 0
    for texte in textes:
        total += len(re.findall(r"\b(?:Selon|D['’]après)\s", texte, re.IGNORECASE))
        phrases = [p for p in re.split(r"(?<=[.!?])\s+", texte) if p.strip()]
        consecutives = 0
        for ph in phrases:
            if _ATTRIB_DEBUT_RE.match(ph):
                consecutives += 1
                if consecutives == 2 and len(feedback) < 4:
                    feedback.append(f"phrases consécutives en « Selon… » : « {ph[:70]}… »")
            else:
                consecutives = 0
    if total > MAX_ATTRIBUTIONS_SELON:
        feedback.append(f"{total} « Selon/D'après » au total (maximum : {MAX_ATTRIBUTIONS_SELON})")
    return feedback


# Titres sensationnalistes/tabloïd repérés en audit (« Patient bizarre aux
# urgences… », « La possibilité de couper un atome au couteau ? ») — le
# modèle paraphrase parfois trop fidèlement un titre RSS racoleur au lieu de
# reformuler le fait de façon factuelle et neutre.
_TITRE_SENSATIONNALISTE_RE = re.compile(
    r"\b(?:bizarre|insolite|incroyable|improbable|hallucinant|dingue|choc|"
    r"stupéfiant|ahurissant|hallucinante|surprenant[e]?|inattendu[e]?)\b",
    re.IGNORECASE,
)
_TITRE_QUESTION_RE = re.compile(r"\?\s*$|^(?:peut-on|peut-il|est-ce que|pourquoi|comment)\b", re.IGNORECASE)
# Retour éditorial (25/07) : titres trop génériques ("Découverte sur les
# larves de mollusques abyssaux") sans chiffre ni nom propre — faible valeur
# SEO/partage. Un chiffre (date, montant, %) ou un nom propre (acteur,
# institution, lieu) ancre le titre dans du concret.
_TITRE_A_UN_CHIFFRE_RE = re.compile(r"\d")


def _titre_a_un_nom_propre(titre: str) -> bool:
    """Un mot capitalisé après le premier mot du titre = nom propre probable
    (acteur, institution, lieu) — on ignore le tout premier mot (toujours
    capitalisé en début de phrase, pas un signal de spécificité)."""
    mots = titre.split()
    return any(m[:1].isupper() for m in mots[1:] if m[:1].isalpha())


def titre_de_mauvaise_qualite(art: dict) -> str | None:
    """Détecte un titre non conforme à la règle 7 (factuel, neutre, 10-15 mots,
    jamais de question ni de vocabulaire putaclic) — retourne un message de
    correction ou None si le titre est correct."""
    titre = str(art.get("titre", "") or "").strip()
    if not titre:
        return None
    nb_mots = len(titre.split())
    problemes = []
    if _TITRE_SENSATIONNALISTE_RE.search(titre):
        mot = _TITRE_SENSATIONNALISTE_RE.search(titre).group()
        problemes.append(f"vocabulaire putaclic/sensationnaliste (« {mot} »)")
    if _TITRE_QUESTION_RE.search(titre):
        problemes.append("formulation en question au lieu d'un titre factuel")
    if nb_mots < 6:
        problemes.append(f"trop court ({nb_mots} mots, minimum 6-10 attendus)")
    titre_generique = False
    if not _TITRE_A_UN_CHIFFRE_RE.search(titre) and not _titre_a_un_nom_propre(titre):
        problemes.append("trop générique (aucun chiffre ni nom propre — acteur, institution, lieu)")
        titre_generique = True
    if not problemes:
        return None
    consigne_generique = (
        " Ajoute un élément concret (un chiffre, une date, un acteur nommé, une institution, un lieu) "
        "au lieu d'une formulation abstraite type 'Découverte sur…'."
        if titre_generique else ""
    )
    return (f"le titre « {titre} » a un problème : {', '.join(problemes)}. "
            "Réécris-le en 10 à 15 mots, factuel et neutre, qui résume l'essentiel de l'article "
            "SANS vocabulaire putaclic (bizarre, insolite, choc…) et SANS tournure de question — "
            "énonce le fait directement, comme le ferait un titre de presse de référence."
            + consigne_generique)


# Tournures artificielles typiques d'un texte généré automatiquement — signalées
# nommément par l'utilisateur comme remplissage stylistique récurrent.
_CLICHES_IA_RE = re.compile(
    r"\b(?:s['’]inscrit dans une dynamique|constitue un enjeu majeur|"
    r"illustre la diversité des situations|permet une plong[ée]e dans|"
    r"intervient dans un contexte o[uù]|pourrait transformer|"
    r"reflète une [ée]volution plus large|"
    r"offre une plateforme|"
    r"d[ée]velopper (?:leurs?|ses|ces) comp[ée]tences et gagner de l['’]exp[ée]rience|"
    r"n[ée]cessite une approche nuanc[ée]e)\b",
    re.IGNORECASE,
)


def cliches_ia(art: dict) -> list[str]:
    """Détecte les tournures génériques de remplissage (règle 5, charte
    éditoriale) dans le résumé et le corps — retourne la liste des expressions
    trouvées, ou [] si l'article est propre."""
    corps = art.get("corps") or {}
    resume = art.get("resume")
    textes = [str(corps.get(k, "") or "") for k in ("faits", "contexte", "nuances")]
    if isinstance(resume, list):
        textes.append(" ".join(str(p) for p in resume))
    elif resume:
        textes.append(str(resume))
    trouvees = []
    for texte in textes:
        for m in _CLICHES_IA_RE.finditer(texte):
            expr = m.group()
            if expr not in trouvees:
                trouvees.append(expr)
    return trouvees


_INTRO_GENERIQUE_RE = re.compile(
    r"(?:^|\. )(?:"
    r"[A-ZÀ-Ü][^.]{0,120}(?:"
    r"est (?:un|une) (?:défi|enjeu|sujet|question|problème|phénomène|thème|domaine)"
    r"|(?:nécessite|requiert) une approche"
    r"|(?:pourrait|peut) (?:changer|transformer|révolutionner|modifier profondément)"
    r"|s'inscrit dans une dynamique"
    r"|constitue un enjeu majeur"
    r"|il est (?:essentiel|important|crucial|fondamental) de"
    r"|(?:les études|la recherche|la science) (?:montre|révèle|indique) que"
    r"|il convient de (?:comprendre|noter|souligner|rappeler)"
    r")[^.]{0,80}\.)",
    re.IGNORECASE | re.MULTILINE,
)


def intro_generique(art: dict) -> list[str]:
    """Détecte les phrases d'introduction vagues/génériques dans le résumé
    ou le début des sections — entrée directe dans les faits obligatoire."""
    resume = art.get("resume")
    texte_resume = ""
    if isinstance(resume, list):
        texte_resume = " ".join(str(p) for p in resume[:2])
    elif resume:
        texte_resume = str(resume)
    corps = art.get("corps") or {}
    debut_faits = str(corps.get("faits", "") or "")[:300]
    trouvees = []
    for texte in (texte_resume, debut_faits):
        for m in _INTRO_GENERIQUE_RE.finditer(texte):
            expr = m.group().strip()[:100]
            if expr not in trouvees:
                trouvees.append(expr)
    return trouvees


# Retour externe (revues éditoriales du 22/07 et du 25/07) : "Débats et
# nuances" retombe régulièrement sur des généralités ("les défis sont
# nombreux", "c'est un problème difficile, les recherches continuent",
# "les utilisateurs doivent être conscients...") au lieu de limites ou
# d'incertitudes concrètes liées au sujet. Une phrase générique est tolérée
# si elle est suivie d'un exemple concret (chiffre, terme technique, nom
# propre) ; sinon c'est du remplissage pur.
_NUANCE_VAGUE_RE = re.compile(
    r"(?:les?\s+)?(?:d[ée]fis|enjeux|implications|cons[ée]quences|risques)\s+"
    r"(?:sont|restent|demeurent)\s+(?:nombreux(?:\s+et\s+complexes)?|complexes|"
    r"multiples|importantes?|significatifs?|consid[ée]rables)\b"
    r"|\bc['’]est un (?:problème|sujet|domaine) (?:difficile|complexe)\b"
    r"|\bil s['’]agit d['’]un (?:problème|sujet|domaine) (?:difficile|complexe)\b"
    r"|\bles? recherches? (?:continue(?:nt)?|se poursuit|se poursuivent)\b"
    r"|\b(?:les? utilisateurs?|le lecteur|le grand public|chacun) doivent? (?:rester|être) (?:conscients?|prudents?|vigilants?)\b"
    r"|\bla vigilance (?:est|reste) de mise\b"
    r"|\bsoul[eè]ve(?:nt)? (?:des|de nombreuses) questions?\b(?!\s+(?:sur|quant|concernant)\s+\S)"
    r"|\breste(?:nt)? (?:incertaine?s?|flou(?:e|s)?|à (?:d[ée]montrer|confirmer|pr[ée]ciser))\b",
    re.IGNORECASE,
)
_A_UN_FAIT_PRECIS_RE = re.compile(r"\d|%|€|\$")


def nuances_vagues(art: dict) -> list[str]:
    """Détecte dans « Débats et nuances » les généralités de remplissage
    (« les défis sont nombreux ») qui ne sont suivies d'aucun exemple concret
    (chiffre, donnée précise) dans la même phrase ou la suivante."""
    corps = art.get("corps") or {}
    texte = str(corps.get("nuances", "") or "")
    if not texte:
        return []
    phrases = re.split(r"(?<=[.!?])\s+", texte)
    trouvees = []
    for i, phrase in enumerate(phrases):
        m = _NUANCE_VAGUE_RE.search(phrase)
        if not m:
            continue
        fenetre = phrase + " " + (phrases[i + 1] if i + 1 < len(phrases) else "")
        if _A_UN_FAIT_PRECIS_RE.search(fenetre):
            continue  # un chiffre/donnée précise suit de près : pas du remplissage
        expr = m.group().strip()
        if expr not in trouvees:
            trouvees.append(expr)
    return trouvees


# Retour externe (revue éditoriale du 22/07) : un usage ou une application
# encore à l'état de prototype/étude/projet est parfois présenté comme acquis
# ("ouvre de nouvelles perspectives", "représente une avancée majeure") au
# lieu du conditionnel attendu pour du potentiel non démontré.
_AFFIRMATION_PROSPECTIVE_RE = re.compile(
    r"\b(?:ouvre|ouvrent|repr[ée]sente(?:nt)?|marque(?:nt)?|constitue(?:nt)?)\s+"
    r"(?:de\s+nouvelles?\s+perspectives|une\s+avanc[ée]e\s+majeure|un\s+tournant"
    r"|des?\s+perspectives\s+(?:nouvelles|prometteuses)|une\s+r[ée]volution)\b"
    r"|\bva(?:\s+ainsi)?\s+(?:changer|transformer)\s+(?:la\s+donne|le\s+secteur)\b"
    r"|\bpermettra\s+de\b(?!.{0,15}(?:potentiellement|peut[- ]être))",
    re.IGNORECASE,
)
_CONDITIONNEL_DEJA_PRESENT_RE = re.compile(
    r"\b(?:pourrait|pourraient|pourrait\s+potentiellement|selon\s+les\s+chercheurs|"
    r"si\s+cette\s+piste\s+se\s+confirme|reste\s+à\s+d[ée]montrer|"
    r"n'est\s+pas\s+encore\s+d[ée]montr[ée])\b",
    re.IGNORECASE,
)


def affirmation_non_demontree(art: dict) -> list[str]:
    """Détecte les formulations affirmatives sur un usage/potentiel qui n'est
    pas encore démontré (prototype, étude préliminaire, projet) — ces
    passages doivent être au conditionnel, pas présentés comme acquis."""
    corps = art.get("corps") or {}
    textes = [str(corps.get(k, "") or "") for k in ("faits", "contexte", "nuances")]
    trouvees = []
    for texte in textes:
        for m in _AFFIRMATION_PROSPECTIVE_RE.finditer(texte):
            debut = max(0, m.start() - 60)
            fin = min(len(texte), m.end() + 60)
            fenetre = texte[debut:fin]
            if _CONDITIONNEL_DEJA_PRESENT_RE.search(fenetre):
                continue  # déjà nuancé à proximité (pourrait, reste à démontrer…)
            expr = m.group().strip()
            if expr not in trouvees:
                trouvees.append(expr)
    return trouvees


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


class TronqueError(Exception):
    """La complétion a été coupée à max_tokens (finish_reason='length') —
    le JSON est forcément invalide, inutile de le parser."""


class QuotaJournalierEpuise(RuntimeError):
    """Toutes les clés Groq ont épuisé leur quota JOURNALIER (TPD) — attendre
    62 s ne sert à rien, le budget ne se libère qu'à minuit UTC. Le run doit
    s'arrêter proprement au lieu de moudre des cycles d'attente à vide."""


# Clés dont le quota JOURNALIER est épuisé — mortes jusqu'à la fin du run.
# Diagnostic du 16/07 : 4 runs dans la journée avaient consommé le budget
# quotidien de la plupart des clés ; le code traitait tous les 429 comme des
# limites par MINUTE et attendait 62s × 8 cycles × 12 sujets = 76 min d'attente
# pour rien (0 article). Le corps de l'erreur Groq distingue les deux :
# "tokens per minute (TPM)" vs "tokens per day (TPD)".
_CLES_MORTES_JOUR: set = set()
_ROTATION_APPELS = [0]  # compteur global — départ tournant dans la liste des clés


def _est_quota_journalier(err: str) -> bool:
    e = err.lower()
    return "per day" in e or "tpd" in e or "tokens per day" in e or "requests per day" in e or "rpd" in e


def _tpd_restant(err: str) -> int | None:
    """Extrait le solde journalier réel du corps d'erreur Groq
    (« Limit 100000, Used 97500, Requested 8000 »). Un 429 « per day » ne
    signifie PAS que la clé est vide : seulement que CETTE requête (prompt +
    max_tokens réservés) dépasse ce qui reste. Constat du 18/07 : des clés
    déclarées « épuisées » à 14h08 acceptaient des appels à 16h11 — elles
    n'étaient pas vides, nos requêtes étaient trop grosses pour leur solde.
    Retourne None si les chiffres sont absents du message."""
    m = re.search(r"Limit (\d+), Used (\d+)", err)
    if m:
        return int(m.group(1)) - int(m.group(2))
    m = re.search(r"Remaining (\d+)", err)
    return int(m.group(1)) if m else None


def _groq_call(api_key: str, messages: list, max_tokens: int = 3500) -> str:
    """Appelle Groq avec la clé donnée. Lève une exception en cas d'erreur.

    max_tokens relevé de 4500 à 6000 le 15/07 : deux générations valides ont été
    perdues dans le même run (complétion tronquée pile à 4500, JSON invalide,
    « Pas de JSON dans la réponse ») — le modèle voulait clairement produire
    plus que 4500 tokens de sortie. Plafond gardé modéré (pas 8000+) car un
    run du même jour a révélé la vraie limite Groq : 12 000 tokens/minute PAR
    CLÉ (erreur 413 « Request too large », TPM Limit 12000) — un prompt déjà
    lourd (jusqu'à ~9000 tokens observés) + un max_tokens trop généreux
    rapprocherait chaque appel de ce plafond dur.

    Lève TronqueError si la complétion est coupée à max_tokens
    (finish_reason='length') : le JSON est invalide par construction —
    3 sujets perdus ainsi les 15-16/07, dont deux fois le même.
    """
    client = Groq(api_key=api_key)
    # La limite TPM compte prompt + max_tokens RÉSERVÉS, pas les tokens
    # réellement produits : prompt lourd + réservation généreuse = 413
    # « Request too large » systématique, quel que soit le quota restant.
    # Plafond TPM propre à chaque modèle (constat du 21/07 : gpt-oss-120b n'a
    # que 8K TPM contre 12K pour Llama 3.3 — utiliser le plafond de Llama sur
    # gpt-oss produisait un 413 à 0 token traité, à chaque appel, quel que
    # soit le quota journalier restant).
    _TPM_PAR_MODELE = {
        "llama-3.3-70b-versatile": 12_000,
        "openai/gpt-oss-120b": 8_000,
        "openai/gpt-oss-20b": 8_000,
        "qwen/qwen3.6-27b": 8_000,
        "llama-3.1-8b-instant": 6_000,
    }
    tpm = _TPM_PAR_MODELE.get(GROQ_MODEL, 12_000)
    marge_securite = 500
    prompt_estime = int(sum(len(m.get("content", "")) for m in messages) / 3.3)
    disponible = tpm - marge_securite - prompt_estime
    # Pas de plancher qui dépasserait le budget réel (même piège corrigé le
    # 21/07 côté repêchage TPD) : mieux vaut une réservation honnête, quitte
    # à risquer une troncature déjà gérée séparément, qu'un 413 certain.
    max_tokens = max(200, min(max_tokens, disponible))
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        max_tokens=max_tokens,
        temperature=0.1,
        messages=messages,
    )
    u = response.usage
    if u:
        print(f"     [TOKENS] prompt={u.prompt_tokens} completion={u.completion_tokens} "
              f"total={u.total_tokens}", flush=True)
    choice = response.choices[0]
    if getattr(choice, "finish_reason", None) == "length":
        raise TronqueError(f"complétion coupée à {max_tokens} tokens")
    return choice.message.content.strip()


def generate(content: str, category_hint: str, extra_sources: list[dict] | None = None,
             rss_url: str | None = None, retry_feedback: list[str] | None = None,
             repetition_feedback: list[str] | None = None,
             intra_feedback: list[str] | None = None,
             selon_feedback: list[str] | None = None,
             expand_feedback: str | None = None,
             titre_feedback: str | None = None,
             cliches_feedback: list[str] | None = None,
             intro_feedback: list[str] | None = None,
             nuances_feedback: list[str] | None = None,
             prospectif_feedback: list[str] | None = None,
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
    is_retry = bool(retry_feedback or repetition_feedback or intra_feedback or selon_feedback or expand_feedback or titre_feedback or cliches_feedback or intro_feedback or nuances_feedback or prospectif_feedback)
    # La relance "expand" a besoin de matière source (le problème est que
    # l'article n'a pas assez puisé dedans), mais PAS des extraits intégraux :
    # run du 18/07 matin, 2 sujets perdus en « réponse tronquée » parce que le
    # prompt d'étoffement (~10 000 tokens avec extraits complets + article
    # précédent) ne laissait que ~1 500 tokens de réponse dans la fenêtre TPM
    # de 12 000 — trop peu pour un article JSON complet (~2 000 tokens). Des
    # extraits raccourcis mais une réponse qui peut FINIR valent mieux que des
    # extraits complets pour une réponse coupée en plein JSON (arbitrage
    # validé par Nahil le 18/07). Les autres relances corrigent un défaut déjà
    # connu sans avoir besoin de ré-analyser le contenu en détail.
    is_expand = bool(expand_feedback)
    # Expérimentation snippet_len 950→3000 (15/07) ANNULÉE avant mesure :
    # l'audit des logs de prod montre que presque tous les sujets saturent
    # déjà à 8 sources réelles — exactement le plafond max_results de
    # duckduckgo_search(). Le facteur limitant n'est donc pas la profondeur
    # de CHAQUE source (ce que snippet_len contrôlait) mais le NOMBRE de
    # sources distinctes trouvées. On isole cette variable-là à la place
    # (voir duckduckgo_search) — une hypothèse, une mesure à la fois.
    # 950 car. ≈ 2-3 paragraphes : suffisant pour ancrer des faits précis
    # sans dépasser le budget Groq (déjà rate-limité en continu, voir logs).
    snippet_len = 950 if not is_retry else (450 if is_expand else 200)
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

    content_len = 7000 if not is_retry else (2500 if is_expand else 1500)

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
        "6. Si les extraits disponibles ne fournissent pas assez de faits précis pour 500 mots sans inventer, "
        "réponds uniquement HORS_PERIMETRE.\n"
    )
    instruction_finale = (
        "Corrige maintenant l'article ci-dessus." if (is_retry and previous_article)
        else "Rédige maintenant l'article complet."
    )

    # ── Ancrage sur UN SEUL événement ──
    # Défaut identifié le 19/07 (article Alzheimer, critique externe) : la
    # recherche par mots-clés remonte des sources qui partagent le THÈME
    # (« Alzheimer ») mais pas la même ACTUALITÉ (étude lithium + anticorps
    # anti-amyloïde + inversion des symptômes = 3 études distinctes fusionnées
    # de force). Le CONTENU SOURCE PRINCIPAL ci-dessus est l'événement unique
    # de l'article. Les autres sources ne sont pas jetées (ni matière ni
    # sources perdues) : celles qui décrivent une étude/annonce DIFFÉRENTE
    # servent de mise en perspective dans « Contexte », jamais confondues avec
    # le fait principal.
    ancre_block = (
        "\n\n⚠ ANGLE UNIQUE — RÈGLE DE COHÉRENCE ABSOLUE :\n"
        "L'article traite d'UN SEUL événement : celui décrit dans le CONTENU SOURCE "
        "PRINCIPAL ci-dessus (l'étude, l'annonce ou la décision précise qui est l'actualité du jour).\n"
        "- « Les faits » : UNIQUEMENT cet événement précis et ses données. N'y mélange JAMAIS "
        "les résultats d'une autre étude, même sur le même thème général.\n"
        "- Les sources ci-dessus qui décrivent une étude / une découverte / une annonce DIFFÉRENTE "
        "(autre équipe, autre mécanisme, autre date) ne rapportent PAS le même fait : utilise-les "
        "dans « Contexte » comme mise en perspective (« d'autres travaux récents… », en les "
        "distinguant clairement de l'actualité principale), jamais fusionnées dans « Les faits » "
        "comme si c'était la même trouvaille.\n"
        "- Si, après lecture, les sources ne convergent pas vers un événement principal identifiable "
        "et ne parlent que de sujets épars reliés par un simple mot-clé commun, réponds HORS_PERIMETRE "
        "plutôt que de produire un article qui agrège des actualités sans rapport.\n"
        "- TEST ANTI-DIGRESSION pour « Contexte » et « Débats et nuances » : avant d'écrire une phrase "
        "qui mentionne un AUTRE cas, lieu, instance ou exemple similaire (un autre volcan, un autre pays, "
        "un autre incident du même type…), vérifie qu'elle répond à la question « est-ce que ça aide "
        "directement à comprendre CETTE actualité précise ? ». Si la réponse est non — si c'est juste un "
        "fait parallèle intéressant mais sans lien de cause, de méthode ou de comparaison chiffrée avec "
        "l'événement principal — NE L'ÉCRIS PAS, même si une source en parle. Une comparaison n'est "
        "légitime que si elle est explicitement mise en relation avec le sujet principal (« contrairement "
        "à X, qui... », « comme dans le cas de Y, mais avec cette différence : ... ») — jamais une simple "
        "juxtaposition (« par ailleurs, X se produit aussi »).\n"
    )

    user_msg = (
        f"{attrib_header}"
        f"Catégorie probable : {category_hint}\n\n"
        f"CONTENU SOURCE PRINCIPAL :\n{content[:content_len]}"
        f"{sources_block}"
        f"{ancre_block}"
        f"{article_precedent_block}"
        f"RAPPEL ATTRIBUTION :\n"
        f"1. Le champ 'sources' ne doit contenir QUE des entrées dont l'URL figure dans les SOURCES ci-dessus.\n"
        f"2. Noms autorisés pour « Selon X » : {noms_autorises}. Aucun autre.\n"
        f"3. N'attribue un fait à une source QUE si ce fait est explicitement présent dans son extrait CONTENU.\n"
        f"   Si une information n'est dans aucun extrait, présente-la sans attribution ou omets-la.\n"
        f"4. JAMAIS « selon les experts », « des études montrent », « les scientifiques estiment » sans source précise.\n"
        f"5. STYLE D'ATTRIBUTION : maximum {MAX_ATTRIBUTIONS_SELON} « Selon X » / « D'après X » dans tout l'article, "
        f"et jamais deux phrases consécutives qui commencent ainsi. Varie les formes : attribution en fin de phrase "
        f"(« …, indique X »), verbe de citation (« X rapporte que… »), ou regroupe plusieurs faits d'une même source "
        f"sous une seule attribution. La variation porte sur la FORME uniquement — chaque fait attribué reste lié à "
        f"sa source réelle.\n"
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
            "étaient une quasi-répétition du corps 'faits' ou d'une autre phrase du résumé : « "
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

    if selon_feedback:
        user_msg += (
            "\n\nCORRECTION OBLIGATOIRE — ta précédente réponse abusait des attributions "
            "« Selon X » / « D'après X » : " + " ; ".join(selon_feedback[:4]) + ". "
            f"Réduis à {MAX_ATTRIBUTIONS_SELON} maximum : regroupe les faits d'une même source sous une seule "
            "attribution et varie les formes (« …, indique X », « X rapporte que… »). "
            "N'attribue JAMAIS un fait à une source absente de la liste pour autant."
        )

    if expand_feedback:
        user_msg += (
            "\n\nCORRECTION OBLIGATOIRE — " + expand_feedback + " "
            "Va chercher des faits NOUVEAUX et précis (chiffres, dates, déclarations) dans les "
            "extraits CONTENU des sources listées ci-dessus — ils contiennent plus de matière que "
            "ce que tu as utilisé. N'invente RIEN : si une source ne permet pas d'étoffer une section, "
            "cite-en une autre de la liste plutôt que de laisser la section courte. "
            "Renvoie l'article COMPLET (toutes les sections), pas seulement la partie à étoffer."
        )

    if titre_feedback:
        user_msg += "\n\nCORRECTION OBLIGATOIRE — " + titre_feedback

    if cliches_feedback:
        user_msg += (
            "\n\nCORRECTION OBLIGATOIRE — ta précédente réponse contenait des tournures "
            "génériques de remplissage typiques d'un texte généré automatiquement : « "
            + " » ; « ".join(cliches_feedback[:5]) + " ». "
            "Réécris ces passages en langage concret et informatif (un fait précis, un chiffre, "
            "un acteur nommé) — n'utilise ce type de formule que si elle apporte une information "
            "réellement nouvelle, jamais comme remplissage."
        )

    if intro_feedback:
        user_msg += (
            "\n\nCORRECTION OBLIGATOIRE — ton introduction ou le début de 'faits' contient "
            "des phrases génériques vides d'information : « "
            + " » ; « ".join(intro_feedback[:3]) + " ». "
            "Remplace-les par une entrée directe dans le fait principal : commence par un chiffre, "
            "un acteur nommé, une date ou une action concrète. Supprime toute phrase du type "
            "'ce sujet est un défi', 'il est important de comprendre', 'cette question s'inscrit dans…' "
            "— ces formules n'apportent aucune information au lecteur."
        )

    if nuances_feedback:
        user_msg += (
            "\n\nCORRECTION OBLIGATOIRE — ta section 'Débats et nuances' contient des généralités "
            "creuses, jamais suivies d'un exemple concret : « " + " » ; « ".join(nuances_feedback[:5]) + " ». "
            "Remplace chacune par une limite, une incertitude ou un désaccord PRÉCIS et propre à ce "
            "sujet (un chiffre encore provisoire, un point que les sources ne tranchent pas, une "
            "méthodologie contestée) — si tu ne trouves aucun exemple concret dans les sources, "
            "supprime la phrase plutôt que de la garder vide de sens."
        )

    if prospectif_feedback:
        user_msg += (
            "\n\nCORRECTION OBLIGATOIRE — ton article présente comme acquis un usage, un impact ou "
            "un potentiel qui n'est pourtant pas démontré dans les sources : « "
            + " » ; « ".join(prospectif_feedback[:5]) + " ». "
            "Mets ces passages au CONDITIONNEL (« pourrait », « pourrait potentiellement », « si "
            "cette piste se confirme ») dès que la source elle-même parle d'un prototype, d'une étude "
            "préliminaire, d'un projet ou d'une application envisagée — ne présente comme acquis que "
            "ce qui est déjà effectivement en usage ou démontré selon la source."
        )

    # Les modèles "reasoning" de Groq (famille openai/gpt-oss-*, qwen*)
    # documentent explicitement d'éviter les system prompts — tout mettre
    # dans le message utilisateur (doc officielle Groq, section Reasoning :
    # "Avoid system prompts - include all instructions in the user message!").
    # Comportement par défaut (Llama) strictement inchangé.
    if GROQ_MODEL.startswith(("openai/gpt-oss", "qwen/")):
        messages = [
            {"role": "user", "content": _select_prompt(article_type) + "\n\n" + user_msg},
        ]
    else:
        messages = [
            {"role": "system", "content": _select_prompt(article_type)},
            {"role": "user",   "content": user_msg},
        ]

    raw = None
    _all_keys = GROQ_ALL_KEYS
    # 8 cycles max (≈8 min) par article : le job GitHub a désormais 5 h
    # (timeout-minutes: 300) — on attend les fenêtres de rate limit Groq
    # plutôt que de perdre le sujet. La protection contre le timeout reste
    # le budget GLOBAL de la boucle de génération, pas ce plafond par
    # article. Si toutes les clés sont encore en rate limit après 8 cycles,
    # on abandonne CET article et on passe au suivant.
    # DISTINCTION TPM/TPD (16/07) : un 429 « per day » signifie que la clé a
    # épuisé son quota JOURNALIER — attendre 62 s est inutile, elle est retirée
    # de la rotation pour tout le run. Si TOUTES les clés sont mortes pour la
    # journée, QuotaJournalierEpuise remonte à la boucle principale qui arrête
    # le run proprement (les sujets seront retentés au créneau suivant).
    MAX_RETRY_CYCLES = 8  # cycles complets sur toutes les clés avant abandon
    RETRY_WAIT = 62       # secondes d'attente entre deux cycles (fenêtre rate-limit Groq = 60s)
    troncature_deja_reduite = False
    # Réservation de réponse : 3500 par défaut (voir _groq_call) ; montée à
    # 6000 UNIQUEMENT pour la relance après troncature — payer plus de TPD
    # seulement quand l'article en a réellement besoin, plutôt que de le
    # perdre (1 sujet mort tronqué deux fois à 3500 la nuit du 19/07).
    reservation_reponse = 3500
    for cycle in range(MAX_RETRY_CYCLES):
        keys_to_try = [(k, l) for k, l in _all_keys if k and k not in _CLES_MORTES_JOUR]
        if not keys_to_try:
            raise QuotaJournalierEpuise(
                "Toutes les clés Groq ont épuisé leur quota journalier (TPD)")
        # Départ tournant : ne pas marteler toujours la clé 1 en premier —
        # chaque appel commence sur la clé suivante de la rotation.
        offset = _ROTATION_APPELS[0] % len(keys_to_try)
        _ROTATION_APPELS[0] += 1
        keys_to_try = keys_to_try[offset:] + keys_to_try[:offset]
        for key, label in keys_to_try:
            try:
                raw = _groq_call(key, messages, max_tokens=reservation_reponse)
                break
            except TronqueError:
                # Complétion coupée à max_tokens : réessayer UNE fois (même
                # clé, même cycle) avec une consigne de concision explicite
                # ET une réservation doublée — sans ça le sujet est perdu à
                # coup sûr (JSON invalide).
                if troncature_deja_reduite:
                    raise ValueError("Réponse tronquée à max_tokens malgré la consigne de concision")
                troncature_deja_reduite = True
                reservation_reponse = 6000
                print(f"     [GROQ] Complétion tronquée à max_tokens — nouvelle tentative avec consigne de concision et réservation élargie")
                messages = messages + [{
                    "role": "user",
                    "content": ("Ta réponse précédente a été coupée car trop longue. "
                                "Recommence en visant 800 mots de corps MAXIMUM au total : "
                                "va à l'essentiel, fusionne les redites, ta réponse JSON "
                                "complète doit tenir en moins de 4000 tokens."),
                }]
                continue
            except Exception as e:
                err = str(e)
                if "429" in err or "rate_limit" in err.lower():
                    if _est_quota_journalier(err):
                        # Lire le solde RÉEL avant de condamner la clé : un
                        # 429 « per day » peut venir d'une requête trop grosse
                        # pour le solde restant, pas d'une clé vide.
                        restant = _tpd_restant(err)
                        prompt_est = int(sum(len(m.get("content", "")) for m in messages) / 3.3)
                        # Constat du 21/07 : marge de 2200 + plancher de
                        # réservation à 1500 pouvaient exiger un solde réel
                        # bien supérieur à ce qu'exprimait la condition (le
                        # max(1500,...) pouvait dépasser restant-prompt_est-300
                        # et redemander plus que ce qui restait). Sur ce run,
                        # 18 clés avaient un solde réel (22 à 7869 tokens) mais
                        # aucune n'a jamais atteint cette marge — le repêchage
                        # ne s'est JAMAIS déclenché. Reformulé pour que la
                        # réservation soit toujours strictement bornée par le
                        # solde réel (pas de plancher qui la dépasse) : la
                        # troncature JSON qui en résulterait est déjà gérée
                        # séparément par la relance à réservation élargie.
                        MARGE_MIN_COMPLETION = 1200  # en dessous, JSON quasi toujours coupé
                        SECURITE = 200
                        if restant is not None and restant > prompt_est + MARGE_MIN_COMPLETION + SECURITE:
                            reservation = restant - prompt_est - SECURITE
                            try:
                                print(f"     [GROQ] {label} : solde journalier ~{restant} tokens — "
                                      f"nouvel essai avec réservation réduite à {reservation}")
                                raw = _groq_call(key, messages, max_tokens=reservation)
                                break
                            except Exception:
                                pass  # échec confirmé → clé morte ci-dessous
                        _CLES_MORTES_JOUR.add(key)
                        print(f"     [GROQ] {label} : quota JOURNALIER épuisé"
                              f"{f' (solde ~{restant} tokens, insuffisant)' if restant is not None else ''}"
                              f" — retirée de la rotation pour ce run")
                        # Message BRUT de Groq (21/07, doute de Nahil sur une
                        # possible confusion TPD/TPM) — tronqué à 300 car. pour
                        # ne pas polluer les logs, mais suffisant pour vérifier
                        # noir sur blanc "per day" vs "per minute" sans se fier
                        # à notre seule classification.
                        print(f"     [GROQ-BRUT] {err[:300]}")
                        continue
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
        if not [(k, l) for k, l in _all_keys if k and k not in _CLES_MORTES_JOUR]:
            raise QuotaJournalierEpuise(
                "Toutes les clés Groq ont épuisé leur quota journalier (TPD)")
        raise RuntimeError(f"Quota Groq épuisé sur toutes les clés après {MAX_RETRY_CYCLES} cycles d'attente")

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
    # Vrai titre de l'article/dépêche source (pas le nom du média) : le LLM
    # laisse souvent le champ 'titre' vide, la section SOURCES n'affichait
    # alors que « Média · Lire la source » sans intitulé (constat 19/07). On
    # réinjecte le titre réel remonté par DuckDuckGo/RSS quand il manque.
    real_headline_by_url = {
        s["url"]: (s.get("title") or "").strip()
        for s in real_sources if (s.get("title") or "").strip()
    }
    if "sources" in art:
        verified = []
        for src in art["sources"]:
            if not isinstance(src, dict):
                continue
            url = src.get("url") or ""
            path = urlparse(url).path.rstrip("/") if url else ""
            if not _est_source_citables(url):
                continue  # marchand/social — jamais une source, quel que soit le chemin d'entrée
            if url in real_urls and len(path) > 3 and urlparse(url).scheme in ("http", "https"):
                src = dict(src)
                src["institution"] = real_title_by_url.get(url, src.get("institution", ""))
                if not (src.get("titre") or "").strip():
                    headline = real_headline_by_url.get(url, "")
                    # Ne pas dupliquer le nom du média comme titre
                    if headline and headline.lower() != (src.get("institution") or "").lower():
                        src["titre"] = headline
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
    # Le LLM peut renvoyer "label_gauche": null ou des acteurs incomplets —
    # .get(clé, défaut) ne remplace pas un null existant (affichait "None"
    # aux deux extrémités de l'axe). On filtre aussi les acteurs sans nom ou
    # sans position numérique, et on borne la position à [0, 100].
    label_g = positions.get("label_gauche") or "Favorable"
    label_d = positions.get("label_droite") or "Critique"
    # Un acteur dont le DÉTAIL indique qu'aucune position n'est rapportée
    # (le LLM le génère quand même, avec une position inventée) ne doit PAS
    # figurer sur le curseur — sinon on affiche une prise de position là où
    # la légende dit « aucune position rapportée » (bug du 19/07, article
    # pompiers volontaires). On masque ces acteurs incertains.
    _SANS_POSITION_RE = re.compile(
        r"aucune prise de position|aucune position|non rapport|pas de position|"
        r"n['’]est pas rapport|position (?:inconnue|incertaine|non établie)|"
        r"ne se prononce pas|non précisée?|indéterminée?",
        re.IGNORECASE,
    )
    acteurs = []
    for a in positions["acteurs"]:
        if not isinstance(a, dict) or not a.get("nom"):
            continue
        if _SANS_POSITION_RE.search(str(a.get("detail") or "")):
            continue  # position non attestée → masquée
        try:
            pos = max(0, min(100, float(a.get("position"))))
        except (TypeError, ValueError):
            continue
        acteurs.append({**a, "position": pos})
    # Un spectre n'a de sens qu'avec AU MOINS DEUX camps réellement positionnés
    # (règle 10 du prompt : deux positions opposées, chacune attestée). S'il
    # reste 0 ou 1 acteur après filtrage, on masque tout le bloc plutôt que
    # d'afficher un curseur à un seul point.
    if len(acteurs) < 2:
        return ""
    COLORS = ["#4a90d9", "#e57373", "#66bb6a", "#ffa726", "#ab47bc"]
    markers = "\n".join(
        f'<div class="spectrum__marker" style="left:{a["position"]:g}%">'
        f'<span class="spectrum__marker-dot" style="background:{COLORS[i % len(COLORS)]}"></span>'
        f'</div>'
        for i, a in enumerate(acteurs)
    )
    legend_items = "\n".join(
        f'<div class="spectrum__legend-item">'
        f'<span class="spectrum__legend-dot" style="background:{COLORS[i % len(COLORS)]}"></span>'
        f'<span class="spectrum__legend-name">{_esc(a["nom"])}</span>'
        f'<span class="spectrum__legend-sub">{_esc(a.get("detail") or "")}</span>'
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
    # Fallback par CATÉGORIE en anglais : envoyer un titre français brut à
    # Pexels (moteur anglophone) renvoie des images génériques hors-sujet —
    # une plage de bord de mer sur un article pompiers, p.ex. (constat 19/07,
    # l'extraction LLM échouait sous rate limit et retombait sur le titre FR).
    # Mieux vaut une image neutre mais cohérente avec la rubrique.
    _FALLBACK_CATEGORIE = {
        "sante": "hospital medical laboratory",
        "science": "science laboratory research",
        "economie": "office business finance city",
        "tech": "technology computer data center",
        "environnement": "nature landscape environment",
        "societe": "city street people france",
    }
    fallback_kw = _FALLBACK_CATEGORIE.get((category or "").lower(), "france city landscape")

    key = GROQ_ALL_KEYS[0][0] if GROQ_ALL_KEYS else ""
    if not key:
        return fallback_kw
    try:
        messages = [{
            "role": "user",
            "content": (
                f"Article: {title}\n"
                f"Summary: {summary[:200]}\n"
                f"Category: {category}\n\n"
                "Extract 3-4 English keywords to search for a relevant stock photo illustration. "
                "Prefer concrete visual subjects (place, object, event, scene). "
                "If the subject is specifically about women/girls or men/boys "
                "(e.g. women's sport, a female athlete), include 'women' or 'men' "
                "in the keywords so the photo matches — never a mismatched gender. "
                "Avoid abstract concepts. "
                "Reply with ONLY the keywords separated by spaces, nothing else."
            )
        }]
        result = _groq_call(key, messages, max_tokens=30)
        # Nettoyer la réponse (parfois entre guillemets ou avec ponctuation)
        clean = re.sub(r'[^\w\s]', '', result).strip().lower()
        # Un mot-clé anglophone plausible contient surtout de l'ASCII : si la
        # réponse est vide ou visiblement restée en français, prendre le
        # fallback catégorie plutôt qu'un titre FR inutilisable par Pexels.
        kw = clean[:80] if clean else fallback_kw
        # Garde-fou déterministe : sujet explicitement féminin (titre FR) →
        # forcer "women" si le LLM ne l'a pas mis (photo d'hommes sur un
        # article "CAN féminine", constat 26/07).
        if re.search(r"f[ée]minin|f[ée]minine|\bfemmes?\b|\bdames?\b", title or "", re.IGNORECASE):
            if "women" not in kw and "woman" not in kw:
                kw = f"women {kw}"
        return kw
    except Exception:
        return fallback_kw


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
    Ne touche pas au fichier si l'optimisation ne réduit pas sa taille.
    Génère aussi les variantes WebP (pleine taille + vignette 480px) servies
    par les templates — le JPEG reste la source de vérité (og:image, RSS,
    newsletter, fallback <picture>)."""
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
        _make_webp_variants(p, img=img)
    except Exception as e:
        print(f"  [WARN] optimisation image {path}: {e}")


def _make_webp_variants(jpg_path: str, img=None) -> None:
    """Écrit slug.webp (≤1200px, q80) et slug-480.webp (≤480px, q78) à côté
    du JPEG. Les cartes s'affichent à 400×110 ou 80×54 : servir le 1200px
    partout gaspillait ~80 % du poids transféré."""
    from PIL import Image
    if img is None:
        img = Image.open(jpg_path)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
    base, _ = os.path.splitext(str(jpg_path))
    img.save(base + ".webp", "WEBP", quality=80, method=6)
    thumb = img
    if img.width > 480:
        ratio = 480 / img.width
        thumb = img.resize((480, int(img.height * ratio)), Image.LANCZOS)
    thumb.save(base + "-480.webp", "WEBP", quality=78, method=6)


def _ensure_webp_variants(img_dir: str = "assets/images") -> None:
    """Auto-réparation à chaque run : génère les variantes WebP manquantes
    pour tout JPEG du dossier (images ajoutées par d'autres scripts, stock
    historique). Ne réécrit jamais une variante existante."""
    from pathlib import Path as _P
    made = 0
    for jpg in _P(img_dir).glob("*.jpg"):
        if jpg.stem.endswith("-480"):
            continue
        base = str(jpg)[: -len(".jpg")]
        if os.path.exists(base + ".webp") and os.path.exists(base + "-480.webp"):
            continue
        try:
            _make_webp_variants(str(jpg))
            made += 1
        except Exception as e:
            print(f"  [WARN] variantes WebP {jpg.name}: {e}")
    if made:
        print(f"  [images] {made} jeu(x) de variantes WebP générés")


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
    1. Pexels (photos de stock modernes, professionnelles, jamais de gravures
       ni de vrais patients — c'est la source par défaut depuis juillet 2026 :
       Wikimedia en premier servait des gravures du XVIIIe et des photos
       médicales de patients réels identifiables)
    2. Wikimedia Commons (fallback, filtré : jamais pour la catégorie santé,
       jamais d'œuvres d'art/scans de musée)
    3. og-default.jpg

    Retourne (source_type, credit) ex: ("pexels", "Pexels / John Doe")
    """
    import urllib.parse
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    hdrs = {"User-Agent": "LesFaits/1.1 (lesfaits.contact@gmail.com)"}

    # Noms de fichier suspects : cartes/logos/schémas, MAIS AUSSI tout ce qui
    # trahit une œuvre d'art ou un scan d'archive (gravures, lithographies,
    # collections de musée type Wellcome) — Wikimedia en est saturé et une
    # gravure satirique du XVIIIe a déjà illustré un article nutrition.
    _BAD = (
        "map", "flag", "logo", "icon", "diagram", "chart", "graph", "coat",
        "blason", "carte", "drapeau", "schema", "plan_", "seal_", "emblem",
        "stamp", "badge", "symbol", "sign_", "portrait_", "headshot",
        "engraving", "etching", "woodcut", "lithograph", "gravure", "estampe",
        "drawing", "sketch", "painting", "tableau", "manuscript", "manuscrit",
        "wellcome", "folio", "plate_", "illustration_", "caricature",
        "patient", "autopsy", "cadaver", "surgery_", "wound",
    )
    # Termes d'œuvre d'art dans les métadonnées Wikimedia (catégories/description)
    _ART_META = (
        "engraving", "etching", "woodcut", "lithograph", "painting", "drawing",
        "watercolor", "watercolour", "manuscript", "wellcome collection",
        "wellcome images", "art of", "oil on canvas", "18th century",
        "17th century", "19th century", "medieval", "caricature", "satirical",
        "patients", "medical illustration",
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

    # ── 1. Pexels — source PRINCIPALE (photos pro, jamais d'archives) ────────
    if PEXELS_KEY:
        try:
            r = requests.get(
                "https://api.pexels.com/v1/search",
                params={"query": vis_kw, "orientation": "landscape",
                        "per_page": 10, "size": "large"},
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

    # ── 2. Wikimedia Commons — fallback filtré ───────────────────────────────
    # JAMAIS pour la santé : Commons contient des photos de patients réels
    # identifiables (une photo d'enfant malade a déjà illustré un article).
    if category != "sante":
        try:
            params = urllib.parse.urlencode({
                "action": "query", "format": "json", "generator": "search",
                "gsrnamespace": "6", "gsrsearch": vis_kw, "gsrlimit": "20",
                "prop": "imageinfo",
                "iiprop": "url|size|mime|extmetadata", "iiurlwidth": "1200"
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
                # Métadonnées : rejeter œuvres d'art, scans d'archives, patients
                meta = ii.get("extmetadata") or {}
                meta_txt = " ".join(
                    str((meta.get(k) or {}).get("value", ""))
                    for k in ("Categories", "ImageDescription", "ObjectName")
                ).lower()
                if any(t in meta_txt for t in _ART_META):
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

# ── Lecteur audio (synthèse vocale navigateur, Web Speech API) ─────────────────
# Aucune API externe, aucun fichier audio généré : le texte est lu directement
# depuis le DOM déjà rendu (chapeau + faits + contexte + nuances), donc jamais
# désynchronisé du contenu affiché. Découpage phrase par phrase — lire un très
# long texte en un seul utterance fait planter la synthèse de Chrome après
# ~15s de silence interne (bug connu) ; la lecture par petits segments contourne
# le problème ET permet un vrai pause/reprise/progression.
AUDIO_PLAYER_HTML = """<div class="audio-player" id="audio-player" style="display:none">
  <div class="audio-player__row">
    <button type="button" class="audio-player__btn" id="audio-play" aria-pressed="false">
      <span class="audio-player__icon" id="audio-icon">🔊</span>
      <span id="audio-label">Écouter cet article</span>
    </button>
    <button type="button" class="audio-player__ctrl audio-player__ctrl--stop" id="audio-stop" aria-label="Arrêter la lecture" style="display:none">⏹</button>
  </div>
  <div class="audio-player__progress" id="audio-progress-wrap" style="display:none"><div class="audio-player__bar" id="audio-bar"></div></div>
  <div class="audio-player__settings" id="audio-settings" style="display:none">
    <label class="audio-player__setting-label" for="audio-speed">Vitesse</label>
    <select class="audio-player__select" id="audio-speed" aria-label="Vitesse de lecture">
      <option value="0.85">0.85×</option>
      <option value="1" selected>1×</option>
      <option value="1.15">1.15×</option>
      <option value="1.35">1.35×</option>
    </select>
  </div>
</div>"""

# Menu flottant + moteur audio persistant + navigation douce — injectés
# une seule fois par page via _build_footer(), jamais recréés lors d'une
# navigation interne (voir soft-nav plus bas) afin que la lecture survive
# au passage vers une autre page du site.
# AUDIO_GLOBAL_VERSION : à incrémenter à CHAQUE modification du bloc ci-dessous.
# patch_articles.py compare cette version aux sentinelles présentes dans les
# pages déjà publiées et remplace le bloc entier si elle diffère — sans ça,
# les articles patchés une première fois garderaient l'ancien moteur pour
# toujours (le simple marqueur "LFAudio existe" ne détecte pas les évolutions).
AUDIO_GLOBAL_VERSION = 9
AUDIO_GLOBAL_HTML = f"""<!-- LF_AUDIO_GLOBAL_START v{AUDIO_GLOBAL_VERSION} -->""" + """<div class="audio-float" id="audio-float" style="display:none" role="region" aria-label="Lecture audio en cours">
  <button type="button" class="audio-float__ctrl" id="audio-float-prev" aria-label="Phrase précédente"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4.6 3v10" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><path d="M12.4 3.6v8.8a.5.5 0 0 1-.8.4L6.2 8.4a.5.5 0 0 1 0-.8l5.4-4.4a.5.5 0 0 1 .8.4z" fill="currentColor"/></svg></button>
  <button type="button" class="audio-float__ctrl audio-float__ctrl--play" id="audio-float-play" aria-label="Lecture/Pause">
    <span id="audio-float-icon"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M5.2 3.2v9.6M10.8 3.2v9.6" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg></span>
  </button>
  <button type="button" class="audio-float__ctrl" id="audio-float-next" aria-label="Phrase suivante"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M11.4 3v10" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><path d="M3.6 3.6v8.8a.5.5 0 0 0 .8.4l5.4-4.4a.5.5 0 0 0 0-.8L4.4 3.2a.5.5 0 0 0-.8.4z" fill="currentColor"/></svg></button>
  <div class="audio-float__info">
    <span class="audio-float__title" id="audio-float-title"></span>
    <span class="audio-float__time" id="audio-float-time"></span>
  </div>
  <button type="button" class="audio-float__ctrl audio-float__ctrl--close" id="audio-float-close" aria-label="Fermer la lecture"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 4 8 8M12 4l-8 8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg></button>
</div>
<script>
(function(){
  // ── Lecteur audio PERSISTANT ────────────────────────────────────────────
  // Vit dans le pied de page, chargé une seule fois par vraie navigation
  // (jamais recréé par la navigation douce ci-dessous) : l'état de lecture
  // (segments, index, voix, vitesse) survit donc quand on quitte la page de
  // l'article en cours vers l'accueil ou un autre article.
  if(!('speechSynthesis' in window)){window.LFAudio={attachArticle:function(){}};return;}
  var floatBar=document.getElementById('audio-float'),
      floatPlay=document.getElementById('audio-float-play'),
      floatIcon=document.getElementById('audio-float-icon'),
      floatPrev=document.getElementById('audio-float-prev'),
      floatNext=document.getElementById('audio-float-next'),
      floatClose=document.getElementById('audio-float-close'),
      floatTitle=document.getElementById('audio-float-title'),
      floatTime=document.getElementById('audio-float-time');

  var segments=[],idx=0,playing=false,paused=false,rate=1,voice=null,voicesReady=false;
  try{
    var savedRate=localStorage.getItem('lesfaits_audio_rate');
    if(savedRate)rate=parseFloat(savedRate)||1;
  }catch(e){}

  function pickVoice(){
    var all=speechSynthesis.getVoices();
    if(!all.length)return false;
    var fr=all.filter(function(v){return v.lang&&v.lang.toLowerCase().indexOf('fr')===0;});
    if(!fr.length)fr=all;
    voice=fr.find(function(v){return v.name.indexOf('Google')!==-1;})||fr[0];
    return true;
  }
  function ensureVoiceLoaded(cb){
    if(voicesReady){cb();return;}
    if(pickVoice()){voicesReady=true;cb();return;}
    var done=false;
    var onChange=function(){
      if(done)return;
      if(pickVoice()){done=true;voicesReady=true;speechSynthesis.removeEventListener('voiceschanged',onChange);cb();}
    };
    speechSynthesis.addEventListener('voiceschanged',onChange);
    setTimeout(function(){
      if(done)return;
      done=true;
      speechSynthesis.removeEventListener('voiceschanged',onChange);
      pickVoice();
      voicesReady=true;
      cb();
    },400);
  }
  ensureVoiceLoaded(function(){});

  function clearHighlight(){
    segments.forEach(function(s){if(s.node)s.node.classList.remove('audio-reading');});
  }
  function remainingWords(){
    var w=0;
    for(var i=idx;i<segments.length;i++)w+=segments[i].words;
    return w;
  }
  function formatTime(sec){
    sec=Math.max(0,Math.round(sec));
    var m=Math.floor(sec/60),s=sec%60;
    return m+':'+(s<10?'0':'')+s;
  }
  // Compte à rebours en temps réel : l'estimation (mots restants / débit)
  // n'est recalculée qu'à chaque changement de phrase — entre deux phrases,
  // un ticker décrémente l'affichage seconde par seconde à partir de la
  // dernière estimation, pour que le temps restant vive sous les yeux du
  // lecteur au lieu de sauter par à-coups.
  var estBase=0,estBaseAt=0,tickTimer=null;
  function displayRemaining(sec){
    if(!floatTime)return;
    floatTime.textContent=formatTime(sec)+' restant'+(sec>=60?'es':'');
  }
  function startTicker(){
    stopTicker();
    tickTimer=setInterval(function(){
      if(!playing||paused)return;
      var left=estBase-(Date.now()-estBaseAt)/1000;
      displayRemaining(Math.max(left,1));
    },1000);
  }
  function stopTicker(){
    if(tickTimer){clearInterval(tickTimer);tickTimer=null;}
  }
  function updateProgress(){
    var local=document.getElementById('audio-bar'),
        wrap=document.getElementById('audio-progress-wrap');
    // Ces éléments locaux n'existent que si on est ENCORE sur la page de
    // l'article en cours de lecture — absents après navigation, sans risque.
    if(local&&segments.length)local.style.width=((idx/segments.length)*100)+'%';
    if(segments.length){
      estBase=remainingWords()/(2.5*rate);
      estBaseAt=Date.now();
      displayRemaining(estBase);
    }
  }
  function speakNext(){
    if(idx>=segments.length){stop();return;}
    var seg=segments[idx];
    clearHighlight();
    if(seg.node)seg.node.classList.add('audio-reading');
    var u=new SpeechSynthesisUtterance(seg.text);
    u.lang='fr-FR';
    if(voice)u.voice=voice;
    u.rate=rate;
    u.onend=function(){
      if(!playing||paused)return;
      idx++;
      updateProgress();
      speakNext();
    };
    u.onerror=function(){
      if(!playing||paused)return;
      idx++;
      speakNext();
    };
    speechSynthesis.speak(u);
  }
  // Icônes SVG (jamais d'emoji : Android/Windows les rendent en glyphes
  // colorés hors charte, impossible à styler en CSS).
  var SVG_PAUSE='<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M5.2 3.2v9.6M10.8 3.2v9.6" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>';
  var SVG_PLAY='<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M5.2 3.4v9.2a.5.5 0 0 0 .77.42l7-4.6a.5.5 0 0 0 0-.84l-7-4.6a.5.5 0 0 0-.77.42z" fill="currentColor"/></svg>';
  function setFloatIcon(playIcon){
    if(floatIcon)floatIcon.innerHTML=playIcon?SVG_PAUSE:SVG_PLAY;
  }
  function localEls(){
    return {
      play:document.getElementById('audio-play'),
      icon:document.getElementById('audio-icon'),
      label:document.getElementById('audio-label'),
      stop:document.getElementById('audio-stop'),
      progressWrap:document.getElementById('audio-progress-wrap'),
      settings:document.getElementById('audio-settings'),
    };
  }
  function setLocalPlayingUI(isPlaying){
    var l=localEls();
    if(l.icon)l.icon.textContent=isPlaying?'⏸':'🔊';
    if(l.label)l.label.textContent=isPlaying?'Pause':'Écouter cet article';
    if(l.stop)l.stop.style.display=isPlaying?'inline-flex':'none';
    if(l.progressWrap)l.progressWrap.style.display=isPlaying?'block':'none';
    // Réglage de vitesse masqué tant que la lecture n'a pas démarré : allège
    // le haut de l'article (constat 20/07, Nahil) — il n'a d'utilité qu'une
    // fois la lecture en cours.
    if(l.settings)l.settings.style.display=isPlaying?'flex':'none';
    if(l.play)l.play.setAttribute('aria-pressed',isPlaying?'true':'false');
  }
  function start(){
    playing=true;paused=false;
    setLocalPlayingUI(true);
    if(floatBar)floatBar.style.display='flex';
    setFloatIcon(true);
    updateProgress(); // affiche le temps restant dès l'ouverture du menu, pas après la 1re phrase
    startTicker();
    speakNext();
  }
  function stop(){
    playing=false;paused=false;idx=0;
    stopTicker();
    speechSynthesis.cancel();
    clearHighlight();
    setLocalPlayingUI(false);
    if(floatBar)floatBar.style.display='none';
    updateProgress();
  }
  function togglePlayPause(){
    if(!playing)return;
    if(paused){
      paused=false;
      speechSynthesis.resume();
      setLocalPlayingUI(true);
      setFloatIcon(true);
      updateProgress(); // repart d'une estimation fraîche, la pause a figé le temps
    }else{
      paused=true;
      speechSynthesis.pause();
      var l=localEls();
      if(l.icon)l.icon.textContent='▶';
      if(l.label)l.label.textContent='Reprendre';
      setFloatIcon(false);
    }
  }
  function jumpTo(newIdx){
    if(!playing)return;
    idx=Math.max(0,Math.min(segments.length-1,newIdx));
    speechSynthesis.cancel();
    updateProgress();
    if(!paused)speakNext();
  }

  if(floatPlay)floatPlay.addEventListener('click',togglePlayPause);
  if(floatPrev)floatPrev.addEventListener('click',function(){jumpTo(idx-1);});
  if(floatNext)floatNext.addEventListener('click',function(){jumpTo(idx+1);});
  if(floatClose)floatClose.addEventListener('click',stop);

  window.addEventListener('pagehide',function(){speechSynthesis.cancel();});
  window.addEventListener('beforeunload',function(){speechSynthesis.cancel();});

  // ── Rattachement à la page COURANTE ─────────────────────────────────────
  // Appelé au chargement initial ET après chaque navigation douce : (re)lie
  // le bouton "Écouter cet article" de la page affichée, sans jamais toucher
  // à une lecture déjà en cours tant que l'utilisateur ne reclique pas.
  window.LFAudio={
    attachArticle:function(){
      var playBtn=document.getElementById('audio-play'),
          stopBtn=document.getElementById('audio-stop'),
          speedSel=document.getElementById('audio-speed');
      if(speedSel){
        speedSel.value=String(rate);
        speedSel.addEventListener('change',function(){
          rate=parseFloat(speedSel.value)||1;
          try{localStorage.setItem('lesfaits_audio_rate',String(rate));}catch(e){}
          updateProgress();
        });
      }
      if(!playBtn)return; // page sans lecteur (accueil, catégories…)
      var wrap=document.getElementById('audio-player');
      // Le bouton n'apparaît que si le navigateur sait vraiment synthétiser —
      // évite un bouton mort sur les navigateurs sans TTS (déjà garanti ici
      // puisque tout ce script sort tôt si speechSynthesis est absent).
      if(wrap)wrap.style.display='block';
      playBtn.addEventListener('click',function(){
        if(playing){togglePlayPause();return;}
        // Construit les segments à partir du DOM affiché À L'INSTANT du clic
        // (jamais mis en cache) : résumé + paragraphe suivant chaque <h2>.
        var nodes=[];
        var resumeEl=document.querySelector('.art__resume');
        if(resumeEl)nodes.push(resumeEl);
        document.querySelectorAll('.art__h2').forEach(function(h2){
          var p=h2.nextElementSibling;
          if(p&&p.tagName==='P')nodes.push(p);
        });
        if(!nodes.length)return;
        var built=[];
        nodes.forEach(function(node){
          var text=node.textContent.trim();
          if(!text)return;
          var sentences=text.match(/[^.!?]+[.!?]+(\s+|$)/g)||[text];
          sentences.forEach(function(s){
            s=s.trim();
            if(s)built.push({text:s,node:node,words:s.split(/\s+/).length});
          });
        });
        if(!built.length)return;
        segments=built;idx=0;
        var titleEl=document.querySelector('.art__title');
        if(floatTitle)floatTitle.textContent=titleEl?titleEl.textContent.trim():'';
        ensureVoiceLoaded(start);
      });
      if(stopBtn)stopBtn.addEventListener('click',stop);
    }
  };
  window.LFAudio.attachArticle();
})();
</script>
<script>
(function(){
  // ── Navigation douce (interne au site) ──────────────────────────────────
  // But : garder le lecteur audio (et le menu flottant) actifs quand on
  // quitte la page de l'article en cours d'écoute — un vrai rechargement de
  // page couperait immédiatement speechSynthesis (contrainte du navigateur,
  // aucun code ne peut l'éviter). On intercepte donc les clics sur les liens
  // internes, on va chercher le HTML de la page suivante en arrière-plan et
  // on ne remplace QUE le contenu de <main> — le pied de page (et donc le
  // moteur audio ci-dessus) n'est jamais recréé, son état persiste.
  function isSoftNavLink(a){
    if(!a||!a.href)return false;
    if(a.origin!==location.origin)return false;
    if(a.hasAttribute('download'))return false;
    if(a.target&&a.target!=='_self')return false;
    var rel=a.getAttribute('rel')||'';
    if(rel.indexOf('external')!==-1)return false;
    if(/\.(xml|json|ico|pdf|jpg|jpeg|png|webp|svg)$/i.test(a.pathname))return false;
    // Ancre vers la même page (ex: #newsletter) : laisser le scroll natif.
    if(a.pathname===location.pathname&&a.hash)return false;
    return true;
  }

  function runScripts(container){
    // innerHTML n'exécute jamais les <script> qu'il insère : on les recrée
    // pour forcer l'exécution (barre de progression, boutons de partage,
    // favoris, etc. — tout ce qui est injecté par générer_article()).
    container.querySelectorAll('script').forEach(function(old){
      if(old.type==='application/ld+json')return; // données seules
      // try/catch par script : une erreur de syntaxe dans UN script de la
      // page cible (elle serait tout aussi cassée en chargement normal) ne
      // doit ni bloquer les scripts suivants ni faire échouer la navigation
      // douce — sans ça, l'exception remonterait au .catch() de navigateTo
      // qui déclencherait un rechargement complet et couperait la lecture.
      try{
        var s=document.createElement('script');
        for(var i=0;i<old.attributes.length;i++)s.setAttribute(old.attributes[i].name,old.attributes[i].value);
        s.textContent=old.textContent;
        old.parentNode.replaceChild(s,old);
      }catch(err){
        if(window.console&&console.warn)console.warn('[soft-nav] script ignoré:',err);
      }
    });
  }

  // Zone page-spécifique = TOUS les nœuds du <body> entre </header> et
  // <footer>, pas seulement <main> : l'accueil a son manifeste ("100 % IA")
  // AVANT <main>, les autres pages ont la newsletter APRÈS </main> — ne
  // remplacer que <main> laissait ces blocs de l'ancienne page collés à la
  // nouvelle (bug repéré le 13/07 : manifeste de l'accueil affiché au-dessus
  // du contenu de l'archive après navigation).
  function pageZone(rootDoc){
    var body=rootDoc.body;
    if(!body)return null;
    var nodes=[],started=false;
    for(var n=body.firstChild;n;n=n.nextSibling){
      if(n.nodeType===1&&n.tagName==='HEADER'){started=true;continue;}
      if(n.nodeType===1&&n.tagName==='FOOTER')break;
      if(started)nodes.push(n);
    }
    var footer=body.querySelector(':scope > footer');
    return (started&&footer)?{nodes:nodes,footer:footer}:null;
  }

  // Jeton de navigation : deux clics rapprochés (ex. newsletter puis logo)
  // déclenchent deux navigateTo() qui se chevauchent. Sans garde, le scroll
  // DIFFÉRÉ du premier clic (jusqu'à 300ms + 2 frames, pour une ancre) peut
  // s'exécuter APRÈS le scrollTo(0,0) immédiat du second clic et l'écraser —
  // bug observé le 15/07 : clic newsletter puis clic logo → on retombait sur
  // la section newsletter au lieu du haut de page. Chaque navigateTo() prend
  // un numéro ; toute application de résultat (DOM, scroll) vérifie qu'elle
  // est toujours la navigation la plus récente avant d'agir.
  var navSeq=0;
  function navigateTo(url,isPop){
    var myNav=++navSeq;
    var cur=pageZone(document);
    if(!cur){location.href=url;return;}
    fetch(url).then(function(r){
      if(!r.ok)throw new Error('HTTP '+r.status);
      return r.text();
    }).then(function(html){
      if(myNav!==navSeq)return; // une navigation plus récente a démarré entre-temps
      var doc=new DOMParser().parseFromString(html,'text/html');
      var next=pageZone(doc);
      if(!next){location.href=url;return;} // page hors gabarit (404, confirmation…) : navigation classique
      document.title=doc.title;
      cur.nodes.forEach(function(n){n.parentNode&&n.parentNode.removeChild(n);});
      var inserted=[];
      next.nodes.forEach(function(n){
        var imported=document.importNode(n,true);
        cur.footer.parentNode.insertBefore(imported,cur.footer);
        inserted.push(imported);
      });
      if(!isPop)history.pushState({},'',url);
      // Respecter l'ancre de destination (ex: /a-propos.html#reseaux) :
      // scroller vers l'élément cible plutôt qu'en haut de page. Différé
      // d'une frame : scroller pendant que le navigateur calcule encore la
      // mise en page des nœuds fraîchement insérés donne une position fausse.
      var hash='';
      try{hash=new URL(url,location.origin).hash;}catch(err){}
      if(hash){
        // Ancre : ne pas remonter en haut (évite le flash top→bas sur mobile)
        // Deux rAF + délai pour laisser le layout se stabiliser après insertion.
        requestAnimationFrame(function(){
          requestAnimationFrame(function(){
            setTimeout(function(){
              if(myNav!==navSeq)return; // navigation suivante déjà en cours : ne pas écraser son scroll
              var target=document.querySelector(hash);
              if(target)target.scrollIntoView({behavior:'smooth',block:'start'});
            },300);
          });
        });
      } else {
        window.scrollTo(0,0);
      }
      inserted.forEach(function(n){
        if(n.nodeType!==1)return;
        if(n.tagName==='SCRIPT'){
          // Script directement enfant de <body> dans la zone : le recréer
          var s=document.createElement('script');
          for(var i=0;i<n.attributes.length;i++)s.setAttribute(n.attributes[i].name,n.attributes[i].value);
          s.textContent=n.textContent;
          try{n.parentNode.replaceChild(s,n);}catch(err){}
          return;
        }
        runScripts(n);
      });
      if(window.LFAudio)window.LFAudio.attachArticle();
    }).catch(function(){location.href=url;}); // repli : navigation classique si le fetch échoue
  }

  document.addEventListener('click',function(e){
    if(e.defaultPrevented||e.button!==0||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey)return;
    var a=e.target.closest('a[href]');
    if(!isSoftNavLink(a))return;
    e.preventDefault();
    navigateTo(a.href,false);
  });
  window.addEventListener('popstate',function(){navigateTo(location.href,true);});
})();
</script>
<!-- LF_AUDIO_GLOBAL_END -->
"""

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
    'connect-src \'self\' https://cloud.umami.is https://api.web3forms.com https://e6ad0381.sibforms.com; '
    'base-uri \'self\'; '
    'form-action \'self\'; '
    'frame-ancestors \'none\';"/>'
)

# Formulaire HÉBERGÉ Brevo (sibforms) : endpoint public par conception, AUCUNE
# clé API côté client (l'ancienne injection de BREVO_CONTACTS_KEY dans le HTML
# exposait une clé à droits complets — fuite corrigée en juillet 2026).
# Le double opt-in et la liste cible sont configurés dans Brevo, côté serveur.
SIBFORMS_URL = "https://e6ad0381.sibforms.com/serve/MUIFAErfidn3h7DoaZcjIRh-48s1GoiE0vZOe_KG-skCwDznnQ2831i0IkHsSaXfUJ15hBl1CH3ElJVKdGDdXdxHpt6v7iX-hAlyWb0i0M7mtq6UhgJ9JJyCUhNwckwfxW8EUJkF_hkjb4qX8YSntlFraZFiCcgQhZ3PXsPvAcSa9oEyPOgeL1EtAB4akgMS-hz76NcGAUSqOt3L1w=="

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
        <input type="email" id="nl-email" name="EMAIL" class="nl-compact__input" placeholder="vous@exemple.fr" required autocomplete="email" aria-required="true"/>
        <button type="submit" class="nl-compact__btn" id="nl-btn">S'abonner →</button>
      </div>
      <div class="nl-compact__cats" role="group" aria-label="Rubriques">
        <label class="nl-compact__cat nl-cat--societe"><input type="checkbox" name="CAT_SOCIETE" value="1"/><span class="nl-cat__dot" aria-hidden="true"></span>Société</label>
        <label class="nl-compact__cat nl-cat--science"><input type="checkbox" name="CAT_SCIENCE" value="1"/><span class="nl-cat__dot" aria-hidden="true"></span>Science</label>
        <label class="nl-compact__cat nl-cat--economie"><input type="checkbox" name="CAT_ECONOMIE" value="1"/><span class="nl-cat__dot" aria-hidden="true"></span>Économie</label>
        <label class="nl-compact__cat nl-cat--tech"><input type="checkbox" name="CAT_TECH" value="1"/><span class="nl-cat__dot" aria-hidden="true"></span>Tech</label>
        <label class="nl-compact__cat nl-cat--sante"><input type="checkbox" name="CAT_SANTE" value="1"/><span class="nl-cat__dot" aria-hidden="true"></span>Santé</label>
        <label class="nl-compact__cat nl-cat--environnement"><input type="checkbox" name="CAT_ENVIRONNEMENT" value="1"/><span class="nl-cat__dot" aria-hidden="true"></span>Environnement</label>
      </div>
      <p class="nl-compact__hint">Aucune sélection = toutes les rubriques.</p>
      <label class="nl-compact__consent">
        <input type="checkbox" id="nl-consent" required aria-required="true"/>
        <span>J'accepte de recevoir la newsletter et la <a href="confidentialite.html">politique de confidentialité</a>.</span>
      </label>
      <p class="nl-compact__msg" id="nl-msg" role="alert" aria-live="polite"></p>
    </form>
  </div>
</section>
<script>
(function(){{
  var SIB_URL="{SIBFORMS_URL}";
  var form=document.getElementById("nl-form"),msgEl=document.getElementById("nl-msg"),btn=document.getElementById("nl-btn");
  if(!form)return;
  form.addEventListener("submit",function(e){{
    e.preventDefault();
    msgEl.className="nl-compact__msg";msgEl.textContent="";
    var email=(document.getElementById("nl-email").value||"").trim();
    var consent=document.getElementById("nl-consent").checked;
    if(!email||!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)){{msgEl.textContent="Veuillez saisir une adresse email valide.";msgEl.className="nl-compact__msg nl-compact__msg--err";return;}}
    if(!consent){{msgEl.textContent="Veuillez accepter les conditions.";msgEl.className="nl-compact__msg nl-compact__msg--err";return;}}
    var data=new FormData();
    data.append("EMAIL",email);
    data.append("LESFAITS_VERIFICATION","1");
    ["CAT_SOCIETE","CAT_SCIENCE","CAT_ECONOMIE","CAT_TECH","CAT_SANTE","CAT_ENVIRONNEMENT"].forEach(function(k){{
      var cb=form.querySelector('input[name="'+k+'"]');
      if(cb&&cb.checked)data.append(k,"1");
    }});
    var freqEl=form.querySelector('input[name="FREQ"]:checked');
    data.append("FREQ",freqEl?freqEl.value:"both");
    data.append("email_address_check","");
    data.append("locale","fr");
    btn.disabled=true;btn.textContent="Envoi…";
    fetch(SIB_URL,{{method:"POST",mode:"no-cors",body:data}})
    .then(function(){{
      msgEl.textContent="Un email de confirmation vient de vous être envoyé — cliquez sur le lien pour valider votre inscription (vérifiez vos spams).";
      msgEl.className="nl-compact__msg nl-compact__msg--ok";form.reset();
    }})
    .catch(function(){{msgEl.textContent="Erreur réseau. Réessayez dans un instant.";msgEl.className="nl-compact__msg nl-compact__msg--err";}})
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
</footer>""" + AUDIO_GLOBAL_HTML

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
    """Horodatage ISO 8601 de la GÉNÉRATION réelle de l'article (Paris), avec
    le vrai offset (+01:00 CET / +02:00 CEST). Aligné sur date_pub depuis le
    22/07 (demande de Nahil) : c'est l'heure technique réelle qui fait foi,
    plus le créneau arrondi 07h00/18h00."""
    now = datetime.now(ZoneInfo("Europe/Paris"))
    iso = now.strftime("%Y-%m-%dT%H:%M:%S%z")
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
        f'<picture><source type="image/webp" srcset="{hero_src[:-4]}.webp"/>'
        f'<img class="art__hero" src="{hero_src}" alt="Illustration : {_esc(art["titre"])}" loading="eager" fetchpriority="high" style="aspect-ratio:16/9;object-fit:cover"/></picture>'
        f'</figure>'
    ) if hero_src else ""

    # Sources
    def _source_link(s):
        url = s.get("url") or ""
        parsed = urlparse(url) if url else None
        path = parsed.path.rstrip("/") if parsed else ""
        # Défense en profondeur : les URLs viennent de flux RSS et de moteurs
        # de recherche tiers — seuls http(s) sont insérés en href.
        if url and parsed.scheme in ("http", "https") and len(path) > 3:
            return f' · <a href="{_esc(url)}" target="_blank" rel="noopener noreferrer external" aria-label="{_esc(s.get("institution","Source"))} (ouvre dans un nouvel onglet)">Lire la source →</a>'
        return ""

    verified_sources = [s for s in art.get("sources", []) if s.get("url")
                        and urlparse(s["url"]).scheme in ("http", "https")
                        and len(urlparse(s["url"]).path.rstrip("/")) > 3]
    def _source_date(s):
        # Masquer le champ date quand il est absent (évite d'afficher "None")
        d = s.get("date")
        return f' · {_esc(str(d))}' if d and str(d).strip().lower() not in ("none", "null", "") else ""

    def _source_li(s):
        # Le correcteur LLM peut renvoyer un objet source incomplet — un champ
        # manquant ne doit jamais faire planter le rendu (le crash arrivait
        # après génération + vérification + image : tout le quota perdu).
        institution = s.get("institution") or _media_name_from_url(s.get("url", ""), "") or "Source"
        titre = s.get("titre") or ""
        titre_html = f' · <em>{_esc(titre)}</em>' if titre else ""
        return f'<li><cite>{_esc(institution)}</cite>{titre_html}{_source_date(s)}{_source_link(s)}</li>'

    if verified_sources:
        sources_li = "\n".join(_source_li(s) for s in verified_sources)
        sources_html = f'<section class="sources" aria-label="Sources"><h3>SOURCES</h3><ol>{sources_li}</ol></section>'
    else:
        sources_html = '<section class="sources sources--unverified" aria-label="Sources"><p style="color:#999;font-style:italic;font-size:.85rem;margin:0">Sources citées dans le texte — URLs non vérifiées directement.</p></section>'

    nb_src = len(verified_sources)

    # Temps de lecture — même base que le plancher éditorial et le rapport
    # "Terminé — N mots" (chapeau + corps, voir _mots_totaux) : ce calcul
    # dupliquait auparavant son propre compte (corps seul), d'où le badge
    # public affichant 320 mots quand nb_mots (déjà corrigé) valait 420.
    word_count = _mots_totaux(art)
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
                f'<img src="assets/images/{_slug_ascii(a["slug"])}-480.webp" alt="{a["titre"]}" width="400" height="110" style="width:calc(100% + 32px);margin:-14px -16px 12px;height:110px;object-fit:cover;display:block;border-radius:var(--radius) var(--radius) 0 0">'
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

    # Fusionné avec le badge IA en une seule ligne légère (constat 20/07,
    # Nahil : trop d'éléments empilés en haut d'article) — au lieu de 2 blocs
    # séparés (badge IA + rangée de coches), une seule ligne de texte.
    verify_html = (
        f'<span class="meta__sep" aria-hidden="true">·</span>'
        f'<span class="art__verify-item">✓ {nb_src} source{"s" if nb_src > 1 else ""} vérifiée{"s" if nb_src > 1 else ""}</span>'
        f'<span class="art__verify-item">✓ Sources concordantes</span>'
    ) if nb_src > 0 else ""

    # ── Transparence : pourquoi CET article a été publié ─────────────────────
    # Section de bas de page (pas un compteur qualifié dans les méta) : le
    # protocole de vérification devient l'argument de marque, expliqué en
    # clair plutôt que résumé en badges techniques.
    _bilan = bilan_qualite_sources(verified_sources)
    _statut = art.get("statut_verification", "")
    _statut_txt = {
        "conforme_du_premier_coup": "Le fact-check automatisé n'a relevé aucune anomalie : article publié tel que généré.",
        "corrige_automatiquement":  "Le fact-check automatisé a détecté des écarts, l'article a été corrigé automatiquement puis revalidé avant publication.",
    }.get(_statut, "Vérification antérieure au protocole détaillé ci-dessous.")
    _src_txt_parts = []
    if _bilan["primaire"]:
        _src_txt_parts.append(f'{_bilan["primaire"]} source{"s" if _bilan["primaire"] > 1 else ""} primaire{"s" if _bilan["primaire"] > 1 else ""} (institution, gouvernement, revue scientifique)')
    if _bilan["secondaire"]:
        _src_txt_parts.append(f'{_bilan["secondaire"]} média{"s" if _bilan["secondaire"] > 1 else ""} de référence')
    if _bilan["tertiaire"]:
        _src_txt_parts.append(f'{_bilan["tertiaire"]} source{"s" if _bilan["tertiaire"] > 1 else ""} de contexte')
    _src_txt = ", ".join(_src_txt_parts) if _src_txt_parts else "les sources listées ci-dessus"
    pourquoi_html = f"""<div class="art__pourquoi">
  <h3>Pourquoi cet article a été publié</h3>
  <ul>
    <li><strong>Sources :</strong> {nb_src} source{"s" if nb_src > 1 else ""} distincte{"s" if nb_src > 1 else ""} — {_src_txt}. Notre règle : au moins une source primaire ou deux sources secondaires indépendantes, sinon l'article n'est pas publié.</li>
    <li><strong>Garde-fous éditoriaux :</strong> détection automatique des répétitions, des attributions non sourcées et des tournures génériques avant publication.</li>
    <li><strong>Fact-check :</strong> {_statut_txt}</li>
    <li><strong>Rédaction :</strong> texte entièrement généré par IA (Groq Llama 3.3), jamais de relecture humaine avant mise en ligne — voir <a href="/methode.html">notre méthode</a> pour le détail complet du protocole.</li>
  </ul>
</div>"""

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
  <link rel="stylesheet" href="/src/style.css?v=2"/>
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
      <input type="search" class="header__search-input" aria-label="Rechercher un article" placeholder="Rechercher…" autocomplete="off" onkeydown="if(event.key==='Enter'&&this.value.trim())window.location=(document.querySelector('base').href)+'recherche.html?q='+encodeURIComponent(this.value.trim())"/>
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
    <span class="meta__sep" aria-hidden="true">·</span>
    <span title="Nombre de mots de l'article" style="color:var(--muted);font-size:.85rem">{word_count} mots</span>
  </div>
  <div class="art__ai-badge" role="note">🤖 Rédigé par IA — <a href="methode.html" style="color:inherit;text-decoration:underline">notre méthode</a>{verify_html}</div>
  {AUDIO_PLAYER_HTML}
  <div class="art__rule"></div>
  {hero_img}
  <p class="art__resume">{_esc(resume_txt)}</p>
  <h2 class="art__h2">Les faits</h2><p>{faits}</p>
  <h2 class="art__h2">Contexte</h2><p>{contexte}</p>
  <h2 class="art__h2">Débats et nuances</h2><p>{nuances}</p>
  {build_spectrum_html(art.get("positions", {}))}
  {share_html}
  {sources_html}
  {pourquoi_html}
  {related_html}
  <p class="art__badge">Généré par IA · Protocole Les Faits v1.2 · {date_pub}</p>
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
            f'<img src="assets/images/{_slug_ascii(a["slug"])}-480.webp" alt="{_esc(a["titre"])}" width="400" height="110" style="width:calc(100% + 32px);margin:-14px -16px 12px;height:110px;object-fit:cover;display:block;border-radius:var(--radius) var(--radius) 0 0">'
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
    # Les templates servent des .webp : garantir que chaque JPEG a ses
    # variantes avant de générer le HTML qui les référence.
    _ensure_webp_variants()
    articles = load_index()
    if not articles:
        return

    # Génération des cards "side" (articles 1-3)
    def side_card(a):
        return f"""<a class="une__side-item" href="articles/{a['slug']}.html" style="display:grid;grid-template-columns:64px 1fr;gap:14px;align-items:center">
          <img src="assets/images/{_slug_ascii(a['slug'])}-480.webp" alt="{_esc(a['titre'])}" loading="lazy" style="width:64px;height:64px;object-fit:cover;border-radius:4px;display:block">
          <div>
          <span class="cat cat--{a['categorie']}">{_cat_up(a['categorie'])}</span>
          <h3 class="title-md">{_esc(a['titre'])}</h3>
          <div class="meta"><span class="meta__src">{a['nb_sources']} sources</span>
          <span class="meta__sep">·</span><span>{a['date']}</span></div>
          </div>
        </a>"""

    def mini_card(a):
        return f"""<a class="card3" href="articles/{a['slug']}.html">
          <img class="card3__img" src="assets/images/{_slug_ascii(a['slug'])}-480.webp" alt="{_esc(a['titre'])}" loading="lazy">
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

    # "À la une" : les articles les plus INTÉRESSANTS parmi les récents, pas
    # juste le plus récent (demande de Nahil, 22/07) — nb de sources et
    # longueur comme proxys de substance éditoriale.
    def _interet(a: dict) -> float:
        return a.get("nb_sources", 0) * 10 + min(a.get("nb_mots", 0), 800) / 20

    _MOIS_IDX = {"janvier":1,"février":2,"mars":3,"avril":4,"mai":5,"juin":6,
                 "juillet":7,"août":8,"septembre":9,"octobre":10,"novembre":11,"décembre":12}

    def _parse_date_pub(s: str):
        import re
        m = re.match(r"(\d+)\s+(\w+)\s+(\d+),\s*(\d+)h(\d+)", s or "")
        if not m or m.group(2) not in _MOIS_IDX:
            return None
        j, mois, an, h, mn = m.groups()
        return datetime(int(an), _MOIS_IDX[mois], int(j), int(h), int(mn))

    # Fenêtre glissante de 48h (23/07, retour Nahil : "à la une" doit se
    # renouveler chaque jour) — si moins de 4 articles publiés récemment
    # (créneau calme), on retombe sur les 15 derniers pour garder du choix.
    _seuil_48h = datetime.now() - timedelta(hours=48)
    fenetre_recente = [a for a in articles if (_d := _parse_date_pub(a.get("date", ""))) and _d >= _seuil_48h]
    if len(fenetre_recente) < 4:
        fenetre_recente = articles[:15] if len(articles) > 15 else list(articles)
    fenetre_recente.sort(key=_interet, reverse=True)

    main_art  = fenetre_recente[0]
    used_une  = {main_art["slug"]}
    # Side : 3 articles diversifiés (catégories différentes du main et entre eux),
    # toujours classés par intérêt plutôt que par pure fraîcheur
    side_arts = _pick_diverse(fenetre_recente[1:], 3, used_une)
    used_une.update(a["slug"] for a in side_arts)
    # Grille "Derniers articles" : AUCUNE exclusion, même pas le hero — cette
    # section doit toujours montrer les 6 vrais articles les plus récents
    # (retour Nahil, 23/07 : exclure le hero faisait sauter un article plus
    # récent au profit d'un plus vieux). Le recoupement visuel avec "à la
    # une" est accepté.
    grid_arts = _pick_diverse(articles, 6, set(), force_diversity=False)
    used_grid = {main_art["slug"]}
    used_grid.update(a["slug"] for a in side_arts)
    used_grid.update(a["slug"] for a in grid_arts)
    # Liste "À lire aussi" : 6 articles diversifiés, excluant hero+side+grille
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
  <link rel="stylesheet" href="/src/style.css?v=2"/>
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
      <input type="search" class="header__search-input" aria-label="Rechercher un article" placeholder="Rechercher…" autocomplete="off" onkeydown="if(event.key==='Enter'&&this.value.trim())window.location=(document.querySelector('base').href)+'recherche.html?q='+encodeURIComponent(this.value.trim())"/>
    </div>
    {HEADER_NAV_DESKTOP}
    {DARK_TOGGLE}
    {BURGER_BTN}
  </div>
</header>
<div class="manifeste">
  <div class="manifeste__inner">
    <div class="manifeste__headline">100&nbsp;% IA. <span>0&nbsp;% parti pris.</span></div>
    <a href="methode.html" class="manifeste__link">Notre méthode →</a>
  </div>
</div>
<main id="contenu">
<div class="wrap">
  <div class="une">
    <div class="une__label">À LA UNE</div>
    <div style="height:2px;background:var(--blue);margin-bottom:1px"></div>
    <div class="une__grid">
      <a class="une__main" href="articles/{main['slug']}.html">
        <img src="assets/images/{_slug_ascii(main['slug'])}.webp" alt="{main['titre']}" loading="eager" style="width:calc(100% + 72px);margin:-32px -36px 20px;height:240px;object-fit:cover;display:block">
        <span class="cat cat--{main['categorie']}">{_cat_up(main['categorie'])}</span>
        <h2 class="title-xl">{main['titre']}</h2>
        <p class="excerpt">{resume}</p>
        <div class="meta">
          <span class="meta__src">{main['nb_sources']} sources</span>
          <span class="meta__sep">·</span><span>{main['date']}</span>
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
</main>

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
        img     = f"{base}/assets/images/{_slug_ascii(slug)}.jpg"
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
          <img class="card3__img" src="assets/images/{_slug_ascii(a['slug'])}-480.webp" alt="{_esc(a['titre'])}" loading="lazy">
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
  <link rel="stylesheet" href="/src/style.css?v=2"/>
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
      <input type="search" class="header__search-input" aria-label="Rechercher un article" placeholder="Rechercher…" autocomplete="off" onkeydown="if(event.key==='Enter'&&this.value.trim())window.location=(document.querySelector('base').href)+'recherche.html?q='+encodeURIComponent(this.value.trim())"/>
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
            img_src = f"assets/images/{_slug_ascii(a['slug'])}-480.webp"
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
  <link rel="stylesheet" href="/src/style.css?v=2"/>
  {FAVICON_LINKS}
  <script>(function(){{var s=localStorage.getItem('theme'),d=s==='dark'||(s===null&&window.matchMedia('(prefers-color-scheme:dark)').matches);document.documentElement.setAttribute('data-theme',d?'dark':'light');}})();</script>
</head>
<body>
{BURGER_HTML}
<header class="header">
  <div class="header__inner">
    <a href="index.html" class="brand">{BRAND_ICON}<div class="brand__logotype"><span class="fact">les</span><span class="uel">faits</span></div></a>
    <div class="header__search">
      <input type="search" class="header__search-input" aria-label="Rechercher un article" placeholder="Rechercher…" autocomplete="off" onkeydown="if(event.key==='Enter'&&this.value.trim())window.location=(document.querySelector('base').href)+'recherche.html?q='+encodeURIComponent(this.value.trim())"/>
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
      if(shown<rows.length)btn.textContent="Voir plus d'articles ("+(rows.length-shown)+" restants)";
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
  <link rel="stylesheet" href="/src/style.css?v=2"/>
  {FAVICON_LINKS}
  {_DARK_INIT_HEAD}
</head>
<body>
{BURGER_HTML}
<header class="header">
  <div class="header__inner">
    <a href="index.html" class="brand">{BRAND_ICON}<div class="brand__logotype"><span class="fact">les</span><span class="uel">faits</span></div></a>
    <div class="header__search">
      <input type="search" class="header__search-input" aria-label="Rechercher un article" placeholder="Rechercher…" autocomplete="off" onkeydown="if(event.key==='Enter'&&this.value.trim())window.location=(document.querySelector('base').href)+'recherche.html?q='+encodeURIComponent(this.value.trim())"/>
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
      var img = 'assets/images/'+a.slug.normalize('NFD').replace(/[\\u0300-\\u036f]/g,'')+'-480.webp';
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
        "nb_mots":   art.get("nb_mots", 0),
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
    # Historique : max_results 8→15 testé le 15/07 pour élargir le vivier de
    # sources distinctes. Résultat mesuré sur 2 runs complets : 0 article
    # publié à chaque fois — la plupart des sujets remontaient 13-15 sources,
    # gonflant certains prompts à >11000 tokens, à un cheveu du plafond Groq
    # de 12000 tokens/minute PAR CLÉ (découvert le 15/07 via une erreur 413).
    # Un seul appel pouvait donc épuiser le budget d'une clé, et comme tous
    # les sujets du batch avaient la même taille de prompt gonflée, les 4
    # clés se retrouvaient à sec simultanément.
    # Fix : chercher large (15) pour avoir un vrai choix, mais N'INJECTER
    # dans le prompt que les 8 meilleures (triées par qualité de source —
    # primaire > secondaire > tertiaire) — voir le tri juste après
    # l'enrichissement. Le prompt retrouve sa taille d'origine, mais avec de
    # meilleures sources qu'avant (choisies parmi 15 candidates, pas les 8
    # premières trouvées).
    extra = duckduckgo_search(item["title"] + " " + cat, max_results=15)
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

    # Plafond d'injection dans le prompt : les 8 meilleures par qualité
    # (primaire d'abord, puis secondaire, puis tertiaire), stable à qualité
    # égale (tri stable + ordre de découverte conservé en second critère).
    _QUALITE_RANG = {"primaire": 0, "secondaire": 1, "tertiaire": 2, "interdite": 3}
    extra = sorted(
        extra,
        key=lambda s: _QUALITE_RANG.get(qualite_source(s.get("url", "")), 3)
    )[:8]

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
        selon       = attributions_trop_repetitives(art)
        titre_pb    = titre_de_mauvaise_qualite(art)
        cliches     = cliches_ia(art)
        intro_pb    = intro_generique(art)
        nuances_pb  = nuances_vagues(art)
        prospectif  = affirmation_non_demontree(art)
        if fantomes or repetitions or intra or selon or titre_pb or cliches or intro_pb or nuances_pb or prospectif:
            details = []
            if fantomes:
                details.append(f"{len(fantomes)} attribution(s) hors sources")
            if repetitions:
                details.append(f"{len(repetitions)} phrase(s) du résumé quasi identiques au corps")
            if intra:
                details.append(f"{len(intra)} répétition(s) intra-article")
            if selon:
                details.append(f"abus de « Selon X » ({len(selon)} signalement(s))")
            if titre_pb:
                details.append("titre non conforme")
            if cliches:
                details.append(f"{len(cliches)} tournure(s) générique(s) IA")
            if intro_pb:
                details.append(f"intro générique ({len(intro_pb)} phrase(s))")
            if nuances_pb:
                details.append(f"{len(nuances_pb)} généralité(s) sans exemple concret dans Débats et nuances")
            if prospectif:
                details.append(f"{len(prospectif)} affirmation(s) prospective(s) non conditionnelle(s)")
            print(f"     [GARDE] {' + '.join(details)} — relance corrective unique…")
            art = generate(content, cat, extra_sources=extra, rss_url=item.get("url"),
                           retry_feedback=fantomes or None,
                           repetition_feedback=repetitions or None,
                           intra_feedback=intra or None,
                           selon_feedback=selon or None,
                           titre_feedback=titre_pb or None,
                           cliches_feedback=cliches or None,
                           intro_feedback=intro_pb or None,
                           nuances_feedback=nuances_pb or None,
                           prospectif_feedback=prospectif or None,
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
            # Défauts de style persistants après relance : avertissement uniquement,
            # l'article passe quand même (le quota Groq est la ressource rare).
            if resume_repete_corps(art):
                print(f"     [AVERTISSEMENT] Résumé toujours proche du corps après relance")
            if faits_repetitifs(art):
                print(f"     [AVERTISSEMENT] Répétitions intra-article persistantes après relance")
            if attributions_trop_repetitives(art):
                print(f"     [AVERTISSEMENT] Abus de « Selon X » persistant après relance")
            if titre_de_mauvaise_qualite(art):
                print(f"     [AVERTISSEMENT] Titre toujours non conforme après relance")
            if cliches_ia(art):
                print(f"     [AVERTISSEMENT] Tournures génériques IA persistantes après relance")
            if nuances_vagues(art):
                print(f"     [AVERTISSEMENT] Débats et nuances toujours génériques après relance")
            if affirmation_non_demontree(art):
                print(f"     [AVERTISSEMENT] Affirmation prospective toujours non conditionnelle après relance")

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

        # ── Garde-fou longueur/sources : la vraie règle éditoriale (500 mots,
        # 3 sources — voir SYSTEM_PROMPT règles 1 et 3), pas une approximation.
        # BUG CORRIGÉ : ce garde-fou vérifiait auparavant "600 caractères" et
        # "3 sources" — 600 caractères ≈ 100 mots, soit 7 fois moins que la
        # règle réellement annoncée. Résultat : les articles de 187 à 352 mots
        # publiés le 12/07 passaient tous ce contrôle sans problème. Corrigé
        # sur le nombre de MOTS réel (pas une conversion approximative en
        # caractères) et sur le vrai seuil de 4 sources.
        def _deficit_longueur_sources(a: dict) -> tuple[int, int]:
            return _mots_totaux(a), len(a.get("sources") or [])

        MIN_MOTS_CORPS = 500
        MIN_SOURCES = 3
        # Tolérance de 150 mots après relance (portée de 100 à 150 le 20/07,
        # Nahil : deux articles rejetés à 378/382 mots, trop proches du seuil
        # pour justifier une perte sèche) : la cible reste 500 mots, mais un
        # article qui plafonne à 350-499 mots malgré la relance d'étoffement
        # est accepté s'il est bien sourcé — plancher dur = 350 mots.
        TOLERANCE_MOTS = 150
        mots, nb_src = _deficit_longueur_sources(art)
        if mots < MIN_MOTS_CORPS or nb_src < MIN_SOURCES:
            manque_mots = max(0, MIN_MOTS_CORPS - mots)
            manque_src = max(0, MIN_SOURCES - nb_src)
            details = []
            if manque_mots:
                details.append(f"{mots} mots au lieu de {MIN_MOTS_CORPS} minimum")
            if manque_src:
                details.append(f"{nb_src} source(s) citée(s) au lieu de {MIN_SOURCES} minimum")
            print(f"     [GARDE] Article trop court/peu sourcé ({' + '.join(details)}) — relance d'étoffement…")
            expand_msg = (
                f"Ton article ne fait que {mots} mots (chapeau + faits + contexte + nuances) "
                f"(minimum {MIN_MOTS_CORPS}) et ne cite que {nb_src} source(s) (minimum {MIN_SOURCES})."
                if manque_mots and manque_src else
                f"Ton article ne fait que {mots} mots (chapeau + faits + contexte + nuances) "
                f"(minimum {MIN_MOTS_CORPS})." if manque_mots else
                f"Ton article ne cite que {nb_src} source(s) (minimum {MIN_SOURCES})."
            )
            art_expanded = generate(content, cat, extra_sources=extra, rss_url=item.get("url"),
                                    expand_feedback=expand_msg, article_type=article_type,
                                    previous_article=art)
            if isinstance(art_expanded, dict) and art_expanded:
                art = art_expanded
            mots, nb_src = _deficit_longueur_sources(art)
            if mots < MIN_MOTS_CORPS - TOLERANCE_MOTS or nb_src < MIN_SOURCES:
                print(f"     [REJET QUALITÉ] Toujours insuffisant après relance "
                      f"({mots} mots, {nb_src} source(s)) — rejet définitif")
                return False
            if mots < MIN_MOTS_CORPS:
                print(f"     [OK] Étoffement accepté sous tolérance : {mots} mots "
                      f"(< {MIN_MOTS_CORPS} mais ≥ {MIN_MOTS_CORPS - TOLERANCE_MOTS}), {nb_src} sources")
            else:
                print(f"     [OK] Étoffement réussi : {mots} mots, {nb_src} sources")

        # ── Règle de publication par QUALITÉ des sources (liste blanche) ──
        # « Au moins une source primaire OU deux sources secondaires
        # indépendantes » — une pile de sources tertiaires (vulgarisation,
        # blogs, agrégateurs) ne suffit jamais, quel que soit leur nombre.
        bilan = bilan_qualite_sources(art.get("sources", []))
        art["qualite_sources"] = bilan
        if bilan["primaire"] < 1 and bilan["secondaire"] < 2:
            print(f"     [REJET SOURCES] Qualité insuffisante : "
                  f"{bilan['primaire']} primaire(s), {bilan['secondaire']} secondaire(s), "
                  f"{bilan['tertiaire']} tertiaire(s) — il faut ≥1 primaire ou ≥2 secondaires")
            return False

        # ── Passes 2/3 : fact-check + correction automatique ──
        art, statut_verif = verifier_article(art, article_type=article_type)
        if statut_verif in ("rejete_sensible", "rejete_qualite"):
            # Messages déjà affichés dans verifier_article
            return False
        # Philosophie : empêcher qu'un mauvais article soit publié, pas en
        # publier un maximum. Si le protocole de vérification n'a pas pu
        # aller au bout (rate limit, erreur API), l'article N'EST PAS publié
        # — le sujet sera retenté au run suivant, la vérification n'est
        # jamais optionnelle.
        if statut_verif in ("erreur_verification", "non_verifie"):
            print(f"     [REJET PROTOCOLE] Vérification incomplète ({statut_verif}) — "
                  f"article non publié, le sujet sera retenté au prochain run")
            return False
        art["statut_verification"] = statut_verif

        # ── Re-contrôle déterministe APRÈS correction LLM ──
        # Le correcteur (passe 3) réécrit le texte APRÈS le passage des
        # garde-fous : sa sortie partait en publication sans re-vérification.
        # Constaté le 18/07 : phrases dupliquées mot pour mot entre sections
        # (jusqu'à 3 occurrences, attributions différentes) et corps sous le
        # plancher de 400 mots. Stratégie « réparer, pas éradiquer » (Nahil,
        # 18/07) : d'abord dédoublonnage déterministe gratuit (supprimer les
        # phrases quasi identiques au-delà de la 1re occurrence), et rejet
        # SEULEMENT si l'article reste sous le plancher après réparation —
        # signe que la duplication masquait un article creux. Pas de relance
        # Groq ici : le quota reste la ressource rare.
        if statut_verif == "corrige_automatiquement":
            if faits_repetitifs(art) or resume_repete_corps(art):
                _n_supp = _supprimer_phrases_dupliquees(art)
                if _n_supp:
                    print(f"     [RÉPARATION] {_n_supp} phrase(s) dupliquée(s) "
                          f"supprimée(s) après correction LLM")
            _mots_final = _mots_totaux(art)
            _restants = faits_repetitifs(art)
            if _mots_final < MIN_MOTS_CORPS - TOLERANCE_MOTS or _restants:
                _defauts = []
                if _mots_final < MIN_MOTS_CORPS - TOLERANCE_MOTS:
                    _defauts.append(f"{_mots_final} mots (< {MIN_MOTS_CORPS - TOLERANCE_MOTS})")
                if _restants:
                    _defauts.append("répétitions résiduelles")
                print(f"     [REJET POST-CORRECTION] Article dégradé même "
                      f"après réparation ({' + '.join(_defauts)}) — non "
                      f"publié, sujet retenté au prochain run")
                return False

        # La catégorie publiée est TOUJOURS celle du classifieur déterministe
        # (detect_category, lexique v2) — jamais celle choisie par le LLM, dont
        # la liste autorisée dans le prompt était incomplète (pas de "sante")
        # et dont le choix contredisait régulièrement le lexique.
        art["categorie"] = cat

        # Le badge public reflète le nombre de sources réellement citées
        # APRÈS correction, jamais le nombre fourni en entrée
        art["nb_sources"] = len(art.get("sources", []))

        # Compter les mots finaux pour le système de scoring longueur ET le
        # badge public (chapeau + corps — voir _mots_totaux)
        art["nb_mots"] = _mots_totaux(art)

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
        print(f"     ✓ {art['slug']}.html ({art['nb_sources']} src, {art.get('nb_mots', 0)} mots)")
        return True

    except QuotaJournalierEpuise:
        raise  # remonte à la boucle principale : arrêter le run, pas juste ce sujet
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


def run(dry_run=False, text_input=None, nb_max=36):
    # nb_max 18 -> 36 (26/07, passage à 2 runs/jour au lieu de 4) : en
    # regroupant matin+soir sur 2 créneaux au lieu d'étaler sur des runs
    # manuels supplémentaires dans l'après-midi, chaque run doit tenter deux
    # fois plus de sujets pour ne pas publier moins d'articles au total.
    # nb_max 12 -> 18 (23/07, retour Nahil) : plusieurs runs récents montrent
    # que le quota Groq n'est PAS le facteur limitant (budget encore large en
    # fin de run) — c'est le taux de rejet éditorial (angle insuffisant,
    # sources insuffisantes, sujet sensible) qui borne le volume publié à
    # 1-2 articles sur 12 essayés. Plus de candidats testés par créneau =
    # plus de chances de trouver des sujets qui passent les garde-fous, sans
    # rien assouplir. Le garde-fou de budget (_BUDGET_SECONDES, 4h) protège
    # toujours contre un run qui dépasserait le timeout GitHub.
    published = load_published()
    new_pub   = set()
    MOIS = ["janvier","février","mars","avril","mai","juin",
            "juillet","août","septembre","octobre","novembre","décembre"]
    now      = datetime.now()
    # Heure AFFICHÉE = heure réelle de génération de l'article (demande de
    # Nahil, 22/07) — recalculée pour chaque article dans la boucle
    # ci-dessous plutôt que figée une fois pour tout le run.
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
        # Budget : le job GitHub a 5 h (timeout-minutes: 300) et la génération
        # démarre à 01h05/13h05 Paris pour un déploiement à ~06h/18h. On
        # s'arrête à 4 h car le budget est vérifié ENTRE deux articles : un
        # dernier article entamé juste sous la limite peut encore prendre
        # ~20 min (8 cycles de rate limit + relances) — 4 h + marge < 5 h.
        _pipeline_start = time.time()
        _BUDGET_SECONDES = 4 * 60 * 60  # 4 heures
        print(f"\n[GÉNÉRATION]")
        for item in selection:
            elapsed = time.time() - _pipeline_start
            if elapsed > _BUDGET_SECONDES:
                print(f"  [BUDGET] {elapsed/60:.1f} min écoulées — arrêt pour éviter le timeout GitHub (budget={_BUDGET_SECONDES//60} min)")
                break
            try:
                _now_article = datetime.now()
                date_pub = f"{_now_article.day} {MOIS[_now_article.month-1]} {_now_article.year}, {_now_article.strftime('%Hh%M')}"
                if generer_article(item, dry_run, published, new_pub, date_pub, published_topics):
                    # Ajouter le titre généré à published_topics pour éviter les doublons dans la même session
                    published_topics.add(item.get("title", ""))
            except QuotaJournalierEpuise:
                print(f"\n  [ARRÊT] Quota Groq JOURNALIER épuisé sur toutes les clés — "
                      f"inutile d'attendre (le budget ne se libère qu'à minuit UTC). "
                      f"Les sujets restants seront retentés au prochain créneau.")
                break
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
    active_keys = len(GROQ_KEYS_SECONDAIRES)
    if active_keys:
        print(f"[INFO] {active_keys} clé(s) Groq de secours détectée(s) — bascule automatique si rate limit")

    run(dry_run=args.dry_run, text_input=args.text)

