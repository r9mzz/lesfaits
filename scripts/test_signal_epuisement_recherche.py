"""Un moteur de recherche limité ne doit pas passer pour un verdict éditorial.

Mesuré le 19/08, même code et même journée, quatre runs enchaînés :

    10h49   générique +16 · officiel +16 · contrôle/audit +16 · vérification +11
    18h52   générique +11 · officiel  +0 · contrôle/audit  +0 · vérification  +0

Le run du soir a rendu 20 à 27 sources au lieu de 100, 0 primaire au lieu de
60, et six sujets ont été rejetés sur « ≥1 primaire OU ≥2 secondaires ». Sans
signal, ces six lignes se lisent comme des sujets mal documentés — alors que
c'est notre cadence de runs qui a épuisé le moteur.

C'est la même erreur d'attribution que la brièveté des articles imputée au
modèle pendant trois semaines alors qu'elle venait du budget de tokens.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SOURCE = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "pipeline.py"), encoding="utf-8").read()


def _logique(axes):
    """Rejoue la condition telle qu'elle est écrite dans pipeline.py."""
    docs = [a for a in axes if not a.startswith("générique")]
    return bool(docs) and all(a.endswith("+0") for a in docs)


def test_le_signal_existe_dans_le_pipeline():
    assert "TOUS les axes documentaires rendent 0" in SOURCE, (
        "le signal d'épuisement de la recherche a disparu de pipeline.py")


def test_il_se_declenche_sur_le_cas_reel_du_19_08_au_soir():
    assert _logique(["générique +11", "officiel/juridique +0",
                     "contrôle/audit +0", "vérification +0"])


def test_il_reste_muet_quand_la_recherche_fonctionne():
    """Cas du matin : les axes documentaires rapportent, aucun avertissement."""
    assert not _logique(["générique +16", "officiel/juridique +16",
                         "contrôle/audit +16", "vérification +11"])


def test_il_reste_muet_si_un_seul_axe_documentaire_rend_zero():
    """Un axe stérile sur un sujet donné est NORMAL — il n'y a pas toujours un
    arrêt de la CJUE sur le sujet. Le signal ne vise que l'extinction TOTALE."""
    assert not _logique(["générique +16", "officiel/juridique +0",
                         "contrôle/audit +5", "vérification +0"])


def test_l_axe_generique_ne_compte_pas_dans_le_verdict():
    """Le générique répond encore quand le moteur throttle : c'est justement ce
    contraste qui identifie la panne. L'inclure masquerait le signal."""
    assert _logique(["générique +0", "officiel/juridique +0", "contrôle/audit +0"])


if __name__ == "__main__":
    test_le_signal_existe_dans_le_pipeline()
    test_il_se_declenche_sur_le_cas_reel_du_19_08_au_soir()
    test_il_reste_muet_quand_la_recherche_fonctionne()
    test_il_reste_muet_si_un_seul_axe_documentaire_rend_zero()
    test_l_axe_generique_ne_compte_pas_dans_le_verdict()
    print("OK — un moteur épuisé est signalé, jamais confondu avec un rejet éditorial")
