import uuid
from io import StringIO
from unittest.mock import patch

import requests
from django.core.management import call_command
from django.test import TestCase, override_settings

from organisations.models import Organisation
from sync.models import PendingUpstreamRequest
from users.models import User

CLOUD = 'https://cloud.example.test/api'


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


@override_settings(INSTANCE_ROLE='local', IS_LOCAL_INSTANCE=True,
                   CLOUD_API_URL=CLOUD, INSTANCE_TOKEN='jeton-instance')
class PushUpstreamTests(TestCase):
    """Remontee des operations du bar vers le serveur central.

    C'est le moment ou le travail fait hors-ligne devient visible pour l'admin et entre dans la
    comptabilite. Deux exigences priment : ne jamais dupliquer une vente, et ne jamais en perdre
    une en silence."""

    def setUp(self):
        self.organisation = Organisation.objects.create(name=f'Org {uuid.uuid4()}')
        self.serveuse = User.objects.create(
            organisation=self.organisation, role='serveur', name='Serveuse',
            phone=f'{uuid.uuid4().int % 10**9:09d}',
        )

    def _queue(self, path='/api/orders/client-tabs/create/', **extra):
        return PendingUpstreamRequest.objects.create(
            organisation=self.organisation,
            user=self.serveuse,
            method='POST',
            path=path,
            body={'client_name': 'Table 4'},
            idempotency_key=extra.pop('idempotency_key', 'cle-abc'),
            client_created_at='2026-09-21T14:00:00Z',
            cashier_session='session-42',
            **extra,
        )

    def test_une_operation_remontee_quitte_la_file(self):
        self._queue()

        with patch('requests.request', return_value=FakeResponse(201)):
            call_command('push_upstream')

        self.assertEqual(PendingUpstreamRequest.objects.count(), 0)

    def test_le_contexte_metier_est_rejoue_tel_quel(self):
        """La cle d'idempotence evite de dupliquer la vente ; la session de caisse et
        l'horodatage d'origine l'imputent a la bonne caisse, meme fermee depuis."""
        self._queue()

        with patch('requests.request', return_value=FakeResponse(201)) as sent:
            call_command('push_upstream')

        headers = sent.call_args.kwargs['headers']
        self.assertEqual(headers['Idempotency-Key'], 'cle-abc')
        self.assertEqual(headers['X-Cashier-Session'], 'session-42')
        self.assertEqual(headers['X-Client-Created-At'], '2026-09-21T14:00:00Z')
        self.assertEqual(headers['Authorization'], 'Instance jeton-instance')
        self.assertEqual(headers['X-Acting-User'], str(self.serveuse.id))
        self.assertEqual(sent.call_args.args[1], f'{CLOUD}/api/orders/client-tabs/create/')

    def test_les_operations_partent_dans_l_ordre(self):
        """Une commande doit exister dans le cloud avant les articles qu'on y ajoute."""
        self._queue(path='/api/orders/client-tabs/create/')
        self._queue(path='/api/orders/client-tabs/abc/items/')

        with patch('requests.request', return_value=FakeResponse(201)) as sent:
            call_command('push_upstream')

        paths = [call.args[1] for call in sent.call_args_list]
        self.assertEqual(paths, [
            f'{CLOUD}/api/orders/client-tabs/create/',
            f'{CLOUD}/api/orders/client-tabs/abc/items/',
        ])

    def test_une_coupure_reseau_arrete_la_remontee_sans_rien_consommer(self):
        self._queue()
        self._queue(path='/api/orders/client-tabs/abc/items/')

        with patch('requests.request', side_effect=requests.ConnectionError('injoignable')) as sent:
            call_command('push_upstream')

        # Une seule tentative : passer a la suivante casserait l'ordre.
        self.assertEqual(sent.call_count, 1)
        self.assertEqual(
            PendingUpstreamRequest.objects.filter(
                status=PendingUpstreamRequest.STATUS_PENDING
            ).count(),
            2,
        )

    def test_un_conflit_part_en_quarantaine_sans_bloquer_les_suivantes(self):
        conflit = self._queue()
        suivante = self._queue(path='/api/orders/client-tabs/abc/items/')

        responses = [
            FakeResponse(409, {'detail': 'Cet onglet a deja ete encaisse.'}),
            FakeResponse(201),
        ]
        with patch('requests.request', side_effect=responses):
            call_command('push_upstream')

        conflit.refresh_from_db()
        self.assertEqual(conflit.status, PendingUpstreamRequest.STATUS_QUARANTINED)
        self.assertIn('deja ete encaisse', conflit.last_error)
        # La suivante a bien ete transmise : un conflit ne doit pas geler tout le bar.
        self.assertFalse(PendingUpstreamRequest.objects.filter(pk=suivante.pk).exists())

    def test_un_jeton_refuse_arrete_tout_sans_rien_perdre(self):
        """Jeton d'instance revoque : insister echouerait pareil, et mettre les operations en
        quarantaine ferait perdre des ventes pour un simple probleme de configuration."""
        entry = self._queue()

        with patch('requests.request', return_value=FakeResponse(401, {'detail': 'Instance inconnue.'})):
            call_command('push_upstream')

        entry.refresh_from_db()
        self.assertEqual(entry.status, PendingUpstreamRequest.STATUS_PENDING)
        self.assertEqual(entry.attempts, 1)

    def test_une_panne_du_serveur_central_est_reessayee_plus_tard(self):
        entry = self._queue()

        with patch('requests.request', return_value=FakeResponse(503)):
            call_command('push_upstream')

        entry.refresh_from_db()
        self.assertEqual(entry.status, PendingUpstreamRequest.STATUS_PENDING)

    @override_settings(INSTANCE_ROLE='cloud', IS_LOCAL_INSTANCE=False)
    def test_le_serveur_central_ne_remonte_rien(self):
        self._queue()

        with patch('requests.request') as sent:
            call_command('push_upstream')

        sent.assert_not_called()


@override_settings(INSTANCE_ROLE='local', IS_LOCAL_INSTANCE=True,
                   CLOUD_API_URL=CLOUD, INSTANCE_TOKEN='jeton-instance')
class RefusDePermissionTests(TestCase):
    """Un refus portant sur UNE operation ne doit pas bloquer les suivantes.

    Le cas reel : le caissier ouvre la journee au bar - il en a le droit la-bas - et cette
    ouverture remonte vers un serveur central qui, lui, la reserve a l'admin. Confondre ce refus
    avec un jeton revoque gelait la file entiere, et toutes les ventes de la journee restaient
    bloquees derriere, indefiniment."""

    def setUp(self):
        self.organisation = Organisation.objects.create(name=f'Org {uuid.uuid4()}')
        self.user = User.objects.create(
            organisation=self.organisation, role='caissier', name='Caissier',
            phone=f'{uuid.uuid4().int % 10**9:09d}',
        )

    def _queue(self, path):
        return PendingUpstreamRequest.objects.create(
            organisation=self.organisation, user=self.user, method='POST', path=path, body={},
        )

    def test_un_refus_de_permission_est_ecarte_et_la_file_continue(self):
        refusee = self._queue('/api/organisations/business-day/open/')
        suivante = self._queue('/api/orders/client-tabs/create/')

        reponses = [FakeResponse(403, {'detail': 'You do not have permission.'}),
                    FakeResponse(201, {})]
        with patch('requests.request', side_effect=reponses):
            call_command('push_upstream', stdout=StringIO())

        refusee.refresh_from_db()
        self.assertEqual(refusee.status, PendingUpstreamRequest.STATUS_QUARANTINED)
        # La vente qui suivait est bien partie : c'est tout l'enjeu.
        self.assertFalse(PendingUpstreamRequest.objects.filter(pk=suivante.pk).exists())

    def test_un_jeton_revoque_arrete_tout_sans_rien_consommer(self):
        """Distinction inverse : la, toutes les operations echoueraient pareil. Les mettre en
        quarantaine les perdrait toutes pour une panne d'authentification reparable."""
        premiere = self._queue('/api/orders/client-tabs/create/')
        seconde = self._queue('/api/orders/client-tabs/create/')

        with patch('requests.request', return_value=FakeResponse(401, {'detail': 'Instance inconnue.'})):
            call_command('push_upstream', stdout=StringIO())

        premiere.refresh_from_db()
        seconde.refresh_from_db()
        self.assertEqual(premiere.status, PendingUpstreamRequest.STATUS_PENDING)
        self.assertEqual(seconde.status, PendingUpstreamRequest.STATUS_PENDING)
