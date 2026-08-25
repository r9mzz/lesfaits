# -*- coding: utf-8 -*-
"""Résolution du modèle, partagée génération / vérification.

⚠ TROISIÈME BUG DE LA MÊME FAMILLE. Le 19/08, la génération et le fact-check
lisaient deux listes de CLÉS différentes → 401 silencieux, 32 articles générés,
zéro publié. Corrigé par `cles_fournisseur`. Le 24/08, ils lisent deux MODÈLES
différents pour la même raison : chacun résout dans son coin.

Ce que le run 273 montrait :

    run_pipeline_v3.py force GROQ_MODEL_OVERRIDE = "openai/gpt-oss-120b"
    …avant l'import de pipeline, et LLM_BASE_URL pointe sur api.mistral.ai

Un nom de modèle GROQ envoyé à l'API MISTRAL. Ce garde-fou datait du 16/08,
quand Groq a retiré llama-3.3-70b : il était juste à ce moment-là, et il est
devenu faux au changement de fournisseur sans que rien ne le signale — comme
la table des fenêtres, comme les 11 clés, comme le ratio caractères/token.

Règle qui en sort : **un défaut propre à un fournisseur ne doit s'appliquer que
si c'est ce fournisseur qui sert.** D'où `est_mistral()`, testé plutôt que
supposé.
"""
from __future__ import annotations

import os

# Modèles par défaut, PAR FOURNISSEUR. Un nom de modèle n'est jamais portable :
# c'est la leçon du 16/08 (Groq retire un modèle) rejouée à l'envers.
MODELE_REDACTION_MISTRAL = "mistral-large-latest"
MODELE_REDACTION_GROQ = "openai/gpt-oss-120b"


def _fournisseur(env: dict | None = None) -> str:
    """Nom du fournisseur qui SERT, lu sur l'URL. Jamais supposé."""
    base = ((env or os.environ).get("LLM_BASE_URL", "") or "").lower()
    if not base:
        return "groq"
    if "mistral.ai" in base:
        return "mistral"
    if "googleapis.com" in base or "generativelanguage" in base:
        return "gemini"
    return "inconnu"


def est_mistral(env: dict | None = None) -> bool:
    """Le fournisseur qui sert est-il Mistral ? Lu sur l'URL, jamais supposé."""
    return _fournisseur(env) == "mistral"


def modele_redaction(env: dict | None = None) -> str:
    """Modèle de rédaction ET de fact-check — une seule source de vérité.

    `GROQ_MODEL_OVERRIDE` reste prioritaire : c'est le levier d'essai A/B
    branché le 17/08, et le retirer empêcherait de tester un modèle sans
    engager la production. Mais il ne sert plus de VALEUR PAR DÉFAUT — un
    défaut doit suivre le fournisseur.
    """
    lire = (env or os.environ).get
    choix = (lire("GROQ_MODEL_OVERRIDE", "") or "").strip()
    if choix:
        return choix

    fournisseur = _fournisseur(env)
    if fournisseur == "mistral":
        return MODELE_REDACTION_MISTRAL
    if fournisseur == "groq":
        return MODELE_REDACTION_GROQ

    # ── 25/08 : un fournisseur INCONNU ne doit pas recevoir un nom Groq ─────
    # L'essai Gemini l'a montré : `[VERIF-AUTH] modèle=openai/gpt-oss-120b` sur
    # une base Google. La génération marchait (essai_fournisseur patche
    # `pipeline.GROQ_MODEL` après l'import) mais la VÉRIFICATION serait partie
    # avec un nom Groq — donc un 404 sur chaque article, et un run entier
    # perdu à croire que le fournisseur écrit mal.
    #
    # C'est la 4e occurrence de « un défaut propre à un fournisseur survit au
    # changement de fournisseur ». On ne devine plus : hors Groq et Mistral, le
    # modèle doit être NOMMÉ explicitement (GROQ_MODEL_OVERRIDE, ou l'entrée
    # `modele` des workflows d'essai). Lever ici est volontaire — un nom
    # silencieusement faux coûte un run, une exception coûte une seconde.
    raise RuntimeError(
        f"Fournisseur non reconnu ({lire('LLM_BASE_URL', '')!r}) : aucun modèle "
        "par défaut ne peut être deviné. Nommer le modèle via "
        "GROQ_MODEL_OVERRIDE (ou l'entrée `modele` du workflow)."
    )
