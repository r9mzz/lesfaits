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

    # ⚠ Ce contrôle portait sur le TEXTE de la ligne, pas sur son effet. Il a
    # donc cassé le 18/08 quand les défauts sont devenus solidaires du
    # fournisseur — alors même que la propriété qu'il protège était intacte.
    # Un test qui lit le code source interdit toute réécriture, y compris
    # correcte ; on vérifie donc le COMPORTEMENT, par import réel.
    assert 'llama-3.1-8b-instant"' not in pipeline.split("JUGE_SOURCES_MODELE")[1][:200], (
        "Le modèle retiré llama-3.1-8b-instant ne doit jamais redevenir le défaut du juge."
    )

    import importlib
    import os as _os
    import sys as _sys

    _sys.path.insert(0, str(HERE))
    _os.environ.setdefault("GROQ_API_KEY", "x")

    def _defauts(base_url: str) -> tuple[str, str]:
        _anc = _os.environ.get("LLM_BASE_URL")
        if base_url:
            _os.environ["LLM_BASE_URL"] = base_url
        else:
            _os.environ.pop("LLM_BASE_URL", None)
        try:
            for m in ("pipeline",):
                _sys.modules.pop(m, None)
            mod = importlib.import_module("pipeline")
            return mod.GROQ_MODEL, mod.JUGE_SOURCES_MODELE
        finally:
            if _anc is None:
                _os.environ.pop("LLM_BASE_URL", None)
            else:
                _os.environ["LLM_BASE_URL"] = _anc
            _sys.modules.pop("pipeline", None)

    _red, _juge = _defauts("")
    assert "llama-3.1-8b-instant" not in _juge, (
        "Le modèle retiré ne doit jamais être le défaut du juge."
    )
    assert _juge != _red, (
        "Le juge doit rester DISTINCT du modèle de rédaction : sinon il puise "
        "dans le quota qui bloque déjà les runs, et le garde-fou le refuse."
    )

    # Un nom de modèle n'a de sens que chez le fournisseur qui le sert : pointer
    # Mistral avec des noms Groq produit un 404 sur chaque appel, soit la panne
    # des 15-17/08 dans l'autre sens.
    _red_m, _juge_m = _defauts("https://api.mistral.ai/v1")
    assert "mistral" in _red_m and "mistral" in _juge_m, (
        f"Sous Mistral, les défauts restent des modèles Groq ({_red_m}, {_juge_m}) "
        "— chaque appel échouerait en 404."
    )
    assert _juge_m != _red_m, "Juge et rédacteur doivent rester distincts sous tout fournisseur."
    # ⚠ 19/08 — ces deux contrôles lisaient le TEXTE SOURCE de pipeline.py.
    # La table des fenêtres a déménagé dans `fenetres_modeles.py` (le
    # fact-checker en a besoin aussi, il portait la valeur Groq en dur) et le
    # test a cassé alors que la propriété protégée était intacte. On lit
    # désormais la VALEUR, pas la ligne de code : elle survit à un
    # déplacement, à un reformatage, et dit ce qu'on veut vraiment garantir.
    from fenetres_modeles import _TPM_PAR_MODELE_GEN

    for _m in ("groq/compound", "groq/compound-mini"):
        assert _TPM_PAR_MODELE_GEN.get(_m) == 8_000, (
            f"Le plafond runtime de {_m} doit rester aligné sur le compteur "
            "réellement servi (gpt-oss-120b, 8 000 TPM) : les 70 000 de la "
            "grille tarifaire ne décrivent pas ce qui nous rejette."
        )

    print("OK — modèles Groq runtime, juge de pertinence et plafonds TPM verrouillés")


if __name__ == "__main__":
    main()
