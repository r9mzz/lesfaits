# -*- coding: utf-8 -*-
"""Régressions chronologiques : projet ou échéance future != annonce périmée."""
import os
import sys
import unittest

os.environ.pop("LLM_BASE_URL", None)
os.environ.pop("LLM_API_KEY", None)

sys.path.insert(0, os.path.dirname(__file__))
import verification


class AnnoncePerimeeIntentionTest(unittest.TestCase):
    def test_annonce_passee_d_un_projet_futur_est_ecartee(self):
        probleme = {
            "bloc": 1,
            "type": "annonce_perimee",
            "description": (
                "La phrase présente comme un fait accompli ce qui est décrit "
                "dans les sources comme une intention ou un projet : vouloir construire."
            ),
            "phrase": (
                "Le 25 août 2026, SpaceX a annoncé vouloir construire une base "
                "spatiale en Louisiane."
            ),
        }
        self.assertTrue(verification._annonce_intention_pas_perimee(probleme))
        self.assertEqual(verification._problemes_bloquants([probleme]), [])

    def test_vraie_annonce_devenue_obsolete_reste_bloquante(self):
        probleme = {
            "bloc": 1,
            "type": "annonce_perimee",
            "description": (
                "Une source plus récente établit que le lancement a déjà eu lieu ; "
                "la formulation à venir est donc dépassée."
            ),
            "phrase": "SpaceX prévoit de lancer la fusée demain.",
        }
        self.assertFalse(verification._annonce_intention_pas_perimee(probleme))
        self.assertEqual(verification._problemes_bloquants([probleme]), [probleme])

    def test_intention_annoncee_reste_bloquante_si_le_rapport_etablit_un_etat_plus_recent(self):
        probleme = {
            "bloc": 1,
            "type": "annonce_perimee",
            "description": (
                "Le projet annoncé a été abandonné selon une source plus récente."
            ),
            "phrase": "L'entreprise a annoncé vouloir construire le site.",
        }
        self.assertFalse(verification._annonce_intention_pas_perimee(probleme))
        self.assertEqual(verification._problemes_bloquants([probleme]), [probleme])

    def test_echeance_explicitement_future_non_encore_en_vigueur_est_ecartee(self):
        """Cas réel du run du 27/08 : le juge inversait la chronologie."""
        probleme = {
            "bloc": 1,
            "type": "annonce_perimee",
            "description": (
                "La source [1] (La Croix, 26 août 2026) décrit une réunion tenue le "
                "26 août 2026, ce qui implique que l'obligation de réception des "
                "factures électroniques n'est pas encore en vigueur à cette date."
            ),
            "phrase": (
                "À compter du 1er septembre 2026, toutes les entreprises devront "
                "être en mesure de recevoir des factures électroniques."
            ),
        }
        self.assertTrue(verification._echeance_future_pas_perimee(probleme))
        self.assertEqual(verification._problemes_bloquants([probleme]), [])

    def test_echeance_reportee_reste_bloquante(self):
        probleme = {
            "bloc": 1,
            "type": "annonce_perimee",
            "description": (
                "L'échéance du 1er septembre 2026 a été reportée au 1er janvier 2027 "
                "par une source plus récente."
            ),
            "phrase": (
                "À compter du 1er septembre 2026, toutes les entreprises devront "
                "être en mesure de recevoir des factures électroniques."
            ),
        }
        self.assertFalse(verification._echeance_future_pas_perimee(probleme))
        self.assertEqual(verification._problemes_bloquants([probleme]), [probleme])

    def test_date_non_etablie_reste_bloquante(self):
        probleme = {
            "bloc": 1,
            "type": "annonce_perimee",
            "description": (
                "Aucune source fournie ne confirme la date du 1er septembre 2026."
            ),
            "phrase": (
                "À compter du 1er septembre 2026, toutes les entreprises devront "
                "être en mesure de recevoir des factures électroniques."
            ),
        }
        self.assertFalse(verification._echeance_future_pas_perimee(probleme))
        self.assertEqual(verification._problemes_bloquants([probleme]), [probleme])

    def test_approbation_commission_confirmee_par_communique_du_meme_jour_est_ecartee(self):
        """Cas réel du run du 28/08 : la source primaire du jour prouve le fait."""
        probleme = {
            "bloc": 1,
            "type": "annonce_perimee",
            "description": (
                "Le résumé présente l'approbation comme un événement passé, alors que "
                "la source [1] est un communiqué de la Commission du 27 août 2026, "
                "daté du même jour que l'événement. Aucune source plus récente n'est fournie."
            ),
            "phrase": (
                "Le 27 août 2026, la Commission européenne a approuvé le plan social "
                "pour le climat de la Grèce."
            ),
        }
        self.assertTrue(verification._approbation_commission_meme_jour_pas_perimee(probleme))
        self.assertEqual(verification._problemes_bloquants([probleme]), [])

    def test_approbation_commission_retirée_reste_bloquante(self):
        probleme = {
            "bloc": 1,
            "type": "annonce_perimee",
            "description": (
                "Le communiqué de la Commission du 27 août 2026 mentionnait l'approbation, "
                "mais une décision plus récente indique qu'elle a été retirée."
            ),
            "phrase": (
                "Le 27 août 2026, la Commission européenne a approuvé le plan social "
                "pour le climat de la Grèce."
            ),
        }
        self.assertFalse(verification._approbation_commission_meme_jour_pas_perimee(probleme))
        self.assertEqual(verification._problemes_bloquants([probleme]), [probleme])


if __name__ == "__main__":
    unittest.main()
