"""Un article d'actualité sans aucune date ne situe pas son fait.

── MESURÉ LE 20/08 sur les 174 articles publiés ──────────────────────────────

    juin 35 %  ·  juillet 47 %  ·  août 50 %  ·  ensemble 43 %

Stable, aucune amélioration au fil des mois. Cas d'école,
`additifs-alimentaires-risque-sante` : « L'Inserm rapporte que TROIS NOUVELLES
ÉTUDES montrent des associations… » — pas une date, pas une année. Le lecteur
ne sait pas si le fait date de la semaine ou de 2019, sur un site dont
l'argument est précisément la vérifiabilité.

⚠ AVERTISSEMENT SEUL, et c'est la mesure qui l'impose, pas la prudence : à
43 % du corpus, bloquer rejetterait près d'un article sur deux, et brancher le
contrôle sur la relance corrective ferait payer un aller-retour Groq à presque
chaque sujet. Règle du projet : « précision > rappel sur les garde-fous à
relance ». On journalise d'abord, on décide ensuite sur des chiffres.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("GROQ_API_KEY", "x")

import pipeline as P  # noqa: E402


def _art(faits, contexte="", nuances=""):
    return {"corps": {"faits": faits, "contexte": contexte, "nuances": nuances}}


def test_le_cas_ecole_du_corpus_est_attrape():
    a = _art("L'Inserm rapporte que trois nouvelles études montrent des "
             "associations entre additifs et risque accru de cancer.")
    assert P.article_sans_date(a)


def test_une_date_explicite_suffit():
    for phrase in (
        "L'Inserm a publié le 12 août 2026 trois études.",
        "Le rapport de 2024 chiffrait déjà le phénomène.",
        "Le 1er septembre, la mesure entrera en vigueur.",
    ):
        assert not P.article_sans_date(_art(phrase)), phrase


def test_les_reperes_relatifs_comptent_aussi():
    """« ce mardi », « hier » situent le fait — refuser ces formes pousserait à
    une écriture administrative, alors que la charte veut du français lisible."""
    for phrase in ("Le ministère a annoncé la mesure ce mardi.",
                   "La décision a été rendue hier.",
                   "Le vote a eu lieu jeudi 14."):
        assert not P.article_sans_date(_art(phrase)), phrase


def test_une_date_dans_le_contexte_suffit():
    """Le repère peut vivre dans n'importe quelle section : exiger qu'il soit
    dans « faits » serait une contrainte de forme, pas d'information."""
    assert not P.article_sans_date(
        _art("Le dispositif est critiqué.", contexte="Créé en 2019, il visait…"))


def test_le_controle_reste_un_AVERTISSEMENT():
    """Ne jamais le promouvoir en bloquant sans avoir d'abord fait baisser le
    taux côté prompt. À 43 %, bloquer rejetterait un article sur deux."""
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "pipeline.py"), encoding="utf-8").read()
    assert '("article_sans_date", article_sans_date' in src, (
        "le contrôle n'est plus branché dans _CONTROLES_AVERTISSEMENT")
    i = src.index("_CONTROLES_AVERTISSEMENT = [")
    fin = src.index("]", i)
    assert "article_sans_date" in src[i:fin], (
        "article_sans_date a quitté la liste des AVERTISSEMENTS — s'il est "
        "devenu bloquant ou relançable, la mesure des 43 % doit être refaite")


if __name__ == "__main__":
    test_le_cas_ecole_du_corpus_est_attrape()
    test_une_date_explicite_suffit()
    test_les_reperes_relatifs_comptent_aussi()
    test_une_date_dans_le_contexte_suffit()
    test_le_controle_reste_un_AVERTISSEMENT()
    print("OK — absence de date journalisée en avertissement, jamais bloquante")
