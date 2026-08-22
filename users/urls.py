from django.urls import path
from .views import (
    LoginView, LogoutView,
    UserListCreateView, UserDetailView,
    AvailablePermissionsListView, UserPermissionsUpdateView,
)

urlpatterns = [
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('users/', UserListCreateView.as_view(), name='user-list-create'),
    path('users/<uuid:pk>/', UserDetailView.as_view(), name='user-detail'),
    path('users/<uuid:pk>/permissions/', UserPermissionsUpdateView.as_view(), name='user-permissions-update'),
    path('permissions/available/', AvailablePermissionsListView.as_view(), name='available-permissions'),
]