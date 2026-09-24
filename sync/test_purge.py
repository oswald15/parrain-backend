import uuid
from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from organisations.models import Organisation
from sync.models import IdempotencyRecord, PendingDownstreamRequest, SyncInstance


class PurgeTests(TestCase):
    """Purge des tables de synchronisation.

    Elles grossissent a chaque vente et a chaque correction. Mais purger trop tot fait
    reapparaitre exactement ce que ces tables empechent : une vente dupliquee, ou une annulation
    qui n'atteint jamais le bar."""

    def setUp(self):
        self.organisation = Organisation.objects.create(name=f'Org {uuid.uuid4()}')

    def _run(self, **options):
        out = StringIO()
        call_command('purge_idempotency', stdout=out, **options)
        return out.getvalue()

    def _age(self, model, pk, days):
        model.objects.filter(pk=pk).update(created_at=timezone.now() - timedelta(days=days))

    def _trace(self, key, days):
        record = IdempotencyRecord.objects.create(
            organisation=self.organisation, key=key, method='POST',
            path='/api/orders/create/', request_fingerprint='x',
        )
        self._age(IdempotencyRecord, record.pk, days)
        return record

    def _correction(self, days=0):
        operation = PendingDownstreamRequest.objects.create(
            organisation=self.organisation, method='POST',
            path='/api/orders/abc/cancel/', body=None,
        )
        self._age(PendingDownstreamRequest, operation.pk, days)
        return operation

    def _instance(self, acked=0):
        return SyncInstance.objects.create(
            organisation=self.organisation, name=f'Poste {uuid.uuid4()}',
            last_downstream_id=acked,
        )

    def test_une_trace_ancienne_est_supprimee(self):
        self._trace('vieille', days=30)

        self._run()

        self.assertFalse(IdempotencyRecord.objects.exists())

    def test_une_trace_recente_est_conservee(self):
        """Elle protege encore : un appareil reste hors-ligne rejouera son action, et sans cette
        trace la vente serait comptee deux fois."""
        self._trace('recente', days=1)

        self._run()

        self.assertEqual(IdempotencyRecord.objects.count(), 1)

    def test_une_correction_appliquee_par_tous_les_postes_est_supprimee(self):
        operation = self._correction()
        self._instance(acked=operation.pk)

        self._run()

        self.assertFalse(PendingDownstreamRequest.objects.exists())

    def test_une_correction_retenue_par_le_poste_le_plus_en_retard(self):
        """Le test qui compte. Un poste eteint deux semaines doit retrouver a son rallumage les
        annulations faites pendant son absence : les purger a l'age les lui ferait perdre en
        silence, et son resume de caisse compterait indefiniment des ventes annulees."""
        operation = self._correction(days=30)
        self._instance(acked=operation.pk)
        self._instance(acked=0)

        self._run()

        self.assertTrue(PendingDownstreamRequest.objects.filter(pk=operation.pk).exists())

    def test_une_correction_qu_aucun_poste_n_a_vue_est_conservee(self):
        self._correction(days=30)
        self._instance(acked=0)

        self._run()

        self.assertEqual(PendingDownstreamRequest.objects.count(), 1)

    def test_un_poste_revoque_ne_retient_plus_rien(self):
        """Sans quoi une instance volee, desactivee depuis la console, figerait la table pour
        toujours."""
        self._correction(days=30)
        instance = self._instance(acked=0)
        SyncInstance.objects.filter(pk=instance.pk).update(is_active=False)

        self._run()

        self.assertFalse(PendingDownstreamRequest.objects.exists())

    def test_sans_poste_actif_la_retention_laisse_le_temps_d_une_reinstallation(self):
        self._correction(days=1)

        self._run()

        self.assertEqual(PendingDownstreamRequest.objects.count(), 1)

    def test_les_etablissements_sont_purges_independamment(self):
        """La borne d'un bar ne doit jamais s'appliquer a un autre : les identifiants de
        corrections sont globaux, un bar tres en avance effacerait les corrections d'un voisin
        qui ne les a pas encore vues."""
        other = Organisation.objects.create(name=f'Org {uuid.uuid4()}')
        mine = self._correction()
        self._instance(acked=mine.pk)
        theirs = PendingDownstreamRequest.objects.create(
            organisation=other, method='POST', path='/api/orders/xyz/cancel/', body=None,
        )
        SyncInstance.objects.create(
            organisation=other, name='Poste voisin', last_downstream_id=0,
        )

        self._run()

        self.assertFalse(PendingDownstreamRequest.objects.filter(pk=mine.pk).exists())
        self.assertTrue(PendingDownstreamRequest.objects.filter(pk=theirs.pk).exists())
