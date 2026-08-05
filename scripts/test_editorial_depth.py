# -*- coding: utf-8 -*-
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from editorial_depth import (  # noqa: E402
    apply_headings, section_depth, sourcing_warning, validate_heading,
)
from editorial_quality import ArticleRecord, Source  # noqa: E402


def make_article(*, facts, context, nuances, sources=None, fmt="article", words=420):
    return ArticleRecord(
        path=Path("test.html"), slug="test", title="Une mesure modifie le transport ferroviaire",
        lead="La mesure entre en vigueur au mois de septembre.",
        facts=facts, context=context, nuances=nuances, date_iso="2026-08-06",
        sources=sources or [Source("Ministère", "Nouvelle mesure ferroviaire", "https://transport.gouv.fr/mesure")],
        format=fmt, words=words, is_new=True,
    )


class EditorialDepthTests(unittest.TestCase):
    def test_redundant_context_is_rejected(self):
        facts = (
            "Le ministère a publié une nouvelle règle pour les trains régionaux. "
            "Elle entre en vigueur en septembre et modifie les conditions de remboursement. "
        ) * 5
        context = (
            "La nouvelle règle pour les trains régionaux entre en vigueur en septembre "
            "et change les conditions de remboursement des voyageurs. "
        ) * 4
        nuances = (
            "Les billets achetés avant septembre restent soumis aux anciennes conditions, "
            "tandis que les abonnements font l'objet d'un calendrier séparé. "
        ) * 3
        result = section_depth(make_article(facts=facts, context=context, nuances=nuances))
        self.assertTrue(any("contexte" in issue for issue in result.hard))

    def test_distinct_sections_are_accepted(self):
        facts = (
            "Le ministère a publié une règle pour les trains régionaux. Elle entre en vigueur "
            "en septembre, fixe un délai de trente jours et prévoit un formulaire numérique. "
        ) * 5
        context = (
            "Le dispositif remplace une procédure créée en 2019. Les régions géraient jusque-là "
            "leurs propres délais, ce qui produisait des calendriers différents selon les réseaux. "
        ) * 4
        nuances = (
            "Les billets internationaux ne sont pas concernés. Les associations de voyageurs "
            "demandent encore des précisions sur les correspondances et les abonnements annuels. "
        ) * 3
        result = section_depth(make_article(facts=facts, context=context, nuances=nuances))
        self.assertEqual([], result.hard)

    def test_long_article_without_depth_is_rejected(self):
        result = section_depth(make_article(
            facts="Le décret entre en vigueur lundi. " * 40,
            context="", nuances="",
        ))
        self.assertTrue(any("sans contexte" in issue for issue in result.hard))

    def test_brief_is_not_forced_into_sections(self):
        result = section_depth(make_article(
            facts="Le décret entre en vigueur lundi.", context="", nuances="", fmt="breve", words=120,
        ))
        self.assertEqual([], result.hard)

    def test_heading_must_be_grounded(self):
        section = "Le décret fixe un délai de trente jours pour demander un remboursement."
        self.assertTrue(validate_heading("Un délai de trente jours pour les remboursements", section))
        self.assertFalse(validate_heading("Une révolution historique pour tous les voyageurs", section))
        self.assertFalse(validate_heading("Les faits", section))

    def test_apply_headings_preserves_section_identity(self):
        html = '''<!DOCTYPE html><html><head></head><body>
        <h2 class="art__h2">Les faits</h2><p>Le décret fixe un délai de trente jours.</p>
        <h2 class="art__h2">Contexte</h2><p>La procédure précédente datait de 2019.</p>
        <h2 class="art__h2">Débats et nuances</h2><p>Les billets internationaux sont exclus.</p>
        </body></html>'''
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "article.html"
            path.write_text(html, encoding="utf-8")
            article = make_article(
                facts="Le décret fixe un délai de trente jours.",
                context="La procédure précédente datait de 2019.",
                nuances="Les billets internationaux sont exclus.",
            )
            article.path = path
            changed = apply_headings(article, {
                "faits": "Un délai de trente jours fixé par décret",
                "contexte": "Une procédure héritée de 2019",
                "nuances": "Les billets internationaux restent exclus",
            })
            self.assertTrue(changed)
            result = path.read_text(encoding="utf-8")
            self.assertIn('data-section="faits"', result)
            self.assertIn("Une procédure héritée de 2019", result)
            self.assertNotIn(">Contexte<", result)

    def test_probable_same_dispatch_is_reported(self):
        sources = [
            Source("Média A", "Le gouvernement annonce une nouvelle règle pour les trains", "https://a.test/x"),
            Source("Média B", "Le gouvernement annonce une nouvelle règle pour les trains régionaux", "https://b.test/x"),
            Source("Média C", "Nouvelle règle pour les trains annoncée par le gouvernement", "https://c.test/x"),
        ]
        article = make_article(
            facts="Fait précis. " * 80, context="Contexte distinct. " * 40,
            nuances="Limite documentée. " * 30, sources=sources,
        )
        self.assertIsNotNone(sourcing_warning(article))

    def test_primary_source_prevents_dispatch_warning(self):
        sources = [
            Source("Ministère", "Le gouvernement annonce une nouvelle règle pour les trains", "https://transport.gouv.fr/regle"),
            Source("Média B", "Le gouvernement annonce une nouvelle règle pour les trains régionaux", "https://b.test/x"),
            Source("Média C", "Nouvelle règle pour les trains annoncée par le gouvernement", "https://c.test/x"),
        ]
        article = make_article(
            facts="Fait précis. " * 80, context="Contexte distinct. " * 40,
            nuances="Limite documentée. " * 30, sources=sources,
        )
        self.assertIsNone(sourcing_warning(article))


if __name__ == "__main__":
    unittest.main(verbosity=2)
