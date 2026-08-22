from django.db import models
from django.utils import timezone
import uuid

class Organisation(models.Model):
    SUBSCRIPTION_CHOICES = [
        ('free', 'Free'),
        ('pro', 'Pro'),
        ('premium', 'Premium'),
    ]

    # Etat de licence gere exclusivement par console.services.licence.ServiceLicence.etat() -
    # champ denormalise/cache pour permettre un filtrage/tri rapide sur l'ecran console
    # "Organisations", jamais ecrit directement par un serializer (voir organisations/serializers.py).
    STATUT_CHOICES = [
        ('en_attente', 'En attente'),
        ('active', 'Active'),
        ('en_grace', 'En grâce'),
        ('bloquee', 'Bloquée'),
        ('suspendue', 'Suspendue'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    address = models.CharField(max_length=255, blank=True, null=True)
    ville = models.CharField(max_length=100, blank=True, null=True)
    phone_contact = models.CharField(max_length=20, blank=True, null=True)
    subscription_plan = models.CharField(
        max_length=20,
        choices=SUBSCRIPTION_CHOICES,
        default='free'
    )
    # Le representant de l'organisation aupres de l'editeur (console systeme) - un seul par
    # organisation, impose au niveau base via OneToOneField. SET_NULL : desactiver ce compte
    # ne doit jamais faire disparaitre l'organisation (jamais de suppression, archivage seul).
    supadmin = models.OneToOneField(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='organisation_dirigee'
    )
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default='en_attente')
    archivee = models.BooleanField(default=False)
    # Anti-recul d'horloge (console.services.licence) : comparee a la date du poste a chaque
    # connexion d'un utilisateur de cette organisation.
    derniere_activite_le = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

class Department(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name='departments')
    name = models.CharField(max_length=100)
    budget = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('organisation', 'name')
        ordering = ['name']

    def __str__(self):
        return self.name

class BusinessDay(models.Model):
    """Journee de travail globale a l'organisation. Tant qu'aucune n'est ouverte (is_open),
    BusinessDayGateMiddleware bloque toute action d'ecriture pour les roles non-admin - seul
    un admin/superadmin peut ouvrir ou fermer. Le fond de caisse de depart est fixe PAR
    CAISSIER (voir CashierDayBalance) plutot que globalement, puisque chaque caissier a son
    propre tiroir-caisse physique. A la fermeture, le solde de fermeture de chaque caissier est
    calcule et fige (voir BusinessDayCloseView) - les compteurs 'du jour' (CaissierDailySummaryView)
    sont scopes sur la session ouverte plutot que sur la date calendaire, donc ils reviennent a 0
    des la fermeture (plus de session en cours) et repartent de zero a la prochaine ouverture."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name='business_days')
    date = models.DateField(default=timezone.now)
    is_open = models.BooleanField(default=False)
    opened_at = models.DateTimeField(null=True, blank=True)
    opened_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='business_days_opened'
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='business_days_closed'
    )

    class Meta:
        # -opened_at (pas -date) : plusieurs journees peuvent partager la meme date calendaire
        # si l'admin ferme et rouvre plusieurs fois le meme jour - seul l'horodatage precis
        # garantit que la plus recente sort en premier (voir BusinessDayHistoryView).
        ordering = ['-opened_at']


class CashierDayBalance(models.Model):
    """Solde de caisse d'un caissier pour une BusinessDay donnee. opening_amount est fixe par
    l'admin a l'ouverture ; closing_amount est calcule automatiquement a la fermeture
    (opening_amount + ventes encaissees - sorties de caisse de CE caissier depuis l'ouverture
    de la session) - voir BusinessDayCloseView. Permet a l'admin de consulter l'historique
    caisse par caisse, jour par jour (BusinessDayHistoryView)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business_day = models.ForeignKey(BusinessDay, on_delete=models.CASCADE, related_name='cashier_balances')
    cashier = models.ForeignKey('users.User', on_delete=models.CASCADE, related_name='day_balances')
    opening_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    closing_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    class Meta:
        unique_together = ('business_day', 'cashier')
