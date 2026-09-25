# Guide d'installation — Le Parrain dans un bar

**Un seul document. Suivez-le de haut en bas, sans rien sauter.**

Chaque etape dit : ce que vous tapez, ce que vous devez voir, et quoi faire si ca rate.

---

## Sommaire

- [A quoi ca sert](#a-quoi-ca-sert)
- [Les trois machines](#les-trois-machines)
- [Les adresses : le piege a eviter](#les-adresses--le-piege-a-eviter)
- [Avant de partir chez le client](#avant-de-partir-chez-le-client)
- [PARTIE 1 — Sur le serveur](#partie-1--sur-le-serveur-chez-vous-avec-internet)
- [PARTIE 2 — Sur le PC du bar](#partie-2--sur-le-pc-du-bar)
- [PARTIE 3 — Les tablettes et le navigateur](#partie-3--les-tablettes-et-le-navigateur)
- [PARTIE 4 — Le test qui decide](#partie-4--le-test-qui-decide)
- [PARTIE 5 — Au quotidien](#partie-5--au-quotidien)
- [En cas de probleme](#en-cas-de-probleme)

---

## A quoi ca sert

Aujourd'hui, si internet tombe dans le bar, **la serveuse et le caissier ne se voient plus**.
Le bon envoye par la serveuse n'arrive pas a la caisse. Le client n'est pas servi.

On installe donc **une copie du logiciel sur le PC du caissier**. Tout le monde continue de
travailler ensemble sur le Wi-Fi du bar, meme sans internet. Les ventes remontent vers le
serveur des que internet revient.

---

## Les trois machines

Retenez ces trois noms, ils reviennent partout dans ce guide.

| Nom | Ce que c'est | Ou |
|---|---|---|
| **Le serveur** | `cave-backend.bunker-store.store` | Sur internet. Il ne bouge pas. |
| **Le poste** | Le PC du caissier | **Dans le bar.** C'est lui qu'on installe. |
| **Les tablettes** | Les telephones des serveuses | Dans le bar, sur le Wi-Fi. |

```
        Wi-Fi du bar (marche meme sans internet)
    +------------------------------------------+
    |                                          |
    |   Tablettes  -------->  LE POSTE         |
    |                         (PC du caissier) |
    +------------------------------+-----------+
                                   |
                                   | internet, quand il y en a
                                   v
                              LE SERVEUR
                          (et l'ecran de l'admin)
```

**A dire au patron du bar AVANT d'installer :** une fois le poste installe, **s'il tombe en
panne, tout le bar s'arrete**, les serveuses aussi. Avant, une panne de ce PC les laissait
travailler. C'est le prix a payer pour travailler sans internet.

---

## Les adresses : le piege a eviter

C'est l'erreur la plus courante, et elle ne se voit pas. **Lisez ce tableau deux fois.**

| Ou on l'ecrit | Adresse a ecrire | Se termine par `/api` ? |
|---|---|---|
| Fichier `.env` du poste, ligne `CLOUD_API_URL` | `https://cave-backend.bunker-store.store` | **NON** |
| Fichier `.env` du poste, ligne `LOCAL_API_URL` | `http://127.0.0.1:8000` | **NON** |
| Tablette, ecran *Profil > Serveur du bar* | `http://192.168.1.10:8000/api` | **OUI** |

Dans le fichier `.env`, **ne jamais mettre `/api` a la fin**. Le logiciel l'ajoute tout seul.
Si vous le mettez, il cherchera `.../api/api/...` et tout echouera.

Rassurez-vous : si vous vous trompez, le logiciel refuse de demarrer et vous dit exactement
quoi corriger.

---

## Avant de partir chez le client

Le bar a une mauvaise connexion — c'est la raison meme de l'installation. **Tout telecharger
chez vous avant de partir.** Sinon vous y passez la soiree.

**A mettre sur une cle USB :**

- [ ] L'installateur **Python 3.13** — https://python.org/downloads (Windows installer 64-bit)
- [ ] L'installateur **PostgreSQL 17** — https://postgresql.org/download/windows
- [ ] L'installateur **Node.js LTS** — https://nodejs.org
- [ ] **Le dossier du projet** entier (`le_parrain-main` et `le_parrain_front-main`)
- [ ] **L'APK** de l'application des serveuses
- [ ] Les **paquets Python** deja telecharges (voir encadre ci-dessous)

**A avoir note sur un papier :**

- [ ] Le **jeton** de l'etablissement (PARTIE 1, etape 3)
- [ ] L'**adresse IP fixe** que le poste aura dans le bar (a demander au patron ou a son
      installateur reseau)

> **Preparer les paquets chez vous, la veille**
>
> Dans `le_parrain-main` :
> ```
> pip download -r requirements.txt -d paquets_python
> ```
> Copiez le dossier `paquets_python` sur la cle.
>
> Dans `le_parrain_front-main` :
> ```
> npm ci
> npm run build -- --configuration instance
> ```
> Copiez les dossiers `node_modules` et `dist` sur la cle.
>
> Au bar, plus rien a telecharger.

---

## PARTIE 1 — Sur le serveur (chez vous, avec internet)

### Etape 1 — Verifier que le serveur est a jour

Connectez-vous a votre serveur et tapez :

```bash
docker compose exec backend python manage.py creer_instance
```

**Ce que vous devez voir :** la liste de vos etablissements.

**Si vous voyez « Unknown command » :** votre serveur est trop ancien. **Arretez-vous ici** et
redeployez-le avec la derniere version du code. Sans cela, rien de la suite ne fonctionnera.

### Etape 2 — Verifier que l'etablissement existe

Le bar doit deja exister sur le serveur, avec ses produits, ses departements et son personnel.
Si ce n'est pas le cas :

1. Dans la **console systeme**, creez l'organisation et son **superadmin**.
2. Connectez-vous avec ce superadmin sur `https://parrain-seven.vercel.app`.
3. Creez les **departements**, les **produits**, puis les **comptes** du caissier et des
   serveuses.

Notez les identifiants du caissier et d'une serveuse : vous en aurez besoin pour le test.

### Etape 3 — Creer le jeton du poste

```bash
docker compose exec backend python manage.py creer_instance --organisation "NOM EXACT DU BAR"
```

**Ce que vous devez voir :**

```
Instance creee pour NOM DU BAR : Poste caisse

  INSTANCE_TOKEN=xK9fL2mQ...
```

**NOTEZ CE JETON TOUT DE SUITE.** Il ne sera plus jamais affiche.

**Si elle dit que le bar a deja un poste :** normal si vous reinstallez. Relancez en ajoutant
`--remplacer` (l'ancien jeton cessera de marcher), ou `--supplementaire` si vous ajoutez un
deuxieme PC dans le meme bar.

---

## PARTIE 2 — Sur le PC du bar

### Etape 4 — Regler l'heure

**Parametres > Heure et langue** : verifier que **« Regler l'heure automatiquement »** est
active.

Une horloge fausse range les ventes dans la mauvaise caisse. Ca ne se voit qu'a la fin du mois.

### Etape 5 — Installer Python

Lancez l'installateur Python depuis la cle USB.

**Sur le premier ecran, cochez « Add python.exe to PATH ».** C'est la case qu'on oublie, et
sans elle plus rien ne marche ensuite.

Puis cliquez « Install Now ».

**Verifier.** Menu Demarrer > tapez `powershell` > ouvrez-le, puis :

```powershell
python --version
```

**Ce que vous devez voir :** `Python 3.13.x`

### Etape 6 — Installer PostgreSQL

Lancez l'installateur PostgreSQL. Cliquez « Next » partout, sauf :

- **Mot de passe** : il en demande un pour le compte `postgres`. **NOTEZ-LE**, il servira a
  l'etape 10.
- **Port** : laissez `5432`.

**Verifier :**

```powershell
psql --version
```

**Si vous voyez « psql n'est pas reconnu » :** ajoutez `C:\Program Files\PostgreSQL\17\bin`
au PATH de Windows, fermez PowerShell, rouvrez-le, reessayez.

### Etape 7 — Installer Node.js

Lancez l'installateur Node.js, cliquez « Next » partout.

**Verifier :**

```powershell
node --version
```

### Etape 8 — Copier le projet

Copiez le projet depuis la cle vers **`C:\parrain`**. Vous devez avoir :

```
C:\parrain\le_parrain-main
C:\parrain\le_parrain_front-main
C:\parrain\paquets_python
```

Puis, dans PowerShell :

```powershell
cd C:\parrain\le_parrain-main
python -m venv .venv
.\.venv\Scripts\activate
```

**Ce que vous devez voir :** la ligne commence maintenant par `(.venv)`.

### Etape 9 — Installer les paquets du logiciel

```powershell
pip install --no-index --find-links C:\parrain\paquets_python -r requirements.txt
```

**Ce que vous devez voir :** `Successfully installed ...` avec une longue liste.

> Si le bar a internet, `pip install -r requirements.txt` suffit.

### Etape 10 — Creer la base de donnees

```powershell
createdb -U postgres parrain_local
```

Il demande le mot de passe note a l'etape 6.

**Ce que vous devez voir :** rien du tout. Pas de message = c'est reussi.

### Etape 11 — Ecrire le fichier de configuration

D'abord, une cle secrete :

```powershell
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

Copiez la longue ligne affichee.

Creez ensuite le fichier **`C:\parrain\le_parrain-main\.env`**.

> Avec le Bloc-notes : Fichier > Enregistrer sous, choisir **« Tous les fichiers »** dans le
> type, et nommer `.env` — sinon Windows l'appellera `.env.txt` et rien ne marchera.

Collez ceci dedans :

```
INSTANCE_ROLE=local

CLOUD_API_URL=https://cave-backend.bunker-store.store
INSTANCE_TOKEN=COLLEZ_ICI_LE_JETON_DE_L_ETAPE_3
LOCAL_API_URL=http://127.0.0.1:8000

DB_NAME=parrain_local
DB_USER=postgres
DB_PASSWORD=COLLEZ_ICI_LE_MOT_DE_PASSE_DE_L_ETAPE_6
DB_HOST=localhost
DB_PORT=5432

SECRET_KEY=COLLEZ_ICI_LA_LIGNE_GENEREE_CI_DESSUS
DEBUG=0

EXTRA_ALLOWED_HOSTS=192.168.1.10
EXTRA_CORS_ORIGINS=http://192.168.1.10
```

**Remplacez `192.168.1.10`** par l'adresse IP fixe du poste dans ce bar (les deux lignes).

**La ligne la plus importante est la premiere.** Sans `INSTANCE_ROLE=local`, le PC se prend
pour le serveur : il ne garde rien, ne remonte rien, et le caissier ne peut pas ouvrir la
journee sans internet.

### Etape 12 — Preparer la base et descendre les donnees

```powershell
python manage.py migrate
python manage.py setup_local_instance
```

**Ce que vous devez voir :** une suite de `[OK]`, puis `Instance prete.`

**Cette etape a besoin d'internet.** Elle telecharge les produits, les prix et le personnel.

**Si vous voyez une ligne `[X]` :**

| Message | Ce qu'il faut faire |
|---|---|
| `CLOUD_API_URL se termine par '/api'` | Enlevez `/api` a la fin, dans le `.env` |
| `INSTANCE_TOKEN absent` | Vous avez oublie de coller le jeton |
| `Jeton refuse` | Le jeton est faux, ou vous avez fait `--remplacer` depuis |
| `Serveur central injoignable` | Pas d'internet, ou l'adresse est mal ecrite |

### Etape 13 — Demarrer le logiciel

Ouvrez **une NOUVELLE fenetre PowerShell** (gardez l'autre ouverte) :

```powershell
cd C:\parrain\le_parrain-main
.\.venv\Scripts\activate
python manage.py runserver 0.0.0.0:8000 --noreload
```

**Ce que vous devez voir :** `Starting development server at http://0.0.0.0:8000/`

**Laissez cette fenetre ouverte.** Si vous la fermez, le bar s'arrete.

> Le `0.0.0.0` est essentiel : sans lui, le PC ne repondrait qu'a lui-meme et les tablettes ne
> le trouveraient jamais.

### Etape 14 — VERIFIER (ne sautez pas cette etape)

Ouvrez **une TROISIEME fenetre PowerShell** :

```powershell
cd C:\parrain\le_parrain-main
.\.venv\Scripts\activate
python manage.py diagnostic_instance
```

**Ce que vous devez voir :** des `OK` partout, et a la fin :

```
  A saisir sur les tablettes : http://192.168.1.10:8000/api

Tout est en ordre. L'instance est prete pour le test hors-ligne.
```

**NOTEZ L'ADRESSE AFFICHEE.** C'est elle qu'on saisira sur les tablettes.

**N'allez pas plus loin tant que vous voyez un `ECHEC`.** Chaque ligne `ECHEC` est suivie d'une
fleche `->` qui dit quoi faire.

### Etape 15 — Demarrer la synchronisation

Ouvrez **une QUATRIEME fenetre PowerShell** :

```powershell
cd C:\parrain\le_parrain-main
.\.venv\Scripts\activate
python manage.py run_sync
```

**Ce que vous devez voir, toutes les 30 secondes :**

```
0 operation(s) remontee(s), 0 mise(s) en quarantaine.
```

**Laissez cette fenetre ouverte aussi.** C'est elle qui envoie les ventes au serveur.

### Etape 16 — Preparer l'ecran du caissier

Ouvrez **une CINQUIEME fenetre PowerShell** :

```powershell
cd C:\parrain\le_parrain_front-main
npm install -g serve
serve -s dist\esther-pay\browser -l 4200
```

> Si vous n'avez pas copie `dist` depuis chez vous, faites avant :
> `npm ci` puis `npm run build -- --configuration instance`

**Ce que vous devez voir :** `Accepting connections at http://localhost:4200`

**Laissez cette fenetre ouverte.**

### Etape 17 — Faire tout redemarrer tout seul

**C'est l'etape la plus souvent bâclee, et celle qui se paie le plus cher.** Le bar aura des
coupures de courant et des extinctions le soir. Si elle est mal faite, un matin le systeme ne
redemarre pas et personne ne comprend pourquoi.

Quatre choses doivent revenir seules :

| Quoi | Comment ca redemarre |
|---|---|
| PostgreSQL | Tout seul (service Windows installe en « Automatique ») |
| Le backend | Tache planifiee (ci-dessous) |
| La synchronisation | Tache planifiee (ci-dessous) |
| L'ecran du caissier | Tache planifiee + raccourci de demarrage (etape 17 bis) |

#### Creer les trois taches

Ouvrez le **Planificateur de taches** (menu Demarrer, tapez « planificateur »).

Pour **chacune** des trois lignes du tableau : clic droit sur « Bibliotheque du Planificateur »
> **Creer une tache** (surtout pas « Creer une tache de base », elle n'a pas les reglages qu'il
faut).

**Onglet General**
- Nom : celui de la colonne « Nom » ci-dessous
- Cocher **« Executer meme si l'utilisateur n'est pas connecte »**
- Cocher **« Executer avec les autorisations maximales »**

**Onglet Declencheurs** > Nouveau
- Commencer la tache : **Au demarrage de l'ordinateur**
- Cocher **« Differer la tache pendant : 1 minute »**

> **Pourquoi ce delai ?** Au demarrage, Windows lance tout en meme temps. Sans lui, le backend
> demarre avant que PostgreSQL soit pret, ne trouve pas la base, et s'arrete. Il ne reessaiera
> jamais tout seul. Une minute suffit.

**Onglet Actions** > Nouveau > Demarrer un programme — voir le tableau.

**Onglet Conditions**
- **Decocher « N'executer que si l'ordinateur est alimente par le secteur »** (sinon, sur un
  portable sur batterie, rien ne demarre)

**Onglet Parametres**
- Cocher **« Si la tache echoue, redemarrer toutes les : 1 minute »**, **3 fois**
- **DECOCHER « Arreter la tache si elle s'execute plus de : 3 jours »**

> **Ce dernier point est un piege.** Il est coche par defaut. Si vous le laissez, Windows
> **tuera le backend au bout de trois jours** de fonctionnement. Le bar s'arretera un soir, sans
> raison apparente, et redemarrer le PC « reparera » le probleme — jusqu'a trois jours plus tard.

| Nom | Programme | Arguments | Commencer dans |
|---|---|---|---|
| Parrain - Backend | `C:\parrain\le_parrain-main\.venv\Scripts\python.exe` | `manage.py runserver 0.0.0.0:8000 --noreload` | `C:\parrain\le_parrain-main` |
| Parrain - Synchro | `C:\parrain\le_parrain-main\.venv\Scripts\python.exe` | `manage.py run_sync` | `C:\parrain\le_parrain-main` |
| Parrain - Ecran caisse | `C:\Program Files\nodejs\npx.cmd` | `serve -s dist\esther-pay\browser -l 4200` | `C:\parrain\le_parrain_front-main` |

Windows demandera le **mot de passe du compte Windows** a l'enregistrement de chaque tache.
C'est normal : c'est ce qui lui permet de les lancer sans que personne soit connecte.

### Etape 17 bis — Ouvrir l'ecran du caissier automatiquement

Les trois taches ci-dessus font tourner le logiciel, mais **personne n'ouvre le navigateur**.
Le caissier arriverait devant un bureau vide.

1. Sur le PC, activez la **connexion automatique Windows** (pour que le bureau s'ouvre sans mot
   de passe apres une coupure de courant) : touche Windows + R, tapez `netplwiz`, decochez
   « Les utilisateurs doivent entrer un nom d'utilisateur et un mot de passe », validez, et
   saisissez le mot de passe du compte.
2. Touche Windows + R, tapez **`shell:startup`**, validez. Un dossier s'ouvre.
3. Clic droit dans ce dossier > **Nouveau > Raccourci**.
4. Comme emplacement, saisissez (en adaptant a votre navigateur) :
   ```
   "C:\Program Files\Google\Chrome\Application\chrome.exe" --start-fullscreen http://localhost:4200
   ```
5. Nommez-le « Caisse » et validez.

Au demarrage, le PC ouvrira desormais la caisse en plein ecran, tout seul.

### Etape 17 ter — VERIFIER, en redemarrant pour de vrai

**Ne sautez pas cette etape.** Une tache planifiee mal reglee ne previent personne : elle ne
fait rien, silencieusement.

1. **Eteignez completement le PC** (pas « redemarrer » : eteindre, puis rallumer). C'est ce qui
   se passera apres une coupure de courant.
2. Attendez **deux minutes** sans rien toucher.
3. L'ecran de caisse doit s'etre ouvert tout seul.
4. Ouvrez PowerShell et lancez :
   ```powershell
   cd C:\parrain\le_parrain-main
   .\.venv\Scripts\activate
   python manage.py diagnostic_instance
   ```

**Ce que vous devez voir :** tout vert, comme a l'etape 14.

**Si le diagnostic dit « Le backend local ne repond pas » :** la tache « Parrain - Backend » n'a
pas demarre. Dans le Planificateur, cliquez dessus et regardez la colonne **« Dernier resultat
de l'execution »** :

| Resultat | Cause probable |
|---|---|
| `0x1` | Mauvais chemin dans « Commencer dans », ou `.venv` absent |
| `0x2` | Le programme est introuvable : verifiez le chemin exact du `.exe` |
| La tache est « Prete » et n'a jamais tourne | Le declencheur n'est pas « Au demarrage de l'ordinateur » |
| `0x41303` | La tache n'a jamais ete executee : relancez-la a la main pour voir l'erreur |

Vous pouvez tester une tache sans redemarrer : clic droit dessus > **Executer**.

---

## PARTIE 3 — Les tablettes et le navigateur

### Etape 18 — Le navigateur du caissier

L'etape 17 bis l'ouvre deja automatiquement au demarrage. Il reste deux choses a faire.

**Verifiez l'adresse affichee** — elle doit etre exactement :

```
http://localhost:4200
```

**Dites au caissier de ne JAMAIS ouvrir `parrain-seven.vercel.app` sur ce PC.** Sans internet,
cette page ne s'afficherait meme pas, et il croirait le systeme en panne. Retirez-la des
favoris et de l'historique si elle y est.

### Etape 19 — Chaque tablette

1. Installez l'APK depuis la cle USB.
2. **Avec internet**, connectez-vous une premiere fois avec le compte de la serveuse.
3. Allez dans **Profil > Serveur du bar**.
4. Saisissez l'adresse donnee par le diagnostic a l'etape 14 :
   ```
   http://192.168.1.10:8000/api
   ```
   **Avec `/api` a la fin, cette fois.**
5. Validez. Le message doit dire « Serveur enregistre. »

A faire **une seule fois par tablette**.

---

## PARTIE 4 — Le test qui decide

**Faites-le avant l'ouverture, jamais pendant le service.**

### Etape 20 — Preparer

1. **Avec internet**, le caissier se connecte sur `http://localhost:4200`.
2. **Avec internet**, la serveuse se connecte sur sa tablette.
3. L'admin ouvre la journee. (Sans internet, le caissier peut l'ouvrir lui-meme.)

> La connexion passe toujours par le serveur. **Sans internet, personne ne peut se connecter.**
> Une fois connectes, ils le restent — c'est tout l'interet. Dites-leur de **ne pas se
> deconnecter** pendant le service.

### Etape 21 — Couper internet

**Debranchez le cable internet de la box**, ou coupez sa connexion sortante.

**NE COUPEZ PAS LE WI-FI.** Le Wi-Fi du bar doit continuer de fonctionner.

### Etape 22 — LE moment de verite

1. La serveuse ouvre un onglet client et envoie un bon.
2. **Le caissier doit le voir apparaitre sur son ecran.**
3. Le caissier valide le bon.
4. Le caissier encaisse.

**Si le caissier voit le bon : ca marche.** C'est exactement ce qui ne fonctionnait pas avant.

**Si le caissier ne voit rien**, allez a [En cas de probleme](#en-cas-de-probleme).

### Etape 23 — Rebrancher et verifier

1. Rebranchez internet.
2. Attendez une minute. La fenetre `run_sync` doit afficher `1 operation(s) remontee(s)`.
3. Sur `https://parrain-seven.vercel.app`, avec le compte admin :
   - [ ] **une seule** vente, pas deux
   - [ ] le stock a baisse **une seule fois**
   - [ ] la vente est dans la bonne session de caisse

### Etape 24 — Verifier le sens inverse

1. Depuis l'ecran de l'admin, **annulez cette vente**.
2. Attendez une minute.
3. Sur le PC du bar, regardez le resume de caisse : **la vente doit avoir disparu** et le stock
   etre remonte.

Puis l'inverse : annulez une autre vente **depuis le poste du bar**, attendez une minute, et
verifiez qu'elle est bien annulee cote admin.

Si l'une des deux ne passe pas, la synchronisation ne tourne pas : verifiez `LOCAL_API_URL` dans
le `.env` et le journal du service.

> Le retrait d'un seul article d'une commande circule de la meme facon, dans les deux sens.

---

## PARTIE 5 — Au quotidien

### Ce que le bar doit savoir

- **Le PC du caissier reste allume pendant tout le service.**
- **Tout le monde se connecte pendant qu'il y a internet**, au debut du service.
- **Personne ne se deconnecte** pendant une coupure.

### Le matin, apres une extinction ou une coupure de courant

**Il n'y a rien a faire.** On allume le PC, on attend deux minutes, l'ecran de caisse s'ouvre
tout seul. Le caissier se connecte (avec internet) et le service commence.

Si l'ecran de caisse ne s'est pas ouvert, ou affiche une erreur :

```powershell
cd C:\parrain\le_parrain-main
.\.venv\Scripts\activate
python manage.py diagnostic_instance
```

Il dira lequel des trois programmes n'a pas demarre.

### Ce que l'admin doit savoir

Sur son tableau de bord, un **bandeau d'avertissement** apparait quand un bar n'a pas encore
tout remonte. Tant qu'il est la, **les chiffres affiches sont incomplets**. Ce n'est pas une
panne : le bar travaille hors-ligne, ses ventes arriveront.

Dans **Archives > Consommations non enregistrees**, il peut y avoir des ventes servies que le
systeme n'a jamais pu enregistrer (cas rare : PC du bar definitivement perdu). Elles doivent
etre **ressaisies a la main**, puis marquees comme traitees. Elles ne disparaissent jamais :
elles restent la trace de l'ecart.

### Sauvegardes

La base du PC contient les ventes **tant qu'elles ne sont pas remontees**. Si le disque lache
avant, elles n'existent nulle part ailleurs.

Voir [EXPLOITATION.md](EXPLOITATION.md). **A mettre en place le jour de l'installation.**

### Si le PC du bar tombe en panne

Tant qu'il y a internet, le bar peut repasser sur le serveur — **mais appareil par appareil,
a la main** :

- **Tablettes** : *Profil > Serveur du bar* → `https://cave-backend.bunker-store.store/api`
- **Caissier** : ouvrir `https://parrain-seven.vercel.app` sur un autre appareil

Si une tablette a des bons non transmis, l'ecran affiche **la liste de ce qui sera perdu** et
demande confirmation. **Le bon reflexe est de rallumer le PC** et d'attendre que la file se
vide. N'abandonnez que si son disque est definitivement mort ; la liste reste affichee ensuite,
pour ressaisie a la main.

---

## En cas de probleme

**Le premier reflexe, toujours :**

```powershell
cd C:\parrain\le_parrain-main
.\.venv\Scripts\activate
python manage.py diagnostic_instance
```

Il ne casse rien et peut etre lance en plein service.

### Le caissier ne voit pas le bon de la serveuse

| Verifiez | Comment |
|---|---|
| Le diagnostic est vert | Commande ci-dessus |
| La tablette vise le poste | *Profil > Serveur du bar* : doit contenir `192.168.`, **pas** `cave-backend` |
| Le PC repond | Sur le PC, ouvrir `http://localhost:8000/api/` dans le navigateur |
| La tablette est sur le bon Wi-Fi | Celui du bar, pas les donnees mobiles |

**Si le PC repond mais pas depuis la tablette :** l'APK est trop ancien. Il faut celui construit
apres le 22/09/2026.

### Le caissier a une page blanche

Son navigateur est sur Vercel au lieu de `http://localhost:4200`.

### Ce matin, rien ne s'est lance apres le redemarrage

Ouvrez le **Planificateur de taches** et regardez les trois taches « Parrain - ... », colonne
**« Dernier resultat de l'execution »**. Clic droit > **Executer** relance celle qui manque.

Les causes les plus frequentes, dans l'ordre :

1. **La case « Arreter la tache si elle s'execute plus de 3 jours » est restee cochee.**
   Windows a tue le programme. Decochez-la (onglet Parametres) — voir etape 17.
2. **Pas de delai au demarrage.** Le backend a demarre avant PostgreSQL et s'est arrete.
   Ajoutez « Differer la tache pendant : 1 minute » au declencheur.
3. **Le PC a demarre sans que personne ouvre la session** et la connexion automatique n'est pas
   activee : les taches tournent, mais le navigateur ne s'ouvre pas. Voir etape 17 bis.

### « Connexion impossible : le serveur central est injoignable »

Normal s'il n'y a pas internet. **Il faut internet pour se connecter.** Retablissez-le, ou
attendez.

### Le diagnostic dit « operation(s) en quarantaine »

Ce sont des ventes encaissees que le serveur a refusees. **Ne les ignorez pas.** Notez le
nombre affiche et appelez le support.

### Tout est casse, je veux recommencer

**Verifiez d'abord** que `run_sync` affiche `0 operation(s) en attente` : sinon vous effacez des
ventes qui n'ont pas encore ete transmises.

```powershell
dropdb -U postgres parrain_local
createdb -U postgres parrain_local
python manage.py migrate
python manage.py setup_local_instance
```

---

## Pour aller plus loin

Ces documents ne sont **pas necessaires** pour installer. Ils expliquent le pourquoi.

- [INSTANCE_LOCALE.md](INSTANCE_LOCALE.md) — le detail de la configuration et ses limites
- [TEST_TERRAIN.md](TEST_TERRAIN.md) — la repetition a faire chez soi avant un vrai bar
- [EXPLOITATION.md](EXPLOITATION.md) — sauvegardes, restauration, purges

---

## Une derniere chose, honnetement

Au moment ou ce guide est ecrit, **ce systeme n'a jamais tourne contre un vrai serveur**. Les
tests automatises simulent les reponses.

**Faites l'installation complete chez vous d'abord**, sur une machine de test et avec un
etablissement de test. Une soiree chez vous vaut mieux qu'une soiree ratee chez un client.
