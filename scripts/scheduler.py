"""
Factuel — Scheduler éditorial
===============================
Publie automatiquement 10 articles le matin + 5 le soir.

Usage :
    python scheduler.py              # tourne en continu, respecte les créneaux
    python scheduler.py --now matin  # force le créneau matin maintenant
    python scheduler.py --now soir   # force le créneau soir maintenant
    python scheduler.py --dry-run    # simule sans générer
    python scheduler.py --statut     # affiche le statut et quitte

Créneaux par défaut :
    Matin : 07h00 — 10 articles
    Soir  : 18h30 —  5 articles
"""

import sys, os, time, json, argparse, subprocess
from datetime import datetime, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT     = Path(__file__).parent.parent
DATA     = ROOT / "data"
LOG_FILE = DATA / "scheduler.log"
DATA.mkdir(exist_ok=True)

# ── Créneaux ──────────────────────────────────────────────────────────────────
CRENEAUX = {
    "matin": {"heure": 7,  "minute": 0,  "nb_articles": 10},
    "soir":  {"heure": 18, "minute": 30, "nb_articles": 5},
}

# ── Filtres éditoriaux par créneau ────────────────────────────────────────────
# Matin : données structurelles, rapports institutionnels, science
# Soir  : actualités de la journée, réactions, mises à jour

WHITELIST_MATIN = [
    "rapport", "étude", "données", "statistique", "taux", "bilan",
    "publication", "recherche", "enquête", "résultats",
    "insee", "eurostat", "cnrs", "inserm", "dares", "anses", "citepa",
    "budget", "finances", "déficit", "emploi", "chômage",
    "environnement", "énergie", "climat", "science", "santé",
]

WHITELIST_SOIR = [
    "france", "décision", "loi", "décret", "réforme", "annonce",
    "rapport", "institution", "données", "économie", "société",
    "technologie", "numérique", "intelligence artificielle",
    "europe", "eurozone", "parlement",
]

BLACKLIST_COMMUN = [
    "guerre", "attentat", "terrorisme", "meurtre", "accident mortel",
    "fait divers", "célébrité", "people", "scandale privé",
    "sondage popularité", "parti politique", "élection présidentielle",
]


def log(msg: str):
    now  = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    line = f"[{now}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def derniere_publication() -> dict:
    path = DATA / "scheduler_state.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"matin": None, "soir": None}


def sauver_publication(creneau: str):
    path  = DATA / "scheduler_state.json"
    state = derniere_publication()
    state[creneau] = datetime.now().isoformat()
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def deja_publie_aujourd_hui(creneau: str) -> bool:
    state = derniere_publication()
    last  = state.get(creneau)
    if not last:
        return False
    return datetime.fromisoformat(last).date() == datetime.now().date()


def run_pipeline(dry_run: bool = False):
    """Lance le pipeline RSS principal."""
    cmd = [sys.executable, str(ROOT / "scripts" / "pipeline.py")]
    if dry_run:
        cmd.append("--dry-run")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run(cmd, env=env)
    return result.returncode == 0


def executer_creneau(nom: str, dry_run: bool = False):
    c = CRENEAUX[nom]
    log(f"{'='*50}")
    log(f"Créneau {nom.upper()} — objectif {c['nb_articles']} articles")
    log(f"{'='*50}")

    if not dry_run and deja_publie_aujourd_hui(nom):
        log(f"[SKIP] Créneau {nom} déjà exécuté aujourd'hui — prochain : demain {c['heure']}h{c['minute']:02d}")
        return

    ok = run_pipeline(dry_run=dry_run)

    if not dry_run:
        sauver_publication(nom)
        log(f"✓ Créneau {nom} terminé et enregistré")
    else:
        log(f"✓ Créneau {nom} simulé (dry-run)")


def prochain_creneau() -> tuple[str, datetime, float]:
    now       = datetime.now()
    candidats = []
    for nom, c in CRENEAUX.items():
        target = now.replace(hour=c["heure"], minute=c["minute"], second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        candidats.append((nom, target, (target - now).total_seconds()))
    candidats.sort(key=lambda x: x[2])
    return candidats[0]


def afficher_statut():
    nom, target, diff = prochain_creneau()
    h = int(diff // 3600)
    m = int((diff % 3600) // 60)
    print(f"\nFactuel Scheduler — statut")
    print(f"  Prochain créneau : {nom.upper()} à {target.strftime('%H:%M')} (dans {h}h{m:02d}m)")
    state = derniere_publication()
    for n, c in CRENEAUX.items():
        last = state.get(n)
        dt   = datetime.fromisoformat(last).strftime("%d/%m %H:%M") if last else "jamais"
        deja = " ✓ (fait aujourd'hui)" if last and datetime.fromisoformat(last).date() == datetime.now().date() else ""
        print(f"  {n.capitalize()} {c['heure']}h{c['minute']:02d} ({c['nb_articles']} articles) — dernière publication : {dt}{deja}")
    print()


def boucle(dry_run: bool = False):
    log("Factuel Scheduler démarré")
    log(f"Matin {CRENEAUX['matin']['heure']}h{CRENEAUX['matin']['minute']:02d} "
        f"({CRENEAUX['matin']['nb_articles']} articles) | "
        f"Soir {CRENEAUX['soir']['heure']}h{CRENEAUX['soir']['minute']:02d} "
        f"({CRENEAUX['soir']['nb_articles']} articles)")
    afficher_statut()

    while True:
        now = datetime.now()
        for nom, c in CRENEAUX.items():
            if now.hour == c["heure"] and now.minute == c["minute"]:
                executer_creneau(nom, dry_run=dry_run)
        # Vérifie toutes les 30 secondes pour ne pas rater une minute pile
        time.sleep(30)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Factuel — Scheduler éditorial automatique")
    parser.add_argument("--now",     choices=["matin", "soir"], help="Forcer un créneau immédiatement")
    parser.add_argument("--dry-run", action="store_true",       help="Simuler sans générer")
    parser.add_argument("--statut",  action="store_true",       help="Afficher le statut et quitter")
    args = parser.parse_args()

    if args.statut:
        afficher_statut()
    elif args.now:
        log(f"Forçage créneau {args.now}...")
        executer_creneau(args.now, dry_run=args.dry_run)
    else:
        try:
            boucle(dry_run=args.dry_run)
        except KeyboardInterrupt:
            log("Scheduler arrêté manuellement.")
