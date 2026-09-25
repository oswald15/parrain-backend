# Banc de fiabilite

Les tests automatises fabriquent les reponses du serveur central : ils verifient que le code se
comporte bien face a ce qu'on imagine que le serveur repondra. Ce banc fait l'inverse - **deux
processus Django reels, deux bases distinctes, de vraies requetes HTTP entre les deux.**

Il a trouve trois defauts qu'aucun des 191 tests ne pouvait voir, parce qu'ils tenaient tous a
l'assemblage et non aux pieces :

1. Le caissier ne pouvait pas ouvrir la journee au bar - le middleware refusait avant que la
   permission qui l'y autorise soit consultee.
2. Cette ouverture, une fois remontee, etait refusee par le serveur central et **gelait la file
   entiere** : toutes les ventes de la journee restaient bloquees derriere.
3. Les corrections de l'admin n'atteignaient le bar dans AUCUN sens : la commande et ses
   lignes portent des identifiants differents de chaque cote. Corrige en les adressant par
   identite naturelle (voir sync/corrections.py) ; le banc verifie desormais les quatre sens.

## Monter le banc

```bash
# Deux bases dediees
createdb -U postgres parrain_banc_cloud
createdb -U postgres parrain_banc_local

# Variables communes
export DB_USER=postgres DB_PASSWORD=... DB_HOST=localhost DB_PORT=5432
export SECRET_KEY=banc-essai-non-secret DEBUG=0
export EXTRA_ALLOWED_HOSTS=127.0.0.1,localhost

# Migrer les deux
DB_NAME=parrain_banc_cloud INSTANCE_ROLE=cloud python manage.py migrate
DB_NAME=parrain_banc_local INSTANCE_ROLE=local python manage.py migrate
```

Peupler le cloud (etablissement, personnel, produit, jeton d'instance), puis :

```bash
# Le serveur central du banc
DB_NAME=parrain_banc_cloud INSTANCE_ROLE=cloud python manage.py runserver 127.0.0.1:8001 --noreload

# L'instance du bar
export DB_NAME=parrain_banc_local INSTANCE_ROLE=local
export CLOUD_API_URL=http://127.0.0.1:8001 LOCAL_API_URL=http://127.0.0.1:8000
export INSTANCE_TOKEN=<le jeton>
python manage.py setup_local_instance
python manage.py runserver 127.0.0.1:8000 --noreload
```

## Mesurer

```bash
python scripts/banc_fiabilite/scenario.py
```

`BANC_TOURS=50` pour allonger. Le script sort en code 1 des qu'un ecart apparait.

## Pieges rencontres, pour ne pas les redecouvrir

- **Les telephones sont normalises en `+237...`.** Un compte cree avec un numero brut ne peut
  pas se connecter.
- **L'identifiant de l'onglet doit etre fourni par le client** (`id` dans le corps), comme le
  fait l'application mobile. Sans lui, le cloud en attribue un autre et tout ce qui suit part
  en quarantaine.
- **`runserver --noreload` ne recharge pas le code.** Apres une correction, arreter le processus
  - et verifier qu'il est bien mort : `netstat -ano | grep :8000`. Un ancien processus survivant
  repond avec l'ancien code et fait croire que le correctif ne marche pas.
- **Le stock ne baisse qu'a la validation du bon**, pas a son envoi.
