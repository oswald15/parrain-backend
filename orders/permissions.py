from rest_framework import permissions

class IsAdminOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user.role in ['admin', 'superadmin']

class IsAdminOrApprovisionneur(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user.role in ['admin', 'superadmin', 'approvisionneur']

class IsServeur(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user.role in ['serveur']

class IsCaissier(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user.role in ['caissier']

class IsCaissierOrAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user.role in ['caissier', 'admin', 'superadmin']
