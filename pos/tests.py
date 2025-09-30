from django.test import TestCase
from django.contrib.auth import get_user_model
from .models import Branch, Product

class SmokeTest(TestCase):
    def test_basic(self):
        Branch.objects.create(name="Test")
        Product.objects.create(name="P", price=10, min_price=5)
        self.assertEqual(Branch.objects.count(), 1)
        self.assertEqual(Product.objects.count(), 1)
