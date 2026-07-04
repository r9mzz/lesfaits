"""Test de RÉGÉNÉRATION sur 3 articles de pile B (ne publie/écrit rien).
Cette version route la GÉNÉRATION vers Anthropic (Sonnet) au lieu de Groq,
pour mesurer coût + qualité quand la génération elle-même passe sur Anthropic
(Groq gratuit étant plafonné à ~10 articles/jour).

Réplique le flux réel de generer_article : recherche de sources fraîches sur
le SUJET, seuil de 5 sources, génération contrainte aux seules URLs réelles,
garde-fous, puis vérification Anthropic.

Issues : rejet_sources / regenere / moderation.
Coupe-circuit : plafond dur d'appels Anthropic (génération + vérification
partagent le même compteur). Rien n'est écrit sur disque."""
import sys, re, json
from pathlib import Path
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import verification
import pipeline

MAX_ANTHROPIC = 40
_n_gen = 0
_n_verif = 0


class BudgetAtteint(Exception):
    pass


def _total():
    return _n_gen + _n_verif


# Génération routée vers Anthropic (remplace _groq_call, même interface)
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
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": verification.ANTHROPIC_KEY,
                 "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": "claude-sonnet-4-6", "max_tokens": max_tokens,
              "system": system, "messages": turns},
        timeout=180,
    )
    r.raise_for_status()
    return r.json()["content"][0]["text"].strip()
pipeline._groq_call = _gen_anthropic

# Vérification : même clé, compteur partagé pour le plafond
_verif_orig = verification._anthropic_call
def _verif_compte(*a, **k):
    global _n_verif
    if _total() >= MAX_ANTHROPIC:
        raise BudgetAtteint(f"Plafond {MAX_ANTHROPIC} appels atteint")
    _n_verif += 1
    return _verif_orig(*a, **k)
verification._anthropic_call = _verif_compte

# Neutraliser les écritures (test pur)
verification.enqueue_moderation = lambda *a, **k: None
verification._log = lambda *a, **k: None

SLUGS = [
    "exoplanete-proche-terre-conditions-vie",
    "openai-reporte-introduction-bourse-2027",
    "loi-urgence-agricole-acetamipride",
]


def meta(slug):
    html = (ROOT / "articles" / f"{slug}.html").read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(html, "lxml")
    t = soup.select_one("h1.art__title")
    titre = t.get_text(strip=True) if t else slug
    cat = pipeline.detect_category(titre)  # recatégorisation fraîche
    return titre, cat


def wc(txt):
    return len((txt or "").split())


def regenerer(slug):
    titre, cat = meta(slug)
    print(f"\n{'='*100}\n>>> {slug}\n    titre : {titre}\n    catégorie (fraîche) : {cat}\n{'='*100}", flush=True)

    extra = pipeline.duckduckgo_search(titre + " " + cat, max_results=8)
    pubmed = pipeline.pubmed_search(titre, max_results=4)
    seen = {s["url"] for s in extra}
    for p in pubmed:
        if p["url"] not in seen:
            extra.append(p); seen.add(p["url"])
    specific = [s for s in extra if len(urlparse(s["url"]).path.rstrip("/")) > 5]
    print(f"    sources fraîches : {len(specific)} spécifiques / {len(extra)} brutes", flush=True)
    if len(specific) < 5:
        print(f"    STATUT: rejet_sources", flush=True)
        return "rejet_sources"

    content = titre
    for s in specific:
        fc = pipeline.fetch_full_content(s["url"])
        if len(fc) > 500:
            content = fc
            print(f"    contenu de base : {s['url'][:70]} ({len(fc)} car.)", flush=True)
            break

    art = pipeline.generate(content, cat, extra_sources=extra, rss_url=None)
    fant = pipeline.attributions_fantomes(art)
    if fant:
        art = pipeline.generate(content, cat, extra_sources=extra, rss_url=None, retry_feedback=fant)
        if pipeline.attributions_fantomes(art):
            print(f"    STATUT: moderation  (fantômes persistants)", flush=True)
            return "moderation"
    if pipeline.resume_repete_corps(art):
        art = pipeline.generate(content, cat, extra_sources=extra, rss_url=None,
                                repetition_feedback=pipeline.resume_repete_corps(art))
    if pipeline.faits_repetitifs(art):
        art = pipeline.generate(content, cat, extra_sources=extra, rss_url=None,
                                repetition_feedback=pipeline.faits_repetitifs(art))
    if pipeline.sujet_sante_sans_source_officielle(art):
        print(f"    STATUT: moderation  (santé sans source officielle)", flush=True)
        return "moderation"

    total = sum(len(art["corps"].get(k, "")) for k in ("faits", "contexte", "nuances"))
    if len(art.get("sources", [])) < 3 or total < 600:
        print(f"    STATUT: rejet_sources  (corps/sources insuffisants)", flush=True)
        return "rejet_sources"

    art_final, statut = verification.verifier_article(art)
    print(f"    sources finales : {art_final.get('nb_sources')} | "
          f"mots f/c/n : {wc(art_final['corps'].get('faits',''))}/"
          f"{wc(art_final['corps'].get('contexte',''))}/{wc(art_final['corps'].get('nuances',''))}", flush=True)
    print(f"    aperçu faits : {art_final['corps'].get('faits','')[:220]}", flush=True)
    if statut in ("conforme_du_premier_coup", "corrige_automatiquement"):
        print(f"    STATUT: regenere  ({statut})", flush=True)
        return "regenere"
    print(f"    STATUT: moderation  ({statut})", flush=True)
    return "moderation"


def main():
    print(f"Génération: Anthropic Sonnet | Vérif: Anthropic | plafond {MAX_ANTHROPIC} appels (~{MAX_ANTHROPIC*0.05:.2f} $ ordre de grandeur)", flush=True)
    res = {}
    for slug in SLUGS:
        try:
            res[slug] = regenerer(slug)
        except BudgetAtteint as e:
            print(f"\n[BUDGET] {e}", flush=True); res[slug] = "budget_atteint"; break
        except Exception as e:
            import traceback
            print(f"    [ERREUR] {type(e).__name__}: {e}\n{traceback.format_exc()}", flush=True)
            res[slug] = "erreur"
    print(f"\n{'='*100}\nRÉSUMÉ\n{'='*100}", flush=True)
    for s, st in res.items():
        print(f"  {s:48s} -> {st}", flush=True)
    print(f"\nAppels génération : {_n_gen} | vérification : {_n_verif} | TOTAL : {_total()}/{MAX_ANTHROPIC}", flush=True)
    print(f"Coût ordre de grandeur (~0,05 $/appel, À CONFIRMER sur facturation) : ~{_total()*0.05:.2f} $", flush=True)
    if _total() and res:
        done = [s for s in res.values() if s in ("regenere","moderation")]
        if done:
            print(f"Coût/article traité (gén+vérif complète) : ~{_total()*0.05/max(len(done),1):.2f} $", flush=True)


if __name__ == "__main__":
    main()
