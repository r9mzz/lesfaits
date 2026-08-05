# -*- coding: utf-8 -*-
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from editorial_quality import (  # noqa: E402
    ArticleRecord, Source, annotate_attributions, repeated_statement,
    same_event, timeline_conflict,
)


def article(title, urls, *, date="2026-08-05", body="", slug="x"):
    return ArticleRecord(
        path=Path(f"{slug}.html"), slug=slug, title=title, lead=body, facts="",
        context="", nuances="", date_iso=date,
        sources=[Source(name=f"S{i}", title=title, url=u) for i, u in enumerate(urls, 1)],
        is_new=True,
    )


class EditorialQualityTests(unittest.TestCase):
    def test_same_event_with_shared_source(self):
        a = article(
            "Collision lunaire d’une fusée SpaceX",
            ["https://example.com/spacex-lune", "https://media.test/a"], slug="a",
        )
        b = article(
            "Une fusée SpaceX s’écrase sur la Lune",
            ["https://example.com/spacex-lune?utm_source=rss", "https://media.test/b"], slug="b",
        )
        self.assertTrue(same_event(a, b))

    def test_different_events_same_company_not_duplicate(self):
        a = article("SpaceX lance une fusée vers Mars", ["https://a.test/mars"], slug="a")
        b = article("SpaceX reporte le vol d’une fusée météo", ["https://b.test/meteo"], slug="b")
        self.assertFalse(same_event(a, b))

    def test_timeline_conflict(self):
        text = "La fusée devait s’écraser mercredi. Elle a percuté la Lune à 8 heures."
        self.assertTrue(timeline_conflict(text))

    def test_timeline_transition_is_allowed(self):
        text = "La fusée devait s’écraser mercredi, puis elle a percuté la Lune à 8 heures."
        self.assertFalse(timeline_conflict(text))

    def test_repeated_statement(self):
        text = (
            "La collision ne présente aucun danger pour la Terre et laissera un cratère. "
            "La collision ne présente aucun danger pour la Terre mais intéresse les chercheurs."
        )
        self.assertTrue(repeated_statement(text))

    def test_numbered_attribution(self):
        sources = [
            Source("France Info", "Titre A", "https://a.test"),
            Source("Le Monde", "Titre B", "https://b.test"),
        ]
        result = annotate_attributions(
            "Selon France Info et Le Monde, la mesure entre en vigueur lundi.", sources
        )
        self.assertNotIn("Selon", result)
        self.assertIn('href="#source-1"', result)
        self.assertIn('href="#source-2"', result)
        self.assertTrue(result.startswith("La mesure"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
