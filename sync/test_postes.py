import uuid
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from organisations.models import Organisation
from sync.models import SyncInstance
from users.models import User


class Base(TestCase):
    def setUp(self):
        self.organisation = Organisation.objects.create(name=f'Org {uuid.uuid4()}')
        self.admin = self._user('admin', 'Admin')
        self.autre_org = Organisation.objects.create(name=f'Org {uuid.uuid4()}')

    def _user(self, role, nom, organisation=None):
        return User.objects.create(
            organisation=organisation or self.organisation, role=role, name=nom,
            phone=f'{uuid.uuid4().int % 10**9:09d}',
        )

    def _client(self, user):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Token {Token.objects.create(user=user).key}')
        return client

    def _poste(self, organisation=None, **extra):
        defauts = {'name': 'Poste caisse', 'pending_operations': 0,
                   'last_seen_at': timezone.now()}
        defauts.update(extra)
        return SyncInstance.objects.create(
            organisation=organisation or self.organisation, **defauts
        )


class ConsultationTests(Base):
    """L'admin doit voir ses propres postes.

    La console de l'editeur les voit deja, mais attendre l'editeur pour agir - un dimanche soir,
    apres un vol - n'est pas tenable."""

    def test_l_admin_voit_les_postes_de_son_etablissement(self):
        self._poste(name='Poste bar')

        reponse = self._client(self.admin).get(reverse('sync-postes'))

        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.data['postes'][0]['nom'], 'Poste bar')

    def test_un_etablissement_ne_voit_pas_les_postes_d_un_autre(self):
        self._poste(organisation=self.autre_org, name='Poste voisin')

        reponse = self._client(self.admin).get(reverse('sync-postes'))

        self.assertEqual(reponse.data['postes'], [])

    def test_la_liste_dit_quel_poste_est_en_retard(self):
        """C'est l'information utile : un poste qui n'a pas donne signe de vie, ou qui garde des
        ventes, veut dire que les chiffres consultes sont incomplets."""
        self._poste(name='A jour')
        self._poste(name='En retard', pending_operations=4)

        postes = {p['nom']: p for p in self._client(self.admin).get(reverse('sync-postes')).data['postes']}

        self.assertTrue(postes['A jour']['a_jour'])
        self.assertFalse(postes['En retard']['a_jour'])
        self.assertIn('4', postes['En retard']['retard'])

    def test_un_poste_sans_contact_recent_est_signale(self):
        self._poste(name='Muet', last_seen_at=timezone.now() - timedelta(hours=3))

        poste = self._client(self.admin).get(reverse('sync-postes')).data['postes'][0]

        self.assertFalse(poste['a_jour'])

    def test_un_caissier_ne_voit_pas_cet_ecran(self):
        caissier = self._user('caissier', 'Caissier')

        reponse = self._client(caissier).get(reverse('sync-postes'))

        self.assertEqual(reponse.status_code, 403)

    def test_la_liste_ne_contient_jamais_le_jeton(self):
        """Meme regle que dans la console : le jeton permet d'agir au nom de n'importe quel
        employe, une page qui l'affiche en permanence l'expose aux captures d'ecran."""
        poste = self._poste()

        reponse = self._client(self.admin).get(reverse('sync-postes'))

        self.assertNotIn(poste.token, str(reponse.data))
        self.assertNotIn('token', reponse.data['postes'][0])


class CreationTests(Base):
    def test_l_admin_cree_un_poste_et_recoit_son_jeton(self):
        reponse = self._client(self.admin).post(
            reverse('sync-postes'), {'nom': 'Poste terrasse'}, format='json'
        )

        self.assertEqual(reponse.status_code, 201, getattr(reponse, 'data', reponse.content))
        poste = SyncInstance.objects.get()
        self.assertEqual(reponse.data['token'], poste.token)
        self.assertEqual(poste.organisation, self.organisation)

    def test_le_poste_appartient_toujours_a_l_etablissement_de_l_admin(self):
        """Le corps ne doit pas pouvoir designer un autre etablissement : ce serait un jeton
        valide sur les donnees d'un client qui n'est pas le sien."""
        self._client(self.admin).post(
            reverse('sync-postes'),
            {'nom': 'Intrusion', 'organisation': str(self.autre_org.id)},
            format='json',
        )

        self.assertEqual(SyncInstance.objects.get().organisation, self.organisation)

    def test_un_etablissement_peut_avoir_plusieurs_postes(self):
        client = self._client(self.admin)

        client.post(reverse('sync-postes'), {'nom': 'Bar principal'}, format='json')
        client.post(reverse('sync-postes'), {'nom': 'Annexe'}, format='json')

        self.assertEqual(SyncInstance.objects.filter(organisation=self.organisation).count(), 2)
        self.assertEqual(len(set(SyncInstance.objects.values_list('token', flat=True))), 2)

    def test_un_caissier_ne_peut_pas_creer_de_poste(self):
        caissier = self._user('caissier', 'Caissier')

        reponse = self._client(caissier).post(reverse('sync-postes'), {}, format='json')

        self.assertEqual(reponse.status_code, 403)
        self.assertFalse(SyncInstance.objects.exists())


class RevocationTests(Base):
    """La raison d'etre de cet ecran : couper un poste vole sans attendre l'editeur."""

    def test_l_admin_revoque_un_poste_de_son_etablissement(self):
        poste = self._poste()

        reponse = self._client(self.admin).post(
            reverse('sync-poste-revoquer', args=[poste.id])
        )

        self.assertEqual(reponse.status_code, 200)
        poste.refresh_from_db()
        self.assertFalse(poste.is_active)

    def test_la_revocation_n_efface_pas_l_historique_du_poste(self):
        """Le dernier contact et ce qui restait a remonter sont ce qu'on voudra lire apres un
        vol : les effacer reviendrait a perdre la trace de ce qui manque."""
        poste = self._poste(pending_operations=7)

        self._client(self.admin).post(reverse('sync-poste-revoquer', args=[poste.id]))

        poste.refresh_from_db()
        self.assertEqual(poste.pending_operations, 7)
        self.assertIsNotNone(poste.last_seen_at)

    def test_on_ne_revoque_pas_le_poste_d_un_autre_etablissement(self):
        etranger = self._poste(organisation=self.autre_org)

        reponse = self._client(self.admin).post(
            reverse('sync-poste-revoquer', args=[etranger.id])
        )

        self.assertEqual(reponse.status_code, 404)
        etranger.refresh_from_db()
        self.assertTrue(etranger.is_active)

    def test_un_caissier_ne_peut_pas_revoquer(self):
        """Sinon le caissier pourrait couper le poste sur lequel il travaille."""
        poste = self._poste()
        caissier = self._user('caissier', 'Caissier')

        reponse = self._client(caissier).post(
            reverse('sync-poste-revoquer', args=[poste.id])
        )

        self.assertEqual(reponse.status_code, 403)
        poste.refresh_from_db()
        self.assertTrue(poste.is_active)

    def test_un_poste_revoque_ne_peut_plus_synchroniser(self):
        """Le vrai effet attendu, verifie bout en bout plutot que sur le seul drapeau."""
        poste = self._poste()
        instance_client = APIClient()
        instance_client.credentials(HTTP_AUTHORIZATION=f'Instance {poste.token}')
        self.assertEqual(instance_client.get(reverse('sync-referentiel')).status_code, 200)

        self._client(self.admin).post(reverse('sync-poste-revoquer', args=[poste.id]))

        self.assertEqual(instance_client.get(reverse('sync-referentiel')).status_code, 401)
