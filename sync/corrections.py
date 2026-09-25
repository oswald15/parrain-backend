"""Reecriture des corrections vers une adresse que les deux cotes comprennent.

Le probleme, mesure sur banc d'essai : une meme vente porte l'identifiant `dd465252` au bar et
`d2388e13` dans le cloud. Chaque base fabrique le sien, independamment. Une correction qui cite
cet identifiant est donc incomprehensible pour l'autre cote, qui repond 404 - elle part en
quarantaine, et la vente reste corrigee d'un seul cote. Les lignes de commande sont pires
encore : leur identifiant est un entier auto-incremente, qui ne peut pas coincider.

Ce que les deux cotes partagent :

    onglet      -> identifiant genere par le client
    departement -> vient du referentiel
    produit     -> vient du referentiel

Et ces trois-la suffisent a designer ce qu'on veut corriger, parce que le code metier le dit
deja lui-meme :

    order, _ = Order.objects.get_or_create(client_tab=..., department=...)
    order_item, _ = OrderItem.objects.get_or_create(order=..., product=...)

Une commande est donc unique par (onglet, departement), et une ligne par (commande, produit).
Le probleme n'etait pas qu'il manquait un identifiant partage : c'est qu'on s'adressait au
mauvais.

La reecriture est faite ici plutot que dans chaque capture : la remontee et la descente ont
exactement le meme besoin, et une divergence entre les deux se paierait par des corrections qui
passent dans un sens et pas dans l'autre.
"""

import re

CANCEL_PATTERN = re.compile(
    r'^/api/orders/(?P<order_id>[0-9a-f-]{36})/cancel/?$', re.IGNORECASE
)
REMOVE_ITEM_PATTERN = re.compile(
    r'^/api/orders/(?P<order_id>[0-9a-f-]{36})/items/(?P<item_id>\d+)/?$', re.IGNORECASE
)

CANCEL_PATH = '/api/orders/corrections/annuler/'
REMOVE_ITEM_PATH = '/api/orders/corrections/retirer-ligne/'


def rewrite(method, path, body):
    """Rend (methode, chemin, corps) adresses par identite naturelle.

    Renvoie l'original quand il n'y a rien a reecrire, ou quand l'identite naturelle n'est pas
    determinable : mieux vaut une correction qui part en quarantaine, donc visible, qu'une
    correction perdue au moment meme de sa capture.
    """
    path = path or ''

    match = CANCEL_PATTERN.match(path)
    if match:
        cle = _identite_commande(match.group('order_id'))
        if cle is None:
            return method, path, body
        return 'POST', CANCEL_PATH, {**(body or {}), **cle}

    match = REMOVE_ITEM_PATTERN.match(path)
    if match:
        cle = _identite_commande(match.group('order_id'))
        produit = _produit_de_la_ligne(match.group('item_id'))
        if cle is None or produit is None:
            return method, path, body
        # La methode change aussi : l'ecran supprime en DELETE, la correction se rejoue en POST
        # avec un corps - une requete DELETE ne peut pas en porter un de facon portable.
        return 'POST', REMOVE_ITEM_PATH, {**(body or {}), **cle, 'product': produit}

    return method, path, body


def _identite_commande(order_id):
    """(onglet, departement) de la commande, ou None si elle n'en a pas."""
    from orders.models import Order

    order = Order.objects.filter(id=order_id).values(
        'client_tab_id', 'department_id'
    ).first()
    if not order or not order['client_tab_id'] or not order['department_id']:
        # Une vente directe au comptoir n'a pas d'onglet, donc pas d'identite naturelle
        # partagee. On ne sait pas la designer autrement, et on n'invente pas.
        return None
    return {
        'client_tab': str(order['client_tab_id']),
        'department': str(order['department_id']),
    }


def _produit_de_la_ligne(item_id):
    from orders.models import OrderItem

    item = OrderItem.objects.filter(id=item_id).values('product_id').first()
    return str(item['product_id']) if item and item['product_id'] else None
