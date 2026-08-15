# -*- coding: utf-8 -*-
"""Non-régression du garde [PERTINENCE] 0 source (rendu bloquant le 15/08).

Importe la fonction RÉELLE de pipeline.py, pas une fixture recopiée. Le bug
du 15/08 (main cassé, run du soir mort à zéro article) venait d'un test qui
validait un patch contre sa propre copie du texte plutôt que contre le
fichier réel — un patch par marqueur pouvait donc diverger silencieusement
d'un commit qui reformulait ce même texte, sans qu'aucun test ne le voie.
Importer directement la fonction élimine cette classe de bug par construction.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline import _lot_entierement_juge_sans_source_precise as gate


def test_lot_entierement_juge_sans_source_precise_bloque():
    extra = [{"_pertinence": "generale"} for _ in range(10)]
    assert gate(extra, 10) is True


def test_jugement_partiel_ne_bloque_jamais():
    extra = [{"_pertinence": "generale"} for _ in range(5)] + [{} for _ in range(5)]
    assert gate(extra, 10) is False


def test_lot_plus_court_que_le_plafond_juge_reste_bloquant_si_complet():
    extra = [{"_pertinence": "hors_sujet"} for _ in range(3)]
    assert gate(extra, 10) is True


def test_lot_vide_ne_bloque_pas():
    assert gate([], 10) is False


if __name__ == "__main__":
    test_lot_entierement_juge_sans_source_precise_bloque()
    test_jugement_partiel_ne_bloque_jamais()
    test_lot_plus_court_que_le_plafond_juge_reste_bloquant_si_complet()
    test_lot_vide_ne_bloque_pas()
    print("OK — test_pertinence_bloquant.py")
