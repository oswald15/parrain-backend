"""Cree un etablissement complet pour eprouver le mecanisme d'instance locale.

Une repetition demande un etablissement avec des produits, des departements et du personnel -
et surtout pas un vrai client, puisqu'elle y cree de vraies ventes qu'il faudrait ensuite
demeler de sa comptabilite.

Monter tout cela a la main dans la console prend un quart d'heure et se rate facilement. Cette
commande le fait en une fois, et se relance a l'identique.

Refuse d'ecrire dans un etablissement existant : c'est la seule protection entre une repetition
et les donnees d'un client.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from organisations.models import Department, Organisation
from products.models import DepartmentStock, Product
from users.models import User
from users.phone import normalize_phone


class Command(BaseCommand):
    help = "Cree un etablissement de test complet (departement, produit, personnel)."

    def add_arguments(self, parser):
        parser.add_argument('--nom', required=True, help="Nom de l'etablissement de test.")
        parser.add_argument(
            '--mot-de-passe', required=True,
            help=(
                "Mot de passe des trois comptes crees. Volontairement sans valeur par defaut : "
                "un mot de passe connu code en dur sur un serveur de production serait une "
                "porte d'entree qu'on oublierait de refermer."
            ),
        )
        parser.add_argument(
            '--stock', type=int, default=500,
            help='Quantite du produit de test (defaut: 500).',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if settings.IS_LOCAL_INSTANCE:
            raise CommandError(
                "Cette commande s'execute sur le serveur central. Sur le poste d'un bar, les "
                "etablissements descendent du referentiel et ne se creent pas sur place."
            )

        nom = options['nom'].strip()
        if Organisation.objects.filter(name=nom).exists():
            raise CommandError(
                f'"{nom}" existe deja. Cette commande refuse d\'ecrire dans un etablissement '
                "existant : une repetition y creerait de vraies ventes, a demeler ensuite de sa "
                "comptabilite. Choisir un autre nom."
            )

        organisation = Organisation.objects.create(name=nom)
        departement = Department.objects.create(
            organisation=organisation, name='Bar', is_active=True
        )

        produit = Product.objects.create(
            organisation=organisation, name='Castel', code='TEST-01',
            price=1000, purchase_price=600, stock_quantity=options['stock'],
            shared_stock=False, is_active=True,
        )
        DepartmentStock.objects.create(
            organisation=organisation, department=departement, product=produit,
            quantity=options['stock'], weighted_average_cost=600, sale_price=1000,
        )

        admin = self._creer(organisation, departement, 'admin', 'Admin test',
                            options['mot_de_passe'])
        caissier = self._creer(organisation, departement, 'caissier', 'Caissier test',
                               options['mot_de_passe'])
        serveuse = self._creer(organisation, departement, 'serveur', 'Serveuse test',
                               options['mot_de_passe'])
        serveuse.assigned_cashier = caissier
        serveuse.save(update_fields=['assigned_cashier'])

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'Etablissement de test cree : {organisation.name}'))
        self.stdout.write('')
        self.stdout.write('  Comptes (meme mot de passe pour les trois) :')
        for role, compte in (('admin', admin), ('caissier', caissier), ('serveuse', serveuse)):
            self.stdout.write(f'    {role:9} {compte.phone}')
        self.stdout.write('')
        self.stdout.write(f'  Produit : {produit.name}, {options["stock"]} en stock, '
                          f'departement {departement.name}')
        self.stdout.write('')
        self.stdout.write('  Etape suivante - creer le jeton du poste :')
        self.stdout.write(f'    python manage.py creer_instance --organisation "{organisation.name}"')
        self.stdout.write('')
        self.stdout.write(self.style.WARNING(
            "  A supprimer une fois la repetition terminee : ces comptes partagent un mot de "
            "passe et n'ont aucune raison de survivre sur un serveur de production."
        ))

    def _creer(self, organisation, departement, role, nom, mot_de_passe):
        """Numero pris dans une plage dediee, en cherchant le premier libre.

        Les numeros sont normalises en +237... a l'enregistrement : les creer bruts donnerait des
        comptes impossibles a utiliser, la connexion normalisant ce qu'on lui saisit.
        """
        for suffixe in range(1, 1000):
            telephone = normalize_phone(f'69900{suffixe:04d}')
            if not User.objects.filter(phone=telephone).exists():
                break
        else:
            raise CommandError('Plus aucun numero libre dans la plage de test.')

        compte = User.objects.create(
            organisation=organisation, role=role, name=nom,
            phone=telephone, is_active=True,
        )
        compte.set_password(mot_de_passe)
        compte.save()
        compte.departments.add(departement)
        return compte
