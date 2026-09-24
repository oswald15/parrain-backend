import uuid

from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from orders.models import Order, OrderItem
from organisations.models import Department, Organisation
from products.models import DepartmentStock, Product
from sync.downstream import should_capture
from sync.models import PendingDownstreamRequest, SyncInstance
from users.models import User


class DownstreamBase(TestCase):
    def setUp(self):
        self.organisation = Organisation.objects.create(name=f'Org {uuid.uuid4()}')
        self.admin = User.objects.create(
            organisation=self.organisation, role='admin', name='Admin',
            phone=f'{uuid.uuid4().int % 10**9:09d}',
        )
        self.department = Department.objects.create(
            organisation=self.organisation, name='Bar'
        )
        self.product = Product.objects.create(
            organisation=self.organisation, name='Castel', price=1000,
            purchase_price=600, stock_quantity=50,
        )
        DepartmentStock.objects.create(
            organisation=self.organisation, department=self.department, product=self.product,
            quantity=50, weighted_average_cost=600, sale_price=1000,
        )
        self.order = Order.objects.create(
            organisation=self.organisation, department=self.department,
            status='fermee', number_of_customers=1, total_amount=2000,
        )
        OrderItem.objects.create(
            order=self.order, product=self.product, quantity=2, unit_price=1000,
        )
        self.client = APIClient()
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Token {Token.objects.create(user=self.admin).key}'
        )

    def _instance(self, organisation=None):
        return SyncInstance.objects.create(
            organisation=organisation or self.organisation, name='Poste caisse',
            pending_operations=0, last_seen_at=timezone.now(),
        )

    def _cancel(self):
        return self.client.post(reverse('order-cancel', args=[self.order.id]))


class DownstreamCaptureTests(DownstreamBase):
    """Capture des corrections de l'admin, pour qu'elles redescendent vers le bar.

    Sans elle, une vente annulee depuis le serveur central continue d'exister au bar : le resume
    de caisse du poste la compte toujours, et le caissier remet en fin de service un montant qui
    ne correspond a rien."""

    def test_une_annulation_faite_dans_le_cloud_est_capturee(self):
        self._instance()

        response = self._cancel()

        self.assertEqual(response.status_code, 200, response.data)
        operation = PendingDownstreamRequest.objects.get(organisation=self.organisation)
        self.assertEqual(operation.method, 'POST')
        self.assertIn(str(self.order.id), operation.path)
        self.assertEqual(operation.user_id, self.admin.id)

    def test_rien_n_est_capture_pour_un_etablissement_sans_instance(self):
        """Ces bars travaillent directement sur le serveur central : empiler des corrections que
        personne ne viendra chercher ferait grossir la table sans fin."""
        response = self._cancel()

        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(PendingDownstreamRequest.objects.exists())

    def test_une_operation_remontee_par_le_bar_ne_redescend_pas(self):
        """Le piege de ce mecanisme : sans protection, chaque vente du bar ferait un aller-retour
        et serait appliquee une seconde fois sur place - stock decremente deux fois.

        Bout en bout. La decision elle-meme est couverte par ShouldCaptureTests, qui est le test
        qui mord : ici, deux mecanismes independants empechent la boucle, et retirer le garde
        explicite ne ferait pas echouer ce test."""
        instance = self._instance()

        pushing = APIClient()
        pushing.credentials(
            HTTP_AUTHORIZATION=f'Instance {instance.token}',
            HTTP_X_ACTING_USER=str(self.admin.id),
        )
        response = pushing.post(reverse('order-cancel', args=[self.order.id]))

        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(PendingDownstreamRequest.objects.exists())

    def test_une_lecture_n_est_pas_capturee(self):
        self._instance()

        self.client.get(reverse('order-list'))

        self.assertFalse(PendingDownstreamRequest.objects.exists())


class ShouldCaptureTests(TestCase):
    """La decision de capturer, prise isolement.

    Les deux garde-fous anti-boucle vivent ici. Ils ne sont pas couverts par un test bout en bout
    credible : la resolution de l'auteur ignore deja les requetes d'instance, si bien qu'une
    boucle ne se declare pas en integration - mais ce n'est pas sur ce hasard que la protection
    doit reposer."""

    def setUp(self):
        self.factory = RequestFactory()

    def _post(self, **headers):
        return self.factory.post('/api/orders/x/cancel/', **headers)

    def test_capture_une_correction_ordinaire(self):
        self.assertTrue(should_capture(self._post(), 200))

    def test_ignore_une_operation_remontee_par_un_bar(self):
        """Elle vient du bar : la renvoyer la-bas l'y appliquerait une seconde fois."""
        request = self._post(HTTP_AUTHORIZATION='Instance jeton-du-bar')

        self.assertFalse(should_capture(request, 200))

    def test_ignore_un_rejeu_de_synchronisation(self):
        request = self._post(HTTP_X_SYNC_REPLAY='1')

        self.assertFalse(should_capture(request, 200))

    def test_ignore_une_action_qui_a_echoue(self):
        """Rejouer au bar une correction que le cloud a refusee y produirait la meme erreur."""
        self.assertFalse(should_capture(self._post(), 400))

    def test_ignore_ce_qui_est_hors_liste_blanche(self):
        request = self.factory.post('/api/products/create/')

        self.assertFalse(should_capture(request, 200))

    @override_settings(IS_LOCAL_INSTANCE=True)
    def test_ne_capture_rien_sur_l_instance_du_bar(self):
        """Elle n'a personne a qui faire descendre ses operations."""
        self.assertFalse(should_capture(self._post(), 200))


class DownstreamOperationsViewTests(DownstreamBase):
    """Ce que le bar vient chercher."""

    def setUp(self):
        super().setUp()
        self.instance = self._instance()
        self.other = Organisation.objects.create(name=f'Org {uuid.uuid4()}')

    def _operation(self, organisation=None, path='/api/orders/1/cancel/'):
        return PendingDownstreamRequest.objects.create(
            organisation=organisation or self.organisation,
            user=self.admin if organisation is None else None,
            method='POST', path=path, body=None,
        )

    def _fetch(self, after=None):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Instance {self.instance.token}')
        query = f'?after={after}' if after is not None else ''
        return client.get(reverse('sync-operations') + query)

    def test_le_bar_recoit_les_corrections_de_son_etablissement(self):
        operation = self._operation()

        response = self._fetch()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item['id'] for item in response.data['operations']], [operation.pk]
        )
        self.assertEqual(
            response.data['operations'][0]['acting_user_id'], str(self.admin.id)
        )

    def test_les_corrections_d_un_autre_etablissement_ne_sont_jamais_servies(self):
        """Une fuite entre clients, pas seulement une erreur d'imputation : le bar rejouerait
        l'annulation d'une vente qui ne lui appartient pas."""
        self._operation(organisation=self.other)

        response = self._fetch()

        self.assertEqual(response.data['operations'], [])

    def test_le_curseur_ecarte_ce_qui_est_deja_applique(self):
        first = self._operation()
        second = self._operation()

        response = self._fetch(after=first.pk)

        self.assertEqual(
            [item['id'] for item in response.data['operations']], [second.pk]
        )

    def test_demander_la_suite_vaut_accuse_de_reception(self):
        """Le curseur est memorise cote serveur : une instance reinstallee, qui repart sans
        curseur, ne doit pas rejouer d'anciennes annulations sur des ventes disparues."""
        first = self._operation()
        second = self._operation()

        self._fetch(after=first.pk)
        response = self._fetch()

        self.instance.refresh_from_db()
        self.assertEqual(self.instance.last_downstream_id, first.pk)
        self.assertEqual(
            [item['id'] for item in response.data['operations']], [second.pk]
        )

    def test_un_compte_utilisateur_ne_peut_pas_lire_ce_flux(self):
        self._operation()

        response = self.client.get(reverse('sync-operations'))

        self.assertEqual(response.status_code, 403)
