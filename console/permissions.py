from rest_framework.permissions import BasePermission

from .models import Editeur


class IsEditeur(BasePermission):
    """A n'utiliser qu'avec EditeurTokenAuthentication (voir views_base.EditeurAPIView) -
    request.user est alors une instance Editeur, jamais users.User."""
    def has_permission(self, request, view):
        return bool(request.user and isinstance(request.user, Editeur) and request.user.is_active)
