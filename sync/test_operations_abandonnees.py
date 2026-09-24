import uuid

from django.test import TestCase
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from organisations.models import Organisation
from sync.models import OperationAbandonnee
from users.models import User

LISTE = 'operations-abandonnees'


class OperationsAbandonneesTests(TestCase):
    """Consommations servies que rien n'a pu enregistrer.

    Le poste du caissier est mort avec des bons encore dans la tablette d'une serveuse. Ces bons
    ne peuvent etre rejoues nulle part - mais le client a bu. Sans cette remontee, l'archive
    resterait dans un telephone : tablette perdue ou reinstallee, et ces ventes disparaitraient
    sans que personne cote admin n'ait su qu'elles avaient existe."""

    def setUp(self):
        self.organisation = Organisation.objects.create(name=f'Org {uuid.uuid4()}')
        self.serveuse = self._user('serveur', 'Serveuse')
        self.admin = self._user('admin', 'Admin')
        self.autre_org = Organisation.objects.create(name=f'Org {uuid.uuid4()}')

    def _user(self, role, name, organisation=None):
        return User.objects.create(
            organisation=organisation or self.organisation, role=role, name=name,
            phone=f'{uuid.uuid4().int % 10**9:09d}',
        )

    def _client(self, user):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Token {Token.objects.create(user=user).key}')
        return client

    def _payload(self, operation_id=None):
        return {'operations': [{
            'id': str(operation_id or uuid.uuid4()),
            'libelle': 'Onglet Table 7',
            'detail': '2 × Beaufort',
            'montant': '1200.00',
            'client_created_at': '2026-09-22T19:35:00Z',
            'raw': {'items': [{'product': 'x', 'quantity': 2}]},
        }]}

    # --- signalement par la tablette ------------------------------------------

    def test_la_tablette_signale_une_vente_servie_jamais_enregistree(self):
        response = self._client(self.serveuse).post(
            reverse(LISTE), self._payload(), format='json'
        )

        self.assertEqual(response.status_code, 201, response.data)
        operation = OperationAbandonnee.objects.get()
        self.assertEqual(operation.libelle, 'Onglet Table 7')
        self.assertEqual(operation.user, self.serveuse)
        self.assertEqual(operation.organisation, self.organisation)
        self.assertEqual(operation.raw['items'][0]['quantity'], 2)

    def test_un_signalement_repete_ne_cree_pas_de_doublon(self):
        """La tablette reessaie tant qu'elle n'a pas de reponse : sans idempotence, la meme
        consommation serait reclamee plusieurs fois au client."""
        operation_id = uuid.uuid4()
        client = self._client(self.serveuse)

        client.post(reverse(LISTE), self._payload(operation_id), format='json')
        client.post(reverse(LISTE), self._payload(operation_id), format='json')

        self.assertEqual(OperationAbandonnee.objects.count(), 1)

    def test_le_montant_absent_est_accepte(self):
        """La tablette n'avait pas le catalogue en cache. Un montant approxime sur une
        consommation servie serait pire qu'un montant absent."""
        payload = self._payload()
        payload['operations'][0]['montant'] = None

        response = self._client(self.serveuse).post(reverse(LISTE), payload, format='json')

        self.assertEqual(response.status_code, 201, response.data)
        self.assertIsNone(OperationAbandonnee.objects.get().montant)

    def test_un_corps_mal_forme_est_refuse_sans_rien_enregistrer(self):
        response = self._client(self.serveuse).post(
            reverse(LISTE), {'operations': 'pas une liste'}, format='json'
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(OperationAbandonnee.objects.exists())

    def test_un_anonyme_ne_peut_rien_signaler(self):
        response = APIClient().post(reverse(LISTE), self._payload(), format='json')

        self.assertIn(response.status_code, (401, 403))
        self.assertFalse(OperationAbandonnee.objects.exists())

    # --- lecture ---------------------------------------------------------------

    def _existante(self, user=None, organisation=None):
        return OperationAbandonnee.objects.create(
            id=uuid.uuid4(), organisation=organisation or self.organisation,
            user=user, libelle='Onglet Table 7', detail='2 × Beaufort',
        )

    def test_l_admin_voit_toutes_celles_de_son_etablissement(self):
        self._existante(user=self.serveuse)

        response = self._client(self.admin).get(reverse(LISTE))

        self.assertEqual(len(response.data['operations']), 1)
        self.assertEqual(response.data['operations'][0]['serveuse'], 'Serveuse')

    def test_un_autre_etablissement_ne_voit_rien(self):
        """Ces lignes nomment des clients et des montants : elles ne doivent jamais fuir."""
        self._existante(organisation=self.autre_org)

        response = self._client(self.admin).get(reverse(LISTE))

        self.assertEqual(response.data['operations'], [])

    def test_la_serveuse_ne_voit_que_les_siennes(self):
        collegue = self._user('serveur', 'Collegue')
        self._existante(user=self.serveuse)
        self._existante(user=collegue)

        response = self._client(self.serveuse).get(reverse(LISTE))

        self.assertEqual(len(response.data['operations']), 1)

    # --- traitement -------------------------------------------------------------

    def test_marquer_traitee_ne_supprime_pas_la_ligne(self):
        """Le principe du systeme : ce qui n'est plus utile est archive, jamais supprime. Cette
        ligne reste la seule trace d'un ecart entre ce qui a ete bu et ce qui a ete
        comptabilise."""
        operation = self._existante(user=self.serveuse)

        response = self._client(self.admin).post(
            reverse('operation-abandonnee-traiter', args=[operation.pk])
        )

        self.assertEqual(response.status_code, 200, response.data)
        operation.refresh_from_db()
        self.assertIsNotNone(operation.traitee_le)
        self.assertEqual(operation.traitee_par, self.admin)
        self.assertTrue(OperationAbandonnee.objects.filter(pk=operation.pk).exists())

    def test_une_serveuse_ne_peut_pas_marquer_traitee(self):
        """C'est l'admin qui ressaisit dans le serveur central : lui seul sait que c'est fait."""
        operation = self._existante(user=self.serveuse)

        response = self._client(self.serveuse).post(
            reverse('operation-abandonnee-traiter', args=[operation.pk])
        )

        self.assertEqual(response.status_code, 403)
        operation.refresh_from_db()
        self.assertIsNone(operation.traitee_le)

    def test_on_ne_peut_pas_traiter_la_ligne_d_un_autre_etablissement(self):
        operation = self._existante(organisation=self.autre_org)

        response = self._client(self.admin).post(
            reverse('operation-abandonnee-traiter', args=[operation.pk])
        )

        self.assertEqual(response.status_code, 404)
