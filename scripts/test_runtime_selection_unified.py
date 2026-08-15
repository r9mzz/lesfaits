# -*- coding: utf-8 -*-
"""Régression : V3 ne doit jamais remplacer la sélection native de pipeline.py.

Le 14/08, des correctifs importants avaient été ajoutés à
``selectionner_meilleurs`` (signal de veille et un seul événement par run),
mais ``run_pipeline_v3.py`` remplaçait ensuite toute la fonction au runtime.
Le code relu et le code exécuté divergeaient donc silencieusement.

Ce test vérifie que V3 conserve mot pour mot une sélection native sentinelle et
n'injecte plus le vieux chemin ``selectionner_sujets``. Le cooldown exact
post-génération, lui, doit rester actif.
"""
from __future__ import annotations

import run_pipeline_v3 as v3


SAMPLE = '''
QUOTA_CATEGORIE = 6

def selectionner_meilleurs(candidats, nb_max=10, quota_cat=QUOTA_CATEGORIE):
    # SIGNAL_VEILLE_CANONIQUE : sentinelle du test
    grappes_vues = set()
    selection = []
    for item in candidats:
        grappe = (item.get("_veille") or {}).get("grappe")
        if grappe and grappe in grappes_vues:
            continue
        selection.append(item)
        if grappe:
            grappes_vues.add(grappe)
    return selection


def _extract_json(raw):
    return {"slug": "test"}


def generer():
    raw = "{}"
    art = _extract_json(raw)
    return art
'''


def main() -> None:
    original = v3._original_prepared_pipeline_source
    try:
        v3._original_prepared_pipeline_source = lambda: SAMPLE
        out = v3._prepared_pipeline_source_v3()
    finally:
        v3._original_prepared_pipeline_source = original

    assert "SIGNAL_VEILLE_CANONIQUE" in out, "V3 a écrasé la sélection native"
    assert out.count("def selectionner_meilleurs") == 1, "sélection dupliquée"
    assert "selectionner_sujets" not in out, "ancien cerveau de classement encore injecté"
    assert "[COOLDOWN REJET]" in out, "cooldown post-génération perdu"
    print("OK — sélection native conservée, cooldown V3 maintenu")


if __name__ == "__main__":
    main()
