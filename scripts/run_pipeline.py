# -*- coding: utf-8 -*-
"""Point d'entrée renforcé du pipeline Les Faits.

Il ajoute une consigne rédactionnelle spécialisée aux appels de génération,
consolide les retraits déclarés, exécute le pipeline historique sans le
dupliquer, puis lance les gardes éditoriaux sur les SEULS nouveaux articles.
"""
from __future__ import annotations

import copy
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PIPELINE = ROOT / "scripts" / "pipeline.py"

# Le pipeline historique n'attend que 15 minutes quand toutes les clés Groq
# sont temporairement au plafond TPD. Or le quota est une fenêtre glissante de
# 24 h et les crons GitHub peuvent être décalés de plusieurs heures d'un jour à
# l'autre : une clé consommée à 15 h la veille peut encore être bloquée lors
# d'un départ à 13 h le lendemain. Le budget global de génération reste borné à
# 4 h dans pipeline.py et le job GitHub à 5 h ; 150 minutes laissent donc encore
# au moins 90 minutes pour produire quelques articles solides plutôt que rendre
# immédiatement un lot vide.
GROQ_WAIT_MAX_MINUTES = int(os.getenv("GROQ_WAIT_MAX_MINUTES", "150"))

# Mode démonstrateur : continuer à tester les candidats jusqu'à obtenir au plus
# deux articles qui passent la grille stricte de showcase_quality.py. Ce plafond
# porte sur les articles réellement acceptés, pas sur le nombre de tentatives.
MAX_SHOWCASE_PUBLICATIONS = int(os.getenv("MAX_SHOWCASE_PUBLICATIONS", "2"))

EDITORIAL_ADDENDUM = r"""

CONSIGNE PREMIUM DE LISIBILITÉ — PRIORITÉ ABSOLUE :
- Un article intéressant n'est pas un article spectaculaire : il apporte des détails précis,
  une chronologie nette, des comparaisons utiles et des conséquences déjà établies par les sources.
- Chaque paragraphe doit faire avancer la compréhension. Supprime toute phrase générique,
  toute conclusion vide et toute répétition, y compris entre le résumé et le corps.
- Le résumé annonce le fait central une seule fois. « Les faits » établit ce qui s'est passé.
  « Contexte » explique uniquement ce qui permet de comprendre cet événement précis.
  « Nuances » expose uniquement une limite, une incertitude ou un désaccord réellement documenté.
  Une section sans matière distincte doit rester vide plutôt que d'être remplie.
- Chronologie obligatoire : choisis l'état le plus récent établi par les sources. Ne mélange jamais
  « devait/va/sera » et « a eu lieu/s'est produit » pour le même événement sans expliquer la transition.
- Ne qualifie jamais un fait d'« inédit », « historique », « record », « majeur » ou
  « révolutionnaire » si une source autorisée ne l'établit pas explicitement.
- Évite les titres télégraphiques. Écris un français naturel avec les articles et prépositions nécessaires.
- Quand plusieurs sources établissent la même affirmation, fusionne-les dans une attribution unique.
  Ne construis jamais une succession mécanique « Selon X… D'après Y… Selon Z… ».
- La neutralité n'est pas l'abstention : tu peux écrire qu'une affirmation n'est pas étayée si une
  source de vérification ou les données fournies l'établissent explicitement, en attribuant ce constat.
- N'ajoute aucun fait absent de la matière fournie. La précision prime toujours sur la longueur.

MODE VITRINE — LA SORTIE DOIT POUVOIR ÊTRE PUBLIÉE SANS RÉSERVE :
- Utilise AU MOINS 6 sources distinctes, réparties sur AU MOINS 5 domaines.
  Privilégie au moins 1 source primaire et 2 médias de référence ; à défaut,
  utilise au moins 5 médias de référence indépendants. Toutes les sources
  présentes dans le tableau final doivent être réellement appelées par une note [n].
- Le corps doit contenir au minimum 420 mots de faits, 180 mots de contexte et
  130 mots de nuances, en plusieurs paragraphes. Si la matière ne permet pas
  trois sections substantielles et réellement différentes, réponds uniquement
  HORS_PERIMETRE au lieu de remplir ou d'étirer le texte.
- Les trois intertitres éditoriaux sont obligatoires, spécifiques au sujet et
  ancrés dans leur section. « Les faits », « Contexte », « À retenir » ou tout
  autre libellé générique sont interdits.
- L'angle_reponse doit être une vraie question de lecteur, précise et non
  interchangeable. Le résumé doit comporter exactement trois phrases : fait,
  enjeu, puis limite ou incertitude.
- Répartis au moins 10 appels de notes [n] dans l'ensemble du texte. Une note
  ne remplace pas la synthèse : plusieurs sources qui établissent le même fait
  restent groupées sur une seule phrase.
"""


def _article_slugs(root: Path = ROOT) -> set[str]:
    articles_dir = root / "articles"
    if not articles_dir.exists():
        return set()
    return {path.stem for path in articles_dir.glob("*.html")}


def _generated_article_paths(before: set[str], root: Path = ROOT) -> set[Path]:
    """Retourne uniquement les fichiers créés pendant CE run.

    ``pipeline.py`` met à jour le bloc « à lire aussi » de nombreux anciens
    articles à chaque reconstruction. Leur présence dans ``git status`` ne doit
    jamais les faire passer pour des articles neufs. Les stubs de consolidation
    sont également créés avant la photographie ``before`` et sont donc exclus.
    """
    after = _article_slugs(root)
    return {
        (root / "articles" / f"{slug}.html").resolve()
        for slug in after - before
    }


def _patch_groq_generation_prompt() -> None:
    """Intercepte uniquement le prompt de rédaction, jamais le fact-checker."""
    try:
        import groq
    except Exception:
        return

    original = groq.Groq

    class _CompletionsProxy:
        def __init__(self, wrapped):
            self._wrapped = wrapped

        def create(self, *args, **kwargs):
            messages = kwargs.get("messages")
            if isinstance(messages, list):
                patched = copy.deepcopy(messages)
                for message in patched:
                    if message.get("role") != "system":
                        continue
                    content = message.get("content")
                    if not isinstance(content, str):
                        continue
                    is_writer = (
                        "IA rédactrice de Les Faits" in content
                        or "journal numérique français indépendant" in content
                    )
                    is_checker = "fact-checker" in content.lower()
                    if is_writer and not is_checker and "CONSIGNE PREMIUM DE LISIBILITÉ" not in content:
                        message["content"] = content + EDITORIAL_ADDENDUM
                kwargs["messages"] = patched
            return self._wrapped.create(*args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._wrapped, name)

    class _ChatProxy:
        def __init__(self, wrapped):
            self._wrapped = wrapped
            self.completions = _CompletionsProxy(wrapped.completions)

        def __getattr__(self, name):
            return getattr(self._wrapped, name)

    class _ClientProxy:
        def __init__(self, wrapped):
            self._wrapped = wrapped
            self.chat = _ChatProxy(wrapped.chat)

        def __getattr__(self, name):
            return getattr(self._wrapped, name)

    def patched_groq(*args, **kwargs):
        return _ClientProxy(original(*args, **kwargs))

    groq.Groq = patched_groq


def _replace_once(source: str, marker: str, replacement: str, label: str) -> str:
    """Remplacement strict : jamais de patch silencieux sur une autre version."""
    if source.count(marker) != 1:
        raise RuntimeError(f"Marqueur {label} introuvable ou dupliqué dans pipeline.py")
    return source.replace(marker, replacement, 1)


def _prepared_pipeline_source() -> str:
    """Prépare le pipeline historique pour un run qualité-first.

    Trois adaptations sont appliquées sans modifier le fichier historique :
    attente du quota glissant, grille vitrine avant écriture HTML, puis arrêt
    après le nombre demandé d'articles réellement acceptés.
    """
    if not 15 <= GROQ_WAIT_MAX_MINUTES <= 180:
        raise ValueError(
            "GROQ_WAIT_MAX_MINUTES doit rester compris entre 15 et 180 minutes"
        )
    if not 1 <= MAX_SHOWCASE_PUBLICATIONS <= 3:
        raise ValueError(
            "MAX_SHOWCASE_PUBLICATIONS doit rester compris entre 1 et 3"
        )

    source = PIPELINE.read_text(encoding="utf-8")
    source = _replace_once(
        source,
        "ATTENTE_MAX_LIBERATION = 15 * 60",
        f"ATTENTE_MAX_LIBERATION = {GROQ_WAIT_MAX_MINUTES} * 60",
        "ATTENTE_MAX_LIBERATION",
    )

    html_marker = "        try:\n            html = build_article_html(art, date_pub)"
    showcase_guard = """        from showcase_quality import validate_generated_article
        _showcase_ok, _showcase_reasons = validate_generated_article(art, article_type)
        if not _showcase_ok:
            print("     [REJET VITRINE] " + " ; ".join(_showcase_reasons))
            return False
        print(
            f"     [VITRINE] ✓ article admis : {art.get('nb_mots', 0)} mots, "
            f"{len(art.get('sources') or [])} sources"
        )

        try:
            html = build_article_html(art, date_pub)"""
    source = _replace_once(source, html_marker, showcase_guard, "garde vitrine")

    cap_marker = '                    published_topics.add(item.get("title", ""))'
    cap_replacement = cap_marker + f"""
                    if len(new_pub) >= {MAX_SHOWCASE_PUBLICATIONS}:
                        print(
                            "  [VITRINE] Objectif atteint : "
                            f"{{len(new_pub)}} article(s) premium accepté(s)."
                        )
                        break"""
    source = _replace_once(source, cap_marker, cap_replacement, "plafond vitrine")

    compile(source, str(PIPELINE), "exec")
    print(
        f"[PRÉVOL] Attente Groq : {GROQ_WAIT_MAX_MINUTES} min ; "
        f"objectif vitrine : {MAX_SHOWCASE_PUBLICATIONS} article(s) maximum"
    )
    return source


def _run_legacy_pipeline() -> None:
    old_argv0 = sys.argv[0]
    sys.argv[0] = str(PIPELINE)
    namespace = {
        "__name__": "__main__",
        "__file__": str(PIPELINE),
        "__package__": None,
        "__cached__": None,
    }
    try:
        try:
            source = _prepared_pipeline_source()
            exec(compile(source, str(PIPELINE), "exec"), namespace)
        except SystemExit as exc:
            if exc.code not in (None, 0):
                raise
    finally:
        sys.argv[0] = old_argv0


def main() -> int:
    os.chdir(ROOT)
    args = set(sys.argv[1:])

    retirement = {"changed": False}
    # Un dry-run doit rester totalement sans effet de bord. Tous les autres
    # modes appliquent les consolidations avant que le pipeline reconstruise
    # ses index ou sélectionne de nouveaux sujets.
    if "--dry-run" not in args:
        from apply_retirements import apply_retirements
        retirement = apply_retirements(ROOT)

    # Photographie APRÈS consolidation et AVANT génération : les gardes ne
    # contrôleront que les nouveaux fichiers, jamais les anciens articles dont
    # le bloc de bas de page a été rafraîchi pendant le rebuild.
    article_slugs_before = _article_slugs(ROOT)

    _patch_groq_generation_prompt()
    _run_legacy_pipeline()

    if "--dry-run" in args or "--rebuild" in args:
        return 0

    generated_paths = _generated_article_paths(article_slugs_before, ROOT)
    print(f"[GARDE ÉDITORIAL] {len(generated_paths)} fichier(s) réellement nouveau(x) à contrôler.")

    import editorial_quality
    import editorial_depth

    # Les deux modules gardent un repli basé sur git status pour leur usage
    # autonome. Dans le vrai pipeline, on impose la liste exacte calculée ici.
    editorial_quality._changed_article_paths = lambda: set(generated_paths)
    quality = editorial_quality.process_generated_articles(ROOT)

    # Un article rejeté par le premier garde n'existe plus : ne pas le reparcourir.
    editorial_depth._changed_article_paths = lambda: {
        path for path in generated_paths if path.exists()
    }
    depth = editorial_depth.process_editorial_depth(ROOT)

    if retirement.get("changed") or quality.get("needs_rebuild") or depth.get("needs_rebuild"):
        print("[GARDE ÉDITORIAL] Reconstruction des pages après consolidation/retrait…")
        subprocess.run(
            [sys.executable, str(PIPELINE), "--rebuild"],
            cwd=ROOT, check=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
