"""Écarter les reproches que leur propre citation dément.

Relecture à la main des 27 reproches bloquants du run 276 : 4 fondés, 20
infondés, 2 indécidables (soit 15 % de justesse). La famille la plus flagrante
est celle-ci : le juge réclame un mot qui figure DÉJÀ dans la phrase citée.

⚠ CE N'EST PAS UN ASSOUPLISSEMENT. Aucun motif n'est retiré, aucun seuil
baissé. On écarte uniquement des reproches dont la citation ou la description
apporte elle-même la preuve qu'ils sont faux — ce qu'un humain vérifie en dix
secondes.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("GROQ_API_KEY", "x")

import verification as V


def _pb(type_, phrase, description, bloc=1):
    return {"bloc": bloc, "type": type_, "phrase": phrase, "description": description}


def test_cas_reel_inserm():
    """Cas exact du run 276 : « préliminaires » est dans la phrase."""
    p = _pb("niveau_preuve_insuffisant",
            "Selon les données préliminaires de l'Inserm, des disparités "
            "territoriales apparaissent.",
            "L'article présente des résultats comme des constats établis sans "
            "rappeler explicitement que les données sont préliminaires.")
    assert V._reproche_auto_contredit(p)
    assert V._problemes_bloquants([p]) == []


def test_cas_reel_attribution():
    """Cas exact du run 276 : l'attribution ET le conditionnel sont présents."""
    p = _pb("accusation_presentee_comme_fait",
            "VIH.org indique que ces territoires présenteraient des taux élevés "
            "d'infections sexuellement transmissibles.",
            "L'article présente cette affirmation comme un constat neutre, sans "
            "attribution explicite dans cette phrase.")
    assert V._reproche_auto_contredit(p)


def test_symetrie_source_absente_cas_run_280():
    """Le juge ne peut exiger une limite qu'il dit lui-même absente de la source."""
    p = _pb(
        "niveau_preuve_insuffisant",
        "Selon les travaux cités, la valeur peut varier selon les conditions [1].",
        "La source [1] ne précise pas les limites méthodologiques ou les "
        "incertitudes associées. L'article ne mentionne pas ces limites "
        "méthodologiques ni ces incertitudes.",
    )
    assert V._reproche_exige_source_absente(p)
    assert V._problemes_bloquants([p]) == []


def test_symetrie_ne_masque_pas_une_suraffirmation():
    """Si le reproche porte aussi sur un niveau de preuve renforcé, il bloque."""
    p = _pb(
        "niveau_preuve_insuffisant",
        "Le traitement améliore la survie [1].",
        "La source [1] ne précise pas les limites méthodologiques. L'article ne "
        "mentionne pas ces limites et présente l'efficacité comme un résultat acquis.",
    )
    assert not V._reproche_exige_source_absente(p)
    assert len(V._problemes_bloquants([p])) == 1


def test_reserve_deja_presente_ne_doit_pas_etre_repetee_cas_run_281():
    """Cas du 26/08 : le juge reconnaît les limites ailleurs puis exige un doublon."""
    p = _pb(
        "niveau_preuve_insuffisant",
        "Les études précliniques sur des souris montrent des effets sur certains "
        "marqueurs, mais ces résultats sont préliminaires, obtenus sur de petits "
        "effectifs et sans validation à long terme [5].",
        "La phrase omet de préciser le stade de la recherche (préclinique) et les "
        "limites méthodologiques exactes (effectifs, durée de suivi) déjà mentionnées "
        "dans les faits et nuances, mais le résumé doit rappeler le caractère "
        "préliminaire de ces résultats.",
    )
    assert V._reproche_exige_repetition(p)
    assert V._problemes_bloquants([p]) == []


def test_vraie_omission_sans_aveu_de_presence_reste_bloquante():
    """Sans reconnaissance explicite d'une réserve déjà présente, on ne filtre rien."""
    p = _pb(
        "niveau_preuve_insuffisant",
        "Le traitement améliore la survie [1].",
        "L'article ne précise pas que l'étude est préclinique et le résumé doit "
        "rappeler que l'efficacité n'est pas acquise.",
    )
    assert not V._reproche_exige_repetition(p)
    assert len(V._problemes_bloquants([p])) == 1


def test_un_reproche_fonde_bloque_toujours():
    """Les 4 reproches fondés du run visaient des attributions collectives
    floues — « comme le rappellent les experts », « les autorités ont
    souligné ». Ceux-là doivent continuer de bloquer."""
    p = _pb("accusation_presentee_comme_fait",
            "En France, les effets sanitaires restent à évaluer, comme le "
            "rappellent les experts.",
            "L'article présente cette affirmation comme un fait établi sans "
            "attribution précise à une source identifiée.")
    assert not V._reproche_auto_contredit(p)
    assert len(V._problemes_bloquants([p])) == 1


def test_un_reproche_qui_ne_parle_pas_d_absence_est_intact():
    """Le garde-fou ne s'applique QU'AUX reproches d'omission. Un chiffre faux
    reste un chiffre faux même si le mot « selon » figure dans la phrase."""
    p = _pb("chiffre_errone",
            "Selon l'Insee, l'inflation atteint 2,1 % sur un an.",
            "La source indique 1,9 % et non 2,1 %.")
    assert not V._reproche_auto_contredit(p)
    assert len(V._problemes_bloquants([p])) == 1


def test_sans_phrase_citee_on_ne_tranche_pas():
    """Faute de citation, le garde historique ne peut rien démentir."""
    p = _pb("niveau_preuve_insuffisant", "",
            "sans rappeler que les données sont préliminaires")
    assert not V._reproche_auto_contredit(p)


if __name__ == "__main__":
    n = 0
    for nom, fn in sorted(globals().items()):
        if nom.startswith("test_"):
            fn(); n += 1; print(f"  ✓ {nom}")
    print(f"{n} tests OK")
