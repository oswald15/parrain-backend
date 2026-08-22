from rest_framework import permissions

class IsAdminOrApprovisionneur(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user.role in ['admin', 'superadmin', 'approvisionneur']

class IsAdminOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user.role == 'admin'

class IsAdminOrSuperAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user.role in ['admin', 'superadmin']
