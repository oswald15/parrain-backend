"""Capture des corrections de l'admin, en vue de leur descente vers le bar.

Miroir de sync/upstream.py. Le serveur central est le seul a connaitre ce que l'admin corrige a
distance : une vente annulee, un article retire d'une commande. Tant que ces corrections ne
redescendaient pas, le bar continuait de compter la vente dans son resume de caisse, et le
caissier remettait en fin de service un montant qui ne correspondait a rien.

Rien ne s'active sur l'instance du bar : elle n'a personne a qui faire descendre ses operations.
"""

import json

from django.conf import settings

from organisations.auth_utils import resolve_user_from_token
from .models import PendingDownstreamRequest, SyncInstance

SAFE_METHODS = ('GET', 'HEAD', 'OPTIONS')

# Rejeu en cours : cette requete EST deja une synchronisation, la capturer la renverrait d'ou
# elle vient. C'est le garde-fou anti-boucle, lu des deux cotes (voir upstream.should_capture).
REPLAY_HEADER = 'HTTP_X_SYNC_REPLAY'

# Corrections a faire descendre : ce que l'admin modifie a distance sur des ventes.
#
# Liste blanche, comme pour la remontee. Le referentiel descend deja par son propre canal
# (sync/views.py::ReferentialSyncView) et n'a rien a faire ici.
CAPTURED_PREFIXES = (
    '/api/orders/',
)

EXCLUDED_SUFFIXES = (
    '/invoice-pdf/',
)


def should_capture(request, status_code):
    """Une correction faite dans le cloud, aboutie, sur un etablissement equipe d'une instance."""
    if settings.IS_LOCAL_INSTANCE:
        return False
    if request.method in SAFE_METHODS:
        return False
    if request.META.get(REPLAY_HEADER):
        return False
    # Une operation remontee par un bar : elle vient de la, elle n'a pas a y retourner. Sans ce
    # test, chaque vente ferait un aller-retour et serait appliquee deux fois au bar.
    if request.META.get('HTTP_AUTHORIZATION', '').startswith('Instance '):
        return False
    if not any(request.path.startswith(prefix) for prefix in CAPTURED_PREFIXES):
        return False
    if any(request.path.endswith(suffix) for suffix in EXCLUDED_SUFFIXES):
        return False
    return 200 <= status_code < 300


class DownstreamCaptureMiddleware:
    """Enregistre les corrections de l'admin pour descente ulterieure vers les bars equipes."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Lu avant la vue : DRF consomme le flux, il n'est plus relisible ensuite.
        body = self._read_body(request) if not settings.IS_LOCAL_INSTANCE else None

        response = self.get_response(request)

        try:
            if should_capture(request, response.status_code):
                self._capture(request, body)
        except Exception:
            # Une capture ratee ne doit jamais faire echouer la correction elle-meme : l'admin
            # verrait une erreur sur une action pourtant passee, et la referait.
            pass

        return response

    def _read_body(self, request):
        try:
            raw = request.body
        except Exception:
            return None
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return None

    def _capture(self, request, body):
        user = resolve_user_from_token(request)
        if not user or not getattr(user, 'organisation_id', None):
            return

        # Seuls les etablissements equipes ont quelque chose a recevoir. Les autres travaillent
        # directement sur le serveur central : y empiler des corrections que personne ne viendra
        # chercher ferait grossir la table sans fin.
        if not SyncInstance.objects.filter(
            organisation_id=user.organisation_id, is_active=True
        ).exists():
            return

        PendingDownstreamRequest.objects.create(
            organisation_id=user.organisation_id,
            user=user,
            method=request.method,
            path=request.path,
            query_string=request.META.get('QUERY_STRING', '')[:500],
            body=body,
        )
