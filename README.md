# 🍷 Le Parrain – Wi-Fi Voucher Backend

**Le Parrain** est une application **SaaS** de gestion pour bars/snacks permettant :

- de suivre les consommations clients,
- d’automatiser la génération de **vouchers Wi-Fi** (QR code) valables 15 minutes,
- de gérer le personnel (serveurs, barmans, admin),
- et d’analyser les performances commerciales.

---

## 📖 Par où commencer

Chaque document répond à une question, et ils se lisent dans cet ordre. Aucun ne résume les
autres : sauter une étape fait perdre du temps plus loin.

| Quand | Document | Ce qu'il donne |
|---|---|---|
| **1.** Avant tout | Ce README | Installation du backend, lancement en local |
| **2.** Avant de vendre à un client | [AUDIT_CAHIER_DES_CHARGES.md](../AUDIT_CAHIER_DES_CHARGES.md) | Ce que le produit fait vraiment, et ce qu'il ne fait pas |
| **3.** Avant la première mise en production | [EXPLOITATION.md](EXPLOITATION.md) | Sauvegardes, restauration, migrations, purges à planifier |
| **4.** Avant d'équiper un bar | [TEST_TERRAIN.md](TEST_TERRAIN.md) | Comment vérifier le mode hors-ligne — **la répétition chez soi d'abord** |
| **5.** Le jour de l'installation | [INSTALLATION_POSTE.md](INSTALLATION_POSTE.md) | Machine neuve : de zéro au poste en service |
| **5 bis.** Référence | [INSTANCE_LOCALE.md](INSTANCE_LOCALE.md) | Le détail de la configuration, machine déjà équipée |
| **6.** Sur place, et ensuite | `python manage.py diagnostic_instance` | Vérifie que l'instance est réellement en service |

**Ne pas inverser 4 et 5.** `INSTALLATION_POSTE.md` décrit *comment installer* ; `TEST_TERRAIN.md`
dit *ce qu'il faut avoir vérifié et emporté avant de le faire chez un client* — le jeton d'instance,
les installateurs, un APK à jour. Découvrir sur place qu'il manque quelque chose coûte le
déplacement.

Le point d'arrivée n'est pas un document mais **le test de l'étape A8 de
[TEST_TERRAIN.md](TEST_TERRAIN.md)** : internet coupé, le caissier voit le bon de la serveuse et
l'encaisse. Tant qu'il n'a pas été fait, le système n'est pas vérifié — quel que soit le nombre
de tests automatisés qui passent.

---

## 🚀 Fonctionnalités clés

- 🔒 Authentification sécurisée par **numéro de téléphone** (sans email)
- 🧑‍🍳 Gestion des **rôles** : Serveur, Barman, Admin
- 📦 Gestion du **stock** et des bons de réapprovisionnement
- 🧾 Suivi des **commandes** et des statuts (ouverte/fermée)
- 📱 Génération automatique de **QR codes Wi-Fi**
- 🏢 Structure **multi-organisation (SaaS)**
- 📊 Statistiques sur les ventes et la performance du personnel

---

## 🛠️ Stack technique

- **Langage** : Python 3.13 (voir `Dockerfile`)
- **Framework** : Django 6 + Django REST Framework
- **Base de données** : PostgreSQL
- **QR Code** : `qrcode` Python
- **Gestion secrets** : `.env` via `python-decouple`
- **Déploiement recommandé** : Docker, Railway, Heroku, Render...

---

## 📁 Structure du projet

le-parrain-backend/
├── apps/
│ ├── users/ # Authentification et rôles
│ ├── orders/ # Commandes et paiements
│ ├── products/ # Produits et catégories
│ ├── stock/ # Réapprovisionnements
│ ├── vouchers/ # Génération QR Wi-Fi
│ └── organisations/ # Multi-tenancy
├── wifi_voucher_saas/ # Configuration Django
├── .env.example
├── requirements.txt
├── README.md
└── manage.py

---

## ⚙️ Installation locale

### 1. Cloner le projet

git clone 
cd le-parrain-backend

#### 2. Créer un environnement virtuel

python -m venv env
source env/bin/activate        # Linux/macOS
# ou
.\env\Scripts\activate         # Windows

---

## 🏪 Instance locale dans un bar

Voir **[INSTALLATION_POSTE.md](INSTALLATION_POSTE.md)** : installation complète sur une machine
neuve, pour que serveuses et caissier continuent de travailler ensemble sans internet.

Voir **[INSTANCE_LOCALE.md](INSTANCE_LOCALE.md)** : le détail de la configuration et ce qu'elle
implique, sur une machine déjà équipée.

Voir **[TEST_TERRAIN.md](TEST_TERRAIN.md)** : comment vérifier que ça marche — une répétition
chez soi d'abord, puis le test au bar. À lire avant d'installer chez un client.

## 🛡️ Exploitation (sauvegardes, restauration, mises à jour)

Voir **[EXPLOITATION.md](EXPLOITATION.md)** : script de sauvegarde automatisé
(`scripts/backup.sh`), procédure de restauration, et points de vigilance en production.
