from rest_framework import serializers
from .models import Order, OrderItem, CashExpense, Transaction, Consignment, ClientTab, Bon, BonItem


class OrderItemSerializer(serializers.ModelSerializer):
    product_name = serializers.ReadOnlyField(source='product.name')
    product_image = serializers.ReadOnlyField(source='product.image_url')
    is_consignable = serializers.ReadOnlyField(source='product.is_consignable')
    deposit_amount = serializers.ReadOnlyField(source='product.deposit_amount')

    class Meta:
        model = OrderItem
        fields = [
            'id', 'product', 'product_name', 'product_image', 'quantity', 'unit_price',
            'is_consignable', 'deposit_amount'
        ]
        read_only_fields = ['id']


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True)
    serveur_name = serializers.ReadOnlyField(source='serveur.name')
    cashier_name = serializers.ReadOnlyField(source='cashier.name')
    department_name = serializers.ReadOnlyField(source='department.name')

    class Meta:
        model = Order
        fields = [
            'id', 'number_of_customers', 'status', 'total_amount',
            'payment_type', 'created_at', 'closed_at', 'items',
            'serveur_name', 'cashier_name', 'client_name', 'department',
            'department_name'
        ]
        read_only_fields = [
            'created_at', 'closed_at', 'total_amount',
            'serveur_name', 'cashier_name', 'department_name'
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Les lignes retirées (is_removed=True) restent en base pour l'archivage
        # mais ne doivent plus apparaitre dans l'etat courant de la commande.
        data['items'] = OrderItemSerializer(instance.items.filter(is_removed=False), many=True).data
        return data

    def create(self, validated_data):
        items_data = validated_data.pop('items')
        order = Order.objects.create(**validated_data)
        total = 0
        quantity = 0
        for item in items_data:
            OrderItem.objects.create(order=order, **item)
            total += item['quantity'] * item['unit_price']
            quantity += item['quantity']
        order.total_amount = total
        order.save()
        Transaction.objects.create(
            organisation=order.organisation,
            department=order.department,
            transaction_type='facturation',
            number=str(order.id),
            quantity=quantity,
            amount=order.total_amount,
            waitress_code=order.serveur.phone if order.serveur else '',
            serveur=order.serveur,
            client=order.client_name,
            order=order,
            author=order.serveur,
        )
        return order

    def update(self, instance, validated_data):
        items_data = validated_data.pop('items', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if items_data:
            for item_data in items_data:
                product = item_data.get('product')
                quantity = item_data.get('quantity')
                unit_price = item_data.get('unit_price')

                order_item, created = OrderItem.objects.get_or_create(
                    order=instance,
                    product=product,
                    defaults={'quantity': quantity, 'unit_price': unit_price}
                )

                if not created:
                    order_item.quantity += quantity
                    order_item.unit_price = unit_price
                    order_item.save()

        instance.total_amount = sum(
            item.quantity * item.unit_price
            for item in instance.items.filter(is_removed=False)
        )

        if instance.status == 'fermee' and not instance.closed_at:
            from django.utils import timezone
            instance.closed_at = timezone.now()

        instance.save()
        return instance


class CashExpenseSerializer(serializers.ModelSerializer):
    cashier_name = serializers.ReadOnlyField(source='cashier.name')

    class Meta:
        model = CashExpense
        fields = [
            'id', 'organisation', 'cashier', 'cashier_name', 'expense_type',
            'motif', 'label', 'amount', 'description', 'created_at'
        ]
        read_only_fields = ['organisation', 'cashier', 'cashier_name', 'created_at']

    def validate(self, data):
        if not data.get('expense_type') or not data.get('motif') or not data.get('amount'):
            raise serializers.ValidationError('Type de depense, motif et montant sont obligatoires.')
        return data


class TransactionSerializer(serializers.ModelSerializer):
    department_name = serializers.ReadOnlyField(source='department.name')
    destination_department_name = serializers.ReadOnlyField(source='destination_department.name')
    serveur_name = serializers.ReadOnlyField(source='serveur.name')
    author_name = serializers.ReadOnlyField(source='author.name')
    product_name = serializers.ReadOnlyField(source='product.name')

    class Meta:
        model = Transaction
        fields = '__all__'


class BonItemSerializer(serializers.ModelSerializer):
    product_name = serializers.ReadOnlyField(source='product.name')
    product_image = serializers.ReadOnlyField(source='product.image_url')
    is_consignable = serializers.ReadOnlyField(source='product.is_consignable')
    deposit_amount = serializers.ReadOnlyField(source='product.deposit_amount')

    class Meta:
        model = BonItem
        fields = [
            'id', 'product', 'product_name', 'product_image', 'quantity', 'unit_price',
            'is_consignable', 'deposit_amount'
        ]


class BonSerializer(serializers.ModelSerializer):
    department_name = serializers.ReadOnlyField(source='department.name')
    created_by_name = serializers.ReadOnlyField(source='created_by.name')
    validated_by_name = serializers.ReadOnlyField(source='validated_by.name')
    cancelled_by_name = serializers.ReadOnlyField(source='cancelled_by.name')
    items = BonItemSerializer(many=True, read_only=True)

    class Meta:
        model = Bon
        fields = [
            'id', 'order', 'department', 'department_name', 'status', 'total_amount',
            'created_at', 'created_by', 'created_by_name', 'validated_at', 'validated_by',
            'validated_by_name', 'cancelled_at', 'cancelled_by',
            'cancelled_by_name', 'items'
        ]
        read_only_fields = [
            'status', 'total_amount', 'created_at', 'created_by', 'created_by_name',
            'validated_at', 'validated_by', 'validated_by_name',
            'cancelled_at', 'cancelled_by', 'cancelled_by_name', 'items'
        ]


class ClientTabSerializer(serializers.ModelSerializer):
    serveur_name = serializers.ReadOnlyField(source='serveur.name')
    orders = OrderSerializer(many=True, read_only=True)
    bons = BonSerializer(many=True, read_only=True)

    class Meta:
        model = ClientTab
        fields = [
            'id', 'client_name', 'status', 'total_amount', 'serveur', 'serveur_name',
            'created_at', 'invoiced_at', 'closed_at', 'orders', 'bons'
        ]
        read_only_fields = [
            'status', 'total_amount', 'serveur', 'serveur_name', 'created_at',
            'invoiced_at', 'closed_at', 'orders', 'bons'
        ]


class ConsignmentSerializer(serializers.ModelSerializer):
    product_name = serializers.ReadOnlyField(source='product.name')
    product_image = serializers.ReadOnlyField(source='product.image_url')
    department_name = serializers.ReadOnlyField(source='department.name')
    created_by_name = serializers.ReadOnlyField(source='created_by.name')
    returned_by_name = serializers.ReadOnlyField(source='returned_by.name')

    class Meta:
        model = Consignment
        fields = [
            'id', 'order', 'department', 'department_name', 'product', 'product_name', 'product_image',
            'client_name', 'quantity', 'unit_deposit_amount', 'status', 'created_at',
            'created_by', 'created_by_name', 'returned_at', 'returned_by', 'returned_by_name'
        ]
        read_only_fields = [
            'status', 'created_at', 'created_by', 'created_by_name',
            'returned_at', 'returned_by', 'returned_by_name'
        ]
