# -*- coding: utf-8 -*-
"""Non-régression : une enquête descriptive n'a pas de phase clinique."""
from __future__ import annotations

import verification
import run_pipeline_v3


def main() -> None:
    original = verification.PROMPT_DETECTION
    run_pipeline_v3._patch_verification_evidence_scope()
    patched = verification.PROMPT_DETECTION

    assert patched != original
    assert "POUR UN ESSAI, UNE ÉTUDE CLINIQUE, PRÉCLINIQUE OU D'EFFICACITÉ" in patched
    assert "NE PAS appliquer ce critère de « stade/phase » à une enquête descriptive" in patched
    assert "population étudiée, la période, la taille/constitution de l'échantillon" in patched

    # Les exigences médicales restent présentes : le correctif ne neutralise
    # ni les phases d'essai ni les contrôles d'indicateur/comparateur.
    assert "phase 1/1b/2/3" in patched
    assert "survie SANS PROGRESSION" in patched
    assert "COMPARATEUR" in patched

    print("OK — périmètre niveau_preuve_insuffisant corrigé sans baisse de garde")


if __name__ == "__main__":
    main()
