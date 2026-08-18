# -*- coding: utf-8 -*-
"""Compatibilité fournisseur pour le fact-checker.

Le cœur historique reste dans ``verification_legacy.py``. Ce module applique
uniquement la même résolution fournisseur/modèle que ``pipeline.py`` puis
expose le module historique comme ``verification``. Ainsi les fonctions du
fact-checker gardent leurs globals et les patches runtime V3 continuent de
modifier le vrai ``PROMPT_DETECTION``.
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

# Important : renvoyer le vrai module historique, pas une copie de ses symboles.
# Les fonctions importées conservent ainsi leurs globals, et
# run_pipeline_v3._patch_verification_evidence_scope() modifie bien le prompt
# réellement utilisé par detecter().
sys.modules[__name__] = _verification
