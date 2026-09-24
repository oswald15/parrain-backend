from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Min
from django.utils import timezone

from sync.models import IdempotencyRecord, PendingDownstreamRequest, SyncInstance

DEFAULT_RETENTION_DAYS = 7


class Command(BaseCommand):
    help = (
        "Supprime les traces d'idempotence anterieures a la duree de retention, et les "
        "corrections que tous les bars ont appliquees. "
        "A planifier quotidiennement (cron / tache planifiee)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--days', type=int, default=DEFAULT_RETENTION_DAYS,
            help=f'Duree de retention en jours (defaut: {DEFAULT_RETENTION_DAYS}).',
        )

    def handle(self, *args, **options):
        days = options['days']
        # La retention doit couvrir largement la plus longue coupure reseau envisageable : une
        # trace purgee trop tot ferait rejouer - donc dupliquer - une action encore en attente
        # dans la file d'un appareil reste hors-ligne.
        cutoff = timezone.now() - timedelta(days=days)
        deleted, _ = IdempotencyRecord.objects.filter(created_at__lt=cutoff).delete()
        self.stdout.write(self.style.SUCCESS(
            f'{deleted} trace(s) d\'idempotence supprimee(s) (anterieures a {cutoff:%Y-%m-%d %H:%M}).'
        ))

        self.stdout.write(self.style.SUCCESS(
            f'{self._purge_downstream(cutoff)} correction(s) descendue(s) supprimee(s).'
        ))

    def _purge_downstream(self, cutoff):
        """Corrections de l'admin dont plus aucun bar n'a besoin.

        Le critere est l'accuse de reception, PAS l'anciennete : un poste eteint deux semaines
        doit retrouver a son rallumage les annulations faites pendant son absence. Purger a
        l'age les lui ferait perdre en silence, et son resume de caisse compterait indefiniment
        des ventes annulees.

        La borne est le poste le plus en retard de l'etablissement : tant qu'un seul n'a pas
        applique une correction, elle reste.
        """
        deleted = 0
        organisation_ids = PendingDownstreamRequest.objects.values_list(
            'organisation_id', flat=True
        ).distinct()

        for organisation_id in organisation_ids:
            acked = SyncInstance.objects.filter(
                organisation_id=organisation_id, is_active=True
            ).aggregate(borne=Min('last_downstream_id'))['borne']

            queryset = PendingDownstreamRequest.objects.filter(organisation_id=organisation_id)
            if acked is None:
                # Plus aucun poste actif : l'etablissement est repasse entierement dans le cloud,
                # ou son instance a ete revoquee. Personne ne viendra chercher ces corrections -
                # mais on laisse passer la retention, le temps qu'un poste reinstalle se declare.
                deleted += queryset.filter(created_at__lt=cutoff).delete()[0]
            else:
                deleted += queryset.filter(pk__lte=acked).delete()[0]

        return deleted
