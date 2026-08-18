"""
Les Faits — Pipeline éditorial IA v2
====================================
Sources RSS reelles → Filtre éditorial → Groq (Llama) → HTML → Site reconstruit

Usage:
    python pipeline.py                  # scan toutes les sources RSS
    python pipeline.py --dry-run        # scan sans générer
    python pipeline.py --text "..."     # article depuis texte libre
"""

import os, re, json, time, hashlib, argparse, sys, unicodedata
from collections import Counter
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

# ── UNE SEULE CLÉ, QUAND LE FOURNISSEUR CHANGE ──────────────────────────────
# Les 11 clés Groq existent pour contourner un plafond journalier de 100 k
# tokens PAR COMPTE. Un fournisseur dont le palier gratuit accorde 1 milliard
# de tokens par mois n'a pas ce problème : une clé suffit, et en ouvrir onze
# n'apporterait rien.
#
# `LLM_API_KEY` remplace donc la liste entière quand elle est définie. Tout le
# reste du code continue de lire `GROQ_ALL_KEYS` — rotation, marquage des clés
# mortes, tour de clé du juge de pertinence : rien à réécrire, et une liste
# d'un seul élément traverse ces mécanismes sans cas particulier (l'index de
# rotation `hash % len` vaut alors toujours 0).
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
if LLM_API_KEY:
    GROQ_ALL_KEYS = [(LLM_API_KEY, "clé fournisseur")]

# ── Clés CÂBLÉES mais ABSENTES des secrets (constat 10/08) ───────────────────
# Quatre jours sans publication : le pipeline tournait sur 9 clés alors que
# `pipeline.yml` en câble 23. Les secrets GROQ_API_KEY_7 à _18 n'existent plus.
#
# GitHub Actions passe `${{ secrets.X }}` d'un secret inexistant comme chaîne
# VIDE, pas comme variable absente. Le filtre `if v` les écartait donc en
# silence : capacité divisée par 2,5, aucun message, aucun échec. C'est ce qui
# a permis à quatre jours de passer sans qu'on sache pourquoi.
#
# On distingue ici les trois états, ce que `os.environ` permet justement :
#   absente de l'environnement → non câblée dans le workflow, normal
#   présente mais vide         → CÂBLÉE ET MANQUANTE ← la panne silencieuse
#   présente et non vide       → utilisable
GROQ_CLES_CABLEES_VIDES: list[str] = [
    nom for nom in (["GROQ_API_KEY"] + [f"GROQ_API_KEY_{i}" for i in range(2, 41)])
    if nom in os.environ and not os.environ[nom].strip()
]


def diagnostic_cles_groq() -> None:
    """Écrit la capacité en tête de run, et alerte si une clé câblée manque.

    ⚠ LE QUOTA GROQ EST PAR COMPTE, PAS PAR CLÉ (correctif du 10/08, Nahil).
    Quatre clés créées sur un même compte se PARTAGENT ses 100 k tokens/jour :
    elles valent 25 k chacune, pas 100 k. Ajouter des clés sur un compte déjà
    utilisé n'ajoute donc AUCUNE capacité — c'est pourquoi 12 d'entre elles ont
    été retirées le 10/08, sans perte. Ne jamais estimer la capacité en
    multipliant le nombre de clés par 100 k : c'est le nombre de COMPTES
    DISTINCTS qui compte, et le code ne peut pas le connaître depuis une clé.

    Diagnostic seul : n'interrompt rien, ne change aucune décision.
    """
    utilisables = len(GROQ_ALL_KEYS)
    manquantes = len(GROQ_CLES_CABLEES_VIDES)
    print(f"[CLÉS GROQ] {utilisables} clé(s) utilisable(s) sur "
          f"{utilisables + manquantes} câblée(s). Capacité réelle = "
          f"100 k × nombre de COMPTES distincts (non déductible d'ici).")
    if manquantes:
        # ::warning:: remonte dans le résumé du run GitHub, pas seulement dans
        # le journal — c'est ce qui manquait pour qu'une perte soit vue.
        # Ne se déclenche que sur un secret câblé ET absent : les clés
        # volontairement retirées le sont AUSSI du workflow, donc pas d'alerte.
        print(f"::warning::{manquantes} clé(s) Groq câblée(s) dans pipeline.yml mais "
              f"ABSENTE(S) des secrets GitHub : {', '.join(GROQ_CLES_CABLEES_VIDES)}. "
              f"Soit créer les secrets, soit retirer les lignes du workflow — "
              f"une clé câblée et vide est silencieusement ignorée.")
PEXELS_KEY     = os.getenv("PEXELS_API_KEY", "")
PIXABAY_KEY    = os.getenv("PIXABAY_API_KEY", "")

# ══════════════════════════════════════════════════════════════════════════════
# SOURCES RSS — retournent du texte propre, pas de JavaScript
# ══════════════════════════════════════════════════════════════════════════════

# Nombre maximum d'articles retenus par flux à chaque run (voir fetch_rss).
# 8 → 20 le 28/07, puis 20 → 40 le 11/08. Mesure qui l'a motivé : à 20, la
# quasi-totalité des flux rendaient EXACTEMENT 20 items — ils étaient donc tous
# tronqués, et on ignorait systématiquement les mêmes articles (les plus
# anciens du flux). On ne savait pas ce qu'on ne voyait pas.
# Ce plafond ne coûte AUCUN token Groq : il n'élargit que le vivier où
# `selectionner_meilleurs` puise ses candidats. Les appels DuckDuckGo, eux, ne
# concernent que les 6 sujets réellement générés par run — donc inchangés.
MAX_ITEMS_PAR_FLUX = 40

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
    # Science internationale
    {"name": "Futura Sciences",      "url": "https://www.futura-sciences.com/rss/actualites.xml"},
    {"name": "CNRS Actualités",      "url": "https://lejournal.cnrs.fr/rss"},
    # Santé publique
    {"name": "INSERM Actualités",    "url": "https://www.inserm.fr/feed/"},
    # Environnement
    {"name": "Reporterre",           "url": "https://reporterre.net/spip.php?page=backend"},
    # Sécurité sanitaire
    # ── Ajouts du 19/07 (Nahil : besoin de plus de matière) ──
    # fetch_rss ignore déjà silencieusement un flux mort (voir gestion 415/406
    # existante) — un flux qui ne répond pas ne casse rien, il rapporte juste
    # 0 sujet. Confiance haute (format standard, documenté) sauf mention contraire.
    {"name": "The Conversation France", "url": "https://theconversation.com/fr/articles.atom"},
    {"name": "RFI",                  "url": "https://www.rfi.fr/fr/rss"},
    {"name": "Numerama",             "url": "https://www.numerama.com/feed/"},
    {"name": "Novethic",             "url": "https://www.novethic.fr/feed"},
    # Institutionnels à forte valeur (source PRIMAIRE directe) mais URL non
    # vérifiable depuis cet environnement (réseau restreint) — à confirmer
    # dans les logs du prochain run réel (GitHub Actions) : chercher
    # "[COLLECTE RSS]" et le nombre d'items par flux.
    {"name": "Santé Publique France", "url": "https://www.santepubliquefrance.fr/rss/actualites.xml"},
    # ── Deuxième vague (19/07, suite) : couvrir les domaines déjà en liste
    # blanche primaire/secondaire mais qui n'avaient encore AUCUN flux RSS
    # configuré — le levier le plus direct pour plus de matière sans rien
    # assouplir. Mêmes réserves de confiance qu'au-dessus (réseau sandbox
    # bloqué, à confirmer au run réel via "[COLLECTE RSS]").
    # -- Presse déjà secondaire, RSS manquant --
    # ancienne URL "www.leparisien.fr/rss.xml" en 404 depuis leur migration
    # d'infra RSS vers un sous-domaine dédié (constat 26/07) — nouveau flux
    # général confirmé par recherche externe (feeds.leparisien.fr/leparisien/rss).
    {"name": "Le Parisien",          "url": "https://feeds.leparisien.fr/leparisien/rss"},
    {"name": "L'Express",            "url": "https://www.lexpress.fr/rss/alaune.xml"},
    {"name": "Ouest-France",         "url": "https://www.ouest-france.fr/rss-en-continu.xml"},
    {"name": "La Croix",             "url": "https://www.la-croix.com/rss.xml"},
    {"name": "France 24",            "url": "https://www.france24.com/fr/rss"},
    {"name": "Mediapart",            "url": "https://www.mediapart.fr/articles/feed"},
    {"name": "20 Minutes",           "url": "https://www.20minutes.fr/feeds/rss-une.xml"},
    # -- Institutions déjà primaires, RSS manquant --
    {"name": "Sénat",                "url": "https://www.senat.fr/themes/rss/therss4.rss"},
    # ── Sources ajoutées le 28/07 — rendement VÉRIFIÉ par check_feeds.py sur
    # le runner GitHub (8 articles chacune) avant ajout, contrairement à la
    # vague du 19/07 dont 13 flux sur 14 étaient morts faute de test.
    {"name": "Le Monde International", "url": "https://www.lemonde.fr/international/rss_full.xml"},
    {"name": "France Culture",       "url": "https://radiofrance.fr/franceculture/rss"},
    {"name": "Courrier international", "url": "https://www.courrierinternational.com/feed/all/rss.xml"},
    {"name": "Slate.fr",             "url": "https://www.slate.fr/rss.xml"},
    {"name": "France Info Sciences", "url": "https://www.francetvinfo.fr/sciences.rss"},
    {"name": "INSERM presse",        "url": "https://presse.inserm.fr/feed/"},
    {"name": "IRD",                  "url": "https://www.ird.fr/rss.xml"},
    # ── Institutions qui PUBLIENT elles-mêmes (11/08) ────────────────────────
    # 69 % des articles publiés n'ont aucune source primaire, alors que
    # `SOURCES_MAJEURES` valorise déjà l'OMS, la Commission et France Stratégie
    # (+35) : elles n'étaient simplement jamais collectées. Elles ne pouvaient
    # apparaître qu'en aval, si DuckDuckGo les trouvait.
    #
    # Ces trois-là sont les SEULES retenues sur 30 URL testées avec le parseur
    # du pipeline (`scripts/test_flux_candidats.py`). Rendement mesuré avant
    # ajout, jamais supposé :
    #     OMS français          20 items →  5 candidats (dont un à 85 points,
    #                                       très au-dessus du sommet actuel)
    #     Commission européenne 20 items →  3 candidats
    #     France Stratégie      10 items →  1 candidat
    # Écartées faute de rendement : CNIL (0 candidat), Parlement européen (0),
    # Autorité de la concurrence (1, un titre de formulaire), ANSES et INSEE
    # (offres de stage). Injoignables ou URL fausses : Cour des comptes,
    # Légifrance, Banque de France, Météo-France, INRAE, CEA, IGN, Pasteur,
    # Défenseur des droits, ADEME, Vie publique, Assemblée nationale.
    #
    # ⚠ Testé depuis une machine ordinaire. Les WAF de `.gouv.fr` renvoient 403
    # à l'IP des runners GitHub : surveiller `[RSS ERREUR]` sur France Stratégie
    # au premier run, et le retirer s'il est bloqué. L'OMS et la Commission ne
    # sont pas concernées.
    #
    # L'OMS est prise en FRANÇAIS : la version anglaise rendait 13 candidats
    # mais `detect_category` et les lexiques de score ne fonctionnent que sur du
    # français, les sujets auraient été mal classés.
    # OMS RETIRÉE le 12/08 après un seul run. Elle répond 200 depuis une
    # machine ordinaire — testée avec les en-têtes du pipeline, sans en-tête et
    # avec un UA navigateur, 306 ko à chaque fois — mais renvoie 400 depuis le
    # runner GitHub. Blocage par IP, donc rien à corriger côté code : c'est le
    # cas documenté « il faut remplacer la source, changer d'adresse n'y change
    # rien ». Une source morte coûte jusqu'à 12 s de timeout par run.
    # C'était la meilleure prise de la journée du 11/08 (un candidat à 85
    # points, très au-dessus du reste) : si une adresse OMS accessible depuis un
    # datacenter est trouvée un jour, elle vaut la peine d'être retentée — mais
    # via `check_feeds.py`, qui teste DEPUIS le runner. La tester d'ici ne
    # prouve rien, c'est exactement l'erreur que ce commentaire documente.
    {"name": "Commission européenne", "url": "https://ec.europa.eu/commission/presscorner/api/rss?language=fr&pagesize=30"},
    {"name": "France Stratégie",     "url": "https://www.strategie.gouv.fr/rss.xml"},
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


def _extraire_texte_pdf(contenu: bytes) -> str:
    """Texte d'un PDF officiel (rapport, arrêt, étude) — matière que le
    pipeline n'atteignait jamais avant le 05/08.

    Constat en lisant la page « logiciel libre » d'un confrère 100 % IA plus
    étoffé que nous (Poppler dans leur pile) : nos sources DuckDuckGo pointent
    régulièrement vers des PDF (Cour des comptes, Sénat, IGAS, institutions
    européennes) — exactement les documents que le sourcing par question du
    05/08 est censé aller chercher. Sans extraction dédiée, ces liens ne
    servaient à rien : `fetch_full_content` passait le PDF brut à
    BeautifulSoup comme si c'était du HTML, qui n'en tirait que du bruit ou
    une chaîne vide. pypdf est pur Python — aucun binaire système requis,
    contrairement à poppler/pdftotext, donc rien à installer sur le runner."""
    try:
        from pypdf import PdfReader
        from io import BytesIO
    except Exception:
        # Volontairement large (pas seulement ImportError) : une dépendance
        # de pypdf peut échouer à l'import pour des raisons d'environnement
        # sans rapport avec le PDF lui-même — un sujet entier ne doit jamais
        # se perdre pour ça, on repart avec un simple manque de matière.
        return ""
    try:
        reader = PdfReader(BytesIO(contenu))
        # Un rapport officiel peut faire des centaines de pages : on ne lit
        # que le début, largement suffisant pour le résumé exécutif et les
        # premiers constats chiffrés, et ça borne le temps d'extraction.
        pages = reader.pages[:25]
        texte = " ".join(p.extract_text() or "" for p in pages)
        return re.sub(r"\s+", " ", texte).strip()
    except Exception:
        # PDF corrompu, chiffré ou scanné sans couche texte (image pure) :
        # on ne fait pas d'OCR ici, on repart avec une chaîne vide plutôt que
        # de faire planter l'enrichissement d'un sujet entier.
        return ""


def fetch_full_content(url: str) -> str:
    """Scrape le contenu complet d'un article depuis son URL.
    Refuse les éditeurs de presse protégés (droits voisins)."""
    if _est_presse_protegee(url):
        return ""
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        content_type = (r.headers.get("Content-Type") or "").lower()
        if "application/pdf" in content_type or url.lower().split("?")[0].endswith(".pdf"):
            return _extraire_texte_pdf(r.content)[:8000]
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
    "ird.fr",  # institut public de recherche ajouté le 28/07
    # ── Ajouts du 05/08, avec le sourcing par question ────────────────────
    # Ces domaines sont visés par les nouveaux axes de recherche (voir
    # `_AXES_RECHERCHE`). Sans les déclarer ici, un arrêt de la CJUE ou un
    # rapport de l'OCDE compterait « tertiaire » et ne vaudrait rien pour la
    # règle « ≥1 primaire OU ≥2 secondaires » — la recherche aurait ramené la
    # bonne source et le contrôle l'aurait ignorée.
    # (legifrance/eur-lex/curia/eurostat/drees/dares sont déjà couverts par
    #  les suffixes .gouv.fr, .europa.eu et .int ci-dessus.)
    "oecd.org", "ipcc.ch", "citepa.org", "efsa.europa.eu",
    "imf.org", "worldbank.org", "fao.org", "unesco.org", "ilo.org",
    "eurofound.europa.eu", "echr.coe.int", "coe.int",
    "defenseurdesdroits.fr", "cnil.fr", "arcom.fr", "autoritedelaconcurrence.fr",
    "igas.gouv.fr", "strategie.gouv.fr", "france-strategie.gouv.fr",
    "observatoire-des-inegalites.fr", "ofce.sciences-po.fr",
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
    "courrierinternational.com", "slate.fr",  # ajoutés le 28/07
    # Organismes de VÉRIFICATION (05/08) — ils ne sont pas « primaires » (ils
    # ne produisent pas le fait) mais ce sont eux qui établissent si une
    # affirmation publique est étayée. C'est la matière qui manquait le plus à
    # nos articles : sans eux, on rapporte une polémique sans jamais pouvoir
    # dire ce que les vérifications en disent.
    "factuel.afp.com", "newtral.es", "fullfact.org", "maldita.es",
    "correctiv.org", "faktencheck.afp.com", "snopes.com", "politifact.com",
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


# ── Juge de pertinence documentaire ──────────────────────────────────────────
# Question FERMÉE et vérifiable : « ce document traite-t-il du sujet précis de
# l'article ? » — à ne pas confondre avec « ce sujet mérite-t-il un article ? »,
# jugement éditorial dont le backtest du 12/08 a rendu 50 %, soit le hasard.
#
# Petit modèle assumé : la réponse tient en un mot. Faire juger la pertinence
# par le modèle qui rédige coûterait le prix d'un article pour une question à
# trois issues.
JUGE_SOURCES_MODELE = os.getenv("JUGE_SOURCES_MODELE", "") or "openai/gpt-oss-20b"
# `llama-3.1-8b-instant` a été retiré par Groq le 17/08 en même temps que le
# modèle de rédaction : le juge est tombé sur NotFoundError aux 20 sujets du
# run de 18h58. `openai/gpt-oss-20b` est servi (vérifié sur GET /models) et
# convient : la tâche demande UN mot de réponse, pas de raisonnement long.
# Il reste distinct du modèle de rédaction, ce que le garde-fou exige.
# Nombre de sources examinées, dans l'ordre de qualité déjà établi. Les 45
# résultats bruts ne partent pas tous dans le prompt : juger la queue serait
# payer pour classer ce qui ne sera pas lu.
JUGE_SOURCES_MAX = int(os.getenv("JUGE_SOURCES_MAX", "10"))

_PROMPT_PERTINENCE = """Tu vérifies si un document peut servir de source à un article de presse.

On te donne le TITRE de l'article, puis un DOCUMENT (institution, titre, URL).

Question unique : ce document traite-t-il du sujet PRÉCIS de l'article, ou
seulement de son thème général ?

Réponds PERTINENTE si le document porte sur l'événement, l'étude, la décision
ou le chiffre précis annoncé par le titre de l'article.

Réponds GENERALE si le document ne traite que du thème large — une fiche
encyclopédique, une page « données » permanente, un portail de rubrique, un
dossier de fond — sans porter sur le fait précis de l'article.

Réponds HORS_SUJET si le document parle d'autre chose.

On te donne PLUSIEURS documents numérotés. Réponds une ligne par document, dans
l'ordre, au format exact « n: VERDICT » — rien d'autre, aucune explication.

Exemple pour trois documents :
1: PERTINENTE
2: GENERALE
3: HORS_SUJET"""


def juger_pertinence_sources(titre: str, sources: list) -> bool:
    """Annote `sources` d'un `_pertinence` et dit si le jugement a eu lieu.

    NE LÈVE JAMAIS et ne bloque jamais : sans clé, sans réseau, sur erreur API
    ou sur réponse inattendue, la fonction renonce et laisse les sources telles
    quelles — l'appelant retombe alors sur le tri par qualité seul. Perdre un
    article entier parce qu'un juge auxiliaire a échoué serait absurde : il
    améliore le classement, il n'est pas indispensable à la publication.

    ⚠ LEÇON DU 13/08, À NE PAS OUBLIER : ce repli n'a PAS protégé le pipeline.
    Le site d'appel passait `sujet.get("title")` alors que le paramètre de
    `generer_article` s'appelle `item` — un `NameError` levé en ÉVALUANT
    l'argument, donc avant même d'entrer ici. Deux runs morts sur le premier
    sujet, deux jours sans publication.

    Les quatre angles couverts par `test_pertinence_sources.py` (pas de clé,
    pas de réseau, erreur d'API, réponse inattendue) étaient les bons ; le
    cinquième — l'appel ne part jamais — ne pouvait par construction être vu
    par aucun d'eux. **Un garde-fou interne ne protège jamais son propre site
    d'appel.** Tester une fonction en isolation ne dit rien de son intégration :
    c'est `pyflakes` sur tout `scripts/`, ajouté en CI le 13/08, qui attrape
    cette classe d'erreur — en une seconde et sans quota.
    """
    if os.getenv("JUGE_SOURCES", "1") == "0" or not titre or not sources:
        return False
    if not GROQ_ALL_KEYS:
        return False
    # Les limites Groq (TPM comme TPD) sont PAR MODÈLE : voir `_TPM_PAR_MODELE`,
    # qui donne 12 000 tokens/min au 70b et 6 000 au 8b — deux compteurs
    # distincts. Le juge tourne donc sur un stock que le rédacteur n'utilise
    # pas, et son coût contre le budget de génération est nul.
    #
    # Cette propriété disparaît si le juge est pointé sur le modèle de
    # rédaction : il se met alors à consommer le quota qui bloque déjà les runs
    # (les 7 comptes étaient à 90-99 % du TPD le 12/08), et rien ne le
    # signalerait. On refuse plutôt que de le faire en silence.
    if JUGE_SOURCES_MODELE == GROQ_MODEL:
        print(f"     [PERTINENCE] juge désactivé : il utiliserait {GROQ_MODEL}, "
              f"le modèle de rédaction, et mangerait son quota. "
              f"Régler JUGE_SOURCES_MODELE sur un petit modèle distinct.")
        return False
    # UN SEUL APPEL POUR TOUTES LES SOURCES (17/08). La première version posait
    # une question par source — jusqu'à 10 appels par sujet, tous sur
    # `GROQ_ALL_KEYS[0]`, jamais sur la rotation. Compté sur un run à 20 sujets :
    #
    #   génération + vérification   ~72 appels, répartis sur 6 clés  → ~12/clé
    #   juge de pertinence         ~200 appels, TOUS sur la clé 1    → ~200
    #                                                                  ───────
    #   clé 1, par run                                                 ~212
    #
    # Le plafond gratuit est de 250 requêtes/jour et 30/minute : un run passait,
    # deux non — et il y en a deux ou trois de programmés. Le juge aurait donc
    # fait tomber le run sur un plafond de REQUÊTES au moment précis où le
    # passage à `groq/compound` supprime le plafond de TOKENS.
    #
    # Le groupage ramène ~200 appels à ~20 et supprime au passage la répétition
    # du prompt système dix fois par sujet. Le tour de clé suit le sujet, ce qui
    # répartit enfin la charge.
    try:
        _cle = GROQ_ALL_KEYS[abs(hash(titre)) % len(GROQ_ALL_KEYS)][0]
        client = _client(_cle)
    except Exception as e:  # noqa: BLE001
        print(f"     [PERTINENCE] juge indisponible ({type(e).__name__}) — tri par qualité seul")
        return False

    lot = list(sources[:JUGE_SOURCES_MAX])
    blocs = []
    for i, s in enumerate(lot, 1):
        url = s.get("url", "")
        blocs.append(
            f"--- DOCUMENT {i} ---\n"
            f"institution : {s.get('institution') or _media_name_from_url(url, '') or 'Source'}\n"
            f"titre du document : {s.get('titre') or s.get('title') or ''}\n"
            f"adresse : {urlparse(url).netloc}{urlparse(url).path}")
    try:
        r = client.chat.completions.create(
            model=JUGE_SOURCES_MODELE,
            messages=[{"role": "system", "content": _PROMPT_PERTINENCE},
                      {"role": "user",
                       "content": f"ARTICLE : {titre}\n\n" + "\n".join(blocs)}],
            temperature=0, max_tokens=12 * len(lot) + 20)
        reponse = (r.choices[0].message.content or "").strip().upper()
    except Exception as e:  # noqa: BLE001
        # On renonce sans insister : le juge n'est qu'un tri, il ne doit jamais
        # faire attendre un run.
        print(f"     [PERTINENCE] interrompu ({type(e).__name__}) — tri par qualité seul")
        return False

    # Lecture par NUMÉRO, jamais par position dans la réponse : un modèle qui
    # saute une ligne ou en ajoute une décalerait tous les verdicts suivants et
    # attribuerait à chaque source celui de sa voisine — silencieusement.
    juges = 0
    for ligne in reponse.splitlines():
        m = re.match(r"\s*(\d+)\s*[:.\)-]\s*(.+)", ligne)
        if not m:
            continue
        idx = int(m.group(1)) - 1
        if not 0 <= idx < len(lot):
            continue
        mot = m.group(2)
        if "HORS" in mot:
            lot[idx]["_pertinence"] = "hors_sujet"
        elif "GENERALE" in mot or "GÉNÉRALE" in mot:
            lot[idx]["_pertinence"] = "generale"
        elif "PERTINENTE" in mot:
            lot[idx]["_pertinence"] = "pertinente"
        else:
            continue  # réponse inattendue : on ne classe pas au hasard
        juges += 1
    if juges < len(lot):
        print(f"     [PERTINENCE] {juges}/{len(lot)} source(s) classée(s) — "
              f"les autres restent triées par qualité")
    return juges > 0


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


# ══════════════════════════════════════════════════════════════════════════════
# SOURCING PAR QUESTION — et non plus par corroboration (05/08)
# ══════════════════════════════════════════════════════════════════════════════
# Constat comparatif du 05/08 (Nahil, sur un confrère 100 % IA) : à sujet égal,
# ils publient 21 sources dont des textes de droit primaire, deux arrêts de
# justice, des séries statistiques et deux organismes de vérification ; nous en
# publions 4, presque toujours des reprises de la même dépêche (médiane mesurée
# sur nos 149 articles).
#
# La cause n'était pas la qualité de la recherche mais sa QUESTION. Nos trois
# requêtes demandaient « qui d'autre parle de ce sujet ? » — une logique de
# corroboration, qui ne peut par construction ramener que des articles de
# presse. Une logique de recherche demande « quels documents établissent les
# faits de ce sujet ? », et va chercher le texte de loi, l'arrêt, la série
# statistique, le rapport d'audit, la vérification.
#
# C'est aussi la racine du déficit de matière qui nous a fait créer le format
# brève : ces documents étaient disponibles, on ne les cherchait pas.
#
# Chaque axe ne coûte AUCUN token Groq — seule l'injection dans le prompt est
# facturée, et elle reste bornée par BUDGET_MATIERE. Le coût d'un axe est une
# requête DDG (~1-2 s), payée une fois par sujet.
_AXES_UNIVERSELS = (
    # (nom, suffixe de requête) — joués sur TOUS les sujets.
    ("générique", ""),
    ("officiel/juridique",
     "site:legifrance.gouv.fr OR site:eur-lex.europa.eu OR site:curia.europa.eu "
     "OR site:conseil-etat.fr OR site:vie-publique.fr"),
    ("contrôle/audit",
     "rapport site:ccomptes.fr OR site:senat.fr OR site:assemblee-nationale.fr "
     "OR site:igas.gouv.fr OR site:defenseurdesdroits.fr"),
    ("vérification",
     "vérification site:factuel.afp.com OR site:lemonde.fr OR site:newtral.es "
     "OR site:fullfact.org"),
    # ── CONTRADICTION (15/08) ────────────────────────────────────────────────
    # Les quatre axes ci-dessus demandent tous QUI ÉTABLIT le fait. Aucun ne
    # demande QUI LE CONTESTE. Un article sourcé uniquement par ce qui va dans
    # son sens n'est pas neutre : il est unanime par construction, et son
    # unanimité est un artefact de la requête, pas un état du débat.
    #
    # C'est aussi la cause matérielle d'un défaut mesuré : « Débats et
    # nuances » doit contenir limites, incertitudes et désaccords. Quand la
    # recherche n'a rapporté aucun désaccord, la section se remplit de
    # généralités — « il est essentiel de renforcer la vigilance ». On ne
    # demandait simplement jamais au moteur de les trouver.
    #
    # Le vocabulaire est volontairement celui du DÉSACCORD ARGUMENTÉ (critiques,
    # limites, réserves, contestation) et non celui de la polémique : on cherche
    # l'objection étayée d'un chercheur, d'une ONG ou d'une autorité, pas la
    # réaction indignée. Coût : une requête DuckDuckGo, zéro token Groq.
    ("contradiction",
     "critiques OR limites OR réserves OR contestation OR \"remis en cause\""),
)

# Axes supplémentaires selon la rubrique — c'est ce qui distingue une recherche
# d'une requête générique : on ne cherche pas les mêmes documents pour un
# sujet santé et pour un sujet économique.
_AXES_PAR_CATEGORIE = {
    "sante": (
        ("santé officielle",
         "site:has-sante.fr OR site:ansm.sante.fr OR site:santepubliquefrance.fr "
         "OR site:who.int OR site:efsa.europa.eu"),
        ("littérature médicale",
         "étude site:pubmed.ncbi.nlm.nih.gov OR site:thelancet.com OR site:nejm.org "
         "OR site:inserm.fr"),
    ),
    "science": (
        ("publication scientifique",
         "site:nature.com OR site:science.org OR site:pnas.org OR site:cnrs.fr "
         "OR site:cea.fr"),
    ),
    "environnement": (
        ("environnement officiel",
         "site:ademe.fr OR site:citepa.org OR site:ipcc.ch OR site:meteofrance.fr "
         "OR site:eea.europa.eu OR site:anses.fr"),
    ),
    "economie": (
        ("statistiques économiques",
         "chiffres site:insee.fr OR site:banque-france.fr OR site:oecd.org "
         "OR site:ec.europa.eu OR site:dares.travail-emploi.gouv.fr"),
    ),
    "societe": (
        ("statistiques publiques",
         "chiffres site:insee.fr OR site:drees.solidarites-sante.gouv.fr "
         "OR site:ined.fr OR site:observatoire-des-inegalites.fr"),
    ),
    "tech": (
        ("régulation numérique",
         "site:cnil.fr OR site:arcom.fr OR site:autoritedelaconcurrence.fr "
         "OR site:digital-strategy.ec.europa.eu"),
    ),
}


def _requetes_recherche(query: str, categorie: str = "") -> list[tuple[str, str]]:
    """Construit les requêtes de recherche documentaire pour un sujet.

    Retourne une liste de (nom_axe, requête). 4 axes universels + 1 à 2 axes
    propres à la rubrique, soit 5 à 6 requêtes par sujet."""
    axes = list(_AXES_UNIVERSELS) + list(_AXES_PAR_CATEGORIE.get((categorie or "").lower(), ()))
    return [(nom, f"{query} {suffixe}".strip()) for nom, suffixe in axes]


def duckduckgo_search(query: str, max_results: int = 8, categorie: str = "") -> list[dict]:
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

    rendement_axes: list[str] = []
    for nom_axe, q in _requetes_recherche(query, categorie):
        avant = len(results)
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
                        "_axe":    nom_axe,
                    })
        except Exception:
            pass
        rendement_axes.append(f"{nom_axe} +{len(results) - avant}")

    # Rendement PAR AXE : sans ça, on ne saura pas lesquels rapportent
    # réellement des documents et lesquels sont du temps perdu — c'est la
    # mesure qui permettra d'élaguer ou d'étendre `_AXES_PAR_CATEGORIE` sur
    # des chiffres relevés plutôt que devinés.
    _q = Counter(qualite_source(r["url"]) for r in results)
    print(f"     [SOURCING] {len(results)} sources — "
          f"{_q.get('primaire', 0)} primaire(s), {_q.get('secondaire', 0)} secondaire(s), "
          f"{_q.get('tertiaire', 0)} tertiaire(s)  |  " + " · ".join(rendement_axes))

    # BUG CORRIGÉ (30/07), toujours valable : ne JAMAIS interrompre la boucle
    # sur `len(results) >= max_results`. Les axes documentaires (juridique,
    # audit, vérification, rubrique) passent APRÈS l'axe générique — s'arrêter
    # au plafond revient à ne jamais les exécuter, ce qui était exactement le
    # cas avant le 30/07 : le pipeline exigeait une source primaire tout en
    # sautant la seule requête conçue pour en trouver une.
    # On coupe donc UNIQUEMENT à la fin, après avoir joué tous les axes, et le
    # tri par qualité (primaire d'abord) est fait par l'appelant.
    #
    # ── MAIS COUPER PAR ORDRE D'ARRIVÉE REPRODUISAIT LE MÊME BUG (15/08) ─────
    # `results[:max_results]` tronque dans l'ordre où les axes ont été joués.
    # L'axe générique passe en premier et rapporte le plus, si bien que les
    # DERNIERS axes se faisaient couper les premiers — exactement le défaut du
    # 30/07, déplacé de la boucle vers la troncature. L'ajout d'un cinquième
    # axe (« contradiction », 15/08), placé en fin de liste, l'aurait rendu
    # inopérant sans qu'aucun message ne le signale.
    #
    # On sert donc les axes À TOUR DE RÔLE : chacun place son meilleur
    # résultat, puis son deuxième, et ainsi de suite jusqu'au plafond. L'ordre
    # interne à chaque axe est préservé, aucun axe ne peut être vidé par un
    # autre, et un axe peu productif ne bloque personne — sa file s'épuise et
    # les autres continuent.
    if len(results) <= max_results:
        return results
    files: dict[str, list] = {}
    for r in results:
        files.setdefault(r.get("_axe", "?"), []).append(r)
    equitable, i = [], 0
    while len(equitable) < max_results and any(len(f) > i for f in files.values()):
        for f in files.values():
            if i < len(f):
                equitable.append(f[i])
                if len(equitable) >= max_results:
                    break
        i += 1
    return equitable


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

        # RSS utilise <item>, Atom utilise <entry> — et Atom met tout dans un
        # namespace, donc root.iter("item") ne trouvait RIEN sur un flux Atom.
        # Aucune erreur n'était levée : la source renvoyait simplement 0 article
        # en silence, en paraissant fonctionner dans les logs. C'était le cas de
        # The Conversation France (articles.atom), muette depuis son ajout
        # (constat 28/07). On repère les entrées par leur nom de balise LOCAL,
        # namespace ignoré.
        def _local(tag) -> str:
            return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""

        def _texte(el, *noms) -> str:
            """findtext insensible au namespace, sur plusieurs noms possibles."""
            for enfant in el:
                if _local(enfant.tag) in noms:
                    if enfant.text and enfant.text.strip():
                        return enfant.text.strip()
                    # Atom : <link href="…"/> porte l'URL en attribut
                    href = enfant.get("href")
                    if href:
                        return href.strip()
            return ""

        entrees = [e for e in root.iter() if _local(e.tag) in ("item", "entry")]

        items = []
        for item in entrees:
            title = _texte(item, "title")
            link  = _texte(item, "link", "id")
            # RSS : description / content:encoded — Atom : summary / content
            desc  = _texte(item, "description", "summary", "content", "encoded")
            # Contenu complet si disponible (content:encoded, namespacé)
            full  = item.find("content:encoded", ns)
            content_raw = full.text if full is not None and full.text else desc

            # Nettoyer le HTML dans le contenu
            if content_raw:
                soup = BeautifulSoup(content_raw, "html.parser")
                content_clean = soup.get_text(separator=" ", strip=True)
            else:
                content_clean = ""

            pub_date = _texte(item, "pubDate", "published", "updated") or datetime.now().isoformat()

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

        # Plafond par flux : 8 → 20 (28/07). À 8, le gisement était borné à
        # ~230 articles/run AVANT tout filtre, alors que Le Monde publie à lui
        # seul plusieurs dizaines d'articles par jour et par rubrique. Ce
        # plafond ne coûte rien en quota Groq : il n'élargit que le vivier où
        # `selectionner_meilleurs` puise ses nb_max sujets — plus de choix à
        # score égal, donc de meilleurs candidats, pas davantage de générations.
        return items[:MAX_ITEMS_PAR_FLUX]

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
# TEST CLOS (31/07) — NON CONCLUANT, mots-clés réintégrés ci-dessous.
# Mesure sur le run du 31/07 matin : 3 sujets sur 14 tentés (21 %) ont été
# générés en entier — ~17 k tokens chacun — puis rejetés « sujet sensible »
# par la vérification LLM (mineurs, migrants victimes de sévices,
# personnalités politiques). Le prompt strict ne suffit donc PAS à les
# traiter : ils passent la collecte, consomment le quota, et meurent à la
# dernière étape. Les rejeter à la collecte rend ce budget aux sujets
# publiables. Ne pas les retirer à nouveau sans mesurer le taux de rejet
# « sujet sensible » en aval.

BLACKLIST = [
    # ── Sujets sensibles — affinés le 31/07 ────────────────────────────────
    # Le critère de `sujet_sensible` (verification.py) n'est PAS le thème mais
    # la MISE EN CAUSE DE PERSONNES : mineur impliqué, affaire pénale en cours
    # visant des personnes, critique nominale. Bloquer « guerre » ou « parti
    # politique » ratait donc la cible : ça éliminait « guerre commerciale »,
    # « guerre des prix » et l'analyse institutionnelle d'un conflit — des
    # sujets sans aucune personne mise en cause — tout en laissant passer des
    # récits de victimes qui ne contiennent pas ces mots.
    # On bloque désormais le VOCABULAIRE DE VICTIMES ET DE PROCÉDURE PÉNALE,
    # qui est ce que la vérification refuse réellement en aval. Le géopolitique
    # et l'institutionnel sans personnes nommées repassent.
    "fait divers", "meurtre", "assassinat", "accident mortel",
    "attentat", "terrorisme",
    # Victimes (le motif n°1 des rejets mesurés le 31/07)
    "victimes civiles", "sévices", "torture", "massacre", "charnier",
    "viol ", "agression sexuelle", "pédocriminal", "maltraitance",
    "bombardement", "frappe meurtrière", "otage",
    # Procédure pénale visant des personnes
    "mis en examen", "garde à vue", "mise en examen", "inculpé",
    "procès de", "condamné à de la prison",
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

# ── Communication de marque déguisée en actualité ────────────────────────────
# Constat 30/07 (Nahil) : « Amazon Prime Video organise Obsessed Fest pour les
# fans de comédies romantiques » figurait parmi les 78 candidats d'un run. Ce
# n'est pas de l'information, c'est un communiqué de presse — mais il ne
# déclenchait RIEN : pas de prix (donc `_COMMERCE_RE` muet), pas de vocabulaire
# sportif, un contenu long et frais d'une source « média reconnu », donc même
# un bonus de densité. Le barème ne savait pas distinguer « une entreprise fait
# quelque chose d'intéressant » de « une entreprise fait sa promotion ».
#
# Le motif exige DEUX éléments : une marque/plateforme ET un verbe de
# communication. La marque seule ne suffit jamais — « Netflix perd 2 millions
# d'abonnés » ou « Amazon condamné par la Commission européenne » sont de
# vraies actualités et doivent passer.
_MARQUES_PROMO = (
    r"amazon|prime video|netflix|disney\+?|apple tv|canal\+?|paramount\+?"
    # « meta » est volontairement ABSENT : le mot matche la balise <meta> et
    # s'emploie couramment hors marque. On vise les plateformes par leur nom
    # de produit, jamais par un mot ambigu.
    r"|spotify|deezer|tiktok|snapchat|instagram|facebook|whatsapp|youtube|twitch"
    r"|ubisoft|nintendo|playstation|xbox|steam"
)
# « annonce » et « propose » ont été TESTÉS puis retirés : ce sont les verbes
# neutres de l'actualité d'entreprise (« TikTok annonce lutter contre l'AI
# slop » est un vrai sujet), et ils faisaient le seul faux positif mesuré sur
# les 154 articles publiés. On ne garde que les verbes d'événementiel.
_PROMO_VERBES = (
    # « célèbre » retiré : c'est aussi un adjectif très courant (« un célèbre
    # mathématicien »), il produisait un faux positif sur un article publié.
    r"organise|dévoile|inaugure"
    r"|met en ligne|donne rendez-vous|s'associe"
)
_PR_MARQUE_RE = re.compile(
    rf"\b(?:{_MARQUES_PROMO})\b.{{0,60}}\b(?:{_PROMO_VERBES})\b"
    rf"|\b(?:{_PROMO_VERBES})\b.{{0,60}}\b(?:{_MARQUES_PROMO})\b"
    # « pour les fans de… », « à ne pas manquer » : adresse au public-cible,
    # marqueur de communication et jamais de compte rendu factuel.
    rf"|pour les fans de|à ne pas manquer|disponible dès maintenant"
    rf"|nouvelle saison de|bande[- ]annonce",
    re.IGNORECASE,
)

# ── Divertissement / culture-spectacle : malus, pas rejet ────────────────────
# Une sortie de série ou un casting n'est pas illégitime en soi, mais ce n'est
# pas ce que Les Faits cherche à traiter. On rétrograde plutôt que d'exclure :
# un festival peut avoir une portée réelle (financement public, polémique).
_DIVERTISSEMENT_RE = re.compile(
    r"\b(?:s[ée]rie|saison \d|[ée]pisode|casting|acteur|actrice|r[ée]alisateur"
    r"|box[- ]office|blockbuster|spin[- ]off|reboot|tr[ai]iler"
    r"|album|clip|tourn[ée]e|concert|festival|jeu vid[ée]o|streaming)\b",
    re.IGNORECASE,
)

# ── Enjeu public : le signal POSITIF qui manquait au barème ──────────────────
# Le barème ne récompensait que des propriétés de forme (source connue,
# longueur, fraîcheur, chiffres). Rien ne mesurait ce qui rend un sujet
# intéressant : une décision, une mesure, une donnée qui engage des gens.
# Ce bonus est ce qui doit faire remonter un rapport de la Cour des comptes
# au-dessus d'un communiqué de plateforme de streaming.
_ENJEU_PUBLIC_RE = re.compile(
    r"\b(?:d[ée]cret|loi\b|r[ée]forme|r[ée]glementation|directive|jugement"
    r"|condamn[ée]|amende|enqu[êe]te|rapport|audit|plainte|proc[èe]s"
    r"|budget|financement|subvention|imp[ôo]t|taxe|cotisation|retraite"
    r"|h[ôo]pital|[ée]cole|logement|transport|[ée]nergie|climat|pollution"
    r"|[ée]missions|biodiversit[ée]|s[ée]cheresse|canicule"
    r"|essai clinique|vaccin|[ée]pid[ée]mie|mortalit[ée]|pr[ée]valence"
    r"|ch[ôo]mage|salaire|pouvoir d'achat|in[ée]galit[ée]s|pauvret[ée])\b",
    re.IGNORECASE,
)

# Contenu commercial déguisé en article : prix précis + enseigne de vente
_COMMERCE_RE = re.compile(
    # ATTENTION : toujours accepter les DEUX écritures de la devise, « € » et
    # le mot « euros ». Écrire seulement « € » a laissé passer l'article même
    # qui a motivé cette règle — « Lidl : 5 appareils de cuisine à moins de 10
    # euros » (26/07) — alors que la variante « à moins de 10 € » était bien
    # rejetée. Les motifs « perd/chute de X euros » plus bas, écrits ensuite,
    # géraient déjà le mot ; l'incohérence a survécu à l'élargissement du 26/07.
    #
    # ── 11/08 : le « € » était accepté MAIS INERTE ──────────────────────────
    # `(?:€|euros?)\b` : après « euros » le « s » crée une frontière de mot,
    # mais « € » est non-alphanumérique et ce qui le suit l'est rarement
    # (virgule, espace, fin de titre) — donc `\b` échouait et TOUT prix écrit
    # avec le symbole passait au travers. Mesuré le 11/08 : « À moins de
    # 400 €, ce PC portable Acer tombe à pic » a consommé une des six
    # tentatives du run, générée en entier avant d'être rejetée pour « angle
    # insuffisant ». La frontière est désormais portée par le mot seul.
    r"(?:à partir de|dès|seulement|au prix de|(?:à\s+)?moins de)\s*\d+[.,]?\d*\s*(?:€|euros?\b)"
    r"|\d+[.,]\d{2}\s*(?:€|euros?\b)\s*(?:chez|sur)\b"
    r"|chez\s+(?:cdiscount|amazon|aliexpress|rakuten|darty|boulanger|leclerc|carrefour|lidl|aldi|action)"
    r"|(?:cdiscount|aliexpress|rakuten)\b"
    r"|^\d+\s+\w+.{0,40}\b(?:lidl|aldi|action|cdiscount|amazon)\b"
    # Bons plans / promos déguisés en article (ex: "le Dell 16 perd 350 euros").
    # Motifs volontairement étroits : "promotion" seul ou "moins cher" seul
    # apparaissent dans de vrais articles (promotion sociale, essence moins
    # chère) — on ne matche que le vocabulaire marketing sans ambiguïté.
    r"|bons? plans?\b|\bpromos?\b|\ben promo\b|ventes? flash|prix cassés?"
    r"|meilleures? offres?|\d+\s*%\s*de\s*r[ée]duction|offre à saisir"
    # Variantes relevées le 11/08 : « perd 38 % de son prix », « une offre à ne
    # pas rater ». Le motif « perd X euros » ne couvrait que la devise, jamais
    # le pourcentage, et « meilleures offres » ne couvrait pas « à ne pas
    # rater/manquer ». Ce titre scorait 60 et occupait la 6e place du tri.
    r"|(?:perd|chute de|baisse de)\s+\d+\s*%\s*(?:de\s+)?(?:son|le)\s+prix"
    r"|prix\s+(?:chute|baisse|perd)\s+de\s+\d+\s*%"
    r"|offres?\s+à\s+ne\s+pas\s+(?:rater|manquer)"
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
        # Télécoms : angle mort du lexique jusqu'au 28/07 — un article sur le
        # bannissement de Huawei des réseaux télécoms européens ne déclenchait
        # AUCUN mot-clé "tech" et retombait sur les mots génériques du lexique
        # "science" (« étude », « chercheurs »…).
        "télécom", "opérateur mobile", "huawei", "zte", "ericsson", "nokia",
        "fibre optique", "équipementier",
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
# Plafond par catégorie. ATTENTION : ce quota borne la sélection AVANT nb_max —
# avec 6 catégories, un quota de 3 plafonnait la sélection à 18 sujets, quel que
# soit nb_max. Constat 29/07 : 655 articles collectés, 71 candidats après
# filtre… et exactement 18 retenus, alors que nb_max valait 36. Porté à 6 pour
# que nb_max redevienne le vrai plafond (6 × 6 = 36). Toute hausse de nb_max
# doit s'accompagner d'une hausse d'ici, sinon elle n'a aucun effet.
QUOTA_CATEGORIE = 6
# Société : plafond légèrement réduit — catégorie fourre-tout où atterrissent
# les papiers d'ambiance ; 3 max par créneau (relevé de 2 le 13/07 après une
# matinée où seulement 9 candidats au total ont passé le filtre RSS et où
# 3 sujets société solides ont été écartés par le quota alors que les autres
# catégories n'avaient qu'un candidat chacune).
# Société reste plus contrainte : catégorie fourre-tout où atterrissent les
# papiers d'ambiance.
QUOTA_PAR_CATEGORIE = {"societe": 6}


# Mots-clés à FAIBLE pouvoir discriminant : ils apparaissent dans le corps de
# presque n'importe quel article ("une étude montre…", "les chercheurs…",
# "l'entreprise…", "la société…"). Comptés 3 points au même titre qu'un terme
# décisif comme "exoplanète", ils faisaient gagner leur catégorie par simple
# accumulation dans le corps — et "science", 2e de _CAT_PRIORITE, remportait
# en prime toutes les égalités. D'où « Transport aérien / détroit d'Ormuz »
# classé science (28/07). Ils ne comptent donc QUE dans le titre, et pour
# 2 points au lieu de 3 : un titre reste un signal fiable, pas le corps.
_MOTS_FAIBLES = {
    "étude ", "chercheurs", "scientifique", "expérience ", "laboratoire",
    "évolution ", "cellule", "physique", "chimie", "biologie", "espèce ",
    "entreprise", "société", "milliard", "commerce", "application",
    "croissance", "expérience", "traitement",
}


def _scores_categories(text: str) -> dict:
    """Score lexical brut par catégorie : un mot-clé trouvé dans le titre
    (≈120 premiers caractères) pèse 3, dans le corps 1. Les mots-clés à faible
    pouvoir discriminant (_MOTS_FAIBLES) ne comptent que dans le titre, pour 2."""
    text_l = text.lower()
    head   = text_l[:120]
    scores = {}
    for cat, kws in CATEGORIES_MAP.items():
        s = 0
        for kw in kws:
            faible = kw in _MOTS_FAIBLES
            if kw in head:
                s += 2 if faible else 3
            elif not faible and kw in text_l:
                s += 1
        scores[cat] = s
    return scores


# Score minimum pour qu'un classement soit jugé fiable. À 1 point — un seul
# mot-clé croisé au détour du corps — c'est du bruit, et l'égalité entre deux
# catégories à 1 point était tranchée par _CAT_PRIORITE, donc au profit de
# "science" (2e de la liste) : « Transport aérien / détroit d'Ormuz » a été
# classé science sur le seul mot « spatial » croisé dans le corps, à égalité
# avec « industrie » pour économie. En dessous du seuil, on assume la rubrique
# fourre-tout plutôt qu'un faux classement spécifique.
SCORE_CATEGORIE_MIN = 2


def detect_category(text: str) -> str:
    """Classement déterministe par lexique pondéré. En cas d'égalité,
    _CAT_PRIORITE départage du plus spécifique au plus générique."""
    scores = _scores_categories(text)
    best = max(_CAT_PRIORITE, key=lambda c: scores[c])
    return best if scores[best] >= SCORE_CATEGORIE_MIN else "societe"


def _age_heures(date_str: str) -> float:
    """Retourne l'âge en heures d'une date RSS (approximatif)."""
    from email.utils import parsedate_to_datetime
    try:
        dt = parsedate_to_datetime(date_str)
        dt = dt.replace(tzinfo=None)
        return max(0, (datetime.now() - dt).total_seconds() / 3600)
    except Exception:
        return 48.0  # inconnu → considéré comme vieux


_MOTS_GENERIQUES_CACHE: dict[int, frozenset] = {}
DF_MOT_GENERIQUE = 3  # présent dans ≥3 titres publiés = vocabulaire de rubrique

# ── Poids du barème, extraits en constantes (10/08) ───────────────────────────
# Ils étaient codés en dur dans `score_editorial`, donc impossibles à faire
# varier pour mesurer leur effet. Les valeurs ci-dessous sont EXACTEMENT celles
# d'avant : cette extraction ne change rien au comportement, elle rend
# seulement le barème testable (`scripts/mesure_ab_bareme.py`).
#
# Ce qu'on cherche à corriger, mesuré le 10/08 sur 610 items : 10 grappes de
# ≥3 médias sur 14 franchissent le seuil de sélection, mais UNE SEULE est
# retenue — les faits majeurs passent le seuil puis perdent le classement
# contre des pièces de magazine mono-source. Le +35 « source majeure » est une
# prime au NOM DU MÉDIA, pas au sujet, et il domine tous les autres termes.
PONDS_SOURCE_MAJEURE = 35
PONDS_MEDIA_RECONNU = 15
PONDS_ENJEU_FORT = 30
PONDS_ENJEU_MOYEN = 15
# Malus « aucun marqueur d'actualité » : ni chiffre, ni institution nommée, ni
# enjeu public. Un texte qui n'a aucun des trois n'est presque jamais un fait
# du jour. 0 = désactivé (comportement d'avant le 10/08).
MALUS_SANS_SUBSTANCE = 0


def _mots_generiques_corpus(published_topics: set) -> frozenset:
    """Formes présentes dans au moins `DF_MOT_GENERIQUE` titres déjà publiés.

    Calculé une fois par run (le même jeu de titres sert à tous les candidats),
    mémoïsé sur l'identité du set — `score_editorial` est appelé des centaines
    de fois par run et recalculer 140 titres à chaque appel serait absurde.
    """
    cle = id(published_topics)
    if cle not in _MOTS_GENERIQUES_CACHE:
        import unicodedata
        from collections import Counter

        def _formes(s: str) -> set[str]:
            s = unicodedata.normalize("NFD", s or "")
            s = "".join(c for c in s if unicodedata.category(c) != "Mn")
            return set(w[:8] for w in s.lower().split() if len(w) > 5)

        df: Counter = Counter()
        for t in published_topics:
            df.update(_formes(t))
        _MOTS_GENERIQUES_CACHE.clear()  # un seul corpus vivant à la fois
        _MOTS_GENERIQUES_CACHE[cle] = frozenset(
            m for m, c in df.items() if c >= DF_MOT_GENERIQUE
        )
    return _MOTS_GENERIQUES_CACHE[cle]


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

    # Communication de marque : un communiqué n'est pas une actualité
    if _PR_MARQUE_RE.search(text[:800]):
        return -1, ["Communication de marque (marque + verbe événementiel)"]

    # Seuil de contenu : 300 caractères — SAUF pour la presse protégée et les
    # sources de référence. Ce filtre est censé écarter les sujets sans
    # substance ; il mesurait en réalité la GÉNÉROSITÉ DU FLUX. Or les 20
    # médias de `_PRESSE_PROTEGEE` ne diffusent qu'un chapeau court (droits
    # voisins), et les flux institutionnels un simple intitulé. Constat 30/07 :
    # 10 sources sur 36 ne produisaient AUCUN candidat — Le Monde Planète,
    # Le Monde Idées, Le Monde Décodeurs, Libération, Le Parisien, France
    # Culture, Numerama, Slate, et surtout le Sénat et Santé Publique France,
    # deux sources PRIMAIRES. Le pipeline jetait la presse de référence parce
    # qu'elle respecte le droit voisin.
    # Ce n'est pas un assouplissement : la matière de l'article ne vient pas
    # du teaser RSS mais des sources recherchées ensuite (jusqu'à 26), et tous
    # les contrôles de fond restent inchangés.
    _seuil_contenu = 300
    _src_connue = (any(s in src or s in text[:200] for s in SOURCES_MAJEURES)
                   or any(s in src for s in SOURCES_MEDIAS))
    if _est_presse_protegee(item.get("url", "")) or _src_connue:
        _seuil_contenu = 140
    if len(item["content"]) < _seuil_contenu:
        return -1, [f"Contenu trop court : {len(item['content'])} chars (min {_seuil_contenu})"]

    # ── BARÈME POSITIF ───────────────────────────────────────────────────────

    # Source majeure (+35)
    is_majeure = any(s in src or s in text[:200] for s in SOURCES_MAJEURES)
    if is_majeure:
        score += PONDS_SOURCE_MAJEURE
        reasons.append(f"+{PONDS_SOURCE_MAJEURE} source majeure")

    # Source média reconnu (+15, non cumulable avec majeure)
    elif any(s in src for s in SOURCES_MEDIAS):
        score += PONDS_MEDIA_RECONNU
        reasons.append(f"+{PONDS_MEDIA_RECONNU} média reconnu")

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

    # ── BONUS ENJEU PUBLIC : ce que « meilleur » devrait vouloir dire ───────
    # Le reste du barème ne note que la FORME (source connue, longueur,
    # fraîcheur). Rien n'y mesurait l'intérêt du sujet lui-même, si bien qu'un
    # communiqué de plateforme de streaming, long et frais, pouvait devancer
    # un rapport de la Cour des comptes. Ce bonus note la PORTÉE : décision
    # publique, argent public, santé, environnement, travail — ce qui engage
    # des gens. Bonus fort à partir de 3 marqueurs pour ne pas récompenser une
    # mention isolée ; le titre pèse double, c'est là qu'est le vrai sujet.
    title_lower_brut = item["title"].lower()
    marqueurs = set(m.group(0).lower() for m in _ENJEU_PUBLIC_RE.finditer(debut))
    marqueurs_titre = set(m.group(0).lower() for m in _ENJEU_PUBLIC_RE.finditer(title_lower_brut))
    poids = len(marqueurs) + 2 * len(marqueurs_titre)
    if poids >= 4:
        score += PONDS_ENJEU_FORT
        reasons.append(f"+{PONDS_ENJEU_FORT} enjeu public fort (poids {poids} : {sorted(marqueurs)[:3]})")
    elif poids >= 2:
        score += PONDS_ENJEU_MOYEN
        reasons.append(f"+{PONDS_ENJEU_MOYEN} enjeu public (poids {poids} : {sorted(marqueurs)[:3]})")

    # Malus « aucun marqueur d'actualité » : ni chiffre, ni institution nommée,
    # ni enjeu public. Composé uniquement de signaux déjà calculés ci-dessus —
    # aucun nouveau détecteur, donc rien de nouveau à calibrer. Désactivé par
    # défaut (MALUS_SANS_SUBSTANCE = 0).
    if MALUS_SANS_SUBSTANCE and nb_chiffres == 0 and not a_institution and poids == 0:
        score -= MALUS_SANS_SUBSTANCE
        reasons.append(f"-{MALUS_SANS_SUBSTANCE} aucun marqueur d'actualité "
                       f"(0 chiffre, 0 institution, 0 enjeu public)")

    # ── MALUS DIVERTISSEMENT / CULTURE-SPECTACLE ────────────────────────────
    # Rétrogradation, pas rejet : un festival ou une série peuvent avoir une
    # portée réelle (financement public, polémique). Mais à défaut d'enjeu
    # identifié, ils ne doivent pas occuper une des rares places de génération.
    if _DIVERTISSEMENT_RE.search(title_lower_brut):
        score -= 30
        reasons.append("-30 divertissement/culture-spectacle (titre)")
    elif _DIVERTISSEMENT_RE.search(debut):
        score -= 15
        reasons.append("-15 divertissement/culture-spectacle (contenu)")

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

    # ── Mots GÉNÉRIQUES du corpus : ignorés dans le test de doublon (10/08) ──
    # Mesure sur une collecte réelle (619 items, 36 sources) : le barème place
    # en tête des pièces de magazine mono-source, et COULE les faits les plus
    # couverts de la journée — sur 12 grappes de ≥3 médias, 4 sont écartées par
    # cette pénalité, dont Gaza/Trump (8 médias) et le détroit d'Ormuz.
    # Le rapprochement se faisait sur des mots présents partout : « découverte »
    # apparaît dans 12 des 140 titres publiés, « France » dans 12, « recherche »
    # et « publique » dans 3. Partager « découverte » avec un article déjà
    # publié ne dit rien du sujet — c'est du vocabulaire de rubrique.
    # Distribution mesurée sur les 140 titres : 529 formes, dont 90 % dans UN
    # seul titre et 3 % seulement dans 3 titres ou plus. Le seuil de 3 isole
    # donc les 14 formes réellement génériques sans toucher au vocabulaire
    # distinctif — « éclipse », « drones », « détroit » restent à DF=1.
    # Ne PAS descendre ce seuil à 2 sans refaire la mesure : 54 formes (10 %)
    # y passeraient, dont des mots parfaitement discriminants.
    _generiques = _mots_generiques_corpus(published_topics)

    title_words = _norm_words(item["title"])
    for topic in published_topics:
        topic_words = _norm_words(topic)
        shared = (title_words & topic_words) - _generiques
        overlap = len(shared)
        # Il faut DEUX mots communs pour conclure au doublon. La règle
        # précédente rejetait sur un seul mot dès qu'il faisait 8 caractères —
        # or, une fois les mots tronqués à 8 caractères pour absorber les
        # variantes singulier/pluriel, « faire 8 caractères » ne veut plus dire
        # « être rare » : ça désigne n'importe quel mot d'au moins 8 lettres.
        # Résultat mesuré sur les 129 titres publiés (28/07) : 49 % d'entre eux
        # se rejetaient mutuellement, sur des collisions absurdes — « Huawei
        # face à un bannissement » vs « Apple accélère ses mises à jour de
        # SÉCURITÉ », « Comores : six médinas HISTORIQUES » vs « Vague de
        # chaleur HISTORIQUE », « CAN FÉMININE » vs « Douleurs chroniques
        # FÉMININES ». Avec deux mots communs exigés : 15 %, et le vrai doublon
        # visé (les deux articles sur la carie néandertalienne) reste attrapé,
        # il partage 4 mots. Ne jamais revenir à un rejet sur un seul mot.
        if overlap >= 2:
            score -= 500  # rejet quasi-certain : même sujet déjà publié
            reasons.append(f"-500 sujet très redondant (overlap: {overlap}, mots: {sorted(shared)[:3]} avec '{topic[:40]}')")
            break
        elif overlap == 1:
            # Simple voisinage lexical : on rétrograde, on ne tue pas. À -60,
            # tout candidat sous 80 points passait sous le seuil de sélection
            # (20) — c'était un second rejet déguisé sur un seul mot commun.
            score -= 25
            reasons.append(f"-25 sujet proche (1 mot commun avec '{topic[:40]}')")
            break

    return score, reasons


# Compteurs de rejet du filtre éditorial, remplis par `filtrer_et_classer` et
# vidés au début de chaque run. Diagnostic seul : ils n'influencent rien.
_STATS_REJETS: "Counter[str]" = Counter()
_STATS_REJETS_SOURCE: "Counter[str]" = Counter()


def _titre_norme(titre: str) -> str:
    """Titre réduit à sa forme comparable : accents et ponctuation retirés."""
    import unicodedata
    t = unicodedata.normalize("NFD", titre or "")
    t = "".join(c for c in t if unicodedata.category(c) != "Mn").lower()
    return " ".join(re.findall(r"\w+", t))[:70]


# ── ACHARNEMENT SUR UN SUJET DÉJÀ CONDAMNÉ ────────────────────────────────
# Mesuré le 17/08 sur `verification_log.json` : 11 sujets totalisent 42
# générations complètes, dont 31 sont des REPRISES d'un sujet déjà rejeté sur
# `angle_insuffisant` — soit ~1,1 M tokens, un quota journalier entier, dépensé
# à re-condamner. Le record : « nouvelles addictions » 11 fois, Edgar Morin 7
# fois en 5 jours.
#
# ⚠ Le seuil est mesuré, pas choisi. Les deux retours gagnants connus (un sujet
# rejeté puis publié plus tard) ont demandé 1 et 3 rejets préalables. Bloquer
# dès la 2e tentative les tuerait tous les deux ; bloquer à partir de la 3e
# économise 20 générations (~700 k tokens) et n'en coûte qu'un. C'est ce troc-là
# qui est retenu.
#
# ⚠ Levier DISTINCT de celui écarté le 15/08. Celui-là proposait d'allonger
# `REJECT_COOLDOWN_HOURS` (36 h) et tuait 5 des 6 premières reprises, qui sont
# souvent gagnantes — refusé après mesure. Ici on ne touche pas à la première
# reprise : on arrête l'acharnement au-delà. Ne pas confondre les deux.
ACHARNEMENT_MIN_REJETS = 2      # bloque à partir de la (n+1)e tentative
ACHARNEMENT_FENETRE_J = 7       # au-delà, le sujet peut revenir avec un angle neuf


def _sujets_condamnes(maintenant: datetime | None = None) -> set[str]:
    """Sujets rejetés au moins `ACHARNEMENT_MIN_REJETS` fois sur l'angle.

    ⚠ Appariement par ÉGALITÉ EXACTE de titre normalisé, jamais par similarité.
    Le rapprochement approximatif de titres a été rustiné trois fois (26/07,
    28/07, 02/08) et s'est révélé faux chaque fois : sur 161 titres publiés,
    aucun critère ne sépare le vrai doublon du faux positif. Un blocage ici est
    coûteux (le sujet ne sera plus jamais tenté de la fenêtre), donc on n'accepte
    que la certitude.

    La clé est le `titre_rss` journalisé depuis le 14/08, à défaut le slug
    généré. Ne JAMAIS utiliser `item["id"]` : c'est un md5 d'URL, et une même
    dépêche reprise par un autre flux ou republiée avec un paramètre de tracking
    donne un id différent (bug du 30/07).

    Ne lève jamais : journal absent ou illisible → ensemble vide, aucun blocage.
    """
    try:
        chemin = Path("data/verification_log.json")
        if not chemin.exists():
            return set()
        entrees = json.loads(chemin.read_text(encoding="utf-8"))
        if not isinstance(entrees, list):
            return set()
        limite = (maintenant or datetime.now()) - timedelta(days=ACHARNEMENT_FENETRE_J)
        compte: Counter = Counter()
        for e in entrees:
            if not isinstance(e, dict) or not e.get("angle_insuffisant"):
                continue
            try:
                quand = datetime.fromisoformat(str(e.get("date", "")).replace("Z", "+00:00"))
                if quand.tzinfo is not None:
                    quand = quand.replace(tzinfo=None)
            except ValueError:
                continue
            if quand < limite:
                continue
            cle = _titre_norme(e.get("titre_rss") or "") or _titre_norme(e.get("slug") or "")
            if cle:
                compte[cle] += 1
        return {k for k, n in compte.items() if n >= ACHARNEMENT_MIN_REJETS}
    except Exception as exc:  # noqa: BLE001
        print(f"  [ACHARNEMENT] journal illisible ({type(exc).__name__}) — aucun blocage")
        return set()


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
            # Comptage par MOTIF : sans ça, on ne sait pas où meurent les
            # ~88 % de candidats perdus entre la collecte et le scoring, et on
            # en est réduit à des hypothèses sur le barème.
            _STATS_REJETS[reasons[0].split(" :")[0].split(" (")[0]] += 1
            _STATS_REJETS_SOURCE[source_name] += 1
        else:
            item["_score"]   = score
            item["_reasons"] = reasons
            item["_reject"]  = score < seuil_score
            item["_cat"]     = detect_category(item["title"] + " " + item["content"])
            if item["_reject"]:
                _STATS_REJETS[f"Score sous le seuil ({seuil_score})"] += 1
                _STATS_REJETS_SOURCE[source_name] += 1
        resultats.append(item)

    return sorted(
        [i for i in resultats if not i.get("_reject")],
        key=lambda x: x["_score"],
        reverse=True,
    )


# Procédure pénale visant une PERSONNE — à distinguer soigneusement du thème.
# Le critère retenu par la charte depuis le 31/07 n'est pas le sujet (guerre,
# justice, faits divers) mais la MISE EN CAUSE d'une personne. On ne liste donc
# ici que du vocabulaire de procédure, jamais des thèmes : « corruption »,
# « trafic » ou « violences » seuls désignent aussi bien un rapport de la Cour
# des comptes qu'une affaire individuelle, et les inclure déclasserait des
# sujets d'intérêt public parfaitement publiables.
_PROCEDURE_PENALE_RE = re.compile(
    r"\b(?:mis(?:e)? en examen|mis(?:e)? en cause|garde [àa] vue|"
    r"information judiciaire|enqu[êe]te judiciaire|instruction judiciaire|"
    r"soup[çc]onn[ée]|accus[ée] de|poursuivi(?:e)? pour|inculp[ée]|"
    r"compara[îi]t|comparution|r[ée]quisitions?|proc[èe]s (?:de|du|de la|contre)|"
    # `\d+` et non `\d` : sur « condamné à 18 mois », un `\d` unique laisse la
    # frontière de mot tomber entre le 1 et le 8 et le motif échoue. Même piège
    # de `\b` que celui trouvé dans le filtre commercial le 11/08.
    r"condamn[ée] [àa] (?:\d+|de la prison|(?:une|la) peine|la perp[ée]tuit[ée]|mort)|"
    r"plainte contre|"
    r"mandat d'arr[êe]t|perquisition|"
    # ── Ce qui PRÉCÈDE la procédure (14/08) ─────────────────────────────────
    # Les motifs ci-dessus ne voient que le vocabulaire judiciaire une fois la
    # procédure nommée. Or le fil RSS livre d'abord le décès, et la procédure
    # n'est nommée que plus tard : le 14/08, « Une femme retrouvée morte dans
    # la chaufferie d'un hôpital » a été classée 1re sur 156 candidats, a
    # consommé une génération entière (~40 k tokens) et a été rejetée
    # `sujet_sensible` — « affaire pénale en cours visant une personne ». Le
    # même événement occupait aussi la 3e place sous un autre titre.
    #
    # Mesuré sur les 610 items du corpus gelé : 2,8 % → 3,8 % de déclassements,
    # soit 6 items de plus, tous corrects (un père écroué, deux enquêtes du
    # parquet, un magistrat du parquet). Vérifié sur le classement réel du
    # 14/08 : déclasse les n°1 et n°3, NE TOUCHE PAS la brève Insee publiée.
    #
    # Rappel : ceci reste une CLÉ DE TRI, jamais un rejet (cf.
    # `selectionner_meilleurs`). Ces sujets restent dans le vivier et sont
    # tentés si les meilleurs sont épuisés.
    # PAS de « meurtre », « homicide », « assassinat », « féminicide » : ce sont
    # des THÈMES, pas des procédures, et la règle en tête de ce bloc les exclut
    # explicitement. Essayés le 14/08, ils déclassaient « Le nombre d'homicides
    # recensés par le ministère de l'Intérieur » — une statistique publique,
    # soit exactement le sujet d'intérêt public à garder en tête de file. Les
    # affaires individuelles restent prises par « mis en examen », « parquet
    # de… » ou « retrouvé mort », qui décrivent une procédure ou un cas précis.
    r"d[ée]c[èe]s suspect|mort suspecte|"
    r"ouverture d['’]une enqu[êe]te|enqu[êe]tes? (?:ouverte|confi[ée]e)"
    r")\b"
    # Radicaux TRONQUÉS : jamais suivis de `\b`, la frontière échouerait sur la
    # lettre suivante (« retrouvée », « retrouvés »). Groupe séparé pour cette
    # seule raison.
    r"|(?:retrouv[ée]{1,2}s? (?:mort|sans vie)"
    r"|corps (?:sans vie|retrouv|d[ée]couvert)"
    r"|parquet (?:de |du |saisi|a ouvert|ouvre))",
    re.IGNORECASE,
)


def _est_procedure_penale_personne(texte: str) -> int:
    """1 si le texte relève d'une procédure pénale visant une personne, sinon 0.

    Sert de CLÉ DE TRI (les 1 passent en fin de file), jamais de rejet. Retourne
    un entier pour être utilisable directement comme clé de `sorted`.
    """
    return 1 if _PROCEDURE_PENALE_RE.search(texte or "") else 0


# Âge maximum d'un sujet pour que la persistance lui vaille un bonus. Au-delà,
# l'article n'est plus une actualité même s'il traîne encore dans les fils —
# voir la mesure dans `selectionner_meilleurs`. Le pipeline tournant deux fois
# par jour, 36 h laissent passer deux créneaux : un sujet monté dans la nuit
# reste éligible au run du lendemain soir.
VEILLE_AGE_MAX_H = 36


def selectionner_meilleurs(
    candidats: list[dict],
    nb_max: int = 10,
    quota_cat: int = QUOTA_CATEGORIE,
) -> list[dict]:
    """
    Sélectionne les nb_max meilleurs articles en respectant le quota par catégorie.

    ── Déclassement des procédures pénales visant une personne (11/08) ───────
    Mesure sur les 308 sujets tentés depuis juillet, avec leur verdict réel :

        procédure pénale visant une personne   n=11   1 publié   10/10 « sensible »
        catastrophe / épidémie (victimes)      n=31   7 publiés  23 %

    La première catégorie est refusée par le fact-checker avec une constance
    parfaite : la tenter, c'est dépenser une des 6 tentatives du run pour un
    rejet certain. La seconde SE PUBLIE — une mesure antérieure qui mélangeait
    les deux sous « vocabulaire de victimes » était trompeuse et concluait à
    tort qu'il fallait aussi écarter les catastrophes et les épidémies.

    On DÉCLASSE, on n'exclut pas : ces sujets restent dans le vivier et passent
    en fin de file. Si les meilleurs sont épuisés, ils sont tentés quand même.
    Un malus de score aurait été plus simple mais aurait valu exclusion — sous
    le seuil de 20, un candidat moyen pénalisé disparaît du vivier.
    """
    # ── SIGNAL DE VEILLE — phase 2, 14/08 ────────────────────────────────────
    # Le barème note la FORME d'un candidat : source connue, fraîcheur,
    # longueur, densité de chiffres. Rien n'y mesure si le fait COMPTE. C'est
    # la cause mesurée du goulot — 64 % des rejets qualité sont des sujets
    # jugés creux, après ~35 000 jetons dépensés.
    #
    # La veille apporte enfin cette mesure, et on la branche sur ce qu'elle a
    # d'EXACT : la persistance d'un article dans les fils. Un fait qui compte y
    # reste plusieurs heures ; un communiqué disparaît au passage suivant.
    # Cette valeur se lit sur un item isolé, appariée par URL canonique, sans
    # aucun rapprochement approximatif.
    #
    # On n'utilise DÉLIBÉRÉMENT pas le nombre de rédactions couvrant le fait,
    # qui serait pourtant plus riche : il exige de regrouper les articles, et
    # le backtest du 13/08 a montré que notre regroupement fusionne des sujets
    # sans rapport. Un regroupement erroné GONFLE ce compteur — un seuil haut y
    # est donc plus exposé qu'un seuil bas. Il est journalisé, pas utilisé :
    # quelques runs diront lequel des deux prédit la publication.
    #
    # BONUS, jamais malus. Un candidat absent du journal (flux ajouté depuis,
    # dépêche parue entre deux passages, veille jamais lancée) garde son score
    # d'origine : la veille ne peut qu'ajouter de l'information, jamais en
    # retirer à un sujet qu'elle n'a pas vu.
    try:
        from veille import signal_editorial
        _sig = signal_editorial([i.get("url", "") for i in candidats if i.get("url")])
    except Exception as e:  # noqa: BLE001
        print(f"     [VEILLE] signal indisponible ({type(e).__name__}) — barème seul")
        _sig = {}

    if _sig:
        _vus = 0
        for i in candidats:
            s = _sig.get(i.get("url", ""))
            if not s:
                continue
            _vus += 1
            # DEUX conditions, jamais la persistance seule.
            #
            # `heures_visible` grandit mécaniquement avec l'âge : une page
            # permanente laissée trois jours dans un flux atteindrait le palier
            # maximum sans rien avoir d'une actualité — précisément le sujet de
            # magazine que le fact-checker recale ensuite pour « angle
            # insuffisant ». Mesuré sur les 2 908 items du journal :
            #
            #   persistant (>=6 h) ET récent (<=36 h)   737    ← signal
            #   persistant MAIS vieux                  1156    ← bruit
            #
            # Sans la borne d'âge, le bonus irait à une majorité de faux
            # positifs. C'est la règle « confirmé ET frais » établie le 13/08,
            # appliquée ici pour la première fois.
            #
            # Paliers volontairement grossiers : la mesure est jeune (70 h), et
            # un barème fin sur des données jeunes est une précision inventée.
            h = s["heures_visible"]
            bonus = 0 if s["age_h"] > VEILLE_AGE_MAX_H else 25 if h >= 6 else 15 if h >= 2 else 0
            i["_score"] = i.get("_score", 0) + bonus
            i["_veille"] = s
            if bonus:
                i.setdefault("_reasons", []).append(
                    f"veille : visible {h:.0f} h (+{bonus})")
        print(f"     [VEILLE] {_vus}/{len(candidats)} candidats retrouvés dans le journal, "
              f"{sum(1 for i in candidats if i.get('_veille', {}).get('heures_visible', 0) >= 6)} "
              f"persistants (>=6 h)")

    # `sorted` est stable : à statut égal l'ordre par score est préservé.
    candidats = sorted(
        candidats,
        key=lambda i: (_est_procedure_penale_personne(
            f"{i.get('title', '')} {i.get('content', '')[:600]}"),
            -i.get("_score", 0)),
    )

    selection = []
    compteur  = {}

    # UN SEUL SUJET PAR ÉVÉNEMENT DANS UN MÊME RUN.
    #
    # Constat du 14/08, en rejouant la sélection sur les 863 dépêches du jour :
    # la censure par le Conseil constitutionnel de l'interdiction des réseaux
    # sociaux aux moins de 15 ans occupait SIX des onze premières places, sous
    # six titres différents — « Les Sages ont censuré », « le Conseil
    # constitutionnel censure », « l'interdiction s'effondre »… Sur un run à six
    # tentatives, c'était le run entier consacré à un seul fait, et six articles
    # quasi identiques publiés dans la même heure.
    #
    # Le filtre anti-doublon historique ne pouvait pas les voir : il compare les
    # MOTS DES TITRES, et six rédactions couvrant la même décision écrivent six
    # titres sans mot distinctif commun. C'est le quatrième défaut de cette
    # famille depuis juillet, et CLAUDE.md interdit d'en tenter un cinquième
    # rustinage par les titres.
    #
    # La veille, elle, les compte DÉJÀ ensemble : elle les a regroupés. Le
    # pipeline ne le savait pas parce qu'il ne le lui demandait pas. On lui
    # demande.
    #
    # ⚠ Le regroupement est imparfait et documenté comme tel. Ici, cela n'a
    # PAS la même gravité qu'ailleurs : un regroupement trop large ne fait que
    # reporter un sujet au run suivant, jamais publier un doublon. Le risque est
    # borné du bon côté — c'est ce qui rend ce branchement acceptable alors
    # qu'on refuse d'utiliser le même regroupement pour le bonus de score.
    grappes_vues: set = set()
    condamnes = _sujets_condamnes()
    if condamnes:
        print(f"     [ACHARNEMENT] {len(condamnes)} sujet(s) rejeté(s) "
              f"≥{ACHARNEMENT_MIN_REJETS} fois sur l'angle — non retentés")

    for item in candidats:
        if len(selection) >= nb_max:
            break
        if _titre_norme(item.get("title", "")) in condamnes:
            print(f"     [ACHARNEMENT] déjà condamné {ACHARNEMENT_MIN_REJETS}× — "
                  f"« {item.get('title', '')[:64]} »")
            continue
        cat = item.get("_cat", "societe")
        if compteur.get(cat, 0) >= QUOTA_PAR_CATEGORIE.get(cat, quota_cat):
            continue
        _grappe = (item.get("_veille") or {}).get("grappe")
        if _grappe and _grappe in grappes_vues:
            print(f"     [DOUBLON RUN] même événement déjà retenu — "
                  f"« {item.get('title', '')[:64]} »")
            continue
        selection.append(item)
        if _grappe:
            grappes_vues.add(_grappe)
        compteur[cat] = compteur.get(cat, 0) + 1

    return selection


# ══════════════════════════════════════════════════════════════════════════════
# GÉNÉRATION VIA GROQ
# ══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """Tu es l'IA rédactrice de Les Faits, journal numérique français indépendant.
Ligne éditoriale absolue : "Juste les faits. Aucun parti pris."

RÉPONDS UNIQUEMENT EN JSON VALIDE, sans texte avant ou après, sans bloc ```json.

⚠ PARAGRAPHES — MÉCANISME OBLIGATOIRE (11/08) : dans "faits", "contexte" et
"nuances", insère un caractère de saut de ligne (\n) entre chaque paragraphe.
C'est le SEUL moyen technique de séparer visuellement les paragraphes à
l'affichage — un texte de plus de 3-4 phrases sans aucun \n s'affiche comme UN
SEUL bloc ininterrompu, illisible, quel que soit le nombre de phrases ou leur
qualité individuelle. Découpe par IDÉE : un paragraphe = un fait principal ou
un groupe de faits liés, jamais une simple liste de phrases juxtaposées sans
lien. Une section de 450 mots tient normalement en 3 à 5 paragraphes.

⚠ VARIÉTÉ DE PHRASE — INTERDICTION DE LA CHAÎNE MONOTONE (15/08) : jamais plus
de 2 phrases consécutives construites sur le moule "[Acteur] a/ont [verbe]"
(ex. « L'Insee a confirmé… », « La Banque de France a dressé… », « Le Conseil
a décidé… », « Le Sénat a abordé… » à la suite = interdit, même avec des
verbes différents à chaque fois). Ce ne sont pas des reformulations, c'est une
scansion répétitive qui rend le texte illisible même quand chaque phrase est
correcte. Alterne les attaques de phrase : le CHIFFRE en tête (« 2,1 %, c'est
le niveau atteint par… »), une subordonnée (« Alors que les prix du gaz
grimpent de 10,3 %, … »), ou la fusion de deux faits liés dans UNE phrase au
lieu de deux phrases séparées sur le même acteur. Si deux faits proviennent de
la même famille (deux composantes d'un même chiffre, deux décisions du même
organisme), regroupe-les dans une seule phrase plutôt que d'en faire deux
phrases consécutives identiques en structure.

Format obligatoire :
{
  "angle_reponse": "UNE question précise, formulée du point de vue du LECTEUR, à laquelle tout l'article va répondre — pas le thème du sujet, la question qu'il se pose en le lisant. Exemple sur un afflux migratoire massif : « Ce chiffre change-t-il quelque chose pour la France ? », pas « Que s'est-il passé ? ». Cette question dicte tout ce qui suit : les intertitres, le choix des faits à développer, la conclusion. Un article qui ne fait que résumer un sujet sans y répondre a échoué, même s'il est bien écrit.",
  "titre": "Titre factuel informatif, 6 à 15 mots, sans exclamation ni question",
  "slug": "slug-kebab-case-descriptif-max-65-chars",
  "image_keyword": "3 mots EN ANGLAIS — paysage, bâtiment ou objet UNIQUEMENT, jamais de visages ni personnes (ex: 'wheat field france', 'hospital building', 'solar panels europe')",
  "resume": [
    "Phrase 1 : ANNONCE le fait principal (qui, quoi) en une accroche synthétique — un SEUL chiffre-clé maximum. Ne livre PAS ici tout le détail chiffré : le décompte complet, les montants, les pourcentages détaillés vont dans 'faits'. Le résumé donne envie de lire 'faits', il ne le remplace pas. Vocabulaire et syntaxe DIFFÉRENTS de 'faits'.",
    "Phrase 2 : l'enjeu essentiel (qui/quand/pourquoi ça compte), avec des mots différents de la section 'contexte' (2 lignes min).",
    "Phrase 3 : nuance, limite ou débat en cours (2 lignes min)."
  ],
  "titre_faits": "Intertitre ÉDITORIAL de la section 'faits' — 4 à 9 mots qui annoncent ce que cette section établit, pas un nom de fonction. JAMAIS 'Les faits'. Il doit servir 'angle_reponse' : ex. sur le chiffre d'un afflux migratoire, « Le chiffre brut, et ce qu'il recouvre réellement » plutôt que « Les faits ». Doit être compréhensible seul, sans lire le reste de l'article.",
  "corps": {
    "faits": "VISE 450 mots — autant que la matière le permet, jamais plus qu'elle n'en porte. C'est ICI que vit le détail complet, PAS dans le résumé : l'actualité immédiate et TOUTES ses données du jour — chiffres précis, décompositions, montants, dates, acteurs nommés, résultats quantitatifs, déclarations exactes avec citation numérotée (voir FORMAT DE CITATION ci-dessous). RÈGLE ANTI-REDONDANCE : chaque phrase doit apporter une donnée que le résumé n'a PAS déjà donnée. Si 'faits' ne fait que reformuler le résumé, l'article échoue — développe, chiffre, détaille au-delà de l'accroche. NE JAMAIS inclure d'historique, d'évolution sur plusieurs années ni de comparaisons internationales — cela va exclusivement dans 'contexte'. JAMAIS d'URL dans le texte. Utiliser plusieurs paragraphes.",
    "contexte": "VISE 200 mots, sans élargir le sujet pour y arriver. UNIQUEMENT de l'historique et de la mise en perspective DIRECTEMENT liés au sujet PRÉCIS de l'article — pas au thème général. RESTE CENTRÉ : n'élargis pas à des sujets connexes (budget global de l'État, modèle économique d'ensemble, politique générale du secteur) sauf s'ils sont INDISPENSABLES pour comprendre CE fait précis. Mieux vaut un contexte court et pertinent qu'un contexte large et dilué. Évolutions sur 5-10 ans, comparaisons, cadre réglementaire ou scientifique du sujet exact. NE JAMAIS reprendre les faits déjà énoncés dans 'faits'. Chiffres comparatifs obligatoires.",
    "nuances": "150 mots SI LES SOURCES CONTIENNENT DE QUOI LES ÉCRIRE — sinon, chaîne VIDE (voir la règle du plancher conditionnel). RÔLE EXCLUSIF — répondre à : « Qu'est-ce qu'un lecteur devrait savoir avant de tirer une conclusion ? ». UNIQUEMENT des informations NOUVELLES : limites, incertitudes, désaccords, points non encore établis, positions des acteurs. TOUTE projection ou hypothèse future ('pourrait être réduit', 'devrait augmenter', 'risque de') doit être ATTRIBUÉE PRÉCISÉMENT à qui l'énonce (annonce officielle, responsable nommé, rapport daté) — sinon RETIRE-la, ne l'invente jamais. INTERDIT de répéter, reformuler ou résumer un fait déjà présenté dans 'faits' ou 'contexte'. Limites méthodologiques, désaccords entre experts, ce que les données ne permettent pas de conclure."
  },
  "titre_contexte": "Intertitre éditorial de 'contexte', même logique que 'titre_faits' — ex. « Un pic hors norme, une mécanique déjà vue » plutôt que « Contexte ».",
  "titre_nuances": "Intertitre éditorial de 'nuances' — ex. « Ce que les vérifications en disent » ou « Ce qui reste établi, et ce qui ne l'est pas » plutôt que « Débats et nuances ». Doit annoncer une VRAIE tension ou incertitude présente dans le texte, jamais un intitulé générique interchangeable d'un article à l'autre.",
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

FORMAT DE CITATION — NOTES NUMÉROTÉES, PAS D'ATTRIBUTION EN PROSE (05/08).
Ce journal citait jusqu'ici « Selon Le Monde, RTBF et 20 Minutes, … » dans le
corps du texte. Sur un article à 10-20 sources, ça empile les noms de médias
et rend le texte illisible — c'est le défaut n°1 relevé par une revue externe.
Le corps ne nomme donc PLUS aucune source : chaque fait vérifiable porte un
numéro entre crochets renvoyant à sa position dans le tableau 'sources' (le
1er élément du tableau = [1], le 2e = [2], etc.) :
    « Le ministère de l'Intérieur espagnol parle de 50 000 entrées [1]. Le
      gouvernement autonome de Ceuta avance 60 000 [2]. »
Si PLUSIEURS sources rapportent le même fait, groupe leurs numéros à la fin de
LA PHRASE UNIQUE qui le rapporte — jamais une phrase par source :
    « L'incendie a touché un entrepôt classé Seveso, provoquant le
      confinement de 30 000 habitants [1][3][5]. »
Une phrase peut porter plusieurs faits distincts, chacun avec SON numéro au
point où il est énoncé — ne rejette pas tous les numéros en fin de phrase si
plusieurs faits différents s'y trouvent. Le nom d'un média ou d'une
institution peut apparaître dans le texte SEULEMENT si le fait porte sur cet
acteur lui-même (« Human Rights Watch estime que… », « l'Insee a révisé son
estimation »), jamais comme simple attribution d'un chiffre.

RÈGLES ABSOLUES — toute violation = article rejeté :
1. MINIMUM 4 sources distinctes et citables. Si tu ne peux pas atteindre 4 sources réelles : réponds uniquement HORS_PERIMETRE
2. Chaque donnée chiffrée DOIT porter sa citation numérotée [n] au point où elle est énoncée (voir FORMAT DE CITATION) — JAMAIS d'URL dans le corps du texte, les URLs sont réservées au tableau sources
3. Corps total : plancher ABSOLU 350 mots combinés, cible 800 si la matière le porte. Ne JAMAIS atteindre un volume en répétant, en généralisant ou en comblant : 380 mots établis valent mieux que 800 dont 300 sont du remplissage. Matière insuffisante pour 350 : HORS_PERIMETRE
4. Résumé : chaque phrase minimum 25 mots, concrète, avec au moins un fait mesurable. INTERDIT de commencer par une phrase générique du type "Ce sujet est un défi", "Cette découverte pourrait changer", "Il est essentiel de comprendre", "s'inscrit dans une dynamique" — entrer DIRECTEMENT dans le fait principal avec chiffres ou acteurs.
5. Aucun adjectif évaluatif sans source (alarmant, historique, sans précédent, incroyable...)
6. Aucune opinion. Aucun parti pris. Chaque fait cité porte sa citation numérotée [n] (voir FORMAT DE CITATION) — jamais de nom de média dans le texte pour ça.
7. Titre : 6-15 mots, informatif, factuel — il doit résumer l'essentiel de l'article
8. Sources préférées : institutions officielles (INSEE, CNRS, INSERM, Eurostat, OMS, gouvernement), journaux de référence, publications peer-reviewed, textes de loi et jurisprudence, organismes de vérification — MAIS uniquement si leur URL figure dans SOURCES DISPONIBLES. RÈGLE DE CITATION : ne mets un numéro [n] sur un fait que si ce fait figure LITTÉRALEMENT dans l'extrait CONTENU fourni pour la source n. Ne pas inventer, ne pas extrapoler depuis la mémoire d'entraînement. Si une institution que tu connais n'est pas dans la liste SOURCES DISPONIBLES, ne l'ajoute PAS au tableau 'sources' et ne cite aucun numéro pour elle.
9. Slug en français kebab-case, descriptif, max 65 caractères
10. positions : génère ce bloc UNIQUEMENT si le sujet contient un véritable désaccord entre deux parties identifiables qui contestent ou défendent activement une même décision ou proposition — chacune avec une position EXPLICITEMENT attestée dans les sources (déclaration citée, vote enregistré, communiqué officiel). Critère opérationnel : deux camps avec des positions opposées ET défendables toutes les deux. INTERDIT si : acte institutionnel unilatéral sans opposition tracée (sanction disciplinaire, excommunication, condamnation judiciaire, décision administrative), décision technique, bilan statistique, découverte scientifique. Dans tous ces cas : verifie=false, acteurs=[]. Ne jamais inventer ou déduire une position. position = 0 (totalement favorable/consensuel) à 100 (totalement critique/opposé).
11. Le résumé ('resume') et le corps ('faits') ne doivent JAMAIS contenir de phrases identiques ou quasi identiques (mêmes mots, même structure) : le résumé est une synthèse reformulée, pas un copier-coller déguisé du corps.
12. Séparation stricte des registres : 'faits' = actualité immédiate uniquement (le fait du jour). 'contexte' = historique, évolution passée, comparaisons uniquement. Ne jamais mettre du contexte historique dans 'faits', ni redire les faits du jour dans 'contexte'.
13. FUSION DES SOURCES OBLIGATOIRE : si plusieurs sources rapportent exactement la même information (même fait, même chiffre, même résultat), les fusionner en UNE SEULE phrase avec les numéros groupés en fin de phrase — ex : "[fait] [2][5][7]". INTERDIT d'écrire une phrase par source pour le même fait. Une nouvelle source ne justifie une phrase propre que si elle apporte une information DIFFÉRENTE.
14. CONTRÔLE QUALITÉ AVANT SOUMISSION — avant de finaliser le JSON, vérifier explicitement :
    a) Chaque section remplit-elle UNIQUEMENT son rôle (faits=actualité, contexte=historique/mise en perspective, nuances=limites/incertitudes) ?
    b) Une même idée apparaît-elle plusieurs fois ? Si oui, supprimer toutes les occurrences sauf la première.
    c) Chaque paragraphe apporte-t-il au moins une information nouvelle non dite avant ?
    d) La section 'nuances' contient-elle uniquement des limites, incertitudes, désaccords — AUCUN fait déjà présenté ?
    e) Plusieurs sources disent-elles la même chose ? Si oui, les fusionner.
    f) Une phrase peut-elle être supprimée sans perte d'information ? Si oui, la supprimer.
    Si l'un de ces contrôles échoue, corriger AVANT de soumettre le JSON.
15. Chaque source citée dans le texte doit apporter un élément NOUVEAU (chiffre, angle, nuance). Ne JAMAIS répéter la même information avec des numéros différents à chaque phrase. RÈGLE DE SYNTHÈSE : quand plusieurs sources rapportent le même fait de façon identique ou quasi identique, les fusionner en UNE SEULE phrase de synthèse avec les numéros groupés en fin de phrase. N'utiliser des phrases séparées que si les sources apportent des informations DIFFÉRENTES.
    MAUVAIS (interdit) : « Le Vatican a excommunié six évêques [1]. Le Vatican a confirmé l'excommunication de ces six évêques [2]. Le Vatican a confirmé l'excommunication de six évêques [3]. »
    BON (attendu) : « Le Vatican a confirmé l'excommunication de six évêques de la Fraternité Saint-Pie X, actant le schisme de ce mouvement avec Rome [1][2][3]. »
16. ACTUALITÉ UNIQUEMENT : le sujet doit reposer sur un événement daté des dernières 48 heures (étude publiée, décision officielle, annonce, vote, incident). Un sujet intemporel ou encyclopédique sans événement déclencheur récent (ex: « la théorie de l'évolution », « le coucou, un oiseau stratège ») = réponds HORS_PERIMETRE.
17. CADRAGES EMPRUNTÉS INTERDITS : ne jamais reprendre mot pour mot un jugement de valeur ou un cadrage éditorial présent dans une source (ex : "crise sans précédent", "modèle à bout de souffle", "tournant historique") comme s'il s'agissait d'un fait neutre. Si un tel cadrage est pertinent, l'attribuer explicitement : « Selon [Source], il s'agit d'une crise sans précédent. » Ne jamais présenter l'angle éditorial d'une source comme l'angle factuel de l'article.
18. PAS D'EXTRAPOLATION NON SOURCÉE : n'écris jamais de projection ou de conséquence future ("cette mesure pourrait entraîner", "cela risque de", "on pourrait s'attendre à") sauf si une source listée formule explicitement cette projection. Si la conséquence n'est pas dans les extraits CONTENU, ne la mentionne pas.
19. RÉSULTATS INCERTAINS : si une étude est préliminaire, non encore répliquée, ou issue d'un seul chercheur, indique explicitement ce statut ("une étude préliminaire suggère que...", "selon une première analyse, non encore répliquée..."). Ne jamais présenter un résultat d'étude unique comme un fait établi. Le mot "prouve" ou "démontre définitivement" est interdit sauf citation directe attribuée.
20. SECTIONS DENSES, PAS VAGUES : chaque phrase de 'contexte' et 'nuances' doit apporter un fait précis et sourcé (chiffre, date, acteur, étude). Les formulations génériques sans contenu factuel sont interdites : "il est difficile de prévoir les conséquences", "la situation reste complexe", "les experts sont partagés" — supprimer ou remplacer par un fait réel tiré des sources.
21. nb_sources EXACT : le champ "nb_sources" doit correspondre exactement au nombre de sources DISTINCTES effectivement citées dans le texte final (chaque URL du tableau sources comptée une fois, même si citée plusieurs fois dans le corps). Pas de sources fantômes, pas de double-comptage.
22. LÉGAL : ne jamais qualifier quelqu'un de "coupable", "l'assassin", "le violeur" avant condamnation définitive — utiliser "mis en examen", "soupçonné de", "présumé". Ne jamais identifier un mineur par son nom dans une affaire pénale. Si le sujet implique une affaire judiciaire en cours, présenter les faits comme allégations de l'accusation, pas comme faits établis.
23. UNE IDÉE = UNE SEULE APPARITION dans tout l'article (résumé + faits + contexte + nuances confondus). Avant de rendre ta réponse, relis chaque phrase : si elle n'apporte AUCUNE information nouvelle par rapport à ce qui précède (même reformulée, même avec une attribution différente), supprime-la ou fusionne-la avec la première occurrence.
24. RÔLE STRICT DES SECTIONS : résumé = ENTRÉE DIRECTE dans le fait principal (chiffre, acteur, date dès la première phrase) — jamais une « présentation du sujet » ni une phrase d'ambiance ; 'faits' = uniquement les faits principaux du jour ; 'contexte' = uniquement les éléments qui permettent de COMPRENDRE les faits, sans les répéter ; 'nuances' = uniquement ce qu'un lecteur devrait savoir avant de tirer une conclusion (limites, désaccords, incertitudes, points non établis). Aucun contenu d'une section ne doit pouvoir être déplacé dans une autre.
25. TRIBUNE / PRISE DE POSITION : si la source principale est une tribune, chronique, interview ou essai d'opinion, TOUT l'article doit faire comprendre qu'il s'agit des analyses et propositions de son auteur, pas de faits établis. Utiliser systématiquement des verbes d'opinion ("estime", "plaide pour", "propose", "juge", "défend l'idée que") et le signaler dès le titre ou le résumé (ex : "Selon l'économiste X…"). Ne jamais transformer un argument d'auteur en constat factuel.

26. ARTICLES MÉDICAUX — NIVEAU DE PREUVE OBLIGATOIRE (revue éditoriale externe du 31/07, article NP137). Dès le résumé, puis à chaque résultat, indiquer le STADE de la recherche. Ne jamais écrire qu'un traitement "a amélioré la survie" quand la source décrit un essai précoce : écrire "dans un essai de phase 1b, les chercheurs ont observé…". Distinguer strictement quatre statuts, jamais interchangeables : résultat observé dans un essai / efficacité confirmée / traitement validé / traitement disponible en pratique clinique.
Nommer chaque indicateur avec précision — survie GLOBALE, survie SANS PROGRESSION, taux de réponse et opérabilité sont des choses différentes. Ne jamais écrire "amélioration de la survie" si la source ne parle que de survie sans progression. Pour chaque résultat chiffré, donner l'indicateur exact, sa valeur, le groupe concerné, la durée de suivi et le nombre de patients quand la source les fournit.
Toute comparaison chiffrée ("cinq mois de plus") exige un COMPARATEUR EXPLICITE : plus que quoi, chez qui, mesuré comment ? Si la source ne l'identifie pas, ne pas formuler la comparaison — donner la valeur brute en précisant qu'aucun groupe de comparaison n'est décrit.
Les limites doivent être SPÉCIFIQUES à l'étude (essai précoce, effectif réduit, absence de randomisation, tolérance à long terme inconnue, impossibilité de conclure à un standard de traitement). "Des recherches supplémentaires sont nécessaires" est interdit : c'est vrai de toute étude, donc ça n'informe pas.
Le contexte doit expliquer le MÉCANISME (ce qu'est la cible biologique, pourquoi elle est visée, comment le traitement est supposé agir), jamais répéter que la maladie est grave et difficile à traiter.

27. ACCUSATIONS VISANT UNE ENTREPRISE, UNE INSTITUTION OU UNE PERSONNE (même revue, article Perenco/RDC). Une accusation reste une accusation dans tout l'article : elle doit être attribuée à qui la porte ("Human Rights Watch estime que…"), jamais reformulée en constat ("les activités exposent les populations à des risques graves"). Distinguer fait observé / accusation / conclusion d'une ONG / résultat d'un audit / décision administrative ou judiciaire.
La RÉPONSE de l'acteur mis en cause doit être cherchée dans les sources et rapportée. Si elle est absente, l'écrire explicitement : "La réaction de [acteur] n'était pas disponible dans les sources consultées à la date de publication." Ne jamais faire figurer un acteur dans "positions" sans exposer sa position réelle — une entrée vide vaut mieux qu'une entrée trompeuse.
La source PRIMAIRE d'une accusation est le document original (le rapport lui-même), pas les médias qui le commentent. Si plusieurs sources ne font que relayer le même document, elles ne constituent PAS des confirmations indépendantes : les fusionner en une attribution groupée.
Vérifier le PAYS et l'entité concernés : une source portant sur un État homonyme, une autre juridiction ou une autre filiale est hors sujet et ne doit pas être citée (ex : le Congo-Brazzaville n'est pas la République démocratique du Congo).

28. AGENTIVITÉ — NE PAS PRÊTER D'INTENTION À UN OBJET TECHNIQUE. Les actes de COMMUNICATION et de DÉCISION appartiennent aux organisations et aux personnes, jamais aux systèmes qu'elles opèrent : une entreprise annonce, révèle, publie, reconnaît, décide, suspend. Un modèle, un algorithme ou un logiciel ne « révèle » rien et ne « décide » rien.
    MAUVAIS : « L'IA d'Anthropic a révélé que ses modèles avaient accédé à des systèmes. »
    BON : « Anthropic a révélé que ses modèles avaient accédé à des systèmes. »
    En revanche, une action TECHNIQUE effectivement décrite par les sources s'attribue bien au système : « le modèle a accédé aux systèmes », « l'algorithme a classé 12 000 dossiers » sont corrects. La distinction est entre ce qu'un système FAIT (technique, attribuable) et ce qu'une organisation DIT ou DÉCIDE (jamais attribuable au système).
    Cette confusion n'est pas une facilité de style : elle transforme un incident opérationnel en récit d'intention, et elle est d'autant plus grave dans un article qui porte justement sur le comportement d'un système.

29. PLANCHER CONDITIONNEL DE « DÉBATS ET NUANCES » — NE JAMAIS COMBLER. Cette section n'a de longueur imposée que si les sources fournies contiennent réellement des limites, des incertitudes, des désaccords ou des critiques ATTESTÉS. Si elles n'en contiennent aucun, renvoie une chaîne VIDE pour 'nuances' : c'est la bonne réponse, elle ne sera pas comptée comme un défaut, et la section ne sera pas affichée au lecteur.
    N'écris JAMAIS une limite que tu déduis toi-même, une précaution d'usage ('des recherches supplémentaires sont nécessaires' quand aucune source ne le dit), ni une injonction ('il est essentiel de renforcer la vigilance').
    Une section vide est honnête. Une section remplie de généralités affirme au lecteur qu'un débat existe alors que rien ne l'atteste : c'est une invention, au même titre qu'un chiffre inventé.
"""

# ──────────────────────────────────────────────────────────────────────────────
# PROMPT BRÈVE (02/08)
#
# Constat à l'origine du format : sur 251 vérifications loguées, DEUX articles
# étaient conformes du premier coup (0,8 %). Un taux d'échec de 99 % ne décrit
# pas des sorties ratées, il décrit une consigne impossible — on demandait 500
# mots structurés (chapeau + faits + contexte + nuances) à partir d'une matière
# qui, une fois la redondance inter-sources retirée, en contient souvent 150.
#
# Le modèle n'avait alors que deux issues : s'arrêter court (→ relance
# d'étoffement, premier poste de dépense du run) ou remplir. Quand il remplit,
# il produit exactement ce que les garde-fous détectent — tournures génériques,
# répétitions inter-sections, affirmations non démontrées. Et surtout :
# « Contexte » et « Débats et nuances » n'ayant, sur un sujet mince, AUCUNE
# matière factuelle à contenir, le modèle les remplit avec du cadrage. Le
# cadrage inventé, c'est la prise de position — la seule chose que ce journal
# ne peut pas se permettre.
#
# La brève supprime le problème à la racine plutôt que de le corriger en aval :
# pas de section à remplir, donc aucune surface où broder. Ce n'est PAS un
# assouplissement de la charte — les règles d'attribution, de neutralité, de
# sourcing et le protocole de vérification s'appliquent à l'identique. C'est le
# format qui s'aligne sur la matière, au lieu de l'inverse.
# ──────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT_BREVE = """Tu es l'IA rédactrice de Les Faits, journal numérique français indépendant.
Ligne éditoriale absolue : "Juste les faits. Aucun parti pris."

Tu rédiges une BRÈVE : le fait du jour, établi et sourcé, et RIEN d'autre.
Une brève n'est pas un article raté ni un résumé — c'est un format complet en
soi. Elle ne contient ni mise en perspective historique, ni débat, ni analyse.

RÉPONDS UNIQUEMENT EN JSON VALIDE, sans texte avant ou après, sans bloc ```json.

Format obligatoire :
{
  "titre": "Titre factuel informatif, 6 à 15 mots, sans exclamation ni question",
  "slug": "slug-kebab-case-descriptif-max-65-chars",
  "image_keyword": "3 mots EN ANGLAIS — paysage, bâtiment ou objet UNIQUEMENT, jamais de visages ni personnes (ex: 'wheat field france', 'hospital building', 'solar panels europe')",
  "resume": [
    "UNE SEULE phrase, 25 à 40 mots, JAMAIS deux. Elle porte L'ÉVÉNEMENT et rien d'autre : quoi, où, quand, le chiffre-clé. Entrée DIRECTE dans le fait — jamais de phrase d'ambiance, jamais de mise en contexte, jamais de justification ('dans le but de', 'afin de'). C'est l'attaque de la brève, pas son résumé : ce qui est écrit ici ne sera PAS réécrit dans 'faits'."
  ],
  "corps": {
    "faits": "110 à 200 mots, 4 à 8 phrases, un seul bloc. COMMENCE PAR CE QUE LE RÉSUMÉ N'A PAS DIT — jamais par une reformulation de la phrase du résumé, même avec d'autres mots. UNIQUEMENT le fait du jour et ses données propres : chiffres précis, montants, dates, acteurs nommés, décisions, résultats. ATTRIBUTION : une SEULE attribution groupée en tête de section, puis les faits s'enchaînent SANS réattribuer à chaque phrase (voir règle 6). JAMAIS d'URL dans le texte.",
    "contexte": "",
    "nuances": ""
  },
  "sources": [
    {"institution": "Nom exact institution", "titre": "Titre exact publication ou rapport", "date": "Date précise", "url": "URL FOURNIE DANS LES SOURCES DISPONIBLES UNIQUEMENT — sinon null"}
  ],
  "categorie": "science|economie|societe|tech|environnement|sante",
  "nb_sources": 3,
  "positions": {"verifie": false, "label_gauche": "", "label_droite": "", "acteurs": []}
}

RÈGLES ABSOLUES — toute violation = brève rejetée :
1. "contexte" et "nuances" DOIVENT être des chaînes VIDES (""). N'écris rien dedans, sous aucun prétexte. Si tu as de la matière historique ou des limites méthodologiques à exposer, c'est que le sujet méritait un article complet — ce n'est pas le format demandé ici, ignore cette matière.
2. "positions" est TOUJOURS {"verifie": false, ...} avec "acteurs": []. Une brève ne met jamais en scène un débat.
3. MINIMUM 3 sources distinctes et citables, toutes issues de SOURCES DISPONIBLES. Si tu ne peux pas atteindre 3 sources réelles : réponds uniquement HORS_PERIMETRE
4. Chaque donnée chiffrée doit PROVENIR d'une source listée et être COUVERTE par une attribution — celle de tête suffit (règle 6), il n'est pas demandé d'en remettre une à chaque phrase. Aucun chiffre qui ne figure pas dans les extraits fournis. JAMAIS d'URL dans le corps.
5. RÈGLE D'ATTRIBUTION : n'écris "Selon [Institution]" que si le fait attribué figure LITTÉRALEMENT dans l'extrait CONTENU fourni pour cette institution. Ne jamais citer une institution absente de SOURCES DISPONIBLES, même si tu la connais.
6. ATTRIBUTION GROUPÉE EN TÊTE — règle de forme la plus importante de ce format. Une brève cite 3 à 10 sources en 150 mots : si tu attribues phrase par phrase, le lecteur lit une liste de médias au lieu de lire les faits. Procède donc ainsi, dans cet ordre :
   a) UNE attribution groupée ouvre la section et couvre le fait principal : « Selon Libération, RTBF et 20 Minutes, un incendie s'est déclaré dans un entrepôt classé Seveso, conduisant au confinement de 30 000 habitants. »
   b) ENSUITE, les faits s'enchaînent SANS attribution : cette attribution de tête vaut pour tout ce qui suit. « Les communes concernées sont Gandrange, Amnéville et Rombas. L'entrepôt mesure 500 m². Le confinement a été levé en fin de matinée. »
   c) Ne nomme une source SÉPARÉMENT que si elle apporte un fait que les autres ne donnent PAS — et une seule fois, au moment de ce fait.
   INTERDIT ABSOLU : deux phrases consécutives commençant chacune par une attribution différente. Si tu en écris deux à la suite, c'est que le fait est le même : fusionne-les.
   MAUVAIS : « Selon RTBF, les communes concernées incluent Gandrange. D'après Radiofrance, l'incendie a été maîtrisé. Selon BFM TV, la préfecture a appelé les habitants à se confiner. D'après RTL, l'incendie touche un entrepôt de la société Safe. »
   BON : « Selon RTBF, Radiofrance et RTL, l'incendie a touché un entrepôt de la société Safe à Gandrange avant d'être maîtrisé. La préfecture avait appelé les habitants au confinement. »
7. Aucune opinion, aucun parti pris, aucun adjectif évaluatif sans source (alarmant, historique, sans précédent, majeur, inquiétant...).
8. PAS D'EXTRAPOLATION : aucune projection ni conséquence future ("pourrait entraîner", "risque de", "devrait permettre") sauf si une source listée la formule explicitement — auquel cas elle est attribuée à cette source.
9. CADRAGES EMPRUNTÉS INTERDITS : ne jamais reprendre le jugement de valeur d'une source ("crise sans précédent", "tournant historique") comme s'il s'agissait d'un fait neutre. L'attribuer ou le supprimer.
10. ACTUALITÉ UNIQUEMENT : le fait doit être daté des dernières 48 heures (décision, publication, annonce, vote, résultat, incident). Un sujet intemporel ou encyclopédique sans événement déclencheur récent = réponds HORS_PERIMETRE.
11. RÉSULTATS INCERTAINS : une étude préliminaire, non répliquée ou issue d'un seul groupe doit être présentée comme telle. Pour un résultat médical, nommer le stade (phase 1/2/3, observationnelle) et l'indicateur EXACT (survie globale ≠ survie sans progression ≠ taux de réponse). "prouve" et "démontre" sont interdits hors citation attribuée.
12. ACCUSATIONS : une accusation, une conclusion d'ONG ou un résultat d'audit reste attribué à qui le porte ("Human Rights Watch estime que…"), jamais reformulé en constat. Si la réponse de l'acteur mis en cause ne figure pas dans les sources, l'écrire : "La réaction de [acteur] n'était pas disponible dans les sources consultées."
13. LÉGAL : jamais "coupable", "l'assassin", "le violeur" avant condamnation définitive — "mis en examen", "soupçonné de", "présumé". Ne jamais identifier un mineur dans une affaire pénale. Une affaire en cours se présente comme allégations de l'accusation.
14. RÔLES SÉPARÉS DU RÉSUMÉ ET DE L'ATTAQUE — second défaut structurel de ce format. Sur 150 mots, un résumé qui « résume » et une attaque qui « énonce » disent forcément la même chose : il n'y a pas la place de la dire deux fois autrement. Les deux ne se répartissent donc pas la même matière, ils se la PARTAGENT :
    - le résumé porte L'ÉVÉNEMENT : quoi, où, quand, le chiffre-clé ;
    - 'faits' commence par LA SUITE : le détail, les acteurs, les conséquences, les chiffres secondaires. Sa première phrase doit être impossible à deviner à la lecture du résumé.
    TEST AVANT DE RENDRE : relis la phrase du résumé, puis la première phrase de 'faits'. Si la seconde redit la première — même reformulée, même avec un chiffre en plus —, SUPPRIME-la et commence 'faits' par la phrase suivante.
    MAUVAIS : résumé « La baignade en zone non autorisée est désormais passible d'une amende de 68 euros. » puis faits « La baignade en zone non autorisée est désormais passible d'une amende de 68 euros, contre 38 euros auparavant. »
    BON : résumé « La baignade en zone non autorisée est désormais passible d'une amende de 68 euros depuis le 2 août. » puis faits « Le montant était de 38 euros auparavant, et l'amende peut être dressée par procès-verbal électronique. »
15. UNE IDÉE = UNE SEULE APPARITION. Le résumé et 'faits' ne doivent jamais contenir de phrases identiques ou quasi identiques. Relis avant de rendre : si une phrase n'apporte aucune information nouvelle par rapport à ce qui précède, supprime-la.
16. Titre : 6-15 mots, informatif, factuel, sans vocabulaire putaclic et sans tournure en question.
17. nb_sources EXACT : le nombre de sources DISTINCTES effectivement citées dans le texte final.
18. AGENTIVITÉ — les actes de COMMUNICATION et de DÉCISION appartiennent aux organisations, jamais aux systèmes qu'elles opèrent. Une entreprise annonce, révèle, publie, reconnaît ; un modèle ou un algorithme ne « révèle » rien. Écrire « Anthropic a révélé que ses modèles avaient accédé à des systèmes », jamais « l'IA d'Anthropic a révélé ». Une action TECHNIQUE décrite par les sources reste attribuable au système (« le modèle a accédé aux systèmes ») : la distinction est entre ce qu'un système FAIT et ce qu'une organisation DIT.
19. Si les extraits disponibles ne fournissent pas assez de faits précis pour 110 mots sans inventer : réponds uniquement HORS_PERIMETRE. Mieux vaut aucune brève qu'une brève brodée."""

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


_CITATION_RE = re.compile(r"\[(\d{1,2})\]")


def strip_citations_invalides(art: dict) -> dict:
    """Retire les [n] hors plage plutôt que la phrase entière — contrairement
    à une attribution fantôme, un numéro de citation invalide ne rend pas la
    phrase fausse, juste sa preuve mal reliée. Repli déterministe, sans appel
    Groq, dans la même logique « réparer plutôt que rejeter » que
    `strip_attributions_invalides`."""
    nb_sources = len(art.get("sources") or [])

    def _clean(texte: str) -> str:
        return _CITATION_RE.sub(
            lambda m: m.group(0) if 1 <= int(m.group(1)) <= nb_sources else "", texte
        )

    art = dict(art)
    corps = dict(art.get("corps", {}) or {})
    for field in ("faits", "contexte", "nuances"):
        if field in corps and corps[field]:
            corps[field] = re.sub(r"  +", " ", _clean(corps[field])).strip()
    resume = art.get("resume")
    if isinstance(resume, list):
        art["resume"] = [re.sub(r"  +", " ", _clean(r)).strip() if isinstance(r, str) else r for r in resume]
    elif isinstance(resume, str):
        art["resume"] = re.sub(r"  +", " ", _clean(resume)).strip()
    art["corps"] = corps
    return art


def citations_hors_liste(art: dict) -> list[str]:
    """Format citation (05/08) : chaque [n] dans le corps doit renvoyer à un
    élément RÉEL du tableau 'sources' (1 = premier élément). Un [n] hors
    plage est une source fantôme au même titre qu'un « Selon X » inventé —
    même famille de défaut que `attributions_fantomes`, mêmes conséquences si
    on ne le rejoue pas après la passe de correction (voir le retrait du
    03/08 : une attribution fantôme réintroduite par la correction avait été
    publiée faute d'être revérifiée)."""
    corps = art.get("corps", {}) or {}
    texte = " ".join([
        " ".join(art.get("resume", []) if isinstance(art.get("resume"), list) else [art.get("resume", "") or ""]),
        corps.get("faits", ""), corps.get("contexte", ""), corps.get("nuances", ""),
    ])
    nb_sources = len(art.get("sources") or [])
    hors_plage = sorted({int(n) for n in _CITATION_RE.findall(texte)
                          if not (1 <= int(n) <= nb_sources)})
    if not hors_plage:
        return []
    return [f"[{n}] ne correspond à aucune source (le tableau 'sources' en compte {nb_sources})"
            for n in hors_plage]


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


# ──────────────────────────────────────────────────────────────────────────────
# Seuils éditoriaux par FORMAT (02/08)
#
# Un seul jeu de seuils existait, calibré sur l'article de 500 mots, et il
# s'appliquait à tout. Les voici explicités par format pour que la brève ne
# soit pas jugée à l'aune d'un format qu'elle n'est pas — et pour qu'on ne
# puisse pas affaiblir les seuils de l'ARTICLE en croyant toucher à la brève.
#
# Le plancher de sourcing (3 sources) est IDENTIQUE dans les deux formats, et
# la règle de qualité (≥1 primaire OU ≥2 secondaires) s'applique sans
# changement. Une brève est plus courte, jamais moins sourcée.
# ──────────────────────────────────────────────────────────────────────────────
SEUILS_FORMAT = {
    # cible : longueur demandée au prompt ; plancher : refus en dessous.
    # cible article 500 → 800 (05/08, Nahil) : avec le sourcing par question,
    # la matière disponible ne justifie plus un plafond bas — priorité à la
    # profondeur. Le PLANCHER reste 350 : ne pas rejeter un article par
    # ailleurs bon parce que la matière d'UN sujet précis était plus mince que
    # la moyenne. Ne monter le plancher qu'après avoir mesuré, sur plusieurs
    # runs, que la nouvelle cible est tenue sans relance systématique.
    # 800 → 600 (10/08) : la cible de 800 date du 05/08, dernier jour où le
    # site a publié quelque chose. Depuis, chaque run entame 7 à 9 sujets, n'en
    # mène AUCUN jusqu'à la grille vitrine et meurt sur le quota — la fenêtre
    # glissante ne se recharge jamais, le run suivant démarre à sec. 600 mots
    # reste au-dessus des 500 d'avant le 05/08, donc sans renoncer à la
    # profondeur, mais rend une tentative finançable. Le plancher ne bouge pas.
    # ⚠ Ce n'est PAS le correctif de fond : même finançables, les articles
    # échouent sur le sujet et la matière, pas sur la longueur.
    "article": {"cible": 600, "plancher": 350, "sources": 3},
    "breve":   {"cible": 130, "plancher": 100, "sources": 3},
}


def _seuils(article_type: str) -> dict:
    """Seuils applicables au type d'article (les dossiers suivent l'article)."""
    return SEUILS_FORMAT["breve"] if article_type == "breve" else SEUILS_FORMAT["article"]


# Un article long qui revient sous son plancher est-il converti en brève, ou
# relancé en étoffement comme avant ? Mettre à False rétablit exactement le
# comportement d'avant le 02/08 (relance puis rejet), pour comparer.
CONVERSION_BREVE_SI_COURT = True


def _mots_resume_faits(art: dict) -> int:
    """Mots du périmètre d'une BRÈVE : chapeau + 'faits'. Sert à savoir si un
    article long revenu trop court contient malgré tout une brève complète."""
    corps = art.get("corps") or {}
    mots = len(str(corps.get("faits", "") or "").split())
    resume = art.get("resume") or []
    if isinstance(resume, str):
        resume = [resume]
    return mots + sum(len(str(r or "").split()) for r in resume)


def _reduire_en_breve(art: dict) -> None:
    """Ramène un article au format brève, sur place et sans appel Groq.

    Les sections 'contexte' et 'nuances' sont VIDÉES, jamais résumées : sur un
    sujet dont la matière ne portait pas 500 mots, ce sont précisément elles
    que le modèle a remplies avec du cadrage faute de faits — c'est de là que
    viennent les prises de position. Le bloc 'positions' tombe pour la même
    raison : un débat qui n'existe pas dans les sources n'a pas à être mis en
    scène. Ce qui reste (chapeau + faits) est ce qui était réellement sourcé.
    """
    corps = art.setdefault("corps", {})
    corps["contexte"] = ""
    corps["nuances"] = ""
    art["positions"] = {"verifie": False, "label_gauche": "", "label_droite": "", "acteurs": []}

    # ── Chapeau ramené à UNE phrase (12/08) ──────────────────────────────────
    # Oubli de la version initiale : on vidait les sections mais on gardait le
    # chapeau en TROIS phrases du format article. Or « chapeau d'une phrase »
    # est la définition même de la brève, et la grille vitrine le contrôle.
    # Constat sur le run du 12/08 : les DEUX seuls sujets à avoir atteint la
    # grille ont été refusés sur « chapeau de brève : 3 phrase(s) au lieu
    # d'une ». Le correctif de la veille menait enfin les articles jusqu'à la
    # grille — pour les faire buter sur un défaut que la conversion introduisait
    # elle-même.
    # On garde la PREMIÈRE phrase : dans le format article c'est celle qui entre
    # directement dans le fait principal (règle 4 du SYSTEM_PROMPT), les deux
    # suivantes portant l'enjeu et la nuance, hors périmètre d'une brève.
    resume = art.get("resume") or []
    if isinstance(resume, str):
        resume = [resume]
    if len(resume) > 1:
        art["resume"] = [str(resume[0])]
    elif len(resume) == 1:
        # Une seule entrée mais plusieurs phrases dedans : même défaut, autre
        # forme. On coupe à la fin de la première.
        phrases = re.split(r"(?<=[.!?])\s+", str(resume[0]).strip())
        if len(phrases) > 1:
            art["resume"] = [phrases[0]]


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


def _supprimer_phrases_identiques(art: dict) -> int:
    """Retire les phrases répétées MOT POUR MOT dans l'article.

    Variante stricte de `_supprimer_phrases_dupliquees`, destinée au chemin
    COMMUN de publication — donc appliquée à tous les articles, corrigés ou
    validés du premier coup.

    Mesuré le 15/08 sur les 161 articles longs publiés : 43 contiennent une
    phrase entière dupliquée à l'identique. Exemple réellement en ligne, deux
    fois dans le même article :

        « La gestion sanitaire des vagues de chaleur est un enjeu important
          pour les autorités de santé. »

    La comparaison ignore la casse, les accents, la ponctuation et les espaces
    — « Selon l'Insee, X. » et « Selon l’Insee, X ! » sont la même phrase — mais
    RIEN d'autre. Deux phrases qui disent la même chose avec des mots
    différents sont conservées : les traiter relève de la réécriture, pas d'une
    réparation déterministe, et c'est précisément là que la variante permissive
    fait des dégâts quand on l'applique partout.

    La PREMIÈRE occurrence est toujours gardée, dans l'ordre de lecture
    (résumé → faits → contexte → nuances). Le résumé n'est jamais modifié : il
    sert de référence, une phrase du corps qui le recopie mot pour mot saute.
    """
    def _cle(p: str) -> str:
        s = unicodedata.normalize("NFD", p.lower())
        s = "".join(c for c in s if unicodedata.category(c) != "Mn")
        return re.sub(r"[^a-z0-9]+", "", s)

    corps = art.get("corps", {}) or {}
    resume = art.get("resume") or []
    if isinstance(resume, str):
        resume = [resume]
    vues = set()
    for r in resume:
        for p in re.split(r"(?<=[.!?])\s+", str(r or "")):
            if len(p.strip()) > 40:
                vues.add(_cle(p))

    n_supp = 0
    for section in ("faits", "contexte", "nuances"):
        texte = corps.get(section, "") or ""
        conservees = []
        for p in re.split(r"(?<=[.!?])\s+", texte):
            p = p.strip()
            if not p:
                continue
            # Les phrases courtes (transitions, énoncés d'une poignée de mots)
            # ne sont pas dédoublonnées : une répétition y est souvent
            # légitime, et le risque de couper du sens dépasse le gain.
            if len(p) <= 40:
                conservees.append(p)
                continue
            k = _cle(p)
            if k in vues:
                n_supp += 1
                continue
            vues.add(k)
            conservees.append(p)
        if n_supp:
            corps[section] = " ".join(conservees)
    return n_supp


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


# ── Règle 10 — fusion des sources obligatoire ────────────────────────────────
# attributions_trop_repetitives ne compte QUE les formes « Selon / D'après »
# (règle 4, qui encourage justement à VARIER les formes). Un article qui empile
# une phrase par source en variant le verbe passe donc entre les mailles des
# deux garde-fous : « …, indique Le Monde. … selon Le Figaro. RFI rapporte
# que… Numerama note que… BFM TV indique que… 01net précise que…
# Universfreebox souligne que… » — constat 28/07 sur l'article Huawei, où la
# section « Les faits » alignait 7 sources en 7 phrases quasi interchangeables
# pour un même fait, exactement ce que la règle 10 interdit. Le contrôle LLM
# l'avait vu mais classé « défaut de style non bloquant ».
_ATTRIB_VERBES = (
    r"indique|indiquent|rapporte|rapportent|note|notent|précise|précisent|"
    r"souligne|soulignent|estime|estiment|explique|expliquent|affirme|"
    r"affirment|ajoute|ajoutent|relève|relèvent|observe|observent|"
    r"constate|constatent|détaille|détaillent|confirme|confirment|"
    r"écrit|écrivent|rappelle|rappellent"
)
# Un nom de source : 1 à 3 mots commençant par une majuscule ou un chiffre
# (« Le Monde », « BFM TV », « 01net », « Universfreebox »).
#
# AUDIT 12/08 — deux angles morts mesurés sur les 161 articles publiés, qui
# faisaient tomber la détection d'empilement à 13 % là où le comptage manuel
# des phrases attribuées consécutives en trouve 40 % :
#
#  1. le nom précédé d'un ARTICLE n'était pas vu. « Selon le WHO », « D'après
#     le Pasteur » : après « Selon », le motif exigeait une majuscule, or il
#     rencontrait « le ». Aucune capture — donc une phrase pourtant attribuée
#     comptait comme non attribuée, ce qui CASSAIT la série de consécutives.
#  2. un nom contenant un mot en minuscule était TRONQUÉ à son premier mot :
#     « D'après Santé publique France » ne rendait que « Santé ». Le même
#     organisme apparaissait alors sous plusieurs noms selon la phrase, ce qui
#     gonflait artificiellement le compte de sources DISTINCTES ici, et le
#     faussait ailleurs.
#
# Cas d'école : articles/rougeole-antiviral-etude.html — 5 phrases attribuées
# d'affilée dans « Les faits », 0 détectée avant ce correctif.
#
# Le mot en minuscule n'est accepté qu'ENTRE deux mots capitalisés (« Santé
# publique France »), et jamais s'il s'agit d'une conjonction : sans cette
# exclusion, « Selon Le Monde et Le Figaro » se capturerait comme le nom
# unique « Le Monde et Le », fusionnant deux sources distinctes en une.
_MOT_MAJ = r"[A-ZÀ-ÖØ-Þ0-9][\wÀ-ÖØ-öø-ÿ’'\-]*"
_MOT_LIAISON = r"(?!(?:et|ou|avec|puis|selon|mais|dont|qui|que)\s)[a-zà-öø-ÿ][\wÀ-ÖØ-öø-ÿ’'\-]*"
# Queue en minuscules des noms d'institutions françaises : « Cour des comptes »,
# « Défenseur des droits », « Autorité de la concurrence ». Elle n'est acceptée
# qu'introduite par de/des/du/d', ce qui la borne — sans cette contrainte, le
# motif continuerait à avaler la phrase après le nom.
_QUEUE_INSTIT = r"(?:\s+(?:des?|du|d['’])\s*[a-zà-öø-ÿ][\wÀ-ÖØ-öø-ÿ’'\-]*){0,2}"
_NOM_SOURCE = rf"{_MOT_MAJ}(?:\s+(?:{_MOT_LIAISON}\s+)?{_MOT_MAJ}){{0,2}}{_QUEUE_INSTIT}"
# Article ou préposition facultatif devant le nom (« selon le WHO »,
# « d'après l'Inserm », « selon la Cour des comptes »).
_DET_SOURCE = r"(?:l['’]|le\s+|la\s+|les\s+|du\s+|des\s+|de\s+la\s+)?"
_ATTRIB_TOUTE_FORME_RE = re.compile(
    rf"(?:[Ss]elon|[Dd]['’]après)\s+{_DET_SOURCE}({_NOM_SOURCE})"
    rf"|({_NOM_SOURCE})\s+(?:{_ATTRIB_VERBES})\b"
    rf"|(?:{_ATTRIB_VERBES})\s+({_NOM_SOURCE})"
)
# Mots qui ouvrent une phrase et seraient pris pour un nom de source.
_FAUX_NOMS = {
    "le", "la", "les", "ce", "cette", "ces", "il", "elle", "ils", "elles",
    "cela", "en", "de", "des", "du", "un", "une", "on", "leur", "leurs",
    "son", "sa", "ses", "cet", "par", "pour", "dans", "mais", "or", "et",
    "l", "d", "qui", "que", "dont", "où", "ainsi", "enfin", "outre",
}
# Au-delà de ce nombre de phrases consécutives portant chacune une source
# DIFFÉRENTE, on considère l'empilement caractérisé.
MAX_SOURCES_EMPILEES = 4
# Nombre de sources DISTINCTES qu'il faut voir dans cette série pour parler
# d'empilement.
#
# MESURE 12/08 sur les 161 articles longs publiés, taux de déclenchement :
#
#   série >=4 phrases   sources distinctes >=4   26 / 161  (16 %)   ← avant
#   série >=4 phrases   sources distinctes >=3   30 / 161  (19 %)
#   série >=4 phrases   sources distinctes >=2   31 / 161  (19 %)   ← retenu
#   série >=3 phrases   sources distinctes >=2   49 / 161  (30 %)   ← écarté
#
# Exiger 4 sources distinctes ratait le défaut le plus courant : la MÊME source
# étalée sur plusieurs phrases consécutives au lieu d'être fusionnée en une
# (« Selon le CERN, … D'après le CERN, … » ; trois phrases d'affilée attribuées
# à Futura Sciences dans volcan-inconnu-sicile). C'est la règle 1 (une idée =
# une apparition) autant que la règle 10, et le lecteur y lit exactement le
# même défaut : un paragraphe qui avance par empilement d'attributions.
#
# Les 5 articles gagnés par ce passage de 4 à 2 ont été relus un par un : les
# 5 sont de vrais défauts, aucun faux positif. Le passage à une série de 3
# phrases a en revanche été écarté — 30 % du corpus pour un défaut à relance
# corrective, et la règle du projet est « précision > rappel » sur ces
# garde-fous, le quota Groq étant la ressource rare.
MIN_SOURCES_DISTINCTES_EMPILEES = 2


def nom_source_normalise(nom: str) -> str:
    """Clé de comparaison de deux noms de sources : accents, casse, espaces et
    ponctuation retirés.

    AUDIT 12/08 — un même organisme apparaît sous plusieurs orthographes selon
    l'endroit où le modèle l'a repris : « Santepubliquefrance » (repris du nom
    de domaine) et « Santé publique France » (repris du texte) cohabitent dans
    un même article — mesuré sur articles/rougeole-antiviral-etude.html, où il
    est ainsi compté DEUX fois dans les 6 sources affichées au lecteur. Toute
    comparaison de noms de sources doit passer par cette clé, jamais par une
    égalité de chaînes."""
    sans_accent = unicodedata.normalize("NFD", nom.lower())
    sans_accent = "".join(c for c in sans_accent if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "", sans_accent)


def _sources_attribuees(phrase: str) -> set:
    """Noms de sources auxquels une phrase attribue explicitement un fait,
    toutes formes confondues (« selon X », « X indique », « indique X »).

    Dédoublonne sur `nom_source_normalise` : deux orthographes du même
    organisme dans une même phrase ne comptent que pour UNE source, sans quoi
    le seuil d'empilement se franchit tout seul sur une source unique."""
    par_cle: dict[str, str] = {}
    for m in _ATTRIB_TOUTE_FORME_RE.finditer(phrase):
        nom = (m.group(1) or m.group(2) or m.group(3) or "").strip()
        if not nom:
            continue
        premier = nom.split()[0].lower().strip("’'")
        if premier in _FAUX_NOMS or len(nom) < 2:
            continue
        cle = nom_source_normalise(nom)
        if not cle:
            continue
        # À clé égale, on garde la forme la plus complète (« Santé publique
        # France » plutôt que « Santé »), c'est elle qui sera montrée au modèle
        # dans le message de relance.
        if len(nom) > len(par_cle.get(cle, "")):
            par_cle[cle] = nom
    return set(par_cle.values())


# ── Incohérence temporelle titre ↔ faits ─────────────────────────────────────
# Le pipeline agrège des sources publiées à des dates différentes sur un même
# événement. Quand le titre est repris d'une dépêche écrite AVANT l'événement
# et le corps de dépêches écrites APRÈS, l'article annonce au futur ce qu'il
# raconte ensuite au passé — constat 28/07 sur l'article CXMT, titré
# « s'apprête à réaliser la plus grosse levée de fonds » alors que « Les faits »
# décrivent l'introduction en Bourse déjà cotée (« a flambé de plus de 500 %
# lors de sa première journée de cotation »). Ni les garde-fous ni le
# fact-check LLM ne l'avaient vu.
_TITRE_PROSPECTIF_RE = re.compile(
    r"s['’]appr[êe]te à|se pr[ée]pare à|est sur le point de|en passe de|"
    r"va bient[ôo]t|pr[ée]voit de|envisage de|devrait bient[ôo]t",
    re.IGNORECASE,
)
# Marqueurs d'un événement DÉJÀ survenu (passé composé d'accomplissement).
_FAIT_ACCOMPLI_RE = re.compile(
    r"\ba (?:flamb[ée]|bondi|grimp[ée]|chut[ée]|d[ée]coll[ée]|lev[ée]|r[ée]alis[ée]|"
    r"conclu|sign[ée]|annonc[ée]|ouvert|cl[ôo]tur[ée]|d[ée]but[ée])\b|"
    r"s['’]est (?:envol[ée]|effondr[ée]|conclu[e]?)\b|"
    r"lors de sa premi[èe]re (?:journ[ée]e|s[ée]ance)\b|"
    r"\bont (?:lev[ée]|r[ée]alis[ée]|conclu|sign[ée])\b",
    re.IGNORECASE,
)


def incoherence_temporelle(art: dict) -> list[str]:
    """Titre annonçant un événement à venir alors que « Les faits » le
    décrivent comme déjà survenu. On n'examine que le DÉBUT des faits (le fait
    principal du jour) pour ne pas confondre avec un antécédent historique
    mentionné plus loin."""
    titre = str(art.get("titre", "") or "")
    m_titre = _TITRE_PROSPECTIF_RE.search(titre)
    if not m_titre:
        return []
    faits = str((art.get("corps", {}) or {}).get("faits", "") or "")
    m_fait = _FAIT_ACCOMPLI_RE.search(faits[:400])
    if not m_fait:
        return []
    return [
        f"le titre annonce un événement à venir (« {m_titre.group(0)} ») alors que "
        f"« Les faits » le décrivent comme déjà survenu (« …{m_fait.group(0)}… ») — "
        f"le titre vient probablement d'une source publiée avant l'événement"
    ]


# ── Neutralité — prise de position éditoriale ────────────────────────────────
# Le chapeau et « Débats et nuances » exposent des faits, des limites et des
# incertitudes (règle 2), jamais ce qu'un acteur DOIT faire. Constat 28/07 sur
# l'article Perenco/RDC : « Les autorités congolaises doivent prendre des
# mesures pour réguler les activités des entreprises pétrolières et protéger
# l'environnement, comme le souligne Viralmag » — une injonction politique,
# adossée qui plus est à une source tertiaire. Attribuer une injonction à une
# source ne la rend pas neutre : si une ONG réclame une mesure, il faut
# l'écrire comme SA demande (« HRW demande que… »), jamais comme une nécessité
# énoncée par le journal. Taux mesuré sur les 150 articles publiés : 5 %, et
# les 7 cas relevés sont tous de véritables prises de position.
_PRISE_DE_POSITION_RE = re.compile(
    r"\b(?:les autorit[ée]s(?:\s+\w+)?|le gouvernement|l['’][ÉEe]tat|les pouvoirs publics|"
    r"les entreprises|la communaut[ée] internationale|les d[ée]cideurs|les industriels|"
    r"les institutions)\s+(?:\w+\s+){0,3}?doi(?:t|vent)\b"
    r"|\bil est (?:urgent|imp[ée]ratif) (?:de|d['’]|que)\b"
    # AUDIT 12/08 — « Il est essentiel de renforcer la vigilance et les mesures
    # de prévention » constituait à elle seule la moitié de la section « Débats
    # et nuances » de articles/rougeole-antiviral-etude.html : une injonction du
    # journal, publiée, non détectée. Même famille que « urgent/impératif », qui
    # était déjà couverte.
    #
    # Mesuré sur les 161 articles longs publiés :
    #   essentiel|crucial|primordial|indispensable         12 / 161  ( 7 %)  ← retenu
    #   + nécessaire                                       20 / 161  (12 %)  ← écarté
    #   + important                                        80 / 161  (50 %)  ← écarté
    #
    # « important » est le piège déjà documenté le 28/07 sur cliches_ia :
    # « il est important de noter que » est un connecteur français courant, pas
    # une prise de position. « nécessaire » est écarté pour une raison propre au
    # sujet : « il est nécessaire de poursuivre les recherches » est la réserve
    # scientifique standard, exactement ce que « Débats et nuances » doit
    # contenir — le motif punirait le bon comportement.
    #
    # Les verbes de MONSTRATION (noter, rappeler, souligner, comprendre…) sont
    # exclus : « il est essentiel de comprendre la différence entre X et Y »
    # explique, il ne réclame rien.
    r"|\bil est (?:essentiel|crucial|primordial|indispensable)\s+(?:de|d['’])\s+"
    r"(?!noter|rappeler|souligner|pr[ée]ciser|comprendre|distinguer|garder|retenir)"
    r"|n[ée]cessit(?:e|ant) une (?:action|r[ée]ponse|intervention) (?:urgente|imm[ée]diate)"
    r"|\bdoi(?:t|vent) (?:prendre des mesures|agir|intervenir|r[ée]guler|l[ée]gif[ée]rer)\b",
    re.IGNORECASE,
)


def prise_de_position(art: dict) -> list[str]:
    """Injonctions (« les autorités doivent… ») dans le chapeau ou « Débats et
    nuances ». Défaut corrigeable : relance corrective combinée."""
    resume = art.get("resume")
    if isinstance(resume, list):
        resume = " ".join(str(x) for x in resume)
    textes = [str(resume or ""), str((art.get("corps", {}) or {}).get("nuances", "") or "")]
    trouvees = []
    for texte in textes:
        for m in _PRISE_DE_POSITION_RE.finditer(texte):
            extrait = texte[max(0, m.start() - 40):m.end() + 60].strip()
            if extrait not in trouvees:
                trouvees.append(extrait)
    return trouvees


def sources_non_fusionnees(art: dict) -> list[str]:
    """Règle 10 : détecte l'empilement « une phrase = une source » — plusieurs
    phrases consécutives attribuant chacune à une source DIFFÉRENTE, au lieu
    d'une phrase de synthèse à attribution groupée. Défaut corrigeable :
    déclenche la relance corrective combinée."""
    corps = art.get("corps", {}) or {}
    feedback = []
    for section in ("faits", "contexte", "nuances"):
        texte = str(corps.get(section, "") or "")
        phrases = [p for p in re.split(r"(?<=[.!?])\s+", texte) if p.strip()]
        serie_noms: dict[str, str] = {}
        serie_len = 0
        for ph in phrases:
            noms = _sources_attribuees(ph)
            if noms:
                serie_len += 1
                # Dédoublonnage par clé normalisée : « Santepubliquefrance » et
                # « Santé publique France » sont le même organisme, et une
                # source unique répétée n'est PAS un empilement.
                for n in noms:
                    serie_noms.setdefault(nom_source_normalise(n), n)
            else:
                serie_len = 0
                serie_noms = {}
            if (serie_len >= MAX_SOURCES_EMPILEES
                    and len(serie_noms) >= MIN_SOURCES_DISTINCTES_EMPILEES):
                feedback.append(
                    f"section « {section} » : {serie_len} phrases consécutives "
                    f"attribuées chacune à une source différente "
                    f"({', '.join(sorted(serie_noms.values())[:6])}) — fusionner celles "
                    f"qui rapportent le même fait en UNE phrase à attribution groupée"
                )
                break
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
# Cadrage NARRATIF : le titre raconte un match (vainqueur / perdant / duel)
# au lieu d'énoncer un fait. Constat 31/07 (Nahil) : « L'île d'Oléron remporte
# son bras de fer avec Airbnb » — publié, alors que le fait est « le Conseil
# constitutionnel valide l'encadrement des meublés touristiques ». Le garde-fou
# existant ne connaissait que les ADJECTIFS putaclic (bizarre, insolite, choc)
# et ne voyait pas la mise en récit, qui est pourtant une prise de position :
# désigner un gagnant, c'est prendre parti sur l'issue.
# Mesuré sur les 158 titres publiés : 1 déclenchement (0,6 %) — celui-là
# précisément. Précision maximale, aucun faux positif.
_TITRE_NARRATIF_RE = re.compile(
    r"\b(?:bras de fer|remporte|remportent|l'emporte|victoire|défaite|camouflet"
    r"|revers cinglant|coup de (?:tonnerre|massue|grâce)|tacle|s'attaque à"
    r"|riposte|contre-attaque|duel|affronte|humilié|fait plier|cède face à"
    r"|coup dur)\b",
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
    if _TITRE_NARRATIF_RE.search(titre):
        _m = _TITRE_NARRATIF_RE.search(titre).group()
        problemes.append(
            f"cadrage narratif « {_m} » — le titre raconte un affrontement avec "
            f"un vainqueur au lieu d'énoncer le fait (quelle décision, de qui, sur quoi)")
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
    r"n[ée]cessite une approche nuanc[ée]e|"
    # Remplissage méta constaté sur l'article CXMT (28/07) : des phrases qui
    # annoncent qu'il faudrait donner du contexte… sans en donner aucun.
    r"pour approfondir le contexte|"
    r"les (?:faits|informations) pr[ée]sent[ée]s dans (?:ce|cet)|"
    r"refl[èe]tent la situation actuelle|"
    r"sont bas[ée]s sur les informations disponibles|"
    r"les facteurs cl[ée]s qui influencent|"
    r"les tendances du march[ée] et les facteurs|"
    r"joue un r[ôo]le (?:cl[ée]|essentiel|important) dans|"
    r"soul[èe]ve des questions (?:importantes|cruciales)(?: et complexes)?)\b",
    re.IGNORECASE,
)


# NOTE — « il est important de noter/souligner que… » a été testé puis écarté
# comme motif (28/07) : même en ne le retenant que sans donnée chiffrée dans la
# phrase, il faisait passer le taux de déclenchement de cliches_ia de 4 % à
# 42 % du corpus. C'est un connecteur français courant, pas un défaut en soi ;
# le remplissage réel de l'article CXMT est déjà attrapé par les motifs
# spécifiques ci-dessus. Le quota Groq étant la ressource rare et ce garde-fou
# déclenchant une relance, on privilégie la précision au rappel.


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
# ── Domaines sensibles : SCINDÉS le 11/08 (décision Nahil) ───────────────────
# Ces deux listes ne formaient qu'un seul motif, combiné à `_SITUATION_ACTIVE_RE`
# pour un rejet déterministe. Conséquence : toute épidémie « en cours » était
# refusée avant même le fact-check — c'est ce qui a tué la brève Ebola du 11/08,
# sur « domaine sensible ('Ebola') + situation active ('en cours') ».
#
# Or le critère de la charte, affiné le 31/07, n'est PAS le thème mais la mise
# en cause de PERSONNES. Le fact-checker lui-même l'écrit : « NE classe pas
# sujet_sensible au seul motif qu'un sujet est politique, réglementaire,
# diplomatique ou économique ». Une épidémie sans personne mise en cause ni
# mineur impliqué n'entre dans aucun de ses trois critères — le blocage
# déterministe était donc PLUS strict que la règle qu'il était censé appliquer.
#
# Le volet SANITAIRE ne déclenche donc plus de rejet ici. Il reste couvert par
# `sujet_sante_sans_source_officielle`, qui exige une source institutionnelle
# (INSERM, OMS, Santé publique France, ANSES, ANSM, Pasteur, .gouv.fr) et
# envoie l'article en modération à défaut. C'est ce filet — une exigence de
# SOURCE plutôt qu'un veto sur le THÈME — qui rend l'ouverture tenable.
#
# Le volet PÉNAL/SÉCURITÉ garde le rejet déterministe : il vise des personnes
# nommées, et la mesure du 11/08 est sans appel — 10 rejets sur 10.
_DOMAINE_SANITAIRE_RE = re.compile(
    r"\b(?:ebola|marburg|lassa|h5n1|grippe aviaire|variole|rougeole|"
    r"m[ée]ningite|choléra|cholera|botulisme|listeria)\b",
    re.IGNORECASE,
)
_DOMAINE_SENSIBLE_RE = re.compile(
    r"\b(?:terrorisme|attentat|prise d.otage|enlèvement|"
    r"mis en examen|garde [àa] vue|perquisition|mandat d.arr[eê]t)\b",
    re.IGNORECASE,
)

# Mineur impliqué
# ── Mineur impliqué — motif RÉPARÉ le 11/08 ──────────────────────────────────
# La version précédente terminait par `(?:victim|bless|tu[ée]|agress)\b` : des
# RADICAUX TRONQUÉS suivis d'une frontière de mot. Après « bless » vient « é »,
# un caractère de mot — la frontière n'existe donc pas et le motif échouait.
# Échappaient de ce fait à la protection la plus sensible du pipeline :
#     « Un collégien blessé lors d'une agression »
#     « Une lycéenne victime de harcèlement »
#     « Un élève blessé dans la cour »
#     « Un adolescent de 16 ans tué dans une rixe »   (titre réel, 4 médias)
# Troisième occurrence du même piège dans la même journée (filtre commercial,
# procédure pénale, ici) : ne JAMAIS faire suivre un radical tronqué de `\b`,
# écrire `radical\w*`.
#
# La forme « adolescent de N ans tué/blessé » est ajoutée : c'est la tournure
# de presse la plus courante et elle n'était couverte par aucune branche.
_MINEUR_RE = re.compile(
    r"\bmineur\w*"
    r"|\benfant\w*\s+(?:victim|concern|impliqu|d[ée]c[ée]d|bless|tu[ée]|agress)\w*"
    r"|\badolescent\w*\s+(?:victim|concern|impliqu|d[ée]c[ée]d|bless|tu[ée]|agress|mis\w*\s+en)\w*"
    r"|\badolescent\w*\s+de\s+\d+\s+ans[^.]{0,20}(?:victim|bless|tu[ée]|agress|d[ée]c[ée]d)\w*"
    r"|(?:\bcoll[ée]gien|\blyc[ée]en|\b[ée]l[èe]ve)\w*[^.]{0,30}(?:victim|bless|tu[ée]|agress|d[ée]c[ée]d)\w*",
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

    # Volet pénal / sécurité uniquement : le volet sanitaire a été retiré de ce
    # veto le 11/08 (voir `_DOMAINE_SANITAIRE_RE`). Une épidémie en cours passe
    # désormais au fact-check, et reste soumise à l'exigence de source
    # officielle de `sujet_sante_sans_source_officielle`.
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


# ──────────────────────────────────────────────────────────────────────────────
# DOSSIERS SUSPENDUS — 03/08, à rouvrir sur mesure
#
# Mesure sur les runs des 02 et 03/08 : 13 dossiers menés à la vérification,
# **0 conforme du premier coup**, 1 seul publié — et c'est celui qui a dû être
# retiré (« L'IA Claude d'Anthropic s'échappe d'un test », chapeau ouvrant sur
# une attribution inventée).
#
# Deux raisons de suspendre plutôt que de borner :
#   1. Ils consomment les places de format long. Le garde-fou de budget ne
#      dégrade que les `actu` : le run du soir a produit 6 dossiers pour 1 actu,
#      `longs_restants` est descendu à −3. Résultat, QUATRE runs consécutifs
#      sans actu vérifiée — la comparaison brève/actu, seul test contrôlé du
#      format brève, n'a jamais pu avoir lieu. Les suspendre la débloque.
#   2. Le routage vers `dossier_science` se décide sur le TEASER RSS
#      (`_SCIENCE_HYPO_RE` sur `snippet[:500]`). Le titre seul de l'article
#      Claude donne « actu » : c'est un mot du teaser qui a envoyé une
#      actualité chaude vers le prompt « exploration scientifique
#      hypothétique ». Quatrième occurrence de la classe « décision prise sur
#      l'extrait RSS » (catégorie, _PR_MARQUE_RE, flux Atom).
#
# CONSÉQUENCE ASSUMÉE : les sujets scientifiques hypothétiques passent
# désormais par le prompt ACTU, donc SANS le garde-fou `_ASSERTIF_SCIENCE_RE`
# qui interdit les formulations assertives. À peser au moment de rouvrir. Les
# filtres de REJET (listicle, Liste A, Liste B) restent actifs à l'identique :
# seul le FORMAT dossier est suspendu, pas les protections.
#
# Pour rouvrir : repasser à False, et mesurer le taux de conforme_du_premier_coup
# des dossiers sur au moins deux runs avant d'en tirer une conclusion.
DOSSIERS_SUSPENDUS = True


def classifier_type_article(title: str, snippet: str) -> str:
    """Classifie un article AVANT génération (déterministe, zéro LLM).

    Retourne :
      "actu"             → pipeline ACTU standard
      "dossier_portrait" → portrait neutre d'une personne non-politique
      "dossier_science"  → exploration scientifique hypothétique
      "rejete"           → listicle, lifestyle, portrait polémique

    Tant que `DOSSIERS_SUSPENDUS` vaut True, les deux types de dossier sont
    rendus comme "actu" — les rejets, eux, restent des rejets.
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
        return "actu" if DOSSIERS_SUSPENDUS else "dossier_portrait"

    # Détection science hypothétique (titre + début snippet)
    if _SCIENCE_HYPO_RE.search(title) or _SCIENCE_HYPO_RE.search(snippet[:500]):
        # Liste B s'applique aussi ici
        if _LISTE_B_RE.search(texte_raw):
            return "rejete"
        return "actu" if DOSSIERS_SUSPENDUS else "dossier_science"

    return "actu"


def _select_prompt(article_type: str) -> str:
    """Retourne le SYSTEM_PROMPT adapté au type d'article."""
    if article_type == "breve":
        return SYSTEM_PROMPT_BREVE
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


def _reparer_json_tronque(texte: str):
    """Referme un JSON coupé en cours d'écriture, ou None si irrécupérable.

    Coupe ce qui suit la dernière valeur complète (chaîne, objet ou tableau
    refermé), retire une éventuelle clé ou virgule orpheline, puis referme les
    `{` / `[` restés ouverts. Utilisé pour récupérer un article dont la
    génération a été tronquée à max_tokens — la coupure tombe en général dans
    le tableau « sources », après un corps d'article complet.
    """
    # Une seule passe pour savoir, à chaque index, si l'on est dans une chaîne
    # et quelle est la pile de structures ouvertes. On ne peut pas se contenter
    # du dernier point « propre » rencontré : après une coupure au milieu du
    # tableau "sources", le dernier guillemet fermé appartient à une clé
    # orpheline (« {"url" ») et couper là produit un JSON invalide. On collecte
    # donc tous les points de coupe plausibles et on remonte depuis la fin
    # jusqu'au premier qui se referme proprement.
    hors_chaine: list[bool] = []
    piles: list[tuple] = []
    pile: list[str] = []
    dans_chaine = echappe = False
    candidats: list[int] = []
    for i, c in enumerate(texte):
        hors_chaine.append(not dans_chaine)
        piles.append(tuple(pile))
        if dans_chaine:
            if echappe:
                echappe = False
            elif c == "\\":
                echappe = True
            elif c == '"':
                dans_chaine = False
                candidats.append(i + 1)
            continue
        if c == '"':
            dans_chaine = True
        elif c in "{[":
            pile.append(c)
        elif c in "}]":
            if not pile:
                return None
            pile.pop()
            candidats.append(i + 1)
        elif c == ",":
            candidats.append(i)

    for coupe in reversed(candidats):
        tronc = texte[:coupe].rstrip()
        # Retirer virgule finale puis clé orpheline (« , "sources": » ou
        # « {"url" » sans valeur), éventuellement enchaînées.
        for _ in range(3):
            avant = tronc
            tronc = re.sub(r'[,\s]+$', '', tronc)
            tronc = re.sub(r',?\s*"[^"]*"\s*:\s*$', '', tronc)
            tronc = re.sub(r',?\s*\{\s*"[^"]*"$', '', tronc)
            tronc = re.sub(r',?\s*"[^"]*"$', '', tronc) if tronc.rstrip().endswith('"') and re.search(r'[\{\[]\s*"[^"]*"$', tronc) else tronc
            if tronc == avant:
                break
        if not tronc:
            continue
        # Recalculer la pile réellement ouverte à ce point
        p2: list[str] = []
        ds = ec = False
        for c in tronc:
            if ds:
                if ec:
                    ec = False
                elif c == "\\":
                    ec = True
                elif c == '"':
                    ds = False
                continue
            if c == '"':
                ds = True
            elif c in "{[":
                p2.append(c)
            elif c in "}]":
                if p2:
                    p2.pop()
        if ds:
            continue  # coupe tombée dans une chaîne : point suivant
        ferme = tronc + "".join("}" if o == "{" else "]" for o in reversed(p2))
        try:
            obj = json.loads(ferme)
        except Exception:
            continue
        if isinstance(obj, dict) and obj:
            return obj
    return None


class TronqueError(Exception):
    """La complétion a été coupée à max_tokens (finish_reason='length') —
    le JSON est forcément invalide en l'état.

    `contenu` porte le texte partiel : il contient presque toujours un article
    complet coupé dans la liste des sources, et `_extract_json` sait refermer
    un JSON tronqué. Sans ce champ, le texte était jeté avec l'exception et le
    sujet perdu (34 sujets et ~323 k tokens ainsi gâchés sur 27 runs, mesuré
    le 28/07)."""

    def __init__(self, message: str, contenu: str = ""):
        super().__init__(message)
        self.contenu = contenu


class QuotaJournalierEpuise(RuntimeError):
    """Toutes les clés Groq ont épuisé leur quota JOURNALIER (TPD).

    ATTENTION — le TPD Groq est une FENÊTRE GLISSANTE de 24 h, PAS une remise à
    zéro à minuit UTC comme on l'a longtemps cru. Preuve (run du 29/07 à 03h34) :
    les délais « try again in… » renvoyés par Groq étaient étalés entre 03h46 et
    05h40, alors qu'un reset quotidien les aurait tous groupés à 00h00. Chaque
    clé se libère progressivement, à mesure que les tokens consommés 24 h plus
    tôt sortent de la fenêtre.

    Deux conséquences : (1) les runs de l'après-midi amputent le budget du run
    du lendemain matin, 12 h plus tard ; (2) abandonner un run parce que « tout
    est épuisé » gâche des sujets alors qu'une clé peut redevenir utilisable en
    quelques minutes — d'où l'attente ciblée avant de lever cette exception."""


# Clés dont le quota JOURNALIER est épuisé — mortes jusqu'à la fin du run.
# Diagnostic du 16/07 : 4 runs dans la journée avaient consommé le budget
# quotidien de la plupart des clés ; le code traitait tous les 429 comme des
# limites par MINUTE et attendait 62s × 8 cycles × 12 sujets = 76 min d'attente
# pour rien (0 article). Le corps de l'erreur Groq distingue les deux :
# "tokens per minute (TPM)" vs "tokens per day (TPD)".
_CLES_MORTES_JOUR: set = set()
# Délai (secondes) annoncé par Groq avant qu'une clé morte revienne — le TPD
# étant une fenêtre glissante, on s'en sert pour attendre plutôt qu'abandonner.
_DELAIS_LIBERATION: dict = {}
# Au-delà de ce délai, attendre la libération d'une clé coûte plus de temps de
# run qu'elle ne rapporte d'articles — on préfère rendre la main.
ATTENTE_MAX_LIBERATION = 15 * 60
_ROTATION_APPELS = [0]  # compteur global — départ tournant dans la liste des clés



# ── CHOIX DU FOURNISSEUR ───────────────────────────────────────────────────
# Groq a retiré `llama-3.3-70b-versatile` le 17/08 sans préavis, et ses modèles
# restants plafonnent à 8 000 tokens par requête — sous la taille d'un prompt
# d'article. Le fournisseur est donc devenu une variable, pas une constante.
#
# Tous ces services parlent le protocole OpenAI. Le SDK `groq` ne peut pourtant
# pas les viser : il code en dur le chemin `/openai/v1/chat/completions`, si
# bien qu'une `base_url` pointée sur Mistral produirait
# `https://api.mistral.ai/v1/openai/v1/…`. On passe donc par le client `openai`
# dès qu'une base est fournie, et les appels restent identiques au caractère
# près — même `.chat.completions.create(...)`, mêmes paramètres.
#
#   LLM_BASE_URL vide                      → Groq, comportement inchangé
#   LLM_BASE_URL=https://api.mistral.ai/v1 → Mistral
#
# ⚠ Changer de fournisseur ne garantit RIEN sur la qualité rédactionnelle : le
# prompt système, ses règles numérotées et la sortie JSON ont été calibrés deux
# mois sur Llama 3.3. Mesurer avec `model_compare.yml` avant d'engager la
# production — c'est exactement l'erreur commise le 17/08 avec `groq/compound`,
# validé sur une fenêtre puis démenti par le premier run réel.
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "").strip()


def _client(api_key: str):
    """Client de complétion, Groq par défaut, tout service compatible sinon."""
    if LLM_BASE_URL:
        from openai import OpenAI
        return OpenAI(api_key=api_key, base_url=LLM_BASE_URL)
    return Groq(api_key=api_key)


def _est_quota_journalier(err: str) -> bool:
    e = err.lower()
    return "per day" in e or "tpd" in e or "tokens per day" in e or "requests per day" in e or "rpd" in e


def _delai_liberation(err: str) -> int | None:
    """Secondes avant que la clé redevienne utilisable, d'après le « try again
    in 1h24m14.4s » de Groq. Le TPD étant une fenêtre glissante, ce délai est
    exploitable : inutile d'abandonner un run quand une clé revient dans
    quelques minutes. Retourne None si le message ne le précise pas."""
    m = re.search(r"try again in (?:(\d+)h)?(?:(\d+)m)?([\d.]+)s", err)
    if not m:
        return None
    return int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + int(float(m.group(3)))


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


def _reponse_degeneree(raw: str) -> bool:
    """La réponse de Groq n'est pas du texte : octets de contrôle répétés.

    Signature observée le 30/07 : des séquences comme « \\x13\\x13… » ou
    « \\ufffd/\\ufffd/… » sur des milliers de caractères, sans une seule
    accolade. Deux critères, cumulatifs pour éviter les faux positifs sur un
    texte contenant un caractère exotique isolé : (a) aucune accolade ouvrante,
    (b) plus de 10 % de caractères de contrôle ou de remplacement.
    """
    if not raw or "{" in raw or len(raw) < 200:
        return False
    # Critère 1 — PAUVRETÉ DE L'ALPHABET. C'est le critère fiable : une
    # réponse dégénérée boucle sur 2 ou 3 caractères (« _�_�_� », « (�(�(� »),
    # là où du français en compte plusieurs dizaines.
    # La première version ne testait que les caractères de contrôle et U+FFFD
    # et n'a rien attrapé au run du 31/07 (4 sujets perdus) : le « � » visible
    # dans les logs GitHub est un artefact d'affichage, la chaîne reçue par
    # Python contient des caractères imprimables d'un autre bloc Unicode.
    # Ne jamais se fier à la classe des caractères, seulement à leur variété.
    if len(set(raw)) <= 15:
        return True
    # Critère 2 — densité de caractères de contrôle (filet de sécurité).
    suspects = sum(1 for c in raw if c == "�" or (ord(c) < 32 and c not in "\n\r\t"))
    return suspects > len(raw) * 0.10


# Combien de caractères pèse un token dans NOS prompts — mesuré le 18/08, pas
# supposé. Le pipeline utilisait 3,3 depuis l'origine, sans que ce chiffre ait
# jamais été confronté à l'API. Mesure sur les messages réellement construits
# par `generate()`, en lisant `usage.prompt_tokens` renvoyé par Groq :
#
#   configuration        caractères   estimé à 3,3   RÉEL   car./token
#   brève 6 sources         18 502        5 606      4 872     3,80
#   article 4 sources       30 938        9 375      7 874     3,93
#   article 10 sources      34 132       10 343      8 768     3,89
#
# Valeur retenue : 3,8 — la mesure la plus BASSE, pas la moyenne. Surestimer un
# peu le prompt ne coûte que de la marge ; le sous-estimer ferait réserver plus
# de sortie qu'il n'en reste et produirait un 413 certain, c'est-à-dire un sujet
# perdu. L'asymétrie des conséquences commande l'arrondi.
#
# ⚠ Ce ratio dépend de la LANGUE et du contenu : du JSON et des URLs se
# tokenisent moins bien que de la prose. Il a été mesuré sur nos prompts réels
# et sur `openai/gpt-oss-120b` ; le revérifier avec `groq_ratio.yml` en cas de
# changement de modèle ou de refonte du prompt.
_CHARS_PAR_TOKEN = 3.8


# Plafond TPM propre à chaque modèle (constat du 21/07 : gpt-oss-120b n'a que
# 8K TPM contre 12K pour Llama 3.3 — utiliser le plafond de Llama sur gpt-oss
# produisait un 413 à 0 token traité, à chaque appel, quel que soit le quota
# journalier restant). Hissé au niveau module le 15/08 : la réservation
# d'écriture de `generate()` doit lire la MÊME table que `_groq_call`, sinon
# elle réserve contre une fenêtre qui n'est pas celle de l'appel réel.
_TPM_PAR_MODELE_GEN = {
    "llama-3.3-70b-versatile": 12_000,
    "openai/gpt-oss-120b": 8_000,
    "openai/gpt-oss-20b": 8_000,
    "qwen/qwen3.6-27b": 8_000,
    "llama-3.1-8b-instant": 6_000,
    # Relevé sur la grille « Free Plan Limits » de Groq le 17/08, après le
    # retrait de llama-3.3-70b : ce sont les DEUX seules entrées de l'offre
    # gratuite dont la fenêtre laisse tourner le format long. 70 000 TPM, et
    # surtout TPD affiché « — » : aucun plafond journalier.
    #
    #   modèle                    TPM     prompt nominal   reste pour ÉCRIRE
    #   llama-3.3-70b (retiré)  12 000       10 021             1 479
    #   gpt-oss-120b / qwen      8 000       10 021               200
    #   groq/compound           70 000       13 355             3 500
    #
    # À 70 000, la matière n'est plus coupée du tout (prompt complet, 10 × 950
    # caractères) et la réservation bute sur NOTRE plafond, plus sur la fenêtre.
    #
    # ⚠ AVANT DE LES CHOISIR — ce ne sont pas des modèles nus mais le système
    # agentique de Groq, qui dispose d'outils côté serveur (recherche web).
    # Un modèle qui peut aller chercher un fait ailleurs peut introduire dans
    # l'article une information ABSENTE des extraits fournis : c'est la règle 5
    # de la charte, celle sur laquelle tout le reste repose. À vérifier sur un
    # run contrôlé avant d'en faire le modèle par défaut, jamais à supposer.
    # ⚠ 8 000, PAS les 70 000 de la grille tarifaire. Mesuré le 17/08 : Groq
    # facture `groq/compound` sur le compteur d'`openai/gpt-oss-120b`, comme
    # le dit son propre refus — « Rate limit reached for model
    # openai/gpt-oss-120b … on tokens per minute (TPM): Limit 8000 ». Compound
    # n'est pas un modèle mais un système bâti dessus : il hérite du plafond
    # et n'y échappe pas. Déclarer 70 000 a fait envoyer des requêtes de
    # 17 000 tokens, refusées 40 fois sur 40 en « 413 Request Entity Too
    # Large ». C'est la cause des zéro article du run de 18h58.
    # Mistral, palier gratuit : 500 000 tokens/minute et 1 milliard/mois — soit
    # 62 fois la fenêtre de Groq. Nos requêtes d'article (~11 900 tokens) y
    # pèsent 2 % : la réservation d'écriture ne coupe alors plus rien, ce qui
    # est le but. ⚠ Un modèle ABSENT de cette table retombe sur 12 000 par
    # défaut, ce qui ferait couper la matière pour rien — ajouter toute
    # nouvelle référence ici.
    "mistral-large-latest": 500_000,
    "mistral-medium-latest": 500_000,
    "mistral-small-latest": 500_000,
    "open-mistral-nemo": 500_000,
    "groq/compound": 8_000,
    "groq/compound-mini": 8_000,
}

# Tout ce qu'un prompt de génération porte en dehors du prompt système, du
# contenu principal et des extraits de sources : en-tête d'attribution, bloc
# d'ancrage sur un événement unique, rappels d'attribution, consigne finale.
# Mesuré le 15/08 sur les messages réellement construits (~5 000 caractères,
# arrondi au-dessus pour ne jamais SOUS-estimer le prompt : sous-estimer
# reviendrait à réserver moins d'écriture qu'annoncé).
_SURCOUT_PROMPT_CHARS = 3800


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
    client = _client(api_key)
    # La limite TPM compte prompt + max_tokens RÉSERVÉS, pas les tokens
    # réellement produits : prompt lourd + réservation généreuse = 413
    # « Request too large » systématique, quel que soit le quota restant.
    # Table hissée au niveau module (voir `_TPM_PAR_MODELE_GEN`) pour que la
    # réservation d'écriture de `generate()` raisonne sur la même fenêtre.
    tpm = _TPM_PAR_MODELE_GEN.get(GROQ_MODEL, 12_000)
    marge_securite = 500
    prompt_estime = int(sum(len(m.get("content", "")) for m in messages) / _CHARS_PAR_TOKEN)
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
    choice = response.choices[0]
    u = response.usage
    if u:
        # `finish_reason` est le seul moyen de distinguer deux pannes qui se
        # ressemblent : une complétion COUPÉE au plafond (« length ») et un
        # modèle qui s'arrête de lui-même en ayant omis des champs (« stop »).
        # Le 18/08, Mistral a rendu 1 540 tokens mais un JSON sans `corps` ni
        # `sources` : sans ce champ, impossible de dire si le texte a été
        # tronqué ou jamais écrit — deux diagnostics opposés.
        print(f"     [TOKENS] prompt={u.prompt_tokens} completion={u.completion_tokens} "
              f"total={u.total_tokens} fin={getattr(choice, 'finish_reason', '?')} "
              f"réservé={max_tokens}", flush=True)
    if getattr(choice, "finish_reason", None) == "length":
        raise TronqueError(f"complétion coupée à {max_tokens} tokens",
                           contenu=(choice.message.content or ""))
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
             fusion_feedback: list[str] | None = None,
             position_feedback: list[str] | None = None,
             temporel_feedback: list[str] | None = None,
             citations_feedback: list[str] | None = None,
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
    is_retry = bool(retry_feedback or repetition_feedback or intra_feedback or selon_feedback or expand_feedback or titre_feedback or cliches_feedback or intro_feedback or nuances_feedback or prospectif_feedback or fusion_feedback or temporel_feedback or position_feedback or citations_feedback)
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
    # BRÈVE (02/08) : c'est ICI que se fait l'essentiel de l'économie de quota.
    # Une brève de 130 mots n'a pas besoin de 10 extraits de 950 caractères —
    # elle a besoin du fait du jour, que les premières lignes de chaque source
    # portent déjà. On divise la matière injectée par ~2,5, ce qui divise le
    # prompt d'autant : ~2 500 tokens au lieu de ~7 000. Ne pas confondre avec
    # un affaiblissement du sourcing : le NOMBRE de sources trouvées, contrôlées
    # et citées est inchangé, seule la profondeur d'extrait injectée baisse.
    if article_type == "breve" and not is_retry:
        snippet_len = 380
    # CORRECTIF 11/08 : l'étoffement d'un ARTICLE (pas une brève) doit recevoir
    # PLUS de matière, jamais moins — c'est tout son but. Mesuré la nuit du
    # 10-11/08 : 4 sujets sur 6 rejetés « toujours insuffisant après relance »
    # à 270-306 mots, alors que la MATIÈRE disponible sur ces mêmes sujets
    # faisait 6000-9500 caractères. Le snippet_len=450 hérité de l'économie
    # brève du 18/07 affamait la relance précisément quand elle avait besoin
    # de plus de contenu pour allonger le texte, pas moins.
    if is_expand and article_type != "breve":
        snippet_len = 550
    # CORRECTIF 2 (même run, 11/08) : 5000/700 avec les 10 sources déclenchait
    # des troncatures à max_tokens (un article tombé à 44 mots/0 source après
    # récupération de JSON partiel — pire que le problème d'origine). Le calcul
    # avait sous-estimé le coût réel en tokens. On revient à un budget proche
    # du total qui ne tronquait PAS (content 2500 + 10×450 ≈ 7000 car.), en
    # reportant le gain sur la PROFONDEUR par source plutôt que sur leur
    # NOMBRE : 7 sources à 550 car. + 3200 de contenu principal ≈ 7050 car.,
    # quasi identique en volume total, donc même risque de troncature que
    # l'ancienne version qui ne tronquait pas.
    if is_expand and article_type != "breve" and len(real_sources) > 7:
        real_sources = real_sources[:7]
    # Construction du bloc sources isolée dans une fonction : elle doit pouvoir
    # être REJOUÉE avec un `slen` plus court si la fenêtre d'écriture n'y suffit
    # pas (voir la réservation d'écriture, plus bas).
    def _bloc_sources(slen: int) -> tuple[str, list[str]]:
        bloc = ""
        noms: list[str] = []
        if real_sources:
            bloc = "\n\nSOURCES DISPONIBLES — LISTE FERMÉE :\n"
            bloc += (
                "RÈGLE ABSOLUE : pour tout « Selon X » ou « D'après X » dans le texte, "
                "X doit être EXACTEMENT l'une des valeurs NOM_SOURCE listées ci-dessous. "
                "Interdit : utiliser 'SOURCE 1', 'SOURCE 2', un nom de domaine, "
                "un média mentionné À L'INTÉRIEUR d'un extrait, ou tout nom connu par ailleurs.\n\n"
            )
            for i, s in enumerate(real_sources, 1):
                snippet  = s.get("snippet") or ""
                nom      = _media_name_from_url(s["url"], s.get("title", "")) or s.get("title", "Source")
                noms.append(nom)
                bloc += f"--- SOURCE {i} ---\n"
                bloc += f"NOM_SOURCE : {nom}\n"
                bloc += f"URL        : {s['url']}\n"
                if snippet:
                    bloc += f"CONTENU    :\n{snippet[:slen]}\n"
                else:
                    bloc += "CONTENU    : (pas de contenu disponible)\n"
                bloc += f"--- FIN SOURCE {i} ({nom}) ---\n\n"
        return bloc, noms

    sources_block, source_noms = _bloc_sources(snippet_len)
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
    if article_type == "breve" and not is_retry:
        content_len = 2500
    # Même correctif que snippet_len ci-dessus, même mesure du 11/08.
    if is_expand and article_type != "breve":
        content_len = 3200

    # ── RÉSERVATION D'ÉCRITURE ────────────────────────────────────────────
    # Mesuré hors ligne le 15/08, sans consommer un jeton, en interceptant les
    # messages réellement construits ici :
    #
    #   sources × extrait   contenu    prompt (tokens)   reste pour ÉCRIRE
    #   10 × 950 car.        7 000         12 893              200
    #   10 × 950 car.        3 000         11 681              200
    #    8 × 950 car.        7 000         12 226              200
    #   10 × 400 car.        7 000         11 227              273
    #    8 × 400 car.        2 000          9 377            2 123
    #
    # `_groq_call` calcule `max_tokens = tpm - marge - prompt`, avec un
    # PLANCHER à 200. Dans la configuration nominale (10 sources × 950 + 7 000
    # caractères de contenu), ce plancher est atteint : la réservation tombe à
    # 200 tokens, quand un article JSON de 800 mots en demande ~2 000. La
    # complétion est alors coupée par construction — c'est la troncature qui
    # était le 2e motif de perte du tunnel (34 sujets, ~323 k tokens, mesuré
    # le 28/07) et on la traitait comme un caprice du modèle.
    #
    # ⚠ L'effet est INVERSÉ par rapport à l'intuition : plus le sourcing est
    # riche, moins il reste de place pour écrire. Un sujet bien documenté était
    # donc PLUS exposé qu'un sujet pauvre. Ça rend aussi le verdict instable
    # d'une tentative à l'autre — même sujet, autre longueur d'extraits, autre
    # issue — ce qui ressemblait à un jugement éditorial erratique.
    #
    # Le correctif ne touche AUCUN garde-fou et ne retire AUCUNE source : le
    # nombre de sources trouvées, contrôlées et citées est inchangé, seule la
    # PROFONDEUR d'extrait injectée baisse — même arbitrage que celui validé
    # le 18/07 pour l'étoffement. On ne descend jamais sous `_SLEN_PLANCHER` :
    # en dessous, l'extrait ne porte plus de fait attribuable et le remède
    # serait pire que le mal (rejet en HORS_PERIMETRE).
    #
    # Écrit en fonction du TPM du modèle, jamais en dur : le jour où le compte
    # passe en offre payante, la fenêtre s'élargit et cette coupe cesse d'elle-
    # même de s'appliquer. Rien à re-régler.
    _reserve = 1200 if article_type == "breve" else 2000
    _SLEN_PLANCHER = 300
    _tpm = _TPM_PAR_MODELE_GEN.get(GROQ_MODEL, 12_000)
    _sys_len = len(_select_prompt(article_type))

    def _prompt_tokens(clen: int, slen: int) -> int:
        bloc, _ = _bloc_sources(slen)
        # Tout ce qui n'est ni le contenu ni les extraits (en-têtes, règles
        # d'ancrage, rappels) est constant : on le mesure en différentiel.
        return int((_sys_len + len(bloc) + min(len(content), clen)
                    + _SURCOUT_PROMPT_CHARS) / _CHARS_PAR_TOKEN)

    _place = _tpm - 500 - _prompt_tokens(content_len, snippet_len)
    if _place < _reserve:
        _avant = (content_len, snippet_len)
        # Ordre de coupe : les EXTRAITS d'abord, le CONTENU SOURCE PRINCIPAL
        # en dernier. Ce contenu est l'événement unique sur lequel la règle
        # d'ancrage fait reposer tout l'article ; l'amputer en premier
        # reviendrait à retirer le fait du jour pour garder la mise en
        # perspective. Plancher à 2 500 caractères pour la même raison.
        while _place < _reserve and (snippet_len > _SLEN_PLANCHER or content_len > 2500):
            if snippet_len > _SLEN_PLANCHER:
                snippet_len = max(_SLEN_PLANCHER, snippet_len - 100)
            else:
                content_len = max(2500, content_len - 500)
            _place = _tpm - 500 - _prompt_tokens(content_len, snippet_len)
        sources_block, source_noms = _bloc_sources(snippet_len)
        noms_autorises = " | ".join(f'"{n}"' for n in source_noms) if source_noms else "(aucune)"
        print(f"     [FENÊTRE] matière réduite pour garder de quoi écrire : "
              f"contenu {_avant[0]}→{content_len} car., extraits {_avant[1]}→{snippet_len} car. "
              f"· réservation d'écriture {_place} tokens (cible {_reserve})", flush=True)
        if _place < _reserve:
            print(f"     [FENÊTRE] ⚠ plancher atteint : {_place} tokens seulement pour écrire "
                  f"— le prompt système ({int(_sys_len / _CHARS_PAR_TOKEN)} tokens) occupe l'essentiel "
                  f"de la fenêtre de {_tpm}", flush=True)

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
        "6. Si les extraits disponibles ne fournissent pas assez de faits précis pour 350 mots sans inventer, "
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

    if fusion_feedback:
        user_msg += (
            "\n\nCORRECTION OBLIGATOIRE (règle 10 — fusion des sources) — ta précédente "
            "réponse empilait une phrase par source au lieu de les fusionner : "
            + " ; ".join(fusion_feedback[:3]) + ". "
            "Quand PLUSIEURS sources rapportent la MÊME information, écris UNE seule "
            "phrase avec attribution groupée — « Selon Le Monde, RFI et BFM TV, [fait] » "
            "— au lieu d'une phrase par source qui répète le fait en le reformulant. "
            "Une source ne mérite une phrase à elle seule que si elle apporte une "
            "information DIFFÉRENTE (un chiffre, une date, un acteur que les autres "
            "ne donnent pas). Supprime les phrases qui n'ajoutent rien."
        )

    if position_feedback:
        user_msg += (
            "\n\nCORRECTION OBLIGATOIRE (neutralité) — ta précédente réponse prenait "
            "position au lieu de rapporter : " + " ; ".join(position_feedback[:3]) + ". "
            "Le journal ne dit JAMAIS ce qu'un gouvernement, une institution ou une "
            "entreprise devrait faire. Si une source réclame une mesure, écris-le comme "
            "SA demande — « Human Rights Watch demande au gouvernement de publier les "
            "résultats de l'audit » — jamais comme une nécessité énoncée par l'article "
            "(« les autorités doivent… », « il est urgent de… »). Dans « Débats et "
            "nuances », remplace ces injonctions par de vraies limites : ce qui reste "
            "inconnu, contesté ou non établi."
        )

    if citations_feedback:
        user_msg += (
            "\n\nCORRECTION OBLIGATOIRE (citations) — " + " ; ".join(citations_feedback[:6]) + ". "
            "Chaque [n] dans le texte doit renvoyer au n-ième élément du tableau "
            "'sources' que tu renvoies, rien d'autre. Corrige le numéro s'il visait "
            "la bonne source à une position différente, ou retire la phrase si le "
            "fait ne provient d'aucune source listée."
        )

    if temporel_feedback:
        user_msg += (
            "\n\nCORRECTION OBLIGATOIRE (cohérence temporelle) — "
            + " ; ".join(temporel_feedback[:2]) + ". "
            "Les sources fournies n'ont pas toutes été publiées au même moment : "
            "certaines annoncent l'événement AVANT qu'il ait lieu, d'autres le "
            "racontent APRÈS. Réécris le titre ET le chapeau au temps de ce qui "
            "s'est RÉELLEMENT produit selon les sources les plus récentes — "
            "si l'événement a eu lieu, ne l'annonce jamais comme à venir. "
            "Vérifie aussi que les chiffres du chapeau et ceux de « Les faits » "
            "décrivent la même réalité dans la même unité."
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
    # Une brève complète fait ~450 tokens de JSON. Réserver 3 500 comme pour un
    # article gaspille de la fenêtre TPM (12 000/min/clé, prompt + réservation)
    # sans rien apporter : 1 500 laisse trois fois la marge nécessaire tout en
    # permettant à une clé de traiter plusieurs brèves dans la même minute.
    if article_type == "breve":
        reservation_reponse = 1500
    for cycle in range(MAX_RETRY_CYCLES):
        keys_to_try = [(k, l) for k, l in _all_keys if k and k not in _CLES_MORTES_JOUR]
        if not keys_to_try:
            # Le TPD est une fenêtre glissante : une clé « morte » redevient
            # utilisable dès que ses tokens d'il y a 24 h sortent de la fenêtre,
            # et Groq annonce le délai exact. Le run du 29/07 a abandonné alors
            # qu'une clé revenait dans 6 min 32 s. On attend donc la première
            # libération quand elle est proche, au lieu de perdre les sujets
            # restants.
            def _reveiller_cles_expirees() -> list:
                for _k, _echeance in list(_DELAIS_LIBERATION.items()):
                    if _echeance <= time.time():
                        _CLES_MORTES_JOUR.discard(_k)
                        _DELAIS_LIBERATION.pop(_k, None)
                return [(k, l) for k, l in _all_keys if k and k not in _CLES_MORTES_JOUR]

            # 1) Réveiller d'abord les clés dont le délai est DÉJÀ écoulé. Sans
            # cette étape, une clé annonçant « try again in 1m3s » restait morte
            # jusqu'à la fin du run : le réveil n'avait lieu qu'à l'intérieur du
            # bloc d'attente ci-dessous, or une échéance passée donne un délai
            # négatif qui ne satisfait pas la condition — on abandonnait donc
            # avec des clés redevenues utilisables (constat sur le run du soir
            # du 29/07, qui s'est arrêté alors qu'une clé était libre depuis
            # plusieurs minutes).
            keys_to_try = _reveiller_cles_expirees()

            # 2) Sinon, attendre la prochaine libération si elle est proche.
            if not keys_to_try:
                _proch = min(_DELAIS_LIBERATION.values()) if _DELAIS_LIBERATION else None
                _attente = int(_proch - time.time()) if _proch else None
                if _attente is not None and 0 < _attente <= ATTENTE_MAX_LIBERATION:
                    print(f"     [GROQ] Toutes les clés au quota, mais l'une se libère "
                          f"dans {_attente // 60} min {_attente % 60} s (le TPD est une "
                          f"fenêtre glissante) — attente plutôt qu'abandon…")
                    time.sleep(_attente + 5)
                    keys_to_try = _reveiller_cles_expirees()
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
                # Réponse DÉGÉNÉRÉE : Groq renvoie parfois des octets répétés
                # en boucle au lieu de texte (« \x13\x13… », « �/�/… »).
                # Ce n'est pas du JSON malformé, c'est le modèle qui déraille ;
                # aucune réparation n'est possible. Constat 30/07 après-midi :
                # 9 sujets sur 14 perdus comme ça, comptés en « Pas de JSON ».
                # On réessaie sur la CLÉ SUIVANTE plutôt que de perdre le sujet
                # — la dégénérescence est aléatoire, pas liée au contenu.
                if _reponse_degeneree(raw):
                    print(f"     [GROQ] {label} : réponse dégénérée "
                          f"({len(raw)} car. non textuels) — nouvelle clé…")
                    continue
                break
            except TronqueError as _tronque:
                # Complétion coupée à max_tokens : réessayer UNE fois (même
                # clé, même cycle) avec une consigne de concision explicite
                # ET une réservation doublée — sans ça le sujet est perdu à
                # coup sûr (JSON invalide).
                if troncature_deja_reduite:
                    # Dernier recours avant de perdre le sujet : récupérer le
                    # JSON partiel. Mesuré sur 27 runs (28/07) : la relance à
                    # 6000 ne sauve que 11 % des cas (4 sur 38), et les 34
                    # échecs restants ont brûlé ~323 k tokens — 3 quotas
                    # journaliers de clé — pour zéro article. La distribution
                    # des complétions est bimodale (médiane 1417 tokens, ou
                    # emballement jusqu'à la coupure) : quand le modèle part en
                    # boucle, lui donner plus de place ne le fait pas
                    # converger. L'article récupéré repasse par TOUS les
                    # garde-fous (longueur, sources, qualité, fact-check) —
                    # s'il est réellement incomplet, il est rejeté là.
                    if _tronque.contenu.strip():
                        print("     [GROQ] Toujours tronquée — récupération du "
                              "JSON partiel plutôt que perte du sujet…")
                        raw = _tronque.contenu
                        break
                    raise ValueError("Réponse tronquée à max_tokens malgré la consigne de concision")
                troncature_deja_reduite = True
                reservation_reponse = 6000
                print(f"     [GROQ] Complétion tronquée à max_tokens — nouvelle tentative avec consigne de concision et réservation élargie")
                messages = messages + [{
                    "role": "user",
                    "content": ("Ta réponse précédente a été coupée car trop longue. "
                                "Recommence en visant 600 mots de corps MAXIMUM au total : "
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
                        prompt_est = int(sum(len(m.get("content", "")) for m in messages) / _CHARS_PAR_TOKEN)
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
                        _d = _delai_liberation(err)
                        if _d is not None:
                            _DELAIS_LIBERATION[key] = time.time() + _d
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
        # BUG CORRIGÉ (07/08) : ce second cas remontait un RuntimeError NU,
        # pas `QuotaJournalierEpuise` — `run()` ne le rattrape que par son
        # `except Exception` générique, donc il ne casse PAS la boucle sur
        # `selection` : le sujet suivant est tenté, retombe sur les MÊMES
        # clés dans le même état, et répète l'attente. Constat du run du
        # 06/08 après-midi : 3h31 à enchaîner ce cycle sujet après sujet,
        # 0 article produit, jusqu'à l'annulation externe du job.
        # Si les 8 cycles courts (62 s) de ce bloc n'ont rien débloqué juste
        # après avoir déjà attendu jusqu'à ATTENTE_MAX_LIBERATION pour la
        # meilleure clé disponible, aucun sujet suivant n'ira mieux tant que
        # la fenêtre glissante n'a pas bougé — traiter ce cas comme le
        # premier, pour que le run s'arrête au lieu de tourner à vide.
        raise QuotaJournalierEpuise(
            f"Quota Groq épuisé sur toutes les clés après {MAX_RETRY_CYCLES} cycles d'attente")

    # BUG CORRIGÉ (30/07) : le marqueur n'était cherché que dans les 60
    # PREMIERS caractères. Le prompt demande de répondre HORS_PERIMETRE quand
    # les sources ne suffisent pas (règle 10), mais le modèle le fait souvent
    # précédé d'une phrase d'explication — le marqueur tombe alors au-delà de
    # 60 caractères, la réponse ne contient aucune accolade, et on la comptait
    # en « Pas de JSON dans la réponse », c'est-à-dire en panne technique.
    # C'était en réalité un verdict éditorial correct, mal classé. On cherche
    # donc le marqueur dans toute réponse dépourvue de JSON.
    if "HORS_PERIMETRE" in raw[:60] or ("{" not in raw and "HORS_PERIMETRE" in raw):
        raise ValueError(raw.strip()[:120])

    # Extraire le JSON robustement (le modèle peut ajouter du texte avant/après)
    def _extract_json(text):
        m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if m:
            candidate = re.sub(r',\s*([\}\]])', r'\1', m.group(1))
            return json.loads(candidate)
        start = text.find('{')
        if start == -1:
            # Journaliser la réponse brute : sans ça, « Pas de JSON » est un
            # diagnostic aveugle. C'était 3 pertes sur 14 au run du 30/07
            # (~66 k tokens) sans qu'on puisse savoir ce que Groq avait rendu.
            print(f"     [GROQ-BRUT] réponse sans JSON ({len(text)} car.) : "
                  f"{text.strip()[:300]!r}")
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
            # Repli sur la dernière accolade valide : ne marche que si la
            # coupure laisse une structure équilibrée. Or une troncature tombe
            # presque toujours AU MILIEU du tableau "sources" — il reste alors
            # un `[` ouvert et aucun préfixe n'est parsable. On referme donc
            # explicitement les structures restées ouvertes.
            repare = _reparer_json_tronque(candidate)
            if repare is not None:
                return repare
            raise ValueError("JSON non réparable")

    art = _extract_json(raw)

    # Un JSON récupéré après troncature peut se terminer en pleine phrase.
    # On coupe la dernière phrase incomplète de chaque section plutôt que de
    # publier un texte suspendu ; si la section devient trop courte, les
    # garde-fous de longueur s'en chargent juste après.
    if isinstance(art, dict) and isinstance(art.get("corps"), dict):
        for _sec, _txt in list(art["corps"].items()):
            if not isinstance(_txt, str) or not _txt.strip():
                continue
            _t = _txt.rstrip()
            if _t[-1:] in ".!?»\"'" :
                continue
            _coupe = max(_t.rfind("."), _t.rfind("!"), _t.rfind("?"))
            if _coupe > 40:  # garder la section si au moins une phrase entière
                art["corps"][_sec] = _t[:_coupe + 1]
                print(f"     [RÉCUP] section « {_sec} » : dernière phrase "
                      f"incomplète coupée")

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
        # Instituts publics de recherche ajoutés le 28/07 (sources primaires)
        "ird.fr", "inrae.fr", "cea.fr", "ademe.fr",
    ],
    "press_agency": ["reuters.com", "afp.com", "apnews.com"],
    "media": [
        "lemonde.fr", "lefigaro.fr", "leparisien.fr", "liberation.fr",
        "bbc.com", "theguardian.com", "nytimes.com", "francetvinfo.fr",
        "franceinfo.fr", "rtl.fr", "bfmtv.com", "20minutes.fr",
        "lepoint.fr", "lexpress.fr", "nouvelobs.com", "mediapart.fr",
        # Médias ajoutés le 28/07 — sans cette entrée ils seraient comptés
        # "tertiaires" et ne compteraient pas pour la règle ≥2 secondaires.
        "radiofrance.fr", "franceculture.fr", "courrierinternational.com",
        "slate.fr", "novethic.fr", "lesechos.fr", "ouest-france.fr",
        "la-croix.com", "france24.com", "rfi.fr", "theconversation.com",
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


def _est_du_francais(kw: str) -> bool:
    """Le mot-clé visuel est-il resté en français ?

    Pexels est un moteur anglophone : une requête française ne rend rien de
    pertinent et l'article récupère une image générique hors-sujet. Deux
    critères, l'un OU l'autre suffit :
      (a) un mot vide français (de, des, du, le, la, pour, avec…) — ces mots
          n'existent pas dans une requête anglaise de 3-4 mots ;
      (b) une lettre accentuée — l'anglais n'en a pas, et `clean` a déjà
          retiré la ponctuation sans toucher aux accents.
    Volontairement étroit : « france », « paris », « europe » sont des mots
    anglais valides en requête stock et ne doivent PAS déclencher.
    """
    if not kw:
        return False
    if re.search(r"[éèêëàâçùûôîï]", kw):
        return True
    _VIDES_FR = {"de", "des", "du", "le", "la", "les", "un", "une", "et",
                 "en", "au", "aux", "pour", "sur", "avec", "dans", "par"}
    return any(m in _VIDES_FR for m in kw.split())


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
        # BUG CORRIGÉ (05/08) : ce commentaire décrivait un contrôle du
        # français qui N'EXISTAIT PAS — le code ne testait que `if clean`
        # (réponse non vide). Le LLM répond parfois en français malgré la
        # consigne, et ces mots-clés partaient tels quels vers Pexels, moteur
        # anglophone : « festival de films américain », « puces électroniques »,
        # « étoile supergéante rouge » ne rendent rien de pertinent, l'article
        # récupère alors une image générique hors-sujet. Mesuré sur les 149
        # articles publiés : 6 cas (4 %).
        # Même classe de défaut que la journalisation du 02/08 — un commentaire
        # décrivait une intention, pas le code. Le contrôle existe maintenant.
        if clean and _est_du_francais(clean):
            print(f"  [IMG] mots-clés rendus en français (« {clean[:40]} ») — "
                  f"repli sur le fallback catégorie")
            clean = ""
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
    '<a href="/breves.html">Brèves</a>\n'
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
# Brèves — l'éclair, pictogramme du « flash info ». Ajouté le 07/08 : l'entrée
# Brèves réutilisait `_ICO_LIST`, identique à « Tous les articles », donc deux
# icônes rigoureusement identiques côte à côte dans le header (constat Nahil
# sur capture). Un éclair anguleux ne se confond ni avec les lignes+points de
# la liste, ni avec l'étoile arrondie de `_ICO_SPARK`, à 18 px comme au-delà.
_ICO_FLASH = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M13 2 L4 13.5 h6.5 L11 22 l9 -11.5 h-6.5 z"/></svg>'

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
    '      <a class="nav-expand-item" href="/breves.html" aria-label="Brèves">'
    + _ICO_FLASH +
    '<span class="nav-expand-label">Brèves</span></a>\n'
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
      <a href="/breves.html">Brèves</a>
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

    def _source_li(s, n):
        # Le correcteur LLM peut renvoyer un objet source incomplet — un champ
        # manquant ne doit jamais faire planter le rendu (le crash arrivait
        # après génération + vérification + image : tout le quota perdu).
        institution = s.get("institution") or _media_name_from_url(s.get("url", ""), "") or "Source"
        titre = s.get("titre") or ""
        titre_html = f' · <em>{_esc(titre)}</em>' if titre else ""
        # id="source-N" : cible des liens de citation [n] insérés dans le
        # corps par `_rendre_citations` — N = position dans le tableau
        # 'sources' TEL QUE RENVOYÉ PAR LE MODÈLE, pas dans verified_sources
        # (une source sans URL valide est filtrée du rendu mais garde sa
        # position dans le texte : ne jamais renuméroter ici).
        return f'<li id="source-{n}"><cite>{_esc(institution)}</cite>{titre_html}{_source_date(s)}{_source_link(s)}</li>'

    # Position RÉELLE de chaque source dans le tableau d'origine (art["sources"]),
    # pas son rang parmi les seules sources vérifiées : le modèle cite [n] par
    # rapport au tableau complet, filtrer avant de numéroter décalerait tous
    # les liens de citation après la première source sans URL.
    toutes_sources = art.get("sources") or []
    _pos_reelle = {id(s): i + 1 for i, s in enumerate(toutes_sources)}

    if verified_sources:
        sources_li = "\n".join(_source_li(s, _pos_reelle.get(id(s), i + 1))
                               for i, s in enumerate(verified_sources))
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

    # Citations numérotées (05/08) : convertit les [n] laissés dans le texte
    # en liens cliquables vers <li id="source-n"> dans le bloc SOURCES rendu
    # plus haut. Appliqué APRÈS _esc() : [ ] et les chiffres ne sont jamais
    # échappés par html.escape, la recherche est donc sûre sur du HTML déjà
    # nettoyé. Un [n] hors plage (ne devrait plus arriver, voir
    # `citations_hors_liste` / `strip_citations_invalides`) reste affiché en
    # texte brut plutôt que de créer un lien mort.
    def _rendre_citations(texte_echappe: str) -> str:
        nb = len(toutes_sources)
        return _CITATION_RE.sub(
            lambda m: (f'<sup><a href="#source-{m.group(1)}" class="cite" '
                       f'aria-label="Source {m.group(1)}">{m.group(1)}</a></sup>'
                       if 1 <= int(m.group(1)) <= nb else m.group(0)),
            texte_echappe,
        )

    faits    = _rendre_citations(_esc(art["corps"]["faits"])).replace("\n", "</p><p>")
    contexte = _rendre_citations(_esc(art["corps"].get("contexte") or "")).replace("\n", "</p><p>")
    nuances  = _rendre_citations(_esc(art["corps"].get("nuances") or "")).replace("\n", "</p><p>")

    # Une BRÈVE n'a ni « Contexte » ni « Débats et nuances » — on ne rend pas
    # des titres de section vides. Le format est affiché explicitement au
    # lecteur : il doit savoir qu'il lit le fait du jour et rien d'autre, pas
    # se demander si l'article a été tronqué.
    est_breve = (art.get("format") == "breve") or not (contexte.strip() or nuances.strip())
    # Intertitres ÉDITORIAUX (05/08) : le modèle renvoie titre_faits/
    # titre_contexte/titre_nuances, propres au sujet, à la place des noms de
    # fonction fixes ("Les faits", "Contexte", "Débats et nuances") — repli
    # sur ces derniers si le champ est absent (articles antérieurs au 05/08,
    # brèves qui n'en produisent pas, ou omission du modèle : ne jamais
    # planter le rendu pour un champ éditorial manquant).
    titre_faits    = _esc(art.get("titre_faits") or "").strip()    or "Les faits"
    titre_contexte = _esc(art.get("titre_contexte") or "").strip() or "Contexte"
    titre_nuances  = _esc(art.get("titre_nuances") or "").strip()  or "Débats et nuances"
    sections_html = f'<h2 class="art__h2">{titre_faits}</h2><p>{faits}</p>'
    if contexte.strip():
        sections_html += f'\n  <h2 class="art__h2">{titre_contexte}</h2><p>{contexte}</p>'
    if nuances.strip():
        sections_html += f'\n  <h2 class="art__h2">{titre_nuances}</h2><p>{nuances}</p>'
    format_badge = (
        '<span class="meta__sep" aria-hidden="true">·</span>'
        '<span class="art__format" title="Format court : le fait du jour, établi et sourcé, '
        'sans mise en perspective ni analyse">Brève</span>'
    ) if est_breve else ""

    # Articles liés — 1 par catégorie différente de l'article courant
    # ── Bloc de bas d'article : EN BREF, à défaut À LIRE AUSSI (03/08) ──────
    # Les brèves remplacent les articles liés : elles se lisent en trente
    # secondes, ce qui en fait un bien meilleur « et sinon, quoi d'autre » en
    # fin de lecture qu'un second article de 500 mots. C'est aussi ce qui leur
    # donne une distribution — sans ça une brève n'existe que sur l'accueil,
    # le temps d'être poussée hors de la une par la suivante.
    # REPLI OBLIGATOIRE : tant que le corpus compte moins de 3 brèves (4 au
    # 03/08), on retombe sur les articles liés. Un bloc à moitié vide serait
    # pire que l'ancien.
    related_html = ""
    try:
        _breves = _breves_recentes(exclure_slug=slug, n=3)
        if len(_breves) >= 3:
            _cards = "\n".join(
                f'<a class="art__related-card art__related-card--breve" href="articles/{b["slug"]}.html">'
                f'<span class="cat cat--{b["categorie"]}">{_cat_up(b["categorie"])}</span>'
                f'<div class="title-sm">{_esc(b["titre"])}</div>'
                f'<div style="font-size:10px;color:var(--muted);margin-top:6px">'
                f'{_esc(b.get("date", "").split(",")[0])} · {b.get("nb_sources", 0)} sources</div>'
                f'</a>'
                for b in _breves
            )
            related_html = (
                '<div class="art__related">'
                '<div class="art__related-title">EN BREF'
                '<a href="breves.html" class="art__related-more">Toutes les brèves →</a>'
                '</div>'
                f'<div class="art__related-grid">{_cards}</div></div>'
            )
        all_arts = [] if related_html else load_index()
        other = [a for a in all_arts if a.get("categorie") != cat and a["slug"] != slug]
        seen_cats: set = set()
        related: list = []
        for a in other:
            if a["categorie"] not in seen_cats:
                related.append(a)
                seen_cats.add(a["categorie"])
            if len(related) == 3:
                break
        if all_arts and len(related) < 3:
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
  <a class="share-btn" href="https://twitter.com/intent/tweet?url={art_url}&amp;text={urllib.parse.quote(art['titre'])}" target="_blank" rel="noopener noreferrer external">𝕏 Twitter</a>
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
        # « ✓ Sources concordantes » RETIRÉ le 31/07 (revue éditoriale
        # externe) : la mention s'affichait dès qu'il y avait au moins une
        # source, sans qu'aucune concordance n'ait jamais été mesurée. Or
        # neuf médias qui relaient le même rapport d'ONG ne sont pas neuf
        # confirmations indépendantes — c'était une affirmation invérifiée
        # affichée comme un contrôle passé. Ne pas la réintroduire sans un
        # test réel d'indépendance des sources.
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
    {format_badge}
  </div>
  <div class="art__ai-badge" role="note">🤖 Rédigé par IA — <a href="methode.html" style="color:inherit;text-decoration:underline">notre méthode</a>{verify_html}</div>
  {AUDIO_PLAYER_HTML}
  <div class="art__rule"></div>
  {hero_img}
  <p class="art__resume">{_esc(resume_txt)}</p>
  {sections_html}
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

def _remplacer_bloc_related(path: Path, new_block: str) -> bool:
    """Remplace le bloc `<div class="art__related">…</div>` d'un article.

    Le découpage se fait en comptant les div imbriqués, pas par regex : le bloc
    en contient plusieurs et une expression non gourmande couperait au premier
    `</div>`. Retourne True si le fichier a réellement changé.
    """
    html = path.read_text(encoding="utf-8")
    start = html.find('<div class="art__related">')
    if start < 0:
        return False
    depth, i, end = 0, start, -1
    while i < len(html):
        if html[i:i + 4] == '<div':
            depth += 1; i += 4
        elif html[i:i + 6] == '</div>':
            depth -= 1
            if depth == 0:
                end = i + 6; break
            i += 6
        else:
            i += 1
    if end < 0:
        return False
    new_html = html[:start] + new_block + html[end:]
    if new_html == html:
        return False
    path.write_text(new_html, encoding="utf-8")
    return True


def rebuild_articles_related(articles: list):
    """Met à jour le bloc de bas d'article : EN BREF, à défaut À LIRE AUSSI.

    ATTENTION — cette fonction duplique la construction du bloc faite dans
    `build_article_html`. Les deux DOIVENT rester alignées : la première sert
    à la génération d'un article neuf, celle-ci repatche les ~160 articles
    déjà publiés à chaque `--rebuild`. Un changement appliqué à une seule des
    deux donne un site où les nouveaux articles et les anciens n'ont pas le
    même pied de page (constat 03/08 : le bloc EN BREF n'apparaissait que sur
    les articles générés après la modification).
    """
    updated = 0
    breves_globales = [a for a in articles if a.get("format") == "breve"]
    for art in articles:
        slug = art["slug"]
        cat  = art.get("categorie", "")
        path = ROOT / "articles" / f"{slug}.html"
        if not path.exists():
            continue

        # Priorité aux brèves — même repli que dans build_article_html : sous
        # 3 brèves disponibles hors article courant, on garde les articles liés.
        _breves = [b for b in breves_globales if b["slug"] != slug][:3]
        if len(_breves) >= 3:
            _cards = "".join(
                f'<a class="art__related-card art__related-card--breve" href="articles/{b["slug"]}.html">'
                f'<span class="cat cat--{b["categorie"]}">{_cat_up(b["categorie"])}</span>'
                f'<div class="title-sm">{_esc(b["titre"])}</div>'
                f'<div style="font-size:10px;color:var(--muted);margin-top:6px">'
                f'{_esc(b.get("date", "").split(",")[0])} · {b.get("nb_sources", 0)} sources</div>'
                f'</a>'
                for b in _breves
            )
            new_block = (
                '<div class="art__related">'
                '<div class="art__related-title">EN BREF'
                '<a href="breves.html" class="art__related-more">Toutes les brèves →</a>'
                '</div>'
                f'<div class="art__related-grid">{_cards}</div></div>'
            )
            if _remplacer_bloc_related(path, new_block):
                updated += 1
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
        if _remplacer_bloc_related(path, new_block):
            updated += 1
    print(f"  ✓ {updated} articles mis à jour (bloc de bas d'article)")


def _fmt_badge(a: dict) -> str:
    """Marqueur « Brève » sur les cartes (accueil et pages catégories).

    Les entrées d'articles.json antérieures au 02/08 n'ont pas de champ
    `format` : leur absence vaut "article", ce qu'elles étaient toutes. Aucune
    carte déjà publiée n'est donc modifiée par l'arrivée du format.
    """
    if a.get("format") != "breve":
        return ""
    return ('<span class="meta__sep">·</span>'
            '<span class="meta__format">Brève</span>')


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
          <span class="meta__sep">·</span><span>{a['date']}</span>{_fmt_badge(a)}</div>
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
              <span class="meta__sep">·</span><span>{a['date']}</span>{_fmt_badge(a)}
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
            <span class="meta__sep">·</span><span>{a['date']}</span>{_fmt_badge(a)}
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
        # `sorted` OBLIGATOIRE : itérer directement sur la différence de sets
        # donne un ordre qui varie d'un processus Python à l'autre (hachage des
        # chaînes randomisé). Conséquence constatée le 02/08 : deux rebuilds
        # consécutifs du MÊME code produisaient deux `index.html` différents —
        # la une du site se réorganisait au hasard à chaque déploiement, et
        # chaque run commitait un diff parasite sur index/feed/sitemap.
        # Ne jamais itérer sur un set pour produire un rendu.
        for cat in sorted(missing):
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
    # Les brèves ont leur propre fil (« EN BREF » + breves.html) : les laisser
    # aussi dans la une/grille/liste les affichait DEUX fois sur l'accueil et
    # laissait un format court occuper la place d'un article de fond.
    articles_longs = [a for a in articles if a.get("format") != "breve"]

    _seuil_48h = datetime.now() - timedelta(hours=48)
    fenetre_recente = [a for a in articles_longs if (_d := _parse_date_pub(a.get("date", ""))) and _d >= _seuil_48h]
    if len(fenetre_recente) < 4:
        fenetre_recente = articles_longs[:15] if len(articles_longs) > 15 else list(articles_longs)
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
    grid_arts = _pick_diverse(articles_longs, 6, set(), force_diversity=False)
    used_grid = {main_art["slug"]}
    used_grid.update(a["slug"] for a in side_arts)
    used_grid.update(a["slug"] for a in grid_arts)
    # Liste "À lire aussi" : 6 articles diversifiés, excluant hero+side+grille
    list_arts = _pick_diverse(articles_longs, 6, used_grid)

    side_html  = "\n".join(side_card(a) for a in side_arts) if side_arts else ""
    grid_html  = "\n".join(mini_card(a) for a in grid_arts) if grid_arts else ""
    list_html  = "\n".join(list_card(i, a) for i, a in enumerate(list_arts))

    index_path = ROOT / "index.html"
    html = build_index_html(main_art, side_html, grid_html, list_html)
    index_path.write_text(html, encoding="utf-8")
    print(f"  ✓ index.html reconstruit ({len(articles)} articles)")
    build_category_pages()
    build_archive_page()
    build_breves_page()
    build_favoris_page()
    build_search_json(articles)
    build_feed_xml(articles)
    build_sitemap(articles)
    rebuild_articles_related(articles)


def _build_bloc_breves_accueil() -> str:
    """Section « EN BREF » de l'accueil — le fil des 6 dernières brèves.

    Remplace « À LIRE AUSSI » quand il y a de quoi la remplir. Format liste
    plutôt que grille d'images : une brève n'a pas de valeur visuelle propre,
    elle a une valeur de fil — on en lit six d'un coup d'œil.
    Repli : sous 3 brèves, on rend une chaîne vide et l'appelant retombe sur
    l'ancien bloc. Ne pas retirer ce repli tant que le corpus est jeune.
    """
    breves = _breves_recentes(n=6)
    if len(breves) < 3:
        return ""
    lignes = "\n".join(f"""
        <a class="breve-line" href="articles/{b['slug']}.html">
          <span class="cat cat--{b['categorie']}">{_cat_up(b['categorie'])}</span>
          <span class="breve-line__titre">{_esc(b['titre'])}</span>
          <span class="breve-line__date">{_esc(b.get('date', '').split(',')[0])}</span>
        </a>""" for b in breves)
    return f"""
  <div class="list-section" style="padding-top:40px">
    <div class="section__head" style="margin-bottom:16px">
      <span class="section__title">EN BREF</span>
      <a href="breves.html" class="section__more">Toutes les brèves →</a>
    </div>
    <div class="section__rule"></div>
    <div class="breve-list">{lignes}</div>
  </div>"""


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

  {_build_bloc_breves_accueil() or ('<div class="list-section" style="padding-top:40px"><div class="section__head" style="margin-bottom:16px"><span class="section__title">À LIRE AUSSI</span></div><div class="section__rule"></div><div class="list-grid">' + list_html + '</div></div>' if list_html else '')}
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
        (f"{BASE_URL}/breves.html", "0.7", "daily"),
        (f"{BASE_URL}/methode.html", "0.6", "monthly"),
        (f"{BASE_URL}/a-propos.html", "0.5", "monthly"),
        # mentions-legales, cgu et confidentialite sont volontairement en
        # <meta robots="noindex"> : les déclarer ici revenait à dire à Google
        # « indexe ces pages » pendant qu'elles répondent « ne m'indexe pas »
        # (constat 29/07). Un sitemap ne doit lister que des pages indexables.
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
              <span class="meta__sep">·</span><span>{a['date']}</span>{_fmt_badge(a)}
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
  <!-- Les 6 pages catégories n'avaient ni canonical ni balises Open Graph
       (constat 29/07) : partagées sur un réseau social, elles n'affichaient
       aucun aperçu, et les moteurs n'avaient pas d'URL de référence pour des
       pages pourtant centrales dans la navigation. -->
  <link rel="canonical" href="{BASE_URL}/categories/{cat}.html"/>
  <meta property="og:type" content="website"/>
  <meta property="og:site_name" content="Les Faits"/>
  <meta property="og:locale" content="fr_FR"/>
  <meta property="og:title" content="{label} — Les Faits"/>
  <meta property="og:description" content="Toute l'actualité {label} de Les Faits. Juste les faits. Aucun parti pris."/>
  <meta property="og:url" content="{BASE_URL}/categories/{cat}.html"/>
  <meta property="og:image" content="{BASE_URL}/assets/images/og-home.jpg"/>
  <meta name="twitter:card" content="summary_large_image"/>
  <meta name="twitter:title" content="{label} — Les Faits"/>
  <meta name="twitter:description" content="Toute l'actualité {label} de Les Faits."/>
  <meta name="twitter:image" content="{BASE_URL}/assets/images/og-home.jpg"/>
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
    <a class="archive-row" href="articles/{a['slug']}.html" style="display:grid;grid-template-columns:80px 1fr;gap:12px 20px;padding:16px 0;border-bottom:1px solid var(--rule);align-items:start;text-decoration:none;color:inherit">
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

def _resume_texte(a: dict) -> str:
    """Chapeau d'une entrée d'index en texte plat. `resume` est une liste de
    phrases pour les articles et une liste d'UNE phrase pour les brèves, mais
    d'anciennes entrées le stockent en chaîne — les deux formes coexistent
    dans articles.json et il ne faut pas casser sur les anciennes."""
    r = a.get("resume") or ""
    return " ".join(str(p) for p in r) if isinstance(r, list) else str(r)


def _breves_recentes(exclure_slug: str = "", n: int = 3) -> list[dict]:
    """Les n brèves les plus récentes, hors `exclure_slug`.

    Sert les blocs « EN BREF » de l'accueil et des pages article. Renvoie une
    liste éventuellement plus courte que n — l'appelant DOIT prévoir le repli :
    au 03/08 le corpus n'en compte que 4, et un bloc à moitié vide serait pire
    que l'ancien bloc « À lire aussi ».
    """
    return [a for a in load_index()
            if a.get("format") == "breve" and a.get("slug") != exclure_slug][:n]


def build_breves_page():
    """Génère breves.html — le fil des brèves, du plus récent au plus ancien.

    Rubrique à part entière et non catégorie : le format est ORTHOGONAL aux six
    catégories (une brève est aussi bien « santé » que « économie »). D'où une
    page dédiée plutôt qu'une septième entrée dans `CAT_LABELS`, qui aurait
    cassé le quota par catégorie de la sélection et la palette de couleurs.

    Présentation en fil compact, sans image : une brève tient en 150 mots, la
    donner à lire directement dans la liste vaut mieux qu'une vignette qui
    oblige à cliquer pour découvrir qu'il n'y a que six phrases.
    """
    breves = [a for a in load_index() if a.get("format") == "breve"]

    rows = "\n".join(f"""
    <a class="breve-row" href="articles/{a['slug']}.html">
      <div class="breve-row__meta">
        <span class="cat cat--{a['categorie']}">{_cat_up(a['categorie'])}</span>
        <span class="breve-row__date">{_esc(a.get('date', '').split(',')[0])}</span>
      </div>
      <div>
        <h2 class="breve-row__titre">{_esc(a['titre'])}</h2>
        <p class="breve-row__resume">{_esc(_resume_texte(a))}</p>
        <span class="breve-row__src">{a.get('nb_sources', 0)} sources · {a.get('nb_mots', 0)} mots</span>
      </div>
    </a>""" for a in breves)

    vide = """
    <p style="color:var(--muted);font-size:15px;line-height:1.7">
      Aucune brève publiée pour l'instant. Les brèves paraissent au fil des
      créneaux de publication, deux fois par jour.
    </p>"""

    html = f"""<!DOCTYPE html>
<html lang="fr" data-theme="">
<head>
  <meta charset="UTF-8"/>
  {CSP_META}
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <meta name="description" content="Les brèves de Les Faits : le fait du jour, établi et sourcé, en 150 mots. Sans mise en perspective ni analyse."/>
  <meta property="og:title" content="Brèves — Les Faits"/>
  <meta property="og:description" content="Le fait du jour, établi et sourcé, en 150 mots."/>
  <meta property="og:type" content="website"/>
  <meta property="og:url" content="https://lesfaits.info/breves.html"/>
  <meta property="og:image" content="https://lesfaits.info/assets/images/og-default.jpg"/>
  <meta name="twitter:card" content="summary_large_image"/>
  <meta name="twitter:image" content="https://lesfaits.info/assets/images/og-default.jpg"/>
  <link rel="canonical" href="https://lesfaits.info/breves.html"/>
  <title>Brèves — Les Faits</title>
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

<main class="wrap" style="max-width:760px;margin:48px auto;padding:0 20px 80px">
  <nav aria-label="Fil d'Ariane" style="font-size:13px;color:var(--muted);margin-bottom:32px">
    <a href="index.html" style="color:var(--muted)">Accueil</a>
    <span style="margin:0 6px">›</span>
    <span>Brèves</span>
  </nav>
  <h1 style="font-family:var(--font-serif,Georgia,serif);font-size:2rem;margin-bottom:8px">Brèves</h1>
  <p style="color:var(--muted);font-size:14px;line-height:1.7;margin-bottom:40px;max-width:60ch">
    Le fait du jour, établi et sourcé, en 150 mots — sans mise en perspective
    ni analyse. Une brève suit exactement le même protocole de vérification
    qu'un article : trois sources minimum, au moins une source primaire ou deux
    sources secondaires indépendantes, et le même fact-check avant publication.
    Elle est plus courte, jamais moins vérifiée.
    <a href="methode.html" style="color:var(--blue)">Notre méthode</a>.
  </p>
  <p style="color:var(--muted);font-size:13px;margin-bottom:24px">{len(breves)} brève{'s' if len(breves) > 1 else ''} publiée{'s' if len(breves) > 1 else ''}</p>
  {rows if breves else vide}
</main>

{_build_newsletter_section()}

{_build_footer()}
{_DARK_MODE_JS}
{_ANALYTICS_JS}
</body>
</html>"""

    (ROOT / "breves.html").write_text(html, encoding="utf-8")
    print(f"  ✓ breves.html généré ({len(breves)} brèves)")


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
      return '<a class="archive-row" href="articles/'+a.slug+'.html" style="display:grid;grid-template-columns:80px 1fr;gap:12px 20px;padding:16px 0;border-bottom:1px solid var(--rule);align-items:start;text-decoration:none;color:inherit">'
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
        # "article" (500 mots, 4 sections) | "breve" (130 mots, le fait seul).
        # Absent des entrées antérieures au 02/08 : traiter l'absence comme
        # "article", c'est ce qu'elles étaient toutes.
        "format":    art.get("format", "article"),
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

def audit_matiere(sources: list[dict], snippet_len: int = 950) -> dict:
    """Mesure la RICHESSE DOCUMENTAIRE, pas le volume de caractères.

    Constat (revue externe du 31/07) : `BUDGET_MATIERE` compte des caractères,
    or trois dépêches disant « le chômage baisse / diminue / recule » font
    3 000 caractères pour UN fait, tandis que NASA + ESA + Nature + CNRS font
    2 500 caractères pour quinze faits différents. Le second corpus produit un
    bien meilleur article, et l'ancien compteur les jugeait équivalents —
    pire, il préférait le premier.

    On mesure donc trois choses, sans aucun appel LLM :
      - `faits_distincts` : 5-grammes distincts sur l'ensemble du corpus. Deux
        sources qui reformulent la même phrase partagent leurs 5-grammes et ne
        comptent qu'une fois ; deux sources qui apportent des faits différents
        s'additionnent.
      - `redondance` : part des 5-grammes déjà vus dans une source précédente.
        Proche de 1 = un corpus d'échos, proche de 0 = des sources
        complémentaires.
      - `donnees_chiffrees` : valeurs numériques distinctes (avec leur unité),
        le marqueur le plus fiable d'une information propre à une source.

    Diagnostic seul pour l'instant : la fonction n'influence AUCUNE décision.
    La règle du projet est de mesurer un signal avant de s'en servir pour
    rejeter — c'est ce qui a évité deux faux garde-fous cette semaine.
    """
    def _cinq_grammes(txt: str) -> set:
        mots = re.findall(r"\w+", (txt or "").lower())
        return {" ".join(mots[i:i + 5]) for i in range(max(0, len(mots) - 4))}

    vus, redondants, total = set(), 0, 0
    for src in sources:
        g = _cinq_grammes((src.get("snippet") or "")[:snippet_len])
        total += len(g)
        redondants += len(g & vus)
        vus |= g

    chiffres = set()
    for src in sources:
        for m in re.finditer(r"\b\d[\d\s.,]*\s*(?:%|millions?|milliards?|€|euros?|"
                             r"km|kg|tonnes?|habitants?|cas|décès|ans|jours)\b",
                             (src.get("snippet") or "")[:snippet_len], re.I):
            chiffres.add(re.sub(r"\s+", " ", m.group(0).lower().strip()))

    return {
        "sources": len(sources),
        "faits_distincts": len(vus),
        "redondance": round(redondants / total, 2) if total else 0.0,
        "donnees_chiffrees": len(chiffres),
    }


def _lot_entierement_juge_sans_source_precise(extra: list[dict], juge_max: int) -> bool:
    """True seulement si le juge a examiné tout le lot attendu et n'a trouvé
    aucune source traitant le sujet précis. Un jugement interrompu en cours
    de lot (erreur API — voir `juger_pertinence_sources`) laisse des sources
    sans clé `_pertinence` du tout ; dans ce cas on retourne False plutôt que
    de rejeter un sujet jamais vraiment évalué (15/08, revue croisée — un
    ancien patch dupliquait cette logique dans run_pipeline_v3.py, couplé par
    une chaîne de caractères exacte au texte du print(), et a cassé `main`
    le jour où ce texte a changé)."""
    n_judged = sum(
        1 for s in extra
        if s.get("_pertinence") in {"pertinente", "generale", "hors_sujet"}
    )
    expected_judged = min(juge_max, len(extra))
    return expected_judged > 0 and n_judged >= expected_judged


def generer_article(item: dict, dry_run: bool, published: set, new_pub: set, date_pub: str,
                    published_topics: set | None = None,
                    budget_formats: dict | None = None) -> bool:
    """Génère et publie un article. Retourne True si succès.

    `budget_formats` — compteur MUTABLE partagé par toute la boucle du run, de
    la forme {"longs_restants": n}. Il n'est décrémenté qu'au moment où un
    sujet part réellement en génération longue : un sujet écarté en amont
    (listicle, sources insuffisantes) ne consomme aucun budget. À zéro, tous
    les sujets suivants passent en brève. Absent = aucun plafond, pour les
    appels de test et les régénérations ponctuelles.
    """
    if item["id"] in published:
        return False

    cat = item.get("_cat") or detect_category(item["title"] + " " + item["content"])

    # Classification déterministe ACTU / DOSSIER / REJETE (avant tout appel Groq)
    article_type = classifier_type_article(item["title"], item.get("content", ""))
    if article_type == "rejete":
        print(f"  [REJET DOSSIER] Listicle, lifestyle ou portrait polémique détecté : {item['title'][:55]}")
        return False

    # ── Allocation du format : budget, pas prédiction de qualité (02/08) ──
    # On NE tente PAS de deviner à l'avance si un sujet « mérite » 500 mots :
    # aucune distribution n'a encore été relevée sur `audit_matiere`, et la
    # règle du projet interdit de fixer un seuil avant de l'avoir mesuré.
    # On applique donc la seule règle défendable aujourd'hui, celle d'une
    # rédaction : le budget du créneau paie N articles longs, attribués aux
    # sujets les mieux notés (la sélection est déjà triée par score éditorial),
    # et tout le reste part en brève. Aucun sujet n'est plus perdu faute de
    # quota — il est traité au format que le budget permet.
    # Les dossiers (portrait/science) ne sont jamais dégradés : ils sont rares
    # et leur matière est structurellement épaisse.
    if article_type == "actu" and budget_formats is not None \
            and budget_formats.get("longs_restants", 0) <= 0:
        article_type = "breve"

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
    # 15 → 26 (30/07) : le budget de matière peut retenir jusqu'à 16 sources
    # quand elles sont fines (presse protégée plafonnée à ~200 caractères).
    # Avec un vivier de 15 dont une partie est écartée par `_est_source_citables`
    # et la dédup par titre, ce plafond amont rendait le budget inatteignable —
    # le correctif d'injection ne servait à rien. La recherche DDG ne coûte
    # AUCUN token Groq : élargir le vivier est gratuit, seule l'injection
    # dans le prompt est facturée, et elle reste bornée par BUDGET_MATIERE.
    # 26 → 45 (05/08) : on joue désormais 5 à 6 axes de recherche documentaire
    # au lieu de 3 requêtes de corroboration, donc le vivier brut est plus
    # large. Couper à 26 reviendrait à jeter les documents rapportés par les
    # derniers axes — juridique, audit, vérification — c'est-à-dire exactement
    # ceux qu'on cherchait à obtenir. Le tri par qualité juste après garde les
    # meilleurs, et BUDGET_MATIERE borne ce qui part réellement dans le prompt :
    # élargir ici ne coûte donc aucun token Groq.
    extra = duckduckgo_search(item["title"] + " " + cat, max_results=45, categorie=cat)
    pubmed = pubmed_search(item["title"], max_results=4)
    # Fusionner sans doublons
    seen_urls = {s["url"] for s in extra}
    for p in pubmed:
        if p["url"] not in seen_urls:
            extra.append(p)
            seen_urls.add(p["url"])

    # LES REPRISES DU MÊME ÉVÉNEMENT (17/08) — quand neuf rédactions couvrent
    # le même fait, le pipeline en retenait une et jetait les huit autres comme
    # des doublons. Ce sont pourtant huit angles et huit jeux de détails que la
    # dépêche retenue n'a pas. La veille les connaît déjà : les rendre coûte
    # zéro requête et zéro token.
    #
    # ⚠ Ce sont des reprises de PRESSE : secondaires au mieux, jamais primaires.
    # Elles ne comblent pas le déficit de sources primaires — c'est l'affaire
    # des axes documentaires du 05/08 — et elles entrent comme CANDIDATES, donc
    # elles subissent les mêmes filtres que tout le reste (domaines non
    # citables, qualité, juge de pertinence, BUDGET_MATIERE). Aucun passe-droit.
    try:
        import veille as _veille
        # Plafond volontairement bas au premier branchement : les grappes
        # contiennent du hors-sujet et le juge de pertinence ne note que les 10
        # premières sources après tri. En ajouter huit d'un coup pousserait des
        # documents non jugés dans le prompt. Quatre, puis on mesure.
        _reprises = [r for r in _veille.sources_evenement(item.get("url", ""), plafond=4)
                     if r["url"] not in seen_urls and _est_source_citables(r["url"])]
    except Exception as _e:  # noqa: BLE001
        print(f"     [ÉVÉNEMENT] reprises indisponibles ({type(_e).__name__})")
        _reprises = []
    if _reprises:
        for r in _reprises:
            full = "" if _est_presse_protegee(r["url"]) else fetch_full_content(r["url"])
            r["snippet"] = full[:8000] if len(full) > 500 else (r.get("title") or "")
            extra.append(r)
            seen_urls.add(r["url"])
        print(f"     [ÉVÉNEMENT] {len(_reprises)} reprise(s) du même fait "
              f"ajoutée(s) au vivier (vues par la veille)")

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
    )

    # PERTINENCE DOCUMENTAIRE (12/08) — la qualité du DOMAINE ne dit pas si le
    # document parle du sujet. C'est tout le défaut de
    # `articles/rougeole-antiviral-etude.html` : six sources sérieuses, dont la
    # fiche « Rougeole » de l'OMS et la page « Données » de Santé publique
    # France, sur un article qui annonce un antiviral précis. Toutes primaires,
    # aucune ne traitant le sujet.
    #
    # Backtest du 12/08 (`scripts/test_juge_sources.py`, 60 paires) :
    #
    #                            PERTINENTE  GENERALE  HORS_SUJET
    #   source ↔ SON article         20         10          0
    #   source ↔ article étranger     0         19         11
    #
    # Les deux zéros sont le résultat : jamais une vraie source déclarée hors
    # sujet, jamais une source étrangère déclarée pertinente. Sur le cas
    # d'école, le juge garde la seule source d'origine et écarte les cinq pages
    # permanentes.
    #
    # ⚠ ON TRIE, ON NE JETTE PAS. La règle « n'accepter que PERTINENTE » perd
    # jusqu'à 33 % des sources citées ; avec une médiane de 4 sources par
    # article et un plancher de publication à 3, elle échangerait un problème
    # de qualité contre un problème de quantité. Le juge REHAUSSE les documents
    # qui traitent le sujet, il n'en supprime aucun.
    # `item`, pas `sujet` : le paramètre de `generer_article` s'appelle `item`.
    # La faute de frappe d'origine a tué les runs des 12/08 soir et 13/08 sur
    # le PREMIER sujet, avant toute génération, deux jours de publication
    # perdus — voir l'avertissement sur le site d'appel dans
    # `juger_pertinence_sources`.
    _pertinence = juger_pertinence_sources(item.get("title", ""), extra)
    _RANG_PERTINENCE = {"pertinente": 0, "generale": 1, "": 1, "hors_sujet": 2}
    if _pertinence:
        extra = sorted(
            extra,
            key=lambda s: (_RANG_PERTINENCE.get(s.get("_pertinence", ""), 1),
                           _QUALITE_RANG.get(qualite_source(s.get("url", "")), 3))
        )
        _n_pert = sum(1 for s in extra if s.get("_pertinence") == "pertinente")
        print(f"     [PERTINENCE] {_n_pert} source(s) traitant le sujet précis, "
              f"{sum(1 for s in extra if s.get('_pertinence') == 'generale')} générale(s), "
              f"{sum(1 for s in extra if s.get('_pertinence') == 'hors_sujet')} hors sujet")
        # RENDU BLOQUANT le 11/08 (Nahil) : taux mesuré à 5/11 sujets sur deux
        # runs instrumentés (~45 %), largement au-dessus du seuil de ~10 % qui
        # sert de repère dans ce projet pour juger un motif trop large. Preuve
        # concrète : l'article inflation du 11/08 (Insee/Banque de
        # France/BCE/Vie Publique/Sénat, 5 organisations distinctes dans
        # « faits » — AUCUN autre article publié n'en cite plus d'une). Le
        # log de son run montrait exactement ce cas : 0 source pertinente, 9
        # générales — le prompt exige ≥4 sources citées, donc le modèle a cité
        # les pages permanentes qui ne parlaient PAS du chiffre de juillet
        # pour remplir le quota. Ce n'est pas un défaut de style (l'enchaînement
        # « info d'info d'info ») mais une CONSÉQUENCE MÉCANIQUE de sources hors
        # sujet forcées dans le texte. Rejeter ici évite de payer une
        # génération complète (~35 k tokens) pour un article structurellement
        # voué à ce défaut.
        #
        # PRUDENCE AJOUTÉE (15/08, revue croisée) : le juge peut s'interrompre
        # en cours de lot (erreur API — voir `juger_pertinence_sources`), et
        # renoncer laisse alors des sources SANS `_pertinence` du tout. Sans
        # cette garde, un lot interrompu après avoir jugé 2 sources sur 10,
        # toutes deux « générale », rejetterait un sujet pourtant jamais
        # vraiment évalué. On ne bloque donc que si le lot attendu a été
        # entièrement jugé — un jugement partiel garde le comportement
        # d'avant (avertissement seul, aucun rejet).
        if _n_pert == 0:
            if _lot_entierement_juge_sans_source_precise(extra, JUGE_SOURCES_MAX):
                print("     [REJET] AUCUNE source ne traite le sujet précis du "
                      "titre — rejet définitif (cas « rougeole »/« inflation »)")
                return False
            print("     [PERTINENCE] AUCUNE source pertinente, mais jugement "
                  "partiel — sujet conservé (avertissement seul)")

    # Plafond d'injection : un BUDGET DE MATIÈRE, pas un nombre de sources.
    #
    # Constat 30/07 : les premiers jets font ~250 mots pour une cible de 500,
    # sur TOUS les sujets, y compris les plus riches (incendies en Gironde).
    # Cause : le plafond était « les 8 meilleures sources », quelle que soit
    # leur épaisseur. Or les 20 médias de `_PRESSE_PROTEGEE` sont plafonnés à
    # ~200-1200 caractères (droits voisins) et ne sont pas scrapés — 8 sources
    # protégées, c'est ~1 600 caractères, soit moins de 300 mots de matière.
    # On demandait donc 500 mots sans extrapoler à partir de 300. Le modèle
    # s'arrêtait court : c'était la bonne réponse à une consigne impossible.
    #
    # On compte désormais les caractères réellement disponibles et on continue
    # de piocher (dans l'ordre de qualité) tant que le budget n'est pas atteint.
    # Un sujet couvert par des sources institutionnelles épaisses garde 8
    # sources ; un sujet couvert par de la presse protégée en obtient
    # davantage, ce qui rétablit la matière SANS toucher au plafond légal par
    # source. Bornes : au moins 8 sources, au plus 16 (le prompt tourne déjà à
    # ~7-8 k tokens, il ne faut pas le faire exploser).
    # ATTENTION — le budget doit compter ce qui est RÉELLEMENT INJECTÉ, pas la
    # taille du snippet stocké. `generate()` tronque chaque source à
    # `snippet_len` = 950 caractères (voir le bloc SOURCES DISPONIBLES). Une
    # première version comptait la taille brute (jusqu'à 8 000) : le budget se
    # remplissait avec des sources dont 900 caractères seulement partaient dans
    # le prompt, et la boucle s'arrêtait à 8 sources — le correctif ne servait
    # à rien précisément dans le cas visé.
    #
    # Budget calibré sur la contrainte Groq, pas sur l'envie de matière : la
    # limite est de 12 000 tokens/minute PAR CLÉ, prompt + max_tokens réservés.
    # Le prompt tourne déjà à ~7 000 tokens. 11 000 caractères de sources
    # ≈ 2 750 tokens, contre ~1 900 auparavant (8 × 950) : +850 tokens, ce qui
    # laisse la marge TPM intacte. Ne pas monter ce budget sans revérifier le
    # plafond TPM — un prompt trop lourd fait échouer l'appel en 413.
    SNIPPET_LEN_INJ = 950
    BUDGET_MATIERE = 11000   # caractères effectivement injectés
    # BRÈVE : le budget d'injection suit le format. Ces valeurs DOIVENT rester
    # alignées sur `snippet_len` dans generate() — c'est l'erreur déjà commise
    # une fois ici (budget calculé sur la taille stockée, pas sur la taille
    # injectée) : si les deux divergent, le budget compte des caractères qui
    # ne partent jamais dans le prompt et la boucle s'arrête au mauvais moment.
    if article_type == "breve":
        SNIPPET_LEN_INJ = 380
        BUDGET_MATIERE = 2600
    # MAX 14 → 10 (30/07, après mesure). Le run du 30/07 après-midi a injecté
    # 14 sources sur les 14 sujets, et 9 d'entre eux ont reçu de Groq une
    # réponse NON TEXTUELLE — des octets répétés en boucle (« \x13\x13… »,
    # « \x06\x06… »), pas du JSON malformé mais une dégénérescence du modèle.
    # Le taux est passé de 3/14 à 9/14 dans le seul run où le nombre de
    # sources a doublé : corrélation forte, causalité non démontrée. On
    # redescend à 10 en attendant une mesure propre — le gain de matière est
    # conservé (2 étoffements sur 14 contre 9 avant) sans pousser le prompt
    # aussi loin. Ne pas remonter ce plafond sans vérifier le taux de réponses
    # dégénérées dans les logs `[GROQ-BRUT] réponse sans JSON`.
    MIN_SOURCES_INJ, MAX_SOURCES_INJ = 8, 10
    # Brève : 6 sources injectées au minimum, pas moins. Le garde-fou d'après
    # exige 5 sources RÉELLES (après exclusion des URLs non citables) — passer
    # sous 6 injectées ferait échouer des sujets valides sur ce contrôle-là.
    if article_type == "breve":
        MIN_SOURCES_INJ, MAX_SOURCES_INJ = 6, 8
    _retenues, _budget = [], 0
    for _s in extra:
        if len(_retenues) >= MAX_SOURCES_INJ:
            break
        if len(_retenues) >= MIN_SOURCES_INJ and _budget >= BUDGET_MATIERE:
            break
        _retenues.append(_s)
        _budget += min(len(_s.get("snippet") or ""), SNIPPET_LEN_INJ)
    _audit = audit_matiere(_retenues, SNIPPET_LEN_INJ)
    # Le format retenu est journalisé À CÔTÉ de la mesure de matière : c'est ce
    # qui permettra, après quelques runs, de savoir si un routage par richesse
    # documentaire ferait mieux que le routage par budget appliqué ici — et de
    # fixer un seuil sur des distributions relevées, jamais devinées.
    print(f"     [MATIÈRE] format={article_type} · {_audit['sources']} sources · "
          f"{_audit['faits_distincts']} faits distincts · "
          f"redondance {_audit['redondance']:.0%} · "
          f"{_audit['donnees_chiffrees']} données chiffrées")
    if len(_retenues) > MIN_SOURCES_INJ:
        print(f"     [MATIÈRE] {_budget} caractères sur {len(_retenues)} sources "
              f"(sources fines : {MIN_SOURCES_INJ} n'auraient pas suffi)")
    extra = _retenues

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

    type_label = {"actu": "ACTU", "breve": "BRÈVE", "dossier_portrait": "DOSSIER/portrait",
                  "dossier_science": "DOSSIER/science"}.get(article_type, article_type)
    print(f"  → Génération [{type_label}] : {item['title'][:50]} [{len(specific_sources)} sources réelles]")

    if dry_run:
        print(f"     (dry-run)")
        return False

    # Le budget d'articles longs se consomme ICI, au dernier moment avant le
    # premier appel Groq — pas à la sélection. Un sujet écarté plus haut n'a
    # rien coûté et ne doit donc pas priver le suivant d'un format long.
    if budget_formats is not None and article_type != "breve":
        budget_formats["longs_restants"] = budget_formats.get("longs_restants", 0) - 1

    try:
        art = generate(content, cat, extra_sources=extra, rss_url=item.get("url"),
                       article_type=article_type)

        # Compteur de relances Groq pour cet article — sert de circuit-breaker
        # (voir rejet précoce plus bas).
        nb_garde_retries = 0
        # Garde-fous ayant signalé un défaut RESTÉ dans le texte publié. Passés
        # au log de vérification pour que `conforme_du_premier_coup` soit
        # interprétable (voir INSTRUMENTATION 03/08 plus bas).
        avertissements: list[str] = []

        # ── Article long revenu trop court : convertir AVANT les garde-fous ──
        # C'était le scénario le plus coûteux du pipeline — ~9 000 tokens de
        # relance d'étoffement, suivis dans la plupart des cas d'un rejet
        # définitif : 35 k tokens dépensés pour zéro publication. Or un premier
        # jet qui plafonne à 250 mots n'a pas un problème d'écriture mais un
        # problème de MATIÈRE : les sources n'en portaient pas 500. Le
        # constater après génération est une mesure, pas une supposition.
        # La décision est prise ICI, avant la relance corrective, pour deux
        # raisons : ne pas payer un étoffement vers 500 mots qu'on jetterait
        # juste après, et faire tourner tous les garde-fous suivants avec les
        # seuils du format réellement publié.
        # La charte n'est pas affaiblie : le plancher de l'ARTICLE reste 350
        # mots, aucun texte de 250 mots n'est publié « en tant qu'article ».
        if (CONVERSION_BREVE_SI_COURT and article_type == "actu"
                and isinstance(art, dict) and art
                and _mots_totaux(art) < SEUILS_FORMAT["article"]["plancher"]
                and _mots_resume_faits(art) >= SEUILS_FORMAT["breve"]["plancher"]):
            _mots_avant_conv = _mots_totaux(art)
            _reduire_en_breve(art)
            article_type = "breve"
            print(f"     [CONVERSION] Premier jet à {_mots_avant_conv} mots (plancher article "
                  f"{SEUILS_FORMAT['article']['plancher']}) — bascule en BRÈVE de "
                  f"{_mots_totaux(art)} mots, sans relance d'étoffement")

        # ── Garde-fous 1/3/4 : une SEULE relance corrective combinée ──────────
        # Les trois contrôles (attributions fantômes, résumé qui paraphrase le
        # corps, répétitions intra-article) sont déterministes et indépendants :
        # les évaluer d'abord tous puis relancer une seule fois avec les retours
        # combinés coûte 1 appel Groq au lieu de 3 — les relances en cascade
        # épuisaient le quota des 3 clés dès le 5e sujet du créneau.
        fantomes    = attributions_fantomes(art)
        citations_pb = citations_hors_liste(art)
        repetitions = resume_repete_corps(art)
        intra       = faits_repetitifs(art)
        selon       = attributions_trop_repetitives(art)
        titre_pb    = titre_de_mauvaise_qualite(art)
        cliches     = cliches_ia(art)
        intro_pb    = intro_generique(art)
        nuances_pb  = nuances_vagues(art)
        prospectif  = affirmation_non_demontree(art)
        fusion_pb   = sources_non_fusionnees(art)
        temporel_pb = incoherence_temporelle(art)
        position_pb = prise_de_position(art)
        if fantomes or citations_pb or repetitions or intra or selon or titre_pb or cliches or intro_pb or nuances_pb or prospectif or fusion_pb or temporel_pb or position_pb:
            details = []
            if fantomes:
                details.append(f"{len(fantomes)} attribution(s) hors sources")
            if citations_pb:
                details.append(f"{len(citations_pb)} citation(s) [n] hors liste")
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
            if fusion_pb:
                details.append(f"{len(fusion_pb)} empilement(s) une phrase = une source")
            if temporel_pb:
                details.append("titre au futur pour un événement déjà survenu")
            if position_pb:
                details.append(f"{len(position_pb)} prise(s) de position (neutralité)")
            # PISTE C (31/07) — fusionner l'étoffement dans la relance
            # corrective. Avant : on corrigeait les répétitions dans un appel,
            # puis on constatait que l'article était trop court et on relançait
            # une SECONDE fois. Deux allers-retours complets (~14 000 tokens)
            # pour deux défauts pourtant connus AU MÊME MOMENT. Mesure du
            # 31/07 : 8 étoffements sur 14 générations, dont la quasi-totalité
            # suivait déjà une relance corrective.
            # On joint donc le déficit de longueur au feedback combiné. Le
            # garde-fou d'étoffement dédié reste en place juste après : il ne
            # se déclenchera plus que si cette relance unique n'a pas suffi.
            _mots_avant = _mots_totaux(art)
            _seuil = _seuils(article_type)
            _expand_combine = None
            if _mots_avant < _seuil["plancher"]:
                _perimetre = ("chapeau + faits" if article_type == "breve"
                              else "chapeau + faits + contexte + nuances")
                _expand_combine = (
                    f"Ton texte ne fait que {_mots_avant} mots "
                    f"({_perimetre}), il en faut {_seuil['cible']}. "
                    f"Développe en même temps que tu corriges les points "
                    f"ci-dessus, sans rien inventer au-delà des sources."
                    + (" N'ouvre PAS les sections 'contexte' et 'nuances' : "
                       "elles doivent rester vides, développe uniquement 'faits'."
                       if article_type == "breve" else "")
                )
                details.append(f"trop court ({_mots_avant} mots) — étoffement joint")
            print(f"     [GARDE] {' + '.join(details)} — relance corrective unique…")
            art = generate(content, cat, extra_sources=extra, rss_url=item.get("url"),
                           expand_feedback=_expand_combine,
                           retry_feedback=fantomes or None,
                           citations_feedback=citations_pb or None,
                           repetition_feedback=repetitions or None,
                           intra_feedback=intra or None,
                           selon_feedback=selon or None,
                           titre_feedback=titre_pb or None,
                           cliches_feedback=cliches or None,
                           intro_feedback=intro_pb or None,
                           nuances_feedback=nuances_pb or None,
                           prospectif_feedback=prospectif or None,
                           fusion_feedback=fusion_pb or None,
                           temporel_feedback=temporel_pb or None,
                           position_feedback=position_pb or None,
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
            #
            # INSTRUMENTATION 03/08 — ces avertissements n'existaient que dans la
            # sortie GitHub, jamais dans `verification_log.json`. Conséquence :
            # `conforme_du_premier_coup` se lit « le fact-check LLM n'a rien
            # relevé », PAS « l'article est sorti propre » — un article peut
            # porter plusieurs avertissements de garde-fous restés sans effet et
            # être compté conforme. Tant que ce champ n'était pas journalisé,
            # toute statistique de conformité par format était ininterprétable.
            # Diagnostic seul : aucun de ces avertissements ne bloque, le
            # comportement du pipeline est strictement inchangé.
            _CONTROLES_AVERTISSEMENT = [
                ("resume_repete_corps", resume_repete_corps, "Résumé toujours proche du corps"),
                ("faits_repetitifs", faits_repetitifs, "Répétitions intra-article persistantes"),
                ("attributions_trop_repetitives", attributions_trop_repetitives, "Abus de « Selon X » persistant"),
                ("titre_de_mauvaise_qualite", titre_de_mauvaise_qualite, "Titre toujours non conforme"),
                ("cliches_ia", cliches_ia, "Tournures génériques IA persistantes"),
                ("nuances_vagues", nuances_vagues, "Débats et nuances toujours génériques"),
                ("affirmation_non_demontree", affirmation_non_demontree, "Affirmation prospective non conditionnelle"),
                ("sources_non_fusionnees", sources_non_fusionnees, "Sources toujours empilées une phrase par source"),
                ("incoherence_temporelle", incoherence_temporelle, "Titre au futur pour un événement déjà survenu"),
                ("prise_de_position", prise_de_position, "Prise de position persistante"),
            ]
            for _nom, _fn, _libelle in _CONTROLES_AVERTISSEMENT:
                if _fn(art):
                    avertissements.append(_nom)
                    print(f"     [AVERTISSEMENT] {_libelle} après relance")

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

        # ── Format brève : sections vides, garanties par le code ─────────────
        # Le prompt l'exige (règle 1), mais un modèle qui vient d'écrire 200
        # mots de « faits » remplit volontiers « contexte » par habitude, et
        # une relance corrective peut les rouvrir. On les vide ici plutôt que
        # de les détecter et relancer : c'est gratuit et sans échec possible.
        if article_type == "breve":
            _corps_b = art.get("corps") or {}
            if (_corps_b.get("contexte") or "").strip() or (_corps_b.get("nuances") or "").strip():
                print(f"     [BRÈVE] Sections 'contexte'/'nuances' remplies malgré la "
                      f"consigne — vidées (le fait du jour reste dans 'faits')")
            _reduire_en_breve(art)

        _seuil_fmt     = _seuils(article_type)
        MIN_MOTS_CORPS = _seuil_fmt["cible"]
        MIN_SOURCES    = _seuil_fmt["sources"]
        # Tolérance de 150 mots après relance (portée de 100 à 150 le 20/07,
        # Nahil : deux articles rejetés à 378/382 mots, trop proches du seuil
        # pour justifier une perte sèche) : la cible reste 500 mots, mais un
        # article qui plafonne à 350-499 mots malgré la relance d'étoffement
        # est accepté s'il est bien sourcé — plancher dur = 350 mots.
        # Depuis le 02/08 les deux valeurs viennent de SEUILS_FORMAT, pour que
        # la brève (130 / 100) soit jugée sur son propre format et pas sur
        # celui de l'article. Le sourcing, lui, est identique dans les deux.
        TOLERANCE_MOTS = MIN_MOTS_CORPS - _seuil_fmt["plancher"]
        mots, nb_src = _deficit_longueur_sources(art)
        # Second filet : la relance corrective peut avoir raccourci un article
        # qui passait avant elle. La conversion principale a lieu plus haut,
        # juste après le premier jet — voir [CONVERSION].
        if (CONVERSION_BREVE_SI_COURT and article_type == "actu"
                and mots < _seuil_fmt["plancher"]
                and _mots_resume_faits(art) >= SEUILS_FORMAT["breve"]["plancher"]):
            _reduire_en_breve(art)
            article_type   = "breve"
            _seuil_fmt     = _seuils(article_type)
            MIN_MOTS_CORPS = _seuil_fmt["cible"]
            MIN_SOURCES    = _seuil_fmt["sources"]
            TOLERANCE_MOTS = MIN_MOTS_CORPS - _seuil_fmt["plancher"]
            _mots_avant_conv, (mots, nb_src) = mots, _deficit_longueur_sources(art)
            print(f"     [CONVERSION] Article retombé à {_mots_avant_conv} mots après relance "
                  f"corrective — publié en BRÈVE de {mots} mots")
        # La relance ne part QUE sous le plancher dur (350), pas sous la cible
        # (500). Mesure du run du 30/07 : 9 relances d'étoffement sur 14
        # générations, soit une génération complète (~9 k tokens) payée deux
        # fois dans 64 % des cas — premier poste de dépense du run, pour un
        # résultat qui retombait de toute façon dans la bande 350-499 déjà
        # déclarée acceptable. Un article à 362 mots était donc régénéré pour
        # arriver à 450, alors qu'il était publiable en l'état.
        # La règle éditoriale n'est PAS affaiblie : le plancher de publication
        # reste 350 mots et 3 sources, exactement comme avant. Seul change le
        # moment où l'on dépense un aller-retour Groq.
        SEUIL_RELANCE_MOTS = MIN_MOTS_CORPS - TOLERANCE_MOTS  # 350
        if mots < SEUIL_RELANCE_MOTS or nb_src < MIN_SOURCES:
            manque_mots = max(0, MIN_MOTS_CORPS - mots)
            manque_src = max(0, MIN_SOURCES - nb_src)
            details = []
            if manque_mots:
                details.append(f"{mots} mots au lieu de {MIN_MOTS_CORPS} minimum")
            if manque_src:
                details.append(f"{nb_src} source(s) citée(s) au lieu de {MIN_SOURCES} minimum")
            _lbl_fmt = "brève" if article_type == "breve" else "article"
            _perimetre = ("chapeau + faits" if article_type == "breve"
                          else "chapeau + faits + contexte + nuances")
            print(f"     [GARDE] {_lbl_fmt.capitalize()} trop court/peu sourcé ({' + '.join(details)}) — relance d'étoffement…")
            expand_msg = (
                f"Ton texte ne fait que {mots} mots ({_perimetre}) "
                f"(minimum {MIN_MOTS_CORPS}) et ne cite que {nb_src} source(s) (minimum {MIN_SOURCES})."
                if manque_mots and manque_src else
                f"Ton texte ne fait que {mots} mots ({_perimetre}) "
                f"(minimum {MIN_MOTS_CORPS})." if manque_mots else
                f"Ton texte ne cite que {nb_src} source(s) (minimum {MIN_SOURCES})."
            )
            if article_type == "breve":
                expand_msg += (" N'ouvre PAS 'contexte' ni 'nuances' : elles doivent "
                               "rester vides, développe uniquement 'faits'.")
            art_expanded = generate(content, cat, extra_sources=extra, rss_url=item.get("url"),
                                    expand_feedback=expand_msg, article_type=article_type,
                                    previous_article=art)
            if isinstance(art_expanded, dict) and art_expanded:
                art = art_expanded
            if article_type == "breve":
                _reduire_en_breve(art)
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
        # `contexte` : ce que seul le pipeline connaît au moment du verdict, et
        # qui manquait pour exploiter les 227 étiquettes de
        # `verification_log.json` (voir l'instrumentation dans
        # `verification.py`). Diagnostic seul — rien ne le relit.
        _contexte_verdict = {
            "titre_rss": str(item.get("title") or "")[:200],
            "matiere_faits_distincts": _audit.get("faits_distincts"),
            "matiere_redondance": round(_audit.get("redondance", 0), 3),
            "matiere_donnees_chiffrees": _audit.get("donnees_chiffrees"),
            "n_sources_injectees": len(_retenues),
            "n_sources_trouvees": len(extra),
            "n_sources_pertinentes": sum(
                1 for s in extra if s.get("_pertinence") == "pertinente") or None,
        }
        # Signal de veille, journalisé À CÔTÉ de l'issue. C'est la mesure
        # annoncée le 14/08 et jamais branchée : « quelques runs diront lequel
        # des deux signaux prédit la publication ». Sans ça, la veille alimente
        # la sélection depuis trois jours sans qu'on puisse dire si elle sert.
        # Diagnostic seul — rien ne le relit, aucune décision n'en dépend.
        _v = item.get("_veille") or {}
        if _v:
            _contexte_verdict.update({
                "veille_heures_visible": _v.get("heures_visible"),
                "veille_passages": _v.get("passages"),
                "veille_age_h": _v.get("age_h"),
                "veille_n_flux_grappe": _v.get("n_flux_grappe"),
            })
        art, statut_verif = verifier_article(art, article_type=article_type,
                                            avertissements=avertissements,
                                            contexte=_contexte_verdict)
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
            # Le correcteur travaille sur le JSON complet : il peut rouvrir
            # 'contexte'/'nuances' d'une brève en croyant réparer une section
            # vide. On les revide AVANT de compter les mots, sinon le contrôle
            # de plancher validerait des sections qui ne seront pas rendues.
            if article_type == "breve":
                _reduire_en_breve(art)

            # ── CONTRÔLES BLOQUANTS LÉGAL / SANITAIRE APRÈS CORRECTION ───────
            # Priorité la plus haute du balayage du 03/08 : ces deux contrôles
            # sont BLOQUANTS et ne tournaient qu'AVANT `verifier_article`. Or
            # la passe 3 réécrit le texte ET la liste des sources — elle peut
            # donc réintroduire exactement ce qu'ils écartent.
            # La différence avec les autres contrôles non rejoués n'est pas de
            # degré : le défaut potentiel n'est pas « un mauvais article » mais
            # une mise en cause de personne ou une information de santé
            # publique sans source officielle. C'est-à-dire une exposition
            # juridique, pas un défaut éditorial.
            # Aucune réparation possible ici, contrairement aux attributions
            # fantômes : on ne « nettoie » pas un sujet sensible, on ne publie
            # pas. Le sujet repart au run suivant.
            _rejete_post, _raison_post = _est_rejete_sensible_deterministe(art)
            if _rejete_post:
                print(f"     [REJET POST-CORRECTION] Sujet sensible réintroduit par la "
                      f"correction : {_raison_post} — non publié")
                return False
            if sujet_sante_sans_source_officielle(art):
                print(f"     [REJET POST-CORRECTION] Sujet santé sensible sans source "
                      f"officielle après correction (la passe 3 réécrit aussi la liste "
                      f"des sources) — non publié")
                return False

            # ── ATTRIBUTIONS FANTÔMES APRÈS CORRECTION (03/08) ───────────────
            # C'est ce contrôle-là qui manquait, et il a coûté un retrait
            # public : l'article « L'IA Claude d'Anthropic s'échappe d'un
            # test » a été publié avec un chapeau ouvrant sur « Selon des
            # sources autorisées » — une attribution qui ne renvoie à aucune
            # source réelle, sur un journal dont l'attribution est la règle
            # fondatrice. Le garde-fou déterministe la détecte parfaitement :
            # rejoué sur le texte PUBLIÉ, il déclenche. Mais il ne tournait
            # qu'AVANT `verifier_article`, et la passe 3 réécrit le texte —
            # elle a réintroduit ce que la relance avait nettoyé.
            # Application directe de la leçon déjà écrite pour le sourcing le
            # 28/07 : tout contrôle placé avant `verifier_article` doit être
            # considéré comme invalidé par la passe 3. Même remède, même
            # stratégie « réparer, pas éradiquer » : on retire les attributions
            # invalides sans relance Groq, et on ne rejette que si le retrait
            # ne suffit pas.
            _fantomes_post = attributions_fantomes(art)
            if _fantomes_post:
                _art_nettoye = strip_attributions_invalides(art)
                if not attributions_fantomes(_art_nettoye):
                    art = _art_nettoye
                    print(f"     [RÉPARATION] {len(_fantomes_post)} attribution(s) fantôme(s) "
                          f"réintroduite(s) par la correction, supprimée(s) : "
                          f"{', '.join(_fantomes_post[:3])}")
                else:
                    print(f"     [REJET POST-CORRECTION] Attributions hors sources après "
                          f"correction et impossibles à retirer proprement "
                          f"({', '.join(_fantomes_post[:3])}) — non publié")
                    return False

            # ── CITATIONS [n] HORS LISTE APRÈS CORRECTION (05/08) ────────────
            # Même faille que les attributions fantômes ci-dessus, nouvelle
            # depuis le passage aux notes numérotées : la passe 3 réécrit la
            # liste 'sources' ET peut décaler la position d'un élément — un
            # [4] valide avant correction peut pointer sur la mauvaise source
            # après. Réparation déterministe (retrait du numéro, pas de la
            # phrase), rejet seulement si des citations invalides persistent.
            _citations_post = citations_hors_liste(art)
            if _citations_post:
                _art_sans_citation_ko = strip_citations_invalides(art)
                if not citations_hors_liste(_art_sans_citation_ko):
                    art = _art_sans_citation_ko
                    print(f"     [RÉPARATION] {len(_citations_post)} citation(s) hors liste "
                          f"réintroduite(s) par la correction, numéro(s) retiré(s) : "
                          f"{', '.join(_citations_post[:3])}")
                else:
                    print(f"     [REJET POST-CORRECTION] Citations hors liste après "
                          f"correction et impossibles à retirer proprement "
                          f"({', '.join(_citations_post[:3])}) — non publié")
                    return False

            if faits_repetitifs(art) or resume_repete_corps(art):
                _n_supp = _supprimer_phrases_dupliquees(art)
                if _n_supp:
                    print(f"     [RÉPARATION] {_n_supp} phrase(s) dupliquée(s) "
                          f"supprimée(s) après correction LLM")
            _mots_final = _mots_totaux(art)
            _restants = faits_repetitifs(art)
            # Le correcteur (passe 3) réécrit AUSSI la liste des sources et
            # peut en supprimer : les deux contrôles de sourcing les plus
            # importants (règle 7, 3 sources minimum ; règle de publication
            # ≥1 primaire OU ≥2 secondaires) tournaient AVANT la correction et
            # n'étaient jamais rejoués après. C'est ainsi que l'article Lidl a
            # été publié avec 2 sources (20 Minutes, Le Figaro) le 26/07 alors
            # qu'il en avait assez pour passer le contrôle initial. On les
            # rejoue ici — sans relance Groq (quota rare) : le sujet repart au
            # run suivant.
            _src_final = len(art.get("sources") or [])
            _bilan_final = bilan_qualite_sources(art.get("sources", []))
            art["qualite_sources"] = _bilan_final
            _sourcing_ko = (
                _src_final < MIN_SOURCES
                or (_bilan_final["primaire"] < 1 and _bilan_final["secondaire"] < 2)
            )
            if _mots_final < MIN_MOTS_CORPS - TOLERANCE_MOTS or _restants or _sourcing_ko:
                _defauts = []
                if _mots_final < MIN_MOTS_CORPS - TOLERANCE_MOTS:
                    _defauts.append(f"{_mots_final} mots (< {MIN_MOTS_CORPS - TOLERANCE_MOTS})")
                if _restants:
                    _defauts.append("répétitions résiduelles")
                if _src_final < MIN_SOURCES:
                    _defauts.append(f"{_src_final} source(s) après correction (< {MIN_SOURCES})")
                elif _sourcing_ko:
                    _defauts.append(
                        f"sourcing dégradé après correction "
                        f"({_bilan_final['primaire']} primaire(s), "
                        f"{_bilan_final['secondaire']} secondaire(s))")
                print(f"     [REJET POST-CORRECTION] Article dégradé même "
                      f"après réparation ({' + '.join(_defauts)}) — non "
                      f"publié, sujet retenté au prochain run")
                return False

        # La catégorie publiée est TOUJOURS celle du classifieur déterministe
        # (detect_category, lexique v2) — jamais celle choisie par le LLM, dont
        # la liste autorisée dans le prompt était incomplète (pas de "sante")
        # et dont le choix contredisait régulièrement le lexique.
        #
        # Elle est recalculée sur le TEXTE GÉNÉRÉ (titre + chapeau + faits +
        # contexte) et non plus sur le seul extrait RSS : un teaser tronqué de
        # quelques lignes ne contient presque aucun mot-clé propre au sujet, et
        # le lexique "science" — qui contient des mots très courants
        # (« étude », « chercheurs », « scientifique », « évolution ») — raflait
        # alors la mise par défaut, d'autant qu'il est 2e dans _CAT_PRIORITE et
        # gagne donc les égalités. C'est ce qui a classé en « science » un
        # article sur le bannissement de Huawei des réseaux télécoms (28/07) et
        # un article sur la CAN féminine (26/07). Repli sur la catégorie issue
        # du RSS si le texte généré ne déclenche aucun mot-clé.
        # ── Dédoublonnage FINAL, quel que soit le statut de vérification ─────
        #
        # Mesuré le 15/08 sur les 161 articles longs publiés : 107 déclenchent
        # `faits_repetitifs`, et **43 contiennent une phrase entière dupliquée
        # mot pour mot**. Exemple réellement en ligne, deux fois à l'identique
        # dans le même article :
        #
        #   « La gestion sanitaire des vagues de chaleur est un enjeu important
        #     pour les autorités de santé. »
        #
        # La réparation existait pourtant depuis le 18/07 — mais elle vivait
        # dans la branche `if statut_verif == "corrige_automatiquement"`. Un
        # article validé du PREMIER coup ne passait donc jamais dessus, et
        # c'est le cas le plus fréquent aujourd'hui. Le nettoyage était réservé
        # aux articles qu'on avait dû corriger, c'est-à-dire précisément à ceux
        # qui en avaient le moins besoin une fois corrigés.
        #
        # Le placer ici, dans le chemin COMMUN, le rend inconditionnel. Il est
        # déterministe, ne coûte aucun jeton, et ne peut que RETIRER une
        # répétition littérale — jamais réécrire une phrase ni en inventer une.
        #
        # Le plancher de mots est revérifié juste après : si supprimer les
        # doublons fait passer l'article sous le seuil, c'est que la
        # duplication masquait un article creux, et il n'est pas publié. C'est
        # la stratégie « réparer, pas éradiquer » (Nahil, 18/07), appliquée
        # cette fois à tous les articles.
        # ⚠ On appelle ici la variante STRICTE, pas
        # `_supprimer_phrases_dupliquees`. Cette dernière traite les phrases
        # « quasi identiques » (3 quintuplets communs, ou 62 % de similarité) —
        # seuils tolérables sur les seuls articles corrigés, mais destructeurs
        # appliqués à tous : mesuré sur le corpus, elle nettoie 131 articles
        # sur 161 en retirant 154 mots en médiane, et sur
        # `bulle-froide-atlantique` elle supprime 3 des 4 phrases de
        # « Contexte » — dont des phrases qui ne sont pas des doublons mais
        # simplement proches, deux énoncés sur l'AMOC dépassant facilement
        # 62 % de similarité.
        #
        # Un seuil calibré pour un cas rare devient un massacre appliqué au cas
        # général. On ne retient donc que l'indiscutable : la phrase répétée
        # MOT POUR MOT, qu'aucune relecture ne défendrait.
        _n_dup = _supprimer_phrases_identiques(art)
        if _n_dup:
            print(f"     [RÉPARATION] {_n_dup} phrase(s) répétée(s) mot pour mot "
                  f"supprimée(s) (statut « {statut_verif} »)")
            _mots_apres_dedup = _mots_totaux(art)
            _plancher = SEUILS_FORMAT.get(
                "breve" if article_type == "breve" else "article", {}).get("plancher", 0)
            if _plancher and _mots_apres_dedup < _plancher:
                print(f"     [REJET] {_mots_apres_dedup} mots après retrait des "
                      f"doublons (plancher {_plancher}) — la duplication masquait "
                      f"un article creux, non publié")
                return False

        _corps_cat = art.get("corps", {}) or {}
        _resume_cat = art.get("resume", "")
        if isinstance(_resume_cat, list):
            _resume_cat = " ".join(str(p) for p in _resume_cat)
        _texte_cat = " ".join(str(x or "") for x in (
            art.get("titre", ""), _resume_cat,
            _corps_cat.get("faits", ""), _corps_cat.get("contexte", ""),
        ))
        # ── Communication de marque : recontrôle sur le TEXTE GÉNÉRÉ ────────
        # Constat 30/07 : l'article « Amazon Prime Video organise Obsessed Fest
        # pour les fans de comédies romantiques » a été publié alors que le
        # candidat RSS sélectionné s'intitulait « De "Off Campus" à "Fourth
        # Wing", l'hégémonie de Prime Video » — un sujet culturel défendable,
        # 2e sur 75 au score. C'est la GÉNÉRATION qui a glissé vers l'événement
        # promotionnel trouvé dans les sources. Le filtre `_PR_MARQUE_RE` du
        # scoring ne pouvait rien voir : il s'applique à l'extrait RSS, pas au
        # texte produit. Même classe de piège que la catégorie calculée sur le
        # teaser — d'où le même remède, un recontrôle en aval.
        # Rejet définitif : un communiqué ne se répare pas en le réécrivant.
        if _PR_MARQUE_RE.search(_texte_cat[:1500]):
            _motif = _PR_MARQUE_RE.search(_texte_cat[:1500]).group(0)
            print(f"     [REJET] Communication de marque dans le texte généré "
                  f"(« {_motif} ») — le sujet a glissé du candidat vers un "
                  f"contenu promotionnel, non publié")
            return False

        _scores_cat = _scores_categories(_texte_cat)
        _best_cat   = max(_CAT_PRIORITE, key=lambda c: _scores_cat[c])
        if _scores_cat[_best_cat] < SCORE_CATEGORIE_MIN:
            _best_cat = "societe"
        if _best_cat != cat:
            print(f"     [CATÉGORIE] {cat} (extrait RSS) → {_best_cat} "
                  f"(texte généré, score {_scores_cat[_best_cat]})")
        art["categorie"] = _best_cat

        # Le badge public reflète le nombre de sources réellement citées
        # APRÈS correction, jamais le nombre fourni en entrée
        art["nb_sources"] = len(art.get("sources", []))

        # Compter les mots finaux pour le système de scoring longueur ET le
        # badge public (chapeau + corps — voir _mots_totaux)
        art["nb_mots"] = _mots_totaux(art)
        # Format publié — porté jusqu'à l'index et aux cartes d'accueil : un
        # lecteur doit savoir avant de cliquer qu'il ouvre une brève de 130
        # mots et pas un article. C'est la contrepartie honnête du format.
        art["format"] = "breve" if article_type == "breve" else "article"

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

        _STATS_REJETS.clear()
        _STATS_REJETS_SOURCE.clear()
        rendement: dict[str, tuple[int, int]] = {}  # source → (collectés, retenus)
        brut_total = 0
        for src in RSS_SOURCES:
            items = fetch_rss(src)
            brut_total += len(items)
            retenus_src = 0
            deja_vus = {i["id"] for i in tous_candidats}
            # Dédup par TITRE en plus de l'id : l'id est un hash de l'URL, donc
            # la même dépêche reprise par deux flux (ou republiée avec une URL
            # de tracking) passait deux fois. Constat 30/07 : « En Gironde,
            # 80 hectares dédiés aux recherches forestières » a occupé DEUX des
            # 31 places de sélection et a été généré deux fois — ~26 k tokens
            # brûlés pour le même sujet, tous deux rejetés.
            deja_titres = {_titre_norme(i["title"]) for i in tous_candidats}
            for item in items:
                if item["id"] in published or item["id"] in deja_vus:
                    continue
                if _titre_norme(item["title"]) in deja_titres:
                    continue
                scored = filtrer_et_classer([item], src["name"], published_topics, seuil_score=20)
                if scored:
                    tous_candidats.extend(scored)
                    retenus_src += len(scored)
            rendement[src["name"]] = (len(items), retenus_src)

        # Rapport de rendement : une source en erreur est déjà visible via
        # [RSS ERREUR], mais une source qui répond 200 en renvoyant 0 article
        # ne l'était PAS — c'est ainsi qu'un flux Atom lu comme du RSS est
        # resté muet pendant des semaines en paraissant fonctionner. On liste
        # donc explicitement les sources sans rendement à chaque run.
        muettes = [n for n, (c, _) in rendement.items() if c == 0]
        if muettes:
            print(f"\n  [RENDEMENT] {len(muettes)} source(s) sans aucun article "
                  f"(0 collecté, sans erreur HTTP) : {', '.join(muettes)}")
        steriles = [n for n, (c, r) in rendement.items() if c > 0 and r == 0]
        if steriles:
            print(f"  [RENDEMENT] {len(steriles)} source(s) dont aucun article ne "
                  f"passe le filtre éditorial : {', '.join(steriles)}")
        actives = sum(1 for c, _ in rendement.values() if c > 0)
        print(f"  [RENDEMENT] {actives}/{len(RSS_SOURCES)} sources actives — "
              f"{brut_total} articles collectés avant filtre")

        print(f"\n[SCORING] {len(tous_candidats)} candidats après filtre")

        # Où meurent les articles collectés ? Sans ce décompte, la perte entre
        # la collecte et le scoring (~88 %) est un trou noir : impossible de
        # savoir si le barème écarte du bruit ou de vrais sujets.
        if _STATS_REJETS:
            total_rej = sum(_STATS_REJETS.values())
            print(f"  [REJETS] {total_rej} article(s) écarté(s) par le filtre éditorial :")
            for motif, n in _STATS_REJETS.most_common():
                print(f"    {n:>5}  ({100*n/total_rej:4.1f} %)  {motif}")
            print(f"  [REJETS] sources les plus filtrées : " + ", ".join(
                f"{s} ({n})" for s, n in _STATS_REJETS_SOURCE.most_common(6)))

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
        # ── Répartition du quota entre formats — revu le 05/08 (Nahil) ───────
        # Le format brève (02/08) répondait à un déficit de MATIÈRE, pas à un
        # choix éditorial : sur 150 mots de matière réelle, 500 mots demandés
        # ne pouvaient produire que du remplissage. Depuis, le sourcing par
        # question (05/08) va chercher du droit primaire, des séries
        # statistiques et des organismes de vérification en plus des dépêches
        # — la matière qui manquait est en grande partie revenue.
        # Décision de Nahil : viser PEU d'articles, LONGS et EXCELLENTS,
        # plutôt qu'un volume de brèves. QUOTA_ARTICLES_LONGS couvre donc la
        # quasi-totalité de la sélection — la brève n'est plus le format par
        # défaut, elle reste le SEUL filet de sécurité : la conversion
        # automatique (`CONVERSION_BREVE_SI_COURT`, plus bas dans
        # `generer_article`) continue de basculer un sujet qui n'atteint
        # vraiment pas le plancher article, au lieu de le rejeter — un sujet
        # ponctuellement mince n'est pas perdu, il change juste de format.
        # Si le quota Groq redevient la vraie contrainte (moins de clés que
        # prévu), redescendre ce nombre est le seul paramètre à bouger.
        #
        # ── Constat du 10/08 : la contrainte est REVENUE, non corrigée ici ───
        # Quatre jours sans publication (dernier article : 05/08, 15h09). Les
        # runs sélectionnent 34 sujets, en tentent 1 à 9, épuisent le quota et
        # publient zéro — aucun n'atteint même la grille vitrine. La fenêtre
        # glissante ne se recharge jamais : le run suivant démarre déjà à sec.
        #
        # La capacité n'a PAS baissé : le quota Groq est par COMPTE, pas par
        # clé, donc les 23 clés d'avant valaient déjà ce que valent les 11
        # d'aujourd'hui (voir `diagnostic_cles_groq`). C'est la DEMANDE qui a
        # doublé le 05/08 — dernier jour de publication : ce plafond est passé
        # de 4 à 30, la cible d'article de 500 à 800 mots, et la brève a cessé
        # d'être le format par défaut. Un sujet coûte donc ~3× plus qu'avant.
        # Le plafond réellement appliqué n'est PAS ce 30 (voir ci-dessous).
        # ⚠ LIGNE SOUS CONTRAT — ne pas la réécrire sans lire `run_pipeline.py`.
        # C'est le wrapper que lance le workflow, pas ce fichier directement :
        # il patche le source à la volée et cherche cette affectation par sa
        # chaîne littérale exacte (marqueur « budget formats vitrine »). La
        # transformer en expression calculée fait échouer TOUT le pipeline au
        # démarrage, et la citer dans un commentaire la rend « dupliquée » —
        # les deux erreurs commises le 10/08. Le plafond effectivement appliqué
        # se règle dans `run_pipeline.py`, pas ici.
        QUOTA_ARTICLES_LONGS = 30
        budget_formats = {"longs_restants": QUOTA_ARTICLES_LONGS}
        print(f"\n[GÉNÉRATION] budget : {QUOTA_ARTICLES_LONGS} article(s) long(s), "
              f"puis brèves sur les {max(0, len(selection) - QUOTA_ARTICLES_LONGS)} sujets suivants")
        # ── Réserve de quota : ne pas vider la fenêtre glissante (10/08) ─────
        # Boucle de famine observée du 05 au 10/08 : chaque run entame des
        # sujets jusqu'à l'épuisement total, n'en publie aucun, et laisse la
        # fenêtre de 24 h à sec — le run suivant démarre sans rien et ne peut
        # tenter que 1 à 2 sujets, qui meurent à leur tour. Quatre jours sans
        # publication, alors que la capacité n'avait pas bougé.
        # On plafonne donc les TENTATIVES, pas seulement les acceptations : le
        # run s'arrête en laissant du quota, ce qui permet au suivant d'aller
        # au bout de quelques sujets au lieu de mourir en route. Un sujet non
        # tenté n'est pas perdu — il revient dans la sélection du run suivant.
        # Calibré sur la mesure : les runs des 08-10/08 ont entamé 7 à 9 sujets
        # avant l'épuisement, donc s'arrêter à 6 laisse une réserve réelle.
        # RELEVÉ le 11/08 (Nahil, priorité absolue : un seul article mais
        # parfait, budget non contraignant) : le run du 11/08 12h24 a épuisé
        # ses 6 tentatives sans succès (angle insuffisant ×2, sujet sensible,
        # Ebola, troncature, conversion brève) alors que 35 sujets restaient
        # disponibles après sélection. Le plafond de 6 protégeait le quota du
        # run SUIVANT — utile en temps normal, contre-productif tant que
        # l'objectif est un seul article réussi coûte que coûte. À rabaisser
        # une fois la recette validée et le rythme normal repris.
        MAX_TENTATIVES_PAR_RUN = 20
        _tentatives = 0
        for item in selection:
            elapsed = time.time() - _pipeline_start
            if elapsed > _BUDGET_SECONDES:
                print(f"  [BUDGET] {elapsed/60:.1f} min écoulées — arrêt pour éviter le timeout GitHub (budget={_BUDGET_SECONDES//60} min)")
                break
            if _tentatives >= MAX_TENTATIVES_PAR_RUN:
                print(f"  [RÉSERVE] {_tentatives} sujets tentés — arrêt volontaire pour "
                      f"laisser du quota au créneau suivant. Les {len(selection) - _tentatives} "
                      f"sujets restants repartiront dans la prochaine sélection.")
                break
            _tentatives += 1
            try:
                _now_article = datetime.now()
                date_pub = f"{_now_article.day} {MOIS[_now_article.month-1]} {_now_article.year}, {_now_article.strftime('%Hh%M')}"
                if generer_article(item, dry_run, published, new_pub, date_pub, published_topics,
                                   budget_formats=budget_formats):
                    # Ajouter le titre généré à published_topics pour éviter les doublons dans la même session
                    published_topics.add(item.get("title", ""))
            except QuotaJournalierEpuise:
                print(f"\n  [ARRÊT] Quota Groq épuisé sur toutes les clés, et aucune "
                      f"ne se libère dans les {ATTENTE_MAX_LIBERATION // 60} min. "
                      f"Le TPD est une fenêtre GLISSANTE de 24 h (pas un reset à "
                      f"minuit) : les tokens brûlés hier après-midi pèsent encore "
                      f"ce matin. Les sujets restants seront retentés au prochain "
                      f"créneau.")
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
    diagnostic_cles_groq()

    run(dry_run=args.dry_run, text_input=args.text)

