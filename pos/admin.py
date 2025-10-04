# admin.py
from django.contrib import admin, messages
from django.db.models import Sum, F
from django.core.exceptions import ValidationError
from django import forms
from django.utils.html import format_html  # Used for color-coding in list display
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.shortcuts import render
from django.urls import path
from django.utils.safestring import mark_safe
from .models import (
    Branch,
    Supplier,
    Product,
    ProductStock,
    Customer,
    Sale,
    SaleItem,
    Profile,
)
from decimal import Decimal

User = get_user_model()

# --- Branding Customization: Azariah Pharmacy™ ---
admin.site.site_header = "Azariah Pharmacy™ Administration"
admin.site.site_title = "Azariah Pharmacy™ Admin Portal"
admin.site.index_title = "Azariah Pharmacy™ Management Dashboard"
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
    readonly_fields = ("line_total", "unit_price")  # unit_price should come from the sale record
    autocomplete_fields = ("product",)
    can_delete = False
    verbose_name_plural = "Items Sold"


class ProfileInline(admin.StackedInline):
    """Inline for User Profile to edit branch."""
    model = Profile
    extra = 0
    fields = ('branch',)
    autocomplete_fields = ('branch',)


# --- Product Form Validation ---
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


# --- Custom Actions ---

def restock_products(modeladmin, request, queryset):
    """Custom action to bulk restock products."""
    updated = queryset.update(quantity=F('quantity') + 10)  # Example: add 10 units
    modeladmin.message_user(request, f'Successfully restocked {updated} products.')
restock_products.short_description = "Restock selected products (add 10 units)"


def generate_report(modeladmin, request, queryset):
    """Custom action to generate a simple report."""
    # Placeholder for report generation
    modeladmin.message_user(request, f'Report generated for {queryset.count()} items.', level=messages.SUCCESS)
generate_report.short_description = "Generate report for selected items"


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
    actions = [generate_report]


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "contact")
    search_fields = ("name", "contact")
    list_per_page = 20
    actions = [generate_report]


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    form = ProductAdminForm  # Apply the custom form

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
    actions = [restock_products, generate_report]

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

    def low_stock_warning(self, obj):
        if obj.quantity <= 10:
            return format_html('<span style="color: red; font-weight: bold;">Low Stock!</span>')
        return "OK"
    low_stock_warning.short_description = "Stock Status"

    list_display = (
        "product_name", "branch", "expiry_date", "quantity", "low_stock_warning", "supplier", "unit_cost",
    )
    list_filter = ("branch", "supplier", "expiry_date")
    search_fields = ("product__name", "branch__name", "batch")
    list_editable = ("quantity", "unit_cost")
    date_hierarchy = "expiry_date"
    autocomplete_fields = ("product", "branch", "supplier")
    list_per_page = 20
    actions = [restock_products, generate_report]


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("phone", "name", "email")
    search_fields = ("phone", "name", "email")
    list_per_page = 20
    fieldsets = (
        (None, {"fields": ("phone", "name")}),
        ("Contact Information", {"fields": ("email",)}),
    )
    actions = [generate_report]


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
    actions = [generate_report]

    fieldsets = (
        ("Sale Metadata", {"fields": (("branch", "cashier"), "customer", "notes")}),
        ("Financial Summary", {
            "fields": (("total", "cash_received"), "change_amount"),
            "description": "Total is calculated from line items. Change Due is (Cash Received - Total).",
            'classes': ('collapse', 'open')
        }),
        ("Timestamp", {"fields": ("created_at",), 'classes': ('collapse',)}),
    )


class CustomUserChangeForm(UserChangeForm):
    group = forms.ModelChoiceField(
        queryset=Group.objects.filter(name__in=['Cashier', 'Manager', 'Admin']),
        empty_label="No Role Assigned",
        required=False,
        help_text="Select a single role for this user. Superuser status is handled separately."
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance:
            group = self.instance.groups.first()
            if group:
                self.initial['group'] = group
        self.fields.pop('groups', None)

    class Meta:
        model = User
        fields = UserChangeForm.Meta.fields

    def save_m2m(self):
        # Handle only user_permissions
        user_permissions = self.cleaned_data.get('user_permissions')
        if user_permissions is not None:
            self.instance.user_permissions.set(user_permissions)


class CustomUserAddForm(UserCreationForm):
    group = forms.ModelChoiceField(
        queryset=Group.objects.filter(name__in=['Cashier', 'Manager', 'Admin']),
        empty_label="No Role Assigned",
        required=False,
        help_text="Select a single role for this user. Superuser status is handled after creation."
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        admin_group = Group.objects.filter(name='Admin').first()
        if admin_group:
            self.fields['group'].initial = admin_group
        self.fields.pop('groups', None)

    class Meta:
        model = User
        fields = UserCreationForm.Meta.fields + ('group',)

    def save_m2m(self):
        pass  # No M2M to save beyond group, handled in save_model


class CustomUserAdmin(UserAdmin):
    form = CustomUserChangeForm
    add_form = CustomUserAddForm
    inlines = [ProfileInline]

    def get_role(self, obj):
        if obj.is_superuser:
            role = 'Admin'
            return format_html('<span style="color: green; font-weight: bold;">{}</span>', role)
        group = obj.groups.first()
        role = group.name if group else 'No Role'
        if role == 'Manager':
            return format_html('<span style="color: green; font-weight: bold;">{}</span>', role)
        elif role == 'Cashier':
            return format_html('<span style="color: blue;">{}</span>', role)
        elif role == 'Admin':
            return format_html('<span style="color: green; font-weight: bold;">{}</span>', role)
        else:
            return format_html('<span style="color: gray; font-style: italic;">{}</span>', role)
    get_role.short_description = 'Role'
    get_role.admin_order_field = 'groups'

    def get_branch(self, obj):
        if obj.is_superuser:
            return "HQ"
        try:
            branch = obj.profile.branch.name if obj.profile and obj.profile.branch else 'No Branch'
            if 'No Branch' in branch:
                return format_html('<span style="color: red; font-weight: bold;">{}</span>', branch)
            return branch
        except:
            return format_html('<span style="color: red; font-weight: bold;">No Branch</span>')
    get_branch.short_description = 'Branch'

    list_display = ('username', 'first_name', 'last_name', 'get_role', 'get_branch', 'is_staff', 'is_active', 'date_joined')
    search_fields = ('username', 'first_name', 'last_name', 'email')

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'password1', 'password2')
        }),
        ('Roles', {
            'classes': ('collapse',),
            'fields': ('group',),
            'description': 'Assign a single role: Cashier or Manager via dropdown. Superuser status is handled after creation.',
        }),
    )

    def get_fieldsets(self, request, obj=None):
        fieldsets = super().get_fieldsets(request, obj)
        if obj is not None:
            fieldsets = list(fieldsets)
            # Modify Personal info to remove email
            for i, fs in enumerate(fieldsets):
                if fs[0] == 'Personal info':
                    fields = list(fs[1]['fields'])
                    fields = [f for f in fields if f != 'email']
                    fieldsets[i] = (fs[0], {**fs[1], 'fields': tuple(fields)})
                    break
            permissions_index = next((i for i, fs in enumerate(fieldsets) if fs[0] == 'Permissions'), None)
            if permissions_index is not None:
                roles_fieldset = ('Roles', {
                    'fields': ('group',),
                    'description': 'Assign a single role: Cashier or Manager via dropdown. Superuser is a separate checkbox.',
                    'classes': ('collapse',),
                })
                fieldsets.insert(permissions_index + 1, roles_fieldset)
                # Remove groups from Permissions if present
                for i, fs in enumerate(fieldsets):
                    if fs[0] == 'Permissions':
                        fields = list(fs[1]['fields'])
                        if 'groups' in fields:
                            fields.remove('groups')
                            fieldsets[i] = (fs[0], {**fs[1], 'fields': tuple(fields)})
                        break
            fieldsets = tuple(fieldsets)
        return fieldsets

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        group = form.cleaned_data.get('group')
        obj.groups.clear()
        if group:
            obj.groups.add(group)
        # For superusers/admins, assign HQ branch
        if obj.is_superuser or (group and group.name == 'Admin'):
            hq_branch, created = Branch.objects.get_or_create(name='HQ', defaults={'address': 'Headquarters', 'phone': ''})
            profile, profile_created = Profile.objects.get_or_create(user=obj)
            if profile_created or profile.branch != hq_branch:
                profile.branch = hq_branch
                profile.save()

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(super().get_readonly_fields(request, obj))
        if obj and obj.is_superuser:
            readonly_fields.append('group')
        return readonly_fields


admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)