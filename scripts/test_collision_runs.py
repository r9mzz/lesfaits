"""Deux runs simultanés se disputent les mêmes clés et le même push.

Le 27/08, quatre déclenchements pour deux runs utiles : un run forcé de 4 h 23
a fait annuler le suivant et exécuter le troisième à vide. La fenêtre de
360 min ne pouvait rien y faire — elle mesure le TEMPS ÉCOULÉ depuis le
démarrage précédent, pas l'état courant.

⚠ La distinction verrouillée ici est celle qui compte : `--en-cours` est un
fait d'ÉTAT (un run tourne), la fenêtre est une heuristique d'économie de
quota. C'est pourquoi la concurrence s'applique aussi aux crons et n'est pas
contournable par « forcer » — deux runs simultanés ne sont pas un forçage,
c'est une collision.
"""
import json
import os
import subprocess
import sys
import tempfile

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dernier_run.py")


def _appel(runs, run_courant="99", *args):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as f:
        json.dump({"workflow_runs": runs}, f)
        chemin = f.name
    try:
        out = subprocess.run([sys.executable, SCRIPT, chemin, run_courant, *args],
                             capture_output=True, text=True, check=True)
        return out.stdout.strip()
    finally:
        os.unlink(chemin)


def test_un_run_en_cours_est_signale():
    runs = [{"id": 42, "status": "in_progress", "run_started_at": "2026-08-27T13:00:00Z"}]
    assert _appel(runs, "99", "--en-cours") == "42"


def test_un_run_en_file_compte_aussi():
    """Un run `queued` va démarrer : le laisser passer recrée la collision."""
    for etat in ("queued", "waiting", "requested"):
        runs = [{"id": 7, "status": etat}]
        assert _appel(runs, "99", "--en-cours") == "7", etat


def test_le_run_courant_ne_se_bloque_pas_lui_meme():
    """LE piège de ce garde-fou : le run qui pose la question est lui-même
    `in_progress` dans la liste. S'il se comptait, AUCUN run ne démarrerait
    jamais — le pipeline serait mort en silence."""
    runs = [{"id": 99, "status": "in_progress"}]
    assert _appel(runs, "99", "--en-cours") == ""


def test_aucun_run_actif_laisse_passer():
    runs = [{"id": 1, "status": "completed", "conclusion": "success"},
            {"id": 2, "status": "completed", "conclusion": "failure"}]
    assert _appel(runs, "99", "--en-cours") == ""


def test_json_illisible_ne_bloque_jamais():
    """Règle du fichier : en cas de doute, valeur neutre. Une panne de l'API
    GitHub ne doit pas empêcher un run de tourner."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as f:
        f.write("pas du json")
        chemin = f.name
    try:
        out = subprocess.run([sys.executable, SCRIPT, chemin, "99", "--en-cours"],
                             capture_output=True, text=True, check=True)
        assert out.stdout.strip() == ""
    finally:
        os.unlink(chemin)


def test_les_autres_modes_sont_intacts():
    """`--en-cours` ne doit pas parasiter les deux modes existants, dont
    dépendent pipeline.yml (fenêtre) et deploy.yml (SHA)."""
    runs = [{"id": 1, "status": "completed", "conclusion": "success",
             "head_sha": "abc123", "run_started_at": "2026-08-27T13:00:00Z"}]
    assert _appel(runs, "99", "--sha") == "abc123"
    assert _appel(runs, "99") != "0"


if __name__ == "__main__":
    n = 0
    for nom, fn in sorted(globals().items()):
        if nom.startswith("test_"):
            fn(); n += 1; print(f"  ✓ {nom}")
    print(f"{n} tests OK")
