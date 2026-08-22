from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse
from users.models import User
from organisations.models import Organisation
from .models import Product, Category, StockRequest
import uuid

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
