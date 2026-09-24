# Installer le poste du caissier — machine neuve

Procedure complete, depuis un PC Windows sur lequel rien n'est installe.

`INSTANCE_LOCALE.md` decrit la configuration en supposant Python et PostgreSQL deja presents.
Ce document part de zero.

---

## Avant de partir

**Preparer tout ceci AVANT d'aller chez le client.** Le bar a par definition une connexion peu
fiable : c'est la raison meme de l'installation. Telecharger sur place ce qui aurait pu l'etre
avant, c'est risquer d'y passer la soiree.

| A emporter | Pourquoi |
|---|---|
| **Le jeton d'instance** | Se cree sur le serveur central (etape 0). Impossible a obtenir si internet manque au moment de l'installation. |
| **Un serveur central deja redeploye** | Etape -1. Sans le code de synchronisation en production, rien de ce qui suit ne fonctionne. |
| Installateur **Python 3.13** (windows x86-64 installer) | python.org/downloads |
| Installateur **PostgreSQL 16 ou 17** | postgresql.org/download/windows |
| Installateur **Node.js LTS** | nodejs.org — sert a servir l'interface du caissier |
| **Le code** du projet sur cle USB, ou Git installe | |
| Les **dependances Python et Node deja telechargees** | Voir « Preparer les dependances hors ligne » en fin de document |
| **L'APK** de l'application serveuse | Sur cle USB ou par cable |

**A decider avec le responsable du bar avant l'installation :**

- L'**adresse IP fixe** du poste sur le reseau. Reservation DHCP sur la box, ou adresse
  statique. Sans cela, l'adresse saisie sur les tablettes cessera de fonctionner au prochain
  redemarrage de la box - en general un soir de service.
- Que le poste **reste allume pendant tout le service**, et qu'une panne de ce PC arrete
  desormais **tout le bar**, serveuses comprises. C'est une aggravation par rapport a
  aujourd'hui, et elle doit etre dite avant, pas apres.

---

## Les adresses : deux conventions opposees

C'est l'erreur de saisie la plus probable de toute l'installation, et elle ne se voit pas.

| Ou | Adresse | `/api` ? |
|---|---|---|
| `.env` du poste, `CLOUD_API_URL` | `https://cave-backend.bunker-store.store` | **non** |
| `.env` du poste, `LOCAL_API_URL` | `http://127.0.0.1:8000` | **non** |
| Tablettes, *Profil > Serveur du bar* | `http://192.168.1.10:8000/api` | **oui** |

Le poste veut la **racine** du serveur central : le code y ajoute `/api/...` a chaque appel.
Les appareils, eux, visent une base qui **se termine** par `/api`.

Copier le lien tel qu'on le connait dans `CLOUD_API_URL` enverrait toutes les requetes vers
`.../api/api/orders/...`, et tout echouerait en 404 sans que rien ne designe la cause.
`setup_local_instance` et `diagnostic_instance` refusent desormais cette adresse **avant** le
premier appel reseau, et disent quoi ecrire a la place.

---

## -1. Verifier que le serveur central est a jour

**A faire avant tout le reste.** L'etape 0 ci-dessous n'existe sur le serveur heberge que s'il a
ete redeploye avec le code de synchronisation. Sur une version anterieure, `creer_instance` est
introuvable, et les adresses `/api/sync/...` repondent 404 - le poste ne pourra ni remonter ses
ventes ni descendre son referentiel.

Le deploiement doit inclure :

- l'application `sync` dans `INSTALLED_APPS` ;
- les migrations appliquees (`python manage.py migrate`) ;
- `UpstreamCaptureMiddleware` et `DownstreamCaptureMiddleware` dans `MIDDLEWARE` ;
- `INSTANCE_ROLE=cloud` (ou absent : c'est la valeur par defaut).

Verification rapide, depuis le serveur :

```bash
docker compose exec backend python manage.py creer_instance
```

Sans argument, elle doit **lister les etablissements**. Si la commande est introuvable, le
serveur n'est pas a jour : le redeployer avant d'aller chez le client.

---

## 0. Creer le jeton, sur le serveur central

Depuis n'importe quelle machine ayant acces au serveur heberge :

```bash
docker compose exec backend python manage.py creer_instance --organisation "NOM DU BAR"
```

Sans `--organisation`, la commande liste les etablissements. Elle affiche une ligne
`INSTANCE_TOKEN=...` : **la noter tout de suite**, elle ne sera pas reaffichee.

Un second appel sur le meme etablissement refuse. Il faut alors choisir `--supplementaire` (un
deuxieme poste dans le meme bar) ou `--remplacer` (poste vole ou reinstalle : les anciens jetons
cessent immediatement de fonctionner).

---

## 1. Installer les logiciels de base

Dans cet ordre, en acceptant les options par defaut sauf mention contraire.

### Python 3.13

Cocher **« Add python.exe to PATH »** sur le premier ecran de l'installateur. C'est l'oubli le
plus courant, et il se paie par des commandes introuvables a chaque etape suivante.

```powershell
python --version    # doit afficher 3.13.x
```

### PostgreSQL

**Noter le mot de passe du compte `postgres`** demande pendant l'installation : il sera repris a
l'etape 3. Laisser le port par defaut (5432).

**PostgreSQL et non SQLite.** Le diagnostic le refuse, et pour une raison concrete : SQLite
ignore silencieusement les verrous de ligne, ce qui supprime la protection contre deux
encaissements simultanes.

```powershell
psql --version
```

Si la commande est introuvable, ajouter `C:\Program Files\PostgreSQL\17\bin` au PATH.

### Node.js LTS

```powershell
node --version
```

### Verifier l'heure de la machine

Parametres > Heure et langue > **synchronisation automatique activee**. Une horloge fausse
impute les ventes a la mauvaise session de caisse et peut declencher le controle anti-recul de
la licence. Le diagnostic le verifiera, mais autant le regler maintenant.

---

## 2. Installer le code

Copier le projet depuis la cle USB vers `C:\parrain` (ou le cloner si Git est disponible).

```powershell
cd C:\parrain\le_parrain-main
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

---

## 3. Creer la base de donnees

```powershell
createdb -U postgres parrain_local
```

Le mot de passe demande est celui note a l'etape 1.

---

## 4. Configurer l'instance

Creer `C:\parrain\le_parrain-main\.env` :

```
INSTANCE_ROLE=local

# Racine du serveur central, SANS /api : le code l'ajoute lui-meme a chaque appel.
CLOUD_API_URL=https://cave-backend.bunker-store.store

INSTANCE_TOKEN=<le jeton de l'etape 0>

# Adresse a laquelle le poste se joint LUI-MEME, sans /api egalement.
LOCAL_API_URL=http://127.0.0.1:8000

DB_NAME=parrain_local
DB_USER=postgres
DB_PASSWORD=<mot de passe PostgreSQL>
DB_HOST=localhost
DB_PORT=5432

SECRET_KEY=<une longue chaine aleatoire, differente pour chaque bar>
DEBUG=0

# Adresse fixe du poste sur le reseau du bar : les tablettes la visent directement.
EXTRA_ALLOWED_HOSTS=192.168.1.10
EXTRA_CORS_ORIGINS=http://192.168.1.10
```

**`INSTANCE_ROLE=local` est la bascule essentielle.** Sans lui, le poste se comporte en serveur
central : il ne capture rien, ne remonte rien, et le caissier ne peut pas ouvrir la journee sans
internet.

Pour engendrer une `SECRET_KEY` :

```powershell
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

---

## 5. Mettre en service

```powershell
python manage.py migrate
python manage.py setup_local_instance
```

`setup_local_instance` verifie la configuration, s'assure que le serveur central reconnait
l'etablissement, puis descend le referentiel : produits, prix, personnel, licence. **Internet est
necessaire a cette etape.**

Puis, dans un terminal a part, demarrer le backend :

```powershell
cd C:\parrain\le_parrain-main
.\.venv\Scripts\activate
python manage.py runserver 0.0.0.0:8000
```

`0.0.0.0` et non l'adresse par defaut : sinon le poste n'ecoute que lui-meme et les tablettes ne
le joindront jamais.

---

## 6. Verifier avant d'aller plus loin

Dans un troisieme terminal :

```powershell
python manage.py diagnostic_instance
```

**Ne pas continuer tant qu'il n'est pas vert.** Chaque ECHEC dit quoi corriger. La fin affiche
l'adresse exacte a saisir sur les tablettes.

---

## 7. L'interface du caissier

```powershell
cd C:\parrain\le_parrain_front-main
npm ci
npm run build -- --configuration instance
npm install -g serve
serve -s dist\esther-pay\browser -l 4200
```

Le caissier ouvre ensuite **`http://localhost:4200`**.

**`--configuration instance` et non `production`.** La configuration `production` compile
l'adresse du serveur heberge dans la page : le caissier travaillerait alors a travers internet,
et perdrait tout pendant une coupure. La configuration `instance` compile `localhost:8000`.

**`localhost` et non l'IP du poste**, alors meme que les tablettes visent cette IP. Le navigateur
ne considere comme contexte sur que `localhost` : servie autrement, la page perdrait son Service
Worker, donc le cache de lecture et la file d'attente du caissier.

**Ne jamais ouvrir l'interface hebergee (Vercel) sur ce poste.** Internet coupe, elle ne se
chargerait meme pas.

---

## 8. Demarrage automatique

Trois choses doivent repartir seules apres une coupure de courant. Le plus simple sous Windows
est le **Planificateur de taches**, avec trois taches declenchees « Au demarrage de
l'ordinateur », executees **que l'utilisateur soit connecte ou non**.

| Tache | Programme | Arguments | Dossier de depart |
|---|---|---|---|
| Backend | `C:\parrain\le_parrain-main\.venv\Scripts\python.exe` | `manage.py runserver 0.0.0.0:8000 --noreload` | `C:\parrain\le_parrain-main` |
| Synchronisation | `C:\parrain\le_parrain-main\.venv\Scripts\python.exe` | `manage.py run_sync` | `C:\parrain\le_parrain-main` |
| Interface | `C:\Program Files\nodejs\npx.cmd` | `serve -s dist\esther-pay\browser -l 4200` | `C:\parrain\le_parrain_front-main` |

`--noreload` sur le backend : sans lui, le rechargement automatique lance un second processus,
et deux instances ecrivant dans la meme base est exactement ce qu'on cherche a eviter.

`run_sync` remonte les operations toutes les 30 secondes, fait descendre les corrections de
l'admin a chaque tour, et rafraichit le referentiel tous les 10 tours.

**Verifier en redemarrant reellement le poste**, puis en relancant `diagnostic_instance`. C'est
le seul moyen de savoir que ca tient. Une tache planifiee qui ne demarre pas ne previent
personne.

> `runserver` est un serveur de developpement. Il convient a un poste unique servant une poignee
> d'appareils sur un reseau local, et c'est ce qui est decrit ici. Pour une installation
> definitive, `waitress-serve` est preferable — a evaluer apres le premier test terrain.

---

## 9. Pointer les appareils

### Tablettes des serveuses

Installer l'APK, **se connecter une premiere fois avec internet**, puis *Profil > Serveur du bar*
et saisir l'adresse donnee par le diagnostic :

```
http://192.168.1.10:8000/api
```

Une seule fois par tablette, a l'installation.

### Poste du caissier

`http://localhost:4200`, mis en page de demarrage du navigateur.

---

## 10. Le test qui decide

**A faire avant l'ouverture, jamais pendant le service.**

1. Caissier et serveuse **se connectent pendant qu'internet est la** — obligatoire, la connexion
   est toujours verifiee par le serveur central.
2. L'admin ouvre la journee. Sans internet, le caissier peut le faire lui-meme.
3. **Couper internet, sans couper le Wi-Fi.**
4. La serveuse envoie un bon.
5. **Le caissier doit le voir apparaitre**, le valider, encaisser.
6. Retablir internet, attendre une minute.
7. Verifier dans le serveur central : **une seule** vente, un stock decremente **une seule
   fois**, imputee a la bonne session de caisse.

La procedure detaillee, avec le sens inverse et les cas limites, est dans
[TEST_TERRAIN.md](TEST_TERRAIN.md).

---

## 11. Sauvegardes

La base du poste contient les ventes **tant qu'elles ne sont pas remontees**. Si le disque lache
avant une synchronisation, elles n'existent nulle part ailleurs.

Voir [EXPLOITATION.md](EXPLOITATION.md). A planifier le jour de l'installation, pas plus tard.

---

## Preparer les dependances hors ligne

A faire **chez soi**, sur une machine ayant le meme Windows, avant de partir :

```powershell
# Paquets Python
pip download -r requirements.txt -d paquets_python

# Paquets Node
cd le_parrain_front-main
npm ci                      # remplit node_modules, a copier tel quel
npm run build -- --configuration instance   # l'interface est deja construite
```

Sur place :

```powershell
pip install --no-index --find-links paquets_python -r requirements.txt
```

Copier `node_modules` et `dist` plutot que de relancer `npm ci` sur la connexion du bar.

---

## Ce qui reste a savoir

- **Le poste est un point de panne unique.** S'il tombe, tout le bar s'arrete, y compris les
  serveuses. Le repli manuel est decrit dans [TEST_TERRAIN.md](TEST_TERRAIN.md).
- **Rien de tout ceci n'a encore tourne contre un vrai serveur** au moment ou ces lignes sont
  ecrites. Faire la repetition chez soi (section A de TEST_TERRAIN.md) avant la premiere
  installation chez un client.
