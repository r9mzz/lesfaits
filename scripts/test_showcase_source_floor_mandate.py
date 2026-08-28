#!/usr/bin/env python3
"""Régression: le rendement observé ne peut pas abaisser le plancher de sourcing vitrine.

Le 28/08, MIN_SOURCES a été réduit de 6 à 4 parce que 6 ne laissait survivre
qu'un article sur dix. Ce test verrouille le mandat d'exploitation: une mesure
de volume/rendement peut diagnostiquer un goulet, mais ne peut pas desserrer la
porte éditoriale finale. Le correctif doit se faire en amont (meilleur sourcing),
pas par baisse du seuil de publication.
"""
import showcase_quality as S


def test_plancher_sourcing_vitrine_intact():
    assert S.MIN_SOURCES >= 6, (
        f"MIN_SOURCES={S.MIN_SOURCES}: le plancher éditorial 6 a été abaissé")
    assert S.MIN_DISTINCT_DOMAINS >= 5, (
        f"MIN_DISTINCT_DOMAINS={S.MIN_DISTINCT_DOMAINS}: le plancher 5 a été abaissé")
    assert S.MIN_DISTINCT_DOMAINS <= S.MIN_SOURCES


if __name__ == "__main__":
    test_plancher_sourcing_vitrine_intact()
    print("test_plancher_sourcing_vitrine_intact: OK")
