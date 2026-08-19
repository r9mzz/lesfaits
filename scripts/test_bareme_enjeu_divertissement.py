"""Le barème doit séparer une cyberattaque d'État d'un casque gaming.

Constat de Nahil sur le run 241 du 19/08 : « Piratage du fisc : Mathilde Panot
demande des comptes » sortait à 60 points, à égalité EXACTE avec « Votre setup
mérite mieux : ce casque gaming change tout », et devant « Dune 3 : voici ce
que vous allez rater » à 50.

Mesuré : ce n'était pas un réglage trop mou, c'étaient deux angles morts.

    _ENJEU_PUBLIC_RE  ne connaissait RIEN du champ cyber / données personnelles
    _DIVERTISSEMENT_RE ne connaissait ni « film », ni « cinéma », ni « gaming »

Zéro bonus d'un côté, zéro malus de l'autre : l'égalité était structurelle, pas
accidentelle. Ces tests ne fixent pas de seuil — ils vérifient que le signal
EXISTE, ce qui n'était pas le cas.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("GROQ_API_KEY", "x")

import pipeline as P  # noqa: E402

_PAD = (" Le détail de l'affaire est rapporté par plusieurs rédactions et les "
        "éléments connus à ce stade sont précisés ci-dessous.") * 4


def _score(titre, contenu, source="franceinfo"):
    s, r = P.score_editorial(
        {"title": titre, "content": contenu + _PAD, "link": "https://exemple.fr/a"},
        source, set())
    return s, r


def test_une_cyberattaque_massive_vaut_un_bonus_d_enjeu_public():
    score, raisons = _score(
        "Piratage du fisc : Mathilde Panot demande des comptes au gouvernement",
        "Les données personnelles de 678 000 contribuables ont été dérobées "
        "lors d'une cyberattaque contre le site des impôts.")
    assert any("enjeu public" in x for x in raisons), (
        f"aucun marqueur d'enjeu public sur une atteinte aux données de 678 000 "
        f"personnes — raisons : {raisons}")


def test_le_materiel_de_jeu_et_le_cinema_sont_retrogrades():
    for titre, contenu in (
        ("Votre setup mérite mieux : ce casque gaming change tout",
         "Un casque confortable avec un son immersif pour vos sessions de jeu."),
        ("Dune 3 : voici ce que vous allez rater si vous n'avez pas revu les deux premiers",
         "Le troisieme volet arrive au cinema. Retour sur les intrigues."),
    ):
        _, raisons = _score(titre, contenu, "Clubic")
        assert any("divertissement" in x for x in raisons), (
            f"« {titre[:40]}… » ne reçoit aucun malus — raisons : {raisons}")


def test_l_ecart_est_reel_pas_symbolique():
    """Le sujet d'intérêt public doit devancer NETTEMENT le divertissement.

    On ne teste pas une valeur absolue — le barème bouge — mais le fait que
    l'écart existe. Il valait 0 point avant le 19/08.
    """
    fisc, _ = _score(
        "Piratage du fisc : Mathilde Panot demande des comptes au gouvernement",
        "Les données personnelles de 678 000 contribuables ont été dérobées "
        "lors d'une cyberattaque contre le site des impôts.")
    casque, _ = _score(
        "Votre setup mérite mieux : ce casque gaming change tout",
        "Un casque confortable avec un son immersif.", "Clubic")
    assert fisc - casque >= 40, (
        f"écart de {fisc - casque} points seulement entre une cyberattaque "
        f"d'État et un casque gaming ({fisc} contre {casque})")


def test_un_episode_epidemique_n_est_pas_du_divertissement():
    """« épisode » NU attrapait « épisode épidémique / caniculaire / pluvieux ».

    Défaut ANTÉRIEUR au 19/08, trouvé en vérifiant l'innocuité des ajouts.
    Son unique déclenchement sur les 153 articles publiés était « Hantavirus :
    l'OMS déclare la fin de l'épisode lié au navire de croisière » — le malus
    de −30 frappait donc exactement le type de sujet que le barème doit faire
    remonter. Le sens sériel est conservé par `épisode \\d`.
    """
    assert not P._DIVERTISSEMENT_RE.search(
        "hantavirus : l'oms déclare la fin de l'épisode lié au navire de croisière")
    assert not P._DIVERTISSEMENT_RE.search(
        "un épisode caniculaire attendu sur le sud-est")
    assert P._DIVERTISSEMENT_RE.search("l'épisode 4 de la saison 2 sort demain")



def test_les_pluriels_ne_sont_plus_manques():
    """Onze mots du barème mesurés, onze pluriels manqués (19/08).

    `\b` en fin d'alternation faisait échouer « canicules », « impôts »,
    « lois », « rapports », « enquêtes », « séries », « films »… C'est
    littéralement pourquoi « Piratage du fisc » ne déclenchait rien : son
    corps dit « site des impôts ». Et pourquoi « Canicules : déjà 7 300 morts
    en excès » sortait à +0 d'enjeu public.

    Même classe que le bug singulier/pluriel du filtre anti-doublon (26/07), et
    la même leçon : en français, ne jamais s'en remettre à une correspondance
    de mot strict.
    """
    for mot in ("canicules", "impôts", "lois", "rapports", "épidémies",
                "enquêtes", "taxes", "salaires", "plaintes", "amendes"):
        assert P._ENJEU_PUBLIC_RE.search(mot), f"pluriel manqué : {mot}"
    for mot in ("séries", "films", "concerts", "acteurs"):
        assert P._DIVERTISSEMENT_RE.search(mot), f"pluriel manqué : {mot}"


def test_le_pluriel_n_ouvre_pas_la_porte_aux_faux_positifs():
    """`loi` a perdu son `\b` interne pour attraper « lois ». Vérifier que ça
    ne fait pas matcher « emploi », « loisir », « loin » — le genre de dégât
    qu'un élargissement de motif provoque sans qu'on le voie."""
    for mot in ("emploi", "emplois", "loin", "loisir", "cloison"):
        assert not P._ENJEU_PUBLIC_RE.search(mot), f"faux positif : {mot}"


def test_l_adresse_au_lecteur_est_penalisee_SEULEMENT_sans_enjeu():
    """« 300 000 € dorment sur ce site » interpelle au lieu de rapporter.

    ⚠ Le malus est conditionné à l'absence d'enjeu public, et c'est le cœur de
    la règle. Mesuré sur les 153 articles publiés : un seul titre s'adresse au
    lecteur, « Changements au 1er août pour votre budget » — article de SERVICE
    sur des mesures publiques, légitime. Il porte « budget », donc un marqueur
    d'enjeu, donc il est épargné. Le défaut visé n'est pas le « vous », c'est
    le « vous » SANS rien d'autre.
    """
    putaclic, r1 = _score(
        "300 000 € dorment sur ce site et n'importe qui peut les réclamer",
        "Des comptes bancaires inactifs attendent leurs proprietaires.")
    assert any("lecteur" in x for x in r1), r1

    service, r2 = _score("Changements au 1er août pour votre budget",
                         "Plusieurs mesures entrent en vigueur.")
    assert not any("lecteur" in x for x in r2), (
        f"un article de service sur des mesures publiques est rétrogradé : {r2}")
    assert service > putaclic


if __name__ == "__main__":
    test_une_cyberattaque_massive_vaut_un_bonus_d_enjeu_public()
    test_le_materiel_de_jeu_et_le_cinema_sont_retrogrades()
    test_l_ecart_est_reel_pas_symbolique()
    test_un_episode_epidemique_n_est_pas_du_divertissement()
    test_les_pluriels_ne_sont_plus_manques()
    test_le_pluriel_n_ouvre_pas_la_porte_aux_faux_positifs()
    test_l_adresse_au_lecteur_est_penalisee_SEULEMENT_sans_enjeu()
    print("OK — le barème sépare l'intérêt public du divertissement")
