from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse
from users.models import User
from organisations.models import Organisation, Department
from .models import Product, Category, StockRequest, DepartmentStock, Inventory, InventoryLine
import uuid
from decimal import Decimal

class StockTestCase(APITestCase):
    def setUp(self):
        self.org = Organisation.objects.create(name="Bar Test")
        self.admin = User.objects.create_user(phone="600000000", password="adminpass", role="admin", organisation=self.org)
        self.approvisionneur = User.objects.create_user(phone="611111111", password="appropass", role="approvisionneur", organisation=self.org)
        self.category = Category.objects.create(name="Bières", organisation=self.org)
        self.product = Product.objects.create(
            name="Castel", organisation=self.org,
            category=self.category, stock_quantity=2,
            min_threshold=5, price=1500, unit="bouteille"
        )

    def test_product_below_threshold(self):
        self.client.force_authenticate(user=self.approvisionneur)
        url = reverse('low-stock')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data), 1)

    def test_create_stock_request(self):
        self.client.force_authenticate(user=self.approvisionneur)
        url = reverse('stock-request-list-create')
        data = {
            "product": str(self.product.id),
            "requested_quantity": 10
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_admin_can_approve_stock_request(self):
        self.client.force_authenticate(user=self.approvisionneur)
        stock_req = StockRequest.objects.create(
            organisation=self.org, product=self.product,
            requested_quantity=5, requested_by=self.approvisionneur.name
        )
        self.client.force_authenticate(user=self.admin)
        url = reverse('stock-request-approve', args=[stock_req.id])
        response = self.client.patch(url, data={})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 7)

    def test_shared_stock_is_synchronized_across_departments(self):
        dept_int = Department.objects.create(organisation=self.org, name='Int')
        dept_ext = Department.objects.create(organisation=self.org, name='Ext')
        self.product.shared_stock = True
        self.product.save()
        DepartmentStock.objects.create(
            organisation=self.org, department=dept_int, product=self.product,
            quantity=0, weighted_average_cost=0, sale_price=self.product.price
        )
        DepartmentStock.objects.create(
            organisation=self.org, department=dept_ext, product=self.product,
            quantity=0, weighted_average_cost=0, sale_price=self.product.price
        )

        self.client.force_authenticate(user=self.admin)
        response = self.client.post(reverse('stock-receive'), {
            'department': str(dept_int.id),
            'product': str(self.product.id),
            'quantity': 20,
            'unit_purchase_price': '100',
            'unit_sale_price': str(self.product.price),
        })

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 20)
        self.assertTrue(all(
            stock.quantity == 20
            for stock in DepartmentStock.objects.filter(product=self.product)
        ))

    def test_shared_stock_reception_recalculates_weighted_average_cost(self):
        self.product.shared_stock = True
        self.product.stock_quantity = 10
        self.product.purchase_price = 100
        self.product.save()

        self.client.force_authenticate(user=self.admin)
        response = self.client.post(reverse('stock-receive'), {
            'product': str(self.product.id),
            'quantity': 5,
            'unit_purchase_price': '60',
        })

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 15)
        self.assertEqual(self.product.purchase_price, Decimal('86.67'))

        self.assertTrue(all(
            stock.weighted_average_cost == Decimal('86.67')
            for stock in DepartmentStock.objects.filter(product=self.product)
        ))

    def test_global_stock_blocks_stock_transfer(self):
        dept_int = Department.objects.create(organisation=self.org, name='Int')
        dept_ext = Department.objects.create(organisation=self.org, name='Ext')
        self.product.shared_stock = True
        self.product.save()
        self.client.force_authenticate(user=self.admin)

        response = self.client.post(reverse('stock-transfer'), {
            'source_department': str(dept_int.id),
            'destination_department': str(dept_ext.id),
            'product': str(self.product.id),
            'quantity': 1,
        })

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_inventory_difference_is_physical_stock_minus_system_stock(self):
        inventory = Inventory.objects.create(
            organisation=self.org,
            created_by=self.approvisionneur,
            valuation_mode='achat',
        )
        gain_line = InventoryLine.objects.create(
            inventory=inventory,
            product=self.product,
            system_quantity=50,
            physical_quantity=60,
            purchase_price=100,
            sale_price=150,
        )
        loss_line = InventoryLine.objects.create(
            inventory=inventory,
            product=self.product,
            system_quantity=50,
            physical_quantity=40,
            purchase_price=100,
            sale_price=150,
        )

        self.assertEqual(gain_line.difference, 10)
        self.assertEqual(loss_line.difference, -10)
        self.assertEqual(gain_line.valuation, Decimal('1000'))
        self.assertEqual(loss_line.valuation, Decimal('-1000'))
