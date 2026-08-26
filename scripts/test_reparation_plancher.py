"""La réparation des doublons ne doit pas amputer l'article sous le plancher.

Run 279 — les deux seuls articles ayant passé le fact-check ont été rejetés
ensuite pour longueur :

    [VERIF] aucun bloquant — publié
    [RÉPARATION] 5 phrase(s) dupliquée(s) supprimée(s) après correction
    [REJET VITRINE] total trop court (325 mots, minimum 400)

L'article faisait 643 mots au journal juste avant. Ce n'est donc pas « Mistral
écrit court » : c'est notre propre réparation qui coupe la moitié du texte
APRÈS validation éditoriale.

⚠ Elle coupe en outre sur un critère mesuré comme NON FIABLE — son référentiel
inclut le chapeau, alors qu'étendre `resume_repete_corps` au-delà des « faits »
a été testé puis écarté le 28/07 (taux 7 % → 41-95 %). Mesuré sur 70 articles
publiés : 108 phrases supprimées, dont 49 (45 %) à cause du seul chapeau.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("GROQ_API_KEY", "x")

import pipeline as P


def _phrase(n, mots=25):
    """Phrase unique de longueur contrôlée."""
    return f"Le rapport numéro {n} détaille " + " ".join(
        f"element{n}x{k}" for k in range(mots)) + "."


def _article(n_uniques, n_doublons):
    uniques = [_phrase(i) for i in range(n_uniques)]
    corps = " ".join(uniques + [uniques[0]] * n_doublons)
    return {"resume": ["Chapeau distinct sans rapport lexical avec le corps."],
            "corps": {"faits": corps, "contexte": "", "nuances": ""}}


def _mots(art):
    return sum(len(str(art["corps"][s] or "").split())
               for s in ("faits", "contexte", "nuances"))


def test_les_doublons_sont_supprimes_quand_il_reste_de_la_marge():
    """Le garde-fou n'est pas désarmé : au-dessus du plancher, on coupe."""
    art = _article(n_uniques=30, n_doublons=4)      # très au-dessus de 350
    avant = _mots(art)
    n = P._supprimer_phrases_dupliquees(art)
    assert n > 0, "aucun doublon supprimé alors que la marge le permettait"
    assert _mots(art) < avant


def test_la_reparation_s_arrete_au_plancher():
    """C'est le cas du run 279 : l'article ne doit plus passer sous le seuil
    de publication à cause de sa propre réparation."""
    plancher = P._seuils("actu")["plancher"]
    art = _article(n_uniques=14, n_doublons=6)      # juste au-dessus du seuil
    assert _mots(art) >= plancher, "cas de test mal construit"
    P._supprimer_phrases_dupliquees(art)
    assert _mots(art) >= plancher, (
        f"la réparation a ramené l'article à {_mots(art)} mots, sous le "
        f"plancher de {plancher}")


def test_un_article_deja_sous_le_plancher_nest_pas_ampute_davantage():
    """Si l'article arrive déjà court, la réparation ne l'aggrave pas."""
    art = _article(n_uniques=4, n_doublons=4)
    avant = _mots(art)
    P._supprimer_phrases_dupliquees(art)
    assert _mots(art) == avant


if __name__ == "__main__":
    n = 0
    for nom, fn in sorted(globals().items()):
        if nom.startswith("test_"):
            fn(); n += 1; print(f"  ✓ {nom}")
    print(f"{n} tests OK")
