# Instance locale — installation dans un bar

Configuration de l'instance sur le poste du caissier, et ce qu'elle implique.

**Machine neuve, sans Python ni PostgreSQL ?** Commencer par
[INSTALLATION_POSTE.md](INSTALLATION_POSTE.md), qui part de zero et renvoie ici pour le detail.

## A quoi ca sert

Sans instance locale, tous les appareils du bar passent par le serveur central : **si internet
tombe, la serveuse et le caissier ne se voient plus**. Le bon envoye par la serveuse n'atteint
pas la caisse, il n'est pas valide, et le departement ne sert pas le client.

Avec une instance installee sur le poste du caissier, tout le monde continue de travailler
ensemble sur le Wi-Fi du bar. Les operations remontent vers le serveur central des que internet
revient.

## Ce que l'installation suppose

- Le poste du caissier est un **PC allume pendant tout le service**. S'il s'arrete, **tout le bar
  s'arrete** : les tablettes le visent directement et n'ont plus personne a qui parler, meme si
  internet fonctionne. C'est une aggravation reelle par rapport a aujourd'hui, ou une panne du
  poste laissait au moins la serveuse envoyer ses bons au serveur central. Le poste devient un
  point de panne unique pour l'etablissement entier. Un [repli manuel](#repli-si-le-poste-tombe)
  existe, mais il n'est pas automatique - et pour une bonne raison, expliquee plus bas.
- Le poste a une **adresse IP fixe** sur le reseau du bar : les tablettes la visent directement.
- Internet reste necessaire pour **se connecter** (les identifiants sont verifies par le serveur
  central, le bar ne detient aucun mot de passe). Une coupure a l'heure d'ouverture empeche donc
  de demarrer le service ; une equipe deja connectee, elle, travaille sans interruption.

## 1. Creer l'instance dans la console

Cote serveur central :

```bash
docker compose exec backend python manage.py creer_instance --organisation "NOM DU BAR"
```

Sans `--organisation`, elle liste les etablissements. Elle affiche une ligne `INSTANCE_TOKEN=...`
a recopier a l'etape 2 - **la noter tout de suite**, elle ne sera pas reaffichee.

Un second appel sur le meme etablissement refuse : il faut choisir explicitement
`--supplementaire` (un deuxieme poste dans le meme bar) ou `--remplacer` (poste vole ou
reinstalle, les anciens jetons cessent immediatement de marcher). Rien n'est jamais revoque sans
qu'on le demande : un jeton coupe par megarde arrete un bar en plein service.

Ce jeton vaut pour toutes les operations de cet etablissement - et d'aucun autre. Le revoquer ne
touche pas aux comptes du personnel.

## 2. Configurer le poste du caissier

Fichier `.env` de l'instance locale :

```
INSTANCE_ROLE=local
CLOUD_API_URL=https://votre-serveur-central
INSTANCE_TOKEN=<le jeton de l'etape 1>

# Base locale, propre a ce poste
DB_NAME=...
DB_USER=...
DB_PASSWORD=...
DB_HOST=localhost
DB_PORT=5432
SECRET_KEY=...
DEBUG=0

# Les tablettes joignent ce poste par son IP : elle doit etre autorisee.
EXTRA_ALLOWED_HOSTS=192.168.1.10
EXTRA_CORS_ORIGINS=http://192.168.1.10

# Adresse a laquelle l'instance se joint ELLE-MEME pour appliquer les corrections de l'admin.
# A ne changer que si le serveur local n'ecoute pas sur le port par defaut.
LOCAL_API_URL=http://127.0.0.1:8000
```

**`INSTANCE_ROLE=local` est la bascule essentielle.** Sans lui, le poste se comporte comme un
serveur central : il ne capture rien, ne remonte rien, et le caissier ne peut pas ouvrir la
journee sans l'admin.

## 3. Mettre en service

```bash
python manage.py migrate
python manage.py setup_local_instance
```

`setup_local_instance` verifie la configuration, s'assure que le serveur central reconnait
l'etablissement, puis descend le referentiel (produits, prix, personnel, licence). Chaque refus
indique quoi corriger - l'installation se faisant chez un client, souvent sans acces aux
journaux.

## 4. Lancer la synchronisation continue

```bash
python manage.py run_sync
```

A demarrer automatiquement avec la machine (service Windows ou tache planifiee au demarrage).
La boucle enchaine trois choses toutes les 30 secondes : la remontee des operations du bar, la
descente des corrections de l'admin, et - tous les 10 tours - le rafraichissement du referentiel.

**Les corrections descendent a chaque tour**, pas au rythme du referentiel : une vente annulee
par l'admin qui continue de figurer dans le resume de caisse fausse ce que le caissier remet en
fin de service. Quelques secondes de retard, pas dix minutes.

**L'ordre remontee-puis-descente n'est pas cosmetique** : le referentiel ne rapporte les
quantites de stock que lorsque plus rien n'attend d'etre remonte. Deux taches planifiees
separees pourraient se croiser indefiniment sans jamais converger.

## 5. Pointer les appareils vers le poste

- **Poste du caissier (navigateur)** : `http://localhost:8000/api`. C'est aussi ce qui permet au
  mode hors-ligne du navigateur de continuer a fonctionner, `localhost` etant considere comme
  une origine sure.
- **Tablettes des serveuses** : ecran *Profil > Serveur du bar*, saisir
  `http://192.168.1.10:8000/api`. Une seule fois par tablette, a l'installation.

## Verifier que ca marche

```bash
python manage.py diagnostic_instance
```

Ne modifie rien, relancable en plein service. Chaque ECHEC dit quoi corriger, et la fin affiche
l'adresse a saisir sur les tablettes. **Ne pas continuer tant qu'il n'est pas vert.**

La procedure complete, avec la repetition a faire chez soi d'abord, est dans
[TEST_TERRAIN.md](TEST_TERRAIN.md). En resume, le seul test qui compte :

1. Debrancher **internet** (pas le Wi-Fi).
2. La serveuse ouvre un onglet et envoie un bon.
3. **Le caissier doit le voir apparaitre** et pouvoir le valider, puis encaisser.
4. Retablir internet, attendre une minute.
5. Verifier dans le serveur central : **une seule** vente, un stock decremente **une seule
   fois**, imputee a la bonne session de caisse.

Si l'etape 3 echoue, l'instance locale n'est pas en service : verifier `INSTANCE_ROLE` et
l'adresse configuree sur les appareils.

Une fois cela acquis, verifier le sens inverse :

6. Depuis le serveur central, annuler cette vente.
7. Attendre une minute, puis regarder le resume de caisse **sur le poste du bar** : la vente doit
   en avoir disparu, et le stock etre remonte. Si elle y figure encore, la descente ne tourne pas -
   verifier `LOCAL_API_URL` et le journal du service.

## Repli si le poste tombe

Le poste du caissier est en panne, eteint, ou son disque a lache. **Tant qu'internet fonctionne,
le bar peut continuer sur le serveur central** - mais pas tout seul : chaque appareil doit y etre
repointe a la main.

### Sur chaque tablette

*Profil > Serveur du bar*, remplacer l'adresse du poste par :

```
https://cave-backend.bunker-store.store/api
```

**Si la tablette a des bons non transmis**, l'ecran ne bascule pas tout de suite : il affiche
**la liste de ce qui sera perdu** - heure, onglet, articles, montant - et demande de confirmer.

Ces bons correspondent a des consommations deja servies. Ils ne peuvent pas suivre vers le
serveur central : ils referencent des onglets que l'instance du bar etait seule a connaitre.

**Le bon reflexe reste de rallumer le poste** et d'attendre que la file se vide. N'abandonner
que si son disque est definitivement perdu. Apres l'abandon, la liste **reste affichee sur cet
ecran** : c'est a partir d'elle que la serveuse ressaisit les commandes sur le serveur central.

### Pour le caissier

Ouvrir l'interface hebergee (Vercel) sur un autre appareil, avec internet.

### Pourquoi ce n'est pas automatique

Un repli automatique serait **pire que la panne**. Une tablette qui basculerait seule vers le
serveur central y deposerait ses bons, la ou le caissier - toujours branche sur l'instance - ne
les verrait jamais. Les donnees du bar se couperaient en deux sans que personne s'en apercoive,
et la reconciliation serait a faire a la main, apres coup, sur des ventes deja servies.

Le geste doit donc rester volontaire : on bascule **tout le bar** en meme temps, ou rien.

### Ce qui reste dans le poste

Les ventes que le poste n'avait pas encore remontees sont **dans sa base, pas dans le cloud**.
Elles n'apparaitront jamais toutes seules. Si le disque est intact, rebrancher le poste et
laisser `run_sync` finir son travail avant de le retirer du service. Sinon, la sauvegarde
(voir ci-dessous) est le seul recours.

## Sauvegardes

La base du poste contient les ventes tant qu'elles ne sont pas remontees. Le script
`scripts/backup.sh` s'applique aussi a une instance locale - voir [EXPLOITATION.md](EXPLOITATION.md).

## Limites connues

- **Les corrections qui descendent se limitent aux ventes** (`/api/orders/`). Une annulation faite
  par l'admin atteint bien le bar ; d'autres actions a distance, comme la fermeture de la journee,
  ne descendent pas encore.
- **Une correction que le bar refuse n'est pas rejouee.** Typiquement une vente deja annulee sur
  place. Le refus est ecrit dans le journal du service (`Correction refusee par le bar : ...`) et
  la descente continue, mais personne n'en est averti dans l'interface.
- **Les bons abandonnes se ressaisissent a la main.** Rien ne les reinjecte automatiquement dans
  le serveur central, et le montant n'est calculable que si le catalogue etait en cache sur la
  tablette (voir [Repli si le poste tombe](#repli-si-le-poste-tombe)).
- **Rien de tout cela n'a encore tourne contre un vrai serveur.** Les tests automatises simulent
  le serveur central avec des reponses fabriquees.
