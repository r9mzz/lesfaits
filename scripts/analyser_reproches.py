#!/usr/bin/env python3
"""Accumule les reproches bloquants ET la nature du contenu, run après run.

    python scripts/analyser_reproches.py [--jours N]

POURQUOI CE SCRIPT EXISTE. Deux relectures à la main ont donné des résultats
OPPOSÉS à un jour d'intervalle :

    run 285 (26/08)   26 reproches   4 fondés   17 infondés   (65 % infondés)
    run 290 (27/08)   12 reproches   majorité FONDÉS, dont un vrai contresens
                                     de chiffre et 5 opinions écrites comme
                                     des constats

Ce n'est pas une contradiction, c'est un effet d'ÉCHANTILLON : le run 285 avait
tiré des sujets d'étude scientifique, le 290 des sujets d'opinion économique.
Conclure sur un run reviendrait à refaire l'erreur qui a coûté trois semaines à
ce projet (« la brièveté vient du modèle » alors qu'elle venait du budget).

⚠ CE SCRIPT NE DÉCIDE RIEN ET NE DOIT RIEN DÉCIDER. Il affiche des
distributions pour qu'un seuil, s'il est un jour posé, le soit sur des chiffres
relevés. Trois règles héritées de l'essai juge du 20/08 :

  - ne jamais réimplémenter une règle de décision : les motifs bloquants sont
    lus dans le journal tels que `_problemes_bloquants` les a écrits ;
  - compter les échecs à part, jamais dans le dénominateur — une panne de
    quota ou un timeout n'est pas un verdict éditorial ;
  - afficher le CONTRÔLE de l'instrument à côté du résultat, et refuser de
    conclure quand rien n'a été mesuré.

LA QUESTION À LIRE, et rien d'autre pour l'instant : les sujets dont
`nature_contenu` est une OPINION (tribune, chronique, prise_de_position,
interview) échouent-ils plus que les autres ? Si oui, un malus de sélection se
justifie. Si les colonnes sont plates, il ne se justifie pas — et il ne faudra
pas le poser quand même.
"""
import argparse
import collections
import datetime as dt
import json
import os
import sys

JOURNAL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "verification_log.json")

# Statuts qui traduisent une PANNE, jamais un jugement éditorial. Comptés à
# part : les mêler aux rejets surestimerait la sévérité du pipeline (piège
# relevé le 02/08 — un quota épuisé était logué comme `rejete_qualite`).
STATUTS_TECHNIQUES = {"erreur_verification", "non_verifie"}

# `nature_contenu` valant une OPINION plutôt qu'un fait. Liste alignée sur les
# valeurs que le prompt de détection énumère — ne pas en inventer d'autres.
NATURES_OPINION = {"tribune", "chronique", "prise_de_position", "interview"}


def charger(jours: int | None) -> list:
    try:
        with open(JOURNAL, encoding="utf-8") as f:
            entrees = json.load(f)
    except Exception as e:
        print(f"ERREUR : journal illisible ({e})", file=sys.stderr)
        sys.exit(1)
    if jours is None:
        return entrees
    limite = dt.datetime.now() - dt.timedelta(days=jours)
    gardees = []
    for e in entrees:
        try:
            if dt.datetime.fromisoformat(e["date"]) >= limite:
                gardees.append(e)
        except Exception:
            continue
    return gardees


def _barre(n: int, total: int, largeur: int = 28) -> str:
    if total <= 0:
        return ""
    return "█" * max(1, round(n / total * largeur)) if n else ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jours", type=int, default=None,
                    help="ne lire que les N derniers jours")
    args = ap.parse_args()
    entrees = charger(args.jours)

    techniques = [e for e in entrees if e.get("statut") in STATUTS_TECHNIQUES]
    editoriaux = [e for e in entrees if e.get("statut") not in STATUTS_TECHNIQUES]

    print(f"\n{len(entrees)} entrée(s) lues"
          + (f" (derniers {args.jours} jours)" if args.jours else ""))
    print(f"  verdicts éditoriaux : {len(editoriaux)}")
    print(f"  échecs TECHNIQUES   : {len(techniques)}  "
          "← comptés à part, hors de tout taux")

    if not editoriaux:
        print("\nAucun verdict éditorial : rien à conclure.")
        sys.exit(1)

    # ── 1. Motifs bloquants ─────────────────────────────────────────────────
    motifs = collections.Counter()
    articles_avec_bloquants = 0
    for e in editoriaux:
        types = e.get("bloquants_types") or []
        if not types:
            continue
        articles_avec_bloquants += 1
        for t in types:
            motifs[str(t).split("/")[-1]] += 1

    print(f"\n── MOTIFS BLOQUANTS ({articles_avec_bloquants} article(s) recalé(s) "
          f"après 3 passes) ──")
    if not motifs:
        print("  aucun — le champ `bloquants_types` est vide sur toute la période.")
    total_m = sum(motifs.values())
    for m, n in motifs.most_common():
        print(f"  {n:4d}  {100*n/total_m:5.1f} %  {m:34s} {_barre(n, total_m)}")
    if articles_avec_bloquants:
        print(f"  → {total_m / articles_avec_bloquants:.1f} reproche(s) bloquant(s) "
              "par article recalé")

    # ── 2. nature_contenu × issue ───────────────────────────────────────────
    # LE tableau à lire. Journalisé depuis le 28/08 seulement : il sera vide
    # sur l'historique, et c'est normal — le dire plutôt que de rendre un
    # tableau de zéros qu'on prendrait pour un résultat.
    avec_nature = [e for e in editoriaux if e.get("nature_contenu")]
    print(f"\n── NATURE DU CONTENU × ISSUE  ({len(avec_nature)} entrée(s) "
          "portant le champ) ──")
    if not avec_nature:
        print("  `nature_contenu` n'est journalisé que depuis le 28/08.")
        print("  ⚠ ABSENCE DE DONNÉE, PAS RÉSULTAT NUL — revenir après quelques runs.")
    else:
        par_nature = collections.defaultdict(collections.Counter)
        for e in avec_nature:
            groupe = ("opinion" if e["nature_contenu"] in NATURES_OPINION
                      else "fait")
            par_nature[groupe][e.get("statut", "?")] += 1
            par_nature[e["nature_contenu"]][e.get("statut", "?")] += 1
        print(f"  {'':22s} {'n':>4s}  {'recalés':>8s}  {'aboutis':>8s}")
        for nature in ("opinion", "fait"):
            c = par_nature.get(nature)
            if not c:
                continue
            n = sum(c.values())
            recales = sum(v for k, v in c.items() if k.startswith("rejete"))
            print(f"  {nature:22s} {n:4d}  {recales:8d}  {n - recales:8d}"
                  f"   {100*recales/n:5.1f} % recalés")
        print("\n  détail par valeur :")
        for nature, c in sorted(par_nature.items()):
            if nature in ("opinion", "fait"):
                continue
            n = sum(c.values())
            recales = sum(v for k, v in c.items() if k.startswith("rejete"))
            print(f"    {nature:24s} {n:4d}  dont {recales} recalé(s)")
        if len(avec_nature) < 30:
            print(f"\n  ⚠ n = {len(avec_nature)} : sous 30, tout écart est du "
                  "bruit. Ne poser AUCUN seuil sur ce tableau.")

    # ── 3. Contrôle de l'instrument ─────────────────────────────────────────
    # Affiché à côté du résultat, jamais à la place : un instrument qui confond
    # « aucun problème » et « aucune donnée » produit une conclusion à partir
    # de rien (leçon des quatre verdicts faux du 20/08).
    print("\n── CONTRÔLE DE L'INSTRUMENT ──")
    champs = ("bloquants_types", "bloquants_detail", "nature_contenu",
              "n_sources_pertinentes")
    for champ in champs:
        n = sum(1 for e in editoriaux if e.get(champ))
        print(f"  {champ:24s} présent sur {n:4d} / {len(editoriaux)} verdicts")
    statuts = collections.Counter(e.get("statut") for e in editoriaux)
    print("  statuts :", dict(statuts))
    print()


if __name__ == "__main__":
    main()
