"""Régression : un A/B incomplet ne doit jamais terminer vert."""
import test_model_compare as m


def _sujet():
    return {"title": "Sujet test", "content": "contenu", "url": "https://example.test"}


def test_echec_generation_rend_le_run_rouge():
    original_collecter = m.collecter_sujets
    original_generer = m.generer_avec_modele
    try:
        m.collecter_sujets = lambda n: [_sujet()]
        m.generer_avec_modele = lambda item, modele: (
            {"ok": False, "erreur": "model_not_found"}
            if modele == m.MODELES[0]
            else {"ok": True, "article": {"titre": "ok", "resume": [], "corps": {}, "nb_sources": 1}}
        )
        assert m.main() == 1
    finally:
        m.collecter_sujets = original_collecter
        m.generer_avec_modele = original_generer


def test_toutes_generations_ok_rend_le_run_vert():
    original_collecter = m.collecter_sujets
    original_generer = m.generer_avec_modele
    try:
        m.collecter_sujets = lambda n: [_sujet()]
        m.generer_avec_modele = lambda item, modele: {
            "ok": True,
            "article": {"titre": "ok", "resume": [], "corps": {}, "nb_sources": 1},
        }
        assert m.main() == 0
    finally:
        m.collecter_sujets = original_collecter
        m.generer_avec_modele = original_generer


if __name__ == "__main__":
    test_echec_generation_rend_le_run_rouge()
    test_toutes_generations_ok_rend_le_run_vert()
    print("OK — contrat de sortie A/B")
