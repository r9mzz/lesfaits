import json

cats = {
    'secheresse-estivale-france-changement-climatique': 'environnement',
    'sante-environnementale-impact-humain': 'sante',
    'nasa-lance-mission-sauvetage-telescope-swift': 'science',
    'controle-aerien-france-en-crise': 'societe',
    'canicule-sante-publique-france': 'sante',
    'theorie-evolution-darwin': 'science',
    'emissions-co2-france-recul-2023': 'environnement',
    'loi-contre-ultrafast-fashion-adoptee': 'environnement',
    'subvention-ars-planning-familial-gironde-2026': 'sante',
    'sante-environnementale-defis-savoirs': 'sante',
    'ia-dans-la-sante': 'sante',
}

with open(r'C:\Users\romeo\Downloads\factuel\data\articles.json', encoding='utf-8') as f:
    articles = json.load(f)

for a in articles:
    slug = a['slug']
    if not a.get('categorie') and slug in cats:
        a['categorie'] = cats[slug]
        print(f"  {slug} -> {a['categorie']}")

with open(r'C:\Users\romeo\Downloads\factuel\data\articles.json', 'w', encoding='utf-8') as f:
    json.dump(articles, f, ensure_ascii=False, indent=2)

print('Done.')
