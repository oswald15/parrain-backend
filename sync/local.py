"""Identite de l'instance vis-a-vis d'elle-meme.

Pour appliquer une correction descendue du serveur central, l'instance repasse par sa propre API
(voir sync/management/commands/pull_operations.py). Elle doit donc pouvoir s'y authentifier - et
la seule identite qu'elle possede est le jeton recu a l'installation.

Ce n'est pas une frontiere de confiance supplementaire : ce jeton vit deja en clair dans le `.env`
du poste, et qui le detient peut de toute facon agir sur cet etablissement cote cloud.
"""

from django.conf import settings

from .models import SyncInstance

LOCAL_INSTANCE_NAME = 'Instance locale'


def cloud_url_problem(url):
    """Erreur de saisie la plus probable dans le .env : l'adresse copiee avec son `/api`.

    Deux conventions opposees cohabitent, et c'est une source de confusion legitime. Les
    appareils - tablettes, navigateur du caissier - visent une base qui SE TERMINE par `/api`.
    Le poste, lui, veut la racine du serveur central : le code y ajoute `/api/...` a chaque
    appel. Copier le lien tel qu'on le connait donne `.../api/api/orders/...`, et tout echoue
    en 404 - sans que rien ne designe la cause.

    Renvoie le probleme a corriger, ou None si l'adresse convient.
    """
    if not url:
        return None

    cleaned = url.rstrip('/')
    if cleaned.endswith('/api'):
        return (
            f"CLOUD_API_URL se termine par '/api' ({url}). Le poste attend la RACINE du "
            f"serveur central, sans '/api' : le code l'ajoute lui-meme a chaque appel, et "
            f"toutes les requetes partiraient vers '/api/api/...'. Corriger en : "
            f"{cleaned[: -len('/api')] or '/'}"
        )

    if not cleaned.startswith(('http://', 'https://')):
        return (
            f"CLOUD_API_URL doit commencer par http:// ou https:// (valeur actuelle : {url})."
        )

    return None


def ensure_local_instance(organisation):
    """Garantit que le poste se reconnait lui-meme. Sans objet sur le serveur central."""
    if not settings.IS_LOCAL_INSTANCE or not settings.INSTANCE_TOKEN:
        return None

    instance, created = SyncInstance.objects.get_or_create(
        token=settings.INSTANCE_TOKEN,
        defaults={
            'organisation': organisation,
            'name': LOCAL_INSTANCE_NAME,
            'is_active': True,
        },
    )
    if not created:
        # Le nom n'est jamais ecrase : l'admin a pu le renommer depuis la console, et ce nom est
        # ce qu'il lit dans l'ecran d'etat des postes.
        SyncInstance.objects.filter(pk=instance.pk).update(
            organisation=organisation, is_active=True
        )
    return instance
