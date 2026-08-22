from datetime import timedelta

from django.db.models import Count, Sum
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from organisations.models import Organisation

from .models import Abonnement, CodeActivation, Editeur, EditeurToken, Formule, Journal, Paiement
from .serializers import (
    AbonnementSerializer,
    CodeActivationSerializer,
    EditeurCreateSerializer,
    EditeurLoginSerializer,
    EditeurSerializer,
    EmettreCodeSerializer,
    FormuleSerializer,
    JournalSerializer,
    OrganisationConsoleCreateSerializer,
    OrganisationConsoleDetailSerializer,
    OrganisationConsoleListSerializer,
    PaiementSerializer,
    SuperadminCreateSerializer,
)
from .services.licence import ServiceLicence
from .views_base import (
    EditeurAPIView,
    EditeurListAPIView,
    EditeurListCreateAPIView,
    EditeurRetrieveUpdateAPIView,
)


class EditeurLoginView(APIView):
    """Pas de token a fournir pour se connecter - authentification/permission par defaut de
    DRF (TokenAuthentication global) ne s'applique pas non plus ici : on la coupe explicitement
    pour eviter qu'un token users.User ne soit tente sur cette vue par erreur."""
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = EditeurLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        editeur = serializer.validated_data['editeur']
        token, _ = EditeurToken.objects.get_or_create(editeur=editeur)
        return Response({'token': token.key, 'editeur': EditeurSerializer(editeur).data})


class EditeurLogoutView(EditeurAPIView):
    def post(self, request):
        EditeurToken.objects.filter(editeur=request.user).delete()
        return Response({'message': 'Déconnexion réussie.'})


class OrganisationConsoleListCreateView(EditeurListCreateAPIView):
    def get_queryset(self):
        qs = Organisation.objects.all().order_by('name')
        statut = self.request.query_params.get('statut')
        if statut:
            qs = qs.filter(statut=statut)
        archivee = self.request.query_params.get('archivee')
        if archivee is not None:
            qs = qs.filter(archivee=archivee.lower() == 'true')
        return qs

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return OrganisationConsoleCreateSerializer
        return OrganisationConsoleListSerializer

    def perform_create(self, serializer):
        organisation = serializer.save()
        Journal.objects.create(
            acteur=self.request.user, action='creation_organisation', organisation=organisation,
            details={'name': organisation.name},
        )


class OrganisationConsoleDetailView(EditeurRetrieveUpdateAPIView):
    queryset = Organisation.objects.all()
    serializer_class = OrganisationConsoleDetailSerializer


class OrganisationAbonnementsHistoryView(EditeurListAPIView):
    serializer_class = AbonnementSerializer

    def get_queryset(self):
        return Abonnement.objects.filter(organisation_id=self.kwargs['pk']).order_by('-date_expiration')


class OrganisationCodesHistoryView(EditeurListAPIView):
    serializer_class = CodeActivationSerializer

    def get_queryset(self):
        return CodeActivation.objects.filter(organisation_id=self.kwargs['pk']).order_by('-emis_le')


class SuperadminCreateView(EditeurAPIView):
    """Cree le compte users.User (role=superadmin) d'une organisation et le lie via
    Organisation.supadmin, en une seule action - ferme le flux 'la console cree l'organisation
    ET son premier compte, le reste (employes/departements/catalogue) se gere ensuite depuis
    Administration, cote supadmin lui-meme'."""
    def post(self, request, pk):
        organisation = generics.get_object_or_404(Organisation, pk=pk)
        if organisation.supadmin_id:
            return Response(
                {'detail': 'Cette organisation a déjà un superadmin.'}, status=status.HTTP_400_BAD_REQUEST
            )

        serializer = SuperadminCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        from users.models import User
        user = User.objects.create_user(
            phone=serializer.validated_data['phone'],
            password=serializer.validated_data['password'],
            name=serializer.validated_data['name'],
            role='superadmin',
            organisation=organisation,
        )
        organisation.supadmin = user
        organisation.save(update_fields=['supadmin'])

        Journal.objects.create(
            acteur=request.user, action='creation_superadmin', organisation=organisation,
            details={'nom': user.name, 'phone': user.phone},
        )
        return Response(OrganisationConsoleDetailSerializer(organisation).data, status=status.HTTP_201_CREATED)


class OrganisationSuspendreView(EditeurAPIView):
    def post(self, request, pk):
        organisation = generics.get_object_or_404(Organisation, pk=pk)
        organisation.statut = 'suspendue'
        organisation.save(update_fields=['statut'])
        Journal.objects.create(acteur=request.user, action='suspension', organisation=organisation, details={})
        return Response(OrganisationConsoleDetailSerializer(organisation).data)


class OrganisationReactiverView(EditeurAPIView):
    """Leve une suspension manuelle - ne force PAS le statut a 'active' : ServiceLicence.etat()
    recalcule le vrai statut a partir des abonnements (peut retomber en_grace/bloquee/en_attente
    si aucun abonnement valide n'existe)."""
    def post(self, request, pk):
        organisation = generics.get_object_or_404(Organisation, pk=pk)
        organisation.statut = 'en_attente'  # leve le court-circuit 'suspendue' de etat(), recalcule juste apres
        organisation.save(update_fields=['statut'])
        etat = ServiceLicence.etat(organisation)
        Journal.objects.create(
            acteur=request.user, action='reactivation', organisation=organisation,
            details={'nouveau_statut': etat['statut']},
        )
        return Response(OrganisationConsoleDetailSerializer(organisation).data)


class OrganisationArchiverView(EditeurAPIView):
    def post(self, request, pk):
        organisation = generics.get_object_or_404(Organisation, pk=pk)
        organisation.archivee = True
        organisation.save(update_fields=['archivee'])
        Journal.objects.create(acteur=request.user, action='archivage', organisation=organisation, details={})
        return Response(OrganisationConsoleDetailSerializer(organisation).data)


class FormuleListCreateView(EditeurListCreateAPIView):
    queryset = Formule.objects.all().order_by('libelle')
    serializer_class = FormuleSerializer

    def perform_create(self, serializer):
        formule = serializer.save()
        Journal.objects.create(
            acteur=self.request.user, action='creation_formule', organisation=None,
            details={'libelle': formule.libelle, 'montant_xaf': formule.montant_xaf},
        )


class FormuleDetailView(EditeurRetrieveUpdateAPIView):
    queryset = Formule.objects.all()
    serializer_class = FormuleSerializer

    def perform_update(self, serializer):
        montant_avant = serializer.instance.montant_xaf
        formule = serializer.save()
        if formule.montant_xaf != montant_avant:
            Journal.objects.create(
                acteur=self.request.user, action='changement_tarif', organisation=None,
                details={
                    'formule': formule.libelle,
                    'ancien_montant_xaf': montant_avant,
                    'nouveau_montant_xaf': formule.montant_xaf,
                },
            )


class CodeActivationEmettreView(EditeurAPIView):
    def post(self, request):
        serializer = EmettreCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        organisation = serializer.validated_data['organisation']
        formule = serializer.validated_data['formule']

        code_clair, code = ServiceLicence.emettre_code(organisation, formule, request.user)

        return Response({
            'code': code_clair,
            'numero_serie': code.numero_serie,
            'organisation': str(organisation.id),
            'formule': FormuleSerializer(formule).data,
            'expire_le': code.expire_le,
        }, status=status.HTTP_201_CREATED)


class PaiementListCreateView(EditeurListCreateAPIView):
    serializer_class = PaiementSerializer

    def get_queryset(self):
        qs = Paiement.objects.all().order_by('-recu_le')
        organisation_id = self.request.query_params.get('organisation')
        if organisation_id:
            qs = qs.filter(organisation_id=organisation_id)
        operateur = self.request.query_params.get('operateur')
        if operateur:
            qs = qs.filter(operateur=operateur)
        return qs

    def perform_create(self, serializer):
        paiement = serializer.save(saisi_par=self.request.user)
        Journal.objects.create(
            acteur=self.request.user, action='paiement_enregistre', organisation=paiement.organisation,
            details={'montant_xaf': paiement.montant_xaf, 'operateur': paiement.operateur},
        )


class JournalListView(EditeurListAPIView):
    """Lecture seule par construction - aucune autre methode/vue n'existe sur ce chemin, voir
    console/models.py::Journal."""
    serializer_class = JournalSerializer

    def get_queryset(self):
        qs = Journal.objects.all()
        organisation_id = self.request.query_params.get('organisation')
        if organisation_id:
            qs = qs.filter(organisation_id=organisation_id)
        action = self.request.query_params.get('action')
        if action:
            qs = qs.filter(action=action)
        return qs


class EditeurListCreateView(EditeurListCreateAPIView):
    queryset = Editeur.objects.all().order_by('nom')

    def get_serializer_class(self):
        return EditeurCreateSerializer if self.request.method == 'POST' else EditeurSerializer


class EditeurDetailView(EditeurRetrieveUpdateAPIView):
    queryset = Editeur.objects.all()
    serializer_class = EditeurSerializer


class TableauDeBordView(EditeurAPIView):
    def get(self, request):
        now = timezone.now()
        par_statut = dict(Organisation.objects.values_list('statut').annotate(n=Count('id')))
        echeances = Abonnement.objects.filter(
            statut='en_cours', date_expiration__gte=now, date_expiration__lte=now + timedelta(days=7)
        ).select_related('organisation').order_by('date_expiration')
        paiements_mois = Paiement.objects.filter(
            recu_le__year=now.year, recu_le__month=now.month
        ).aggregate(total=Sum('montant_xaf'))['total'] or 0

        return Response({
            'organisations_par_statut': par_statut,
            'echeances_7_jours': [
                {
                    'organisation': a.organisation.name,
                    'organisation_id': str(a.organisation_id),
                    'date_expiration': a.date_expiration,
                }
                for a in echeances
            ],
            'paiements_du_mois_xaf': paiements_mois,
            'organisations_bloquees': Organisation.objects.filter(statut='bloquee').count(),
        })
