"""Enveloppe d'erreur normalisee, pour que la file d'attente hors-ligne sache quoi faire.

Cote client, la decision a prendre apres un echec n'est pas la meme selon la cause :
reessayer plus tard, abandonner definitivement, ou alerter l'utilisateur. Or un code HTTP seul
ne suffit pas a trancher - deux erreurs 400 peuvent appeler des reactions opposees. Chaque
reponse d'erreur porte donc un `code` machine stable, en plus du message destine a l'humain.

Convention pour la file d'attente :
  - 2xx                  -> action passee, retirer de la file
  - 409 + code metier    -> l'etat a change entre-temps : mise en quarantaine + alerte
  - 400 / 422            -> requete definitivement invalide : mise en quarantaine
  - 401 / 403            -> rafraichir le jeton puis reessayer, SANS consommer la cle
  - 5xx / reseau         -> reessayer plus tard
"""

from rest_framework.views import exception_handler as drf_exception_handler

# Codes metier employes lors d'un conflit d'etat. Stables : le client s'appuie dessus pour
# afficher un message utile ("cet onglet a ete encaisse par un collegue") plutot qu'un code brut.
CONFLICT_CODES = {
    'tab_already_closed': "Cet onglet a deja ete encaisse.",
    'tab_not_invoiced': "Cet onglet n'est pas pret pour encaissement.",
    'bon_already_handled': "Ce bon a deja ete valide ou annule.",
    'session_already_open': 'Une session de caisse est deja ouverte.',
    'no_open_session': "Aucune session de caisse ouverte.",
    'idempotency_in_progress': 'Action en cours de traitement.',
    'idempotency_key_reuse': "Cle d'idempotence reutilisee pour une autre action.",
}


def exception_handler(exc, context):
    """Ajoute un `code` machine a toute reponse d'erreur qui n'en porte pas encore.

    Le repli `error` reste volontairement generique : il vaut mieux un code inconnu mais
    present (le client sait alors qu'il s'agit d'une erreur definitive) qu'une reponse sans
    code, que la file ne saurait pas classer."""
    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    data = response.data
    if isinstance(data, dict) and 'code' not in data:
        data['code'] = _default_code(response.status_code)
    return response


def _default_code(status_code):
    if status_code == 409:
        return 'conflict'
    if status_code in (401, 403):
        return 'auth_required'
    if status_code == 404:
        return 'not_found'
    return 'error'
