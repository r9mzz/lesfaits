# -*- coding: utf-8 -*-
"""Non-régression : un sujet sans preuve précise est ignoré sans tuer le run."""
from __future__ import annotations

from run_pipeline_v3 import _patch_zero_precise_sources_abort


SOURCE = '''def f(extra):
    _pertinence = True
    _RANG_PERTINENCE = {"pertinente": 0, "generale": 1, "": 1, "hors_sujet": 2}
    JUGE_SOURCES_MAX = 10
    if _pertinence:
        extra = sorted(extra, key=lambda s: 0)
        _n_pert = sum(1 for s in extra if s.get("_pertinence") == "pertinente")
        print(f"     [PERTINENCE] {_n_pert} source(s) traitant le sujet précis, "
              f"{sum(1 for s in extra if s.get('_pertinence') == 'generale')} générale(s), "
              f"{sum(1 for s in extra if s.get('_pertinence') == 'hors_sujet')} hors sujet")
        # AVERTISSEMENT seulement, pas un rejet — le taux réel de « zéro source
        # pertinente » n'a jamais été mesuré sur un run complet, et la règle du
        # projet interdit de rendre bloquant un contrôle dont on ignore le taux
        # de déclenchement. À rendre bloquant quand quelques runs l'auront
        # chiffré : c'est exactement le cas rougeole.
        if _n_pert == 0:
            print("     [PERTINENCE] AUCUNE source ne traite le sujet précis du "
                  "titre — cas « rougeole », article probablement creux")
    return "generation"
'''


def _run(extra):
    patched = _patch_zero_precise_sources_abort(SOURCE)
    ns = {}
    exec(patched, ns)
    return ns["f"](extra)


def test_full_judged_batch_without_precise_source_is_skipped_cleanly():
    extra = [{"_pertinence": "generale"} for _ in range(10)]
    assert _run(extra) is False


def test_partial_judgment_never_blocks():
    extra = [{"_pertinence": "generale"} for _ in range(5)] + [{} for _ in range(5)]
    assert _run(extra) == "generation"


def test_one_precise_source_keeps_generation():
    extra = [{"_pertinence": "pertinente"}] + [{"_pertinence": "generale"} for _ in range(9)]
    assert _run(extra) == "generation"


def test_rejected_subject_does_not_abort_following_subject():
    batches = [
        [{"_pertinence": "generale"} for _ in range(10)],
        [{"_pertinence": "pertinente"}] + [{"_pertinence": "generale"} for _ in range(9)],
    ]
    results = [_run(batch) for batch in batches]
    assert results == [False, "generation"]


def main():
    test_full_judged_batch_without_precise_source_is_skipped_cleanly()
    test_partial_judgment_never_blocks()
    test_one_precise_source_keeps_generation()
    test_rejected_subject_does_not_abort_following_subject()
    print("OK — zéro source précise ignore le sujet sans interrompre le run")


if __name__ == "__main__":
    main()
