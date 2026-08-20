"""Les plafonds de matière étaient ceux de Groq, pas les nôtres.

── CONSTAT DE NAHIL, 20/08, en comparant avec Le Courrier de France ──────────

Leur article sur le piratage du fisc cite CINQ sources — moins que nos dix — et
fait ~1 000 mots. La différence n'est pas le nombre de sources, c'est ce qu'ils
LISENT de chacune : la page entière, quand nous n'injections que 950 caractères,
soit environ 150 mots.

On ne peut pas écrire 900 mots à partir de 150 mots de matière par source. La
brièveté de nos articles était une contrainte d'ENTRÉE, pas un défaut de
rédaction — troisième fois que ce projet attribue au modèle ce qui venait d'un
budget (après la famine de complétion du 15/08 et le guillemet du 19/08).

Ces plafonds — 950 caractères d'extrait, 7 000 de contenu, 20 sujets par run —
ont tous été fixés pour la fenêtre de 12 000 tokens et le TPD de 100 000 de
Groq. Ils survivaient à un fournisseur qu'on a quitté, comme les clés réservées
au fact-check et la borne 11 500 du correcteur.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("GROQ_API_KEY", "x")

import pipeline as P  # noqa: E402

SRC = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipeline.py"),
           encoding="utf-8").read()


def _prompt_pour(modele, snippet=6000, contenu=30000, n=10):
    """Construit un vrai prompt et rend (caractères, tokens, réservation)."""
    vus = []

    def faux(api_key, messages, max_tokens=3500):
        tpm = P._TPM_PAR_MODELE_GEN.get(P.GROQ_MODEL, 12_000)
        car = sum(len(m.get("content", "")) for m in messages)
        pr = int(car / P._CHARS_PAR_TOKEN)
        vus.append((car, pr, max(200, min(max_tokens, tpm - 500 - pr))))
        raise RuntimeError("interception")

    avant, P.GROQ_MODEL = P.GROQ_MODEL, modele
    vrai, P._groq_call = P._groq_call, faux
    try:
        P.generate("y" * contenu, "societe",
                   [{"url": f"https://e{i}.fr/d", "title": f"D{i}",
                     "snippet": "x" * snippet, "institution": f"I{i}"} for i in range(n)])
    except Exception:
        pass
    finally:
        P._groq_call, P.GROQ_MODEL = vrai, avant
    return vus[0]


def test_une_fenetre_large_donne_une_matiere_profonde():
    _, tk_groq, _ = _prompt_pour("llama-3.3-70b-versatile")
    _, tk_mistral, _ = _prompt_pour("mistral-large-latest")
    assert tk_mistral > 2 * tk_groq, (
        f"la matière injectée ne profite pas de la fenêtre large "
        f"({tk_mistral} tokens contre {tk_groq})")


def test_la_reservation_d_ecriture_ne_rabote_plus():
    """Le mécanisme du 15/08 reste en place, mais il n'a plus rien à couper :
    il doit rendre la réservation PLEINE, pas le plancher de 200."""
    _, _, reserve = _prompt_pour("mistral-large-latest")
    assert reserve >= 3000, f"réservation d'écriture de {reserve} tokens seulement"


def test_la_petite_fenetre_reste_protegee():
    """⚠ Ne pas casser Groq en élargissant Mistral : sur 12 000 tokens, la
    matière doit toujours être coupée pour garder de quoi écrire."""
    _, _, reserve = _prompt_pour("llama-3.3-70b-versatile")
    assert reserve > 1200, f"réservation de {reserve} tokens sur petite fenêtre"


def test_les_plafonds_suivent_la_fenetre_et_non_une_constante():
    for marqueur in ("_profond = _fenetre_gen >= 100_000",
                     "if _profond else 950",
                     "if _profond else 7000"):
        assert marqueur in SRC, f"plafond redevenu une constante : {marqueur}"


def test_le_plafond_de_sujets_par_run_suit_aussi():
    """« Je ne veux pas quelques sujets de plus, je veux TOUS les sujets. »
    L'arrêt à 20 protégeait le TPD de 100 000 tokens de Groq, partagé entre
    deux runs. Mistral offre 1 milliard/mois : un run en consomme 0,04 %."""
    assert "MAX_TENTATIVES_PAR_RUN = (" in SRC and "999 if" in SRC, (
        "le plafond de sujets par run est redevenu une constante")
    assert "_BUDGET_SECONDES" in SRC, (
        "le garde-fou de temps doit rester : c'est lui la contrainte réelle")


def test_le_redacteur_connait_les_motifs_qui_le_rejettent():
    """Question de Nahil : « pourquoi on ne donne pas toutes les contraintes
    avant la rédaction ? ». Le prompt ne nommait AUCUN des six motifs
    bloquants du fact-checker — le rédacteur ignorait ce qui le fait rejeter.
    """
    prompt = P.SYSTEM_PROMPT
    assert "SIX seuls motifs bloquants" in prompt
    for motif in ("chiffre_errone", "annonce_perimee", "niveau_preuve_insuffisant",
                  "incoherence_inter_sections", "accusation_presentee_comme_fait",
                  "source_inventee"):
        assert motif in prompt, f"motif bloquant absent du prompt de rédaction : {motif}"


if __name__ == "__main__":
    test_une_fenetre_large_donne_une_matiere_profonde()
    test_la_reservation_d_ecriture_ne_rabote_plus()
    test_la_petite_fenetre_reste_protegee()
    test_les_plafonds_suivent_la_fenetre_et_non_une_constante()
    test_le_plafond_de_sujets_par_run_suit_aussi()
    test_le_redacteur_connait_les_motifs_qui_le_rejettent()
    print("OK — la profondeur de lecture suit la fenêtre, le rédacteur connaît les motifs bloquants")
