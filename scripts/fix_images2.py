"""Second pass: fix keywords that still produce bad/no images."""
import json, os
from pathlib import Path

ROOT = Path(r'C:\Users\romeo\Downloads\factuel')
IMAGES_DIR = ROOT / 'assets' / 'images'

# Keywords validated by Wikimedia test — short and concrete
KEYWORD_FIXES = {
    'secheresse-estivale-france-changement-climatique': 'cracked dry soil earth',
    'canicule-sante-publique-france':                   'heatwave hot summer street',
    'emissions-co2-france-recul-2023':                  'factory chimney smoke pollution',
    'loi-contre-ultrafast-fashion-adoptee':             'textile recycling clothing donation bins',
    'subvention-ars-planning-familial-gironde-2026':    'health clinic waiting room patients',
    'sante-environnementale-impact-humain':             'air pollution smog industrial city',
    'ia-dans-la-sante':                                 'digital health technology computer screen',
    'premier-cas-ebola-france':                         'hospital nurse gown protective equipment',
    'chantal-delsol-droite-antimoderne':                'palais bourbon assemblee nationale paris',
}

with open(ROOT / 'data' / 'articles.json', encoding='utf-8') as f:
    articles = json.load(f)

for a in articles:
    slug = a['slug']
    if slug in KEYWORD_FIXES:
        old = a.get('image_keyword', '')
        new = KEYWORD_FIXES[slug]
        if old != new:
            a['image_keyword'] = new
            print(f"  {slug[:42]}: {old!r} -> {new!r}")
            # Delete image to force re-download
            img = IMAGES_DIR / f"{slug}.jpg"
            if img.exists():
                img.unlink()
                print(f"    deleted {img.name}")

with open(ROOT / 'data' / 'articles.json', 'w', encoding='utf-8') as f:
    json.dump(articles, f, ensure_ascii=False, indent=2)

print('\nDone.')
