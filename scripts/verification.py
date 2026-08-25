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

# Une erreur HTTP 402 de vérification signifie que le compte/fournisseur ne
# permet pas l'appel (ex. abonnement Mistral absent). Le run du 25/08 a répété
# exactement le même 402 article après article. C'est une panne non transitoire
# pour le processus : après le premier constat, toutes les vérifications restent
# fail-closed mais aucun nouvel appel réseau voué à échouer n'est lancé.
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
    # Le moteur historique nomme encore toute erreur « Groq », même lorsque
    # GROQ_URL pointe vers Mistral. Corriger uniquement le libellé observable.
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

            # 402 = paiement/abonnement requis : changer de requête, attendre
            # ou retenter le même compte ne peut pas corriger la panne dans ce
            # processus. On la mémorise et on continue à refuser toute
            # publication non vérifiée via le garde fail-closed ci-dessous.
            if message.startswith("Groq 402:"):
                _PROVIDER_FATAL_ERROR = _normaliser_erreur_fournisseur(message)
                print(
                    "     [VERIF] fournisseur indisponible de façon permanente "
                    "pour ce processus (HTTP 402) — appels suivants bloqués"
                )
                raise RuntimeError(_PROVIDER_FATAL_ERROR) from exc

            if not (message.startswith("Groq 401:") or message.startswith("Groq 403:")):
                raise

            mortes = getattr(_verification, "_CLES_MORTES_JOUR", set())
            vivantes = [k for k in _verification.GROQ_KEYS if k not in mortes]
            if not vivantes:
                raise

            cle_invalide = vivantes[0]
            _verification.GROQ_KEYS = [
                k for k in _verification.GROQ_KEYS if k != cle_invalide
            ]
            print(
                "     [VERIF] clé refusée par authentification (401/403) — "
                "retirée de la rotation pour ce processus"
            )
            if not _verification.GROQ_KEYS:
                raise RuntimeError(
                    "Aucune clé de vérification valide après erreur d'authentification"
                ) from exc


_verification._llm_call = _provider_auth_rotating_llm_call

# La liste ``sources`` est l'espace d'adressage des citations [n] et reste
# strictement immuable pendant toutes les passes de correction.
_verification._provider_original_corriger = _verification.corriger


def _provider_sources_immutables_corriger(art: dict, *args, **kwargs):
    sources_originales = copy.deepcopy(art.get("sources", [])) if isinstance(art, dict) else []
    corrige = _verification._provider_original_corriger(art, *args, **kwargs)
    if isinstance(corrige, dict):
        corrige["sources"] = sources_originales
    return corrige


_verification.corriger = _provider_sources_immutables_corriger

# Si le fact-check n'a pas abouti, l'article ne peut pas être publié
# automatiquement.
_verification._provider_original_verifier_article = _verification.verifier_article


def _provider_fail_closed_verifier_article(*args, **kwargs):
    article, statut = _verification._provider_original_verifier_article(*args, **kwargs)
    if statut in {"erreur_verification", "non_verifie"}:
        slug = article.get("slug", "?") if isinstance(article, dict) else "?"
        print(
            f"     [REJET QUALITÉ] vérification indisponible ({statut}) — "
            "publication automatique interdite"
        )
        try:
            _verification._log(
                slug,
                "rejete_qualite",
                {
                    "raison": "verification_indisponible",
                    "statut_verification_initial": statut,
                },
            )
        except Exception:
            pass
        return article, "rejete_qualite"
    return article, statut


_verification.verifier_article = _provider_fail_closed_verifier_article


def _empreinte(k: str) -> str:
    return f"{k[:4]}…{k[-3:]} ({len(k)} car.)" if len(k) > 8 else "(vide ou trop courte)"


print(
    f"     [VERIF-AUTH] cible={_verification.GROQ_URL} · modèle={_MODEL} · "
    f"clés={len(_verification.GROQ_KEYS)} · "
    f"source={'LLM_API_KEY' if _LLM_KEY else 'GROQ_API_KEY*'} · "
    f"{_empreinte(_verification.GROQ_KEYS[0]) if _verification.GROQ_KEYS else 'AUCUNE'}",
    file=sys.stderr,
    flush=True,
)

# Important : renvoyer le vrai module historique, pas une copie de ses symboles.
sys.modules[__name__] = _verification
