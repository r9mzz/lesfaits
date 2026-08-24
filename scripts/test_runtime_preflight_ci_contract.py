from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "runtime-preflight-v3-ci.yml"
RUNTIME = ROOT / "scripts" / "run_pipeline_v3.py"


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


def test_runtime_preflight_ci_tracks_rss_runtime_normalization() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    normalizer = "scripts/normalize_feed_pubdates.py"
    semantic_test = "scripts/test_feed_pubdates.py"
    runtime_test = "scripts/test_runtime_feed_pubdates_v3.py"

    assert text.count(normalizer) >= 2, (
        "la CI doit surveiller et compiler le normaliseur des dates RSS"
    )
    assert text.count(semantic_test) >= 3, (
        "la CI doit surveiller, compiler et exécuter le test sémantique des dates RSS"
    )
    assert text.count(runtime_test) >= 4, (
        "la CI doit surveiller, compiler et exécuter le verrou de câblage RSS du runtime"
    )


def test_runtime_preflight_ci_tracks_sitemap_runtime_normalization() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    normalizer = "scripts/normalize_sitemap_lastmod.py"
    semantic_test = "scripts/test_sitemap_lastmod.py"
    runtime_test = "scripts/test_runtime_sitemap_v3.py"

    assert text.count(normalizer) >= 2, (
        "la CI doit surveiller et compiler le normaliseur des lastmod sitemap"
    )
    assert text.count(semantic_test) >= 3, (
        "la CI doit surveiller, compiler et exécuter le test sémantique du sitemap"
    )
    assert text.count(runtime_test) >= 4, (
        "la CI doit surveiller, compiler et exécuter le verrou de câblage sitemap du runtime"
    )


def test_runtime_preflight_ci_tracks_shared_model_resolver() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    resolver = "scripts/modele_fournisseur.py"
    assert text.count(resolver) >= 2, (
        "modele_fournisseur.py pilote le modèle de génération et de vérification : "
        "la CI runtime doit le surveiller et le compiler"
    )


def test_runtime_preflight_ci_matches_runtime_regression_suite() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    runtime = RUNTIME.read_text(encoding="utf-8")

    block = re.search(
        r"_RUNTIME_REGRESSION_TESTS\s*=\s*\((.*?)\)\n\n",
        runtime,
        flags=re.S,
    )
    assert block, "suite _RUNTIME_REGRESSION_TESTS introuvable dans run_pipeline_v3.py"
    tests = re.findall(r'"([^"]+\.py)"', block.group(1))
    assert tests, "suite runtime V3 vide"

    for test_name in tests:
        path = f"scripts/{test_name}"
        assert workflow.count(path) >= 3, (
            f"la CI doit surveiller, compiler et exécuter le même test que le runtime : {path}"
        )

    assert workflow.count("scripts/pipeline.py") >= 2, (
        "pipeline.py est exécuté par le runtime : la CI de prévol doit le surveiller et le compiler"
    )


if __name__ == "__main__":
    test_runtime_preflight_ci_tracks_native_precise_source_gate()
    test_runtime_preflight_ci_tracks_rss_runtime_normalization()
    test_runtime_preflight_ci_tracks_sitemap_runtime_normalization()
    test_runtime_preflight_ci_tracks_shared_model_resolver()
    test_runtime_preflight_ci_matches_runtime_regression_suite()
    print("OK: contrat CI du prévol runtime V3")
