from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed

from .models import EditeurToken


class EditeurTokenAuthentication(TokenAuthentication):
    """Miroir de rest_framework.authentication.TokenAuthentication, mais interroge
    EditeurToken/Editeur plutot que le Token/AUTH_USER_MODEL global - garantit qu'un token
    users.User ne peut jamais authentifier une requete console, et inversement (decision D1)."""
    keyword = 'Token'
    model = EditeurToken

    def authenticate_credentials(self, key):
        try:
            token = EditeurToken.objects.select_related('editeur').get(key=key)
        except EditeurToken.DoesNotExist:
            raise AuthenticationFailed("Token invalide.")
        if not token.editeur.is_active:
            raise AuthenticationFailed("Compte éditeur désactivé.")
        return (token.editeur, token)
