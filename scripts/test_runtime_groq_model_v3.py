# -*- coding: utf-8 -*-
"""Régression : le runtime V3 ne doit jamais repartir sur un modèle Groq retiré."""
from pathlib import Path


HERE = Path(__file__).resolve().parent
RUNTIME = HERE / "run_pipeline_v3.py"


def main() -> None:
    source = RUNTIME.read_text(encoding="utf-8")

    empty_guard = 'if not os.environ.get("GROQ_MODEL_OVERRIDE", "").strip():'
    assignment = 'os.environ["GROQ_MODEL_OVERRIDE"] = "openai/gpt-oss-120b"'
    legacy_import = "import run_pipeline as legacy"

    assert empty_guard in source, (
        "Le runtime V3 doit traiter une variable GROQ_MODEL_OVERRIDE présente mais vide comme absente."
    )
    assert assignment in source, "Le runtime V3 ne force pas le remplaçant Groq de production."
    assert legacy_import in source, "Import run_pipeline introuvable dans le runtime V3."
    assert source.index(empty_guard) < source.index(assignment) < source.index(legacy_import), (
        "Le modèle doit être résolu, y compris si l'override est vide, AVANT l'import/exécution du pipeline historique."
    )
    assert 'os.environ.setdefault("GROQ_MODEL_OVERRIDE"' not in source, (
        "setdefault laisse intacte une variable d'environnement présente mais vide et réactive le modèle retiré."
    )
    assert '"test_runtime_groq_model_v3.py"' in source, (
        "Le test du modèle Groq doit être rejoué par le prévol runtime V3."
    )
    print("OK — override Groq absent ou vide verrouillé avant import du pipeline")


if __name__ == "__main__":
    main()
