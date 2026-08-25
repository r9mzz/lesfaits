"""Un 402 sur une clé ne doit pas condamner la vérification entière.

Mesuré sur les runs 273 et 275, profil identique :

    générations réussies : 18-22   (la génération passe à la clé suivante)
    vérifications        :  0      (le fact-check s'arrêtait sur la clé 1)
    refus 402            : 20-22

Le fact-check levait sur tout code >= 400, donc abandonnait AVANT d'essayer
les clés 2 et 3. Les clés supplémentaires ne servaient qu'à la moitié du
pipeline, et le fail-closed rejetait ensuite chaque article : 18 générations
payées pour zéro publication, deux runs de suite.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("GROQ_API_KEY", "x")

import verification_legacy as V


class _Reponse:
    def __init__(self, code, texte='{"conforme": true, "problemes": []}'):
        self.status_code = code
        self.text = texte

    def json(self):
        import json
        return {"choices": [{"message": {"content": self.text}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10,
                          "total_tokens": 20}}


def _rejouer(codes, cles):
    """Rejoue une séquence de réponses HTTP et rend les clés réellement
    essayées. `codes` est indexé par clé."""
    essayees = []
    V.GROQ_KEYS = list(cles)
    V._CLES_MORTES_JOUR.clear()

    def faux_post(url, headers=None, json=None, timeout=None):
        cle = headers["Authorization"].split()[-1]
        essayees.append(cle)
        code = codes.get(cle, 200)
        return _Reponse(code, '{"detail":"Check your subscription"}'
                        if code >= 400 else _Reponse(200).text)

    vrai = V.requests.post
    V.requests.post = faux_post
    try:
        erreur = None
        try:
            V._llm_call("prompt de test", 1500)
        except Exception as exc:  # noqa: BLE001
            erreur = exc
        return essayees, erreur
    finally:
        V.requests.post = vrai
        V._CLES_MORTES_JOUR.clear()


def test_402_passe_a_la_cle_suivante():
    """C'est le défaut mesuré : la clé 1 épuisée tuait tout le fact-check."""
    essayees, erreur = _rejouer({"k1": 402}, ["k1", "k2", "k3"])
    assert "k2" in essayees, (
        f"la clé 2 n'a jamais été essayée après un 402 sur la clé 1 : {essayees}")
    assert erreur is None, f"la vérification a échoué alors que k2 répondait : {erreur}"


def test_402_sur_toutes_les_cles_echoue_proprement():
    """Fail-closed préservé : sans clé vivante, on NE publie PAS.

    C'est la règle fondatrice — aucun article sans vérification. Le correctif
    doit faire durer la recherche d'une clé, jamais l'abandonner.
    """
    essayees, erreur = _rejouer({"k1": 402, "k2": 402, "k3": 402}, ["k1", "k2", "k3"])
    assert set(essayees) == {"k1", "k2", "k3"}, essayees
    assert erreur is not None, "un quota épuisé partout doit lever, pas publier"
    # ⚠ Le préfixe est CONTRACTUEL : c'est l'unique déclencheur du « fail fast »
    # de verification.py (25/08), qui cesse d'appeler le fournisseur article
    # après article une fois la panne constatée. Sans lui, la rotation ajoutée
    # ici masquerait ce garde-fou et rendrait chaque sujet payant en réseau.
    assert str(erreur).startswith("Groq 402:"), (
        f"le fail-fast de verification.py ne reconnaîtra pas : {erreur!r}")


def test_une_panne_de_configuration_leve_tout_de_suite():
    """Un 401/404 est identique sur toutes les clés : parcourir la liste
    entière ne ferait que retarder le diagnostic."""
    essayees, erreur = _rejouer({"k1": 404}, ["k1", "k2", "k3"])
    assert essayees == ["k1"], f"un 404 ne doit pas faire tourner la rotation : {essayees}"
    assert erreur is not None


if __name__ == "__main__":
    n = 0
    for nom, fn in sorted(globals().items()):
        if nom.startswith("test_"):
            fn(); n += 1; print(f"  ✓ {nom}")
    print(f"{n} tests OK")
