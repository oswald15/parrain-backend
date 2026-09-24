"""Connexion relayee au serveur central, depuis une instance installee dans un bar.

Choix assume : **la connexion exige internet**, sans tolerance hors-ligne. L'instance locale ne
detient donc aucune empreinte de mot de passe - c'est le serveur central qui verifie les
identifiants, applique le controle anti-recul d'horloge et l'etat de la licence.

Consequence a connaitre : si internet est coupe au moment d'ouvrir, personne ne peut se
connecter et le service ne demarre pas. En revanche, une equipe deja connectee continue de
travailler normalement pendant toute la coupure - c'est ce que l'instance locale garantit.
"""

import requests
from django.conf import settings
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.response import Response

from users.models import User

TIMEOUT_SECONDS = 20


def login_through_cloud(request):
    """Verifie les identifiants aupres du serveur central, puis ouvre une session LOCALE.

    Le jeton renvoye est celui de l'instance locale, pas celui du cloud : les appareils du bar
    parlent a l'instance, et doivent continuer a le faire une fois internet coupe.
    """
    if not settings.CLOUD_API_URL:
        return Response(
            {'detail': "Instance locale mal configuree : CLOUD_API_URL absent.",
             'code': 'instance_misconfigured'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    url = settings.CLOUD_API_URL.rstrip('/') + '/api/auth/login/'
    try:
        upstream = requests.post(url, json=request.data, timeout=TIMEOUT_SECONDS)
    except requests.RequestException:
        return Response(
            {'detail': "Connexion impossible : le serveur central est injoignable. "
                       "Verifiez la connexion internet.",
             'code': 'cloud_unreachable'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    if upstream.status_code != 200:
        # Identifiants refuses, licence bloquee, horloge incoherente : la decision appartient au
        # serveur central et son message est transmis tel quel.
        try:
            payload = upstream.json()
        except ValueError:
            payload = {'detail': "Connexion refusee par le serveur central."}
        return Response(payload, status=upstream.status_code)

    payload = upstream.json()
    user_id = (payload.get('user') or {}).get('id')
    user = User.objects.filter(id=user_id).first() if user_id else None
    if user is None:
        return Response(
            {'detail': "Cet utilisateur n'est pas encore connu de l'instance locale. "
                       "Lancez une synchronisation du referentiel (pull_referential).",
             'code': 'user_not_synced'},
            status=status.HTTP_409_CONFLICT,
        )

    # Session locale : c'est ce jeton qui servira a travailler pendant une coupure. Le jeton du
    # cloud n'est pas conserve - la remontee des operations utilise l'identifiant d'instance.
    token, _ = Token.objects.get_or_create(user=user)
    payload['token'] = token.key
    return Response(payload)
