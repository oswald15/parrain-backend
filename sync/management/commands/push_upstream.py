"""Remonte vers le serveur central les operations faites au bar.

A lancer en boucle sur l'instance locale (service, ou tache planifiee toutes les minutes) : les
operations partent au fil de l'eau des qu'internet est disponible, ce qui limite a quelques
secondes ce qui serait perdu si le poste du caissier tombait en panne.
"""

import json

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from sync.models import PendingUpstreamRequest

TIMEOUT_SECONDS = 20


class Command(BaseCommand):
    help = "Rejoue vers le serveur central les operations enregistrees au bar."

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit', type=int, default=200,
            help='Nombre maximum d operations traitees en une passe.',
        )

    def handle(self, *args, **options):
        if not settings.IS_LOCAL_INSTANCE:
            self.stderr.write(
                "Cette commande ne s'execute que sur une instance locale (INSTANCE_ROLE=local)."
            )
            return
        if not settings.CLOUD_API_URL or not settings.INSTANCE_TOKEN:
            self.stderr.write('CLOUD_API_URL et INSTANCE_TOKEN doivent etre renseignes.')
            return

        entries = PendingUpstreamRequest.objects.filter(
            status=PendingUpstreamRequest.STATUS_PENDING
        ).order_by('pk')[:options['limit']]

        sent = quarantined = 0
        for entry in entries:
            outcome = self._send(entry)
            if outcome == 'sent':
                sent += 1
            elif outcome == 'quarantined':
                quarantined += 1
            elif outcome == 'stop':
                # Reseau coupe ou probleme d'authentification : inutile d'insister, et surtout
                # il ne faut pas passer a la suivante. L'ordre doit rester intact - une commande
                # doit arriver avant les articles qu'on y ajoute.
                break

        self.stdout.write(self.style.SUCCESS(
            f'{sent} operation(s) remontee(s), {quarantined} mise(s) en quarantaine.'
        ))

    def _send(self, entry):
        url = settings.CLOUD_API_URL.rstrip('/') + entry.path
        if entry.query_string:
            url = f'{url}?{entry.query_string}'

        headers = {
            'Authorization': f'Instance {settings.INSTANCE_TOKEN}',
            'Content-Type': 'application/json',
            # Ce qu'il reste a remonter APRES celle-ci : le serveur central s'en sert pour
            # refuser les actions qui ecraseraient des ventes encore en route.
            'X-Pending-Operations': str(max(self._remaining() - 1, 0)),
        }
        if entry.user_id:
            headers['X-Acting-User'] = str(entry.user_id)
        # Les en-tetes d'origine sont rejouees telles quelles : la cle d'idempotence permet au
        # cloud de reconnaitre un rejeu, et le contexte metier d'imputer la vente a la bonne
        # session de caisse meme si elle est fermee depuis (voir orders/cash_sessions.py).
        if entry.idempotency_key:
            headers['Idempotency-Key'] = entry.idempotency_key
        if entry.client_created_at:
            headers['X-Client-Created-At'] = entry.client_created_at
        if entry.cashier_session:
            headers['X-Cashier-Session'] = entry.cashier_session

        try:
            response = requests.request(
                entry.method,
                url,
                data=json.dumps(entry.body) if entry.body is not None else None,
                headers=headers,
                timeout=TIMEOUT_SECONDS,
            )
        except requests.RequestException as error:
            self._record_attempt(entry, str(error))
            return 'stop'

        if 200 <= response.status_code < 300:
            entry.sent_at = timezone.now()
            entry.save(update_fields=['sent_at'])
            entry.delete()
            return 'sent'

        detail = self._detail(response)

        # Jeton d'instance invalide ou revoque : toutes les operations suivantes echoueraient
        # de la meme facon. On s'arrete sans rien consommer, en attendant une intervention.
        #
        # 401 seulement, et c'est une distinction qui compte : l'authentification d'instance
        # renvoie 401 (voir SyncInstanceAuthentication.authenticate_header), tandis qu'un 403
        # vient d'une permission metier et ne concerne QUE cette operation. Les confondre gelait
        # la file entiere derriere une seule action refusee - et avec elle toutes les ventes du
        # bar, indefiniment.
        if response.status_code == 401:
            self._record_attempt(entry, detail)
            return 'stop'

        # Panne du serveur central : on retentera plus tard, l'ordre est preserve.
        if response.status_code >= 500:
            self._record_attempt(entry, detail)
            return 'stop'

        # Conflit ou requete devenue invalide : l'operation n'aboutira jamais. On l'ecarte pour
        # ne pas bloquer tout le bar derriere elle, mais elle reste visible : une vente encaissee
        # ne doit jamais disparaitre en silence parce que le cloud l'a refusee.
        entry.status = PendingUpstreamRequest.STATUS_QUARANTINED
        entry.attempts += 1
        entry.last_error = detail
        entry.save(update_fields=['status', 'attempts', 'last_error'])
        return 'quarantined'

    def _remaining(self):
        return PendingUpstreamRequest.objects.filter(
            status=PendingUpstreamRequest.STATUS_PENDING
        ).count()

    def _record_attempt(self, entry, detail):
        entry.attempts += 1
        entry.last_error = detail[:2000]
        entry.save(update_fields=['attempts', 'last_error'])

    def _detail(self, response):
        try:
            payload = response.json()
        except ValueError:
            return f'HTTP {response.status_code}'
        if isinstance(payload, dict):
            return str(payload.get('detail') or payload)[:2000]
        return str(payload)[:2000]
