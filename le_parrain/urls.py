from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('users.urls')),
    path('api/organisations/', include('organisations.urls')),
    path('api/stock/', include('products.urls')),
    path('api/orders/', include('orders.urls')),
    path('api/console/', include('console.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)