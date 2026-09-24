from django.conf import settings
from rest_framework import permissions


class CanOpenBusinessDay(permissions.BasePermission):
    """Ouvrir ou fermer la journee de travail.

    Reserve a l'admin sur le serveur central, comme avant. Mais sur une instance installee dans
    le bar, le caissier en est aussi capable : sinon une coupure d'internet au moment d'ouvrir
    empecherait le bar de travailler de toute la journee, alors que c'est precisement ce que
    l'instance locale doit rendre impossible. L'admin garde la main a distance des que le reseau
    revient, et l'ouverture faite sur place remonte comme les autres operations."""

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.role in ['admin', 'superadmin']:
            return True
        return settings.IS_LOCAL_INSTANCE and request.user.role == 'caissier'


class IsSuperAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.role == 'superadmin'
        )

class IsAdminOrSuperAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.role in ['admin', 'superadmin']
        )