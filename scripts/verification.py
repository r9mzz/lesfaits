# -*- coding: utf-8 -*-
"""Compatibilité fournisseur pour le fact-checker.

Le cœur historique reste dans ``verification_legacy.py``. Ce module applique
uniquement la même résolution fournisseur/modèle que ``pipeline.py`` puis
expose le module historique comme ``verification``. Ainsi les fonctions du
fact-checker gardent leurs globals et les patches runtime V3 continuent de
modifier le vrai ``PROMPT_DETECTION``.

Sécurité de publication : une vérification indisponible ne doit jamais être
interprétée comme un feu vert. Le wrapper fournisseur transforme les états
``erreur_verification`` / ``non_verifie`` en rejet qualité, sans modifier les
seuils éditoriaux ni le contenu de l'article.
"""
from __future__ import annotations

import copy
import os
import re
import sys

import verification_legacy as _verification
from cles_fournisseur import cles_fournisseur
from modele_fournisseur import modele_redaction

_BASE_POUR_DEFAUT = os.getenv("LLM_BASE_URL", "")
_MODEL = modele_redaction()
_BASE_URL = os.getenv("LLM_BASE_URL", "").strip()
_LLM_KEYS = cles_fournisseur()
_LLM_KEY = _LLM_KEYS[0] if _LLM_KEYS else ""

_verification.GROQ_MODEL = _MODEL
if _LLM_KEYS:
    _verification.GROQ_KEYS = list(_LLM_KEYS)

if _BASE_URL:
    _verification.GROQ_URL = _BASE_URL.rstrip("/") + "/chat/completions"
else:
    _verification.GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

_RETROSPECTIVE_SOURCE_RULE = """
⚠ CHRONOLOGIE DES SOURCES — une source publiée APRÈS un événement peut parfaitement le décrire rétrospectivement. La seule différence entre la date de publication de la source et la date de l'événement n'est JAMAIS, à elle seule, un motif ``annonce_perimee`` ou ``chronologie_confuse``. Signale ``annonce_perimee`` uniquement si le TEXTE DE L'ARTICLE présente comme futur, actuel ou définitif un état que les extraits fournis établissent explicitement comme déjà survenu, terminé, dépassé ou provisoire. Ne déduis jamais qu'une source « ne peut pas décrire » un événement antérieur simplement parce qu'elle a été publiée plus tard.
""".strip()
if _RETROSPECTIVE_SOURCE_RULE not in _verification.PROMPT_DETECTION:
    _verification.PROMPT_DETECTION += "\n\n" + _RETROSPECTIVE_SOURCE_RULE

_FUTURE_PROJECTION_RULE = """
⚠ PROJECTIONS ET FUTUR RÉEL — le simple emploi du futur, du conditionnel ou d'un verbe comme « prévoit », « projette », « envisage » n'est JAMAIS en soi un motif ``annonce_perimee``. Si les extraits décrivent réellement une prévision, un scénario, une échéance ou un événement encore futur à la date de l'article, l'article DOIT pouvoir le présenter comme futur. La date de publication d'une prévision antérieure à l'échéance confirme au contraire qu'il s'agit d'une projection ; elle ne la rend pas périmée. N'utilise ``annonce_perimee`` que lorsqu'un extrait plus récent établit explicitement que l'événement annoncé a déjà eu lieu, a été annulé, a changé d'état ou que la formulation temporelle de l'article contredit l'état le plus récent fourni. Ne transforme jamais une simple différence de temps grammatical en contradiction chronologique.
""".strip()
if _FUTURE_PROJECTION_RULE not in _verification.PROMPT_DETECTION:
    _verification.PROMPT_DETECTION += "\n\n" + _FUTURE_PROJECTION_RULE

_verification._provider_original_llm_call = _verification._llm_call
_PROVIDER_FATAL_ERROR = None


def _provider_name() -> str:
    base = _BASE_URL.lower()
    if "mistral" in base:
        return "Mistral"
    if base:
        return "Fournisseur LLM"
    return "Groq"


def _normaliser_erreur_fournisseur(message: str) -> str:
    if _BASE_URL and message.startswith("Groq "):
        return _provider_name() + message[len("Groq"):]
    return message


def _provider_auth_rotating_llm_call(*args, **kwargs):
    global _PROVIDER_FATAL_ERROR
    if _PROVIDER_FATAL_ERROR is not None:
        raise RuntimeError(_PROVIDER_FATAL_ERROR)
    while True:
        try:
            return _verification._provider_original_llm_call(*args, **kwargs)
        except RuntimeError as exc:
            message = str(exc)
            if message.startswith("Groq 402:"):
                _PROVIDER_FATAL_ERROR = _normaliser_erreur_fournisseur(message)
                print("     [VERIF] fournisseur indisponible de façon permanente pour ce processus (HTTP 402) — appels suivants bloqués")
                raise RuntimeError(_PROVIDER_FATAL_ERROR) from exc
            if not (message.startswith("Groq 401:") or message.startswith("Groq 403:")):
                raise
            mortes = getattr(_verification, "_CLES_MORTES_JOUR", set())
            vivantes = [k for k in _verification.GROQ_KEYS if k not in mortes]
            if not vivantes:
                raise
            cle_invalide = vivantes[0]
            _verification.GROQ_KEYS = [k for k in _verification.GROQ_KEYS if k != cle_invalide]
            print("     [VERIF] clé refusée par authentification (401/403) — retirée de la rotation pour ce processus")
            if not _verification.GROQ_KEYS:
                raise RuntimeError("Aucune clé de vérification valide après erreur d'authentification") from exc


_verification._llm_call = _provider_auth_rotating_llm_call

_verification._provider_original_corriger = _verification.corriger


def _provider_sources_immutables_corriger(art: dict, *args, **kwargs):
    sources_originales = copy.deepcopy(art.get("sources", [])) if isinstance(art, dict) else []
    corrige = _verification._provider_original_corriger(art, *args, **kwargs)
    if isinstance(corrige, dict):
        corrige["sources"] = sources_originales
    return corrige


_verification.corriger = _provider_sources_immutables_corriger

_SOURCE_ABSENCE_RE = re.compile(
    r"(?:la\s+)?source\s*\[?\d+\]?[^.]{0,180}(?:ne\s+(?:pr[ée]cise|mentionne|d[ée]taille|fournit|donne|indique)\s+pas|n['’](?:indique|apporte)\s+pas)",
    re.IGNORECASE,
)
_ARTICLE_OMISSION_RE = re.compile(
    r"(?:l['’]article|la\s+phrase)[^.]{0,220}(?:ne\s+(?:pr[ée]cise|mentionne|int[èe]gre|d[ée]taille|fournit|donne)\s+pas|omet)",
    re.IGNORECASE,
)
_PREUVE_RENFORCEE_RE = re.compile(
    r"efficacit[ée]|survie|comparateur|phase\s*[123]|pr[ée]clinique|comme\s+(?:un\s+)?(?:fait|r[ée]sultat)\s+(?:acquis|[ée]tabli)|pr[ée]sente[^.]{0,80}(?:comme\s+[ée]tabli|comme\s+acquis)",
    re.IGNORECASE,
)
_RESERVE_DEJA_PRESENTE_RE = re.compile(
    r"d[ée]j[àa]\s+(?:mentionn[ée]e?s?|pr[ée]cis[ée]e?s?|indiqu[ée]e?s?|pr[ée]sent[ée]e?s?|int[ée]gr[ée]e?s?)[^.]{0,140}(?:faits|nuances|article|autre\s+section)",
    re.IGNORECASE,
)
_DEMANDE_REPETITION_RESUME_RE = re.compile(
    r"(?:le\s+)?r[ée]sum[ée][^.]{0,100}\bdoit\b[^.]{0,100}(?:rappeler|reprendre|mentionner|r[ée]p[ée]ter)",
    re.IGNORECASE,
)


def _provider_reproche_exige_source_absente(probleme: dict) -> bool:
    if str(probleme.get("type") or "") != "niveau_preuve_insuffisant":
        return False
    description = str(probleme.get("description") or "")
    if not (_SOURCE_ABSENCE_RE.search(description) and _ARTICLE_OMISSION_RE.search(description)):
        return False
    if _PREUVE_RENFORCEE_RE.search(description):
        return False
    print("     [JUGE] reproche écarté — le rapport exige une limite qu'il déclare lui-même absente de la source (règle de symétrie)")
    return True


def _provider_reproche_exige_repetition(probleme: dict) -> bool:
    """Écarte uniquement un reproche qui reconnaît la réserve déjà présente
    puis exige explicitement sa répétition dans le résumé.

    La règle est volontairement étroite : une vraie omission, une suraffirmation
    ou un simple reproche sans aveu de présence ailleurs reste bloquant.
    """
    if str(probleme.get("type") or "") != "niveau_preuve_insuffisant":
        return False
    description = str(probleme.get("description") or "")
    if not (_RESERVE_DEJA_PRESENTE_RE.search(description) and _DEMANDE_REPETITION_RESUME_RE.search(description)):
        return False
    print("     [JUGE] reproche écarté — le rapport reconnaît la réserve déjà présente puis exige sa répétition dans le résumé")
    return True


_verification._reproche_exige_source_absente = _provider_reproche_exige_source_absente
_verification._reproche_exige_repetition = _provider_reproche_exige_repetition
if hasattr(_verification, "_problemes_bloquants"):
    _verification._provider_original_problemes_bloquants = _verification._problemes_bloquants

    def _provider_problemes_bloquants(problemes: list) -> list:
        retenus = _verification._provider_original_problemes_bloquants(problemes)
        return [
            p for p in retenus
            if not _provider_reproche_exige_source_absente(p)
            and not _provider_reproche_exige_repetition(p)
        ]

    _verification._problemes_bloquants = _provider_problemes_bloquants

_verification._provider_original_verifier_article = _verification.verifier_article


def _provider_fail_closed_verifier_article(*args, **kwargs):
    article, statut = _verification._provider_original_verifier_article(*args, **kwargs)
    if statut in {"erreur_verification", "non_verifie"}:
        slug = article.get("slug", "?") if isinstance(article, dict) else "?"
        print(f"     [REJET QUALITÉ] vérification indisponible ({statut}) — publication automatique interdite")
        try:
            _verification._log(slug, "rejete_qualite", {"raison": "verification_indisponible", "statut_verification_initial": statut})
        except Exception:
            pass
        return article, "rejete_qualite"
    return article, statut


_verification.verifier_article = _provider_fail_closed_verifier_article


def _empreinte(k: str) -> str:
    return f"{k[:4]}…{k[-3:]} ({len(k)} car.)" if len(k) > 8 else "(vide ou trop courte)"


print(
    f"     [VERIF-AUTH] cible={_verification.GROQ_URL} · modèle={_MODEL} · clés={len(_verification.GROQ_KEYS)} · source={'LLM_API_KEY' if _LLM_KEY else 'GROQ_API_KEY*'} · {_empreinte(_verification.GROQ_KEYS[0]) if _verification.GROQ_KEYS else 'AUCUNE'}",
    file=sys.stderr,
    flush=True,
)

sys.modules[__name__] = _verification
