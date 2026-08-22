from django.contrib import admin
from .models import WifiVoucher


@admin.register(WifiVoucher)
class WifiVoucherAdmin(admin.ModelAdmin):
    list_display = ('code', 'organisation', 'order', 'expires_at', 'created_at')
    list_filter = ('organisation',)
    search_fields = ('code',)
