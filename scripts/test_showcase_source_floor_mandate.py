#!/usr/bin/env python3
"""Le rendement ne peut pas desserrer la vitrine — mais un seuil impossible
n'est pas un garde-fou.

⚠ ARBITRAGE DE NAHIL, 28/08. Ce fichier gelait `MIN_SOURCES >= 6` et rendait
sa décision (« Mets 4 », puis « Confirme 4 ») inapplicable sans faire échouer
la CI. Il n'est PAS supprimé : la propriété qu'il défend est juste et reste
verrouillée ci-dessous. C'est son CRITÈRE qui change — une mesure remplace un
chiffre historique.

CE QUI EST CONSERVÉ, mot pour mot, de l'intention d'origine : une mesure de
volume ou de rendement ne peut pas justifier d'abaisser la porte éditoriale
finale au niveau de la charte. `test_la_vitrine_reste_plus_exigeante_que_la_charte`
l'interdit toujours, et 3 échoue.

CE QUI EST AJOUTÉ, et qui manquait : un seuil que la production n'atteint
JAMAIS ne sélectionne pas, il éteint. Mesuré sur les articles ayant franchi le
fact-check 3 passes en entier — à 6, un sur dix survit ; le site n'a rien
publié depuis le 14/08.

⚠ POURQUOI « corriger en amont » ne s'applique pas ici, et c'est le point que
les quatre annulations n'ont pas traité :

    sources TROUVÉES par la recherche       médiane 10
    sources jugées PERTINENTES par le juge  médiane  3

Le sourcing ramène déjà dix documents. C'est le juge de pertinence qui n'en
retient que trois sur le sujet précis. Exiger six citations oblige à citer du
hors-sujet — exactement ce que ce juge existe pour empêcher. Avant de reposer
6, il faut infirmer CETTE mesure, pas réaffirmer le principe.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("GROQ_MODEL_OVERRIDE", "mistral-large-latest")

import pipeline  # noqa: E402
import showcase_quality as S  # noqa: E402

# Sources CITÉES par les articles ayant passé le fact-check 3 passes en entier,
# relevé le 28/08 dans `verification_log.json` (statut `corrige_automatiquement`).
# ⚠ n = 10 : ordre de grandeur, pas réglage fin.
SOURCES_ARTICLES_VALIDES = {3: 6, 4: 1, 5: 2, 8: 1}


def test_le_rendement_ne_peut_pas_abaisser_la_vitrine_au_niveau_de_la_charte():
    """La propriété d'origine de ce fichier, conservée telle quelle."""
    plancher = pipeline.SEUILS_FORMAT["article"]["sources"]
    assert S.MIN_SOURCES > plancher, (
        f"MIN_SOURCES={S.MIN_SOURCES} n'est pas au-dessus du plancher de la "
        f"charte ({plancher}) : la vitrine n'exigerait plus rien de plus "
        "qu'un article ordinaire, ce que le mandat interdit")
    assert S.MIN_DISTINCT_DOMAINS >= 3
    assert S.MIN_DISTINCT_DOMAINS <= S.MIN_SOURCES


def test_le_seuil_ne_peut_pas_fermer_la_publication():
    """Le bord qui manquait, et qui aurait évité quatre allers-retours."""
    survivants = sum(n for src, n in SOURCES_ARTICLES_VALIDES.items()
                     if src >= S.MIN_SOURCES)
    total = sum(SOURCES_ARTICLES_VALIDES.values())
    assert survivants / total >= 0.35, (
        f"MIN_SOURCES={S.MIN_SOURCES} ne laisse passer que {survivants}/{total} "
        f"({100*survivants/total:.0f} %) des articles ayant franchi le "
        "fact-check 3 passes. À ce niveau la grille ne mesure plus la qualité "
        "rédactionnelle mais le rendement du juge de pertinence.")


if __name__ == "__main__":
    n = 0
    for nom, fn in sorted(globals().items()):
        if nom.startswith("test_"):
            fn(); n += 1; print(f"  ✓ {nom}")
    print(f"{n} tests OK")
