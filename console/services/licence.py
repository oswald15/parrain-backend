"""Point de controle unique du cycle de licence (voir CONSOLE-SYSTEME.md section 5).
Aucune vue ni middleware ne doit reimplementer ces regles ailleurs - tout passe par
ServiceLicence.etat() / emettre_code() / consommer_code()."""
import base64
import hashlib
from datetime import timedelta

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from organisations.services.verification_licence import construire_payload, verifier_signature

from ..exceptions import CodeDejaUtilise, CodePerime, OrganisationNonCorrespondante, SignatureInvalide
from ..models import Abonnement, CodeActivation, Journal
from .code_format import generer_code_clair, generer_numero_serie, normaliser

DUREE_GRACE = timedelta(days=7)
DUREE_EXPIRATION_CODE_NON_UTILISE = timedelta(days=30)


def _empreinte(code_clair):
    return hashlib.sha256(code_clair.encode('utf-8')).hexdigest()


def _signer(payload_bytes):
    clef_privee = Ed25519PrivateKey.from_private_bytes(
        base64.b64decode(settings.EDITEUR_ED25519_PRIVATE_KEY_B64)
    )
    return base64.b64encode(clef_privee.sign(payload_bytes)).decode()


class ServiceLicence:

    @staticmethod
    def etat(organisation):
        """{'statut', 'jours_restants', 'message'} - lit et, si necessaire, ecrit
        organisation.statut (champ denormalise, jamais touche ailleurs). Appele par le
        middleware de blocage a chaque requete non exemptee, et a la connexion pour le
        bandeau d'alerte."""
        if organisation.statut == 'suspendue':
            return {
                'statut': 'suspendue', 'jours_restants': None,
                'message': "Compte suspendu par l'éditeur.",
            }

        now = timezone.now()
        # exclude(statut='remplace') plutot que filter(statut='en_cours') : la branche
        # "bloquee" ci-dessous bascule cet abonnement a statut='expire' comme effet de bord -
        # un filtre strict sur 'en_cours' ne le retrouverait plus au prochain appel et ferait
        # regresser l'organisation a 'en_attente' au lieu de rester 'bloquee'. 'remplace' est
        # le seul statut qui signifie vraiment "il existe un abonnement plus recent, ignorer
        # celui-ci" (voir consommer_code).
        abo = organisation.abonnements.exclude(statut='remplace').order_by('-date_expiration').first()
        if not abo:
            ServiceLicence._appliquer_transition(organisation, 'en_attente')
            return {'statut': 'en_attente', 'jours_restants': None, 'message': "Aucun abonnement actif."}

        jours_restants = (abo.date_expiration - now).days
        if now <= abo.date_expiration:
            nouveau_statut = 'active'
            message = f"Expire dans {jours_restants} jour(s)." if jours_restants <= 7 else None
        elif now <= abo.date_expiration + DUREE_GRACE:
            nouveau_statut = 'en_grace'
            jours_grace_restants = max((abo.date_expiration + DUREE_GRACE - now).days, 0)
            message = f"Période de grâce : {jours_grace_restants} jour(s) restant(s) avant blocage."
        else:
            nouveau_statut = 'bloquee'
            message = "Organisation bloquée. Saisissez un nouveau code d'activation pour réactiver."
            if abo.statut != 'expire':
                abo.statut = 'expire'
                abo.save(update_fields=['statut'])

        if organisation.statut != nouveau_statut:
            ServiceLicence._appliquer_transition(organisation, nouveau_statut)

        return {'statut': nouveau_statut, 'jours_restants': max(jours_restants, 0), 'message': message}

    @staticmethod
    def _appliquer_transition(organisation, nouveau_statut):
        organisation.statut = nouveau_statut
        organisation.save(update_fields=['statut'])

    @staticmethod
    @transaction.atomic
    def emettre_code(organisation, formule, editeur):
        """Retourne (code_clair, CodeActivation). code_clair n'est JAMAIS persiste - la vue
        d'emission (phase 4) doit le retourner une seule fois dans la reponse HTTP, sans
        jamais l'ecrire nulle part."""
        code_clair = generer_code_clair()
        numero_serie = generer_numero_serie()
        emis_le = timezone.now()
        payload = construire_payload(organisation.id, formule.duree_jours, emis_le, numero_serie)
        signature = _signer(payload)

        code = CodeActivation.objects.create(
            organisation=organisation,
            formule=formule,
            empreinte=_empreinte(code_clair),
            numero_serie=numero_serie,
            duree_jours=formule.duree_jours,
            emis_le=emis_le,
            emis_par=editeur,
            expire_le=emis_le + DUREE_EXPIRATION_CODE_NON_UTILISE,
            signature=signature,
            statut='actif',
        )
        Journal.objects.create(
            acteur=editeur, action='emission_code', organisation=organisation,
            details={
                'numero_serie': numero_serie,
                'formule': formule.libelle,
                'duree_jours': formule.duree_jours,
            },
        )
        return code_clair, code

    @staticmethod
    @transaction.atomic
    def consommer_code(organisation, code_clair, editeur=None):
        """Verifie et consomme un code, cree/prolonge l'Abonnement correspondant. Leve l'une
        des 4 exceptions de console.exceptions selon la regle en echec - ordre impose par le
        document (signature, organisation, deja-utilise, perime), chacune disant clairement
        laquelle a echoue."""
        code_normalise = normaliser(code_clair)
        empreinte = _empreinte(code_normalise)

        try:
            code = CodeActivation.objects.select_for_update().select_related('formule').get(empreinte=empreinte)
        except CodeActivation.DoesNotExist:
            raise SignatureInvalide()

        payload = construire_payload(code.organisation_id, code.duree_jours, code.emis_le, code.numero_serie)
        if not verifier_signature(payload, code.signature):
            # Defense en profondeur : la ligne existe mais sa signature ne correspond plus a
            # son contenu - n'arrive que si la base a ete modifiee hors du flux d'emission.
            raise SignatureInvalide()

        if code.organisation_id != organisation.id:
            raise OrganisationNonCorrespondante()

        if code.statut == 'utilise':
            raise CodeDejaUtilise()

        now = timezone.now()
        if code.statut == 'expire' or code.expire_le < now:
            if code.statut != 'expire':
                code.statut = 'expire'
                code.save(update_fields=['statut'])
            raise CodePerime()

        etat_avant = ServiceLicence.etat(organisation)['statut']

        if etat_avant in ('active', 'en_grace'):
            # Regle 3 : un renouvellement pendant la periode active/grace PROLONGE depuis la
            # date d'expiration en cours, il ne la remplace pas.
            abo_precedent = organisation.abonnements.exclude(statut='remplace').order_by('-date_expiration').first()
            date_debut = abo_precedent.date_debut if abo_precedent else now
            date_expiration = (abo_precedent.date_expiration if abo_precedent else now) + timedelta(days=code.duree_jours)
            if abo_precedent:
                abo_precedent.statut = 'remplace'
                abo_precedent.save(update_fields=['statut'])
        else:
            # Regle 4 : un renouvellement apres blocage ouvre une periode a compter de la saisie.
            date_debut = now
            date_expiration = now + timedelta(days=code.duree_jours)

        abonnement = Abonnement.objects.create(
            organisation=organisation,
            formule=code.formule,
            date_debut=date_debut,
            date_expiration=date_expiration,
            montant_xaf=code.formule.montant_xaf,
            statut='en_cours',
            ouvert_par_code=code,
        )

        code.statut = 'utilise'
        code.utilise_le = now
        code.save(update_fields=['statut', 'utilise_le'])

        ServiceLicence._appliquer_transition(organisation, 'active')

        if etat_avant in ('bloquee', 'suspendue'):
            Journal.objects.create(
                acteur=editeur, action='deblocage_par_code', organisation=organisation,
                details={'numero_serie': code.numero_serie},
            )

        return abonnement
