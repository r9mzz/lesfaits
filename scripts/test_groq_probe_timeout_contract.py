#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Régression : le workflow Groq doit laisser assez de temps à la sonde 65 s."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "groq_check.yml"
PROBE = ROOT / "scripts" / "sonde_taille_requete.py"


def main() -> int:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    probe = PROBE.read_text(encoding="utf-8")

    assert "python3 scripts/sonde_taille_requete.py" in workflow, (
        "groq_check.yml n'appelle plus la sonde versionnée"
    )
    assert "sleep(65)" in probe or "sleep(65.0)" in probe, (
        "le contrat doit être revu si l'attente de la sonde change"
    )

    match = re.search(r"timeout-minutes:\s*(\d+)", workflow)
    assert match, "timeout-minutes absent de groq_check.yml"
    timeout = int(match.group(1))
    assert timeout >= 30, (
        f"timeout Groq insuffisant ({timeout} min) pour une sonde qui attend 65 s entre essais"
    )

    print(f"OK — timeout Groq {timeout} min compatible avec la sonde à 65 s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
