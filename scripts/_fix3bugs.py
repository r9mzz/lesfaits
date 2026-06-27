"""
Corrige 3 bugs sur tous les articles :
1. Liens "À lire aussi" : href="SLUG.html" → href="articles/SLUG.html"
2. Dark mode JS init : supprime prefers-color-scheme fallback (→ défaut light)
3. Spectrum : supprime TOUS les blocs spectrum (divs imbriqués)
"""
import re
from pathlib import Path

ARTICLES = list(Path("articles").glob("*.html"))

OLD_DARK = "(function(){var s=localStorage.getItem('theme'),d=s==='dark'||(s===null&&window.matchMedia('(prefers-color-scheme:dark)').matches);document.documentElement.setAttribute('data-theme',d?'dark':'light');})();"
NEW_DARK = "(function(){var s=localStorage.getItem('theme');document.documentElement.setAttribute('data-theme',s==='dark'?'dark':'light');})();"


def remove_spectrum(html):
    """Supprime tous les blocs <div class="spectrum">...</div> avec divs imbriqués."""
    result = []
    i = 0
    while i < len(html):
        # Cherche le début d'un bloc spectrum
        idx = html.find('<div class="spectrum">', i)
        if idx == -1:
            result.append(html[i:])
            break
        # Ajoute tout ce qui précède
        result.append(html[i:idx])
        # Compte les divs imbriqués pour trouver la fermeture correcte
        depth = 0
        j = idx
        while j < len(html):
            open_tag = html.find('<div', j)
            close_tag = html.find('</div>', j)
            if open_tag == -1 and close_tag == -1:
                j = len(html)
                break
            if open_tag != -1 and (close_tag == -1 or open_tag < close_tag):
                depth += 1
                j = open_tag + 4
            else:
                depth -= 1
                j = close_tag + 6
                if depth == 0:
                    break
        # Saute aussi les espaces/newlines après le bloc
        while j < len(html) and html[j] in ' \t\n\r':
            j += 1
        i = j
    return "".join(result)


def fix_related_links(html):
    """Corrige les href dans les blocs À lire aussi : SLUG.html → articles/SLUG.html"""
    # Trouve le bloc art__related et corrige chaque href sans chemin
    def fix_href(m):
        href = m.group(1)
        if not href.startswith("articles/") and not href.startswith("../") and not href.startswith("http") and "/" not in href:
            return f'href="articles/{href}"'
        return f'href="{href}"'

    # Trouve tous les blocs art__related et corrige leurs hrefs
    def fix_related_block(m):
        block = m.group(0)
        block = re.sub(r'href="([^"]+\.html)"', fix_href, block)
        return block

    return re.sub(r'<div class="art__related">.*?</div>\s*</div>', fix_related_block, html, flags=re.DOTALL)


fixed = 0
for path in ARTICLES:
    html = path.read_text(encoding="utf-8")
    original = html

    # 1. Fix liens "À lire aussi"
    html = fix_related_links(html)

    # 2. Fix dark mode init
    html = html.replace(OLD_DARK, NEW_DARK)

    # 3. Supprimer tous les blocs spectrum
    html = remove_spectrum(html)

    if html != original:
        path.write_text(html, encoding="utf-8")
        fixed += 1
        print(f"  OK {path.name}")

print(f"\nTermine -- {fixed} articles modifies")
