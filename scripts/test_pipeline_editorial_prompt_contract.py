from pathlib import Path


PIPELINE = Path(__file__).with_name("pipeline.py")


def main() -> None:
    source = PIPELINE.read_text(encoding="utf-8")

    # Contrat de rédaction ajouté après le diagnostic du 15/08 : la règle
    # contre les enchaînements monotones doit vivre dans le vrai pipeline,
    # pas seulement dans un wrapper ou une documentation non exécutée.
    required = (
        "VARIÉTÉ DE PHRASE — INTERDICTION DE LA CHAÎNE MONOTONE",
        "jamais plus",
        "phrases consécutives",
        "[Acteur] a/ont [verbe]",
    )
    missing = [fragment for fragment in required if fragment not in source]
    assert not missing, f"Contrat rédactionnel absent de pipeline.py: {missing}"

    print("OK: le prompt runtime conserve le garde anti-chaîne monotone")


if __name__ == "__main__":
    main()
