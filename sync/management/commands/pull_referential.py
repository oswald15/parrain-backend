"""Recupere depuis le serveur central le referentiel de l'etablissement.

Produits, prix, departements, personnel et licence sont decides par l'admin dans le cloud. Le
bar en garde une copie locale pour pouvoir travailler sans internet, et la rafraichit des que le
reseau le permet.
"""

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from console.models import Abonnement, Formule
from organisations.models import Department, Organisation
from products.models import Category, DepartmentStock, Product
from sync.local import ensure_local_instance
from sync.models import PendingUpstreamRequest
from users.models import User

TIMEOUT_SECONDS = 30


class Command(BaseCommand):
    help = "Met a jour le referentiel local depuis le serveur central."

    def handle(self, *args, **options):
        if not settings.IS_LOCAL_INSTANCE:
            self.stderr.write(
                "Cette commande ne s'execute que sur une instance locale (INSTANCE_ROLE=local)."
            )
            return
        if not settings.CLOUD_API_URL or not settings.INSTANCE_TOKEN:
            self.stderr.write('CLOUD_API_URL et INSTANCE_TOKEN doivent etre renseignes.')
            return

        url = settings.CLOUD_API_URL.rstrip('/') + '/api/sync/referentiel/'
        try:
            response = requests.get(
                url,
                headers={
                    'Authorization': f'Instance {settings.INSTANCE_TOKEN}',
                    'X-Pending-Operations': str(
                        PendingUpstreamRequest.objects.filter(
                            status=PendingUpstreamRequest.STATUS_PENDING
                        ).count()
                    ),
                },
                timeout=TIMEOUT_SECONDS,
            )
        except requests.RequestException as error:
            self.stderr.write(f'Serveur central injoignable : {error}')
            return

        if response.status_code != 200:
            self.stderr.write(f'Refus du serveur central (HTTP {response.status_code}).')
            return

        payload = response.json()

        # Une descente de referentiel ne doit jamais laisser le bar a moitie mis a jour : des
        # produits sans leur categorie, ou des prix incoherents entre deux departements.
        with transaction.atomic():
            applied_quantities = self._apply(payload)

        self.stdout.write(self.style.SUCCESS(
            'Referentiel mis a jour'
            + ('.' if applied_quantities else " (quantites de stock conservees : des ventes restent a remonter).")
        ))

    def _apply(self, payload):
        organisation = self._upsert_organisation(payload['organisation'])
        # Pose ici plutot qu'a l'installation seule : le poste doit se reconnaitre lui-meme pour
        # appliquer les corrections descendues, et cela doit se reparer tout seul si la base
        # locale a ete recreee entre-temps (voir sync/local.py).
        ensure_local_instance(organisation)

        for item in payload.get('departments', []):
            Department.objects.update_or_create(
                id=item['id'],
                defaults={
                    'organisation': organisation,
                    'name': item['name'],
                    'is_active': item['is_active'],
                },
            )

        for item in payload.get('categories', []):
            Category.objects.update_or_create(
                id=item['id'],
                defaults={'organisation': organisation, 'name': item['name']},
            )

        for item in payload.get('products', []):
            Product.objects.update_or_create(
                id=item['id'],
                defaults={
                    'organisation': organisation,
                    'category_id': item['category_id'],
                    'code': item['code'],
                    'name': item['name'],
                    'purchase_price': item['purchase_price'],
                    'price': item['price'],
                    'image_url': item['image_url'],
                    'min_threshold': item['min_threshold'],
                    'unit': item['unit'],
                    'is_active': item['is_active'],
                    'is_consignable': item['is_consignable'],
                    'deposit_amount': item['deposit_amount'],
                    'shared_stock': item['shared_stock'],
                    # `stock_quantity` jamais ecrase ici : c'est le bar qui le decremente.
                },
            )

        applied_quantities = self._can_apply_quantities()
        for item in payload.get('department_stocks', []):
            defaults = {
                'organisation': organisation,
                'department_id': item['department_id'],
                'product_id': item['product_id'],
                'sale_price': item['sale_price'],
                'weighted_average_cost': item['weighted_average_cost'],
                'min_threshold': item['min_threshold'],
            }
            if applied_quantities:
                defaults['quantity'] = item['quantity']
            stock, created = DepartmentStock.objects.update_or_create(
                id=item['id'], defaults=defaults
            )
            # Une ligne de stock qui apparait (produit nouvellement affecte a un departement)
            # doit bien partir de la quantite du cloud, meme si des ventes attendent : sans
            # cela elle resterait a zero et le produit serait invendable au bar.
            if created and not applied_quantities:
                DepartmentStock.objects.filter(pk=stock.pk).update(quantity=item['quantity'])

        self._upsert_users(payload.get('users', []), organisation)
        self._upsert_licence(payload, organisation)

        return applied_quantities

    def _can_apply_quantities(self):
        """Les quantites ne descendent que si le bar n'a plus rien a remonter.

        Le serveur central ignore encore les ventes en attente : appliquer ses quantites les
        ferait disparaitre de l'ecran, et le caissier verrait un stock superieur au reel pendant
        tout le service. Une fois la file videe, le cloud fait autorite et la descente reprend.
        """
        return not PendingUpstreamRequest.objects.filter(
            status=PendingUpstreamRequest.STATUS_PENDING
        ).exists()

    def _upsert_organisation(self, item):
        organisation, _ = Organisation.objects.update_or_create(
            id=item['id'],
            defaults={'name': item['name'], 'statut': item['statut']},
        )
        return organisation

    def _upsert_users(self, items, organisation):
        for item in items:
            user, _ = User.objects.update_or_create(
                id=item['id'],
                defaults={
                    'organisation': organisation,
                    'name': item['name'],
                    'phone': item['phone'],
                    'role': item['role'],
                    'is_active': item['is_active'],
                },
            )
            user.departments.set(item.get('department_ids', []))

        # Le rattachement caissier est pose dans un second temps : il designe un autre
        # utilisateur, qui peut ne pas encore exister au premier passage de la boucle.
        for item in items:
            User.objects.filter(id=item['id']).update(
                assigned_cashier_id=item.get('assigned_cashier_id')
            )

    def _upsert_licence(self, payload, organisation):
        for item in payload.get('formules', []):
            Formule.objects.update_or_create(
                id=item['id'],
                defaults={
                    'libelle': item['libelle'],
                    'duree_jours': item['duree_jours'],
                    'montant_xaf': item['montant_xaf'],
                    'active': item['active'],
                },
            )

        for item in payload.get('abonnements', []):
            Abonnement.objects.update_or_create(
                id=item['id'],
                defaults={
                    'organisation': organisation,
                    'formule_id': item['formule_id'],
                    'date_debut': item['date_debut'],
                    'date_expiration': item['date_expiration'],
                    'montant_xaf': item['montant_xaf'],
                    'statut': item['statut'],
                },
            )
