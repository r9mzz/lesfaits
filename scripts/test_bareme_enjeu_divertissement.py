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



def test_un_titre_en_question_est_retrograde():
    """Notre charte (règle 6) interdit à NOS titres d'être une question.

    `titre_de_mauvaise_qualite` le fait respecter — mais seulement sur le titre
    GÉNÉRÉ, jamais sur le candidat RSS qu'on choisit de traiter. On s'interdisait
    une forme tout en la choisissant comme sujet.

    Mesuré : 0 titre en question sur les 153 articles publiés. Le malus ne peut
    rétrograder aucun sujet du type de ceux qu'on a jugé bon de publier.
    """
    _, raisons = _score("Un campus, combien ça rapporte ? Le poids économique du CESI",
                        "Le CESI a publié une étude sur son impact économique local.",
                        "Ouest-France")
    assert any("question" in x for x in raisons), raisons


def test_le_vrai_sujet_d_actualite_passe_devant_le_communique():
    """Demande de Nahil : « le campus ne doit pas être premier ».

    Cas mesurés le 19/08, avant : campus 85, canicules 57, Arctique 55,
    piratage 52. Le campus tirait 35 de ses 50 points du seul fait
    qu'Ouest-France l'avait publié — être repris par un grand titre ne dit RIEN
    de l'importance du sujet.
    """
    pad = (" Le detail de l affaire est rapporte par plusieurs redactions et les "
           "elements connus sont precises.") * 4
    def sc(t, c, src):
        return P.score_editorial(
            {"title": t, "content": c + pad, "link": "https://x.fr/a"}, src, set())[0]

    campus = sc("Un campus, combien ça rapporte ? Le poids économique du CESI",
                "Le CESI a publié une étude sur son impact économique local.",
                "Ouest-France")
    canicule = sc("Canicules : déjà 7.300 morts en excès en France",
                  "Santé publique France publie son bilan de mortalité.", "Le Monde")
    arctique = sc("Annulation d'un rapport sur l'Arctique : les scientifiques s'inquiètent",
                  "Le rapport annuel sur le climat arctique a été annulé.", "Le Monde")
    assert canicule > campus and arctique > campus, (
        f"campus {campus} tient encore devant canicule {canicule} / "
        f"Arctique {arctique}")


def test_le_poids_du_SUJET_ne_redescend_pas_sous_la_forme_sans_decision():
    """Ventilation mesurée sur les 153 titres publiés : 94,2 % FORME / 5,8 %
    SUJET avant le 19/08, 90,8 / 9,2 après.

    Ce test ne fige pas un ratio idéal — personne ne sait ce qu'il vaut. Il
    empêche un retour SILENCIEUX à l'état d'avant : le barème avait dérivé
    jusqu'à ne plus noter que l'emballage, et rien ne le signalait.
    """
    assert P.PONDS_ENJEU_FORT >= 45 and P.PONDS_ENJEU_MOYEN >= 25, (
        f"le bonus d'enjeu public est retombé à {P.PONDS_ENJEU_FORT} / "
        f"{P.PONDS_ENJEU_MOYEN} : le barème renote la forme plus que le sujet")


if __name__ == "__main__":
    test_une_cyberattaque_massive_vaut_un_bonus_d_enjeu_public()
    test_le_materiel_de_jeu_et_le_cinema_sont_retrogrades()
    test_l_ecart_est_reel_pas_symbolique()
    test_un_episode_epidemique_n_est_pas_du_divertissement()
    test_les_pluriels_ne_sont_plus_manques()
    test_le_pluriel_n_ouvre_pas_la_porte_aux_faux_positifs()
    test_l_adresse_au_lecteur_est_penalisee_SEULEMENT_sans_enjeu()
    test_un_titre_en_question_est_retrograde()
    test_le_vrai_sujet_d_actualite_passe_devant_le_communique()
    test_le_poids_du_SUJET_ne_redescend_pas_sous_la_forme_sans_decision()
    print("OK — le barème sépare l'intérêt public du divertissement")
