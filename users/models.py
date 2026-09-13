from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
import uuid

from organisations.models import Organisation

DEFAULT_PASSWORD = 'password123'


class UserManager(BaseUserManager):
    def create_user(self, phone, password=None, **extra_fields):
        if not phone:
            raise ValueError('Le num?ro de t?l?phone est requis')

        extra_fields.setdefault('name', phone)
        user = self.model(phone=phone, **extra_fields)

        if password is not None:
            user.set_password(password)
        else:
            user.set_password(DEFAULT_PASSWORD)

        user.save(using=self._db)
        return user

    def create_superuser(self, phone, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', 'superadmin')
        extra_fields.setdefault('name', phone)
        return self.create_user(phone, password=password, **extra_fields)


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
    must_change_password = models.BooleanField(default=False)
    password_reset_expires_at = models.DateTimeField(null=True, blank=True)

    USERNAME_FIELD = 'phone'
    REQUIRED_FIELDS = ['name']

    objects = UserManager()

    class Meta:
        permissions = [
            ('manage_users', "Peut g?rer les utilisateurs"),
            ('manage_user_permissions', "Peut modifier les droits des utilisateurs"),
        ]

    def __str__(self):
        return f"{self.phone} - {self.role}"
