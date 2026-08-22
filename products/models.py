from django.db import models
import uuid
from organisations.models import Organisation, Department

class Category(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name

class Product(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True)
    code = models.CharField(max_length=50, blank=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    image_url = models.TextField(blank=True, null=True)
    stock_quantity = models.IntegerField(default=0)
    min_threshold = models.PositiveIntegerField(default=5, help_text="Seuil d'alerte de stock")
    unit = models.CharField(max_length=20, default="pièce")
    is_active = models.BooleanField(default=True)
    is_consignable = models.BooleanField(default=False)
    deposit_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def is_below_threshold(self):
        return self.stock_quantity < self.min_threshold

    @property
    def margin(self):
        return self.price - self.purchase_price

    @property
    def margin_percent(self):
        if not self.purchase_price:
            return 0
        return (self.margin / self.purchase_price) * 100

    def __str__(self):
        return self.name

class StockRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'En attente'),
        ('approved', 'Approuvé'),
        ('rejected', 'Rejeté')
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='stock_requests')
    requested_quantity = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    requested_by = models.CharField(max_length=100)

    def __str__(self):
        return f"Demande de {self.requested_quantity} x {self.product.name}"

    class Meta:
        ordering = ['-created_at']

class BudgetRequest(models.Model):
    """Demande de budget d'approvisionnement : l'approvisionneur demande un montant pour
    pouvoir approvisionner un departement. Des que l'admin valide, il precise le montant
    REELLEMENT accorde (validated_amount, peut differer du montant demande) - ce montant
    s'ajoute au solde disponible de l'approvisionneur (User.available_budget), qui est ensuite
    decremente automatiquement a chaque reception de stock (voir StockReceptionView) tant
    qu'il reste suffisant."""
    STATUS_CHOICES = [('en_attente', 'En attente'), ('validee', 'Validee'), ('refusee', 'Refusee')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE)
    approvisionneur = models.ForeignKey('users.User', on_delete=models.CASCADE, related_name='budget_requests')
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True)
    requested_amount = models.DecimalField(max_digits=12, decimal_places=2)
    note = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='en_attente')
    created_at = models.DateTimeField(auto_now_add=True)
    validated_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='budget_requests_reviewed'
    )

    class Meta:
        ordering = ['-created_at']


class DepartmentStock(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE)
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name='stock_items')
    family = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='stock_items'
    )
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='department_stocks')
    quantity = models.IntegerField(default=0)
    weighted_average_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    sale_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    min_threshold = models.PositiveIntegerField(default=5)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('department', 'product')
        ordering = ['department__name', 'product__name']

    @property
    def margin(self):
        return self.sale_price - self.weighted_average_cost

    @property
    def margin_percent(self):
        if not self.weighted_average_cost:
            return 0
        return (self.margin / self.weighted_average_cost) * 100

class StockMovement(models.Model):
    MOVEMENT_CHOICES = [
        ('approvisionnement', 'Approvisionnement'),
        ('transfert', 'Transfert'),
        ('sortie_vente', 'Sortie vente'),
        ('ajustement', 'Ajustement'),
        ('avarie', 'Avarie'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE)
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name='stock_movements')
    family = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='stock_movements'
    )
    destination_department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='incoming_stock_movements'
    )
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    movement_type = models.CharField(max_length=30, choices=MOVEMENT_CHOICES)
    quantity = models.IntegerField()
    unit_purchase_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    unit_sale_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    author = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True)
    note = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

class PurchaseOrder(models.Model):
    STATUS_CHOICES = [
        ('pending', 'En attente'),
        ('received', 'Receptionnee'),
        ('cancelled', 'Annulee'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    supplier_name = models.CharField(max_length=150, blank=True)
    quantity = models.PositiveIntegerField()
    estimated_unit_cost = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    note = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    author = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True)

    class Meta:
        ordering = ['-created_at']

class Avarie(models.Model):
    REASON_CHOICES = [
        ('casse', 'Casse'),
        ('perime', 'Perime'),
        ('deteriore', 'Deteriore'),
        ('autre', 'Autre'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE)
    department = models.ForeignKey(Department, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    reason = models.CharField(max_length=20, choices=REASON_CHOICES, default='autre')
    note = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    author = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True)

    class Meta:
        ordering = ['-created_at']
