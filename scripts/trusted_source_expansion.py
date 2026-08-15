# -*- coding: utf-8 -*-
"""Extension conservatrice du sourcing documentaire Les Faits.

Objectif : augmenter fortement les chances de trouver des documents primaires
et des confirmations indépendantes sans transformer le moteur en aspirateur à
blogs. Ce module n'abaisse aucun seuil : il élargit uniquement les domaines
reconnus comme fiables et les axes de recherche exécutés avant la rédaction.

Le patch est volontairement strict : si la structure attendue de pipeline.py
change, il échoue au prévol au lieu d'appliquer silencieusement une politique
incomplète.
"""
from __future__ import annotations


EXTRA_PRIMARY_DOMAINS = (
    # France — administrations, données et régulateurs
    "data.gouv.fr", "service-public.fr", "amf-france.org", "ameli.fr",
    "urssaf.fr", "brgm.fr", "cerema.fr", "ofb.gouv.fr", "agencebio.org",
    # Union européenne / Europe — institutions et agences
    "ecb.europa.eu", "europarl.europa.eu", "consilium.europa.eu",
    "ecdc.europa.eu", "ema.europa.eu", "echa.europa.eu", "eea.europa.eu",
    "enisa.europa.eu",
    # Organisations internationales / statistiques
    "who.int", "un.org", "unicef.org", "wmo.int", "iea.org", "irena.org",
    # États-Unis — agences et données publiques utiles aux sujets internationaux
    "noaa.gov", "usgs.gov", "cdc.gov", "nih.gov", "fda.gov", "sec.gov",
    "nist.gov",
    # Instituts statistiques étrangers de premier rang
    "ons.gov.uk", "statcan.gc.ca", "bfs.admin.ch", "destatis.de",
    # Revues / synthèses scientifiques de référence
    "jamanetwork.com", "cochranelibrary.com", "acpjournals.org",
)

EXTRA_SECONDARY_DOMAINS = (
    # Agences / économie / international
    "ft.com", "bloomberg.com", "economist.com", "politico.eu",
    # Services publics ou rédactions internationales de référence
    "dw.com", "npr.org", "cbc.ca", "abc.net.au", "swissinfo.ch",
    "tagesschau.de", "elpais.com",
)

EXTRA_UNIVERSAL_AXES = (
    (
        "statistiques officielles",
        "chiffres OR données site:insee.fr OR site:eurostat.ec.europa.eu "
        "OR site:data.gouv.fr OR site:oecd.org OR site:worldbank.org "
        "OR site:imf.org",
    ),
    (
        "institutions européennes et internationales",
        "site:ec.europa.eu OR site:consilium.europa.eu OR "
        "site:europarl.europa.eu OR site:who.int OR site:un.org",
    ),
    (
        "agences et confirmations indépendantes",
        "site:reuters.com OR site:apnews.com OR site:afp.com OR site:bbc.com "
        "OR site:ft.com",
    ),
)

EXTRA_CATEGORY_AXES = {
    "sante": (
        (
            "agences sanitaires internationales",
            "site:who.int OR site:ecdc.europa.eu OR site:ema.europa.eu "
            "OR site:cdc.gov OR site:fda.gov OR site:nih.gov",
        ),
        (
            "revues et synthèses cliniques",
            "site:jamanetwork.com OR site:cochranelibrary.com OR "
            "site:acpjournals.org OR site:bmj.com OR site:nejm.org",
        ),
    ),
    "science": (
        (
            "agences scientifiques publiques",
            "site:nasa.gov OR site:esa.int OR site:cern.ch OR site:noaa.gov "
            "OR site:usgs.gov OR site:nih.gov",
        ),
    ),
    "environnement": (
        (
            "climat et observation officielle",
            "site:wmo.int OR site:eea.europa.eu OR site:noaa.gov OR "
            "site:copernicus.eu OR site:ipcc.ch OR site:iea.org",
        ),
    ),
    "economie": (
        (
            "banques centrales et marchés",
            "site:ecb.europa.eu OR site:banque-france.fr OR site:imf.org "
            "OR site:oecd.org OR site:worldbank.org OR site:amf-france.org",
        ),
        (
            "statistiques économiques internationales",
            "site:eurostat.ec.europa.eu OR site:ons.gov.uk OR site:statcan.gc.ca "
            "OR site:destatis.de",
        ),
    ),
    "societe": (
        (
            "données sociales publiques",
            "site:drees.solidarites-sante.gouv.fr OR "
            "site:dares.travail-emploi.gouv.fr OR site:ined.fr "
            "OR site:eurostat.ec.europa.eu OR site:data.gouv.fr",
        ),
    ),
    "tech": (
        (
            "cybersécurité et standards officiels",
            "site:cnil.fr OR site:enisa.europa.eu OR site:nist.gov "
            "OR site:cyber.gouv.fr OR site:digital-strategy.ec.europa.eu",
        ),
    ),
}


def _replace_once(source: str, marker: str, replacement: str, label: str) -> str:
    if source.count(marker) != 1:
        raise RuntimeError(
            f"Marqueur sourcing {label} introuvable ou dupliqué : "
            f"{source.count(marker)} occurrence(s)"
        )
    return source.replace(marker, replacement, 1)


def patch_pipeline_source(source: str) -> str:
    """Injecte la politique de sourcing fiable dans la copie runtime du pipeline."""
    # 1) Étendre les listes blanches APRÈS leur déclaration, sans réécrire les
    # tuples historiques. Ainsi la provenance de l'extension reste explicite.
    marker_quality = "\n\ndef qualite_source(url: str) -> str:\n"
    quality_injection = '''

# Extension sourcing premium (runtime V3) — domaines explicitement fiables.
from trusted_source_expansion import EXTRA_PRIMARY_DOMAINS, EXTRA_SECONDARY_DOMAINS
_DOMAINES_PRIMAIRES = tuple(dict.fromkeys(_DOMAINES_PRIMAIRES + EXTRA_PRIMARY_DOMAINS))
_DOMAINES_SECONDAIRES = tuple(dict.fromkeys(_DOMAINES_SECONDAIRES + EXTRA_SECONDARY_DOMAINS))


def qualite_source(url: str) -> str:
'''
    source = _replace_once(source, marker_quality, quality_injection, "qualite_source")

    # 2) Ajouter des axes documentaires au moteur existant. On conserve tous
    # les axes historiques et on déduplique par nom pour rendre le patch idempotent.
    marker_queries = "\n\ndef _requetes_recherche(query: str, categorie: str = \"\") -> list[tuple[str, str]]:\n"
    query_injection = '''

# Extension sourcing premium (runtime V3) — davantage de documents primaires.
from trusted_source_expansion import EXTRA_UNIVERSAL_AXES, EXTRA_CATEGORY_AXES
_AXES_UNIVERSELS = tuple(dict.fromkeys(_AXES_UNIVERSELS + EXTRA_UNIVERSAL_AXES))
for _cat, _axes_extra in EXTRA_CATEGORY_AXES.items():
    _existants = tuple(_AXES_PAR_CATEGORIE.get(_cat, ()))
    _noms = {a[0] for a in _existants}
    _AXES_PAR_CATEGORIE[_cat] = _existants + tuple(
        a for a in _axes_extra if a[0] not in _noms
    )


def _requetes_recherche(query: str, categorie: str = "") -> list[tuple[str, str]]:
'''
    source = _replace_once(source, marker_queries, query_injection, "requetes_recherche")

    # 3) Plus de candidats PAR AXE avant le tri qualité. Le plafond final de
    # sources injectées au rédacteur reste contrôlé ailleurs par le pipeline :
    # ceci augmente le choix, pas le volume publié ni les seuils.
    source = _replace_once(
        source,
        'for r in ddgs.text(q, max_results=10, region="fr-fr"):',
        'for r in ddgs.text(q, max_results=16, region="fr-fr"): ',
        "ddg_max_results",
    )

    # 4) Le défaut historique de 8 résultats par défaut est trop étroit quand
    # aucun appelant ne précise son propre plafond. Les appels explicites gardent
    # leur valeur ; seul le défaut passe à 24.
    source = _replace_once(
        source,
        'def duckduckgo_search(query: str, max_results: int = 8, categorie: str = "") -> list[dict]:',
        'def duckduckgo_search(query: str, max_results: int = 24, categorie: str = "") -> list[dict]:',
        "duckduckgo_default",
    )

    compile(source, "pipeline_trusted_sources.py", "exec")
    return source
