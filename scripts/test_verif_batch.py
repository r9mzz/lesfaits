"""Test batch : fait passer un échantillon d'articles publiés dans
verifier_article() (passes 2+3 Anthropic) et affiche la distribution des
statuts, SANS réécrire aucun fichier. Échantillon choisi pour stresser :
doublon/quasi-doublon, candidats bloc 5 (légal), et cas neutres (faux positifs)."""
import sys
from pathlib import Path
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent))
from verification import verifier_article, ANTHROPIC_KEY

SLUGS = [
    "sante-environnementale-impact-humain",
    "sante-environnementale-defis-savoirs",
    "adn-revolutionne-enquetes-criminelles",
    "violences-enfants-france-insuffisante",
    "accident-jean-pierre-raffarin-paris",
    "mousses-champignons-symbiose-inattendue",
    "redmi-15-5g-smartphone-abordable",
    "knds-reporte-entree-bourse-volatilite-marche",
    "spiruline-super-aliment-nutritionnel",
    "le-coucou-un-oiseau-strategique",
    "canicule-france-hausse-deces-morts-animaux",
    "canicule-sante-publique-france",
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


print(f"Clé Anthropic présente : {bool(ANTHROPIC_KEY)}")
print(f"Échantillon : {len(SLUGS)} articles")
print("=" * 100)

resultats = []
for slug in SLUGS:
    try:
        art = load_article(slug)
    except Exception as e:
        print(f"[ERREUR CHARGEMENT] {slug} : {e}")
        continue
    print(f"\n>>> {slug}")
    art_final, statut = verifier_article(art)
    resultats.append((slug, statut))
    print(f"    STATUT : {statut}")

print("\n" + "=" * 100)
print("RÉPARTITION DES STATUTS")
print("=" * 100)
from collections import Counter
c = Counter(s for _, s in resultats)
for statut, n in c.most_common():
    print(f"  {statut} : {n}/{len(resultats)}")

print("\nDÉTAIL PAR ARTICLE :")
for slug, statut in resultats:
    print(f"  {slug:55s} -> {statut}")
