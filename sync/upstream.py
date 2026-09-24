"""Capture des operations du bar, en vue de leur remontee vers le serveur central.

Une instance installee dans le bar est la seule a connaitre ce qui s'y passe pendant une coupure
d'internet. Chaque ecriture qu'elle traite est donc enregistree telle quelle, pour etre rejouee
plus tard vers le cloud (voir sync/models.py::PendingUpstreamRequest).

Rien de tout cela ne s'active sur le serveur central : la capture serait sans objet, et
dupliquerait chaque operation dans une table qui ne serait jamais videe.
"""

import json

from django.conf import settings

from organisations.auth_utils import resolve_user_from_token
from .models import PendingUpstreamRequest

SAFE_METHODS = ('GET', 'HEAD', 'OPTIONS')

# Operations a remonter : ce que le bar produit et que le cloud ignore.
#
# Liste blanche, comme partout ailleurs dans ce chantier. Une action ajoutee plus tard ne doit
# pas se retrouver remontee sans qu'on l'ait decide - a plus forte raison une action de
# referentiel, qui descend du cloud et ne doit surtout pas y remonter en sens inverse.
CAPTURED_PREFIXES = (
    '/api/orders/',
    '/api/organisations/business-day/',
)

# Jamais capture, meme sous les prefixes ci-dessus.
EXCLUDED_SUFFIXES = (
    # Genere un PDF a la volee, ne modifie rien.
    '/invoice-pdf/',
)


def should_capture(request, status_code):
    """Une ecriture metier du bar, effectivement aboutie."""
    if not settings.IS_LOCAL_INSTANCE:
        return False
    if request.method in SAFE_METHODS:
        return False
    # Correction descendue du serveur central, en cours d'application ici : la capturer la
    # renverrait d'ou elle vient, et le cloud l'appliquerait une seconde fois.
    if request.META.get('HTTP_X_SYNC_REPLAY'):
        return False
    if not any(request.path.startswith(prefix) for prefix in CAPTURED_PREFIXES):
        return False
    if any(request.path.endswith(suffix) for suffix in EXCLUDED_SUFFIXES):
        return False
    # Seules les actions reellement passees sont remontees : rejouer dans le cloud une requete
    # qui a echoue au bar y produirait la meme erreur, en encombrant la file pour rien.
    return 200 <= status_code < 300


class UpstreamCaptureMiddleware:
    """Enregistre les ecritures du bar pour remontee ulterieure.

    Place APRES les gardes metier (licence, journee de travail) dans settings.MIDDLEWARE : une
    requete qu'ils refusent n'arrive jamais ici, et n'a donc pas a etre remontee.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Le corps doit etre lu AVANT la vue : une fois le flux consomme par DRF, il n'est plus
        # relisible. Django le met en cache des le premier acces, la vue le retrouvera donc.
        body = self._read_body(request) if settings.IS_LOCAL_INSTANCE else None

        response = self.get_response(request)

        try:
            if should_capture(request, response.status_code):
                self._capture(request, body)
        except Exception:
            # La capture ne doit jamais faire echouer une vente deja encaissee. Une operation
            # perdue ici se rattrapera par une resynchronisation manuelle ; une caisse qui
            # tombe en plein service, non.
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

        PendingUpstreamRequest.objects.create(
            organisation_id=user.organisation_id,
            user=user,
            method=request.method,
            path=request.path,
            query_string=request.META.get('QUERY_STRING', '')[:500],
            body=body,
            idempotency_key=request.META.get('HTTP_IDEMPOTENCY_KEY', '')[:255],
            client_created_at=request.META.get('HTTP_X_CLIENT_CREATED_AT', '')[:64],
            cashier_session=request.META.get('HTTP_X_CASHIER_SESSION', '')[:64],
        )
