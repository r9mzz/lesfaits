# -*- coding: utf-8 -*-
"""Complément de mesure : POURQUOI le barème écarte les faits les plus couverts.

`mesure_clustering.py` établit que 12 grappes sur 13 (≥3 médias) sont absentes
de la sélection. Objection à écarter avant d'en conclure quoi que ce soit :
une partie de ces grappes sont des sujets sensibles (affaires pénales, guerre,
victimes) que la charte rejette à juste titre. Le gain réel n'est donc pas
« 12 sujets ratés » mais « N sujets ratés ET publiables ».

Ce script rejoue `score_editorial` sur un représentant de chaque grappe et
affiche le score et les motifs. Ne modifie rien, n'appelle ni Groq ni DDG.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent))

import pipeline as P  # noqa: E402
from mesure_clustering import clusteriser, collecter  # noqa: E402


def main() -> int:
    items = collecter()
    grappes = [g for g in clusteriser(items, 0.34)
               if len({x["_source"] for x in g}) >= 3]
    published_topics = {a.get("titre", "") for a in P.load_index()[:140]}

    publiables = sensibles = sous_seuil = 0
    print(f"=== {len(grappes)} grappes ≥3 médias : verdict du barème actuel ===\n")
    for g in grappes:
        medias = sorted({x["_source"] for x in g})
        rep = g[0]
        score, motifs = P.score_editorial(rep, rep.get("_source", "?"), published_topics)
        typ = P.classifier_type_article(rep["title"], rep.get("content", ""))

        if typ == "rejete" or score == -1:
            verdict, cat = "REJETÉ", "sensible/filtré"
            sensibles += 1
        elif score < 20:
            verdict, cat = f"score {score}", "sous le seuil de 20"
            sous_seuil += 1
        else:
            verdict, cat = f"score {score}", "PUBLIABLE — raté par la sélection"
            publiables += 1

        print(f"  [{len(medias)} médias] {rep['title'][:74]}")
        print(f"      {verdict:>10}  {cat}")
        if motifs:
            print(f"      motifs : {' | '.join(str(m)[:58] for m in motifs[:3])}")
        print()

    print("=== BILAN ===")
    print(f"  grappes écartées comme sensibles/filtrées : {sensibles}")
    print(f"  grappes sous le seuil de score            : {sous_seuil}")
    print(f"  grappes PUBLIABLES mais non sélectionnées : {publiables}")
    print()
    print("  Seul le dernier chiffre mesure un gain réel. Les deux premiers sont")
    print("  des rejets que la charte assume, et le clustering ne doit pas les")
    print("  contourner — il doit servir à hiérarchiser ce qui reste publiable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
