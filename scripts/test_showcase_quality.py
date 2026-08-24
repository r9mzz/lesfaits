# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from showcase_quality import validate_generated_article  # noqa: E402


def _section(words: list[str], repetitions: int, paragraphs: int, citations: list[int]) -> str:
    sentences = []
    for i in range(repetitions):
        citation = citations[i % len(citations)]
        sentence = " ".join(words) + f" précise la donnée vérifiable numéro {i + 1} [{citation}]."
        sentences.append(sentence)
    size = max(1, len(sentences) // paragraphs)
    chunks = [" ".join(sentences[i:i + size]) for i in range(0, len(sentences), size)]
    return "\n\n".join(chunks[:paragraphs - 1] + [" ".join(chunks[paragraphs - 1:])])


def valid_article() -> dict:
    facts = _section(
        [
            "décret", "ministère", "calendrier", "application", "bénéficiaires",
            "montant", "barème", "formulaire", "échéance", "territoire",
            "administration", "versement", "condition", "dossier", "contrôle",
        ],
        repetitions=30,
        paragraphs=3,
        citations=[1, 2, 3, 4, 5, 6],
    )
    context = _section(
        [
            "réforme", "historique", "trajectoire", "comparaison", "européenne",
            "décennie", "précédent", "évolution", "législative", "financement",
            "architecture", "institutionnelle", "révision", "ancienne", "période",
        ],
        repetitions=13,
        paragraphs=2,
        citations=[1, 2, 4, 5],
    )
    nuances = _section(
        [
            "limites", "méthode", "échantillon", "incertitude", "recours",
            "exclusion", "délai", "évaluation", "hypothèse", "documentation",
            "divergence", "interprétation", "audit", "réserve", "indépendance",
        ],
        repetitions=10,
        paragraphs=2,
        citations=[1, 3, 5, 6],
    )
    return {
        "angle_reponse": (
            "Que changent concrètement ces six mesures pour les bénéficiaires concernés ?"
        ),
        "titre": (
            "Le décret français détaille six changements applicables dès septembre 2026"
        ),
        "resume": [
            "Le décret publié cette semaine modifie six règles administratives et fixe un calendrier précis pour les bénéficiaires, les organismes payeurs et les services chargés du contrôle [1][2].",
            "Les nouvelles modalités concernent les montants, les formulaires, les échéances et les justificatifs, avec une entrée en application échelonnée selon les situations [3][4].",
            "Les documents disponibles précisent toutefois plusieurs limites de méthode, des délais de recours et des catégories encore exclues du dispositif annoncé [5][6].",
        ],
        "titre_faits": "Le décret détaille le calendrier d’application",
        "titre_contexte": "Dix ans de réforme et de comparaison",
        "titre_nuances": "Les limites de méthode encore documentées",
        "corps": {
            "faits": facts,
            "contexte": context,
            "nuances": nuances,
        },
        "sources": [
            {"institution": "Insee", "titre": "Données nationales du dispositif", "url": "https://www.insee.fr/fr/statistiques/100"},
            {"institution": "Le Monde", "titre": "Le calendrier précis de la réforme", "url": "https://www.lemonde.fr/societe/article/2026/08/06/calendrier.html"},
            {"institution": "Reuters", "titre": "France publishes new administrative decree", "url": "https://www.reuters.com/world/europe/france-decree-2026-08-06/"},
            {"institution": "France Info", "titre": "Ce qui change pour les bénéficiaires", "url": "https://www.francetvinfo.fr/economie/reforme-beneficiaires.html"},
            {"institution": "BBC", "titre": "How the French system will change", "url": "https://www.bbc.com/news/articles/example"},
            {"institution": "The Guardian", "titre": "French reform and its documented limits", "url": "https://www.theguardian.com/world/2026/aug/06/french-reform"},
        ],
        "nb_sources": 6,
        "qualite_sources": {"primaire": 1, "secondaire": 5, "tertiaire": 0},
    }


class ShowcaseQualityTests(unittest.TestCase):
    def test_full_showcase_article_is_accepted(self):
        ok, reasons = validate_generated_article(valid_article(), "actu")
        self.assertTrue(ok, reasons)
        self.assertEqual(reasons, [])

    def test_article_long_soumis_comme_breve_est_refuse(self):
        """Un ARTICLE présenté comme brève est refusé — mais sur ses défauts de
        brève, plus au motif « format exclu ».

        Depuis le 10/08 la vitrine accepte le format brève (voir
        MIN_WORDS_BREVE) : le refus ne doit donc plus porter sur le format
        lui-même, mais sur ce qui, dans ce texte, n'est pas une brève —
        contexte et nuances remplis, chapeau en trois phrases.
        """
        ok, reasons = validate_generated_article(valid_article(), "breve")
        self.assertFalse(ok)
        self.assertFalse(any("format" in r and "exclu" in r for r in reasons),
                         f"le format brève ne doit plus être exclu : {reasons}")
        self.assertTrue(any("contexte" in r for r in reasons), reasons)
        self.assertTrue(any("phrase" in r for r in reasons), reasons)

    def test_breve_vitrine_conforme_est_acceptee(self):
        """Le cas qui a coûté quatre jours de silence : un texte de ~280 mots,
        rejeté comme article trop court, doit passer comme brève."""
        breve = {
            "titre": "Sécheresse : des restrictions d'eau sur 70 % du territoire français",
            "resume": ["Le ministère de la transition écologique a placé 70 % du "
                       "territoire sous restrictions d'eau au 9 août, un niveau "
                       "jamais atteint à cette date depuis 2003."],
            "corps": {
                "faits": (
                    "Selon le ministère de la transition écologique [1], le Bureau de "
                    "recherches géologiques et minières [2] et Météo-France [3], "
                    "soixante-dix pour cent du territoire métropolitain est soumis à au "
                    "moins un arrêté de restriction d'eau au 9 août 2026. Quarante-deux "
                    "départements sont placés en situation de crise, le niveau le plus "
                    "élevé, contre dix-neuf à la même date en 2025. Les prélèvements "
                    "agricoles y sont interdits en journée et les usages domestiques non "
                    "prioritaires suspendus. Les nappes phréatiques affichent un niveau "
                    "inférieur à la normale sur les trois quarts des points de mesure. "
                    "Le déficit de précipitations atteint quarante pour cent depuis le "
                    "mois de mars sur le pourtour méditerranéen. Les préfectures "
                    "concernées doivent réexaminer les arrêtés toutes les deux semaines "
                    "jusqu'au retour à la normale, précise le ministère."
                ),
                "contexte": "",
                "nuances": "",
            },
            "sources": [
                {"institution": "Ministère de la transition écologique",
                 "url": "https://www.ecologie.gouv.fr/secheresse-2026"},
                {"institution": "BRGM", "url": "https://www.brgm.fr/nappes-aout-2026"},
                {"institution": "Météo-France", "url": "https://meteofrance.fr/bilan-aout"},
                {"institution": "Le Monde", "url": "https://www.lemonde.fr/planete/secheresse"},
            ],
            "nb_sources": 4,
        }
        ok, reasons = validate_generated_article(breve, "breve")
        self.assertTrue(ok, reasons)
        self.assertEqual(reasons, [])

    def test_short_sourcing_is_rejected(self):
        art = valid_article()
        art["sources"] = art["sources"][:4]
        art["nb_sources"] = 4
        ok, reasons = validate_generated_article(art, "actu")
        self.assertFalse(ok)
        self.assertTrue(any("sourcing trop court" in reason for reason in reasons))

    def test_generic_heading_is_rejected(self):
        art = valid_article()
        art["titre_contexte"] = "Contexte"
        ok, reasons = validate_generated_article(art, "actu")
        self.assertFalse(ok)
        self.assertTrue(any("intertitre contexte" in reason for reason in reasons))

    def test_uncited_source_is_rejected(self):
        art = valid_article()
        for key in ("faits", "contexte", "nuances"):
            art["corps"][key] = art["corps"][key].replace("[6]", "[5]")
        art["resume"] = [sentence.replace("[6]", "[5]") for sentence in art["resume"]]
        ok, reasons = validate_generated_article(art, "actu")
        self.assertFalse(ok)
        self.assertTrue(any("non citées" in reason for reason in reasons))


if __name__ == "__main__":
    unittest.main(verbosity=2)
