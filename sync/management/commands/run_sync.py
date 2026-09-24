"""Synchronisation continue d'une instance installee dans un bar.

Remonte les operations au fil de l'eau et rafraichit le referentiel. Concu pour tourner en
permanence sur le poste du caissier, demarre avec la machine.

Boucle unique plutot que deux taches planifiees separees : la remontee doit passer AVANT la
descente. Le referentiel ne rapporte les quantites de stock que lorsque plus rien n'attend
d'etre remonte - les enchainer dans cet ordre permet donc de converger des le premier tour,
la ou deux taches independantes pourraient se croiser indefiniment.
"""

import time

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand

DEFAULT_PUSH_INTERVAL = 30
DEFAULT_PULL_EVERY = 10


class Command(BaseCommand):
    help = "Remonte les operations et rafraichit le referentiel, en continu."

    def add_arguments(self, parser):
        parser.add_argument(
            '--interval', type=int, default=DEFAULT_PUSH_INTERVAL,
            help=f'Secondes entre deux remontees (defaut: {DEFAULT_PUSH_INTERVAL}).',
        )
        parser.add_argument(
            '--pull-every', type=int, default=DEFAULT_PULL_EVERY,
            help=(
                'Descendre le referentiel tous les N tours '
                f'(defaut: {DEFAULT_PULL_EVERY}). Les prix changent rarement, inutile de le '
                'recharger aussi souvent que la remontee.'
            ),
        )
        parser.add_argument(
            '--once', action='store_true',
            help='Un seul tour, puis sortie. Utile pour un diagnostic.',
        )

    def handle(self, *args, **options):
        if not settings.IS_LOCAL_INSTANCE:
            self.stderr.write(
                "Cette commande ne s'execute que sur une instance locale (INSTANCE_ROLE=local)."
            )
            return

        turn = 0
        while True:
            turn += 1
            # Une panne de synchronisation ne doit jamais arreter la boucle : le bar continue de
            # travailler, et c'est precisement quand le reseau va mal qu'elle doit persister.
            self._safely('remontee', 'push_upstream')
            # A chaque tour, et non au rythme du referentiel : une vente annulee par l'admin qui
            # continue de figurer dans le resume de caisse fausse ce que le caissier remet en fin
            # de service. Quelques secondes de retard, pas dix minutes.
            self._safely('corrections', 'pull_operations')
            if turn % options['pull_every'] == 1 or options['pull_every'] == 1:
                self._safely('descente', 'pull_referential')

            if options['once']:
                return
            time.sleep(options['interval'])

    def _safely(self, label, command):
        try:
            call_command(command)
        except Exception as error:
            self.stderr.write(f'[{label}] echec ignore : {error}')
