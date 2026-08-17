# -*- coding: utf-8 -*-
"""Régression : le runtime V3 ne doit jamais repartir sur un modèle Groq retiré."""
from pathlib import Path


HERE = Path(__file__).resolve().parent
RUNTIME = HERE / "run_pipeline_v3.py"


def main() -> None:
    source = RUNTIME.read_text(encoding="utf-8")

    override = 'os.environ.setdefault("GROQ_MODEL_OVERRIDE", "openai/gpt-oss-120b")'
    legacy_import = "import run_pipeline as legacy"

    assert override in source, "Le runtime V3 ne force pas le remplaçant Groq de production."
    assert legacy_import in source, "Import run_pipeline introuvable dans le runtime V3."
    assert source.index(override) < source.index(legacy_import), (
        "Le modèle doit être fixé AVANT l'import/exécution du pipeline historique."
    )
    assert '"test_runtime_groq_model_v3.py"' in source, (
        "Le test du modèle Groq doit être rejoué par le prévol runtime V3."
    )
    print("OK — modèle Groq de production verrouillé avant import du pipeline")


if __name__ == "__main__":
    main()
