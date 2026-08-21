"""Verrouille les trois défauts de sélection mesurés le 21/08 sur des sujets
d'actualité RÉELS que le pipeline a laissé passer (liste fournie par Nahil).

Chaque cas est un titre effectivement présent dans nos flux (vérifié dans
data/veille.json) et pourtant jamais retenu. Les valeurs attendues ne sont pas
des scores exacts — elles disent seulement de quel côté du seuil de sélection
(20) le candidat doit tomber. Figer un score exact rendrait ce test cassant à
chaque retouche du barème, pour aucun gain.
"""
import datetime
import pipeline as P

SEUIL = 20


def _score(titre: str, contenu: str, source: str) -> int:
    now = datetime.datetime.now(datetime.timezone.utc)
    return P.score_editorial(
        {"title": titre, "content": contenu, "url": "https://www.lemonde.fr/x",
         "published": now.isoformat()},
        source, set())[0]


def test_blacklist_ancree_au_debut_du_mot():
    """« sabotage » ne doit pas être rejeté sur le mot « otage ».

    Mesuré sur les 3 157 items de data/veille.json : la correspondance en
    sous-chaîne nue éliminait 5 titres, tous le même sujet majeur (Nord
    Stream), avant même d'être notés.
    """
    s = _score("Nord Stream : arrestation d'un ex-commandant ukrainien "
               "soupçonné d'avoir saboté le gazoduc",
               "Un ancien commandant ukrainien soupçonné d'avoir participé au "
               "sabotage des gazoducs Nord Stream a été arrêté en Croatie sur "
               "un mandat d'arrêt européen émis par le parquet allemand.",
               "Le Monde")
    assert s >= SEUIL, f"sujet majeur sous le seuil : {s}"


def test_pluriels_et_accords_restent_bloques():
    """La frontière est ancrée AU DÉBUT seulement : ancrer les deux côtés
    casserait les pluriels, qui sont de vrais positifs (6 titres mesurés)."""
    for titre in ("Un aéroport militaire syrien frappé, des bombardements "
                  "attribués à Israël",
                  "L'ancienne vice-présidente inculpée pour détournement"):
        assert _score(titre, "x" * 300, "Le Monde") == -1, titre


def test_teaser_court_nest_plus_un_rejet():
    """Un chapeau bref n'est plus éliminé avant notation : la substance est
    testée en aval (PERTINENCE_MIN_POUR_GENERER, bilan_qualite_sources)."""
    s = _score("Alerte aux baïnes en Charente-Maritime après trois noyades",
               "La préfecture de Charente-Maritime a émis une alerte aux "
               "baïnes sur le littoral.", "franceinfo")
    assert s >= SEUIL, f"sujet bref mais réel écarté : {s}"


def test_item_vide_toujours_rejete():
    """Le garde-fou subsiste pour l'item dont on ne peut RIEN juger."""
    assert _score("Titre nu sans chapeau", "", "Le Monde") == -1


def test_procedure_judiciaire_compte_comme_enjeu_public():
    """Un fait judiciaire ne doit pas attendre son jugement pour être une
    actualité : `arrestation`, `parquet`, `mandat d'arrêt`, `extradition`."""
    s = _score("Le parquet de Paris enquête sur des soupçons d'ingérence "
               "russe ciblant Édouard Philippe",
               "Le parquet de Paris a ouvert une enquête sur des soupçons "
               "d'ingérence russe visant l'ancien premier ministre.",
               "franceinfo")
    assert s >= SEUIL, f"enquête du parquet sous le seuil : {s}"


def test_le_commercial_reste_rejete():
    """Élargir le vivier ne doit pas rouvrir la porte aux listicles."""
    assert _score("Lidl : 5 appareils de cuisine à moins de 10 euros",
                  "Sélection de produits à petit prix chez Lidl cette "
                  "semaine dans le rayon cuisine.", "Le Monde") == -1


if __name__ == "__main__":
    n = 0
    for nom, fn in sorted(globals().items()):
        if nom.startswith("test_"):
            fn(); n += 1; print(f"  ✓ {nom}")
    print(f"{n} tests OK")
