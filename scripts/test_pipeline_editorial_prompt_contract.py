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


# ── FIDÉLITÉ AU TEMPS ET À LA MODALITÉ — 20/08 ───────────────────────────────
#
# Les 133 blocages du journal ne disent JAMAIS « le fait est faux ». Ils disent
# que le temps du verbe, la modalité ou l'attribution ne correspondent pas à ce
# que la source affirme :
#
#     36 niveau_preuve_insuffisant · 28 annonce_perimee · 23 chiffre_errone
#     21 incoherence_inter_sections · 15 accusation_presentee_comme_fait
#
# Cas réels : « a officialisé la création » quand la source écrit « veut une
# nouvelle unité » ; un essai présenté comme une efficacité acquise ; la
# qualification d'un député rapportée comme un constat.
#
# Le prompt évoquait ces notions de façon éparse (« conditionnel » 2 fois,
# « préliminaire » 2 fois) sans jamais énoncer la règle générale. Ce test
# vérifie qu'elle y est, et couvre les quatre familles de blocage.
def test_regle_de_fidelite_a_la_source():
    import os as _os
    import sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    _os.environ.setdefault("GROQ_API_KEY", "x")
    import pipeline as _P

    prompt = _P.SYSTEM_PROMPT
    assert "FIDÉLITÉ AU TEMPS ET À LA MODALITÉ" in prompt, (
        "la règle qui vise la cause n°1 des rejets a disparu du prompt")
    for attendu, famille in (
        ("veut", "annonce_perimee — projet présenté comme fait accompli"),
        ("préliminaire", "niveau_preuve_insuffisant — marqueur d'incertitude"),
        ("conditionnel", "modalité durcie"),
        ("SA position", "accusation_presentee_comme_fait"),
        ("réserve", "chiffre_errone — réserve détachée du chiffre"),
    ):
        assert attendu in prompt, f"famille non couverte : {famille}"
    # La règle ne doit PAS pousser à inventer des limites absentes des sources :
    # ce serait contredire la règle 5 (rien hors des extraits fournis), et neuf
    # des reproches du juge demandent précisément cela.
    assert "n'en invente pas" in prompt, (
        "la règle autorise implicitement à inventer une limite méthodologique")


def test_la_numerotation_des_regles_reste_unique():
    """Défaut du 29/07 : 26 règles pour 23 numéros, les 13/14/15 dupliqués.

    Il est revenu le 20/08 — deux règles « 27. » coexistaient AVANT mon ajout.
    Un numéro dupliqué rend ambiguë toute référence à « la règle N », dans ce
    fichier comme dans les tests.
    """
    import os as _os
    import re as _re
    import sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    _os.environ.setdefault("GROQ_API_KEY", "x")
    import pipeline as _P

    debut = _P.SYSTEM_PROMPT.index("RÈGLES ABSOLUES")
    nums = [int(m.group(1))
            for m in _re.finditer(r"^(\d+)\. ", _P.SYSTEM_PROMPT[debut:], _re.M)]
    assert nums == list(range(1, len(nums) + 1)), (
        f"numérotation des RÈGLES ABSOLUES non séquentielle : {nums}")


test_regle_de_fidelite_a_la_source()
test_la_numerotation_des_regles_reste_unique()
print("OK — fidélité à la source énoncée, numérotation unique")
