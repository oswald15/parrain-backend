# 🍷 Le Parrain – Wi-Fi Voucher Backend

**Le Parrain** est une application **SaaS** de gestion pour bars/snacks permettant :

- de suivre les consommations clients,
- d’automatiser la génération de **vouchers Wi-Fi** (QR code) valables 15 minutes,
- de gérer le personnel (serveurs, barmans, admin),
- et d’analyser les performances commerciales.

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

- **Langage** : Python 3.11+
- **Framework** : Django 5 + Django REST Framework
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

git clone https://github.com/Essimbi/le-parrain-backend.git
cd le-parrain-backend

#### 2. Créer un environnement virtuel

python -m venv env
source env/bin/activate        # Linux/macOS
# ou
.\env\Scripts\activate         # Windows
