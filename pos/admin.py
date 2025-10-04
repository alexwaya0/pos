# admin.py
from django.contrib import admin, messages
from django.db.models import Sum
from django.core.exceptions import ValidationError
from django import forms
from django.utils.html import format_html # Used for color-coding in list display
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from .models import (
    Branch,
    Supplier,
    Product,
    ProductStock,
    Customer,
    Sale,
    SaleItem,
    UserActivityLog,
)
from decimal import Decimal

User = get_user_model()

# --- Branding Customization: Amigo POS™ ---
admin.site.site_header = "Amigo POS™ Administration"
admin.site.site_title = "Amigo POS™ Admin Portal"
admin.site.index_title = "Amigo POS™ Management Dashboard"
# --------------------------------------------------------

# --- Inline Models ---

class ProductStockInline(admin.TabularInline):
    """Inline for ProductStock, optimized for entry and performance."""
    model = ProductStock
    extra = 0
    fields = ("branch", "batch", "expiry_date", "quantity", "unit_cost")
    autocomplete_fields = ("branch", "supplier")
    verbose_name_plural = "Branch Stock Details (Inventory)"
    classes = ('collapse', 'open')


class SaleItemInline(admin.TabularInline):
    """Inline for SaleItem, optimized for data entry and review."""
    model = SaleItem
    extra = 0
    fields = ("product", "qty", "unit_price", "line_total")
    readonly_fields = ("line_total", "unit_price") # unit_price should come from the sale record
    autocomplete_fields = ("product",) 
    can_delete = False
    verbose_name_plural = "Items Sold"


# --- Product Form Validation (Fixes the ModelForm import error) ---
class ProductAdminForm(forms.ModelForm):
    """Custom form for ProductAdmin to enforce business rules."""
    class Meta:
        model = Product
        fields = '__all__'

    def clean(self):
        cleaned_data = super().clean()
        price = cleaned_data.get("price")
        min_price = cleaned_data.get("min_price")

        # Validation: Min price cannot be higher than the default price
        if price is not None and min_price is not None and min_price > price:
            self.add_error(
                'min_price',
                "The Minimum Price (Floor Price) cannot be greater than the Default Selling Price."
            )
        return cleaned_data


# --- Main Models ---

@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "address")
    search_fields = ("name", "phone")
    list_per_page = 20
    fieldsets = (
        ("Branch Information", {"fields": ("name", "phone")}),
        ("Location Details", {"fields": ("address",)}),
    )


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "contact")
    search_fields = ("name", "contact")
    list_per_page = 20


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    form = ProductAdminForm # Apply the custom form
    
    def total_stock_qty(self, obj):
        """Calculates total quantity and color-codes if zero."""
        total = obj.stocks.aggregate(Sum("quantity"))["quantity__sum"]
        if total is None or total == 0:
             return format_html('<span style="color: red; font-weight: bold;">{}</span>', 0)
        return total
    total_stock_qty.short_description = "Total Stock Qty"
    total_stock_qty.admin_order_field = 'name' 

    list_display = (
        "name", "category", "price", "min_price", "total_stock_qty",
    )
    search_fields = ("name", "category")
    list_filter = ("category", "created_at")
    list_editable = ("price", "min_price")
    inlines = [ProductStockInline]
    readonly_fields = ("created_at", "total_stock_qty")
    ordering = ("name",)
    list_per_page = 25
    
    fieldsets = (
        ("Product Details", {"fields": ("name", "category", "description")}),
        ("Pricing & Stock", {
            "fields": ("price", "min_price", "total_stock_qty"),
            "description": "Base price is the default selling price. Min price is the floor."
        }),
        (None, {"fields": ("created_at",)}),
    )


@admin.register(ProductStock)
class ProductStockAdmin(admin.ModelAdmin):
    def product_name(self, obj):
        return obj.product.name
    product_name.short_description = "Product"

    list_display = (
        "product_name", "branch", "expiry_date", "quantity", "supplier", "unit_cost",
    )
    list_filter = ("branch", "supplier", "expiry_date")
    search_fields = ("product__name", "branch__name", "batch")
    list_editable = ("quantity", "unit_cost")
    date_hierarchy = "expiry_date"
    autocomplete_fields = ("product", "branch", "supplier")
    list_per_page = 20
    

@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("phone", "name", "email")
    search_fields = ("phone", "name", "email")
    list_per_page = 20
    fieldsets = (
        (None, {"fields": ("phone", "name")}),
        ("Contact Information", {"fields": ("email",)}),
    )


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    
    def customer_display(self, obj):
        return str(obj.customer) if obj.customer else "Walk-in"
    customer_display.short_description = "Customer"

    def change_amount(self, obj):
        """Safely calculates the change due and color-codes the output."""
        # Use Decimal('0.00') as a safe fallback for new/unsaved objects
        total = obj.total or Decimal('0.00')
        cash_received = obj.cash_received or Decimal('0.00')
        
        change = cash_received - total
        
        if change > 0:
            return format_html('<span style="color: green; font-weight: bold;">₱ {:.2f}</span>', change)
        elif change < 0:
            # Should not happen on a completed sale, but shows short-payment
            return format_html('<span style="color: red;">₱ {:.2f}</span>', change)
        return f"₱ {Decimal('0.00'):.2f}"

    change_amount.short_description = "Change Due"

    list_display = (
        "id", "branch", "customer_display", "cashier", "created_at",
        "total", "cash_received", "change_amount",
    )
    list_filter = ("branch", "cashier", "created_at")
    search_fields = ("customer__phone", "customer__name", "branch__name")
    date_hierarchy = "created_at"
    readonly_fields = ("created_at", "total", "change_amount") 
    autocomplete_fields = ("branch", "cashier", "customer") 
    inlines = [SaleItemInline]
    list_per_page = 20
    
    fieldsets = (
        ("Sale Metadata", {"fields": (("branch", "cashier"), "customer", "notes")}),
        ("Financial Summary", {
            "fields": (("total", "cash_received"), "change_amount"),
            "description": "Total is calculated from line items. Change Due is (Cash Received - Total).",
            'classes': ('collapse', 'open')
        }),
        ("Timestamp", {"fields": ("created_at",), 'classes': ('collapse',)}),
    )

class CustomUserAdmin(UserAdmin):
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Roles', {
            'fields': ('groups',),
            'description': 'Assign roles: Cashier, Manager, or Admin by selecting the appropriate group.',
        }),
    )

    # Customize fieldsets to move 'groups' to a new fieldset
    original_fieldsets = UserAdmin.fieldsets
    permissions_fieldset = list(original_fieldsets[2])  # Permissions fieldset
    permissions_dict = permissions_fieldset[1]
    permissions_fields = list(permissions_dict['fields'])
    permissions_fields.remove('groups')
    permissions_dict['fields'] = tuple(permissions_fields)
    permissions_fieldset = tuple(permissions_fieldset)

    roles_fieldset = ('Roles', {
        'fields': ('groups',),
        'description': 'Assign roles: Cashier, Manager, or Admin by selecting the appropriate group.',
    })

    fieldsets = (
        original_fieldsets[0],
        original_fieldsets[1],
        permissions_fieldset,
        roles_fieldset,
        original_fieldsets[3],
    )

admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)

@admin.register(UserActivityLog)
class UserActivityLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'action', 'timestamp', 'ip_address')
    list_filter = ('action', 'timestamp')
    search_fields = ('user__username', 'user__first_name', 'user__last_name')
    date_hierarchy = 'timestamp'
    readonly_fields = ('timestamp',)
    ordering = ('-timestamp',)
    list_per_page = 50