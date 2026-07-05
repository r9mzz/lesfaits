"""Régénération par lot — pile B, premier lot de 15 articles max.

NE PUBLIE RIEN. Produit deux fichiers dans data/ :
  regen_batch_YYYYMMDD_HHMMSS.json  — rapport complet (article généré, sources
                                       enrichies, fantômes, statuts)
  regen_batch_YYYYMMDD_HHMMSS.csv   — résumé tabulaire pour lecture rapide

Logique de sélection : quota par catégorie (ceil(MAX_ARTICLES / n_cats)) pour
garantir la diversité thématique, tri intra-catégorie par date décroissante.

Coupe-circuit : plafond dur de MAX_ANTHROPIC appels partagés entre génération
et vérification. Lève BudgetAtteint dès dépassement — résultats partiels
sauvegardés avant d'arrêter.
"""
import sys, json, csv, math, re, time, os
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime
from collections import defaultdict
import unicodedata

# Sous Windows, lire ANTHROPIC_API_KEY depuis le registre user si absente du process
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

# ── Paramètres ──────────────────────────────────────────────────────────────
MAX_ARTICLES   = 15
MAX_ANTHROPIC  = 90   # ~4,50 $ au tarif mesuré (~0,05 $/appel) avec marge 50 %

# Slugs à exclure de ce lot (faux positifs pile B ou comportements connus)
EXCLURE = {
    "openai-reporte-introduction-bourse-2027",  # HORS_PERIMETRE récurrent
    "exoplanete-proche-terre-conditions-vie",   # HORS_PERIMETRE récurrent
    "controle-aerien-france-en-crise",          # faux positif doublon
    "ia-dechiffre-papyrus-antiques",            # faux positif identifié
}

# Si non-vide, bypasse la sélection CSV et traite exactement ces slugs.
# Utile pour relancer un sous-ensemble (ex. uniquement les HORS_PERIMETRE).
FORCER_SLUGS: list[str] = []

# ── Compteur d'appels ────────────────────────────────────────────────────────
_n_gen   = 0
_n_verif = 0


class BudgetAtteint(Exception):
    pass


def _total():
    return _n_gen + _n_verif


# Patcher génération (Anthropic à la place de Groq pour les tests en CI ;
# en production Groq est utilisé directement — commenter les deux lignes
# ci-dessous pour utiliser Groq)
import requests as _req


def _gen_anthropic(api_key, messages, max_tokens=8000):
    global _n_gen
    if _total() >= MAX_ANTHROPIC:
        raise BudgetAtteint(f"Plafond {MAX_ANTHROPIC} appels atteint")
    _n_gen += 1
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


pipeline._groq_call = _gen_anthropic

# Patcher vérification pour compter les appels
_verif_orig = verification._anthropic_call


def _verif_compte(*a, **k):
    global _n_verif
    if _total() >= MAX_ANTHROPIC:
        raise BudgetAtteint(f"Plafond {MAX_ANTHROPIC} appels atteint")
    _n_verif += 1
    return _verif_orig(*a, **k)


verification._anthropic_call = _verif_compte

# Neutraliser les écritures de verification.py (pas de publication)
verification.enqueue_moderation = lambda *a, **k: None
verification._log = lambda *a, **k: None


# ── Sélection des slugs ──────────────────────────────────────────────────────

def _norm_cat(cat: str) -> str:
    """Normalise les variantes de casse/accents des catégories du CSV."""
    c = unicodedata.normalize("NFD", cat.strip())
    c = "".join(ch for ch in c if unicodedata.category(ch) != "Mn").lower()
    return c or "autre"


def selectionner_slugs() -> list[dict]:
    """Lit triage_corpus.csv, filtre pile B hors exclusions, sélectionne
    MAX_ARTICLES articles avec quota par catégorie et tri date décroissante.
    Si FORCER_SLUGS est défini, retourne directement ces slugs (dans l'ordre)."""
    if FORCER_SLUGS:
        return [{"slug": s, "pile": "B", "categorie": "", "date": ""} for s in FORCER_SLUGS]

    csv_path = ROOT / "triage_corpus.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"triage_corpus.csv introuvable ({csv_path})")

    with open(csv_path, encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f)
                if r["pile"] == "B" and r["slug"] not in EXCLURE]

    by_cat = defaultdict(list)
    for r in rows:
        by_cat[_norm_cat(r.get("categorie", ""))].append(r)

    n_cats = len(by_cat)
    quota  = math.ceil(MAX_ARTICLES / max(n_cats, 1))

    selected = []
    for cat in sorted(by_cat):
        arts = sorted(by_cat[cat], key=lambda r: r.get("date", ""), reverse=True)
        selected.extend(arts[:quota])

    return selected[:MAX_ARTICLES]


# ── Lecture titre depuis HTML ─────────────────────────────────────────────────

def _lire_titre(slug: str) -> str:
    path = ROOT / "articles" / f"{slug}.html"
    if not path.exists():
        return slug
    from bs4 import BeautifulSoup
    html = path.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(html, "lxml")
    t = soup.select_one("h1.art__title")
    return t.get_text(strip=True) if t else slug


# ── Traitement d'un article ───────────────────────────────────────────────────

def traiter(row: dict) -> dict:
    slug  = row["slug"]
    titre = _lire_titre(slug)
    cat   = pipeline.detect_category(titre)

    print(f"\n{'='*90}\n>>> {slug}\n    titre : {titre[:70]}\n    cat   : {cat}", flush=True)

    result: dict = {"slug": slug, "titre": titre, "categorie": cat,
                    "fantomes_pass1": [], "fantomes_pass2": [],
                    "nb_mots": {}, "nb_sources": 0, "sources": [],
                    "sources_enrichies": [], "article_json": None}

    # 1. Recherche de sources
    extra  = pipeline.duckduckgo_search(titre + " " + cat, max_results=8)
    pubmed = pipeline.pubmed_search(titre, max_results=4)
    seen   = {s["url"] for s in extra}
    for p in pubmed:
        if p["url"] not in seen:
            extra.append(p); seen.add(p["url"])

    specific = [s for s in extra
                if len(urlparse(s["url"]).path.rstrip("/")) > 5
                and not pipeline._est_source_exclue(s["url"])]
    print(f"    sources : {len(specific)} spécifiques / {len(extra)} brutes", flush=True)

    if len(specific) < 5:
        print(f"    STATUT: rejet_sources", flush=True)
        result["statut"] = "rejet_sources"
        return result

    # 2. Enrichissement scraping
    for src in extra:
        if not pipeline._est_presse_protegee(src["url"]):
            full = pipeline.fetch_full_content(src["url"])
            if len(full) > 500:
                src["snippet"] = full[:8000]

    # Sauvegarder les sources enrichies pour le rapport (snippet tronqué à 500)
    result["sources_enrichies"] = [
        {"url": s["url"], "title": s.get("title", ""),
         "snippet_chars": len(s.get("snippet", "")),
         "snippet_preview": s.get("snippet", "")[:500]}
        for s in extra
    ]

    # 3. Contenu de base : première source scrapée pertinente (≥2 mots-clés du titre)
    #    Wikipedia est exclu du rôle de contenu principal (trop générique pour ancrer
    #    une actualité datée) — il peut rester dans extra_sources comme source secondaire.
    _mots_titre = {w for w in re.findall(r"[a-zà-ÿ]+", titre.lower()) if len(w) >= 5}
    content = titre
    for s in specific:
        try:
            host = (urlparse(s["url"]).hostname or "").lower()
        except Exception:
            host = ""
        if "wikipedia.org" in host:
            continue
        fc = pipeline.fetch_full_content(s["url"])
        if len(fc) < 500:
            continue
        fc_lower = fc.lower()
        if sum(1 for w in _mots_titre if w in fc_lower) >= 2:
            content = fc
            print(f"    contenu base : {s['url'][:65]} ({len(fc)} car.)", flush=True)
            break
    else:
        if content == titre:
            print(f"    contenu base : titre seul (aucune source pertinente)", flush=True)

    # 4. Génération pass-1
    art = pipeline.generate(content, cat, extra_sources=extra, rss_url=None)
    src_names = [s.get("institution", "?") for s in art.get("sources", [])]
    print(f"    sources validées p1 : {src_names}", flush=True)

    fant1 = pipeline.attributions_fantomes(art)
    result["fantomes_pass1"] = fant1
    if fant1:
        print(f"    fantômes p1 : {fant1}", flush=True)
        art = pipeline.generate(content, cat, extra_sources=extra,
                                rss_url=None, retry_feedback=fant1)
        fant2 = pipeline.attributions_fantomes(art)
        result["fantomes_pass2"] = fant2
        if fant2:
            print(f"    fantômes p2 (persistants) : {fant2}", flush=True)
            result["statut"]     = "moderation"
            result["article_json"] = art
            _enrich_result(result, art)
            return result

    # 5. Gardes-fous résumé/répétition (non bloquants)
    reps = pipeline.resume_repete_corps(art)
    if reps:
        art = pipeline.generate(content, cat, extra_sources=extra,
                                rss_url=None, repetition_feedback=reps)
    intra = pipeline.faits_repetitifs(art)
    if intra:
        art = pipeline.generate(content, cat, extra_sources=extra,
                                rss_url=None, repetition_feedback=intra)

    # 6. Garde-fou santé
    if pipeline.sujet_sante_sans_source_officielle(art):
        print(f"    STATUT: moderation (santé sans source officielle)", flush=True)
        result["statut"]     = "moderation"
        result["article_json"] = art
        _enrich_result(result, art)
        return result

    # 7. Vérification fact-checker
    art_final, statut = verification.verifier_article(art)
    result["statut"]     = statut
    result["article_json"] = art_final
    _enrich_result(result, art_final)

    corps = art_final.get("corps", {}) or {}
    wc    = lambda t: len((t or "").split())
    print(f"    mots f/c/n : {wc(corps.get('faits',''))}/{wc(corps.get('contexte',''))}"
          f"/{wc(corps.get('nuances',''))}  |  sources : {art_final.get('nb_sources')}  "
          f"|  statut : {statut}", flush=True)

    return result


def _enrich_result(result: dict, art: dict):
    corps = art.get("corps", {}) or {}
    wc    = lambda t: len((t or "").split())
    result["nb_mots"]   = {
        "faits":    wc(corps.get("faits",    "")),
        "contexte": wc(corps.get("contexte", "")),
        "nuances":  wc(corps.get("nuances",  "")),
        "total":    wc(corps.get("faits","")) + wc(corps.get("contexte","")) + wc(corps.get("nuances","")),
    }
    result["nb_sources"] = art.get("nb_sources", 0)
    result["sources"]    = [{"institution": s.get("institution", ""),
                              "url": s.get("url", ""),
                              "titre": s.get("titre", "")}
                             for s in art.get("sources", [])]


# ── Rapport ───────────────────────────────────────────────────────────────────

def sauvegarder(results: list[dict], ts: str):
    data_dir = ROOT / "data"
    data_dir.mkdir(exist_ok=True)

    # JSON complet
    json_path = data_dir / f"regen_batch_{ts}.json"
    rapport = {
        "date": ts,
        "parametres": {"max_articles": MAX_ARTICLES, "max_anthropic": MAX_ANTHROPIC},
        "appels": {"generation": _n_gen, "verification": _n_verif, "total": _total()},
        "articles": results,
    }
    json_path.write_text(json.dumps(rapport, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  Rapport JSON : {json_path.name}", flush=True)

    # CSV résumé
    csv_path = data_dir / f"regen_batch_{ts}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["slug", "statut", "categorie", "nb_mots_total",
                    "nb_sources", "nb_fantomes_p1", "nb_fantomes_p2"])
        for r in results:
            w.writerow([
                r["slug"], r.get("statut", ""), r.get("categorie", ""),
                r.get("nb_mots", {}).get("total", 0),
                r.get("nb_sources", 0),
                len(r.get("fantomes_pass1", [])),
                len(r.get("fantomes_pass2", [])),
            ])
    print(f"  Rapport CSV  : {csv_path.name}", flush=True)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"REGEN BATCH — {ts}", flush=True)
    print(f"Plafond : {MAX_ARTICLES} articles | {MAX_ANTHROPIC} appels Anthropic", flush=True)
    print("Aucune publication automatique — rapport uniquement\n", flush=True)

    slugs = selectionner_slugs()
    print(f"Articles sélectionnés ({len(slugs)}) :")
    for r in slugs:
        print(f"  [{_norm_cat(r.get('categorie',''))[:12]:12s}] {r['slug']}")
    print(flush=True)

    results = []
    for row in slugs:
        try:
            res = traiter(row)
            results.append(res)
        except BudgetAtteint as e:
            print(f"\n[BUDGET] {e}", flush=True)
            results.append({"slug": row["slug"], "statut": "budget_atteint",
                            "fantomes_pass1": [], "fantomes_pass2": [],
                            "nb_mots": {}, "nb_sources": 0, "sources": [],
                            "sources_enrichies": [], "article_json": None})
            break
        except Exception as e:
            import traceback
            print(f"    [ERREUR] {type(e).__name__}: {e}\n{traceback.format_exc()}", flush=True)
            results.append({"slug": row["slug"], "statut": "erreur",
                            "fantomes_pass1": [], "fantomes_pass2": [],
                            "nb_mots": {}, "nb_sources": 0, "sources": [],
                            "sources_enrichies": [], "article_json": None})

    # Résumé console
    print(f"\n{'='*90}\nRÉSUMÉ\n{'='*90}", flush=True)
    compteurs: dict[str, int] = {}
    for r in results:
        st = r.get("statut", "?")
        compteurs[st] = compteurs.get(st, 0) + 1
        print(f"  {r['slug']:50s} -> {st}", flush=True)
    print(flush=True)
    for st, n in sorted(compteurs.items()):
        print(f"  {st:30s} : {n}", flush=True)
    print(f"\nAppels : gen={_n_gen}  verif={_n_verif}  total={_total()}/{MAX_ANTHROPIC}", flush=True)
    print(f"Coût estimé (~0,05 $/appel) : ~{_total()*0.05:.2f} $", flush=True)

    sauvegarder(results, ts)


if __name__ == "__main__":
    main()
