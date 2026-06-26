"""Patch les pages statiques : dark toggle dans le header, nouveau footer."""
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
PAGES = ["methode.html", "contact.html", "corrections.html", "recherche.html"]

DARK_TOGGLE = '<button class="dark-toggle" id="dark-toggle" aria-label="Mode sombre" title="Mode sombre">🌙</button>'

DARK_INIT_SCRIPT = """<script>
(function(){var s=localStorage.getItem('theme');var d=s==='dark'||(s===null&&window.matchMedia('(prefers-color-scheme:dark)').matches);document.documentElement.setAttribute('data-theme',d?'dark':'light');})();
</script>"""

DARK_FULL_SCRIPT = """<script>
(function(){
  var btn=document.getElementById('dark-toggle');
  var s=localStorage.getItem('theme');
  var dark=s==='dark'||(s===null&&window.matchMedia('(prefers-color-scheme:dark)').matches);
  document.documentElement.setAttribute('data-theme',dark?'dark':'light');
  if(btn)btn.textContent=dark?'☀️':'🌙';
  if(btn)btn.addEventListener('click',function(){
    var d=document.documentElement.getAttribute('data-theme')==='dark';
    document.documentElement.setAttribute('data-theme',d?'light':'dark');
    localStorage.setItem('theme',d?'light':'dark');
    btn.textContent=d?'🌙':'☀️';
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

for page in PAGES:
    path = ROOT / page
    if not path.exists():
        print(f"  SKIP {page} (introuvable)")
        continue

    html = path.read_text(encoding="utf-8")
    orig = html

    # 1. Ajouter data-theme="" à <html> si absent
    html = re.sub(r'<html([^>]*?)(?:\s+data-theme="[^"]*")?>', lambda m: f'<html{m.group(1)} data-theme="">', html, count=1)

    # 2. Injecter script init dark mode après <body> si pas déjà là
    if "localStorage.getItem('theme')" not in html:
        html = re.sub(r'(<body[^>]*>)', r'\1\n' + DARK_INIT_SCRIPT, html, count=1)

    # 3. Ajouter dark toggle dans le header (avant </div> qui ferme header__inner)
    if 'dark-toggle' not in html:
        html = re.sub(r'(\s*)(</div>\s*</header>)', lambda m: f'\n    {DARK_TOGGLE}{m.group(1)}{m.group(2)}', html, count=1)

    # 4. Remplacer tout le bloc footer
    html = re.sub(r'<footer class="footer".*?</footer>', NEW_FOOTER, html, flags=re.DOTALL)

    # 5. Ajouter script dark mode complet avant </body>
    if 'btn.addEventListener' not in html:
        html = re.sub(r'(</body>)', DARK_FULL_SCRIPT + r'\n\1', html)

    if html != orig:
        path.write_text(html, encoding="utf-8")
        print(f"  ✓ {page} patché")
    else:
        print(f"  = {page} inchangé")

print("Patch terminé.")
