import shutil
import tempfile
from pathlib import Path

from django.test import Client, TestCase, override_settings
from django.urls import clear_url_caches, reverse

import le_parrain.urls


class BaseSpa(TestCase):
    """L'interface du caissier servie par l'instance du bar.

    Un bar a plusieurs caisses : le serveur local tourne sur un PC, les autres caissiers s'y
    connectent par le reseau. L'interface doit donc venir de ce serveur, sur la meme origine que
    l'API - sans quoi chaque caissier appellerait son propre poste."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.repertoire = Path(tempfile.mkdtemp())
        (cls.repertoire / 'index.html').write_text('<title>Caisse</title>', encoding='utf-8')
        (cls.repertoire / 'main-ABC123.js').write_text('console.log(1)', encoding='utf-8')
        (cls.repertoire / 'ngsw-worker.js').write_text('// sw', encoding='utf-8')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.repertoire, ignore_errors=True)
        super().tearDownClass()

    def _recharger_urls(self):
        """Les routes de l'interface sont construites a l'import : il faut les reconstruire
        quand le role change."""
        clear_url_caches()
        import importlib
        importlib.reload(le_parrain.urls)

    def setUp(self):
        self._recharger_urls()
        self.client = Client()

    def tearDown(self):
        self._recharger_urls()


@override_settings(INSTANCE_ROLE='local', IS_LOCAL_INSTANCE=True)
class ServieParLInstanceTests(BaseSpa):
    def setUp(self):
        self.enter_context = self.settings(INSTANCE_SPA_DIR=str(self.repertoire))
        self.enter_context.enable()
        self.addCleanup(self.enter_context.disable)
        super().setUp()

    def test_la_racine_renvoie_l_interface(self):
        reponse = self.client.get('/')

        self.assertEqual(reponse.status_code, 200)
        self.assertIn(b'Caisse', b''.join(reponse.streaming_content))

    def test_les_fichiers_de_l_interface_sont_servis(self):
        reponse = self.client.get('/main-ABC123.js')

        self.assertEqual(reponse.status_code, 200)

    def test_le_service_worker_est_servi_a_la_racine(self):
        """Il doit etre a la racine, sinon son perimetre ne couvre pas l'application et le cache
        hors-ligne du caissier ne fonctionne pas."""
        reponse = self.client.get('/ngsw-worker.js')

        self.assertEqual(reponse.status_code, 200)

    def test_une_adresse_interne_renvoie_l_interface_et_non_404(self):
        """`/caisse` n'est pas un fichier : c'est une route que l'interface resout elle-meme.
        Sans ce repli, actualiser la page sur un autre ecran que l'accueil donnerait 404."""
        reponse = self.client.get('/caisse/onglets')

        self.assertEqual(reponse.status_code, 200)
        self.assertIn(b'Caisse', b''.join(reponse.streaming_content))

    def test_l_api_n_est_pas_avalee_par_le_repli(self):
        """LE risque de ces routes attrape-tout : placees avant l'API, elles renverraient la page
        d'accueil a la place des donnees, et rien ne fonctionnerait plus."""
        reponse = self.client.get(reverse('sync-referentiel'))

        self.assertEqual(reponse.status_code, 401)

    def test_l_administration_django_reste_joignable(self):
        reponse = self.client.get('/admin/')

        self.assertIn(reponse.status_code, (301, 302))

    def test_un_chemin_remontant_ne_lit_pas_un_fichier_hors_du_repertoire(self):
        """Ce qui compte n'est pas le code de reponse mais le CONTENU : un repli sur la page
        d'accueil renvoie 200, et c'est la bonne reponse. La faute serait de renvoyer le fichier
        vise."""
        secret = self.repertoire.parent / 'secret_hors_interface.txt'
        secret.write_text('MOT-DE-PASSE-EN-CLAIR', encoding='utf-8')
        self.addCleanup(secret.unlink, missing_ok=True)

        for chemin in ('/../secret_hors_interface.txt',
                       '/..%2Fsecret_hors_interface.txt',
                       '/%2e%2e/secret_hors_interface.txt'):
            reponse = self.client.get(chemin)
            corps = (b''.join(reponse.streaming_content)
                     if reponse.streaming else reponse.content)
            self.assertNotIn(b'MOT-DE-PASSE-EN-CLAIR', corps, chemin)


@override_settings(INSTANCE_ROLE='cloud', IS_LOCAL_INSTANCE=False)
class PasServieParLeServeurCentralTests(BaseSpa):
    """Le serveur central n'a pas d'interface a servir : elle est hebergee separement."""

    def setUp(self):
        self.enter_context = self.settings(INSTANCE_SPA_DIR=str(self.repertoire))
        self.enter_context.enable()
        self.addCleanup(self.enter_context.disable)
        super().setUp()

    def test_la_racine_ne_sert_rien(self):
        reponse = self.client.get('/')

        self.assertEqual(reponse.status_code, 404)

    def test_l_api_fonctionne_normalement(self):
        reponse = self.client.get(reverse('sync-referentiel'))

        self.assertEqual(reponse.status_code, 401)


@override_settings(INSTANCE_ROLE='local', IS_LOCAL_INSTANCE=True, INSTANCE_SPA_DIR='')
class SansInterfaceConstruiteTests(BaseSpa):
    """Une instance dont l'interface n'a pas ete copiee doit rester utilisable : les tablettes
    n'en ont pas besoin, elles parlent directement a l'API."""

    def test_l_api_fonctionne_meme_sans_interface(self):
        reponse = self.client.get(reverse('sync-referentiel'))

        self.assertEqual(reponse.status_code, 401)

    def test_la_racine_repond_404_sans_planter(self):
        reponse = self.client.get('/')

        self.assertEqual(reponse.status_code, 404)
