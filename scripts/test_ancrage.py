# -*- coding: utf-8 -*-
"""Le contrôle d'ancrage retire les phrases absentes des sources, garde les autres."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("GROQ_API_KEY", "x")
from pipeline import ancrer_article  # noqa: E402

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


if __name__ == "__main__":
    n = 0
    for nom, fn in sorted(globals().items()):
        if nom.startswith("test_"):
            fn(); n += 1; print(f"  ✓ {nom}")
    print(f"{n} tests OK")
