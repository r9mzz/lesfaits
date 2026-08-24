"""Verrouille la résolution des clés du fournisseur unique.

Contexte : l'hypothèse « une clé suffit » (18/08) a coûté trois jours de
production. Le 22/08 le quota Mistral s'épuise aux trois quarts du run, les 23
et 24 ne produisent rien, et le job GitHub reste vert. Ces tests ne vérifient
pas qu'il y a N clés — ils vérifient que le mécanisme d'ajout fonctionne et que
les deux côtés (génération, fact-check) lisent la MÊME liste.
"""
import os
import subprocess
import sys

from cles_fournisseur import cles_fournisseur


def test_lit_les_cles_supplementaires():
    env = {"LLM_API_KEY": "a", "LLM_API_KEY_2": "b", "LLM_API_KEY_3": "c"}
    assert cles_fournisseur(env) == ["a", "b", "c"]


def test_sans_cle_principale_aucune_cle():
    """Sans LLM_API_KEY, le fournisseur historique reste seul maître.

    Renvoyer les clés secondaires seules ferait basculer le pipeline sur un
    fournisseur à moitié configuré — pire qu'une panne franche.
    """
    assert cles_fournisseur({}) == []
    assert cles_fournisseur({"LLM_API_KEY_2": "b"}) == []


def test_dedoublonne():
    """Deux secrets sur la même clé ne font pas deux quotas.

    Sans ça, la rotation compterait deux fois une clé déjà morte et croirait
    disposer d'une réserve qui n'existe pas.
    """
    assert cles_fournisseur({"LLM_API_KEY": "a", "LLM_API_KEY_2": "a"}) == ["a"]


def test_ignore_les_trous_et_les_blancs():
    env = {"LLM_API_KEY": " a ", "LLM_API_KEY_2": "   ", "LLM_API_KEY_4": "d"}
    assert cles_fournisseur(env) == ["a", "d"]


def test_generation_et_verification_lisent_la_meme_liste():
    """Le 401 du 19/08 venait de deux résolutions divergentes.

    On compare les DEUX modules dans un même environnement : ils doivent
    annoncer le même nombre de clés. C'est la propriété qui manquait.
    """
    code = (
        "import pipeline, verification, verification_legacy;"
        "print(len(pipeline.GROQ_ALL_KEYS), len(verification_legacy.GROQ_KEYS))"
    )
    # On part de l'environnement réel (sinon le sous-processus perd les
    # paquets installés) et on surcharge uniquement ce qui est sous test.
    env = dict(os.environ)
    for i in range(2, 41):
        env.pop(f"LLM_API_KEY_{i}", None)
    env.update({"LLM_API_KEY": "k1", "LLM_API_KEY_2": "k2",
                "LLM_API_KEY_3": "k3",
                "LLM_BASE_URL": "https://api.mistral.ai/v1"})
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, env=env, cwd=".")
    assert out.returncode == 0, out.stderr[-800:]
    gen, verif = out.stdout.strip().split()[-2:]
    assert gen == verif == "3", f"génération {gen} clés, fact-check {verif}"


if __name__ == "__main__":
    n = 0
    for nom, fn in sorted(globals().items()):
        if nom.startswith("test_"):
            fn(); n += 1; print(f"  ✓ {nom}")
    print(f"{n} tests OK")
