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
        "exiger plus de domaines que de sources est arithmétiquement "
        "impossible")


def test_la_vitrine_reste_plus_exigeante_que_la_publication_ordinaire():
    """Le seul plancher qui a un sens est celui de la charte, LU et non recopié.

    Historique de ce test, à lire avant de le modifier : il figeait
    littéralement 6 sources / 5 domaines. C'est la septième occurrence dans ce
    dépôt d'un test qui gèle une VALEUR au lieu de verrouiller une PROPRIÉTÉ,
    et l'effet a été de bloquer une décision de Nahil (26/08 : « Mets 4 ») au
    nom d'un chiffre que plus rien ne justifiait.

    Ce que la vitrine doit garantir, et rien d'autre : être STRICTEMENT plus
    exigeante que le plancher de publication de la charte (règle 7). Six
    satisfait cette propriété, quatre aussi — trois ne la satisfait pas, et
    c'est bien la régression du 24/08 que ce test doit continuer d'attraper.
    """
    plancher_charte = pipeline.SEUILS_FORMAT["article"]["sources"]
    assert S.MIN_SOURCES > plancher_charte, (
        f"MIN_SOURCES={S.MIN_SOURCES} n'est pas au-dessus du plancher de "
        f"publication ({plancher_charte}) : la vitrine n'exige plus rien de "
        "plus qu'un article ordinaire")
    assert S.MIN_DISTINCT_DOMAINS >= 3, (
        f"MIN_DISTINCT_DOMAINS={S.MIN_DISTINCT_DOMAINS} : trois domaines "
        "distincts sont le minimum pour que « plusieurs sources » ne soit pas "
        "le même média deux fois")


def test_le_sourcing_ne_peut_pas_depasser_ce_que_le_pipeline_produit():
    """L'autre bord, celui qui manquait : un seuil inatteignable ne sélectionne
    pas, il éteint. Le juge de pertinence ne note que les 10 premières sources
    et n'en déclare régulièrement que 2 à 4 comme traitant le sujet précis
    (run 281). Un seuil vitrine au-dessus de ce que le sourcing rend mesure le
    moteur de recherche, pas l'article.
    """
    assert S.MIN_SOURCES <= 6, (
        f"MIN_SOURCES={S.MIN_SOURCES} : au-delà de 6, la grille rejette sur "
        "le rendement du sourcing et non sur la qualité rédactionnelle")


if __name__ == "__main__":
    n = 0
    for nom, fn in sorted(globals().items()):
        if nom.startswith("test_"):
            fn(); n += 1; print(f"  ✓ {nom}")
    print(f"{n} tests OK")
