from rest_framework import permissions


class HasManageUsersRight(permissions.BasePermission):
    def has_permission(self, request, view):
        u = request.user
        return bool(
            u and u.is_authenticated and (
                u.role in ['admin', 'superadmin'] or u.has_perm('users.manage_users')
            )
        )


class HasManageUserPermissionsRight(permissions.BasePermission):
    def has_permission(self, request, view):
        u = request.user
        return bool(
            u and u.is_authenticated and (
                u.role in ['admin', 'superadmin'] or u.has_perm('users.manage_user_permissions')
            )
        )
