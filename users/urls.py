from django.urls import path
from .views import (
    LoginView, LogoutView,
    UserListCreateView, UserDetailView,
    AvailablePermissionsListView, UserPermissionsUpdateView,
    UserPasswordResetView, PasswordChangeView,
)

urlpatterns = [
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('users/', UserListCreateView.as_view(), name='user-list-create'),
    path('users/<uuid:pk>/', UserDetailView.as_view(), name='user-detail'),
    path('users/<uuid:pk>/permissions/', UserPermissionsUpdateView.as_view(), name='user-permissions-update'),
    path('users/<uuid:pk>/password-reset/', UserPasswordResetView.as_view(), name='user-password-reset'),
    path('password-change/', PasswordChangeView.as_view(), name='password-change'),
    path('permissions/available/', AvailablePermissionsListView.as_view(), name='available-permissions'),
]