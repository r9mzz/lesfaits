# -*- coding: utf-8 -*-
"""Grille de publication « vitrine » pour Les Faits.

Cette grille intervient sur l'article final, après génération, relances,
contrôles déterministes et fact-check. Elle ne réécrit rien : un texte qui
n'atteint pas le niveau démonstrateur est refusé et le pipeline essaie le sujet
suivant. L'objectif n'est pas le volume, mais un ou deux articles publiables
sans réserve éditoriale.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from urllib.parse import urlsplit, urlunsplit

# ── RECALIBRAGE DU 21/08 — même erreur que la grille brève, même correctif ───
# Ces seuils rejetaient 140 articles publiés sur 140. Mesuré, pas supposé : le
# `total` de la vitrine est faits+contexte+nuances, CHAPEAU EXCLU (Boohoo,
# run 258 : 461 mots au journal, 435 comptés ici). Sur cette grandeur exacte,
# les 140 articles longs du corpus, sections mesurées une à une :
#
#              min   p33  médiane   max   ancien seuil
#     faits     48   135     150    345      420
#     contexte  25   106     119    185      180
#     nuances   16    91     104    172      130
#     total    158   327     372    670      760
#
# Le MAXIMUM jamais atteint par ce site est 670 mots, contre un seuil de 760 :
# la grille était inatteignable par construction, pas exigeante. Un article
# passait donc tout le protocole — génération, relances, garde-fous, fact-check
# 3 passes — pour mourir sur un seuil que rien n'avait jamais franchi.
#
# C'est EXACTEMENT le défaut corrigé le 12/08 sur la grille brève, dont le
# commentaire ci-dessous dit « je les avais posés sur le haut de la
# distribution en croyant les poser à la mesure du format ». Le même calibrage
# est repris ici : on écarte le tiers inférieur, on garde le reste.
#
# `total` = 400 (décision de Nahil, 21/08). Le nombre tombe au-dessus de la
# médiane mesurée : il garde le TIERS SUPÉRIEUR du corpus (36 %), ce qui est
# sélectif sans être impossible. Les minima de section sont posés au 33e
# percentile ; ils ne coûtent que 2 points de plus (36 % → 34 %), donc ils
# disciplinent la répartition sans devenir un second couperet.
#
# ⚠ Ce recalibrage NE TOUCHE À AUCUN autre critère de la vitrine : hiérarchie
# des sources, citations réellement appelées dans le texte, intertitres ancrés,
# nouveauté du contexte et des nuances, dépêche recyclée, chapeau ≥ 65 mots
# (déjà tenu par 85 % du corpus) restent inchangés. Boohoo échouait aussi sur
# « 0 primaire » et « sources listées mais non citées [2,3,5,7] » — ces
# reproches-là sont fondés et continuent de rejeter.
#
# ⚠ À MESURER AU PROCHAIN RUN, écrit avant et non après : la longueur cesse
# d'être le couperet, donc les rejets vitrine vont se déplacer vers les
# critères de SOURCING et de CITATION. Si le prochain run rejette encore tout,
# lire le motif — ce ne sera plus le même problème, et le remède non plus.
MIN_WORDS = {
    "faits": 135,
    "contexte": 106,
    "nuances": 91,
    "total": 400,
}
# ── 26/08 : DÉCISION DE NAHIL, APRÈS MESURE — 6 → 4 sources ────────────────
# ⚠ CE N'EST PAS UNE BAISSE POUR FAIRE DU VOLUME, et l'annulation du 24/08 avait
# raison de s'en méfier : le mandat interdit d'abaisser un seuil éditorial pour
# publier davantage. Ce qui est corrigé ici est une CONTRADICTION ARITHMÉTIQUE
# entre deux portes du même pipeline, pas un niveau d'exigence.
#
#     PERTINENCE_MIN_POUR_GENERER = 3   laisse passer un sujet à 3 sources
#                                        jugées pertinentes ;
#     MIN_SOURCES = 6                    en exigeait ensuite 6 CITÉES.
#
# Mesuré sur les 185 articles instrumentés de l'ère Mistral :
#
#     sources TROUVÉES par la recherche : médiane 10
#     sources jugées PERTINENTES        : médiane  3
#     sources CITÉES dans l'article     : médiane  5
#
#     ≥3 sources pertinentes disponibles : 131/185  (71 %)
#     ≥4                                 :  88/185  (48 %)
#     ≥6                                 :  35/185  (19 %)
#
# Dans 81 % des cas il n'existe pas 6 sources traitant le sujet PRÉCIS. Exiger
# d'en citer 6 ne peut donc produire qu'une chose : que le rédacteur cite des
# sources du thème général comme si elles documentaient le fait — le défaut
# « inflation » corrigé le 11/08, celui-là même que le juge de pertinence a été
# construit pour empêcher. L'écart médiane 5 citées / 3 pertinentes montre que
# la pression du seuil produit DÉJÀ cet effet.
#
# 4 reste AU-DESSUS de la charte (règle 7 : 3 sources) : l'intention « vitrine »
# est préservée. Le seuil devient atteignable dans 48 % des cas au lieu de 19 %.
#
# ⚠ CE QUI PROTÈGE LA QUALITÉ N'EST PAS CE COMPTE, et n'est pas touché : la
# règle « ≥1 source primaire OU ≥2 secondaires indépendantes » reste entière.
# C'est le raisonnement déjà écrit le 12/08 en abaissant le seuil des brèves de
# 4 à 3 : « la hiérarchie des sources protège la qualité, pas le compte brut ».
MIN_SOURCES = 4

# Proportion d'origine conservée : 6/5 tolérait UN domaine dupliqué, 4/3 aussi.
# Le nombre de domaines ne peut jamais dépasser le nombre de sources.
MIN_DISTINCT_DOMAINS = 3

# ── Grille BRÈVE (10/08) ─────────────────────────────────────────────────────
# Mesuré sur 24 générations : le modèle rend 271, 278, 300, 306 mots quand on
# lui en demande 600 (800 jusqu'au 10/08). Quatre articles sur quatre dans la
# même bande étroite — ce n'est pas de la variance, c'est le plafond de matière
# des sources. Avec le plancher article à 350 et la conversion en brève
# DÉSACTIVÉE en mode vitrine, ces textes étaient rejetés : d'où quatre jours
# sans publication à partir du 05/08.
#
# Un texte de 280 mots n'est pas un article de 600 mots raté, c'est une brève
# réussie. On l'accepte donc COMME BRÈVE, avec une grille propre au format —
# pas la grille article assouplie. Ce qui suit est exigeant à sa mesure :
#   · chapeau + faits ≥ 125 mots au TOTAL, faits ≥ 100, chapeau ≥ 15.
#     RECALIBRÉ le 12/08 sur les 12 brèves réellement publiées, mesurées une à
#     une plutôt qu'estimées :
#         chapeau   min 15   médiane 20   max 50
#         faits     min 95   médiane 119  max 149
#         total     min 111  médiane 146  max 182
#     Les seuils précédents (20 / 110 / 140) rejetaient SIX de ces douze brèves
#     — la moitié de ce que le journal avait jugé publiable — pendant que le
#     site ne publiait plus rien depuis sept jours. Erreur de calibrage de ma
#     part : je les avais posés sur le haut de la distribution en croyant les
#     poser « à la mesure du format ». Les seuils actuels écartent le tiers
#     inférieur et gardent les huit meilleures ;
#   · chapeau d'UNE phrase, conforme au SYSTEM_PROMPT_BREVE. La conversion
#     depuis un article ne garde que la première phrase du chapeau à trois
#     phrases — c'est elle qui entre dans le fait principal (règle 4). Cela
#     retire 30 à 35 mots au total, ce que les seuils ci-dessus intègrent ;
#   · contexte et nuances VIDES — c'est la définition du format, pas une
#     dispense : une brève qui les remplit n'est pas une brève ;
#   · 3 URLs et 3 domaines distincts — la charte exige 3 sources pour la brève
#     comme pour l'article ; exiger davantage ici serait plus strict qu'elle ;
#   · même hiérarchie de sources et même contrôle de dépêche recyclée que
#     l'article : plus court ne veut pas dire moins sourcé.
MIN_WORDS_BREVE = {"total": 125, "faits": 100, "resume": 15}
# 4 → 3 (12/08). La charte exige 3 sources pour une brève ET pour un article ;
# exiger 4 ici était plus strict que la charte elle-même, sans mesure pour le
# justifier. Deux sujets du run du 12/08 ont été refusés sur « 3 URL distinctes,
# minimum 4 » alors qu'ils respectaient la règle éditoriale. La hiérarchie des
# sources (≥1 primaire OU ≥2 secondaires) reste, elle, inchangée : c'est elle
# qui protège la qualité, pas le compte brut.
MIN_SOURCES_BREVE = 3
MIN_DISTINCT_DOMAINS_BREVE = 3

_GENERIC_HEADINGS = {
    "les faits", "faits", "contexte", "le contexte", "debat et nuances",
    "debats et nuances", "nuances", "les nuances", "ce qu il faut savoir",
    "a retenir", "en bref", "pour comprendre", "ce qui change",
}
_GENERIC_ANGLES = (
    "que s est il passe", "que faut il savoir", "de quoi s agit il",
    "qu est ce que cela signifie", "pourquoi est ce important",
)
_STOPWORDS = {
    "alors", "apres", "avec", "avoir", "avant", "chez", "comme", "dans",
    "depuis", "devant", "elle", "elles", "entre", "etre", "fait", "faire",
    "leurs", "mais", "meme", "pour", "sans", "selon", "sous", "tout",
    "toute", "toutes", "vers", "plus", "moins", "cette", "ceux", "cela",
    "celui", "celle", "dont", "ainsi", "aussi", "encore", "peut", "doit",
    "devrait", "article", "annonce", "actualite", "information", "resultat",
}
_FILLER_RE = re.compile(
    r"\b(?:il est important de noter|dans les années à venir|pourrait révolutionner|"
    r"pourrait avoir des implications|suscite l['’]intérêt|"
    r"des recherches supplémentaires sont nécessaires|"
    r"il reste difficile de prévoir|seul l['’]avenir dira|"
    r"la situation reste complexe|les experts sont partagés)\b",
    re.I,
)
_PRIMARY_SUFFIXES = (
    ".gouv.fr", ".gov", ".europa.eu", ".int", "elysee.fr",
    "assemblee-nationale.fr", "senat.fr", "vie-publique.fr",
    "insee.fr", "banque-france.fr", "has-sante.fr", "anses.fr",
    "ansm.sante.fr", "meteofrance.fr", "ined.fr", "cnrs.fr", "inserm.fr",
    "inrae.fr", "cea.fr", "ademe.fr", "pasteur.fr",
    "santepubliquefrance.fr", "nasa.gov", "esa.int", "cern.ch", "cnes.fr",
    "nature.com", "science.org", "thelancet.com", "nejm.org", "bmj.com",
    "ncbi.nlm.nih.gov", "pubmed.gov", "cell.com", "pnas.org",
    "courdecassation.fr", "conseil-etat.fr", "ccomptes.fr", "oecd.org",
    "ipcc.ch", "imf.org", "worldbank.org", "fao.org", "unesco.org",
    "ilo.org", "cnil.fr", "arcom.fr", "autoritedelaconcurrence.fr",
)
_SECONDARY_DOMAINS = (
    "afp.com", "reuters.com", "apnews.com", "lemonde.fr", "lefigaro.fr",
    "liberation.fr", "lesechos.fr", "leparisien.fr", "lepoint.fr",
    "lexpress.fr", "nouvelobs.com", "mediapart.fr", "la-croix.com",
    "ouest-france.fr", "sudouest.fr", "20minutes.fr", "francetvinfo.fr",
    "franceinfo.fr", "france24.com", "rfi.fr", "radiofrance.fr",
    "bbc.com", "theguardian.com", "nytimes.com", "washingtonpost.com",
    "letemps.ch", "rts.ch", "lesoir.be", "rtbf.be", "theconversation.com",
    "sciencesetavenir.fr", "pourlascience.fr", "numerama.com", "novethic.fr",
    "courrierinternational.com", "slate.fr", "factuel.afp.com",
    "fullfact.org", "correctiv.org", "snopes.com", "politifact.com",
)


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFD", str(text or ""))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.lower().replace("’", "'")
    text = re.sub(r"[^a-z0-9' ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\wÀ-ÿ'-]+\b", str(text or ""), re.UNICODE))


def _tokens(text: str) -> set[str]:
    return {
        word[:10] for word in re.findall(r"[a-z0-9]+", _norm(text))
        if len(word) >= 4 and word not in _STOPWORDS
    }


def _novelty(section: str, previous: str) -> float:
    current = _tokens(section)
    before = _tokens(previous)
    if not current:
        return 0.0
    return len(current - before) / len(current)


def _paragraph_count(text: str) -> int:
    """Compte les paragraphes comme le RENDU les compte : sur un \n simple.

    ── 26/08 : la vitrine exigeait une convention que personne n'utilise ─────
    Run 279 : les deux seuls articles ayant passé le fact-check ont été rejetés
    sur « faits / contexte / nuances insuffisamment aéré (1 paragraphe) ». Or
    ils étaient correctement découpés. Trois composants, deux conventions :

        prompt de génération   « insère un \n entre chaque paragraphe »   simple
        build_article_html     .replace("\n", "</p><p>")                  simple
        vitrine                re.split(r"\n\s*\n")                      DOUBLE

    La vitrine était la seule à réclamer une ligne vide. Le modèle faisait
    exactement ce qu'on lui demandait, le site l'affichait correctement, et la
    grille comptait 1 paragraphe faute de trouver la ligne vide qu'elle seule
    attendait.

    MESURE avant correction, sur 60 articles publiés : tous rendent 3 à 5
    paragraphes (médiane 5) — le \n simple fonctionne depuis toujours. C'était
    donc bien la vitrine qui était fausse, pas la rédaction.

    On garde la coupe sur ligne vide EN PLUS du \n simple : un modèle qui
    doublerait les sauts de ligne ne doit pas voir ses paragraphes comptés en
    double, et `split` sur \n suivi du filtre des vides s'en charge.
    """
    text = str(text or "").strip()
    if not text:
        return 0
    paragraphs = [p for p in re.split(r"[\r\n]+", text) if p.strip()]
    return len(paragraphs)


def _canonical_url(url: str) -> str:
    try:
        parts = urlsplit(str(url or ""))
        host = parts.netloc.lower().removeprefix("www.")
        path = re.sub(r"/+$", "", parts.path)
        return urlunsplit((parts.scheme.lower() or "https", host, path, "", ""))
    except Exception:
        return str(url or "").split("?", 1)[0].split("#", 1)[0].rstrip("/")


def _host(url: str) -> str:
    try:
        return (urlsplit(str(url or "")).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _source_quality(url: str) -> str:
    host = _host(url)
    if any(host == suffix.lstrip(".") or host.endswith(suffix) for suffix in _PRIMARY_SUFFIXES):
        return "primaire"
    if any(host == domain or host.endswith("." + domain) for domain in _SECONDARY_DOMAINS):
        return "secondaire"
    return "tertiaire"


def _valid_heading(heading: str, section: str) -> bool:
    heading = str(heading or "").strip()
    words = heading.split()
    norm = _norm(heading)
    if not 4 <= len(words) <= 12 or len(heading) > 96:
        return False
    if norm in _GENERIC_HEADINGS or heading.endswith(("?", "!", ".")):
        return False
    heading_tokens = _tokens(heading)
    section_tokens = _tokens(section)
    return bool(heading_tokens and len(heading_tokens & section_tokens) >= 1)


def _max_cross_similarity(section: str, previous: str) -> float:
    def sentences(text: str) -> list[str]:
        return [
            _norm(sentence) for sentence in re.split(r"(?<=[.!?…])\s+", str(text or ""))
            if _word_count(sentence) >= 10
        ]

    current = sentences(section)
    before = sentences(previous)
    if not current or not before:
        return 0.0
    return max(SequenceMatcher(None, a, b).ratio() for a in current for b in before)


def _source_title_similarity(sources: list[dict]) -> float:
    titles = [_norm(s.get("titre") or s.get("title") or "") for s in sources]
    titles = [title for title in titles if _word_count(title) >= 5]
    if len(titles) < 3:
        return 0.0
    ratios = [
        SequenceMatcher(None, titles[i], titles[j]).ratio()
        for i in range(len(titles)) for j in range(i + 1, len(titles))
    ]
    return sum(ratios) / len(ratios) if ratios else 0.0


def _valider_breve(art: dict) -> tuple[bool, list[str]]:
    """Grille vitrine du format BRÈVE — exigeante à sa mesure, pas allégée.

    Les contrôles partagés avec l'article sont conservés à l'identique :
    hiérarchie des sources, détection de dépêche recyclée, remplissage,
    cohérence du compteur, citations numérotées dans le texte. Seuls changent
    les seuils de longueur et de structure, parce que le format n'a ni
    contexte, ni nuances, ni angle-question.
    """
    reasons: list[str] = []

    title = str(art.get("titre") or "").strip()
    tw = _word_count(title)
    if not 6 <= tw <= 15 or title.endswith(("?", "!")):
        reasons.append(f"titre non vitrine ({tw} mots ou ponctuation inadéquate)")

    resume = art.get("resume") or []
    resume_list = resume if isinstance(resume, list) else [resume]
    if len(resume_list) != 1:
        reasons.append(f"chapeau de brève : {len(resume_list)} phrase(s) au lieu d'une")
    resume_text = " ".join(str(x) for x in resume_list).strip()
    if _word_count(resume_text) < MIN_WORDS_BREVE["resume"]:
        reasons.append(f"chapeau trop court ({_word_count(resume_text)} mots, "
                       f"minimum {MIN_WORDS_BREVE['resume']})")

    body = art.get("corps") or {}
    facts = str(body.get("faits") or "").strip()
    mots_faits = _word_count(facts)
    mots_total = mots_faits + _word_count(resume_text)
    if mots_faits < MIN_WORDS_BREVE["faits"]:
        reasons.append(f"faits trop court ({mots_faits} mots, "
                       f"minimum vitrine {MIN_WORDS_BREVE['faits']})")
    if mots_total < MIN_WORDS_BREVE["total"]:
        reasons.append(f"brève trop courte ({mots_total} mots chapeau + faits, "
                       f"minimum vitrine {MIN_WORDS_BREVE['total']})")
    # Une brève qui remplit contexte/nuances n'est pas une brève : le rendu HTML
    # ne les affiche pas, le lecteur ne les verrait jamais.
    for cle in ("contexte", "nuances"):
        if str(body.get(cle) or "").strip():
            reasons.append(f"une brève ne doit pas remplir « {cle} »")

    if _FILLER_RE.search(resume_text + " " + facts):
        reasons.append("formule générique ou remplissage détecté")
    if _max_cross_similarity(resume_text, facts) >= 0.84:
        reasons.append("le chapeau répète presque la première phrase des faits")

    sources = [s for s in (art.get("sources") or []) if isinstance(s, dict)]
    urls = [u for u in (_canonical_url(s.get("url") or "") for s in sources) if u]
    distinct_urls = set(urls)
    domains = {_host(u) for u in distinct_urls if _host(u)}
    if len(distinct_urls) < MIN_SOURCES_BREVE:
        reasons.append(f"sourcing trop court ({len(distinct_urls)} URL distinctes, "
                       f"minimum {MIN_SOURCES_BREVE})")
    if len(domains) < MIN_DISTINCT_DOMAINS_BREVE:
        reasons.append(f"sourcing trop concentré ({len(domains)} domaines distincts)")

    q = {"primaire": 0, "secondaire": 0, "tertiaire": 0}
    for u in distinct_urls:
        q[_source_quality(u)] += 1
    if not (q["primaire"] >= 1 or q["secondaire"] >= 2):
        reasons.append(f"hiérarchie des sources insuffisante "
                       f"({q['primaire']} primaire, {q['secondaire']} secondaires)")
    similarite = _source_title_similarity(sources)
    if similarite >= 0.80 and q["primaire"] == 0:
        reasons.append(f"sources probablement dérivées d'une même dépêche ({similarite:.0%})")

    # Les citations numérotées [n] sont le format des ARTICLES (05/08). Une
    # brève NATIVE attribue en prose (« Selon X, Y et Z », règle 6 de
    # SYSTEM_PROMPT_BREVE) et n'en contient légitimement aucune. Exiger un
    # minimum d'appels de note imposait donc à un des deux chemins le style de
    # l'autre — deux refus sur « 0 appels de note » le 12/08. On vérifie que
    # celles qui existent sont valides, on n'en exige pas un nombre.
    citations = [int(n) for n in re.findall(r"\[(\d+)\]", resume_text + " " + facts)]
    if any(n < 1 or n > len(sources) for n in citations):
        reasons.append("citation numérotée hors de la liste des sources")

    declared = art.get("nb_sources")
    if declared is not None and int(declared or 0) != len(sources):
        reasons.append(f"compteur de sources incohérent ({declared} déclaré, {len(sources)} listées)")

    return not reasons, reasons


def validate_generated_article(art: dict, article_type: str) -> tuple[bool, list[str]]:
    """Valide un article final avant son écriture sur disque.

    Le mode vitrine ne publie que des ACTU longues : les dossiers utilisent
    encore d'anciens prompts et les brèves ne démontrent pas la profondeur
    recherchée. Le pipeline poursuit simplement avec le candidat suivant.
    """
    reasons: list[str] = []
    if article_type == "breve":
        return _valider_breve(art)
    if article_type != "actu":
        reasons.append(f"format {article_type!r} exclu du lot vitrine")
        return False, reasons

    title = str(art.get("titre") or "").strip()
    title_words = _word_count(title)
    if not 8 <= title_words <= 15 or title.endswith(("?", "!")):
        reasons.append(f"titre non vitrine ({title_words} mots ou ponctuation inadéquate)")

    angle = str(art.get("angle_reponse") or "").strip()
    angle_norm = _norm(angle)
    if _word_count(angle) < 8 or not angle.endswith("?"):
        reasons.append("angle lecteur absent ou insuffisamment précis")
    if any(generic in angle_norm for generic in _GENERIC_ANGLES):
        reasons.append("angle lecteur générique et interchangeable")

    resume = art.get("resume") or []
    if not isinstance(resume, list) or len(resume) != 3:
        reasons.append("résumé non structuré en trois phrases distinctes")
        resume_text = str(resume or "")
    else:
        resume_text = " ".join(str(x) for x in resume)
        if _word_count(resume_text) < 65:
            reasons.append("résumé trop mince pour annoncer fait, enjeu et limite")

    body = art.get("corps") or {}
    facts = str(body.get("faits") or "").strip()
    context = str(body.get("contexte") or "").strip()
    nuances = str(body.get("nuances") or "").strip()
    counts = {
        "faits": _word_count(facts),
        "contexte": _word_count(context),
        "nuances": _word_count(nuances),
    }
    counts["total"] = counts["faits"] + counts["contexte"] + counts["nuances"]
    for key, minimum in MIN_WORDS.items():
        if counts[key] < minimum:
            reasons.append(f"{key} trop court ({counts[key]} mots, minimum vitrine {minimum})")

    for key, section, minimum_paragraphs in (
        ("faits", facts, 3), ("contexte", context, 2), ("nuances", nuances, 2),
    ):
        paragraphs = _paragraph_count(section)
        if paragraphs < minimum_paragraphs:
            reasons.append(f"{key} insuffisamment aéré ({paragraphs} paragraphe(s))")

    context_novelty = _novelty(context, facts)
    nuances_novelty = _novelty(nuances, facts + " " + context)
    if context_novelty < 0.34:
        reasons.append(f"contexte trop proche des faits ({context_novelty:.0%} de matière nouvelle)")
    if nuances_novelty < 0.38:
        reasons.append(f"nuances trop proches du reste ({nuances_novelty:.0%} de matière nouvelle)")
    if _max_cross_similarity(context, facts) >= 0.84:
        reasons.append("une phrase du contexte répète presque les faits")
    if _max_cross_similarity(nuances, facts + " " + context) >= 0.84:
        reasons.append("une phrase des nuances répète presque une section précédente")

    if _FILLER_RE.search(resume_text + " " + facts + " " + context + " " + nuances):
        reasons.append("formule générique ou remplissage détecté")

    headings = {
        "faits": str(art.get("titre_faits") or ""),
        "contexte": str(art.get("titre_contexte") or ""),
        "nuances": str(art.get("titre_nuances") or ""),
    }
    for key, section in (("faits", facts), ("contexte", context), ("nuances", nuances)):
        if not _valid_heading(headings[key], section):
            reasons.append(f"intertitre {key} absent, générique ou non ancré dans la section")

    sources = [s for s in (art.get("sources") or []) if isinstance(s, dict)]
    urls = [_canonical_url(s.get("url") or "") for s in sources]
    urls = [url for url in urls if url]
    distinct_urls = set(urls)
    domains = {_host(url) for url in distinct_urls if _host(url)}
    if len(distinct_urls) < MIN_SOURCES:
        reasons.append(f"sourcing trop court ({len(distinct_urls)} URL distinctes, minimum {MIN_SOURCES})")
    if len(domains) < MIN_DISTINCT_DOMAINS:
        reasons.append(f"sourcing trop concentré ({len(domains)} domaines distincts)")

    quality_counts = {"primaire": 0, "secondaire": 0, "tertiaire": 0}
    for url in distinct_urls:
        quality_counts[_source_quality(url)] += 1
    strong_sourcing = (
        quality_counts["primaire"] >= 1 and quality_counts["secondaire"] >= 2
    ) or quality_counts["secondaire"] >= 5
    if not strong_sourcing:
        reasons.append(
            "hiérarchie des sources insuffisante "
            f"({quality_counts['primaire']} primaire, {quality_counts['secondaire']} secondaires)"
        )

    similarity = _source_title_similarity(sources)
    if similarity >= 0.80 and quality_counts["primaire"] == 0:
        reasons.append(f"sources probablement dérivées d'une même dépêche ({similarity:.0%})")

    full_text = " ".join((resume_text, facts, context, nuances))
    citations = [int(n) for n in re.findall(r"\[(\d+)\]", full_text)]
    cited = set(citations)
    expected = set(range(1, len(sources) + 1))
    if any(n < 1 or n > len(sources) for n in cited):
        reasons.append("citation numérotée hors de la liste des sources")
    if expected and cited != expected:
        missing = sorted(expected - cited)
        reasons.append(f"sources listées mais non citées dans le texte : {missing[:6]}")
    if len(citations) < 10:
        reasons.append(f"maillage de citations trop faible ({len(citations)} appels de note)")
    for key, section in (("faits", facts), ("contexte", context), ("nuances", nuances)):
        if not re.search(r"\[\d+\]", section):
            reasons.append(f"section {key} sans citation numérotée")

    declared = art.get("nb_sources")
    if declared is not None and int(declared or 0) != len(sources):
        reasons.append(f"compteur de sources incohérent ({declared} déclaré, {len(sources)} listées)")

    return not reasons, reasons
