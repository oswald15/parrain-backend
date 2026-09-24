import uuid
from io import StringIO
from unittest.mock import patch

import requests
from django.core.management import call_command
from django.test import TestCase, override_settings

from organisations.models import Organisation
from sync.models import SyncInstance
from users.models import User

CLOUD = 'https://cloud.example.test'
LOCAL = 'http://127.0.0.1:8000'


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


@override_settings(INSTANCE_ROLE='local', IS_LOCAL_INSTANCE=True,
                   CLOUD_API_URL=CLOUD, INSTANCE_TOKEN='jeton-instance',
                   LOCAL_API_URL=LOCAL)
class PullOperationsTests(TestCase):
    """Descente des corrections de l'admin vers le bar.

    Une vente annulee dans le cloud doit disparaitre du resume de caisse du poste, sans quoi le
    caissier remet en fin de service un montant qui ne correspond a rien."""

    def setUp(self):
        self.organisation = Organisation.objects.create(name=f'Org {uuid.uuid4()}')
        self.admin = User.objects.create(
            organisation=self.organisation, role='admin', name='Admin',
            phone=f'{uuid.uuid4().int % 10**9:09d}',
        )
        self.instance = SyncInstance.objects.create(
            organisation=self.organisation, name='Instance locale', token='jeton-instance',
        )

    def _operation(self, pk, path='/api/orders/abc/cancel/'):
        return {
            'id': pk, 'method': 'POST', 'path': path, 'query_string': '',
            'body': None, 'acting_user_id': str(self.admin.id),
        }

    def _run(self, operations, local_status=200, local_side_effect=None):
        out, err = StringIO(), StringIO()
        replays = []

        def replay(method, url, **kwargs):
            replays.append((method, url, kwargs.get('headers', {})))
            if local_side_effect:
                raise local_side_effect
            status = local_status(len(replays)) if callable(local_status) else local_status
            return FakeResponse(status, {'detail': 'refus'})

        with patch('requests.get', return_value=FakeResponse(200, {'operations': operations})), \
                patch('requests.request', side_effect=replay):
            call_command('pull_operations', stdout=out, stderr=err)

        self.instance.refresh_from_db()
        return out.getvalue(), err.getvalue(), replays

    def test_une_correction_est_rejouee_contre_l_api_locale(self):
        """Rejouee, et non ecrite en base : l'annulation doit produire ici exactement ce qu'elle
        produit ailleurs - stock rendu, ecritures au journal, bonne session de caisse."""
        _, err, replays = self._run([self._operation(7)])

        self.assertEqual(err, '')
        method, url, headers = replays[0]
        self.assertEqual(method, 'POST')
        self.assertEqual(url, f'{LOCAL}/api/orders/abc/cancel/')
        self.assertEqual(headers['X-Acting-User'], str(self.admin.id))
        self.assertEqual(self.instance.last_downstream_id, 7)

    def test_le_rejeu_est_marque_pour_ne_pas_repartir_vers_le_cloud(self):
        """Sans cette marque, la correction serait capturee comme une operation du bar et le
        cloud l'appliquerait une seconde fois."""
        _, _, replays = self._run([self._operation(7)])

        self.assertEqual(replays[0][2]['X-Sync-Replay'], '1')

    def test_l_instance_injoignable_ne_fait_pas_avancer_le_curseur(self):
        """Le curseur vaut accuse de reception : l'avancer sur une correction non appliquee la
        perdrait definitivement."""
        _, err, _ = self._run(
            [self._operation(7)],
            local_side_effect=requests.ConnectionError('injoignable'),
        )

        self.assertIn('injoignable', err)
        self.assertEqual(self.instance.last_downstream_id, 0)

    def test_l_ordre_est_preserve_en_cas_de_panne(self):
        """Une suppression d'article ne peut pas preceder l'annulation de la commande qui la
        porte : on s'arrete a la premiere qui ne passe pas."""
        _, _, replays = self._run(
            [self._operation(7), self._operation(8)],
            local_side_effect=requests.ConnectionError('injoignable'),
        )

        self.assertEqual(len(replays), 1)

    def test_une_correction_refusee_est_signalee_sans_bloquer_les_suivantes(self):
        """Typiquement une vente deja annulee sur place. L'ecart est reel et quelqu'un doit
        pouvoir le retrouver - mais il ne doit pas bloquer toute la descente derriere lui."""
        _, err, replays = self._run(
            [self._operation(7), self._operation(8)],
            local_status=lambda attempt: 400 if attempt == 1 else 200,
        )

        self.assertIn('refusee', err)
        self.assertEqual(len(replays), 2)
        self.assertEqual(self.instance.last_downstream_id, 8)

    def test_une_panne_de_l_instance_arrete_la_passe(self):
        """HTTP 500 : le poste repond mal, pas l'operation qui est mauvaise. On retentera."""
        _, _, replays = self._run(
            [self._operation(7), self._operation(8)], local_status=500,
        )

        self.assertEqual(len(replays), 1)
        self.assertEqual(self.instance.last_downstream_id, 0)

    def test_le_curseur_est_envoye_au_serveur_central(self):
        self.instance.last_downstream_id = 12
        self.instance.save(update_fields=['last_downstream_id'])

        with patch('requests.get', return_value=FakeResponse(200, {'operations': []})) as fetch:
            call_command('pull_operations', stdout=StringIO(), stderr=StringIO())

        self.assertEqual(fetch.call_args.kwargs['params'], {'after': 12})

    @override_settings(INSTANCE_ROLE='cloud', IS_LOCAL_INSTANCE=False)
    def test_refuse_de_tourner_sur_le_serveur_central(self):
        err = StringIO()
        call_command('pull_operations', stderr=err)

        self.assertIn('instance locale', err.getvalue())
