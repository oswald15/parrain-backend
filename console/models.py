import binascii
import os
import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.db import models
from django.utils import timezone


class EditeurManager(BaseUserManager):
    def create_editeur(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("L'email est requis")
        editeur = self.model(email=self.normalize_email(email), **extra_fields)
        editeur.set_password(password)
        editeur.save(using=self._db)
        return editeur


class Editeur(AbstractBaseUser):
    """Acteur de la console systeme, separe de users.User (voir CONSOLE-SYSTEME.md, decision
    D1) : un editeur gere plusieurs organisations clientes, alors que tout utilisateur de l'app
    metier (admin/superadmin/...) est scope a une seule organisation. Pas de PermissionsMixin -
    tous les editeurs sont egaux pour l'instant (decision mineure, voir plan)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nom = models.CharField(max_length=100)
    email = models.CharField(max_length=255, unique=True)
    is_active = models.BooleanField(default=True)
    cree_le = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['nom']

    objects = EditeurManager()

    def __str__(self):
        return self.email


def generer_cle_token():
    return binascii.hexlify(os.urandom(20)).decode()


class EditeurToken(models.Model):
    """Miroir de rest_framework.authtoken.Token, mais rattache a Editeur plutot qu'a
    AUTH_USER_MODEL (Token.user est fige sur settings.AUTH_USER_MODEL - la separation D1
    impose donc son propre modele de token, verifie par console.authentication.EditeurTokenAuthentication)."""
    key = models.CharField(max_length=40, primary_key=True)
    editeur = models.OneToOneField(Editeur, on_delete=models.CASCADE, related_name='auth_token')
    created = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.key:
            self.key = generer_cle_token()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.key


class Formule(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    libelle = models.CharField(max_length=100)
    duree_jours = models.PositiveIntegerField()
    montant_xaf = models.PositiveIntegerField()  # le XAF n'a pas de sous-unite, un entier suffit
    active = models.BooleanField(default=True)  # jamais supprimee (referencee par l'historique des Abonnement)

    def __str__(self):
        return f"{self.libelle} ({self.duree_jours}j, {self.montant_xaf} XAF)"


class CodeActivation(models.Model):
    STATUT_CHOICES = [
        ('actif', 'Actif'),
        ('utilise', 'Utilisé'),
        ('expire', 'Expiré'),
        ('revoque', 'Révoqué'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organisation = models.ForeignKey(
        'organisations.Organisation', on_delete=models.CASCADE, related_name='codes_activation'
    )
    # PROTECT, jamais supprimee : garde la tracabilite meme si le tarif de la formule change
    # ensuite - duree_jours ci-dessous est copie/fige au moment de l'emission, independamment
    # d'une eventuelle modification ulterieure de Formule.duree_jours.
    formule = models.ForeignKey(Formule, on_delete=models.PROTECT, related_name='codes_activation')
    # Le code en clair n'est JAMAIS stocke - seule son empreinte (SHA-256 hex) l'est.
    empreinte = models.CharField(max_length=64, unique=True, db_index=True)
    numero_serie = models.CharField(max_length=40, unique=True, db_index=True)
    duree_jours = models.PositiveIntegerField()
    # default=timezone.now (pas auto_now_add) : le service de licence doit connaitre cette
    # valeur AVANT l'enregistrement pour la signer (Ed25519) - auto_now_add l'aurait ecrasee
    # silencieusement a l'insertion, rendant la signature invalide des la creation.
    emis_le = models.DateTimeField(default=timezone.now)
    emis_par = models.ForeignKey(
        Editeur, on_delete=models.SET_NULL, null=True, blank=True, related_name='codes_emis'
    )
    expire_le = models.DateTimeField()  # emis_le + 30 jours (non-usage), calcule a l'emission
    utilise_le = models.DateTimeField(null=True, blank=True)
    # Signature Ed25519 (base64) du payload {organisation_id, duree_jours, emis_le, numero_serie},
    # reverifiee a la consommation - defense en profondeur (console/services/licence.py).
    signature = models.CharField(max_length=200, blank=True)
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default='actif')

    def __str__(self):
        return f"{self.numero_serie} - {self.organisation.name}"


class Abonnement(models.Model):
    STATUT_CHOICES = [
        ('en_cours', 'En cours'),
        ('expire', 'Expiré'),
        ('remplace', 'Remplacé'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organisation = models.ForeignKey(
        'organisations.Organisation', on_delete=models.CASCADE, related_name='abonnements'
    )
    # PROTECT : ne jamais perdre l'historique tarifaire d'un abonnement passe.
    formule = models.ForeignKey(Formule, on_delete=models.PROTECT, related_name='abonnements')
    date_debut = models.DateTimeField()
    date_expiration = models.DateTimeField()
    montant_xaf = models.PositiveIntegerField()  # fige au moment de l'ouverture, meme si Formule change ensuite
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default='en_cours')
    ouvert_par_code = models.ForeignKey(
        CodeActivation, on_delete=models.SET_NULL, null=True, blank=True, related_name='abonnements_ouverts'
    )
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date_expiration']

    def __str__(self):
        return f"{self.organisation.name} - {self.formule.libelle} - {self.statut}"


class Paiement(models.Model):
    OPERATEUR_CHOICES = [
        ('mobile_money', 'Mobile Money'),
        ('orange_money', 'Orange Money'),
        ('especes', 'Espèces'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organisation = models.ForeignKey(
        'organisations.Organisation', on_delete=models.CASCADE, related_name='paiements'
    )
    montant_xaf = models.PositiveIntegerField()
    operateur = models.CharField(max_length=20, choices=OPERATEUR_CHOICES)
    reference = models.CharField(max_length=100, blank=True)  # vide pour espèces
    recu_le = models.DateTimeField()
    saisi_par = models.ForeignKey(
        Editeur, on_delete=models.SET_NULL, null=True, blank=True, related_name='paiements_saisis'
    )
    note = models.TextField(blank=True)

    class Meta:
        ordering = ['-recu_le']

    def __str__(self):
        return f"{self.organisation.name} - {self.montant_xaf} XAF - {self.operateur}"


class Journal(models.Model):
    """Piste d'audit - lecture seule par construction : aucune vue update/delete n'existe pour
    ce modele (voir console/views.py), c'est ca qui garantit 'jamais modifiable depuis
    l'interface', pas une simple permission qu'on pourrait contourner."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    acteur = models.ForeignKey(
        Editeur, on_delete=models.SET_NULL, null=True, blank=True, related_name='actions'
    )
    action = models.CharField(max_length=50)
    organisation = models.ForeignKey(
        'organisations.Organisation', on_delete=models.SET_NULL, null=True, blank=True, related_name='journal'
    )
    details = models.JSONField(default=dict, blank=True)
    fait_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fait_le']

    def __str__(self):
        return f"{self.fait_le} - {self.action}"
