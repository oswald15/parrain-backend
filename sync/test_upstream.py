import uuid
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from organisations.models import BusinessDay, CashierDayBalance, Department, Organisation
from products.models import DepartmentStock, Product
from sync.models import PendingUpstreamRequest
from users.models import User


class UpstreamCaptureTests(TestCase):
    """Capture des operations du bar en vue de leur remontee.

    Une instance installee dans le bar est la seule a savoir ce qui s'y est passe pendant une
    coupure. Si une vente n'est pas capturee, elle n'existera jamais dans le cloud : ni pour
    l'admin, ni dans la comptabilite.

    L'authentification se fait par jeton et non par `force_authenticate` : le middleware resout
    l'utilisateur lui-meme depuis l'entete Authorization, en amont de DRF."""

    def setUp(self):
        self.organisation = Organisation.objects.create(name=f'Org {uuid.uuid4()}')
        self.department = Department.objects.create(organisation=self.organisation, name='Bar')
        self.caissier = User.objects.create(
            organisation=self.organisation, role='caissier', name='Caissier',
            phone=f'{uuid.uuid4().int % 10**9:09d}',
        )
        self.caissier.departments.add(self.department)
        self.serveuse = User.objects.create(
            organisation=self.organisation, role='serveur', name='Serveuse',
            phone=f'{uuid.uuid4().int % 10**9:09d}', assigned_cashier=self.caissier,
        )
        self.product = Product.objects.create(
            organisation=self.organisation, name='Castel', price=1000,
            purchase_price=600, stock_quantity=100,
        )
        DepartmentStock.objects.create(
            organisation=self.organisation, department=self.department, product=self.product,
            quantity=100, weighted_average_cost=600, sale_price=1000,
        )
        now = timezone.now()
        self.business_day = BusinessDay.objects.create(
            organisation=self.organisation, date=now.date(), is_open=True, opened_at=now,
        )
        CashierDayBalance.objects.create(
            business_day=self.business_day, cashier=self.caissier,
            opening_amount=Decimal('10000'), opened_at=now,
        )
        self.client = APIClient()
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Token {Token.objects.create(user=self.serveuse).key}'
        )

    def _create_tab(self, **extra):
        return self.client.post(
            reverse('client-tab-create'),
            {'client_name': 'Table 4'},
            format='json',
            **extra,
        )

    @override_settings(INSTANCE_ROLE='local', IS_LOCAL_INSTANCE=True)
    def test_une_vente_faite_au_bar_est_capturee(self):
        response = self._create_tab(HTTP_IDEMPOTENCY_KEY='cle-abc')

        self.assertEqual(response.status_code, 201, response.data)
        entry = PendingUpstreamRequest.objects.get()
        self.assertEqual(entry.method, 'POST')
        self.assertTrue(entry.path.endswith('/client-tabs/create/'))
        self.assertEqual(entry.organisation_id, self.organisation.id)
        self.assertEqual(entry.user_id, self.serveuse.id)
        self.assertEqual(entry.body['client_name'], 'Table 4')
        self.assertEqual(entry.status, PendingUpstreamRequest.STATUS_PENDING)

    @override_settings(INSTANCE_ROLE='local', IS_LOCAL_INSTANCE=True)
    def test_la_cle_d_idempotence_est_conservee(self):
        """C'est elle qui evitera de dupliquer la vente dans le cloud au moment du rejeu."""
        self._create_tab(HTTP_IDEMPOTENCY_KEY='cle-abc')

        self.assertEqual(PendingUpstreamRequest.objects.get().idempotency_key, 'cle-abc')

    @override_settings(INSTANCE_ROLE='cloud', IS_LOCAL_INSTANCE=False)
    def test_le_serveur_central_ne_capture_rien(self):
        """Capturer sur le cloud remplirait une table que rien ne viderait jamais."""
        response = self._create_tab()

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(PendingUpstreamRequest.objects.count(), 0)

    @override_settings(INSTANCE_ROLE='local', IS_LOCAL_INSTANCE=True)
    def test_une_correction_descendue_du_cloud_ne_remonte_pas(self):
        """L'autre moitie du garde-fou anti-boucle (voir sync/downstream.py).

        Une annulation faite par l'admin redescend au bar et s'applique en repassant par cette
        API. Sans cette exclusion, elle serait capturee comme une operation du bar, repartirait
        vers le cloud, et y serait appliquee une seconde fois."""
        response = self._create_tab(HTTP_X_SYNC_REPLAY='1')

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(PendingUpstreamRequest.objects.count(), 0)

    @override_settings(INSTANCE_ROLE='local', IS_LOCAL_INSTANCE=True)
    def test_les_lectures_ne_sont_pas_capturees(self):
        self.client.get(reverse('client-tab-list'))

        self.assertEqual(PendingUpstreamRequest.objects.count(), 0)

    @override_settings(INSTANCE_ROLE='local', IS_LOCAL_INSTANCE=True)
    def test_une_action_refusee_n_est_pas_capturee(self):
        """Rejouer dans le cloud une requete qui a echoue au bar y produirait la meme erreur."""
        response = self.client.post(
            reverse('client-tab-add-items', args=[uuid.uuid4()]),
            {'department': str(self.department.id), 'items': []},
            format='json',
        )

        self.assertGreaterEqual(response.status_code, 400)
        self.assertEqual(PendingUpstreamRequest.objects.count(), 0)

    @override_settings(INSTANCE_ROLE='local', IS_LOCAL_INSTANCE=True)
    def test_l_ordre_de_capture_est_preserve(self):
        """Une commande doit exister dans le cloud avant les articles qu'on y ajoute."""
        created = self._create_tab()
        tab_id = created.data['id']

        self.client.post(
            reverse('client-tab-add-items', args=[tab_id]),
            {
                'bon': str(uuid.uuid4()),
                'department': str(self.department.id),
                'items': [{'product': str(self.product.id), 'quantity': 2}],
            },
            format='json',
        )

        entries = list(PendingUpstreamRequest.objects.all())
        self.assertEqual(len(entries), 2)
        self.assertTrue(entries[0].path.endswith('/client-tabs/create/'))
        self.assertTrue(entries[1].path.endswith('/items/'))
        self.assertLess(entries[0].pk, entries[1].pk)

    @override_settings(INSTANCE_ROLE='local', IS_LOCAL_INSTANCE=True)
    def test_le_referentiel_ne_remonte_pas(self):
        """Le referentiel DESCEND du cloud. Le remonter en sens inverse ecraserait les
        modifications de l'admin par une copie locale peut-etre perimee."""
        admin = User.objects.create(
            organisation=self.organisation, role='admin', name='Admin',
            phone=f'{uuid.uuid4().int % 10**9:09d}',
        )
        admin_client = APIClient()
        admin_client.credentials(
            HTTP_AUTHORIZATION=f'Token {Token.objects.create(user=admin).key}'
        )

        response = admin_client.post(
            reverse('product-list-create'),
            {'name': 'Nouveau produit', 'price': 500, 'purchase_price': 300},
            format='json',
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(PendingUpstreamRequest.objects.count(), 0)
