# -*- coding: utf-8 -*-
"""Le contrôle de profondeur lit les sections comme le site les rend."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bs4 import BeautifulSoup  # noqa: E402
from editorial_quality import _section_texts  # noqa: E402

ACTUEL = """<article>
<h2 class="art__h2" data-section="faits">Ce que montrent les chiffres de juin</h2><p>Premier paragraphe des faits.</p><p>Deuxième paragraphe des faits.</p><p>Troisième.</p>
<h2 class="art__h2" data-section="contexte">Une hausse inédite depuis 2003</h2><p>Contexte un.</p><p>Contexte deux.</p>
<h2 class="art__h2" data-section="nuances">Ce que les données ne disent pas</h2><p>Nuance un.</p><p>Nuance deux.</p>
<section class="sources"><ol><li id="source-1"><cite>Insee</cite></li></ol></section>
</article>"""

ANCIEN = """<article>
<h2 class="art__h2">Les faits</h2><p>Faits anciens.</p>
<h2 class="art__h2">Contexte</h2><p>Contexte ancien.</p>
<h2 class="art__h2">Débats et nuances</h2><p>Nuances anciennes.</p>
</article>"""


def test_format_actuel_tous_paragraphes_et_bonne_section():
    s = _section_texts(BeautifulSoup(ACTUEL, "html.parser"))
    assert "Premier" in s["facts"] and "Troisième" in s["facts"]
    assert s["context"] == "Contexte un. Contexte deux."
    assert s["nuances"] == "Nuance un. Nuance deux."


def test_ancien_format_reconnu_par_libelle():
    s = _section_texts(BeautifulSoup(ANCIEN, "html.parser"))
    assert s == {"facts": "Faits anciens.", "context": "Contexte ancien.",
                 "nuances": "Nuances anciennes."}


if __name__ == "__main__":
    n = 0
    for nom, fn in sorted(globals().items()):
        if nom.startswith("test_"):
            fn()
            n += 1
            print(f"  ✓ {nom}")
    print(f"{n} tests OK")
