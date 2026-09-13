from rest_framework import generics, permissions, filters, status
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import ValidationError, PermissionDenied
from django.db import models
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.utils.encoding import smart_str
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.db import transaction
import os
import uuid
from decimal import Decimal, InvalidOperation
from .models import (
    Product, StockRequest, Category, DepartmentStock, StockMovement, PurchaseOrder, Avarie,
    BudgetRequest, Inventory, InventoryLine,
)
from organisations.models import Department
from orders.models import Transaction
from .serializers import (
    ProductSerializer, StockRequestSerializer, CategorySerializer,
    DepartmentStockSerializer, StockMovementSerializer,
    StockReceptionSerializer, StockTransferSerializer,
    PurchaseOrderSerializer, AvarieSerializer, BudgetRequestSerializer,
    InventorySerializer,
)
from .permissions import IsAdminOrApprovisionneur, IsAdminOnly, IsAdminOrSuperAdmin

class ProductListCreateView(generics.ListCreateAPIView):
    serializer_class = ProductSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticated(), IsAdminOrSuperAdmin()]

    def get_queryset(self):
        queryset = Product.objects.filter(organisation=self.request.user.organisation)
        active_param = self.request.query_params.get('active')
        if active_param == 'true':
            queryset = queryset.filter(is_active=True)
        elif active_param == 'false':
            queryset = queryset.filter(is_active=False)
        return queryset

    @transaction.atomic
    def perform_create(self, serializer):
        image = self.request.FILES.get('image')
        image_url = None
        if image:
            ext = os.path.splitext(image.name)[1]
            filename = f"{uuid.uuid4().hex}{ext}"
            path = f"images/{filename}"
            default_storage.save(path, ContentFile(image.read()))
            image_url = f"{settings.MEDIA_URL}images/{filename}"
        serializer.save(
            organisation=self.request.user.organisation,
            image_url=image_url
        )

class ProductRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ProductSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticated(), IsAdminOrSuperAdmin()]

    def get_queryset(self):
        return Product.objects.filter(organisation=self.request.user.organisation)

    def perform_update(self, serializer):
        instance = self.get_object()
        image = self.request.FILES.get('image')
        if image:
            if instance.image_url:
                # Les anciennes lignes peuvent encore contenir une URL absolue (avant ce
                # correctif) - on ne garde que la partie apres MEDIA_URL dans les deux cas.
                old_path = instance.image_url.split(settings.MEDIA_URL)[-1]
                if default_storage.exists(old_path):
                    default_storage.delete(old_path)
            ext = os.path.splitext(image.name)[1]
            filename = f"{uuid.uuid4().hex}{ext}"
            path = f"images/{filename}"
            default_storage.save(path, ContentFile(image.read()))
            image_url = f"{settings.MEDIA_URL}images/{filename}"
            serializer.save(image_url=image_url)
        else:
            serializer.save()

    def perform_destroy(self, instance):
        # Soft-delete : le produit reste en base (archivage), l'image aussi.
        instance.is_active = False
        instance.save()

class ProductBelowThresholdView(generics.ListAPIView):
    serializer_class = ProductSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Product.objects.filter(
            organisation=self.request.user.organisation,
            stock_quantity__lt=models.F('min_threshold')
        )

class DepartmentStockListView(generics.ListAPIView):
    serializer_class = DepartmentStockSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = DepartmentStock.objects.filter(organisation=self.request.user.organisation)
        department = self.request.query_params.get('department')
        if department:
            queryset = queryset.filter(department_id=department)
        if self.request.user.role == 'approvisionneur':
            queryset = queryset.filter(department__in=self.request.user.departments.all())

        for stock in queryset:
            if stock.product.shared_stock:
                stock.quantity = stock.product.stock_quantity
                stock.save(update_fields=['quantity'])

        return queryset

class DepartmentStockAssignView(APIView):
    """Associe un produit existant a un departement avec un prix de vente,
    independamment d'une reception physique de stock (ex: cree la ligne
    DepartmentStock avec quantite=0 si elle n'existe pas encore)."""
    permission_classes = [permissions.IsAuthenticated, IsAdminOrSuperAdmin]

    def post(self, request):
        department = get_object_or_404(
            Department, id=request.data.get('department'), organisation=request.user.organisation
        )
        product = get_object_or_404(
            Product, id=request.data.get('product'), organisation=request.user.organisation
        )
        raw_sale_price = request.data.get('sale_price')
        if raw_sale_price is None:
            return Response({'detail': 'Le prix de vente est obligatoire.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            sale_price = Decimal(str(raw_sale_price))
        except (InvalidOperation, ValueError):
            return Response({'detail': 'Prix de vente invalide.'}, status=status.HTTP_400_BAD_REQUEST)

        stock, created = DepartmentStock.objects.get_or_create(
            organisation=request.user.organisation,
            department=department,
            product=product,
            defaults={
                'family': product.category,
                'quantity': product.stock_quantity if product.shared_stock else 0,
                'weighted_average_cost': product.purchase_price,
                'sale_price': sale_price,
                'min_threshold': product.min_threshold,
            }
        )
        if product.shared_stock:
            stock.quantity = product.stock_quantity
            stock.sale_price = sale_price
            stock.save(update_fields=['quantity', 'sale_price'])
            product.sync_shared_stock_to_departments()
        else:
            if not created:
                stock.sale_price = sale_price
                stock.save()

        return Response(
            DepartmentStockSerializer(stock).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
        )

class StockMovementListView(generics.ListAPIView):
    serializer_class = StockMovementSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = StockMovement.objects.filter(organisation=self.request.user.organisation)
        department = self.request.query_params.get('department')
        if department:
            queryset = queryset.filter(department_id=department)
        return queryset

class StockReceptionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        if request.user.role not in ['superadmin', 'admin', 'approvisionneur']:
            return Response({'detail': 'Action non autorisee.'}, status=status.HTTP_403_FORBIDDEN)

        serializer = StockReceptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        reception_cost = data['quantity'] * data['unit_purchase_price']
        if request.user.role == 'approvisionneur' and reception_cost > request.user.available_budget:
            return Response(
                {'detail': f"Solde insuffisant (disponible : {request.user.available_budget}, requis : {reception_cost}). Demandez un budget a l'admin."},
                status=status.HTTP_400_BAD_REQUEST
            )

        product = get_object_or_404(Product, id=data['product'], organisation=request.user.organisation)
        department = None
        if not product.shared_stock:
            if not data.get('department'):
                return Response(
                    {'detail': 'Ce produit doit etre approvisionne dans un departement.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            department = get_object_or_404(
                Department, id=data['department'], organisation=request.user.organisation
            )
            if request.user.role == 'approvisionneur' and department not in request.user.departments.all():
                return Response({'detail': 'Departement non attribue.'}, status=status.HTTP_403_FORBIDDEN)

        family = product.category
        explicit_sale_price = data.get('unit_sale_price')
        stock = None
        sale_price = explicit_sale_price or product.price
        if department:
            stock, _ = DepartmentStock.objects.get_or_create(
                organisation=request.user.organisation,
                department=department,
                product=product,
                defaults={
                    'family': family,
                    'quantity': product.stock_quantity if product.shared_stock else 0,
                    'weighted_average_cost': data['unit_purchase_price'],
                    'sale_price': sale_price,
                    'min_threshold': product.min_threshold,
                }
            )
            if explicit_sale_price is None:
                sale_price = stock.sale_price

        if product.shared_stock:
            shared_stock_rows = DepartmentStock.objects.filter(
                organisation=request.user.organisation,
                product=product,
            )
            shared_base_quantity = shared_stock_rows.aggregate(total=models.Sum('quantity'))['total'] or 0
            old_quantity = shared_base_quantity if shared_stock_rows.exists() else product.stock_quantity
            new_quantity = old_quantity + data['quantity']
            old_value = old_quantity * product.purchase_price
            incoming_value = data['quantity'] * data['unit_purchase_price']
            product.purchase_price = (old_value + incoming_value) / new_quantity if new_quantity else data['unit_purchase_price']
            product.stock_quantity = new_quantity
            product.save()
            product.sync_shared_stock_to_departments()
            if stock:
                stock.quantity = product.stock_quantity
                stock.sale_price = sale_price
                stock.save(update_fields=['quantity', 'sale_price'])
        else:
            old_value = stock.quantity * stock.weighted_average_cost
            incoming_value = data['quantity'] * data['unit_purchase_price']
            new_quantity = stock.quantity + data['quantity']
            stock.weighted_average_cost = (old_value + incoming_value) / new_quantity
            if family:
                stock.family = family
            stock.quantity = new_quantity
            stock.sale_price = sale_price
            stock.save()

            product.stock_quantity = sum(item.quantity for item in product.department_stocks.all())
            product.save()

        movement = StockMovement.objects.create(
            organisation=request.user.organisation,
            department=department,
            family=family,
            product=product,
            movement_type='approvisionnement',
            quantity=data['quantity'],
            unit_purchase_price=data['unit_purchase_price'],
            unit_sale_price=sale_price,
            author=request.user,
            note=data.get('note')
        )
        Transaction.objects.create(
            organisation=request.user.organisation,
            department=department,
            product=product,
            transaction_type='approvisionnement',
            number=str(movement.id),
            quantity=data['quantity'],
            amount=data['quantity'] * data['unit_purchase_price'],
            author=request.user,
        )

        if request.user.role == 'approvisionneur':
            request.user.available_budget -= reception_cost
            request.user.save()

        purchase_order_id = data.get('purchase_order')
        if purchase_order_id:
            PurchaseOrder.objects.filter(
                id=purchase_order_id, organisation=request.user.organisation
            ).update(status='received')

        return Response(StockMovementSerializer(movement).data, status=status.HTTP_201_CREATED)

class StockTransferView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if request.user.role not in ['superadmin', 'admin', 'approvisionneur'] or (
            request.user.role == 'approvisionneur' and not request.user.can_transfer_stock
        ):
            return Response({'detail': 'Transfert non autorise.'}, status=status.HTTP_403_FORBIDDEN)

        serializer = StockTransferSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        product = get_object_or_404(Product, id=data['product'], organisation=request.user.organisation)

        if product.shared_stock:
            return Response(
                {'detail': 'Le transfert entre départements est désactivé en mode stock global.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        source = get_object_or_404(Department, id=data['source_department'], organisation=request.user.organisation)
        destination = get_object_or_404(Department, id=data['destination_department'], organisation=request.user.organisation)

        if request.user.role == 'approvisionneur':
            allowed = request.user.departments.all()
            if source not in allowed or destination not in allowed:
                return Response({'detail': 'Departement non attribue.'}, status=status.HTTP_403_FORBIDDEN)

        source_stock = get_object_or_404(DepartmentStock, department=source, product=product)
        if source_stock.quantity < data['quantity']:
            return Response({'detail': 'Stock insuffisant.'}, status=status.HTTP_400_BAD_REQUEST)

        destination_stock, _ = DepartmentStock.objects.get_or_create(
            organisation=request.user.organisation,
            department=destination,
            product=product,
            defaults={
                'family': source_stock.family,
                'quantity': 0,
                'weighted_average_cost': source_stock.weighted_average_cost,
                'sale_price': source_stock.sale_price,
                'min_threshold': source_stock.min_threshold,
            }
        )

        source_stock.quantity -= data['quantity']
        source_stock.save()
        destination_stock.quantity += data['quantity']
        destination_stock.weighted_average_cost = source_stock.weighted_average_cost
        if destination_stock.sale_price in (None, 0):
            destination_stock.sale_price = source_stock.sale_price
        destination_stock.save()

        movement = StockMovement.objects.create(
            organisation=request.user.organisation,
            department=source,
            family=source_stock.family,
            destination_department=destination,
            product=product,
            movement_type='transfert',
            quantity=data['quantity'],
            unit_purchase_price=source_stock.weighted_average_cost,
            unit_sale_price=source_stock.sale_price,
            author=request.user,
            note=data.get('note')
        )
        Transaction.objects.create(
            organisation=request.user.organisation,
            department=source,
            destination_department=destination,
            product=product,
            transaction_type='transfert',
            number=str(movement.id),
            quantity=data['quantity'],
            amount=data['quantity'] * source_stock.weighted_average_cost,
            author=request.user,
        )
        return Response(StockMovementSerializer(movement).data, status=status.HTTP_201_CREATED)

class StockRequestListCreateView(generics.ListCreateAPIView):
    serializer_class = StockRequestSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrApprovisionneur]

    def get_queryset(self):
        return StockRequest.objects.filter(organisation=self.request.user.organisation)

    def perform_create(self, serializer):
        serializer.save(
            organisation=self.request.user.organisation,
            requested_by=self.request.user.name
        )

class StockRequestApproveView(generics.UpdateAPIView):
    serializer_class = StockRequestSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOnly]

    def get_queryset(self):
        # Sans ce filtre, un admin pouvait approuver (et donc crediter du stock) la demande de
        # N'IMPORTE QUELLE organisation en devinant son UUID.
        return StockRequest.objects.filter(organisation=self.request.user.organisation)

    def perform_update(self, serializer):
        instance = serializer.save(status='approved')
        instance.product.stock_quantity += instance.requested_quantity
        instance.product.save()
        instance.product.sync_shared_stock_to_departments()

class MyBudgetView(APIView):
    """Solde disponible de l'approvisionneur connecte, a jour (contrairement aux donnees
    recuperees a la connexion, qui ne se rafraichissent pas automatiquement) - a appeler apres
    chaque reception de stock ou validation de demande pour afficher le solde reel."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response({'available_budget': request.user.available_budget})


class BudgetRequestListCreateView(generics.ListCreateAPIView):
    """L'approvisionneur demande un budget pour approvisionner un departement ; l'admin voit
    toutes les demandes de l'organisation (pour les valider/refuser), l'approvisionneur ne voit
    que les siennes."""
    serializer_class = BudgetRequestSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrApprovisionneur]

    def get_queryset(self):
        queryset = BudgetRequest.objects.filter(organisation=self.request.user.organisation)
        if self.request.user.role == 'approvisionneur':
            queryset = queryset.filter(approvisionneur=self.request.user)
        return queryset

    def perform_create(self, serializer):
        if self.request.user.role != 'approvisionneur':
            raise ValidationError({'detail': 'Seul un approvisionneur peut demander un budget.'})
        serializer.save(organisation=self.request.user.organisation, approvisionneur=self.request.user)


class BudgetRequestValidateView(APIView):
    """L'admin valide une demande en precisant le montant reellement accorde - ce montant
    s'ajoute au solde disponible de l'approvisionneur (voir User.available_budget)."""
    permission_classes = [permissions.IsAuthenticated, IsAdminOrSuperAdmin]

    @transaction.atomic
    def post(self, request, pk):
        budget_request = get_object_or_404(BudgetRequest, id=pk, organisation=request.user.organisation)
        if budget_request.status != 'en_attente':
            return Response({'detail': 'Cette demande a deja ete traitee.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            validated_amount = Decimal(str(request.data.get('validated_amount')))
        except (TypeError, InvalidOperation):
            return Response({'detail': 'Montant accorde invalide.'}, status=status.HTTP_400_BAD_REQUEST)
        if validated_amount < 0:
            return Response({'detail': 'Montant accorde invalide.'}, status=status.HTTP_400_BAD_REQUEST)

        budget_request.status = 'validee'
        budget_request.validated_amount = validated_amount
        budget_request.reviewed_at = timezone.now()
        budget_request.reviewed_by = request.user
        budget_request.save()

        approvisionneur = budget_request.approvisionneur
        approvisionneur.available_budget += validated_amount
        approvisionneur.save()

        Transaction.objects.create(
            organisation=request.user.organisation,
            department=budget_request.department,
            transaction_type='octroi_budget',
            number=str(budget_request.id),
            amount=validated_amount,
            author=request.user,
        )

        return Response(BudgetRequestSerializer(budget_request).data)


class BudgetRequestRejectView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdminOrSuperAdmin]

    def post(self, request, pk):
        budget_request = get_object_or_404(BudgetRequest, id=pk, organisation=request.user.organisation)
        if budget_request.status != 'en_attente':
            return Response({'detail': 'Cette demande a deja ete traitee.'}, status=status.HTTP_400_BAD_REQUEST)

        budget_request.status = 'refusee'
        budget_request.reviewed_at = timezone.now()
        budget_request.reviewed_by = request.user
        budget_request.save()

        return Response(BudgetRequestSerializer(budget_request).data)


class InventoryListCreateView(generics.ListCreateAPIView):
    serializer_class = InventorySerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrApprovisionneur]

    def get_queryset(self):
        return Inventory.objects.filter(
            organisation=self.request.user.organisation
        ).prefetch_related('lines__product__category', 'lines__department')

    @transaction.atomic
    def perform_create(self, serializer):
        if self.request.user.role != 'approvisionneur':
            raise PermissionDenied('Seul un approvisionneur peut creer un inventaire.')
        inventory = serializer.save(
            organisation=self.request.user.organisation,
            created_by=self.request.user,
            status='en_attente',
        )
        products = Product.objects.filter(
            organisation=self.request.user.organisation, is_active=True
        ).select_related('category')
        for product in products:
            if product.shared_stock:
                InventoryLine.objects.create(
                    inventory=inventory,
                    product=product,
                    system_quantity=product.stock_quantity,
                    purchase_price=product.purchase_price,
                    sale_price=product.price,
                )
                continue
            stocks = DepartmentStock.objects.filter(product=product).select_related('department')
            for stock in stocks:
                InventoryLine.objects.create(
                    inventory=inventory,
                    product=product,
                    department=stock.department,
                    system_quantity=stock.quantity,
                    purchase_price=stock.weighted_average_cost,
                    sale_price=stock.sale_price,
                )


class InventoryDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = InventorySerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrApprovisionneur]
    http_method_names = ['get', 'patch', 'head', 'options']

    def get_queryset(self):
        return Inventory.objects.filter(
            organisation=self.request.user.organisation
        ).prefetch_related('lines__product__category', 'lines__department')

    @transaction.atomic
    def partial_update(self, request, *args, **kwargs):
        inventory = self.get_object()
        if inventory.status == 'valide':
            return Response({'detail': 'Cet inventaire est deja valide.'}, status=status.HTTP_400_BAD_REQUEST)
        valuation_mode = request.data.get('valuation_mode')
        if valuation_mode is not None:
            if valuation_mode not in dict(Inventory.VALUATION_CHOICES):
                return Response({'valuation_mode': 'Mode de valorisation invalide.'}, status=status.HTTP_400_BAD_REQUEST)
            inventory.valuation_mode = valuation_mode
            inventory.save(update_fields=['valuation_mode'])
        lines = request.data.get('lines', [])
        if lines and not isinstance(lines, list):
            return Response({'lines': 'Une liste de quantites est attendue.'}, status=status.HTTP_400_BAD_REQUEST)
        for item in lines or []:
            try:
                line = inventory.lines.get(id=item['id'])
                quantity = int(item['physical_quantity'])
            except (KeyError, TypeError, ValueError, InventoryLine.DoesNotExist):
                return Response({'lines': 'Ligne ou quantite invalide.'}, status=status.HTTP_400_BAD_REQUEST)
            if quantity < 0:
                return Response({'lines': 'La quantite physique ne peut pas etre negative.'}, status=status.HTTP_400_BAD_REQUEST)
            line.physical_quantity = quantity
            line.save(update_fields=['physical_quantity'])
        inventory.status = 'en_attente'
        inventory.save(update_fields=['status'])
        return Response(InventorySerializer(inventory).data)


class InventoryValidateView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdminOnly]

    @transaction.atomic
    def post(self, request, pk):
        inventory = get_object_or_404(
            Inventory.objects.prefetch_related('lines'),
            id=pk,
            organisation=request.user.organisation,
        )
        if inventory.status == 'valide':
            return Response({'detail': 'Cet inventaire est deja valide.'}, status=status.HTTP_400_BAD_REQUEST)
        lines = list(inventory.lines.select_related('product'))
        if any(line.physical_quantity is None for line in lines):
            return Response({'detail': 'Toutes les quantites physiques doivent etre saisies.'}, status=status.HTTP_400_BAD_REQUEST)
        touched_products = set()
        for line in lines:
            if line.department_id is None:
                line.product.stock_quantity = line.physical_quantity
                line.product.save(update_fields=['stock_quantity'])
                line.product.sync_shared_stock_to_departments()
                touched_products.add(line.product_id)
            else:
                DepartmentStock.objects.filter(
                    department_id=line.department_id, product_id=line.product_id
                ).update(quantity=line.physical_quantity)
                touched_products.add(line.product_id)
        for product_id in touched_products:
            product = Product.objects.get(id=product_id)
            if not product.shared_stock:
                product.stock_quantity = sum(
                    stock.quantity for stock in product.department_stocks.all()
                )
                product.save(update_fields=['stock_quantity'])
        inventory.status = 'valide'
        inventory.validated_by = request.user
        inventory.validated_at = timezone.now()
        inventory.save(update_fields=['status', 'validated_by', 'validated_at'])
        return Response(InventorySerializer(inventory).data)


class InventoryDepartmentProfitabilityView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdminOnly]

    def get(self, request, department_id):
        department = get_object_or_404(Department, id=department_id, organisation=request.user.organisation)
        sales = Transaction.objects.filter(
            organisation=request.user.organisation,
            department=department,
            transaction_type='sortie_vente',
            product__isnull=False,
        ).values('product_id').annotate(
            sold_quantity=models.Sum('quantity'),
            sold_amount=models.Sum('amount'),
        )
        sales_by_product = {row['product_id']: row for row in sales}
        stocks = DepartmentStock.objects.filter(
            organisation=request.user.organisation,
            department=department,
        ).select_related('product', 'product__category')
        result = []
        expected_benefit = Decimal('0')
        realized_benefit = Decimal('0')
        for stock in stocks:
            sale = sales_by_product.get(stock.product_id)
            margin = stock.sale_price - stock.weighted_average_cost
            expected_benefit += stock.quantity * margin
            quantity = (sale or {}).get('sold_quantity') or 0
            sold_amount = (sale or {}).get('sold_amount') or Decimal('0')
            realized_benefit += sold_amount - (quantity * stock.weighted_average_cost)
            result.append({
                'product': stock.product_id,
                'code': stock.product.code,
                'name': stock.product.name,
                'image': stock.product.image_url,
                'family': stock.product.category.name if stock.product.category else None,
                'sold_quantity': quantity,
                'cmp': stock.weighted_average_cost,
                'sale_price': stock.sale_price,
                'margin': margin,
                'benefit': margin * quantity,
            })
        return Response({
            'department': str(department.id),
            'department_name': department.name,
            'expected_benefit': expected_benefit,
            'realized_benefit': realized_benefit,
            'benefit': expected_benefit,
            'products': result,
        })


class CategoryListCreateView(generics.ListCreateAPIView):
    serializer_class = CategorySerializer

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticated(), IsAdminOrSuperAdmin()]

    def get_queryset(self):
        return Category.objects.filter(organisation=self.request.user.organisation)

    def perform_create(self, serializer):
        serializer.save(organisation=self.request.user.organisation)

class CategoryRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = CategorySerializer

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticated(), IsAdminOrSuperAdmin()]

    def get_queryset(self):
        return Category.objects.filter(organisation=self.request.user.organisation)

class PurchaseOrderListCreateView(generics.ListCreateAPIView):
    """L'« Achat » du manuel operationnel : commande fournisseur, n'affecte
    pas le stock departement (ca c'est le role de StockReceptionView, qui
    peut ensuite etre liee a cette commande pour la marquer receptionnee)."""
    serializer_class = PurchaseOrderSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrApprovisionneur]

    def get_queryset(self):
        queryset = PurchaseOrder.objects.filter(organisation=self.request.user.organisation)
        status_param = self.request.query_params.get('status')
        if status_param in ['pending', 'received', 'cancelled']:
            queryset = queryset.filter(status=status_param)
        return queryset

    def perform_create(self, serializer):
        purchase_order = serializer.save(
            organisation=self.request.user.organisation,
            author=self.request.user
        )
        Transaction.objects.create(
            organisation=purchase_order.organisation,
            product=purchase_order.product,
            transaction_type='achat',
            number=str(purchase_order.id),
            quantity=purchase_order.quantity,
            amount=purchase_order.quantity * purchase_order.estimated_unit_cost,
            author=self.request.user,
        )

class AvarieCreateView(generics.ListCreateAPIView):
    """Declaration de perte de stock (bouteilles cassees, perimees...).
    Decremente le stock du departement, comme une vente, mais sans passer
    par une commande client."""
    serializer_class = AvarieSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrApprovisionneur]

    def get_queryset(self):
        queryset = Avarie.objects.filter(organisation=self.request.user.organisation)
        department = self.request.query_params.get('department')
        if department:
            queryset = queryset.filter(department_id=department)
        return queryset

    @transaction.atomic
    def perform_create(self, serializer):
        department = serializer.validated_data['department']
        product = serializer.validated_data['product']
        quantity = serializer.validated_data['quantity']

        if department.organisation_id != self.request.user.organisation_id:
            raise ValidationError({'department': 'Departement invalide.'})
        if self.request.user.role == 'approvisionneur' and department not in self.request.user.departments.all():
            raise PermissionDenied('Departement non attribue.')

        if product.shared_stock:
            if product.stock_quantity < quantity:
                raise ValidationError({'quantity': 'Stock insuffisant pour declarer cette avarie.'})
            product.stock_quantity -= quantity
            product.save()
            product.sync_shared_stock_to_departments()
        else:
            stock = get_object_or_404(DepartmentStock, department=department, product=product)
            if stock.quantity < quantity:
                raise ValidationError({'quantity': 'Stock insuffisant pour declarer cette avarie.'})

            stock.quantity -= quantity
            stock.save()

            product.stock_quantity = sum(item.quantity for item in product.department_stocks.all())
            product.save()

        avarie = serializer.save(organisation=self.request.user.organisation, author=self.request.user)

        if product.shared_stock:
            unit_price = product.purchase_price or 0
        else:
            stock = get_object_or_404(DepartmentStock, department=department, product=product)
            unit_price = stock.weighted_average_cost

        StockMovement.objects.create(
            organisation=self.request.user.organisation,
            department=department,
            family=product.category,
            product=product,
            movement_type='avarie',
            quantity=quantity,
            unit_purchase_price=unit_price,
            author=self.request.user,
            note=avarie.note
        )
        Transaction.objects.create(
            organisation=self.request.user.organisation,
            department=department,
            product=product,
            transaction_type='avaries',
            number=str(avarie.id),
            quantity=quantity,
            amount=quantity * unit_price,
            author=self.request.user,
        )
