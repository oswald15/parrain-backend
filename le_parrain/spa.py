"""L'interface du caissier, servie par l'instance du bar elle-meme.

Un bar a plusieurs caisses : chaque caissier a son PC, et tous doivent voir les memes onglets.
Un seul serveur local tourne donc dans le batiment, et les autres postes s'y connectent par le
Wi-Fi.

Cela impose de servir l'interface depuis ce serveur, sur la meme origine que l'API. La version
precedente compilait `http://localhost:8000` dans la page : un second caissier ouvrant
l'interface depuis son PC appelait SON propre localhost, donc rien. Servie ici, avec une adresse
d'API relative, la meme page fonctionne depuis n'importe quel appareil du reseau.

Effets de bord, tous bienvenus :
  - Node.js disparait de l'installation - plus de serveur statique separe, un logiciel de moins
    a installer chez le client.
  - Le caissier du PC serveur ouvre `localhost`, seule origine que le navigateur considere comme
    sure : il garde son cache hors-ligne. Les autres n'en ont pas besoin, le serveur local etant
    joignable tant que le Wi-Fi tient.
  - Plus de CORS a configurer pour le navigateur : meme origine.

Rien de tout cela ne s'active sur le serveur central, qui n'a pas d'interface a servir -
celle-ci est hebergee separement.
"""

import posixpath
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404
from django.urls import re_path
from django.views.static import serve


def _repertoire():
    chemin = getattr(settings, 'INSTANCE_SPA_DIR', '')
    return Path(chemin) if chemin else None


def disponible():
    """Vrai seulement sur une instance locale disposant d'une interface construite."""
    if not settings.IS_LOCAL_INSTANCE:
        return False
    repertoire = _repertoire()
    return bool(repertoire and (repertoire / 'index.html').is_file())


def _index(request):
    return FileResponse(open(_repertoire() / 'index.html', 'rb'), content_type='text/html')


def _fichier_ou_index(request, chemin):
    """Un vrai fichier s'il existe, sinon la page d'accueil.

    Le repli est ce qui fait fonctionner les adresses internes de l'application : `/caisse` n'est
    pas un fichier, c'est une route que l'interface resout elle-meme une fois chargee. Sans ce
    repli, actualiser la page sur un ecran autre que l'accueil renverrait 404.
    """
    # La protection contre les chemins remontants est celle de `django.views.static.serve`, qui
    # refuse tout ce qui sort du repertoire - verifie : `/../secret`, `/..%2Fsecret` et
    # `/%2e%2e/secret` ne fuient rien. La normalisation ci-dessous ne protege pas, elle rend
    # seulement honnete le test `is_file()` qui suit.
    normalise = posixpath.normpath('/' + chemin).lstrip('/')
    cible = _repertoire() / normalise
    if normalise and not normalise.startswith('..') and cible.is_file():
        return serve(request, normalise, document_root=str(_repertoire()))
    if not (_repertoire() / 'index.html').is_file():
        raise Http404
    return _index(request)


def urlpatterns():
    """Routes a placer EN DERNIER : elles capturent tout ce qui reste."""
    if not disponible():
        return []
    return [
        re_path(r'^$', _index, name='spa-index'),
        re_path(r'^(?P<chemin>.+)$', _fichier_ou_index, name='spa-fichier'),
    ]
