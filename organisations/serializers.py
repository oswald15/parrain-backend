from rest_framework import serializers
from .models import Organisation, Department, BusinessDay, CashierDayBalance

class OrganisationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organisation
        fields = '__all__'
        # statut/archivee/derniere_activite_le/supadmin pilotent le cycle de licence -
        # ServiceLicence (app console) est le seul ecrivain autorise. Aucun role metier
        # (y compris superadmin, qui recoit ce serializer complet) ne doit pouvoir les
        # modifier via l'API - c'est l'interdit explicite "un supadmin ne peut jamais
        # modifier sa propre date d'expiration, par quelque chemin que ce soit".
        read_only_fields = ['statut', 'archivee', 'derniere_activite_le', 'supadmin']

class OrganisationAdminUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organisation
        fields = ['name', 'description', 'address', 'phone_contact']

class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = [
            'id', 'organisation', 'name', 'budget', 'is_active',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['organisation', 'created_at', 'updated_at']


class CashierDayBalanceSerializer(serializers.ModelSerializer):
    cashier_name = serializers.ReadOnlyField(source='cashier.name')

    class Meta:
        model = CashierDayBalance
        fields = ['id', 'cashier', 'cashier_name', 'opening_amount', 'closing_amount']
        read_only_fields = fields


class BusinessDaySerializer(serializers.ModelSerializer):
    opened_by_name = serializers.ReadOnlyField(source='opened_by.name')
    closed_by_name = serializers.ReadOnlyField(source='closed_by.name')
    cashier_balances = CashierDayBalanceSerializer(many=True, read_only=True)

    class Meta:
        model = BusinessDay
        fields = [
            'id', 'date', 'is_open',
            'opened_at', 'opened_by', 'opened_by_name',
            'closed_at', 'closed_by', 'closed_by_name',
            'cashier_balances',
        ]
        read_only_fields = [
            'date', 'is_open', 'opened_at', 'opened_by', 'opened_by_name',
            'closed_at', 'closed_by', 'closed_by_name', 'cashier_balances',
        ]
