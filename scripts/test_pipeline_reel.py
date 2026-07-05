"""Test du pipeline en conditions réelles — 1 article, 0 publication.

Collecte les flux RSS normalement, choisit le meilleur candidat du jour,
le génère via Claude (patch identique à regen_batch.py), lance la
vérification complète, puis rapporte le résultat SANS rien écrire sur le site.

Coupe-circuit : MAX_ANTHROPIC = 10 appels (génération + vérification).
Rien n'est publié — garantie structurelle via mtime sur articles/ et articles.json.

Usage :
    python test_pipeline_reel.py                        # RSS du jour
    python test_pipeline_reel.py --text "sujet précis"  # sujet forcé
    python test_pipeline_reel.py --stats                # taux cumulés
"""
import sys, json, os, re, copy, difflib
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime

# Lire ANTHROPIC_API_KEY depuis le registre Windows si absent du process
if not os.environ.get("ANTHROPIC_API_KEY"):
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as _k:
            _val, _ = winreg.QueryValueEx(_k, "ANTHROPIC_API_KEY")
            os.environ["ANTHROPIC_API_KEY"] = _val
    except Exception:
        pass

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import pipeline
import verification
import requests as _req

# ── Budget dur ───────────────────────────────────────────────────────────────
MAX_ANTHROPIC = 10

_n_gen   = 0
_n_verif = 0


class BudgetAtteint(Exception):
    pass


def _total():
    return _n_gen + _n_verif


# ── Patch génération : Claude au lieu de Groq ─────────────────────────────────
def _gen_anthropic(api_key, messages, max_tokens=8000):
    global _n_gen
    if _total() >= MAX_ANTHROPIC:
        raise BudgetAtteint(f"Plafond {MAX_ANTHROPIC} appels atteint")
    _n_gen += 1
    print(f"  [API gen #{_n_gen}] appel Claude…", flush=True)
    system, turns = "", []
    for m in messages:
        if m["role"] == "system":
            system = m["content"]
        else:
            turns.append({"role": m["role"], "content": m["content"]})
    r = _req.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": verification.ANTHROPIC_KEY,
                 "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": "claude-sonnet-4-6", "max_tokens": max_tokens,
              "system": system, "messages": turns},
        timeout=180,
    )
    r.raise_for_status()
    return r.json()["content"][0]["text"].strip()


# Original conservé ; le patch Claude est appliqué conditionnellement dans __main__
_groq_call_orig = pipeline._groq_call

# ── Patch vérification : compteur d'appels ────────────────────────────────────
_verif_orig = verification._anthropic_call


def _verif_compte(*a, **k):
    global _n_verif
    if _total() >= MAX_ANTHROPIC:
        raise BudgetAtteint(f"Plafond {MAX_ANTHROPIC} appels atteint")
    _n_verif += 1
    print(f"  [API verif #{_n_verif}] passe vérification…", flush=True)
    return _verif_orig(*a, **k)


verification._anthropic_call = _verif_compte

# ── Patch enqueue_moderation : capture les problèmes sans écrire en prod ─────
_captured_moderation: list[dict] = []
_enqueue_orig = verification.enqueue_moderation


def _enqueue_capture(art, rapport_init, rapport_final):
    _captured_moderation.append({
        "slug":           art.get("slug", "?"),
        "sujet_sensible": rapport_init.get("sujet_sensible"),
        "sujet_raison":   rapport_init.get("sujet_sensible_raison", ""),
        "conforme_init":  rapport_init.get("conforme"),
        "problemes_init": rapport_init.get("problemes", []),
        "conforme_final": rapport_final.get("conforme") if rapport_final else None,
        "problemes_final": rapport_final.get("problemes", []) if rapport_final else [],
    })
    # On appelle quand même l'original pour que la queue de modération soit
    # cohérente — en mode test, c'est acceptable d'écrire dans la file,
    # puisqu'elle n'est pas lue automatiquement.
    _enqueue_orig(art, rapport_init, rapport_final)


verification.enqueue_moderation = _enqueue_capture

# ── Garde structurelle : mtime sur les fichiers de publication ────────────────
_ARTICLES_DIR  = ROOT / "articles"
_ARTICLES_JSON = ROOT / "data" / "articles.json"


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except FileNotFoundError:
        return 0.0


_initial_mtimes = {
    str(_ARTICLES_JSON): _mtime(_ARTICLES_JSON),
    **{str(f): _mtime(f) for f in _ARTICLES_DIR.glob("*.html")},
}


def _verifier_aucune_publication():
    changed = []
    for path, t0 in _initial_mtimes.items():
        if _mtime(Path(path)) != t0:
            changed.append(path)
    new_files = [
        str(f) for f in _ARTICLES_DIR.glob("*.html")
        if str(f) not in _initial_mtimes
    ]
    changed += new_files
    if changed:
        raise RuntimeError(
            f"ALERTE : {len(changed)} fichier(s) modifié(s) malgré le mode test !\n"
            + "\n".join(changed[:5])
        )
    print("\n[OK] Aucun fichier de publication modifié.")


# ── Diff texte entre deux versions d'article ─────────────────────────────────
def _diff_corps(art_avant: dict, art_apres: dict) -> dict:
    """Compare les sections faits/contexte/nuances entre deux versions.
    Retourne un dict section→(lignes_retirées, lignes_ajoutées, ratio_changement).
    """
    resultat = {}
    for section in ("faits", "contexte", "nuances"):
        avant = (art_avant.get("corps") or {}).get(section, "") or ""
        apres = (art_apres.get("corps") or {}).get(section, "") or ""
        if avant == apres:
            resultat[section] = {"ratio": 0.0, "retirees": [], "ajoutees": []}
            continue
        ratio = 1 - difflib.SequenceMatcher(None, avant, apres).ratio()
        # Diff ligne par ligne (phrases)
        avant_l = [s.strip() for s in re.split(r"(?<=[.!?])\s+", avant) if len(s.strip()) > 20]
        apres_l = [s.strip() for s in re.split(r"(?<=[.!?])\s+", apres) if len(s.strip()) > 20]
        diff = list(difflib.unified_diff(avant_l, apres_l, lineterm="", n=0))
        retirees = [l[1:] for l in diff if l.startswith("-") and not l.startswith("---")]
        ajoutees = [l[1:] for l in diff if l.startswith("+") and not l.startswith("+++")]
        resultat[section] = {
            "ratio":    round(ratio, 3),
            "retirees": retirees[:5],
            "ajoutees": ajoutees[:5],
        }
    return resultat


# ── Collecte RSS ─────────────────────────────────────────────────────────────
def _get_tous_candidats() -> list:
    published = pipeline.load_published()
    published_topics = {a.get("titre", "") for a in pipeline.load_index()[:140]}
    tous = []
    for src in pipeline.RSS_SOURCES:
        items = pipeline.fetch_rss(src)
        deja_vus = {i["id"] for i in tous}
        for item in items:
            if item["id"] in published or item["id"] in deja_vus:
                continue
            scored = pipeline.filtrer_et_classer([item], src["name"], published_topics, seuil_score=20)
            if scored:
                tous.extend(scored)
    tous.sort(key=lambda x: x["_score"], reverse=True)
    return tous


def collecter_meilleur():
    print("\n[COLLECTE RSS]", flush=True)
    tous_candidats = _get_tous_candidats()

    if not tous_candidats:
        print("[ERREUR] Aucun candidat RSS valide trouvé.", flush=True)
        return None, []

    print(f"\n[SCORING] {len(tous_candidats)} candidat(s) — top 10 :")
    print(f"{'─'*70}")
    print(f"  {'SCORE':>5}  {'CAT':<12}  TITRE")
    print(f"{'─'*70}")
    for c in tous_candidats[:10]:
        print(f"  {c['_score']:>5}  {c.get('_cat','?'):<12}  {c['title'][:50]}")
    print(f"{'─'*70}")

    meilleur = tous_candidats[0]
    print(f"\n[SÉLECTION] → {meilleur['title']}")
    print(f"             Score : {meilleur['_score']}  |  Catégorie : {meilleur.get('_cat')}")
    print(f"             Source RSS : {meilleur.get('source_name')}  |  URL : {meilleur.get('url','')[:80]}")
    return meilleur, tous_candidats


# ── Génération + vérification sans publication ────────────────────────────────
def tester_article(item: dict) -> dict:
    rapport = {
        "titre_rss":        item["title"],
        "url_rss":          item.get("url", ""),
        "source_rss":       item.get("source_name", ""),
        "score_editorial":  item.get("_score"),
        "categorie":        item.get("_cat"),
        "ts":               datetime.now().isoformat(),
        "statut":           "non_lance",
        "nb_sources_ddg":   0,
        "nb_sources_finales": 0,
        "garde_fantomes":   None,   # détail du garde-fou 1 (diff avant/après relance)
        "fantomes_residuels": [],
        "problemes_verif":  [],
        "sujet_sensible":   False,
        "sujet_raison":     "",
        "article":          None,
    }

    cat = item.get("_cat") or pipeline.detect_category(item["title"] + " " + item["content"])

    # Scraping contenu complet
    print("\n[SCRAPING] contenu principal…", flush=True)
    full_content = ""
    if item.get("url"):
        full_content = pipeline.fetch_full_content(item["url"])
    content = full_content if len(full_content) > 500 else item["content"]
    print(f"  → {len(content)} chars utilisés")

    # Recherche DDG + PubMed
    print("\n[DDG] recherche de sources corroborantes…", flush=True)
    extra = pipeline.duckduckgo_search(item["title"] + " " + cat, max_results=8)
    pubmed = pipeline.pubmed_search(item["title"], max_results=4)
    seen_urls = {s["url"] for s in extra}
    for p in pubmed:
        if p["url"] not in seen_urls:
            extra.append(p)
            seen_urls.add(p["url"])
    for src in extra:
        if not pipeline._est_presse_protegee(src["url"]):
            full = pipeline.fetch_full_content(src["url"])
            if len(full) > 500:
                src["snippet"] = full[:8000]

    specific_sources = [
        s for s in extra
        if len(urlparse(s["url"]).path.rstrip("/")) > 5
        and not pipeline._est_source_exclue(s["url"])
    ]
    rapport["nb_sources_ddg"] = len(specific_sources)
    print(f"  → {len(specific_sources)} source(s) réelle(s) disponibles")

    if len(specific_sources) < 5:
        rapport["statut"] = "rejet_sources_insuffisantes"
        print(f"  [REJET] Moins de 5 sources — impossible de générer.")
        return rapport

    # ── Génération ────────────────────────────────────────────────────────────
    print("\n[GÉNÉRATION]", flush=True)
    try:
        art = pipeline.generate(content, cat, extra_sources=extra, rss_url=item.get("url"))
    except BudgetAtteint as e:
        rapport["statut"] = "budget_atteint"; rapport["erreur"] = str(e)
        return rapport
    except ValueError as e:
        rapport["statut"] = "hors_perimetre" if "HORS_PERIMETRE" in str(e) else "erreur_generation"
        rapport["erreur"] = str(e)[:200]
        return rapport

    # Garde-fou 1 : attributions fantômes — on sauvegarde l'état AVANT relance
    fantomes_v1 = pipeline.attributions_fantomes(art)
    if fantomes_v1:
        print(f"  [GARDE] {len(fantomes_v1)} attribution(s) hors sources — relance…", flush=True)
        art_v1 = copy.deepcopy(art)  # snapshot avant correction
        try:
            art = pipeline.generate(content, cat, extra_sources=extra, rss_url=item.get("url"),
                                    retry_feedback=fantomes_v1)
            fantomes_v2 = pipeline.attributions_fantomes(art)
        except BudgetAtteint as e:
            rapport["statut"] = "budget_atteint"; rapport["erreur"] = str(e)
            rapport["garde_fantomes"] = {"avant": fantomes_v1, "apres": "budget_atteint"}
            return rapport
        # Diff complet entre les deux passes
        diff = _diff_corps(art_v1, art)
        rapport["garde_fantomes"] = {
            "fantomes_v1":    fantomes_v1,
            "fantomes_v2":    fantomes_v2,
            "resolus":        [f for f in fantomes_v1 if f not in fantomes_v2],
            "persistants":    fantomes_v2,
            "diff_par_section": diff,
        }
    else:
        rapport["garde_fantomes"] = {"fantomes_v1": [], "fantomes_v2": [], "resolus": [], "persistants": []}

    fantomes_final = pipeline.attributions_fantomes(art)
    rapport["fantomes_residuels"] = fantomes_final

    # Garde-fou 3 : résumé répété
    repetitions = pipeline.resume_repete_corps(art)
    if repetitions:
        print(f"  [GARDE] résumé quasi-identique au corps — relance…", flush=True)
        try:
            art = pipeline.generate(content, cat, extra_sources=extra, rss_url=item.get("url"),
                                    repetition_feedback=repetitions)
        except BudgetAtteint as e:
            rapport["statut"] = "budget_atteint"; rapport["erreur"] = str(e)
            return rapport

    # Garde-fou 4 : répétitions intra-article
    intra = pipeline.faits_repetitifs(art)
    if intra:
        print(f"  [GARDE] {len(intra)} répétition(s) intra-article — relance…", flush=True)
        try:
            art = pipeline.generate(content, cat, extra_sources=extra, rss_url=item.get("url"),
                                    repetition_feedback=intra)
        except BudgetAtteint as e:
            rapport["statut"] = "budget_atteint"; rapport["erreur"] = str(e)
            return rapport

    # Garde-fou 2 : santé sensible sans source officielle
    if pipeline.sujet_sante_sans_source_officielle(art):
        rapport["statut"] = "moderation_sante"
        rapport["article"] = art
        print("  [MODÉRATION] Sujet santé sensible sans source officielle.")
        return rapport

    nb_src = len(art.get("sources", []))
    rapport["nb_sources_finales"] = nb_src
    total_chars = sum(len(art["corps"].get(k, "")) for k in ["faits", "contexte", "nuances"])
    print(f"  → {nb_src} source(s) finale(s)  |  {total_chars} chars de corps")

    if nb_src < 3:
        rapport["statut"] = "rejet_sources_post_generation"; rapport["article"] = art
        return rapport
    if total_chars < 600:
        rapport["statut"] = "rejet_corps_trop_court"; rapport["article"] = art
        return rapport

    # ── Vérification Anthropic (3 passes) ────────────────────────────────────
    print("\n[VÉRIFICATION]", flush=True)
    try:
        art, statut_verif = verification.verifier_article(art)
    except BudgetAtteint as e:
        rapport["statut"] = "budget_atteint"; rapport["erreur"] = str(e)
        rapport["article"] = art
        return rapport

    rapport["statut"]            = statut_verif
    rapport["article"]           = art
    rapport["nb_sources_finales"] = len(art.get("sources", []))
    rapport["fantomes_residuels"] = pipeline.attributions_fantomes(art)

    # Récupérer les problèmes depuis le patch enqueue_moderation
    if _captured_moderation:
        last = _captured_moderation[-1]
        rapport["sujet_sensible"]  = bool(last.get("sujet_sensible"))
        rapport["sujet_raison"]    = last.get("sujet_raison", "")
        pb_init  = last.get("problemes_init", [])
        pb_final = last.get("problemes_final", [])
        # On expose les problèmes résiduels (après correction) si dispo, sinon initiaux
        rapport["problemes_verif"] = pb_final if pb_final else pb_init

    return rapport


# ── Stats cumulées ────────────────────────────────────────────────────────────
def afficher_stats(since: str | None = None, modele: str | None = None):
    """Affiche les stats cumulées.

    `since`  filtre sur la date YYYYMMDD (inclusif).
    `modele` filtre sur le champ 'modele' du JSON (groq / claude).
    """
    fichiers = sorted((ROOT / "data").glob("test_reel_*.json"))
    if since:
        fichiers = [f for f in fichiers if f.name[10:18] >= since]
    if not fichiers:
        msg = f"Aucun rapport depuis {since}" if since else "Aucun rapport trouvé"
        print(msg + " dans data/test_reel_*.json")
        return

    total = 0
    details = []
    # 5 buckets clairs, mutuellement exclusifs
    buckets = {
        "publie_direct":         [],  # conforme_du_premier_coup
        "auto_corrige_republie": [],  # corrige_automatiquement / auto_corrige
        "rejete_sensible":       [],  # sujet/légal, rejet définitif (nouveau statut)
        "echec_technique":       [],  # rejete_qualite + a_corriger_manuellement (compat) + erreurs
        "hors_perimetre":        [],  # pas d'actu datée disponible (distinct des échecs techniques)
    }

    def _bucket(statut: str) -> str:
        if statut == "conforme_du_premier_coup":
            return "publie_direct"
        if statut in ("corrige_automatiquement", "auto_corrige"):
            return "auto_corrige_republie"
        if statut == "rejete_sensible":
            return "rejete_sensible"
        if statut == "hors_perimetre":
            return "hors_perimetre"
        # rejete_qualite, a_corriger_manuellement (ancien), moderation_sante,
        # rejet_*, budget_atteint, erreur_* → tous des échecs techniques
        return "echec_technique"

    for f in fichiers:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if modele and d.get("modele", "claude") != modele:
            continue
        statut = d.get("statut", "?")
        b = _bucket(statut)
        buckets[b].append(f.name)
        total += 1
        details.append({
            "date":    f.name[10:25],
            "modele":  d.get("modele", "claude"),
            "statut":  statut,
            "bucket":  b,
            "titre":   d.get("titre_rss", "?")[:50],
            "src_ddg": d.get("nb_sources_ddg", "?"),
            "src_fin": d.get("nb_sources_finales", "?"),
            "fant":    len(d.get("fantomes_residuels", d.get("fantomes", []))),
            "sensible": d.get("sujet_sensible", False),
        })

    if total == 0:
        print("Aucun rapport trouvé.")
        return

    titre_modele = f" [{modele.upper()}]" if modele else ""
    print("\n" + "=" * 70)
    print(f"STATS CUMULÉES{titre_modele} — {total} test(s)")
    print("=" * 70)

    LABELS = {
        "publie_direct":         "Publié direct (conforme)",
        "auto_corrige_republie": "Auto-corrigé et republié",
        "rejete_sensible":       "Rejeté sensible/légal",
        "echec_technique":       "Échec technique (qualité/sources)",
        "hors_perimetre":        "Hors périmètre (pas d'actu datée)",
    }
    publiable = len(buckets["publie_direct"]) + len(buckets["auto_corrige_republie"])
    print(f"\n  {'CATÉGORIE':<37}  {'N':>4}  {'%':>5}")
    print(f"  {'─'*50}")
    for key, label in LABELS.items():
        n = len(buckets[key])
        if n == 0:
            continue
        pct = 100 * n / total if total else 0
        marker = " ◄" if key in ("publie_direct", "auto_corrige_republie") else ""
        print(f"  {label:<37}  {n:>4}  {pct:>4.0f}%{marker}")
    print(f"  {'─'*50}")
    print(f"  {'TOTAL':<37}  {total:>4}")
    print(f"\n  Taux publiable : {publiable}/{total}"
          f"  ({100*publiable/total:.0f}%)" if total else "")

    print(f"\n  {'DATE':<17}  {'MOD':<6}  {'BUCKET':<20}  {'STATUT BRUT':<25}  {'S.DDG':>5}  {'S.FIN':>5}  {'FANT':>4}")
    print(f"  {'─'*97}")
    for d in details:
        sens = " [S]" if d["sensible"] else ""
        print(f"  {d['date']:<17}  {d['modele']:<6}  {d['bucket']:<20}  {d['statut']:<25}  "
              f"{str(d['src_ddg']):>5}  {str(d['src_fin']):>5}  {d['fant']:>4}  "
              f"{d['titre'][:35]}{sens}")
    print("=" * 70)


# ── Point d'entrée ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", type=str, default=None,
                        help="Forcer un sujet précis (bypass RSS)")
    parser.add_argument("--stats", action="store_true",
                        help="Afficher les stats cumulées de tous les tests précédents")
    parser.add_argument("--since", type=str, default=None, metavar="YYYYMMDD",
                        help="Filtrer les stats à partir de cette date (ex: 20260707)")
    parser.add_argument("--modele", choices=["groq", "claude"], default=None,
                        help="Moteur de génération : groq ou claude (défaut claude). "
                             "En mode --stats, filtre les résultats par modèle.")
    parser.add_argument("--reuse-item", action="store_true",
                        help="Réutiliser le candidat RSS du dernier run (pour comparer les modèles sur le même sujet)")
    args = parser.parse_args()
    modele = args.modele or "claude"   # défaut génération = claude

    if args.stats:
        # --modele sans valeur → filtre absent (toutes modèles)
        afficher_stats(since=args.since, modele=args.modele)
        sys.exit(0)

    # ── Appliquer le patch de génération selon le modèle choisi ──────────────
    if modele == "claude":
        pipeline._groq_call = _gen_anthropic
    else:
        pipeline._groq_call = _groq_call_orig  # Groq natif

    print("=" * 70)
    print("TEST PIPELINE RÉEL — 1 article, 0 publication")
    print(f"Budget : {MAX_ANTHROPIC} appels Anthropic max")
    print(f"Modèle : {modele.upper()}")
    if args.text:
        print(f"Mode   : sujet forcé via --text")
    if args.reuse_item:
        print(f"Mode   : candidat réutilisé depuis test_item_latest.json")
    print("=" * 70, flush=True)

    _ITEM_CACHE = ROOT / "data" / "test_item_latest.json"

    try:
        if args.text:
            meilleur = {
                "id":          __import__("hashlib").md5(args.text.encode()).hexdigest()[:14],
                "title":       args.text[:80],
                "url":         "",
                "content":     args.text,
                "source_name": "Manuel",
                "date":        datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000"),
                "_score":      50,
                "_cat":        pipeline.detect_category(args.text),
            }
            rapport = tester_article(meilleur)
        elif args.reuse_item:
            if not _ITEM_CACHE.exists():
                print("[ERREUR] Aucun test_item_latest.json trouvé — lancez d'abord sans --reuse-item.")
                sys.exit(1)
            meilleur = json.loads(_ITEM_CACHE.read_text(encoding="utf-8"))
            print(f"\n[REUSE] Candidat : {meilleur['title'][:70]}", flush=True)
            rapport = tester_article(meilleur)
        else:
            meilleur, tous_candidats = collecter_meilleur()
            if not meilleur:
                sys.exit(1)
            # Sauvegarder le meilleur candidat pour --reuse-item (campagne comparaison)
            _ITEM_CACHE.write_text(json.dumps(meilleur, ensure_ascii=False), encoding="utf-8")
            rapport = tester_article(meilleur)
            if rapport["statut"] in ("hors_perimetre", "rejet_sources_insuffisantes"):
                print(f"\n[INFO] '{rapport['statut']}' — tentative sur les candidats suivants…", flush=True)
                for suivant in tous_candidats[1:3]:
                    print(f"\n{'─'*50}\nCandidat : {suivant['title'][:60]}", flush=True)
                    r2 = tester_article(suivant)
                    if r2["statut"] not in ("hors_perimetre", "rejet_sources_insuffisantes"):
                        rapport = r2; meilleur = suivant
                        _ITEM_CACHE.write_text(json.dumps(meilleur, ensure_ascii=False), encoding="utf-8")
                        break
                    print(f"  → {r2['statut'].upper()} aussi.", flush=True)

    except KeyboardInterrupt:
        print("\n[INTERROMPU]")
        sys.exit(0)
    finally:
        try:
            _verifier_aucune_publication()
        except RuntimeError as e:
            print(f"\n[ALERTE CRITIQUE] {e}")

    # ── Résumé terminal ───────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("RÉSULTAT")
    print("=" * 70)
    print(f"Sujet             : {rapport['titre_rss']}")
    print(f"Source RSS        : {rapport['source_rss']}")
    print(f"Catégorie         : {rapport['categorie']}")
    print(f"Sources DDG+PM    : {rapport['nb_sources_ddg']}")
    print(f"Sources finales   : {rapport['nb_sources_finales']}")
    print(f"Statut            : {rapport['statut'].upper()}")
    print(f"Appels API        : gen={_n_gen}  verif={_n_verif}  total={_total()}/{MAX_ANTHROPIC}")

    # Détail garde-fou fantômes
    gf = rapport.get("garde_fantomes") or {}
    if gf.get("fantomes_v1"):
        print(f"\nGarde-fou attributions fantômes :")
        print(f"  Détectés (v1) : {gf['fantomes_v1']}")
        print(f"  Résolus       : {gf.get('resolus', [])}")
        print(f"  Persistants   : {gf.get('persistants', [])}")
        diff = gf.get("diff_par_section", {})
        for sec, d in diff.items():
            if d["ratio"] > 0.01:
                print(f"  Diff [{sec}] : {d['ratio']*100:.1f}% modifié")
                for l in d.get("retirees", [])[:2]:
                    print(f"    − {l[:100]}")
                for l in d.get("ajoutees", [])[:2]:
                    print(f"    + {l[:100]}")

    if rapport.get("fantomes_residuels"):
        print(f"\nFantômes résiduels ({len(rapport['fantomes_residuels'])}) :")
        for f in rapport["fantomes_residuels"][:5]:
            print(f"  • {f}")

    if rapport.get("sujet_sensible"):
        print(f"\nSujet sensible : {rapport.get('sujet_raison', '(raison non capturée)')}")

    if rapport.get("problemes_verif"):
        pbs = rapport["problemes_verif"]
        print(f"\nProblèmes vérification ({len(pbs)}) :")
        for p in pbs[:8]:
            t = p.get("type", "?"); s = p.get("section", "?")
            x = (p.get("explication") or p.get("phrase_exacte") or "")[:120]
            print(f"  [{t}/{s}] {x}")

    if rapport.get("article"):
        art = rapport["article"]
        total_chars = sum(len((art.get("corps") or {}).get(k, "")) for k in ["faits", "contexte", "nuances"])
        print(f"\nArticle généré    : «{art.get('titre','?')}»")
        print(f"Slug              : {art.get('slug','?')}")
        print(f"Corps total       : {total_chars} chars")
        for s in art.get("sources", []):
            print(f"  • {s.get('institution','?')}  →  {(s.get('url') or 'null')[:80]}")

    # Sauvegarde JSON
    rapport["modele"] = modele
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = ROOT / "data" / f"test_reel_{ts}.json"
    rapport_save = {k: v for k, v in rapport.items() if k != "article"}
    if rapport.get("article"):
        a = rapport["article"]
        rapport_save["article_resume"] = {
            "titre":     a.get("titre"),
            "slug":      a.get("slug"),
            "nb_sources": len(a.get("sources", [])),
            "sources":   a.get("sources", []),
            "corps_chars": {k: len((a.get("corps") or {}).get(k, ""))
                            for k in ["faits", "contexte", "nuances"]},
        }
    out.write_text(json.dumps(rapport_save, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nRapport JSON : {out.name}")

    # Stats cumulées à la fin de chaque run
    print()
    afficher_stats(since=args.since)
