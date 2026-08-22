from rest_framework import serializers
from decimal import Decimal
from .models import Product, StockRequest, Category, DepartmentStock, StockMovement, PurchaseOrder, Avarie, BudgetRequest

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'description']

class ProductSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(),
        source='category',
        required=False,
        allow_null=True,
        write_only=True
    )
    is_below_threshold = serializers.SerializerMethodField()
    margin = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    margin_percent = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = Product
        fields = [
            'id', 'code', 'name', 'description', 'purchase_price', 'price',
            'margin', 'margin_percent', 'image_url', 'stock_quantity',
            'min_threshold', 'unit', 'category', 'category_id', 'is_below_threshold',
            'is_active', 'is_consignable', 'deposit_amount'
        ]

    def validate(self, attrs):
        request = self.context.get('request')
        category = attrs.get('category')
        if category and request and category.organisation != request.user.organisation:
            raise serializers.ValidationError({'category_id': 'Categorie invalide pour cette organisation.'})
        return attrs

    def get_is_below_threshold(self, obj):
        return obj.is_below_threshold()


class StockRequestSerializer(serializers.ModelSerializer):
    product_name = serializers.ReadOnlyField(source='product.name')
    organisation = serializers.PrimaryKeyRelatedField(read_only=True)
    requested_by = serializers.CharField(read_only=True)

    class Meta:
        model = StockRequest
        fields = [
            'id', 'product', 'product_name', 'requested_quantity', 'status',
            'requested_by', 'created_at', 'updated_at', 'organisation'
        ]
        read_only_fields = ['status', 'created_at', 'updated_at', 'requested_by', 'organisation']

class BudgetRequestSerializer(serializers.ModelSerializer):
    approvisionneur_name = serializers.ReadOnlyField(source='approvisionneur.name')
    department_name = serializers.ReadOnlyField(source='department.name')
    reviewed_by_name = serializers.ReadOnlyField(source='reviewed_by.name')

    class Meta:
        model = BudgetRequest
        fields = [
            'id', 'approvisionneur', 'approvisionneur_name', 'department', 'department_name',
            'requested_amount', 'note', 'status', 'created_at',
            'validated_amount', 'reviewed_at', 'reviewed_by', 'reviewed_by_name',
        ]
        read_only_fields = [
            'approvisionneur', 'approvisionneur_name', 'department_name', 'status', 'created_at',
            'validated_amount', 'reviewed_at', 'reviewed_by', 'reviewed_by_name',
        ]


class DepartmentStockSerializer(serializers.ModelSerializer):
    product_name = serializers.ReadOnlyField(source='product.name')
    product_code = serializers.ReadOnlyField(source='product.code')
    product_image = serializers.ReadOnlyField(source='product.image_url')
    department_name = serializers.ReadOnlyField(source='department.name')
    family_name = serializers.ReadOnlyField(source='family.name')
    margin = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    margin_percent = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = DepartmentStock
        fields = [
            'id', 'organisation', 'department', 'department_name', 'product',
            'product_name', 'product_code', 'product_image', 'family', 'family_name', 'quantity',
            'weighted_average_cost', 'sale_price', 'margin', 'margin_percent', 'min_threshold', 'updated_at'
        ]
        read_only_fields = ['organisation', 'updated_at']

class StockMovementSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockMovement
        fields = '__all__'
        read_only_fields = ['organisation', 'author', 'created_at']

class StockReceptionSerializer(serializers.Serializer):
    department = serializers.UUIDField()
    product = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1)
    unit_purchase_price = serializers.DecimalField(max_digits=10, decimal_places=2)
    unit_sale_price = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    purchase_order = serializers.UUIDField(required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True)

class StockTransferSerializer(serializers.Serializer):
    source_department = serializers.UUIDField()
    destination_department = serializers.UUIDField()
    product = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1)
    note = serializers.CharField(required=False, allow_blank=True)

class PurchaseOrderSerializer(serializers.ModelSerializer):
    product_name = serializers.ReadOnlyField(source='product.name')
    author_name = serializers.ReadOnlyField(source='author.name')

    class Meta:
        model = PurchaseOrder
        fields = [
            'id', 'product', 'product_name', 'supplier_name', 'quantity',
            'estimated_unit_cost', 'status', 'note', 'created_at', 'author', 'author_name'
        ]
        read_only_fields = ['status', 'created_at', 'author', 'author_name']

class AvarieSerializer(serializers.ModelSerializer):
    product_name = serializers.ReadOnlyField(source='product.name')
    department_name = serializers.ReadOnlyField(source='department.name')
    author_name = serializers.ReadOnlyField(source='author.name')

    class Meta:
        model = Avarie
        fields = [
            'id', 'department', 'department_name', 'product', 'product_name',
            'quantity', 'reason', 'note', 'created_at', 'author', 'author_name'
        ]
        read_only_fields = ['created_at', 'author', 'author_name']
