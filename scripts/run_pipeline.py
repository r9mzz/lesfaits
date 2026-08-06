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


def _prepared_pipeline_source() -> str:
    """Prépare le pipeline historique avec une attente TPD adaptée aux crons.

    Le remplacement reste volontairement strict : si le marqueur change ou est
    dupliqué, le run échoue avant tout appel API au lieu d'exécuter une version
    dont la protection quota serait ambiguë.
    """
    if not 15 <= GROQ_WAIT_MAX_MINUTES <= 180:
        raise ValueError(
            "GROQ_WAIT_MAX_MINUTES doit rester compris entre 15 et 180 minutes"
        )

    source = PIPELINE.read_text(encoding="utf-8")
    marker = "ATTENTE_MAX_LIBERATION = 15 * 60"
    if source.count(marker) != 1:
        raise RuntimeError(
            "Marqueur ATTENTE_MAX_LIBERATION introuvable ou dupliqué dans pipeline.py"
        )

    replacement = f"ATTENTE_MAX_LIBERATION = {GROQ_WAIT_MAX_MINUTES} * 60"
    prepared = source.replace(marker, replacement, 1)
    compile(prepared, str(PIPELINE), "exec")
    print(
        f"[PRÉVOL] Attente maximale d'une libération Groq : "
        f"{GROQ_WAIT_MAX_MINUTES} min"
    )
    return prepared


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