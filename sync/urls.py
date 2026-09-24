from django.urls import path

from .views import (
    DownstreamOperationsView,
    InstanceStatusView,
    OperationAbandonneeTraiterView,
    OperationsAbandonneesView,
    ReferentialSyncView,
)

urlpatterns = [
    path('operations-abandonnees/', OperationsAbandonneesView.as_view(),
         name='operations-abandonnees'),
    path('operations-abandonnees/<uuid:pk>/traiter/', OperationAbandonneeTraiterView.as_view(),
         name='operation-abandonnee-traiter'),
    path('referentiel/', ReferentialSyncView.as_view(), name='sync-referentiel'),
    path('operations/', DownstreamOperationsView.as_view(), name='sync-operations'),
    path('etat/', InstanceStatusView.as_view(), name='sync-etat'),
]
