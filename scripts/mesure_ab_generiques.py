# -*- coding: utf-8 -*-
"""A/B strict du filtre « mots génériques » sur UN SEUL corpus.

Le premier essai comparait deux collectes différentes (les flux bougent entre
deux exécutions) : l'écart mesuré n'était donc attribuable à rien. Ici la
collecte est faite UNE fois, puis rescorée deux fois — filtre désactivé, puis
activé — sur exactement les mêmes items et les mêmes titres publiés.

    python scripts/mesure_ab_generiques.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent))

import pipeline as P  # noqa: E402
from mesure_clustering import clusteriser, collecter, norm_tokens  # noqa: E402


def scorer_tout(items, published_topics, df_seuil):
    """Rescore le corpus avec un seuil de généricité donné.

    `df_seuil` très grand ⇒ aucun mot n'est générique ⇒ comportement d'avant.
    """
    P.DF_MOT_GENERIQUE = df_seuil
    P._MOTS_GENERIQUES_CACHE.clear()
    out = []
    for it in items:
        score, motifs = P.score_editorial(dict(it), it.get("_source", "?"), published_topics)
        out.append((score, motifs, it))
    return out


def main() -> int:
    items = collecter()
    if not items:
        print("Aucun item collecté.")
        return 1
    published_topics = {a.get("titre", "") for a in P.load_index()[:140]}
    grappes = [g for g in clusteriser(items, 0.34)
               if len({x["_source"] for x in g}) >= 3]
    tokens_grappes = [set().union(*[norm_tokens(x["title"]) for x in g]) for g in grappes]

    avant = scorer_tout(items, published_topics, 10 ** 9)   # filtre désactivé
    apres = scorer_tout(items, published_topics, 3)          # filtre actif

    def stats(res, lbl):
        retenus = [r for r in res if r[0] >= 20]
        penalises = [r for r in res if any("sujet proche" in str(m) or "très redondant" in str(m)
                                           for m in r[1])]
        # combien de faits multi-médias franchissent le seuil ?
        grappes_ok = 0
        for tg in tokens_grappes:
            if any(r[0] >= 20 and len(norm_tokens(r[2]["title"]) & tg) >= 2 for r in res):
                grappes_ok += 1
        print(f"  {lbl}")
        print(f"     candidats au-dessus du seuil (20) : {len(retenus):4} / {len(res)}")
        print(f"     pénalisés par l'anti-doublon      : {len(penalises):4}")
        print(f"     grappes ≥3 médias franchissant 20 : {grappes_ok:4} / {len(grappes)}")
        return len(retenus), len(penalises), grappes_ok

    print(f"=== A/B sur le MÊME corpus : {len(items)} items, {len(grappes)} grappes ≥3 médias ===\n")
    a = stats(avant, "AVANT — tout mot commun compte")
    print()
    b = stats(apres, "APRÈS — mots présents dans ≥3 titres publiés ignorés")

    print("\n=== DELTA ===")
    print(f"  candidats au-dessus du seuil : {a[0]:+4} → {b[0]:+4}  ({b[0]-a[0]:+d})")
    print(f"  pénalisés par l'anti-doublon : {a[1]:+4} → {b[1]:+4}  ({b[1]-a[1]:+d})")
    print(f"  grappes ≥3 médias récupérées : {a[2]:+4} → {b[2]:+4}  ({b[2]-a[2]:+d})")

    # Contrôle indispensable : le filtre ne doit pas laisser passer de vrais
    # doublons. On liste les candidats qui passent APRÈS et qui partagent ≥2
    # mots distinctifs avec un titre déjà publié.
    print("\n=== CONTRÔLE : vrais doublons laissés passer ? ===")
    generiques = P._mots_generiques_corpus(published_topics)
    suspects = 0
    for score, _m, it in apres:
        if score < 20:
            continue
        tw = {w[:8] for w in P._norm_words(it["title"])} if hasattr(P, "_norm_words") else set()
        for t in published_topics:
            partages = (norm_tokens(it["title"]) & norm_tokens(t)) - generiques
            if len(partages) >= 3:
                suspects += 1
                print(f"   ⚠ « {it['title'][:58]} »")
                print(f"     vs publié « {t[:58]} » — {sorted(partages)[:4]}")
                break
    if not suspects:
        print("   aucun : aucun candidat retenu ne partage ≥3 mots distinctifs")
        print("   avec un article déjà publié.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
