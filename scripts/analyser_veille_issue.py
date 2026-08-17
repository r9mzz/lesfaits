"""Le signal de veille prédit-il l'issue du sujet ? — mesure, pas décision.

Question posée le 14/08 et restée sans réponse faute d'instrument : la veille
alimente la sélection avec un bonus de persistance, et rien n'enregistrait ce
qu'elle avait dit sur chaque sujet. Les champs `veille_*` sont journalisés
depuis le 17/08 ; ce script les croise avec l'issue réelle.

    python scripts/analyser_veille_issue.py

⚠ NE FIXE AUCUN SEUIL et n'en propose aucun. Il affiche des distributions. La
règle du projet est de ne jamais poser un seuil avant d'avoir vu la
distribution qu'il découpe — c'est celle qui a été violée trois fois sur le
filtre anti-doublon.

⚠ Tant que le nombre de sujets instrumentés est faible, tout écart lu ici est
du bruit. Le script affiche l'effectif AVANT les taux, exprès : sur n=6, un
seul sujet chanceux déplace un pourcentage de 17 points.
"""
import json
import sys
from collections import Counter
from pathlib import Path

LOG = Path("data/verification_log.json")
# Un sujet « abouti » a passé le fact-check ; les autres ont été rejetés ou
# ont échoué techniquement. On ne compte JAMAIS une panne comme un rejet
# éditorial : deux des neuf rejets du 01/08 étaient un quota épuisé et un JSON
# tronqué, journalisés sous le même statut.
ABOUTI = {"conforme_du_premier_coup", "corrige_automatiquement"}
REJET_EDITORIAL = {"rejete_qualite", "rejete_sensible"}


def _classes(valeur, bornes):
    for haut in bornes:
        if valeur < haut:
            return f"< {haut}"
    return f">= {bornes[-1]}"


def main() -> int:
    if not LOG.exists():
        print("journal absent — rien à mesurer")
        return 0
    entrees = json.loads(LOG.read_text(encoding="utf-8"))
    avec = [e for e in entrees
            if isinstance(e, dict) and e.get("veille_heures_visible") is not None]

    print("=" * 74)
    print(f"SIGNAL DE VEILLE × ISSUE — {len(avec)} sujet(s) instrumenté(s) "
          f"sur {len(entrees)} entrées")
    print("=" * 74)
    if not avec:
        print("\n  Aucun sujet ne porte encore le signal de veille.")
        print("  L'instrumentation date du 17/08 : il faut quelques runs.")
        return 0
    if len(avec) < 30:
        print(f"\n  ⚠ EFFECTIF FAIBLE ({len(avec)}). Ne rien conclure : sur un si petit")
        print("  nombre, un seul sujet déplace tous les taux. Relire dans quelques runs.")

    for champ, bornes, libelle in (
        ("veille_heures_visible", [2, 6, 12, 24], "PERSISTANCE (heures dans les fils)"),
        ("veille_n_flux_grappe", [2, 3, 5, 8], "NOMBRE DE FLUX de la grappe"),
        ("veille_age_h", [12, 24, 36], "ÂGE du sujet (heures)"),
    ):
        print(f"\n  {libelle}")
        print(f"    {'tranche':>10}  {'n':>4}  {'aboutis':>8}  {'rejets édito':>13}")
        paquets: dict[str, Counter] = {}
        for e in avec:
            v = e.get(champ)
            if v is None:
                continue
            c = paquets.setdefault(_classes(float(v), bornes), Counter())
            if e.get("statut") in ABOUTI:
                c["abouti"] += 1
            elif e.get("statut") in REJET_EDITORIAL:
                c["rejet"] += 1
            else:
                c["technique"] += 1
        for tranche in sorted(paquets, key=lambda s: float(s.split()[-1])):
            c = paquets[tranche]
            n = c["abouti"] + c["rejet"]
            taux = f"{100 * c['abouti'] / n:.0f} %" if n else "—"
            print(f"    {tranche:>10}  {n:>4}  {c['abouti']:>4} ({taux:>5})  {c['rejet']:>13}")

    print("\n  La question à laquelle ces tableaux répondront :")
    print("  le taux d'aboutissement MONTE-T-IL avec la persistance ou le nombre")
    print("  de flux ? Si oui, le bonus de veille mérite plus de poids dans")
    print("  `score_editorial`. Si les colonnes sont plates, il n'en mérite pas.")
    print("  Aucun seuil ne doit être fixé avant que ces colonnes soient lisibles.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
