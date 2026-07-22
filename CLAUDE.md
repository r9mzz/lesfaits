# Les Faits — lesfaits.info

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
  `post_x.yml`, `newsletter.yml` (Brevo).
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

## Pièges connus

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
