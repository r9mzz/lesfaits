from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "runtime-preflight-v3-ci.yml"


def test_runtime_preflight_ci_tracks_native_precise_source_gate() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    removed = "scripts/test_zero_precise_sources_gate.py"
    replacement = "scripts/test_pertinence_bloquant.py"
    contract = "scripts/test_runtime_preflight_ci_contract.py"

    assert removed not in text, "la CI référence encore le test supprimé du garde de source précise"
    assert text.count(replacement) >= 3, (
        "la CI doit surveiller, compiler et exécuter le test natif de pertinence bloquante"
    )
    assert text.count(contract) >= 3, (
        "le test de contrat doit lui-même être surveillé, compilé et exécuté par la CI"
    )


if __name__ == "__main__":
    test_runtime_preflight_ci_tracks_native_precise_source_gate()
    print("OK: contrat CI du prévol runtime V3")
