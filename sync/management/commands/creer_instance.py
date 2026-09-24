"""Cree le jeton d'une instance a installer dans un bar.

S'execute sur le SERVEUR CENTRAL, souvent par SSH, au moment d'equiper un etablissement. Une
commande plutot qu'un `shell -c` : la ligne est longue, tapee a distance, et relancee deux fois
elle creerait un second jeton sans rien dire - l'installateur repartirait avec le mauvais.

Ne revoque jamais rien sans qu'on le demande explicitement : un jeton revoque par megarde arrete
un bar en service.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from organisations.models import Organisation
from sync.models import SyncInstance

DEFAULT_NAME = 'Poste caisse'


class Command(BaseCommand):
    help = "Cree (ou remplace) le jeton d'une instance locale pour un etablissement."

    def add_arguments(self, parser):
        parser.add_argument(
            '--organisation',
            help="Nom exact de l'etablissement. Omis, la commande liste les etablissements.",
        )
        parser.add_argument(
            '--nom', default=DEFAULT_NAME,
            help=f'Nom du poste, tel que l\'admin le verra (defaut: "{DEFAULT_NAME}").',
        )
        parser.add_argument(
            '--supplementaire', action='store_true',
            help='Ajouter un second poste a un etablissement qui en a deja un.',
        )
        parser.add_argument(
            '--remplacer', action='store_true',
            help=(
                'Revoquer les postes existants et en creer un neuf. A utiliser si un poste a '
                'ete vole ou reinstalle : les anciens jetons cessent immediatement de marcher.'
            ),
        )

    def handle(self, *args, **options):
        if settings.IS_LOCAL_INSTANCE:
            raise CommandError(
                "Cette commande s'execute sur le serveur central, pas sur le poste d'un bar."
            )

        organisation = self._resolve(options['organisation'])
        existing = SyncInstance.objects.filter(organisation=organisation, is_active=True)

        if existing.exists() and not (options['supplementaire'] or options['remplacer']):
            self.stderr.write(
                f'{organisation.name} a deja {existing.count()} poste(s) actif(s) :'
            )
            for instance in existing:
                self.stderr.write(f'  - {instance.name}')
            raise CommandError(
                'Relancer avec --supplementaire pour ajouter un poste, ou --remplacer pour '
                'revoquer les existants (poste vole ou reinstalle).'
            )

        if options['remplacer']:
            revoked = existing.update(is_active=False)
            self.stdout.write(self.style.WARNING(
                f'{revoked} poste(s) revoque(s) : leurs jetons ne fonctionnent plus.'
            ))

        instance = SyncInstance.objects.create(
            organisation=organisation, name=options['nom']
        )

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Instance creee pour {organisation.name} : {instance.name}'
        ))
        self.stdout.write('')
        self.stdout.write('  INSTANCE_TOKEN=' + instance.token)
        self.stdout.write('')
        self.stdout.write(
            'A recopier dans le .env du poste du caissier (voir INSTANCE_LOCALE.md).'
        )
        # Le jeton n'est affiche qu'ici. Il reste lisible en base, mais le dire evite que
        # l'installateur reparte sans l'avoir note.
        self.stdout.write(
            'Le noter maintenant : cette commande ne le reaffichera pas.'
        )

    def _resolve(self, name):
        """Un nom d'etablissement se tape mal par SSH : mieux vaut lister que deviner."""
        if not name:
            raise CommandError(
                'Preciser --organisation. Etablissements existants :\n'
                + self._catalogue()
            )

        organisation = Organisation.objects.filter(name=name).first()
        if organisation is None:
            raise CommandError(
                f'Aucun etablissement nomme "{name}". Etablissements existants :\n'
                + self._catalogue()
            )
        return organisation

    def _catalogue(self):
        names = Organisation.objects.values_list('name', flat=True).order_by('name')
        if not names:
            return '  (aucun)'
        return '\n'.join(f'  - {name}' for name in names)
