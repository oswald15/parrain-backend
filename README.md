# 🍷 Le Parrain – Wi-Fi Voucher Backend

**Le Parrain** est une application **SaaS** de gestion pour bars/snacks permettant :

- de suivre les consommations clients,
- d’automatiser la génération de **vouchers Wi-Fi** (QR code) valables 15 minutes,
- de gérer le personnel (serveurs, barmans, admin),
- et d’analyser les performances commerciales.

---

## 📖 Par où commencer

**Pour installer le système dans un bar, un seul document suffit :**

### → [GUIDE_INSTALLATION.md](GUIDE_INSTALLATION.md)

Il part d'un PC vierge et va jusqu'au test final, étape par étape, sans rien supposer connu.
Tout le reste ci-dessous est de la documentation de fond — utile pour comprendre, pas nécessaire
pour installer.

| Document | À quoi il sert |
|---|---|
| [GUIDE_INSTALLATION.md](GUIDE_INSTALLATION.md) | **Installer.** Le seul à suivre le jour J. |
| [AUDIT_CAHIER_DES_CHARGES.md](../AUDIT_CAHIER_DES_CHARGES.md) | Ce que le produit fait vraiment, et ce qu'il ne fait pas |
| [EXPLOITATION.md](EXPLOITATION.md) | Sauvegardes, restauration, migrations, purges à planifier |
| [TEST_TERRAIN.md](TEST_TERRAIN.md) | La répétition à faire chez soi avant un vrai bar |
| [INSTANCE_LOCALE.md](INSTANCE_LOCALE.md) | Le détail de la configuration et ses limites connues |
| Ce README | Installation du backend pour développer |

Le point d'arrivée n'est pas un document mais **le test de l'étape 22 du guide** : internet
coupé, le caissier voit le bon de la serveuse et l'encaisse. Tant qu'il n'a pas été fait, le
système n'est pas vérifié — quel que soit le nombre de tests automatisés qui passent.

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
- **QR Code** : rendu côté client (aucun paquet Python dédié)
- **Gestion secrets** : `.env` via `python-decouple`
- **Déploiement recommandé** : Docker, Railway, Heroku, Render...

---

## 📁 Structure du projet

le_parrain-main/
├── users/           # Authentification et rôles
├── orders/          # Commandes, caisse, sessions
├── products/        # Produits, catégories, inventaire
├── organisations/   # Multi-tenancy, journée de travail
├── vouchers/        # Vouchers Wi-Fi
├── console/         # Console éditeur, licences
├── sync/            # Instance locale : remontée, descente, diagnostic
├── le_parrain/      # Configuration Django
├── requirements.txt
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

Voir **[GUIDE_INSTALLATION.md](GUIDE_INSTALLATION.md)** : la procédure complète, d'un PC vierge
jusqu'au test final, pour que serveuses et caissier continuent de travailler ensemble sans
internet.

Voir **[INSTANCE_LOCALE.md](INSTANCE_LOCALE.md)** : le détail de la configuration et ce qu'elle
implique.

Voir **[TEST_TERRAIN.md](TEST_TERRAIN.md)** : comment vérifier que ça marche — une répétition
chez soi d'abord, puis le test au bar. À lire avant d'installer chez un client.

## 🛡️ Exploitation (sauvegardes, restauration, mises à jour)

Voir **[EXPLOITATION.md](EXPLOITATION.md)** : script de sauvegarde automatisé
(`scripts/backup.sh`), procédure de restauration, et points de vigilance en production.
