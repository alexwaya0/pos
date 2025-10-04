from django.conf import settings
from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator
from decimal import Decimal

class Branch(models.Model):
    name = models.CharField(max_length=120)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=30, blank=True)

    class Meta:
        verbose_name = "Branch"
        verbose_name_plural = "Branches"

    def __str__(self):
        return self.name

class Supplier(models.Model):
    name = models.CharField(max_length=200)
    contact = models.CharField(max_length=200, blank=True)

    def __str__(self):
        return self.name

class Product(models.Model):
    # pharmacy item
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=120, blank=True)
    description = models.TextField(blank=True)
    # price is the default selling price
    price = models.DecimalField(max_digits=10, decimal_places=2)
    # fixed minimum floor price that cashier can't go below
    min_price = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(Decimal('0.00'))])
    # total quantity available in branch-level stock entries (use ProductStock per branch)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class ProductStock(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="stocks")
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="stocks")
    batch = models.CharField(max_length=120, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    quantity = models.IntegerField(default=0)
    supplier = models.ForeignKey(Supplier, null=True, blank=True, on_delete=models.SET_NULL)
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        unique_together = ("product", "branch", "batch", "expiry_date")

    def __str__(self):
        return f"{self.product.name} @ {self.branch.name} ({self.quantity})"

class Customer(models.Model):
    name = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=30, unique=False)
    email = models.EmailField(blank=True)

    def __str__(self):
        return f"{self.phone} - {self.name or 'Customer'}"

class Sale(models.Model):
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    cashier = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    customer = models.ForeignKey(Customer, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    cash_received = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"Sale #{self.id} - {self.branch.name} - {self.created_at.date()}"

class SaleItem(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    product_stock = models.ForeignKey(ProductStock, on_delete=models.PROTECT, null=True, blank=True)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    qty = models.IntegerField()
    line_total = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.product.name} x{self.qty}"

class UserActivityLog(models.Model):
    ACTION_CHOICES = [
        ('login', 'Login'),
        ('logout', 'Logout'),
    ]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='activity_logs')
    action = models.CharField(max_length=10, choices=ACTION_CHOICES)
    timestamp = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.user.username} - {self.get_action_display()} at {self.timestamp}"