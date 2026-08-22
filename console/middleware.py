from django.http import JsonResponse

from organisations.auth_utils import resolve_user_from_token

from .services.licence import ServiceLicence

SAFE_METHODS = ('GET', 'HEAD', 'OPTIONS')

# Toujours autorise, meme organisation bloquee/suspendue : authentification, la console
# elle-meme (jamais gatee par cette regle metier - voir console.authentication), et les 2
# ecrans supadmin exemptes par le document (Abonnement + saisie de code).
EXEMPT_PREFIXES = (
    '/api/auth/login',
    '/api/auth/register',
    '/api/auth/logout',
    '/api/console/',
    '/api/organisations/abonnement/',
    '/api/organisations/activer-code/',
)

# "Bloque" = nouvelles operations refusees ; cloturer un travail deja engage reste permis
# (voir CONSOLE-SYSTEME.md section 5 : un bar qui expire un samedi 22h ne doit pas perdre sa
# caisse). Enumeration explicite plutot qu'un prefixe large, pour ne jamais laisser passer une
# creation par accident (ex: /client-tabs/create/ doit rester bloque).
ALLOWED_PATH_SUFFIXES_WHILE_BLOQUEE = (
    '/business-day/close/',
    '/invoice/',
    '/invoice-pdf/',
    '/encaisser/',
    '/validate/',
    '/cancel/',
)


class LicenceGateMiddleware:
    """Point de controle unique du blocage par licence (CONSOLE-SYSTEME.md section 5) - aucune
    vue ne doit reimplementer cette regle. Contrairement a BusinessDayGateMiddleware, ne fait
    AUCUNE exception par role : une organisation bloquee/suspendue bloque tout le monde, y
    compris son propre supadmin, pour toute nouvelle operation - seuls les 2 ecrans exemptes
    ci-dessus restent joignables.

    Enregistre AVANT BusinessDayGateMiddleware (voir settings.MIDDLEWARE) : une organisation
    bloquee n'a pas a etre informee que 'la journee n'est pas ouverte', le message de blocage
    licence doit primer."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        block_response = self._check(request)
        if block_response:
            return block_response
        return self.get_response(request)

    def _check(self, request):
        if request.method in SAFE_METHODS:
            return None
        if not request.path.startswith('/api/'):
            return None
        if any(request.path.startswith(p) for p in EXEMPT_PREFIXES):
            return None

        user = resolve_user_from_token(request)
        if not user or not user.is_authenticated:
            return None  # laisse DRF renvoyer le 401 approprie
        if not user.organisation_id:
            return None

        etat = ServiceLicence.etat(user.organisation)
        if etat['statut'] not in ('bloquee', 'suspendue'):
            return None
        if any(request.path.endswith(s) for s in ALLOWED_PATH_SUFFIXES_WHILE_BLOQUEE):
            return None

        return JsonResponse(
            {'detail': etat['message'] or "Organisation bloquée."},
            status=403,
        )
