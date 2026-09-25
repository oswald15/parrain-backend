import uuid

from django.test import TestCase, override_settings
from django.utils import timezone
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from orders.models import ClientTab, Order, OrderItem, Transaction
from organisations.models import Department, Organisation
from products.models import DepartmentStock, Product
from sync.corrections import rewrite
from sync.models import PendingDownstreamRequest, PendingUpstreamRequest, SyncInstance
from users.models import User


class Base(TestCase):
    def setUp(self):
        self.organisation = Organisation.objects.create(name=f'Org {uuid.uuid4()}')
        self.admin = User.objects.create(
            organisation=self.organisation, role='admin', name='Admin',
            phone=f'{uuid.uuid4().int % 10**9:09d}',
        )
        self.department = Department.objects.create(organisation=self.organisation, name='Bar')
        self.product = Product.objects.create(
            organisation=self.organisation, name='Castel', price=1000,
            purchase_price=600, stock_quantity=50,
        )
        DepartmentStock.objects.create(
            organisation=self.organisation, department=self.department, product=self.product,
            quantity=50, weighted_average_cost=600, sale_price=1000,
        )
        self.tab = ClientTab.objects.create(
            organisation=self.organisation, client_name='Table 4', status='ouvert',
        )
        self.order = Order.objects.create(
            organisation=self.organisation, department=self.department, client_tab=self.tab,
            status='fermee', number_of_customers=1, total_amount=2000,
        )
        OrderItem.objects.create(
            order=self.order, product=self.product, quantity=2, unit_price=1000,
        )
        self.client = APIClient()
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Token {Token.objects.create(user=self.admin).key}'
        )


class ReecritureTests(Base):
    """Une correction doit etre adressee par ce que les deux cotes savent nommer.

    Une meme vente porte un identifiant different au bar et dans le cloud : chaque base fabrique
    le sien. Une annulation qui le cite est incomprehensible pour l'autre cote, qui repond 404 -
    et la vente reste annulee d'un seul cote."""

    def test_l_annulation_est_adressee_par_onglet_et_departement(self):
        _, chemin, corps = rewrite('POST', f'/api/orders/{self.order.id}/cancel/', {'reason': 'erreur'})

        self.assertEqual(chemin, '/api/orders/corrections/annuler/')
        self.assertEqual(corps['client_tab'], str(self.tab.id))
        self.assertEqual(corps['department'], str(self.department.id))
        # Le corps d'origine est conserve : la raison de l'annulation ne doit pas disparaitre.
        self.assertEqual(corps['reason'], 'erreur')

    def test_une_vente_sans_onglet_n_est_pas_reecrite(self):
        """Vente directe au comptoir : aucune identite naturelle partagee. On n'invente pas."""
        sans_onglet = Order.objects.create(
            organisation=self.organisation, department=self.department,
            status='fermee', number_of_customers=1, total_amount=500,
        )

        _, chemin, _ = rewrite('POST', f'/api/orders/{sans_onglet.id}/cancel/', {})

        self.assertEqual(chemin, f'/api/orders/{sans_onglet.id}/cancel/')

    def test_les_autres_operations_passent_telles_quelles(self):
        _, chemin, corps = rewrite('POST', '/api/orders/client-tabs/create/', {'client_name': 'Table 9'})

        self.assertEqual(chemin, '/api/orders/client-tabs/create/')
        self.assertEqual(corps, {'client_name': 'Table 9'})

    def test_une_commande_introuvable_laisse_l_adresse_d_origine(self):
        """Mieux vaut une correction en quarantaine, donc visible, qu'une correction perdue au
        moment meme de sa capture."""
        _, chemin, _ = rewrite('POST', f'/api/orders/{uuid.uuid4()}/cancel/', {})

        self.assertIn('/cancel/', chemin)


class AnnulationParIdentiteNaturelleTests(Base):
    """La vue qui resout (onglet, departement) vers SA commande a elle."""

    def _annuler(self, **corps):
        defaut = {'client_tab': str(self.tab.id), 'department': str(self.department.id)}
        defaut.update(corps)
        return self.client.post(reverse('order-cancel-by-key'), defaut, format='json')

    def test_annule_la_commande_et_recredite_le_stock(self):
        reponse = self._annuler(reason='erreur de saisie')

        self.assertEqual(reponse.status_code, 200, getattr(reponse, 'data', reponse.content))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'annulee')
        self.assertEqual(self.order.cancel_reason, 'erreur de saisie')
        stock = DepartmentStock.objects.get(department=self.department, product=self.product)
        self.assertEqual(stock.quantity, 52)

    def test_annuler_deux_fois_ne_change_rien_de_plus(self):
        """Les deux cotes reagissent souvent au meme probleme, et la correction peut etre rejouee.

        Une erreur l'enverrait en quarantaine sans raison. Mais repondre 200 ne suffit pas : il
        faut que la seconde annulation ne PRODUISE rien - sinon le journal compte deux
        annulations pour une vente, et les rapports d'ecart sont faux."""
        self._annuler()
        ecritures = Transaction.objects.filter(transaction_type='annulation_facture').count()

        reponse = self._annuler()

        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(
            Transaction.objects.filter(transaction_type='annulation_facture').count(),
            ecritures,
        )
        stock = DepartmentStock.objects.get(department=self.department, product=self.product)
        self.assertEqual(stock.quantity, 52)

    def test_un_couple_inconnu_repond_404(self):
        autre = Department.objects.create(organisation=self.organisation, name='Terrasse')

        reponse = self._annuler(department=str(autre.id))

        self.assertEqual(reponse.status_code, 404)

    def test_un_autre_etablissement_ne_peut_pas_annuler(self):
        etranger = Organisation.objects.create(name=f'Org {uuid.uuid4()}')
        intrus = User.objects.create(
            organisation=etranger, role='admin', name='Intrus',
            phone=f'{uuid.uuid4().int % 10**9:09d}',
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Token {Token.objects.create(user=intrus).key}')

        reponse = client.post(reverse('order-cancel-by-key'), {
            'client_tab': str(self.tab.id), 'department': str(self.department.id),
        }, format='json')

        self.assertEqual(reponse.status_code, 404)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'fermee')


@override_settings(INSTANCE_ROLE='local', IS_LOCAL_INSTANCE=True)
class CaptureDeLAnnulationAuBarTests(Base):
    """Le bar annule : ce qui part vers le cloud doit etre la forme naturelle."""

    def test_la_remontee_capture_l_adresse_partagee(self):
        self.client.post(reverse('order-cancel', args=[self.order.id]))

        capturee = PendingUpstreamRequest.objects.get()
        self.assertEqual(capturee.path, '/api/orders/corrections/annuler/')
        self.assertEqual(capturee.body['client_tab'], str(self.tab.id))


class CaptureDeLAnnulationDansLeCloudTests(Base):
    """L'admin annule dans le cloud : ce qui descend doit etre la forme naturelle."""

    def test_la_descente_capture_l_adresse_partagee(self):
        # A jour : sinon le garde-fou anti-corrections refuse l'annulation, et il n'y a rien a
        # capturer (voir orders/views.py::_refuse_if_bar_not_synced).
        SyncInstance.objects.create(
            organisation=self.organisation, name='Poste caisse',
            pending_operations=0, last_seen_at=timezone.now(),
        )

        self.client.post(reverse('order-cancel', args=[self.order.id]))

        capturee = PendingDownstreamRequest.objects.get()
        self.assertEqual(capturee.path, '/api/orders/corrections/annuler/')
        self.assertEqual(capturee.body['department'], str(self.department.id))


class ReecritureDuRetraitDeLigneTests(Base):
    """Une ligne porte un identifiant ENTIER auto-incremente : il ne peut pas coincider entre
    deux bases. Le produit, lui, vient du referentiel et porte le meme des deux cotes."""

    def test_le_retrait_est_adresse_par_onglet_departement_et_produit(self):
        ligne = self.order.items.first()

        methode, chemin, corps = rewrite(
            'DELETE', f'/api/orders/{self.order.id}/items/{ligne.id}/', None
        )

        self.assertEqual(chemin, '/api/orders/corrections/retirer-ligne/')
        self.assertEqual(corps['client_tab'], str(self.tab.id))
        self.assertEqual(corps['department'], str(self.department.id))
        self.assertEqual(corps['product'], str(self.product.id))

    def test_la_methode_devient_post(self):
        """L'ecran supprime en DELETE. La correction se rejoue en POST : une requete DELETE ne
        peut pas porter un corps de facon portable, et c'est le corps qui designe la ligne."""
        ligne = self.order.items.first()

        methode, _, _ = rewrite('DELETE', f'/api/orders/{self.order.id}/items/{ligne.id}/', None)

        self.assertEqual(methode, 'POST')

    def test_une_ligne_introuvable_laisse_l_adresse_d_origine(self):
        methode, chemin, _ = rewrite('DELETE', f'/api/orders/{self.order.id}/items/999999/', None)

        self.assertEqual(methode, 'DELETE')
        self.assertIn('/items/999999/', chemin)


class RetraitDeLigneParIdentiteNaturelleTests(Base):
    """La vue qui resout (onglet, departement, produit) vers SA ligne a elle."""

    def _retirer(self, **corps):
        defaut = {
            'client_tab': str(self.tab.id),
            'department': str(self.department.id),
            'product': str(self.product.id),
        }
        defaut.update(corps)
        return self.client.post(
            reverse('order-item-remove-by-key'), defaut, format='json'
        )

    def test_retire_la_ligne_recredite_le_stock_et_recalcule_le_total(self):
        reponse = self._retirer()

        self.assertEqual(reponse.status_code, 200, getattr(reponse, 'data', reponse.content))
        ligne = self.order.items.first()
        ligne.refresh_from_db()
        self.assertTrue(ligne.is_removed)
        stock = DepartmentStock.objects.get(department=self.department, product=self.product)
        self.assertEqual(stock.quantity, 52)
        self.order.refresh_from_db()
        self.assertEqual(self.order.total_amount, 0)

    def test_retirer_deux_fois_ne_change_rien_de_plus(self):
        """Sans cela, un second passage recrediterait le stock une seconde fois et ecrirait un
        second avoir - la marchandise reapparaitrait en stock sans etre revenue."""
        self._retirer()
        avoirs = Transaction.objects.filter(transaction_type='avoir').count()

        reponse = self._retirer()

        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(Transaction.objects.filter(transaction_type='avoir').count(), avoirs)
        stock = DepartmentStock.objects.get(department=self.department, product=self.product)
        self.assertEqual(stock.quantity, 52)

    def test_un_produit_absent_de_la_commande_repond_404(self):
        autre = Product.objects.create(
            organisation=self.organisation, name='Beaufort', price=800, purchase_price=500,
        )

        reponse = self._retirer(product=str(autre.id))

        self.assertEqual(reponse.status_code, 404)

    def test_un_autre_etablissement_ne_peut_pas_retirer(self):
        etranger = Organisation.objects.create(name=f'Org {uuid.uuid4()}')
        intrus = User.objects.create(
            organisation=etranger, role='admin', name='Intrus',
            phone=f'{uuid.uuid4().int % 10**9:09d}',
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Token {Token.objects.create(user=intrus).key}')

        reponse = client.post(reverse('order-item-remove-by-key'), {
            'client_tab': str(self.tab.id),
            'department': str(self.department.id),
            'product': str(self.product.id),
        }, format='json')

        self.assertEqual(reponse.status_code, 404)
        self.assertFalse(self.order.items.first().is_removed)


@override_settings(INSTANCE_ROLE='local', IS_LOCAL_INSTANCE=True)
class CaptureDuRetraitAuBarTests(Base):
    def test_la_remontee_capture_l_adresse_partagee(self):
        ligne = self.order.items.first()

        self.client.delete(reverse('order-item-delete', args=[self.order.id, ligne.id]))

        capturee = PendingUpstreamRequest.objects.get()
        self.assertEqual(capturee.method, 'POST')
        self.assertEqual(capturee.path, '/api/orders/corrections/retirer-ligne/')
        self.assertEqual(capturee.body['product'], str(self.product.id))
