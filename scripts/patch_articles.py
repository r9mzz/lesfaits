"""Patche les articles HTML existants avec les nouvelles fonctionnalités."""
import json, os, re

BASE_URL = "https://r9mzz.github.io/lesfaits-site"
OLD_BASE = "https://r9mzz.github.io/lesfaits"   # ancienne URL (sans -site)

with open("data/search.json", encoding="utf-8") as f:
    all_arts = json.load(f)
arts_by_slug = {a["slug"]: a for a in all_arts}

# ── À lire aussi ───────────────────────────────────────────────────────────────
patched_related = 0
for fn in os.listdir("articles"):
    if not fn.endswith(".html"):
        continue
    slug = fn[:-5]
    art = arts_by_slug.get(slug)
    if not art:
        continue
    cat = art.get("categorie", "")
    related = [a for a in all_arts if a.get("categorie") == cat and a["slug"] != slug][:3]
    if not related:
        continue

    cards = "\n".join(
        # width/height explicites pour que lazy-loading se déclenche correctement
        f'<a class="art__related-card" href="articles/{a["slug"]}.html">'
        f'<img src="assets/images/{a["slug"]}.jpg" alt="" width="400" height="110" loading="lazy" style="width:calc(100% + 32px);margin:-14px -16px 12px;height:110px;object-fit:cover;display:block;border-radius:var(--radius) var(--radius) 0 0">'
        f'<span class="cat cat--{a["categorie"]}">{a["categorie"].upper()}</span>'
        f'<div class="title-sm">{a["titre"]}</div>'
        f'<div style="font-size:10px;color:var(--muted);margin-top:6px">{a["date"]}</div>'
        f'</a>'
        for a in related
    )
    new_block = (
        f'<div class="art__related">'
        f'<div class="art__related-title">À LIRE AUSSI</div>'
        f'<div class="art__related-grid">{cards}</div>'
        f'</div>'
    )
    path = f"articles/{fn}"
    html = open(path, encoding="utf-8").read()
    new_html = re.sub(r'<div class="art__related">.*?</div></div>', new_block, html, flags=re.DOTALL)
    if new_html != html:
        open(path, "w", encoding="utf-8").write(new_html)
        patched_related += 1

print(f"{patched_related} articles patchés (à lire aussi)")

# ── Corrections générales sur chaque article ────────────────────────────────────
BTT = (
    '<button class="back-to-top" id="btt" aria-label="Retour en haut" title="Retour en haut">↑</button>\n'
    '<script>\n'
    '(function(){\n'
    '  var btn=document.getElementById("btt");\n'
    '  window.addEventListener("scroll",function(){btn.classList.toggle("visible",window.scrollY>300);},{passive:true});\n'
    '  btn.addEventListener("click",function(){window.scrollTo({top:0,behavior:"smooth"});});\n'
    '})();\n'
    '</script>'
)

patched2 = 0
for fn in os.listdir("articles"):
    if not fn.endswith(".html"):
        continue
    slug = fn[:-5]
    art = arts_by_slug.get(slug, {})
    cat = art.get("categorie", "")
    path = f"articles/{fn}"
    html = open(path, encoding="utf-8").read()
    changed = False

    # 1. Corriger les anciennes URLs /lesfaits/ → /lesfaits-site/
    if OLD_BASE in html:
        html = html.replace(OLD_BASE, BASE_URL)
        changed = True

    # 2. Couleurs catégorie sur les spans .cat sans classe couleur
    if cat and f'cat--{cat}' not in html:
        html = html.replace(
            f'<span class="cat">{cat.upper()}</span>',
            f'<span class="cat cat--{cat}">{cat.upper()}</span>'
        )
        changed = True

    # 3. Supprimer l'ancien disclaimer mal placé (avant art__resume)
    old_disclaimer_pattern = re.compile(
        r'<div class="art__disclaimer">.*?</div>\s*\n?\s*<p class="art__resume">',
        re.DOTALL
    )
    if old_disclaimer_pattern.search(html):
        html = old_disclaimer_pattern.sub('<p class="art__resume">', html)
        changed = True

    # 4. Badge "Généré par IA"
    if '<p class="art__badge">Rédigé par IA ·' in html:
        html = html.replace(
            '<p class="art__badge">Rédigé par IA ·',
            '<p class="art__badge">Généré par IA ·'
        )
        changed = True

    # 5. Supprimer les blocs newsletter
    html_before = html
    html = re.sub(r'<div class="newsletter-block">.*?</div>\s*\n?\s*', '', html, flags=re.DOTALL)
    if html != html_before:
        changed = True

    # 6. Back-to-top avant </body>
    if 'back-to-top' not in html:
        html = html.replace('</body>', BTT + '\n</body>', 1)
        changed = True

    if changed:
        open(path, "w", encoding="utf-8").write(html)
        patched2 += 1

print(f"{patched2} articles patchés (URLs, disclaimer, newsletter, back-to-top, couleurs)")
