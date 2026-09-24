"""Protections contre les actions qui ecraseraient le travail d'un bar hors-ligne.

Certaines actions du serveur central ecrivent le stock en VALEUR ABSOLUE - la validation d'un
inventaire, typiquement. Executees pendant qu'un bar a des ventes non remontees, elles effacent
ces ventes du stock sans que personne ne s'en apercoive : les quantites paraissent coherentes,
mais elles ignorent des consommations reellement servies.
"""

from datetime import timedelta

from django.utils import timezone

from .models import SyncInstance

# Au-dela de ce delai sans contact, on ne sait plus ce que le bar a fait entre-temps. Le
# compteur d'operations en attente qu'il avait declare n'est plus une information fiable :
# l'absence de nouvelles n'est pas une preuve qu'il n'a rien vendu.
STALE_CONTACT_AFTER = timedelta(minutes=15)


def bars_not_up_to_date(organisation):
    """Instances de cet etablissement dont le travail n'est pas entierement remonte.

    Deux cas, traites de la meme facon car indiscernables dans leurs consequences :
    - le bar a declare des operations encore en attente ;
    - le bar ne s'est pas manifeste depuis trop longtemps, et peut tres bien etre en plein
      service hors-ligne.
    """
    cutoff = timezone.now() - STALE_CONTACT_AFTER
    unsure = []
    for instance in SyncInstance.objects.filter(organisation=organisation, is_active=True):
        if instance.pending_operations > 0:
            unsure.append((instance, f'{instance.pending_operations} operation(s) en attente'))
        elif instance.last_seen_at is None or instance.last_seen_at < cutoff:
            unsure.append((instance, 'aucun contact recent'))
    return unsure


def describe_blocking_bars(organisation):
    """Message destine a l'admin, ou None si rien ne bloque."""
    unsure = bars_not_up_to_date(organisation)
    if not unsure:
        return None
    details = ', '.join(f'{instance.name} ({reason})' for instance, reason in unsure)
    return (
        "Des ventes peuvent ne pas encore etre remontees : " + details + ". "
        "Attendez la synchronisation avant de valider, sinon ces ventes seront effacees du stock."
    )
