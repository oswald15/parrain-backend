from rest_framework import generics, permissions, status
from django.db import models, transaction
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.http import HttpResponse
from io import BytesIO
from xhtml2pdf import pisa
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import ValidationError, PermissionDenied
from orders.models import Order, OrderItem, CashExpense, Transaction, Consignment, ClientTab, Bon, BonItem
from products.models import DepartmentStock, Product
from organisations.models import Department, BusinessDay
from .serializers import (
    OrderSerializer, OrderItemSerializer, CashExpenseSerializer, TransactionSerializer,
    ConsignmentSerializer, ClientTabSerializer, BonSerializer, BonItemSerializer,
)
from .permissions import IsServeur, IsAdminOnly, IsCaissier, IsAdminOrApprovisionneur, IsCaissierOrAdmin
from datetime import datetime
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from django.db.models import Sum, Count
from django.utils.dateparse import parse_date
from django.db.models import Sum, F


def parse_date_param(value):
    # django.utils.dateparse.parse_date raises TypeError (instead of returning
    # None) when given None, so guard explicitly before calling it.
    return parse_date(value) if value else None


def caissier_visible_tab_filter(user):
    """Filtre Q pour les ClientTab visibles par un caissier : deux mecanismes d'assignation
    donnent acces, independamment l'un de l'autre - la serveuse lui est explicitement
    rattachee (User.assigned_cashier), OU au moins une commande de l'onglet touche un
    departement qui lui est assigne (User.departments)."""
    return (
        models.Q(serveur__assigned_cashier=user) |
        models.Q(orders__department__in=user.departments.all())
    )


def caissier_can_access_tab(user, tab):
    """Equivalent de caissier_visible_tab_filter mais pour une instance ClientTab deja chargee
    (utilise dans les vues d'action - valider/annuler un bon, encaisser - plutot qu'un
    queryset)."""
    if tab.serveur and tab.serveur.assigned_cashier_id == user.id:
        return True
    caissier_dept_ids = set(user.departments.values_list('id', flat=True))
    tab_dept_ids = set(tab.orders.values_list('department_id', flat=True))
    return bool(caissier_dept_ids & tab_dept_ids)


def _validate_stock_for_closure(order):
    """Leve ValidationError si le stock departemental est insuffisant pour un item
    actif de la commande. Lecture seule - ne decremente rien (voir
    _decrement_stock_for_closure), pour permettre de verifier plusieurs commandes
    (ex: un ClientTab multi-departements) avant de decrementer quoi que ce soit."""
    for item in order.items.filter(is_removed=False):
        stock = DepartmentStock.objects.filter(
            department=order.department, product=item.product
        ).first()
        available = stock.quantity if stock else 0
        if available < item.quantity:
            raise ValidationError({
                'detail': f"Stock insuffisant pour {item.product.name} "
                          f"({available} disponible, {item.quantity} demande)."
            })


def _decrement_stock_for_closure(order):
    for item in order.items.filter(is_removed=False):
        stock = DepartmentStock.objects.get(department=order.department, product=item.product)
        stock.quantity -= item.quantity
        stock.save()


def _create_sortie_vente_transaction(order, author):
    Transaction.objects.get_or_create(
        organisation=order.organisation,
        order=order,
        transaction_type='sortie_vente',
        defaults={
            'department': order.department,
            'number': str(order.id),
            'payment_type': order.payment_type,
            'quantity': sum(item.quantity for item in order.items.filter(is_removed=False)),
            'amount': order.total_amount,
            'waitress_code': order.serveur.phone if order.serveur else '',
            'serveur': order.serveur,
            'client': order.client_name,
            'author': author,
        }
    )


class OrdersOpenedTodayView(generics.ListAPIView):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        today = datetime.now().date()
        status_param = self.request.query_params.get('status')
        allowed_statuses = ['ouverte', 'servie']
        queryset = Order.objects.filter(
            organisation=self.request.user.organisation,
            created_at__date=today,
            status__in=[status_param] if status_param in allowed_statuses else allowed_statuses,
            client_tab__isnull=True,
        )
        if self.request.user.role == 'serveur':
            queryset = queryset.filter(serveur=self.request.user)
        if self.request.user.role == 'caissier':
            queryset = queryset.filter(
                models.Q(serveur__assigned_cashier=self.request.user) |
                models.Q(department__in=self.request.user.departments.all())
            ).distinct()
        return queryset.order_by('-created_at')


class OrdersClosedTodayView(generics.ListAPIView):
    """Commandes encaissees du jour - la serveuse voit les siennes (scope calendaire, date du
    jour). Le caissier voit celles qu'il a personnellement encaissees DEPUIS L'OUVERTURE DE LA
    SESSION en cours (meme perimetre que CaissierDailySummaryView) - vide si aucune session
    n'est ouverte, pour rester coherent avec le compteur qui revient alors a 0."""
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user

        if user.role == 'caissier':
            current_day = BusinessDay.objects.filter(
                organisation=user.organisation, is_open=True
            ).first()
            if not current_day:
                return Order.objects.none()
            return Order.objects.filter(
                organisation=user.organisation, cashier=user,
                closed_at__gte=current_day.opened_at, status='fermee'
            ).order_by('-closed_at')

        today = datetime.now().date()
        queryset = Order.objects.filter(
            organisation=user.organisation, closed_at__date=today, status='fermee'
        )
        if user.role == 'serveur':
            queryset = queryset.filter(serveur=user)
        return queryset.order_by('-closed_at')

class OrderCreateView(generics.CreateAPIView):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated, IsServeur]

    def perform_create(self, serializer):
        if not self.request.user.organisation:
            from rest_framework.exceptions import ValidationError
            raise ValidationError('Utilisateur sans organisation.')
        serializer.save(organisation=self.request.user.organisation, serveur=self.request.user)

class OrderListView(generics.ListAPIView):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated, IsServeur]

    def get_queryset(self):
        queryset = Order.objects.filter(serveur=self.request.user)
        status_param = self.request.query_params.get('status')
        if status_param in ['ouverte', 'servie', 'fermee']:
            queryset = queryset.filter(status=status_param)
        return queryset.order_by('-created_at')

class AdminOrderListView(generics.ListAPIView):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOnly]

    def get_queryset(self):
        queryset = Order.objects.filter(organisation=self.request.user.organisation)
        department = self.request.query_params.get('department')
        status_param = self.request.query_params.get('status')
        client = self.request.query_params.get('client')
        if department:
            queryset = queryset.filter(department_id=department)
        if status_param in ['ouverte', 'servie', 'fermee', 'annulee']:
            queryset = queryset.filter(status=status_param)
        if client:
            queryset = queryset.filter(client_name__icontains=client)
        return queryset.order_by('-created_at')

class OrderStatusUpdateView(generics.UpdateAPIView):
    queryset = Order.objects.all()
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        order = super().get_object()
        user = self.request.user
        # Verifie l'appartenance a l'organisation AVANT toute branche par role - sans ca, un
        # admin/superadmin authentifie pouvait cloturer (encaisser, decrementer le stock) la
        # commande de N'IMPORTE QUELLE autre organisation en devinant son UUID.
        if order.organisation_id != user.organisation_id:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Vous n'êtes pas autorisé à modifier cette commande.")
        if user.role in ['admin', 'superadmin']:
            return order
        if user.role == 'caissier' and order.serveur and (
            order.serveur.assigned_cashier_id == user.id or
            (order.department_id and user.departments.filter(id=order.department_id).exists())
        ):
            return order
        if user.role == 'serveur' and order.serveur_id == user.id:
            return order
        from rest_framework.exceptions import PermissionDenied
        raise PermissionDenied("Vous n'êtes pas autorisé à modifier cette commande.")

    @transaction.atomic
    def perform_update(self, serializer):
        was_already_fermee = serializer.instance.status == 'fermee'
        becoming_fermee = serializer.validated_data.get('status') == 'fermee' and not was_already_fermee

        if becoming_fermee:
            _validate_stock_for_closure(serializer.instance)

        order = serializer.save()

        if becoming_fermee:
            _decrement_stock_for_closure(order)

        if order.status == 'fermee':
            order.cashier = self.request.user
            order.save()
            _create_sortie_vente_transaction(order, self.request.user)

class OrderItemDeleteView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdminOnly]

    @transaction.atomic
    def delete(self, request, order_id, item_id):
        order = get_object_or_404(Order, id=order_id, organisation=request.user.organisation)
        item = get_object_or_404(OrderItem, id=item_id, order=order, is_removed=False)

        removed_quantity = item.quantity
        removed_amount = item.quantity * item.unit_price
        removed_product = item.product

        # Soft-delete : la ligne reste en base pour l'archivage, seule sa visibilite change.
        item.is_removed = True
        item.removed_at = timezone.now()
        item.removed_by = request.user
        item.save()

        # Si le stock avait deja ete decompte (commande encaissee), on le recredite.
        if order.status == 'fermee':
            stock = DepartmentStock.objects.filter(department=order.department, product=removed_product).first()
            if stock:
                stock.quantity += removed_quantity
                stock.save()

        order.total_amount = sum(i.quantity * i.unit_price for i in order.items.filter(is_removed=False))
        order.save()

        Transaction.objects.create(
            organisation=order.organisation,
            department=order.department,
            product=removed_product,
            transaction_type='avoir',
            number=str(order.id),
            quantity=removed_quantity,
            amount=removed_amount,
            waitress_code=order.serveur.phone if order.serveur else '',
            serveur=order.serveur,
            client=order.client_name,
            order=order,
            author=request.user,
        )

        return Response(OrderSerializer(order).data)

class OrderCancelView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdminOrApprovisionneur]

    @transaction.atomic
    def post(self, request, order_id):
        order = get_object_or_404(Order, id=order_id, organisation=request.user.organisation)
        if order.status == 'annulee':
            return Response({'detail': 'Commande deja annulee.'}, status=status.HTTP_400_BAD_REQUEST)

        # Si la commande etait deja encaissee, le stock decompte a la cloture est integralement recredite.
        if order.status == 'fermee':
            for item in order.items.filter(is_removed=False):
                stock = DepartmentStock.objects.filter(department=order.department, product=item.product).first()
                if stock:
                    stock.quantity += item.quantity
                    stock.save()

        order.status = 'annulee'
        order.cancelled_at = timezone.now()
        order.cancelled_by = request.user
        order.cancel_reason = request.data.get('reason', '')
        order.save()

        Transaction.objects.create(
            organisation=order.organisation,
            department=order.department,
            transaction_type='annulation_facture',
            number=str(order.id),
            quantity=sum(i.quantity for i in order.items.filter(is_removed=False)),
            amount=order.total_amount,
            waitress_code=order.serveur.phone if order.serveur else '',
            serveur=order.serveur,
            client=order.client_name,
            order=order,
            author=request.user,
        )

        return Response(OrderSerializer(order).data)

class OrderValidateView(generics.UpdateAPIView):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated, IsCaissier]

    def get_queryset(self):
        # Sans ce filtre, un caissier pouvait valider la commande de N'IMPORTE QUELLE
        # organisation en devinant son UUID (queryset non scope + aucune verification d'objet).
        return Order.objects.filter(organisation=self.request.user.organisation)

    def perform_update(self, serializer):
        serializer.save(status="servie")

class DailyRevenueView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        today = datetime.now().date()
        orders = Order.objects.filter(
            serveur=request.user,
            closed_at__date=today,
            status='fermee'
        )
        total_revenue = sum(order.total_amount for order in orders)
        return Response({
            'date': today,
            'total_revenue': total_revenue,
            'total_closed_orders': orders.count()
        })

class GlobalDailyRevenueView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdminOnly]

    def get(self, request):
        today = datetime.now().date()
        orders = Order.objects.filter(
            organisation=request.user.organisation,
            closed_at__date=today,
            status='fermee'
        )

        total_revenue = orders.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        total_orders = orders.count()

        cash_payments = orders.filter(payment_type='cash').aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        mobile_money_payments = orders.filter(payment_type='mobile_money').aggregate(Sum('total_amount'))['total_amount__sum'] or 0


        serveurs_involved = orders.values_list('serveur__name', flat=True).distinct()

        return Response({
            'date': today,
            'total_revenue': total_revenue,
            'total_closed_orders': total_orders,
            'cash_payments': cash_payments, # NOUVEAU
            'mobile_money_payments': mobile_money_payments, # NOUVEAU
            'serveurs': list(serveurs_involved),
        })
      
class ServeurPerformanceView(APIView):
    permission_classes = [IsAdminOnly]

    def get(self, request):
        organisation = request.user.organisation
        start_date = parse_date_param(request.query_params.get('start_date')) or timezone.now().date()
        end_date = parse_date_param(request.query_params.get('end_date')) or start_date

        orders = Order.objects.filter(
            organisation=organisation,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
            status='fermee'
        )
        department = request.query_params.get('department')
        if department:
            orders = orders.filter(department_id=department)

        stats = (
            orders.values('serveur__id', 'serveur__name')
            .annotate(
                total_orders=Count('id'),
                total_sales=Sum('total_amount')
            )
            .order_by('-total_sales')
        )

        return Response({
            "from": start_date,
            "to": end_date,
            "performance": stats
        })

class DepartmentProfitabilityReportView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdminOnly]

    def get(self, request):
        organisation = request.user.organisation
        start_date = parse_date_param(request.query_params.get('start_date')) or timezone.now().date()
        end_date = parse_date_param(request.query_params.get('end_date')) or start_date
        department = request.query_params.get('department')

        stock_qs = DepartmentStock.objects.filter(organisation=organisation)
        if department:
            stock_qs = stock_qs.filter(department_id=department)

        stock_by_department = (
            stock_qs.values('department__id', 'department__name')
            .annotate(
                stock_value=Sum(F('quantity') * F('weighted_average_cost')),
                potential_sale_value=Sum(F('quantity') * F('sale_price')),
            )
            .order_by('department__name')
        )

        sales_qs = Transaction.objects.filter(
            organisation=organisation,
            transaction_type='sortie_vente',
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
        )
        if department:
            sales_qs = sales_qs.filter(department_id=department)
        sales_by_department = {
            row['department_id']: row
            for row in sales_qs.values('department_id').annotate(
                sold_quantity=Sum('quantity'),
                sold_amount=Sum('amount'),
            )
        }

        report = []
        for row in stock_by_department:
            stock_value = row['stock_value'] or 0
            potential_sale_value = row['potential_sale_value'] or 0
            margin = potential_sale_value - stock_value
            margin_percent = (margin / stock_value * 100) if stock_value else 0
            sales = sales_by_department.get(row['department__id'], {})
            report.append({
                'department_id': row['department__id'],
                'department_name': row['department__name'],
                'stock_value': stock_value,
                'potential_sale_value': potential_sale_value,
                'margin': margin,
                'margin_percent': margin_percent,
                'sold_quantity': sales.get('sold_quantity') or 0,
                'sold_amount': sales.get('sold_amount') or 0,
            })

        return Response({
            'from': start_date,
            'to': end_date,
            'departments': report,
        })

class GlobalCashPositionView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdminOnly]

    def get(self, request):
        organisation = request.user.organisation
        start_date = parse_date_param(request.query_params.get('start_date')) or timezone.now().date()
        end_date = parse_date_param(request.query_params.get('end_date')) or start_date

        base_qs = Transaction.objects.filter(
            organisation=organisation,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
        )
        revenue_qs = base_qs.filter(transaction_type='sortie_vente')
        expense_qs = base_qs.filter(transaction_type='sortie_caisse')

        total_revenue = revenue_qs.aggregate(Sum('amount'))['amount__sum'] or 0
        total_expenses = expense_qs.aggregate(Sum('amount'))['amount__sum'] or 0

        by_department = (
            revenue_qs.values('department__id', 'department__name')
            .annotate(revenue=Sum('amount'))
            .order_by('-revenue')
        )

        return Response({
            'from': start_date,
            'to': end_date,
            'total_revenue': total_revenue,
            'total_expenses': total_expenses,
            'net_cash': total_revenue - total_expenses,
            'by_department': list(by_department),
        })

class CaissierDailySummaryView(APIView):
    """Resume de caisse du caissier connecte, scope sur la SESSION en cours (depuis
    l'ouverture de la journee par l'admin) plutot que sur la date calendaire - des la
    fermeture de la journee, tout revient a 0 (plus de session en cours), et repart de zero
    a la prochaine ouverture (voir organisations/models.py::BusinessDay)."""
    permission_classes = [permissions.IsAuthenticated, IsCaissier]

    def get(self, request):
        current_day = BusinessDay.objects.filter(
            organisation=request.user.organisation, is_open=True
        ).first()

        if not current_day:
            return Response({
                'date': datetime.now().date(),
                'total_revenue': 0,
                'total_closed_orders': 0,
                'cash_payments': 0,
                'mobile_money_payments': 0,
                'total_expenses': 0,
                'opening_amount': 0,
                'net_cash': 0,
                'by_department': [],
            })

        balance = current_day.cashier_balances.filter(cashier=request.user).first()
        opening_amount = balance.opening_amount if balance else 0

        orders = Order.objects.filter(
            cashier=request.user,
            closed_at__gte=current_day.opened_at,
            status='fermee'
        )
        expenses = CashExpense.objects.filter(
            cashier=request.user, created_at__gte=current_day.opened_at, is_deleted=False
        )

        total_revenue = orders.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        total_expenses = expenses.aggregate(Sum('amount'))['amount__sum'] or 0
        cash_payments = orders.filter(payment_type='cash').aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        mobile_money_payments = orders.filter(payment_type='mobile_money').aggregate(Sum('total_amount'))['total_amount__sum'] or 0

        by_department = (
            orders.values('department__id', 'department__name')
            .annotate(revenue=Sum('total_amount'), orders_count=Count('id'))
            .order_by('-revenue')
        )

        return Response({
            'date': current_day.date,
            'total_revenue': total_revenue,
            'total_closed_orders': orders.count(),
            'cash_payments': cash_payments,
            'mobile_money_payments': mobile_money_payments,
            'total_expenses': total_expenses,
            'opening_amount': opening_amount,
            'net_cash': opening_amount + total_revenue - total_expenses,
            'by_department': [
                {
                    'department_id': row['department__id'],
                    'department_name': row['department__name'],
                    'revenue': row['revenue'] or 0,
                    'orders_count': row['orders_count'],
                }
                for row in by_department
            ],
        })

class CashExpenseListCreateView(generics.ListCreateAPIView):
    serializer_class = CashExpenseSerializer
    permission_classes = [permissions.IsAuthenticated, IsCaissier]

    def get_queryset(self):
        queryset = CashExpense.objects.filter(organisation=self.request.user.organisation, is_deleted=False)
        if self.request.user.role == 'caissier':
            queryset = queryset.filter(cashier=self.request.user)
        return queryset

    def perform_create(self, serializer):
        expense = serializer.save(
            organisation=self.request.user.organisation,
            cashier=self.request.user
        )
        Transaction.objects.create(
            organisation=expense.organisation,
            transaction_type='sortie_caisse',
            number=str(expense.id),
            amount=expense.amount,
            expense=expense,
            author=self.request.user,
        )

class CashExpenseDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = CashExpenseSerializer
    permission_classes = [permissions.IsAuthenticated, IsCaissier]

    def perform_destroy(self, instance):
        instance.is_deleted = True
        instance.deleted_at = timezone.now()
        instance.deleted_by = self.request.user
        instance.save()
        Transaction.objects.create(
            organisation=instance.organisation,
            transaction_type='avoir',
            number=str(instance.id),
            amount=instance.amount,
            expense=instance,
            author=self.request.user,
        )

    def get_queryset(self):
        queryset = CashExpense.objects.filter(organisation=self.request.user.organisation, is_deleted=False)
        if self.request.user.role == 'caissier':
            queryset = queryset.filter(cashier=self.request.user)
        return queryset

class TransactionListView(generics.ListAPIView):
    serializer_class = TransactionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = Transaction.objects.filter(organisation=self.request.user.organisation)
        if self.request.user.role == 'serveur':
            queryset = queryset.filter(serveur=self.request.user)
        if self.request.user.role == 'caissier':
            queryset = queryset.filter(
                models.Q(author=self.request.user) |
                models.Q(serveur__assigned_cashier=self.request.user) |
                models.Q(department__in=self.request.user.departments.all())
            )
        department = self.request.query_params.get('department')
        serveur = self.request.query_params.get('serveur')
        transaction_type = self.request.query_params.get('transaction_type')
        start_date = parse_date_param(self.request.query_params.get('start_date'))
        end_date = parse_date_param(self.request.query_params.get('end_date'))
        if department:
            queryset = queryset.filter(department_id=department)
        if serveur:
            queryset = queryset.filter(serveur_id=serveur)
        if transaction_type:
            queryset = queryset.filter(transaction_type=transaction_type)
        if start_date:
            queryset = queryset.filter(created_at__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__date__lte=end_date)
        return queryset.distinct().order_by('-created_at')

class ConsignmentCreateView(APIView):
    """Le caissier consigne une ou plusieurs bouteilles emportees par le client
    (Section 3.1 du manuel : 'Consignation a la caisse ... effectuee et
    enregistree par le Caissier')."""
    permission_classes = [permissions.IsAuthenticated, IsCaissier]

    @transaction.atomic
    def post(self, request):
        order_id = request.data.get('order')
        items = request.data.get('items') or []
        if not items:
            return Response({'detail': 'Au moins un produit consignable est requis.'}, status=status.HTTP_400_BAD_REQUEST)

        order = None
        if order_id:
            order = get_object_or_404(Order, id=order_id, organisation=request.user.organisation)

        total_amount = 0
        total_quantity = 0
        created = []
        for item in items:
            product = get_object_or_404(Product, id=item.get('product'), organisation=request.user.organisation)
            quantity = int(item.get('quantity') or 0)
            if quantity <= 0:
                continue
            if not product.is_consignable:
                return Response(
                    {'detail': f"{product.name} n'est pas consignable."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            consignment = Consignment.objects.create(
                organisation=request.user.organisation,
                order=order,
                department=order.department if order else None,
                product=product,
                client_name=order.client_name if order else request.data.get('client_name', ''),
                quantity=quantity,
                unit_deposit_amount=product.deposit_amount,
                created_by=request.user,
            )
            created.append(consignment)
            total_amount += quantity * product.deposit_amount
            total_quantity += quantity

        if not created:
            return Response({'detail': 'Aucune ligne de consignation valide.'}, status=status.HTTP_400_BAD_REQUEST)

        Transaction.objects.create(
            organisation=request.user.organisation,
            department=order.department if order else None,
            transaction_type='consignation',
            number=str(order.id) if order else '',
            quantity=total_quantity,
            amount=total_amount,
            order=order,
            client=order.client_name if order else request.data.get('client_name', ''),
            author=request.user,
        )

        return Response(ConsignmentSerializer(created, many=True).data, status=status.HTTP_201_CREATED)

class ConsignmentListView(generics.ListAPIView):
    serializer_class = ConsignmentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = Consignment.objects.filter(organisation=self.request.user.organisation)
        status_param = self.request.query_params.get('status')
        client = self.request.query_params.get('client')
        if status_param in ['sortie', 'rendue']:
            queryset = queryset.filter(status=status_param)
        if client:
            queryset = queryset.filter(client_name__icontains=client)
        return queryset

class ConsignmentReturnView(APIView):
    """Retour de la bouteille vide : la Serveuse (ou la Caisse, selon
    l'organisation interne, Section 3.1 du manuel) valide la deconsignation."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        if request.user.role not in ['serveur', 'caissier', 'admin', 'superadmin', 'approvisionneur']:
            return Response({'detail': 'Action non autorisee.'}, status=status.HTTP_403_FORBIDDEN)

        consignment = get_object_or_404(Consignment, id=pk, organisation=request.user.organisation)
        if consignment.status == 'rendue':
            return Response({'detail': 'Consignation deja rendue.'}, status=status.HTTP_400_BAD_REQUEST)

        consignment.status = 'rendue'
        consignment.returned_at = timezone.now()
        consignment.returned_by = request.user
        consignment.save()

        Transaction.objects.create(
            organisation=consignment.organisation,
            department=consignment.department,
            product=consignment.product,
            transaction_type='deconsignation',
            number=str(consignment.order_id) if consignment.order_id else '',
            quantity=consignment.quantity,
            amount=consignment.quantity * consignment.unit_deposit_amount,
            order=consignment.order,
            client=consignment.client_name,
            author=request.user,
        )

        return Response(ConsignmentSerializer(consignment).data)


class ClientTabCreateView(generics.CreateAPIView):
    """Ouvre un onglet client pour la serveuse (tablette mobile) : un client
    physique peut ensuite consommer des produits de plusieurs departements,
    chacun materialise par une Order distincte liee a cet onglet."""
    serializer_class = ClientTabSerializer
    permission_classes = [permissions.IsAuthenticated, IsServeur]

    def perform_create(self, serializer):
        serializer.save(organisation=self.request.user.organisation, serveur=self.request.user)


class ClientTabListView(generics.ListAPIView):
    serializer_class = ClientTabSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = ClientTab.objects.filter(organisation=self.request.user.organisation)
        if self.request.user.role == 'serveur':
            queryset = queryset.filter(serveur=self.request.user)
        elif self.request.user.role == 'caissier':
            queryset = queryset.filter(caissier_visible_tab_filter(self.request.user)).distinct()
        status_param = self.request.query_params.get('status')
        if status_param in dict(ClientTab.STATUS_CHOICES):
            queryset = queryset.filter(status=status_param)
        return queryset


class ClientTabDetailView(generics.RetrieveDestroyAPIView):
    """Lecture d'un onglet unique, a jour (orders/items imbriques) - utilisee par
    la tablette pour rafraichir un onglet quand la serveuse bascule entre
    plusieurs clients ouverts en parallele.

    Le DELETE permet a la serveuse de supprimer un onglet cree par erreur (client deja
    cree par une autre serveuse, ou qui finalement ne commande pas) - voir
    perform_destroy : uniquement la proprietaire, et uniquement un onglet encore vide
    (aucune commande ajoutee). Une fois une commande ajoutee, il faut annuler le(s) bon(s)
    correspondant(s) plutot que de supprimer l'onglet (voir BonCancelView)."""
    serializer_class = ClientTabSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = ClientTab.objects.filter(organisation=self.request.user.organisation)
        if self.request.user.role == 'serveur':
            queryset = queryset.filter(serveur=self.request.user)
        elif self.request.user.role == 'caissier':
            queryset = queryset.filter(caissier_visible_tab_filter(self.request.user)).distinct()
        return queryset

    def perform_destroy(self, instance):
        user = self.request.user
        if user.role != 'serveur' or instance.serveur_id != user.id:
            raise PermissionDenied("Seule la serveuse proprietaire peut supprimer cet onglet.")
        if instance.status != 'ouvert' or instance.orders.exists():
            raise ValidationError({'detail': "Cet onglet contient deja des commandes, il ne peut plus etre supprime."})
        instance.delete()


class ClientTabAddItemsView(APIView):
    """Ajoute un lot de produits d'un departement donne a un onglet client ouvert.
    Cree ou reutilise l'Order (onglet, departement), resout le prix depuis
    DepartmentStock.sale_price (jamais depuis le payload client). La reponse
    contient uniquement les items de CE lot pour permettre a la tablette
    d'imprimer un bon de sortie ne montrant que ce qui vient d'etre ajoute."""
    permission_classes = [permissions.IsAuthenticated, IsServeur]

    @transaction.atomic
    def post(self, request, pk):
        tab = get_object_or_404(
            ClientTab, id=pk, organisation=request.user.organisation, serveur=request.user
        )
        if tab.status != 'ouvert':
            return Response({'detail': "Cet onglet n'est plus ouvert."}, status=status.HTTP_400_BAD_REQUEST)

        department_id = request.data.get('department')
        items = request.data.get('items') or []
        if not department_id or not items:
            return Response(
                {'detail': 'Departement et au moins un produit sont requis.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        department = get_object_or_404(Department, id=department_id, organisation=request.user.organisation)

        order, _ = Order.objects.get_or_create(
            client_tab=tab, department=department,
            defaults={
                'organisation': request.user.organisation,
                'serveur': request.user,
                'client_name': tab.client_name,
                'number_of_customers': 1,
            }
        )

        # (product, delta_quantity, unit_price) par ligne - delta_quantity est la quantite
        # de CET appel, pas la quantite cumulee de l'OrderItem apres fusion. C'est ce delta
        # qui doit apparaitre sur le bon de sortie imprime, pas le total accumule.
        deltas = []
        for entry in items:
            product = get_object_or_404(Product, id=entry.get('product'), organisation=request.user.organisation)
            quantity = int(entry.get('quantity') or 0)
            if quantity <= 0:
                continue
            stock = get_object_or_404(DepartmentStock, department=department, product=product)

            order_item, created = OrderItem.objects.get_or_create(
                order=order, product=product, is_removed=False,
                defaults={'quantity': quantity, 'unit_price': stock.sale_price}
            )
            if not created:
                order_item.quantity += quantity
                order_item.save()

            deltas.append((product, quantity, order_item.unit_price))

        if not deltas:
            return Response({'detail': 'Aucune ligne valide.'}, status=status.HTTP_400_BAD_REQUEST)

        order.total_amount = sum(i.quantity * i.unit_price for i in order.items.filter(is_removed=False))
        order.save()

        bon = Bon.objects.create(
            organisation=request.user.organisation,
            client_tab=tab,
            order=order,
            department=department,
            created_by=request.user,
            total_amount=sum(qty * price for _, qty, price in deltas),
        )
        bon_items = BonItem.objects.bulk_create([
            BonItem(bon=bon, product=product, quantity=qty, unit_price=price)
            for product, qty, price in deltas
        ])

        tab.total_amount = sum(o.total_amount for o in tab.orders.filter(status__in=['ouverte', 'servie']))
        tab.save()

        return Response({
            'order': OrderSerializer(order).data,
            'added_items': BonItemSerializer(bon_items, many=True).data,
            'tab': ClientTabSerializer(tab).data,
        }, status=status.HTTP_201_CREATED)


class BonCancelView(APIView):
    """Le caissier annule un bon (un lot ajoute) avant l'encaissement final -
    reverse son effet sur l'Order/OrderItem qu'il avait alimente, sans toucher
    au stock (jamais decremente avant l'encaissement de toute facon)."""
    permission_classes = [permissions.IsAuthenticated, IsCaissierOrAdmin]

    @transaction.atomic
    def post(self, request, pk):
        bon = get_object_or_404(Bon, id=pk, organisation=request.user.organisation)

        if request.user.role == 'caissier' and not caissier_can_access_tab(request.user, bon.client_tab):
            return Response(
                {'detail': "Vous n'etes pas autorise a annuler ce bon."},
                status=status.HTTP_403_FORBIDDEN
            )

        if bon.status != 'actif':
            return Response({'detail': 'Ce bon est deja annule.'}, status=status.HTTP_400_BAD_REQUEST)
        if bon.client_tab.status not in ['ouvert', 'facture']:
            return Response(
                {'detail': "Cet onglet est deja encaisse, le bon ne peut plus etre annule."},
                status=status.HTTP_400_BAD_REQUEST
            )

        order = bon.order
        for bon_item in bon.items.all():
            order_item = OrderItem.objects.filter(
                order=order, product=bon_item.product, is_removed=False
            ).first()
            if not order_item:
                continue
            remaining = order_item.quantity - bon_item.quantity
            if remaining <= 0:
                order_item.is_removed = True
                order_item.removed_at = timezone.now()
                order_item.removed_by = request.user
                order_item.save()
            else:
                order_item.quantity = remaining
                order_item.save()

        order.total_amount = sum(i.quantity * i.unit_price for i in order.items.filter(is_removed=False))
        order.save()

        tab = bon.client_tab
        tab.total_amount = sum(o.total_amount for o in tab.orders.filter(status__in=['ouverte', 'servie']))
        tab.save()

        bon.status = 'annule'
        bon.cancelled_at = timezone.now()
        bon.cancelled_by = request.user
        bon.save()

        return Response(ClientTabSerializer(tab).data)


class BonValidateView(APIView):
    """Le caissier valide un bon (un lot ajoute) : simple confirmation qu'il a
    bien recu/verifie ce lot, sans effet sur l'Order/OrderItem/le stock -
    contrairement a l'annulation qui reverse le lot, la validation ne fait que
    marquer le bon comme controle. La serveuse voit ce statut et peut alors
    imprimer le bon de sortie correspondant."""
    permission_classes = [permissions.IsAuthenticated, IsCaissierOrAdmin]

    @transaction.atomic
    def post(self, request, pk):
        bon = get_object_or_404(Bon, id=pk, organisation=request.user.organisation)

        if request.user.role == 'caissier' and not caissier_can_access_tab(request.user, bon.client_tab):
            return Response(
                {'detail': "Vous n'etes pas autorise a valider ce bon."},
                status=status.HTTP_403_FORBIDDEN
            )

        if bon.status != 'actif':
            return Response({'detail': 'Ce bon ne peut plus etre valide.'}, status=status.HTTP_400_BAD_REQUEST)
        if bon.client_tab.status not in ['ouvert', 'facture']:
            return Response(
                {'detail': "Cet onglet est deja encaisse, le bon ne peut plus etre valide."},
                status=status.HTTP_400_BAD_REQUEST
            )

        bon.status = 'valide'
        bon.validated_at = timezone.now()
        bon.validated_by = request.user
        bon.save()

        return Response(ClientTabSerializer(bon.client_tab).data)


class ClientTabInvoiceView(APIView):
    """La serveuse facture l'onglet : consolide toutes les Order (une par
    departement touche) en une facture unique, imprimee cote mobile."""
    permission_classes = [permissions.IsAuthenticated, IsServeur]

    @transaction.atomic
    def post(self, request, pk):
        tab = get_object_or_404(
            ClientTab, id=pk, organisation=request.user.organisation, serveur=request.user
        )
        if tab.status != 'ouvert':
            return Response({'detail': "Cet onglet n'est plus ouvert."}, status=status.HTTP_400_BAD_REQUEST)

        orders = tab.orders.filter(status='ouverte')
        if not orders.exists():
            return Response({'detail': 'Aucun produit sur cet onglet.'}, status=status.HTTP_400_BAD_REQUEST)

        orders.update(status='servie')

        tab.total_amount = sum(o.total_amount for o in tab.orders.filter(status='servie'))
        tab.status = 'facture'
        tab.invoiced_at = timezone.now()
        tab.save()

        return Response(ClientTabSerializer(tab).data)


class ClientTabInvoicePdfView(APIView):
    """Genere le PDF de la facture d'un onglet deja facture - document canonique
    consultable/imprimable a la demande (plus d'impression thermique automatique
    a la facturation, voir ClientTabInvoiceView : celle-ci ne fait QUE changer le
    statut de l'onglet, l'impression cote mobile est desormais un choix separe).

    Accepte l'authentification via ?token=... en plus de l'entete Authorization : ouvert
    depuis un navigateur/lecteur PDF externe (Linking.openURL cote mobile), qui n'envoie pas
    nos entetes personnalisees."""
    permission_classes = []

    def get(self, request, pk):
        user = request.user
        if not user.is_authenticated:
            token_value = request.GET.get('token')
            token = Token.objects.select_related('user').filter(key=token_value).first() if token_value else None
            if not token:
                return Response({'detail': 'Authentification requise.'}, status=status.HTTP_401_UNAUTHORIZED)
            user = token.user

        tab = get_object_or_404(ClientTab, id=pk, organisation=user.organisation)

        if user.role == 'serveur' and tab.serveur_id != user.id:
            return Response({'detail': "Vous n'etes pas autorise a consulter cette facture."}, status=status.HTTP_403_FORBIDDEN)
        if user.role == 'caissier' and not caissier_can_access_tab(user, tab):
            return Response({'detail': "Vous n'etes pas autorise a consulter cette facture."}, status=status.HTTP_403_FORBIDDEN)

        if tab.status not in ['facture', 'encaisse']:
            return Response(
                {'detail': "Cet onglet n'a pas encore ete facture."}, status=status.HTTP_400_BAD_REQUEST
            )

        departments = []
        for order in tab.orders.filter(status__in=['servie', 'fermee']):
            items = [
                {
                    'product_name': item.product.name,
                    'quantity': item.quantity,
                    'unit_price': item.unit_price,
                    'line_total': item.quantity * item.unit_price,
                }
                for item in order.items.filter(is_removed=False)
            ]
            if items:
                departments.append({
                    'name': order.department.name if order.department else 'Departement',
                    'items': items,
                })

        html = render_to_string('orders/facture_pdf.html', {
            'organisation': user.organisation,
            'tab': tab,
            'departments': departments,
            'total_amount': tab.total_amount,
        })

        buffer = BytesIO()
        pisa.CreatePDF(html, dest=buffer)
        response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="facture-{tab.client_name}.pdf"'
        return response


class ClientTabCloseView(APIView):
    """Encaissement cote caissier : cloture atomiquement toutes les Order de
    l'onglet (une par departement). Le stock de TOUS les departements est
    verifie avant la moindre decrementation, pour qu'une penurie sur un seul
    departement bloque l'encaissement entier plutot que de le faire a moitie."""
    permission_classes = [permissions.IsAuthenticated, IsCaissierOrAdmin]

    @transaction.atomic
    def post(self, request, pk):
        tab = get_object_or_404(ClientTab, id=pk, organisation=request.user.organisation)

        if request.user.role == 'caissier' and not caissier_can_access_tab(request.user, tab):
            return Response(
                {'detail': "Vous n'etes pas autorise a encaisser cet onglet."},
                status=status.HTTP_403_FORBIDDEN
            )

        if tab.status != 'facture':
            return Response(
                {'detail': "Cet onglet n'est pas pret pour encaissement."},
                status=status.HTTP_400_BAD_REQUEST
            )

        orders = list(tab.orders.filter(status='servie'))
        if not orders:
            return Response({'detail': 'Aucune commande a encaisser sur cet onglet.'}, status=status.HTTP_400_BAD_REQUEST)

        payment_type = request.data.get('payment_type')

        for order in orders:
            _validate_stock_for_closure(order)

        for order in orders:
            _decrement_stock_for_closure(order)
            order.status = 'fermee'
            order.closed_at = timezone.now()
            order.cashier = request.user
            order.payment_type = payment_type
            order.save()
            _create_sortie_vente_transaction(order, request.user)

        tab.status = 'encaisse'
        tab.closed_at = timezone.now()
        tab.save()

        return Response(ClientTabSerializer(tab).data)
