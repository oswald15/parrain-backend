from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.authtoken.models import Token
from django.contrib.auth.models import Permission
from .models import User
from .serializers import (
    LoginSerializer, UserSerializer,
    UserListSerializer, UserCreateSerializer, UserUpdateSerializer,
    UserPermissionsSerializer, MANAGEABLE_PERMISSION_CODENAMES, PasswordChangeSerializer,
)
from .permissions import HasManageUsersRight, HasManageUserPermissionsRight
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.contrib.auth.hashers import make_password
from datetime import timedelta

# RegisterView (inscription anonyme, AllowAny, organisation choisie librement par le client)
# a ete retiree : aucun frontend (web/mobile) ne l'appelait, et elle permettait a n'importe
# qui de creer un compte serveur rattache a l'organisation de son choix en devinant son UUID -
# une vraie faille, pas juste du code mort. La creation de compte se fait desormais uniquement
# via UserListCreateView (authentifie, organisation forcee au createur) ou
# console.views.SuperadminCreateView (premier compte d'une organisation, cote console).

@method_decorator(csrf_exempt, name='dispatch')
class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        from django.utils import timezone
        from console.services.licence import ServiceLicence

        serializer = LoginSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.validated_data['user']
            device_date = serializer.validated_data.get('device_date')
            organisation = user.organisation

            licence_etat = None
            if organisation:
                # Anti-recul d'horloge (console.services.licence) : comparee au poste de
                # l'utilisateur, au niveau organisation (pas seulement supadmin) - reculer
                # l'horloge d'un appareil ne doit jamais permettre de prolonger indument
                # une periode de grace/blocage.
                if (
                    device_date
                    and organisation.derniere_activite_le
                    and device_date < organisation.derniere_activite_le
                ):
                    return Response(
                        {'detail': "Date du système incohérente."},
                        status=status.HTTP_403_FORBIDDEN,
                    )
                now = timezone.now()
                organisation.derniere_activite_le = max(device_date, now) if device_date else now
                organisation.save(update_fields=['derniere_activite_le'])
                licence_etat = ServiceLicence.etat(organisation)

            token, created = Token.objects.get_or_create(user=user)
            response_data = {
                'token': token.key,
                'user': UserSerializer(user).data,
            }
            if licence_etat:
                response_data['licence'] = licence_etat
            return Response(response_data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        request.user.auth_token.delete()
        return Response({"message": "Déconnexion réussie."}, status=status.HTTP_200_OK)


class UserPasswordResetView(APIView):
    permission_classes = [IsAuthenticated, HasManageUsersRight]

    def post(self, request, pk):
        target = generics.get_object_or_404(
            User.objects.filter(organisation=request.user.organisation), pk=pk
        )
        temporary_password = get_random_string(12)
        target.password = make_password(temporary_password)
        target.must_change_password = True
        target.password_reset_expires_at = timezone.now() + timedelta(minutes=10)
        target.save(update_fields=['password', 'must_change_password', 'password_reset_expires_at'])
        return Response({
            'detail': 'Mot de passe temporaire genere. Il expire dans 10 minutes.',
            'temporary_password': temporary_password,
            'expires_at': target.password_reset_expires_at,
        })


class PasswordChangeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        user = request.user
        user.set_password(serializer.validated_data['new_password'])
        user.must_change_password = False
        user.password_reset_expires_at = None
        user.save(update_fields=['password', 'must_change_password', 'password_reset_expires_at'])
        Token.objects.filter(user=user).delete()
        token = Token.objects.create(user=user)
        return Response({'token': token.key, 'user': UserSerializer(user).data})


class UserListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated, HasManageUsersRight]

    def get_serializer_class(self):
        return UserCreateSerializer if self.request.method == 'POST' else UserListSerializer

    def get_queryset(self):
        user = self.request.user
        # Toujours scope a sa propre organisation, y compris pour un superadmin - avant ce
        # correctif, un superadmin voyait/pouvait desactiver les employes de N'IMPORTE QUELLE
        # organisation (le role seul etait verifie, jamais l'appartenance a l'organisation).
        queryset = User.objects.filter(organisation=user.organisation).order_by('name')
        role = self.request.query_params.get('role')
        if role:
            queryset = queryset.filter(role=role)
        return queryset

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context


class UserDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated, HasManageUsersRight]
    serializer_class = UserUpdateSerializer

    def get_queryset(self):
        return User.objects.filter(organisation=self.request.user.organisation)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save()


class AvailablePermissionsListView(APIView):
    permission_classes = [IsAuthenticated, HasManageUsersRight]

    def get(self, request):
        perms = Permission.objects.filter(codename__in=MANAGEABLE_PERMISSION_CODENAMES)
        data = [{'codename': p.codename, 'name': p.name} for p in perms]
        return Response(data)


class UserPermissionsUpdateView(APIView):
    permission_classes = [IsAuthenticated, HasManageUserPermissionsRight]

    def patch(self, request, pk):
        queryset = User.objects.filter(organisation=self.request.user.organisation)
        target = generics.get_object_or_404(queryset, pk=pk)
        serializer = UserPermissionsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        codenames = serializer.validated_data['permissions']
        perms = Permission.objects.filter(codename__in=codenames)
        target.user_permissions.set(perms)
        return Response(UserListSerializer(target).data)
