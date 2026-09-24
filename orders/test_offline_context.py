import uuid
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from orders.models import Order, OrderItem
from organisations.models import BusinessDay, CashierDayBalance, Department, Organisation
from products.models import DepartmentStock, Product
from users.models import User


class OfflineBusinessContextTests(TestCase):
    """Verifie qu'une action faite hors-ligne est comptabilisee dans la caisse a laquelle elle
    appartient reellement, et non dans celle ouverte au moment ou le reseau revient.

    Sans ce rattachement, une vente encaissee a 14h et synchronisee a 19h - apres que le
    caissier a ferme sa caisse a 18h - disparaissait purement et simplement du solde, alors que
    l'argent etait bien dans le tiroir au comptage. C'est de l'argent non comptabilise."""

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
        self.opened_at = timezone.now() - timedelta(hours=6)
        self.business_day = BusinessDay.objects.create(
            organisation=self.organisation, date=self.opened_at.date(),
            is_open=True, opened_at=self.opened_at,
        )
        self.session = CashierDayBalance.objects.create(
            business_day=self.business_day, cashier=self.caissier,
            opening_amount=Decimal('10000'), opened_at=self.opened_at,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.caissier)

    def _pending_order(self, quantity=3):
        order = Order.objects.create(
            organisation=self.organisation, department=self.department, serveur=self.serveuse,
            status='servie', number_of_customers=1, total_amount=Decimal(1000 * quantity),
        )
        OrderItem.objects.create(
            order=order, product=self.product, quantity=quantity, unit_price=Decimal('1000'),
        )
        return order

    def _close_session(self):
        from orders import cash_sessions

        self.session.closing_amount = cash_sessions.compute_closing_amount(self.session)
        self.session.closed_at = timezone.now()
        self.session.save()

    def test_vente_hors_ligne_synchronisee_apres_fermeture_reste_dans_sa_caisse(self):
        order = self._pending_order(quantity=3)
        self._close_session()
        self.assertEqual(self.session.closing_amount, Decimal('10000'))

        # La vente remonte enfin : elle a eu lieu pendant la session, avant sa fermeture.
        response = self.client.patch(
            reverse('order-update', args=[order.id]),
            {'status': 'fermee', 'payment_type': 'cash'},
            format='json',
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
            HTTP_X_CASHIER_SESSION=str(self.session.id),
            HTTP_X_CLIENT_CREATED_AT=(self.opened_at + timedelta(hours=1)).isoformat(),
        )

        self.assertEqual(response.status_code, 200, response.data)
        order.refresh_from_db()
        self.session.refresh_from_db()

        self.assertEqual(order.cashier_session_id, self.session.id)
        self.assertIsNotNone(order.client_created_at, "L'horodatage reel n'a pas ete conserve")
        self.assertEqual(
            self.session.closing_amount, Decimal('13000'),
            'La vente hors-ligne est absente du solde de la session ou elle a eu lieu',
        )
        self.assertIsNotNone(
            self.session.adjusted_after_close_at,
            "L'ajustement d'une caisse deja fermee doit etre trace pour l'admin",
        )

    def test_une_session_encore_ouverte_nest_pas_marquee_comme_ajustee(self):
        order = self._pending_order(quantity=2)

        response = self.client.patch(
            reverse('order-update', args=[order.id]),
            {'status': 'fermee', 'payment_type': 'cash'},
            format='json',
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.session.refresh_from_db()
        self.assertIsNone(self.session.closing_amount)
        self.assertIsNone(
            self.session.adjusted_after_close_at,
            "Une session ouverte n'a pas de solde arrete, donc rien a ajuster",
        )

    def test_le_resume_de_caisse_compte_la_vente_rattachee(self):
        order = self._pending_order(quantity=2)
        self.client.patch(
            reverse('order-update', args=[order.id]),
            {'status': 'fermee', 'payment_type': 'cash'},
            format='json', HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )

        summary = self.client.get(reverse('caissier-daily-summary'))

        self.assertEqual(summary.status_code, 200)
        self.assertEqual(Decimal(str(summary.data['total_revenue'])), Decimal('2000'))
        self.assertEqual(Decimal(str(summary.data['net_cash'])), Decimal('12000'))
        # L'app a besoin de cet identifiant pour rattacher ses actions hors-ligne a la bonne
        # caisse, y compris apres un rechargement de page.
        self.assertEqual(summary.data['session_id'], str(self.session.id))


class BusinessDayGateReplayTests(TestCase):
    """Le gate de journee de travail bloque les ecritures des roles non-admin tant que l'admin
    n'a pas ouvert la journee. Il doit laisser passer les rejeux hors-ligne : sinon, toutes les
    ventes faites pendant une coupure reseau seraient rejetees en bloc si la journee a ete
    fermee entre-temps.

    Ces tests utilisent une authentification par jeton (et non force_authenticate) car le
    middleware resout l'utilisateur lui-meme depuis l'entete Authorization, en amont de DRF."""

    def setUp(self):
        self.organisation = Organisation.objects.create(name=f'Org {uuid.uuid4()}')
        self.serveuse = User.objects.create(
            organisation=self.organisation, role='serveur', name='Serveuse',
            phone=f'{uuid.uuid4().int % 10**9:09d}',
        )
        token = Token.objects.create(user=self.serveuse)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        # Aucune journee ouverte : le gate est actif.

    def test_ecriture_en_direct_reste_bloquee_journee_fermee(self):
        response = self.client.post(
            reverse('client-tab-create'), {'client_name': 'Table 1'}, format='json',
        )

        self.assertEqual(response.status_code, 403)

    def test_rejeu_hors_ligne_passe_malgre_la_journee_fermee(self):
        response = self.client.post(
            reverse('client-tab-create'), {'client_name': 'Table 1'}, format='json',
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )

        self.assertEqual(
            response.status_code, 201,
            'Un rejeu hors-ligne ne doit pas etre perdu parce que la journee a ete fermee',
        )
