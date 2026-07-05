"""
Analyse un run pipeline.yml et le verification_log.json du même jour.
Usage : python scripts/analyser_run.py [RUN_ID]
        Si RUN_ID absent, prend le dernier run pipeline.yml.

Sorties (dans l'ordre) :
  1. Alertes quota / accès
  2. Verdict sourcing (comparaison au baseline)
  3. Conformité par cause (quota / qualité / sensible / hors-périmètre)
  4. ACTU vs DOSSIER (séparés)
  5. Alertes appels LLM (>8 appels par article)
  6. Détail par article
"""
import sys, json, re, subprocess
from collections import Counter
from datetime import date
from pathlib import Path

# Force UTF-8 sur Windows (évite UnicodeEncodeError avec les caractères spéciaux)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent.parent
VERIF_LOG = ROOT / "data" / "verification_log.json"

# ── Baselines (runs 04-05/07 avant tous les fixes) ────────────────────────────
# Observé sur 14 articles : 0 publiés, bloquants_restants moy=4.6, init moy=16
BASELINE_CONFORMITE  = 0.0        # 0/14
BASELINE_BLOQUANTS   = 4.6        # bloquants_restants moyens après 3 tentatives
BASELINE_INIT        = 16.0       # problemes_initiaux moyens
SEUIL_APPELS_LLM     = 8          # alerte si total estimé > cette valeur


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


def fetch_log(run_id: str) -> tuple[str, str]:
    """Retourne (log_text, run_date_iso) ex. ('...', '2026-07-04')."""
    print(f"  Récupération des logs pour run {run_id}…")
    log = subprocess.check_output(
        ["gh", "run", "view", run_id, "--log"],
        cwd=str(ROOT)
    ).decode("utf-8", errors="replace")

    # Extraire la date depuis les timestamps du log (format 2026-07-04T...)
    m = re.search(r"(\d{4}-\d{2}-\d{2})T", log)
    run_date = m.group(1) if m else date.today().isoformat()
    return log, run_date


# ── 2. Parser les logs pour les événements pipeline ───────────────────────────

def parse_pipeline_log(log: str) -> dict:
    """Extrait les métriques clés du log du run.

    Format des lignes depuis la mise à jour Format Dossier :
      → Génération [ACTU] : titre [N sources réelles]
      → Génération [DOSSIER/portrait] : titre [N sources réelles]
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
                "type":   m.group(1).strip(),
                "titre":  m.group(2).strip(),
                "sources": int(m.group(3)),
                "gardes": 0,
            })
            continue

        # Ancien format sans type
        m2 = re.search(r"→ Génération\s*:\s*(.+?)\s*\[(\d+) sources réelles\]", line)
        if m2:
            results["articles_tentes"].append({
                "type":   "actu",
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


# ── 3. Lire le verification_log.json ─────────────────────────────────────────

def load_verif_for_date(run_date: str) -> list:
    if not VERIF_LOG.exists():
        return []
    entries = json.loads(VERIF_LOG.read_text(encoding="utf-8"))
    return [e for e in entries if e.get("date", "").startswith(run_date)]


def _split_by_type(verif: list) -> tuple[list, list]:
    actu, dossier = [], []
    for e in verif:
        t = e.get("article_type", "actu")
        if t.startswith("dossier"):
            dossier.append(e)
        else:
            actu.append(e)
    return actu, dossier


# ── 4. Calcul appels LLM estimés ─────────────────────────────────────────────

def _anthropic_calls(statut: str, tentatives) -> int:
    """Estimation des appels Anthropic selon le statut."""
    if statut == "conforme_du_premier_coup":
        return 1   # 1 détection uniquement
    if statut in ("rejete_sensible", "sujet_sensible"):
        return 1   # détection seulement
    # rejete_qualite, a_corriger_manuellement, corrige_automatiquement
    try:
        t = int(tentatives)
    except (TypeError, ValueError):
        t = 2   # défaut si absent
    return 1 + t * 2   # 1 detect initial + (detect+correct) par tentative


def _total_llm(groq_appels: int, verif_entry: dict | None) -> int:
    if verif_entry is None:
        return groq_appels   # pas encore vérifié
    statut = verif_entry.get("statut", "")
    tentatives = verif_entry.get("tentatives")
    return groq_appels + _anthropic_calls(statut, tentatives)


# ── 5. Sections d'affichage ───────────────────────────────────────────────────

def _section(titre: str):
    print(f"\n── {titre} ──")


def _afficher_alertes_quota(pipeline: dict, verif: list):
    _section("1. ALERTES QUOTA / ACCÈS")
    tentes = pipeline["articles_tentes"]
    nb_tentes = len(tentes)
    nb_verif  = len(verif)

    if pipeline["quota_epuise"]:
        non_tentes = max(0, 10 - nb_tentes)   # suppose 10 sujets planifiés
        print(f"  ⚠  QUOTA ÉPUISÉ — {nb_tentes} article(s) généré(s), "
              f"~{non_tentes} sujet(s) jamais tenté(s).")
    else:
        print(f"  Quota : OK  ({nb_tentes} articles tentés)")

    if pipeline["groq_rate_limits"] > 0:
        print(f"  ⚠  Rate limits Groq : {pipeline['groq_rate_limits']} fois")

    if nb_verif < nb_tentes:
        ecart = nb_tentes - nb_verif
        print(f"  ⚠  {ecart} article(s) tenté(s) n'ont pas atteint la vérification "
              f"(généré={nb_tentes}, vérifié={nb_verif}).")

    if pipeline["hors_perimetre"] > 0:
        print(f"  ⚠  HORS_PERIMETRE : {pipeline['hors_perimetre']} sujet(s) ignoré(s) à la sélection")


def _afficher_verdict_sourcing(verif_actu: list):
    _section("2. VERDICT FIX SOURCING (ACTU)")

    if not verif_actu:
        print("  Pas de données ACTU — run non arrivé à la vérification.")
        return

    # Conformité
    statuts = Counter(e.get("statut") for e in verif_actu)
    publies = (statuts.get("conforme_du_premier_coup", 0)
               + statuts.get("corrige_automatiquement", 0))
    total   = len(verif_actu)
    taux    = publies / total if total else 0

    # Bloquants restants (proxy bloc 2 — seule métrique disponible pour tous statuts)
    bloquants = [e["bloquants_restants"] for e in verif_actu
                 if isinstance(e.get("bloquants_restants"), int)]
    moy_bloquants = sum(bloquants) / len(bloquants) if bloquants else None

    # Problèmes initiaux (indicateur de la détection initiale)
    init_vals = [e["problemes_initiaux"] for e in verif_actu
                 if isinstance(e.get("problemes_initiaux"), int)]
    moy_init = sum(init_vals) / len(init_vals) if init_vals else None

    print(f"  Conformité ACTU         : {publies}/{total}  "
          f"(baseline : {int(BASELINE_CONFORMITE)}/14)")

    if moy_bloquants is not None:
        decrease = (BASELINE_BLOQUANTS - moy_bloquants) / BASELINE_BLOQUANTS * 100
        delta_blq = f"-{decrease:.0f}%" if decrease >= 0 else f"+{-decrease:.0f}% (PIRE)"
        print(f"  Bloquants restants moy. : {moy_bloquants:.1f}  "
              f"(baseline {BASELINE_BLOQUANTS:.1f}  →  {delta_blq})")
        if moy_init is not None:
            dec_init = (BASELINE_INIT - moy_init) / BASELINE_INIT * 100
            delta_init = f"-{dec_init:.0f}%" if dec_init >= 0 else f"+{-dec_init:.0f}% (PIRE)"
            print(f"  Problèmes initiaux moy. : {moy_init:.1f}  "
                  f"(baseline {BASELINE_INIT:.1f}  →  {delta_init})")

        if publies > 0:
            verdict = "✓  FIX VALIDÉ"
            detail  = f"{publies} article(s) publié(s)"
        elif decrease >= 60:
            verdict = "✓  FIX VALIDÉ"
            detail  = f"{decrease:.0f}% de réduction des bloquants"
        elif decrease >= 30:
            verdict = "~  AMÉLIORATION PARTIELLE"
            detail  = f"{decrease:.0f}% de réduction des bloquants — d'autres blocs restent à traiter"
        elif decrease >= 0:
            verdict = "✗  NON CONCLUANT"
            detail  = f"seulement {decrease:.0f}% de réduction — vérifier si le fix a bien été déployé"
        else:
            verdict = "✗  RÉGRESSION"
            detail  = f"bloquants en hausse de {-decrease:.0f}% par rapport au baseline"
    elif publies > 0:
        verdict = "✓  FIX VALIDÉ"
        detail  = f"{publies} article(s) publié(s)"
    else:
        verdict = "✗  NON CONCLUANT"
        detail  = "aucune donnée de bloquants disponible"

    print(f"\n  VERDICT : {verdict}")
    print(f"           ({detail})")


def _afficher_causes(pipeline: dict, verif: list):
    _section("3. CONFORMITÉ PAR CAUSE")

    nb_tentes = len(pipeline["articles_tentes"])
    nb_verif  = len(verif)
    statuts   = Counter(e.get("statut") for e in verif)

    publies         = (statuts.get("conforme_du_premier_coup", 0)
                       + statuts.get("corrige_automatiquement", 0))
    rejet_qualite   = (statuts.get("rejete_qualite", 0)
                       + statuts.get("a_corriger_manuellement", 0))
    rejet_sensible  = (statuts.get("rejete_sensible", 0)
                       + statuts.get("sujet_sensible", 0))
    non_atteints    = max(0, nb_tentes - nb_verif)   # générés mais non vérifiés
    quota_non_tentes = max(0, 10 - nb_tentes) if pipeline["quota_epuise"] else 0
    hp = pipeline["hors_perimetre"]

    total_echecs = rejet_qualite + rejet_sensible + non_atteints + quota_non_tentes + hp

    print(f"  Publiés                 : {publies}")
    print(f"  Rejet qualité           : {rejet_qualite}"
          + ("  ← cause principale" if rejet_qualite and rejet_qualite >= max(rejet_sensible, non_atteints) else ""))
    print(f"  Rejet sensible          : {rejet_sensible}")
    if non_atteints:
        print(f"  Générés non vérifiés    : {non_atteints}  (crash ou quota Anthropic ?)")
    if quota_non_tentes:
        print(f"  Jamais tentés (quota)   : {quota_non_tentes}  ← quota épuisé avant la fin")
    if hp:
        print(f"  Hors périmètre (sélect.): {hp}")

    if total_echecs > 0 and publies == 0:
        # Identifier la cause principale
        causes = {
            "quota épuisé": quota_non_tentes,
            "rejet qualité": rejet_qualite,
            "rejet sensible": rejet_sensible,
            "non atteints": non_atteints,
        }
        principale = max(causes, key=causes.get)
        print(f"\n  Cause principale du 0 publication : {principale.upper()}")


def _bloc_verif(entries: list):
    if not entries:
        print("  Aucune entrée.")
        return

    statuts = Counter(e.get("statut") for e in entries)
    publies = (statuts.get("conforme_du_premier_coup", 0)
               + statuts.get("corrige_automatiquement", 0))
    total   = len(entries)

    print(f"  Taux publication          : {publies}/{total}")
    for s in ("conforme_du_premier_coup", "corrige_automatiquement",
              "rejete_qualite", "a_corriger_manuellement", "rejete_sensible", "sujet_sensible"):
        n = statuts.get(s, 0)
        if n:
            print(f"    {s:<32}: {n}")

    bloquants = [e["bloquants_restants"] for e in entries
                 if isinstance(e.get("bloquants_restants"), int)]
    if bloquants:
        moy = sum(bloquants) / len(bloquants)
        print(f"  Moy. bloquants restants   : {moy:.1f}")

    print(f"\n  Détail par article :")
    for e in entries:
        slug  = e.get("slug", "?")[:38]
        s     = e.get("statut", "?")
        init  = e.get("problemes_initiaux", "?")
        bloc  = e.get("bloquants_restants", "?")
        print(f"    {slug:<38} | init={str(init):<3} bloquants={str(bloc):<3} | {s}")


def _afficher_actu_dossier(verif: list):
    has_type_field = any("article_type" in e for e in verif)
    verif_actu, verif_dossier = _split_by_type(verif)

    if not verif:
        _section("4. ACTU vs DOSSIER (0 entrées aujourd'hui)")
        print("  Aucune entrée dans verification_log.json pour aujourd'hui.")
        return

    if not has_type_field:
        _section(f"4. ACTU ({len(verif)} entrées — champ article_type absent)")
        print("  Runs antérieurs au Format Dossier — séparation ACTU/DOSSIER indisponible.")
        _bloc_verif(verif_actu)
        return

    _section(f"4a. ACTU ({len(verif_actu)} entrées)")
    _bloc_verif(verif_actu)

    if verif_dossier:
        _section(f"4b. DOSSIER ({len(verif_dossier)} entrées)")
        print("  (Premier run avec Format Dossier — aucune référence historique)")
        _bloc_verif(verif_dossier)
    else:
        _section("4b. DOSSIER : 0 article vérifié")
        print("  Aucun candidat DOSSIER n'a passé la vérification, ou aucun trouvé.")


def _afficher_alertes_llm(pipeline: dict, verif: list):
    _section("5. ALERTES APPELS LLM")

    tentes = pipeline["articles_tentes"]
    alertes = []

    for i, art in enumerate(tentes):
        groq_appels = 1 + art["gardes"]
        verif_entry = verif[i] if i < len(verif) else None
        total = _total_llm(groq_appels, verif_entry)

        if total > SEUIL_APPELS_LLM:
            slug = verif_entry.get("slug", "—") if verif_entry else "—"
            alertes.append((i + 1, art["titre"][:40], groq_appels, total, slug))

    if not alertes:
        print(f"  OK — aucun article au-dessus du seuil de {SEUIL_APPELS_LLM} appels.")
    else:
        print(f"  ⚠  {len(alertes)} article(s) dépassent {SEUIL_APPELS_LLM} appels LLM :")
        for num, titre, groq, total, slug in alertes:
            print(f"    {num}. {titre:<40} | Groq={groq}  total≈{total}  slug={slug}")

    # Résumé global
    total_groq = len(tentes) + pipeline["garde_retries"]
    total_anthropic = sum(
        _anthropic_calls(e.get("statut", ""), e.get("tentatives"))
        for e in verif
    )
    print(f"\n  Total appels estimés ce run :")
    print(f"    Groq (génération)   : {total_groq}")
    print(f"    Anthropic (verif)   : {total_anthropic}")
    print(f"    TOTAL               : {total_groq + total_anthropic}")


def afficher(run_id: str, pipeline: dict, verif: list, run_date: str = ""):
    sep = "=" * 72
    label_date = run_date or date.today().isoformat()
    print(f"\n{sep}")
    print(f"ANALYSE RUN {run_id} — {label_date}")
    print(sep)

    # Groq — aperçu global
    tentes = pipeline["articles_tentes"]
    actu_log    = [a for a in tentes if a["type"] in ("ACTU", "actu")]
    dossier_log = [a for a in tentes if a["type"] not in ("ACTU", "actu")]

    print(f"\n  Articles tentés : {len(tentes)}"
          f"  (ACTU={len(actu_log)}, DOSSIER={len(dossier_log)})")
    print(f"  Articles publiés: {pipeline['articles_publies']}")
    print(f"  Détail articles :")
    for i, art in enumerate(tentes, 1):
        flags = ""
        if art.get("rejet_precoce"):  flags += " [REJET PRÉCOCE]"
        if art.get("rejet_dossier"):  flags += " [REJET DOSSIER]"
        print(f"    {i:2}. [{art['type']:<18}] "
              f"{art['titre'][:42]:<42} "
              f"src={art['sources']} gardes={art['gardes']}{flags}")

    verif_actu, _ = _split_by_type(verif)

    _afficher_alertes_quota(pipeline, verif)
    _afficher_verdict_sourcing(verif_actu)
    _afficher_causes(pipeline, verif)
    _afficher_actu_dossier(verif)
    _afficher_alertes_llm(pipeline, verif)

    print(f"\n{sep}\n")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_id = get_run_id(sys.argv[1] if len(sys.argv) > 1 else None)
    log, run_date = fetch_log(run_id)
    pipeline = parse_pipeline_log(log)
    verif = load_verif_for_date(run_date)
    afficher(run_id, pipeline, verif, run_date)
