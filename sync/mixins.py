import hashlib
import json

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.utils.encoders import JSONEncoder

from .models import IdempotencyRecord

IDEMPOTENCY_HEADER = 'HTTP_IDEMPOTENCY_KEY'
UNSAFE_METHODS = ('POST', 'PUT', 'PATCH', 'DELETE')

# Statuts que l'on ne memorise JAMAIS : ils ne decrivent pas l'issue de l'action mais une
# condition passagere. Memoriser un 401 sur un token expire condamnerait definitivement une
# vente pourtant valide, alors qu'il suffit de rafraichir le token et de rejouer la meme cle.
NON_MEMOIZED_STATUSES = (401, 403, 408, 429)


def compute_fingerprint(request):
    """Empreinte stable du corps de la requete, pour detecter une meme cle reutilisee sur une
    action differente. Le tri des cles JSON evite qu'un changement d'ordre de serialisation
    cote client fasse echouer un rejeu pourtant legitime."""
    try:
        payload = json.dumps(getattr(request, 'data', None), sort_keys=True, cls=JSONEncoder)
    except (TypeError, ValueError):
        payload = str(getattr(request, 'data', None))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def _jsonify(data):
    """Normalise le corps d'une reponse DRF en JSON pur : il contient des types (UUID, Decimal,
    datetime) que le JSONField ne sait pas serialiser tels quels.

    On passe par l'encodeur de DRF, pas celui de Django : ce dernier tronque les microsecondes
    des dates, si bien que la reponse rejouee ne serait pas rigoureusement identique a
    l'originale."""
    if data is None:
        return None
    return json.loads(json.dumps(data, cls=JSONEncoder))


class _IdempotentReplay(Exception):
    """Interrompt le flux DRF avant l'execution de la vue, pour renvoyer la reponse memorisee.

    Passer par une exception n'est pas cosmetique : c'est le seul moyen d'empecher reellement
    le handler de s'executer. Se contenter de remplacer la reponse a la fin laisserait la vente
    se rejouer (et donc se dupliquer) avant d'etre masquee par la reponse d'origine."""

    def __init__(self, response):
        self.response = response
        super().__init__('Rejeu idempotent')


class IdempotencyMixin:
    """Rend une vue rejouable sans effet de bord, pour le mode hors-ligne.

    A placer A GAUCHE des classes de base DRF (ex: `class MaVue(IdempotencyMixin, APIView)`).
    Le traitement a lieu apres `initial()` (authentification et permissions deja jouees), donc
    `request.user` et son organisation sont disponibles - contrairement a un middleware Django,
    qui tourne avant l'authentification DRF et devrait re-parser l'entete Authorization a la
    main (voir organisations/middleware.py).

    Sans entete `Idempotency-Key`, la vue se comporte exactement comme avant : aucune
    regression possible sur les appels en ligne existants (web et mobile actuels).

    Deroule, pour une requete portant une cle :
      1. `dispatch` ouvre une transaction englobant TOUT : prise de cle, execution de la vue et
         memorisation de la reponse. Il ne peut donc jamais exister d'etat ou la vente est
         enregistree mais la cle absente - c'est exactement cet etat qui ferait dupliquer
         l'action au rejeu suivant.
      2. La prise de cle est un INSERT protege par la contrainte d'unicite (organisation, key),
         isole dans un savepoint : sous PostgreSQL une erreur d'integrite invalide la
         transaction courante, le savepoint la contient. Cet INSERT sert aussi de verrou : une
         requete concurrente portant la meme cle attend la fin de la premiere, puis relit sa
         reponse au lieu de rejouer l'action.
      3. Si la cle est deja connue, on leve `_IdempotentReplay` : la vue ne s'execute pas et on
         renvoie la reponse d'origine, code HTTP compris.

    Les reponses 2xx et 4xx deterministes sont memorisees : une action deja faite doit renvoyer
    son resultat d'origine, pas une erreur d'etat trompeuse du type "cet onglet n'est plus
    ouvert". Les 5xx et les statuts passagers (voir NON_MEMOIZED_STATUSES) liberent la cle pour
    que le rejeu retente reellement l'action."""

    def dispatch(self, request, *args, **kwargs):
        if request.method not in UNSAFE_METHODS or not request.META.get(IDEMPOTENCY_HEADER):
            return super().dispatch(request, *args, **kwargs)
        with transaction.atomic():
            return super().dispatch(request, *args, **kwargs)

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        self._idempotency_record = None

        if request.method not in UNSAFE_METHODS:
            return

        key = request.META.get(IDEMPOTENCY_HEADER)
        organisation_id = getattr(request.user, 'organisation_id', None)
        if not key or not organisation_id:
            return

        fingerprint = compute_fingerprint(request)

        try:
            # Savepoint : sans lui, l'erreur d'unicite invaliderait la transaction ouverte par
            # dispatch et toute requete ulterieure echouerait.
            with transaction.atomic():
                self._idempotency_record = IdempotencyRecord.objects.create(
                    organisation_id=organisation_id,
                    user=request.user,
                    key=key,
                    method=request.method,
                    path=request.path,
                    request_fingerprint=fingerprint,
                )
        except IntegrityError:
            existing = IdempotencyRecord.objects.filter(
                organisation_id=organisation_id, key=key
            ).first()
            if existing is None:
                # Course improbable (trace purgee entre l'INSERT et la relecture) : on laisse la
                # vue s'executer normalement plutot que de bloquer l'utilisateur.
                return
            raise _IdempotentReplay(self._replay_response(existing, fingerprint))

    def _replay_response(self, existing, fingerprint):
        if existing.request_fingerprint != fingerprint:
            return Response(
                {
                    'detail': "Cette cle d'idempotence a deja ete utilisee pour une autre action.",
                    'code': 'idempotency_key_reuse',
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if existing.state == IdempotencyRecord.STATE_COMPLETED:
            return Response(existing.response_body, status=existing.response_status)
        return Response(
            {
                'detail': 'Cette action est en cours de traitement, reessayez dans un instant.',
                'code': 'idempotency_in_progress',
            },
            status=status.HTTP_409_CONFLICT,
        )

    def handle_exception(self, exc):
        if isinstance(exc, _IdempotentReplay):
            # Court-circuit : ni permission ni validation a rejouer, la reponse est deja connue.
            return exc.response
        return super().handle_exception(exc)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)

        record = getattr(self, '_idempotency_record', None)
        if record is None:
            return response

        if response.status_code >= 500 or response.status_code in NON_MEMOIZED_STATUSES:
            IdempotencyRecord.objects.filter(pk=record.pk).delete()
            return response

        IdempotencyRecord.objects.filter(pk=record.pk).update(
            state=IdempotencyRecord.STATE_COMPLETED,
            response_status=response.status_code,
            response_body=_jsonify(response.data),
            completed_at=timezone.now(),
        )
        return response
