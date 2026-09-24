from django.contrib import admin

from .models import IdempotencyRecord


@admin.register(IdempotencyRecord)
class IdempotencyRecordAdmin(admin.ModelAdmin):
    list_display = ('key', 'organisation', 'user', 'method', 'path', 'state', 'response_status', 'created_at')
    list_filter = ('state', 'method', 'organisation')
    search_fields = ('key', 'path')
    readonly_fields = (
        'id', 'organisation', 'user', 'key', 'method', 'path', 'request_fingerprint',
        'state', 'response_status', 'response_body', 'created_at', 'completed_at',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
