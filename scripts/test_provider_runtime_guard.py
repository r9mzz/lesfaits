"""Régression : une base LLM externe exige sa clé dédiée."""
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
    raise AssertionError("configuration incomplète acceptée")


# Groq par défaut : aucune base externe, aucune clé dédiée requise.
expect_ok({})
expect_ok({"LLM_BASE_URL": "", "LLM_API_KEY": ""})
expect_ok({"LLM_BASE_URL": "   ", "LLM_API_KEY": ""})

# Fournisseur externe correctement configuré.
expect_ok({"LLM_BASE_URL": "https://api.mistral.ai/v1", "LLM_API_KEY": "secret"})

# Le défaut observé : base externe activée mais secret absent/vide.
expect_fail({"LLM_BASE_URL": "https://api.mistral.ai/v1"})
expect_fail({"LLM_BASE_URL": "https://api.mistral.ai/v1", "LLM_API_KEY": ""})
expect_fail({"LLM_BASE_URL": "https://api.mistral.ai/v1", "LLM_API_KEY": "   "})

print("OK provider runtime guard")
