"""Test ponctuel : fait passer un article déjà publié dans verifier_article()
(passes 2+3 Anthropic) et affiche le rapport, SANS réécrire le fichier."""
import re, json, sys
from pathlib import Path
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent))
from verification import verifier_article, ANTHROPIC_KEY

SLUG = "agriculture-defis-climatiques-extremes"
ROOT = Path(__file__).parent.parent
path = ROOT / "articles" / f"{SLUG}.html"
html = path.read_text(encoding="utf-8")
soup = BeautifulSoup(html, "lxml")

titre = soup.select_one("h1.art__title").get_text(strip=True)
cat = soup.select_one("span.art__cat").get_text(strip=True).lower()
resume = soup.select_one("p.art__resume").get_text(strip=True)

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

art = {
    "slug": SLUG,
    "titre": titre,
    "categorie": cat,
    "resume": resume,
    "corps": sections,
    "sources": sources,
    "nb_sources": len(sources),
}

print(f"Clé Anthropic présente : {bool(ANTHROPIC_KEY)}")
print(f"Article chargé : {titre!r} — {len(sources)} sources, sections: {list(sections.keys())}")
print("=" * 80)

art_final, statut = verifier_article(art)

print("STATUT:", statut)
print("=" * 80)
if statut in ("corrige_automatiquement", "a_corriger_manuellement"):
    print("--- AVANT (faits) ---")
    print(art["corps"].get("faits", ""))
    print("--- APRÈS (faits) ---")
    print(art_final["corps"].get("faits", ""))
    print("--- AVANT (contexte) ---")
    print(art["corps"].get("contexte", ""))
    print("--- APRÈS (contexte) ---")
    print(art_final["corps"].get("contexte", ""))
    print("--- AVANT (nuances) ---")
    print(art["corps"].get("nuances", ""))
    print("--- APRÈS (nuances) ---")
    print(art_final["corps"].get("nuances", ""))
