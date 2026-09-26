import uuid
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from organisations.models import Department, Organisation
from products.models import DepartmentStock, Product
from users.models import User


@override_settings(INSTANCE_ROLE='cloud', IS_LOCAL_INSTANCE=False)
class CreerEtablissementTestTests(TestCase):
    """Montage d'un etablissement pour la repetition.

    Elle se fait sur le serveur de production : la seule chose qui separe une repetition des
    donnees d'un vrai client est le refus d'ecrire dans un etablissement existant."""

    def _run(self, *args):
        out, err = StringIO(), StringIO()
        erreur = None
        try:
            call_command('creer_etablissement_test', *args, stdout=out, stderr=err)
        except CommandError as levee:
            erreur = str(levee)
        return out.getvalue(), erreur

    def test_cree_tout_ce_qu_il_faut_pour_vendre(self):
        sortie, erreur = self._run('--nom', 'ZZ Test', '--mot-de-passe', 'MotDePasseLong!2026')

        self.assertIsNone(erreur)
        organisation = Organisation.objects.get(name='ZZ Test')
        self.assertEqual(Department.objects.filter(organisation=organisation).count(), 1)
        self.assertEqual(Product.objects.filter(organisation=organisation).count(), 1)
        self.assertEqual(DepartmentStock.objects.get(organisation=organisation).quantity, 500)
        self.assertEqual(
            sorted(User.objects.filter(organisation=organisation).values_list('role', flat=True)),
            ['admin', 'caissier', 'serveur'],
        )

    def test_les_numeros_sont_normalises_donc_utilisables(self):
        """Crees bruts, ces comptes seraient impossibles a utiliser : la connexion normalise ce
        qu'on lui saisit et ne les retrouverait pas."""
        self._run('--nom', 'ZZ Test', '--mot-de-passe', 'MotDePasseLong!2026')

        for compte in User.objects.all():
            self.assertTrue(compte.phone.startswith('+237'), compte.phone)

    def test_les_comptes_peuvent_reellement_se_connecter(self):
        self._run('--nom', 'ZZ Test', '--mot-de-passe', 'MotDePasseLong!2026')

        caissier = User.objects.get(role='caissier')
        self.assertTrue(caissier.check_password('MotDePasseLong!2026'))

    def test_la_serveuse_est_rattachee_au_caissier(self):
        self._run('--nom', 'ZZ Test', '--mot-de-passe', 'MotDePasseLong!2026')

        serveuse = User.objects.get(role='serveur')
        self.assertEqual(serveuse.assigned_cashier, User.objects.get(role='caissier'))

    def test_refuse_d_ecrire_dans_un_etablissement_existant(self):
        """LE garde-fou : une repetition lancee sur un vrai client y creerait de vraies ventes,
        a demeler ensuite de sa comptabilite."""
        vrai_client = Organisation.objects.create(name='Bar_le Parrain')

        _, erreur = self._run('--nom', 'Bar_le Parrain', '--mot-de-passe', 'MotDePasseLong!2026')

        self.assertIsNotNone(erreur)
        self.assertEqual(Department.objects.filter(organisation=vrai_client).count(), 0)
        self.assertEqual(User.objects.filter(organisation=vrai_client).count(), 0)

    def test_deux_etablissements_de_test_n_entrent_pas_en_collision(self):
        self._run('--nom', 'ZZ Test A', '--mot-de-passe', 'MotDePasseLong!2026')

        _, erreur = self._run('--nom', 'ZZ Test B', '--mot-de-passe', 'MotDePasseLong!2026')

        self.assertIsNone(erreur)
        self.assertEqual(User.objects.count(), 6)
        self.assertEqual(len(set(User.objects.values_list('phone', flat=True))), 6)

    def test_rappelle_de_supprimer_apres_coup(self):
        sortie, _ = self._run('--nom', 'ZZ Test', '--mot-de-passe', 'MotDePasseLong!2026')

        self.assertIn('supprimer', sortie.lower())

    @override_settings(INSTANCE_ROLE='local', IS_LOCAL_INSTANCE=True)
    def test_refuse_sur_le_poste_d_un_bar(self):
        """La-bas les etablissements descendent du referentiel : en creer un localement donnerait
        un etablissement que le serveur central ne connait pas."""
        _, erreur = self._run('--nom', 'ZZ Test', '--mot-de-passe', 'MotDePasseLong!2026')

        self.assertIsNotNone(erreur)
        self.assertFalse(Organisation.objects.exists())
