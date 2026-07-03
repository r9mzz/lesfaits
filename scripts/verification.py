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

PROMPT_DETECTION = """Tu es un fact-checker indépendant et rigoureux pour Les Faits. Analyse l'article ci-dessous par rapport à sa liste de sources autorisées, selon la charte "Critères Premium" ci-dessous. Sois exhaustif : ton rôle est de trouver TOUS les problèmes, pas de donner le bénéfice du doute.

Chaque type de problème appartient à un bloc. Le bloc détermine si l'article peut être corrigé automatiquement ou doit partir en relecture humaine — indique-le pour chaque problème via le champ "bloc".

BLOC 1 — FACTUEL (zéro tolérance) :
- chiffre_errone : un chiffre/statistique/date ne correspond pas exactement à ce que dit la source citée (pas d'arrondi ni d'extrapolation non signalée)
- chronologie_confuse : un événement antérieur/historique est mentionné sans que sa date et son rapport avec l'événement du jour soient explicites (deux époques mélangées implicitement)
- incoherence_inter_sections : une même affirmation présentée différemment dans deux sections du même article
- fait_tranche_arbitrairement : un fait incertain ou contesté présenté comme définitivement établi

BLOC 2 — SOURCING (100% vérifiable) :
- source_inventee : tout nom de média, expert, institution, étude cité dans le texte qui n'apparaît pas dans les sources autorisées
- formule_vague : "selon les experts", "des études montrent", "selon les sources", "il est établi" sans référence précise à une source de la liste
- source_non_editoriale : une source non-journalistique/non-institutionnelle (ex : un outil de traduction, un dictionnaire) citée comme autorité factuelle
- source_derivee_comptee_comme_primaire : plusieurs sources listées qui ne font que recopier la même dépêche/communiqué sans apporter d'info distincte, comptées comme des sources indépendantes alors qu'elles ne le sont pas

BLOC 3 — ORIGINALITÉ (zéro plagiat déguisé) :
- paraphrase_structurelle : une phrase reprend la structure et l'essentiel du vocabulaire d'une source sans guillemets (changer un adverbe n'est pas une reformulation)
- citation_non_attribuee : une citation directe non entre guillemets ou non attribuée nommément
- cadrage_emprunte : un jugement de valeur ou un cadrage editorial d'une source (ex: "modèle patriarcal", "crise sans précédent") présenté comme un fait neutre par Les Faits au lieu d'être attribué explicitement ("selon X") ou reformulé factuellement

BLOC 4 — RÉDACTION (zéro remplissage) :
- redondance : toute phrase de "contexte" ou "nuances" qui répète, même reformulée, une idée déjà présente dans "faits" ou ailleurs dans l'article
- section_gonflee : "contexte" ou "nuances" rempli avec du vague générique ("il est difficile de prévoir les conséquences") au lieu d'un fait distinct sourcé, ou alors que la section n'apporte rien et devrait être coupée
- faux_debat : "positions des acteurs" ou "nuances" présente un désaccord qui n'est pas réel/symétrique (ex : appliqué à une sanction, une décision de justice, un acte institutionnel unilatéral qui n'a qu'un seul camp)
- jugement_de_valeur : tout adjectif, adverbe ou tournure qui trahit une opinion plutôt qu'un fait neutre
- extrapolation : toute anticipation de conséquence future non explicitement sourcée
- compteur_incoherent : le champ "nb_sources" ne correspond pas au nombre réel de sources distinctes effectivement utilisées

BLOC 5 — LÉGAL (toujours grave, jamais corrigeable automatiquement) :
- presomption_innocence : une personne appelée "coupable"/"l'assassin"/"le violeur" avant condamnation définitive, au lieu de "mis en examen", "soupçonné", "présumé", "poursuivi pour"
- affaire_en_cours_presentee_comme_fait : une affaire judiciaire en cours présentée comme un fait établi au lieu d'être attribuée à l'accusation/aux enquêteurs ou mise au conditionnel
- diffamation_potentielle : une affirmation négative sur une personne identifiée nommément qui n'est pas strictement sourcée et vérifiable
- mineur_identifie : un mineur impliqué dans une affaire pénale (victime ou mis en cause) identifié par nom, photo ou établissement

Pour CHAQUE problème trouvé, cite la phrase exacte concernée (mot pour mot, copiée depuis l'article) et précise dans quelle section elle se trouve.

Réponds en JSON strict, sans texte hors JSON :
{
  "conforme": true/false,
  "problemes": [
    {
      "bloc": 1-5,
      "section": "faits | contexte | nuances | resume | titre | positions",
      "type": "chiffre_errone | chronologie_confuse | incoherence_inter_sections | fait_tranche_arbitrairement | source_inventee | formule_vague | source_non_editoriale | source_derivee_comptee_comme_primaire | paraphrase_structurelle | citation_non_attribuee | cadrage_emprunte | redondance | section_gonflee | faux_debat | jugement_de_valeur | extrapolation | compteur_incoherent | presomption_innocence | affaire_en_cours_presentee_comme_fait | diffamation_potentielle | mineur_identifie",
      "phrase_exacte": "citation mot pour mot de l'article",
      "explication": "pourquoi c'est un problème, en une phrase"
    }
  ]
}

ARTICLE :
{ARTICLE_JSON}

SOURCES AUTORISÉES :
{SOURCES}"""

PROMPT_CORRECTION = """Tu es un correcteur pour Les Faits. Voici un article et un rapport précis de ses défauts. Ta mission : produire une version corrigée qui règle CHAQUE problème listé, sans en introduire de nouveaux — et qui reste un article dense et substantiel, PAS un résumé squelettique.

RÈGLES DE CORRECTION :
- Pour un "chiffre_errone" : corrige le chiffre pour qu'il corresponde exactement à la source citée.
- Pour une "chronologie_confuse" : ajoute la date de l'événement historique et une formule explicite de distinction ("en 2001, soit 25 ans plus tôt...").
- Pour une "incoherence_inter_sections" : harmonise les deux sections sur la version la plus précisément sourcée.
- Pour un "fait_tranche_arbitrairement" : reformule pour indiquer explicitement l'incertitude ou la controverse ("selon X, non confirmé par Y").
- Pour une "source_inventee" : supprime la phrase ou le passage concerné, SAUF si l'information peut être reformulée en te basant uniquement sur les sources autorisées — dans ce cas, réécris-la en l'attribuant correctement.
- Pour une "formule_vague" : soit tu la relies à une source précise de la liste, soit tu la supprimes.
- Pour une "source_non_editoriale" : supprime la référence à cette source comme autorité factuelle ; garde l'info seulement si une autre source de la liste, éditoriale ou institutionnelle, l'atteste aussi.
- Pour une "source_derivee_comptee_comme_primaire" : corrige "nb_sources" pour ne compter qu'une fois les sources qui recopient la même dépêche.
- Pour une "paraphrase_structurelle" : réécris entièrement la phrase avec une structure et un vocabulaire différents, ou mets la formulation source entre guillemets avec attribution.
- Pour une "citation_non_attribuee" : ajoute les guillemets et l'attribution nommée, ou reformule en discours indirect factuel.
- Pour un "cadrage_emprunte" : attribue explicitement le jugement à sa source ("selon X") ou reformule en langage factuel neutre.
- Pour une "redondance" : NE SUPPRIME PAS SIMPLEMENT LA PHRASE. Remplace-la par un fait DISTINCT tiré des mêmes sources autorisées, encore inutilisé dans l'article — un chiffre précis, une date, un autre acteur cité, une méthodologie, une réaction, une comparaison historique ou géographique, une conséquence concrète. Les sources contiennent presque toujours plus de matière que ce qui a été extrait au premier passage ; relis-les intégralement pour trouver cet angle neuf. Supprimer purement et simplement n'est acceptable QUE si tu as vérifié qu'aucun fait distinct exploitable ne reste dans les sources.
- Pour une "section_gonflee" : si un fait distinct sourcé existe encore, utilise-le ; sinon, coupe la section plutôt que de la laisser vague.
- Pour un "faux_debat" : supprime le cadrage pour/contre et remplace par une présentation factuelle de la décision/sanction, ou indique explicitement qu'il n'y a pas de désaccord réel.
- Pour un "jugement_de_valeur" : reformule en langage neutre et factuel, sans réduire la longueur.
- Pour une "extrapolation" : supprime, sauf si tu peux l'attribuer explicitement à une source qui l'exprime.
- Pour un "compteur_incoherent" : recompte et corrige le champ "nb_sources" pour qu'il reflète exactement la réalité du texte corrigé.

Objectif de longueur : chaque section corrigée (faits/contexte/nuances) doit rester proche de sa longueur originale (± 15 %), sauf si les sources sont réellement épuisées de tout fait distinct. Un article de presse a plusieurs paragraphes par section, pas une phrase unique — la richesse vient de la variété des faits cités, jamais de leur répétition.

Ne modifie AUCUNE partie de l'article qui n'est pas mentionnée dans le rapport de problèmes. Ne réécris pas le style au-delà de ce qui est nécessaire pour corriger les problèmes signalés.

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

    # Bloc 5 (légal) : jamais de correction automatique, toujours modération
    # humaine — présomption d'innocence, mineurs, diffamation ne se "corrigent"
    # pas par un patch de texte, ils exigent une décision éditoriale humaine.
    problemes_bloc5 = [p for p in rapport.get("problemes", []) if p.get("bloc") == 5]
    if problemes_bloc5:
        print(f"     [MODÉRATION] {len(problemes_bloc5)} problème(s) légal(aux) (bloc 5) — "
              f"jamais de correction automatique, mis en file")
        enqueue_moderation(art, rapport, {})
        _log(slug, "a_corriger_manuellement", {
            "problemes_initiaux": n_pb,
            "bloc5": [p.get("type") for p in problemes_bloc5],
        })
        return art, "a_corriger_manuellement"

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
