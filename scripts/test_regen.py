"""Test de RÉGÉNÉRATION sur 3 articles de pile B (ne publie/écrit rien).
Réplique le flux réel de generer_article : recherche de sources fraîches sur
le SUJET (titre de l'ancien article), seuil de 5 sources, génération Groq
contrainte aux seules URLs réelles, garde-fous, puis vérification Anthropic.

Trois issues possibles, rapportées distinctement :
  - rejet_sources : < 5 sources fraîches trouvées → retomberait en pile C (purge)
  - regenere      : généré + vérifié conforme/corrigé automatiquement
  - moderation    : généré mais nécessite relecture humaine (bloc 1/2/5, sujet
                    sensible, perte de substance, ou garde-fou fantômes/santé)

Coupe-circuit : plafond dur d'appels ANTHROPIC (le coût réel). Groq compté
pour info (génération, tarif négligeable)."""
import sys, re
from pathlib import Path
from urllib.parse import urlparse
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import verification
import pipeline

# ── Coupe-circuit budget (appels Anthropic uniquement) ──────────────────────
MAX_ANTHROPIC = 40
_n_anthropic = 0
_n_groq = 0


class BudgetAtteint(Exception):
    pass


_anthropic_orig = verification._anthropic_call
def _anthropic_compte(*a, **k):
    global _n_anthropic
    if _n_anthropic >= MAX_ANTHROPIC:
        raise BudgetAtteint(f"Plafond {MAX_ANTHROPIC} appels Anthropic atteint")
    _n_anthropic += 1
    return _anthropic_orig(*a, **k)
verification._anthropic_call = _anthropic_compte

_groq_orig = pipeline._groq_call
def _groq_compte(*a, **k):
    global _n_groq
    _n_groq += 1
    return _groq_orig(*a, **k)
pipeline._groq_call = _groq_compte

# Neutraliser les écritures (file de modération / log) — test pur, sans effet
verification.enqueue_moderation = lambda *a, **k: None
verification._log = lambda *a, **k: None

# ── Échantillon contrasté ───────────────────────────────────────────────────
SLUGS = [
    "exoplanete-proche-terre-conditions-vie",     # evergreen/science — devrait trouver des sources
    "openai-reporte-introduction-bourse-2027",     # tech récent — COMPARER (article déjà sain), pas corriger
    "loi-urgence-agricole-acetamipride",           # législatif daté/niche — test du rejet_sources
]


def meta(slug):
    html = (ROOT / "articles" / f"{slug}.html").read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(html, "lxml")
    t = soup.select_one("h1.art__title")
    titre = t.get_text(strip=True) if t else slug
    m = re.search(r"cat--([a-z]+)", html)
    cat = m.group(1) if m else pipeline.detect_category(titre)
    return titre, cat


def wc(txt):
    return len((txt or "").split())


def regenerer(slug):
    titre, cat = meta(slug)
    print(f"\n{'='*100}\n>>> {slug}\n    titre : {titre}\n    catégorie : {cat}\n{'='*100}", flush=True)

    # 1. Recherche de sources FRAÎCHES sur le sujet
    extra = pipeline.duckduckgo_search(titre + " " + cat, max_results=8)
    pubmed = pipeline.pubmed_search(titre, max_results=4)
    seen = {s["url"] for s in extra}
    for p in pubmed:
        if p["url"] not in seen:
            extra.append(p); seen.add(p["url"])
    specific = [s for s in extra if len(urlparse(s["url"]).path.rstrip("/")) > 5]
    print(f"    sources fraîches trouvées : {len(specific)} spécifiques / {len(extra)} brutes", flush=True)

    if len(specific) < 5:
        print(f"    STATUT: rejet_sources  (< 5 sources → retomberait en pile C)", flush=True)
        return "rejet_sources"

    # 2. Contenu de base = premier article frais réellement récupérable
    content = titre
    for s in specific:
        fc = pipeline.fetch_full_content(s["url"])
        if len(fc) > 500:
            content = fc
            print(f"    contenu de base : {s['url'][:70]} ({len(fc)} car.)", flush=True)
            break

    # 3. Génération contrainte aux sources réelles + garde-fous (comme generer_article)
    art = pipeline.generate(content, cat, extra_sources=extra, rss_url=None)

    fant = pipeline.attributions_fantomes(art)
    if fant:
        art = pipeline.generate(content, cat, extra_sources=extra, rss_url=None, retry_feedback=fant)
        if pipeline.attributions_fantomes(art):
            print(f"    STATUT: moderation  (attributions fantômes persistantes)", flush=True)
            return "moderation"
    rep = pipeline.resume_repete_corps(art)
    if rep:
        art = pipeline.generate(content, cat, extra_sources=extra, rss_url=None, repetition_feedback=rep)
    intra = pipeline.faits_repetitifs(art)
    if intra:
        art = pipeline.generate(content, cat, extra_sources=extra, rss_url=None, repetition_feedback=intra)
    if pipeline.sujet_sante_sans_source_officielle(art):
        print(f"    STATUT: moderation  (sujet santé sans source officielle)", flush=True)
        return "moderation"

    total = sum(len(art["corps"].get(k, "")) for k in ("faits", "contexte", "nuances"))
    if len(art.get("sources", [])) < 3 or total < 600:
        print(f"    STATUT: rejet_sources  (corps/sources insuffisants après génération)", flush=True)
        return "rejet_sources"

    # 4. Vérification Anthropic
    art_final, statut = verification.verifier_article(art)
    print(f"    sources finales : {art_final.get('nb_sources')} | "
          f"mots faits/contexte/nuances : "
          f"{wc(art_final['corps'].get('faits',''))}/"
          f"{wc(art_final['corps'].get('contexte',''))}/"
          f"{wc(art_final['corps'].get('nuances',''))}", flush=True)
    if statut in ("conforme_du_premier_coup", "corrige_automatiquement"):
        print(f"    STATUT: regenere  ({statut})", flush=True)
        return "regenere"
    print(f"    STATUT: moderation  ({statut})", flush=True)
    return "moderation"


def main():
    print(f"Anthropic clé : {bool(verification.ANTHROPIC_KEY)} | plafond : {MAX_ANTHROPIC} appels (~{MAX_ANTHROPIC*0.05:.2f} $)", flush=True)
    resultats = {}
    for slug in SLUGS:
        try:
            resultats[slug] = regenerer(slug)
        except BudgetAtteint as e:
            print(f"\n[BUDGET] {e} — arrêt", flush=True)
            resultats[slug] = "budget_atteint"
            break
        except Exception as e:
            import traceback
            print(f"    [ERREUR] {type(e).__name__}: {e}", flush=True)
            print(traceback.format_exc(), flush=True)
            resultats[slug] = "erreur"
    print(f"\n{'='*100}\nRÉSUMÉ\n{'='*100}", flush=True)
    for slug, st in resultats.items():
        print(f"  {slug:48s} -> {st}", flush=True)
    print(f"\nAppels Anthropic : {_n_anthropic}/{MAX_ANTHROPIC}  (~{_n_anthropic*0.05:.2f} $)", flush=True)
    print(f"Appels Groq (génération, négligeable) : {_n_groq}", flush=True)


if __name__ == "__main__":
    main()
