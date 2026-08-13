# -*- coding: utf-8 -*-
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from editorial_quality import (  # noqa: E402
    ArticleRecord, Source, annotate_attributions, improve_article_html,
    parse_article, quality_issues, repeated_statement, same_event,
    timeline_conflict,
)

ROOT = Path(__file__).resolve().parent.parent


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

    def test_real_spacex_regression(self):
        # Le premier article réel a été consolidé le 06/08 et son fichier est
        # désormais un stub de redirection. Conserver ici les caractéristiques
        # éditoriales du doublon d'origine rend la régression stable sans
        # dépendre de l'état courant du corpus ni affaiblir le détecteur.
        a = article(
            "Collision lunaire d’une fusée SpaceX",
            [
                "https://example.com/impact-fusee-lune",
                "https://media.test/collision-lunaire",
            ],
            body=(
                "La fusée devait s’écraser mercredi. "
                "Elle a percuté la Lune à plus de 8 500 kilomètres par heure."
            ),
            slug="collision-lunaire-fusee-spacex",
        )
        b = article(
            "Fusée SpaceX s’écrase sur la Lune",
            [
                "https://example.com/impact-fusee-lune?utm_source=rss",
                "https://media.test/fusee-spacex",
            ],
            slug="fusee-spacex-ecrase-lune",
        )
        self.assertTrue(same_event(a, b))
        self.assertTrue(timeline_conflict(a.lead + " " + a.facts))

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

    def test_repeated_statement_ignores_le_nom_du_sujet(self):
        """Nommer deux fois le sujet n'est pas une redite.

        Ces deux phrases ne partagent que le nom propre et un syntagme de
        thème. Avant le 13/08 elles suffisaient à un rejet dur : le 5-gramme
        « le cheval blanc d uffington » ne porte que deux mots de fond, les
        trois autres étant des articles absents de `_STOPWORDS`. Le contrôle
        rejetait ainsi 96 % des articles publiés.
        """
        text = (
            "La conservation du patrimoine culturel est un défi pour les géoglyphes "
            "anciens comme le cheval blanc d'Uffington. "
            "Le cheval blanc d'Uffington est un géoglyphe situé dans l'Oxfordshire, "
            "en Angleterre, qui date d'environ trois mille ans."
        )
        self.assertFalse(repeated_statement(text))

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

    def test_brief_with_generic_filler_is_rejected(self):
        a = article(
            "Une découverte scientifique annoncée",
            ["https://a.test/etude"],
            body="Cette découverte pourrait révolutionner le secteur dans les années à venir.",
        )
        a.format = "breve"
        hard, _ = quality_issues(a)
        self.assertTrue(any("remplissage générique" in issue for issue in hard))

    def test_html_citations_and_transparency_wording(self):
        html = '''<!DOCTYPE html><html lang="fr"><head></head><body>
        <p class="art__resume">Selon France Info et Le Monde, la mesure entre en vigueur lundi.</p>
        <h2 class="art__h2">Les faits</h2><p>Selon France Info, le texte a été publié.</p>
        <div class="art__ai-badge">✓ 2 sources vérifiées</div>
        <div class="art__pourquoi">Le fact-check automatisé n'a relevé aucune anomalie : article publié tel que généré.</div>
        <section class="sources"><ol>
        <li><cite>France Info</cite><em>Titre A</em><a href="https://a.test">Lire</a></li>
        <li><cite>Le Monde</cite><em>Titre B</em><a href="https://b.test">Lire</a></li>
        </ol></section></body></html>'''
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.html"
            path.write_text(html, encoding="utf-8")
            record = ArticleRecord(
                path=path, slug="test", title="Test", lead="", facts="",
                context="", nuances="", date_iso="2026-08-05",
                sources=[
                    Source("France Info", "Titre A", "https://a.test"),
                    Source("Le Monde", "Titre B", "https://b.test"),
                ],
            )
            improve_article_html(record)
            result = path.read_text(encoding="utf-8")
            self.assertIn('id="source-1"', result)
            self.assertIn('href="#source-1"', result)
            self.assertIn("2 sources consultées", result)
            self.assertIn("aucun défaut bloquant", result)
            self.assertNotIn("Selon France Info et Le Monde", result)

    def test_generation_prompt_is_reinforced(self):
        import types
        from run_pipeline import EDITORIAL_ADDENDUM, _patch_groq_generation_prompt

        captured = {}

        class FakeCompletions:
            def create(self, *args, **kwargs):
                captured.update(kwargs)
                return object()

        class FakeChat:
            completions = FakeCompletions()

        class FakeClient:
            chat = FakeChat()

        fake_groq = types.ModuleType("groq")
        fake_groq.Groq = lambda *args, **kwargs: FakeClient()
        previous = sys.modules.get("groq")
        try:
            sys.modules["groq"] = fake_groq
            _patch_groq_generation_prompt()
            client = fake_groq.Groq(api_key="test")
            client.chat.completions.create(messages=[{
                "role": "system",
                "content": "Tu es l'IA rédactrice de Les Faits, journal numérique français indépendant.",
            }])
            content = captured["messages"][0]["content"]
            self.assertIn("CONSIGNE PREMIUM DE LISIBILITÉ", content)
            self.assertIn(EDITORIAL_ADDENDUM.strip(), content)
        finally:
            if previous is None:
                sys.modules.pop("groq", None)
            else:
                sys.modules["groq"] = previous


if __name__ == "__main__":
    unittest.main(verbosity=2)