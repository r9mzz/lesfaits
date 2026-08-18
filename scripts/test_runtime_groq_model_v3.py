# -*- coding: utf-8 -*-
"""Régression : les modèles Groq réellement utilisés par V3 doivent rester servis et cohérents."""
from pathlib import Path


HERE = Path(__file__).resolve().parent
RUNTIME = HERE / "run_pipeline_v3.py"
PIPELINE = HERE / "pipeline.py"


def main() -> None:
    runtime = RUNTIME.read_text(encoding="utf-8")
    pipeline = PIPELINE.read_text(encoding="utf-8")

    empty_guard = 'if not os.environ.get("GROQ_MODEL_OVERRIDE", "").strip():'
    assignment = 'os.environ["GROQ_MODEL_OVERRIDE"] = "openai/gpt-oss-120b"'
    legacy_import = "import run_pipeline as legacy"

    assert empty_guard in runtime, (
        "Le runtime V3 doit traiter une variable GROQ_MODEL_OVERRIDE présente mais vide comme absente."
    )
    assert assignment in runtime, "Le runtime V3 ne force pas le remplaçant Groq de production."
    assert legacy_import in runtime, "Import run_pipeline introuvable dans le runtime V3."
    assert runtime.index(empty_guard) < runtime.index(assignment) < runtime.index(legacy_import), (
        "Le modèle doit être résolu, y compris si l'override est vide, AVANT l'import/exécution du pipeline historique."
    )
    assert 'os.environ.setdefault("GROQ_MODEL_OVERRIDE"' not in runtime, (
        "setdefault laisse intacte une variable d'environnement présente mais vide et réactive le modèle retiré."
    )
    assert '"test_runtime_groq_model_v3.py"' in runtime, (
        "Le test du modèle Groq doit être rejoué par le prévol runtime V3."
    )

    assert 'JUGE_SOURCES_MODELE = os.getenv("JUGE_SOURCES_MODELE", "") or "openai/gpt-oss-20b"' in pipeline, (
        "Le juge de pertinence doit utiliser par défaut openai/gpt-oss-20b, pas un modèle Groq retiré."
    )
    assert 'JUGE_SOURCES_MODELE = os.getenv("JUGE_SOURCES_MODELE", "") or "llama-3.1-8b-instant"' not in pipeline, (
        "Le modèle retiré llama-3.1-8b-instant ne doit jamais redevenir le défaut du juge."
    )
    assert '"groq/compound": 8_000' in pipeline, (
        "Le plafond runtime de groq/compound doit rester aligné sur le compteur servi gpt-oss-120b à 8 000 TPM."
    )
    assert '"groq/compound-mini": 8_000' in pipeline, (
        "Le plafond runtime de groq/compound-mini doit rester à 8 000 TPM tant qu'aucune mesure contraire n'est validée."
    )

    print("OK — modèles Groq runtime, juge de pertinence et plafonds TPM verrouillés")


if __name__ == "__main__":
    main()
