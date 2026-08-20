"""Le juge ne peut exiger que ce que les extraits contiennent.

── POURQUOI CETTE RÈGLE, ET POURQUOI ELLE N'AFFAIBLIT RIEN ───────────────────

Le rédacteur a l'interdiction ABSOLUE d'écrire un fait absent des sources
(règle 5 de sa charte). Quand le fact-checker lui reproche une information que
les extraits ne contiennent pas — « l'article ne précise pas la taille de
l'échantillon » alors qu'aucun extrait ne la donne — il exige littéralement
qu'il l'invente. Les deux consignes se contredisent, et l'article est bloqué
quoi qu'il fasse.

Mesuré sur le journal, avant correctif :

    36 reproches niveau_preuve_insuffisant, dont
        14 demandent un marqueur d'incertitude       → LÉGITIMES, satisfiables
         9 demandent des limites méthodologiques      → souvent absentes
         6 disent que la source contient l'info omise → LÉGITIMES

    3 reproches bloquants sur 163 spéculent : « la source [2] les détaille
    PROBABLEMENT ». Rare (2 %), mais ça a coûté l'article Ebola du run 253.

La règle ne retire donc aucun motif et ne baisse aucun seuil : elle interdit
d'exiger l'impossible et de bloquer sur une hypothèse. Un reproche fondé sur
un extrait reste bloquant à l'identique.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("GROQ_API_KEY", "x")

import verification_legacy as V  # noqa: E402


def test_la_regle_de_symetrie_est_dans_le_prompt():
    p = V.PROMPT_DETECTION
    assert "RÈGLE DE SYMÉTRIE" in p
    assert "QUE ce qui figure dans les extraits fournis" in p
    assert "N'EST PAS un problème" in p, (
        "la règle décrit l'interdiction sans dire ce que le juge doit conclure")


def test_la_speculation_est_explicitement_interdite():
    """Cas réel du run 253, article Ebola en RDC : « la phrase ne précise pas
    le stade des études précliniques, alors que la source [2] les détaille
    PROBABLEMENT ». Un article bloqué sur une hypothèse."""
    p = V.PROMPT_DETECTION
    assert "probablement" in p.lower() and "supposition" in p.lower()


def test_le_motif_reste_bloquant():
    """⚠ La règle ne désarme RIEN. `niveau_preuve_insuffisant` doit rester dans
    les motifs bloquants : ses reproches dominants (stade de la recherche omis
    alors que la source le donne) visent un défaut réel, ajouté le 31/07 après
    une revue éditoriale externe.
    """
    faux = [{"bloc": 1, "type": "niveau_preuve_insuffisant"}]
    assert V._problemes_bloquants(faux), (
        "niveau_preuve_insuffisant a cessé d'être bloquant — ce n'était pas "
        "l'objet du correctif de symétrie")
    for t in ("chiffre_errone", "incoherence_inter_sections", "annonce_perimee",
              "accusation_presentee_comme_fait"):
        assert V._problemes_bloquants([{"bloc": 1, "type": t}]), t
    assert V._problemes_bloquants([{"bloc": 2, "type": "source_inventee"}])


def test_les_conditions_legitimes_survivent():
    """Les clauses (a), (b), (c) — stade omis alors que la source le donne,
    indicateurs interchangés, comparateur absent — sont intactes."""
    p = V.PROMPT_DETECTION
    for garde in ("stade de la recherche", "survie SANS PROGRESSION",
                  "COMPARATEUR soit identifié"):
        assert garde in p, f"condition légitime perdue : {garde}"


if __name__ == "__main__":
    test_la_regle_de_symetrie_est_dans_le_prompt()
    test_la_speculation_est_explicitement_interdite()
    test_le_motif_reste_bloquant()
    test_les_conditions_legitimes_survivent()
    print("OK — le juge n'exige que ce que les extraits contiennent, sans rien désarmer")
