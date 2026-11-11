# Labo Tirages — relais FDJ

Application d'analyse statistique EuroMillions et Loto (`index.html`), publiée avec GitHub Pages.

Une page web n'a pas le droit de lire directement les archives du site FDJ. Ce dépôt contourne la limite sans aucun serveur :

1. La tâche planifiée `.github/workflows/relais-fdj.yml` lance `fetch_fdj.py` plusieurs fois par jour.
2. Le script télécharge les archives ZIP officielles publiées sur les pages « Historique » de FDJ, vérifie chacune (ZIP intègre, CSV FDJ lisible, dates) et les range dans `data/`.
3. `data/manifest.json` indique quand FDJ a été interrogé avec succès pour la dernière fois et liste les éventuelles erreurs.
4. L'application, servie à la même adresse, lit `data/` à chaque ouverture et quand on touche « Actualiser les tirages ».

Garanties :
- une archive valide n'est jamais remplacée par un fichier invalide (page de blocage, téléchargement tronqué) ;
- si le relais n'a pas pu interroger FDJ depuis plus de 36 heures, l'application l'affiche et n'indique jamais « Historique à jour » ;
- en cas d'échec, l'exécution apparaît en rouge dans l'onglet « Actions » et GitHub envoie un e-mail.

Lancer le relais à la main : onglet **Actions** → **Relais FDJ** → **Run workflow**.

Vos tirages, grilles et réglages restent dans votre navigateur ; rien n'est envoyé au dépôt.
