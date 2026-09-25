import uuid
from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from orders.models import Order, OrderItem
from organisations.models import Department, Organisation
from products.models import DepartmentStock, Inventory, InventoryLine, Product
from sync.models import SyncInstance
from users.models import User


class InventoryValidationGuardTests(TestCase):
    """Protection de la validation d'inventaire.

    Valider un inventaire ecrase le stock par le compte physique, en valeur absolue. Si un bar a
    des ventes qui n'ont pas encore remonte, elles disparaissent du stock sans laisser de trace :
    les quantites paraissent coherentes, mais elles ignorent des consommations reellement
    servies. C'est une perte comptable silencieuse - le pire genre."""

    def setUp(self):
        self.organisation = Organisation.objects.create(name=f'Org {uuid.uuid4()}')
        self.admin = User.objects.create(
            organisation=self.organisation, role='admin', name='Admin',
            phone=f'{uuid.uuid4().int % 10**9:09d}',
        )
        self.product = Product.objects.create(
            organisation=self.organisation, name='Castel', price=1000,
            purchase_price=600, stock_quantity=50,
        )
        # Le produit doit etre affecte a un departement : le total de l'organisation est
        # recalcule comme la somme des stocks departementaux, et vaudrait zero sans cela.
        self.department = Department.objects.create(
            organisation=self.organisation, name='Bar'
        )
        self.stock = DepartmentStock.objects.create(
            organisation=self.organisation, department=self.department, product=self.product,
            quantity=50, weighted_average_cost=600, sale_price=1000,
        )
        self.inventory = Inventory.objects.create(
            organisation=self.organisation, created_by=self.admin, valuation_mode='achat',
        )
        InventoryLine.objects.create(
            inventory=self.inventory, product=self.product, department=self.department,
            system_quantity=50, physical_quantity=48, purchase_price=600, sale_price=1000,
        )
        self.client = APIClient()
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Token {Token.objects.create(user=self.admin).key}'
        )

    def _validate(self):
        return self.client.post(reverse('inventory-validate', args=[self.inventory.id]))

    def _instance(self, pending=0, last_seen_minutes_ago=1):
        return SyncInstance.objects.create(
            organisation=self.organisation,
            name='Poste caisse',
            pending_operations=pending,
            last_seen_at=timezone.now() - timedelta(minutes=last_seen_minutes_ago),
        )

    def test_la_validation_est_refusee_si_des_ventes_attendent(self):
        self._instance(pending=3)

        response = self._validate()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'bar_not_synced')
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 50, 'Le stock a ete ecrase malgre le refus')

    def test_la_validation_est_refusee_si_le_bar_n_a_pas_donne_signe_de_vie(self):
        """L'absence de nouvelles n'est pas une preuve que le bar n'a rien vendu : il peut etre
        en plein service hors-ligne, et son dernier compteur connu ne vaut plus rien."""
        self._instance(pending=0, last_seen_minutes_ago=120)

        response = self._validate()

        self.assertEqual(response.status_code, 409)
        self.assertIn('aucun contact recent', response.data['detail'])

    def test_la_validation_passe_quand_le_bar_est_a_jour(self):
        self._instance(pending=0, last_seen_minutes_ago=1)

        response = self._validate()

        self.assertEqual(response.status_code, 200, response.data)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 48)

    def test_une_instance_revoquee_ne_bloque_plus_rien(self):
        """Un poste mis hors service ne doit pas geler indefiniment les inventaires."""
        instance = self._instance(pending=5)
        instance.is_active = False
        instance.save()

        response = self._validate()

        self.assertEqual(response.status_code, 200, response.data)

    def test_sans_instance_locale_le_comportement_reste_celui_d_avant(self):
        """Non-regression : un etablissement entierement dans le cloud n'est pas concerne."""
        response = self._validate()

        self.assertEqual(response.status_code, 200, response.data)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 48)

    def test_seul_l_etablissement_concerne_est_pris_en_compte(self):
        """Un autre bar en retard ne doit pas bloquer les inventaires de celui-ci."""
        autre = Organisation.objects.create(name=f'Autre {uuid.uuid4()}')
        SyncInstance.objects.create(
            organisation=autre, name='Poste voisin', pending_operations=10,
            last_seen_at=timezone.now(),
        )

        response = self._validate()

        self.assertEqual(response.status_code, 200, response.data)


class AdminRemoteCorrectionGuardTests(TestCase):
    """Corrections a distance sur une vente du bar.

    Annuler une vente ou retirer une ligne recredite le stock et reecrit des montants. Fait
    depuis le serveur central pendant qu'un bar encaisse hors-ligne, cela diverge de ce que le
    bar enregistre de son cote - sans moyen de reconcilier les deux versions ensuite."""

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

    def _bar_behind(self):
        return SyncInstance.objects.create(
            organisation=self.organisation, name='Poste caisse',
            pending_operations=2, last_seen_at=timezone.now(),
        )

    def test_annuler_une_vente_est_refuse_si_le_bar_est_en_retard(self):
        self._bar_behind()

        response = self.client.post(reverse('order-cancel', args=[self.order.id]))

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'bar_not_synced')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'fermee')

    def test_annuler_une_vente_reste_possible_quand_le_bar_est_a_jour(self):
        SyncInstance.objects.create(
            organisation=self.organisation, name='Poste caisse',
            pending_operations=0, last_seen_at=timezone.now(),
        )

        response = self.client.post(reverse('order-cancel', args=[self.order.id]))

        self.assertEqual(response.status_code, 200, response.data)

    def test_retirer_une_ligne_est_refuse_si_le_bar_est_en_retard(self):
        self._bar_behind()
        item = self.order.items.first()

        response = self.client.delete(
            reverse('order-item-delete', args=[self.order.id, item.id])
        )

        self.assertEqual(response.status_code, 409)
        item.refresh_from_db()
        self.assertFalse(item.is_removed)

    def test_une_remontee_du_bar_n_est_jamais_bloquee_par_ce_garde_fou(self):
        """Le piege de ce mecanisme, et le plus couteux.

        L'annulation faite par l'admin SUR PLACE est capturee puis rejouee vers le cloud - elle
        passe donc par l'endpoint qui porte le garde-fou. Or une instance qui rejoue declare
        forcement qu'il lui reste des operations : sans exemption, elle se bloquerait elle-meme,
        l'annulation partirait en quarantaine, et on perdrait exactement ce que ce mecanisme est
        cense proteger."""
        instance = self._bar_behind()

        pushing = APIClient()
        pushing.credentials(
            HTTP_AUTHORIZATION=f'Instance {instance.token}',
            HTTP_X_ACTING_USER=str(self.admin.id),
            HTTP_X_PENDING_OPERATIONS='5',
        )
        response = pushing.post(reverse('order-cancel', args=[self.order.id]))

        self.assertEqual(response.status_code, 200, response.data)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'annulee')


class InstanceStatusViewTests(TestCase):
    """Etat de synchronisation expose a l'admin.

    Un bar hors-ligne depuis deux heures affiche un chiffre d'affaires en baisse qui n'a rien de
    reel. L'admin doit pouvoir le savoir avant d'en tirer des conclusions."""

    def setUp(self):
        self.organisation = Organisation.objects.create(name=f'Org {uuid.uuid4()}')
        self.admin = User.objects.create(
            organisation=self.organisation, role='admin', name='Admin',
            phone=f'{uuid.uuid4().int % 10**9:09d}',
        )
        self.client = APIClient()
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Token {Token.objects.create(user=self.admin).key}'
        )

    def test_un_bar_a_jour_est_signale_comme_tel(self):
        SyncInstance.objects.create(
            organisation=self.organisation, name='Poste caisse',
            pending_operations=0, last_seen_at=timezone.now(),
        )

        response = self.client.get(reverse('sync-etat'))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['up_to_date'])
        self.assertEqual(response.data['instances'][0]['name'], 'Poste caisse')

    def test_un_bar_en_retard_est_signale_avec_sa_raison(self):
        SyncInstance.objects.create(
            organisation=self.organisation, name='Poste caisse',
            pending_operations=4, last_seen_at=timezone.now(),
        )

        response = self.client.get(reverse('sync-etat'))

        self.assertFalse(response.data['up_to_date'])
        self.assertIn('4 operation(s) en attente', response.data['instances'][0]['reason'])

    def test_un_bar_silencieux_est_signale(self):
        SyncInstance.objects.create(
            organisation=self.organisation, name='Poste caisse',
            pending_operations=0, last_seen_at=timezone.now() - timedelta(hours=2),
        )

        response = self.client.get(reverse('sync-etat'))

        self.assertFalse(response.data['up_to_date'])
        self.assertIn('aucun contact recent', response.data['instances'][0]['reason'])

    def test_un_etablissement_sans_instance_est_considere_a_jour(self):
        """Un bar entierement dans le cloud n'a rien a synchroniser."""
        response = self.client.get(reverse('sync-etat'))

        self.assertTrue(response.data['up_to_date'])
        self.assertEqual(response.data['instances'], [])

    def test_l_etat_d_un_autre_etablissement_n_est_pas_expose(self):
        autre = Organisation.objects.create(name=f'Autre {uuid.uuid4()}')
        SyncInstance.objects.create(
            organisation=autre, name='Poste voisin', pending_operations=9,
            last_seen_at=timezone.now(),
        )

        response = self.client.get(reverse('sync-etat'))

        self.assertTrue(response.data['up_to_date'])
        self.assertEqual(response.data['instances'], [])

    def test_un_caissier_n_y_a_pas_acces(self):
        caissier = User.objects.create(
            organisation=self.organisation, role='caissier', name='Caissier',
            phone=f'{uuid.uuid4().int % 10**9:09d}',
        )
        client = APIClient()
        client.credentials(
            HTTP_AUTHORIZATION=f'Token {Token.objects.create(user=caissier).key}'
        )

        response = client.get(reverse('sync-etat'))

        self.assertEqual(response.status_code, 403)


@override_settings(INSTANCE_ROLE='local', IS_LOCAL_INSTANCE=True)
class GardeFouSurLePosteDuBarTests(TestCase):
    """Le garde-fou anti-corrections ne doit PAS s'appliquer sur le poste du bar.

    Il protege le serveur central contre des corrections portant sur des donnees qu'un bar est
    peut-etre en train de modifier hors-ligne. Sur le poste, le bar EST cette autorite. Applique
    la aussi, il empechait l'admin present sur place d'annuler quoi que ce soit - la ligne
    d'instance locale n'ayant jamais de contact recent avec elle-meme."""

    def setUp(self):
        self.organisation = Organisation.objects.create(name=f'Org {uuid.uuid4()}')
        self.admin = User.objects.create(
            organisation=self.organisation, role='admin', name='Admin sur place',
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
        self.order = Order.objects.create(
            organisation=self.organisation, department=self.department,
            status='fermee', number_of_customers=1, total_amount=2000,
        )
        OrderItem.objects.create(
            order=self.order, product=self.product, quantity=2, unit_price=1000,
        )
        # Le poste se reconnait lui-meme, sans contact recent : c'est l'etat normal d'une
        # instance locale, et c'est precisement ce qui declenchait le refus.
        SyncInstance.objects.create(
            organisation=self.organisation, name='Instance locale',
            pending_operations=0, last_seen_at=None,
        )
        self.client = APIClient()
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Token {Token.objects.create(user=self.admin).key}'
        )

    def test_l_admin_peut_annuler_une_vente_depuis_le_poste(self):
        response = self.client.post(reverse('order-cancel', args=[self.order.id]))

        self.assertEqual(response.status_code, 200, getattr(response, 'data', response.content))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'annulee')
