"""Verrouille le recalibrage du 21/08 de la grille vitrine.

Le défaut corrigé : `MIN_WORDS["total"] = 760` rejetait 140 articles publiés
sur 140, le maximum jamais atteint par le site étant 670 mots. Un article
franchissait tout le protocole — génération, relances, garde-fous, fact-check
3 passes — pour mourir sur un seuil que rien n'avait jamais atteint.

Ce test ne fige pas les valeurs de longueur : il vérifie la PROPRIÉTÉ qui
manquait, à savoir qu'un seuil de publication reste atteignable par la
production réelle. Les minima de sourcing, eux, ont un plancher éditorial
historique explicite : ils ne doivent jamais être abaissés pour faire du volume.
"""
import showcase_quality as S

# Distribution mesurée le 21/08 sur les 140 articles longs publiés, sections
# comptées une à une. `total` = faits+contexte+nuances, CHAPEAU EXCLU — c'est
# la grandeur que la grille additionne réellement (vérifié sur le run 258 :
# Boohoo, 461 mots au journal, 435 comptés par la vitrine).
CORPUS = {           # min   p33  médiane   max
    "faits":    (48, 135, 150, 345),
    "contexte": (25, 106, 119, 185),
    "nuances":  (16,  91, 104, 172),
    "total":   (158, 327, 372, 670),
}


def test_chaque_seuil_est_atteignable():
    """Aucun seuil ne doit dépasser le MAXIMUM jamais produit par le site."""
    for cle, (_, _, _, maxi) in CORPUS.items():
        seuil = S.MIN_WORDS[cle]
        assert seuil <= maxi, (
            f"{cle} : seuil vitrine {seuil} > maximum jamais atteint {maxi} — "
            "inatteignable par construction")


def test_le_total_reste_selectif():
    """La vitrine doit trancher, pas tout laisser passer."""
    assert S.MIN_WORDS["total"] >= CORPUS["total"][1], (
        "seuil total sous le tiers inférieur du corpus : la vitrine ne "
        "sélectionne plus rien")


def test_les_sections_ne_contredisent_pas_le_total():
    """faits+contexte+nuances ne peut pas exiger plus que le total."""
    somme = sum(S.MIN_WORDS[k] for k in ("faits", "contexte", "nuances"))
    assert somme <= S.MIN_WORDS["total"], (
        f"sections {somme} mots > total {S.MIN_WORDS['total']} : le seuil "
        "total ne décide plus de rien")


def test_les_criteres_non_longueur_sont_intacts():
    """Le recalibrage de longueur ne desserre QUE la longueur."""
    assert S.MIN_DISTINCT_DOMAINS <= S.MIN_SOURCES, (
        "exiger plus de domaines distincts que de sources est "
        "arithmétiquement impossible")


# ⚠ Les deux bords du sourcing vivent désormais dans
# `test_showcase_source_floor_mandate.py`, avec l'arbitrage de Nahil du 28/08 et
# la mesure qui le fonde. Ne pas les redupliquer ici : c'est la duplication qui
# a permis quatre annulations successives sans qu'aucune ne voie la mesure.


if __name__ == "__main__":
    n = 0
    for nom, fn in sorted(globals().items()):
        if nom.startswith("test_"):
            fn(); n += 1; print(f"  ✓ {nom}")
    print(f"{n} tests OK")
