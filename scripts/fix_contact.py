"""Met a jour le footer contact dans tous les HTML."""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent.parent

OLD1 = 'SOUTENIR</h4>\n      <a href="#">Faire un don</a><a href="#">Contact</a>'
NEW1 = 'CONTACT</h4>\n      <a href="mailto:Factuelinfo.contact@gmail.com">Nous écrire</a>\n      <a href="#">Corrections publiques</a>'

n = 0
files = list((ROOT / "articles").glob("*.html")) + [ROOT / "index.html"]
for p in files:
    text = p.read_text(encoding="utf-8")
    if "SOUTENIR" in text:
        p.write_text(text.replace(OLD1, NEW1), encoding="utf-8")
        n += 1
        print(f"  OK {p.name}")

print(f"\nTotal : {n} fichier(s) mis a jour")
