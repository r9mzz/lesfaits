from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import verification  # noqa: E402


def test_retrospective_source_date_rule_is_in_runtime_prompt() -> None:
    prompt = verification.PROMPT_DETECTION
    assert "une source publiée APRÈS un événement peut parfaitement le décrire rétrospectivement" in prompt
    assert "n'est JAMAIS, à elle seule, un motif ``annonce_perimee``" in prompt
    assert "Ne déduis jamais qu'une source « ne peut pas décrire » un événement antérieur" in prompt


def test_real_annonce_perimee_definition_remains_strict() -> None:
    prompt = verification.PROMPT_DETECTION
    assert "présente comme À VENIR" in prompt
    assert "DÉJÀ SURVENU" in prompt
    assert "le TEXTE DE L'ARTICLE présente comme futur, actuel ou définitif" in prompt


if __name__ == "__main__":
    test_retrospective_source_date_rule_is_in_runtime_prompt()
    test_real_annonce_perimee_definition_remains_strict()
    print("OK — chronologie rétrospective du fact-checker verrouillée")
