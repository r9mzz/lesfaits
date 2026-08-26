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


def test_le_sourcing_reste_plus_strict_que_la_charte():
    """L'INTENTION du garde-fou posé le 24/08 est conservée, son critère change.

    Ce test interdisait toute valeur sous 6/5, au motif — juste — que le mandat
    d'exploitation défend d'abaisser un seuil éditorial pour faire du volume.
    Mais 6 n'était pas un niveau d'exigence : c'était une CONTRADICTION avec
    `PERTINENCE_MIN_POUR_GENERER = 3`, qui laisse passer un sujet disposant de
    3 sources pertinentes. Mesuré sur 185 articles : 19 % seulement en ont 6.
    Dans 81 % des cas, atteindre 6 suppose de citer des sources du thème
    général — le défaut « inflation » du 11/08.

    Le plancher défendu ici n'est donc plus un chiffre historique, c'est la
    CHARTE : la vitrine doit rester plus stricte qu'elle (règle 7, 3 sources),
    jamais descendre à son niveau ni en dessous. 4 sources / 3 domaines
    (décision de Nahil, 26/08) satisfont cette propriété.
    """
    assert S.MIN_SOURCES > 3, (
        f"MIN_SOURCES={S.MIN_SOURCES} : la vitrine ne peut pas être moins "
        "exigeante que la charte (règle 7 : 3 sources)")
    assert S.MIN_DISTINCT_DOMAINS <= S.MIN_SOURCES, (
        "on ne peut pas exiger plus de domaines que de sources")
    assert S.MIN_DISTINCT_DOMAINS >= 3, (
        "trois reprises d'une même dépêche ne valent pas trois sources")


if __name__ == "__main__":
    n = 0
    for nom, fn in sorted(globals().items()):
        if nom.startswith("test_"):
            fn(); n += 1; print(f"  ✓ {nom}")
    print(f"{n} tests OK")
