from django.urls import path
from .views import (
    OrganisationMineView, OrganisationDetailView,
    LicenceEtatView, OrganisationAbonnementView, OrganisationActiverCodeView,
    DepartmentListCreateView, DepartmentDetailView,
    BusinessDayCurrentView, BusinessDayOpenView, BusinessDayCloseView, BusinessDayHistoryView,
)

urlpatterns = [
    path('', OrganisationMineView.as_view(), name='organisation-mine'),
    path('licence-etat/', LicenceEtatView.as_view(), name='organisation-licence-etat'),
    path('abonnement/', OrganisationAbonnementView.as_view(), name='organisation-abonnement'),
    path('activer-code/', OrganisationActiverCodeView.as_view(), name='organisation-activer-code'),
    path('<uuid:pk>/', OrganisationDetailView.as_view(), name='organisation-detail'),
    path('departments/', DepartmentListCreateView.as_view(), name='department-list-create'),
    path('departments/<uuid:pk>/', DepartmentDetailView.as_view(), name='department-detail'),
    path('business-day/current/', BusinessDayCurrentView.as_view(), name='business-day-current'),
    path('business-day/open/', BusinessDayOpenView.as_view(), name='business-day-open'),
    path('business-day/close/', BusinessDayCloseView.as_view(), name='business-day-close'),
    path('business-day/history/', BusinessDayHistoryView.as_view(), name='business-day-history'),
]
