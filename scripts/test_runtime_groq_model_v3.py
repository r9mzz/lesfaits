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
