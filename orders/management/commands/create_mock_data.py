from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime, timedelta
import random

from organisations.models import Organisation
from users.models import User
from products.models import Category, Product
from orders.models import Order, OrderItem

class Command(BaseCommand):
    help = 'Creates mock data for Organisation, Users, Products, and Orders.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting to create mock data...'))

        # --- 1. Create Organisation ---
        org, created = Organisation.objects.get_or_create( #
            name="Global Drinks Inc.", #
            defaults={
                'description': 'A global distributor of beverages.', #
                'address': '123 Main Street, Douala', #
                'phone_contact': '237678123456', #
                'subscription_plan': 'premium' #
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'Created Organisation: {org.name}'))
        else:
            self.stdout.write(self.style.WARNING(f'Organisation "{org.name}" already exists.'))

        # --- 2. Create Users ---
        users_data = [
            {'phone': '237111222333', 'name': 'Admin User', 'role': 'admin', 'is_staff': True}, #
            {'phone': '237444555666', 'name': 'Caissier John', 'role': 'caissier'}, #
            {'phone': '237777888999', 'name': 'Serveur Alice', 'role': 'serveur'}, #
            {'phone': '237000111222', 'name': 'Serveur Bob', 'role': 'serveur'}, #
        ]

        created_users = {}
        for data in users_data:
            user, created = User.objects.get_or_create( #
                phone=data['phone'], #
                defaults={
                    'name': data['name'], #
                    'role': data['role'], #
                    'organisation': org, #
                    'is_staff': data.get('is_staff', False) #
                }
            )
            if created:
                user.set_password('password123') # Set a default password
                user.save()
                self.stdout.write(self.style.SUCCESS(f'Created User: {user.name} ({user.role})'))
            else:
                self.stdout.write(self.style.WARNING(f'User "{user.name}" already exists.'))
            created_users[user.role] = user # Store one instance of each role

        admin_user = created_users.get('admin') #
        caissier_user = created_users.get('caissier') #
        serveur_alice = created_users.get('serveur') #
        serveur_bob = User.objects.get(phone='237000111222') # Retrieve specifically if not stored above

        if not all([admin_user, caissier_user, serveur_alice, serveur_bob]):
            self.stdout.write(self.style.ERROR("Failed to create all required users. Exiting."))
            return

        # --- 3. Create Categories and Products ---
        category_drinks, _ = Category.objects.get_or_create( #
            name='Boissons', #
            organisation=org, #
            defaults={'description': 'Boissons alcoolisées et non-alcoolisées'} #
        )
        category_food, _ = Category.objects.get_or_create( #
            name='Nourriture', #
            organisation=org, #
            defaults={'description': 'Plats et snacks'} #
        )

        products_data = [
            {'name': 'Whisky Jack Daniel\'s', 'price': 2500, 'stock_quantity': 50, 'category': category_drinks, 'unit': 'bouteille'}, #
            {'name': 'Champagne Moët', 'price': 3500, 'stock_quantity': 20, 'category': category_drinks, 'unit': 'bouteille'}, #
            {'name': 'Vodka Grey Goose', 'price': 2000, 'stock_quantity': 40, 'category': category_drinks, 'unit': 'bouteille'}, #
            {'name': 'Rhum Diplomatico', 'price': 2200, 'stock_quantity': 30, 'category': category_drinks, 'unit': 'bouteille'}, #
            {'name': 'Coca-Cola (canette)', 'price': 500, 'stock_quantity': 100, 'category': category_drinks, 'unit': 'pièce'}, #
            {'name': 'Bière Locale (grande)', 'price': 800, 'stock_quantity': 80, 'category': category_drinks, 'unit': 'bouteille'}, #
            {'name': 'Poulet DG', 'price': 5000, 'stock_quantity': 15, 'category': category_food, 'unit': 'plat'}, #
            {'name': 'Frites', 'price': 1500, 'stock_quantity': 30, 'category': category_food, 'unit': 'portion'}, #
        ]

        created_products = []
        for data in products_data:
            product, created = Product.objects.get_or_create( #
                name=data['name'], #
                organisation=org, #
                defaults={
                    'price': data['price'], #
                    'stock_quantity': data['stock_quantity'], #
                    'category': data['category'], #
                    'unit': data['unit'], #
                }
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'Created Product: {product.name}'))
            else:
                self.stdout.write(self.style.WARNING(f'Product "{product.name}" already exists.'))
            created_products.append(product)

        # --- 4. Create Orders (Mock Data) ---
        self.stdout.write(self.style.SUCCESS('Creating mock orders...'))
        
        today = timezone.now().date()
        yesterday = today - timedelta(days=1)
        day_before_yesterday = today - timedelta(days=2)

        all_serveurs = User.objects.filter(role='serveur', organisation=org) #
        if not all_serveurs.exists():
            self.stdout.write(self.style.ERROR("No serveur users found. Cannot create orders."))
            return

        # Function to create an order
        def create_order(serveur_user, num_customers, status, payment_type=None, created_offset_minutes=None, closed_offset_minutes=None, order_date=today):
            created_at = datetime.combine(order_date, datetime.min.time())
            if created_offset_minutes is not None:
                created_at += timedelta(minutes=created_offset_minutes)
            else:
                created_at = timezone.now() - timedelta(minutes=random.randint(5, 120))

            closed_at = None
            if status == 'fermee' and closed_offset_minutes is not None:
                closed_at = datetime.combine(order_date, datetime.min.time())
                closed_at += timedelta(minutes=closed_offset_minutes)
                if closed_at < created_at: # Ensure closed_at is after created_at
                    closed_at = created_at + timedelta(minutes=random.randint(10, 60))
            elif status == 'fermee':
                closed_at = created_at + timedelta(minutes=random.randint(10, 60))

            order = Order.objects.create( #
                organisation=org, #
                serveur=serveur_user, #
                number_of_customers=num_customers, #
                status=status, #
                payment_type=payment_type, #
                created_at=created_at, #
                closed_at=closed_at #
            )
            self.stdout.write(f'Created order {order.id} (Status: {order.status}) by {serveur_user.name}')

            total_amount = 0
            num_items = random.randint(1, 4)
            selected_products = random.sample(created_products, min(num_items, len(created_products)))
            for prod in selected_products:
                quantity = random.randint(1, 3)
                OrderItem.objects.create( #
                    order=order, #
                    product=prod, #
                    quantity=quantity, #
                    unit_price=prod.price #
                )
                total_amount += prod.price * quantity #

            order.total_amount = total_amount #
            order.save() #
            return order

        # --- Today's Orders ---
        # New orders (ouverte) by Alice
        create_order(serveur_alice, 3, 'ouverte', created_offset_minutes=1400) # 23h20
        create_order(serveur_alice, 2, 'ouverte', created_offset_minutes=1380) # 23h00

        # Preparing orders (servie) by Bob
        create_order(serveur_bob, 4, 'servie', created_offset_minutes=1350) # 22h30
        create_order(serveur_bob, 1, 'servie', created_offset_minutes=1320) # 22h00

        # Closed orders today (fermée) by Alice
        create_order(serveur_alice, 2, 'fermee', 'cash', created_offset_minutes=1000, closed_offset_minutes=1030) # 16h30
        create_order(serveur_alice, 5, 'fermee', 'mobile_money', created_offset_minutes=900, closed_offset_minutes=945) # 15h45
        create_order(serveur_alice, 1, 'fermee', 'cash', created_offset_minutes=800, closed_offset_minutes=815) # 13h35

        # Closed orders today (fermée) by Bob
        create_order(serveur_bob, 3, 'fermee', 'cash', created_offset_minutes=700, closed_offset_minutes=720) # 12h00
        create_order(serveur_bob, 2, 'fermee', 'mobile_money', created_offset_minutes=600, closed_offset_minutes=630) # 10h30

        # --- Yesterday's Orders ---
        # Example closed order from yesterday to ensure historical data works
        create_order(serveur_alice, 3, 'fermee', 'cash', order_date=yesterday, created_offset_minutes=900, closed_offset_minutes=930) # 15h30 yesterday
        create_order(serveur_bob, 2, 'fermee', 'mobile_money', order_date=yesterday, created_offset_minutes=800, closed_offset_minutes=815) # 13h35 yesterday

        self.stdout.write(self.style.SUCCESS('Mock data creation complete!'))