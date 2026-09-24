"""Rattachement des recettes et depenses a une session de caisse.

Avant le mode hors-ligne, le solde d'un caissier se calculait par fenetre temporelle : tout ce
qui portait un horodatage serveur posterieur a l'ouverture de sa session. Ce raccourci ne tient
plus des qu'une action peut etre enregistree des heures apres s'etre produite - une vente
encaissee a 14h et synchronisee a 19h tombait alors hors de la session fermee a 18h, et
disparaissait du solde alors que l'argent etait bien dans le tiroir au comptage.

Le rattachement est donc desormais explicite (`Order.cashier_session`,
`CashExpense.cashier_session`), la fenetre temporelle ne servant plus que de repli pour les
enregistrements anterieurs a ce changement.
"""

from django.db import models
from django.db.models import Sum
from django.utils import timezone

from orders.models import CashExpense, Order
from organisations.models import CashierDayBalance
from sync.context import claimed_session_id


def resolve_session(user, request):
    """Session de caisse a laquelle rattacher l'action en cours.

    Priorite a la session declaree par le client (entete `X-Cashier-Session`) : c'est la seule
    information fiable pour une action faite hors-ligne, puisque la session concernee peut etre
    fermee depuis. A defaut, on prend la session ouverte du caissier - le cas normal en ligne.

    La session declaree est verifiee : elle doit appartenir a ce caissier et a son organisation,
    sinon un client pourrait imputer ses ventes a la caisse d'un collegue."""
    if getattr(user, 'role', None) != 'caissier':
        return None

    claimed = claimed_session_id(request)
    if claimed:
        session = CashierDayBalance.objects.filter(
            id=claimed, cashier=user, business_day__organisation=user.organisation
        ).first()
        if session:
            return session

    return CashierDayBalance.objects.filter(
        business_day__organisation=user.organisation,
        business_day__is_open=True,
        cashier=user,
        closing_amount__isnull=True,
    ).first()


def _legacy_window(session):
    """Fenetre temporelle de repli, pour les enregistrements sans rattachement explicite
    (anterieurs a l'introduction de `cashier_session`)."""
    upper = session.closed_at or timezone.now()
    return session.opened_at, upper


def session_orders(session):
    """Commandes encaissees imputables a cette session."""
    lower, upper = _legacy_window(session)
    return Order.objects.filter(cashier=session.cashier, status='fermee').filter(
        models.Q(cashier_session=session)
        | models.Q(cashier_session__isnull=True, closed_at__gte=lower, closed_at__lte=upper)
    )


def session_expenses(session):
    """Sorties de caisse imputables a cette session."""
    lower, upper = _legacy_window(session)
    return CashExpense.objects.filter(cashier=session.cashier, is_deleted=False).filter(
        models.Q(cashier_session=session)
        | models.Q(cashier_session__isnull=True, created_at__gte=lower, created_at__lte=upper)
    )


def compute_closing_amount(session):
    """Fond de depart + recettes encaissees - sorties de caisse, pour cette session."""
    revenue = session_orders(session).aggregate(total=Sum('total_amount'))['total'] or 0
    expenses = session_expenses(session).aggregate(total=Sum('amount'))['total'] or 0
    return session.opening_amount + revenue - expenses


def attach_and_refresh(session):
    """Recalcule le solde d'une session DEJA FERMEE a laquelle une action vient d'etre rattachee.

    Choix metier assume : on recalcule plutot que de figer. L'argent d'une vente faite
    hors-ligne etait physiquement dans le tiroir au moment du comptage ; laisser le solde
    systeme a sa valeur d'origine le ferait diverger du reel. En contrepartie, un montant deja
    arrete change apres coup : `adjusted_after_close_at` horodate l'ajustement pour que l'admin
    le voie au lieu de le subir en silence.

    Sans effet sur une session encore ouverte : son solde n'est calcule qu'a la fermeture."""
    if session is None or session.closing_amount is None:
        return
    session.closing_amount = compute_closing_amount(session)
    session.adjusted_after_close_at = timezone.now()
    session.save(update_fields=['closing_amount', 'adjusted_after_close_at'])
