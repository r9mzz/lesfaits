"""Régression : configuration fournisseur atomique et modèle runtime cohérent."""
from provider_runtime_guard import validate_provider_access, validate_provider_env


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


class FakeResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


def fake_post_from(statuses, calls):
    remaining = iter(statuses)

    def post(url, **kwargs):
        calls.append((url, kwargs))
        status = next(remaining)
        return FakeResponse(status, f"status={status}")

    return post


# Régression run #297 : une clé 402 puis des clés 403 tier_not_allowed ne doit
# plus faire tenter des dizaines de sujets. Si TOUTES les clés ont une panne
# permanente, le run échoue avant la collecte.
env_permanent = {
    "LLM_BASE_URL": "https://api.mistral.ai/v1",
    "LLM_API_KEY": "key1",
    "LLM_API_KEY_2": "key2",
    "LLM_API_KEY_3": "key3",
    "GROQ_MODEL_OVERRIDE": "mistral-large-latest",
}
calls = []
try:
    validate_provider_access(env_permanent, post=fake_post_from([402, 403, 403], calls))
except RuntimeError as exc:
    message = str(exc)
    assert "mistral-large-latest" in message
    assert "402" in message and "403" in message
    assert "avant collecte" in message
else:
    raise AssertionError("trois refus permanents fournisseur n'ont pas arrêté le prévol")
assert len(calls) == 3
assert all(call[1]["json"]["model"] == "mistral-large-latest" for call in calls)

# Une clé refusée n'interdit pas le run si une autre clé a réellement accès.
calls = []
validate_provider_access(env_permanent, post=fake_post_from([403, 200], calls))
assert len(calls) == 2

# Un incident transitoire ne doit pas être transformé en panne permanente :
# le pipeline possède déjà ses retries pour 429/5xx/réseau.
calls = []
validate_provider_access(env_permanent, post=fake_post_from([503, 403, 403], calls))
assert len(calls) == 3

print("OK provider runtime guard")
