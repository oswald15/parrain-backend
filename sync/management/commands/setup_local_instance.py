"""Mise en service d'une instance installee dans un bar.

A lancer une fois apres l'installation sur le poste du caissier. Verifie la configuration,
s'assure que le serveur central est joignable et reconnait l'etablissement, puis descend le
referentiel pour que le bar puisse travailler.

Ecrite comme un diagnostic et non comme un script silencieux : l'installation se fait chez un
client, souvent par quelqu'un qui n'a pas acces aux journaux. Chaque verification doit donc dire
clairement ce qui manque et quoi faire.
"""

import requests
from django.conf import settings
from django.core.management import call_command

from sync.local import cloud_url_problem
from django.core.management.base import BaseCommand

TIMEOUT_SECONDS = 20


class Command(BaseCommand):
    help = "Verifie la configuration d'une instance locale et descend le referentiel."

    def handle(self, *args, **options):
        checks = [
            self._check_role,
            self._check_settings,
            self._check_cloud,
        ]
        for check in checks:
            problem = check()
            if problem:
                self.stderr.write(self.style.ERROR(f'[X] {problem}'))
                self.stderr.write('\nMise en service interrompue.')
                return

        self.stdout.write(self.style.SUCCESS('[OK] Configuration valide.'))
        self.stdout.write('Descente du referentiel...')
        call_command('pull_referential')
        self.stdout.write(self.style.SUCCESS(
            "\nInstance prete. Lancez la synchronisation en continu avec : manage.py run_sync"
        ))

    def _check_role(self):
        if not settings.IS_LOCAL_INSTANCE:
            return (
                "INSTANCE_ROLE vaut 'cloud'. Sur le poste d'un bar, il doit valoir 'local' "
                "(a renseigner dans le fichier .env)."
            )
        self.stdout.write('[OK] Role : instance locale.')
        return None

    def _check_settings(self):
        if not settings.CLOUD_API_URL:
            return "CLOUD_API_URL absent du fichier .env : adresse du serveur central."
        if not settings.INSTANCE_TOKEN:
            return (
                "INSTANCE_TOKEN absent du fichier .env : jeton de cet etablissement, "
                "a creer depuis la console puis a recopier ici."
            )
        problem = cloud_url_problem(settings.CLOUD_API_URL)
        if problem:
            return problem
        self.stdout.write(f'[OK] Serveur central : {settings.CLOUD_API_URL}')
        return None

    def _check_cloud(self):
        url = settings.CLOUD_API_URL.rstrip('/') + '/api/sync/referentiel/'
        try:
            response = requests.get(
                url,
                headers={'Authorization': f'Instance {settings.INSTANCE_TOKEN}'},
                timeout=TIMEOUT_SECONDS,
            )
        except requests.RequestException as error:
            return (
                f"Serveur central injoignable ({error}). Verifiez la connexion internet "
                f"et l'adresse CLOUD_API_URL."
            )

        if response.status_code in (401, 403):
            return (
                "Jeton refuse par le serveur central. Verifiez INSTANCE_TOKEN, ou que "
                "l'instance n'a pas ete revoquee depuis la console."
            )
        if response.status_code != 200:
            return f'Reponse inattendue du serveur central (HTTP {response.status_code}).'

        try:
            nom = response.json().get('organisation', {}).get('name', '?')
        except ValueError:
            return "Reponse illisible du serveur central."

        self.stdout.write(f'[OK] Etablissement reconnu : {nom}')
        return None
