from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from . import spa

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('users.urls')),
    path('api/organisations/', include('organisations.urls')),
    path('api/stock/', include('products.urls')),
    path('api/orders/', include('orders.urls')),
    path('api/console/', include('console.urls')),
    path('api/sync/', include('sync.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# EN DERNIER, et seulement sur l'instance d'un bar : ces routes capturent tout ce qui n'a pas
# ete reconnu plus haut, pour que les adresses internes de l'interface fonctionnent au
# rafraichissement. Placees avant /api/, elles l'avaleraient (voir le_parrain/spa.py).
urlpatterns += spa.urlpatterns()