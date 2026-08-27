"""Un reproche qui exige la RÉPÉTITION d'une réserve déjà écrite ne bloque plus.

Relecture à la main des 26 reproches bloquants du run 285 : 4 fondés, 17
infondés, 5 indécidables. Sept reproches — 27 % — réclamaient qu'une réserve
DÉJÀ présente soit reprise ailleurs, ce que la règle 1 de la charte interdit
(une idée = une seule apparition). On rejetait donc des articles parce qu'ils
respectent la charte.

⚠ CE FICHIER DOIT AUTANT PROUVER CE QUI EST ÉCARTÉ QUE CE QUI RESTE BLOQUANT.
Un garde-fou de ce type se transforme en desserrage silencieux dès qu'il attrape
un cas de trop : les tests de non-écartement (`_reste_bloquant`) sont donc la
moitié qui compte. Les descriptions sont les VRAIES, copiées du journal du run
285, jamais reformulées — une paraphrase testerait ma reformulation, pas le
juge.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import verification_legacy as V  # noqa: E402

ARTICLE = {
    "resume": "L'écart de production atteint 8,5 %.",
    "corps": {
        "faits": ("Selon l'analyse, exploratoire et observationnelle, de "
                  "l'institut, l'écart est mesuré depuis fin 2019."),
        "contexte": "Le contexte macroéconomique est dégradé.",
        "nuances": "Ces estimations restent préliminaires.",
    },
}


def _bloquant(type_, description, bloc=1, phrase=""):
    return {"bloc": bloc, "type": type_, "description": description, "phrase": phrase}


def _ecarte(p, article=ARTICLE):
    return V._problemes_bloquants([p], article) == []


def _reste_bloquant(p, article=ARTICLE):
    return V._problemes_bloquants([p], article) == [p]


# ── Ce qui doit être ÉCARTÉ — reproches réels du run 285 ────────────────────

def test_aveu_de_presence_dans_les_faits():
    """« ce qui est POURTANT MENTIONNÉ dans les faits » (reproche 25)."""
    p = _bloquant("niveau_preuve_insuffisant",
                  "La phrase ne précise pas explicitement que l'étude est de "
                  "nature exploratoire et observationnelle, ce qui est pourtant "
                  "mentionné dans les faits et dans la source [1].")
    assert _ecarte(p)


def test_reserve_deja_soulignee_dans_les_faits():
    """« limites méthodologiques DÉJÀ SOULIGNÉES dans les faits » (reproche 26)."""
    p = _bloquant("niveau_preuve_insuffisant",
                  "La phrase utilise le verbe 'suggère' sans rappeler que cette "
                  "suggestion repose sur une étude observationnelle et "
                  "exploratoire, ce qui minimise les limites méthodologiques "
                  "déjà soulignées dans les faits et la source [1].")
    assert _ecarte(p)


def test_precision_donnee_puis_reprochee():
    """« Cette précision EST DONNÉE, mais… » (reproche 23)."""
    p = _bloquant("niveau_preuve_insuffisant",
                  "Cette précision est donnée dans l'article, mais elle n'est "
                  "pas intégrée de manière systématique dans la phrase "
                  "précédente, qui reste trop affirmative.")
    assert _ecarte(p)


def test_terme_present_dans_le_corps_simple_reprise():
    """Pas d'aveu, mais « exploratoire » est bien dans le corps (reproche 15/16).

    C'est le cas qui EXIGE l'article : sur la seule description, rien ne prouve
    que l'article porte la réserve.
    """
    p = _bloquant("niveau_preuve_insuffisant",
                  "La source [2] précise que ces chiffres sont des « estimations "
                  "exploratoires », mais cette nuance méthodologique n'est pas "
                  "intégrée systématiquement dans l'article (ex. : reprise dans "
                  "le résumé sans cette réserve).")
    assert _ecarte(p)


def test_chiffre_declare_correct_sous_motif_errone():
    """« Le chiffre de 8,5 % EST CORRECT, mais… » (reproche 8)."""
    p = _bloquant("chiffre_errone",
                  "Le chiffre de 8,5 % est correct, mais le résumé omet de "
                  "préciser que cet écart est mesuré 'depuis fin 2019'.")
    assert _ecarte(p)


# ── Ce qui doit RESTER BLOQUANT — les 4 fondés du run 285 ───────────────────

def test_chiffre_absent_des_extraits_reste_bloquant():
    """Reproche 12 : un chiffre que la source ne donne pas. Règle 5."""
    p = _bloquant("chiffre_errone",
                  "La source [5] ne fournit pas explicitement les chiffres du "
                  "déficit public (5,8 %) ou de la dette (113 %) pour 2024. Ces "
                  "données ne sont pas confirmées par les extraits fournis.")
    assert _reste_bloquant(p)


def test_renvoi_de_citation_faux_reste_bloquant():
    """Reproche 24 : [4] pointe vers la source numérotée 2."""
    p = _bloquant("source_inventee",
                  "Le renvoi [4] est utilisé dans l'article, mais la source "
                  "correspondante dans le tableau est numérotée 2. Le renvoi "
                  "est donc incorrect.", bloc=2)
    assert _reste_bloquant(p)


def test_interpretation_non_attribuee_reste_bloquante():
    """Reproche 20 : une analyse du Sénat présentée sans le dire."""
    p = _bloquant("accusation_presentee_comme_fait",
                  "La phrase attribue la réticence de la BEI à des raisons sans "
                  "préciser que cette interprétation émane du Sénat.")
    assert _reste_bloquant(p)


# ── Les bords qui empêchent le garde-fou de devenir un desserrage ───────────

def test_reserve_absente_du_corps_reste_bloquante():
    """LE test central. Même formulation exacte que le cas écarté plus haut,
    mais le terme réclamé n'est NULLE PART dans l'article : le reproche est
    alors une vraie omission et doit bloquer."""
    article = {"resume": "Un résumé.",
               "corps": {"faits": "Des faits sans la moindre réserve.",
                         "contexte": "", "nuances": ""}}
    p = _bloquant("niveau_preuve_insuffisant",
                  "La source [2] précise que ces chiffres sont des « estimations "
                  "exploratoires », mais cette nuance n'est pas reprise dans le "
                  "résumé.")
    assert _reste_bloquant(p, article)


def test_sans_article_on_ne_prouve_rien_donc_on_bloque():
    """Appelé sans article (essai_juge_corpus, vieux appels), le garde-fou ne
    peut RIEN prouver sur le corps : il doit se taire, pas deviner."""
    p = _bloquant("niveau_preuve_insuffisant",
                  "cette nuance n'est pas reprise dans le résumé, alors que la "
                  "source la qualifie d'exploratoire.")
    assert V._problemes_bloquants([p]) == [p]


def test_aveu_portant_sur_la_source_seule_ne_suffit_pas():
    """« déjà mentionné DANS LA SOURCE » ne dit pas que l'ARTICLE le porte.
    C'est la distinction qui sépare ce garde-fou d'un blanc-seing."""
    article = {"resume": "Un résumé.",
               "corps": {"faits": "Des faits.", "contexte": "", "nuances": ""}}
    p = _bloquant("niveau_preuve_insuffisant",
                  "La limite est déjà mentionnée dans la source [3], mais "
                  "l'article ne la reprend jamais.")
    assert _reste_bloquant(p, article)


def test_omission_de_fond_sans_demande_de_reprise_reste_bloquante():
    """Une omission franche, sans vocabulaire de répétition, bloque."""
    p = _bloquant("niveau_preuve_insuffisant",
                  "L'article présente ces effets comme établis alors qu'aucun "
                  "chiffre ne les étaye dans les extraits fournis.")
    assert _reste_bloquant(p)


def test_signature_reste_compatible_avec_un_seul_argument():
    """`_problemes_bloquants(problemes)` est appelé sans article à sept endroits
    du dépôt (essai_juge_corpus, tests, backtests). La signature ne doit pas
    casser."""
    assert V._problemes_bloquants([]) == []


if __name__ == "__main__":
    n = 0
    for nom, fn in sorted(globals().items()):
        if nom.startswith("test_"):
            fn(); n += 1; print(f"  ✓ {nom}")
    print(f"{n} tests OK")
