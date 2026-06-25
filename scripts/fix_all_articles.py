"""Corrige tous les articles existants : logo, footer contact, ordre rubriques."""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).parent.parent

FIXES = [
    # Logo cassé
    (
        '<div class="brand__logo">F</div>\n      <div><div class="brand__name">Factuel</div><div class="brand__slogan">Juste les faits. Aucun parti pris.</div></div>',
        '<div class="brand__logotype"><span class="fact">les</span><span class="uel">faits</span></div>'
    ),
    # Footer brand logo
    (
        '<div class="brand__logo" style="width:32px;height:32px;font-size:18px">F</div>\n        <div class="brand__name" style="font-size:16px">Factuel</div>',
        '<div class="brand__logotype"><span class="fact">les</span><span class="uel">faits</span></div>'
    ),
    # Footer CONTACT doublon
    (
        '<div class="footer__col"><h4>CONTACT</h4>\n      <a href="mailto:lesfaits.contact@gmail.com">Nous \xe9crire</a>\n      <a href="#">Corrections publiques</a>\n    </div>',
        '<div class="footer__col"><h4>CONTACT</h4>\n      <a href="mailto:lesfaits.contact@gmail.com">Nous \xe9crire</a>\n      <a href="mailto:lesfaits.contact@gmail.com?subject=Signalement erreur">Signaler une erreur</a>\n    </div>'
    ),
    # Ordre rubriques footer articles
    (
        '<div class="footer__col"><h4>RUBRIQUES</h4>\n      <a href="../categories/science.html">Science</a>\n      <a href="../categories/economie.html">\xc9conomie</a>\n      <a href="../categories/societe.html">Soci\xe9t\xe9</a>',
        '<div class="footer__col"><h4>RUBRIQUES</h4>\n      <a href="../categories/societe.html">Soci\xe9t\xe9</a>\n      <a href="../categories/science.html">Science</a>\n      <a href="../categories/economie.html">\xc9conomie</a>'
    ),
    # Contester un fait sans lien → avec mailto
    (
        '<a class="contest-btn" href="#">Contester un fait</a>',
        '<a class="contest-btn" href="mailto:lesfaits.contact@gmail.com?subject=Contestation">Contester un fait</a>'
    ),
]

n = 0
for p in sorted((ROOT / "articles").glob("*.html")):
    text = p.read_text(encoding="utf-8")
    changed = False
    for old, new in FIXES:
        if old in text:
            text = text.replace(old, new)
            changed = True
    if changed:
        p.write_text(text, encoding="utf-8")
        n += 1
        print(f"  OK {p.name}")

print(f"\nTotal : {n} article(s) mis a jour")
