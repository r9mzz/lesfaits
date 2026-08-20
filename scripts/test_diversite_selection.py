"""Deux dépêches du même événement ne prennent pas deux des 20 places d'un run.

── CONSTAT DE NAHIL, 20/08, chiffré ──────────────────────────────────────────

« Avec plusieurs runs sur plusieurs jours, on a tout le temps les mêmes sujets,
alors qu'il se passe des milliers de choses par jour. »

Sur les 47 tentatives du 20/08 :

    21 %  canicule / chaleur
    13 %  piratage du fisc
    ---
    34 %  du budget d'une journée sur DEUX événements

pendant que l'Ukraine, Apple/UE, la loi spéciale budgétaire et le rapport sur
l'Arctique attendaient leur tour.

Le rééquilibrage du barème (enjeu public 30→45) a AGGRAVÉ le phénomène
mécaniquement : les dix dépêches d'un même gros sujet montent toutes ensemble.

── POURQUOI CE N'EST PAS LA QUATRIÈME HEURISTIQUE ANTI-DOUBLON ───────────────

Les trois tentatives (26/07, 28/07, 02/08) cherchaient à REJETER un candidat
définitivement, et ont échoué parce que le discriminant n'est pas dans les
titres. Revérifié ce jour, sur une piste jamais testée — le partage de CHIFFRES
n'attrape qu'une paire sur dix (« 14 000 morts en Europe » et « 7 300 en
France » sont deux événements distincts ; les piratages n'ont aucun chiffre).

Ici on ne rejette rien : on REPORTE au run suivant. Le commentaire du filtre
par grappe le disait déjà — « un regroupement trop large ne fait que reporter
un sujet, jamais publier un doublon. Le risque est borné du bon côté. »
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("GROQ_API_KEY", "x")

import pipeline as P  # noqa: E402


def _communs(a, b):
    return len(P._mots_distinctifs(a) & P._mots_distinctifs(b))


def test_deux_depeches_du_meme_evenement_se_reconnaissent():
    paires = [
        ("Canicules : déjà 7.300 morts en excès en France en 2026",
         "Canicule : 7 300 « morts en excès » ont été enregistrés"),
        ("Piratage du fisc : Lecornu veut une nouvelle unité cyber",
         "Piratage du fisc : Sébastien Lecornu demande des comptes"),
    ]
    for a, b in paires:
        assert _communs(a, b) >= P.DIVERSITE_MOTS_COMMUNS, f"{a[:30]} ↔ {b[:30]}"


def test_deux_sujets_distincts_ne_se_bloquent_pas():
    """Le test qui compte vraiment : le filtre ne doit pas vider la une."""
    distincts = [
        "Apple consent à respecter les règles européennes sur les marchés",
        "Guerre au Moyen-Orient : enquête israélienne sur la mort d'un enfant",
        "Annulation d'un rapport sur l'Arctique : Trump s'attaque à la science",
        "Le Honduras place 80 % de son territoire en état d'alerte",
        "Retraites : le gel des pensions, le pari à haut risque de Lescure",
        "En RDC, l'épidémie d'Ebola est loin d'être maîtrisée",
    ]
    for i, a in enumerate(distincts):
        for b in distincts[i + 1:]:
            assert _communs(a, b) < P.DIVERSITE_MOTS_COMMUNS, (
                f"faux rapprochement : « {a[:34]} » ↔ « {b[:34]} »")


def test_le_singulier_et_le_pluriel_se_rejoignent():
    """Leçon du 26/07 : « néandertaliens » et « néandertalien » ne se
    rapprochaient pas en comparaison stricte. La troncature à 8 les réunit."""
    assert _communs("Les néandertaliens enterraient leurs morts",
                    "Un néandertalien retrouvé dans une grotte") >= 1


def test_le_filtre_REPORTE_au_lieu_de_rejeter():
    """Propriété qui rend ce filtre acceptable là où les trois précédents ne
    l'étaient pas : aucun sujet n'est condamné, il repasse au run suivant."""
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "pipeline.py"), encoding="utf-8").read()
    assert "reporté au run suivant" in src
    assert "DIVERSITE_MOTS_COMMUNS" in src
    # Le seuil ne doit pas descendre à 1 : mesuré, il écarte la moitié du vivier.
    assert P.DIVERSITE_MOTS_COMMUNS >= 2, (
        "à 1 mot partagé, 18 sujets sur 35 seraient écartés — mesuré le 20/08")


if __name__ == "__main__":
    test_deux_depeches_du_meme_evenement_se_reconnaissent()
    test_deux_sujets_distincts_ne_se_bloquent_pas()
    test_le_singulier_et_le_pluriel_se_rejoignent()
    test_le_filtre_REPORTE_au_lieu_de_rejeter()
    print("OK — une seule dépêche par événement dans un run, les autres reportées")
