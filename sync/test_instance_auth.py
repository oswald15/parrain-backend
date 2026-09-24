import uuid

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from orders.models import ClientTab
from organisations.models import Organisation
from sync.models import SyncInstance
from users.models import User


class SyncInstanceAuthenticationTests(TestCase):
    """Authentification des instances installees dans les bars.

    Une instance pousse les operations de SON etablissement en declarant quel employe les a
    faites. Le controle central est le cloisonnement : le jeton d'un bar ne doit jamais permettre
    d'ecrire dans les donnees d'un autre - ce serait une fuite entre clients, pas une simple
    erreur d'imputation."""

    def setUp(self):
        self.organisation = Organisation.objects.create(name=f'Bar A {uuid.uuid4()}')
        self.serveuse = User.objects.create(
            organisation=self.organisation, role='serveur', name='Serveuse A',
            phone=f'{uuid.uuid4().int % 10**9:09d}',
        )
        self.instance = SyncInstance.objects.create(
            organisation=self.organisation, name='Poste caisse A'
        )

        self.autre_organisation = Organisation.objects.create(name=f'Bar B {uuid.uuid4()}')
        self.serveuse_autre_bar = User.objects.create(
            organisation=self.autre_organisation, role='serveur', name='Serveuse B',
            phone=f'{uuid.uuid4().int % 10**9:09d}',
        )

        self.client = APIClient()

    def _push_tab(self, token, acting_user_id, client_name='Table 4'):
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Instance {token}',
            HTTP_X_ACTING_USER=str(acting_user_id),
        )
        return self.client.post(
            reverse('client-tab-create'), {'client_name': client_name}, format='json'
        )

    def test_une_instance_remonte_une_operation_au_nom_de_son_employe(self):
        response = self._push_tab(self.instance.token, self.serveuse.id)

        self.assertEqual(response.status_code, 201, response.data)
        tab = ClientTab.objects.get()
        self.assertEqual(tab.serveur_id, self.serveuse.id)
        self.assertEqual(tab.organisation_id, self.organisation.id)

    def test_une_instance_ne_peut_pas_ecrire_dans_un_autre_etablissement(self):
        """Le controle qui protege les clients les uns des autres."""
        response = self._push_tab(self.instance.token, self.serveuse_autre_bar.id)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(ClientTab.objects.count(), 0)

    def test_un_jeton_revoque_est_refuse(self):
        self.instance.is_active = False
        self.instance.save()

        response = self._push_tab(self.instance.token, self.serveuse.id)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(ClientTab.objects.count(), 0)

    def test_un_jeton_inconnu_est_refuse(self):
        response = self._push_tab('jeton-invente', self.serveuse.id)

        self.assertEqual(response.status_code, 401)

    def test_l_employe_doit_etre_declare(self):
        """Sans auteur, l'operation serait imputee a un compte technique et disparaitrait des
        statistiques de la serveuse comme de la caisse."""
        self.client.credentials(HTTP_AUTHORIZATION=f'Instance {self.instance.token}')

        response = self.client.post(
            reverse('client-tab-create'), {'client_name': 'Table 4'}, format='json'
        )

        self.assertEqual(response.status_code, 401)

    def test_la_date_de_derniere_remontee_est_tracee(self):
        """Elle permet a l'admin de savoir si les chiffres d'un bar sont a jour."""
        self.assertIsNone(self.instance.last_seen_at)

        self._push_tab(self.instance.token, self.serveuse.id)

        self.instance.refresh_from_db()
        self.assertIsNotNone(self.instance.last_seen_at)

    def test_l_authentification_par_jeton_utilisateur_fonctionne_toujours(self):
        """Non-regression : l'ajout de ce mecanisme ne doit rien changer pour les clients."""
        from django.utils import timezone
        from rest_framework.authtoken.models import Token

        from organisations.models import BusinessDay

        now = timezone.now()
        BusinessDay.objects.create(
            organisation=self.organisation, date=now.date(), is_open=True, opened_at=now,
        )
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Token {Token.objects.create(user=self.serveuse).key}'
        )

        response = self.client.post(
            reverse('client-tab-create'), {'client_name': 'Table 7'}, format='json'
        )

        self.assertEqual(response.status_code, 201)

    def test_une_remontee_passe_meme_si_la_journee_est_fermee_dans_le_cloud(self):
        """Comportement voulu, et facile a casser par inadvertance.

        L'operation a eu lieu au bar alors que sa journee etait ouverte. Le serveur central,
        lui, peut tres bien n'avoir aucune journee ouverte au moment de la remontee - la refuser
        ferait perdre une vente reellement encaissee. BusinessDayGateMiddleware ne reconnait que
        l'entete `Token` et laisse donc passer les remontees, qui portent `Instance`."""
        self.assertFalse(
            self.organisation.business_days.filter(is_open=True).exists()
        )

        response = self._push_tab(self.instance.token, self.serveuse.id)

        self.assertEqual(response.status_code, 201, response.data)
