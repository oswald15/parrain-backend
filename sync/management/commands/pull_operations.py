"""Applique au bar les corrections faites par l'admin dans le serveur central.

Sans cette descente, une vente annulee a distance continue d'exister au bar : le stock finit par
converger a la descente du referentiel, mais le resume de caisse du poste compte toujours cette
vente, et le caissier remet en fin de service un montant qui ne correspond a rien.

La correction est appliquee en rejouant l'appel HTTP contre l'API DE L'INSTANCE ELLE-MEME, et non
par une ecriture en base : une annulation doit produire ici exactement ce qu'elle produit
ailleurs - stock rendu, ecritures au journal, imputation a la bonne session de caisse. Ecrire
directement en base reviendrait a reimplementer cette logique, et a la laisser diverger.
"""

import json

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

from sync.models import SyncInstance

TIMEOUT_SECONDS = 20


class Command(BaseCommand):
    help = "Applique localement les corrections venues du serveur central."

    def handle(self, *args, **options):
        if not settings.IS_LOCAL_INSTANCE:
            self.stderr.write(
                "Cette commande ne s'execute que sur une instance locale (INSTANCE_ROLE=local)."
            )
            return
        if not settings.CLOUD_API_URL or not settings.INSTANCE_TOKEN:
            self.stderr.write('CLOUD_API_URL et INSTANCE_TOKEN doivent etre renseignes.')
            return

        instance = SyncInstance.objects.filter(token=settings.INSTANCE_TOKEN).first()
        if instance is None:
            self.stderr.write(
                "Instance locale inconnue : lancer d'abord `setup_local_instance`."
            )
            return

        operations = self._fetch(instance.last_downstream_id)
        if operations is None:
            return

        applied = refused = 0
        for operation in operations:
            outcome = self._apply(operation)
            if outcome == 'stop':
                # Le poste ne repond pas a lui-meme : rien ne sert de continuer, et surtout le
                # curseur ne doit pas avancer. L'ordre compte - une suppression d'article ne peut
                # pas preceder l'annulation de la commande qui la porte.
                break
            if outcome == 'refused':
                refused += 1
            else:
                applied += 1
            instance.last_downstream_id = operation['id']

        SyncInstance.objects.filter(pk=instance.pk).update(
            last_downstream_id=instance.last_downstream_id
        )
        self.stdout.write(self.style.SUCCESS(
            f'{applied} correction(s) appliquee(s), {refused} refusee(s).'
        ))

    def _fetch(self, after):
        url = settings.CLOUD_API_URL.rstrip('/') + '/api/sync/operations/'
        try:
            response = requests.get(
                url,
                params={'after': after},
                headers={'Authorization': f'Instance {settings.INSTANCE_TOKEN}'},
                timeout=TIMEOUT_SECONDS,
            )
        except requests.RequestException as error:
            self.stderr.write(f'Serveur central injoignable : {error}')
            return None

        if response.status_code != 200:
            self.stderr.write(f'Refus du serveur central (HTTP {response.status_code}).')
            return None

        return response.json().get('operations', [])

    def _apply(self, operation):
        url = settings.LOCAL_API_URL.rstrip('/') + operation['path']
        if operation.get('query_string'):
            url = f"{url}?{operation['query_string']}"

        headers = {
            'Authorization': f'Instance {settings.INSTANCE_TOKEN}',
            'Content-Type': 'application/json',
            # Marque le rejeu : sans elle, la correction serait capturee par la remontee et
            # repartirait vers le cloud, qui l'appliquerait une seconde fois.
            'X-Sync-Replay': '1',
        }
        if operation.get('acting_user_id'):
            headers['X-Acting-User'] = operation['acting_user_id']

        body = operation.get('body')
        try:
            response = requests.request(
                operation['method'],
                url,
                data=json.dumps(body) if body is not None else None,
                headers=headers,
                timeout=TIMEOUT_SECONDS,
            )
        except requests.RequestException as error:
            self.stderr.write(f"Instance locale injoignable : {error}")
            return 'stop'

        if 200 <= response.status_code < 300:
            return 'applied'

        if response.status_code >= 500:
            return 'stop'

        # Correction que le bar ne peut pas appliquer - typiquement une vente deja annulee sur
        # place. On passe a la suivante pour ne pas bloquer toute la descente derriere elle, mais
        # jamais en silence : l'ecart est reel et quelqu'un doit pouvoir le retrouver.
        self.stderr.write(
            f"Correction refusee par le bar : {operation['method']} {operation['path']} "
            f"(HTTP {response.status_code}) - {self._detail(response)}"
        )
        return 'refused'

    def _detail(self, response):
        try:
            payload = response.json()
        except ValueError:
            return f'HTTP {response.status_code}'
        if isinstance(payload, dict):
            return str(payload.get('detail') or payload)[:500]
        return str(payload)[:500]
