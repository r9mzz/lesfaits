# -*- coding: utf-8 -*-
"""Non-régression : le contenu du header ne doit jamais être dans un calque filtré.

Constat 25/08 — le menu « Catégories » s'affichait flou : texte et bordures
comme au crayon gras, alors que le reste de la page était net. `.header`
portait `backdrop-filter`, or un élément filtré crée un contexte de
composition et TOUS ses descendants y sont rasterisés : ils perdent
l'anticrénelage sous-pixel du texte. `.nav-cats-dd` vit dans
`.header__inner > nav`, donc dedans.

Le flou est désormais porté par `.header::before`. Ce test verrouille
l'arbitrage, parce que rien d'autre ne le signalerait : aucune erreur, aucun
avertissement, juste un rendu mou que seul l'œil attrape — et il a fallu une
capture d'écran d'un lecteur pour le voir.

Vaut aussi pour `filter` et `transform`, qui créent le même calque.

    python scripts/test_header_nettete.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
CSS = Path(__file__).resolve().parent.parent / "src" / "style.css"

# Propriétés qui rasterisent tout le sous-arbre.
FILTRANTES = ("backdrop-filter", "-webkit-backdrop-filter", "filter", "transform")


def bloc(nom: str, css: str) -> str:
    """Corps de la règle `nom` — le sélecteur exact, pas ses variantes."""
    # Ancré en DÉBUT DE LIGNE : la règle est précédée d'un commentaire,
    # pas d'une accolade fermante — un motif sur `}` ne la trouvait pas.
    m = re.search(r"^" + re.escape(nom) + r"\s*\{([^}]*)\}", css, re.S | re.M)
    return m.group(1) if m else ""


def main() -> int:
    css = CSS.read_text(encoding="utf-8")
    ok = True

    corps = bloc(".header", css)
    if not corps:
        print("ÉCHEC : règle `.header` introuvable dans src/style.css")
        return 1

    print("=== `.header` ne doit porter AUCUNE propriété filtrante ===")
    for prop in FILTRANTES:
        # `\s*:` pour ne pas confondre `filter` avec `backdrop-filter`.
        present = re.search(r"(?:^|;|\s)" + re.escape(prop) + r"\s*:", corps)
        if present:
            ok = False
            print(f"  ÉCHEC  {prop} présent — tout le header redevient flou")
        else:
            print(f"  OK     {prop} absent")

    print("\n=== le verre dépoli doit rester, porté par `::before` ===")
    avant = bloc(".header::before", css)
    if "backdrop-filter" in avant:
        print("  OK     `.header::before` porte le backdrop-filter")
    else:
        ok = False
        print("  ÉCHEC  le flou a disparu du pseudo-élément — effet perdu")

    print("\n" + ("TOUS CONFORMES" if ok else "RÉGRESSION"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
