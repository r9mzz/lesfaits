#!/usr/bin/env python3
"""Interroge la liste des runs d'un workflow (JSON de l'API GitHub).

    dernier_run.py <fichier.json> <run_id_courant>          → timestamp Unix du
        run le plus récent hors run courant, ou 0.
    dernier_run.py <fichier.json> <run_id_courant> --sha    → head_sha du
        dernier run RÉUSSI hors run courant, ou chaîne vide.

Sert aux garde-fous anti-déclenchement-redondant de pipeline.yml (fenêtre de
temps : le quota Groq est la ressource rare) et de deploy.yml (comparaison de
SHA : ne jamais bloquer un déploiement qui a réellement du neuf à publier).
En cas de doute on renvoie une valeur neutre — on ne bloque jamais un run
faute d'information.
"""
import datetime as dt
import json
import sys


def charger(chemin: str) -> list:
    try:
        return json.load(open(chemin, encoding="utf-8")).get("workflow_runs", [])
    except Exception:
        return []


def main() -> None:
    chemin, run_courant = sys.argv[1], sys.argv[2]
    veut_sha = "--sha" in sys.argv
    runs = charger(chemin)

    if veut_sha:
        for r in runs:  # l'API renvoie les runs du plus récent au plus ancien
            if str(r.get("id")) == str(run_courant):
                continue
            if r.get("conclusion") == "success" and r.get("head_sha"):
                print(r["head_sha"])
                return
        print("")
        return

    dernier = 0
    for r in runs:
        if str(r.get("id")) == str(run_courant) or not r.get("run_started_at"):
            continue
        try:
            t = dt.datetime.fromisoformat(r["run_started_at"].replace("Z", "+00:00"))
        except Exception:
            continue
        dernier = max(dernier, int(t.timestamp()))
    print(dernier)


if __name__ == "__main__":
    main()
