from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone
import uuid
from organisations.models import Organisation

class UserManager(BaseUserManager):
    def create_user(self, phone, password=None, **extra_fields):
        if not phone:
            raise ValueError('Le numéro de téléphone est requis')
        user = self.model(phone=phone, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, phone, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', 'superadmin')
        return self.create_user(phone, password, **extra_fields)

class User(AbstractBaseUser, PermissionsMixin):
    ROLE_CHOICES = [
        ('superadmin', 'Super Admin'),
        ('admin', 'Admin'),
        ('approvisionneur', 'Approvisionneur'),
        ('caissier', 'Caissier'),
        ('serveur', 'Serveur')
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organisation = models.ForeignKey(Organisation, on_delete=models.SET_NULL, null=True, blank=True)
    departments = models.ManyToManyField('organisations.Department', blank=True, related_name='users')
    can_transfer_stock = models.BooleanField(default=False)
    # Solde courant d'un approvisionneur : augmente quand l'admin valide une BudgetRequest
    # (products/models.py), diminue a chaque reception de stock (StockReceptionView) - il ne
    # peut pas approvisionner au-dela de ce solde. Non pertinent pour les autres roles.
    available_budget = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    assigned_cashier = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_serveurs',
        limit_choices_to={'role': 'caissier'}
    )
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20, unique=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_login = models.DateTimeField(blank=True, null=True)

    USERNAME_FIELD = 'phone'
    REQUIRED_FIELDS = ['name']

    objects = UserManager()

    class Meta:
        permissions = [
            ('manage_users', "Peut gérer les utilisateurs"),
            ('manage_user_permissions', "Peut modifier les droits des utilisateurs"),
        ]

    def __str__(self):
        return f"{self.phone} - {self.role}"
