"""Fix bad image keywords and re-download affected images."""
import json
import os
from pathlib import Path

ROOT = Path(r'C:\Users\romeo\Downloads\factuel')

# Better English keywords — specific, visual, geographically relevant
KEYWORD_FIXES = {
    'ia-dans-la-sante':
        'medical AI diagnostic computer hospital',
    'loi-contre-ultrafast-fashion-adoptee':
        'textile waste fashion clothing pile',
    'sante-environnementale-impact-humain':
        'air pollution city smog factory',
    'sante-environnementale-defis-savoirs':
        'laboratory scientist environment research',
    'subvention-ars-planning-familial-gironde-2026':
        'health center clinic France building',
    'premier-cas-ebola-france':
        'hospital isolation ward protective suit',
    'canicule-sante-publique-france':
        'heatwave sun thermometer France city',
    'emissions-co2-france-recul-2023':
        'industrial chimney smoke carbon emissions Europe',
    'controle-aerien-france-en-crise':
        'air traffic control tower airport radar',
    'secheresse-estivale-france-changement-climatique':
        'drought cracked earth dry river France',
    'chantal-delsol-droite-antimoderne':
        'french parliament assembly nationale paris',
}

IMAGES_DIR = ROOT / 'assets' / 'images'

with open(ROOT / 'data' / 'articles.json', encoding='utf-8') as f:
    articles = json.load(f)

to_redownload = []
for a in articles:
    slug = a['slug']
    if slug in KEYWORD_FIXES:
        old = a.get('image_keyword', '')
        new = KEYWORD_FIXES[slug]
        a['image_keyword'] = new
        print(f"  keyword: {slug[:40]}")
        print(f"    {old!r} -> {new!r}")
        # Delete old image so it gets re-downloaded
        img_path = IMAGES_DIR / f"{slug}.jpg"
        if img_path.exists():
            img_path.unlink()
            print(f"    deleted {img_path.name}")
        to_redownload.append(slug)

with open(ROOT / 'data' / 'articles.json', 'w', encoding='utf-8') as f:
    json.dump(articles, f, ensure_ascii=False, indent=2)

print(f"\nDone. {len(to_redownload)} images to re-download.")
print("Run: python scripts/pipeline.py --rebuild  (will re-download missing images)")
