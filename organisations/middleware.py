from django.http import JsonResponse
from sync.context import is_replay
from .auth_utils import resolve_user_from_token
from .models import BusinessDay

SAFE_METHODS = ('GET', 'HEAD', 'OPTIONS')

# Toujours autorise meme journee fermee : authentification (il faut pouvoir se connecter/
# deconnecter independamment de l'etat de la journee - sinon un admin ne pourrait meme pas se
# reconnecter pour la rouvrir si sa session expire pendant qu'elle est fermee).
EXEMPT_PREFIXES = (
    '/api/auth/login',
    '/api/auth/register',
    '/api/auth/logout',
    # Signalement de consommations servies que rien n'a pu enregistrer (poste du caissier
    # perdu). Ce n'est pas une vente de plus mais la declaration d'une vente qui a deja eu lieu,
    # et elle se fait justement quand le bar ne tourne pas : journee fermee, materiel en panne.
    # La soumettre au garde de journee reviendrait a ne jamais pouvoir la remonter.
    '/api/sync/operations-abandonnees',
)


class BusinessDayGateMiddleware:
    """Bloque toute action d'ecriture (methode non-GET) sur l'API pour les roles non-admin
    tant qu'aucune BusinessDay n'est ouverte pour leur organisation (voir
    organisations/models.py::BusinessDay). Implemente en middleware Django plutot qu'en
    permission DRF ajoutee a chaque vue individuellement : une seule regle centrale, aucun
    risque d'oublier une vue lors de l'ajout de nouvelles fonctionnalites.

    La resolution de l'utilisateur se fait manuellement depuis l'entete Authorization (le
    middleware Django s'execute AVANT l'authentification DRF, request.user n'est donc pas
    encore disponible a ce stade pour une authentification par token)."""

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

        if user.role in ('admin', 'superadmin'):
            return None
        if not user.organisation_id:
            return None

        is_open = BusinessDay.objects.filter(
            organisation_id=user.organisation_id, is_open=True
        ).exists()
        if is_open:
            return None

        # Rejeu d'une action faite hors-ligne : elle s'est produite alors que la journee etait
        # bien ouverte, la refuser maintenant ferait perdre une vente reellement encaissee.
        # C'est l'app qui verifie cette regle au moment de l'action, sur l'etat de journee
        # qu'elle a en cache (decision de cadrage) ; ce gate ne protege que contre le travail
        # en direct hors journee ouverte, pas contre la synchronisation d'un travail passe.
        if is_replay(request):
            return None

        return JsonResponse(
            {'detail': "La journee est fermee. Contactez l'administrateur pour l'ouvrir."},
            status=403,
        )
