"""
Analyse un run pipeline.yml et le verification_log.json du même jour.
Usage : python scripts/analyser_run.py [RUN_ID]
        Si RUN_ID absent, prend le dernier run pipeline.yml.

Sorties (séparées ACTU / DOSSIER) :
  - Tokens Groq consommés estimés par type
  - Statuts Anthropic séparés : ACTU vs DOSSIER
  - Moyenne bloquants par type (pour isoler quel changement pose problème)
  - Verdict fix sourcing (ACTU uniquement — métrique de référence)
"""
import sys, json, re, subprocess
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
VERIF_LOG = ROOT / "data" / "verification_log.json"

SEUIL_BLOC2_AVANT = 9   # médiane observée avant le fix sourcing (runs 04-05/07)


# ── 1. Récupérer les logs GitHub Actions ─────────────────────────────────────

def get_run_id(run_id_arg: str | None) -> str:
    if run_id_arg:
        return run_id_arg
    out = subprocess.check_output(
        ["gh", "run", "list", "--workflow=pipeline.yml", "--limit=1",
         "--json", "databaseId"],
        cwd=str(ROOT)
    )
    runs = json.loads(out)
    if not runs:
        sys.exit("Aucun run pipeline.yml trouvé.")
    return str(runs[0]["databaseId"])


def fetch_log(run_id: str) -> str:
    print(f"  Récupération des logs pour run {run_id}…")
    return subprocess.check_output(
        ["gh", "run", "view", run_id, "--log"],
        cwd=str(ROOT)
    ).decode("utf-8", errors="replace")


# ── 2. Parser les logs pour les événements pipeline ───────────────────────────

def parse_pipeline_log(log: str) -> dict:
    """Extrait les métriques clés du log du run.

    Format des lignes depuis la mise à jour Format Dossier :
      → Génération [ACTU] : titre [N sources réelles]
      → Génération [DOSSIER/portrait] : titre [N sources réelles]
      → Génération [DOSSIER/science] : titre [N sources réelles]
    Ancien format (sans type) encore possible pour les runs d'avant :
      → Génération : titre [N sources réelles]
    """
    results = {
        "articles_tentes": [],
        "garde_retries": 0,
        "groq_rate_limits": 0,
        "quota_epuise": False,
        "articles_publies": 0,
        "hors_perimetre": 0,
    }

    for line in log.splitlines():
        line = re.sub(r"^.*?\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z ", "", line)

        # Nouveau format avec type
        m = re.search(r"→ Génération \[([^\]]+)\]\s*:\s*(.+?)\s*\[(\d+) sources réelles\]", line)
        if m:
            results["articles_tentes"].append({
                "type":   m.group(1).strip(),   # "ACTU" | "DOSSIER/portrait" | "DOSSIER/science"
                "titre":  m.group(2).strip(),
                "sources": int(m.group(3)),
                "gardes": 0,
            })
            continue

        # Ancien format sans type (runs antérieurs au Format Dossier)
        m2 = re.search(r"→ Génération\s*:\s*(.+?)\s*\[(\d+) sources réelles\]", line)
        if m2:
            results["articles_tentes"].append({
                "type":   "actu",   # type par défaut pour les anciens runs
                "titre":  m2.group(1).strip(),
                "sources": int(m2.group(2)),
                "gardes": 0,
            })
            continue

        if "[GARDE]" in line and results["articles_tentes"]:
            results["garde_retries"] += 1
            results["articles_tentes"][-1]["gardes"] += 1

        if "Rate limit sur clé" in line:
            results["groq_rate_limits"] += 1

        if "quota journalier" in line.lower() or "quota épuisé" in line.lower():
            results["quota_epuise"] = True

        if "[REJET PRÉCOCE]" in line and results["articles_tentes"]:
            results["articles_tentes"][-1]["rejet_precoce"] = True

        if "[REJET DOSSIER]" in line and results["articles_tentes"]:
            results["articles_tentes"][-1]["rejet_dossier"] = True

        m3 = re.search(r"Terminé — (\d+) article\(s\) publié", line)
        if m3:
            results["articles_publies"] = int(m3.group(1))

        if "HORS_PERIMETRE" in line:
            results["hors_perimetre"] += 1

    return results


# ── 3. Lire le verification_log.json pour aujourd'hui ─────────────────────────

def load_verif_today() -> list:
    if not VERIF_LOG.exists():
        return []
    entries = json.loads(VERIF_LOG.read_text(encoding="utf-8"))
    today = date.today().isoformat()
    return [e for e in entries if e.get("date", "").startswith(today)]


def _split_by_type(verif: list) -> tuple[list, list]:
    """Sépare les entrées verif en (actu, dossier).
    Utilise le champ article_type si présent (runs après Format Dossier).
    Fallback : tout en actu si le champ est absent.
    """
    actu, dossier = [], []
    for e in verif:
        t = e.get("article_type", "actu")
        if t.startswith("dossier"):
            dossier.append(e)
        else:
            actu.append(e)
    return actu, dossier


# ── 4. Affichage ──────────────────────────────────────────────────────────────

def _bloc_verif(label: str, entries: list):
    """Affiche les stats de vérification pour un groupe d'articles."""
    if not entries:
        print(f"  Aucune entrée.")
        return

    statuts = Counter(e.get("statut") for e in entries)
    publies = statuts.get("conforme_du_premier_coup", 0) + statuts.get("corrige_automatiquement", 0)
    total = len(entries)
    taux = f"{publies}/{total}" if total else "—"

    print(f"  Taux publication          : {taux}")
    print(f"    conforme_du_premier_coup : {statuts.get('conforme_du_premier_coup', 0)}")
    print(f"    corrige_automatiquement  : {statuts.get('corrige_automatiquement', 0)}")
    print(f"    rejete_qualite           : {statuts.get('rejete_qualite', 0)}")
    print(f"    rejete_sensible          : {statuts.get('rejete_sensible', 0)}")

    bloquants = [e.get("bloquants_restants") for e in entries
                 if isinstance(e.get("bloquants_restants"), int)]
    if bloquants:
        moy = sum(bloquants) / len(bloquants)
        print(f"  Moy. bloquants restants   : {moy:.1f}  (seuil avant fix : {SEUIL_BLOC2_AVANT})")

    print(f"\n  Détail par article :")
    for e in entries:
        slug = e.get("slug", "?")[:38]
        s = e.get("statut", "?")
        init = e.get("problemes_initiaux", "?")
        bloc = e.get("bloquants_restants", "?")
        print(f"    {slug:<38} | init={str(init):<3} bloquants={str(bloc):<3} | {s}")


def afficher(run_id: str, pipeline: dict, verif: list):
    sep = "=" * 72
    print(f"\n{sep}")
    print(f"ANALYSE RUN {run_id} — {date.today()}")
    print(sep)

    # ── Groq : répartition par type ──
    print("\n── GROQ ──")
    tentes = pipeline["articles_tentes"]
    actu_log   = [a for a in tentes if a["type"] in ("ACTU", "actu")]
    dossier_log = [a for a in tentes if a["type"] not in ("ACTU", "actu")]

    nb_tentes = len(tentes)
    print(f"  Total articles tentés  : {nb_tentes}  (ACTU={len(actu_log)}, DOSSIER={len(dossier_log)})")
    print(f"  Retries garde-fous     : {pipeline['garde_retries']}")
    print(f"  Rate limits (appels)   : {pipeline['groq_rate_limits']}")
    print(f"  Quota épuisé           : {'OUI ⚠' if pipeline['quota_epuise'] else 'non'}")
    print(f"  Articles publiés       : {pipeline['articles_publies']}")

    nb_appels = nb_tentes + pipeline["garde_retries"]
    tokens_estimes = nb_appels * 8500
    print(f"  Appels Groq estimés    : {nb_appels}  (~{tokens_estimes:,} tokens)")

    print(f"\n  Détail par article :")
    for i, art in enumerate(tentes, 1):
        flags = ""
        if art.get("rejet_precoce"):  flags += " [REJET PRÉCOCE]"
        if art.get("rejet_dossier"):  flags += " [REJET DOSSIER]"
        print(f"    {i}. [{art['type']:<18}] {art['titre'][:42]:<42} gardes={art['gardes']}{flags}")

    # ── Vérification Anthropic — séparée ACTU / DOSSIER ──
    has_type_field = any("article_type" in e for e in verif)
    verif_actu, verif_dossier = _split_by_type(verif)

    if not verif:
        print(f"\n── VÉRIFICATION ANTHROPIC (0 entrées aujourd'hui) ──")
        print("  Aucune entrée dans verification_log.json pour aujourd'hui.")
        print("  (0 article n'a atteint la vérification, ou log non encore à jour.)")
    else:
        if not has_type_field:
            print(f"\n── VÉRIFICATION ANTHROPIC ({len(verif)} entrées — champ article_type absent) ──")
            print("  Runs antérieurs au Format Dossier — séparation ACTU/DOSSIER indisponible.")
            print("  Toutes les entrées affichées comme ACTU par défaut.")
        else:
            print(f"\n── VÉRIFICATION ANTHROPIC — ACTU ({len(verif_actu)} entrées) ──")

        _bloc_verif("ACTU", verif_actu)

        if has_type_field and verif_dossier:
            print(f"\n── VÉRIFICATION ANTHROPIC — DOSSIER ({len(verif_dossier)} entrées) ──")
            print("  (Premier run avec Format Dossier — aucune donnée de référence)")
            _bloc_verif("DOSSIER", verif_dossier)

        if has_type_field and not verif_dossier:
            print(f"\n── DOSSIER : 0 article vérifié aujourd'hui ──")
            print("  (Aucun candidat DOSSIER n'a passé la vérification, ou aucun trouvé)")

    # ── Verdict fix sourcing (ACTU uniquement) ──
    print(f"\n── VERDICT FIX SOURCING (ACTU) ──")
    if not verif_actu:
        print("  Pas de données ACTU — le run n'a peut-être pas atteint la vérification.")
    else:
        statuts_actu = Counter(e.get("statut") for e in verif_actu)
        publies = statuts_actu.get("conforme_du_premier_coup", 0) + statuts_actu.get("corrige_automatiquement", 0)
        bloquants = [e.get("bloquants_restants") for e in verif_actu
                     if isinstance(e.get("bloquants_restants"), int)]
        if publies > 0:
            print(f"  ✓ {publies} article(s) ACTU publié(s) — fix sourcing efficace.")
        elif bloquants and sum(bloquants) / len(bloquants) < SEUIL_BLOC2_AVANT:
            moy = sum(bloquants) / len(bloquants)
            print(f"  ~ 0 publié mais bloquants moy. {moy:.1f} < seuil {SEUIL_BLOC2_AVANT}")
            print(f"    → Amélioration partielle : fix sourcing a réduit les bloquants,")
            print(f"      d'autres blocs (rédaction, redondance) restent à traiter.")
        else:
            print(f"  ✗ Pas d'amélioration mesurable — vérifier les logs détaillés.")

    if verif_dossier:
        print(f"\n── VERDICT DOSSIER ──")
        statuts_d = Counter(e.get("statut") for e in verif_dossier)
        pub_d = statuts_d.get("conforme_du_premier_coup", 0) + statuts_d.get("corrige_automatiquement", 0)
        print(f"  {pub_d}/{len(verif_dossier)} articles DOSSIER publiés (pas de référence historique).")

    print(f"\n{sep}\n")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_id = get_run_id(sys.argv[1] if len(sys.argv) > 1 else None)
    log = fetch_log(run_id)
    pipeline = parse_pipeline_log(log)
    verif = load_verif_today()
    afficher(run_id, pipeline, verif)
