# Les Faits — lesfaits.info

## VEILLE CONTINUE — phase 1 lancée le 12/08, NE DÉCIDE RIEN

Idée de Nahil : arrêter de choisir un sujet sur une PHOTO deux fois par jour,
observer les flux en continu, et n'écrire que ce qui a prouvé son intérêt.

**Pourquoi c'est la bonne cible** : 64 % de nos rejets qualité sont
`angle_insuffisant` — le goulot est la SÉLECTION, pas la rédaction. Et ça rend
enfin exploitable la piste écrite ici depuis le 01/08 (« quand 8 flux sur 36
couvrent le même fait, c'est le signal d'importance le plus fiable
disponible ») : ce signal est **inutilisable sur une photo**, puisqu'à 3 h du
matin une dépêche tombée il y a dix minutes n'a été reprise par personne et
ressemble à un sujet mort. C'est le TEMPS qui les sépare.

**PHASE 2 BRANCHÉE LE 14/08** — la veille alimente désormais la sélection, via
`signal_editorial()`. Ce qui a été branché, et surtout ce qui ne l'a PAS été :

- **on utilise la PERSISTANCE, pas le nombre de rédactions.** Un fait qui
  compte reste plusieurs heures dans les fils, un communiqué disparaît au
  passage suivant. Cette valeur se lit sur un item ISOLÉ, appariée par URL
  canonique — l'URL du candidat est littéralement une clé du journal, aucun
  rapprochement approximatif n'intervient ;
- **le nombre de rédactions est journalisé, jamais utilisé.** Il serait plus
  riche, mais il exige le regroupement, et le backtest du 13/08 a montré que
  celui-ci fusionne des sujets sans rapport. ⚠ Un regroupement erroné GONFLE ce
  compteur : un seuil HAUT y est donc PLUS exposé qu'un seuil bas, pas moins.
  C'est l'inverse de l'intuition, et c'est ce qui a fait écarter la première
  conception. Quelques runs diront lequel des deux signaux prédit la
  publication ;
- **DEUX conditions, jamais la persistance seule.** `heures_visible` grandit
  mécaniquement avec l'âge : une page permanente laissée trois jours dans un
  flux atteindrait le palier maximum. Mesuré sur 2 908 items — persistant ET
  récent : 737 ; persistant MAIS vieux : 1 156. Sans la borne
  `VEILLE_AGE_MAX_H = 36`, le bonus irait à une majorité de faux positifs ;
- **BONUS, jamais malus.** Un candidat absent du journal garde son score
  d'origine : la veille ne peut qu'ajouter de l'information, jamais en retirer
  à un sujet qu'elle n'a pas vu. Journal absent, illisible ou vide → aucun
  signal, aucune exception, barème d'origine.

`scripts/veille.py` + `.github/workflows/veille.yml` (cron horaire) :

- **coût zéro token Groq** — uniquement la lecture des flux RSS ;
- **n'écrit que son journal et ne consomme aucun jeton** — propriété
  verrouillée par un test. (L'étanchéité « le pipeline ne lit pas
  data/veille.json » était la garantie de la PHASE 1 ; elle est levée depuis le
  14/08, remplacée par les garanties ci-dessus.) ;
- le journal garde **chaque item séparément** avec `premiere_vue`,
  `derniere_vue`, `passages` et la liste des flux qui l'ont repris. Le
  regroupement en « événements » est **recalculé à chaque rapport, jamais
  stocké** : on peut donc changer d'algorithme plus tard et le rejouer sur les
  données déjà collectées, sans rien recollecter. C'est tout l'intérêt de
  séparer la collecte de l'analyse ;
- fenêtre glissante de 72 h, URLs canonisées (le tracking `?xtor=RSS-16` ne
  doit pas créer un item neuf — sinon la persistance mesurée serait toujours
  nulle, variante du bug du 30/07).

**Ce qu'il faut lire après quelques jours, et rien d'autre pour l'instant :**
`python scripts/veille.py --rapport` affiche la distribution du nombre de flux
distincts par événement et celle de la persistance en heures. **La question
est : cette distribution est-elle assez étalée pour qu'un seuil ait un sens,
ou tout est-il à 1 flux ?** Si tout est à 1, l'idée ne tient pas et il ne faut
pas la rafistoler. Ne fixer aucun seuil avant d'avoir vu ces distributions —
c'est exactement la règle violée trois fois de suite sur le filtre anti-doublon.

⚠ Le regroupement par mots de titre est **provisoire et assumé comme tel**. Il
a échoué trois fois (26/07, 28/07, 02/08) et ne doit pas devenir la décision
finale ; il ne sert ici qu'à afficher des ordres de grandeur. Limite connue et
verrouillée par un test : la troncature à 8 caractères ne rapproche pas
« antillais » de « antilles ».

### Premier passage réel — 12/08 00h32 UTC, 902 items

```
                                    n grappes    part
1 seul flux                            459       80 %
2 flux                                  65       11 %
3 à 4 flux                              33        6 %
5 à 7 flux                              13        2 %
8 flux et plus                           5        1 %
```

⚠ Ces chiffres sont ceux du regroupement CORRIGÉ (575 grappes). Une première
version de ce tableau donnait 88 % / 7 % / 3 % / 1 % / 1 % sur 537 grappes :
elle avait été calculée avec le regroupement par composantes connexes, celui
qui produisait les blobs décrits plus bas. **Ne pas reprendre ces valeurs-là.**

**La distribution est étalée : un seuil a du sens.** 80 % du bruit ne sera
jamais repris par personne, et 51 événements par passage sortent à 3 flux ou
plus. C'est le premier critère de sélection mesuré dont ce projet
dispose — le barème `score_editorial` n'a jamais noté que la forme.

La persistance en heures ne veut encore rien dire (un seul passage, tout est à
0 h) : c'est la mesure à relire dans deux ou trois jours.

### Le délai de confirmation — objection de Nahil, et la mesure qui y répond

« Lundi tous les journaux parlent du séisme, nous on en parle samedi. »
Attendre qu'un sujet soit confirmé n'a de sens que si la confirmation arrive
en HEURES. Le rapport mesure donc `delai_confirmation` : l'écart entre la 1re
et la 3e apparition d'une grappe, c'est-à-dire le temps qu'il aurait fallu
attendre pour publier sur un critère « au moins 3 reprises ».

Deux critères INDÉPENDANTS, à exiger ensemble le jour où la sélection sera
branchée : `n_flux` (le sujet compte) ET `age_h` (il est encore d'actualité).
Un séisme largement repris mais vieux de trois jours est un sujet manqué, pas
un sujet à écrire — le rapport affiche déjà le décompte des événements
confirmés apparus il y a moins de 12 / 24 / 48 h.

⚠ Sur un seul passage, `delai_confirmation` et `age_h` valent 0 pour tout le
monde : tous les items ont été vus au même instant. **Ces deux mesures ne
veulent rien dire avant plusieurs passages espacés** — ne pas les interpréter
avant le 13/08.

Rappel de cadrage à opposer à l'objection : le pipeline ne tourne que deux
fois par jour (~2 h et ~14 h Paris), donc une info tombée à 4 h attend déjà
dix heures aujourd'hui, sans veille. La veille ne crée pas ce retard, elle
comble le trou entre deux runs.

**Défaut trouvé et corrigé sur ce premier passage** : le regroupement par
composantes connexes chaînait de proche en proche (A rejoint B, B rejoint C) et
produisait des grappes de 59 articles sans rapport, créditées de 20 flux. Les
7 grappes de tête étaient toutes des blobs — **les chiffres les plus
intéressants du rapport étaient donc les plus faux**. Remplacé par un
regroupement par CHEF DE FILE : un item ne rejoint une grappe que s'il partage
2 mots distinctifs avec le premier item de cette grappe, jamais avec un membre
quelconque. Après correction, le classement montre une vraie une : séisme en
Colombie (9 flux), Ebola en RDC (8), offensive de Trump sur la vaccination (9),
canicule (6), condamnation d'Assad (6).

Ce correctif a été rejoué **sur les données déjà collectées, sans recollecter
un seul flux** — c'est exactement ce que permet le stockage des items bruts, et
la raison de ne jamais figer le regroupement dans le journal.

⚠ Le regroupement reste imparfait : la grappe « éclipse solaire » compte encore
30 items et mélange des angles différents. Ne pas fonder un seuil sur le haut
de la distribution sans regarder le contenu des grappes concernées.

⚠ Le sandbox de développement n'a pas d'accès réseau vers les domaines des
flux (403 du proxy) : la veille ne peut y être vérifiée que par
`scripts/test_veille.py` (fetch_rss simulé). Tout passage réel doit être
déclenché sur le runner GitHub.

## FAMINE DE COMPLÉTION — mesurée le 15/08, corrigée. C'est la vraie cause des troncatures

Mesure hors ligne, sans un jeton dépensé : on intercepte les messages
réellement construits par `generate()` et on applique le calcul de
`_groq_call` (`max_tokens = tpm − marge − prompt`, plancher 200).

```
sources × extrait   contenu    prompt (tokens)   reste pour ÉCRIRE
10 × 950 car.        7 000         12 893              200
10 × 950 car.        3 000         11 681              200
 8 × 950 car.        7 000         12 226              200
10 × 400 car.        7 000         11 227              273
 8 × 400 car.        2 000          9 377            2 123
```

**Dans la configuration nominale, le rédacteur disposait de 200 tokens pour
écrire un article JSON qui en demande ~2 000.** La complétion était coupée par
construction. C'est le 2e motif de perte du tunnel (34 sujets, ~323 k tokens,
mesuré le 28/07), traité jusqu'ici comme un caprice du modèle.

**L'effet était INVERSÉ par rapport à l'intuition : plus le sourcing était
riche, moins il restait de place pour écrire.** Un sujet bien documenté était
donc PLUS exposé qu'un sujet pauvre. C'est aussi ce qui rendait le verdict
instable d'une tentative à l'autre — même sujet, autres longueurs d'extraits,
issue opposée. Le « verdict erratique » n'était pas éditorial.

**Correctif (réservation d'écriture, `generate()`)** : le budget de matière est
calculé À REBOURS depuis la fenêtre, pour garantir 2 000 tokens d'écriture
(1 200 pour une brève). Trois propriétés verrouillées par
`scripts/test_fenetre_ecriture.py` :

- **le NOMBRE de sources injectées n'est jamais réduit** — seule la PROFONDEUR
  des extraits baisse (même arbitrage que le 18/07). Couper des sources ferait
  échouer « ≥1 primaire OU ≥2 secondaires » sur des sujets valides : ce serait
  affaiblir un contrôle pour tenir un budget ;
- **les extraits sont coupés AVANT le contenu source principal**, jamais
  l'inverse : ce contenu est l'événement unique sur lequel la règle d'ancrage
  fait reposer l'article. Planchers 300 car. par extrait, 2 500 pour le contenu ;
- **tout est écrit en fonction du TPM du modèle, jamais en dur**
  (`_TPM_PAR_MODELE_GEN`, hissée au niveau module pour que `generate()` et
  `_groq_call` lisent la même table). Le jour où le compte passe en offre
  payante, la fenêtre s'élargit et la coupe cesse d'elle-même. Rien à re-régler.

Après correctif : 1 940 à 2 340 tokens d'écriture dans tous les cas mesurés,
contre 200 avant.

### ⚠ À LIRE AVANT D'INTERPRÉTER LE PROCHAIN `[MATIÈRE]` — écrit AVANT le run

La réservation d'écriture fait tomber la profondeur d'extrait injectée de 950 à
300 caractères dans la configuration nominale, soit **−68 %**. La ligne
`[MATIÈRE]` (faits distincts, redondance, données chiffrées) est calculée sur
ces extraits : **elle va s'effondrer mécaniquement au prochain run.** Les 810 /
1 142 / 1 267 faits distincts relevés le 12/08 ne seront comparables à rien.

**Ce n'est PAS une régression du sourcing.** Le nombre de sources trouvées,
contrôlées et citées est inchangé — c'est verrouillé par un test. Seule la
profondeur LUE par le rédacteur baisse, parce qu'à 12 000 tokens de fenêtre on
ne peut pas à la fois tout lire et avoir la place d'écrire.

Écrit avant le run et non après, précisément pour ne pas refaire l'erreur qui a
coûté trois semaines : la brièveté des articles a été attribuée au modèle alors
qu'elle venait du budget. Une chute de `[MATIÈRE]` lue sans ce paragraphe serait
mal attribuée de la même façon. Toute comparaison de richesse documentaire doit
donc couper le corpus au 15/08, comme on l'a fait au 30/07 pour les images.

### Le plancher du prompt contredisait la section devenue facultative

Relevé par une session parallèle juste après le correctif « nuances
conditionnelles » : `nuances` pouvait rester vide, mais les RÈGLES ABSOLUES
exigeaient toujours « minimum 500 mots combinés (faits + contexte + nuances) »,
sous la mention « toute violation = article rejeté ». **Une section facultative
dans une somme obligatoire : la contrainte d'invention n'était pas supprimée,
elle était déplacée sur `faits` et `contexte`.** Dont les minima propres
disaient déjà 450 + 200 = 650, soit plus que les 500 exigés.

Et l'arithmétique était de toute façon impossible : les premiers jets mesurés
sur les runs réels font 235 à 333 mots. Même défaut que celui consigné au
commentaire du budget de matière du 30/07 — « on demandait 500 mots sans
extrapoler à partir de 300 ; le modèle s'arrêtait court, c'était la bonne
réponse à une consigne impossible » — rejoué un cran plus haut.

Aligné sur le plancher qui rejette RÉELLEMENT
(`SEUILS_FORMAT["article"]["plancher"] = 350`), cible 800 rappelée, et les
`MINIMUM n mots` des sections passés en `VISE n mots`. **Aucun garde-fou n'est
touché** : le plancher de publication, l'étoffement et le rejet sous 350 mots
sont inchangés. C'est le prompt qui cesse de réclamer ce que le budget interdit.
Verrouillé par `scripts/test_nuances_conditionnelles.py` (section 5), qui lit
le seuil dans `SEUILS_FORMAT` plutôt que de le recopier.

### La croissance du prompt système est désormais une décision, pas un effet de bord

Le 15/08, une consigne de mise en paragraphes — utile, elle manquait vraiment —
a coûté **+470 tokens** sur une fenêtre déjà à zéro, sans que rien ne le
signale. Tant que la fenêtre n'est pas une contrainte vérifiée, chaque bonne
idée ajoutée au prompt retire silencieusement de la place à l'écriture, et
personne ne fait le lien avec les articles tronqués.

`test_fenetre_ecriture.py` plafonne donc le prompt système en tokens. Ce n'est
pas une interdiction d'enrichir : relever le plafond est permis, mais devient
un geste explicite, et le diff dit combien de tokens d'écriture ont été
échangés contre la nouvelle règle.

### Le taux de change entre une règle et un article — à citer avant tout ajout au prompt

Où vont réellement les 6 601 tokens du prompt système (mesuré) :

```
RÈGLES ABSOLUES numérotées        4 325 tk    66 %
schéma JSON (champs)              1 610 tk    24 %
rôle, charte, format de citation    666 tk    10 %
```

**Deux tiers du prompt sont la charte éditoriale elle-même.** Il n'y a pas de
gras à retirer : réduire, c'est arbitrer sur le protocole. L'hypothèse « les
règles doublées par un garde-fou déterministe en aval sont récupérables » a été
testée et réfutée — sources ≥ 4, plancher de mots, adjectifs évaluatifs,
citation `[n]`, anti-redondance pèsent ensemble 304 tokens, soit 4,6 %. Payées
deux fois, oui ; ce n'est pas un levier.

Ce qui manquait à toutes ces décisions, c'était un PRIX. Au ratio observé sur
les complétions ayant réellement produit un article publiable (1 423 tk → 449
mots, 1 505 tk → 623 mots, soit 2,4 à 3,2 tokens par mot rendu) :

> **100 tokens ajoutés au prompt ≈ 30 à 40 mots que l'article ne pourra plus
> contenir.**

La question n'est donc plus « payer ou se saborder », mais « cette règle
vaut-elle 30 mots d'article ? ». Repères mesurés : la consigne de mise en
paragraphes du 15/08 a coûté 470 tokens (~150 mots), la règle 3 du plancher
conditionnel 61 tokens (~20 mots). Les deux se défendent à ce prix ; on ne le
connaissait pas. ⚠ Ce taux vaut pour une fenêtre de 12 000 tokens : il change
si le compte passe en offre payante.

### Premier relèvement du plafond — et ce qu'il coûte (17/08)

Le plafond s'est déclenché au premier merge, ce qui est exactement son rôle. La
règle « interdire la chaîne monotone [Acteur] a [verbe] répétée » (`0de58664`,
ajoutée sur `main` le 15/08 sur un exemple de Nahil) pèse **+292 tokens**, soit
~90 mots d'article. Elle vise un défaut de rédaction réel et constaté : elle les
vaut. Plafond relevé de 6 700 à 7 000, l'échange écrit dans le test.

⚠ **Mais la marge est maintenant épuisée, et c'est le chiffre à retenir :**

```
complétions ayant réellement produit un article publiable   1 423 / 1 505 tk
fenêtre nominale (10 sources) après correctif, au 15/08             1 604 tk
fenêtre nominale après la règle du 15/08, mesurée au 17/08          1 403 tk
```

Le cas nominal est repassé **SOUS** les deux seules complétions publiables
connues. Le mécanisme de réservation fonctionne (8× mieux que les 200 tokens
d'origine), mais il ne crée pas de place : il en redistribue. **Le prochain
ajout au prompt se paiera en articles tronqués**, pas en marge rognée. Les deux
issues restent la fenêtre payante ou l'arbitrage sur le protocole.

⚠ **Ce que le correctif ne règle PAS, et qu'il faut lire dans le journal.** À
12 000 tokens de fenêtre on ne peut pas avoir les deux : `[FENÊTRE] ⚠ plancher
atteint` signale les sujets où la matière a été coupée jusqu'au plancher et où
il reste malgré tout moins que la cible. **Le prompt système pèse 6 356 tokens,
soit plus de la moitié de la fenêtre.** Les deux seules issues sont une fenêtre
plus large (offre payante) ou un prompt système plus court — et le raccourcir
revient à retirer des règles éditoriales, ce qu'aucun agent ne décide seul.

## RÉSULTAT NÉGATIF — ne PAS allonger le cooldown des rejets `angle_insuffisant`

Proposition écartée après mesure (15/08) : porter `REJECT_COOLDOWN_HOURS` de 36
à 7 jours pour cesser de repayer la génération d'un sujet déjà jugé creux.

Mesure sur le journal (les dates y sont, la question était mesurable) : **83
sujets rejetés sur `angle_insuffisant`, 6 publiés plus tard**, avec des délais
de 0,1 · 0,4 · 0,9 · 0,9 · 2,0 · 10,0 jours.

```
cooldown 36 h (actuel) : tue 4 des 6 retours gagnants
cooldown 7 jours       : en tue 5 sur 6
```

Comptabilité complète : 7 jours éviteraient 9 tentatives perdues de plus
(~360 k tokens ≈ 0,5–0,7 article espéré) contre **un article certain perdu**.
Le troc est perdant. `REJECT_COOLDOWN_HOURS = 36` reste inchangé.

⚠ Le résultat le plus intéressant est ailleurs : **4 des 6 retours gagnants
surviennent en moins de 24 h.** À cette échelle le monde n'a pas changé — c'est
le VERDICT qui a changé, même sujet, autre génération, jugement opposé. Rapproché
de la famine de complétion ci-dessus, c'est probablement la même histoire : un
modèle qui n'a que 200 tokens pour écrire produit un résumé générique, et rate
le critère quel que soit le sujet. `angle_insuffisant` n'est donc pas
uniquement un défaut de sélection ; une part est un tirage sur la génération.
Réserves : n=6, biais de sélection, six appariements de slugs vérifiés à la main.

## L'ÉVÉNEMENT COMME UNITÉ — branché le 17/08, à mesurer au prochain run

La piste ouverte le 01/08 (« clusteriser les items RSS par événement au lieu de
les dédupliquer ») est enfin exploitée pour ce qu'elle apporte EN PLUS du signal
d'importance : la MATIÈRE. Quand neuf rédactions couvrent le même fait, le
pipeline en retenait une et jetait les huit autres comme des doublons — alors
que ce sont huit angles et huit jeux de détails que la dépêche retenue n'a pas.

`veille.sources_evenement(url)` rend ces reprises comme sources CANDIDATES,
pour zéro requête et zéro token (la veille les a déjà lues). Trois bornes :

- **candidates, pas retenues** : elles rejoignent le vivier de
  `duckduckgo_search` et subissent les mêmes filtres (domaines non citables,
  qualité de domaine, juge de pertinence, `BUDGET_MATIERE`). Aucun passe-droit ;
- **elles ne comblent pas le déficit de PRIMAIRES** : ce sont des reprises de
  presse, secondaires au mieux. Ne pas attendre d'elles ce que seuls les axes
  documentaires du 05/08 peuvent donner ;
- **plafond 4 au premier branchement**, parce que le juge de pertinence ne note
  que les 10 premières sources après tri : en ajouter huit d'un coup pousserait
  des documents NON JUGÉS dans le prompt.

### ⚠ RÉSULTAT NÉGATIF — ne pas filtrer les reprises par leur titre

Les grappes contiennent du hors-sujet : « Au Japon, des pluies diluviennes »
dans celle du séisme en Colombie, « Trump exfiltré en secret » dans celle de son
offensive sur les vaccins. Tentative de réancrer la règle des 2 mots
distinctifs sur le CANDIDAT plutôt que sur le chef de grappe : **elle ne filtre
rien** — « pluies au Japon » partage « morts » et « moins » avec « 132 morts
après le séisme », deux mots courants que `_mots_bruyants` ne coupe pas au seuil
de 10 %.

C'est le même échec que les trois rustinages du filtre anti-doublon (26/07,
28/07, 02/08) : **le discriminant n'existe pas dans les titres.** On s'en remet
donc à l'instrument mesuré sur cette question exacte — le juge de pertinence,
dont le backtest du 12/08 n'a jamais déclaré pertinente une source étrangère
(0 sur 30). Le hors-sujet arrive en queue de tri et n'entre pas dans le prompt.

## POIDS DE LA VEILLE — la mesure est branchée, la décision attend les runs

Le bonus de persistance vaut au maximum +25, soit moins que « source longue +
média connu ». C'est probablement trop peu : c'est le SEUL signal du barème qui
parle du sujet et non de son emballage. Mais rien n'était enregistré, donc rien
n'était mesurable.

Depuis le 17/08, `verification_log.json` porte `veille_heures_visible`,
`veille_passages`, `veille_age_h` et `veille_n_flux_grappe` à côté de l'issue.
`python scripts/analyser_veille_issue.py` croise les deux.

**La question, et rien d'autre : le taux d'aboutissement monte-t-il avec la
persistance ou le nombre de flux ?** Si oui, le bonus mérite plus de poids ; si
les colonnes sont plates, il n'en mérite pas. Ne fixer aucun seuil avant que ces
colonnes soient lisibles — et se souvenir qu'à n < 30 tout écart est du bruit.

## ACHARNEMENT — mesuré et bloqué le 17/08. Un quota entier dépensé à re-condamner

Le point 4 des « deux premiers travaux à faire » du 01/08 est enfin traité, avec
la clé qu'il recommandait (`_titre_norme`, jamais `item["id"]`).

Mesure sur `verification_log.json` : **11 sujets totalisent 42 générations
complètes, dont 31 sont des reprises d'un sujet déjà rejeté sur
`angle_insuffisant`** — ~1,1 M tokens, un quota journalier entier. Record :
« nouvelles addictions » 11 fois, Edgar Morin 7 fois en 5 jours, l'INSERM
magazine n°69 6 fois.

⚠ **Le seuil est mesuré, pas choisi.** Les deux retours gagnants identifiables
(sujet rejeté puis publié plus tard) ont demandé **1 et 3** rejets préalables :

```
bloquer dès la 2e tentative : tue les DEUX retours gagnants
bloquer dès la 3e           : économise 20 générations (~700 k tokens), en coûte 1
```

`ACHARNEMENT_MIN_REJETS = 2` (donc blocage à la 3e tentative),
`ACHARNEMENT_FENETRE_J = 7` — au-delà, le sujet peut revenir avec un angle neuf.

⚠ **Levier DISTINCT de celui écarté plus haut**, ne pas les confondre : le
résultat négatif du 15/08 portait sur l'allongement de `REJECT_COOLDOWN_HOURS`,
qui tue la PREMIÈRE reprise — souvent gagnante. Ici la première reprise reste
intacte ; on arrête seulement l'acharnement au-delà.

Ce qui rendait le blocage impossible jusqu'ici : la sélection ne connaît que le
titre RSS, alors que le journal ne portait que le slug GÉNÉRÉ — même décalage de
vocabulaire que le défaut A du filtre anti-doublon. C'est le champ `titre_rss`,
journalisé depuis le 14/08 via le contexte de vérification, qui rend
l'appariement exact possible. Le cooldown de `editorial_ranking.py` existait et
était testé, mais n'était branché qu'APRÈS génération (`run_pipeline_v3.py`) :
il économisait le fact-check, jamais les ~35 k tokens de rédaction.

Verrouillé par `scripts/test_acharnement.py` : égalité EXACTE de titre normalisé
(aucun rapprochement approximatif — il a échoué trois fois), seuls les rejets
portant `angle_insuffisant` comptent (une panne de quota ne condamne pas un
sujet), et journal absent ou illisible → aucun blocage.

## AUDIT DU CORPUS PUBLIÉ — 12/08, ce que valent réellement nos articles

Demande de Nahil : « nos articles ne sont même pas bien et pas intéressants ».
Audit des **161 articles longs publiés** (relecture du HTML, pas des journaux
de run). Tout ce qui suit est MESURÉ.

### Ce que dit le corpus

```
domaines les plus cités   Le Monde 58 · Futura-Sciences 45 · Sciences et Avenir 24
                          franceinfo 18 · Le Figaro 16 · Wikipédia 10 · Inserm 13
médiane                   4 sources/article  (confrère mesuré le 05/08 : 21)
densité factuelle         < 1 chiffre / 100 mots
articles SANS aucune date 60 / 161  (37 %)
redondance                médiane 10,5 % de 5-grammes répétés ; 116/161 > 3 %
longueur                  médiane 499 mots ; 0 / 161 atteint la cible de 800
sources listées jamais    médiane 20 % des sources ne sont pas nommées dans
nommées dans le corps     le corps de l'article
```

**Nous écrivons à partir de reprises de presse et de vulgarisation, pas de
documents.** L'Inserm arrive derrière Wikipédia dans nos sources. Le déficit
de matière que le format brève avait été créé pour absorber est là, entier :
le sourcing par question du 05/08 n'a jamais tourné sur un run complet (le
pipeline s'est arrêté le jour même), donc **rien de ce constat n'infirme ni ne
confirme les changements du 05/08** — il décrit le corpus d'AVANT.

### Taux de déclenchement des garde-fous sur les articles PUBLIÉS

Tous ces contrôles sont rejoués après la passe 3, mais uniquement en
AVERTISSEMENT (`_CONTROLES_AVERTISSEMENT`) : ils n'ont donc bloqué ni réparé
aucun des articles ci-dessous.

```
faits_repetitifs                107 / 161  (66 %)
attributions_trop_repetitives    95 / 161  (59 %)
sources_non_fusionnees           31 / 161  (19 %)   ← 16 % avant correctif
prise_de_position                21 / 161  (13 %)   ←  6 % avant correctif
cliches_ia                       10 / 161  ( 6 %)
nuances_vagues                    1 / 161  ( 1 %)
```

**Deux tiers des articles publiés déclenchent le détecteur de répétitions.**
C'est le chiffre à traiter en priorité, et il n'est PAS corrigé ici : il
demande de décider si ces avertissements doivent devenir bloquants ou
réparables, ce qui coûte du quota et n'a pas été tranché.

### Corrigé le 12/08 — la détection d'attribution était borgne

Cas d'école : `articles/rougeole-antiviral-etude.html`. Le titre promet un
antiviral à l'étude ; l'antiviral apparaît une fois, sans nom, sans
laboratoire, sans résultat. Le reste est une fiche encyclopédique sur la
rougeole, écrite à partir de pages permanentes (fiche « Rougeole » de l'OMS,
page « Données » de Santé publique France) qui ne parlent pas du sujet.

Deux angles morts dans `_sources_attribuees`, tous deux réparés et testés
(`scripts/test_attribution_empilement.py`) :

- **le nom précédé d'un article n'était pas vu** (« Selon le WHO », « d'après
  le Pasteur ») — le motif exigeait une majuscule juste après « Selon ». La
  phrase comptait comme NON attribuée et cassait la série de consécutives ;
- **un nom à mot minuscule interne était tronqué** (« Santé publique France »
  → « Santé »), si bien qu'un même organisme apparaissait sous plusieurs noms
  et gonflait le compte de sources DISTINCTES.

`MIN_SOURCES_DISTINCTES_EMPILEES = 2` remplace l'exigence de 4 sources
distinctes : le défaut le plus courant est la MÊME source étalée sur des
phrases consécutives (trois phrases d'affilée attribuées à Futura Sciences
dans `volcan-inconnu-sicile`), pas quatre sources différentes. Seuils mesurés
avant de choisir, et les 5 articles gagnés relus un par un — 5 vrais défauts,
aucun faux positif. La variante « série de 3 phrases » (30 % du corpus) a été
écartée : précision > rappel sur un garde-fou à relance.

`prise_de_position` couvre désormais « il est essentiel/crucial/primordial/
indispensable de… » (7 %), qui laissait passer « Il est essentiel de renforcer
la vigilance » — la moitié de la section « Débats et nuances » de l'article
rougeole. **`important` (50 % du corpus) et `nécessaire` (12 %) délibérément
exclus** : le premier est le connecteur déjà écarté de `cliches_ia` le 28/07,
le second attrape « il est nécessaire de poursuivre les recherches », qui est
exactement la réserve scientifique que la section doit contenir.

### Deux affirmations à ne PAS reprendre — vérifiées et fausses

- « Santé publique France est comptée deux fois, donc l'article n'a pas
  6 sources mais 5 » : faux dans ce qui compte. `bilan_qualite_sources`
  dédoublonne DÉJÀ par domaine (vérifié : deux URLs santepubliquefrance.fr +
  une who.int → 2 primaires, pas 3). La règle « ≥1 primaire OU ≥2 secondaires »
  n'est pas trompée. Seul l'affichage liste deux documents distincts, ce qui
  est exact.
- « le détecteur d'empilement ne déclenche pas » : il déclenchait, mais sur
  16 % au lieu des 40 % de phrases attribuées consécutives comptées à la main.
  L'écart venait de l'extraction des noms, pas du seuil de série.

### JUGE DE PERTINENCE — implémenté le 12/08, en TRI et pas en filtre

Le levier n°1 de l'audit est traité. `juger_pertinence_sources()` interroge un
petit modèle (`llama-3.1-8b-instant`) sur une question fermée et vérifiable :
« ce document traite-t-il du sujet PRÉCIS de l'article, ou seulement de son
thème général ? » Les sources sont ensuite triées pertinence d'abord, qualité
de domaine ensuite.

**Backtest avant implémentation** (`scripts/test_juge_sources.py`, 60 paires,
référence construite sans étiquetage humain : chaque source réellement citée
présentée avec son article puis avec un article étranger) :

```
                            PERTINENTE   GENERALE   HORS_SUJET
source ↔ SON article            20          10           0      (n=30)
source ↔ article étranger        0          19          11      (n=30)
```

**Les deux zéros sont le résultat** : jamais une vraie source déclarée hors
sujet, jamais une source étrangère déclarée pertinente. Sur le cas d'école
rougeole, le juge garde la seule source d'origine (Sciences et Avenir) et
écarte les cinq pages permanentes (OMS, Inserm, Pasteur, 2× Santé publique
France).

⚠ **ON TRIE, ON NE JETTE PAS.** La règle « n'accepter que PERTINENTE » perdrait
jusqu'à 33 % des sources citées ; avec une médiane de 4 sources par article et
un plancher de publication à 3, elle échangerait un problème de qualité contre
un problème de quantité. Ce 33 % est d'ailleurs un PLAFOND : une partie de ces
sources « perdues » sont des pages génériques que le juge a raison d'écarter —
même contamination de la référence que pour le juge de sujet.

Le cas « zéro source pertinente » est journalisé en AVERTISSEMENT
(`[PERTINENCE]`), pas en rejet : son taux réel n'a jamais été mesuré sur un run
complet. **À rendre bloquant quand quelques runs l'auront chiffré** — c'est
exactement le cas rougeole.

Innocuité verrouillée par `scripts/test_pertinence_sources.py` : sans clé, sans
réseau, sur erreur API ou réponse inattendue, le juge renonce et laisse le tri
par qualité. Il renonce dès la PREMIÈRE erreur (en rate limit, insister sur dix
sources ferait attendre le run entier pour un simple tri), ne supprime jamais
une source, et s'éteint avec `JUGE_SOURCES=0`. Plafond `JUGE_SOURCES_MAX = 10`
sources jugées : les 45 résultats bruts ne partent pas tous dans le prompt,
juger la queue serait payer pour classer ce qui ne sera pas lu.

**Le surcoût contre le budget de génération est NUL, pas de ~7 %.** Une
première estimation raisonnait en jetons comme s'ils étaient fongibles : ils ne
le sont pas. Les limites Groq sont PAR MODÈLE — `_TPM_PAR_MODELE` donne 12 000
tokens/min au 70b et 6 000 au 8b, deux compteurs distincts. Le juge puise donc
dans un stock que le rédacteur n'utilise pas, ce qui compte d'autant plus les
jours où les comptes sont à 90-99 % du TPD sur le 70b. ⚠ Inférence forte, non
encore observée : la table par modèle prouve la séparation du TPM, la même
structure vaut chez Groq pour le TPD mais aucun refus sur le 8b ne l'a confirmé
chez nous. Vérifiable gratuitement au prochain run — un refus sur le juge
nommera `llama-3.1-8b-instant` dans le corps d'erreur.

Cette propriété disparaît si le juge est pointé sur le modèle de rédaction : il
mangerait alors le quota qui bloque déjà les runs, en silence. Le juge REFUSE
donc de démarrer quand `JUGE_SOURCES_MODELE == GROQ_MODEL`, et le dit.

Le tri et la fenêtre TPM sont COMPLÉMENTAIRES, pas redondants : réduire la
fenêtre change combien de matière passe, le tri change laquelle. À budget large
les sources passent toutes quel que soit l'ordre ; à budget serré, l'ordre EST
la sélection — le tri devient structurant exactement là où la place manque.

### RÉSULTAT NÉGATIF — juge de SUJET, ne pas retenter tel quel

`scripts/test_juge_sujet.py` demandait au même petit modèle « ce sujet
mérite-t-il un article ? », sur 184 sujets étiquetés par l'issue réelle de leur
vérification (84 `angle_insuffisant`, 100 menés au bout). **50 % de justesse sur
un échantillon équilibré, soit exactement le hasard.**

Deux enseignements, le second plus important que le premier :

- le juge ne voyait que le titre reconstitué depuis le slug (« Cxmt levee de
  fonds asie »), sans accents ni ponctuation — handicap réel ;
- **la référence elle-même est fausse.** Parmi les « bons articles » que le juge
  a écartés figurent « Obsessed fest prime video romcom » (l'événement marketing
  Amazon qui a motivé `_PR_MARQUE_RE`) et « Nettoyage toilettes erreurs ». Ces
  sujets ne sont pas étiquetés bons, ils sont étiquetés « le fact-checker ne les
  a pas signalés creux ». Le juge avait raison contre l'étiquette.

La différence avec le juge de sources est structurelle et vaut pour toute
tentative future : « ce document traite-t-il de ce sujet ? » est une question
FACTUELLE, avec une bonne réponse qu'un humain peut trancher ; « ce sujet
mérite-t-il un article ? » est un jugement éditorial non vérifiable. Refaire ce
test proprement suppose de construire une référence à la main, sujet par sujet.

### Non fait, et pourquoi

- **Abandon avant génération quand le sujet du titre n'est documenté nulle
  part** : le juge de pertinence fournit désormais le signal (`[PERTINENCE] 0
  source`), il reste à en faire un rejet une fois le taux mesuré.
- **Contrôle « article sans aucune date »** (37 % du corpus) : à ajouter en
  avertissement d'abord.
- **Analyse du Courrier de France** : le domaine est bloqué par la politique
  réseau du sandbox (403 du proxy sur CONNECT, sept chemins essayés). Aucune
  analyse n'a pu être faite ; ne pas reconstruire leurs articles de mémoire.
  Voies possibles : allowlist du proxy, ou un job GitHub Actions jetable qui
  récupère le HTML en artefact (même mécanisme que `check_feeds.yml`).

## IMAGES — la coupe par fenêtre attribue le gain mesuré au 30/07, pas au 05/08

Mesure de la part d'images « étape 0 » (source institutionnelle propre à
l'article, via `data-img-source`) faite par une session parallèle, revérifiée
le 07/08 après synchro (23 commits de retard sur `origin/main` au moment de la
mesure initiale — corrigé, `a85e056` et `d46f265` sont bien mergés).

```
                                              n    étape 0
avant le 30/07                               130     19 %
30/07 → 04/08  (réparation requête DDG seule) 15     33 %
depuis le 05/08 (+ sourcing question + PDF)    4     25 %
```

**Le gain mesuré (19 % → 33 %) est entièrement dans la fenêtre où seule la
réparation du 30/07 était active.** L'apport du sourcing par question et de
l'extraction PDF (05/08) reste NON MESURÉ — n=4, ni confirmé ni infirmé. Ne pas
créditer le 05/08 de ce gain ; ne pas non plus conclure qu'il n'apporte rien.
Refaire cette coupe à trois fenêtres quand la fenêtre du 05/08 aura une
quinzaine d'articles.

**Affirmation retirée** : une mesure précédente disait les images de dernier
recours (repli `pillow`) « entièrement disparues depuis le 30/07 ». Faux — un
des 4 articles publiés depuis le 05/08 est en `pillow`. L'affirmation reposait
sur n=15 et n'a pas tenu 4 articles de plus. Le fond (ces images sont devenues
rares) reste vrai ; l'absolu ne l'était pas. Même travers que le run du matin
compté 1/6 et les brèves comptées 3/10 plus tôt cette semaine — sur un petit n,
ne jamais écrire « toujours »/« jamais », écrire la fraction et se souvenir
qu'elle bougera.

## PIÈGE ÉVITÉ — leur page « logiciel libre » n'est pas un modèle à copier

Nahil a partagé la page technique du Courrier de France (Debian, Caddy,
CrowdSec, Poppler, faster-whisper…). Tentation immédiate : en publier une
équivalente. **Écarté** : la moitié de leur liste décrit un serveur qu'ils
opèrent eux-mêmes (OS, pare-feu, certificats) — nous sommes sur GitHub Pages,
sans serveur à nous. Une page copiée aurait prétendu à une infrastructure
qu'on n'a pas, exactement le genre de faux qu'on retire sur `corrections.html`.

**Ce qui comptait dans cette page, ce n'était pas la lister nous aussi — c'est
ce qu'elle révèle de LEUR architecture de collecte, pour combler un vrai
écart chez nous :**

- `Poppler` (lecture de PDF) → **implémenté le 05/08**, voir ci-dessous.
- `faster-whisper` + `FFmpeg` (transcription locale de podcasts/conférences)
  → PAS implémenté. Coût de calcul et de dépendances trop lourd pour le
  budget de ce run (CPU du runner GitHub, quota Groq déjà la ressource rare).
  À reconsidérer seulement si le gisement PDF ne suffit pas.
- `curl` + `pandoc` (texte complet, pas juste un snippet) → on le fait déjà
  depuis avant (`fetch_full_content`), rien à changer.

### PDF officiels — le vrai trou comblé

`fetch_full_content()` passait un PDF à BeautifulSoup comme si c'était du
HTML — bruit ou chaîne vide, jamais exploité. Or les rapports de la Cour des
comptes, du Sénat, de l'IGAS, des institutions européennes sont très souvent
des PDF : exactement les documents que `_AXES_RECHERCHE` (05/08) est censé
aller chercher. Sans extraction dédiée, ces liens ne servaient à rien.

`_extraire_texte_pdf()` (pypdf, pur Python — aucun binaire poppler à
installer sur le runner) détecte le PDF par Content-Type ou suffixe d'URL,
lit les 25 premières pages (résumé exécutif + premiers constats chiffrés,
borne le temps d'extraction sur un rapport de plusieurs centaines de pages).
Échec d'import ou PDF corrompu/scanné sans couche texte → chaîne vide,
JAMAIS d'exception qui ferait perdre le sujet entier.

Non mesuré sur un run réel — le sandbox de développement n'a pas d'accès
réseau vers ces domaines. Testé en isolant la logique d'intégration (bornage
25 pages, résilience à l'échec d'import, non-régression du chemin HTML) avec
un `PdfReader` simulé.

## PANNE DU 06/08 — run du matin perdu, run de l'après-midi bloqué 3h31 pour 0 article

Deux runs, deux causes distinctes, aucune liée aux changements du 05/08.

### Run du matin (03h32) : 151 articles générés, jamais publiés

`git rebase origin/main` échouait immédiatement avec `error: cannot rebase:
You have unstaged changes` — le commit contenant le travail restait local au
runner, détruit à la fin du job. **Cause** : la commande `git add` de l'étape
« Sauvegarder les articles générés » dans `pipeline.yml` listait
`articles/ assets/ categories/ data/ index.html archive.html feed.xml
sitemap.xml src/` — sans `breves.html` ni `favoris.html`, tous deux régénérés
par `rebuild_index()` au même titre que `index.html`. Ils restaient modifiés
mais NON STAGÉS après le commit, et bloquaient le rebase automatique.

Même classe de bug que celui corrigé dans `deploy.yml` le 03-04/08
(`breves.html` absent de sa liste blanche de copie) — mais ce sont deux
mécanismes de publication différents (`git add` local vs `cp` vers le repo
public), donc deux listes séparées, et seule celle de `deploy.yml` avait été
corrigée.

**Corrigé** : les deux fichiers ajoutés à la liste, et un filet de sécurité
ajouté dans la boucle de retry (`git add -A` + `git commit --amend --no-edit`
avant chaque nouvelle tentative de rebase) pour qu'un futur fichier généré
oublié de la liste ne puisse plus reproduire ce blocage.

### Run de l'après-midi (13h01) : 3h31, 0 article, annulé

`generate()` a deux chemins d'échec sur épuisement de quota :
- toutes les clés définitivement mortes → `QuotaJournalierEpuise` (type dédié,
  rattrapé par `run()` qui arrête proprement la boucle) ;
- des clés pas encore marquées mortes, mais dont les 8 cycles courts (62 s) de
  nouvelle tentative échouent quand même → **`RuntimeError` nu**, jamais
  rattrapé par le `except QuotaJournalierEpuise` de `run()`. Le sujet suivant
  était alors tenté, retombait sur les MÊMES clés dans le même état, et
  répétait l'attente — enchaîné pendant 3h31 sans produire un seul article,
  jusqu'à l'annulation externe du job.

Le problème est resté invisible avant le 05/08 parce que l'attente maximale
avant abandon (`ATTENTE_MAX_LIBERATION`) était de 15 min ; une session
parallèle l'a portée à 150 min via `GROQ_WAIT_MAX_MINUTES` (mode vitrine,
`scripts/run_pipeline.py`) pour donner sa chance à un run tardif — ce qui a
aussi multiplié par 10 le coût de chaque répétition du bug.

**Corrigé** : le second chemin lève maintenant `QuotaJournalierEpuise` lui
aussi. Si les 8 cycles courts n'ont rien débloqué juste après avoir déjà
attendu jusqu'à `ATTENTE_MAX_LIBERATION` pour la meilleure clé, aucun sujet
suivant n'ira mieux tant que la fenêtre glissante n'a pas bougé — le run
s'arrête au lieu de tourner à vide.

### Le « mode vitrine » découvert au passage (scripts/run_pipeline.py)

Une session parallèle a construit, sans modifier `pipeline.py` directement,
un point d'entrée qui l'enveloppe : patch du prompt de génération via un proxy
sur le client `groq` (exigences éditoriales renforcées — 6+ sources sur 5+
domaines, 420/180/130 mots par section, 10+ appels de citation, intertitres
obligatoires), une grille de validation supplémentaire avant écriture HTML
(`showcase_quality.py`), et un plafond dur sur le nombre d'articles
RÉELLEMENT ACCEPTÉS (`MAX_SHOWCASE_PUBLICATIONS`, 2 par défaut) — le run
s'arrête dès que ce nombre est atteint plutôt que d'épuiser la sélection.
C'est la mise en œuvre de la demande de Nahil du 05/08 (« deux trois articles
mais je veux de l'excellence »), construite en couche au-dessus de
`SYSTEM_PROMPT` plutôt qu'en le réécrivant.

## RÉDACTION — angle, intertitres, citations numérotées (05/08, décision Nahil)

Suite directe de l'audit Courrier de France : Nahil a validé les trois chantiers
qui restaient ouverts, et demandé d'arrêter la brève comme format par défaut —
« deux trois articles mais je veux de l'excellence, long, bien rédigé,
intéressant ». Implémenté dans `SYSTEM_PROMPT` (articles complets uniquement,
voir « Ce qui n'a PAS été touché » plus bas).

### 1. `angle_reponse` — une question avant d'écrire

Nouveau champ JSON, rempli AVANT le reste : la question précise, du point de
vue du lecteur, à laquelle l'article va répondre (« ce chiffre change-t-il
quelque chose pour la France ? », pas « que s'est-il passé ? »). Le
fact-checker vérifie maintenant la congruence (extension du critère
`angle_insuffisant`) : un article qui expose des faits sans jamais revenir à
sa propre question est un angle manqué, même bien sourcé.

### 2. Intertitres éditoriaux

`titre_faits` / `titre_contexte` / `titre_nuances` remplacent en rendu les
noms de fonction fixes (« Les faits », « Contexte », « Débats et nuances »).
Repli sur ces libellés génériques si le champ est absent — articles
antérieurs au 05/08, brèves (qui n'en produisent pas), ou omission du modèle.
Ne touche à AUCUN garde-fou : ils opèrent tous sur `corps.faits/contexte/
nuances` (le contenu), jamais sur ces nouveaux champs (le titre affiché).

### 3. Citations numérotées — fin de l'attribution en prose

Le corps ne contient plus « Selon Le Monde, RTBF et 20 Minutes » : chaque fait
porte un `[n]` renvoyant au n-ième élément du tableau `sources`. Rendu par
`_rendre_citations()` dans `build_article_html` en lien cliquable vers
`<li id="source-n">` dans le bloc SOURCES.

**Point d'attention géré** : la position `n` doit rester celle du tableau
`sources` D'ORIGINE, jamais celle de `verified_sources` (liste filtrée sans
URL valide) — sinon toute source filtrée décale les numéros de citation qui
la suivent et casse tous les liens en aval. Résolu par `id(s)` (les objets
sources ne sont jamais copiés entre les deux listes) plutôt que par un
recomptage. Testé avec des sources filtrées en position 2 et 3 : les citations
`[1]` et `[4]` pointent bien vers `id="source-1"` et `id="source-4"`, pas vers
un décompte 1/2.

**Garde-fou dédié** : `citations_hors_liste()` détecte un `[n]` sans source
correspondante — même famille de défaut que `attributions_fantomes`, et
rejoué après la passe 3 pour la même raison (voir le retrait du 03/08 : un
défaut de ce type réintroduit par la correction et jamais revérifié après).
Réparation déterministe par `strip_citations_invalides()` : retire le numéro,
jamais la phrase entière (une citation mal reliée ne rend pas le fait faux).
`verification.py` (`PROMPT_DETECTION`) est informé du nouveau format pour ne
pas signaler l'absence de nom de média comme un défaut.

### Le format brève n'est plus la colonne vertébrale

`QUOTA_ARTICLES_LONGS` 4 → 30 (couvre la quasi-totalité de la sélection) :
la brève avait été créée pour compenser un déficit de matière ; le sourcing
par question (voir section précédente) répare une bonne part de ce déficit.
La brève reste le SEUL filet de sécurité via la conversion automatique
existante (`CONVERSION_BREVE_SI_COURT`) : un sujet qui n'atteint vraiment pas
le plancher article bascule en brève au lieu d'être rejeté — elle n'est plus
choisie par défaut, elle reste choisie par nécessité.

`SEUILS_FORMAT["article"]["cible"]` 500 → 800 mots. Le PLANCHER reste 350 —
ne jamais rejeter un article par ailleurs bon parce qu'un sujet précis avait
moins de matière que la moyenne. Ne monter le plancher qu'après avoir mesuré
que la nouvelle cible est tenue sans relance systématique.

### Ce qui n'a PAS été touché — à faire si le résultat le justifie

- **`SYSTEM_PROMPT_BREVE`** garde l'attribution groupée en prose (règle 6 du
  02/08) : elle fonctionne pour ce format et n'a pas la place structurelle
  pour des intertitres (pas de contexte/nuances à nommer). Ne pas lui
  appliquer les citations numérotées sans mesurer d'abord si le format brève
  survit à la baisse de `QUOTA_ARTICLES_LONGS`.
- **`SYSTEM_PROMPT_DOSSIER_PORTRAIT` / `SYSTEM_PROMPT_DOSSIER_SCIENCE`** :
  aucun `angle_reponse` ni intertitre éditorial. Rendu inchangé pour ces
  formats (repli automatique sur les libellés génériques).
- Aucune mesure réelle encore : le prochain run est le premier avec ces trois
  changements. À lire en priorité — le taux de citations hors liste rejouées
  après correction (`[RÉPARATION] … citation(s) hors liste`), et si la cible
  de 800 mots est atteinte sans relance systématique.

## SOURCING PAR QUESTION — 05/08, le vrai écart avec la concurrence

Nahil a trouvé **Le Courrier de France** (lecourrierdefrance.fr), autre journal
100 % IA, et demandé pourquoi leurs articles sont plus intéressants. La réponse
est structurelle, pas rédactionnelle. Mesure sur un de leurs articles (Ceuta,
1er août) contre nos 149 publiés :

```
NOUS : médiane 4 sources (max 10), presque toujours des reprises de la même dépêche
EUX  : 21 sources — droit primaire (EUR-Lex, code frontières Schengen art. 41),
       2 arrêts de la CJUE, séries statistiques, 2 organismes de vérification,
       chacune datée, typée (officiel/investigation/partie prenante/académique)
       et appelée par une NOTE NUMÉROTÉE au niveau de chaque affirmation
```

**La cause n'était pas la qualité de la recherche, mais sa QUESTION.** Nos trois
requêtes demandaient « qui d'autre parle de ce sujet ? » — une logique de
CORROBORATION, qui ne peut par construction ramener que des articles de presse.
Une logique de RECHERCHE demande « quels documents établissent les faits de ce
sujet ? » et va chercher le texte de loi, l'arrêt, la série statistique, le
rapport d'audit, la vérification.

C'est aussi la racine du déficit de matière qui avait motivé le format brève :
ces documents étaient disponibles depuis le début, on ne les cherchait pas.
**Ne pas en conclure que la brève était une erreur** — elle reste le bon format
quand la matière est réellement mince ; mais elle traitait un symptôme.

### Ce qui a été implémenté (05/08)

`_AXES_RECHERCHE` dans `duckduckgo_search()` : **4 axes universels + 1 à 2 axes
propres à la rubrique**, soit 5 à 6 requêtes par sujet au lieu de 3.

```
universels : générique · officiel/juridique · contrôle/audit · vérification
par rubrique : santé officielle + littérature médicale (sante),
               publication scientifique (science), environnement officiel,
               statistiques économiques (economie), statistiques publiques
               (societe), régulation numérique (tech)
```

Trois points à ne pas défaire :
- **Ne JAMAIS interrompre la boucle sur `len(results) >= max_results`.** Les axes
  documentaires passent APRÈS l'axe générique : couper au plafond revient à ne
  jamais les exécuter. C'est exactement le bug du 30/07, qui avait rendu la
  requête institutionnelle inatteignable pendant des semaines.
- **Tout nouveau domaine visé par un axe DOIT être ajouté à
  `_DOMAINES_PRIMAIRES` ou `_DOMAINES_SECONDAIRES`**, sinon il compte
  « tertiaire » et ne vaut rien pour la règle « ≥1 primaire OU ≥2 secondaires » —
  la recherche ramènerait la bonne source et le contrôle l'ignorerait. Ajoutés
  le 05/08 : OCDE, GIEC, Citepa, EFSA, FMI, Banque mondiale, FAO, OIT, CEDH,
  Défenseur des droits, CNIL, Arcom, Autorité de la concurrence, IGAS, France
  Stratégie. Et en secondaires, les organismes de VÉRIFICATION (AFP Factuel,
  Newtral, Full Fact, Maldita, Correctiv) — ils n'établissent pas le fait mais
  ils établissent si une affirmation publique est étayée, matière qui nous
  manquait totalement.
- `max_results` 26 → 45 : avec 5-6 axes le vivier brut est plus large, et couper
  à 26 jetterait précisément les documents des derniers axes. Le tri par qualité
  et `BUDGET_MATIERE` bornent ce qui part réellement dans le prompt — élargir
  ici ne coûte AUCUN token Groq.

`[SOURCING]` journalise à chaque sujet le total, la répartition primaire/
secondaire/tertiaire ET le rendement par axe. **C'est la mesure à lire au
prochain run** : elle dira quels axes rapportent des documents et lesquels sont
du temps perdu, pour élaguer sur des chiffres plutôt qu'à l'intuition.

### Les deux chantiers suivants, non faits

2. **Notes de bas de page numérotées** à la place de l'attribution en prose
   (« Selon Libération, RTBF et 20 Minutes… »). Ça supprimerait à la racine
   l'empilement « une phrase = une source » qu'on combat depuis le 28/07 avec
   `sources_non_fusionnees`, la règle 6 des brèves et deux détecteurs — le texte
   redevient fluide et la preuve reste attachée à l'affirmation.
3. **Intertitres éditoriaux** au lieu de « Les faits / Contexte / Débats et
   nuances ». Les leurs portent l'information et font avancer la démonstration
   (« Le chiffre de la nuit, et ce qu'il contient », « Libre circulation et
   Schengen : deux régimes distincts ») ; les nôtres sont des noms de fonction,
   du mobilier, identiques sur tous les sujets.

### La question éditoriale que ça pose, et qui appartient à Nahil

Leur article écrit : « L'agence AP classe cette causalité *non étayée*. Newtral
ne la valide pas non plus. » Puis donne le raisonnement : « Un appel d'air
général se verrait partout, pas sur un seul point pendant qu'il recule ailleurs. »

C'est un argument tiré des données, et c'est neutre. **Notre charte l'interdit de
fait** : `prise_de_position` est si large qu'on ne peut pas écrire « cette
affirmation n'est pas étayée » même quand deux organismes de vérification le
disent. On confond neutralité et abstention, et c'est pourquoi nos articles ne
répondent jamais à la question que le lecteur se pose. À trancher.

## AUDIT ESTHÉTIQUE/LIENS DU 04/08 — .nav-dropdown cassé sur 171 pages, et un garde-fou permanent

Nahil a demandé un audit complet, focalisé esthétique/liens, après plusieurs
allers-retours frustrants sur des défauts visuels ponctuels (page contact).
Le vrai défaut n'était pas là où on le cherchait.

**Le bug le plus grave** : le template article (`build_article_html`) utilise
un menu déroulant `.nav-dropdown` / `.nav-dropdown__trigger` /
`.nav-dropdown__menu` / `.nav-dropdown__sep` — **sans AUCUNE règle CSS nulle
part**, ni dans `src/style.css`, ni en `<style>` inline. Sur **171 des
192 pages du site** (toutes les pages article, donc la quasi-totalité du
trafic), le menu "Société / Science / Économie / Tech / Santé /
Environnement / Favoris / …" s'affichait en liste brute, non positionnée,
sans fond ni bordure. Les pages statiques (index, catégories, archive) ont un
menu ANALOGUE mais sous d'autres noms de classe (`nav-cats-dd`,
`nav-cats-wrap`), correctement stylé — les deux implémentations ont divergé
et seule celle des articles a été oubliée. **Corrigé** : CSS ajoutée dans
`src/style.css` juste après `.nav-cats-dd`, reprenant le même habillage
visuel. Aucune page article n'a eu besoin d'être patchée : la feuille de
style est chargée par toutes, donc le correctif s'applique instantanément
partout.

**Deux autres défauts réels, corrigés à la source** (`scripts/pipeline.py`) :
- `var(--border)` dans le template `.archive-row` (archive.html, favoris.html)
  — cette variable CSS n'existe nulle part, le vrai nom est `--rule`. Le
  séparateur entre lignes de liste était donc invisible. Corrigé aux deux
  occurrences, puis `--rebuild` relancé pour regénérer archive.html/
  favoris.html/index.html avec la bonne valeur (149 pages concernées).
- `&` non échappée dans le lien de partage Twitter (`&text=` au lieu de
  `&amp;text=`) — HTML invalide (les navigateurs le tolèrent, mais ça reste un
  défaut). Corrigé à la source ; **les 171 articles déjà publiés le portent
  encore** (pas de patch rétroactif fait — impact visuel nul, priorité basse).

**Trois choses ressemblaient à des bugs et n'en étaient pas** — à ne pas
re-signaler sans vérifier à nouveau :
- `.meta__src`, `.archive-row`, `.audio-player__ctrl--stop`, `.list-section`
  n'ont pas de CSS dédiée, mais tout leur style vient d'un `style=""` inline
  ou d'une classe parente (`.meta`) — fonctionnement voulu, pas un oubli.
- `breves.html` n'existe qu'après `--rebuild` (comme `index.html`) : absent
  du dépôt tant qu'aucun rebuild n'a tourné, ce n'est pas un lien cassé.
- Les ancres `../contact.html#erreur` depuis `articles/` avec `<base href="/">`
  se résolvent correctement (RFC 3986 : les navigateurs clampent au domaine
  racine, un premier audit maison avec une résolution de chemin naïve les
  signalait à tort).

### Le garde-fou permanent — pour que ça ne se reproduise plus

`scripts/check_seo.py` (déjà bloquant au déploiement, voir `deploy.yml`)
détecte désormais **toute classe utilisée dans le HTML sans définition CSS
trouvée nulle part** (`classes_sans_css()`), scanné sur les pages statiques
ET sur les 171 articles — pas un échantillon, parce que c'est justement un
échantillon qui avait laissé passer celui-ci. Une classe volontairement sans
CSS dédiée (style entièrement inline) doit être ajoutée à
`CLASSES_HOOK_SANS_CSS` **après vérification manuelle**, jamais pour faire
taire l'alerte. C'est le même principe que le garde-fou blanc-liste de
`deploy.yml` (03/08) sur les pages non copiées : une nouvelle classe HTML est
un signal qui doit être vu, jamais un échec silencieux.

## RETRAIT PUBLIC DU 03/08 — et le balayage qu'il a déclenché

**Article retiré :** « L'IA Claude d'Anthropic s'échappe d'un test et pirate
trois entreprises » (03/08, 06h02). Retrait documenté sur `corrections.html`,
stub de redirection vers `/categories/tech.html`, sorti de l'index.

Son chapeau s'ouvrait sur **« Selon des sources autorisées »** — une
attribution qui ne renvoie à aucune source réelle, sur un journal dont
l'attribution est la règle fondatrice. Il présentait en outre une erreur de
configuration comme une évasion délibérée d'un modèle, et ses 8 sources étaient
8 reprises d'une même annonce, sans lien vers la publication d'origine.

### Cinq causes, toutes des classes déjà connues

1. **Routage décidé sur le TEASER RSS.** `classifier_type_article` a envoyé
   l'article en `dossier_science` : le titre seul donne `actu`, c'est
   `_SCIENCE_HYPO_RE` qui a matché dans `snippet[:500]`. Une actualité chaude a
   reçu le prompt « exploration scientifique hypothétique ». **Quatrième**
   occurrence de la classe « décision prise sur l'extrait RSS » (catégorie,
   `_PR_MARQUE_RE`, flux Atom). Le fact-checker a pourtant renvoyé
   `nature_contenu: "actualite_factuelle"` — l'information était dans le
   rapport, rien ne s'en sert.
2. **`attributions_fantomes` n'était pas rejoué après la passe 3.** Rejoué sur
   le texte publié, il déclenche sur « des sources autorisées ». Il ne tournait
   qu'avant `verifier_article` ; la correction a réintroduit ce que la relance
   avait nettoyé. **CORRIGÉ le 03/08.**
3. **`source_derivee_comptee_comme_primaire` signalé DEUX fois, non bloquant.**
   Bilan réel : 0 primaire, 2 secondaires, 6 tertiaires.
4. **`incoherence_inter_sections` n'a pas vu la contradiction** entre le chapeau
   (« s'échappe », « contourner les mesures de sécurité ») et les nuances
   (« aucun comportement autonome n'a été observé »). Motif bloquant, muet ici.
5. **Le budget d'articles longs ne bornait pas les dossiers.** La bascule vers
   la brève ne s'applique qu'à `actu` : run du soir 6 dossiers pour 1 actu,
   `longs_restants` à −3. **Dossiers suspendus le 03/08**, voir plus bas.

### Mesure : ne PAS rendre `source_derivee_comptee_comme_primaire` bloquant

Mesuré sur les 166 articles publiés, avant tout changement :

```
0 source PRIMAIRE                    : 114 articles (69 %)
  dont publiés sur « ≥2 secondaires » :  63
motif dans les rapports journalisés   :  35 sur 80 rapports (44 %)
```

Très au-dessus du seuil de ~10 % du corpus au-delà duquel la règle du projet
juge un motif trop large. Le bloquer rejetterait la majorité de la production.
Le vrai levier est en amont — trouver des sources primaires, pas rejeter en
aval celles qui n'en ont pas.

**Et ce levier fonctionne déjà.** La 3e requête DuckDuckGo
(`site:gouv.fr OR inserm OR insee OR who.int`) n'était JAMAIS exécutée avant sa
réparation du 30/07 : la boucle s'arrêtait au plafond de résultats avant de
l'atteindre. Mesure en coupant le corpus à cette date :

```
publiés AVANT le 30/07  : n=133  sans primaire 70 %  moy. 0,47 primaire/article
publiés DEPUIS le 30/07 : n= 15  sans primaire 53 %  moy. 1,20 primaire/article
```

La moyenne de sources primaires par article est **multipliée par 2,5**. Le 69 %
global est donc un héritage des 133 articles antérieurs, pas l'état courant de
la production. ⚠ n=15 : à reconfirmer sur un corpus plus large avant toute
décision — mais l'hypothèse « la requête ne rend rien d'exploitable » est
réfutée. Ne pas la ré-émettre sans refaire cette coupe par date.

### Balayage complet : contrôles avant `verifier_article`

La passe 3 réécrit le texte ET la liste des sources. **Tout contrôle placé
avant elle doit être considéré comme invalidé.** État au 03/08 :

| contrôle | rejoué après | décision |
|---|---|---|
| `attributions_fantomes` | **oui** (03/08) | garder — c'est la règle fondatrice, réparation par `strip_attributions_invalides` puis rejet si insuffisant |
| `faits_repetitifs` | oui | garder, avec `_supprimer_phrases_dupliquees` |
| `resume_repete_corps` | oui | garder |
| longueur (mots) + nombre de sources | oui (calcul inline, pas via `_deficit_longueur_sources`) | garder |
| `bilan_qualite_sources` | oui | garder |
| `_reduire_en_breve` | oui | garder — le correcteur rouvre les sections vides |
| `_est_rejete_sensible_deterministe` | **oui** (03/08) | garder — contrôle BLOQUANT de nature légale : la correction peut réintroduire du vocabulaire de victime ou de procédure pénale. Aucune réparation possible, rejet sec. |
| `sujet_sante_sans_source_officielle` | **oui** (03/08) | garder — la passe 3 réécrit la liste des sources : un article santé peut perdre la source officielle qui autorisait sa publication. Rejet sec. |
| `attributions_trop_repetitives`, `titre_de_mauvaise_qualite`, `cliches_ia`, `intro_generique`, `nuances_vagues`, `affirmation_non_demontree`, `sources_non_fusionnees`, `incoherence_temporelle`, `prise_de_position` | NON | acceptable : ce sont des AVERTISSEMENTS, pas des blocages. Mais depuis le 03/08 ils sont journalisés — les rejouer après correction coûte zéro token et rendrait le journal exact. À faire quand le reste sera stable. |

Ne pas ajouter un contrôle avant `verifier_article` sans trancher sa ligne dans
ce tableau.

### Ne JAMAIS juger un fait récent à l'aune de la connaissance d'un LLM

Le 04/08, la brève « Anthropic : trois organisations touchées » a failli être
retirée parce qu'elle citait un modèle nommé **« Claude Mythos 5 »**, jugé
improbable — les gammes connues étant Opus, Sonnet, Haiku, Fable. Vérification
faite à la source primaire : **Claude Mythos 5 existe**, annoncé le 9 juin 2026,
modèle de cybersécurité en accès restreint (Project Glasswing). Sa présence
dans un article sur des tests de cybersécurité est parfaitement cohérente.

Deux relecteurs successifs ont conclu « nom inventé » à partir de la même
limite de connaissance (mai 2026) pour un fait de juin. Un retrait sur cette
base aurait supprimé un article exact et publié une correction fausse.

Cela vaut AUSSI pour le pipeline : le fact-checker tourne sur Llama 3.3, dont
la connaissance s'arrête elle aussi dans le passé. Il peut signaler comme
inventé un nom de produit, une institution ou un événement postérieurs à son
entraînement. C'est pourquoi `source_inventee` doit se lire « absent des
sources fournies », jamais « inconnu de moi ».

**Le seul critère est la charte, règle 5 : le fait figure-t-il littéralement
dans les extraits fournis ?** Vérifiable, publiable en justification, et
indépendant de ce que quiconque croit savoir. Ne pas y substituer un jugement
de vraisemblance.

### `conforme_du_premier_coup` ne veut pas dire « sorti propre »

Ce statut ne reflète QUE le fact-check LLM. Un article peut porter plusieurs
avertissements de garde-fous déterministes restés sans effet et être compté
conforme. Jusqu'au 03/08 ces avertissements n'existaient que dans la sortie
GitHub : toute statistique de conformité par format était ininterprétable.
Ils sont désormais journalisés dans `avertissements_garde_fous`. **Ne rien
construire sur les taux de conformité mesurés avant cette date.**


## FORMAT BRÈVE — introduit le 02/08, À MESURER AU PROCHAIN RUN

**Le diagnostic qui l'a motivé.** Sur les 251 vérifications loguées depuis le
début, **2 articles étaient conformes du premier coup (0,8 %)**. Un taux
d'échec de 99 % ne décrit pas des sorties ratées : il décrit une consigne
impossible. On demandait 500 mots en quatre sections à partir d'une matière
qui, une fois retirée la redondance entre sources (les mêmes dépêches
reprises), en portait souvent 150.

Le modèle n'avait alors que deux issues : s'arrêter court (→ relance
d'étoffement, premier poste de dépense du run) ou remplir. Quand il remplit, il
produit exactement ce que les garde-fous détectent. Et surtout : « Contexte » et
« Débats et nuances », n'ayant aucune matière factuelle à contenir sur un sujet
mince, se remplissent de cadrage. **Le cadrage inventé, c'est la prise de
position** — le seul défaut que ce journal ne peut pas se permettre.

**Ce n'est PAS un assouplissement de la charte.** Attribution, neutralité,
sourcing (3 sources minimum, ≥1 primaire OU ≥2 secondaires), fact-check en
3 passes, `angle_insuffisant`, blocs légaux : tout s'applique à l'identique. Le
plancher de l'ARTICLE reste 350 mots — aucun texte de 250 mots n'est publié
« en tant qu'article ». C'est le format qui s'aligne sur la matière disponible,
au lieu de l'inverse.

### Comment ça marche

- **`SYSTEM_PROMPT_BREVE`** (pipeline.py) : chapeau d'une phrase + `faits` de
  110-200 mots. `contexte` et `nuances` sont des chaînes VIDES, `positions` est
  neutralisé. Prompt de 5 450 caractères contre 16 129 pour l'article.
- **Allocation par BUDGET, pas par prédiction de qualité.**
  `QUOTA_ARTICLES_LONGS = 4` dans `run()` : les 4 sujets les mieux notés (la
  sélection est déjà triée par score éditorial) reçoivent le format long, tout
  le reste part en brève. Aucun seuil de « richesse » n'a été inventé — la
  règle du projet interdit de fixer un seuil non mesuré, et aucune distribution
  d'`audit_matiere` n'a encore été relevée. C'est le seul paramètre à bouger
  pour arbitrer profondeur / couverture.
- **Conversion a posteriori** (`CONVERSION_BREVE_SI_COURT`) : un premier jet
  d'article sous 350 mots dont le chapeau + `faits` atteint 100 mots bascule en
  brève **immédiatement, avant la relance corrective** — au lieu de payer un
  étoffement vers 500 mots puis de rejeter. Sous 100 mots de `faits`, rejet
  définitif comme avant : une brève squelettique n'est pas publiée.
- **Économie** : injection réduite (6-8 sources × 380 car. au lieu de 10 × 950),
  `content_len` 2 500 au lieu de 7 000, réservation de réponse 1 500 au lieu de
  3 500. Une brève devrait coûter ~8-10 k tokens contre ~35 k — **estimation non
  encore vérifiée sur un run réel**.
- Le fact-checker reçoit `article_type="breve"` et un préambule qui lui
  interdit de signaler l'absence de contexte/nuances comme un défaut. Sans lui
  il jugerait la brève à l'aune d'un format qu'elle n'est pas.
- Côté public : sections vides jamais rendues, badge « Brève » sur la page
  article et sur les cartes (accueil + catégories). Les entrées d'articles.json
  antérieures au 02/08 n'ont pas de champ `format` : absence = article.

### Ce qu'il faut mesurer au premier run, avant tout autre changement

`python scripts/analyser_run.py` sépare désormais **ACTU / BRÈVE / DOSSIER** et
affiche le taux de `conforme_du_premier_coup` par format. Deux questions, dans
cet ordre :

1. **Le taux de conformité des brèves dépasse-t-il celui des actus ?** C'est
   toute la thèse. Référence à battre : 0,8 % tous formats confondus.
2. **Combien de tokens coûte réellement une brève ?** Relever `[VERIF-TOKENS]`
   et le total Groq, diviser par le nombre de brèves menées au bout.

**⚠ PLAFOND DE L'EXPÉRIENCE — à lire avant d'interpréter le résultat.** Le
format brève ne peut pas corriger `angle_insuffisant`, qui juge le SUJET et non
l'écriture : un sujet creux le reste à 130 mots comme à 500. Or `angle_insuffisant`
représente **64 % des rejets qualité**. Le taux ABSOLU de publication est donc
borné par un problème de sélection que le format ne touche pas — s'il bouge peu,
ce n'est PAS un échec du format brève. La seule lecture concluante est la
comparaison **brève contre actu à l'intérieur du même run** : même quota, mêmes
détecteurs, mêmes motifs bloquants, seul le format change. C'est le seul test
contrôlé disponible.

Corollaire : ne pas comparer au taux d'un autre jour, et ne pas prendre un petit
échantillon pour une référence. Le run du matin du 02/08 a donné 1
`conforme_du_premier_coup` sur 6 — sur n=6, un seul article chanceux suffit à
produire ce chiffre. Repère historique : 0,8 % (2 sur 251).

**⚠ COUPURE DU 04/08 — ce qui est mesuré change de nature, à écrire AVANT le
run pour ne pas le découvrir en interprétant le résultat.**

Les règles 6 (attribution groupée) et 14 (chapeau ≠ attaque) n'améliorent QUE
les brèves. À partir du run du 04/08 au soir, la comparaison intra-run ne
mesure donc plus « format brève contre format actu à consigne égale », mais
**« brève + règles d'attribution et de chapeau » contre « actu inchangée »**.
Si les brèves l'emportent, une part du gain vient des règles, pas du format.

- **Thèse d'origine — « le format seul suffit » : testée les 02 et 03/08**, à
  consigne égale. Résultat de cette fenêtre, le seul propre : 0 correction sur
  16 brèves contre 2 sur 4 actus, et 7 rejets de brèves sur 7 dus à
  `angle_insuffisant` (le sujet), jamais à la rédaction.
- **À partir du 04/08 : on teste le format OUTILLÉ.** Suffisant pour la
  décision produit — ce qui compte est de savoir quel format publier, règles
  comprises — mais ne permet plus de conclure sur la thèse d'origine. Ne pas
  attribuer au format un gain qui peut venir des règles.

Ne toucher à `QUOTA_ARTICLES_LONGS` qu'après ces deux mesures. Si les brèves
échouent autant que les articles, le problème n'est pas le format et il faudra
chercher ailleurs — piste suivante identifiée : **clusteriser les items RSS par
événement au lieu de les dédupliquer**. Quand 8 flux sur 36 couvrent le même
fait, c'est le signal d'importance le plus fiable disponible (il remplace le
jugement du chef d'édition qui n'existe pas ici), et il est aujourd'hui traité
comme du bruit par le filtre anti-doublon.

`[MATIÈRE]` journalise maintenant le format retenu à côté de la mesure de
richesse documentaire : après quelques runs, ces couples permettront de savoir
si un routage par `audit_matiere` ferait mieux que le routage par budget — avec
des distributions relevées, jamais devinées.

**⚠ CORRECTIF DU 07/08 — cette comparaison n'aura probablement jamais lieu dans
les conditions prévues ci-dessus.** `QUOTA_ARTICLES_LONGS` est passé de 4 à 30
le 05/08 (décision Nahil, voir « RÉDACTION — angle, intertitres, citations
numérotées » plus haut) : la brève a cessé d'être le format par défaut avant
que la fenêtre « format OUTILLÉ » (04/08 →) ait accumulé assez d'articles pour
être lisible. Le repère resté valide est la fenêtre propre des 02-03/08 ci-dessus
(0 correction sur 16 brèves contre 2 sur 4 actus, à consigne égale) — tout ce
qui suit le 05/08 compare deux populations dont l'une (l'actu longue) a aussi
changé de forme (citations numérotées, intertitres éditoriaux, angle_reponse),
donc un écart mesuré après cette date ne peut plus être attribué au format seul
ni même au « format outillé » isolément. Ne pas aller chercher dans les logs
une comparaison brève/actu propre postérieure au 04/08 : elle n'existe pas.

## Test guerre/faits-divers/politique — CLOS le 31/07, NON CONCLUANT

**Affinement du 31/07** : le critère de `sujet_sensible` n'est PAS le thème
mais la **mise en cause de personnes** (mineur impliqué, affaire pénale en
cours, critique nominale). Bloquer « guerre » ou « parti politique » ratait
donc la cible : ça éliminait « guerre commerciale » et l'analyse
institutionnelle d'un conflit, tout en laissant passer des récits de victimes
sans ces mots. `BLACKLIST` bloque désormais le **vocabulaire de victimes et de
procédure pénale** (victimes civiles, sévices, massacre, bombardement, mis en
examen, garde à vue…), pas les thèmes. Le géopolitique et l'institutionnel
sans personnes nommées repassent.

Les mots-clés guerre/faits-divers/politique, retirés de `BLACKLIST` le 26/07
pour voir si la charte et la vérification LLM suffisaient à les traiter avec
neutralité, y ont été **réintégrés le 31/07**. Mesure sur le run du 31/07
matin : **3 sujets sur 14 tentés (21 %)** ont été générés en entier — ~17 k
tokens chacun — puis rejetés « sujet sensible » par la vérification LLM
(mineurs, migrants victimes de sévices, personnalités politiques). Le prompt
strict ne suffit pas : ces sujets passent la collecte, consomment le quota, et
meurent à la dernière étape. Les rejeter à la collecte rend ce budget aux
sujets publiables. Ne pas les retirer à nouveau sans mesurer le taux de rejet
« sujet sensible » en aval.

## ÉTAT AU 01/08 — à lire en premier

**Les deux runs du 01/08 ont produit ZÉRO article.** Le dernier article publié
date du 31/07 (« L'île d'Oléron remporte son bras de fer avec Airbnb » — titre
non neutre, à l'origine du garde-fou `_TITRE_NARRATIF_RE`).

**HYPOTHÈSE RÉFUTÉE LE 02/08 — ne pas la reprendre.** Cette section attribuait
le zéro du 01/08 aux deux motifs bloquants ajoutés au fact-check le 31/07
(`niveau_preuve_insuffisant`, `accusation_presentee_comme_fait`), avec la
mention « très probablement de mon fait ». **Les données la contredisent.**
Lecture des 9 `rejete_qualite` du 01-02/08 :

```
6  angle_insuffisant           ← sujet jugé creux, rejet définitif immédiat
1  motifs bloquants (3 passes) ← le seul candidat pour les deux motifs du 31/07
1  TECHNIQUE : quota Groq épuisé pendant la vérification
1  TECHNIQUE : JSON tronqué pendant la correction
```

Les deux motifs du 31/07 ne peuvent donc expliquer **au mieux qu'un rejet sur
neuf**. Sur l'ensemble du log, même profil : **67 des 105 `rejete_qualite` sont
des `angle_insuffisant` (64 %)**. Le zéro du 01/08 s'explique par six sujets
creux et deux pannes techniques — pas par un durcissement du fact-check.

Deux leçons de méthode, au-delà du chiffre :

- Une hypothèse écrite « très probablement de mon fait » en tête du fichier de
  reprise est lue comme un fait par la session suivante. Marquer explicitement
  ce qui est mesuré et ce qui est supposé.
- **Les pannes techniques sont loguées sous le même statut que les décisions
  éditoriales** (`rejete_qualite`). Deux des neuf entrées sont un quota épuisé
  et un JSON tronqué. Tant que c'est le cas, tout comptage de « rejets qualité »
  surestime la sévérité éditoriale du pipeline.

### Les 11 vérifications du 01/08

```
6  rejete_qualite            ← investigué le 02/08, voir ci-dessus
3  corrige_automatiquement   ← ont passé le fact-check, et pourtant NON PUBLIÉS
1  erreur_verification
1  rejete_sensible
```

**PIÈGE MAJEUR : `corrige_automatiquement` dans `verification_log.json` ne veut
PAS dire « publié ».** Trois articles (`pollution-fioul-saint-maur-des-fosses`,
`senat-bloque-rapport-souffrance-psychique`, …) ont ce statut et n'existent
dans `articles/`. Ils ont survécu à tout le protocole éditorial puis sont morts
sur les contrôles rejoués APRÈS correction (≥3 sources, ≥1 primaire OU
≥2 secondaires, ≥350 mots — voir « Sourcing non revérifié après correction »).
Ne jamais compter les articles publiés depuis ce journal : compter les fichiers
réellement créés dans `articles/`.

### Les deux premiers travaux à faire, dans cet ordre

1. ~~Lire les 6 `rejete_qualite` du 01/08~~ — **FAIT le 02/08**, voir la
   réfutation ci-dessus. Les deux motifs du 31/07 ne dominent pas ; ne pas les
   repasser en non bloquants sur la foi de l'ancienne hypothèse. Ils visent de
   vrais défauts (revue éditoriale externe du 31/07, articles NP137 et Perenco)
   et rien ne démontre aujourd'hui que leur seuil est trop large.
   ⚠ Le commentaire du code affirmait que « la description du fact-checker est
   journalisée depuis le 31/07 » : **c'était faux**, elle n'était que `print`ée
   et `_log` ne recevait que des comptes. Corrigé le 02/08 — `bloquants_types`,
   `bloquants_detail` et `types_restants` sont désormais réellement écrits dans
   `verification_log.json`. Un commentaire décrivait une intention, pas le code.
2. **Comprendre pourquoi 3 articles validés meurent au contrôle final.** C'est
   le goulot le plus coûteux du pipeline : ~35 k tokens dépensés par article,
   jusqu'au bout, pour zéro publication.
3. **Le vrai goulot est la SÉLECTION, pas la rédaction.** Les deux extrémités
   du tunnel disent la même chose : 423 des 507 sujets écartés au filtre
   éditorial le sont sur un score sous le seuil (83 %), et 67 des 105 rejets
   qualité sont des `angle_insuffisant` (64 %). Le barème note la FORME (source,
   fraîcheur, longueur, densité de chiffres) plus un bonus d'enjeu public jamais
   calibré ; le fact-checker, lui, juge le SUJET — et le recale deux fois sur
   trois, après ~35 k tokens dépensés. Piste principale : **clusteriser les
   items RSS par événement au lieu de les dédupliquer.** Quand 8 flux sur 36
   couvrent le même fait, la taille du cluster est le seul signal d'importance
   disponible (il remplace le chef d'édition qui n'existe pas ici), et le filtre
   anti-doublon le traite aujourd'hui comme du bruit.
4. **Mémoriser les rejets `angle_insuffisant`** — un sujet définitivement jugé
   creux est retenté indéfiniment, aucune trace n'est gardée. Mesure du 02/08 :
   67 rejets pour 48 sujets distincts, soit **19 générations complètes payées
   pour re-condamner un sujet déjà rejeté** (~400-500 k tokens, un créneau
   entier). Le record : l'INSERM magazine n°69 / nouvelles addictions, généré et
   rejeté **16 fois sur 12 jours** (16/07 → 02/08), sous deux slugs différents.
   ⚠ **Ne pas indexer sur `item["id"]`** : c'est un md5 de l'URL, donc une même
   dépêche republiée avec une URL de tracking ou reprise par un autre flux donne
   un id différent — bug déjà rencontré le 30/07 (« En Gironde, 80 hectares »
   généré deux fois). Clé recommandée : `_titre_norme(title)`, ou le couple
   id + titre normalisé. Les 3 « pommes de terre cultivées grâce à la mer » sur
   trois jours ressemblent à de la reprise multi-flux, pas au même lien.

### Ce qui a marché, mesuré

- **`MAX_TENTATIVES` 3 (piste E)** : deux articles sont allés jusqu'à la 3e
  tentative le 01/08, dont un a fini `corrige_automatiquement`. Le mécanisme
  fonctionne — c'est le contrôle final qui l'a ensuite recalé.
- Collecte et sélection sont saines : ~650 collectés, ~125 candidats,
  36 sélectionnés. Le haut du tunnel n'est plus le problème.

### Les deux plafonds, à ne pas confondre

- **10-14 tentatives par run** : plafond de QUOTA (~35 k tokens par sujet mené
  au bout, 1,1 M sur 24 h glissantes partagés entre deux runs). C'est une
  division, pas un bug.
- **0 à 1 publié sur 10-14** : plafond de CONVERSION. C'est là qu'est le vrai
  problème, et c'est là qu'il faut chercher.

### Correctifs du 30-31/07 ayant tourné le 01/08, non encore isolés

`_reponse_degeneree` (détection sur la PAUVRETÉ DE L'ALPHABET, pas la classe
des caractères — la 1re version testait les caractères de contrôle et n'a rien
attrapé), BLACKLIST affinée (vocabulaire de victimes, pas les thèmes), fusion
de l'étoffement dans la relance corrective (piste C), `_TITRE_NARRATIF_RE`,
instrumentation `[VERIF-TOKENS]` (jusqu'au 31/07 `verification.py` ne
journalisait AUCUN token : tous les totaux « par run » ne couvraient que la
génération, la moitié du budget était invisible).

`audit_matiere()` mesure la RICHESSE documentaire (5-grammes distincts,
redondance, données chiffrées) plutôt que le volume de caractères. **Diagnostic
seul, n'influence aucune décision** — relever les distributions réelles avant
de fixer un seuil. C'est probablement le plus gros levier restant : écarter un
sujet documentairement pauvre AVANT génération économise ~35 k tokens ET
améliore la qualité.

### Méthode et erreurs à ne pas refaire

Mesurer le taux de déclenchement d'un motif sur les articles publiés AVANT de
l'ajouter ; au-delà de ~10 % du corpus il est trop large. Quand la mesure
préalable est impossible (motif inédit), l'ajouter en NON bloquant d'abord.

Erreurs commises : se fier à l'affichage des logs GitHub plutôt qu'à ce que
Python reçoit ; ajouter un détecteur sans vérifier qu'il n'existe pas déjà ;
compter les articles publiés depuis `verification_log.json` au lieu de
`articles/` ; annoncer un gain avant de l'avoir mesuré.

## ESPACE LECTEURS SOUS CHAQUE ARTICLE — décidé le 02/08 (Nahil), à construire

Décision de Nahil, à ne pas re-discuter : un espace d'expression **sous chaque
article**, pas par rubrique. Les lecteurs réagissent aux faits bruts qu'on leur
présente. **Toute contribution est relue AVANT publication** — rien n'apparaît
en ligne sans validation.

### Architecture — aucun service tiers, aucun serveur

Le site est statique (GitHub Pages) et doit le rester. La plomberie existe déjà
en grande partie :

```
lecteur écrit  →  formulaire Web3Forms (déjà en place sur contact.html)
               →  data/moderation_queue.json  (le fichier existe déjà)
               →  relecture (voir ci-dessous)
               →  commit dans le dépôt
               →  rendu HTML au déploiement suivant
```

Contraintes à respecter :
- **pas de service de commentaires tiers** (Disqus & co) : la CSP l'interdit,
  et ça introduirait du pistage ;
- les contributions vivent dans git, donc tout est traçable — cohérent avec la
  transparence revendiquée par le site ;
- le rendu passe par `build_article_html`, donc **le HTML des articles déjà
  publiés ne sera PAS régénéré** (voir « Pièges connus ») : prévoir un patch
  rétroactif dédié pour poser le bloc sur les articles existants.

### Relecture : approche recommandée en deux étages

1. **Filtre IA** avec une charte de modération (insultes, hors-sujet, propos
   haineux, attaques nommées) — cohérent avec un journal 100 % IA, et ça passe
   à l'échelle. ⚠ Consomme du quota Groq, la ressource déjà limitante : à
   n'activer qu'en dehors des créneaux de génération, ou sur un modèle plus
   petit.
2. **Validation humaine** du reste, par lot, en quelques secondes.

### Limite à assumer et à AFFICHER

Le déploiement tourne 2×/jour : une contribution écrite à 10h paraît à 18h.
Ce n'est pas un forum temps réel, c'est un courrier des lecteurs. L'écrire
explicitement sous le formulaire (« les contributions sont relues avant
publication ») — c'est cohérent avec un journal qui documente tous ses
contrôles, et ça évite que le lecteur croie à un bug.

Option si le volume le justifie : déclencher un déploiement à chaque lot validé.

## Philosophie éditoriale — priorité absolue

Le pipeline n'existe pas pour maximiser le nombre d'articles publiés. Il
existe pour **empêcher qu'un mauvais article soit publié**. Un run qui ne
publie rien parce que rien n'a passé les contrôles est un run réussi, pas un
échec. Ne jamais assouplir un garde-fou pour publier plus — le différenciateur
éditorial de Les Faits est un protocole de vérification transparent, pas le
volume de contenu.

Journal 100 % IA : génération d'articles ET vérification éditoriale 3 passes
sur Groq Llama 3.3 (3 clés en rotation — le compte Anthropic n'a plus de
crédits et ne sera pas réapprovisionné, décision de Nahil en juillet 2026 ;
quand Groq est en rate limit, on attend jusqu'à 8 cycles de 62 s plutôt que
de perdre le sujet). Site statique déployé sur GitHub Pages via le repo
`lesfaits-site`.

## Architecture

- `scripts/pipeline.py` — tout le pipeline : collecte RSS, scoring, génération,
  garde-fous déterministes, rendu HTML, index/feed/sitemap.
- `scripts/verification.py` — fact-check + correction (Groq Llama 3.3).
- Workflows : `pipeline.yml` (génération ~01h05/13h05 Paris, très en avance car
  les crons GitHub ont 1-4 h de retard), `deploy.yml` (mise en ligne ~07h/18h),
  `post_x.yml`, `newsletter.yml` (Brevo), `check_feeds.yml` (diagnostic RSS).
- **L'« automate externe » est IDENTIFIÉ depuis le 12/08 : c'est cron-job.org**,
  sur le compte de Nahil, quatre tâches nommées « Lesfaits ». Elles appellent
  l'API GitHub en `workflow_dispatch` avec un jeton personnel, pour contourner
  le retard de 1 à 4 h des crons GitHub. Horaires affichés en heure de Paris,
  d'où la conversion qui avait brouillé la piste :

  | tâche | Paris | UTC | cible |
  |---|---|---|---|
  | Génération matin | 17h00 | 15h00 | `pipeline.yml` |
  | Génération soir | 17h50 | 15h50 | `pipeline.yml` |
  | Déploiement matin | 06h00 | 04h00 | `deploy.yml` |
  | Déploiement soir | 06h50 | 04h50 | `deploy.yml` |

  **Ne PAS les supprimer.** Avec la fenêtre de garde portée à 360 min, elles se
  comportent comme un filet de sécurité qui ne se déclenche que quand il sert :
  un jour normal, le cron GitHub a déjà tourné, la tâche est ignorée en 8 s
  (vérifié sur le run du 11/08 15h00 — toutes les étapes réelles « skipped »,
  zéro token consommé) ; un jour où GitHub ne déclenche rien, le dernier run
  date de plus de 6 h et la tâche sauve le run. Piste « Routines Claude »
  définitivement écartée — liste vérifiée le 12/08, dix entrées, toutes des
  rappels ponctuels de juillet déjà tirés.

  Les garde-fous restent nécessaires et ne changent pas
  (`scripts/dernier_run.py`) : `pipeline.yml` ignore un `workflow_dispatch`
  démarrant moins de 360 min après le précédent — les crons du dépôt (matin +
  après-midi) ne sont JAMAIS filtrés, sinon un cron retardé par GitHub tombant
  après un déclenchement externe serait bloqué par lui et on perdrait le vrai
  run ; `deploy.yml` ignore un déploiement dont le SHA est déjà en ligne
  (critère de CONTENU, jamais de temps : ne jamais bloquer un déploiement qui a
  du neuf). Option `forcer` dans les deux cas.

  ⚠ Ces tâches utilisent un jeton d'accès personnel GitHub. Si les
  déclenchements externes cessent un jour sans explication, vérifier d'abord
  son expiration — pas le code.
- Les articles affichent l'heure RÉELLE de génération (changement du 22/07,
  Nahil — avant cette date, l'heure affichée était arrondie au créneau
  07h00/18h00, jamais la génération technique ; ce n'est plus le cas).
- Après toute modif des templates : `python scripts/pipeline.py --rebuild`
  régénère index, catégories, archive, favoris, search.json, feed, sitemap.

## Charte éditoriale — règles INTANGIBLES

Ces règles sont codées dans les prompts (règles 11-15 du SYSTEM_PROMPT) ET dans
les garde-fous déterministes. Ne jamais les affaiblir ; toute modification des
prompts ou des garde-fous doit les préserver.

1. **Une idée = une seule apparition** dans tout l'article (résumé + faits +
   contexte + nuances). Plusieurs sources qui disent la même chose = UNE phrase
   de synthèse avec attribution groupée, jamais des reformulations successives.
2. **Rôle strict des sections** :
   - résumé (chapeau) : entrée DIRECTE dans le fait principal (chiffre, acteur,
     date) — jamais de phrase générique d'introduction ;
   - « Les faits » : uniquement les faits principaux du jour ;
   - « Contexte » : uniquement historique et mise en perspective — JAMAIS les
     faits du jour ni la méthodologie de l'étude ;
   - « Débats et nuances » : répond exclusivement à la question « Qu'est-ce
     qu'un lecteur devrait savoir avant de tirer une conclusion ? » — limites,
     incertitudes, désaccords, points non établis. JAMAIS de répétition d'un
     fait déjà présenté.
3. **Tribunes / prises de position** : tout l'article doit présenter le contenu
   comme les analyses et propositions de l'auteur (« estime », « plaide pour »,
   « propose »), signalé dès le titre — jamais comme des faits établis.
4. **Attributions** : max 7 « Selon X » par article, jamais deux phrases
   consécutives qui commencent ainsi, formes variées.
5. Chaque fait attribué doit figurer littéralement dans les sources fournies ;
   aucune extrapolation, aucun cadrage éditorial emprunté sans attribution.

6. **Titre** : factuel, neutre, 6-15 mots, jamais de vocabulaire putaclic
   (bizarre, insolite, choc…) ni de tournure en question.
7. **Longueur/sourcing minimum** : 500 mots sur chapeau+faits+contexte+nuances
   (avec une tolérance de 150 mots après relance d'étoffement, soit 350 mots
   acceptés au plancher — élargi de 400 à 350 le 20/07, Nahil), 3 sources
   minimum — un article qui n'atteint pas ce
   seuil après relance est rejeté définitivement, jamais publié incomplet.
8. **Angle éditorial obligatoire** : un sujet sans actualité identifiable, avec
   des sources trop pauvres pour l'expliquer, ou dont le contexte doit être
   rempli avec un fait divers sans rapport, n'est PAS publié — même si le texte
   est par ailleurs bien écrit. Mieux vaut publier moins d'articles que publier
   un sujet creux ou un cas médical sans diagnostic/mécanisme/évolution connus.
9. **Tournures génériques de remplissage** interdites sauf si elles apportent
   une information précise : « s'inscrit dans une dynamique », « constitue un
   enjeu majeur », « illustre la diversité des situations », « permet une
   plongée dans », « intervient dans un contexte où », « pourrait
   transformer », « reflète une évolution plus large ».
10. **Fusion des sources obligatoire** : si plusieurs sources rapportent
    exactement la même information, les fusionner en UNE phrase avec attribution
    groupée (« Selon Pressesante, Doctissimo et Futura Sciences, [fait] »). Une
    source ne justifie une phrase propre que si elle apporte une information
    DIFFÉRENTE. Ne jamais empiler une phrase par source pour le même fait.
11. **Contrôle qualité avant publication** — 7 critères non négociables. Tout
    article est refusé tant que l'un d'eux échoue :
    a) Chaque section remplit-elle UNIQUEMENT son rôle ?
    b) Une même idée apparaît-elle plusieurs fois ? → supprimer toutes les
       occurrences sauf la première.
    c) Chaque paragraphe apporte-t-il au moins une information nouvelle ?
    d) Le contexte aide-t-il à comprendre sans répéter les faits ?
    e) Débats et nuances = uniquement limites/incertitudes/désaccords, jamais
       les résultats principaux.
    f) Une phrase peut-elle être supprimée sans perte d'info ? → la supprimer.
    g) Plusieurs sources disent la même chose ? → les fusionner.

Garde-fous déterministes correspondants (déclenchent UNE relance corrective
combinée, jamais des relances en cascade — le quota Groq est la ressource rare) :
`attributions_fantomes`, `resume_repete_corps` (y compris répétitions internes
au chapeau), `faits_repetitifs` (intra ET inter-sections, 5-grammes),
`attributions_trop_repetitives`, `titre_de_mauvaise_qualite`, `cliches_ia`,
`intro_generique` (intros vagues sans information — déclenche correction),
`nuances_vagues` (généralités sans exemple concret dans « Débats et
nuances » — « les défis sont nombreux » sans chiffre ni fait précis qui
suit — retour revue éditoriale externe du 22/07), `affirmation_non_demontree`
(usage/potentiel présenté comme acquis — « ouvre de nouvelles perspectives »
— alors que la source ne décrit qu'un prototype/étude préliminaire/projet ;
doit être au conditionnel, même retour du 22/07).
Garde-fou séparé (non combiné, relance d'étoffement dédiée) :
`_deficit_longueur_sources` (500 mots cible / 350 mots plancher après
tolérance, 3 sources minimum — vérifier le compte de MOTS réel, jamais une
approximation en caractères).

Contrôle LLM (passe 2 de `verification.py`, indépendant des garde-fous
déterministes) : le fact-checker évalue aussi `angle_insuffisant` (le sujet
mérite-t-il un article ?) et `nature_contenu` (tribune/chronique/interview
doivent être signalées dès l'intro) — `angle_insuffisant: true` = rejet
définitif immédiat, jamais de tentative de correction (un sujet creux ne se
répare pas en réécrivant le texte).

## Quota Groq — fenêtre glissante, PAS un reset à minuit

Constat du 29/07, à démontrer avant toute remise en cause : le TPD Groq
(100 k tokens) est une **fenêtre glissante de 24 h**. Preuve — sur le run de
03h34 UTC, les délais « try again in… » renvoyés par Groq s'étalaient de 03h46
à 05h40 ; un reset quotidien les aurait tous groupés à 00h00. Deux
conséquences directes :

- **Les runs de l'après-midi amputent le budget du lendemain matin** (12 h plus
  tard, on est toujours dans la fenêtre). C'est ce qui a limité le run du 29/07
  à 1 article : les clés étaient déjà à 97 % consommées AVANT son démarrage
  (327 k tokens consommés par le run, ~1,07 M déjà comptabilisés sur les
  11 clés). D'où l'importance du garde-fou anti-run-rapproché.
- **Ne jamais abandonner un run sur « quota épuisé » sans regarder le délai
  annoncé** : le 29/07, une clé revenait dans 6 min 32 s et le run a rendu la
  main. `_delai_liberation()` extrait ce délai ; en dessous de
  `ATTENTE_MAX_LIBERATION` (15 min) le pipeline attend au lieu de perdre les
  sujets restants.

## Tunnel de sélection — mesures du 28/07 (27 runs)

623 candidats collectés → 319 générations tentées → **33 publiés (10 %)**.
Répartition des rejets : angle insuffisant 41, **troncature Groq 34**,
qualité des sources 30, sujet sensible 40, listicle 8, post-correction 12,
protocole (quota) 6. Autrement dit **~30 % des pertes ne sont PAS des
décisions éditoriales** mais des échecs techniques. Points à surveiller :

- **Troncature à max_tokens** : distribution bimodale — complétion médiane
  1 417 tokens, ou emballement du modèle jusqu'à la coupure. Donner plus de
  place ne fait pas converger (la relance à 6 000 ne sauvait que 11 % des
  cas, 4 sur 38) ; les 34 échecs restants brûlaient ~323 k tokens, soit
  3 quotas journaliers de clé, pour zéro article. Le contenu partiel est
  désormais récupéré (`_reparer_json_tronque`) plutôt que jeté.
- **Flux RSS morts** : 13 des ~41 sources renvoient 404/403/500 depuis le
  20/07 (elles ont été ajoutées sans être testées). Un flux mort est visible
  dans les logs (`[RSS ERREUR]`), mais un flux Atom lu comme du RSS ne l'est
  PAS : il renvoie 0 article en silence. Toujours vérifier le rendement réel
  d'une source, pas seulement l'absence d'erreur.
- **Le quota par catégorie borne la sélection AVANT `nb_max`** : avec
  6 catégories, `QUOTA_CATEGORIE = 3` plafonnait à 18 sujets quel que soit
  `nb_max`. Constat 29/07 : 655 articles collectés, 71 candidats… et exactement
  18 retenus, alors que `nb_max` valait 36. Porté à 6 par catégorie. Toute
  hausse de `nb_max` doit s'accompagner d'une hausse du quota, sinon elle
  n'a **aucun** effet.
- **Plafond par flux** (`MAX_ITEMS_PAR_FLUX`) : porté de 8 à 20 le 28/07. À 8,
  la collecte était bornée à ~230 articles/run avant tout filtre. Ce plafond ne
  coûte rien en quota Groq — il n'élargit que le vivier où
  `selectionner_meilleurs` puise ses `nb_max` sujets.

## Barème de sélection — « meilleur » doit vouloir dire « le plus intéressant »

Constat 30/07 (Nahil) : « Amazon Prime Video organise Obsessed Fest pour les
fans de comédies romantiques » figurait parmi les 78 candidats d'un run. Cause
racine : **le barème ne notait que la FORME** — source connue, longueur,
fraîcheur, densité de chiffres. Aucun critère ne mesurait l'intérêt du sujet
lui-même, si bien qu'un communiqué de plateforme, long et frais, pouvait
devancer un rapport de la Cour des comptes. Trois ajouts dans
`score_editorial` :

- `_PR_MARQUE_RE` — **rejet immédiat** de la communication de marque. Exige
  DEUX éléments : une marque/plateforme ET un verbe d'événementiel. La marque
  seule ne suffit JAMAIS — « Netflix perd 2 millions d'abonnés », « Amazon
  condamné par la Commission européenne » sont de vraies actualités.
- `_ENJEU_PUBLIC_RE` — **bonus** (+30 / +15) sur la portée : décision publique,
  argent public, santé, environnement, travail. Le titre pèse double. C'est le
  seul signal POSITIF du barème qui parle du sujet et non de son emballage.
- `_DIVERTISSEMENT_RE` — **malus** (-30 titre / -15 corps), pas rejet : un
  festival peut avoir une portée réelle (financement public, polémique).

Mots écartés après mesure sur les 154 articles publiés, ne pas les
réintroduire : `annonce` et `propose` (verbes neutres de l'actualité
d'entreprise), `célèbre` (aussi un adjectif : « un célèbre mathématicien »),
et la marque `meta` (matche la balise `<meta>` et s'emploie hors marque).

**Le filtre commercial doit accepter les DEUX écritures de la devise**, « € »
et le mot « euros ». N'écrire que « € » a laissé passer pendant quatre jours
l'article même qui avait motivé la règle — « Lidl : 5 appareils de cuisine à
moins de 10 euros » — alors que la variante « à moins de 10 € » était bien
rejetée.

`_STATS_REJETS` / `_STATS_REJETS_SOURCE` affichent à chaque run le décompte des
rejets **par motif et par source** (`[REJETS]`). Sans ça, la perte entre la
collecte et le scoring (~88 % : 655 → 78) est un trou noir et toute analyse du
barème est une hypothèse. Diagnostic seul, n'influence aucune décision.

## Sources RSS — ne jamais en ajouter sans mesurer

`scripts/check_feeds.py` + le workflow `check_feeds.yml` (déclenchement manuel)
mesurent le rendement RÉEL de chaque flux depuis le runner GitHub — le sandbox
de développement n'a pas d'accès réseau vers ces domaines, une URL ne peut donc
PAS y être validée. Le script teste aussi des URLs candidates avant tout
rebranchement, et inspecte les flux qui répondent 200 avec 0 article.

État mesuré le 28/07 : **24 sources sur 40** produisaient des articles
(192 collectés) — la vague d'ajouts du 19/07 avait 13 flux morts sur 14,
ajoutés sans test. Après réparation : **36 sources sur 36, 635 articles
collectés**. Leçons :

- Un **403** sur `.gouv.fr`, Les Échos, 20 Minutes ou Banque de France est un
  blocage WAF sur l'IP du runner GitHub, pas une mauvaise URL : changer
  d'adresse n'y change rien, il faut remplacer la source.
- Une source morte coûte jusqu'à **12 s de timeout par run** (3 tentatives
  d'en-têtes), pour zéro article — les supprimer accélère la collecte.
- Un flux qui répond **200 avec 0 article** est le pire cas : invisible dans
  les logs. D'où le rapport `[RENDEMENT]` affiché à chaque run.
- Tout nouveau domaine doit être ajouté à `_DOMAINES_PRIMAIRES` ou
  `_DOMAINES_SECONDAIRES` — sinon il compte « tertiaire » et ne vaut rien pour
  la règle ≥1 primaire OU ≥2 secondaires, quel que soit son sérieux. Attention,
  ces listes sont distinctes de `_SOURCE_DOMAINS` (qui sert au choix d'image et
  aux droits voisins) : modifier l'une ne modifie pas l'autre.
- Trois causes distinctes derrière un « 200 avec 0 article », que l'inspection
  du contenu brut permet seule de départager : page HTML servie à la place du
  flux (Vie Publique, ANSES — supprimées), flux RSS valide mais réellement vide
  (ADEME — supprimée), ou format non reconnu par le parseur (The Conversation,
  Atom — réparée côté code).

## Prompt de génération — cohérence

Audit du 29/07. Trois défauts corrigés, à ne pas réintroduire :

- **Le prompt se contredisait sur le chapeau** : la règle 4 exige d'« entrer
  DIRECTEMENT dans le fait principal » et interdit les phrases génériques,
  mais la règle sur le rôle des sections définissait le résumé comme une
  « présentation rapide du sujet ». C'est précisément la formulation qui
  produisait les chapeaux d'ambiance (« La situation dans la province du Kongo
  Central soulève des inquiétudes… »). Les deux règles disent désormais la
  même chose.
- **Numérotation dupliquée** : 26 règles pour 23 numéros, les 13/14/15
  apparaissant deux fois avec des contenus différents — ce qui rendait la
  référence « règles 11-15 » de ce fichier ambiguë. Renumérotées 1-25, sans
  perte d'instruction (vérifié par comparaison des sujets avant/après).
- **Titre** : le prompt exigeait 10-15 mots là où la charte et le garde-fou
  disent 6-15. Le prompt refusait donc des titres courts que le pipeline
  accepte. Aligné sur 6-15.

Trois seuils de sourcing coexistent, et c'est VOULU — ne pas les « harmoniser »
sans comprendre : 5 sources doivent être TROUVÉES avant génération (garde-fou
DuckDuckGo/PubMed), le prompt demande d'en CITER au moins 4, et le contrôle
après correction en exige au moins 3 (charte règle 7). Ce sont trois étapes
différentes du tunnel, pas une contradiction.

## Rendu HTML — audit du 29/07 (174 pages)

`scripts/check_seo.py` ne couvre que 5 pages statiques et 6 balises. Un audit
complet a relevé quatre défauts, tous corrigés :

- **7 articles du 26-27/06 avaient 2 `</div>` orphelins chacun** (HTML
  malformé). Le template actuel est correct — les 147 autres articles sont
  équilibrés : c'était du dégât hérité d'une ancienne version, réparé par un
  patch ponctuel.
- **Le champ de recherche principal ne servait à rien** : il partageait son
  `id` avec celui du header, si bien que `getElementById` renvoyait celui du
  header. Le JS attachait donc ses écouteurs au mauvais champ et `hInput`
  valait toujours `null`. Identifiants séparés.
- **Les 6 pages catégories n'avaient ni canonical ni Open Graph** — partagées
  sur un réseau social, elles n'affichaient aucun aperçu.
- **3 pages en `noindex` étaient déclarées dans le sitemap** (mentions
  légales, CGU, confidentialité) : signal contradictoire envoyé aux moteurs.

Attention aux faux positifs quand on réaudite : toutes les pages portent
`<base href="/">`, donc un chemin relatif se résout depuis la RACINE et non
depuis le dossier de la page. Sans en tenir compte, un audit signale des
milliers de « liens cassés » qui fonctionnent parfaitement.

## Pièges connus

- **Catégorie calculée sur l'extrait RSS et non sur l'article** (constat
  28/07 — Huawei/réseaux télécoms classé « science », CAN féminine classée
  « science ») : `detect_category` tournait sur le teaser RSS tronqué, qui
  ne contient presque aucun mot-clé propre au sujet ; le lexique « science »
  (plein de mots courants — « étude », « chercheurs », « scientifique »)
  raflait alors la mise, d'autant qu'il est 2e dans `_CAT_PRIORITE` et gagne
  les égalités. Trois correctifs : catégorie recalculée sur le TEXTE GÉNÉRÉ
  (titre + chapeau + faits + contexte), `_MOTS_FAIBLES` (mots peu
  discriminants comptés seulement dans le titre), et `SCORE_CATEGORIE_MIN`
  (en dessous de 2, on assume « societe » plutôt qu'un faux classement
  spécifique). Ne jamais reclasser depuis le seul extrait RSS.
- **Empilement « une phrase = une source »** (constat 28/07 sur l'article
  Huawei — 7 sources en 7 phrases quasi interchangeables dans « Les faits »,
  vu par le contrôle LLM mais classé « défaut de style non bloquant ») :
  `attributions_trop_repetitives` ne compte QUE les formes « Selon /
  D'après » — or la règle 4 encourage justement à varier les formes, donc un
  empilement en « indique X », « X rapporte », « X note » passait entre les
  mailles des deux garde-fous. Garde-fou dédié `sources_non_fusionnees`
  (règle 10) : ≥4 phrases consécutives attribuées chacune à une source
  DIFFÉRENTE → relance corrective combinée. Ne pas fusionner ce garde-fou
  avec celui de la règle 4, ils sanctionnent deux défauts opposés (répéter
  une forme / empiler des sources).
- **Flux Atom lus comme du RSS** (constat 28/07) : `fetch_rss` ne parcourait
  que les balises `<item>` (RSS). Atom utilise `<entry>`, dans un namespace —
  `root.iter("item")` n'y trouvait rien et la source renvoyait 0 article
  SANS erreur, en paraissant fonctionner dans les logs. The Conversation
  France (`articles.atom`) était muette depuis son ajout. Les entrées sont
  désormais repérées par leur nom de balise local, namespace ignoré.
- **Filtre anti-doublon trop agressif** (constat 28/07) : rejeter sur UN seul
  mot commun de 8 caractères n'a plus de sens une fois les mots tronqués à 8
  caractères pour absorber les variantes singulier/pluriel — « faire 8
  caractères » ne désigne plus un mot rare mais n'importe quel mot d'au moins
  8 lettres. Mesure sur les 129 titres publiés : 49 % se rejetaient
  mutuellement (« Huawei… » vs « Apple… **sécurité** », « médinas
  **historiques** » vs « chaleur **historique** », « CAN **féminine** » vs
  « douleurs **féminines** »). Il faut DEUX mots communs pour un rejet
  (15 %) ; un seul mot ne vaut qu'une rétrogradation (-25, pas -60 : à -60
  tout candidat sous 80 points passait sous le seuil de sélection, c'était un
  rejet déguisé). Ne jamais rejeter sur un seul mot commun.
- **Filtre anti-doublon — RÉSULTAT NÉGATIF du 02/08, ne pas retenter.**
  Doublon publié : « Éclipse solaire du 12 août 2026 » (01/08) et « Éclipse
  solaire du 12 août visible en France » (02/08). Deux défauts distincts, à ne
  pas confondre :

  - **A — on compare deux vocabulaires que le prompt fabrique différents.**
    `published_topics` contient les titres GÉNÉRÉS, le filtre les compare aux
    titres RSS. Le candidat était « Le Soleil s'éclipse au cœur de l'été » :
    overlap 0, aucune pénalité. Sur les titres générés, l'overlap valait 2 →
    rejet. Même famille que « catégorie calculée sur l'extrait RSS » et
    « `_PR_MARQUE_RE` appliqué à l'extrait RSS ». Il n'existe AUCUN recontrôle
    de doublon en aval : le titre généré n'est jamais comparé avant écriture.
  - **B — `_norm_words` découpe sur les espaces, sans retirer la ponctuation**,
    alors que `_titre_norme` (dix lignes plus bas) la retire via `\w+`. Deux
    normaliseurs, deux règles, même fichier. `s'éclipse` → `s'eclips`, qui ne
    matchera jamais `eclipse` : 61 formes corrompues sur 138 titres.

  **Le correctif B n'est PAS gratuit** — mesuré sur les 161 titres publiés,
  pas supposé : 25 → 32 paires en rejet (+28 %), 348 → 379 en rétrogradation.
  Retirer la ponctuation recompose aussi les clés tronquées à 8 caractères
  (`d'urgenc` → `urgence`), donc le voisinage se redessine au-delà des cas
  visés. Les 7 paires nouvelles = 2 articles seulement : « Frugalia / IA »
  (faux positif franc) et l'explicatif canicule. Acceptable, et le correctif
  supprime surtout une incohérence interne.

  **Ce qui NE sépare PAS un vrai doublon d'un faux positif — les trois ont été
  testés le 02/08 et ont échoué :**

  | piste | vrai doublon (éclipse) | faux positif (Canadair/Palantir) |
  |---|---|---|
  | seuil de mots communs | 2 | 2 |
  | rareté (DF min du corpus) | 2 | 2 |
  | adjacence des mots partagés | oui | oui (« intelligence artificielle ») |

  La rareté échoue parce que sur 161 titres elle mesure la taille du corpus,
  pas la spécificité : le mot rare de la paire Canadair est le VERBE
  `remplace` (DF=2). **Le discriminant n'existe pas dans les titres.** C'est
  le troisième rustinage de cette heuristique (26/07, 28/07, 02/08) ; ne pas
  en tenter un quatrième. « Deux items parlent du même événement » se lit dans
  les sources partagées et les entités nommées — c'est le clustering.

  **Ce que corrige quoi, à ne pas confondre :** stocker le titre RSS source
  dans `articles.json` règle le défaut A, donc les doublons MANQUÉS. Ça ne
  touche PAS les faux positifs, dont la cause est qu'une expression figée de
  deux mots (`intelligence artificielle`, `loi d'urgence`) compte comme deux
  signaux indépendants — orthogonal au décalage de vocabulaire. Seul le
  clustering règle les deux. Ne pas attendre du stockage du titre RSS un
  bénéfice qu'il ne peut pas rendre.

  ⚠ **Piège d'interprétation** : l'explicatif canicule serait bloqué comme
  doublon alors que son vrai défaut est l'absence d'événement daté (règle 8 /
  `angle_insuffisant`). Le résultat est souhaitable aujourd'hui, mais ce n'est
  PAS une preuve que le filtre vise juste — et si ce sujet revient avec un
  angle daté (canicule réelle, rapport Météo-France), le filtre le bloquera
  cette fois à tort. Un blocage de doublon est permanent, le sujet ne l'est pas.
- **Sourcing non revérifié après correction** (constat 28/07 — article Lidl
  publié avec 2 sources) : les deux contrôles de sourcing (règle 7, 3 sources
  minimum ; règle ≥1 primaire OU ≥2 secondaires) tournaient AVANT la passe de
  correction, qui réécrit aussi la liste des sources et peut en supprimer.
  Ils sont rejoués après correction. Tout contrôle placé avant
  `verifier_article` doit être considéré comme potentiellement invalidé par
  la passe 3.
- **Titre au futur pour un événement déjà survenu** (constat 28/07 sur
  l'article CXMT — titré « s'apprête à réaliser la plus grosse levée de
  fonds » alors que « Les faits » décrivent l'action déjà cotée, « a flambé
  de plus de 500 % lors de sa première journée ») : le pipeline agrège des
  sources publiées à des dates différentes ; quand le titre vient d'une
  dépêche pré-événement et le corps de dépêches post-événement, l'article
  annonce au futur ce qu'il raconte au passé. Garde-fou déterministe
  `incoherence_temporelle` + critère LLM `annonce_perimee` (bloquant après
  correction). Le même article cumulait une contradiction chiffrée non
  détectée (chapeau « 1 000 milliards de yuans » ≈ 120 Md€ vs faits
  « 450 milliards d'euros ») → `incoherence_inter_sections` renforcé sur la
  conversion d'unités/devises et sur deux valeurs divergentes du même chiffre.
- **Prise de position éditoriale** (constat 28/07 sur l'article Perenco/RDC —
  « Les autorités congolaises doivent prendre des mesures pour réguler les
  activités des entreprises pétrolières, comme le souligne Viralmag ») : le
  journal ne dit JAMAIS ce qu'un acteur devrait faire. Attribuer une injonction
  à une source ne la rend pas neutre — si une ONG réclame une mesure, l'écrire
  comme SA demande. Garde-fou `prise_de_position` sur le chapeau et « Débats et
  nuances » (5 % de déclenchement mesuré).
- **Chapeau répété dans « Débats et nuances »** : `resume_repete_corps` ne
  compare le chapeau qu'à « Les faits ». L'étendre à toutes les sections a été
  TESTÉ puis écarté (28/07) — le taux passait de 7 % à 41-95 % selon la
  métrique, car un chapeau partage forcément des groupes de mots avec le corps
  qu'il résume (noms propres, termes techniques). Aucun seuil ne sépare le
  résumé légitime du recopiage ; ce défaut relève du contrôle LLM
  (`redondance`), pas d'un garde-fou déterministe.
- **Précision > rappel sur les garde-fous à relance** : le quota Groq est la
  ressource rare et chaque garde-fou déclenche une relance corrective. Motif
  « il est important de noter/souligner que… » testé puis ÉCARTÉ de
  `cliches_ia` (28/07) : même restreint aux phrases sans chiffre, il faisait
  passer le déclenchement de 4 % à 42 % du corpus — c'est un connecteur
  français courant, pas un défaut. Toujours mesurer le taux de déclenchement
  sur les articles publiés avant d'ajouter un motif.
- **Listicles commerciaux déguisés** (constat 26/07 — « Lidl : 5 appareils de
  cuisine à moins de 10 euros » publié, lu comme une pub) : `_COMMERCE_RE`
  élargi à « (à) moins de X€ » et aux enseignes discount (Lidl, Aldi, Action)
  en plus de la liste existante — un article n'est pas éditorial simplement
  parce qu'il cite un prix bas, il l'est encore moins avec une enseigne.
- **Doublon de sujet malgré la fenêtre anti-doublon** (constat 26/07 — deux
  articles publiés à 5 h d'intervalle sur la même découverte de carie
  néandertalienne) : le filtre de récurrence dans `score_editorial` comparait
  des mots exacts (« néandertaliens » ≠ « néandertalien », singulier/pluriel
  selon la source RSS) et ne détectait aucun chevauchement. Comparaison
  passée à un préfixe de 8 caractères (accents retirés) plutôt qu'au mot
  exact — ne jamais revenir à une correspondance de mot strict.
- **Image hero hors-sujet sur un article genré** (constat 26/07 — photo de
  joueurs de football HOMMES sur un article « CAN féminine 2026 ») :
  `extract_visual_keywords` ne précisait pas le genre à Pexels, qui renvoie du
  stock majoritairement masculin par défaut sur les requêtes sport neutres.
  Prompt LLM + garde-fou déterministe (regex « féminin(e)/femmes/dames » dans
  le titre → force « women » dans les mots-clés si absent) ajoutés dans
  `extract_visual_keywords`.
- **Sources marchandes interdites** : Amazon, Fnac, Payot, Cultura, réseaux
  sociaux, plateformes d'avis ne sont JAMAIS des sources citables (« Selon
  Amazon » a été publié le 15/07 — trois fiches produit du même livre
  comptées comme trois sources). Blocklist `_DOMAINES_NON_CITABLES_RE` +
  filtre `_est_source_citables()` appliqués dans `duckduckgo_search` ET à la
  vérification des sources ; dédup par titre normalisé (même œuvre/dépêche
  sur plusieurs sites = UNE source). Ne jamais retirer ces filtres.
- **Hiérarchie de sources en liste BLANCHE** (`qualite_source`,
  `bilan_qualite_sources`) : primaire (institutions/gouvernements/revues à
  comité de lecture) / secondaire (agences de presse, médias de référence) /
  tertiaire (vulgarisation, Wikipédia — jamais une preuve) / interdite
  (marchands, réseaux sociaux). Règle de publication : **≥1 source primaire
  OU ≥2 sources secondaires indépendantes**, sinon rejet — un empilement de
  tertiaires ne suffit jamais. Une blocklist seule ne suffit pas (elle
  grandit indéfiniment) ; c'est la liste blanche qui doit primer.
- **Protocole de vérification jamais optionnel** : si le fact-check LLM
  échoue (rate limit, erreur API — statut `erreur_verification` ou
  `non_verifie`), l'article n'est PAS publié, même s'il est par ailleurs bon.
  Le sujet est retenté au run suivant. Ne jamais publier « par défaut » faute
  de vérification complète.
- Le différenciateur éditorial n'est PAS un compteur de sources qualifiées
  dans les méta (badges PRIMAIRE/MÉDIA/CONTEXTE testés puis retirés le
  15/07 sur retour utilisateur) mais la section **« Pourquoi cet article a
  été publié »** en bas de chaque article (`art__pourquoi` dans
  `build_article_html`) : explique en langage clair — pas en indicateurs
  techniques — la répartition des sources par fiabilité, la règle de
  publication appliquée, le résultat du fact-check, et le rappel qu'il n'y a
  jamais de relecture humaine. C'est l'argument de marque du site ("on ne
  vous demande pas de nous croire, on vous montre pourquoi cet article a
  été publié") — à préserver dans tout futur design, ne jamais le réduire à
  un badge ou un score.
- Le HTML des articles déjà publiés N'EST PAS régénéré par
  `pipeline.py --rebuild` (qui ne touche qu'index/catégories/archive/
  sitemap) : toute évolution du template `build_article_html` nécessite un
  patch rétroactif dédié (script ponctuel, non versionné) pour s'appliquer
  aux articles existants.

- Les objets `sources` renvoyés par le correcteur LLM peuvent être incomplets :
  tout accès direct `s["titre"]` / `s["institution"]` au rendu est interdit —
  utiliser `.get()` avec repli (un KeyError ici coûte un article entier).
- `positions` (spectre) : le LLM renvoie parfois `null` — `.get(clé, défaut)`
  ne remplace PAS un null existant, utiliser `or`.
- Images : chaque JPEG doit avoir ses variantes `.webp` et `-480.webp`
  (générées par `_ensure_webp_variants` à chaque rebuild) — les templates
  servent du WebP ; JPEG réservé à og:image, RSS, newsletter.
- Contraste : petits textes bleus en `--blue-ink` (AA), jamais `--blue`.
- Flux RSS capricieux (415 INSERM, 406 The Conversation, XML cassé ANSES) :
  échelle de 3 tentatives + reparse lxml recover dans `fetch_rss`.
- La clé Brevo ne doit JAMAIS être injectée dans le HTML client (fuite corrigée
  en juillet 2026 — formulaire hébergé Brevo uniquement).

## Git

- Branche de travail : `claude/morning-run-verification-r7khv1`, merge dans
  `main` pour mettre en production (le pipeline et le déploiement tournent sur main).
- Les fichiers générés (articles/, index.html, feed.xml, data/*.json…) sont
  commités par le bot à chaque run : en cas de conflit sur ces fichiers, prendre
  la version de main puis relancer `--rebuild`.
