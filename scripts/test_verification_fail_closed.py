# -*- coding: utf-8 -*-
"""Régression : aucun article ne doit être publiable sans fact-check abouti."""
from __future__ import annotations

import verification


def _article():
    return {"slug": "article-test", "titre": "Article test", "corps": {}}


def _run_with_status(status: str) -> str:
    original = verification._provider_original_verifier_article
    original_log = verification._log
    logs = []
    try:
        verification._provider_original_verifier_article = lambda *a, **kw: (_article(), status)
        verification._log = lambda slug, statut, detail=None: logs.append((slug, statut, detail or {}))
        article, final_status = verification.verifier_article(_article())
        assert article["slug"] == "article-test"
        if status in {"erreur_verification", "non_verifie"}:
            assert final_status == "rejete_qualite", (status, final_status)
            assert logs, "le rejet fail-closed doit être journalisé"
            assert logs[-1][1] == "rejete_qualite"
            assert logs[-1][2]["raison"] == "verification_indisponible"
            assert logs[-1][2]["statut_verification_initial"] == status
        else:
            assert final_status == status, (status, final_status)
            assert not logs, "un statut de vérification abouti ne doit pas être réécrit"
        return final_status
    finally:
        verification._provider_original_verifier_article = original
        verification._log = original_log


def main() -> None:
    assert _run_with_status("erreur_verification") == "rejete_qualite"
    assert _run_with_status("non_verifie") == "rejete_qualite"
    assert _run_with_status("conforme_du_premier_coup") == "conforme_du_premier_coup"
    assert _run_with_status("corrige_automatiquement") == "corrige_automatiquement"
    assert _run_with_status("rejete_sensible") == "rejete_sensible"
    assert _run_with_status("rejete_qualite") == "rejete_qualite"
    print("OK — vérification indisponible = rejet, jamais publication")


if __name__ == "__main__":
    main()
