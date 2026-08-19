# -*- coding: utf-8 -*-
"""Verrouille la couverture CI de la table de fenêtres partagée.

`fenetres_modeles.py` pilote à la fois le budget de génération et celui du
fact-checker. Une modification de cette table doit donc déclencher les deux
contrôles qui protègent ces chemins runtime, et la régression dédiée au
correcteur doit réellement être exécutée.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERIFICATION_CI = ROOT / ".github" / "workflows" / "verification-provider-ci.yml"
RUNTIME_CI = ROOT / ".github" / "workflows" / "runtime-preflight-v3-ci.yml"


def _count(text: str, needle: str, minimum: int, label: str) -> None:
    found = text.count(needle)
    assert found >= minimum, f"{label}: {needle!r} apparaît {found} fois, attendu >= {minimum}"


def main() -> None:
    verification = VERIFICATION_CI.read_text(encoding="utf-8")
    runtime = RUNTIME_CI.read_text(encoding="utf-8")

    # Dans verification-provider : path trigger + compilation.
    _count(verification, "scripts/fenetres_modeles.py", 2, "Verification provider CI")
    # Régression du budget correcteur : path trigger + compilation + exécution.
    _count(verification, "scripts/test_fenetre_correcteur.py", 3, "Verification provider CI")
    # Le contrat lui-même doit aussi rester surveillé, compilé et exécuté.
    _count(verification, "scripts/test_fenetres_modeles_ci_contract.py", 3, "Verification provider CI")

    # La génération consomme la même table : un changement doit déclencher et
    # compiler la table avant de rejouer le prévol runtime V3.
    _count(runtime, "scripts/fenetres_modeles.py", 2, "Runtime preflight V3 CI")

    print("OK — table de fenêtres partagée couverte côté vérification et runtime")


if __name__ == "__main__":
    main()
