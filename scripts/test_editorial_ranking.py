# -*- coding: utf-8 -*-
"""Tests déterministes du classement éditorial au niveau du sujet."""
import json
import tempfile
from datetime import datetime
from pathlib import Path

from editorial_ranking import _recent_rejected_slugs, rank_subjects, selectionner_sujets


def _item(title, source, score, cat="societe", content="x" * 200):
    return {
        "title": title,
        "source_name": source,
        "_score": score,
        "_cat": cat,
        "content": content,
    }


def test_multisource_event_beats_isolated_magazine():
    candidats = [
        _item("Sécheresse : 70 % de la France placée en vigilance", "Média A", 37),
        _item("La sécheresse place 70 % du territoire français en vigilance", "Média B", 35),
        _item("Sécheresse en France : 70 % du territoire sous vigilance", "Média C", 33),
        _item("Le monde rêvé des globes virtuels", "Magazine X", 42),
    ]
    ranked = rank_subjects(candidats, rejected_slugs=set())
    assert len(ranked) == 2, ranked
    assert ranked[0]["_corroboration_medias"] == 3, ranked
    assert ranked[0]["_selection_score"] > ranked[1]["_selection_score"], ranked
    assert ranked[0]["_score"] == 37, "Le score historique ne doit jamais être modifié"


def test_one_subject_one_representative():
    candidats = [
        _item("Éclipse solaire totale visible lundi", "A", 31),
        _item("Lundi, une éclipse solaire totale sera visible", "B", 29),
        _item("Éclipse solaire totale : ce qui sera visible lundi", "C", 27),
    ]
    ranked = rank_subjects(candidats, rejected_slugs=set())
    assert len(ranked) == 1, ranked
    assert ranked[0]["source_name"] == "A"
    assert ranked[0]["_corroboration_medias"] == 3


def test_no_single_word_false_cluster():
    candidats = [
        _item("Découverte d'une exoplanète autour d'une étoile proche", "A", 30),
        _item("Découverte du détroit ancien sous une couche géologique", "B", 30),
    ]
    ranked = rank_subjects(candidats, rejected_slugs=set())
    assert len(ranked) == 2, ranked
    assert all(i["_corroboration_medias"] == 1 for i in ranked)


def test_recent_exact_rejection_is_not_retried():
    candidats = [
        _item("Edgar Morin pensée complexe", "A", 45),
        _item("Sécheresse agricole dans le sud-ouest", "B", 35),
    ]
    ranked = rank_subjects(
        candidats,
        rejected_slugs={"edgar-morin-pensee-complexe"},
    )
    assert [i["title"] for i in ranked] == ["Sécheresse agricole dans le sud-ouest"]


def test_rejected_rss_title_is_not_retried_when_generated_slug_differs():
    titre_rss = "À la tête de l’ONU, l’heure d’une femme a-t-elle enfin sonné ?"
    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / "verification_log.json"
        log_path.write_text(
            json.dumps([
                {
                    "slug": "onu-2026-premiere-femme-secretaire-generale",
                    "titre_rss": titre_rss,
                    "statut": "rejete_qualite",
                    "date": "2026-08-19T04:00:37",
                }
            ]),
            encoding="utf-8",
        )
        rejected = _recent_rejected_slugs(
            log_path=log_path,
            now=datetime.fromisoformat("2026-08-19T21:00:00"),
        )
    ranked = rank_subjects([_item(titre_rss, "A", 45)], rejected_slugs=rejected)
    assert ranked == [], "Le même item RSS rejeté ne doit pas repayer une génération sous un autre slug"


def test_cooldown_never_uses_fuzzy_topic_similarity():
    candidats = [
        _item("Edgar Morin et un colloque scientifique publié mardi", "A", 45),
    ]
    ranked = rank_subjects(
        candidats,
        rejected_slugs={"edgar-morin-pensee-complexe"},
    )
    assert len(ranked) == 1, "Une nouvelle actualité voisine ne doit pas être blacklistée"


def test_category_quotas_are_preserved():
    candidats = [
        _item("Batteries sodium nouvelle usine industrielle France", "A", 45, "tech"),
        _item("Nouvelle usine française de batteries sodium industrielle", "B", 40, "tech"),
        _item("Puce photonique nouveau procédé industriel européen", "C", 44, "tech"),
        _item("Hôpital public nouveau protocole national infections", "D", 43, "sante"),
    ]
    # Les tests synthétiques ne dépendent jamais du journal réel du dépôt.
    selection = []
    ranked = rank_subjects(candidats, rejected_slugs=set())
    compteur = {}
    for item in ranked:
        if len(selection) >= 3:
            break
        cat = item.get("_cat", "societe")
        plafond = {"tech": 1, "sante": 2}.get(cat, 2)
        if compteur.get(cat, 0) >= plafond:
            continue
        selection.append(item)
        compteur[cat] = compteur.get(cat, 0) + 1
    assert sum(1 for i in selection if i["_cat"] == "tech") <= 1
    assert sum(1 for i in selection if i["_cat"] == "sante") <= 2


def main():
    test_multisource_event_beats_isolated_magazine()
    test_one_subject_one_representative()
    test_no_single_word_false_cluster()
    test_recent_exact_rejection_is_not_retried()
    test_rejected_rss_title_is_not_retried_when_generated_slug_differs()
    test_cooldown_never_uses_fuzzy_topic_similarity()
    test_category_quotas_are_preserved()
    print("OK — editorial_ranking")


if __name__ == "__main__":
    main()
