"""Verrouille l'élargissement du 24/08 du garde-fou d'acharnement.

Défaut corrigé : le compteur ne regardait QUE `angle_insuffisant`, soit un
motif sur six. Mesuré sur le journal — la canicule générée 11 fois en 4 jours,
Ebola 8 fois, le campus 9 fois, toutes avec `angle_insuffisant = 0`, donc
jamais bloquables. 163 tentatives pour 71 sujets sur l'ère Mistral.
"""
from datetime import datetime, timedelta

import pipeline as P


def _log(tmp_path, entrees):
    import json
    import os
    d = tmp_path / "data"
    d.mkdir(parents=True, exist_ok=True)
    (d / "verification_log.json").write_text(json.dumps(entrees), encoding="utf-8")
    os.chdir(tmp_path)


def _entree(titre, jours, **kw):
    q = datetime.now() - timedelta(days=jours)
    e = {"titre_rss": titre, "date": q.isoformat(), "statut": "rejete_qualite"}
    e.update(kw)
    return e


def test_rejets_bloquants_finissent_par_condamner(tmp_path):
    """Trois verdicts motivés condamnent, même sans angle_insuffisant.

    C'est le cas canicule : 11 rejets sur chiffre_errone et
    incoherence_inter_sections, zéro blocage sous l'ancienne règle.
    """
    _log(tmp_path, [_entree("Canicules : 7 300 morts en excès", j,
                            bloquants_types=["chiffre_errone"])
                    for j in (1, 2, 3)])
    assert P._titre_norme("Canicules : 7 300 morts en excès") in P._sujets_condamnes()


def test_deux_rejets_bloquants_ne_condamnent_pas(tmp_path):
    """Seuil MESURÉ : bloquer à la 3e tentative coûtait 2 articles, à la 4e
    un seul. La 2e reprise reste donc autorisée."""
    _log(tmp_path, [_entree("Sujet deux fois recalé", j,
                            bloquants_types=["chiffre_errone"]) for j in (1, 2)])
    assert P._titre_norme("Sujet deux fois recalé") not in P._sujets_condamnes()


def test_le_seuil_angle_nest_pas_desserre(tmp_path):
    """L'élargissement ne doit PAS relâcher la règle mesurée le 17/08 :
    deux `angle_insuffisant` condamnent toujours."""
    _log(tmp_path, [_entree("Sujet creux", j, angle_insuffisant=True)
                    for j in (1, 2)])
    assert P._titre_norme("Sujet creux") in P._sujets_condamnes()


def test_les_pannes_techniques_ne_condamnent_jamais(tmp_path):
    """Prudence d'origine conservée : un quota épuisé ou un JSON tronqué
    laisse `bloquants_types` vide et ne doit condamner aucun sujet — sinon
    une panne de réseau tuerait un sujet valable."""
    _log(tmp_path, [_entree("Sujet victime d'une panne", j,
                            statut="erreur_verification") for j in (1, 2, 3, 4)])
    assert P._sujets_condamnes() == set()


def test_hors_fenetre_le_sujet_revient(tmp_path):
    """Au-delà de la fenêtre, un sujet peut revenir avec un angle neuf."""
    vieux = P.ACHARNEMENT_FENETRE_J + 3
    _log(tmp_path, [_entree("Vieux sujet", vieux + j,
                            bloquants_types=["chiffre_errone"]) for j in (0, 1, 2)])
    assert P._sujets_condamnes() == set()


def test_le_meme_evenement_sous_des_titres_differents_est_vu(tmp_path):
    """C'est le défaut mesuré sur le run 276 : 12 reprises sur 21 sujets.

    Le garde-fou tournait, mais comparait des titres EXACTEMENT égaux — or la
    canicule revient chaque jour sous un titre neuf. Le regroupement par mots
    distinctifs (celui du filtre de diversité, déjà en service) les réunit.

    ⚠ Coût mesuré avant d'appliquer, sur les 80 articles publiés retrouvés dans
    le journal : 1 aurait été bloqué à tort (1 %), contre 57 % de reprises
    évitées.
    """
    _log(tmp_path, [
        _entree("Canicules : déjà 7 300 morts en excès en France", 1,
                bloquants_types=["chiffre_errone"]),
        _entree("Canicules en France : cinq signes d'un été en surchauffe", 2,
                bloquants_types=["annonce_perimee"]),
        _entree("Canicules et morts en excès : le bilan français", 3,
                bloquants_types=["incoherence_inter_sections"]),
    ])
    condamnes = P._sujets_condamnes()
    assert P._titre_norme("Canicules : déjà 7 300 morts en excès en France") in condamnes, (
        "trois formulations du même événement doivent condamner l'événement")


def test_deux_sujets_sans_rapport_ne_se_condamnent_pas(tmp_path):
    """Un blocage coûte le sujet pour toute la fenêtre : il faut DEUX mots
    distinctifs partagés, jamais un seul. C'est la leçon des trois échecs de
    l'heuristique de titres (26/07, 28/07, 02/08)."""
    _log(tmp_path, [
        _entree("Ebola en RDC : progression exponentielle", 1,
                bloquants_types=["chiffre_errone"]),
        _entree("Retraites : le gel des pensions contesté", 2,
                bloquants_types=["chiffre_errone"]),
        _entree("Nord Stream : arrestation en Croatie", 3,
                bloquants_types=["chiffre_errone"]),
    ])
    assert P._sujets_condamnes() == set(), (
        "trois sujets sans rapport ne forment pas un acharnement")


if __name__ == "__main__":
    import os
    import pathlib
    import tempfile
    n = 0
    for nom, fn in sorted(globals().items()):
        if nom.startswith("test_"):
            garde = os.getcwd()
            with tempfile.TemporaryDirectory() as d:
                try:
                    fn(pathlib.Path(d))
                finally:
                    os.chdir(garde)
            n += 1
            print(f"  ✓ {nom}")
    print(f"{n} tests OK")
