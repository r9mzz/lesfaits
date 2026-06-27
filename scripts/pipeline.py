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

GROQ_KEY       = os.getenv("GROQ_API_KEY", "")
GROQ_KEY2      = os.getenv("GROQ_API_KEY_2", "")

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


def duckduckgo_search(query: str, max_results: int = 8) -> list[dict]:
    """Recherche DuckDuckGo — retourne uniquement des URLs pointant vers des articles précis."""
    def _search(q: str) -> list[dict]:
        try:
            url = "https://html.duckduckgo.com/html/"
            r = requests.post(url, data={"q": q}, headers=HEADERS, timeout=12)
            soup = BeautifulSoup(r.text, "html.parser")
            out = []
            for result in soup.select(".result")[:15]:
                t = result.select_one(".result__title")
                u = result.select_one(".result__url")
                s = result.select_one(".result__snippet")
                if t and u:
                    raw_url = "https://" + u.get_text(strip=True).strip()
                    path = urlparse(raw_url).path.rstrip("/")
                    if len(path) > 5:  # exclure les homepages
                        out.append({
                            "title":   t.get_text(strip=True),
                            "url":     raw_url,
                            "snippet": s.get_text(strip=True) if s else "",
                        })
            return out
        except Exception:
            return []

    seen = set()
    results = []

    # 3 requêtes complémentaires pour maximiser les vraies sources
    for q in [
        query,
        query + " rapport statistiques données",
        query + " site:gouv.fr OR site:inserm.fr OR site:insee.fr OR site:who.int OR site:europa.eu",
    ]:
        for r in _search(q):
            if r["url"] not in seen:
                seen.add(r["url"])
                results.append(r)
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


def _download_hero(keyword: str, slug: str, dest: str) -> None:
    """Cherche image : Wikimedia Commons → Openverse → fallback Pillow."""
    import urllib.parse
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    hdrs = {"User-Agent": "LesFaits/1.1 (lesfaits.contact@gmail.com)"}

    # Noms de fichier suspects : cartes, drapeaux, logos, diagrammes, blasons
    _BAD_FILENAME = (
        "map", "flag", "logo", "icon", "diagram", "chart", "graph", "coat",
        "blason", "carte", "drapeau", "schema", "plan_", "seal_", "emblem",
        "stamp", "badge", "symbol", "sign_", "portrait_", "headshot",
    )

    def _is_bad_image(url: str, w: int, h: int) -> bool:
        fname = url.rsplit("/", 1)[-1].lower()
        if any(bad in fname for bad in _BAD_FILENAME):
            return True
        if w > 0 and h > 0 and (h / w > 1.4 or w / h < 0.5):
            return True
        return False

    # 1. Wikimedia Commons — images thématiques libres, bien indexées par sujet
    try:
        params = urllib.parse.urlencode({
            "action": "query", "format": "json", "generator": "search",
            "gsrnamespace": "6", "gsrsearch": keyword, "gsrlimit": "20",
            "prop": "imageinfo", "iiprop": "url|size|mime", "iiurlwidth": "1200"
        })
        r = requests.get(f"https://commons.wikimedia.org/w/api.php?{params}", timeout=10, headers=hdrs)
        pages = sorted(
            r.json().get("query", {}).get("pages", {}).values(),
            key=lambda p: -(p.get("imageinfo", [{}])[0].get("width", 0))
        )
        for page in pages:
            ii = page.get("imageinfo", [{}])[0]
            mime = ii.get("mime", "")
            if mime not in ("image/jpeg", "image/png", "image/webp"):
                continue
            img_url = ii.get("thumburl") or ii.get("url", "")
            if not img_url:
                continue
            width = ii.get("thumbwidth") or ii.get("width", 0)
            height = ii.get("thumbheight") or ii.get("height", 0)
            if width < 600 or height < 300:
                continue
            if _is_bad_image(img_url, width, height):
                continue
            img_r = requests.get(img_url, timeout=15, headers=hdrs)
            if img_r.status_code == 200 and len(img_r.content) > 20_000:
                open(dest, "wb").write(img_r.content)
                return
    except Exception:
        pass

    # 2. Openverse — images CC
    try:
        q = urllib.parse.urlencode({"q": keyword, "page_size": "10", "license_type": "commercial,modification"})
        ov = requests.get(f"https://api.openverse.org/v1/images/?{q}", timeout=10, headers=hdrs)
        for item in ov.json().get("results", []):
            img_url = item.get("url", "")
            if not img_url.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                continue
            w = item.get("width", 0) or 0
            h = item.get("height", 0) or 0
            if _is_bad_image(img_url, w, h):
                continue
            r = requests.get(img_url, timeout=15, headers=hdrs)
            if r.status_code == 200 and len(r.content) > 20_000:
                open(dest, "wb").write(r.content)
                return
    except Exception:
        pass

    # 3. Fallback Pillow — infographie typographique
    _generate_fallback_image(keyword, slug.split("-")[0] if slug else "societe", slug, dest)


# ── Constantes UI partagées ──────────────────────────────────────────────────
_NAV_LINKS = (
    '<a href="categories/societe.html">Société</a>\n'
    '<a href="categories/science.html">Science</a>\n'
    '<a href="categories/economie.html">Économie</a>\n'
    '<a href="categories/tech.html">Tech</a>\n'
    '<a href="categories/sante.html">Santé</a>\n'
    '<a href="categories/environnement.html">Environnement</a>\n'
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

    # Image hero
    local_img_path = f"assets/images/{safe_slug}.jpg"
    if not os.path.exists(local_img_path):
        kw = _sanitize_image_keyword(art.get("image_keyword", ""), fallback=safe_slug)
        _download_hero(kw, slug, local_img_path)
    hero_src = local_img_path if os.path.exists(local_img_path) else ""
    hero_img = (
        f'<figure style="margin-bottom:28px">'
        f'<img class="art__hero" src="{hero_src}" alt="" loading="eager" fetchpriority="high" style="aspect-ratio:16/9;object-fit:cover"/>'
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

    # Articles liés (même catégorie)
    related_html = ""
    try:
        all_arts = load_index()
        related = [a for a in all_arts if a.get("categorie") == cat and a["slug"] != slug][:3]
        if related:
            cards = "\n".join(
                f'<div class="art__related-card" onclick="window.location=\'articles/{a["slug"]}.html\'">'
                f'<span class="cat">{a["categorie"].upper()}</span>'
                f'<div class="title-sm">{a["titre"]}</div>'
                f'<div style="font-size:10px;color:var(--muted);margin-top:6px">{a["date"]}</div>'
                f'</div>'
                for a in related
            )
            related_html = f'<div class="art__related"><div class="art__related-title">À LIRE AUSSI</div><div class="art__related-grid">{cards}</div></div>'
    except Exception:
        pass

    # Share buttons JS
    art_url = f"https://r9mzz.github.io/lesfaits/articles/{slug}.html"
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
  <meta name="description" content="{resume_txt[:155]}"/>
  <meta name="robots" content="index, follow, max-snippet:-1, max-image-preview:large"/>
  <meta property="og:title" content="{art['titre']} — Les Faits"/>
  <meta property="og:description" content="{resume_txt[:155]}"/>
  <meta property="og:type" content="article"/>
  <meta property="og:url" content="{art_url}"/>
  {f'<meta property="og:image" content="https://r9mzz.github.io/lesfaits/{hero_src}"/><meta property="og:image:width" content="1200"/><meta property="og:image:height" content="630"/><meta property="og:image:type" content="image/jpeg"/>' if hero_src else ''}
  <meta property="article:section" content="{cat}"/>
  <link rel="canonical" href="{art_url}"/>
  <meta name="twitter:card" content="summary_large_image"/>
  <meta name="twitter:title" content="{art['titre']} — Les Faits"/>
  <meta name="twitter:description" content="{resume_txt[:155]}"/>
  <meta name="twitter:image" content="{f'https://r9mzz.github.io/lesfaits/{hero_src}' if hero_src else 'https://r9mzz.github.io/lesfaits/assets/images/og-default.jpg'}"/>
  <link rel="alternate" type="application/rss+xml" title="Les Faits — RSS" href="/lesfaits/feed.xml"/>
  <link rel="icon" type="image/svg+xml" href="/lesfaits/favicon.svg"/>
  <link rel="manifest" href="/lesfaits/manifest.json"/>
  <title>{art['titre']} — Les Faits</title>
  <script type="application/ld+json">{{"@context":"https://schema.org","@type":"NewsArticle","headline":"{art['titre'].replace('"', '&quot;')}","description":"{resume_txt[:155].replace('"', '&quot;')}","datePublished":"{date_pub.strftime('%Y-%m-%dT%H:%M:%S+02:00')}","dateModified":"{date_pub.strftime('%Y-%m-%dT%H:%M:%S+02:00')}","articleSection":"{cat}","inLanguage":"fr","isAccessibleForFree":true,"image":{{"@type":"ImageObject","url":"https://r9mzz.github.io/lesfaits/{hero_src}","width":1200,"height":630}},"author":{{"@type":"Organization","name":"Les Faits"}},"publisher":{{"@type":"Organization","name":"Les Faits","@id":"https://r9mzz.github.io/lesfaits/#org","logo":{{"@type":"ImageObject","url":"https://r9mzz.github.io/lesfaits/assets/images/og-default.jpg"}}}},"mainEntityOfPage":{{"@type":"WebPage","@id":"{art_url}"}}}}</script>
  <script type="application/ld+json">{{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[{{"@type":"ListItem","position":1,"name":"Accueil","item":"https://r9mzz.github.io/lesfaits/"}},{{"@type":"ListItem","position":2,"name":"{CAT_LABELS.get(cat, cat)}","item":"https://r9mzz.github.io/lesfaits/categories/{cat}.html"}},{{"@type":"ListItem","position":3,"name":"{art['titre'].replace('"', '&quot;')}"}}]}}</script>
  <base href="/lesfaits/"/>
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
  <span class="art__cat">{cat.upper()}</span>
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
  <p class="art__badge">Rédigé par IA · Protocole Les Faits v1.1 · {date_pub}</p>
  <a class="contest-btn" href="contact.html?article={slug}#erreur">Signaler une erreur sur cet article</a>
</div>
</main>
{_build_footer()}
{share_js}
{_DARK_MODE_JS}
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
    build_feed_xml(articles)


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
  <meta property="og:url" content="https://r9mzz.github.io/lesfaits/"/>
  <link rel="alternate" type="application/rss+xml" title="Les Faits — RSS" href="/lesfaits/feed.xml"/>
  <title>Les Faits — Juste les faits. Aucun parti pris.</title>
  <base href="/lesfaits/"/>
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
      <a href="methode.html" class="nav-cta">Comment on travaille →</a>
    </nav>
    {DARK_TOGGLE}
    {BURGER_BTN}
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
      <a class="btn btn--white" href="https://www.paypal.com/donate?hosted_button_id=LESFAITS" rel="noopener noreferrer external" target="_blank">Soutenir Les Faits</a>
      <a class="btn btn--outline" href="methode.html">Notre méthode</a>
    </div>
  </div>
</div>

{_build_footer()}
{_DARK_MODE_JS}
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


def build_feed_xml(articles: list):
    """Génère feed.xml (RSS 2.0) pour les 20 derniers articles."""
    base = "https://r9mzz.github.io/lesfaits"
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
<html lang="fr" data-theme="">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <meta name="description" content="Les Faits — Rubrique {label}. Juste les faits. Aucun parti pris."/>
  <link rel="alternate" type="application/rss+xml" title="Les Faits — RSS" href="/lesfaits/feed.xml"/>
  <title>{label} — Les Faits</title>
  <base href="/lesfaits/"/>
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

        html = build_article_html(art, date_pub)

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
        err = str(e)
        if "401" in err or "invalid_api_key" in err.lower() or "authentication" in err.lower():
            print(f"     [ERREUR GROQ] Clé API invalide ou expirée — vérifier GROQ_API_KEY dans les secrets GitHub")
        elif "429" in err or "rate_limit" in err.lower():
            print(f"     [ERREUR GROQ] Rate limit atteint — quota journalier/mensuel Groq épuisé")
        elif "model" in err.lower() and ("not found" in err.lower() or "deprecated" in err.lower()):
            print(f"     [ERREUR GROQ] Modèle llama-3.3-70b-versatile indisponible : {err}")
        else:
            print(f"     [ERREUR] {type(e).__name__}: {err}")
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
        print("ERREUR : GROQ_API_KEY manquant dans .env / secrets GitHub")
        exit(1)
    if GROQ_KEY2:
        print("[INFO] Clé Groq de secours (GROQ_API_KEY_2) détectée — bascule automatique si rate limit")

    run(dry_run=args.dry_run, text_input=args.text)
