from rest_framework.authtoken.models import Token


def resolve_user_from_token(request):
    """Resout l'utilisateur depuis l'entete Authorization: Token <cle> - partage entre
    BusinessDayGateMiddleware et console.middleware.LicenceGateMiddleware, qui s'executent
    tous deux AVANT l'authentification DRF (request.user n'est donc pas encore disponible a
    ce stade)."""
    auth = request.META.get('HTTP_AUTHORIZATION', '')
    if not auth.startswith('Token '):
        return None
    key = auth[len('Token '):].strip()
    try:
        return Token.objects.select_related('user').get(key=key).user
    except Token.DoesNotExist:
        return None
