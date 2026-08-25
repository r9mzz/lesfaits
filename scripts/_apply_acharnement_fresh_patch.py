from pathlib import Path

pipeline = Path("scripts/pipeline.py")
text = pipeline.read_text(encoding="utf-8")

anchor = '''def filtrer_et_classer(\n    items: list[dict],\n'''
helper = '''def _titre_est_condamne(titre: str, condamnes: set[str]) -> bool:\n    \"\"\"Même dossier qu'un sujet déjà condamné, avec la règle de diversité existante.\n\n    L'égalité exacte reste le chemin certain et rapide. Pour une reformulation,\n    on réutilise strictement `_mots_distinctifs` + `DIVERSITE_MOTS_COMMUNS`,\n    déjà calibrés et utilisés pour regrouper les rejets historiques.\n    \"\"\"\n    cle = _titre_norme(titre)\n    if cle in condamnes:\n        return True\n    mots = _mots_distinctifs(titre)\n    if not mots:\n        return False\n    return any(\n        len(mots & _mots_distinctifs(condamne)) >= DIVERSITE_MOTS_COMMUNS\n        for condamne in condamnes\n    )\n\n\n'''
if helper not in text:
    if anchor not in text:
        raise SystemExit("anchor helper introuvable")
    text = text.replace(anchor, helper + anchor, 1)

old = '        if _titre_norme(item.get("title", "")) in condamnes:\n'
new = '        if _titre_est_condamne(item.get("title", ""), condamnes):\n'
if new not in text:
    if old not in text:
        raise SystemExit("condition anti-acharnement introuvable")
    text = text.replace(old, new, 1)

pipeline.write_text(text, encoding="utf-8")
