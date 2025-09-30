from django import forms
from .models import Product, ProductStock, Sale, SaleItem, Customer, Branch

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ["name", "category", "description", "price", "min_price"]

class ProductStockForm(forms.ModelForm):
    class Meta:
        model = ProductStock
        fields = ["product", "branch", "batch", "expiry_date", "quantity", "supplier", "unit_cost"]

class SaleItemForm(forms.Form):
    product_id = forms.IntegerField(widget=forms.HiddenInput)
    product_name = forms.CharField(disabled=True)
    unit_price = forms.DecimalField(max_digits=10, decimal_places=2)
    qty = forms.IntegerField(min_value=1)

class SaleCreateForm(forms.Form):
    branch = forms.ModelChoiceField(queryset=Branch.objects.all())
    customer_phone = forms.CharField(max_length=30, required=False)
    customer_name = forms.CharField(max_length=200, required=False)
    notes = forms.CharField(widget=forms.Textarea, required=False)
    # sale items are handled in view via dynamic forms / JS
