# -*- coding: utf-8 -*-
"""Compatibilité fournisseur pour le fact-checker.

Le cœur historique reste dans ``verification_legacy.py``. Ce module applique
uniquement la même résolution fournisseur/modèle que ``pipeline.py`` puis
expose le module historique comme ``verification``. Ainsi les fonctions du
fact-checker gardent leurs globals et les patches runtime V3 continuent de
modifier le vrai ``PROMPT_DETECTION``.

Sécurité de publication : une vérification indisponible ne doit jamais être
interprétée comme un feu vert. Le moteur historique conservait un comportement
fail-open (``erreur_verification`` / ``non_verifie`` publiables). Le wrapper
fournisseur transforme désormais ces états en rejet qualité, sans modifier les
seuils éditoriaux ni le contenu de l'article.
"""
from __future__ import annotations

import os
import sys

import verification_legacy as _verification

# Le défaut suit le fournisseur : un nom de modèle Groq envoyé à Mistral produit
# un 404 sur chaque vérification, donc zéro article publié — la panne exacte des
# 15-17/08, dans l'autre sens.
_BASE_POUR_DEFAUT = os.getenv("LLM_BASE_URL", "")
_MODEL = (os.getenv("GROQ_MODEL_OVERRIDE", "").strip()
          or ("mistral-large-latest" if "mistral.ai" in _BASE_POUR_DEFAUT
              else "openai/gpt-oss-120b"))
_BASE_URL = os.getenv("LLM_BASE_URL", "").strip()
_LLM_KEY = os.getenv("LLM_API_KEY", "").strip()

_verification.GROQ_MODEL = _MODEL
if _LLM_KEY:
    _verification.GROQ_KEYS = [_LLM_KEY]

if _BASE_URL:
    _verification.GROQ_URL = _BASE_URL.rstrip("/") + "/chat/completions"
else:
    _verification.GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# Le run du 19/08 a montré une asymétrie réelle entre génération et
# vérification : la génération savait continuer avec une autre clé Groq, mais le
# fact-checker historique levait immédiatement sur le premier 401/403. Une seule
# clé révoquée en tête de liste rendait donc TOUTE vérification indisponible,
# même lorsque des clés suivantes restaient valides. On conserve le fail-closed
# si aucune clé ne fonctionne, mais on écarte désormais seulement la clé dont
# l'authentification a réellement échoué puis on réessaie avec la suivante.
_verification._provider_original_llm_call = _verification._llm_call


def _provider_auth_rotating_llm_call(*args, **kwargs):
    while True:
        try:
            return _verification._provider_original_llm_call(*args, **kwargs)
        except RuntimeError as exc:
            message = str(exc)
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

# Le moteur historique publiait explicitement en cas d'échec API de détection
# (et pouvait aussi publier après une erreur de correction si aucun bloquant
# n'était encore connu). Avec un fournisseur invalide, le run du 19/08 a produit
# une série de 401 tout en journalisant « publié sans vérification ». La règle de
# sécurité est désormais simple : si le fact-check n'a pas abouti, l'article ne
# peut pas être publié automatiquement.
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
            # La journalisation ne doit jamais transformer un rejet sûr en
            # nouvelle erreur de runtime.
            pass
        return article, "rejete_qualite"
    return article, statut


_verification.verifier_article = _provider_fail_closed_verifier_article

# ── DIAGNOSTIC D'AUTHENTIFICATION (19/08) ─────────────────────────────────
# Le run de 23h22 a généré 32 articles avec Mistral puis les a TOUS perdus sur
# « Groq 401: {"detail":"Invalid API Key"} » au fact-check. Le format `detail`
# est celui de Mistral : la requête arrivait donc bien chez lui, avec une clé
# qu'il refusait — alors que la génération, qui lit la MÊME variable, passait.
#
# Sans savoir quelle clé part réellement, on ne peut que supposer, et le
# protocole refuse de publier sans vérification : 32 articles écrits, zéro
# publié. Cette ligne dit la provenance et l'empreinte de la clé, jamais la clé.
def _empreinte(k: str) -> str:
    return f"{k[:4]}…{k[-3:]} ({len(k)} car.)" if len(k) > 8 else "(vide ou trop courte)"


print(f"     [VERIF-AUTH] cible={_verification.GROQ_URL} · modèle={_MODEL} · "
      f"clés={len(_verification.GROQ_KEYS)} · "
      f"source={'LLM_API_KEY' if _LLM_KEY else 'GROQ_API_KEY*'} · "
      f"{_empreinte(_verification.GROQ_KEYS[0]) if _verification.GROQ_KEYS else 'AUCUNE'}",
      flush=True)

# Important : renvoyer le vrai module historique, pas une copie de ses symboles.
# Les fonctions importées conservent ainsi leurs globals, et
# run_pipeline_v3._patch_verification_evidence_scope() modifie bien le prompt
# réellement utilisé par detecter().
sys.modules[__name__] = _verification
