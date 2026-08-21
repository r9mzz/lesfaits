#!/usr/bin/env python3
import copy
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

# Evite toute dépendance à des secrets réels pendant le test.
os.environ.setdefault("GROQ_API_KEY", "test-key")

import verification  # noqa: E402


def main() -> None:
    original_sources = [
        {"institution": "Source 1", "titre": "A", "url": "https://example.test/a"},
        {"institution": "Source 2", "titre": "B", "url": "https://example.test/b"},
        {"institution": "Source 3", "titre": "C", "url": "https://example.test/c"},
        {"institution": "Source 4", "titre": "D", "url": "https://example.test/d"},
        {"institution": "Source 5", "titre": "E", "url": "https://example.test/e"},
    ]
    article = {
        "slug": "test",
        "sources": copy.deepcopy(original_sources),
        "corps": {"faits": "Fait confirmé [5].", "contexte": "", "nuances": ""},
    }

    def faux_correcteur(art, *args, **kwargs):
        # Reproduit le défaut observé : le LLM renvoie un article corrigé avec
        # une liste de sources tronquée/réordonnée alors que le texte cite [5].
        corrige = copy.deepcopy(art)
        corrige["sources"] = [copy.deepcopy(original_sources[1])]
        corrige["corps"]["faits"] = "Fait confirmé [5], formulation corrigée."
        return corrige

    ancien = verification._provider_original_corriger
    try:
        verification._provider_original_corriger = faux_correcteur
        corrige = verification.corriger(article, {"problemes": []})
    finally:
        verification._provider_original_corriger = ancien

    assert corrige["sources"] == original_sources, (
        "La correction ne doit jamais modifier l'identité ni l'ordre des sources"
    )
    assert corrige["sources"] is not article["sources"], (
        "La liste restaurée doit être une copie indépendante"
    )
    assert corrige["corps"]["faits"].endswith("formulation corrigée."), (
        "Le verrou des sources ne doit pas annuler les corrections rédactionnelles"
    )
    print("OK: sources immuables pendant les passes de correction")


if __name__ == "__main__":
    main()
