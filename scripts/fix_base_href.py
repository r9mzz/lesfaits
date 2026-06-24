"""Ajoute <base href="/factuel/"> dans tous les HTML du site."""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT     = Path(__file__).parent.parent
BASE_TAG = '<base href="/factuel/"/>'

def fix(path: Path, old_css: str, new_css: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if "<base href" in text:
        return False
    if old_css not in text:
        return False
    text = text.replace(old_css, BASE_TAG + "\n  " + new_css)
    path.write_text(text, encoding="utf-8")
    return True

# index.html
tag = '<link rel="stylesheet" href="src/style.css"/>'
ok = fix(ROOT / "index.html", tag, tag)
print(f"index.html : {'corrige' if ok else 'deja OK'}")

# Articles
n = 0
old = '<link rel="stylesheet" href="../src/style.css"/>'
new = '<link rel="stylesheet" href="src/style.css"/>'
for p in sorted((ROOT / "articles").glob("*.html")):
    if fix(p, old, new):
        n += 1
        print(f"  OK {p.name}")

print(f"\nTotal : {n} article(s) corriges")
