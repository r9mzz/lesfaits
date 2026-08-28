"""L'instrument doit refuser de conclure quand il n'a rien mesuré.

Quatre verdicts faux avant le bon sur `essai_juge_corpus` (20/08) : un
instrument qui confond « aucun problème » et « aucune réponse » produit une
conclusion actionnable à partir de rien. Les trois règles qui en sortent sont
verrouillées ici, sur le nouvel accumulateur.
"""
import json
import os
import subprocess
import sys
import tempfile
from unittest import mock

DOSSIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DOSSIER)

import analyser_reproches as A  # noqa: E402


def _lancer(entrees, *args):
    """Exécute le script sur un journal factice, rend (code, sortie)."""
    with tempfile.TemporaryDirectory() as d:
        data = os.path.join(d, "data")
        os.makedirs(data)
        chemin = os.path.join(data, "verification_log.json")
        with open(chemin, "w", encoding="utf-8") as f:
            json.dump(entrees, f)
        env = dict(os.environ)
        code = ("import sys; sys.path.insert(0, %r); "
                "import analyser_reproches as A; A.JOURNAL = %r; A.main()"
                % (DOSSIER, chemin))
        out = subprocess.run([sys.executable, "-c", code, *args],
                             capture_output=True, text=True, env=env)
        return out.returncode, out.stdout + out.stderr


def test_les_echecs_techniques_sortent_du_denominateur():
    """Une panne de quota ou un timeout n'est pas un verdict éditorial. Les
    compter surestimerait la sévérité du pipeline — piège relevé le 02/08."""
    entrees = [
        {"slug": "a", "statut": "erreur_verification", "date": "2026-08-28T10:00:00"},
        {"slug": "b", "statut": "non_verifie", "date": "2026-08-28T10:00:00"},
        {"slug": "c", "statut": "rejete_qualite", "date": "2026-08-28T10:00:00",
         "bloquants_types": ["1/chiffre_errone"]},
    ]
    code, sortie = _lancer(entrees)
    assert code == 0
    assert "verdicts éditoriaux : 1" in sortie, sortie
    assert "échecs TECHNIQUES   : 2" in sortie, sortie


def test_aucun_verdict_sort_en_erreur():
    """Refuser de conclure quand rien n'a été mesuré : code de sortie 1, pour
    qu'un appel automatisé ne prenne pas le silence pour un résultat."""
    entrees = [{"slug": "a", "statut": "erreur_verification",
                "date": "2026-08-28T10:00:00"}]
    code, sortie = _lancer(entrees)
    assert code == 1, sortie
    assert "rien à conclure" in sortie


def test_un_champ_absent_est_dit_absent_pas_nul():
    """LE défaut central de la famille : `nature_contenu` n'existe pas sur
    l'historique. Rendre un tableau de zéros le ferait lire comme « aucun sujet
    d'opinion », qui est une conclusion — et elle serait fausse."""
    entrees = [{"slug": "a", "statut": "rejete_qualite",
                "date": "2026-08-28T10:00:00",
                "bloquants_types": ["1/chiffre_errone"]}]
    code, sortie = _lancer(entrees)
    assert "ABSENCE DE DONNÉE, PAS RÉSULTAT NUL" in sortie, sortie


def test_petit_echantillon_porte_son_avertissement():
    """Sous n=30 tout écart est du bruit, et le script doit le dire lui-même."""
    entrees = [{"slug": f"s{i}", "statut": "rejete_qualite",
                "date": "2026-08-28T10:00:00",
                "nature_contenu": "tribune" if i % 2 else "actualite_factuelle",
                "bloquants_types": ["1/chiffre_errone"]} for i in range(6)]
    code, sortie = _lancer(entrees)
    assert "n = 6" in sortie and "bruit" in sortie, sortie


def test_le_regroupement_opinion_suit_la_liste_du_prompt():
    """Les valeurs d'opinion ne sont pas inventées : elles sont celles que le
    prompt de détection énumère. Si le prompt change, ce test doit être relu."""
    import verification_legacy as V
    for valeur in A.NATURES_OPINION:
        assert valeur in V.PROMPT_DETECTION, (
            f"« {valeur} » n'existe pas dans le prompt de détection : "
            "l'analyse classerait sur une valeur que le modèle ne rend jamais")


def test_opinion_et_fait_sont_comptes_separement():
    entrees = ([{"slug": f"o{i}", "statut": "rejete_qualite",
                 "date": "2026-08-28T10:00:00", "nature_contenu": "tribune"}
                for i in range(3)]
               + [{"slug": f"f{i}", "statut": "corrige_automatiquement",
                   "date": "2026-08-28T10:00:00",
                   "nature_contenu": "actualite_factuelle"} for i in range(2)])
    code, sortie = _lancer(entrees)
    assert "opinion" in sortie and "fait" in sortie, sortie
    assert "100.0 % recalés" in sortie, sortie


def test_journal_illisible_ne_produit_pas_de_faux_zero():
    with tempfile.TemporaryDirectory() as d:
        chemin = os.path.join(d, "casse.json")
        open(chemin, "w").write("pas du json")
        code = ("import sys; sys.path.insert(0, %r); "
                "import analyser_reproches as A; A.JOURNAL = %r; A.main()"
                % (DOSSIER, chemin))
        out = subprocess.run([sys.executable, "-c", code],
                             capture_output=True, text=True)
        assert out.returncode == 1
        assert "illisible" in out.stderr


if __name__ == "__main__":
    n = 0
    for nom, fn in sorted(globals().items()):
        if nom.startswith("test_"):
            fn(); n += 1; print(f"  ✓ {nom}")
    print(f"{n} tests OK")
