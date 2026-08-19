"""Retirer une citation invalide ne doit pas laisser de cicatrice typographique.

`strip_citations_invalides` retire les `[n]` qui ne renvoient à aucune source —
réparer plutôt que rejeter, un numéro mal relié ne rend pas le fait faux. Mais
retirer « [4] » dans « Fait B [4]. » laissait « Fait B . », une espace avant le
point, visible dans l'article publié. La collapse des espaces doubles déjà en
place ne l'attrape pas : il n'en reste qu'une.

⚠ La correction ne recolle QUE le point et la virgule. En typographie
française, l'espace avant « ; : ! ? » est CORRECTE — la retirer abîmerait un
texte sain pour réparer un cas rare.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("GROQ_API_KEY", "x")

import pipeline as P  # noqa: E402

_TROIS_SOURCES = [{"url": "https://a.fr"}, {"url": "https://b.fr"}, {"url": "https://c.fr"}]


def _repare(texte, resume=None):
    art = P.strip_citations_invalides({
        "corps": {"faits": texte, "contexte": "", "nuances": ""},
        "resume": resume if resume is not None else [],
        "sources": list(_TROIS_SOURCES)})
    return art["corps"]["faits"], art.get("resume")


def test_pas_d_espace_orpheline_avant_le_point():
    texte, _ = _repare("Fait A [1]. Fait B [4]. Fait C [2].")
    assert texte == "Fait A [1]. Fait B. Fait C [2].", texte


def test_la_typographie_francaise_est_respectee():
    """L'espace avant « ; : ! ? » ne doit PAS être supprimée."""
    texte, _ = _repare("Ceci [7] ; cela [8] : vraiment [9] ! ainsi [6] ?")
    assert texte == "Ceci ; cela : vraiment ! ainsi ?", texte


def test_les_citations_valides_ne_bougent_pas():
    texte, _ = _repare("Fait A [1], fait B [2] ; fait C [3].")
    assert texte == "Fait A [1], fait B [2] ; fait C [3].", texte


def test_le_resume_est_nettoye_de_la_meme_facon():
    _, resume = _repare("Rien.", resume=["Un resume [5]."])
    assert resume == ["Un resume."], resume


def test_l_article_d_origine_n_est_jamais_muté():
    """La fonction rend une COPIE. Un appelant qui compare l'avant et l'après
    doit pouvoir le faire — et un appelant qui ignore la valeur de retour doit
    échouer visiblement, pas publier un texte à moitié réparé."""
    art = {"corps": {"faits": "Fait B [4].", "contexte": "", "nuances": ""},
           "sources": list(_TROIS_SOURCES)}
    P.strip_citations_invalides(art)
    assert art["corps"]["faits"] == "Fait B [4]."


if __name__ == "__main__":
    test_pas_d_espace_orpheline_avant_le_point()
    test_la_typographie_francaise_est_respectee()
    test_les_citations_valides_ne_bougent_pas()
    test_le_resume_est_nettoye_de_la_meme_facon()
    test_l_article_d_origine_n_est_jamais_muté()
    print("OK — citations retirées sans cicatrice typographique")
