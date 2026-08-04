# Les Faits — lesfaits.info

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
- **Un automate EXTERNE au dépôt** déclenche `pipeline.yml` à 15h00 et 15h50
  UTC et `deploy.yml` à 04h00 et 04h50 UTC, tous les jours à la minute près
  (constat 28/07, 5-6 jours consécutifs, en `workflow_dispatch` sur le compte
  de Nahil). Il n'est ni dans ce dépôt ni dans les Routines Claude — donc
  impossible à couper depuis le code. Ses effets sont neutralisés par deux
  garde-fous (`scripts/dernier_run.py`) : `pipeline.yml` ignore un
  `workflow_dispatch` démarrant moins de 2 h après le précédent — les deux
  crons du dépôt (matin + après-midi) ne sont JAMAIS filtrés, sinon un cron
  retardé par GitHub tombant après un déclenchement externe serait bloqué par
  lui et on perdrait le vrai run ; `deploy.yml` ignore
  un déploiement dont le SHA est déjà en ligne (critère de CONTENU, jamais de
  temps : ne jamais bloquer un déploiement qui a du neuf). Option `forcer`
  dans les deux cas. **À terme, il faut retrouver et couper cet automate.**
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
