import uuid

from django.urls import path
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.test import APIClient
from rest_framework.views import APIView

from organisations.models import Organisation
from sync.mixins import IdempotencyMixin
from sync.models import IdempotencyRecord
from users.models import User

# Compteur d'executions reelles du handler : c'est lui qui prouve qu'un rejeu n'a PAS
# re-execute l'action (le seul test qui compte vraiment pour une vente).
EXECUTIONS = {'count': 0}


class _ProbeView(IdempotencyMixin, APIView):
    """Vue d'essai : renvoie le statut demande dans le corps, en comptant ses executions."""

    def post(self, request):
        EXECUTIONS['count'] += 1
        requested_status = int(request.data.get('status', 201))
        return Response({'echo': request.data.get('echo', 'ok')}, status=requested_status)


urlpatterns = [path('probe/', _ProbeView.as_view())]


@override_settings(ROOT_URLCONF='sync.tests')
class IdempotencyMixinTests(TestCase):
    def setUp(self):
        EXECUTIONS['count'] = 0
        self.organisation = Organisation.objects.create(name=f'Org {uuid.uuid4()}')
        self.user = User.objects.create(
            organisation=self.organisation, role='caissier', name='Caissier Test',
            phone=f'{uuid.uuid4().int % 10**9:09d}',
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.key = str(uuid.uuid4())

    def _post(self, payload=None, key=None):
        return self.client.post(
            '/probe/', payload or {'echo': 'vente'}, format='json',
            HTTP_IDEMPOTENCY_KEY=key or self.key,
        )

    def test_sans_cle_le_comportement_est_inchange(self):
        """Garde-fou de non-regression : les appels en ligne actuels n'envoient pas d'entete."""
        self.client.post('/probe/', {'echo': 'a'}, format='json')
        self.client.post('/probe/', {'echo': 'a'}, format='json')

        self.assertEqual(EXECUTIONS['count'], 2)
        self.assertEqual(IdempotencyRecord.objects.count(), 0)

    def test_rejeu_ne_reexecute_pas_et_renvoie_la_reponse_dorigine(self):
        first = self._post()
        second = self._post()

        self.assertEqual(EXECUTIONS['count'], 1, "Le rejeu a re-execute l'action")
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.data, first.data)
        self.assertEqual(IdempotencyRecord.objects.count(), 1)

    def test_un_4xx_deterministe_est_memorise(self):
        """Une action deja faite renvoie souvent 400 ("cet onglet n'est plus ouvert") : le rejeu
        doit renvoyer ce meme 400, pas re-executer l'action."""
        first = self._post({'echo': 'x', 'status': 400})
        second = self._post({'echo': 'x', 'status': 400})

        self.assertEqual(EXECUTIONS['count'], 1)
        self.assertEqual(first.status_code, 400)
        self.assertEqual(second.status_code, 400)
        self.assertEqual(
            IdempotencyRecord.objects.get().state, IdempotencyRecord.STATE_COMPLETED
        )

    def test_un_403_nest_pas_memorise(self):
        """Condition passagere (token/permission) : la cle doit rester libre pour un vrai rejeu."""
        response = self._post({'echo': 'x', 'status': 403})

        self.assertEqual(response.status_code, 403)
        self.assertEqual(IdempotencyRecord.objects.count(), 0)

    def test_un_5xx_libere_la_cle_pour_permettre_un_vrai_rejeu(self):
        first = self._post({'echo': 'x', 'status': 500})
        self.assertEqual(first.status_code, 500)
        self.assertEqual(IdempotencyRecord.objects.count(), 0)

        second = self._post({'echo': 'x', 'status': 201})

        self.assertEqual(EXECUTIONS['count'], 2, 'Apres une panne, le rejeu doit reexecuter')
        self.assertEqual(second.status_code, 201)

    def test_meme_cle_avec_un_contenu_different_est_refusee(self):
        self._post({'echo': 'vente A'})
        response = self._post({'echo': 'vente B'})

        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertEqual(response.data['code'], 'idempotency_key_reuse')
        self.assertEqual(EXECUTIONS['count'], 1)

    def test_deux_cles_differentes_sont_deux_actions_distinctes(self):
        self._post(key=str(uuid.uuid4()))
        self._post(key=str(uuid.uuid4()))

        self.assertEqual(EXECUTIONS['count'], 2)
        self.assertEqual(IdempotencyRecord.objects.count(), 2)

    def test_la_cle_est_cloisonnee_par_organisation(self):
        """Deux organisations peuvent emettre la meme cle sans interferer."""
        other_org = Organisation.objects.create(name=f'Org {uuid.uuid4()}')
        other_user = User.objects.create(
            organisation=other_org, role='caissier', name='Autre Caissier',
            phone=f'{uuid.uuid4().int % 10**9:09d}',
        )
        self._post()

        other_client = APIClient()
        other_client.force_authenticate(user=other_user)
        response = other_client.post(
            '/probe/', {'echo': 'vente'}, format='json', HTTP_IDEMPOTENCY_KEY=self.key
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(EXECUTIONS['count'], 2)
        self.assertEqual(IdempotencyRecord.objects.count(), 2)

    def test_une_trace_en_cours_repond_de_reessayer(self):
        IdempotencyRecord.objects.create(
            organisation=self.organisation, user=self.user, key=self.key,
            method='POST', path='/probe/',
            request_fingerprint=self._fingerprint(),
        )

        response = self._post()

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data['code'], 'idempotency_in_progress')
        self.assertEqual(EXECUTIONS['count'], 0)

    def _fingerprint(self):
        from unittest.mock import Mock

        from sync.mixins import compute_fingerprint

        return compute_fingerprint(Mock(data={'echo': 'vente'}))
