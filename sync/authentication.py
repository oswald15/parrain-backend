"""Authentification des instances installees dans les bars.

Une instance locale remonte vers le serveur central les operations faites sur place. Elle ne se
presente pas comme un utilisateur mais comme un etablissement, et declare pour chaque requete
quel employe en est l'auteur - c'est lui qui doit apparaitre dans l'historique et la caisse, pas
un compte technique.

Format attendu :

    Authorization: Instance <jeton>
    X-Acting-User: <uuid de l'employe>

L'employe n'est exige que pour les ECRITURES : une operation doit toujours etre imputee a
quelqu'un. Une lecture - typiquement l'instance qui vient chercher son referentiel - n'a pas
d'auteur, et n'est de toute facon joignable que par les vues acceptant explicitement une
instance (voir sync/views.py::IsSyncInstance).
"""

from django.contrib.auth.models import AnonymousUser
from django.utils import timezone
from rest_framework import authentication, exceptions

from users.models import User
from .models import SyncInstance

KEYWORD = 'Instance'
SAFE_METHODS = ('GET', 'HEAD', 'OPTIONS')
ACTING_USER_HEADER = 'HTTP_X_ACTING_USER'
PENDING_OPERATIONS_HEADER = 'HTTP_X_PENDING_OPERATIONS'


class SyncInstanceAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request):
        auth = request.META.get('HTTP_AUTHORIZATION', '')
        if not auth.startswith(f'{KEYWORD} '):
            # Pas pour nous : on laisse la main aux autres classes d'authentification.
            return None

        token = auth[len(KEYWORD) + 1:].strip()
        instance = SyncInstance.objects.filter(
            token=token, is_active=True
        ).select_related('organisation').first()
        if instance is None:
            raise exceptions.AuthenticationFailed('Instance inconnue ou revoquee.')

        acting_user_id = request.META.get(ACTING_USER_HEADER, '').strip()
        if not acting_user_id:
            if request.method in SAFE_METHODS:
                self._touch(instance, request)
                # Utilisateur anonyme : seules les vues acceptant explicitement une instance
                # sont alors joignables, les autres exigeant un compte authentifie.
                return (AnonymousUser(), instance)
            raise exceptions.AuthenticationFailed(
                "En-tete X-Acting-User manquante : une operation doit etre imputee a un employe."
            )

        # LE controle qui compte : l'employe declare doit appartenir a l'etablissement de
        # l'instance. Sans lui, le jeton d'un bar permettrait d'ecrire dans les donnees d'un
        # autre - une fuite entre clients, pas seulement une erreur d'imputation.
        user = User.objects.filter(
            id=acting_user_id, organisation=instance.organisation
        ).first()
        if user is None:
            raise exceptions.AuthenticationFailed(
                "Employe inconnu pour cet etablissement."
            )

        self._touch(instance, request)
        return (user, instance)

    def _touch(self, instance, request=None):
        """Trace de vie, lue par l'admin pour savoir si les chiffres d'un bar sont a jour.

        L'instance declare au passage combien d'operations elle n'a pas encore remontees : le
        serveur central ne peut pas le deviner, et cette information conditionne des actions
        destructrices comme la validation d'un inventaire."""
        fields = {'last_seen_at': timezone.now()}
        if request is not None:
            raw = request.META.get(PENDING_OPERATIONS_HEADER, '').strip()
            if raw.isdigit():
                fields['pending_operations'] = int(raw)
        SyncInstance.objects.filter(pk=instance.pk).update(**fields)

    def authenticate_header(self, request):
        return KEYWORD
