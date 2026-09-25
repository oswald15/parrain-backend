import uuid

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from organisations.models import BusinessDay, Organisation
from sync.models import SyncInstance
from users.models import User


class OuvertureDeJourneeParLeCaissierTests(TestCase):
    """Le caissier ouvre la journee sur une instance locale.

    C'est le scenario du matin sans internet : l'admin est a distance, injoignable, et le bar
    doit demarrer. Le piege tient a l'ordre d'execution - le garde de journee est un middleware,
    il s'execute AVANT les permissions des vues. Sans exemption, il refuse l'ouverture parce
    qu'aucune journee n'est ouverte, ce qui est precisement l'etat qu'on cherche a quitter."""

    def setUp(self):
        self.organisation = Organisation.objects.create(name=f'Org {uuid.uuid4()}')
        self.caissier = self._user('caissier', 'Caissier')
        self.serveuse = self._user('serveur', 'Serveuse')

    def _user(self, role, nom):
        return User.objects.create(
            organisation=self.organisation, role=role, name=nom,
            phone=f'{uuid.uuid4().int % 10**9:09d}',
        )

    def _client(self, user):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Token {Token.objects.create(user=user).key}')
        return client

    def _ouvrir(self, user):
        return self._client(user).post(
            reverse('business-day-open'),
            {'opening_amounts': {str(self.caissier.id): 0}},
            format='json',
        )

    @override_settings(INSTANCE_ROLE='local', IS_LOCAL_INSTANCE=True)
    def test_le_caissier_peut_ouvrir_la_journee_au_bar(self):
        reponse = self._ouvrir(self.caissier)

        self.assertEqual(reponse.status_code, 201, getattr(reponse, 'data', reponse.content))
        self.assertTrue(
            BusinessDay.objects.filter(organisation=self.organisation, is_open=True).exists()
        )

    @override_settings(INSTANCE_ROLE='cloud', IS_LOCAL_INSTANCE=False)
    def test_le_caissier_ne_peut_pas_ouvrir_depuis_le_serveur_central(self):
        """Le droit reste reserve a l'admin hors du bar : c'est la vue qui en decide, et elle
        doit continuer a le faire maintenant que le middleware laisse passer."""
        reponse = self._ouvrir(self.caissier)

        self.assertEqual(reponse.status_code, 403)
        self.assertFalse(BusinessDay.objects.filter(is_open=True).exists())

    @override_settings(INSTANCE_ROLE='local', IS_LOCAL_INSTANCE=True)
    def test_une_serveuse_ne_peut_pas_ouvrir_la_journee(self):
        reponse = self._ouvrir(self.serveuse)

        self.assertEqual(reponse.status_code, 403)
        self.assertFalse(BusinessDay.objects.filter(is_open=True).exists())

    @override_settings(INSTANCE_ROLE='local', IS_LOCAL_INSTANCE=True)
    def test_une_vente_reste_refusee_tant_que_la_journee_est_fermee(self):
        """L'exemption ne doit couvrir que le pilotage de la journee. Si elle laissait passer
        les ventes, le garde-fou ne servirait plus a rien."""
        reponse = self._client(self.serveuse).post(
            reverse('client-tab-create'), {'client_name': 'Table 4'}, format='json'
        )

        self.assertEqual(reponse.status_code, 403)
        self.assertIn('journee est fermee', str(reponse.content, 'utf-8', errors='ignore').lower())


class RemonteeDeLOuvertureTests(TestCase):
    """L'ouverture faite au bar remonte vers le serveur central.

    Elle a deja eu lieu : la refuser la-haut ne l'annule pas, cela bloque la file du bar - et
    avec elle toutes les ventes de la journee, qui attendent derriere dans un ordre strict."""

    def setUp(self):
        self.organisation = Organisation.objects.create(name=f'Org {uuid.uuid4()}')
        self.caissier = User.objects.create(
            organisation=self.organisation, role='caissier', name='Caissier',
            phone=f'{uuid.uuid4().int % 10**9:09d}',
        )
        self.instance = SyncInstance.objects.create(
            organisation=self.organisation, name='Poste caisse',
        )

    def _remonter(self, acting):
        client = APIClient()
        client.credentials(
            HTTP_AUTHORIZATION=f'Instance {self.instance.token}',
            HTTP_X_ACTING_USER=str(acting.id),
        )
        return client.post(
            reverse('business-day-open'),
            {'opening_amounts': {str(self.caissier.id): 0}},
            format='json',
        )

    @override_settings(INSTANCE_ROLE='cloud', IS_LOCAL_INSTANCE=False)
    def test_le_serveur_central_accepte_l_ouverture_remontee_par_le_bar(self):
        reponse = self._remonter(self.caissier)

        self.assertEqual(reponse.status_code, 201, getattr(reponse, 'data', reponse.content))
        self.assertTrue(
            BusinessDay.objects.filter(organisation=self.organisation, is_open=True).exists()
        )

    @override_settings(INSTANCE_ROLE='cloud', IS_LOCAL_INSTANCE=False)
    def test_une_serveuse_ne_peut_pas_ouvrir_la_journee_par_ce_chemin(self):
        """L'exemption vaut pour le caissier, pas pour n'importe qui : le jeton d'instance
        permet d'agir au nom de tout employe de l'etablissement."""
        serveuse = User.objects.create(
            organisation=self.organisation, role='serveur', name='Serveuse',
            phone=f'{uuid.uuid4().int % 10**9:09d}',
        )

        reponse = self._remonter(serveuse)

        self.assertEqual(reponse.status_code, 403)
        self.assertFalse(BusinessDay.objects.filter(is_open=True).exists())
