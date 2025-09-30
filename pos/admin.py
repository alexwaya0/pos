from django.contrib import admin
from .models import Branch, Supplier, Product, ProductStock, Customer, Sale, SaleItem

@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("name", "address", "phone")

@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "contact")

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "price", "min_price", "created_at")

@admin.register(ProductStock)
class ProductStockAdmin(admin.ModelAdmin):
    list_display = ("product", "branch", "batch", "expiry_date", "quantity")

@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("phone", "name", "email")

class SaleItemInline(admin.TabularInline):
    model = SaleItem
    readonly_fields = ("product", "unit_price", "qty", "line_total")
    extra = 0

@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ("id", "branch", "cashier", "created_at", "total")
    inlines = [SaleItemInline]
