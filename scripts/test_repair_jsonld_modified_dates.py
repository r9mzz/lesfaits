# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from repair_jsonld_modified_dates import repair_html, run  # noqa: E402


def html_with_dates(published: str, modified: str | None) -> str:
    payload = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": "Test",
        "datePublished": published,
    }
    if modified is not None:
        payload["dateModified"] = modified
    return (
        '<html><head><script type="application/ld+json">'
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + "</script></head><body></body></html>"
    )


class RepairDateModifiedTests(unittest.TestCase):
    def test_repairs_modified_before_publication(self):
        html = html_with_dates(
            "2026-08-14T15:40:11+02:00",
            "2026-08-14T13:57:51+02:00",
        )
        updated, count = repair_html(html)
        self.assertEqual(count, 1)
        self.assertIn(
            '"dateModified":"2026-08-14T15:40:11+02:00"', updated
        )

    def test_preserves_later_modified_date(self):
        html = html_with_dates(
            "2026-08-14T15:40:11+02:00",
            "2026-08-14T16:10:00+02:00",
        )
        updated, count = repair_html(html)
        self.assertEqual(count, 0)
        self.assertEqual(updated, html)

    def test_check_mode_reports_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp)
            (site / "articles").mkdir()
            path = site / "articles" / "inflation.html"
            original = html_with_dates(
                "2026-08-14T15:40:11+02:00",
                "2026-08-14T13:57:51+02:00",
            )
            path.write_text(original, encoding="utf-8")
            changed, errors = run(site, check=True)
            self.assertEqual(changed, 0)
            self.assertEqual(len(errors), 1)
            self.assertEqual(path.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
