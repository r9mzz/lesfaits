# -*- coding: utf-8 -*-
"""Régression : les modèles Groq réellement utilisés par V3 doivent rester servis et cohérents."""
from pathlib import Path


HERE = Path(__file__).resolve().parent
RUNTIME = HERE / "run_pipeline_v3.py"
PIPELINE = HERE / "pipeline.py"


def main() -> None:
    runtime = RUNTIME.read_text(encoding="utf-8")
    pipeline = PIPELINE.read_text(encoding="utf-8")

    # ⚠ 24/08 — CINQUIÈME test du projet à verrouiller du TEXTE SOURCE.
    # Ce bloc exigeait littéralement la ligne
    #     os.environ["GROQ_MODEL_OVERRIDE"] = "openai/gpt-oss-120b"
    # et interdisait donc de la corriger — alors qu'elle envoyait un nom de
    # modèle GROQ à l'API MISTRAL (run 273). Le commentaire quelques lignes
    # plus bas disait déjà la leçon, tirée du 18/08 : « un test qui lit le code
    # source interdit toute réécriture, y compris correcte ». Elle n'avait pas
    # été appliquée à ce bloc-ci.
    #
    # Les propriétés RÉELLES à protéger sont au nombre de trois, et se
    # vérifient par le comportement, plus bas comme ici :
    #   1. le modèle est résolu AVANT l'import du pipeline historique ;
    #   2. une variable présente mais VIDE compte comme absente (GitHub Actions
    #      exporte les expressions vides ainsi — piège d'origine) ;
    #   3. un override explicite reste prioritaire (essai A/B du 17/08).
    legacy_import = "import run_pipeline as legacy"
    assert legacy_import in runtime, "Import run_pipeline introuvable dans le runtime V3."

    import os as _os0
    import subprocess as _sp
    import sys as _sys0

    def _modele_v3(env_sup: dict) -> str:
        env = dict(_os0.environ)
        env.pop("GROQ_MODEL_OVERRIDE", None)
        env.setdefault("GROQ_API_KEY", "x")
        # Ce test vérifie uniquement la RÉSOLUTION du modèle avec de fausses
        # clés. Depuis le 29/08, le vrai runtime sonde l'accès au fournisseur
        # avant collecte ; ne pas transformer ce test hors réseau en appel API.
        # `pipeline.yml` n'exporte jamais cette variable : la production ne
        # peut donc pas désactiver accidentellement la sonde.
        env["LLM_SKIP_ACCESS_PROBE"] = "1"
        env.update(env_sup)
        code = ("import run_pipeline_v3, pipeline, verification_legacy;"
                "print(pipeline.GROQ_MODEL, verification_legacy.GROQ_MODEL)")
        out = _sp.run([_sys0.executable, "-c", code], capture_output=True,
                      text=True, env=env, cwd=str(HERE))
        assert out.returncode == 0, out.stderr[-600:]
        gen, verif = out.stdout.strip().split()[-2:]
        assert gen == verif, (
            f"génération et fact-check divergent : {gen} vs {verif} — c'est la "
            "famille de bugs du 19/08 (clés) et du 24/08 (modèle).")
        return gen

    _mistral = {"LLM_BASE_URL": "https://api.mistral.ai/v1", "LLM_API_KEY": "x"}

    # Propriété 2 : vide == absent, dans les deux sens.
    assert _modele_v3({**_mistral, "GROQ_MODEL_OVERRIDE": "   "}) == _modele_v3(_mistral), (
        "Une variable présente mais vide doit compter comme absente."
    )
    # Sous Mistral, JAMAIS un nom de modèle Groq — c'est le défaut du run 273.
    _sous_mistral = _modele_v3(_mistral)
    assert "mistral" in _sous_mistral, (
        f"modèle {_sous_mistral!r} envoyé à l'API Mistral : un nom de modèle "
        "d'un autre fournisseur ne peut pas être servi."
    )
    # Propriété 3 : un override explicite reste prioritaire (essai A/B).
    assert _modele_v3({**_mistral, "GROQ_MODEL_OVERRIDE": "mistral-medium-latest"}) == "mistral-medium-latest"
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

    # Le reste du fichier teste l'import réel et la cohérence des modèles ; on
    # conserve son environnement historique.
    old_override = _os.environ.get("GROQ_MODEL_OVERRIDE")
    old_base = _os.environ.get("LLM_BASE_URL")
    old_key = _os.environ.get("LLM_API_KEY")
    old_skip = _os.environ.get("LLM_SKIP_ACCESS_PROBE")
    try:
        _os.environ["LLM_SKIP_ACCESS_PROBE"] = "1"
        _os.environ.pop("LLM_BASE_URL", None)
        _os.environ.pop("LLM_API_KEY", None)
        _os.environ.pop("GROQ_MODEL_OVERRIDE", None)
        import run_pipeline_v3 as _runtime_mod
        import pipeline as _pipeline_mod
        assert _pipeline_mod.GROQ_MODEL, "Le runtime doit résoudre un modèle non vide."
    finally:
        if old_override is None:
            _os.environ.pop("GROQ_MODEL_OVERRIDE", None)
        else:
            _os.environ["GROQ_MODEL_OVERRIDE"] = old_override
        if old_base is None:
            _os.environ.pop("LLM_BASE_URL", None)
        else:
            _os.environ["LLM_BASE_URL"] = old_base
        if old_key is None:
            _os.environ.pop("LLM_API_KEY", None)
        else:
            _os.environ["LLM_API_KEY"] = old_key
        if old_skip is None:
            _os.environ.pop("LLM_SKIP_ACCESS_PROBE", None)
        else:
            _os.environ["LLM_SKIP_ACCESS_PROBE"] = old_skip

    print("OK — modèle runtime V3 cohérent avec le fournisseur")


if __name__ == "__main__":
    main()
