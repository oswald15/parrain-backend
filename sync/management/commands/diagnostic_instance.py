"""Verifie sur place qu'une instance locale est reellement en service.

Ecrite pour etre lancee chez le client, par quelqu'un qui n'a pas acces aux journaux et ne lira
pas le code. Chaque controle dit ce qui ne va pas ET quoi corriger - un diagnostic qui se
contente d'echouer ne sert a rien a 19h dans un bar.

Elle ne modifie rien : elle peut etre relancee autant de fois qu'on veut, y compris en plein
service.
"""

import socket
from datetime import timezone as dt_timezone
from email.utils import parsedate_to_datetime

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone

from organisations.models import Department
from products.models import Product
from sync.local import cloud_url_problem
from sync.models import PendingUpstreamRequest, SyncInstance
from users.models import User

TIMEOUT_SECONDS = 15
# Au-dela, le controle anti-recul d'horloge de la licence et l'imputation des ventes a une
# session de caisse commencent a produire des resultats incoherents.
MAX_CLOCK_DRIFT_SECONDS = 120


class Command(BaseCommand):
    help = "Verifie qu'une instance locale est correctement installee et joignable."

    def handle(self, *args, **options):
        self.failures = []
        self.warnings = []

        self._section('Configuration')
        self._check_role()
        self._check_cloud_settings()
        self._check_debug()

        self._section('Reseau du bar')
        address = self._detect_address()
        self._check_allowed_hosts(address)
        self._check_cors(address)
        if address:
            # Affiche apres les controles, pour etre la derniere chose lue de cette section :
            # c'est ce qu'on recopie sur chaque tablette.
            self.stdout.write('')
            self.stdout.write(
                f'  A saisir sur les tablettes : http://{address}:8000/api'
            )

        self._section('Base de donnees locale')
        self._check_database()

        self._section('Serveur central')
        payload = self._check_cloud()

        self._section('Instance locale')
        self._check_self_identity()
        self._check_self_reachable()

        self._section('Referentiel descendu')
        self._check_referential()

        self._section("File d'attente")
        self._check_queue()

        self._summarise()

    # ------------------------------------------------------------------ sortie

    def _section(self, title):
        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING(f'--- {title} ---'))

    def _ok(self, message):
        self.stdout.write(self.style.SUCCESS(f'  OK      {message}'))

    def _warn(self, message, fix):
        self.warnings.append(message)
        self.stdout.write(self.style.WARNING(f'  ATTENTION {message}'))
        self.stdout.write(f'            -> {fix}')

    def _fail(self, message, fix):
        self.failures.append(message)
        self.stdout.write(self.style.ERROR(f'  ECHEC   {message}'))
        self.stdout.write(f'          -> {fix}')

    def _summarise(self):
        self.stdout.write('')
        if self.failures:
            raise CommandError(
                f'{len(self.failures)} probleme(s) bloquant(s). '
                "L'instance n'est PAS prete : corriger les lignes ECHEC ci-dessus."
            )
        if self.warnings:
            self.stdout.write(self.style.WARNING(
                f'{len(self.warnings)} avertissement(s). '
                "L'instance fonctionne, mais lire les lignes ATTENTION."
            ))
            return
        self.stdout.write(self.style.SUCCESS(
            "Tout est en ordre. L'instance est prete pour le test hors-ligne."
        ))

    # ----------------------------------------------------------- configuration

    def _check_role(self):
        if settings.IS_LOCAL_INSTANCE:
            self._ok(f'INSTANCE_ROLE = {settings.INSTANCE_ROLE}')
            return
        self._fail(
            f'INSTANCE_ROLE = {settings.INSTANCE_ROLE} : ce poste se comporte en serveur central.',
            'Mettre INSTANCE_ROLE=local dans le .env, puis redemarrer le backend. '
            "Sans cela rien n'est capture, rien ne remonte, et le caissier ne peut pas ouvrir "
            'la journee sans internet.',
        )

    def _check_cloud_settings(self):
        problem = cloud_url_problem(settings.CLOUD_API_URL)
        if problem:
            self._fail(
                problem,
                "Corriger CLOUD_API_URL dans le .env, puis redemarrer le backend.",
            )
        elif settings.CLOUD_API_URL:
            self._ok(f'CLOUD_API_URL = {settings.CLOUD_API_URL}')
        else:
            self._fail(
                'CLOUD_API_URL absent.',
                "Renseigner l'adresse du serveur central dans le .env.",
            )
        if settings.INSTANCE_TOKEN:
            self._ok(f'INSTANCE_TOKEN present ({settings.INSTANCE_TOKEN[:6]}...)')
        else:
            self._fail(
                'INSTANCE_TOKEN absent.',
                'Creer une SyncInstance pour cet etablissement dans la console du serveur '
                'central et copier son jeton dans le .env (voir INSTANCE_LOCALE.md, etape 1).',
            )
        self._ok(f'LOCAL_API_URL = {settings.LOCAL_API_URL}')

    def _check_debug(self):
        if settings.DEBUG:
            self._warn(
                'DEBUG est actif.',
                'Mettre DEBUG=0 : en production il expose la configuration et ralentit le poste.',
            )
        else:
            self._ok('DEBUG desactive')

    # ------------------------------------------------------------------ reseau

    def _detect_address(self):
        """L'adresse par laquelle les tablettes joindront ce poste."""
        address = None
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            # Aucun paquet n'est emis : cela sert seulement a savoir quelle interface le
            # systeme utiliserait. Fonctionne donc meme internet debranche, tant que le Wi-Fi
            # du bar est la - ce qui est exactement le cas a tester.
            probe.connect(('192.168.1.1', 1))
            address = probe.getsockname()[0]
            probe.close()
        except OSError:
            try:
                address = socket.gethostbyname(socket.gethostname())
            except OSError:
                address = None

        if not address or address.startswith('127.'):
            self._warn(
                "Adresse sur le reseau local non determinee.",
                "Relever l'adresse IPv4 du poste avec `ipconfig` : c'est elle que les tablettes "
                'doivent viser, et elle doit etre fixe.',
            )
            return None

        self._ok(f'Adresse du poste sur le reseau : {address}')
        return address

    def _check_allowed_hosts(self, address):
        hosts = list(settings.ALLOWED_HOSTS)
        if '*' in hosts:
            self._warn(
                'ALLOWED_HOSTS accepte tout (*).',
                "Y mettre l'adresse du poste plutot que *, meme sur un reseau local.",
            )
            return
        if address and address not in hosts:
            self._fail(
                f"{address} absent d'ALLOWED_HOSTS : les tablettes recevront une erreur 400.",
                f'Ajouter EXTRA_ALLOWED_HOSTS={address} dans le .env, puis redemarrer.',
            )
            return
        self._ok('ALLOWED_HOSTS couvre le poste')

    def _check_cors(self, address):
        if getattr(settings, 'CORS_ALLOW_ALL_ORIGINS', False):
            self._ok('CORS ouvert (CORS_ALLOW_ALL_ORIGINS)')
            return
        origins = list(getattr(settings, 'CORS_ALLOWED_ORIGINS', []))
        if address and f'http://{address}' not in origins and f'http://{address}:8000' not in origins:
            self._warn(
                f'http://{address} absent des origines CORS.',
                f'Ajouter EXTRA_CORS_ORIGINS=http://{address} si le navigateur du caissier '
                "affiche l'interface depuis cette adresse plutot que depuis localhost.",
            )
            return
        self._ok('Origines CORS couvrent le poste')

    # -------------------------------------------------------------- base locale

    def _check_database(self):
        try:
            connection.ensure_connection()
        except Exception as error:
            self._fail(
                f'Base locale injoignable : {error}',
                'Verifier que PostgreSQL est demarre et que les identifiants du .env sont bons.',
            )
            return
        self._ok(f'Base locale joignable ({connection.settings_dict.get("NAME")})')

        if connection.vendor == 'sqlite':
            self._fail(
                'La base locale est SQLite.',
                'Installer PostgreSQL : SQLite ignore silencieusement les verrous de ligne, ce '
                'qui supprime la protection contre deux encaissements simultanes.',
            )
        else:
            self._ok(f'Moteur : {connection.vendor}')

    # --------------------------------------------------------- serveur central

    def _check_cloud(self):
        if not settings.CLOUD_API_URL or not settings.INSTANCE_TOKEN:
            self._fail(
                'Controle du serveur central impossible : configuration incomplete.',
                'Corriger CLOUD_API_URL et INSTANCE_TOKEN ci-dessus, puis relancer.',
            )
            return None

        url = settings.CLOUD_API_URL.rstrip('/') + '/api/sync/referentiel/'
        try:
            response = requests.get(
                url,
                headers={'Authorization': f'Instance {settings.INSTANCE_TOKEN}'},
                timeout=TIMEOUT_SECONDS,
            )
        except requests.RequestException as error:
            self._warn(
                f'Serveur central injoignable : {error}',
                'Normal si internet est volontairement coupe pour le test. Sinon, verifier la '
                "connexion et l'adresse CLOUD_API_URL.",
            )
            return None

        if response.status_code in (401, 403):
            self._fail(
                'Jeton refuse par le serveur central.',
                'Le jeton est faux ou la SyncInstance a ete revoquee (is_active=False). '
                'En regenerer un depuis la console et le remettre dans le .env.',
            )
            return None
        if response.status_code != 200:
            self._fail(
                f'Le serveur central repond HTTP {response.status_code}.',
                'Verifier que CLOUD_API_URL pointe bien sur le backend et non sur une page web.',
            )
            return None

        payload = response.json()
        self._ok(f"Serveur central joignable, etablissement reconnu : "
                 f"{payload.get('organisation', {}).get('name', '?')}")
        self._check_clock(response)
        return payload

    def _check_clock(self, response):
        """Une horloge fausse fait deraper l'imputation des ventes aux sessions de caisse, et
        peut declencher le controle anti-recul de la licence."""
        raw = getattr(response, 'headers', {}).get('Date')
        if not raw:
            return
        try:
            reference = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=dt_timezone.utc)

        drift = abs((timezone.now() - reference).total_seconds())
        if drift > MAX_CLOCK_DRIFT_SECONDS:
            self._fail(
                f"L'horloge du poste s'ecarte de {int(drift)} s du serveur central.",
                'Activer la synchronisation automatique de l\'heure sur le poste. Une horloge '
                'fausse impute les ventes a la mauvaise session de caisse.',
            )
        else:
            self._ok(f'Horloge du poste alignee (ecart {int(drift)} s)')

    # -------------------------------------------------------- instance locale

    def _check_self_identity(self):
        instance = SyncInstance.objects.filter(token=settings.INSTANCE_TOKEN).first()
        if instance is None:
            self._fail(
                'Le poste ne se reconnait pas lui-meme.',
                'Lancer `python manage.py setup_local_instance` : sans cette identite, les '
                "corrections faites par l'admin ne peuvent pas etre appliquees ici.",
            )
            return
        self._ok(f'Identite locale : {instance.name} ({instance.organisation.name})')

    def _check_self_reachable(self):
        """Le controle le plus proche du reel : l'instance se joint elle-meme par son API, comme
        elle le fera pour appliquer les corrections de l'admin."""
        url = settings.LOCAL_API_URL.rstrip('/') + '/api/sync/referentiel/'
        try:
            response = requests.get(
                url,
                headers={'Authorization': f'Instance {settings.INSTANCE_TOKEN}'},
                timeout=TIMEOUT_SECONDS,
            )
        except requests.RequestException as error:
            self._fail(
                f'Le backend local ne repond pas sur {settings.LOCAL_API_URL} : {error}',
                'Demarrer le backend, ou corriger LOCAL_API_URL si le port est different. '
                "Tant qu'il ne repond pas, aucune correction de l'admin ne descendra.",
            )
            return
        if response.status_code != 200:
            self._fail(
                f'Le backend local repond HTTP {response.status_code} a sa propre identite.',
                'Verifier que setup_local_instance a bien tourne sur CETTE base.',
            )
            return
        self._ok('Le backend local repond et reconnait son jeton')

    # ---------------------------------------------------------- referentiel

    def _check_referential(self):
        counts = {
            'produits': Product.objects.count(),
            'departements': Department.objects.count(),
            'utilisateurs': User.objects.count(),
        }
        if not any(counts.values()):
            self._fail(
                'Le referentiel local est vide.',
                'Lancer `python manage.py pull_referential`. Sans produits ni personnel, '
                'personne ne peut se connecter ni vendre.',
            )
            return
        self._ok(', '.join(f'{value} {label}' for label, value in counts.items()))
        for label, value in counts.items():
            if value == 0:
                self._warn(
                    f'Aucun element : {label}.',
                    "Verifier cote serveur central que l'etablissement en possede.",
                )

    # ------------------------------------------------------------ file d'attente

    def _check_queue(self):
        pending = PendingUpstreamRequest.objects.filter(
            status=PendingUpstreamRequest.STATUS_PENDING
        ).count()
        quarantined = PendingUpstreamRequest.objects.filter(
            status=PendingUpstreamRequest.STATUS_QUARANTINED
        ).count()

        self._ok(f'{pending} operation(s) en attente de remontee')
        if quarantined:
            self._fail(
                f'{quarantined} operation(s) en quarantaine.',
                'Ce sont des ventes encaissees que le serveur central a refusees. Elles ne '
                'remonteront pas toutes seules : les examiner avant de continuer '
                "(table sync_pendingupstreamrequest, colonne last_error).",
            )
        else:
            self._ok('Aucune operation en quarantaine')

        instance = SyncInstance.objects.filter(token=settings.INSTANCE_TOKEN).first()
        if instance:
            self._ok(
                f"Corrections de l'admin appliquees jusqu'au n°{instance.last_downstream_id}"
            )
