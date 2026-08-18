"""Validation minimale de la configuration du fournisseur LLM.

Le runtime ne doit jamais mélanger les identifiants Groq et ceux d'un
fournisseur externe. ``LLM_BASE_URL`` et ``LLM_API_KEY`` forment donc une
configuration atomique : soit les deux sont absents (Groq par défaut), soit
les deux sont présents.

Le runner V3 historique résout encore son fallback Groq avant d'appeler ce
prévol. Quand une base Mistral est configurée sans override explicite utile,
il peut donc arriver ici avec ``openai/gpt-oss-120b`` déjà injecté. Ce nom
n'existe pas chez Mistral : on le remplace par le défaut Mistral canonique
avant tout import du pipeline. Un override Mistral explicite est conservé.
"""
from __future__ import annotations

import os


_GROQ_RUNTIME_DEFAULT = "openai/gpt-oss-120b"
_MISTRAL_RUNTIME_DEFAULT = "mistral-large-latest"


def validate_provider_env(env: dict[str, str] | None = None) -> None:
    """Refuse une configuration partielle et aligne le fallback au fournisseur."""
    values = os.environ if env is None else env
    base_url = str(values.get("LLM_BASE_URL", "") or "").strip()
    api_key = str(values.get("LLM_API_KEY", "") or "").strip()
    if bool(base_url) != bool(api_key):
        if base_url:
            detail = "LLM_BASE_URL est défini mais LLM_API_KEY est vide"
        else:
            detail = "LLM_API_KEY est défini mais LLM_BASE_URL est vide"
        raise RuntimeError(
            "Configuration fournisseur incomplète : " + detail
            + ". Les deux variables doivent être définies ensemble ou laissées vides. "
            "Refus avant tout appel réseau."
        )

    if base_url and "mistral.ai" in base_url.lower():
        model = str(values.get("GROQ_MODEL_OVERRIDE", "") or "").strip()
        if not model or model == _GROQ_RUNTIME_DEFAULT:
            values["GROQ_MODEL_OVERRIDE"] = _MISTRAL_RUNTIME_DEFAULT
