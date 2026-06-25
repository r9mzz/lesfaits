"""Audit complet : nb_sources, liens sources, burger menu, categorie."""
import json, re
from pathlib import Path

ROOT = Path(r'C:\Users\romeo\Downloads\factuel')
ART_DIR = ROOT / 'articles'

with open(ROOT / 'data' / 'articles.json', encoding='utf-8') as f:
    articles = json.load(f)

problems = []

for a in articles:
    slug = a['slug']
    html_path = ART_DIR / f'{slug}.html'
    if not html_path.exists():
        problems.append((slug, 'MISSING HTML'))
        continue

    html = html_path.read_text(encoding='utf-8')

    # 1. Categorie vide
    if not a.get('categorie'):
        problems.append((slug, f'categorie vide'))

    # 2. Burger menu
    if 'nav-mobile' not in html:
        problems.append((slug, 'burger menu manquant'))

    # 3. Compter les vrais liens sources dans <ol>
    sources_block = re.search(r'<div class="sources">.*?</div>', html, re.DOTALL)
    real_links = len(re.findall(r'<li>', sources_block.group())) if sources_block else 0

    # 4. nb_sources concordance
    stated = a.get('nb_sources', 0)
    if real_links != stated:
        problems.append((slug, f'nb_sources: articles.json={stated} mais {real_links} <li> dans HTML'))

    # 5. Articles avec 0 lien "Lire la source"
    lire_source_count = html.count('Lire la source')
    if lire_source_count == 0:
        problems.append((slug, 'aucun lien "Lire la source"'))
    elif lire_source_count < real_links:
        problems.append((slug, f'seulement {lire_source_count}/{real_links} sources ont un lien cliquable'))

    # 6. Image manquante
    img = ROOT / 'assets' / 'images' / f'{slug}.jpg'
    if not img.exists():
        problems.append((slug, 'image manquante'))

    # 7. Image trop petite (picsum fallback ~50KB)
    elif img.stat().st_size < 40_000:
        problems.append((slug, f'image suspecte ({img.stat().st_size//1024}KB — probablement picsum)'))

print(f"=== AUDIT — {len(articles)} articles ===\n")
if not problems:
    print("Aucun problème détecté.")
else:
    for slug, msg in problems:
        print(f"  [{slug[:42]}] {msg}")

print(f"\n{len(problems)} problème(s) trouvé(s).")
