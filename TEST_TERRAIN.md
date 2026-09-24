# Tester le mode hors-ligne

Deux procedures : une **repetition** chez vous, puis le **test au bar**. Elles verifient la meme
chose, mais la repetition ne mobilise personne.

**Commencer par la repetition.** Le test au bar verifie deux choses a la fois - que le mecanisme
fonctionne, et que l'installation est correcte. S'il echoue, on ne sait pas laquelle des deux a
lache, devant un client et pendant un service. La repetition separe les deux questions.

---

## Ce qui change, et ce qui ne change pas

Le serveur heberge (`cave-backend.bunker-store.store`) **est** le serveur central du mecanisme.
Il n'est pas remplace. L'interface hebergee (Vercel) reste celle de l'admin et de
l'approvisionneur.

Ce qui s'ajoute : une instance du backend **sur le PC du caissier, dans le bar**. C'est elle qui
permet a la serveuse et au caissier de continuer a se voir quand internet tombe. Elle n'est pas
hebergeable - hebergee, elle serait injoignable pendant une coupure, ce qui est exactement le
probleme a resoudre.

```
  Wi-Fi du bar (marche sans internet)
  Tablette serveuse ──► PC caissier : backend local + navigateur
                              │
                              │ internet, quand il est la
                              ▼
                   cave-backend.bunker-store.store   ◄── Vercel (admin)
```

### Le poste du caissier devient un point de panne unique

A dire au client avant d'installer, pas apres. Aujourd'hui, si le PC du caissier tombe, la
serveuse continue d'envoyer ses bons au serveur central. **Une fois le bar equipe, elle s'arrete
aussi** : sa tablette vise le poste et n'a plus personne a qui parler, meme si internet
fonctionne.

C'est le prix du travail sans internet, et il se paie dans l'autre sens. Un repli manuel existe
(voir [Repli si le poste tombe](#repli-si-le-poste-tombe)), mais il n'est ni automatique ni
complet.

### Le caissier ne peut pas utiliser Vercel pendant le test

Deux raisons, et la seconde est definitive : une page servie en HTTPS ne peut pas appeler une
adresse en HTTP, et surtout **internet etant coupe, la page Vercel ne se chargera pas du tout.**

L'interface du caissier doit donc etre servie depuis le PC du bar. C'est le point que
`INSTANCE_LOCALE.md` ne disait pas, et il conditionne tout le reste.

---

## Prealable commun : un nouvel APK

Il en faut un, pour deux raisons cumulees.

1. **L'ecran *Profil > Serveur du bar* et la pile hors-ligne n'existent pas dans votre build
   actuel.** Sans lui, aucun moyen de pointer la tablette vers le PC du bar.
2. **Android bloque le trafic en clair depuis Android 9.** L'instance locale sert en
   `http://192.168.x.x:8000` : sans exception, la tablette refusera de la joindre, et le test
   echouera des la premiere tentative.

### Ce qui est deja en place

`expo-build-properties` est installe et `app.json` active `usesCleartextTraffic` - rien a
modifier. Il reste a construire :

```sh
cd le_parrain_mobile
eas build --platform android --profile production
```

**A savoir, parce que c'est un vrai relachement :** cette option autorise **tout** le trafic en
clair de l'application, pas seulement celui vers le reseau du bar. Le restreindre au seul reseau
local demanderait un plugin de configuration sur mesure (`networkSecurityConfig`). En pratique le
reste du trafic va en HTTPS vers `cave-backend.bunker-store.store` et continue d'y aller, mais
plus rien ne l'impose. C'est reversible : retirer l'option de `app.json` et reconstruire.

`EXPO_PUBLIC_API_URL` reste sur `https://cave-backend.bunker-store.store/api` : c'est l'adresse
par defaut, celle d'une tablette qui n'est pas dans un bar equipe. L'adresse locale se saisit sur
la tablette, dans l'application.

---

## A. Repetition chez vous

Une soiree. Il faut : votre PC de developpement, une tablette ou un telephone Android sur le
**meme Wi-Fi**, et le nouvel APK.

### A1. Creer l'instance cote serveur heberge

Sur le serveur qui heberge `cave-backend.bunker-store.store`, selon la facon dont il est deploye :

```bash
# Docker Compose (le cas de ce depot : service "backend")
docker compose exec backend python manage.py creer_instance --organisation "NOM DU BAR DE TEST"

# Environnement virtuel Python (systemd, ou lancement a la main)
cd /chemin/du/projet && source .venv/bin/activate
python manage.py creer_instance --organisation "NOM DU BAR DE TEST"

# Plateforme sans acces shell (Render, Railway, Fly...) : console web du service,
# puis la meme commande.
```

**Le nom exact n'est pas devinable.** Lancer la commande sans `--organisation` : elle liste les
etablissements au lieu d'echouer.

Elle affiche une ligne `INSTANCE_TOKEN=...` a recopier. **La noter tout de suite** : la commande
ne la reaffichera pas, et un second appel refusera de creer un doublon.

**Utiliser un etablissement de test**, pas un bar reel : la repetition va creer de vraies ventes
dans la base de production.

### A2. Une base locale separee

Le poste doit avoir **sa propre base**, distincte de celle de votre developpement courant :

```bash
createdb parrain_instance_locale
```

### A3. Configurer l'instance

Un fichier `.env` a part (ou basculer le votre, en le sauvegardant d'abord) :

```
INSTANCE_ROLE=local
CLOUD_API_URL=https://cave-backend.bunker-store.store
INSTANCE_TOKEN=<le jeton de l'etape A1>
LOCAL_API_URL=http://127.0.0.1:8000

DB_NAME=parrain_instance_locale
DB_USER=postgres
DB_PASSWORD=...
DB_HOST=localhost
DB_PORT=5432
SECRET_KEY=...
DEBUG=0

EXTRA_ALLOWED_HOSTS=192.168.1.10        # remplacer par l'IP de votre PC
EXTRA_CORS_ORIGINS=http://192.168.1.10
```

`INSTANCE_ROLE=local` est la bascule essentielle. Sans lui, le poste se comporte en serveur
central : il ne capture rien, ne remonte rien, et le caissier ne peut pas ouvrir la journee.

### A4. Mettre en service, puis verifier

```bash
python manage.py migrate
python manage.py setup_local_instance
python manage.py runserver 0.0.0.0:8000     # dans un terminal a part
python manage.py diagnostic_instance        # dans un autre
```

**Ne pas continuer tant que le diagnostic n'est pas vert.** Il affiche a la fin l'adresse a
saisir sur les tablettes. S'il signale un ECHEC, il dit quoi corriger.

`runserver` sur `0.0.0.0` et non sur l'adresse par defaut : sinon le poste n'ecoute que
lui-meme, et la tablette ne le joindra pas.

### A5. Lancer la synchronisation

```bash
python manage.py run_sync
```

A laisser tourner. Elle remonte les operations toutes les 30 secondes, fait descendre les
corrections de l'admin a chaque tour, et rafraichit le referentiel tous les 10 tours.

### A6. L'interface du caissier

```bash
cd le_parrain_front-main && yarn start
```

`environment.ts` pointe deja sur `http://localhost:8000` : rien a modifier. Ouvrir
`http://localhost:4200`.

### A7. La tablette

Installer l'APK, se connecter (**avec internet** : la connexion passe toujours par le serveur
central), puis *Profil > Serveur du bar* : saisir `http://192.168.1.10:8000/api`, avec l'adresse
donnee par le diagnostic.

### A8. Le test

1. **Se connecter des deux cotes pendant qu'internet est la** - caissier et serveuse. C'est
   obligatoire : la connexion est toujours verifiee par le serveur central.
2. L'admin ouvre la journee depuis Vercel.
3. **Couper internet sur le PC, sans couper le Wi-Fi.** Debrancher le cable, ou desactiver la
   connexion sortante de la box - pas le Wi-Fi local.
4. La serveuse ouvre un onglet client et envoie un bon.
5. **Le caissier doit le voir apparaitre.** C'est le moment qui decide de tout : c'est ce qui
   n'a jamais fonctionne jusqu'ici.
6. Le caissier valide le bon, puis encaisse.
7. Retablir internet. Attendre une minute.

### A9. Verifier dans le serveur central

Depuis Vercel, sur l'etablissement de test :

- **une seule** vente, pas deux ;
- le stock decremente **une seule fois** ;
- la vente imputee a la bonne session de caisse ;
- le bandeau d'etat du tableau de bord ne signale plus de retard.

Puis le sens inverse :

8. Depuis Vercel, annuler cette vente.
9. Attendre une minute, regarder le resume de caisse **sur le PC** : la vente doit en avoir
   disparu et le stock etre remonte.

### A10. Ce qu'il faut aussi essayer

- **Ouvrir la journee sans internet**, depuis le poste. Interdit dans le cloud, autorise ici.
- **Arreter le backend local en plein service**, le redemarrer : ce qui avait ete encaisse doit
  toujours etre la.
- **Relancer `diagnostic_instance` pendant que internet est coupe** : il doit rester utilisable
  et signaler le serveur central injoignable en ATTENTION, pas en ECHEC.

---

## B. Test au bar

Tout ce qui precede, plus ce que la repetition ne peut pas verifier.

### B1. Ce qui doit etre vrai avant de venir

- Le poste du caissier est un **PC allume pendant tout le service**.
- Il a une **adresse IP fixe** sur le reseau du bar - reservation DHCP sur la box, ou adresse
  statique. Sans cela, l'adresse saisie sur les tablettes cessera de fonctionner au prochain
  redemarrage de la box, en general un soir de service.
- **PostgreSQL**, pas SQLite. Le diagnostic le refuse : SQLite ignore silencieusement les
  verrous de ligne, ce qui supprime la protection contre deux encaissements simultanes.
- L'heure du poste est **synchronisee automatiquement**. Une horloge fausse impute les ventes a
  la mauvaise session de caisse, et peut declencher le controle anti-recul de la licence.

### B2. Installation

Suivre `INSTANCE_LOCALE.md`, puis :

```bash
python manage.py diagnostic_instance
```

### B3. L'interface du caissier, servie localement

`yarn start` est un serveur de developpement : il ne convient pas pour un bar. Construire
l'interface avec `apiBaseUrl` sur `http://localhost:8000/api` et la servir depuis le poste.

**C'est la piece qui manque encore a l'empaquetage** - elle sera traitee avec l'installeur
Windows. Pour un premier test au bar, `yarn start` lance a la main fait l'affaire, a condition de
savoir que ce n'est pas la configuration definitive.

### B4. Au demarrage de la machine

`run_sync` doit demarrer automatiquement (service Windows ou tache planifiee au demarrage). A
verifier en **redemarrant le poste** et en relancant le diagnostic : c'est le seul moyen de
savoir que ca tient.

### B5. Sauvegardes

La base du poste contient les ventes tant qu'elles ne sont pas remontees. Voir
`EXPLOITATION.md`.

### B6. Le test lui-meme

Identique a A8 et A9, avec l'equipe reelle. A faire **avant l'ouverture**, pas pendant le
service.

---

## Le diagnostic

```bash
python manage.py diagnostic_instance
```

Ne modifie rien, relancable autant de fois qu'on veut, y compris en plein service. Il verifie :

| Section | Ce qu'il regarde |
|---|---|
| Configuration | `INSTANCE_ROLE`, `CLOUD_API_URL`, `INSTANCE_TOKEN`, `DEBUG` |
| Reseau du bar | adresse du poste, `ALLOWED_HOSTS`, origines CORS, et **l'adresse a saisir sur les tablettes** |
| Base locale | joignable, et PostgreSQL et non SQLite |
| Serveur central | joignable, jeton accepte, etablissement reconnu, **ecart d'horloge** |
| Instance locale | le poste se reconnait lui-meme, et **son API repond** - sinon aucune correction de l'admin ne descendra |
| Referentiel | produits, departements, personnel descendus |
| File d'attente | operations en attente, et **operations en quarantaine** |

**ECHEC** bloque, **ATTENTION** n'empeche pas de travailler. Chaque ligne dit quoi corriger.

Une operation **en quarantaine** merite qu'on s'arrete : c'est une vente encaissee que le serveur
central a refusee. Elle ne remontera pas toute seule.

---

## Repli si le poste tombe

Panne, coupure de courant prolongee, disque mort. **Tant qu'internet fonctionne, le bar peut
repasser sur le serveur central** - mais chaque appareil doit y etre repointe a la main.

| Appareil | Geste |
|---|---|
| Tablettes | *Profil > Serveur du bar* → `https://cave-backend.bunker-store.store/api` |
| Caissier | Ouvrir l'interface hebergee (Vercel) sur un autre appareil |

**Si la tablette a des bons non transmis**, l'ecran affiche d'abord **la liste de ce qui sera
perdu** - heure, onglet, articles, montant - et demande de confirmer. Ces bons ne peuvent pas
suivre vers le serveur central : ils referencent des onglets que l'instance du bar etait seule a
connaitre.

**Le bon reflexe est de rallumer le poste** et d'attendre que la file se vide. N'abandonner que
si son disque est definitivement perdu. Apres l'abandon, la liste reste affichee sur cet ecran,
pour ressaisie a la main sur le serveur central.

### Pourquoi le repli n'est pas automatique

Ce serait pire que la panne. Une tablette qui basculerait seule vers le serveur central y
deposerait ses bons, la ou le caissier - toujours sur l'instance - ne les verrait jamais. Les
donnees du bar se couperaient en deux sans que personne s'en apercoive. On bascule **tout le bar**
ensemble, ou rien.

### Les ventes restees dans le poste

Ce que le poste n'avait pas encore remonte est **dans sa base, pas dans le cloud**. Rien ne
remontera tout seul. Si le disque est intact, le rebrancher et laisser `run_sync` finir avant de
le retirer du service. Sinon, la sauvegarde est le seul recours - voir `EXPLOITATION.md`.

### A essayer pendant la repetition

Couper le backend local pendant que la tablette est connectee, et **observer ce qu'elle affiche**.
C'est ce que la serveuse verra le jour ou le poste tombera : autant le decouvrir chez soi.

Puis, backend local toujours coupe, envoyer un bon depuis la tablette et aller dans
*Profil > Serveur du bar* : la liste de ce qui serait perdu doit apparaitre, avec le bon article
et le bon montant. **C'est la seule facon de verifier cet ecran** - le projet mobile n'a pas de
tests automatises.

---

## Si l'etape qui decide echoue

Le caissier ne voit pas le bon de la serveuse :

1. `diagnostic_instance` sur le poste. S'il signale un ECHEC, c'est la.
2. Sur la tablette, verifier *Profil > Serveur du bar* : l'adresse doit etre celle du poste, pas
   `cave-backend.bunker-store.store`.
3. Si la tablette affiche une erreur reseau alors que le poste repond depuis son propre
   navigateur : c'est le trafic en clair. L'APK n'a pas `usesCleartextTraffic`.
4. Si le caissier voit une page vide ou une erreur : son navigateur pointe sur Vercel, qui ne se
   charge pas sans internet.
5. Si la tablette repond bien mais que le poste est injoignable, ce n'est pas le test qui echoue,
   c'est le poste : voir [Repli si le poste tombe](#repli-si-le-poste-tombe).

---

## Ce qui n'a toujours pas ete verifie

**Rien de ce mecanisme n'a encore tourne contre un vrai serveur.** Les 168 tests automatises
simulent le serveur central avec des reponses fabriquees. La repetition decrite ici est la
premiere fois que la chaine complete - remontee vers `cave-backend`, descente, connexion -
s'executera pour de bon.
