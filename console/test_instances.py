import uuid

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from console.models import Editeur, Journal
from organisations.models import Organisation
from sync.models import SyncInstance


class Base(TestCase):
    def setUp(self):
        self.organisation = Organisation.objects.create(name=f'Org {uuid.uuid4()}')
        self.editeur = Editeur.objects.create(
            nom='Editeur', email=f'editeur{uuid.uuid4().hex[:8]}@test.local', is_active=True,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.editeur)

    def _creer(self, **corps):
        return self.client.post(
            reverse('console-organisation-instances', args=[self.organisation.id]),
            corps, format='json',
        )

    def _lister(self):
        return self.client.get(
            reverse('console-organisation-instances', args=[self.organisation.id])
        )


class CreationDepuisLaConsoleTests(Base):
    """Le jeton n'etait obtenable qu'en SSH. Tant que c'est l'editeur qui installe cela passe ;
    des qu'un tiers equipe un bar, il est bloque."""

    def test_la_creation_renvoie_le_jeton(self):
        reponse = self._creer(nom='Poste caisse')

        self.assertEqual(reponse.status_code, 201, getattr(reponse, 'data', reponse.content))
        instance = SyncInstance.objects.get()
        self.assertEqual(reponse.data['token'], instance.token)
        self.assertEqual(instance.organisation, self.organisation)
        self.assertEqual(instance.name, 'Poste caisse')

    def test_la_reponse_previent_que_le_jeton_ne_reviendra_pas(self):
        reponse = self._creer()

        self.assertIn('INSTANCE_TOKEN', reponse.data['avertissement'])

    def test_un_nom_par_defaut_est_donne(self):
        reponse = self._creer()

        self.assertEqual(reponse.data['nom'], 'Poste caisse')

    def test_la_creation_est_journalisee_SANS_le_jeton(self):
        """Le journal est une piste d'audit consultable : y ecrire le jeton le rendrait lisible
        indefiniment, ce que l'affichage unique cherche precisement a eviter."""
        reponse = self._creer()

        entree = Journal.objects.get(action='creation_instance_locale')
        self.assertEqual(entree.organisation, self.organisation)
        self.assertNotIn(reponse.data['token'], str(entree.details))

    def test_un_anonyme_ne_peut_pas_creer_de_jeton(self):
        client = APIClient()

        reponse = client.post(
            reverse('console-organisation-instances', args=[self.organisation.id]),
            {}, format='json',
        )

        self.assertIn(reponse.status_code, (401, 403))
        self.assertFalse(SyncInstance.objects.exists())


class ListeSansJetonTests(Base):
    """LE point de la conception : le jeton permet d'agir au nom de n'importe quel employe de
    l'etablissement. Le laisser lisible en permanence dans une page web l'exposerait aux captures
    d'ecran, aux partages d'ecran, et aux comptes editeurs d'anciens collaborateurs."""

    def test_la_liste_ne_contient_jamais_le_jeton(self):
        creation = self._creer()
        jeton = creation.data['token']

        reponse = self._lister()

        self.assertEqual(reponse.status_code, 200)
        self.assertNotIn(jeton, str(reponse.data))
        self.assertNotIn('token', reponse.data['instances'][0])

    def test_la_liste_donne_de_quoi_surveiller_le_poste(self):
        self._creer(nom='Poste terrasse')

        instances = self._lister().data['instances']

        self.assertEqual(instances[0]['nom'], 'Poste terrasse')
        self.assertTrue(instances[0]['actif'])
        self.assertIn('dernier_contact', instances[0])
        self.assertIn('operations_en_attente', instances[0])


class RevocationTests(Base):
    def _revoquer(self, instance):
        return self.client.post(reverse(
            'console-organisation-instance-revoquer',
            args=[self.organisation.id, instance.id],
        ))

    def test_revoquer_coupe_le_poste_sans_effacer_son_historique(self):
        """La ligne porte la date du dernier contact et ce qui restait a remonter : deux
        informations qu'on veut encore pouvoir lire apres un vol."""
        self._creer()
        instance = SyncInstance.objects.get()

        reponse = self._revoquer(instance)

        self.assertEqual(reponse.status_code, 200)
        instance.refresh_from_db()
        self.assertFalse(instance.is_active)
        self.assertTrue(SyncInstance.objects.filter(pk=instance.pk).exists())

    def test_la_revocation_est_journalisee(self):
        self._creer()

        self._revoquer(SyncInstance.objects.get())

        self.assertTrue(Journal.objects.filter(action='revocation_instance_locale').exists())

    def test_revoquer_deux_fois_ne_journalise_qu_une_fois(self):
        self._creer()
        instance = SyncInstance.objects.get()
        self._revoquer(instance)

        self._revoquer(instance)

        self.assertEqual(
            Journal.objects.filter(action='revocation_instance_locale').count(), 1
        )

    def test_on_ne_revoque_pas_le_poste_d_un_autre_etablissement(self):
        autre = Organisation.objects.create(name=f'Org {uuid.uuid4()}')
        etranger = SyncInstance.objects.create(organisation=autre, name='Poste voisin')

        reponse = self.client.post(reverse(
            'console-organisation-instance-revoquer',
            args=[self.organisation.id, etranger.id],
        ))

        self.assertEqual(reponse.status_code, 404)
        etranger.refresh_from_db()
        self.assertTrue(etranger.is_active)
