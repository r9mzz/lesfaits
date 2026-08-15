# Unification de la sélection réellement exécutée

Le workflow de production lance `run_pipeline_v3.py`. Jusqu'au 15/08/2026,
ce runner remplaçait dynamiquement `selectionner_meilleurs()` de `pipeline.py`
par une seconde implémentation fondée sur `editorial_ranking.py`.

Cela créait deux doctrines concurrentes : les corrections les plus récentes du
pipeline natif (signal exact de veille, un seul événement par grappe dans un
run) pouvaient être annulées au runtime, et le vieux clustering de titres
pouvait encore ajouter un bonus multi-médias alors que les backtests récents
avaient conclu qu'un regroupement approximatif ne devait pas gonfler le score.

Désormais V3 laisse la sélection canonique de `pipeline.py` intacte. Il ne
conserve que ses adaptations orthogonales au classement : portée du contrôle de
niveau de preuve et cooldown exact post-génération des slugs récemment rejetés.

Le test `test_v3_preserves_native_subject_selection` verrouille cette propriété :
un futur changement de V3 qui réintroduirait `selectionner_sujets` ou dupliquerait
la fonction de sélection doit faire échouer la CI.
