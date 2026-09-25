"""Mesure finale : le scenario complet du bar, contre un vrai serveur central.

Deux processus Django, deux bases, de vraies requetes HTTP. Rien n'est simule.
"""

import os
import subprocess
import sys
import uuid

import requests

LOCAL, CLOUD = 'http://127.0.0.1:8000', 'http://127.0.0.1:8001'
MDP = 'BancEssai2026!'
TOURS = int(os.environ.get('BANC_TOURS', '15'))


def jeton(tel):
    r = requests.post(f'{LOCAL}/api/auth/login/', json={'phone': tel, 'password': MDP}, timeout=25)
    r.raise_for_status()
    return r.json()['token']


def h(t, cle=True):
    d = {'Authorization': f'Token {t}', 'Content-Type': 'application/json'}
    if cle:
        d['Idempotency-Key'] = str(uuid.uuid4())
    return d


def base(nom, role, script):
    env = dict(os.environ)
    env.update({'DB_NAME': nom, 'INSTANCE_ROLE': role,
                'DJANGO_SETTINGS_MODULE': 'le_parrain.settings'})
    r = subprocess.run([sys.executable, '-c', 'import django; django.setup()\n' + script],
                       capture_output=True, text=True, env=env, cwd=os.getcwd(), timeout=120)
    if r.returncode:
        raise RuntimeError(r.stderr[-600:])
    return r.stdout.split()


def commande(*args):
    r = subprocess.run([sys.executable, 'manage.py', *args],
                       capture_output=True, text=True, cwd=os.getcwd(), timeout=300)
    return (r.stdout + r.stderr).strip().splitlines()[-1]


ETAT = """
from products.models import DepartmentStock
from orders.models import ClientTab, Bon, OrderItem
from organisations.models import BusinessDay
print(DepartmentStock.objects.first().quantity)
print(ClientTab.objects.count())
print(Bon.objects.count())
print(sum(i.quantity for i in OrderItem.objects.all()))
print(BusinessDay.objects.filter(is_open=True).count())
"""

resultats = []


def compare(libelle, obtenu, attendu):
    resultats.append((libelle, obtenu, attendu))


print('--- Mise en place ---')
serveuse, caissier = jeton('690000003'), jeton('690000002')
dep, prod = base('parrain_banc_local', 'local', """
from organisations.models import Department
from products.models import Product
print(Department.objects.first().id); print(Product.objects.first().id)""")

caissier_id = base('parrain_banc_local', 'local', """
from users.models import User
print(User.objects.get(role='caissier').id)""")[0]

r = requests.post(f'{LOCAL}/api/organisations/business-day/open/',
                  json={'opening_amounts': {caissier_id: 0}},
                  headers=h(caissier, cle=False), timeout=25)
print(f'Ouverture de la journee par le caissier : HTTP {r.status_code}')
compare("Le caissier ouvre la journee au bar", r.status_code, 201)

print(f'\n--- {TOURS} ventes, internet coupe (rien ne part) ---')
creees = 0
for tour in range(TOURS):
    onglet = str(uuid.uuid4())
    a = requests.post(f'{LOCAL}/api/orders/client-tabs/create/',
                      json={'id': onglet, 'client_name': f'Table {tour + 1}'},
                      headers=h(serveuse), timeout=25)
    b = requests.post(f'{LOCAL}/api/orders/client-tabs/{onglet}/items/',
                      json={'bon': str(uuid.uuid4()), 'department': dep,
                            'items': [{'product': prod, 'quantity': 2}]},
                      headers=h(serveuse), timeout=25)
    if a.status_code == 201 and b.status_code in (200, 201):
        creees += 1
compare('Ventes creees au bar', creees, TOURS)

print(f'{creees}/{TOURS} ventes creees.')

print('\n--- Internet revient : remontee ---')
print(' ', commande('push_upstream'))
print('  rejeu immediat :', commande('push_upstream'))

local = base('parrain_banc_local', 'local', ETAT)
cloud = base('parrain_banc_cloud', 'cloud', ETAT)

compare('Onglets dans le cloud', int(cloud[1]), int(local[1]))
compare('Bons dans le cloud', int(cloud[2]), int(local[2]))
compare('Articles vendus dans le cloud', int(cloud[3]), int(local[3]))
compare('Journee ouverte dans le cloud', int(cloud[4]), 1)

file = base('parrain_banc_local', 'local', """
from sync.models import PendingUpstreamRequest as P
print(P.objects.filter(status='pending').count())
print(P.objects.filter(status='quarantined').count())""")
compare('Restant en attente', int(file[0]), 0)
compare('En quarantaine', int(file[1]), 0)

print(chr(10) + "--- Sens 1 : l'admin annule dans le cloud, le bar doit suivre ---")
commande_cloud = base('parrain_banc_cloud', 'cloud', """
from orders.models import Order
print(Order.objects.filter(status='ouverte').order_by('created_at').first().id)""")[0]
onglet = base('parrain_banc_cloud', 'cloud', f"""
from orders.models import Order
print(Order.objects.get(id='{commande_cloud}').client_tab_id)""")[0]

admin_cloud = requests.post(f'{CLOUD}/api/auth/login/',
                            json={'phone': '690000001', 'password': MDP}, timeout=25).json()['token']
r = requests.post(f'{CLOUD}/api/orders/{commande_cloud}/cancel/',
                  headers={'Authorization': f'Token {admin_cloud}'}, timeout=25)
print(f'  annulation dans le cloud : HTTP {r.status_code}')
compare("L'admin annule dans le cloud", r.status_code, 200)
print(' ', commande('pull_operations'))

etat = base('parrain_banc_local', 'local', f"""
from orders.models import Order
o = Order.objects.filter(client_tab_id='{onglet}').first()
print(o.status if o else 'introuvable')""")[0]
compare('-> etat au bar apres la descente', etat, 'annulee')

print(chr(10) + "--- Sens 2 : le bar annule, le cloud doit suivre ---")
commande_locale, onglet2 = base('parrain_banc_local', 'local', """
from orders.models import Order
o = Order.objects.filter(status='ouverte').order_by('created_at').first()
print(o.id); print(o.client_tab_id)""")

admin_local = requests.post(f'{LOCAL}/api/auth/login/',
                            json={'phone': '690000001', 'password': MDP}, timeout=25).json()['token']
r = requests.post(f'{LOCAL}/api/orders/{commande_locale}/cancel/',
                  headers={'Authorization': f'Token {admin_local}'}, timeout=25)
print(f'  annulation au bar : HTTP {r.status_code}')
compare("L'admin annule au bar", r.status_code, 200)
print(' ', commande('push_upstream'))

etat = base('parrain_banc_cloud', 'cloud', f"""
from orders.models import Order
o = Order.objects.filter(client_tab_id='{onglet2}').first()
print(o.status if o else 'introuvable')""")[0]
compare('-> etat dans le cloud apres la remontee', etat, 'annulee')

quarantaine = base('parrain_banc_local', 'local', """
from sync.models import PendingUpstreamRequest as P
print(P.objects.filter(status='quarantined').count())""")
compare('Corrections en quarantaine', int(quarantaine[0]), 0)

print(chr(10) + "--- Sens 3 : l'admin retire une ligne dans le cloud, le bar doit suivre ---")
cible = base('parrain_banc_cloud', 'cloud', """
from orders.models import OrderItem
i = OrderItem.objects.filter(is_removed=False, order__status='ouverte').first()
print(i.order_id); print(i.id); print(i.product_id); print(i.order.client_tab_id)""")
commande_c, ligne_c, produit, onglet3 = cible

r = requests.delete(f'{CLOUD}/api/orders/{commande_c}/items/{ligne_c}/',
                    headers={'Authorization': f'Token {admin_cloud}'}, timeout=25)
print(f'  retrait dans le cloud : HTTP {r.status_code}')
compare("L'admin retire une ligne dans le cloud", r.status_code, 200)
print(' ', commande('pull_operations'))

retiree = base('parrain_banc_local', 'local', f"""
from orders.models import OrderItem
i = OrderItem.objects.filter(order__client_tab_id='{onglet3}', product_id='{produit}').first()
print(i.is_removed if i else 'introuvable')""")[0]
compare('-> ligne retiree au bar', retiree, 'True')

print(chr(10) + "--- Sens 4 : le bar retire une ligne, le cloud doit suivre ---")
cible = base('parrain_banc_local', 'local', """
from orders.models import OrderItem
i = OrderItem.objects.filter(is_removed=False, order__status='ouverte').first()
print(i.order_id); print(i.id); print(i.product_id); print(i.order.client_tab_id)""")
commande_l, ligne_l, produit2, onglet4 = cible

r = requests.delete(f'{LOCAL}/api/orders/{commande_l}/items/{ligne_l}/',
                    headers={'Authorization': f'Token {admin_local}'}, timeout=25)
print(f'  retrait au bar : HTTP {r.status_code}')
compare("L'admin retire une ligne au bar", r.status_code, 200)
print(' ', commande('push_upstream'))

retiree = base('parrain_banc_cloud', 'cloud', f"""
from orders.models import OrderItem
i = OrderItem.objects.filter(order__client_tab_id='{onglet4}', product_id='{produit2}').first()
print(i.is_removed if i else 'introuvable')""")[0]
compare('-> ligne retiree dans le cloud', retiree, 'True')

quarantaine = base('parrain_banc_local', 'local', """
from sync.models import PendingUpstreamRequest as P
print(P.objects.filter(status='quarantined').count())""")
compare('Corrections en quarantaine (final)', int(quarantaine[0]), 0)


print('\n' + '=' * 64)
print('MESURE FINALE')
print('=' * 64)
ecarts = 0
for libelle, obtenu, attendu in resultats:
    ok = obtenu == attendu
    ecarts += 0 if ok else 1
    print(f"  {'OK   ' if ok else 'ECART'} {libelle:42} {str(obtenu):>9}  (attendu {attendu})")
print('\n' + ('AUCUN ECART.' if not ecarts else f'{ecarts} ECART(S).'))
sys.exit(0 if not ecarts else 1)
