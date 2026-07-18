# Devenir

Un miroir, pas un tableau de bord.

> # Si une fonctionnalité n'aide pas l'utilisateur à prendre conscience de sa journée en moins de 5 secondes, elle n'entre pas dans l'application.

Cette règle est le filtre de toute décision produit — l'équivalent, pour Devenir,
de ce que « la neutralité comme méthode » est pour Les Faits.

## La promesse

**Chaque heure est un vote pour la personne que tu deviens.**

Quand tu fermes l'application, tu comprends mieux ta journée qu'avant de l'ouvrir.

## Le positionnement

L'utilisateur ne vient pas pour être plus productif. Il vient pour éviter de
laisser ses journées lui échapper. On ne vend pas du temps, on vend de la
conscience.

## Les valeurs

1. **Simplicité** — le moins d'écrans, de texte et de boutons possible.
2. **Beauté** — même vide, l'application doit être agréable. Chaque écran doit
   pouvoir être imprimé comme une affiche.
3. **Rapidité** — une réponse prend moins de 5 secondes, sinon on a perdu.
4. **Aucune morale** — l'application ne juge jamais. Elle montre ; l'utilisateur
   conclut.

## Les 4 écrans (et rien d'autre)

- **Aujourd'hui** — date, phrase d'intention, timeline de la journée, bouton +,
  pause des rappels, la phrase-vote discrète en bas.
- **Check-in** — « Cette dernière heure ? » → tag optionnel → 🌱 Investie /
  ❤️ Importante / 😌 Repos choisi / 🤷 Temps subi. Tap. Fermé.
- **Parcours** — le calendrier. Chaque journée a une intensité lumineuse ;
  la grille raconte les périodes sans un seul chiffre. Un tap ouvre le détail
  du jour (entrées, journal, ce qui comptait pour le lendemain).
- **Réglages** — fréquence, heures, phrase d'intention, export, suppression.

## Ce qui n'entrera jamais

Badges, streaks, niveaux, XP, IA, chatbot, statistiques, objectifs quotidiens,
compteurs de check-in, scores, pourcentages, comparaisons avec hier.
Tout ça existe déjà partout.

## Technique

- `index.html` : application complète, autonome, zéro dépendance.
  Données 100 % locales (`localStorage`, repli mémoire si bloqué) — rien ne
  quitte le téléphone.
- Prototype déployé comme artifact Claude ; à terme, hébergement statique
  simple (le même modèle que lesfaits.info) puis « Ajouter à l'écran
  d'accueil ».
- Limite assumée du format web : pas de notification téléphone fermé. Le
  rappel fiable reste une alarme répétée dans l'app Horloge, l'application est
  l'endroit où l'on répond.
