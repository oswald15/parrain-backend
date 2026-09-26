"""Referentiel servi aux instances installees dans les bars.

Une instance locale a besoin de connaitre les produits, les prix, les departements et le
personnel pour fonctionner sans internet. Ces donnees sont modifiees par l'admin dans le serveur
central et DESCENDENT vers les bars ; elles ne remontent jamais en sens inverse, faute de quoi
une copie locale perimee ecraserait le travail de l'admin.
"""

from django.utils import timezone
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from console.models import Abonnement, Formule
from organisations.models import Department
from products.models import Category, DepartmentStock, Product
from organisations.permissions import IsAdminOrSuperAdmin
from users.models import User
from .guards import bars_not_up_to_date
from .models import OperationAbandonnee, PendingDownstreamRequest, SyncInstance


class IsSyncInstance(permissions.BasePermission):
    """Reserve aux instances : ce referentiel expose tout le catalogue et le personnel d'un
    etablissement, il n'a pas a etre joignable avec un simple compte utilisateur."""

    def has_permission(self, request, view):
        return isinstance(request.auth, SyncInstance)


class ReferentialSyncView(APIView):
    """Instantane complet du referentiel d'un etablissement.

    Volontairement complet plutot qu'incremental : le referentiel d'un bar tient en quelques
    centaines de lignes, et la plupart de ces modeles n'ont pas de date de modification sur
    laquelle s'appuyer. Un instantane evite surtout de rater une suppression, qu'un envoi
    incremental naif laisserait vivre indefiniment dans le bar.
    """

    permission_classes = [IsSyncInstance]

    def get(self, request):
        organisation = request.auth.organisation

        return Response({
            'organisation': {
                'id': str(organisation.id),
                'name': organisation.name,
                'statut': organisation.statut,
            },
            'departments': [
                {
                    'id': str(department.id),
                    'name': department.name,
                    'is_active': department.is_active,
                }
                for department in Department.objects.filter(organisation=organisation)
            ],
            'categories': [
                {'id': str(category.id), 'name': category.name}
                for category in Category.objects.filter(organisation=organisation)
            ],
            'products': [
                {
                    'id': str(product.id),
                    'category_id': str(product.category_id) if product.category_id else None,
                    'code': product.code,
                    'name': product.name,
                    'purchase_price': str(product.purchase_price),
                    'price': str(product.price),
                    'image_url': product.image_url,
                    'min_threshold': product.min_threshold,
                    'unit': product.unit,
                    'is_active': product.is_active,
                    'is_consignable': product.is_consignable,
                    'deposit_amount': str(product.deposit_amount),
                    'shared_stock': product.shared_stock,
                    # `stock_quantity` est volontairement absent : c'est une valeur calculee,
                    # que le bar decremente a chaque vente. La descendre ecraserait les ventes
                    # locales pas encore remontees (voir DepartmentStock ci-dessous).
                }
                for product in Product.objects.filter(organisation=organisation)
            ],
            'department_stocks': [
                {
                    'id': str(stock.id),
                    'department_id': str(stock.department_id),
                    'product_id': str(stock.product_id),
                    'sale_price': str(stock.sale_price),
                    'weighted_average_cost': str(stock.weighted_average_cost),
                    'min_threshold': stock.min_threshold,
                    # La quantite accompagne la ligne, mais l'instance locale ne l'applique que
                    # si elle n'a plus rien a remonter - sans quoi elle effacerait de l'ecran des
                    # ventes deja encaissees (voir la commande pull_referential).
                    'quantity': stock.quantity,
                }
                for stock in DepartmentStock.objects.filter(organisation=organisation)
            ],
            'users': [
                {
                    'id': str(user.id),
                    'name': user.name,
                    'phone': user.phone,
                    'role': user.role,
                    'is_active': user.is_active,
                    'assigned_cashier_id': (
                        str(user.assigned_cashier_id) if user.assigned_cashier_id else None
                    ),
                    'department_ids': [str(pk) for pk in user.departments.values_list('id', flat=True)],
                    # Ni mot de passe ni jeton : cette descente sert a resoudre les auteurs des
                    # operations et a afficher le personnel, pas a authentifier localement.
                }
                for user in User.objects.filter(organisation=organisation).prefetch_related('departments')
            ],
            # Referencees par les abonnements (cle etrangere non nulle) : sans elles, la
            # descente echouerait a l'insertion cote bar.
            'formules': [
                {
                    'id': str(formule.id),
                    'libelle': formule.libelle,
                    'duree_jours': formule.duree_jours,
                    'montant_xaf': formule.montant_xaf,
                    'active': formule.active,
                }
                for formule in Formule.objects.filter(
                    abonnements__organisation=organisation
                ).distinct()
            ],
            'abonnements': [
                {
                    'id': str(abonnement.id),
                    'formule_id': str(abonnement.formule_id),
                    'date_debut': abonnement.date_debut.isoformat(),
                    'date_expiration': abonnement.date_expiration.isoformat(),
                    'montant_xaf': abonnement.montant_xaf,
                    'statut': abonnement.statut,
                }
                # Descendus pour que le bar applique lui-meme l'expiration de licence, sans
                # avoir a joindre le serveur central (voir console/services/licence.py).
                for abonnement in Abonnement.objects.filter(organisation=organisation)
            ],
        })


class DownstreamOperationsView(APIView):
    """Corrections faites par l'admin que le bar n'a pas encore appliquees.

    Le parametre `after` sert a la fois de curseur et d'accuse de reception : demander ce qui
    suit l'operation N, c'est declarer que N est appliquee. Un seul aller-retour, et une lecture
    - donc aucune action a imputer a un employe, la ou un POST d'acquittement en aurait exige un
    pour une simple confirmation technique.
    """

    permission_classes = [IsSyncInstance]
    # Volontairement borne : une instance rallumee apres plusieurs jours rattrape son retard en
    # plusieurs passes plutot que de charger tout l'historique d'un coup.
    PAGE_SIZE = 100

    def get(self, request):
        instance = request.auth
        after = self._cursor(request, instance)

        if after > instance.last_downstream_id:
            SyncInstance.objects.filter(pk=instance.pk).update(last_downstream_id=after)

        operations = PendingDownstreamRequest.objects.filter(
            organisation=instance.organisation, pk__gt=after
        ).order_by('pk')[:self.PAGE_SIZE]

        return Response({
            'operations': [
                {
                    'id': operation.pk,
                    'method': operation.method,
                    'path': operation.path,
                    'query_string': operation.query_string,
                    'body': operation.body,
                    'acting_user_id': (
                        str(operation.user_id) if operation.user_id else None
                    ),
                }
                for operation in operations
            ],
        })

    def _cursor(self, request, instance):
        raw = request.query_params.get('after', '')
        if raw.isdigit():
            return int(raw)
        # Sans curseur declare, on repart de ce que le serveur avait enregistre : une instance
        # reinstallee ne doit pas rejouer d'anciennes annulations sur des ventes disparues.
        return instance.last_downstream_id


class InstanceStatusView(APIView):
    """Etat de synchronisation des postes d'un etablissement, pour l'admin.

    Sans cette information, un admin lit des chiffres sans savoir s'ils sont complets : un bar
    hors-ligne depuis deux heures affiche un chiffre d'affaires en baisse qui n'a rien de reel.
    Il pourrait en tirer des conclusions fausses - ou pire, agir dessus.
    """

    permission_classes = [permissions.IsAuthenticated, IsAdminOrSuperAdmin]

    def get(self, request):
        organisation = request.user.organisation
        instances = SyncInstance.objects.filter(organisation=organisation, is_active=True)
        behind = {instance.pk: reason for instance, reason in bars_not_up_to_date(organisation)}

        return Response({
            # Faux des qu'un poste est en retard : c'est ce drapeau que l'interface utilise pour
            # avertir avant d'afficher des montants.
            'up_to_date': not behind,
            'instances': [
                {
                    'id': str(instance.id),
                    'name': instance.name,
                    'last_seen_at': (
                        instance.last_seen_at.isoformat() if instance.last_seen_at else None
                    ),
                    'pending_operations': instance.pending_operations,
                    'up_to_date': instance.pk not in behind,
                    'reason': behind.get(instance.pk),
                }
                for instance in instances
            ],
        })


class OperationsAbandonneesView(APIView):
    """Consommations servies que rien n'a pu enregistrer.

    Deux usages sur la meme adresse : la tablette d'une serveuse les SIGNALE quand elle retrouve
    le serveur central, l'admin les LIT pour les ressaisir.

    Elles n'existaient jusqu'ici que dans le telephone de la serveuse. Tablette perdue ou
    reinstallee, et ces ventes disparaissaient sans que personne ne sache qu'elles avaient
    existe. Rien n'est jamais supprime ici : une fois ressaisie, une ligne est marquee traitee,
    car elle reste la seule trace d'un ecart entre ce qui a ete bu et ce qui a ete comptabilise.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        operations = OperationAbandonnee.objects.filter(
            organisation=request.user.organisation
        ).select_related('user', 'traitee_par')
        # La serveuse ne voit que les siennes : ce sont ses ventes a elle, et la liste complete
        # d'un etablissement n'a d'interet que pour l'admin.
        if request.user.role not in ('admin', 'superadmin'):
            operations = operations.filter(user=request.user)

        return Response({'operations': [self._serialise(o) for o in operations]})

    def post(self, request):
        """Signalement par la tablette. Repetable : la tablette peut reessayer sans creer de
        doublon, l'identifiant etant celui du bon d'origine."""
        entries = request.data.get('operations')
        if not isinstance(entries, list):
            return Response(
                {'detail': "Le corps doit contenir une liste 'operations'."}, status=400
            )

        enregistrees = []
        for entry in entries:
            if not entry.get('id'):
                continue
            operation, _ = OperationAbandonnee.objects.update_or_create(
                id=entry['id'],
                defaults={
                    'organisation': request.user.organisation,
                    'user': request.user,
                    'libelle': str(entry.get('libelle') or '')[:255],
                    'detail': str(entry.get('detail') or ''),
                    'montant': entry.get('montant'),
                    'client_created_at': str(entry.get('client_created_at') or '')[:64],
                    'raw': entry.get('raw'),
                },
            )
            enregistrees.append(str(operation.pk))

        return Response({'enregistrees': enregistrees}, status=201)

    def _serialise(self, operation):
        return {
            'id': str(operation.pk),
            'libelle': operation.libelle,
            'detail': operation.detail,
            'montant': str(operation.montant) if operation.montant is not None else None,
            'client_created_at': operation.client_created_at,
            'serveuse': operation.user.name if operation.user else None,
            'signalee_le': operation.signalee_le.isoformat(),
            'traitee_le': operation.traitee_le.isoformat() if operation.traitee_le else None,
            'traitee_par': operation.traitee_par.name if operation.traitee_par else None,
        }


class OperationAbandonneeTraiterView(APIView):
    """Marque une consommation comme ressaisie. Ne la supprime pas - elle reste la trace de
    l'ecart, et c'est precisement ce qu'on veut pouvoir relire plus tard."""

    permission_classes = [permissions.IsAuthenticated, IsAdminOrSuperAdmin]

    def post(self, request, pk):
        operation = OperationAbandonnee.objects.filter(
            pk=pk, organisation=request.user.organisation
        ).first()
        if operation is None:
            return Response({'detail': 'Introuvable.'}, status=404)

        operation.traitee_le = timezone.now()
        operation.traitee_par = request.user
        operation.save(update_fields=['traitee_le', 'traitee_par'])
        return Response({'id': str(operation.pk), 'traitee_le': operation.traitee_le.isoformat()})


class PostesView(APIView):
    """Postes de l'etablissement, vus et geres par son admin.

    La console de l'editeur les voit deja. Mais attendre l'editeur pour revoquer un poste vole,
    un dimanche soir, n'est pas tenable : le patron doit pouvoir couper lui-meme. C'est cette
    raison-la qui justifie cet ecran, plus que le confort de creer un poste sans appeler.

    Aucun privilege nouveau : un admin a deja acces a toutes les donnees de son etablissement, et
    un jeton ne donne acces qu'a celles-la.

    **Le jeton n'est renvoye qu'a la creation**, comme dans la console - il permet d'agir au nom
    de n'importe quel employe, et une page qui l'affiche en permanence l'expose aux captures
    d'ecran.
    """

    permission_classes = [permissions.IsAuthenticated, IsAdminOrSuperAdmin]

    def get(self, request):
        organisation = request.user.organisation
        behind = {
            instance.pk: reason
            for instance, reason in bars_not_up_to_date(organisation)
        }
        postes = SyncInstance.objects.filter(organisation=organisation)

        return Response({'postes': [
            {
                'id': str(poste.id),
                'nom': poste.name,
                'actif': poste.is_active,
                'cree_le': poste.created_at.isoformat(),
                'dernier_contact': (
                    poste.last_seen_at.isoformat() if poste.last_seen_at else None
                ),
                'operations_en_attente': poste.pending_operations,
                'a_jour': poste.pk not in behind,
                'retard': behind.get(poste.pk),
            }
            for poste in postes
        ]})

    def post(self, request):
        nom = (request.data.get('nom') or 'Poste caisse').strip()[:150]
        poste = SyncInstance.objects.create(
            organisation=request.user.organisation, name=nom
        )
        return Response({
            'id': str(poste.id),
            'nom': poste.name,
            'token': poste.token,
            'avertissement': (
                "Ce jeton ne sera plus affiche. Le recopier maintenant dans le fichier .env du "
                "poste (INSTANCE_TOKEN)."
            ),
        }, status=201)


class PosteRevoquerView(APIView):
    """Coupe un poste immediatement - vol, perte, reinstallation.

    Ne supprime pas la ligne : elle porte le dernier contact et ce qui restait a remonter, deux
    informations qu'on veut encore pouvoir lire apres coup. Et les comptes du personnel ne sont
    pas touches.
    """

    permission_classes = [permissions.IsAuthenticated, IsAdminOrSuperAdmin]

    def post(self, request, pk):
        poste = SyncInstance.objects.filter(
            pk=pk, organisation=request.user.organisation
        ).first()
        if poste is None:
            return Response({'detail': 'Poste introuvable.'}, status=404)

        SyncInstance.objects.filter(pk=poste.pk).update(is_active=False)
        return Response({'id': str(poste.id), 'actif': False})
