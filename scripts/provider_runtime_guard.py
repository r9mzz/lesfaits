"""Validation minimale de la configuration du fournisseur LLM.

Le runtime ne doit jamais mélanger les identifiants Groq et ceux d'un
fournisseur externe. ``LLM_BASE_URL`` et ``LLM_API_KEY`` forment donc une
configuration atomique : soit les deux sont absents (Groq par défaut), soit
les deux sont présents.
"""
from __future__ import annotations

import os


def validate_provider_env(env: dict[str, str] | None = None) -> None:
    """Refuse toute configuration fournisseur externe partielle."""
    values = os.environ if env is None else env
    base_url = str(values.get("LLM_BASE_URL", "") or "").strip()
    api_key = str(values.get("LLM_API_KEY", "") or "").strip()
    if bool(base_url) == bool(api_key):
        return
    if base_url:
        detail = "LLM_BASE_URL est défini mais LLM_API_KEY est vide"
    else:
        detail = "LLM_API_KEY est défini mais LLM_BASE_URL est vide"
    raise RuntimeError(
        "Configuration fournisseur incomplète : " + detail
        + ". Les deux variables doivent être définies ensemble ou laissées vides. "
        "Refus avant tout appel réseau."
    )
