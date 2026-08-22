from django.contrib import admin
from .models import (
    Category, Product, StockRequest, BudgetRequest,
    DepartmentStock, StockMovement, PurchaseOrder, Avarie,
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'organisation')
    list_filter = ('organisation',)
    search_fields = ('name',)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'organisation', 'category', 'price', 'purchase_price', 'stock_quantity', 'is_active', 'is_consignable')
    list_filter = ('organisation', 'category', 'is_active', 'is_consignable')
    search_fields = ('name', 'code')


@admin.register(StockRequest)
class StockRequestAdmin(admin.ModelAdmin):
    list_display = ('product', 'organisation', 'requested_quantity', 'status', 'requested_by', 'created_at')
    list_filter = ('organisation', 'status')


@admin.register(BudgetRequest)
class BudgetRequestAdmin(admin.ModelAdmin):
    list_display = ('approvisionneur', 'organisation', 'department', 'requested_amount', 'validated_amount', 'status', 'created_at')
    list_filter = ('organisation', 'status', 'department')


@admin.register(DepartmentStock)
class DepartmentStockAdmin(admin.ModelAdmin):
    list_display = ('product', 'department', 'organisation', 'quantity', 'sale_price', 'weighted_average_cost')
    list_filter = ('organisation', 'department')
    search_fields = ('product__name',)


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ('product', 'department', 'movement_type', 'quantity', 'author', 'created_at')
    list_filter = ('organisation', 'department', 'movement_type')


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ('product', 'organisation', 'supplier_name', 'quantity', 'estimated_unit_cost', 'status', 'created_at')
    list_filter = ('organisation', 'status')


@admin.register(Avarie)
class AvarieAdmin(admin.ModelAdmin):
    list_display = ('product', 'department', 'quantity', 'reason', 'author', 'created_at')
    list_filter = ('organisation', 'department', 'reason')
