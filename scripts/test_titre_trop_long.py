"""Le garde-fou du titre n'avait pas de borne HAUTE, et ça tuait des articles.

`titre_de_mauvaise_qualite` vérifiait `nb_mots < 6` sans jamais regarder le
plafond de 15, alors que la charte (règle 6), les deux prompts ET la grille
vitrine le posent. Rien ne rappelait donc au rédacteur qu'il dépassait :
l'article traversait tout le protocole, puis mourait à la toute fin sur
« titre non vitrine ».

Mesuré le 28/08 sur les 7 articles ayant réellement atteint la vitrine :
**5 sur 7 rejetés là-dessus**, à 16, 17, 19 et 21 mots.

Taux de déclenchement relevé AVANT d'ajouter le contrôle, comme la règle du
projet l'exige : sur les 153 titres publiés, médiane 9 mots, maximum 16, et
**un seul au-dessus de 15 (0,7 %)**. Très loin des ~10 % au-delà desquels un
motif est jugé trop large.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("GROQ_MODEL_OVERRIDE", "mistral-large-latest")

import pipeline as p  # noqa: E402
import showcase_quality as S  # noqa: E402

# Titres RÉELS relevés dans les journaux de run, avec leur compte de mots.
TITRES_REELS_TROP_LONGS = [
    ("Le bilan provisoire de la sécheresse en France métropolitaine s'alourdit "
     "encore selon le ministère de la transition écologique", 18),
    ("Les décriées ZFE de Londres et de Paris affichent des résultats "
     "contrastés sur la qualité de l'air urbain", 18),
]


def _titre(t):
    return {"titre": t}


def test_un_titre_trop_long_declenche_la_relance():
    for titre, n in TITRES_REELS_TROP_LONGS:
        assert len(titre.split()) == n, f"jeu de test incohérent : {titre}"
        msg = p.titre_de_mauvaise_qualite(_titre(titre))
        assert msg is not None, f"titre de {n} mots non signalé : {titre}"
        assert "trop long" in msg, msg


def test_un_titre_conforme_ne_declenche_rien():
    """Un titre à la médiane du corpus publié doit rester muet — sinon le
    garde-fou déclenche une relance corrective sur des articles corrects, et
    le quota du fournisseur est la ressource rare."""
    assert p.titre_de_mauvaise_qualite(
        _titre("Inflation à 2,1 % en France sur un an en juillet")) is None


def test_les_bornes_ne_sont_pas_recopiees():
    """Septième famille de défaut du projet : la même valeur écrite à trois
    endroits qui divergent. Le plafond du garde-fou et celui de la vitrine
    doivent être le MÊME nombre."""
    assert p.TITRE_MOTS_MAX == 15
    # La vitrine rejette hors de [8, 15] pour un article : le plafond partagé.
    art = {"titre": " ".join(["mot"] * (p.TITRE_MOTS_MAX + 1))}
    _, raisons = S.validate_generated_article(art, "actu")
    assert any("titre non vitrine" in r for r in raisons), (
        "le plafond du garde-fou et celui de la vitrine ont divergé")


def test_la_relance_vise_la_zone_qui_passe_les_deux_portes():
    """La vitrine exige 8 mots minimum pour un article, la charte 6. Une
    relance qui viserait 6 produirait un titre conforme au garde-fou et rejeté
    par la vitrine — l'article serait perdu après une correction payée."""
    assert p.TITRE_MOTS_CIBLE_MIN >= 8
    msg = p.titre_de_mauvaise_qualite(_titre(" ".join(["mot"] * 20)))
    assert f"{p.TITRE_MOTS_CIBLE_MIN} à {p.TITRE_MOTS_MAX} mots" in msg, msg


def test_un_titre_trop_court_reste_signale():
    """Non-régression : la borne basse existait et doit survivre."""
    msg = p.titre_de_mauvaise_qualite(_titre("Inflation en hausse"))
    assert msg is not None and "trop court" in msg, msg


def test_le_controle_est_rejoue_apres_correction():
    """La passe 3 réécrit le texte ET le titre. Un contrôle placé avant elle
    est invalidé — c'est le tableau du 03/08. `titre_de_mauvaise_qualite`
    figure bien dans les contrôles rejoués."""
    source = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "pipeline.py"), encoding="utf-8").read()
    bloc = source[source.index("_CONTROLES_AVERTISSEMENT"):] if \
        "_CONTROLES_AVERTISSEMENT" in source else source
    assert bloc.count("titre_de_mauvaise_qualite") >= 1, (
        "le contrôle du titre n'est plus rejoué après la passe de correction")


if __name__ == "__main__":
    n = 0
    for nom, fn in sorted(globals().items()):
        if nom.startswith("test_"):
            fn(); n += 1; print(f"  ✓ {nom}")
    print(f"{n} tests OK")
