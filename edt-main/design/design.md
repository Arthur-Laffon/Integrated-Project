# Observation de EDT de l'EN
Vidéos disponibles ici : [ici](https://www.index-education.com/fr/tutoriels-video-edt.php)
## Début de la création
    - Commencent par une création de la grille des heures disponibles : début, fin, durée d'un créneau, pause méridienne (qui est donc universelle) 
    - Pour éviter de bloquer la pause méridienne, ça peut juste être une grande salle sans prof
    - Un menu spécifique aux pauses
    - On peut définir des services pour le self, qui peuvent ou non inclure les profs, et qui peuvent inclure un nombre limité de classes
    - Pour le début, les récréations sont fixées au début, et elles sont pour tout le monde en même temps (mais ça pourrait servir, par ex pour ne pas mettre plusieurs niveaux en même temps sur une récré)
Cette étape fixe les créneaux disponibles et les pauses pour tout le monde
 
## Contraintes sur les matières
- Exemples de contraintes : incompatibilités, limitation du nombre d'heures, créneaux
- Menu avec les toutes les matières existantes
### Incompatibilité
- nombre de cours d'une même matière par intervalle de temps - ex : pas plus d'un cours de maths par jour (ou par 1/2 journée) (ou pas 2 jours de suite : utile pour les TD qui nécessitent de la préparation)
- Pas de succession pour une paire de cours - ex : pas Maths après EPS
- Pour une paire de cours différents : donne la durée min entre un cours de l'un et de l'autre (du coup le premier point c'est pour une paire qui contient deux fois le même cours)



- Volontés de répartir certains cours sur des plages horaires prédéfinies, avec 3 priorités (Absolu, optionnel, voeu) : pas maths l'après midi, plutôt pas de 8 à 10 mais on peut

## Contraintes sur les enseignants
- Max horaire par jour, par demi-journée, par matin, par aprem
- Max plage horaire (temps de présence)
- Nombre de min de jours où le début est >= .. ou la fin est <= ..
- Garantir des demi journées libres
- Heures de trous max
- ET en plus, tous les choix spécifiques à des heures précises : indisponibilité, optionnel, voeu

## Contraintes sur les classes et groupes
- Nombre max d'heures, horaires indisponibles (ça ressemble beaucoup au menu prof)
- Menu groupes pas clair, faudrait voir l'outil

## Contraintes sur les salles
- Possibilité d'avoir des temps de trajet entre les sites

## Autres
- Faire des "cours complexes" : faire des cours qui regroupent plusieurs classes. Ex : créneau cours de langues : toutes les classes doivent pouvoir y aller, et ensuite les groupes sont affectés à différents cours sur cette heure




# UI design
- Pas de séquence linéaire de menus : on fait des choix rapides pour un prof ou une salle, pas une séquence de choix qui dépend des précédents (donc on fait comme EDT...)
- Faut pouvoir save l'état de la configuration (et donc autosave et pouvoir charger)
- Undo, Redo
- Des menus distincts pour gestion de classe, profs, salles, matières
- Toujours un emploi du temps au milieu pour mettre des contraintes de disponibilité spécifiques à des horaires



# GUI code
- Les interfaces graphiques sont faites en Java non ? Ou Python ?
- Pour l'interface simple basée sur les menus qu'on veut faire, on peut probablement utiliser un peu n'importe quoi
- Ce sera en Python
- Ce sera tkinter

# Rendu 0
- Il faut pouvoir:
  - Rentrer les quelques contraintes
  - Afficher l'edt
