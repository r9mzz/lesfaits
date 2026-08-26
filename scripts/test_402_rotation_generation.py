"""Un 402 en RÉDACTION doit faire tourner la clé, pas perdre le sujet.

Run 281 (26/08) : 24 refus 402 « Check your subscription », chacun tuant son
sujet, alors que le fact-check rotationnait déjà correctement depuis le 25/08.
La rédaction ne connaissait que le 429 ; le 402 tombait dans le `raise`
générique. Ce test verrouille les deux propriétés qui manquaient :

  1. une clé refusée en 402 est retirée de la rotation et la SUIVANTE est
     essayée — le sujet n'est pas perdu tant qu'une clé répond ;
  2. quand toutes les clés sont épuisées, l'échec est `QuotaJournalierEpuise`
     (que `run()` rattrape pour arrêter proprement), jamais une exception nue
     qui ferait retenter le sujet suivant sur les mêmes clés mortes.

Le motif est lu dans le code, jamais recopié : on rejoue le VRAI corps
d'erreur Mistral.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("GROQ_MODEL_OVERRIDE", "mistral-large-latest")

import pipeline  # noqa: E402

CORPS_402 = ("Error code: 402 - {'detail': 'Check your subscription on "
             "https://admin.mistral.ai/subscription'}")


def _messages_factices(monkeypatch, refus: set):
    """Remplace l'appel réseau : les clés de `refus` lèvent un 402."""
    appels = []

    def faux_appel(api_key, messages, max_tokens=3500):
        appels.append(api_key)
        if api_key in refus:
            raise RuntimeError(CORPS_402)
        return '{"titre": "T", "resume": "R", "corps": {"faits": "F"}, "sources": []}'

    monkeypatch.setattr(pipeline, "_groq_call", faux_appel)
    return appels


def test_402_bascule_sur_la_cle_suivante(monkeypatch):
    pipeline._CLES_MORTES_JOUR.clear()
    monkeypatch.setattr(pipeline, "GROQ_ALL_KEYS",
                        [("k1", "clé 1"), ("k2", "clé 2")])
    appels = _messages_factices(monkeypatch, refus={"k1"})

    art = pipeline.generate("Un titre", "Un contenu", [])

    assert appels[:2] == ["k1", "k2"], (
        "la clé refusée en 402 doit être suivie d'un essai sur la suivante, "
        f"appels observés : {appels}")
    assert "k1" in pipeline._CLES_MORTES_JOUR
    assert art is not None
    pipeline._CLES_MORTES_JOUR.clear()


def test_toutes_les_cles_402_leve_quota_epuise(monkeypatch):
    pipeline._CLES_MORTES_JOUR.clear()
    monkeypatch.setattr(pipeline, "GROQ_ALL_KEYS",
                        [("k1", "clé 1"), ("k2", "clé 2")])
    _messages_factices(monkeypatch, refus={"k1", "k2"})

    try:
        pipeline.generate("Un titre", "Un contenu", [])
    except pipeline.QuotaJournalierEpuise:
        pass
    except Exception as e:  # pragma: no cover — c'est le défaut qu'on interdit
        raise AssertionError(
            "un solde épuisé sur toutes les clés doit lever "
            f"QuotaJournalierEpuise, pas {type(e).__name__}: {e}")
    else:
        raise AssertionError("aucune exception levée alors que tout est refusé")
    pipeline._CLES_MORTES_JOUR.clear()
