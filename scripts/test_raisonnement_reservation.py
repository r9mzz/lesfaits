"""La réservation doit tenir compte des tokens de RÉFLEXION.

Mesuré sur l'essai Gemini du 25/08 :

    prompt=9150 completion=101 total=11773 fin=length réservé=2628

9150 + 101 = 9251, pas 11773 : 2 522 tokens n'apparaissent nulle part. Ce sont
les tokens de raisonnement, facturés sur le budget de sortie sans figurer dans
`completion`. Le modèle a dépensé sa réservation entière à réfléchir et s'est
fait couper avant d'écrire une phrase.

La valeur est APPRISE sur les réponses réelles, jamais codée en dur : une table
de modèles « à raisonnement » serait le énième réglage propre à un fournisseur,
destiné à survivre au fournisseur suivant et à devenir faux en silence.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("GROQ_API_KEY", "x")

import pipeline as P


class _Usage:
    def __init__(self, p, c, t):
        self.prompt_tokens, self.completion_tokens, self.total_tokens = p, c, t


class _Choice:
    def __init__(self, contenu, fin):
        self.message = type("M", (), {"content": contenu})()
        self.finish_reason = fin


class _Reponse:
    def __init__(self, usage, contenu='{"ok": 1}', fin="stop"):
        self.usage, self.choices = usage, [_Choice(contenu, fin)]


def _appeler(usage, fin="stop"):
    """Fait un appel avec une réponse simulée et rend le max_tokens demandé."""
    vus = {}

    class _FauxClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    vus["max_tokens"] = kw.get("max_tokens")
                    return _Reponse(usage, fin=fin)

    vrai = P._client
    P._client = lambda _k: _FauxClient
    try:
        try:
            P._groq_call("k", [{"role": "user", "content": "x" * 400}], max_tokens=3500)
        except Exception:
            pass
        return vus.get("max_tokens")
    finally:
        P._client = vrai


def test_sans_raisonnement_rien_ne_change():
    P._RAISONNEMENT_OBSERVE.clear()
    demande = _appeler(_Usage(100, 200, 300))          # total == prompt+completion
    assert P._RAISONNEMENT_OBSERVE == {}, P._RAISONNEMENT_OBSERVE
    assert demande == _appeler(_Usage(100, 200, 300)), "réservation modifiée sans raison"


def test_le_raisonnement_est_appris_puis_ajoute():
    """C'est le cas Gemini : 2 522 tokens invisibles au premier appel."""
    P._RAISONNEMENT_OBSERVE.clear()
    avant = _appeler(_Usage(9150, 101, 11773), fin="length")
    assert P._RAISONNEMENT_OBSERVE.get(P.GROQ_MODEL) == 2522, P._RAISONNEMENT_OBSERVE
    apres = _appeler(_Usage(9150, 101, 11773), fin="length")
    assert apres > avant, (
        f"réservation inchangée ({avant} → {apres}) alors que 2 522 tokens de "
        "réflexion ont été observés")


def test_on_garde_le_pire_cas_observe():
    """Le raisonnement varie d'un sujet à l'autre — 2 616 à 5 756 mesurés sur
    deux sujets. Retenir le MAXIMUM, sinon un sujet plus coûteux retronque."""
    P._RAISONNEMENT_OBSERVE.clear()
    _appeler(_Usage(9000, 100, 14000))                 # 4 900
    _appeler(_Usage(9000, 100, 11000))                 # 1 900, plus faible
    assert P._RAISONNEMENT_OBSERVE.get(P.GROQ_MODEL) == 4900


if __name__ == "__main__":
    n = 0
    for nom, fn in sorted(globals().items()):
        if nom.startswith("test_"):
            fn(); n += 1; print(f"  ✓ {nom}")
    print(f"{n} tests OK")
