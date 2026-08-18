"""Validation minimale de la configuration du fournisseur LLM.

Le runtime ne doit jamais envoyer une clé Groq vers une base API externe par
accident. Une base personnalisée n'est donc valide que si sa clé dédiée est
présente et non vide.
"""
from __future__ import annotations

import os


def validate_provider_env(env: dict[str, str] | None = None) -> None:
    """Refuse une base LLM externe sans clé fournisseur dédiée."""
    values = os.environ if env is None else env
    base_url = str(values.get("LLM_BASE_URL", "") or "").strip()
    api_key = str(values.get("LLM_API_KEY", "") or "").strip()
    if base_url and not api_key:
        raise RuntimeError(
            "Configuration fournisseur incomplète : LLM_BASE_URL est défini "
            "mais LLM_API_KEY est vide. Refus avant tout appel réseau."
        )
