# -*- coding: utf-8 -*-
"""MESURE — quels signaux prédisent le sort d'un sujet, avant génération ?

On dispose d'un jeu ÉTIQUETÉ jamais exploité : `data/verification_log.json`
contient ~285 sujets tentés depuis juillet, chacun avec son verdict final
(conforme, corrigé, rejeté qualité, rejeté sensible). Le slug étant dérivé du
titre, on peut calculer sur chaque entrée des signaux disponibles AVANT
génération et mesurer leur pouvoir prédictif.

Objectif : classer les candidats par PROMESSE plutôt que par emballage, pour que
les 6 à 12 sujets réellement tentés soient les plus prometteurs et non les
premiers d'un tri qui note la forme.

Rien n'est modifié, aucun token n'est consommé.

    python scripts/mesure_predicteurs.py
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent))

ROOT = Path(__file__).parent.parent

# Signaux calculables sur un slug/titre, tous disponibles avant génération.
SIGNAUX = {
    "victimes/pénal": (
        "mort", "morts", "tue", "victime", "seisme", "attaque", "guerre",
        "condamne", "proces", "meurtre", "inculpe", "plainte", "enquete",
        "agression", "blesse", "accident", "incendie", "epidemie", "ebola",
    ),
    "santé/médical": (
        "cancer", "vaccin", "essai-clinique", "patient", "maladie", "sante",
        "virus", "traitement", "therapie", "symptome", "demence", "alzheimer",
    ),
    "institution nommée": (
        "inserm", "insee", "cnrs", "senat", "assemblee", "gouvernement",
        "ministere", "cour-des-comptes", "commission", "oms", "ademe",
        "prefecture", "conseil", "agence", "autorite", "anses", "pasteur",
    ),
    "chiffre dans le titre": (),      # traité à part (regex)
    "question/essai": (),             # traité à part
}

QUESTION_RE = re.compile(r"(?:^|-)(?:pourquoi|comment|faut-il|est-ce|peut-on|"
                         r"doit-on|et-si|quels?|quelles?)(?:-|$)")
CHIFFRE_RE = re.compile(r"(?:^|-)\d+(?:-|$)")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower()


def signaux_de(slug: str) -> set[str]:
    n = _norm(slug)
    out = set()
    for nom, mots in SIGNAUX.items():
        if mots and any(m in n for m in mots):
            out.add(nom)
    if CHIFFRE_RE.search(n):
        out.add("chiffre dans le titre")
    if QUESTION_RE.search(n):
        out.add("question/essai")
    return out


def main() -> int:
    log = json.loads((ROOT / "data" / "verification_log.json").read_text(encoding="utf-8"))
    # Un slug peut apparaître plusieurs fois (retentatives) : on garde le
    # verdict le plus favorable, c'est celui qui décide de la publication.
    RANG = {"conforme_du_premier_coup": 0, "corrige_automatiquement": 1,
            "rejete_qualite": 2, "rejete_sensible": 3, "erreur_verification": 4,
            "a_corriger_manuellement": 5, "non_verifie": 6}
    meilleur: dict[str, str] = {}
    for e in log:
        slug, st = e.get("slug"), e.get("statut")
        if not slug or st not in RANG:
            continue
        if slug not in meilleur or RANG[st] < RANG[meilleur[slug]]:
            meilleur[slug] = st

    publiables = {"conforme_du_premier_coup", "corrige_automatiquement"}
    total = len(meilleur)
    n_pub = sum(1 for st in meilleur.values() if st in publiables)
    print(f"jeu étiqueté : {total} sujets distincts")
    print(f"taux de base « atteint la publication » : {n_pub}/{total} = {n_pub/total:.0%}\n")

    print(f"{'signal':<24} {'n':>4} {'publiables':>11} {'taux':>6}  {'écart':>7}")
    print("-" * 60)
    base = n_pub / total
    lignes = []
    for nom in list(SIGNAUX):
        avec = [s for s in meilleur if nom in signaux_de(s)]
        if len(avec) < 8:
            continue
        pub = sum(1 for s in avec if meilleur[s] in publiables)
        taux = pub / len(avec)
        lignes.append((taux - base, nom, len(avec), pub, taux))
    for ecart, nom, n, pub, taux in sorted(lignes):
        fleche = "▼" if ecart < -0.03 else ("▲" if ecart > 0.03 else "=")
        print(f"{nom:<24} {n:>4} {pub:>11} {taux:>5.0%}  {ecart:>+6.0%} {fleche}")

    print("\n=== MOTIF DE REJET DOMINANT PAR SIGNAL ===")
    for nom in list(SIGNAUX):
        avec = [s for s in meilleur if nom in signaux_de(s)]
        if len(avec) < 8:
            continue
        c = Counter(meilleur[s] for s in avec if meilleur[s] not in publiables)
        if c:
            top = c.most_common(2)
            détail = ", ".join(f"{k} ×{v}" for k, v in top)
            print(f"  {nom:<24} {détail}")

    print("\n  Lecture : un écart NÉGATIF fort désigne un signal à faire baisser")
    print("  dans le tri — ces sujets consomment des tentatives pour rien.")
    print("  Un écart positif désigne un signal à faire remonter.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
