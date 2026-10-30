# -*- coding: utf-8 -*-
"""La mise en forme vitrine ne change que la FORME, jamais le fond."""
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("GROQ_API_KEY", "x")
from pipeline import _mise_en_forme_vitrine  # noqa: E402


def _mots(art):
    c = art["corps"]
    return " ".join(str(c.get(k) or "") for k in ("faits", "contexte", "nuances")).split()


def _article():
    return {
        "resume": ["Le budget recule de 3 % [1]. La mesure entre en vigueur en 2027 [2]."],
        "corps": {
            "faits": ("Le Sénat a voté le texte mardi [1]. Il prévoit 5 milliards d'euros [2]. "
                      "La commission avait émis des réserves [1]. Le vote final est attendu jeudi."),
            "contexte": "Le déficit atteint 5,1 % du PIB [2]. Bercy table sur 4,6 % en 2027.",
            "nuances": "Plusieurs économistes doutent de ce chiffre [2]. L'Insee publiera ses comptes en mars.",
        },
        "sources": [{"url": "https://a.fr/1"}, {"url": "https://b.fr/2"}, {"url": "https://c.fr/3"}],
    }


def test_aeration_sans_ajout_ni_retrait_de_mot():
    art = _article()
    avant = _mots(art)
    _mise_en_forme_vitrine(art)
    assert _mots(art) == avant
    assert len(art["corps"]["faits"].split("\n")) == 3
    assert len(art["corps"]["contexte"].split("\n")) == 2
    assert len(art["corps"]["nuances"].split("\n")) == 2


def test_source_jamais_citee_retiree_et_renumerotation_coherente():
    art = _article()
    art["corps"]["faits"] = art["corps"]["faits"].replace("[2]", "[3]")
    art["corps"]["contexte"] = art["corps"]["contexte"].replace("[2]", "[3]")
    art["corps"]["nuances"] = art["corps"]["nuances"].replace("[2]", "[3]")
    art["resume"] = [art["resume"][0].replace("[2]", "[3]")]
    _mise_en_forme_vitrine(art)
    assert [s["url"] for s in art["sources"]] == ["https://a.fr/1", "https://c.fr/3"]
    texte = " ".join(art["resume"]) + " ".join(art["corps"].values())
    assert "[3]" not in texte and "[2]" in texte and "[1]" in texte


def test_rien_si_citation_hors_liste():
    art = _article()
    art["corps"]["faits"] += " Un autre point [7]."
    sources_avant = copy.deepcopy(art["sources"])
    _mise_en_forme_vitrine(art)
    assert art["sources"] == sources_avant


def test_rien_si_toutes_les_sources_sont_citees():
    art = _article()
    art["corps"]["nuances"] += " Une précision [3]."
    _mise_en_forme_vitrine(art)
    assert len(art["sources"]) == 3


if __name__ == "__main__":
    n = 0
    for nom, fn in sorted(globals().items()):
        if nom.startswith("test_"):
            fn()
            n += 1
            print(f"  ✓ {nom}")
    print(f"{n} tests OK")
