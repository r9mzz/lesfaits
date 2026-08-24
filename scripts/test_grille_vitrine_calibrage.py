"""Verrouille le recalibrage du 21/08 de la grille vitrine.

Le défaut corrigé : `MIN_WORDS["total"] = 760` rejetait 140 articles publiés
sur 140, le maximum jamais atteint par le site étant 670 mots. Un article
franchissait tout le protocole — génération, relances, garde-fous, fact-check
3 passes — pour mourir sur un seuil que rien n'avait jamais atteint.

Ce test ne fige pas les valeurs : il vérifie la PROPRIÉTÉ qui manquait, à
savoir qu'un seuil de publication reste atteignable par la production réelle.
Figer 400 le rendrait cassant au prochain arbitrage éditorial, pour rien.
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
    """Aucun seuil ne doit dépasser le MAXIMUM jamais produit par le site.

    C'est la propriété violée avant le 21/08, et elle est plus forte qu'un
    simple « le seuil est bas » : un seuil au-dessus du maximum observé ne
    sélectionne pas les meilleurs articles, il les rejette tous.
    """
    for cle, (_, _, _, maxi) in CORPUS.items():
        seuil = S.MIN_WORDS[cle]
        assert seuil <= maxi, (
            f"{cle} : seuil vitrine {seuil} > maximum jamais atteint {maxi} — "
            "inatteignable par construction")


def test_le_total_reste_selectif():
    """La vitrine doit trancher, pas tout laisser passer.

    Borne basse : au-dessus du 33e percentile, sinon elle cesse de filtrer.
    C'est le calibrage retenu le 12/08 pour la grille brève (« écarter le
    tiers inférieur »), repris ici pour l'article.
    """
    assert S.MIN_WORDS["total"] >= CORPUS["total"][1], (
        "seuil total sous le tiers inférieur du corpus : la vitrine ne "
        "sélectionne plus rien")


def test_les_sections_ne_contredisent_pas_le_total():
    """faits+contexte+nuances ne peut pas exiger plus que le total.

    Une somme de minima supérieure au minimum du total rend le seuil `total`
    décoratif : c'est la somme qui décide, en silence. Même famille de défaut
    que le plancher de prompt du 15/08 — une contrainte déplacée ailleurs.
    """
    somme = sum(S.MIN_WORDS[k] for k in ("faits", "contexte", "nuances"))
    assert somme <= S.MIN_WORDS["total"], (
        f"sections {somme} mots > total {S.MIN_WORDS['total']} : le seuil "
        "total ne décide plus de rien")


def test_les_criteres_non_longueur_sont_intacts():
    """Le recalibrage ne desserre QUE la longueur.

    Boohoo échouait aussi sur « 0 primaire » et « sources listées mais non
    citées » — ces reproches sont fondés et doivent continuer de rejeter.
    """
    assert S.MIN_SOURCES == 6
    assert S.MIN_DISTINCT_DOMAINS == 5


if __name__ == "__main__":
    n = 0
    for nom, fn in sorted(globals().items()):
        if nom.startswith("test_"):
            fn(); n += 1; print(f"  ✓ {nom}")
    print(f"{n} tests OK")
