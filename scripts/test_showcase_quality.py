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

    def test_brief_is_not_a_showcase_article(self):
        ok, reasons = validate_generated_article(valid_article(), "breve")
        self.assertFalse(ok)
        self.assertTrue(any("format" in reason for reason in reasons))

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
