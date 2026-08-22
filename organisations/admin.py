from django.contrib import admin
from .models import Organisation, Department, BusinessDay, CashierDayBalance


@admin.register(Organisation)
class OrganisationAdmin(admin.ModelAdmin):
    list_display = ('name', 'subscription_plan', 'phone_contact', 'address', 'created_at')
    list_filter = ('subscription_plan',)
    search_fields = ('name', 'phone_contact')


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'organisation', 'budget', 'is_active')
    list_filter = ('organisation', 'is_active')
    search_fields = ('name',)


@admin.register(BusinessDay)
class BusinessDayAdmin(admin.ModelAdmin):
    list_display = ('organisation', 'date', 'is_open', 'opened_at', 'opened_by', 'closed_at', 'closed_by')
    list_filter = ('organisation', 'is_open')
    date_hierarchy = 'date'


@admin.register(CashierDayBalance)
class CashierDayBalanceAdmin(admin.ModelAdmin):
    list_display = ('business_day', 'cashier', 'opening_amount', 'closing_amount')
    list_filter = ('business_day__organisation',)
