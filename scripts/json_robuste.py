# -*- coding: utf-8 -*-
"""Lecture tolérante du JSON rendu par un modèle — partagé génération/vérification.

Cette fonction vivait dans `pipeline.py` seul. Le run du 19/08 a montré le
coût de cette asymétrie : la génération lisait correctement le JSON de
Mistral, le fact-checker échouait sur `Expecting ',' delimiter` — même défaut,
un seul des deux extracteurs corrigé. Trois articles ayant passé toute la
chaîne éditoriale ont été perdus ainsi, en `erreur_verification`.

Elle est donc ici, importée par les deux, pour qu'un correctif ne puisse plus
ne profiter qu'à un seul appelant. Aucun cycle d'import : ce module ne dépend
de rien.
"""


def _echapper_controles_json(texte: str) -> str:
    """Échappe les caractères de contrôle bruts À L'INTÉRIEUR des chaînes JSON.

    ── DÉFAUT TROUVÉ LE 18/08, et il vient de NOUS ───────────────────────────

    La norme JSON (RFC 8259) interdit un saut de ligne littéral dans une
    chaîne : il doit être écrit `\n`. Or le prompt exige depuis le 15/08 une
    MISE EN PARAGRAPHES du corps de l'article — on demande donc explicitement
    au modèle de produire ce qui casse notre propre lecture.

    Llama 3.3 échappait ces sauts de ligne ; Mistral les écrit tels quels. La
    conséquence est silencieuse et coûteuse : `json.loads` échoue, le repli
    remonte jusqu'au dernier préfixe parsable, et l'article revient amputé de
    `corps` et de `sources`. Mesuré sur l'essai Mistral du 18/08 —
    `fin=stop`, 1 583 tokens produits, ~250 tokens récupérés : le texte avait
    été écrit, il était perdu à la lecture.

    On ne peut pas se contenter d'un `replace("\n", "\\n")` global : cela
    corromprait la mise en forme du JSON lui-même. On suit donc l'état
    « dans une chaîne ou non », en tenant compte des guillemets échappés.
    """
    out = []
    dans_chaine = False
    echappe = False
    for c in texte:
        if echappe:
            out.append(c)
            echappe = False
            continue
        if c == "\\":
            out.append(c)
            echappe = dans_chaine
            continue
        if c == '"':
            dans_chaine = not dans_chaine
            out.append(c)
            continue
        if dans_chaine and c in "\n\r\t":
            out.append({"\n": "\\n", "\r": "\\r", "\t": "\\t"}[c])
            continue
        out.append(c)
    return "".join(out)
