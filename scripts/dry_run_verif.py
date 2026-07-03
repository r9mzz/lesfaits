"""Dry-run de vérification Anthropic sur un échantillon stratifié d'articles
déjà publiés. NE MODIFIE AUCUN FICHIER — observation uniquement. Affiche :
- la répartition des statuts (conforme / corrige_automatiquement / a_corriger_manuellement)
- le détail des garde-fous déclenchés (bloc5, sujet_sensible, perte_substance)
- le nombre de mots avant/après par section pour chaque article corrigé
- le nombre d'appels API consommés, avec arrêt si le plafond est atteint

Plafond de budget : MAX_APPELS ci-dessous (estimé à ~0,05 $/appel d'après
les tests précédents — approximatif, à vérifier sur la facturation réelle
Anthropic, pas une valeur garantie)."""
import sys, re
from pathlib import Path
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent))
import verification
from verification import verifier_article, ANTHROPIC_KEY

# ── Plafond de budget — coupe net, pas juste un compteur décoratif ─────────
MAX_APPELS = 60  # ~3 $ estimé à 0,05 $/appel — À AJUSTER avant de lancer
_appels_effectues = 0
_budget_atteint = False


class BudgetAtteint(Exception):
    pass


_appel_original = verification._anthropic_call


def _appel_compte(*args, **kwargs):
    global _appels_effectues, _budget_atteint
    if _appels_effectues >= MAX_APPELS:
        _budget_atteint = True
        raise BudgetAtteint(f"Plafond de {MAX_APPELS} appels atteint")
    _appels_effectues += 1
    return _appel_original(*args, **kwargs)


verification._anthropic_call = _appel_compte


# ── Échantillon stratifié (9 articles), pas au hasard ───────────────────────
SLUGS = [
    "sante-environnementale-impact-humain",        # quasi-doublon (A)
    "sante-environnementale-defis-savoirs",         # quasi-doublon (B)
    "violences-enfants-france-insuffisante",        # garde-fou sujet sensible attendu
    "redmi-15-5g-smartphone-abordable",             # ancien format HTML <cite>
    "washington-reautorise-ia-anthropic",           # 3 sources seulement (limite du seuil à 5)
    "accident-jean-pierre-raffarin-paris",          # avait planté en JSON précédemment
    "mousses-champignons-symbiose-inattendue",      # neutre, science
    "knds-reporte-entree-bourse-volatilite-marche", # neutre, économie
    "spiruline-super-aliment-nutritionnel",         # neutre, santé
]

ROOT = Path(__file__).parent.parent


def load_article(slug):
    path = ROOT / "articles" / f"{slug}.html"
    html = path.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "lxml")
    titre = soup.select_one("h1.art__title").get_text(strip=True)
    cat_el = soup.select_one("span.art__cat")
    cat = cat_el.get_text(strip=True).lower() if cat_el else ""
    resume_el = soup.select_one("p.art__resume")
    resume = resume_el.get_text(strip=True) if resume_el else ""
    sections = {}
    for h2 in soup.select("h2.art__h2"):
        label = h2.get_text(strip=True)
        p = h2.find_next_sibling("p")
        key = {"Les faits": "faits", "Contexte": "contexte", "Débats et nuances": "nuances"}.get(label)
        if key and p:
            sections[key] = p.get_text(strip=True)
    sources = []
    for li in soup.select(".sources li"):
        inst_el = li.find("strong") or li.find("cite")
        inst = inst_el.get_text(strip=True) if inst_el else ""
        titre_src_el = li.find("em")
        titre_src = titre_src_el.get_text(strip=True) if titre_src_el else ""
        a = li.find("a")
        url = a["href"] if a else ""
        sources.append({"institution": inst, "titre": titre_src, "url": url})
    return {
        "slug": slug, "titre": titre, "categorie": cat, "resume": resume,
        "corps": sections, "sources": sources, "nb_sources": len(sources),
    }


def wc(txt):
    return len((txt or "").split())


print(f"Clé Anthropic présente : {bool(ANTHROPIC_KEY)}", flush=True)
print(f"Plafond d'appels API : {MAX_APPELS} (~{MAX_APPELS * 0.05:.2f} $ estimé)", flush=True)

resultats = []
for slug in SLUGS:
    if _appels_effectues >= MAX_APPELS:
        print(f"\n[BUDGET ATTEINT] arrêt avant {slug} — {_appels_effectues} appels consommés", flush=True)
        break

    try:
        art = load_article(slug)
    except Exception as e:
        print(f"[ERREUR CHARGEMENT] {slug} : {e}", flush=True)
        continue

    print("\n" + "=" * 100, flush=True)
    print(f">>> {slug} ({art['nb_sources']} sources, catégorie {art['categorie']})", flush=True)
    print("=" * 100, flush=True)

    avant = {k: wc(art["corps"].get(k, "")) for k in ("faits", "contexte", "nuances")}

    art_final, statut = verifier_article(art)

    apres = {k: wc(art_final["corps"].get(k, "")) for k in ("faits", "contexte", "nuances")}

    print(f"\nSTATUT : {statut}", flush=True)
    print(f"Mots avant/après : faits {avant['faits']}→{apres['faits']} | "
          f"contexte {avant['contexte']}→{apres['contexte']} | "
          f"nuances {avant['nuances']}→{apres['nuances']}", flush=True)

    resultats.append({"slug": slug, "statut": statut, "avant": avant, "apres": apres})

    if _budget_atteint:
        print(f"\n[BUDGET ATTEINT] arrêt propre après {slug} — {_appels_effectues}/{MAX_APPELS} appels", flush=True)
        break

print("\n" + "=" * 100, flush=True)
print("RÉSUMÉ", flush=True)
print("=" * 100, flush=True)
from collections import Counter
c = Counter(r["statut"] for r in resultats)
for statut, n in c.most_common():
    print(f"  {statut} : {n}/{len(resultats)}", flush=True)
print(f"\nAppels API consommés (approx) : {_appels_effectues}", flush=True)

print("\nDÉTAIL PAR ARTICLE :", flush=True)
for r in resultats:
    print(f"  {r['slug']:50s} -> {r['statut']}", flush=True)
