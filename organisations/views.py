from django.utils import timezone
from django.db import transaction
from django.db.models import Sum
from rest_framework import generics, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from .models import Organisation, Department, BusinessDay, CashierDayBalance
from .serializers import (
    OrganisationSerializer, OrganisationAdminUpdateSerializer,
    DepartmentSerializer, BusinessDaySerializer
)
from .permissions import IsSuperAdmin, IsAdminOrSuperAdmin

class OrganisationMineView(generics.ListAPIView):
    """Lecture seule de SA PROPRE organisation - jamais une liste d'organisations tierces (un
    superadmin cote app metier ne gere que la sienne). La creation d'une organisation est
    reservee a la console systeme (acteur editeur separe, voir console/views.py) - ce chemin
    n'accepte plus de POST du tout, conforme a la decision D4/architecture verrouillee avec
    l'utilisateur."""
    serializer_class = OrganisationSerializer
    permission_classes = [IsSuperAdmin]

    def get_queryset(self):
        return Organisation.objects.filter(pk=self.request.user.organisation_id)

class OrganisationDetailView(generics.RetrieveUpdateAPIView):
    """RetrieveUpdateAPIView (pas Destroy) : une organisation ne se supprime jamais, seulement
    via l'archivage cote console (CONSOLE-SYSTEME.md, interdit explicite). Le queryset est
    scope a la propre organisation de l'utilisateur - avant ce correctif, n'importe quel
    admin/superadmin authentifie pouvait lire/modifier/supprimer N'IMPORTE QUELLE organisation
    par UUID (permission_classes ne verifiait que le role, jamais la propriete de l'objet)."""
    permission_classes = [IsAdminOrSuperAdmin]

    def get_queryset(self):
        return Organisation.objects.filter(pk=self.request.user.organisation_id)

    def get_serializer_class(self):
        if self.request.user.role == 'admin':
            return OrganisationAdminUpdateSerializer
        return OrganisationSerializer

class DepartmentListCreateView(generics.ListCreateAPIView):
    serializer_class = DepartmentSerializer

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated()]
        return [IsAdminOrSuperAdmin()]

    def get_queryset(self):
        if self.request.user.role == 'approvisionneur':
            return self.request.user.departments.filter(is_active=True)
        return Department.objects.filter(organisation=self.request.user.organisation)

    def perform_create(self, serializer):
        # Toujours l'organisation du createur, y compris pour un superadmin - avant ce
        # correctif, un superadmin pouvait passer un 'organisation' arbitraire dans le corps de
        # la requete et creer un departement dans N'IMPORTE QUELLE organisation. Le fallback
        # "aucune organisation -> en creer/reutiliser une au hasard" a aussi ete retire : c'etait
        # un reliquat d'avant que les organisations soient obligatoires, incompatible avec le
        # modele multi-organisation actuel (auto-attacherait un superadmin orphelin aux donnees
        # de la premiere organisation de toute la plateforme).
        organisation = self.request.user.organisation
        if not organisation:
            raise ValidationError({
                'organisation': 'Utilisateur sans organisation. Assignez une organisation avant de creer un departement.'
            })
        name = serializer.validated_data.get('name')
        if Department.objects.filter(organisation=organisation, name=name).exists():
            raise ValidationError({
                'name': 'Un departement avec ce nom existe deja pour cette organisation.'
            })
        serializer.save(organisation=organisation)

class DepartmentDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = DepartmentSerializer

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated()]
        return [IsAdminOrSuperAdmin()]

    def get_queryset(self):
        if self.request.user.role == 'approvisionneur':
            return self.request.user.departments.filter(is_active=True)
        return Department.objects.filter(organisation=self.request.user.organisation)

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save()


class BusinessDayCurrentView(APIView):
    """Etat de la journee en cours - accessible a tous les roles authentifies (lecture seule)
    pour que le mobile/web puisse afficher un message clair quand la journee est fermee, sans
    avoir besoin d'etre admin juste pour consulter l'etat."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        current = BusinessDay.objects.filter(
            organisation=request.user.organisation, is_open=True
        ).first()
        if not current:
            return Response({'is_open': False})
        return Response(BusinessDaySerializer(current).data)


class BusinessDayOpenView(APIView):
    """L'admin ouvre la journee en precisant le fond de caisse de depart de CHAQUE caissier
    (chacun a son propre tiroir-caisse physique, d'ou un montant par caissier plutot qu'un
    montant global) - bloque si une journee est deja ouverte."""
    permission_classes = [IsAdminOrSuperAdmin]

    @transaction.atomic
    def post(self, request):
        from users.models import User

        if BusinessDay.objects.filter(organisation=request.user.organisation, is_open=True).exists():
            return Response(
                {'detail': 'Une journee est deja ouverte.'}, status=status.HTTP_400_BAD_REQUEST
            )

        opening_amounts = request.data.get('opening_amounts') or {}
        if not isinstance(opening_amounts, dict):
            return Response(
                {'detail': "Format invalide : opening_amounts doit etre un objet {id_caissier: montant}."},
                status=status.HTTP_400_BAD_REQUEST
            )

        cashiers = list(User.objects.filter(
            organisation=request.user.organisation, role='caissier', is_active=True
        ))
        parsed_amounts = {}
        for cashier in cashiers:
            raw = opening_amounts.get(str(cashier.id), 0)
            try:
                parsed_amounts[cashier.id] = float(raw)
            except (TypeError, ValueError):
                return Response(
                    {'detail': f'Montant de depart invalide pour {cashier.name}.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        day = BusinessDay.objects.create(
            organisation=request.user.organisation,
            date=timezone.now().date(),
            is_open=True,
            opened_at=timezone.now(),
            opened_by=request.user,
        )
        balances = CashierDayBalance.objects.bulk_create([
            CashierDayBalance(business_day=day, cashier=cashier, opening_amount=parsed_amounts[cashier.id])
            for cashier in cashiers
        ])

        from orders.models import Transaction
        Transaction.objects.bulk_create([
            Transaction(
                organisation=request.user.organisation,
                transaction_type='fond_caisse',
                number=str(balance.id),
                amount=balance.opening_amount,
                author=request.user,
            )
            for balance in balances
        ])

        return Response(BusinessDaySerializer(day).data, status=status.HTTP_201_CREATED)


class BusinessDayCloseView(APIView):
    """L'admin ferme la journee en cours : calcule et fige le solde de fermeture de chaque
    caissier (fond de depart + ventes encaissees - sorties de caisse depuis l'ouverture de la
    session - voir CashierDayBalance), puis bloque toute nouvelle action des roles non-admin
    jusqu'a la prochaine ouverture (voir BusinessDayGateMiddleware)."""
    permission_classes = [IsAdminOrSuperAdmin]

    @transaction.atomic
    def post(self, request):
        from orders.models import Order, CashExpense

        current = BusinessDay.objects.filter(
            organisation=request.user.organisation, is_open=True
        ).first()
        if not current:
            return Response(
                {'detail': 'Aucune journee ouverte a fermer.'}, status=status.HTTP_400_BAD_REQUEST
            )

        for balance in current.cashier_balances.all():
            revenue = Order.objects.filter(
                cashier=balance.cashier, status='fermee', closed_at__gte=current.opened_at
            ).aggregate(total=Sum('total_amount'))['total'] or 0
            expenses = CashExpense.objects.filter(
                cashier=balance.cashier, created_at__gte=current.opened_at, is_deleted=False
            ).aggregate(total=Sum('amount'))['total'] or 0
            balance.closing_amount = balance.opening_amount + revenue - expenses
            balance.save()

        current.is_open = False
        current.closed_at = timezone.now()
        current.closed_by = request.user
        current.save()
        return Response(BusinessDaySerializer(current).data)


class LicenceEtatView(APIView):
    """Etat de licence minimal (statut/jours_restants/message), pour le bandeau d'alerte -
    accessible a TOUT role authentifie, contrairement a OrganisationAbonnementView
    (formules + coordonnees de paiement, reserve a admin/superadmin) : le document precise que
    le bandeau s'affiche sur CHAQUE ecran, pas seulement ceux du supadmin."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from console.services.licence import ServiceLicence

        organisation = request.user.organisation
        if not organisation:
            return Response({'statut': 'en_attente', 'jours_restants': None, 'message': None})
        return Response(ServiceLicence.etat(organisation))


class OrganisationAbonnementView(APIView):
    """Ecran 'Abonnement' cote supadmin (CONSOLE-SYSTEME.md section 7) - un des 2 seuls ecrans
    exemptes du blocage par licence (voir console.middleware.LicenceGateMiddleware.EXEMPT_PREFIXES).
    Vit dans organisations (auth metier existante), pas dans console (auth editeur separee)."""
    permission_classes = [IsAdminOrSuperAdmin]

    def get(self, request):
        from django.conf import settings
        from console.models import Formule
        from console.serializers import FormuleSerializer
        from console.services.licence import ServiceLicence

        organisation = request.user.organisation
        if not organisation:
            return Response({'detail': 'Utilisateur sans organisation.'}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'etat': ServiceLicence.etat(organisation),
            'formules': FormuleSerializer(Formule.objects.filter(active=True).order_by('montant_xaf'), many=True).data,
            'coordonnees_paiement': getattr(settings, 'EDITEUR_COORDONNEES_PAIEMENT', {}),
        })


class OrganisationActiverCodeView(APIView):
    """Champ de saisie de code, partage par les ecrans Abonnement et Blocage (meme
    implementation cote frontend, voir shared/components/code-entry). N'accepte que le code
    en entree - date_expiration/duree_jours ne viennent jamais du client (voir
    ServiceLicence.consommer_code), pour qu'un supadmin ne puisse jamais modifier sa propre
    date d'expiration par un autre chemin que la verification serveur du code."""
    permission_classes = [IsAdminOrSuperAdmin]

    def post(self, request):
        from console.exceptions import ErreurLicence
        from console.services.code_format import CodeMalforme
        from console.services.licence import ServiceLicence

        organisation = request.user.organisation
        if not organisation:
            return Response({'detail': 'Utilisateur sans organisation.'}, status=status.HTTP_400_BAD_REQUEST)

        code = request.data.get('code', '')
        try:
            ServiceLicence.consommer_code(organisation, code)
        except (ErreurLicence, CodeMalforme) as e:
            return Response({'detail': str(e) or 'Code invalide.'}, status=status.HTTP_400_BAD_REQUEST)

        return Response({'etat': ServiceLicence.etat(organisation)})


class BusinessDayHistoryView(generics.ListAPIView):
    """Historique des journees passees, avec le solde d'ouverture/fermeture de chaque
    caissier - reserve a l'admin."""
    serializer_class = BusinessDaySerializer
    permission_classes = [IsAdminOrSuperAdmin]

    def get_queryset(self):
        return BusinessDay.objects.filter(organisation=self.request.user.organisation, is_open=False)
