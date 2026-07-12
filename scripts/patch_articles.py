"""Patche les articles HTML existants avec les nouvelles fonctionnalités."""
import json, os, re, sys

sys.path.insert(0, os.path.dirname(__file__))
from pipeline import AUDIO_PLAYER_HTML

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
    # 1 article par catégorie différente, puis compléter par même catégorie
    other_cats = [a for a in all_arts if a.get("categorie") != cat and a["slug"] != slug]
    same_cat   = [a for a in all_arts if a.get("categorie") == cat  and a["slug"] != slug]
    seen_cats: set = set()
    related: list = []
    for a in other_cats:
        if a["categorie"] not in seen_cats:
            related.append(a)
            seen_cats.add(a["categorie"])
        if len(related) == 3:
            break
    if len(related) < 3:
        related += same_cat[:3 - len(related)]
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
    # Remplacement robuste : comptage des divs imbriqués pour trouver la fin du bloc
    marker = '<div class="art__related">'
    start = html.find(marker)
    if start < 0:
        continue
    depth, i = 0, start
    end = -1
    while i < len(html):
        if html[i:i+4] == '<div':
            depth += 1
            i += 4
        elif html[i:i+6] == '</div>':
            depth -= 1
            if depth == 0:
                end = i + 6
                break
            i += 6
        else:
            i += 1
    if end < 0:
        continue
    new_html = html[:start] + new_block + html[end:]
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

    # 5. Mettre à jour le bloc newsletter (supprimer l'ancien, réinjecter le nouveau)
    html_before = html
    html = re.sub(r'<div class="newsletter-block">.*?</div>\s*\n?', '', html, flags=re.DOTALL)
    if html != html_before:
        changed = True

    # 5b. Injecter le bloc newsletter unifié (avant art__related ou avant </main>)
    NL_BLOCK = (
        '<div class="newsletter-block">'
        '<div>'
        '<div class="newsletter-block__label">NEWSLETTER</div>'
        '<div class="newsletter-block__text">'
        '<strong>Le résumé du jour dans votre boîte mail</strong>'
        '<span>Chaque soir, les articles du jour en un email. Gratuit. Sans pub.</span>'
        '</div>'
        '</div>'
        '<a class="newsletter-block__btn" href="index.html#newsletter">S\'abonner →</a>'
        '</div>\n'
    )
    if 'newsletter-block' not in html:
        if '<div class="art__related">' in html:
            html = html.replace('<div class="art__related">', NL_BLOCK + '<div class="art__related">', 1)
        else:
            html = html.replace('</main>', NL_BLOCK + '</main>', 1)
        changed = True

    # 6. Back-to-top avant </body>
    if 'back-to-top' not in html:
        html = html.replace('</body>', BTT + '\n</body>', 1)
        changed = True

    # 7. Lien "Favoris" dans la nav (ajouté après coup — absent des articles
    # déjà publiés avant l'introduction de favoris.html)
    if 'favoris.html' not in html:
        html, n1 = re.subn(
            r'(<a href="archive\.html">Tous les articles</a>)',
            r'<a href="favoris.html">Favoris</a>\n\1',
            html
        )
        if n1:
            changed = True

    # 8. Retirer les cœurs ♡/♥ du bouton favori (redondant avec le libellé)
    if '♡ Favoris' in html or '♥ Favori' in html:
        html = html.replace('♡ Favoris', 'Favoris').replace('♥ Favori', 'Favori')
        changed = True

    # 9. Badge de divulgation IA visible (AI Act art. 50) — le badge existant
    # en pied de page (9px, couleur atténuée) ne suffit pas : la réglementation
    # exclut explicitement les mentions cachées/noyées. Ajout d'un badge visible
    # juste sous le méta (date/lecture), en haut de l'article.
    if 'art__ai-badge' not in html:
        html, n2 = re.subn(
            r'(<span class="art__reading-time">Lecture[^<]*</span>\s*</div>)',
            r'\1\n  <div class="art__ai-badge" role="note">🤖 Contenu rédigé par intelligence artificielle — <a href="methode.html" style="color:inherit;text-decoration:underline">notre méthode</a></div>',
            html
        )
        if n2:
            changed = True

    # 10. Lecteur audio (synthèse vocale) — injecté après le bandeau IA, comme
    # dans le template de génération. AUDIO_PLAYER_HTML est importé depuis
    # pipeline.py pour ne jamais diverger du gabarit des nouveaux articles.
    # Insertion par recherche de chaîne simple (pas de re.sub : le lecteur
    # contient des backslashes JS que re.sub interpréterait comme des
    # références de groupe invalides).
    if 'id="audio-player"' not in html:
        badge_start = html.find('<div class="art__ai-badge"')
        if badge_start != -1:
            badge_end = html.find('</div>', badge_start)
            if badge_end != -1:
                insert_at = badge_end + len('</div>')
                html = html[:insert_at] + '\n  ' + AUDIO_PLAYER_HTML + html[insert_at:]
                changed = True

    if changed:
        open(path, "w", encoding="utf-8").write(html)
        patched2 += 1

print(f"{patched2} articles patchés (URLs, disclaimer, newsletter, back-to-top, couleurs)")
