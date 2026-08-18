"""Régression : base et clé LLM externes doivent être configurées ensemble."""
from provider_runtime_guard import validate_provider_env


def expect_ok(env):
    validate_provider_env(env)


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
expect_ok({"LLM_BASE_URL": "https://api.mistral.ai/v1", "LLM_API_KEY": "secret"})

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
