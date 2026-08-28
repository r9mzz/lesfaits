"""Verrouille le recalibrage du 21/08 de la grille vitrine.

Le défaut corrigé : `MIN_WORDS["total"] = 760` rejetait 140 articles publiés
sur 140, le maximum jamais atteint par le site étant 670 mots. Un article
franchissait tout le protocole — génération, relances, garde-fous, fact-check
3 passes — pour mourir sur un seuil que rien n'avait jamais atteint.

Ce test ne fige AUCUNE valeur : il vérifie la propriété qui manquait, à savoir
qu'un seuil de publication reste atteignable par la production réelle.

⚠ CETTE RÈGLE VAUT AUSSI POUR LE SOURCING, et c'est le changement du 28/08.
Les versions précédentes gelaient « MIN_SOURCES >= 6 » comme un plancher
historique. Résultat : la décision de Nahil de le porter à 4 a été annulée
TROIS fois par des sessions parallèles (24/08, 26/08 à 03h23, 26/08 à 15h37),
chaque fois de bonne foi, au nom du mandat « ne jamais affaiblir un garde-fou ».
Le mandat est le bon ; un test qui gèle une valeur ne dit pas si elle protège
quoi que ce soit. Celui-ci mesure.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("GROQ_MODEL_OVERRIDE", "mistral-large-latest")

import pipeline  # noqa: E402
import showcase_quality as S  # noqa: E402

# Distribution mesurée le 21/08 sur les 140 articles longs publiés, sections
# comptées une à une. `total` = faits+contexte+nuances, CHAPEAU EXCLU — c'est
# la grandeur que la grille additionne réellement (vérifié sur le run 258 :
# Boohoo, 461 mots au journal, 435 comptés par la vitrine).
# Sources CITÉES par les articles ayant franchi le fact-check 3 passes EN
# ENTIER — relevé le 28/08 dans `verification_log.json` (statut
# `corrige_automatiquement`). C'est la population que la grille vitrine filtre
# réellement. La mesurer contre le corpus PUBLIÉ n'aurait aucun sens : le site
# ne publie plus rien depuis le 14/08, et c'est précisément ce qu'on répare.
#
# ⚠ n = 10, c'est peu, et aucun réglage fin ne doit s'y appuyer. Ce que ces
# chiffres établissent est un ORDRE DE GRANDEUR : à 6, un article sur dix
# survit. C'est cet écart-là qui est actionnable, pas la deuxième décimale.
SOURCES_ARTICLES_VALIDES = {3: 6, 4: 1, 5: 2, 8: 1}   # sources -> n articles

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
    assert S.MIN_DISTINCT_DOMAINS >= 3, (
        f"MIN_DISTINCT_DOMAINS={S.MIN_DISTINCT_DOMAINS} : sous 3, « plusieurs "
        "sources » peut être le même média deux fois")


def test_la_vitrine_reste_plus_exigeante_que_la_charte():
    """Le bord BAS, celui que les annulations voulaient protéger — et il est
    conservé. La vitrine doit exiger STRICTEMENT plus que le plancher de
    publication ordinaire, lu dans SEUILS_FORMAT et jamais recopié.
    """
    plancher = pipeline.SEUILS_FORMAT["article"]["sources"]
    assert S.MIN_SOURCES > plancher, (
        f"MIN_SOURCES={S.MIN_SOURCES} n'est pas au-dessus du plancher de la "
        f"charte ({plancher}) : la vitrine n'exige plus rien de plus qu'un "
        "article ordinaire")


def test_le_seuil_ne_peut_pas_fermer_la_publication():
    """Le bord HAUT, celui qui manquait, et qui aurait arrêté trois annulations.

    Un seuil que la production n'atteint jamais ne SÉLECTIONNE pas : il éteint.
    Le critère n'est ni 4 ni 6 — c'est la part des articles ayant franchi tout
    le protocole éditorial que la grille laisse encore passer.
    """
    survivants = sum(n for src, n in SOURCES_ARTICLES_VALIDES.items()
                     if src >= S.MIN_SOURCES)
    total = sum(SOURCES_ARTICLES_VALIDES.values())
    part = survivants / total
    assert part >= 0.35, (
        f"MIN_SOURCES={S.MIN_SOURCES} ne laisse passer que {survivants}/{total} "
        f"({100*part:.0f} %) des articles ayant passé le fact-check 3 passes. "
        "À ce niveau la grille ne mesure plus la qualité rédactionnelle mais "
        "le rendement du moteur de recherche, et elle ferme la publication.")


if __name__ == "__main__":
    n = 0
    for nom, fn in sorted(globals().items()):
        if nom.startswith("test_"):
            fn(); n += 1; print(f"  ✓ {nom}")
    print(f"{n} tests OK")
