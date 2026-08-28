"""Régression : ne pas exiger une réserve une troisième fois dans un titre exact.

Cas réel du run du 29/08 : le juge reconnaît que le résumé porte correctement
la réserve, la phrase dit « pourraient ... sans preuve », et le titre de
section dit seulement « les données menacées ». Ce triplet n'affirme jamais
que la compromission est acquise.

Le garde reste volontairement étroit : un titre qui affirme « données
compromises » ou une phrase non prudente doit continuer à bloquer.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import verification as V  # noqa: E402


def _pb(description: str, phrase: str) -> dict:
    return {
        "bloc": 1,
        "type": "niveau_preuve_insuffisant",
        "description": description,
        "phrase": phrase,
    }


def test_cas_reel_donnees_menacees_est_ecarte():
    p = _pb(
        "La formulation du résumé reprend correctement la réserve de la source [5] "
        "(Le Soir), mais cette réserve n'est pas répétée dans le titre des faits "
        "(« les données menacées »), ce qui pourrait laisser penser que la "
        "compromission est confirmée.",
        "elles ont indiqué le 26 août que des informations personnelles pourraient "
        "avoir été compromises, sans en apporter de preuve tangible [5].",
    )
    assert V._problemes_bloquants([p], {}) == []


def test_titre_donnees_compromises_reste_bloquant():
    p = _pb(
        "La formulation du résumé reprend correctement la réserve de la source [5], "
        "mais cette réserve n'est pas répétée dans le titre des faits "
        "(« les données compromises »).",
        "elles ont indiqué que des informations personnelles pourraient avoir été "
        "compromises, sans en apporter de preuve tangible [5].",
    )
    assert V._problemes_bloquants([p], {}) == [p]


def test_phrase_non_prudente_reste_bloquante():
    p = _pb(
        "La formulation du résumé reprend correctement la réserve de la source [5], "
        "mais cette réserve n'est pas répétée dans le titre des faits "
        "(« les données menacées »).",
        "Les informations personnelles ont été compromises [5].",
    )
    assert V._problemes_bloquants([p], {}) == [p]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"  ✓ {test.__name__}")
    print(f"{len(tests)} tests OK")
