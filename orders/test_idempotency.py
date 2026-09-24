import uuid
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from orders.models import Bon, BonItem, ClientTab, Consignment, Order, OrderItem, Transaction
from organisations.models import BusinessDay, CashierDayBalance, Department, Organisation
from products.models import DepartmentStock, Product
from users.models import User


class CaisseFixtureMixin:
    """Decor commun : une organisation avec un bar, un produit en stock, une serveuse, un
    caissier et sa session de caisse ouverte. Volontairement pas un TestCase - en heriter
    ferait reexecuter les tests de la classe parente dans chaque classe enfant."""

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
            purchase_price=600, stock_quantity=100, is_consignable=True, deposit_amount=100,
        )
        self.stock = DepartmentStock.objects.create(
            organisation=self.organisation, department=self.department, product=self.product,
            quantity=100, weighted_average_cost=600, sale_price=1000,
        )
        now = timezone.now()
        self.business_day = BusinessDay.objects.create(
            organisation=self.organisation, date=now.date(), is_open=True, opened_at=now,
        )
        self.session = CashierDayBalance.objects.create(
            business_day=self.business_day, cashier=self.caissier,
            opening_amount=Decimal('10000'), opened_at=now,
        )
        self.serveuse_client = APIClient()
        self.serveuse_client.force_authenticate(user=self.serveuse)
        self.caissier_client = APIClient()
        self.caissier_client.force_authenticate(user=self.caissier)

    def _twice(self, client, method, url, payload=None):
        """Joue deux fois la meme requete avec la meme cle d'idempotence."""
        key = str(uuid.uuid4())
        call = getattr(client, method)
        kwargs = {'format': 'json', 'HTTP_IDEMPOTENCY_KEY': key}
        if payload is None:
            return call(url, **kwargs), call(url, **kwargs)
        return call(url, payload, **kwargs), call(url, payload, **kwargs)

    def _open_tab(self):
        return ClientTab.objects.create(
            organisation=self.organisation, serveur=self.serveuse, client_name='Table 4',
        )

    def _add_items(self, tab, quantity=3):
        return self.serveuse_client.post(
            reverse('client-tab-add-items', args=[tab.id]),
            {
                'department': str(self.department.id),
                'items': [{'product': str(self.product.id), 'quantity': quantity}],
            },
            format='json',
        )


class IdempotencyContractTests(CaisseFixtureMixin, TestCase):
    """Test de contrat par endpoint : rejouer une action avec la meme cle ne doit produire
    qu'un seul effet en base, et renvoyer la meme reponse qu'au premier appel.

    C'est le filet de securite du mode hors-ligne : quand le reseau revient, la file d'attente
    de l'app rejoue les actions, parfois plusieurs fois (coupure pendant l'envoi - l'action est
    passee mais la reponse s'est perdue). Sans idempotence, chaque rejeu revendrait les memes
    articles et redecrementerait le stock."""

    # --- Les deux tests qui protegent l'argent et le stock ---

    def test_rejeu_ajout_articles_ne_double_pas_les_quantites(self):
        """L'endpoint le plus dangereux : il CUMULE les quantites (order_item.quantity += ...).
        Sans idempotence, un rejeu ferait payer deux fois les memes consommations au client."""
        tab = self._open_tab()

        first, second = self._twice(
            self.serveuse_client, 'post', reverse('client-tab-add-items', args=[tab.id]),
            {
                'department': str(self.department.id),
                'items': [{'product': str(self.product.id), 'quantity': 3}],
            },
        )

        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(second.json(), first.json())
        self.assertEqual(OrderItem.objects.get().quantity, 3, 'Quantites cumulees deux fois')
        self.assertEqual(Bon.objects.count(), 1)
        self.assertEqual(BonItem.objects.count(), 1)
        self.assertEqual(Order.objects.get().total_amount, Decimal('3000'))

    def test_rejeu_encaissement_ne_decremente_le_stock_quune_fois(self):
        tab = self._open_tab()
        self._add_items(tab, quantity=4)
        self.serveuse_client.post(reverse('client-tab-invoice', args=[tab.id]), format='json')

        first, second = self._twice(
            self.caissier_client, 'post', reverse('client-tab-close', args=[tab.id]),
            {'payment_type': 'cash'},
        )

        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(second.json(), first.json())
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 96, 'Stock decremente deux fois')
        self.assertEqual(Transaction.objects.filter(transaction_type='sortie_vente').count(), 1)
        self.assertEqual(Order.objects.get().status, 'fermee')

    # --- Les autres endpoints du perimetre gele en Phase 0 ---

    def test_rejeu_creation_onglet_ne_cree_quun_onglet(self):
        first, second = self._twice(
            self.serveuse_client, 'post', reverse('client-tab-create'), {'client_name': 'Table 7'},
        )

        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.json(), first.json())
        self.assertEqual(ClientTab.objects.filter(client_name='Table 7').count(), 1)

    def test_rejeu_suppression_onglet_renvoie_le_succes_memorise(self):
        tab = self._open_tab()

        first, second = self._twice(
            self.serveuse_client, 'delete', reverse('client-tab-detail', args=[tab.id]),
        )

        self.assertEqual(first.status_code, 204)
        self.assertEqual(second.status_code, 204, 'Le rejeu doit renvoyer le succes, pas un 404')
        self.assertEqual(ClientTab.objects.filter(id=tab.id).count(), 0)

    def test_rejeu_facturation_onglet(self):
        tab = self._open_tab()
        self._add_items(tab)

        first, second = self._twice(
            self.serveuse_client, 'post', reverse('client-tab-invoice', args=[tab.id]),
        )

        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(second.json(), first.json())
        tab.refresh_from_db()
        self.assertEqual(tab.status, 'facture')

    def test_rejeu_validation_bon(self):
        tab = self._open_tab()
        self._add_items(tab)
        bon = Bon.objects.get()

        first, second = self._twice(
            self.caissier_client, 'post', reverse('bon-validate', args=[bon.id]),
        )

        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(second.json(), first.json())
        bon.refresh_from_db()
        self.assertEqual(bon.status, 'valide')

    def test_rejeu_annulation_bon_ne_retire_les_articles_quune_fois(self):
        tab = self._open_tab()
        self._add_items(tab, quantity=5)
        bon = Bon.objects.get()

        first, second = self._twice(
            self.caissier_client, 'post', reverse('bon-cancel', args=[bon.id]),
        )

        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(second.json(), first.json())
        bon.refresh_from_db()
        self.assertEqual(bon.status, 'annule')
        self.assertEqual(Order.objects.get().total_amount, Decimal('0'))

    def test_rejeu_creation_consignation(self):
        tab = self._open_tab()
        self._add_items(tab)
        order = Order.objects.get()

        first, second = self._twice(
            self.caissier_client, 'post', reverse('consignment-create'),
            {'order': str(order.id), 'items': [{'product': str(self.product.id), 'quantity': 2}]},
        )

        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.json(), first.json())
        self.assertEqual(Consignment.objects.count(), 1)
        self.assertEqual(Transaction.objects.filter(transaction_type='consignation').count(), 1)

    def test_rejeu_retour_consignation(self):
        consignment = Consignment.objects.create(
            organisation=self.organisation, department=self.department, product=self.product,
            client_name='Table 4', quantity=2, unit_deposit_amount=100, created_by=self.caissier,
        )

        first, second = self._twice(
            self.caissier_client, 'post', reverse('consignment-return', args=[consignment.id]),
        )

        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(second.json(), first.json())
        self.assertEqual(Transaction.objects.filter(transaction_type='deconsignation').count(), 1)

    def test_rejeu_ouverture_session_caisse(self):
        """La session ouverte dans setUp est fermee au prealable, pour pouvoir en rouvrir une."""
        self.session.closing_amount = Decimal('10000')
        self.session.closed_at = timezone.now()
        self.session.save()

        first, second = self._twice(
            self.caissier_client, 'post', reverse('cashier-session-open'),
        )

        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.json(), first.json())
        self.assertEqual(
            CashierDayBalance.objects.filter(
                cashier=self.caissier, closing_amount__isnull=True
            ).count(),
            1,
        )
        self.assertEqual(Transaction.objects.filter(transaction_type='ouverture_session').count(), 1)

    def test_rejeu_fermeture_session_caisse(self):
        first, second = self._twice(
            self.caissier_client, 'post', reverse('cashier-session-close'),
        )

        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(second.json(), first.json())
        self.assertEqual(Transaction.objects.filter(transaction_type='fermeture_session').count(), 1)


class ConflictEnvelopeTests(CaisseFixtureMixin, TestCase):
    """Distingue deux situations que le client doit traiter differemment :
    - MON action a deja abouti (rejeu de ma propre cle) -> succes memorise, on retire de la file
    - QUELQU'UN D'AUTRE a change l'etat entre-temps -> conflit explicite, il faut alerter

    Sans cette distinction, la file d'attente ne peut pas choisir entre retirer l'action et
    prevenir l'utilisateur qu'un collegue est passe avant lui."""

    def test_meme_action_par_un_autre_appareil_renvoie_un_conflit_explicite(self):
        tab = self._open_tab()
        self._add_items(tab)
        bon = Bon.objects.get()

        premier = self.caissier_client.post(
            reverse('bon-cancel', args=[bon.id]), format='json',
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        # Cle DIFFERENTE : ce n'est pas un rejeu, c'est une seconde tentative reelle.
        second = self.caissier_client.post(
            reverse('bon-cancel', args=[bon.id]), format='json',
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )

        self.assertEqual(premier.status_code, 200, premier.data)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.data['code'], 'bon_already_handled')

    def test_conflit_de_session_de_caisse_porte_un_code(self):
        second = self.caissier_client.post(
            reverse('cashier-session-open'), format='json',
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )

        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.data['code'], 'session_already_open')

    def test_toute_erreur_porte_un_code_exploitable_par_la_file(self):
        """Repli : meme une erreur sans code metier dedie doit etre classable par le client."""
        response = self.serveuse_client.post(
            reverse('client-tab-add-items', args=[uuid.uuid4()]),
            {'department': str(self.department.id), 'items': []}, format='json',
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data['code'], 'not_found')
