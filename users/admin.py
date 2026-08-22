from django.contrib import admin
from .models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('phone', 'name', 'role', 'organisation', 'is_active', 'is_staff', 'is_superuser')
    list_filter = ('role', 'organisation', 'is_active')
    search_fields = ('phone', 'name')
    filter_horizontal = ('departments', 'groups', 'user_permissions')
    readonly_fields = ('password', 'last_login', 'created_at')
    fieldsets = (
        (None, {'fields': ('phone', 'password', 'name', 'role')}),
        ('Organisation', {'fields': ('organisation', 'departments', 'assigned_cashier', 'can_transfer_stock', 'available_budget')}),
        ('Droits', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Dates', {'fields': ('created_at', 'last_login')}),
    )
