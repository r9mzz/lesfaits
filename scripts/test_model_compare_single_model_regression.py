"""Régression : un comparatif A/B ne doit jamais accepter un seul modèle."""
import io
from contextlib import redirect_stdout

import test_model_compare as m


def test_single_model_is_rejected_before_collection():
    original_modeles = m.MODELES
    original_collecter = m.collecter_sujets
    try:
        m.MODELES = ["modele-seul"]
        m.collecter_sujets = lambda n: (_ for _ in ()).throw(
            AssertionError("aucune collecte ne doit avoir lieu sans deux modèles")
        )
        sortie = io.StringIO()
        with redirect_stdout(sortie):
            code = m.main()
        assert code == 1
        assert "comparaison A/B impossible" in sortie.getvalue()
    finally:
        m.MODELES = original_modeles
        m.collecter_sujets = original_collecter


if __name__ == "__main__":
    test_single_model_is_rejected_before_collection()
    print("OK — mono-modèle refusé avant collecte")
