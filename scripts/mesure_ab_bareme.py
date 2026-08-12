# -*- coding: utf-8 -*-
"""Banc d'essai du barème : quatre variantes sur UN corpus figé.

Question mesurée : le barème sait-il reconnaître un sujet qui compte ?
Constat du 10/08 (610 items, 36 flux) — 10 grappes de ≥3 médias sur 14
franchissent le seuil de sélection, mais UNE SEULE est retenue. Les faits
majeurs passent le seuil puis perdent le classement contre des pièces de
magazine mono-source, parce que « +35 source majeure » prime le NOM du média.

Variantes testées, toutes sur la même collecte :
  BASE  état actuel
  V1    prime au nom du média ramenée au niveau « média reconnu » (35 → 15)
  V2    malus si aucun marqueur d'actualité (0 chiffre, 0 institution, 0 enjeu)
  V3    bonus enjeu public renforcé (30/15 → 45/25)
  V1+V2+V3

La collecte est mise en CACHE : les flux bougent d'une minute à l'autre, et
comparer deux corpus différents n'attribue rien (erreur commise une fois).

    python scripts/mesure_ab_bareme.py            # réutilise le cache s'il existe
    python scripts/mesure_ab_bareme.py --recolter # force une nouvelle collecte
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent))

import pipeline as P  # noqa: E402
from mesure_clustering import clusteriser, collecter, norm_tokens  # noqa: E402

CACHE = Path(__file__).parent.parent / "data" / "cache_collecte_mesure.json"


def corpus(recolter: bool) -> list[dict]:
    if CACHE.exists() and not recolter:
        items = json.loads(CACHE.read_text(encoding="utf-8"))
        print(f"[CACHE] {len(items)} items relus depuis {CACHE.name}\n")
        return items
    items = collecter()
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    print(f"[CACHE] {len(items)} items écrits dans {CACHE.name}\n")
    return items


VARIANTES = {
    "BASE":     dict(maj=35, enj=(30, 15), malus=0),
    "V1":       dict(maj=15, enj=(30, 15), malus=0),
    "V2":       dict(maj=35, enj=(30, 15), malus=25),
    "V3":       dict(maj=35, enj=(45, 25), malus=0),
    "V1+V2+V3": dict(maj=15, enj=(45, 25), malus=25),
}


def evaluer(items, published_topics, grappes_tokens, cfg):
    P.PONDS_SOURCE_MAJEURE = cfg["maj"]
    P.PONDS_ENJEU_FORT, P.PONDS_ENJEU_MOYEN = cfg["enj"]
    P.MALUS_SANS_SUBSTANCE = cfg["malus"]
    P._MOTS_GENERIQUES_CACHE.clear()

    candidats = []
    for nom in {i["_source"] for i in items}:
        lot = [dict(i) for i in items if i["_source"] == nom]
        candidats += P.filtrer_et_classer(lot, nom, published_topics, seuil_score=20)
    candidats.sort(key=lambda c: c['_score'], reverse=True)
    sel = P.selectionner_meilleurs(candidats, nb_max=34)

    # combien de grappes ≥3 médias sont RETENUES (pas juste au-dessus du seuil)
    retenues = 0
    for tg in grappes_tokens:
        if any(len(norm_tokens(s["title"]) & tg) >= 2 for s in sel):
            retenues += 1
    # part de la sélection couverte par un seul média
    mono = 0
    for s in sel:
        ts = norm_tokens(s["title"])
        if not any(len(ts & tg) >= 2 for tg in grappes_tokens):
            mono += 1
    return sel, retenues, mono


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--recolter", action="store_true")
    args = ap.parse_args()

    items = corpus(args.recolter)
    published_topics = {a.get("titre", "") for a in P.load_index()[:140]}
    grappes = [g for g in clusteriser(items, 0.34)
               if len({x["_source"] for x in g}) >= 3]
    gt = [set().union(*[norm_tokens(x["title"]) for x in g]) for g in grappes]
    print(f"corpus : {len(items)} items · {len(grappes)} grappes ≥3 médias\n")

    resultats = {}
    for nom, cfg in VARIANTES.items():
        sel, ret, mono = evaluer(items, published_topics, gt, cfg)
        resultats[nom] = (sel, ret, mono)

    larg = max(len(n) for n in VARIANTES)
    print(f"{'variante':<{larg}}  {'retenus':>7}  {'grappes ≥3 médias':>18}  {'mono-source':>12}")
    print("-" * (larg + 44))
    for nom in VARIANTES:
        sel, ret, mono = resultats[nom]
        part = f"{mono}/{len(sel)}" if sel else "—"
        pct = f"{mono/len(sel):.0%}" if sel else ""
        print(f"{nom:<{larg}}  {len(sel):>7}  {ret:>10}/{len(grappes):<7}  {part:>8} {pct:>4}")

    base_titres = {s["title"] for s in resultats["BASE"][0]}
    fin_titres = {s["title"] for s in resultats["V1+V2+V3"][0]}
    print(f"\n=== CE QUI ENTRE avec V1+V2+V3 ({len(fin_titres - base_titres)}) ===")
    for t in sorted(fin_titres - base_titres)[:10]:
        print(f"   + {t[:88]}")
    print(f"\n=== CE QUI SORT ({len(base_titres - fin_titres)}) ===")
    for t in sorted(base_titres - fin_titres)[:10]:
        print(f"   - {t[:88]}")

    print("\n=== TÊTE DE SÉLECTION ===")
    for nom in ("BASE", "V1+V2+V3"):
        print(f"\n  {nom}")
        for s in resultats[nom][0][:6]:
            print(f"     [{s.get('_score', '?'):>4}] {s['title'][:76]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
