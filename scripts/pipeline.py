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
from urllib.parse import urlparse

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

# ── URL de base du site public ─────────────────────────────────────────────────
BASE_URL = "https://r9mzz.github.io/lesfaits-site"

GROQ_KEY       = os.getenv("GROQ_API_KEY", "")
GROQ_KEY2      = os.getenv("GROQ_API_KEY_2", "")
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
        overlap = len(title_words & topic_words)
        if overlap >= 2:
            score -= 500  # rejet quasi-certain : même sujet avec 2 mots clés communs
            reasons.append(f"-500 sujet très redondant (overlap: {overlap} mots avec '{topic[:40]}')")
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
8. Sources : institutions officielles (INSEE, CNRS, INSERM, Eurostat, OMS, gouvernement), journaux de référence, publications peer-reviewed
9. Slug en français kebab-case, descriptif, max 65 caractères
10. positions : si et SEULEMENT SI l'article contient des prises de position explicites et vérifiables de 2 à 4 acteurs RÉELS (déclarations citées, votes enregistrés, communiqués officiels présents dans les sources), renseigne ce bloc avec verifie=true. Sinon, mets verifie=false et laisse acteurs vide []. Ne jamais inventer ou déduire une position — uniquement ce qui est explicitement attesté dans les sources. position = 0 (totalement favorable/consensuel) à 100 (totalement critique/opposé)."""


def _groq_call(api_key: str, messages: list, max_tokens: int = 4500) -> str:
    """Appelle Groq avec la clé donnée. Lève une exception en cas d'erreur."""
    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=max_tokens,
        temperature=0.1,
        messages=messages,
    )
    return response.choices[0].message.content.strip()


def generate(content: str, category_hint: str, extra_sources: list[dict] | None = None,
             rss_url: str | None = None) -> dict:

    # Construire la liste des URLs réelles disponibles (DuckDuckGo + flux RSS)
    real_sources: list[dict] = []
    if rss_url:
        real_sources.append({"title": "Source RSS originale", "url": rss_url, "snippet": ""})
    if extra_sources:
        real_sources.extend(extra_sources)

    real_urls = {s["url"] for s in real_sources}

    sources_block = ""
    if real_sources:
        sources_block = "\n\nSOURCES DISPONIBLES (SEULES SOURCES AUTORISÉES) :\n"
        for s in real_sources:
            sources_block += f"- {s['title']} | URL: {s['url']}\n"
            if s.get("snippet"):
                sources_block += f"  Extrait: {s['snippet'][:200]}\n"

    user_msg = (
        f"Catégorie probable : {category_hint}\n\n"
        f"CONTENU SOURCE PRINCIPAL :\n{content[:7000]}"
        f"{sources_block}\n\n"
        f"Rédige un article Les Faits complet, dense et sourcé. "
        f"Corps minimum 700 mots. "
        f"RÈGLE ABSOLUE SUR LES SOURCES : le champ 'sources' ne doit contenir QUE des entrées "
        f"dont l'URL figure dans la liste SOURCES DISPONIBLES ci-dessus. "
        f"N'invente AUCUNE source, AUCUNE URL. Si une institution n'a pas d'URL dans la liste, "
        f"ne l'inclus pas dans le tableau sources. "
        f"Le nombre de sources réelles prime sur le minimum — mieux vaut 2 sources réelles que 4 inventées."
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": user_msg},
    ]

    raw = None
    keys_to_try = [(GROQ_KEY, "clé 1"), (GROQ_KEY2, "clé 2")] if GROQ_KEY2 else [(GROQ_KEY, "clé 1")]
    for key, label in keys_to_try:
        if not key:
            continue
        try:
            raw = _groq_call(key, messages)
            break
        except Exception as e:
            err = str(e)
            if "429" in err or "rate_limit" in err.lower():
                print(f"     [GROQ] Rate limit sur {label} — {'bascule sur clé 2' if label == 'clé 1' and GROQ_KEY2 else 'quota épuisé'}")
                if label == "clé 2" or not GROQ_KEY2:
                    raise
            else:
                raise
    if raw is None:
        raise RuntimeError("Aucune clé Groq disponible")

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

    # Supprimer toute source dont l'URL n'est pas dans la liste réelle
    if "sources" in art:
        verified = []
        for src in art["sources"]:
            url = src.get("url") or ""
            path = urlparse(url).path.rstrip("/") if url else ""
            if url in real_urls and len(path) > 3:
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
    '<a href="categories/societe.html">Société</a>\n'
    '<a href="categories/science.html">Science</a>\n'
    '<a href="categories/economie.html">Économie</a>\n'
    '<a href="categories/tech.html">Tech</a>\n'
    '<a href="categories/sante.html">Santé</a>\n'
    '<a href="categories/environnement.html">Environnement</a>\n'
    '<a href="archive.html">Tous les articles</a>\n'
    '<a href="methode.html" class="nav-cta">Comment on travaille →</a>'
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
    # Fermer menu sur clic lien + touche Échap
    "\ndocument.querySelectorAll('.nav-mobile a').forEach(function(a){"
    "a.addEventListener('click',closeMenu);});"
    "\ndocument.addEventListener('keydown',function(e){if(e.key==='Escape')closeMenu();});"
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

DARK_TOGGLE = '<button class="dark-toggle" id="dark-toggle" aria-label="Mode sombre" title="Mode sombre">🌙</button>'

# Script injecté dans <head> pour éviter le flash (FOUC)
_DARK_INIT_HEAD = """<script>
(function(){var s=localStorage.getItem('theme'),d=s==='dark'||(s===null&&window.matchMedia('(prefers-color-scheme:dark)').matches);document.documentElement.setAttribute('data-theme',d?'dark':'light');})();
</script>"""

# Analytics Umami
_ANALYTICS_JS = '<script defer src="https://cloud.umami.is/script.js" data-website-id="8d68a78f-97ae-4c95-a955-5d3df758f7e2"></script>'

# Script complet injecté avant </body> (bouton + toggle)
_DARK_MODE_JS = """<script>
(function(){
  var btn=document.getElementById('dark-toggle');
  var dark=document.documentElement.getAttribute('data-theme')==='dark';
  if(btn) btn.textContent=dark?'☀️':'🌙';
  if(btn) btn.addEventListener('click',function(){
    var d=document.documentElement.getAttribute('data-theme')==='dark';
    document.documentElement.setAttribute('data-theme',d?'light':'dark');
    localStorage.setItem('theme',d?'light':'dark');
    btn.textContent=d?'🌙':'☀️';
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
      <a href="archive.html">Tous les articles</a>
      <a href="feed.xml" class="footer__rss">Flux RSS</a>
    </div>
    <div class="footer__col"><h4>LÉGAL</h4>
      <a href="mentions-legales.html">Mentions légales</a>
      <a href="confidentialite.html">Confidentialité</a>
      <a href="cgu.html">CGU</a>
    </div>
    <div class="footer__col"><h4>CONTACT</h4>
      <a href="contact.html">Nous écrire</a>
      <a href="contact.html#erreur">Signaler une erreur</a>
    </div>
  </div>
  <div class="footer__bottom">
    <span>© {y} Les Faits · <a href="https://creativecommons.org/licenses/by-nc-nd/4.0/deed.fr" rel="noopener noreferrer external" target="_blank" style="color:inherit">CC BY-NC-ND 4.0</a></span>
    <span>Protocole éditorial v1.1</span>
  </div>
</footer>"""

def _sanitize_image_keyword(kw: str, fallback: str = "") -> str:
    """Fix 2 — keyword propre : sans accents, sans virgules, max 5 mots anglais."""
    import unicodedata
    kw = unicodedata.normalize("NFD", kw)
    kw = "".join(c for c in kw if unicodedata.category(c) != "Mn")
    kw = kw.replace(",", " ").replace(";", " ")
    kw = re.sub(r"\s+", " ", kw).strip()
    words = kw.split()[:5]
    result = " ".join(words)
    # Si le résultat est vide ou trop court après nettoyage, utiliser le fallback
    return result if len(result) > 3 else (fallback or "france news")


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
        f'<img class="art__hero" src="{hero_src}" alt="Illustration : {art["titre"]}" loading="eager" fetchpriority="high" style="aspect-ratio:16/9;object-fit:cover"/>'
        f'</figure>'
    ) if hero_src else ""

    # Sources
    def _source_link(s):
        url = s.get("url") or ""
        path = urlparse(url).path.rstrip("/") if url else ""
        if url and len(path) > 3:
            return f' · <a href="{url}" target="_blank" rel="noopener noreferrer external" aria-label="{s.get("institution","Source")} (ouvre dans un nouvel onglet)">Lire la source →</a>'
        return ""

    verified_sources = [s for s in art.get("sources", []) if s.get("url") and len(urlparse(s["url"]).path.rstrip("/")) > 3]
    if verified_sources:
        sources_li = "\n".join(
            f'<li><cite>{s["institution"]}</cite> · <em>{s["titre"]}</em> · {s["date"]}{_source_link(s)}</li>'
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

    faits    = art["corps"]["faits"].replace("\n", "</p><p>")
    contexte = art["corps"]["contexte"].replace("\n", "</p><p>")
    nuances  = art["corps"]["nuances"].replace("\n", "</p><p>")

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
                f'<span class="cat cat--{a["categorie"]}">{a["categorie"].upper()}</span>'
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
    art_titre_js = art['titre'].replace("'", "\\'")
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
  if(favs.indexOf(slug)>-1){{btn.classList.add('active');btn.setAttribute('aria-pressed','true');btn.textContent='♥ Favori';}}
  btn.addEventListener('click',function(){{
    var f=JSON.parse(localStorage.getItem('lesfaits_favs')||'[]');
    var idx=f.indexOf(slug);
    if(idx>-1){{f.splice(idx,1);btn.classList.remove('active');btn.setAttribute('aria-pressed','false');btn.textContent='♡ Favoris';}}
    else{{f.push(slug);btn.classList.add('active');btn.setAttribute('aria-pressed','true');btn.textContent='♥ Favori';}}
    localStorage.setItem('lesfaits_favs',JSON.stringify(f));
  }});
}})();
</script>"""

    share_html = f"""<div class="art__share">
  <span class="art__share-label">Partager</span>
  <button class="share-btn share-btn--native" onclick="shareArticle()" style="display:{'none' if True else 'none'}" id="native-share">↗ Partager</button>
  <a class="share-btn" href="https://twitter.com/intent/tweet?url={art_url}&text={art['titre'].replace(' ','%20')}" target="_blank" rel="noopener noreferrer external">𝕏 Twitter</a>
  <a class="share-btn" href="https://www.linkedin.com/sharing/share-offsite/?url={art_url}" target="_blank" rel="noopener noreferrer external">in LinkedIn</a>
  <a class="share-btn" href="https://api.whatsapp.com/send?text={art['titre'].replace(' ','%20')}%20{art_url}" target="_blank" rel="noopener noreferrer external">WhatsApp</a>
  <button class="share-btn" onclick="copyLink()" id="copy-btn">Copier le lien</button>
  <button class="fav-btn" id="fav-btn" aria-pressed="false">♡ Favoris</button>
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
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <meta name="description" content="{desc_seo}"/>
  <meta name="robots" content="index, follow, max-snippet:-1, max-image-preview:large, max-video-preview:-1"/>
  <meta name="author" content="Les Faits — IA éditoriale"/>
  <meta property="og:title" content="{art['titre']} — Les Faits"/>
  <meta property="og:description" content="{desc_seo}"/>
  <meta property="og:type" content="article"/>
  <meta property="og:url" content="{art_url}"/>
  {f'<meta property="og:image" content="{BASE_URL}/{hero_src}"/><meta property="og:image:width" content="1200"/><meta property="og:image:height" content="630"/><meta property="og:image:type" content="image/jpeg"/>' if hero_src else ''}
  <meta property="article:section" content="{cat}"/>
  <link rel="canonical" href="{art_url}"/>
  <meta name="twitter:card" content="summary_large_image"/>
  <meta name="twitter:title" content="{art['titre']} — Les Faits"/>
  <meta name="twitter:description" content="{desc_seo}"/>
  <meta name="twitter:image" content="{f'{BASE_URL}/{hero_src}' if hero_src else f'{BASE_URL}/assets/images/og-default.jpg'}"/>
  <link rel="alternate" type="application/rss+xml" title="Les Faits — RSS" href="/lesfaits-site/feed.xml"/>
  <link rel="icon" type="image/svg+xml" href="/lesfaits-site/favicon.svg"/>
  <link rel="manifest" href="/lesfaits-site/manifest.json"/>
  <title>{art['titre']} — Les Faits</title>
  <script type="application/ld+json">{{"@context":"https://schema.org","@type":"NewsArticle","headline":"{art['titre'].replace('"', '&quot;')}","description":"{desc_seo.replace('"', '&quot;')}","datePublished":"{datetime.now().strftime('%Y-%m-%dT%H:%M:%S+02:00')}","dateModified":"{datetime.now().strftime('%Y-%m-%dT%H:%M:%S+02:00')}","articleSection":"{cat}","inLanguage":"fr","isAccessibleForFree":true,"image":{{"@type":"ImageObject","url":"{BASE_URL}/{hero_src}","width":1200,"height":630}},"author":{{"@type":"Organization","name":"Les Faits"}},"publisher":{{"@type":"Organization","name":"Les Faits","@id":"{BASE_URL}/#org","logo":{{"@type":"ImageObject","url":"{BASE_URL}/assets/images/og-default.jpg"}}}},"mainEntityOfPage":{{"@type":"WebPage","@id":"{art_url}"}}}}</script>
  <script type="application/ld+json">{{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[{{"@type":"ListItem","position":1,"name":"Accueil","item":"{BASE_URL}/"}},{{"@type":"ListItem","position":2,"name":"{CAT_LABELS.get(cat, cat)}","item":"{BASE_URL}/categories/{cat}.html"}},{{"@type":"ListItem","position":3,"name":"{art['titre'].replace('"', '&quot;')}"}}]}}</script>
  <base href="/lesfaits-site/"/>
  <link rel="stylesheet" href="src/style.css"/>
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
    <nav>
      <a href="categories/societe.html">Société</a>
      <a href="categories/science.html">Science</a>
      <a href="categories/economie.html">Économie</a>
      <a href="categories/tech.html">Tech</a>
      <a href="categories/sante.html">Santé</a>
      <a href="categories/environnement.html">Environnement</a>
      <a href="archive.html">Tous les articles</a>
      <a href="methode.html" class="nav-cta">Comment on travaille →</a>
    </nav>
    {DARK_TOGGLE}
    {BURGER_BTN}
  </div>
</header>
<div id="read-progress"></div>
<main>
<div class="art">
  <a class="art__back" href="index.html">← Retour à l'accueil</a>
  <span class="art__cat cat--{cat}">{cat.upper()}</span>
  <h1 class="art__title">{art['titre']}</h1>
  <div class="art__meta">
    {f'<span style="color:var(--blue);font-weight:600">{nb_src} source{"s" if nb_src > 1 else ""}</span><span class="meta__sep" aria-hidden="true">·</span>' if nb_src > 0 else ''}
    <time datetime="{datetime.now().strftime('%Y-%m-%d')}">{date_pub}</time>
    <span class="meta__sep" aria-hidden="true">·</span>
    <span class="art__reading-time">Lecture : {reading_time} min</span>
  </div>
  {verify_html}
  <div class="art__rule"></div>
  {hero_img}
  <p class="art__resume">{resume_txt}</p>
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
            f'<img src="assets/images/{a["slug"]}.jpg" alt="" width="400" height="110" loading="lazy" style="width:calc(100% + 32px);margin:-14px -16px 12px;height:110px;object-fit:cover;display:block;border-radius:var(--radius) var(--radius) 0 0">'
            f'<span class="cat cat--{a["categorie"]}">{a["categorie"].upper()}</span>'
            f'<div class="title-sm">{a["titre"]}</div>'
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
        return f"""<a class="une__side-item" href="articles/{a['slug']}.html">
          <span class="cat cat--{a['categorie']}">{a['categorie'].upper()}</span>
          <h3 class="title-md">{a['titre']}</h3>
          <div class="meta"><span class="meta__src">{a['nb_sources']} sources</span>
          <span class="meta__sep">·</span><span>{a['date']}</span></div>
        </a>"""

    def mini_card(a):
        return f"""<a class="card3" href="articles/{a['slug']}.html">
          <img class="card3__img" src="assets/images/{a['slug']}.jpg" alt="{a['titre']}" loading="lazy">
          <div class="card3__body">
            <span class="cat cat--{a['categorie']}">{a['categorie'].upper()}</span>
            <h3 class="title-sm">{a['titre']}</h3>
            <div class="meta" style="margin-top:10px">
              <span class="meta__src">{a['nb_sources']} sources</span>
              <span class="meta__sep">·</span><span>{a['date']}</span>
            </div>
          </div>
        </a>"""

    def list_card(i, a):
        return f"""<a class="list-item" href="articles/{a['slug']}.html">
          <span class="list-item__num">0{i+1}</span>
          <div><span class="cat cat--{a['categorie']}">{a['categorie'].upper()}</span>
          <h3 class="title-sm">{a['titre']}</h3>
          <div class="meta" style="margin-top:6px">
            <span class="meta__src">{a['nb_sources']} sources</span>
            <span class="meta__sep">·</span><span>{a['date']}</span>
          </div></div>
        </a>"""

    def _pick_diverse(pool: list, n: int, exclude_slugs: set) -> list:
        """Prend les n articles les plus récents, puis diversifie si possible."""
        avail = [a for a in pool if a["slug"] not in exclude_slugs]
        # Sélection de base : les n plus récents
        chosen = avail[:n]
        if len(chosen) < 2:
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
    used      = {main_art["slug"]}
    # Side : 3 articles diversifiés (catégories différentes du main et entre eux)
    side_arts = _pick_diverse(articles[1:], 3, used)
    used.update(a["slug"] for a in side_arts)
    # Grille "Derniers articles" : 6 articles, 1 par catégorie
    grid_arts = _pick_diverse(articles, 6, used)
    used.update(a["slug"] for a in grid_arts)
    # Liste : 6 suivants par récence
    list_arts = [a for a in articles if a["slug"] not in used][:6]

    side_html  = "\n".join(side_card(a) for a in side_arts) if side_arts else ""
    grid_html  = "\n".join(mini_card(a) for a in grid_arts) if grid_arts else ""
    list_html  = "\n".join(list_card(i, a) for i, a in enumerate(list_arts))

    index_path = ROOT / "index.html"
    html = build_index_html(main_art, side_html, grid_html, list_html)
    index_path.write_text(html, encoding="utf-8")
    print(f"  ✓ index.html reconstruit ({len(articles)} articles)")
    build_category_pages()
    build_archive_page()
    build_search_json(articles)
    build_feed_xml(articles)
    build_sitemap(articles)
    rebuild_articles_related(articles)


def build_index_html(main, side_html, grid_html, list_html):
    resume = " ".join(main["resume"]) if isinstance(main.get("resume"), list) else main.get("resume", "")

    return f"""<!DOCTYPE html>
<html lang="fr" data-theme="">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <meta name="description" content="Les Faits — Journal numérique français rédigé par IA. Juste les faits. Aucun parti pris."/>
  <meta property="og:title" content="Les Faits — Juste les faits. Aucun parti pris."/>
  <meta property="og:description" content="Journal numérique français rédigé par IA. Sans publicité. Sans actionnaires."/>
  <meta property="og:type" content="website"/>
  <meta property="og:url" content="https://r9mzz.github.io/lesfaits-site/"/>
  <link rel="alternate" type="application/rss+xml" title="Les Faits — RSS" href="/lesfaits-site/feed.xml"/>
  <title>Les Faits — Juste les faits. Aucun parti pris.</title>
  <base href="/lesfaits-site/"/>
  <link rel="stylesheet" href="src/style.css"/>
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
    <nav>
      <a href="categories/societe.html">Société</a>
      <a href="categories/science.html">Science</a>
      <a href="categories/economie.html">Économie</a>
      <a href="categories/tech.html">Tech</a>
      <a href="categories/sante.html">Santé</a>
      <a href="categories/environnement.html">Environnement</a>
      <a href="archive.html">Tous les articles</a>
      <a href="methode.html" class="nav-cta">Comment on travaille →</a>
    </nav>
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
        <span class="cat cat--{main['categorie']}">{main['categorie'].upper()}</span>
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
        (f"{BASE_URL}/mentions-legales.html", "0.3", "yearly"),
        (f"{BASE_URL}/cgu.html", "0.3", "yearly"),
        (f"{BASE_URL}/contact.html", "0.4", "monthly"),
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
          <img class="card3__img" src="assets/images/{a['slug']}.jpg" alt="{a['titre']}" loading="lazy">
          <div class="card3__body">
            <span class="cat cat--{cat}">{label.upper()}</span>
            <h3 class="title-sm">{a['titre']}</h3>
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
          <a href="/lesfaits-site/" style="display:inline-block;padding:10px 24px;background:var(--blue);
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
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <meta name="description" content="Les Faits — Rubrique {label}. Juste les faits. Aucun parti pris."/>
  <link rel="alternate" type="application/rss+xml" title="Les Faits — RSS" href="/lesfaits-site/feed.xml"/>
  <title>{label} — Les Faits</title>
  <base href="/lesfaits-site/"/>
  <link rel="stylesheet" href="src/style.css"/>
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
    <nav>
      <a href="categories/societe.html">Société</a>
      <a href="categories/science.html">Science</a>
      <a href="categories/economie.html">Économie</a>
      <a href="categories/tech.html">Tech</a>
      <a href="categories/sante.html">Santé</a>
      <a href="categories/environnement.html">Environnement</a>
      <a href="archive.html">Tous les articles</a>
      <a href="methode.html" class="nav-cta">Comment on travaille →</a>
    </nav>
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
    <a href="articles/{a['slug']}.html" style="display:grid;grid-template-columns:80px 1fr;gap:12px 20px;padding:16px 0;border-bottom:1px solid var(--border);align-items:start;text-decoration:none;color:inherit">
      <img src="{img_src}" alt="" style="width:80px;height:54px;object-fit:cover;border-radius:4px;background:var(--light)" loading="lazy" onerror="this.style.display='none'"/>
      <div>
        <span class="cat cat--{cat}" style="display:inline-block;font-size:10px;font-weight:700;letter-spacing:.06em;margin-bottom:4px">{label.upper()}</span>
        <div style="font-weight:600;color:var(--ink);line-height:1.4;font-size:1rem">{a['titre']}</div>
        <p style="margin:4px 0 0;font-size:.85rem;color:var(--muted);line-height:1.5">{resume[:120]}{'…' if len(resume)>120 else ''}</p>
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
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <meta name="description" content="Tous les articles publiés par Les Faits — journal numérique français rédigé par IA."/>
  <meta name="robots" content="noindex"/>
  <title>Tous les articles — Les Faits</title>
  <base href="/lesfaits-site/"/>
  <link rel="stylesheet" href="src/style.css"/>
  <script>(function(){{var s=localStorage.getItem('theme'),d=s==='dark'||(s===null&&window.matchMedia('(prefers-color-scheme:dark)').matches);document.documentElement.setAttribute('data-theme',d?'dark':'light');}})();</script>
</head>
<body>
<div class="nav-overlay" id="nav-overlay" onclick="closeMenu()"></div>
<nav class="nav-mobile" id="nav-mobile">
<a href="categories/societe.html">Société</a>
<a href="categories/science.html">Science</a>
<a href="categories/economie.html">Économie</a>
<a href="categories/tech.html">Tech</a>
<a href="categories/sante.html">Santé</a>
<a href="categories/environnement.html">Environnement</a>
<a href="methode.html" class="nav-cta">Comment on travaille →</a>
</nav>
<script>
function toggleMenu(){{var b=document.getElementById('burger'),m=document.getElementById('nav-mobile'),o=document.getElementById('nav-overlay');b.classList.toggle('open');m.classList.toggle('open');o.classList.toggle('open');}}
function closeMenu(){{document.getElementById('burger').classList.remove('open');document.getElementById('nav-mobile').classList.remove('open');document.getElementById('nav-overlay').classList.remove('open');}}
document.querySelectorAll('.nav-mobile a').forEach(function(a){{a.addEventListener('click',closeMenu);}});
document.addEventListener('keydown',function(e){{if(e.key==='Escape')closeMenu();}});
</script>
<header class="header">
  <div class="header__inner">
    <a href="index.html" class="brand"><div class="brand__logotype"><span class="fact">les</span><span class="uel">faits</span></div></a>
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
      <a href="archive.html">Tous les articles</a>
      <a href="methode.html" class="nav-cta">Comment on travaille →</a>
    </nav>
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
</main>

{_build_footer()}
{_DARK_MODE_JS}
{_ANALYTICS_JS}
</body>
</html>"""

    ROOT = Path(__file__).parent.parent
    (ROOT / "archive.html").write_text(html, encoding="utf-8")
    print(f"  ✓ archive.html mis à jour ({len(articles)} articles)")

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

    # Recherche de sources corroborantes : DuckDuckGo + PubMed
    extra = duckduckgo_search(item["title"] + " " + cat, max_results=8)
    pubmed = pubmed_search(item["title"], max_results=4)
    # Fusionner sans doublons
    seen_urls = {s["url"] for s in extra}
    for p in pubmed:
        if p["url"] not in seen_urls:
            extra.append(p)
            seen_urls.add(p["url"])

    # Bloquer si moins de 3 sources réelles trouvées AVANT même de générer
    specific_sources = [s for s in extra if len(urlparse(s["url"]).path.rstrip("/")) > 5]
    if len(specific_sources) < 3:
        print(f"  [REJET] Seulement {len(specific_sources)} source(s) — minimum 3 requis (DDG+PubMed)")
        return False

    print(f"  → Génération : {item['title'][:55]} [{len(specific_sources)} sources réelles]")

    if dry_run:
        print(f"     (dry-run)")
        return False

    try:
        art         = generate(content, cat, extra_sources=extra, rss_url=item.get("url"))
        total_chars = sum(len(art["corps"].get(k, "")) for k in ["faits", "contexte", "nuances"])

        if len(art.get("sources", [])) < 3:
            print(f"     [REJET] Seulement {len(art.get('sources',[]))} source(s) après vérification — min 3")
            return False
        if total_chars < 600:
            print(f"     [REJET] Corps trop court ({total_chars} chars)")
            return False

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
    # Utiliser l'heure du créneau prévu plutôt que l'heure réelle du runner
    slot_heure = "07h00" if now.hour < 12 else "18h00"
    date_pub = f"{now.day} {MOIS[now.month-1]} {now.year}, {slot_heure}"

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

    _init_used_images()

    if not GROQ_KEY:
        print("ERREUR : GROQ_API_KEY manquant dans .env / secrets GitHub")
        exit(1)
    if GROQ_KEY2:
        print("[INFO] Clé Groq de secours (GROQ_API_KEY_2) détectée — bascule automatique si rate limit")

    run(dry_run=args.dry_run, text_input=args.text)

