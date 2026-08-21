"""Le correcteur doit savoir corriger CHAQUE motif qui fait rejeter.

── LA MESURE QUI A TOUT RETOURNÉ, 21/08 ──────────────────────────────────────

Question de Nahil : « s'il trouve toutes ces erreurs, pourquoi il ne l'écrit
pas bien directement ? ». En cherchant la réponse, on a mesuré la
REPRODUCTIBILITÉ du juge sur les trois passes d'un même article :

    passe 1 : accusation_presentee_comme_fait · annonce_perimee · niveau_preuve
    passe 2 :                                   annonce_perimee · niveau_preuve
    passe 3 : accusation_presentee_comme_fait · annonce_perimee · niveau_preuve

Sur 3 articles sur 5, les MÊMES types reviennent aux trois passes. Le juge
n'invente pas des reproches au hasard : il désigne le même défaut, trois fois.

⚠ Ça renverse le diagnostic de la veille. Le problème n'est pas la sévérité du
juge — c'est que la CORRECTION ne corrige pas. Et la cause était dans le prompt
de correction :

    niveau_preuve_insuffisant        AUCUNE consigne
    accusation_presentee_comme_fait  AUCUNE consigne
    annonce_perimee                  consigne d'un seul SENS (passé annoncé
                                     comme futur), alors que nos échecs sont
                                     l'inverse — « a créé » quand la source
                                     dit « veut créer »

Les deux motifs sans consigne sont exactement ceux qui survivaient aux trois
passes. Le juge signalait, le correcteur n'avait pas de règle, le défaut
restait, l'article était rejeté après avoir coûté trois allers-retours.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("GROQ_API_KEY", "x")

import verification_legacy as V  # noqa: E402

BLOQUANTS = ("chiffre_errone", "incoherence_inter_sections", "annonce_perimee",
             "niveau_preuve_insuffisant", "accusation_presentee_comme_fait",
             "source_inventee")


def test_chaque_motif_bloquant_a_sa_consigne_de_correction():
    """Un motif bloquant sans consigne = trois passes payées pour rien."""
    p = V.PROMPT_CORRECTION
    manquants = [m for m in BLOQUANTS if m not in p]
    assert not manquants, (
        f"motifs bloquants sans consigne de correction : {manquants} — "
        "le juge les signalera, le correcteur ne saura pas quoi en faire, "
        "et l'article sera rejeté après trois allers-retours")


def test_les_motifs_bloquants_sont_les_MEMES_des_deux_cotes():
    """La liste du correcteur doit suivre celle du pipeline, pas une copie
    figée : le jour où `_problemes_bloquants` change, ce test le dit."""
    reels = set()
    for t in BLOQUANTS:
        bloc = 2 if t in ("source_inventee",) else 1
        if V._problemes_bloquants([{"bloc": bloc, "type": t}]):
            reels.add(t)
    assert reels == set(BLOQUANTS), (
        f"la liste testée a divergé de `_problemes_bloquants` : {reels}")


def test_annonce_perimee_couvre_les_DEUX_sens():
    """Le sens historique (passé annoncé comme futur) ET celui de nos échecs
    réels : un PROJET présenté comme accompli."""
    p = V.PROMPT_CORRECTION
    assert "PROJET présenté comme accompli" in p
    for forme in ("veut créer", "a officialisé"):
        assert forme in p, f"formulation absente de la consigne : {forme}"


def test_chiffre_errone_sait_quoi_faire_d_un_chiffre_introuvable():
    """« Corrige le chiffre » est impossible quand le chiffre n'est dans AUCUN
    extrait : le correcteur n'a pas la bonne valeur. Il doit supprimer."""
    p = V.PROMPT_CORRECTION
    assert "N'APPARAÎT DANS AUCUN extrait" in p and "SUPPRIME" in p


def test_niveau_preuve_n_autorise_pas_a_inventer_une_limite():
    """Symétrique de la règle donnée au juge le 20/08 : le correcteur ne doit
    pas fabriquer une limite méthodologique pour satisfaire le reproche — ce
    serait violer la règle 5 de la charte."""
    p = V.PROMPT_CORRECTION
    assert "n'invente AUCUNE limite méthodologique" in p


def test_accusation_couvre_toutes_les_sections():
    """Défaut mesuré : une accusation attribuée dans « les faits » mais reprise
    nue dans le résumé reste bloquante."""
    p = V.PROMPT_CORRECTION
    assert "titre, chapeau, faits ET nuances" in p


if __name__ == "__main__":
    test_chaque_motif_bloquant_a_sa_consigne_de_correction()
    test_les_motifs_bloquants_sont_les_MEMES_des_deux_cotes()
    test_annonce_perimee_couvre_les_DEUX_sens()
    test_chiffre_errone_sait_quoi_faire_d_un_chiffre_introuvable()
    test_niveau_preuve_n_autorise_pas_a_inventer_une_limite()
    test_accusation_couvre_toutes_les_sections()
    print("OK — chaque motif bloquant a sa consigne de correction")
