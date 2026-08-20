# -*- coding: utf-8 -*-
"""Diagnostic du juge sur deux populations comparables, sans mélanger les baselines.

Groupe A : articles ``conforme_du_premier_coup`` — zéro problème détecté à l'époque.
Groupe B : meilleures actus longues — elles peuvent avoir eu des problèmes initiaux.

Le ratio du groupe B ne doit jamais être présenté comme une comparaison à « zéro ».
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from dataclasses import dataclass, field

import essai_juge_corpus as base  # noqa: F401  (pose sys.path)
import verification_legacy


@dataclass
class Mesure:
    lus: int = 0
    recales: int = 0
    paires: Counter = field(default_factory=Counter)
    problemes: int = 0
    echecs: int = 0
    motifs: Counter | None = None

    def __post_init__(self) -> None:
        if self.motifs is None:
            self.motifs = Counter()


def mesurer(slugs: list[str], label: str, verification) -> Mesure:
    """Mesure une population homogène et affiche son résultat séparément."""
    m = Mesure()
    print(f"\n--- {label} ({len(slugs)} candidat(s)) ---")
    for slug in slugs:
        art = base.lire_article(slug)
        if art is None:
            print(f"  {slug[:52]:54} (illisible — ignoré)")
            continue
        fmt = base.format_publie(slug)
        try:
            rapport = verification.detecter(art, article_type=fmt)
        except Exception as exc:  # noqa: BLE001
            m.echecs += 1
            print(f"  ⚠ ERREUR  {slug[:44]:46} {type(exc).__name__}: {str(exc)[:60]}")
            continue

        m.lus += 1
        problemes = rapport.get("problemes") or []
        # ⚠ 20/08 — NE PAS réinventer la règle de blocage. Cette ligne filtrait
        # sur un champ `gravite` que le rapport ne porte PAS : elle rendait donc
        # une liste vide en permanence, et le test a annoncé « 0 recalé » sur
        # quatre passages consécutifs. Un verdict net, lisible, et sans aucun
        # rapport avec ce que le pipeline aurait décidé.
        #
        # Le pipeline décide avec `_problemes_bloquants` (croisement bloc+type,
        # périmètre affiné le 31/07 après revue éditoriale externe). On appelle
        # SA fonction : c'est la seule façon de mesurer la décision réelle, et
        # le jour où ses seuils bougent, ce test suit sans qu'on y pense — même
        # raison que le partage de `json_robuste` et de `fenetres_modeles`.
        bloquants = verification_legacy._problemes_bloquants(problemes)
        for p in problemes:
            m.paires[(p.get("bloc"), p.get("type"))] += 1
        m.problemes += len(problemes)
        m.recales += bool(bloquants)
        for p in problemes:
            m.motifs[p.get("type", "?")] += 1
        etat = "❌ RECALÉ" if bloquants else "✅ validé"
        print(f"  {etat}  [{fmt:5}] {slug[:38]:40} {len(problemes):2} problème(s), "
              f"{len(bloquants)} bloquant(s)")

    if m.echecs:
        print(f"  ⚠ {m.echecs} appel(s) en échec : exclus du dénominateur.")
    return m


def afficher_resultat(label: str, m: Mesure, baseline: str) -> None:
    if not m.lus:
        print(f"\n{label}: AUCUN article jugé — aucune conclusion possible.")
        return
    print(f"\n{label}: {m.recales}/{m.lus} recalé(s), {m.problemes} problème(s) "
          f"({m.problemes / m.lus:.1f}/article).")
    print(f"Baseline historique : {baseline}")
    for motif, n in m.motifs.most_common(6):
        print(f"  {n:3}  {motif}")

    # ── CONTRÔLE DE L'INSTRUMENT ────────────────────────────────────────────
    # Sans ceci, « 0 recalé » n'est pas un résultat : c'est peut-être un champ
    # manquant. La règle croise le TYPE et le champ `bloc` — et `bloc` est
    # rempli PAR LE MODÈLE, le prompt le lui demande. Ce test a rendu quatre
    # « 0 recalé » consécutifs sans qu'on puisse les vérifier ; on affiche
    # désormais de quoi trancher au lieu de croire le chiffre.
    _BLOQUANTS = {(1, t) for t in ("chiffre_errone", "incoherence_inter_sections",
                                   "annonce_perimee", "niveau_preuve_insuffisant",
                                   "accusation_presentee_comme_fait")} | {(2, "source_inventee")}
    sans_bloc = sum(v for (b, _), v in m.paires.items() if b is None)
    if sans_bloc:
        print(f"  ⚠ {sans_bloc} problème(s) SANS champ `bloc` : la règle de blocage ne")
        print("    peut pas s'y appliquer — « 0 recalé » serait un ARTEFACT.")
    print("  contrôle (bloc, type) :")
    for (b, t), n in m.paires.most_common(8):
        print(f"    bloc {str(b):>4}  {str(t):36} {n:3}"
              f"{'  ← BLOQUANT' if (b, t) in _BLOQUANTS else ''}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=0, help="limiter chaque population")
    args = ap.parse_args()

    zero = base.meilleurs_slugs()
    actus = base.meilleures_actus(set(zero))
    if args.max:
        zero = zero[:args.max]
        actus = actus[:args.max]
    if not zero and not actus:
        print("Aucun article exploitable dans les deux populations.")
        return 1

    import verification as V

    modele = getattr(V, "GROQ_MODEL", "?")
    print("=" * 76)
    print(f"RELECTURE DU CORPUS LLAMA — juge actuel : {modele}")
    print("Deux populations sont mesurées séparément pour ne pas attribuer au")
    print("second groupe la baseline zéro-problème du premier.")
    print("=" * 76)

    a = mesurer(zero, "GROUPE A — conformes du premier coup", V)
    b = mesurer(actus, "GROUPE B — meilleures actus longues", V)

    print("\n" + "=" * 76)
    afficher_resultat(
        "GROUPE A",
        a,
        "0 problème détecté à l'époque (conforme_du_premier_coup).",
    )
    afficher_resultat(
        "GROUPE B",
        b,
        "problemes_initiaux non nuls possibles ; ne jamais comparer ce groupe à zéro.",
    )
    print("=" * 76)
    print("INTERPRÉTATION : la sévérité du juge se lit d'abord sur le GROUPE A.")
    print("Le GROUPE B sert de contrôle sur les actus longues, pas de baseline zéro.")

    # Un diagnostic où aucune population n'a reçu de réponse ne doit jamais être vert.
    return 0 if (a.lus or b.lus) else 1


if __name__ == "__main__":
    sys.exit(main())
