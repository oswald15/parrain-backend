from django.utils import timezone
from rest_framework import serializers

from organisations.models import Organisation

from .models import Abonnement, CodeActivation, Editeur, Formule, Journal, Paiement


class EditeurLoginSerializer(serializers.Serializer):
    email = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        try:
            editeur = Editeur.objects.get(email=data['email'])
        except Editeur.DoesNotExist:
            raise serializers.ValidationError("Identifiants invalides.")
        if not editeur.is_active or not editeur.check_password(data['password']):
            raise serializers.ValidationError("Identifiants invalides.")
        data['editeur'] = editeur
        return data


class EditeurSerializer(serializers.ModelSerializer):
    class Meta:
        model = Editeur
        fields = ['id', 'nom', 'email', 'is_active', 'cree_le']
        read_only_fields = ['id', 'cree_le']


class EditeurCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = Editeur
        fields = ['id', 'nom', 'email', 'password', 'is_active', 'cree_le']
        read_only_fields = ['id', 'cree_le']

    def create(self, validated_data):
        password = validated_data.pop('password')
        return Editeur.objects.create_editeur(password=password, **validated_data)


class FormuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Formule
        fields = ['id', 'libelle', 'duree_jours', 'montant_xaf', 'active']


class OrganisationConsoleListSerializer(serializers.ModelSerializer):
    date_expiration_courante = serializers.SerializerMethodField()
    jours_restants = serializers.SerializerMethodField()

    class Meta:
        model = Organisation
        fields = [
            'id', 'name', 'ville', 'phone_contact', 'statut', 'archivee',
            'date_expiration_courante', 'jours_restants',
        ]

    def _abonnement_courant(self, obj):
        # exclude(statut='remplace') et non filter(statut='en_cours') : voir
        # ServiceLicence.etat() (meme raisonnement - un abonnement bloque/expire reste "le
        # courant" tant qu'aucun renouvellement ne l'a remplace).
        if not hasattr(obj, '_abo_courant_cache'):
            obj._abo_courant_cache = obj.abonnements.exclude(statut='remplace').order_by('-date_expiration').first()
        return obj._abo_courant_cache

    def get_date_expiration_courante(self, obj):
        abo = self._abonnement_courant(obj)
        return abo.date_expiration if abo else None

    def get_jours_restants(self, obj):
        abo = self._abonnement_courant(obj)
        if not abo:
            return None
        return (abo.date_expiration - timezone.now()).days


class OrganisationConsoleCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organisation
        fields = ['id', 'name', 'description', 'address', 'ville', 'phone_contact']
        read_only_fields = ['id']


class OrganisationConsoleDetailSerializer(serializers.ModelSerializer):
    etat = serializers.SerializerMethodField()
    supadmin_nom = serializers.ReadOnlyField(source='supadmin.name')
    supadmin_phone = serializers.ReadOnlyField(source='supadmin.phone')

    class Meta:
        model = Organisation
        fields = [
            'id', 'name', 'description', 'address', 'ville', 'phone_contact',
            'statut', 'archivee', 'supadmin', 'supadmin_nom', 'supadmin_phone',
            'derniere_activite_le', 'created_at', 'etat',
        ]
        # statut/archivee/derniere_activite_le pilotes exclusivement par ServiceLicence et les
        # actions dediees (suspendre/reactiver/archiver/consommer_code) - jamais par un PATCH
        # direct, meme depuis la console. 'supadmin' reste PATCHable directement (rattachement
        # manuel a un compte deja existant) mais SuperadminCreateView (creer + lier en une
        # fois) est le chemin normal, voir plus bas.
        read_only_fields = [
            'id', 'statut', 'archivee', 'derniere_activite_le', 'created_at', 'etat',
            'supadmin_nom', 'supadmin_phone',
        ]

    def get_etat(self, obj):
        from .services.licence import ServiceLicence
        return ServiceLicence.etat(obj)


class SuperadminCreateSerializer(serializers.Serializer):
    """Cree le compte users.User (role=superadmin) representant l'organisation, ET le lie
    (Organisation.supadmin) en une seule action - voir SuperadminCreateView. Ecriture
    deliberee et etroite de la console dans le modele metier users.User, limitee a ce seul cas
    d'usage (bootstrap du premier compte d'une organisation) ; tout le reste (employes,
    departements, catalogue...) continue de se gerer depuis 'Administration', jamais depuis la
    console (CONSOLE-SYSTEME.md, vocabulaire section 0)."""
    name = serializers.CharField(max_length=100)
    phone = serializers.CharField(max_length=20)
    password = serializers.CharField(min_length=6, write_only=True)

    def validate_phone(self, value):
        from users.models import User
        if User.objects.filter(phone=value).exists():
            raise serializers.ValidationError('Ce numéro de téléphone est déjà utilisé.')
        return value


class AbonnementSerializer(serializers.ModelSerializer):
    formule_libelle = serializers.ReadOnlyField(source='formule.libelle')

    class Meta:
        model = Abonnement
        fields = [
            'id', 'formule', 'formule_libelle', 'date_debut', 'date_expiration',
            'montant_xaf', 'statut', 'cree_le',
        ]
        read_only_fields = fields


class CodeActivationSerializer(serializers.ModelSerializer):
    formule_libelle = serializers.ReadOnlyField(source='formule.libelle')
    emis_par_nom = serializers.ReadOnlyField(source='emis_par.nom')

    class Meta:
        model = CodeActivation
        fields = [
            'id', 'numero_serie', 'formule', 'formule_libelle', 'duree_jours',
            'emis_le', 'emis_par', 'emis_par_nom', 'expire_le', 'utilise_le', 'statut',
        ]
        read_only_fields = fields


class PaiementSerializer(serializers.ModelSerializer):
    saisi_par_nom = serializers.ReadOnlyField(source='saisi_par.nom')

    class Meta:
        model = Paiement
        fields = [
            'id', 'organisation', 'montant_xaf', 'operateur', 'reference',
            'recu_le', 'saisi_par', 'saisi_par_nom', 'note',
        ]
        read_only_fields = ['id', 'saisi_par', 'saisi_par_nom']


class JournalSerializer(serializers.ModelSerializer):
    acteur_nom = serializers.ReadOnlyField(source='acteur.nom')
    organisation_nom = serializers.ReadOnlyField(source='organisation.name')

    class Meta:
        model = Journal
        fields = ['id', 'acteur', 'acteur_nom', 'action', 'organisation', 'organisation_nom', 'details', 'fait_le']
        read_only_fields = fields


class EmettreCodeSerializer(serializers.Serializer):
    organisation = serializers.PrimaryKeyRelatedField(queryset=Organisation.objects.filter(archivee=False))
    formule = serializers.PrimaryKeyRelatedField(queryset=Formule.objects.filter(active=True))
