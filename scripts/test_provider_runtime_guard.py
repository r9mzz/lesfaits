"""Régression : configuration fournisseur atomique et modèle runtime cohérent."""
from provider_runtime_guard import validate_provider_env


def expect_ok(env):
    validate_provider_env(env)
    return env


def expect_fail(env):
    try:
        validate_provider_env(env)
    except RuntimeError as exc:
        assert "LLM_BASE_URL" in str(exc)
        assert "LLM_API_KEY" in str(exc)
        return
    raise AssertionError("configuration fournisseur partielle acceptée")


# Groq par défaut : aucune configuration fournisseur externe.
expect_ok({})
expect_ok({"LLM_BASE_URL": "", "LLM_API_KEY": ""})
expect_ok({"LLM_BASE_URL": "   ", "LLM_API_KEY": "   "})

# Fournisseur externe correctement configuré.
mistral = expect_ok({
    "LLM_BASE_URL": "https://api.mistral.ai/v1",
    "LLM_API_KEY": "secret",
    # Reproduit exactement le fallback injecté trop tôt par run_pipeline_v3.py.
    "GROQ_MODEL_OVERRIDE": "openai/gpt-oss-120b",
})
assert mistral["GROQ_MODEL_OVERRIDE"] == "mistral-large-latest", (
    "Le prévol doit remplacer le fallback Groq injecté par V3 quand la base est Mistral."
)

# Un override Mistral explicite reste prioritaire.
custom = expect_ok({
    "LLM_BASE_URL": "https://api.mistral.ai/v1",
    "LLM_API_KEY": "secret",
    "GROQ_MODEL_OVERRIDE": "mistral-medium-latest",
})
assert custom["GROQ_MODEL_OVERRIDE"] == "mistral-medium-latest"

# Base externe activée mais secret absent/vide.
expect_fail({"LLM_BASE_URL": "https://api.mistral.ai/v1"})
expect_fail({"LLM_BASE_URL": "https://api.mistral.ai/v1", "LLM_API_KEY": ""})
expect_fail({"LLM_BASE_URL": "https://api.mistral.ai/v1", "LLM_API_KEY": "   "})

# Défaut symétrique : une clé fournisseur seule remplace les clés Groq dans
# pipeline.py alors que l'URL reste Groq. Le prévol doit l'arrêter avant réseau.
expect_fail({"LLM_API_KEY": "secret"})
expect_fail({"LLM_BASE_URL": "", "LLM_API_KEY": "secret"})
expect_fail({"LLM_BASE_URL": "   ", "LLM_API_KEY": "secret"})

print("OK provider runtime guard")
