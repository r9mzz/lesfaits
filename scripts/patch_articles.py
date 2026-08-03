"""Patche les articles HTML existants avec les nouvelles fonctionnalités."""
import json, os, re, sys

sys.path.insert(0, os.path.dirname(__file__))
from pipeline import AUDIO_PLAYER_HTML, AUDIO_GLOBAL_HTML, AUDIO_GLOBAL_VERSION, _slug_ascii

CURRENT_AUDIO_MARKER = f"<!-- LF_AUDIO_GLOBAL_START v{AUDIO_GLOBAL_VERSION} -->"


def upsert_audio_global(html: str) -> str | None:
    """Insère le moteur audio persistant après </footer>, ou remplace un bloc
    d'une version antérieure (délimité par les sentinelles LF_AUDIO_GLOBAL_*).
    Retourne le HTML modifié, ou None si la page est déjà à jour / sans footer.
    Le simple test « LFAudio présent » ne suffit pas : il laisserait pour
    toujours l'ancienne version du moteur dans les pages déjà patchées."""
    if CURRENT_AUDIO_MARKER in html:
        return None
    start = html.find("<!-- LF_AUDIO_GLOBAL_START")
    if start != -1:
        end_marker = "<!-- LF_AUDIO_GLOBAL_END -->"
        end = html.find(end_marker, start)
        if end != -1:
            return html[:start] + AUDIO_GLOBAL_HTML.strip() + html[end + len(end_marker):]
        return None  # sentinelle de fin absente : ne pas risquer une coupe aveugle
    if "LFAudio" in html:
        return None  # version pré-sentinelles sans repère fiable : laisser tel quel
    if "</footer>" not in html:
        return None
    footer_end = html.find("</footer>") + len("</footer>")
    return html[:footer_end] + AUDIO_GLOBAL_HTML + html[footer_end:]

BASE_URL = "https://r9mzz.github.io/lesfaits-site"
OLD_BASE = "https://r9mzz.github.io/lesfaits"   # ancienne URL (sans -site)

with open("data/search.json", encoding="utf-8") as f:
    all_arts = json.load(f)
arts_by_slug = {a["slug"]: a for a in all_arts}

# ── Bloc de bas d'article (EN BREF / À lire aussi) ────────────────────────────
# SUPPRIMÉ le 03/08 — ce script en contenait une TROISIÈME copie, après celles
# de `build_article_html` et de `rebuild_articles_related`. Comme deploy.yml
# lance `pipeline.py --rebuild` PUIS ce script, la copie d'ici écrasait le
# travail du rebuild : les 143 articles repatchés en « EN BREF » repartaient
# en « À LIRE AUSSI » quelques secondes plus tard, et le site publiait
# l'ancien bloc alors que tous les logs affichaient le nouveau.
# La construction du bloc appartient à `pipeline.rebuild_articles_related`,
# appelée par `--rebuild`, et à elle seule. Ne pas la réintroduire ici.

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

    # 4b. Corriger les liens newsletter relatifs (anciens articles) → URL absolue
    if 'href="index.html#newsletter"' in html:
        html = html.replace('href="index.html#newsletter"', 'href="/#newsletter"')
        changed = True

    # 5. Mettre à jour le bloc newsletter (supprimer l'ancien, réinjecter le nouveau)
    #
    # BUG CORRIGÉ : l'ancienne regex `<div class="newsletter-block">.*?</div>`
    # (non-gourmande) s'arrête à la PREMIÈRE balise </div> rencontrée. Comme le
    # bloc a des <div> imbriqués (newsletter-block > div anonyme > label), elle
    # ne supprimait que "newsletter-block"><div><div class="newsletter-block__
    # label">NEWSLETTER</div>", laissant orphelins la suite (__text, le bouton,
    # et 2 </div> sans ouverture correspondante). Pire : la vérification de
    # réinjection ('newsletter-block' not in html) restait fausse à cause de
    # ces résidus (qui contiennent encore la sous-chaîne "newsletter-block"),
    # donc le bloc cassé n'était JAMAIS régénéré, même aux runs suivants.
    #
    # État avant nettoyage/réinjection, pour ne marquer 'changed' que si le
    # résultat final diffère vraiment (idempotence : un run sans rien à faire
    # ne doit ni réécrire le fichier, ni polluer le commit).
    html_nl_start = html

    # 1) Suppression d'un bloc newsletter-block ENTIER et bien formé (ancien ou
    #    actuel) : contrairement à art__related (contenu dynamique par article,
    #    nécessitant un comptage de profondeur), le newsletter-block est un
    #    gabarit STATIQUE identique sur tous les articles — une correspondance
    #    littérale exacte est donc fiable ET plus sûre qu'un comptage de
    #    profondeur, qui doit sinon scanner jusqu'à la fin du fichier et peut
    #    ne jamais retomber à 0 à cause d'un déséquilibre <div>/</div> sans
    #    rapport ailleurs dans la page (footer, autres composants).
    # ORDRE IMPORTANT : tenter CE retrait exact EN PREMIER, avant le nettoyage
    # de résidu ci-dessous — le motif du résidu (étape 2) est un SOUS-ENSEMBLE
    # littéral de ce bloc complet ; l'exécuter avant sur un bloc déjà sain le
    # mutilerait (reproduisant la troncature qu'on cherche justement à corriger).
    NL_BLOCK = (
        '<div class="newsletter-block">'
        '<div>'
        '<div class="newsletter-block__label">NEWSLETTER</div>'
        '<div class="newsletter-block__text">'
        '<strong>Le résumé du jour dans votre boîte mail</strong>'
        '<span>Chaque soir, les articles du jour en un email. Gratuit. Sans pub.</span>'
        '</div>'
        '</div>'
        '<a class="newsletter-block__btn" href="/#newsletter">S\'abonner →</a>'
        '</div>'
    )
    # Retirer avec ET sans le \n final : l'insertion (plus bas) ajoute le bloc
    # suivi d'un \n, donc une suppression qui ignore ce \n laisse une ligne
    # vide orpheline qui réapparaît/disparaît selon les runs (non-idempotent).
    html = html.replace(NL_BLOCK + '\n', '')
    html = html.replace(NL_BLOCK, '')
    # Retirer aussi l'ancienne version avec index.html#newsletter
    OLD_NL_BLOCK = NL_BLOCK.replace('href="/#newsletter"', 'href="index.html#newsletter"')
    html = html.replace(OLD_NL_BLOCK + '\n', '')
    html = html.replace(OLD_NL_BLOCK, '')
    NL_BLOCK += '\n'

    # 2) Nettoyage ciblé du résidu EXACT laissé par l'ancien bug (uniquement
    #    utile si l'étape 1 n'a rien trouvé à retirer, c.-à-d. un fichier
    #    encore tronqué depuis un run antérieur à ce correctif) :
    html = html.replace(
        '<div class="newsletter-block__text"><strong>Le résumé du jour dans '
        'votre boîte mail</strong><span>Chaque soir, les articles du jour en '
        'un email. Gratuit. Sans pub.</span></div></div>'
        '<a class="newsletter-block__btn" href="index.html#newsletter">S\'abonner →</a></div>',
        ''
    )
    # Toujours réinjecter un bloc frais et complet — le nettoyage ci-dessus
    # garantit qu'aucun résidu (correct ou tronqué) ne subsiste avant l'ajout.
    if '<div class="art__related">' in html:
        html = html.replace('<div class="art__related">', NL_BLOCK + '<div class="art__related">', 1)
    else:
        html = html.replace('</main>', NL_BLOCK + '</main>', 1)
    if html != html_nl_start:
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
    # dans le template de génération. AUDIO_PLAYER_HTML (markup local, sans
    # script) et AUDIO_GLOBAL_HTML (moteur persistant + navigation douce,
    # injecté une seule fois dans le pied de page) sont importés depuis
    # pipeline.py pour ne jamais diverger du gabarit des nouveaux articles.
    # Insertion par recherche de chaîne simple (pas de re.sub : le lecteur
    # contient des backslashes JS que re.sub interpréterait comme des
    # références de groupe invalides).
    if 'id="audio-play"' not in html:
        # Jamais eu de lecteur : insérer le markup local après le bandeau IA.
        badge_start = html.find('<div class="art__ai-badge"')
        if badge_start != -1:
            badge_end = html.find('</div>', badge_start)
            if badge_end != -1:
                insert_at = badge_end + len('</div>')
                html = html[:insert_at] + '\n  ' + AUDIO_PLAYER_HTML + html[insert_at:]
                changed = True
    elif 'LFAudio' not in html:
        # Ancienne architecture (script et/ou menu flottant encore embarqués
        # dans l'article) : remplacer par le markup allégé — le moteur de
        # lecture vit désormais dans le pied de page (persiste à la navigation).
        block_start = html.find('<div class="audio-player"')
        if block_start != -1:
            script_end = html.find('</script>', block_start)
            if script_end != -1:
                end = script_end + len('</script>')
                html = html[:block_start] + AUDIO_PLAYER_HTML + html[end:]
                changed = True

    html_new = upsert_audio_global(html)
    if html_new is not None:
        html = html_new
        changed = True

    if changed:
        open(path, "w", encoding="utf-8").write(html)
        patched2 += 1

print(f"{patched2} articles patchés (URLs, disclaimer, newsletter, back-to-top, couleurs)")

# ── Pages statiques racine : lecteur audio persistant + navigation douce ───────
# index.html, categories/*.html et archive.html sont régénérés à chaque
# --rebuild (via _build_footer(), qui embarque déjà AUDIO_GLOBAL_HTML) — mais
# les pages statiques suivantes sont maintenues à la main et ne passent jamais
# par le générateur. Sans ce patch, cliquer vers l'une d'elles pendant une
# lecture audio provoquerait un rechargement complet (donc une coupure) au
# lieu d'une navigation douce qui laisse le moteur persistant tourner.
STATIC_ROOT_PAGES = [
    "contact.html", "cgu.html", "confidentialite.html", "corrections.html",
    "favoris.html", "methode.html", "recherche.html", "a-propos.html",
    "mentions-legales.html",
]
patched_static = 0
for fn in STATIC_ROOT_PAGES:
    if not os.path.exists(fn):
        continue
    html = open(fn, encoding="utf-8").read()
    html_new = upsert_audio_global(html)
    if html_new is None:
        continue
    open(fn, "w", encoding="utf-8").write(html_new)
    patched_static += 1

print(f"{patched_static} page(s) statique(s) racine patchée(s) (lecteur audio persistant)")
