from io import StringIO
from unittest.mock import patch

import requests
from django.core.management import call_command
from django.test import TestCase, override_settings

CLOUD = 'https://cloud.example.test'


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


class SetupLocalInstanceTests(TestCase):
    """Mise en service sur le poste d'un bar.

    Elle a lieu chez un client, souvent sans acces aux journaux : chaque refus doit dire ce qui
    manque et quoi faire, pas seulement echouer."""

    def _run(self):
        out, err = StringIO(), StringIO()
        call_command('setup_local_instance', stdout=out, stderr=err)
        return out.getvalue(), err.getvalue()

    @override_settings(INSTANCE_ROLE='cloud', IS_LOCAL_INSTANCE=False)
    def test_refuse_sur_le_serveur_central(self):
        _, err = self._run()

        self.assertIn('INSTANCE_ROLE', err)

    @override_settings(INSTANCE_ROLE='local', IS_LOCAL_INSTANCE=True,
                       CLOUD_API_URL='', INSTANCE_TOKEN='')
    def test_signale_l_adresse_manquante(self):
        _, err = self._run()

        self.assertIn('CLOUD_API_URL', err)

    @override_settings(INSTANCE_ROLE='local', IS_LOCAL_INSTANCE=True,
                       CLOUD_API_URL=CLOUD, INSTANCE_TOKEN='')
    def test_signale_le_jeton_manquant(self):
        _, err = self._run()

        self.assertIn('INSTANCE_TOKEN', err)
        self.assertIn('console', err)

    @override_settings(INSTANCE_ROLE='local', IS_LOCAL_INSTANCE=True,
                       CLOUD_API_URL=CLOUD, INSTANCE_TOKEN='jeton')
    def test_signale_un_serveur_injoignable(self):
        with patch('requests.get', side_effect=requests.ConnectionError('injoignable')):
            _, err = self._run()

        self.assertIn('injoignable', err)

    @override_settings(INSTANCE_ROLE='local', IS_LOCAL_INSTANCE=True,
                       CLOUD_API_URL=CLOUD, INSTANCE_TOKEN='mauvais-jeton')
    def test_signale_un_jeton_refuse(self):
        with patch('requests.get', return_value=FakeResponse(401)):
            _, err = self._run()

        self.assertIn('Jeton refuse', err)
        self.assertIn('revoquee', err)

    @override_settings(INSTANCE_ROLE='local', IS_LOCAL_INSTANCE=True,
                       CLOUD_API_URL=CLOUD, INSTANCE_TOKEN='jeton')
    def test_descend_le_referentiel_quand_tout_est_bon(self):
        payload = {
            'organisation': {'id': '00000000-0000-0000-0000-000000000001',
                             'name': 'Bar du Coin', 'statut': 'active'},
            'departments': [], 'categories': [], 'products': [],
            'department_stocks': [], 'users': [], 'formules': [], 'abonnements': [],
        }
        with patch('requests.get', return_value=FakeResponse(200, payload)):
            out, err = self._run()

        self.assertEqual(err, '')
        self.assertIn('Bar du Coin', out)
        self.assertIn('Instance prete', out)


@override_settings(INSTANCE_ROLE='local', IS_LOCAL_INSTANCE=True,
                   CLOUD_API_URL=CLOUD, INSTANCE_TOKEN='jeton')
class RunSyncTests(TestCase):
    """Boucle de synchronisation continue."""

    def test_la_remontee_passe_avant_la_descente(self):
        """L'ordre n'est pas cosmetique : le referentiel ne rapporte les quantites de stock que
        si plus rien n'attend d'etre remonte. Descendre d'abord ferait manquer cette condition a
        chaque tour, et les quantites ne convergeraient jamais."""
        calls = []
        with patch(
            'sync.management.commands.run_sync.call_command',
            side_effect=lambda name, *a, **k: calls.append(name),
        ):
            call_command('run_sync', '--once', '--pull-every', '1')

        self.assertEqual(calls, ['push_upstream', 'pull_operations', 'pull_referential'])

    def test_une_panne_de_synchronisation_n_arrete_pas_la_boucle(self):
        """C'est exactement quand le reseau va mal que la boucle doit persister."""
        with patch(
            'sync.management.commands.run_sync.call_command',
            side_effect=RuntimeError('serveur injoignable'),
        ):
            err = StringIO()
            call_command('run_sync', '--once', stderr=err)

        self.assertIn('echec ignore', err.getvalue())

    @override_settings(INSTANCE_ROLE='cloud', IS_LOCAL_INSTANCE=False)
    def test_refuse_de_tourner_sur_le_serveur_central(self):
        err = StringIO()
        call_command('run_sync', '--once', stderr=err)

        self.assertIn('instance locale', err.getvalue())


class CloudUrlTests(TestCase):
    """Adresse du serveur central dans le .env.

    Deux conventions opposees cohabitent : les appareils visent une base qui SE TERMINE par
    `/api`, le poste veut la racine. Copier le lien tel qu'on le connait donne
    `.../api/api/orders/...` et tout echoue en 404, sans que rien ne designe la cause."""

    @override_settings(INSTANCE_ROLE='local', IS_LOCAL_INSTANCE=True,
                       CLOUD_API_URL=CLOUD + '/api', INSTANCE_TOKEN='jeton')
    def test_l_adresse_copiee_avec_api_est_refusee_avant_tout_appel(self):
        out, err = StringIO(), StringIO()
        with patch('requests.get') as fetch:
            call_command('setup_local_instance', stdout=out, stderr=err)

        self.assertIn("/api", err.getvalue())
        self.assertIn(CLOUD, err.getvalue())
        # Refusee AVANT le reseau : sinon le message serait "jeton refuse" ou "HTTP 404",
        # qui envoient chercher le probleme ailleurs.
        fetch.assert_not_called()

    @override_settings(INSTANCE_ROLE='local', IS_LOCAL_INSTANCE=True,
                       CLOUD_API_URL=CLOUD + '/api/', INSTANCE_TOKEN='jeton')
    def test_la_barre_finale_ne_masque_pas_l_erreur(self):
        err = StringIO()
        call_command('setup_local_instance', stdout=StringIO(), stderr=err)

        self.assertIn("'/api'", err.getvalue())

    @override_settings(INSTANCE_ROLE='local', IS_LOCAL_INSTANCE=True,
                       CLOUD_API_URL='cave-backend.bunker-store.store', INSTANCE_TOKEN='jeton')
    def test_une_adresse_sans_protocole_est_refusee(self):
        err = StringIO()
        call_command('setup_local_instance', stdout=StringIO(), stderr=err)

        self.assertIn('https://', err.getvalue())

    @override_settings(INSTANCE_ROLE='local', IS_LOCAL_INSTANCE=True,
                       CLOUD_API_URL=CLOUD, INSTANCE_TOKEN='jeton')
    def test_l_adresse_correcte_passe(self):
        payload = {
            'organisation': {'id': '00000000-0000-0000-0000-000000000001',
                             'name': 'Bar du Coin', 'statut': 'active'},
            'departments': [], 'categories': [], 'products': [],
            'department_stocks': [], 'users': [], 'formules': [], 'abonnements': [],
        }
        out, err = StringIO(), StringIO()
        with patch('requests.get', return_value=FakeResponse(200, payload)):
            call_command('setup_local_instance', stdout=out, stderr=err)

        self.assertEqual(err.getvalue(), '')
