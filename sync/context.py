"""Contexte metier d'une action rejouee depuis la file d'attente hors-ligne.

Une action faite hors-ligne est enregistree cote serveur bien apres s'etre reellement produite.
L'horodatage serveur ne dit donc plus QUAND ni DANS QUELLE session de caisse elle a eu lieu :
sans ces informations, une vente encaissee a 14h et synchronisee a 19h disparait du solde de la
session que le caissier a fermee a 18h - alors que l'argent, lui, etait bien dans le tiroir au
moment du comptage.

Le client transmet donc ce contexte dans des entetes HTTP, comme pour `Idempotency-Key` : cela
evite de modifier le corps de chaque requete (et donc chaque serializer) endpoint par endpoint.
"""

import uuid

from django.utils.dateparse import parse_datetime

CLIENT_CREATED_AT_HEADER = 'HTTP_X_CLIENT_CREATED_AT'
CASHIER_SESSION_HEADER = 'HTTP_X_CASHIER_SESSION'
IDEMPOTENCY_HEADER = 'HTTP_IDEMPOTENCY_KEY'


def client_created_at(request):
    """Date/heure reelle de l'action sur l'appareil, ou None si l'appel est fait en ligne.

    Purement declaratif : l'horloge d'un telephone peut etre fausse. Sert a l'audit et au
    rattachement metier, jamais d'arbitre entre deux appareils."""
    raw = request.META.get(CLIENT_CREATED_AT_HEADER)
    if not raw:
        return None
    try:
        return parse_datetime(raw)
    except ValueError:
        return None


def claimed_session_id(request):
    """Session de caisse a laquelle le client rattache l'action, ou None.

    Renvoyee par l'ouverture de session ; l'app la conserve et l'accroche a chaque action faite
    pendant cette session, y compris hors-ligne."""
    raw = request.META.get(CASHIER_SESSION_HEADER)
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except (ValueError, AttributeError, TypeError):
        return None


def is_replay(request):
    """Vrai si la requete provient de la file d'attente hors-ligne.

    Toute action susceptible d'etre rejouee porte une cle d'idempotence - y compris quand le
    reseau est disponible et que la file se vide immediatement. C'est ce qui permet aux
    garde-fous metier (journee/session fermee entre-temps) de distinguer une action legitime
    faite plus tot d'une tentative de travailler hors journee ouverte."""
    return bool(request.META.get(IDEMPOTENCY_HEADER))
