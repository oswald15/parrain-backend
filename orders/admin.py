from django.contrib import admin
from .models import (
    ClientTab, Order, OrderItem, CashExpense, Transaction,
    Consignment, Bon, BonItem,
)


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0


@admin.register(ClientTab)
class ClientTabAdmin(admin.ModelAdmin):
    list_display = ('client_name', 'organisation', 'serveur', 'status', 'total_amount', 'created_at')
    list_filter = ('organisation', 'status')
    search_fields = ('client_name',)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'organisation', 'department', 'serveur', 'cashier', 'status', 'total_amount', 'created_at')
    list_filter = ('organisation', 'department', 'status')
    inlines = [OrderItemInline]


@admin.register(CashExpense)
class CashExpenseAdmin(admin.ModelAdmin):
    list_display = ('label', 'organisation', 'cashier', 'amount', 'expense_type', 'created_at', 'is_deleted')
    list_filter = ('organisation', 'is_deleted')


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('transaction_type', 'organisation', 'department', 'product', 'quantity', 'amount', 'author', 'created_at')
    list_filter = ('organisation', 'transaction_type', 'department')


@admin.register(Consignment)
class ConsignmentAdmin(admin.ModelAdmin):
    list_display = ('product', 'organisation', 'client_name', 'quantity', 'status', 'created_at')
    list_filter = ('organisation', 'status')


class BonItemInline(admin.TabularInline):
    model = BonItem
    extra = 0


@admin.register(Bon)
class BonAdmin(admin.ModelAdmin):
    list_display = ('id', 'organisation', 'client_tab', 'department', 'status', 'total_amount', 'created_at')
    list_filter = ('organisation', 'department', 'status')
    inlines = [BonItemInline]
