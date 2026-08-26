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


def test_future_projection_is_not_annonce_perimee_by_itself() -> None:
    prompt = verification.PROMPT_DETECTION
    assert "le simple emploi du futur, du conditionnel" in prompt
    assert "une prévision, un scénario, une échéance ou un événement encore futur" in prompt
    assert "elle ne la rend pas périmée" in prompt
    assert "un extrait plus récent établit explicitement" in prompt
    assert "Ne transforme jamais une simple différence de temps grammatical" in prompt


def test_current_application_is_compatible_with_past_entry_into_force() -> None:
    prompt = verification.PROMPT_DETECTION
    assert "ÉTAT EN VIGUEUR" in prompt
    assert "est entrée en vigueur" in prompt
    assert "en cours d'application" in prompt
    assert "éventuel défaut de preuve sur la date" in prompt

    faux_positif = {
        "bloc": 1,
        "type": "annonce_perimee",
        "phrase": "La réforme est entrée en vigueur au début de l'année.",
        "description": "La source décrit une réforme en cours d'application et non un événement passé.",
    }
    assert verification._entree_en_vigueur_pas_perimee(faux_positif) is True

    date_non_prouvee = {
        "bloc": 1,
        "type": "annonce_perimee",
        "phrase": "La réforme est entrée en vigueur le 1er janvier 2026.",
        "description": "La source décrit une réforme en cours d'application mais ne confirme pas explicitement la date du 1er janvier 2026.",
    }
    assert verification._entree_en_vigueur_pas_perimee(date_non_prouvee) is False

    vrai_changement_etat = {
        "bloc": 1,
        "type": "annonce_perimee",
        "phrase": "La réforme est entrée en vigueur au début de l'année.",
        "description": "La réforme est en cours d'application mais a ensuite été remplacée par un nouveau dispositif.",
    }
    assert verification._entree_en_vigueur_pas_perimee(vrai_changement_etat) is False


def test_real_annonce_perimee_definition_remains_strict() -> None:
    prompt = verification.PROMPT_DETECTION
    assert "présente comme À VENIR" in prompt
    assert "DÉJÀ SURVENU" in prompt
    assert "le TEXTE DE L'ARTICLE présente comme futur, actuel ou définitif" in prompt


if __name__ == "__main__":
    test_retrospective_source_date_rule_is_in_runtime_prompt()
    test_future_projection_is_not_annonce_perimee_by_itself()
    test_current_application_is_compatible_with_past_entry_into_force()
    test_real_annonce_perimee_definition_remains_strict()
    print("OK — chronologie rétrospective, futur réel et état en vigueur verrouillés")
