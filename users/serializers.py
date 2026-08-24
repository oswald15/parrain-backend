from rest_framework import serializers
from django.contrib.auth.models import Permission
from .models import User
from .phone import normalize_phone
from django.contrib.auth import authenticate

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            'id', 'name', 'phone', 'role', 'organisation', 'can_transfer_stock', 'departments',
            'available_budget',
        ]

class LoginSerializer(serializers.Serializer):
    phone = serializers.CharField()
    password = serializers.CharField(write_only=True)
    # Optionnel : protection anti-recul d'horloge (console.services.licence). Absent = verifie
    # aupres d'aucun poste - compatibilite avec les clients qui ne l'envoient pas encore.
    device_date = serializers.DateTimeField(required=False, allow_null=True, write_only=True)

    def validate(self, data):
        # Meme si un compte a ete cree avec un numero mal normalise (corrige a la source
        # ci-dessous), tolerer les variantes de saisie au login est une defense en profondeur
        # peu couteuse.
        phone = normalize_phone(data.get('phone', ''))
        user = authenticate(phone=phone, password=data.get('password'))
        if not user:
            raise serializers.ValidationError("Identifiants invalides")
        data['user'] = user
        return data


# Whitelist of "métier" permissions exposable in the admin UI (excludes Django's
# default CRUD permissions auto-generated for every model).
MANAGEABLE_PERMISSION_CODENAMES = [
    'manage_users',
    'manage_user_permissions',
    'view_global_revenue',
    'close_any_order',
]


class UserListSerializer(serializers.ModelSerializer):
    permissions = serializers.SerializerMethodField()
    assigned_cashier_name = serializers.ReadOnlyField(source='assigned_cashier.name')

    class Meta:
        model = User
        fields = [
            'id', 'name', 'phone', 'role', 'organisation', 'departments',
            'can_transfer_stock', 'is_active', 'created_at', 'permissions',
            'assigned_cashier', 'assigned_cashier_name', 'available_budget',
        ]

    def get_permissions(self, obj):
        return list(
            obj.user_permissions.filter(codename__in=MANAGEABLE_PERMISSION_CODENAMES)
            .values_list('codename', flat=True)
        )


class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = [
            'id', 'name', 'phone', 'password', 'role', 'departments', 'can_transfer_stock',
            'assigned_cashier',
        ]

    def validate_phone(self, value):
        return normalize_phone(value)

    def validate_role(self, value):
        request = self.context.get('request')
        creator = request.user if request else None
        if value == 'superadmin' and (not creator or creator.role != 'superadmin'):
            raise serializers.ValidationError(
                "Seul un Super Admin peut créer un compte Super Admin."
            )
        return value

    def validate_assigned_cashier(self, value):
        if value is not None and value.role != 'caissier':
            raise serializers.ValidationError("Le caissier assigne doit avoir le role 'caissier'.")
        return value

    def create(self, validated_data):
        departments = validated_data.pop('departments', [])
        request = self.context.get('request')
        validated_data['organisation'] = request.user.organisation
        user = User.objects.create_user(**validated_data)
        if departments:
            user.departments.set(departments)
        return user


class UserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            'id', 'name', 'phone', 'role', 'departments', 'can_transfer_stock', 'is_active',
            'assigned_cashier',
        ]

    def validate_phone(self, value):
        return normalize_phone(value)

    def validate_role(self, value):
        request = self.context.get('request')
        creator = request.user if request else None
        if value == 'superadmin' and (not creator or creator.role != 'superadmin'):
            raise serializers.ValidationError(
                "Seul un Super Admin peut promouvoir un utilisateur en Super Admin."
            )
        return value

    def validate_assigned_cashier(self, value):
        if value is not None and value.role != 'caissier':
            raise serializers.ValidationError("Le caissier assigne doit avoir le role 'caissier'.")
        return value


class UserPermissionsSerializer(serializers.Serializer):
    permissions = serializers.ListField(child=serializers.CharField(), allow_empty=True)

    def validate_permissions(self, value):
        invalid = set(value) - set(MANAGEABLE_PERMISSION_CODENAMES)
        if invalid:
            raise serializers.ValidationError(f"Permissions inconnues: {', '.join(invalid)}")
        return value

