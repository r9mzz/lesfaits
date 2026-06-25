"""Add missing burger nav-mobile block to static HTML pages."""
import re
from pathlib import Path

ROOT = Path(r'C:\Users\romeo\Downloads\factuel')

BURGER_BLOCK = '''\
<div class="nav-overlay" id="nav-overlay" onclick="closeMenu()"></div>
<nav class="nav-mobile" id="nav-mobile">
<a href="categories/societe.html">Société</a>
<a href="categories/science.html">Science</a>
<a href="categories/economie.html">Économie</a>
<a href="categories/tech.html">Tech</a>
<a href="categories/sante.html">Santé</a>
<a href="categories/environnement.html">Environnement</a>
<a href="methode.html" class="nav-cta">Comment on travaille →</a>
</nav>
<script>
function toggleMenu(){var b=document.getElementById('burger'),m=document.getElementById('nav-mobile'),o=document.getElementById('nav-overlay');b.classList.toggle('open');m.classList.toggle('open');o.classList.toggle('open');}
function closeMenu(){document.getElementById('burger').classList.remove('open');document.getElementById('nav-mobile').classList.remove('open');document.getElementById('nav-overlay').classList.remove('open');}
</script>
'''

PAGES = ['methode.html', 'contact.html', 'corrections.html', 'recherche.html']

for name in PAGES:
    path = ROOT / name
    html = path.read_text(encoding='utf-8')

    if 'nav-mobile' in html:
        print(f'  SKIP {name} (already has nav-mobile)')
        continue

    # Ensure there's a burger button; if not, add before </div></header>
    has_burger_btn = 'id="burger"' in html

    # Insert BURGER_BLOCK after <body> tag (first occurrence)
    new_html = re.sub(r'(<body[^>]*>)', r'\1\n' + BURGER_BLOCK, html, count=1)

    if not has_burger_btn:
        # Add burger button before </div>\n</header>
        new_html = new_html.replace(
            '</nav>\n  </div>\n</header>',
            '</nav>\n    <button class="burger" id="burger" aria-label="Menu" onclick="toggleMenu()"><span></span><span></span><span></span></button>\n  </div>\n</header>',
            1
        )

    path.write_text(new_html, encoding='utf-8')
    print(f'  FIXED {name}')
