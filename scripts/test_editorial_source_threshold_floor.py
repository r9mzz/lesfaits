"""Empêche toute baisse silencieuse des seuils éditoriaux de sourcing vitrine.

Le 24/08, MIN_SOURCES a été abaissé de 6 à 3 et MIN_DISTINCT_DOMAINS de 5 à 3
pour augmenter le nombre d'articles susceptibles de franchir la grille finale.
Le mandat d'exploitation interdit explicitement de réduire les seuils éditoriaux
pour faire du volume : ces minima historiques constituent donc un plancher.
"""
import showcase_quality as S


def test_source_thresholds_never_drop_below_historical_floor():
    assert S.MIN_SOURCES >= 6, (
        f"MIN_SOURCES={S.MIN_SOURCES}: baisse sous le plancher éditorial historique 6"
    )
    assert S.MIN_DISTINCT_DOMAINS >= 5, (
        f"MIN_DISTINCT_DOMAINS={S.MIN_DISTINCT_DOMAINS}: baisse sous le plancher historique 5"
    )
    assert S.MIN_DISTINCT_DOMAINS <= S.MIN_SOURCES


if __name__ == "__main__":
    test_source_thresholds_never_drop_below_historical_floor()
    print("1 test OK")
