"""
Analyse un run pipeline.yml et le verification_log.json du même jour.
Usage : python scripts/analyser_run.py [RUN_ID]
        Si RUN_ID absent, prend le dernier run pipeline.yml.

Sorties :
  - Tokens Groq consommés estimés (via nombre d'appels × taille moyenne)
  - Résumé par article : statut, bloquants par bloc
  - Comparaison bloc 2 (sourcing) vs autres blocs
  - Verdict : fix sourcing a-t-il réduit le bloc 2 ?
"""
import sys, json, re, subprocess
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
VERIF_LOG = ROOT / "data" / "verification_log.json"

BLOCS = {1: "FACTUEL", 2: "SOURCING", 3: "ORIGINALITÉ", 4: "RÉDACTION", 5: "LÉGAL"}
SEUIL_BLOC2_AVANT = 9   # médiane observée avant le fix (runs 04-05/07)


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
    """Extrait les métriques clés du log du run."""
    results = {
        "articles_tentes": [],
        "garde_retries": 0,
        "groq_rate_limits": 0,
        "quota_epuise": False,
        "articles_publies": 0,
        "hors_perimetre": 0,
        "erreurs_groq": 0,
    }

    for line in log.splitlines():
        line = re.sub(r"^.*?\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z ", "", line)

        m = re.search(r"→ Génération\s*:\s*(.+?)\s*\[(\d+) sources réelles\]", line)
        if m:
            results["articles_tentes"].append({
                "titre": m.group(1).strip(),
                "sources": int(m.group(2)),
                "gardes": 0,
            })

        if "[GARDE]" in line and results["articles_tentes"]:
            results["garde_retries"] += 1
            results["articles_tentes"][-1]["gardes"] += 1

        if "Rate limit sur clé" in line:
            results["groq_rate_limits"] += 1

        if "quota journalier" in line.lower() or "quota épuisé" in line.lower():
            results["quota_epuise"] = True
            results["erreurs_groq"] += 1

        if "[REJET PRÉCOCE]" in line:
            if results["articles_tentes"]:
                results["articles_tentes"][-1]["rejet_precoce"] = True

        m2 = re.search(r"Terminé — (\d+) article\(s\) publié", line)
        if m2:
            results["articles_publies"] = int(m2.group(1))

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


# ── 4. Affichage ──────────────────────────────────────────────────────────────

def afficher(run_id: str, pipeline: dict, verif: list):
    sep = "=" * 68
    print(f"\n{sep}")
    print(f"ANALYSE RUN {run_id} — {date.today()}")
    print(sep)

    # ── Groq ──
    print("\n── GROQ ──")
    nb_tentes = len(pipeline["articles_tentes"])
    print(f"  Articles tentés       : {nb_tentes}")
    print(f"  Retries garde-fous    : {pipeline['garde_retries']}")
    print(f"  Rate limits (appels)  : {pipeline['groq_rate_limits']}")
    print(f"  Quota épuisé          : {'OUI ⚠' if pipeline['quota_epuise'] else 'non'}")
    print(f"  Articles publiés      : {pipeline['articles_publies']}")

    # Estimation tokens : input ~4k tokens/appel (avec fix), output ~4.5k = ~8.5k/appel
    # Nombre d'appels = tentatives + gardes
    nb_appels = nb_tentes + pipeline["garde_retries"]
    tokens_estimes = nb_appels * 8500
    print(f"  Appels Groq estimés   : {nb_appels}")
    print(f"  Tokens Groq estimés   : ~{tokens_estimes:,}  (hypothèse 8.5k/appel avec nouveau prompt)")

    for i, art in enumerate(pipeline["articles_tentes"], 1):
        rejet = " [REJET PRÉCOCE]" if art.get("rejet_precoce") else ""
        print(f"    {i}. {art['titre'][:50]:<50} gardes={art['gardes']}{rejet}")

    # ── Vérification Anthropic ──
    print(f"\n── VÉRIFICATION ANTHROPIC ({len(verif)} entrées aujourd'hui) ──")

    if not verif:
        print("  Aucune entrée dans verification_log.json pour aujourd'hui.")
        print("  (Soit 0 article n'a atteint la vérification, soit le log n'est pas à jour.)")
    else:
        statuts = Counter(e.get("statut") for e in verif)
        print(f"  conforme_du_premier_coup : {statuts.get('conforme_du_premier_coup', 0)}")
        print(f"  corrige_automatiquement  : {statuts.get('corrige_automatiquement', 0)}")
        print(f"  rejete_qualite           : {statuts.get('rejete_qualite', 0)}")
        print(f"  rejete_sensible          : {statuts.get('rejete_sensible', 0)}")

        # Bloc 2 (sourcing) — métrique principale du fix
        bloc2_par_article = []
        bloquants_par_article = []
        print("\n  Détail par article :")
        for e in verif:
            slug = e.get("slug", "?")[:40]
            statut = e.get("statut", "?")
            pb_init = e.get("problemes_initiaux", "?")
            bloquants = e.get("bloquants_restants", "?")
            # Les blocs ne sont pas stockés par type dans le log actuel —
            # on ne peut sortir que les totaux
            print(f"    {slug:<40} | init={pb_init:<3} bloquants={bloquants:<3} | {statut}")
            if isinstance(bloquants, int):
                bloquants_par_article.append(bloquants)

        if bloquants_par_article:
            moy = sum(bloquants_par_article) / len(bloquants_par_article)
            print(f"\n  Moyenne bloquants restants : {moy:.1f}")

        # Note : les types de blocs (bloc 2 vs autres) ne sont pas journalisés dans
        # verification_log.json — pour l'analyse fine par bloc il faut relancer
        # test_articles_03juillet.py ou ajouter le détail bloc dans _log().
        print()
        print("  ⚠ Le détail par bloc (bloc 2 sourcing vs autres) n'est pas dans le log.")
        print("  Pour le mesurer : relancer test_articles_03juillet.py sur les articles du run.")

    # ── Verdict ──
    print(f"\n── VERDICT FIX SOURCING ──")
    if not verif:
        print("  Pas de données de vérification disponibles — le run n'a peut-être")
        print("  pas atteint la phase de vérification (quota épuisé avant ?)")
    else:
        publies = statuts.get("conforme_du_premier_coup", 0) + statuts.get("corrige_automatiquement", 0)
        if publies > 0:
            print(f"  ✓ {publies} article(s) publié(s) — fix sourcing probablement efficace.")
        elif bloquants_par_article and sum(bloquants_par_article) / len(bloquants_par_article) < SEUIL_BLOC2_AVANT:
            moy = sum(bloquants_par_article) / len(bloquants_par_article)
            print(f"  ~ Taux de publication encore 0% mais moyenne bloquants {moy:.1f} < seuil {SEUIL_BLOC2_AVANT}")
            print(f"    → Amélioration partielle : le fix a réduit les bloquants, d'autres blocs")
            print(f"      (rédaction, redondance) restent à traiter séparément.")
        else:
            print(f"  ✗ Pas d'amélioration mesurable — vérifier les logs détaillés.")

    print(f"\n{sep}\n")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_id = get_run_id(sys.argv[1] if len(sys.argv) > 1 else None)
    log = fetch_log(run_id)
    pipeline = parse_pipeline_log(log)
    verif = load_verif_today()
    afficher(run_id, pipeline, verif)
