"""Fix nb_sources in articles.json and HTML to match actual source links."""
import json, re
from pathlib import Path

ROOT = Path(r'C:\Users\romeo\Downloads\factuel')
ART_DIR = ROOT / 'articles'

with open(ROOT / 'data' / 'articles.json', encoding='utf-8') as f:
    articles = json.load(f)

changed_json = []
changed_html = []

for a in articles:
    slug = a['slug']
    html_path = ART_DIR / f'{slug}.html'
    if not html_path.exists():
        continue

    html = html_path.read_text(encoding='utf-8')

    # Count actual <li> items in the sources <ol>
    sources_block = re.search(r'<div class="sources">.*?</div>', html, re.DOTALL)
    if not sources_block:
        print(f'  SKIP {slug} (no sources block)')
        continue

    real_count = len(re.findall(r'<li>', sources_block.group()))

    stated = a.get('nb_sources', 0)
    if real_count == stated:
        continue

    print(f'  MISMATCH {slug}: articles.json={stated}, HTML links={real_count}')

    # Fix articles.json
    a['nb_sources'] = real_count
    changed_json.append(slug)

    # Fix HTML: replace all occurrences of "{stated} source" with "{real_count} source"
    old_html = html
    html = re.sub(
        rf'\b{stated}\s+sources?\s+vérifi',
        f'{real_count} sources vérifi',
        html
    )
    html = re.sub(
        rf'<span[^>]*>\s*{stated}\s+sources?\s*</span>',
        f'<span style="color:var(--blue);font-weight:600">{real_count} sources</span>',
        html
    )
    if html != old_html:
        html_path.write_text(html, encoding='utf-8')
        changed_html.append(slug)
        print(f'    -> fixed to {real_count}')

with open(ROOT / 'data' / 'articles.json', 'w', encoding='utf-8') as f:
    json.dump(articles, f, ensure_ascii=False, indent=2)

print(f'\nDone: {len(changed_json)} articles.json fixed, {len(changed_html)} HTML fixed.')
