"""Patche les articles HTML existants : dark mode, temps de lecture, nouveau footer."""
import re, json
from pathlib import Path

ROOT    = Path(__file__).parent.parent
ARTICLES = ROOT / "articles"

with open(ROOT / "data" / "articles.json", encoding="utf-8") as f:
    index = {a["slug"]: a for a in json.load(f)}

DARK_INIT = '<script>\n(function(){var s=localStorage.getItem(\'theme\'),d=s===\'dark\'||(s===null&&window.matchMedia(\'(prefers-color-scheme:dark)\').matches);document.documentElement.setAttribute(\'data-theme\',d?\'dark\':\'light\');})();\n</script>'

DARK_TOGGLE = '<button class="dark-toggle" id="dark-toggle" aria-label="Mode sombre" title="Mode sombre">\U0001f319</button>'

DARK_BTN_JS = """<script>
(function(){
  var btn=document.getElementById('dark-toggle');
  var dark=document.documentElement.getAttribute('data-theme')==='dark';
  if(btn) btn.textContent=dark?'☀️':'\U0001f319';
  if(btn) btn.addEventListener('click',function(){
    var d=document.documentElement.getAttribute('data-theme')==='dark';
    document.documentElement.setAttribute('data-theme',d?'light':'dark');
    localStorage.setItem('theme',d?'light':'dark');
    btn.textContent=d?'\U0001f319':'☀️';
  });
})();
</script>"""

NEW_FOOTER = """<footer class="footer" role="contentinfo" aria-label="Pied de page">
  <div class="footer__inner">
    <div class="footer__brand">
      <div class="brand__logotype"><span class="fact">les</span><span class="uel">faits</span></div>
      <p>Journal numérique français rédigé par IA. Sans publicité. Sans actionnaires.</p>
      <p style="font-size:10px;color:var(--muted);margin-top:8px">Aucune publicité · Aucun actionnaire · Aucun cookie de tracking</p>
    </div>
    <div class="footer__col"><h4>RUBRIQUES</h4>
      <a href="categories/societe.html">Société</a>
      <a href="categories/science.html">Science</a>
      <a href="categories/economie.html">Économie</a>
      <a href="categories/tech.html">Tech</a>
      <a href="categories/sante.html">Santé</a>
      <a href="categories/environnement.html">Environnement</a>
    </div>
    <div class="footer__col"><h4>JOURNAL</h4>
      <a href="methode.html">Comment on travaille</a>
      <a href="corrections.html">Corrections publiques</a>
      <a href="archive.html">Tous les articles</a>
      <a href="feed.xml" class="footer__rss">Flux RSS</a>
    </div>
    <div class="footer__col"><h4>LÉGAL</h4>
      <a href="mentions-legales.html">Mentions légales</a>
      <a href="confidentialite.html">Confidentialité</a>
      <a href="cgu.html">CGU</a>
    </div>
    <div class="footer__col"><h4>CONTACT</h4>
      <a href="contact.html">Nous écrire</a>
      <a href="contact.html#erreur">Signaler une erreur</a>
    </div>
  </div>
  <div class="footer__bottom">
    <span>© 2026 Les Faits · <a href="https://creativecommons.org/licenses/by-nc-nd/4.0/deed.fr" rel="noopener noreferrer external" target="_blank" style="color:inherit">CC BY-NC-ND 4.0</a></span>
    <span>Protocole éditorial v1.1</span>
  </div>
</footer>"""

ok = 0
for html_path in sorted(ARTICLES.glob("*.html")):
    slug = html_path.stem
    html = html_path.read_text(encoding="utf-8")
    orig = html

    # 1. <html> → data-theme=""
    html = re.sub(r'<html([^>]*?)(?:\s+data-theme="[^"]*")?>', r'<html\1 data-theme="">', html, count=1)

    # 2. Injecter init dark dans <head> (avant </head>)
    if "localStorage.getItem('theme')" not in html:
        html = html.replace("</head>", DARK_INIT + "\n</head>", 1)

    # 3. Ajouter dark toggle dans header (avant BURGER_BTN ou en fin de header__inner)
    if 'dark-toggle' not in html:
        # Insérer avant le bouton burger
        html = re.sub(
            r'(<button class="burger")',
            DARK_TOGGLE + '\n    ' + r'\1',
            html, count=1
        )

    # 4. Ajouter temps de lecture dans art__meta si absent
    if 'reading-time' not in html and 'art__meta' in html:
        # Compter les mots dans le texte de l'article (hors balises)
        body_text = re.sub(r'<[^>]+>', ' ', html)
        # Extraire la zone entre les h2 principaux
        art_body = re.search(r'Les faits</h2>(.*?)<p class="art__badge"', body_text, re.DOTALL)
        word_count = len((art_body.group(1) if art_body else body_text).split())
        reading_time = max(1, round(word_count / 200))
        # Ajouter après la date
        html = re.sub(
            r'(<span class="meta__sep"[^>]*>·</span>\s*<span>Protocole v1\.1</span>)',
            f'<span class="meta__sep" aria-hidden="true">·</span><span class="art__reading-time">Lecture\xa0: {reading_time}\xa0min</span>',
            html, count=1
        )

    # 5. Remplacer footer
    html = re.sub(r'<footer class="footer".*?</footer>', NEW_FOOTER, html, flags=re.DOTALL, count=1)

    # 6. Injecter JS dark mode complet avant </body>
    if 'btn.addEventListener' not in html:
        html = html.replace("</body>", DARK_BTN_JS + "\n</body>", 1)

    if html != orig:
        html_path.write_text(html, encoding="utf-8")
        ok += 1
        print(f"  ✓ {slug}")
    else:
        print(f"  = {slug} (inchangé)")

print(f"\n{ok} articles mis à jour.")
