from django.urls import path

from .views import (
    CodeActivationEmettreView,
    EditeurDetailView,
    EditeurListCreateView,
    EditeurLoginView,
    EditeurLogoutView,
    FormuleDetailView,
    FormuleListCreateView,
    JournalListView,
    OrganisationAbonnementsHistoryView,
    OrganisationArchiverView,
    OrganisationCodesHistoryView,
    OrganisationConsoleDetailView,
    OrganisationConsoleListCreateView,
    OrganisationReactiverView,
    OrganisationSuspendreView,
    PaiementListCreateView,
    SuperadminCreateView,
    TableauDeBordView,
)

urlpatterns = [
    path('auth/login/', EditeurLoginView.as_view(), name='console-login'),
    path('auth/logout/', EditeurLogoutView.as_view(), name='console-logout'),

    path('organisations/', OrganisationConsoleListCreateView.as_view(), name='console-organisation-list-create'),
    path('organisations/<uuid:pk>/', OrganisationConsoleDetailView.as_view(), name='console-organisation-detail'),
    path('organisations/<uuid:pk>/abonnements/', OrganisationAbonnementsHistoryView.as_view(), name='console-organisation-abonnements'),
    path('organisations/<uuid:pk>/codes/', OrganisationCodesHistoryView.as_view(), name='console-organisation-codes'),
    path('organisations/<uuid:pk>/creer-superadmin/', SuperadminCreateView.as_view(), name='console-organisation-creer-superadmin'),
    path('organisations/<uuid:pk>/suspendre/', OrganisationSuspendreView.as_view(), name='console-organisation-suspendre'),
    path('organisations/<uuid:pk>/reactiver/', OrganisationReactiverView.as_view(), name='console-organisation-reactiver'),
    path('organisations/<uuid:pk>/archiver/', OrganisationArchiverView.as_view(), name='console-organisation-archiver'),

    path('formules/', FormuleListCreateView.as_view(), name='console-formule-list-create'),
    path('formules/<uuid:pk>/', FormuleDetailView.as_view(), name='console-formule-detail'),

    path('codes/emettre/', CodeActivationEmettreView.as_view(), name='console-code-emettre'),

    path('paiements/', PaiementListCreateView.as_view(), name='console-paiement-list-create'),

    path('journal/', JournalListView.as_view(), name='console-journal-list'),

    path('comptes/', EditeurListCreateView.as_view(), name='console-editeur-list-create'),
    path('comptes/<uuid:pk>/', EditeurDetailView.as_view(), name='console-editeur-detail'),

    path('tableau-de-bord/', TableauDeBordView.as_view(), name='console-tableau-de-bord'),
]
