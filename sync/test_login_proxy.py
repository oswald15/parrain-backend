import uuid
from unittest.mock import patch

import requests
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from organisations.models import Organisation
from users.models import User
from users.phone import normalize_phone

CLOUD = 'https://cloud.example.test'


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


@override_settings(INSTANCE_ROLE='local', IS_LOCAL_INSTANCE=True, CLOUD_API_URL=CLOUD)
class LoginProxyTests(TestCase):
    """Connexion depuis une instance installee dans un bar.

    Choix assume : la connexion exige internet. Le bar ne detient aucune empreinte de mot de
    passe, c'est le serveur central qui verifie les identifiants. Une equipe deja connectee
    continue en revanche de travailler pendant toute la coupure."""

    def setUp(self):
        self.organisation = Organisation.objects.create(name=f'Org {uuid.uuid4()}')
        self.serveuse = User.objects.create(
            organisation=self.organisation, role='serveur', name='Serveuse',
            phone=normalize_phone('690000001'),
        )
        self.client = APIClient()

    def _login(self):
        return self.client.post(
            reverse('login'), {'phone': '690000001', 'password': 'secret'}, format='json'
        )

    def _cloud_success(self):
        return FakeResponse(200, {
            'token': 'jeton-du-cloud',
            'user': {'id': str(self.serveuse.id), 'name': 'Serveuse', 'role': 'serveur'},
            'licence': {'statut': 'active'},
        })

    def test_la_connexion_est_verifiee_par_le_serveur_central(self):
        with patch('requests.post', return_value=self._cloud_success()) as sent:
            response = self._login()

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(sent.call_args.args[0], f'{CLOUD}/api/auth/login/')

    def test_le_jeton_rendu_est_celui_de_l_instance_locale(self):
        """Les appareils du bar parlent a l'instance locale, y compris une fois internet coupe :
        leur rendre le jeton du cloud les rendrait inutilisables des la premiere coupure."""
        with patch('requests.post', return_value=self._cloud_success()):
            response = self._login()

        local_token = Token.objects.get(user=self.serveuse).key
        self.assertEqual(response.data['token'], local_token)
        self.assertNotEqual(response.data['token'], 'jeton-du-cloud')

    def test_sans_internet_la_connexion_echoue_avec_un_message_clair(self):
        with patch('requests.post', side_effect=requests.ConnectionError('injoignable')):
            response = self._login()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data['code'], 'cloud_unreachable')

    def test_un_refus_du_serveur_central_est_transmis_tel_quel(self):
        """Identifiants errones, licence bloquee, horloge incoherente : la decision appartient
        au serveur central, son message ne doit pas etre reecrit."""
        with patch('requests.post', return_value=FakeResponse(403, {'detail': 'Date du système incohérente.'})):
            response = self._login()

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['detail'], 'Date du système incohérente.')

    def test_un_utilisateur_inconnu_localement_est_signale_clairement(self):
        """Cas de premiere installation : le referentiel n'a pas encore ete descendu."""
        payload = {
            'token': 'jeton-du-cloud',
            'user': {'id': str(uuid.uuid4()), 'name': 'Inconnu', 'role': 'serveur'},
        }
        with patch('requests.post', return_value=FakeResponse(200, payload)):
            response = self._login()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'user_not_synced')


class LoginOnCloudUnchangedTests(TestCase):
    """Non-regression : le serveur central continue d'authentifier localement."""

    @override_settings(INSTANCE_ROLE='cloud', IS_LOCAL_INSTANCE=False)
    def test_le_serveur_central_ne_relaie_pas_la_connexion(self):
        organisation = Organisation.objects.create(name=f'Org {uuid.uuid4()}')
        User.objects.create_user(
            phone=normalize_phone('690000002'), password='motdepasse',
            organisation=organisation, role='serveur', name='Serveuse',
        )

        with patch('requests.post') as sent:
            response = APIClient().post(
                reverse('login'), {'phone': '690000002', 'password': 'motdepasse'}, format='json'
            )

        sent.assert_not_called()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn('token', response.data)
