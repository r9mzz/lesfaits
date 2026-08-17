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


if __name__ == "__main__":
    test_runtime_preflight_ci_tracks_native_precise_source_gate()
    test_runtime_preflight_ci_tracks_rss_runtime_normalization()
    test_runtime_preflight_ci_tracks_sitemap_runtime_normalization()
    print("OK: contrat CI du prévol runtime V3")
