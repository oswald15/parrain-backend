import uuid
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

import requests
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone
from django.utils.http import http_date

from organisations.models import Department, Organisation
from products.models import Product
from sync.models import PendingUpstreamRequest, SyncInstance
from users.models import User

CLOUD = 'https://cave-backend.example.test'
LOCAL = 'http://127.0.0.1:8000'
TOKEN = 'jeton-instance'
ADDRESS = '192.168.1.10'
DETECT = 'sync.management.commands.diagnostic_instance.Command._detect_address'


class FakeResponse:
    def __init__(self, status_code, payload=None, date=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.headers = {'Date': date} if date else {}

    def json(self):
        return self._payload


@override_settings(INSTANCE_ROLE='local', IS_LOCAL_INSTANCE=True, DEBUG=False,
                   CLOUD_API_URL=CLOUD, INSTANCE_TOKEN=TOKEN, LOCAL_API_URL=LOCAL,
                   ALLOWED_HOSTS=[ADDRESS, 'testserver'],
                   CORS_ALLOWED_ORIGINS=[f'http://{ADDRESS}'])
class DiagnosticTests(TestCase):
    """Diagnostic lance chez le client.

    Il est lu par quelqu'un qui n'a pas acces aux journaux et ne lira pas le code : chaque echec
    doit nommer le probleme ET la correction. Un diagnostic qui se contente d'echouer ne sert a
    rien a 19h dans un bar."""

    def setUp(self):
        self.organisation = Organisation.objects.create(name='Bar du Coin')
        SyncInstance.objects.create(
            organisation=self.organisation, name='Poste caisse', token=TOKEN,
        )
        # Un referentiel descendu : c'est l'etat d'une instance reellement mise en service.
        Department.objects.create(organisation=self.organisation, name='Bar')
        Product.objects.create(
            organisation=self.organisation, name='Castel', price=1000, purchase_price=600,
        )
        User.objects.create(
            organisation=self.organisation, role='caissier', name='Caissier',
            phone=f'{uuid.uuid4().int % 10**9:09d}',
        )

    def _run(self, cloud=None, local=None):
        """Les deux appels reseau sont distingues par leur adresse, comme en vrai."""
        cloud = cloud if cloud is not None else FakeResponse(
            200, {'organisation': {'name': 'Bar du Coin'}}, date=http_date()
        )
        local = local if local is not None else FakeResponse(200, {})

        def fetch(url, **kwargs):
            target = cloud if url.startswith(CLOUD) else local
            if isinstance(target, Exception):
                raise target
            return target

        out, err = StringIO(), StringIO()
        error = None
        # L'adresse reelle du poste de developpement n'a rien a faire dans un test : elle change
        # d'un reseau a l'autre. Les controles qui en dependent ont leurs propres tests.
        with patch('requests.get', side_effect=fetch), patch(DETECT, return_value=ADDRESS):
            try:
                call_command('diagnostic_instance', stdout=out, stderr=err)
            except CommandError as raised:
                error = str(raised)
        return out.getvalue(), error

    # ------------------------------------------------------------------ le cas sain

    def test_une_instance_correcte_ne_signale_rien_de_bloquant(self):
        out, error = self._run()

        self.assertIsNone(error, out)
        self.assertIn('Bar du Coin', out)

    # ------------------------------------------------- ce que le test terrain risque

    @override_settings(INSTANCE_ROLE='cloud', IS_LOCAL_INSTANCE=False)
    def test_le_role_non_bascule_est_la_premiere_cause_d_echec(self):
        """La panne la plus probable a l'installation : tout est en place, mais le poste se
        comporte en serveur central et ne capture rien."""
        out, error = self._run()

        self.assertIsNotNone(error)
        self.assertIn('INSTANCE_ROLE=local', out)

    def test_un_jeton_revoque_est_nomme_comme_tel(self):
        out, error = self._run(cloud=FakeResponse(401))

        self.assertIsNotNone(error)
        self.assertIn('revoquee', out)

    def test_le_backend_local_muet_est_bloquant(self):
        """Tant qu'il ne repond pas, aucune correction de l'admin ne descendra - et le
        diagnostic doit le dire, pas le laisser passer."""
        out, error = self._run(local=requests.ConnectionError('refus de connexion'))

        self.assertIsNotNone(error)
        self.assertIn('backend local ne repond pas', out)

    def test_internet_coupe_n_est_pas_un_echec(self):
        """C'est l'etat normal PENDANT le test hors-ligne : le diagnostic doit rester utilisable
        a ce moment-la, sinon il ne sert que sur un reseau qui marche deja."""
        out, error = self._run(cloud=requests.ConnectionError('injoignable'))

        self.assertIsNone(error, out)
        self.assertIn('ATTENTION', out)

    def test_une_horloge_fausse_est_bloquante(self):
        """Elle impute les ventes a la mauvaise session de caisse, sans rien signaler ailleurs."""
        decalee = http_date((timezone.now() - timedelta(hours=3)).timestamp())
        out, error = self._run(
            cloud=FakeResponse(200, {'organisation': {'name': 'Bar du Coin'}}, date=decalee)
        )

        self.assertIsNotNone(error)
        self.assertIn('horloge', out.lower())

    def test_une_vente_en_quarantaine_est_bloquante(self):
        """Ce sont des ventes encaissees que le cloud a refusees. Passer au service suivant en
        les ignorant, c'est les perdre."""
        PendingUpstreamRequest.objects.create(
            organisation=self.organisation, method='POST', path='/api/orders/create/',
            status=PendingUpstreamRequest.STATUS_QUARANTINED, last_error='conflit',
        )

        out, error = self._run()

        self.assertIsNotNone(error)
        self.assertIn('quarantaine', out)

    def test_un_poste_qui_ne_se_reconnait_pas_est_signale(self):
        SyncInstance.objects.all().delete()

        out, error = self._run()

        self.assertIsNotNone(error)
        self.assertIn('setup_local_instance', out)

    def test_un_referentiel_vide_est_bloquant(self):
        """Sans produits ni personnel, personne ne peut se connecter ni vendre - et cela ne se
        voit qu'au moment ou le service commence."""
        Product.objects.all().delete()
        Department.objects.all().delete()
        User.objects.all().delete()

        out, error = self._run()

        self.assertIsNotNone(error)
        self.assertIn('referentiel local est vide', out)

    def test_le_diagnostic_ne_modifie_rien(self):
        """Il doit etre relancable en plein service, autant de fois qu'on veut."""
        before = SyncInstance.objects.get().last_downstream_id

        self._run()

        self.assertEqual(SyncInstance.objects.get().last_downstream_id, before)
        self.assertEqual(SyncInstance.objects.count(), 1)


@override_settings(INSTANCE_ROLE='local', IS_LOCAL_INSTANCE=True, DEBUG=False,
                   CLOUD_API_URL=CLOUD, INSTANCE_TOKEN=TOKEN, LOCAL_API_URL=LOCAL)
class DiagnosticNetworkTests(TestCase):
    """Controles reseau du poste.

    C'est la panne la plus deroutante a l'installation : tout fonctionne depuis le navigateur du
    caissier, et les tablettes recoivent une erreur 400 que rien n'explique."""

    def setUp(self):
        self.organisation = Organisation.objects.create(name='Bar du Coin')
        SyncInstance.objects.create(
            organisation=self.organisation, name='Poste caisse', token=TOKEN,
        )

    def _run(self):
        out = StringIO()
        with patch('requests.get', return_value=FakeResponse(200, {})), \
                patch(DETECT, return_value=ADDRESS):
            try:
                call_command('diagnostic_instance', stdout=out, stderr=StringIO())
            except CommandError:
                pass
        return out.getvalue()

    @override_settings(ALLOWED_HOSTS=['localhost'], CORS_ALLOWED_ORIGINS=[])
    def test_l_adresse_du_poste_absente_d_allowed_hosts_est_bloquante(self):
        out = self._run()

        self.assertIn(f"{ADDRESS} absent d'ALLOWED_HOSTS", out)
        self.assertIn(f'EXTRA_ALLOWED_HOSTS={ADDRESS}', out)

    @override_settings(ALLOWED_HOSTS=[ADDRESS], CORS_ALLOWED_ORIGINS=[])
    def test_l_origine_cors_manquante_est_signalee_sans_bloquer(self):
        """Elle ne gene que si le caissier affiche l'interface par l'IP du poste plutot que par
        localhost : c'est un avertissement, pas un echec."""
        out = self._run()

        self.assertIn(f'http://{ADDRESS} absent des origines CORS', out)

    @override_settings(ALLOWED_HOSTS=['*'], CORS_ALLOWED_ORIGINS=[f'http://{ADDRESS}'])
    def test_allowed_hosts_ouvert_a_tout_est_signale(self):
        out = self._run()

        self.assertIn('accepte tout', out)

    @override_settings(ALLOWED_HOSTS=[ADDRESS], CORS_ALLOWED_ORIGINS=[f'http://{ADDRESS}'])
    def test_une_configuration_reseau_correcte_ne_dit_rien(self):
        out = self._run()

        self.assertIn('ALLOWED_HOSTS couvre le poste', out)
        self.assertIn('Origines CORS couvrent le poste', out)

    @override_settings(ALLOWED_HOSTS=[ADDRESS])
    def test_l_adresse_a_viser_est_affichee_pour_les_tablettes(self):
        """Elle doit etre lisible sur place : c'est elle qu'on saisit sur chaque tablette."""
        out = self._run()

        self.assertIn(f'http://{ADDRESS}:8000/api', out)


@override_settings(INSTANCE_ROLE='local', IS_LOCAL_INSTANCE=True, DEBUG=False,
                   CLOUD_API_URL='', INSTANCE_TOKEN='', LOCAL_API_URL=LOCAL)
class DiagnosticConfigurationTests(TestCase):
    def test_une_configuration_vide_nomme_ce_qui_manque(self):
        out = StringIO()
        with self.assertRaises(CommandError):
            call_command('diagnostic_instance', stdout=out, stderr=StringIO())

        self.assertIn('CLOUD_API_URL', out.getvalue())
        self.assertIn('INSTANCE_TOKEN', out.getvalue())
        # Le message renvoie a la procedure : l'installateur est sur place, sans le depot.
        self.assertIn('INSTANCE_LOCALE.md', out.getvalue())
