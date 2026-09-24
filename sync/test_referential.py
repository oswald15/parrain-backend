import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from console.models import Abonnement, Formule
from organisations.models import Department, Organisation
from products.models import Category, DepartmentStock, Product
from sync.models import PendingUpstreamRequest, SyncInstance
from users.models import User

CLOUD = 'https://cloud.example.test'


class ReferentialEndpointTests(TestCase):
    """Referentiel servi aux instances.

    Il expose tout le catalogue et le personnel d'un etablissement : son acces doit etre
    strictement reserve aux instances, et cloisonne par etablissement."""

    def setUp(self):
        self.organisation = Organisation.objects.create(name=f'Bar A {uuid.uuid4()}')
        self.department = Department.objects.create(
            organisation=self.organisation, name='Bar'
        )
        self.product = Product.objects.create(
            organisation=self.organisation, name='Castel', price=1000,
            purchase_price=600, stock_quantity=42,
        )
        DepartmentStock.objects.create(
            organisation=self.organisation, department=self.department, product=self.product,
            quantity=42, weighted_average_cost=600, sale_price=1000,
        )
        self.instance = SyncInstance.objects.create(
            organisation=self.organisation, name='Poste caisse'
        )

        self.autre = Organisation.objects.create(name=f'Bar B {uuid.uuid4()}')
        Product.objects.create(
            organisation=self.autre, name='Produit du voisin', price=500, purchase_price=300,
        )

        self.client = APIClient()

    def test_une_instance_recoit_le_referentiel_de_son_etablissement(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Instance {self.instance.token}')

        response = self.client.get(reverse('sync-referentiel'))

        self.assertEqual(response.status_code, 200)
        noms = [p['name'] for p in response.data['products']]
        self.assertEqual(noms, ['Castel'])

    def test_le_referentiel_d_un_autre_etablissement_n_est_jamais_expose(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Instance {self.instance.token}')

        response = self.client.get(reverse('sync-referentiel'))

        noms = [p['name'] for p in response.data['products']]
        self.assertNotIn('Produit du voisin', noms)

    def test_la_quantite_globale_du_produit_ne_descend_pas(self):
        """`stock_quantity` est une valeur calculee que le bar decremente a chaque vente : la
        descendre ecraserait les ventes locales pas encore remontees."""
        self.client.credentials(HTTP_AUTHORIZATION=f'Instance {self.instance.token}')

        response = self.client.get(reverse('sync-referentiel'))

        self.assertNotIn('stock_quantity', response.data['products'][0])

    def test_un_utilisateur_ordinaire_ne_peut_pas_lire_le_referentiel(self):
        admin = User.objects.create(
            organisation=self.organisation, role='admin', name='Admin',
            phone=f'{uuid.uuid4().int % 10**9:09d}',
        )
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Token {Token.objects.create(user=admin).key}'
        )

        response = self.client.get(reverse('sync-referentiel'))

        self.assertEqual(response.status_code, 403)

    def test_aucun_mot_de_passe_n_est_expose(self):
        User.objects.create(
            organisation=self.organisation, role='serveur', name='Serveuse',
            phone=f'{uuid.uuid4().int % 10**9:09d}',
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Instance {self.instance.token}')

        response = self.client.get(reverse('sync-referentiel'))

        for user in response.data['users']:
            self.assertNotIn('password', user)


@override_settings(INSTANCE_ROLE='local', IS_LOCAL_INSTANCE=True,
                   CLOUD_API_URL=CLOUD, INSTANCE_TOKEN='jeton')
class PullReferentialTests(TestCase):
    """Application du referentiel cote bar.

    Le piege de cette etape : les quantites de stock sont ecrites des DEUX cotes - receptions et
    inventaires dans le cloud, ventes au bar. Les appliquer au mauvais moment fait disparaitre
    des ventes de l'ecran du caissier."""

    def setUp(self):
        self.organisation = Organisation.objects.create(name=f'Org {uuid.uuid4()}')
        self.department = Department.objects.create(
            organisation=self.organisation, name='Bar'
        )
        self.product = Product.objects.create(
            organisation=self.organisation, name='Castel', price=1000, purchase_price=600,
        )
        self.stock = DepartmentStock.objects.create(
            organisation=self.organisation, department=self.department, product=self.product,
            quantity=10, weighted_average_cost=600, sale_price=1000,
        )

    def _payload(self, quantity=99, price='1500'):
        return {
            'organisation': {
                'id': str(self.organisation.id),
                'name': self.organisation.name,
                'statut': 'active',
            },
            'departments': [
                {'id': str(self.department.id), 'name': 'Bar', 'is_active': True}
            ],
            'categories': [],
            'products': [{
                'id': str(self.product.id), 'category_id': None, 'code': '',
                'name': 'Castel', 'purchase_price': '600', 'price': price,
                'image_url': None, 'min_threshold': 5, 'unit': 'piece',
                'is_active': True, 'is_consignable': False, 'deposit_amount': '0',
                'shared_stock': False,
            }],
            'department_stocks': [{
                'id': str(self.stock.id),
                'department_id': str(self.department.id),
                'product_id': str(self.product.id),
                'sale_price': price,
                'weighted_average_cost': '600',
                'min_threshold': 5,
                'quantity': quantity,
            }],
            'users': [],
            'formules': [],
            'abonnements': [],
        }

    def _pull(self, payload):
        class FakeResponse:
            status_code = 200

            def json(self_inner):
                return payload

        with patch('requests.get', return_value=FakeResponse()):
            call_command('pull_referential')

    def test_les_prix_descendent_du_cloud(self):
        self._pull(self._payload(price='1500'))

        self.product.refresh_from_db()
        self.assertEqual(self.product.price, Decimal('1500'))

    def test_les_quantites_descendent_quand_le_bar_est_a_jour(self):
        self._pull(self._payload(quantity=99))

        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 99)

    def test_les_quantites_ne_descendent_pas_si_des_ventes_attendent(self):
        """Le cas qui protege le caissier : le cloud ignore encore les ventes en attente, ses
        quantites sont donc superieures au reel. Les appliquer afficherait du stock inexistant."""
        PendingUpstreamRequest.objects.create(
            organisation=self.organisation, method='POST',
            path='/api/orders/client-tabs/abc/items/', body={},
        )

        self._pull(self._payload(quantity=99, price='1500'))

        self.stock.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(self.stock.quantity, 10, 'Les ventes en attente ont ete effacees')
        # Le reste du referentiel descend normalement : seules les quantites sont retenues.
        self.assertEqual(self.product.price, Decimal('1500'))

    def test_une_nouvelle_ligne_de_stock_part_de_la_quantite_du_cloud(self):
        """Sans cela, un produit nouvellement affecte a un departement resterait a zero et
        serait invendable tant que la file n'est pas videe."""
        PendingUpstreamRequest.objects.create(
            organisation=self.organisation, method='POST', path='/api/orders/x/', body={},
        )
        nouveau = Product.objects.create(
            organisation=self.organisation, name='Beaufort', price=800, purchase_price=500,
        )
        payload = self._payload()
        payload['products'].append({
            'id': str(nouveau.id), 'category_id': None, 'code': '', 'name': 'Beaufort',
            'purchase_price': '500', 'price': '800', 'image_url': None, 'min_threshold': 5,
            'unit': 'piece', 'is_active': True, 'is_consignable': False,
            'deposit_amount': '0', 'shared_stock': False,
        })
        nouvelle_ligne = str(uuid.uuid4())
        payload['department_stocks'].append({
            'id': nouvelle_ligne,
            'department_id': str(self.department.id),
            'product_id': str(nouveau.id),
            'sale_price': '800', 'weighted_average_cost': '500',
            'min_threshold': 5, 'quantity': 30,
        })

        self._pull(payload)

        self.assertEqual(DepartmentStock.objects.get(id=nouvelle_ligne).quantity, 30)

    def test_la_licence_descend_pour_etre_appliquee_hors_ligne(self):
        formule = {
            'id': str(uuid.uuid4()), 'libelle': 'Mensuel',
            'duree_jours': 30, 'montant_xaf': 10000, 'active': True,
        }
        now = timezone.now()
        payload = self._payload()
        payload['formules'] = [formule]
        payload['abonnements'] = [{
            'id': str(uuid.uuid4()),
            'formule_id': formule['id'],
            'date_debut': now.isoformat(),
            'date_expiration': (now + timedelta(days=30)).isoformat(),
            'montant_xaf': 10000,
            'statut': 'en_cours',
        }]

        self._pull(payload)

        self.assertEqual(Formule.objects.count(), 1)
        self.assertEqual(Abonnement.objects.filter(organisation=self.organisation).count(), 1)

    @override_settings(INSTANCE_ROLE='cloud', IS_LOCAL_INSTANCE=False)
    def test_le_serveur_central_ne_recupere_rien(self):
        with patch('requests.get') as fetched:
            call_command('pull_referential')

        fetched.assert_not_called()
