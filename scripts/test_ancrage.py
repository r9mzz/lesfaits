# -*- coding: utf-8 -*-
"""Le contrôle d'ancrage retire les phrases absentes des sources, garde les autres."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("GROQ_API_KEY", "x")
from pipeline import ancrer_article, _apparier_source_fournie, SEUILS_FORMAT  # noqa: E402

CNRS = ("Les phosphatières du Quercy, dans le Lot, forment un ensemble d'environ 200 gouffres "
        "qui livrent depuis 60 ans des fossiles de milliers d'animaux disparus. La conservation "
        "est exceptionnelle : la peau préservée et même des globes oculaires. Maëva Orliac, "
        "chercheuse au CNRS, étudie ce renouvellement de la faune en Europe il y a 34 millions "
        "d'années, lors de la Grande Coupure. On ignore encore l'origine des quantités "
        "importantes de phosphate présentes dans ces gouffres. ") * 2
MONDE = ("Le parquet de Paris a décidé de renvoyer Apple devant le tribunal correctionnel. "
         "Le procès s'ouvrira le 17 juin 2027. La plainte de l'association HOP, déposée en "
         "décembre 2022, vise la sérialisation des pièces détachées des iPhone. ") * 3
FOURNIES = [{"url": "https://images.cnrs.fr/actualites/quercy", "snippet": CNRS},
            {"url": "https://www.lemonde.fr/apple?xtor=RSS", "snippet": MONDE}]


def _art(faits, resume=None):
    return {"resume": resume or [], "corps": {"faits": faits, "contexte": "", "nuances": ""},
            "sources": [{"url": "https://images.cnrs.fr/actualites/quercy/"},
                        {"url": "https://lemonde.fr/apple"}]}


def test_phrase_fidele_conservee():
    art = _art("Les phosphatières du Quercy forment un ensemble de 200 gouffres qui livrent "
               "des fossiles depuis 60 ans [1].")
    ok, journal = ancrer_article(art, FOURNIES)
    assert ok and not journal and "200 gouffres" in art["corps"]["faits"]


def test_annee_fausse_retiree():
    art = _art("Le procès s'ouvrira en juin 2027 [2]. La plainte de HOP a été déposée en 2017 [2].")
    ancrer_article(art, FOURNIES)
    assert "2017" not in art["corps"]["faits"] and "2027" in art["corps"]["faits"]


def test_attribution_a_la_mauvaise_source_retiree():
    art = _art("La conservation des globes oculaires est exceptionnelle [1]. "
               "Les anthracothères et les paléothères ont disparu, remplacés par des migrants "
               "asiatiques [1].")
    ancrer_article(art, FOURNIES)
    assert "anthracoth" not in art["corps"]["faits"] and "globes" in art["corps"]["faits"]


def test_phrase_sans_appel_absente_de_toutes_les_sources_retiree():
    art = _art("Des gisements comparables existent à White River aux États-Unis et dans le "
               "bassin de Pékin. Les fossiles couvrent la Grande Coupure il y a 34 millions "
               "d'années [1].")
    ancrer_article(art, FOURNIES)
    assert "White River" not in art["corps"]["faits"] and "34 millions" in art["corps"]["faits"]


def test_trop_de_texte_invente_rejette_l_article():
    art = _art("La notion de Grande Coupure a été identifiée dès le XIXe siècle par des "
               "géologues allemands. Les sites de Mongolie documentent la même transition. "
               "Les 200 gouffres livrent des fossiles depuis 60 ans [1].")
    ok, journal = ancrer_article(art, FOURNIES)
    assert not ok and len(journal) == 2


def test_adresse_reecrite_par_le_redacteur_retrouvee():
    art = _art("Le procès d'Apple s'ouvrira le 17 juin 2027 [2].")
    art["sources"][1]["url"] = "http://lemonde.fr/apple/"
    ok, journal = ancrer_article(art, FOURNIES)
    assert ok and "17 juin 2027" in art["corps"]["faits"]
    assert not [j for j in journal if j.startswith("diagnostic")]


def test_source_jamais_fournie_signalee_et_phrase_retiree():
    art = _art("Le procès d'Apple s'ouvrira le 17 juin 2027 [2].")
    art["sources"][1]["url"] = "https://exemple-inconnu.org/article"
    ancrer_article(art, FOURNIES)
    assert "2027" not in art["corps"]["faits"]


def test_nom_du_media_cite_ne_fait_pas_retirer_la_phrase():
    """Run du 26/11 : « Selon Le Monde, … » retiree pour « nom absent de la
    source : Monde ». Le prompt EXIGE cette attribution, et un journal ne se
    nomme pas dans son propre article : le controle punissait notre regle."""
    art = _art("Selon Le Monde, le procès d'Apple s'ouvrira le 17 juin 2027 [2].")
    ok, journal = ancrer_article(art, FOURNIES)
    assert ok and not journal, journal
    assert "Le Monde" in art["corps"]["faits"]


def test_le_nom_du_media_exempte_ne_couvre_pas_les_autres_noms():
    art = _art("Selon Le Monde, le procès d'Apple s'ouvrira à Bordeaux le 17 juin 2027 [2].")
    ancrer_article(art, FOURNIES)
    assert "Bordeaux" not in art["corps"]["faits"]


def test_numero_de_dossier_n_est_pas_un_chiffre_a_verifier():
    """« T-340/16 » etait lu comme le nombre 340, declare absent de la source."""
    art = _art("Le procès s'ouvrira le 17 juin 2027 dans la procédure T-340/16 [2].")
    ok, journal = ancrer_article(art, FOURNIES)
    assert ok and not journal, journal


def test_chiffre_faux_reste_bloque_hors_reference():
    art = _art("La plainte de HOP visait 450 pièces détachées [2].")
    ancrer_article(art, FOURNIES)
    assert "450" not in art["corps"]["faits"]


def test_url_reecrite_par_le_redacteur_est_appariee():
    """Run du 27/11 : des breves annoncees a « 0 source(s) citee(s) » alors que
    8 sources reelles avaient ete injectees. L'URL renvoyee devait etre
    IDENTIQUE a celle fournie ; le redacteur retire les parametres de suivi."""
    fournies = {"https://www.lemonde.fr/apple?xtor=RSS",
                "https://images.cnrs.fr/actualites/quercy"}
    assert _apparier_source_fournie("http://lemonde.fr/apple",
                                    fournies) == "https://www.lemonde.fr/apple?xtor=RSS"
    assert _apparier_source_fournie("https://images.cnrs.fr/actualites/quercy/",
                                    fournies) == "https://images.cnrs.fr/actualites/quercy"


def test_url_d_une_source_jamais_fournie_n_est_pas_appariee():
    fournies = {"https://www.lemonde.fr/apple?xtor=RSS"}
    assert _apparier_source_fournie("https://exemple-inconnu.org/article", fournies) == ""
    assert _apparier_source_fournie("", fournies) == ""


def test_une_breve_exige_deux_sources_citees():
    """Decision du 27/11 : 2, jamais 1 — une seule source, c'est reprendre le
    cadrage d'un media sans contrepoint."""
    assert SEUILS_FORMAT["breve"]["sources"] == 2


def test_le_contenu_de_la_source_d_origine_ancre_aussi():
    """28/11 : l'article d'origine est injecte dans le prompt comme CONTENU,
    meme quand la presse protegee interdit d'en faire une source citable. Sans
    lui, chaque fait de l'evenement devenait « absent des sources »."""
    art = _art("Le confinement a été levé en fin de matinée à Gandrange.")
    ok, journal = ancrer_article(
        art, FOURNIES,
        contenu_origine=("Un incendie s'est déclaré dans un entrepôt classé Seveso à "
                         "Gandrange. Le confinement des habitants a été levé en fin de "
                         "matinée, selon la préfecture de Moselle. ") * 3,
        url_origine="https://www.republicain-lorrain.fr/incendie")
    assert ok and not journal, journal
    assert "Gandrange" in art["corps"]["faits"]


def test_sans_contenu_d_origine_la_phrase_reste_retiree():
    art = _art("Le confinement a été levé en fin de matinée à Gandrange.")
    ancrer_article(art, FOURNIES)
    assert "Gandrange" not in art["corps"]["faits"]


if __name__ == "__main__":
    n = 0
    for nom, fn in sorted(globals().items()):
        if nom.startswith("test_"):
            fn(); n += 1; print(f"  ✓ {nom}")
    print(f"{n} tests OK")
