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


# ── SEUIL PORTÉ À 3 — mesuré le 20/08 ────────────────────────────────────────
#
# Le run 252 a produit deux articles de 665 et 724 mots, bien écrits, rejetés
# parce qu'ils ne citaient que 2 sources. Le log dit pourquoi : « 2 sources
# traitant le sujet précis, 0 générale, 8 hors sujet ». Le rédacteur a fait ce
# qu'il fallait — refuser de citer du hors-sujet — et le plancher de
# publication l'a recalé.
#
# C'est mécanique : on ne peut pas citer honnêtement 3 sources quand 2
# seulement traitent le sujet. Soit le modèle triche (défaut « inflation » du
# 11/08), soit il est honnête et se fait rejeter. Les deux coûtent ~35 k tokens.
#
# Mesuré sur les 92 sujets instrumentés du journal :
#     1-2 pertinentes : 46 sujets → 0 mené au bout (0 %)
#     3 et plus       : 46 sujets → 2 menés au bout (4 %)
print("\n6. Le seuil de sources pertinentes est aligné sur le plancher de publication")

import os as _os  # noqa: E402
import pipeline as _P  # noqa: E402

assert _P.PERTINENCE_MIN_POUR_GENERER == 3, (
    "le plancher de sources pertinentes doit rester égal au plancher de "
    "publication de la charte (règle 7 : 3 sources citées)")
print("  OK   seuil = 3, comme le plancher de publication")

_src = open(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "pipeline.py"),
            encoding="utf-8").read()

assert "PERTINENCE_MIN_POUR_GENERER" in _src and "_n_pert < PERTINENCE_MIN_POUR_GENERER" in _src, (
    "le garde-fou de pré-génération n'utilise plus le seuil")
print("  OK   le garde-fou compare bien au seuil, pas à une valeur en dur")

# La prudence du 15/08 doit valoir pour le NOUVEAU seuil aussi : un lot
# partiellement jugé ne doit jamais rejeter un sujet jamais vraiment évalué.
_i = _src.index("elif _n_pert < PERTINENCE_MIN_POUR_GENERER")
_bloc = _src[_i:_i + 900]
assert "_lot_entierement_juge_sans_source_precise" in _bloc, (
    "le seuil 3 rejette sans vérifier que le lot a été entièrement jugé — "
    "un juge interrompu condamnerait un sujet jamais évalué")
assert "jugement partiel" in _bloc
print("  OK   un lot partiellement jugé ne déclenche aucun rejet")
