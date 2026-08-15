"""
Les Faits — Vérification éditoriale en 3 passes (Groq Llama 3.3)
==============================================================================
Passe 1 : génération (Groq, dans pipeline.py — inchangée)
Passe 2 : détection  (fact-checker indépendant, sans mémoire de la passe 1)
Passe 3 : correction (uniquement si non conforme), puis passe 2 rejouée

Migré d'Anthropic (claude-sonnet-4-6) vers Groq en juillet 2026 : le compte
Anthropic n'a plus de crédits et ne sera pas réapprovisionné (décision de
Nahil — la génération Anthropic était jugée de qualité insuffisante). Le
fact-check tourne donc sur le même Llama 3.3 que la génération, avec les
mêmes clés et la même rotation anti-rate-limit. Moins fin que Sonnet, mais
un contrôle LLM imparfait vaut mieux que pas de contrôle du tout.

Statuts possibles :
  conforme_du_premier_coup  → publié tel quel
  corrige_automatiquement   → publié corrigé (original + rapport journalisés)
  rejete_sensible           → JAMAIS publié, log seul : sujet sensible (épidémie active,
                              affaire en cours, mineur, citation nominative sensible) ou
                              problème légal (bloc 5) — rejet définitif, aucune retry
  rejete_qualite            → JAMAIS publié, log seul : trop de problèmes bloquants après
                              MAX_TENTATIVES corrections, ou perte de substance détectée
  non_verifie               → aucune clé Groq disponible (comportement historique)
  erreur_verification       → l'API a échoué, publié tel quel + journalisé

Les clés API viennent de l'environnement (secrets GitHub GROQ_API_KEY[_2/_3/_4/_5/_6/_7]).
Aucune clé n'est jamais codée en dur.
"""

import os, re, json, time
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
MODERATION_QUEUE = DATA / "moderation_queue.json"
VERIF_LOG = DATA / "verification_log.json"

# Liste dynamique (23/07, Nahil : 23 clés après nettoyage à 1 clé/compte) — voir pipeline.py pour le
# même mécanisme, GROQ_API_KEY_2 à _N sans plafond codé en dur.
GROQ_KEYS = [k for k in (
    [os.getenv("GROQ_API_KEY", "")]
    + [os.getenv(f"GROQ_API_KEY_{i}", "") for i in range(2, 41)]
) if k]
GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


# ══════════════════════════════════════════════════════════════════════════════
# PROMPTS — adaptés au format d'article actuel du pipeline
# (titre / resume[3] / corps.faits / corps.contexte / corps.nuances / sources[])
# ══════════════════════════════════════════════════════════════════════════════

PROMPT_DETECTION = """Tu es un fact-checker indépendant et rigoureux pour Les Faits. Analyse l'article ci-dessous par rapport à sa liste de sources autorisées, selon la charte "Critères Premium" ci-dessous. Sois exhaustif : ton rôle est de trouver TOUS les problèmes, pas de donner le bénéfice du doute.

AVANT TOUT — LIMITE DE TA PROPRE CONNAISSANCE. Tu juges uniquement par rapport aux sources fournies. Ta connaissance du monde s'arrête à une date passée : un produit, une institution, un chiffre ou un événement que tu ne connais pas peut être parfaitement réel et postérieur à ton entraînement. Ne signale JAMAIS un élément comme inventé, erroné ou périmé au motif que tu l'ignores — seulement s'il contredit les sources listées ou n'y apparaît pas. Cela vaut en particulier pour "source_inventee", "chiffre_errone", "annonce_perimee" et "fait_tranche_arbitrairement".

FORMAT DE CITATION (05/08) : cet article n'attribue PLUS ses faits par une prose du type "Selon X, D'après Y" — chaque fait porte un numéro [n] entre crochets renvoyant à sa position dans le tableau "sources" fourni (1 = premier élément). Ce n'est PAS une absence d'attribution : vérifie le fait contre la source à cette position exacte, exactement comme tu l'aurais fait pour un "Selon X". Un [n] qui renvoie à une source dont le contenu ne confirme pas le fait est un "source_inventee" au même titre qu'une fausse attribution en prose. Ne signale PAS l'absence du nom du média dans le texte comme un défaut — c'est le format attendu, pas un oubli.

Chaque type de problème appartient à un bloc. Le bloc détermine si l'article peut être corrigé automatiquement ou doit partir en relecture humaine — indique-le pour chaque problème via le champ "bloc".

BLOC 1 — FACTUEL (zéro tolérance) :
- chiffre_errone : un chiffre/statistique/date ne correspond pas exactement à ce que dit la source citée (pas d'arrondi ni d'extrapolation non signalée). Vérifie EN PARTICULIER que le chiffre du TITRE dit la même chose que le corps, verbe compris — exemple réel non détecté (28/07) : titre « 15 % des salariés SIGNALENT des irrégularités » alors que le corps dit « 15 % des salariés ESTIMENT QU'IL Y A des irrégularités », et donne plus loin le vrai taux de signalement (1,57 pour 100 employés). Constater un problème et le signaler sont deux actes différents : le titre gonflait le chiffre d'un facteur dix.
- chronologie_confuse : un événement antérieur/historique est mentionné sans que sa date et son rapport avec l'événement du jour soient explicites (deux époques mélangées implicitement)
- incoherence_inter_sections : une même affirmation présentée différemment dans deux sections du même article. Vérifie EXPLICITEMENT deux points, en convertissant si besoin les unités et les devises avant de conclure :
  (a) les chiffres du chapeau et ceux de « Les faits » décrivent-ils la même réalité ? Exemple réel non détecté (28/07) : chapeau « pourrait dépasser les 1 000 milliards de yuans de valorisation » et faits « valorisation à plus de 450 milliards d'euros » — 1 000 milliards de yuans valent environ 120 milliards d'euros, les deux chiffres sont donc incompatibles pour une même valorisation ;
  (b) deux sources donnent-elles deux valeurs différentes du MÊME chiffre (« +500 % » et « +530 % » pour la même séance de cotation) sans que l'article ne les réconcilie ni ne signale l'écart ? Dans ce cas une seule valeur doit être retenue et attribuée, ou l'écart explicitement mentionné.
- annonce_perimee : le titre ou le chapeau présente comme À VENIR (« s'apprête à », « prévoit de », « devrait bientôt ») un événement que « Les faits » décrivent comme DÉJÀ SURVENU (« a levé », « a bondi lors de sa première séance »). Les sources fournies n'ont pas toutes été publiées au même moment : certaines précèdent l'événement, d'autres le suivent. Le titre et le chapeau doivent toujours refléter l'état le plus récent établi par les sources.
- niveau_preuve_insuffisant : article médical ou scientifique qui présente un résultat d'essai comme une efficacité acquise. Est un problème si l'une de ces conditions est vraie : (a) le stade de la recherche (phase 1/1b/2/3, préclinique, étude observationnelle) n'apparaît NI dans le résumé NI à côté du résultat principal alors que la source le précise ; (b) l'article écrit "améliore la survie" quand la source ne décrit qu'une survie SANS PROGRESSION, un taux de réponse ou une opérabilité — ces indicateurs ne sont pas interchangeables ; (c) une comparaison chiffrée est donnée ("cinq mois de plus") sans que le COMPARATEUR soit identifié (plus que quoi, chez qui, mesuré comment) ; (d) les limites se résument à "des recherches supplémentaires sont nécessaires" au lieu des limites réelles de l'essai (effectif, absence de randomisation, durée de suivi, tolérance inconnue). Vérifie AUSSI que la publication scientifique originale figure dans les sources quand la source la mentionne : un communiqué d'institution ne la remplace pas.
- accusation_presentee_comme_fait : une accusation, une conclusion d'ONG ou un résultat d'audit reformulé en constat de la rédaction. "Les activités de X exposent les populations à des risques graves" au lieu de "Human Rights Watch estime que…". Distingue fait observé / accusation / conclusion d'ONG / résultat d'audit / décision administrative ou judiciaire : seule la dernière catégorie s'énonce sans attribution. Signale aussi le cas inverse : une accusation attribuée dans "Les faits" mais reprise sans attribution dans le résumé, le titre ou les nuances.
- acteur_mis_en_cause_sans_reponse : une entreprise, une institution ou une personne est mise en cause sans que l'article rapporte sa réponse, ou indique explicitement qu'elle n'était pas disponible ("La réaction de X n'était pas disponible dans les sources consultées"). Est également un problème un acteur figurant dans "positions" sans qu'aucune position réelle ne lui soit attribuée : une entrée vide est trompeuse, elle simule un équilibre inexistant.
- fait_tranche_arbitrairement : un fait incertain ou contesté présenté comme définitivement établi. Inclut la SIMPLIFICATION EXCESSIVE d'un résultat scientifique ou technique : si la source décrit une avancée partielle, un cas particulier ou une variante spécifique d'un problème ("résultat majeur sur le cas de dimension 3"), l'article ne doit jamais généraliser à "a résolu le problème" / "a démontré la conjecture" sans la même restriction que la source — reprends le niveau de précision exact de la source, jamais un raccourci plus impressionnant qu'elle (retour revue éditoriale du 25/07).

BLOC 2 — SOURCING (100% vérifiable) :
- source_inventee : tout nom de média, expert, institution, étude cité dans le texte qui n'apparaît pas dans les sources autorisées
- formule_vague : "selon les experts", "des études montrent", "selon les sources", "il est établi" sans référence précise à une source de la liste
- source_non_editoriale : une source non-journalistique/non-institutionnelle (ex : un outil de traduction, un dictionnaire) citée comme autorité factuelle. DEUX EXCEPTIONS explicites, même logique dans les deux cas — valable pour un fait brut, jamais pour une appréciation :
  (a) une fiche constructeur/fabricant listée dans les sources autorisées EST une source valable pour des caractéristiques factuelles et mesurables de son propre produit (taille d'écran, capacité de batterie, modèle de processeur, prix affiché) — personne ne connaît mieux ces specs que le fabricant lui-même ;
  (b) une page "guide d'achat / bons plans" d'un média tech reconnu listé dans les sources autorisées EST une source valable pour des faits vérifiables (prix, disponibilité, caractéristiques techniques), même si la rubrique a une visée commerciale.
  Dans les deux cas, la source redevient un problème UNIQUEMENT si elle sert de caution à un jugement de valeur, une recommandation ou un comparatif ("meilleur choix", "excellent rapport qualité-prix", "bon plan à ne pas manquer", "recommandé") — ça reste du discours marketing, pas une source neutre, même attribué explicitement à la source.
- source_derivee_comptee_comme_primaire : plusieurs sources listées qui ne font que recopier la même dépêche/communiqué sans apporter d'info distincte, comptées comme des sources indépendantes alors qu'elles ne le sont pas. Cas typique : un rapport d'ONG ou une étude relayés par huit médias — ce sont huit reprises d'UN document, pas huit confirmations indépendantes. La source primaire est le document original lui-même ; les médias qui le commentent ne le remplacent pas et ne se comptent pas séparément. Le problème n'est PAS que l'information soit fausse, c'est que le compte de sources indépendantes est faux — or c'est lui qui décide de la publication (≥1 primaire OU ≥2 secondaires indépendantes).
- compteur_incoherent : le champ "nb_sources" ne correspond pas au nombre réel de sources distinctes effectivement utilisées (sources fantômes comptées, ou sources utilisées mais non comptées) — c'est une question d'intégrité du sourcing, pas de style

BLOC 3 — ORIGINALITÉ (zéro plagiat déguisé) :
- paraphrase_structurelle : une phrase reprend la structure et l'essentiel du vocabulaire d'une source sans guillemets (changer un adverbe n'est pas une reformulation)
- citation_non_attribuee : une citation directe non entre guillemets ou non attribuée nommément
- cadrage_emprunte : un jugement de valeur ou un cadrage editorial d'une source (ex: "modèle patriarcal", "crise sans précédent") présenté comme un fait neutre par Les Faits au lieu d'être attribué explicitement ("selon X") ou reformulé factuellement

BLOC 4 — RÉDACTION (zéro remplissage) :
- redondance : toute phrase de "contexte" ou "nuances" qui répète, même reformulée, une idée déjà présente dans "faits" ou ailleurs dans l'article
- section_gonflee : "contexte" ou "nuances" rempli avec du vague générique ("il est difficile de prévoir les conséquences") au lieu d'un fait distinct sourcé, ou alors que la section n'apporte rien et devrait être coupée
- contexte_hors_sujet : un fait, une source ou un développement du « Contexte » qui ne porte pas sur le sujet de l'article. Cas typique à repérer sans indulgence : une source qui documente un PAYS, une PÉRIODE ou une ENTITÉ voisine mais différente — exemple réel non détecté (28/07) : un article sur la République démocratique du Congo citant la Direction générale du Trésor sur le Congo-BRAZZAVILLE, l'article admettant lui-même dans la phrase suivante « il est essentiel de considérer les spécificités de la situation en République démocratique du Congo ». Quand le texte signale lui-même que sa source ne porte pas sur le bon périmètre, c'est un aveu : la source n'a pas sa place. Sont également visés une source OU un fait cité en "contexte" qui n'éclaire pas directement le sujet principal de l'article — soit une source d'un domaine large sans lien avec CE sujet précis (ex : une source générale sur l'IA en médecine citée dans un article sur un produit IA grand public), soit un fait vrai et sourcé mais tangentiel qui ne sert qu'à remplir (ex : "la France compte 54 biens classés à l'Unesco" dans un article sur l'inscription de médinas comoriennes — vrai, mais n'aide en rien à comprendre CETTE inscription) (retour revues éditoriales du 25/07)
- angle_annonce_non_tenu : le résumé (chapeau) annonce un angle ou une problématique précise (ex : "la place des femmes dans la société grecque") que le reste de l'article n'aborde ensuite jamais ou à peine — l'article part dans une autre direction sans revenir sur la promesse de son introduction
- faux_debat : "positions des acteurs" ou "nuances" présente un désaccord qui n'est pas réel/symétrique (ex : appliqué à une sanction, une décision de justice, un acte institutionnel unilatéral qui n'a qu'un seul camp)
- jugement_de_valeur : tout adjectif, adverbe ou tournure qui trahit une opinion plutôt qu'un fait neutre
- extrapolation : toute anticipation de conséquence future non explicitement sourcée

BLOC 5 — LÉGAL (toujours grave, jamais corrigeable automatiquement) :
- presomption_innocence : une personne appelée "coupable"/"l'assassin"/"le violeur" avant condamnation définitive, au lieu de "mis en examen", "soupçonné", "présumé", "poursuivi pour"
- affaire_en_cours_presentee_comme_fait : une affaire judiciaire en cours présentée comme un fait établi au lieu d'être attribuée à l'accusation/aux enquêteurs ou mise au conditionnel
- diffamation_potentielle : une affirmation négative sur une personne identifiée nommément qui n'est pas strictement sourcée et vérifiable
- mineur_identifie : un mineur impliqué dans une affaire pénale (victime ou mis en cause) identifié par nom, photo ou établissement

Pour CHAQUE problème trouvé, cite la phrase exacte concernée (mot pour mot, copiée depuis l'article) et précise dans quelle section elle se trouve.

INDÉPENDAMMENT des blocs ci-dessus, évalue aussi si le SUJET lui-même exige une relecture humaine avant publication, quel que soit le nombre de problèmes trouvés — un article peut être parfaitement conforme sur les blocs 1-5 et rester un mauvais candidat à la publication 100% automatique si son sujet le justifie. Indique "sujet_sensible": true si l'article :
- implique un mineur (victime ou mis en cause) d'une manière ou d'une autre, même sans l'identifier nommément
- porte sur une affaire judiciaire ou PÉNALE en cours visant des PERSONNES (mise en examen, procès, enquête criminelle, garde à vue, plainte contre une personne nommée), non définitivement jugée
- contient une critique ou une affirmation négative visant nommément une personne identifiée (responsable politique, particulier, entreprise dirigée par une personne nommée)

NE classe PAS "sujet_sensible": true au seul motif qu'un sujet est politique, réglementaire, diplomatique ou économique. Un débat public normal — décision d'une institution (Commission européenne, gouvernement, autorité de régulation), contentieux administratif ou commercial entre organisations, avis d'une juridiction sur une norme, négociation internationale, désaccord entre États ou entre entreprises — n'est PAS un sujet sensible tant qu'aucune personne physique n'est mise en cause pénalement et qu'aucun mineur n'est impliqué. Ces sujets doivent être traités factuellement, avec les positions des parties attribuées, et non écartés. Le critère est la mise en cause de PERSONNES, jamais la sensibilité politique du thème.

ÉGALEMENT INDÉPENDANT des blocs 1-5 : évalue si le sujet mérite réellement un article, avant même de juger sa rédaction. Indique "angle_insuffisant": true si, ET SEULEMENT SI :
- aucune actualité identifiable ne justifie une publication maintenant (l'article ressemble à une fiche pédagogique générale sans fait déclencheur daté) ;
- les sources fournies sont trop pauvres pour expliquer correctement le sujet (ex : cas médical exceptionnel sans diagnostic, mécanisme ou évolution connus) ;
- le "contexte" a dû être rempli avec un fait divers sans rapport direct avec le sujet principal faute de matière pertinente ;
- un lecteur terminant l'article ne saurait toujours pas ce qui s'est réellement passé, pourquoi c'est publié maintenant, ce qui est établi et ce qui ne l'est pas ;
- le champ "angle_reponse" fourni annonce une question précise (ex. « ce chiffre change-t-il quelque chose pour la France ? ») et rien dans l'article n'y répond explicitement — un article qui expose des faits sans jamais revenir à sa propre question a un angle manqué, pas seulement un sujet mince.

TEST OPÉRATIONNEL OBLIGATOIRE (applique-le systématiquement, ne te fie pas à une impression générale) : cherche dans "faits" UNE phrase qui contienne à la fois (a) un événement précis daté ou datable (annonce, publication, décision, résultat rendu public récemment) ET (b) une donnée chiffrée ou nommée qui lui est propre. Si aucune phrase de "faits" ne remplit ce double critère — si le texte ne fait qu'expliquer un concept, une notion ou un phénomène général en citant des institutions sans jamais dire CE QUI VIENT DE SE PASSER — alors angle_insuffisant = true, même si l'article est bien écrit, bien sourcé et neutre. Un article qui répond à "qu'est-ce que X ?" plutôt qu'à "pourquoi parle-t-on de X maintenant ?" est TOUJOURS insuffisant, quelle que soit la qualité de ses sources. Ce n'est PAS un jugement de style : un article bien écrit sur un sujet creux reste "angle_insuffisant": true. Précise la raison dans "angle_insuffisant_raison".

Classe aussi la nature du contenu dans "nature_contenu", une valeur parmi : "actualite_factuelle", "etude_scientifique", "rapport", "decision_officielle", "declaration", "interview", "tribune", "chronique", "prise_de_position", "sujet_pedagogique". Si la valeur est "tribune", "chronique", "interview" ou "prise_de_position", vérifie que l'introduction de l'article l'indique explicitement (ex : "dans une tribune publiée par X, Y plaide pour...") plutôt que de présenter l'opinion comme un fait établi — sinon, signale-le comme un problème de bloc 3 "cadrage_emprunte".

Réponds en JSON strict, sans texte hors JSON :
{
  "conforme": true/false,
  "sujet_sensible": true/false,
  "sujet_sensible_raison": "explication courte si true, sinon chaîne vide",
  "angle_insuffisant": true/false,
  "angle_insuffisant_raison": "explication courte si true, sinon chaîne vide",
  "nature_contenu": "actualite_factuelle | etude_scientifique | rapport | decision_officielle | declaration | interview | tribune | chronique | prise_de_position | sujet_pedagogique",
  "problemes": [
    {
      "bloc": 1-5,
      "section": "faits | contexte | nuances | resume | titre | positions",
      "type": "chiffre_errone | chronologie_confuse | incoherence_inter_sections | annonce_perimee | fait_tranche_arbitrairement | niveau_preuve_insuffisant | accusation_presentee_comme_fait | acteur_mis_en_cause_sans_reponse | source_inventee | formule_vague | source_non_editoriale | source_derivee_comptee_comme_primaire | paraphrase_structurelle | citation_non_attribuee | cadrage_emprunte | redondance | section_gonflee | contexte_hors_sujet | angle_annonce_non_tenu | faux_debat | jugement_de_valeur | extrapolation | compteur_incoherent | presomption_innocence | affaire_en_cours_presentee_comme_fait | diffamation_potentielle | mineur_identifie",
      "phrase_exacte": "citation mot pour mot de l'article",
      "explication": "pourquoi c'est un problème, en une phrase"
    }
  ]
}

ARTICLE :
{ARTICLE_JSON}

SOURCES AUTORISÉES :
{SOURCES}"""

PROMPT_CORRECTION = """Tu es un correcteur pour Les Faits. Voici un article et un rapport précis de ses défauts. Ta mission : produire une version corrigée qui règle CHAQUE problème listé, sans en introduire de nouveaux — et qui reste un article dense et substantiel, PAS un résumé squelettique.

RÈGLES DE CORRECTION :
- Pour un "chiffre_errone" : corrige le chiffre pour qu'il corresponde exactement à la source citée.
- Pour une "chronologie_confuse" : ajoute la date de l'événement historique et une formule explicite de distinction ("en 2001, soit 25 ans plus tôt...").
- Pour une "incoherence_inter_sections" : harmonise les deux sections sur la version la plus précisément sourcée.
- Pour un "fait_tranche_arbitrairement" : reformule pour indiquer explicitement l'incertitude ou la controverse ("selon X, non confirmé par Y").
- Pour une "source_inventee" : supprime la phrase ou le passage concerné, SAUF si l'information peut être reformulée en te basant uniquement sur les sources autorisées — dans ce cas, réécris-la en l'attribuant correctement.
- Pour une "formule_vague" : soit tu la relies à une source précise de la liste, soit tu la supprimes.
- Pour une "source_non_editoriale" : supprime la référence à cette source comme autorité factuelle ; garde l'info seulement si une autre source de la liste, éditoriale ou institutionnelle, l'atteste aussi.
- Pour une "source_derivee_comptee_comme_primaire" : corrige "nb_sources" pour ne compter qu'une fois les sources qui recopient la même dépêche.
- Pour une "paraphrase_structurelle" : réécris entièrement la phrase avec une structure et un vocabulaire différents, ou mets la formulation source entre guillemets avec attribution.
- Pour une "citation_non_attribuee" : ajoute les guillemets et l'attribution nommée, ou reformule en discours indirect factuel.
- Pour un "cadrage_emprunte" : attribue explicitement le jugement à sa source ("selon X") ou reformule en langage factuel neutre.
- Pour une "redondance" : NE SUPPRIME PAS SIMPLEMENT LA PHRASE. Remplace-la par un fait DISTINCT tiré des mêmes sources autorisées, encore inutilisé dans l'article — un chiffre précis, une date, un autre acteur cité, une méthodologie, une réaction, une comparaison historique ou géographique, une conséquence concrète. Les sources contiennent presque toujours plus de matière que ce qui a été extrait au premier passage ; relis-les intégralement pour trouver cet angle neuf. Supprimer purement et simplement n'est acceptable QUE si tu as vérifié qu'aucun fait distinct exploitable ne reste dans les sources.
- Pour une "section_gonflee" : si un fait distinct sourcé existe encore, utilise-le ; sinon, coupe la section plutôt que de la laisser vague.
- Pour un "contexte_hors_sujet" : remplace le fait ou la source hors-sujet par un fait des sources autorisées directement lié au sujet principal ; si aucun n'existe, coupe le passage plutôt que de garder un contexte qui n'éclaire pas l'article.
- Pour un "angle_annonce_non_tenu" : soit réécris le résumé pour qu'il annonce fidèlement ce que l'article développe réellement, soit développe l'angle annoncé avec des faits des sources autorisées s'ils existent — ne laisse jamais une promesse d'intro sans suite dans le corps de l'article.
- Pour une "annonce_perimee" : réécris le titre ET le chapeau au temps de ce qui s'est réellement produit d'après les sources les plus récentes. Si l'événement a déjà eu lieu, ne l'annonce jamais comme à venir ("s'apprête à", "prévoit de") — l'état le plus récent établi par les sources fait foi, même si le titre d'une source plus ancienne dit le contraire.
- Pour une "incoherence_inter_sections" portant sur des chiffres : ramène-les à une même unité ou devise et ne garde qu'une seule valeur cohérente, attribuée à sa source. Si deux sources donnent deux valeurs différentes du même chiffre, retiens la plus précise ou la plus récente et signale l'écart explicitement plutôt que de présenter les deux comme des faits distincts.
- Pour un "faux_debat" : supprime le cadrage pour/contre et remplace par une présentation factuelle de la décision/sanction, ou indique explicitement qu'il n'y a pas de désaccord réel. IMPORTANT : mets AUSSI à jour le champ JSON "positions" en conséquence — "verifie": false et "acteurs": [] — le graphique de positionnement ne doit jamais afficher un faux débat, même si le problème initial ne portait que sur le texte de 'nuances'.
- Pour un "jugement_de_valeur" : reformule en langage neutre et factuel, sans réduire la longueur.
- Pour une "extrapolation" : supprime, sauf si tu peux l'attribuer explicitement à une source qui l'exprime.
- Pour un "compteur_incoherent" : recompte et corrige le champ "nb_sources" pour qu'il reflète exactement la réalité du texte corrigé.

RÈGLE DE LONGUEUR ABSOLUE — AUSSI IMPORTANTE QUE LES CORRECTIONS ELLES-MÊMES : chaque section corrigée (faits/contexte/nuances) doit faire AU MOINS 85 % des mots de sa version originale. Une correction qui raccourcit une section de plus de 15 % sera REFUSÉE automatiquement et tout ton travail sera perdu. Quand tu dois retirer un passage problématique, tu as exactement trois options, dans cet ordre de préférence : (1) le réécrire correctement (reformuler, attribuer, préciser) ; (2) le remplacer par un fait DISTINCT encore inutilisé tiré des sources autorisées — relis-les intégralement, elles contiennent presque toujours plus de matière que ce qui a été extrait ; (3) en DERNIER recours seulement, si le passage est irrécupérable ET qu'aucun fait neuf n'existe dans les sources, conserver le passage original en l'améliorant a minima plutôt que de le supprimer — SUPPRIMER SANS REMPLACER N'EST JAMAIS UNE OPTION. Un article de presse a plusieurs paragraphes par section, pas une phrase unique — la richesse vient de la variété des faits cités, jamais de leur répétition.

Ne modifie AUCUNE partie de l'article qui n'est pas mentionnée dans le rapport de problèmes. Ne réécris pas le style au-delà de ce qui est nécessaire pour corriger les problèmes signalés.

Réponds avec le même format JSON que l'article original, entièrement corrigé, sans texte hors JSON.

ARTICLE ORIGINAL :
{ARTICLE_JSON}

RAPPORT DE PROBLÈMES :
{RAPPORT}

SOURCES AUTORISÉES :
{SOURCES}"""


# ══════════════════════════════════════════════════════════════════════════════
# APPEL API
# ══════════════════════════════════════════════════════════════════════════════

# Clés au quota JOURNALIER épuisé — mortes jusqu'à la fin du run (le corps
# du 429 Groq distingue « per minute » de « per day » ; attendre 62 s ne sert
# à rien contre une limite quotidienne). Même logique que pipeline.py.
_CLES_MORTES_JOUR: set = set()


# Cumul des tokens consommés par la vérification sur tout le run.
_VERIF_TOKENS = [0]


def _llm_call(prompt: str, max_tokens: int = 6000) -> str:
    """Appel Groq avec rotation des clés + attente sur rate limit — même
    stratégie que la génération (pipeline.py), mais avec moins de patience
    (2 cycles) : une vérification qui rate est publiée en erreur_verification,
    ce n'est pas un sujet perdu comme en génération."""
    if not GROQ_KEYS:
        raise RuntimeError("Aucune clé Groq disponible")
    # La limite TPM Groq (12 000/clé) compte prompt + max_tokens RÉSERVÉS,
    # pas les tokens réellement produits : une réservation trop large fait
    # rejeter l'appel en 413 quel que soit le quota restant. On plafonne donc
    # la réservation à ce que la fenêtre laisse après le prompt (~3,3 car/token
    # en français, marge de sécurité incluse dans le plafond 11 500).
    prompt_estime = int(len(prompt) / 3.3)
    max_tokens = max(1500, min(max_tokens, 11_500 - prompt_estime))
    MAX_CYCLES, WAIT = 2, 62
    last_err = None
    for cycle in range(MAX_CYCLES):
        cles_vivantes = [k for k in GROQ_KEYS if k not in _CLES_MORTES_JOUR]
        if not cles_vivantes:
            raise RuntimeError("Quota Groq journalier épuisé sur toutes les clés (vérification)")
        for key in cles_vivantes:
            r = requests.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {key}",
                         "content-type": "application/json"},
                json={
                    "model": GROQ_MODEL,
                    "max_tokens": max_tokens,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                },
                timeout=180,
            )
            if r.status_code == 429:
                corps = r.text.lower()
                if "per day" in corps or "tpd" in corps or "rpd" in corps:
                    # Lire le solde réel avant de condamner la clé (même
                    # logique que pipeline.py : un 429 « per day » peut venir
                    # d'une requête trop grosse pour le solde, pas d'une clé
                    # vide). Si le solde permet prompt + rapport, on retente
                    # une fois avec une réservation taillée dessus.
                    m = re.search(r"Limit (\d+), Used (\d+)", r.text)
                    restant = (int(m.group(1)) - int(m.group(2))) if m else None
                    prompt_est = int(len(prompt) / 3.3)
                    # Même correctif que pipeline.py (21/07) : marge + plancher
                    # de réservation qui pouvait dépasser ce que la marge
                    # garantissait, empêchant tout repêchage en pratique.
                    MARGE_MIN_COMPLETION = 1000  # rapport JSON tient en ~2000 tokens
                    SECURITE = 200
                    if restant is not None and restant > prompt_est + MARGE_MIN_COMPLETION + SECURITE:
                        reservation = restant - prompt_est - SECURITE
                        r2 = requests.post(
                            GROQ_URL,
                            headers={"Authorization": f"Bearer {key}",
                                     "content-type": "application/json"},
                            json={
                                "model": GROQ_MODEL,
                                "max_tokens": reservation,
                                "messages": [{"role": "user", "content": prompt}],
                                "temperature": 0.2,
                            },
                            timeout=180,
                        )
                        if r2.status_code == 200:
                            print(f"     [VERIF] Solde journalier ~{restant} tokens — appel passé avec réservation réduite à {reservation}")
                            return r2.json()["choices"][0]["message"]["content"].strip()
                    _CLES_MORTES_JOUR.add(key)
                    print(f"     [VERIF] Clé au quota journalier épuisé"
                          f"{f' (solde ~{restant} tokens, insuffisant)' if restant is not None else ''}"
                          f" — retirée de la rotation")
                    print(f"     [VERIF-BRUT] {r.text[:300]}")
                last_err = f"429 rate limit ({r.text[:120]})"
                continue
            if r.status_code >= 400:
                # Le corps de la réponse contient la vraie raison de l'erreur
                # (modèle invalide, requête mal formée…) — sans ce log, une
                # erreur persistante ne laisse aucun indice exploitable.
                raise RuntimeError(f"Groq {r.status_code}: {r.text[:500]}")
            # Comptabiliser les tokens : verification.py n'en journalisait
            # AUCUN, alors qu'il fait 2 à 4 appels par article avec un prompt
            # de fact-check de ~4 200 tokens PLUS l'article et ses sources.
            # Résultat : les totaux « par run » calculés depuis les logs ne
            # couvraient que la génération — la moitié du budget était
            # invisible, et c'est la vérification qui vidait les clés.
            _d = r.json()
            _u = _d.get("usage") or {}
            if _u:
                _VERIF_TOKENS[0] += _u.get("total_tokens", 0)
                print(f"     [VERIF-TOKENS] prompt={_u.get('prompt_tokens')} "
                      f"completion={_u.get('completion_tokens')} "
                      f"total={_u.get('total_tokens')} "
                      f"(cumul vérification : {_VERIF_TOKENS[0]})")
            return _d["choices"][0]["message"]["content"].strip()
        if cycle < MAX_CYCLES - 1:
            print(f"     [VERIF] Toutes les clés Groq en rate limit — attente {WAIT}s")
            time.sleep(WAIT)
    raise RuntimeError(f"Rate limit Groq persistant pour la vérification : {last_err}")


def _extract_json(text: str) -> dict:
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    start = text.find("{")
    if start == -1:
        raise ValueError("Pas de JSON dans la réponse")
    # Compte les accolades pour isoler l'objet JSON complet — texte[start:] seul
    # échoue si la réponse contient du texte après le JSON, ou si le modèle a
    # coupé la réponse en plein milieu (max_tokens atteint).
    depth, end = 0, -1
    in_str, escape = False, False
    for i, ch in enumerate(text[start:], start):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_str:
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end == -1:
        raise ValueError("JSON tronqué ou incomplet dans la réponse (max_tokens atteint ?)")
    return json.loads(text[start:end])


def _sources_block(art: dict) -> str:
    lines = []
    for s in art.get("sources", []):
        lines.append(f"- {s.get('institution','')} | {s.get('titre','')} | {s.get('url') or 'pas d URL'}")
    return "\n".join(lines) or "(aucune source)"


# Préambule injecté en tête du fact-check quand le texte est une BRÈVE (02/08).
# Sans lui, le checker signale l'absence de « Contexte » et de « Débats et
# nuances » comme des sections gonflées ou manquantes, et réclame la mise en
# perspective que ce format exclut par construction : il jugerait la brève à
# l'aune d'un format qu'elle n'est pas. Tout le reste du protocole — factuel,
# sourcing, originalité, légal, sujet sensible, angle insuffisant — s'applique
# à l'identique. Rien n'est retiré au contrôle, seul le format attendu change.
PREAMBULE_BREVE = """FORMAT DU TEXTE À VÉRIFIER : BRÈVE.

Une brève est un format court et complet en soi : un chapeau d'une phrase et une
section « faits » de 110 à 200 mots, rien d'autre. Les champs "contexte" et
"nuances" sont VIDES INTENTIONNELLEMENT.

Conséquences pour ton analyse, à respecter strictement :
- Ne signale JAMAIS l'absence de contexte, de mise en perspective, d'historique,
  de limites méthodologiques ou de débat comme un problème. Ces sections n'ont
  pas à exister ici, leur absence n'est ni une omission ni une section gonflée.
- N'exige aucune longueur minimale au-delà de ce format.
- En revanche, applique SANS AUCUN allègement : les blocs 1 (factuel), 2
  (sourcing), 3 (originalité) et 5 (légal), ainsi que "sujet_sensible" et
  "angle_insuffisant". Une brève mal sourcée, une accusation non attribuée ou un
  chiffre faux dans 110 mots sont exactement aussi graves que dans 500.
- Le TEST OPÉRATIONNEL sur "angle_insuffisant" s'applique tel quel : si "faits"
  ne contient aucune phrase liant un événement daté récent à une donnée chiffrée
  ou nommée qui lui est propre, alors angle_insuffisant = true.

"""


def detecter(art: dict, article_type: str = "actu") -> dict:
    """Passe 2 — fact-check indépendant. Retourne le rapport JSON."""
    prompt = (PROMPT_DETECTION
              .replace("{ARTICLE_JSON}", json.dumps(art, ensure_ascii=False))
              .replace("{SOURCES}", _sources_block(art)))
    if article_type == "breve":
        prompt = PREAMBULE_BREVE + prompt
    elif not str((art.get("corps") or {}).get("nuances", "") or "").strip():
        # Règle 29 du SYSTEM_PROMPT (15/08) : « Débats et nuances » n'a de
        # longueur imposée que si les sources contiennent des limites, des
        # incertitudes ou des désaccords ATTESTÉS. Sinon la section doit rester
        # VIDE — c'est la bonne réponse, pas un manquement.
        #
        # Sans ce préambule, le fact-checker signalerait l'absence comme un
        # défaut et la correction la remplirait de généralités : exactement le
        # comportement qu'on vient de supprimer côté rédaction. Deux étapes qui
        # se contredisent produisent le pire des deux.
        prompt = ("PRÉCISION DE FORMAT : la section « Débats et nuances » de cet "
                  "article est VIDE, et c'est VOULU — les sources fournies ne "
                  "contenaient aucune limite, incertitude ou critique attestée. Ne "
                  "signale PAS cette absence comme un défaut, ne demande PAS de la "
                  "remplir, et n'invente aucune réserve pour la combler. Juge "
                  "l'article sur ce qu'il affirme, pas sur cette section absente.\n\n"
                  ) + prompt
    # Groq compte prompt + max_tokens réservés dans la limite TPM (12 000) :
    # avec 8000 réservés, une détection à prompt ~4 400 tokens dépassait le
    # plafond en un seul appel (413 "Requested 12366") et ne pouvait JAMAIS
    # passer. Un rapport de détection tient largement en 4 000 tokens.
    return _extract_json(_llm_call(prompt, max_tokens=4000))


def corriger(art: dict, rapport: dict, article_type: str = "actu") -> dict:
    """Passe 3 — correction ciblée. Retourne l'article corrigé."""
    prompt = (PROMPT_CORRECTION
              .replace("{ARTICLE_JSON}", json.dumps(art, ensure_ascii=False))
              .replace("{RAPPORT}", json.dumps(rapport, ensure_ascii=False))
              .replace("{SOURCES}", _sources_block(art)))
    if article_type == "breve":
        # La « RÈGLE DE LONGUEUR ABSOLUE » du prompt de correction parle de
        # sections faits/contexte/nuances et pousse à étoffer. Sur une brève,
        # suivie à la lettre, elle rouvrirait les sections vides — exactement
        # ce que le format supprime. pipeline.py les revide ensuite par
        # sécurité, mais autant ne pas payer les tokens de leur rédaction.
        prompt = (
            "FORMAT : BRÈVE. Les champs \"contexte\" et \"nuances\" sont vides "
            "INTENTIONNELLEMENT et doivent le RESTER — ne les remplis sous aucun "
            "prétexte. La règle de longueur ci-dessous ne s'applique qu'au chapeau "
            "et à \"faits\", qui doivent conserver au moins 85 % de leurs mots.\n\n"
            + prompt
        )
    corrige = _extract_json(_llm_call(prompt, max_tokens=4500))
    # Champs techniques jamais modifiables par le correcteur
    for k in ("slug", "categorie", "image_keyword"):
        if k in art:
            corrige[k] = art[k]
    return corrige


# ══════════════════════════════════════════════════════════════════════════════
# JOURNALISATION
# ══════════════════════════════════════════════════════════════════════════════

def _append_json(path: Path, entry: dict):
    data = []
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = []
    data.append(entry)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _log(slug: str, statut: str, detail: dict | None = None):
    _append_json(VERIF_LOG, {
        "slug": slug,
        "statut": statut,
        "date": datetime.now().isoformat(timespec="seconds"),
        **(detail or {}),
    })


def _problemes_bloquants(problemes: list) -> list:
    """Blocs véritablement bloquants :
    - Bloc 1 STRICT : chiffre_errone + incoherence_inter_sections uniquement.
      fait_tranche_arbitrairement / chronologie_confuse = défauts rédactionnels
      (le checker exhaustif les trouve systématiquement dans les articles IA),
      pas des mensonges factuels — non bloquants.
    - Bloc 2 STRICT : source_inventee uniquement.
    - Bloc 5 (légal) : géré en amont (rejete_sensible), jamais ici.
    Blocs 3/4 (style, cadrage) : non bloquants par définition."""
    # Ajouts du 31/07 (revue éditoriale externe, articles NP137 et Perenco/RDC) :
    # présenter un essai précoce comme une efficacité acquise, ou une accusation
    # comme un constat de la rédaction, sont des fautes de FOND — pas de style.
    # Elles touchent à la neutralité, qui est la seule valeur ajoutée du site.
    BLOC1_BLOQUANTS = {"chiffre_errone", "incoherence_inter_sections", "annonce_perimee",
                       "niveau_preuve_insuffisant", "accusation_presentee_comme_fait"}
    BLOC2_BLOQUANTS = {"source_inventee"}
    return [
        p for p in problemes
        if (p.get("bloc") == 1 and p.get("type") in BLOC1_BLOQUANTS)
        or (p.get("bloc") == 2 and p.get("type") in BLOC2_BLOQUANTS)
    ]


def _perte_substance(art_original: dict, art_corrige: dict) -> tuple[bool, str | None, int, int]:
    """Détecte une correction qui coupe au lieu de réécrire — risque identifié
    dès le tout premier test (article agriculture : "Contexte" passé de 4
    phrases à 1 seule après correction, faute de matière neuve dans les
    sources). Ne coûte aucun appel API : simple comptage de mots avant/après.
    Retourne (perte_detectee, section, mots_avant, mots_apres)."""
    SEUIL_RATIO = 0.5   # perte de plus de 50% des mots de la section
    PLANCHER_MOTS = 15  # en dessous, une section devient une coquille vide
    for section in ("faits", "contexte", "nuances"):
        avant = len((art_original.get("corps", {}).get(section) or "").split())
        apres = len((art_corrige.get("corps", {}).get(section) or "").split())
        if avant < 20:
            continue  # section déjà courte à l'origine, pas de risque de "coupe"
        if apres < avant * (1 - SEUIL_RATIO) or apres < PLANCHER_MOTS:
            return True, section, avant, apres
    return False, None, 0, 0


def enqueue_moderation(art: dict, rapport_initial: dict, rapport_final: dict):
    """File d'attente des articles à valider manuellement — jamais publiés."""
    _append_json(MODERATION_QUEUE, {
        "date": datetime.now().isoformat(timespec="seconds"),
        "slug": art.get("slug", "?"),
        "titre": art.get("titre", "?"),
        "article": art,
        "rapport_initial": rapport_initial,
        "rapport_final": rapport_final,
    })


# ══════════════════════════════════════════════════════════════════════════════
# ORCHESTRATION — la fonction appelée par pipeline.py
# ══════════════════════════════════════════════════════════════════════════════

def verifier_article(art: dict, article_type: str = "actu",
                     avertissements: list | None = None,
                     contexte: dict | None = None) -> tuple[dict, str]:
    """
    Applique les passes 2 (détection) et 3 (correction) sur un article généré.
    Retourne (article_final, statut).
    rejete_sensible / rejete_qualite → JAMAIS publié, rejet définitif, log seul.
    article_type : "actu" | "breve" | "dossier_portrait" | "dossier_science" —
    tracé dans le log ET transmis aux deux passes : le fact-checker doit savoir
    qu'une brève n'a ni contexte ni nuances, sinon il rejette le format lui-même.
    """
    slug = art.get("slug", "?")
    # `avertissements` : garde-fous déterministes ayant signalé un défaut que
    # la relance corrective n'a pas réglé et qui reste dans le texte. Sans
    # eux, `conforme_du_premier_coup` ne dit que « le fact-check LLM n'a rien
    # relevé » et surestime la propreté réelle des articles.
    _type_detail = {"article_type": article_type}
    if avertissements:
        _type_detail["avertissements_garde_fous"] = list(avertissements)

    # ── INSTRUMENTATION DU VERDICT (13/08) ───────────────────────────────────
    # `verification_log.json` contient 119 rejets `angle insuffisant` contre
    # 108 passages : une référence ÉTIQUETÉE, indépendante du regroupement et
    # du barème, payée depuis des semaines — le fact-checker lit l'article
    # fini, il n'a jamais vu une grappe. C'est la seule référence non
    # circulaire dont dispose ce projet.
    #
    # Elle est pourtant inexploitable en l'état : le seul champ persisté est le
    # SLUG. Un Bayes naïf sur les mots du slug rend 59 % contre 53 % pour la
    # classe majoritaire — du bruit, parce que `explosion-cambrienne-excrements`
    # a perdu la date, le déclencheur, les chiffres et la couverture, c'est-à-
    # dire tout ce qui sépare une actualité d'un sujet de magazine.
    #
    # On persiste donc, au moment du verdict, ce que le pipeline sait déjà.
    # Coût : zéro token, zéro appel réseau, quelques centaines d'octets. Trois
    # runs et les 227 étiquettes deviennent testables.
    _type_detail["titre"] = str(art.get("titre") or "")[:200]
    _srcs = art.get("sources") or []
    _type_detail["n_sources"] = len(_srcs) if isinstance(_srcs, list) else 0
    _corps = art.get("corps") or {}
    _type_detail["n_mots"] = len(re.findall(
        r"[\w’'-]+",
        " ".join([str(art.get("resume") or "")]
                 + [str(v) for v in _corps.values() if isinstance(v, str)])))
    if contexte:
        # Ce que seul l'appelant connaît : richesse documentaire mesurée par
        # `audit_matiere`, taille de la grappe de veille, rendement du
        # sourcing. Jamais bloquant, jamais lu par le pipeline — diagnostic.
        _type_detail.update({k: v for k, v in contexte.items() if v is not None})

    if not GROQ_KEYS:
        # Pas de clé → comportement historique, tracé comme non vérifié
        return art, "non_verifie"

    try:
        rapport = detecter(art, article_type)
    except Exception as e:
        print(f"     [VERIF] Erreur API détection ({e}) — publié sans vérification")
        _log(slug, "erreur_verification", {"etape": "detection", "erreur": str(e), **_type_detail})
        return art, "erreur_verification"

    # Garde-fou indépendant du score : un sujet sensible (mineur impliqué,
    # affaire judiciaire en cours, personne nommée négativement) part toujours
    # en relecture humaine, même si l'article est par ailleurs 100% conforme
    # sur les blocs 1-5. "Propre selon le détecteur" et "sans risque
    # réputationnel à publier seul" ne sont pas la même chose sur ces sujets.
    if rapport.get("sujet_sensible"):
        raison = rapport.get("sujet_sensible_raison", "")
        print(f"     [REJET] sujet sensible détecté — rejet définitif ({raison})")
        _log(slug, "rejete_sensible", {"sujet_sensible": True, "raison": raison, **_type_detail})
        return art, "rejete_sensible"

    # Angle insuffisant : sujet sans actualité identifiable, sources trop
    # pauvres pour l'expliquer, ou contexte rempli avec un fait divers sans
    # rapport — aucune correction de texte ne répare un sujet creux, donc
    # rejet définitif immédiat, jamais de tentative de correction.
    if rapport.get("angle_insuffisant"):
        raison = rapport.get("angle_insuffisant_raison", "")
        print(f"     [REJET] angle insuffisant — rejet définitif ({raison})")
        _log(slug, "rejete_qualite", {"angle_insuffisant": True, "raison": raison, **_type_detail})
        return art, "rejete_qualite"

    if rapport.get("conforme"):
        # Même filet déterministe que pour corrige_automatiquement : bloc 3/4
        # (dont faux_debat) est non-bloquant et peut coexister avec
        # conforme=true — sans ce nettoyage, un faux débat resterait affiché
        # dans le graphique de positionnement d'un article par ailleurs publié tel quel.
        if any(p.get("type") == "faux_debat" for p in rapport.get("problemes", [])):
            art["positions"] = {"verifie": False, "label_gauche": "",
                                 "label_droite": "", "acteurs": []}
        _log(slug, "conforme_du_premier_coup", _type_detail)
        return art, "conforme_du_premier_coup"

    n_pb = len(rapport.get("problemes", []))

    # Bloc 5 (légal) : jamais de correction automatique, toujours modération
    # humaine — présomption d'innocence, mineurs, diffamation ne se "corrigent"
    # pas par un patch de texte, ils exigent une décision éditoriale humaine.
    problemes_bloc5 = [p for p in rapport.get("problemes", []) if p.get("bloc") == 5]
    if problemes_bloc5:
        print(f"     [REJET] {len(problemes_bloc5)} problème(s) légal(aux) (bloc 5) — rejet définitif")
        _log(slug, "rejete_sensible", {
            "problemes_initiaux": n_pb,
            "bloc5": [p.get("type") for p in problemes_bloc5],
            **_type_detail,
        })
        return art, "rejete_sensible"

    print(f"     [VERIF] {n_pb} problème(s) détecté(s) — correction automatique…")

    # Jusqu'à 2 tentatives de correction : 3 passes consommaient trop de quota
    # Anthropic sur des articles qui ne convergeaient pas (5 bloquants en
    # tentative 1 → 11 en tentative 2 → rejet de toute façon). Si l'article
    # a toujours des bloquants après 2 corrections, une 3ème ne change rien
    # et brûle le budget qui devrait servir aux sujets suivants.
    art_courant = art
    rapport_courant = rapport
    # TEST 31/07 (Nahil) : 2 → 3. Mesure sur les 240 vérifications
    # journalisées — la 2e tentative tourne sur 37 articles et en sauve 9
    # (24 %), pour ~11 500 tokens l'unité, soit ~47 000 tokens par article
    # sauvé. Un sujet NEUF coûte ~500 000 tokens par article publié : corriger
    # un article presque bon est dix fois plus rentable que d'en tenter un
    # autre. Une 3e tentative devrait rester gagnante même à 10 % de réussite.
    # À MESURER sur 2-3 runs : si aucun article n'est sauvé au 3e passage,
    # revenir à 2 (chercher `tentatives: 3` dans data/verification_log.json).
    MAX_TENTATIVES = 3
    for tentative in range(1, MAX_TENTATIVES + 1):
        # Une erreur d'API (JSON mal formé dans la réponse, timeout) n'est pas
        # un défaut de l'article : réessayer une fois avant toute décision.
        # Rejeter sur simple erreur de parsing jetait des articles valides
        # (incohérent avec la détection, qui publie sans vérification en cas
        # d'erreur API).
        art_corrige = rapport_final = None
        derniere_erreur = None
        for essai_api in (1, 2):
            try:
                art_corrige = corriger(art_courant, rapport_courant, article_type)
                rapport_final = detecter(art_corrige, article_type)
                break
            except Exception as e:
                derniere_erreur = e
                if essai_api == 1:
                    print(f"     [VERIF] Erreur API correction (tentative {tentative}) ({e}) — nouvel essai…")
        if rapport_final is None:
            bloquants_connus = _problemes_bloquants(rapport_courant.get("problemes", []))
            if bloquants_connus:
                print(f"     [REJET QUALITÉ] Erreur API persistante ({derniere_erreur}) — "
                      f"{len(bloquants_connus)} bloquant(s) connu(s) non corrigés, rejet")
                _log(slug, "rejete_qualite", {"etape": "correction", "tentative": tentative,
                                              "erreur": str(derniere_erreur),
                                              "bloquants_connus": len(bloquants_connus), **_type_detail})
                return art_courant, "rejete_qualite"
            print(f"     [VERIF] Erreur API persistante ({derniere_erreur}) — "
                  f"défauts restants non bloquants, publié")
            _log(slug, "erreur_verification", {"etape": "correction", "tentative": tentative,
                                               "erreur": str(derniere_erreur), **_type_detail})
            return art_courant, "erreur_verification"

        problemes = rapport_final.get("problemes", [])
        bloquants = _problemes_bloquants(problemes)

        # Sécurité : si la correction a (anormalement) fait apparaître un
        # problème légal, on ne publie jamais automatiquement, quel que soit
        # le reste — cette règle prime sur tout.
        bloc5_apparus = [p for p in problemes if p.get("bloc") == 5]
        if bloc5_apparus:
            print(f"     [REJET] problème légal apparu pendant la correction — rejet définitif")
            _log(slug, "rejete_sensible", {"problemes_initiaux": n_pb, "tentative": tentative, "bloc5": True, **_type_detail})
            return art_corrige, "rejete_sensible"

        if rapport_final.get("sujet_sensible"):
            raison = rapport_final.get("sujet_sensible_raison", "")
            print(f"     [REJET] sujet sensible (tentative {tentative}) — rejet définitif ({raison})")
            _log(slug, "rejete_sensible", {"tentative": tentative, "sujet_sensible": True, "raison": raison, **_type_detail})
            return art_corrige, "rejete_sensible"

        if rapport_final.get("angle_insuffisant"):
            raison = rapport_final.get("angle_insuffisant_raison", "")
            print(f"     [REJET] angle insuffisant (tentative {tentative}) — rejet définitif ({raison})")
            _log(slug, "rejete_qualite", {"tentative": tentative, "angle_insuffisant": True, "raison": raison, **_type_detail})
            return art_corrige, "rejete_qualite"

        # Garde-fou "perte de substance" : la correction a coupé une section
        # au lieu de la réécrire avec un fait neuf (faute de matière dans les
        # sources). Ne bloque jamais en douce — force toujours la modération,
        # quel que soit l'état des blocs 1-5, car publier une section vidée
        # de son contenu casse la promesse de densité même si le texte
        # restant est par ailleurs 100% conforme.
        perte, section_touchee, mots_avant, mots_apres = _perte_substance(art, art_corrige)
        if perte:
            if tentative < MAX_TENTATIVES:
                # Seconde chance AVANT rejet (18/07 : 2 articles/nuit perdus
                # ici) : on relance la correction depuis l'article ORIGINAL
                # intact — pas la version amputée — avec une consigne de
                # longueur explicite injectée dans le rapport. Rejet
                # uniquement si la 2e correction coupe aussi.
                print(f"     [VERIF] perte de substance (tentative {tentative}) : "
                      f"section '{section_touchee}' {mots_avant}→{mots_apres} mots — "
                      f"nouvelle correction avec consigne de longueur")
                rapport_courant = dict(rapport_courant)
                rapport_courant["problemes"] = list(rapport_courant.get("problemes", [])) + [{
                    "bloc": 4,
                    "section": section_touchee,
                    "type": "correction_precedente_trop_coupee",
                    "phrase_exacte": "",
                    "explication": (
                        f"Ta correction précédente a réduit la section « {section_touchee} » "
                        f"de {mots_avant} à {mots_apres} mots — c'est INTERDIT. Corrige les "
                        f"problèmes en REMPLAÇANT chaque passage supprimé par un fait DISTINCT "
                        f"encore inutilisé tiré des sources autorisées (chiffre, date, acteur, "
                        f"réaction, comparaison). La section corrigée doit faire au moins "
                        f"{int(mots_avant * 0.85)} mots. Si aucune matière neuve n'existe dans "
                        f"les sources pour un passage, conserve sa version originale plutôt "
                        f"que de le supprimer."
                    ),
                }]
                art_courant = art  # repartir de l'original intact
                continue
            print(f"     [REJET QUALITÉ] perte de substance (tentative {tentative}) : "
                  f"section '{section_touchee}' {mots_avant}→{mots_apres} mots")
            _log(slug, "rejete_qualite", {
                "tentative": tentative, "perte_substance": True,
                "section": section_touchee, "mots_avant": mots_avant, "mots_apres": mots_apres,
                **_type_detail,
            })
            return art_corrige, "rejete_qualite"

        if rapport_final.get("conforme") or not bloquants:
            # Filet déterministe : si "faux_debat" a été signalé (passe initiale
            # OU rapport final), on ne compte pas sur le correcteur LLM pour
            # avoir nettoyé le JSON 'positions' en conséquence — un faux débat
            # texte ("nuances" corrigé) laissait souvent le graphique de
            # positionnement intact, affichant un Pour/Contre inventé pour un
            # sujet consensuel (constat 19/07, article One Health). On force
            # ici, sans dépendre de l'obéissance du LLM à la consigne du prompt.
            tous_problemes = (rapport or {}).get("problemes", []) + problemes
            if any(p.get("type") == "faux_debat" for p in tous_problemes):
                art_corrige["positions"] = {"verifie": False, "label_gauche": "",
                                             "label_droite": "", "acteurs": []}
            residuel = len(problemes)
            _log(slug, "corrige_automatiquement", {
                "problemes_initiaux": n_pb,
                "tentatives": tentative,
                "problemes_residuels_style": residuel,
                "rapport_initial": rapport,
                **_type_detail,
            })
            if residuel:
                print(f"     [VERIF] {residuel} défaut(s) de style résiduel(s) (bloc 3/4), aucun bloquant — publié")
            return art_corrige, "corrige_automatiquement"

        n_restants = len(problemes)
        types_b = [f"{p.get('bloc')}/{p.get('type')}" for p in bloquants]
        print(f"     [VERIF] tentative {tentative}/{MAX_TENTATIVES} : {n_restants} problème(s) restant(s) "
              f"dont {len(bloquants)} bloquant(s) : {types_b}")
        art_courant, rapport_courant = art_corrige, rapport_final

    # Toujours des problèmes bloquants (factuel/sourcing) après MAX_TENTATIVES
    bloquants_restants = _problemes_bloquants(rapport_courant.get("problemes", []))
    types_bloquants = [f"{p.get('bloc')}/{p.get('type')}" for p in bloquants_restants]
    print(f"     [REJET QUALITÉ] {len(bloquants_restants)} bloquant(s) après {MAX_TENTATIVES} passes : {types_bloquants}")
    # Le TYPE seul ne permet pas de juger si le garde-fou a raison. Constat
    # 30/07 : incoherence_inter_sections est le 1er motif de rejet éditorial
    # (3 sur 14 tentatives), impossible à arbitrer depuis les logs — l'article
    # n'étant pas publié, son texte est perdu. On journalise donc la
    # description renvoyée par le fact-checker, seule trace exploitable.
    # CORRECTIF 02/08 — l'intention ci-dessus n'était pas tenue : les types et
    # les descriptions étaient IMPRIMÉS, jamais journalisés. `_log` ne recevait
    # que des COMPTES (`bloquants_restants: 2`). Conséquence concrète : la
    # question « niveau_preuve_insuffisant et accusation_presentee_comme_fait
    # dominent-ils les rejets ? » est restée sans réponse possible depuis le
    # 31/07 — la seule entrée du 01-02/08 concernée ne dit pas quels motifs ont
    # bloqué, et la sortie GitHub qui les contenait n'est pas requêtable.
    # Même famille d'erreur que « se fier à l'affichage plutôt qu'aux données ».
    # Instrumentation seule : aucune décision du pipeline ne change.
    _detail_bloquants = []
    for _p in bloquants_restants:
        _desc = str(_p.get("description") or _p.get("explication") or "")[:220]
        if _desc:
            print(f"       └ {_p.get('type')} : {_desc}")
        _detail_bloquants.append({"bloc": _p.get("bloc"), "type": _p.get("type"),
                                  "description": _desc,
                                  "phrase": str(_p.get("phrase_exacte") or "")[:220]})
    _log(slug, "rejete_qualite", {
        "problemes_initiaux": n_pb,
        "tentatives": MAX_TENTATIVES,
        "problemes_restants": len(rapport_courant.get("problemes", [])),
        "bloquants_restants": len(bloquants_restants),
        "bloquants_types": [p.get("type") for p in bloquants_restants],
        "bloquants_detail": _detail_bloquants,
        "types_restants": [p.get("type") for p in rapport_courant.get("problemes", [])],
        **_type_detail,
    })
    return art_courant, "rejete_qualite"
