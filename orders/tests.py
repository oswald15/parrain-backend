import uuid

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from orders.models import CashExpense, Transaction
from organisations.models import BusinessDay, Organisation
from sync.models import IdempotencyRecord
from users.models import User


class CashExpenseIdempotencyTests(TestCase):
    """Valide la cle d'idempotence sur une vraie vue metier, effets de bord compris.

    Une sortie de caisse cree DEUX objets (la depense et sa Transaction au journal) : rejouer
    la requete sans protection en creerait deux de chaque, faussant la caisse du caissier."""

    def setUp(self):
        self.organisation = Organisation.objects.create(name=f'Org {uuid.uuid4()}')
        self.cashier = User.objects.create(
            organisation=self.organisation, role='caissier', name='Caissier Test',
            phone=f'{uuid.uuid4().int % 10**9:09d}',
        )
        BusinessDay.objects.create(
            organisation=self.organisation, date=timezone.now().date(),
            is_open=True, opened_at=timezone.now(),
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.cashier)
        self.payload = {
            'expense_type': 'achat',
            'motif': 'Achat de glace',
            'label': 'Glace',
            'amount': '5000.00',
        }

    def _post(self, key):
        return self.client.post(
            '/api/orders/cash-expenses/', self.payload, format='json', HTTP_IDEMPOTENCY_KEY=key
        )

    def test_rejeu_ne_cree_quune_seule_depense_et_une_seule_transaction(self):
        key = str(uuid.uuid4())

        first = self._post(key)
        second = self._post(key)

        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 201, second.data)
        # Comparaison sur le JSON decode, pas sur les octets : PostgreSQL stocke le corps
        # memorise en `jsonb`, qui reordonne les cles. Le contenu rendu au client est donc
        # identique, mais pas l'ordre d'apparition des cles - lequel n'a aucune valeur
        # contractuelle en JSON.
        self.assertEqual(second.json(), first.json())
        self.assertEqual(CashExpense.objects.count(), 1)
        self.assertEqual(Transaction.objects.filter(transaction_type='sortie_caisse').count(), 1)
        self.assertEqual(IdempotencyRecord.objects.count(), 1)

    def test_deux_depenses_distinctes_restent_deux_depenses(self):
        """Garde-fou : deux vraies sorties de caisse identiques mais volontairement distinctes
        (memes montant et motif) doivent bien etre enregistrees deux fois."""
        self._post(str(uuid.uuid4()))
        self._post(str(uuid.uuid4()))

        self.assertEqual(CashExpense.objects.count(), 2)
        self.assertEqual(Transaction.objects.filter(transaction_type='sortie_caisse').count(), 2)

    def test_sans_cle_le_comportement_reste_inchange(self):
        self.client.post('/api/orders/cash-expenses/', self.payload, format='json')
        self.client.post('/api/orders/cash-expenses/', self.payload, format='json')

        self.assertEqual(CashExpense.objects.count(), 2)
        self.assertEqual(IdempotencyRecord.objects.count(), 0)
