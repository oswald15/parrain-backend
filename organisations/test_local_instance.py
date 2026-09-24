import uuid
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from organisations.models import BusinessDay, Organisation
from users.models import User


class BusinessDayLocalInstanceTests(TestCase):
    """Ouvrir la journee depuis le bar, sans internet.

    Sur le serveur central, seul l'admin ouvre la journee. Mais l'instance installee dans le bar
    doit permettre au caissier de le faire : sinon une coupure d'internet a l'heure d'ouverture
    paralyserait le point de vente toute la journee - exactement ce que cette instance existe
    pour eviter. Tant qu'aucune journee n'est ouverte, `BusinessDayGateMiddleware` refuse toute
    ecriture des roles non-admin : le bar serait totalement gele."""

    def setUp(self):
        self.organisation = Organisation.objects.create(name=f'Org {uuid.uuid4()}')
        self.caissier = User.objects.create(
            organisation=self.organisation, role='caissier', name='Caissier',
            phone=f'{uuid.uuid4().int % 10**9:09d}',
        )
        self.serveuse = User.objects.create(
            organisation=self.organisation, role='serveur', name='Serveuse',
            phone=f'{uuid.uuid4().int % 10**9:09d}',
        )
        self.client = APIClient()

    def _open_day(self, user):
        self.client.force_authenticate(user=user)
        return self.client.post(
            reverse('business-day-open'),
            {'opening_amounts': {str(self.caissier.id): 10000}},
            format='json',
        )

    @override_settings(INSTANCE_ROLE='local', IS_LOCAL_INSTANCE=True)
    def test_le_caissier_ouvre_la_journee_sur_une_instance_locale(self):
        response = self._open_day(self.caissier)

        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(
            BusinessDay.objects.filter(organisation=self.organisation, is_open=True).exists()
        )

    @override_settings(INSTANCE_ROLE='cloud', IS_LOCAL_INSTANCE=False)
    def test_le_caissier_ne_peut_pas_ouvrir_la_journee_sur_le_serveur_central(self):
        """Le comportement du cloud ne change pas : l'ouverture y reste une decision d'admin."""
        response = self._open_day(self.caissier)

        self.assertEqual(response.status_code, 403)
        self.assertFalse(BusinessDay.objects.filter(organisation=self.organisation).exists())

    @override_settings(INSTANCE_ROLE='local', IS_LOCAL_INSTANCE=True)
    def test_la_serveuse_ne_peut_pas_ouvrir_la_journee_meme_en_local(self):
        """L'assouplissement vise le caissier, qui tient la caisse - pas tout le personnel."""
        response = self._open_day(self.serveuse)

        self.assertEqual(response.status_code, 403)

    @override_settings(INSTANCE_ROLE='local', IS_LOCAL_INSTANCE=True)
    def test_le_caissier_ferme_la_journee_sur_une_instance_locale(self):
        now = timezone.now()
        BusinessDay.objects.create(
            organisation=self.organisation, date=now.date(), is_open=True, opened_at=now,
        )

        self.client.force_authenticate(user=self.caissier)
        response = self.client.post(reverse('business-day-close'), {}, format='json')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(
            BusinessDay.objects.filter(organisation=self.organisation, is_open=True).exists()
        )

    @override_settings(INSTANCE_ROLE='cloud', IS_LOCAL_INSTANCE=False)
    def test_l_admin_ouvre_toujours_la_journee_sur_le_serveur_central(self):
        """Non-regression : le fonctionnement actuel doit rester intact."""
        admin = User.objects.create(
            organisation=self.organisation, role='admin', name='Admin',
            phone=f'{uuid.uuid4().int % 10**9:09d}',
        )

        response = self._open_day(admin)

        self.assertEqual(response.status_code, 201, response.data)
        balance = BusinessDay.objects.get().cashier_balances.get(cashier=self.caissier)
        self.assertEqual(balance.opening_amount, Decimal('10000'))
