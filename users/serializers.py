from rest_framework import serializers
from django.contrib.auth.models import Permission
from .models import User, DEFAULT_PASSWORD
from .phone import normalize_phone
from django.contrib.auth import authenticate
from django.utils import timezone
from datetime import timedelta

MANAGEABLE_PERMISSION_CODENAMES = ['manage_users', 'manage_user_permissions']

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            'id', 'name', 'phone', 'role', 'organisation', 'can_transfer_stock', 'departments',
            'available_budget',
            'must_change_password',
        ]

class LoginSerializer(serializers.Serializer):
    phone = serializers.CharField()
    password = serializers.CharField(write_only=True)
    device_date = serializers.DateTimeField(required=False, allow_null=True, write_only=True)

    def validate(self, data):
        phone = normalize_phone(data.get('phone', ''))
        user = User.objects.filter(phone=phone).first()
        if not user:
            raise serializers.ValidationError("Identifiants invalides")

        password = data.get('password', '')
        expired = (
            user.must_change_password and
            user.password_reset_expires_at and
            user.password_reset_expires_at <= timezone.now()
        )

        if user.check_password(password):
            if expired:
                user.set_password(DEFAULT_PASSWORD)
                user.must_change_password = True
                user.password_reset_expires_at = timezone.now() + timedelta(minutes=10)
                user.save(update_fields=['password', 'must_change_password', 'password_reset_expires_at'])
                raise serializers.ValidationError({
                    'detail': 'Le mot de passe temporaire a expire. Le mot de passe par defaut a ete applique. Connectez-vous avec "password123" et changez-le imm?diatement.'
                })
            data['user'] = user
            return data

        if expired and password == DEFAULT_PASSWORD and user.check_password(DEFAULT_PASSWORD):
            data['user'] = user
            return data

        raise serializers.ValidationError("Identifiants invalides")

class UserListSerializer(serializers.ModelSerializer):
    permissions = serializers.SerializerMethodField()
    assigned_cashier_name = serializers.ReadOnlyField(source='assigned_cashier.name')

    class Meta:
        model = User
        fields = [
            'id', 'name', 'phone', 'role', 'organisation', 'departments',
            'can_transfer_stock', 'is_active', 'created_at', 'permissions',
            'assigned_cashier', 'assigned_cashier_name', 'available_budget',
            'must_change_password',
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


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)

    def validate(self, data):
        user = self.context['request'].user
        if not user.check_password(data['current_password']):
            raise serializers.ValidationError({'current_password': 'Mot de passe actuel incorrect.'})
        if data['current_password'] == data['new_password']:
            raise serializers.ValidationError({'new_password': 'Le nouveau mot de passe doit etre different.'})
        return data

