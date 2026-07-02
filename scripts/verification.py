"""
Les Faits — Vérification éditoriale en 3 passes (Anthropic claude-sonnet-4-6)
==============================================================================
Passe 1 : génération (Groq, dans pipeline.py — inchangée)
Passe 2 : détection  (fact-checker indépendant, sans mémoire de la passe 1)
Passe 3 : correction (uniquement si non conforme), puis passe 2 rejouée

Statuts possibles :
  conforme_du_premier_coup  → publié tel quel
  corrige_automatiquement   → publié corrigé (original + rapport journalisés)
  a_corriger_manuellement   → JAMAIS publié : mis en file data/moderation_queue.json
  non_verifie               → ANTHROPIC_API_KEY absent (comportement historique)
  erreur_verification       → l'API a échoué, publié tel quel + journalisé

La clé API vient de l'environnement (secret GitHub ANTHROPIC_API_KEY).
Aucune clé n'est jamais codée en dur.
"""

import os, re, json
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
MODERATION_QUEUE = DATA / "moderation_queue.json"
VERIF_LOG = DATA / "verification_log.json"

ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = "claude-sonnet-4-6"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


# ══════════════════════════════════════════════════════════════════════════════
# PROMPTS — adaptés au format d'article actuel du pipeline
# (titre / resume[3] / corps.faits / corps.contexte / corps.nuances / sources[])
# ══════════════════════════════════════════════════════════════════════════════

PROMPT_DETECTION = """Tu es un fact-checker indépendant et rigoureux pour Les Faits. Analyse l'article ci-dessous par rapport à sa liste de sources autorisées. Sois exhaustif : ton rôle est de trouver TOUS les problèmes, pas de donner le bénéfice du doute.

Cherche spécifiquement :
1. SOURCES INVENTÉES : tout nom de média, expert, institution, étude cité dans le texte qui n'apparaît pas dans les sources autorisées
2. FORMULES VAGUES NON SOURCÉES : "selon les experts", "des études montrent", "selon les sources", "il est établi" sans référence précise à une source de la liste
3. REDONDANCES : toute phrase de "contexte" ou "nuances" qui répète, même reformulée, une idée déjà présente dans "faits"
4. JUGEMENTS DE VALEUR : tout adjectif, adverbe ou tournure qui trahit une opinion plutôt qu'un fait neutre
5. EXTRAPOLATIONS : toute anticipation de conséquence future non explicitement sourcée
6. INCOHÉRENCE DU COMPTEUR : le champ "nb_sources" ne correspond pas au nombre réel de sources de la liste effectivement utilisées dans le texte

Pour CHAQUE problème trouvé, cite la phrase exacte concernée (mot pour mot, copiée depuis l'article) et précise dans quelle section elle se trouve.

Réponds en JSON strict, sans texte hors JSON :
{
  "conforme": true/false,
  "problemes": [
    {
      "section": "faits | contexte | nuances | resume | titre",
      "type": "source_inventee | formule_vague | redondance | jugement_de_valeur | extrapolation | compteur_incoherent",
      "phrase_exacte": "citation mot pour mot de l'article",
      "explication": "pourquoi c'est un problème, en une phrase"
    }
  ]
}

ARTICLE :
{ARTICLE_JSON}

SOURCES AUTORISÉES :
{SOURCES}"""

PROMPT_CORRECTION = """Tu es un correcteur pour Les Faits. Voici un article et un rapport précis de ses défauts. Ta mission : produire une version corrigée qui règle CHAQUE problème listé, sans en introduire de nouveaux.

RÈGLES DE CORRECTION :
- Pour une "source_inventee" : supprime la phrase ou le passage concerné, SAUF si l'information peut être reformulée en te basant uniquement sur les sources autorisées — dans ce cas, réécris-la en l'attribuant correctement.
- Pour une "formule_vague" : soit tu la relies à une source précise de la liste, soit tu la supprimes.
- Pour une "redondance" : supprime la répétition dans la section où elle est en trop (garde-la seulement dans "faits").
- Pour un "jugement_de_valeur" : reformule en langage neutre et factuel.
- Pour une "extrapolation" : supprime, sauf si tu peux l'attribuer explicitement à une source qui l'exprime.
- Pour un "compteur_incoherent" : recompte et corrige le champ "nb_sources" pour qu'il reflète exactement la réalité du texte corrigé.

Ne modifie AUCUNE partie de l'article qui n'est pas mentionnée dans le rapport de problèmes. Ne raccourcis pas arbitrairement, ne réécris pas le style, corrige uniquement ce qui est signalé.

Réponds avec le même format JSON que l'article original, entièrement corrigé, sans texte hors JSON.

ARTICLE ORIGINAL :
{ARTICLE_JSON}

RAPPORT DE PROBLÈMES :
{RAPPORT}

SOURCES AUTORISÉES :
{SOURCES}"""


# ══════════════════════════════════════════════════════════════════════════════
# APPEL API
# ══════════════════════════════════════════════════════════════════════════════

def _anthropic_call(prompt: str, max_tokens: int = 6000) -> str:
    r = requests.post(
        ANTHROPIC_URL,
        headers={
            "x-api-key": ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": ANTHROPIC_MODEL,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=180,
    )
    r.raise_for_status()
    return r.json()["content"][0]["text"].strip()


def _extract_json(text: str) -> dict:
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    start = text.find("{")
    if start == -1:
        raise ValueError("Pas de JSON dans la réponse")
    return json.loads(text[start:])


def _sources_block(art: dict) -> str:
    lines = []
    for s in art.get("sources", []):
        lines.append(f"- {s.get('institution','')} | {s.get('titre','')} | {s.get('url') or 'pas d URL'}")
    return "\n".join(lines) or "(aucune source)"


def detecter(art: dict) -> dict:
    """Passe 2 — fact-check indépendant. Retourne le rapport JSON."""
    prompt = (PROMPT_DETECTION
              .replace("{ARTICLE_JSON}", json.dumps(art, ensure_ascii=False))
              .replace("{SOURCES}", _sources_block(art)))
    return _extract_json(_anthropic_call(prompt, max_tokens=4000))


def corriger(art: dict, rapport: dict) -> dict:
    """Passe 3 — correction ciblée. Retourne l'article corrigé."""
    prompt = (PROMPT_CORRECTION
              .replace("{ARTICLE_JSON}", json.dumps(art, ensure_ascii=False))
              .replace("{RAPPORT}", json.dumps(rapport, ensure_ascii=False))
              .replace("{SOURCES}", _sources_block(art)))
    corrige = _extract_json(_anthropic_call(prompt, max_tokens=8000))
    # Champs techniques jamais modifiables par le correcteur
    for k in ("slug", "categorie", "image_keyword"):
        if k in art:
            corrige[k] = art[k]
    return corrige


# ══════════════════════════════════════════════════════════════════════════════
# JOURNALISATION
# ══════════════════════════════════════════════════════════════════════════════

def _append_json(path: Path, entry: dict):
    data = []
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = []
    data.append(entry)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _log(slug: str, statut: str, detail: dict | None = None):
    _append_json(VERIF_LOG, {
        "slug": slug,
        "statut": statut,
        "date": datetime.now().isoformat(timespec="seconds"),
        **(detail or {}),
    })


def enqueue_moderation(art: dict, rapport_initial: dict, rapport_final: dict):
    """File d'attente des articles à valider manuellement — jamais publiés."""
    _append_json(MODERATION_QUEUE, {
        "date": datetime.now().isoformat(timespec="seconds"),
        "slug": art.get("slug", "?"),
        "titre": art.get("titre", "?"),
        "article": art,
        "rapport_initial": rapport_initial,
        "rapport_final": rapport_final,
    })


# ══════════════════════════════════════════════════════════════════════════════
# ORCHESTRATION — la fonction appelée par pipeline.py
# ══════════════════════════════════════════════════════════════════════════════

def verifier_article(art: dict) -> tuple[dict, str]:
    """
    Applique les passes 2 (détection) et 3 (correction) sur un article généré.
    Retourne (article_final, statut). Si statut == "a_corriger_manuellement",
    l'article a déjà été mis en file de modération et NE DOIT PAS être publié.
    """
    slug = art.get("slug", "?")

    if not ANTHROPIC_KEY:
        # Pas de clé → comportement historique, tracé comme non vérifié
        return art, "non_verifie"

    try:
        rapport = detecter(art)
    except Exception as e:
        print(f"     [VERIF] Erreur API détection ({e}) — publié sans vérification")
        _log(slug, "erreur_verification", {"etape": "detection", "erreur": str(e)})
        return art, "erreur_verification"

    if rapport.get("conforme"):
        _log(slug, "conforme_du_premier_coup")
        return art, "conforme_du_premier_coup"

    n_pb = len(rapport.get("problemes", []))
    print(f"     [VERIF] {n_pb} problème(s) détecté(s) — correction automatique…")

    try:
        art_corrige = corriger(art, rapport)
        rapport_final = detecter(art_corrige)
    except Exception as e:
        print(f"     [VERIF] Erreur API correction ({e}) — mis en file de modération")
        enqueue_moderation(art, rapport, {"erreur": str(e)})
        _log(slug, "a_corriger_manuellement", {"etape": "correction", "erreur": str(e)})
        return art, "a_corriger_manuellement"

    if rapport_final.get("conforme"):
        _log(slug, "corrige_automatiquement", {
            "problemes_initiaux": n_pb,
            "rapport_initial": rapport,
        })
        return art_corrige, "corrige_automatiquement"

    # Toujours non conforme après correction → jamais publié automatiquement
    enqueue_moderation(art_corrige, rapport, rapport_final)
    _log(slug, "a_corriger_manuellement", {
        "problemes_initiaux": n_pb,
        "problemes_restants": len(rapport_final.get("problemes", [])),
    })
    return art_corrige, "a_corriger_manuellement"
