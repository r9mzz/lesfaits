# -*- coding: utf-8 -*-
"""La réflexion d'un modèle raisonneur n'est coupée que là où elle est mesurée.

24/10 : nemotron-3-ultra (NVIDIA NIM) dépensait son budget de sortie à réfléchir
et ne laissait pas de place au JSON. `enable_thinking: false` règle cela — mais
ce paramètre ne doit JAMAIS partir chez un autre fournisseur ni pour un autre
modèle.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from modele_fournisseur import corps_sans_reflexion

NVIDIA = {"LLM_BASE_URL": "https://integrate.api.nvidia.com/v1"}
ATTENDU = {"chat_template_kwargs": {"enable_thinking": False}}


def test_coupe_la_reflexion_de_nemotron_sur_nvidia():
    assert corps_sans_reflexion("nvidia/nemotron-3-ultra-550b-a55b", NVIDIA) == ATTENDU


def test_ne_touche_pas_gemma_sur_nvidia():
    assert corps_sans_reflexion("google/gemma-4-31b-it", NVIDIA) == {}


def test_ne_part_jamais_chez_un_autre_fournisseur():
    for base in ("https://api.mistral.ai/v1", "", "https://api.groq.com/openai/v1",
                 "https://generativelanguage.googleapis.com/v1beta/openai"):
        assert corps_sans_reflexion("nvidia/nemotron-3-ultra-550b-a55b",
                                    {"LLM_BASE_URL": base}) == {}, base


def test_modele_vide():
    assert corps_sans_reflexion("", NVIDIA) == {}


if __name__ == "__main__":
    n = 0
    for nom, fn in sorted(globals().items()):
        if nom.startswith("test_"):
            fn()
            n += 1
            print(f"  ✓ {nom}")
    print(f"{n} tests OK")
