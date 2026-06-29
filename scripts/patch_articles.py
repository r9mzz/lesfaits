"""Patche les articles HTML existants avec les nouvelles fonctionnalités."""
import json, os, re

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
        f'<a class="art__related-card" href="articles/{a["slug"]}.html">'
        f'<img src="assets/images/{a["slug"]}.jpg" alt="" loading="lazy" style="width:calc(100% + 32px);margin:-14px -16px 12px;height:110px;object-fit:cover;display:block;border-radius:var(--radius) var(--radius) 0 0">'
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

# ── Disclaimer IA, newsletter, back-to-top, couleurs catégorie ─────────────────
NEWSLETTER = (
    '<div class="newsletter-block">'
    '<div class="newsletter-block__title">La semaine en faits</div>'
    '<div class="newsletter-block__sub">Chaque dimanche. Aucune opinion. Aucun parti pris.</div>'
    '<form class="newsletter-form" onsubmit="handleNL(event)">'
    '<input type="email" placeholder="votre@email.com" required autocomplete="email"/>'
    "<button type=\"submit\">S'abonner</button>"
    '</form>'
    '<div class="newsletter-block__legal">Aucune publicité. Désinscription en un clic.</div>'
    '</div>'
)

BTT = (
    '<button class="back-to-top" id="btt" aria-label="Retour en haut" title="Retour en haut">↑</button>\n'
    '<script>\n'
    '(function(){\n'
    '  var btn=document.getElementById("btt");\n'
    '  window.addEventListener("scroll",function(){btn.classList.toggle("visible",window.scrollY>300);},{passive:true});\n'
    '  btn.addEventListener("click",function(){window.scrollTo({top:0,behavior:"smooth"});});\n'
    '  function handleNL(e){e.preventDefault();e.target.innerHTML="<p style=\\"color:var(--blue);font-weight:600\\">✓ Merci ! Vous recevrez votre première newsletter dimanche.</p>";}\n'
    '  window.handleNL=handleNL;\n'
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

    # 1. Couleurs catégorie sur les spans .cat sans classe couleur
    if cat and f'cat--{cat}' not in html:
        html = html.replace(
            f'<span class="cat">{cat.upper()}</span>',
            f'<span class="cat cat--{cat}">{cat.upper()}</span>'
        )
        changed = True

    # 2. Disclaimer IA avant le résumé
    if 'art__disclaimer' not in html:
        disclaimer = (
            f'<div class="art__disclaimer">'
            f'ℹ️ Cet article a été rédigé par intelligence artificielle '
            f'selon le <a href="methode.html">Protocole Les Faits v1.1</a>. '
            f'Des erreurs peuvent subsister. '
            f'<a href="contact.html?article={slug}#erreur">Signaler une erreur →</a>'
            f'</div>'
        )
        html = html.replace('<p class="art__resume">', disclaimer + '\n  <p class="art__resume">', 1)
        changed = True

    # 3. Newsletter avant les articles liés
    if 'newsletter-block' not in html and '<div class="art__related">' in html:
        html = html.replace('<div class="art__related">', NEWSLETTER + '\n  <div class="art__related">', 1)
        changed = True

    # 4. Back-to-top avant </body>
    if 'back-to-top' not in html:
        html = html.replace('</body>', BTT + '\n</body>', 1)
        changed = True

    if changed:
        open(path, "w", encoding="utf-8").write(html)
        patched2 += 1

print(f"{patched2} articles patchés (disclaimer + newsletter + back-to-top + couleurs)")
