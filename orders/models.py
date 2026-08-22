from django.db import models
import uuid
from organisations.models import Organisation
from users.models import User
from products.models import Product

class ClientTab(models.Model):
    STATUS_CHOICES = [
        ('ouvert', 'Ouvert'), ('facture', 'Facture'), ('encaisse', 'Encaisse'), ('annule', 'Annule')
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE)
    serveur = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='client_tabs',
        limit_choices_to={'role': 'serveur'}
    )
    client_name = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ouvert')
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    invoiced_at = models.DateTimeField(blank=True, null=True)
    closed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['-created_at']

class Order(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE)
    serveur = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, limit_choices_to={'role': 'serveur'})
    client_tab = models.ForeignKey(
        ClientTab, on_delete=models.SET_NULL, blank=True, null=True, related_name='orders'
    )
    cashier = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='cashed_orders',
        limit_choices_to={'role': 'caissier'}
    )
    client_name = models.CharField(max_length=100, blank=True, null=True)
    department = models.ForeignKey(
        'organisations.Department',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='orders'
    )
    number_of_customers = models.IntegerField()
    status = models.CharField(max_length=20, choices=[
        ('ouverte', 'Ouverte'), ('servie', 'Servie'), ('fermee', 'Fermée'), ('annulee', 'Annulée')
    ], default='ouverte')
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    payment_type = models.CharField(max_length=20, choices=[('cash', 'Cash'), ('mobile_money', 'Mobile Money')], blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(blank=True, null=True)
    cancelled_at = models.DateTimeField(blank=True, null=True)
    cancelled_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, blank=True, null=True, related_name='cancelled_orders'
    )
    cancel_reason = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        permissions = [
            ('view_global_revenue', "Peut voir le chiffre d'affaires global"),
            ('close_any_order', "Peut clôturer n'importe quelle commande, hors rattachement"),
        ]

class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.IntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    is_removed = models.BooleanField(default=False)
    removed_at = models.DateTimeField(blank=True, null=True)
    removed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, blank=True, null=True, related_name='removed_order_items'
    )

class CashExpense(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE)
    cashier = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='cash_expenses')
    expense_type = models.CharField(max_length=100)
    motif = models.CharField(max_length=255)
    label = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(blank=True, null=True)
    deleted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, blank=True, null=True, related_name='deleted_cash_expenses'
    )

    class Meta:
        ordering = ['-created_at']

class Transaction(models.Model):
    TRANSACTION_CHOICES = [
        ('achat', 'Achat'),
        ('approvisionnement', 'Approvisionnement'),
        ('avoir', 'Avoir'),
        ('consignation', 'Consignation'),
        ('deconsignation', 'Deconsignation'),
        ('facturation', 'Facturation'),
        ('annulation_facture', 'Retour annulation de facture'),
        ('sortie_vente', 'Sortie vente'),
        ('transfert', 'Transfert'),
        ('sortie_caisse', 'Sortie de caisse'),
        ('avaries', 'Avaries'),
        ('octroi_budget', 'Octroi de budget approvisionneur'),
        ('fond_caisse', 'Fond de caisse (ouverture de journee)'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE)
    department = models.ForeignKey('organisations.Department', on_delete=models.SET_NULL, blank=True, null=True)
    destination_department = models.ForeignKey(
        'organisations.Department',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='destination_transactions'
    )
    transaction_type = models.CharField(max_length=40, choices=TRANSACTION_CHOICES)
    number = models.CharField(max_length=80, blank=True)
    payment_type = models.CharField(max_length=20, blank=True, null=True)
    quantity = models.IntegerField(default=0)
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    waitress_code = models.CharField(max_length=50, blank=True)
    serveur = models.ForeignKey(User, on_delete=models.SET_NULL, blank=True, null=True, related_name='sales_transactions')
    client = models.CharField(max_length=100, blank=True, null=True)
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, blank=True, null=True, related_name='transactions')
    expense = models.ForeignKey(CashExpense, on_delete=models.SET_NULL, blank=True, null=True, related_name='transactions')
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, blank=True, null=True, related_name='transactions')
    author = models.ForeignKey(User, on_delete=models.SET_NULL, blank=True, null=True, related_name='authored_transactions')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

class Consignment(models.Model):
    STATUS_CHOICES = [('sortie', 'Sortie'), ('rendue', 'Rendue')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE)
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, blank=True, null=True, related_name='consignments')
    department = models.ForeignKey('organisations.Department', on_delete=models.SET_NULL, blank=True, null=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    client_name = models.CharField(max_length=100, blank=True, null=True)
    quantity = models.PositiveIntegerField()
    unit_deposit_amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='sortie')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='consignments_created'
    )
    returned_at = models.DateTimeField(blank=True, null=True)
    returned_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='consignments_returned'
    )

    class Meta:
        ordering = ['-created_at']

class Bon(models.Model):
    """Un lot de produits ajoute en un seul appel a un departement d'un ClientTab
    (Bon de sortie physiquement imprime cote mobile). Reste immuable une fois
    cree - source de verite de l'historique ; l'annulation le marque 'annule'
    et reverse son effet sur Order/OrderItem plutot que de le supprimer."""
    STATUS_CHOICES = [('actif', 'Actif'), ('valide', 'Valide'), ('annule', 'Annule')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE)
    client_tab = models.ForeignKey(ClientTab, on_delete=models.CASCADE, related_name='bons')
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='bons')
    department = models.ForeignKey('organisations.Department', on_delete=models.SET_NULL, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='actif')
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='bons_created')
    validated_at = models.DateTimeField(blank=True, null=True)
    validated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='bons_validated'
    )
    cancelled_at = models.DateTimeField(blank=True, null=True)
    cancelled_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='bons_cancelled'
    )

    class Meta:
        ordering = ['-created_at']

class BonItem(models.Model):
    bon = models.ForeignKey(Bon, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
