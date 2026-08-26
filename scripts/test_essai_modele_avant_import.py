"""L'essai de fournisseur doit nommer le modèle AVANT d'importer le pipeline.

Défaut mesuré le 26/08 : l'essai Gemini s'est arrêté en 23 secondes sur

    RuntimeError: Fournisseur non reconnu
    ('https://generativelanguage.googleapis.com/v1beta/openai')

`essai_fournisseur.py` patchait `p.GROQ_MODEL` APRÈS l'import — ce qui ne
couvre que la génération. La vérification résout son propre modèle à l'import
et, hors Groq/Mistral, refuse depuis le 25/08 de deviner plutôt que de partir
avec le nom d'un autre fournisseur.

Le garde-fou avait raison ; c'est l'essai qui lui donnait le nom trop tard.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _modeles(env_sup: dict) -> tuple[str, str]:
    env = dict(os.environ)
    env.pop("GROQ_MODEL_OVERRIDE", None)
    env.setdefault("GROQ_API_KEY", "x")
    env.update(env_sup)
    code = ("import essai_fournisseur, pipeline, verification_legacy;"
            "print(pipeline.GROQ_MODEL, verification_legacy.GROQ_MODEL)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, env=env, cwd=HERE)
    assert out.returncode == 0, out.stderr[-700:]
    return tuple(out.stdout.strip().split()[-2:])


def test_un_fournisseur_inconnu_ne_bloque_plus_l_essai():
    """C'est le cas Gemini : l'essai doit démarrer, pas lever."""
    gen, verif = _modeles({
        "MODELE_ESSAI": "gemini-3.6-flash",
        "LLM_BASE_URL": "https://generativelanguage.googleapis.com/v1beta/openai",
        "LLM_API_KEY": "x"})
    assert gen == verif == "gemini-3.6-flash", (gen, verif)


def test_generation_et_verification_ne_divergent_pas():
    """La propriété qui compte, et la raison du module partagé : un essai qui
    génère avec un modèle et vérifie avec un autre rend un verdict faux."""
    gen, verif = _modeles({
        "MODELE_ESSAI": "mistral-medium-latest",
        "LLM_BASE_URL": "https://api.mistral.ai/v1",
        "LLM_API_KEY": "x"})
    assert gen == verif, f"génération {gen}, fact-check {verif}"


def test_un_override_explicite_reste_prioritaire():
    """`setdefault` : un modèle imposé par l'environnement n'est pas écrasé."""
    gen, _ = _modeles({
        "MODELE_ESSAI": "gemini-3.6-flash",
        "GROQ_MODEL_OVERRIDE": "mistral-large-latest",
        "LLM_BASE_URL": "https://api.mistral.ai/v1",
        "LLM_API_KEY": "x"})
    assert gen == "mistral-large-latest", gen


if __name__ == "__main__":
    n = 0
    for nom, fn in sorted(globals().items()):
        if nom.startswith("test_"):
            fn(); n += 1; print(f"  ✓ {nom}")
    print(f"{n} tests OK")
