"""Test final : appelle verifier_article() (multi-tentatives) sur 2 articles
et affiche le résultat concret — statut + texte corrigé final, pas juste des
statistiques. SANS réécrire les fichiers publiés."""
import sys
from pathlib import Path
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent))
from verification import verifier_article, ANTHROPIC_KEY

SLUGS = [
    "violences-enfants-france-insuffisante",
    "redmi-15-5g-smartphone-abordable",
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
        inst = li.find("strong").get_text(strip=True) if li.find("strong") else ""
        titre_src = li.find("em").get_text(strip=True) if li.find("em") else ""
        a = li.find("a")
        url = a["href"] if a else ""
        sources.append({"institution": inst, "titre": titre_src, "url": url})
    return {
        "slug": slug, "titre": titre, "categorie": cat, "resume": resume,
        "corps": sections, "sources": sources, "nb_sources": len(sources),
    }


print(f"Clé Anthropic présente : {bool(ANTHROPIC_KEY)}", flush=True)

for slug in SLUGS:
    art = load_article(slug)
    print("\n" + "=" * 100, flush=True)
    print(f">>> {slug}", flush=True)
    print("=" * 100, flush=True)
    art_final, statut = verifier_article(art)
    print(f"\nSTATUT FINAL : {statut}", flush=True)
    print(f"\n--- RÉSUMÉ ---\n{art_final.get('resume','')}", flush=True)
    for section in ("faits", "contexte", "nuances"):
        print(f"\n--- {section.upper()} ---\n{art_final['corps'].get(section,'')}", flush=True)
    print(f"\nnb_sources final : {art_final.get('nb_sources')}", flush=True)
