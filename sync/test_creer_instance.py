import uuid
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from organisations.models import Organisation
from sync.models import SyncInstance


@override_settings(INSTANCE_ROLE='cloud', IS_LOCAL_INSTANCE=False)
class CreerInstanceTests(TestCase):
    """Creation du jeton d'un bar, sur le serveur central.

    Tapee par SSH au moment d'equiper un etablissement. Deux erreurs coutent cher : creer un
    second jeton sans le dire - l'installateur repart avec le mauvais - et revoquer par megarde
    celui d'un bar en service, qui s'arrete."""

    def setUp(self):
        self.organisation = Organisation.objects.create(name='Bar du Coin')

    def _run(self, *args):
        out, err = StringIO(), StringIO()
        error = None
        try:
            call_command('creer_instance', *args, stdout=out, stderr=err)
        except CommandError as raised:
            error = str(raised)
        return out.getvalue(), err.getvalue(), error

    def test_cree_un_jeton_et_l_affiche(self):
        out, _, error = self._run('--organisation', 'Bar du Coin')

        self.assertIsNone(error)
        instance = SyncInstance.objects.get()
        self.assertIn(f'INSTANCE_TOKEN={instance.token}', out)
        self.assertEqual(instance.organisation, self.organisation)

    def test_un_second_appel_ne_cree_pas_de_doublon_silencieux(self):
        """L'erreur qui coute le plus cher : l'installateur repartirait avec un jeton, et le bar
        en aurait deux - dont un que personne ne surveille."""
        self._run('--organisation', 'Bar du Coin')

        _, _, error = self._run('--organisation', 'Bar du Coin')

        self.assertIsNotNone(error)
        self.assertIn('--supplementaire', error)
        self.assertEqual(SyncInstance.objects.count(), 1)

    def test_un_second_poste_est_possible_si_on_le_demande(self):
        self._run('--organisation', 'Bar du Coin')

        _, _, error = self._run('--organisation', 'Bar du Coin', '--supplementaire')

        self.assertIsNone(error)
        self.assertEqual(SyncInstance.objects.filter(is_active=True).count(), 2)

    def test_remplacer_revoque_les_anciens(self):
        """Poste vole : les anciens jetons doivent cesser de marcher immediatement."""
        self._run('--organisation', 'Bar du Coin')
        ancien = SyncInstance.objects.get()

        out, _, error = self._run('--organisation', 'Bar du Coin', '--remplacer')

        self.assertIsNone(error)
        ancien.refresh_from_db()
        self.assertFalse(ancien.is_active)
        self.assertEqual(SyncInstance.objects.filter(is_active=True).count(), 1)
        self.assertIn('revoque', out)

    def test_rien_n_est_revoque_sans_qu_on_le_demande(self):
        """Un jeton revoque par megarde arrete un bar en plein service."""
        self._run('--organisation', 'Bar du Coin')

        self._run('--organisation', 'Bar du Coin', '--supplementaire')

        self.assertEqual(SyncInstance.objects.filter(is_active=False).count(), 0)

    def test_un_nom_inconnu_liste_les_etablissements(self):
        """Un nom se tape mal par SSH : mieux vaut lister que renvoyer 'introuvable'."""
        Organisation.objects.create(name='Bar de la Gare')

        _, _, error = self._run('--organisation', 'Bar du Coi')

        self.assertIn('Bar du Coin', error)
        self.assertIn('Bar de la Gare', error)

    def test_sans_organisation_la_commande_liste_au_lieu_d_echouer_sechement(self):
        _, _, error = self._run()

        self.assertIn('Bar du Coin', error)
        self.assertFalse(SyncInstance.objects.exists())

    def test_le_nom_du_poste_est_reglable(self):
        """C'est ce nom que l'admin lit dans l'ecran d'etat des postes."""
        self._run('--organisation', 'Bar du Coin', '--nom', 'Caisse terrasse')

        self.assertEqual(SyncInstance.objects.get().name, 'Caisse terrasse')

    @override_settings(INSTANCE_ROLE='local', IS_LOCAL_INSTANCE=True)
    def test_refuse_de_tourner_sur_le_poste_d_un_bar(self):
        """Un jeton cree la ne serait connu de personne : le serveur central le refuserait."""
        _, _, error = self._run('--organisation', 'Bar du Coin')

        self.assertIn('serveur central', error)
        self.assertFalse(SyncInstance.objects.exists())

    def test_les_jetons_ne_se_repetent_pas(self):
        other = Organisation.objects.create(name=f'Org {uuid.uuid4()}')
        self._run('--organisation', 'Bar du Coin')
        self._run('--organisation', other.name)

        tokens = set(SyncInstance.objects.values_list('token', flat=True))
        self.assertEqual(len(tokens), 2)
