from rest_framework import generics
from rest_framework.views import APIView

from .authentication import EditeurTokenAuthentication
from .permissions import IsEditeur


class EditeurAuthMixin:
    """Fixe l'authentification/permission sur EditeurToken+IsEditeur pour toute vue console -
    empeche qu'une vue console herite par accident de TokenAuthentication (settings.REST_FRAMEWORK,
    qui reste inchange pour ne pas laisser un token users.User s'authentifier ici, voir Phase 4 du plan)."""
    authentication_classes = [EditeurTokenAuthentication]
    permission_classes = [IsEditeur]


class EditeurAPIView(EditeurAuthMixin, APIView):
    pass


class EditeurListCreateAPIView(EditeurAuthMixin, generics.ListCreateAPIView):
    pass


class EditeurRetrieveUpdateAPIView(EditeurAuthMixin, generics.RetrieveUpdateAPIView):
    pass


class EditeurListAPIView(EditeurAuthMixin, generics.ListAPIView):
    pass
