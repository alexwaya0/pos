from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.db import transaction
from django.utils import timezone
from django.core.mail import send_mail
from django.urls import reverse
from decimal import Decimal
from django.db.models import Sum
from .models import Branch, Product, ProductStock, Customer, Sale, SaleItem
from .forms import ProductForm, ProductStockForm, SaleCreateForm
from datetime import timedelta

def in_group(user, group_name):
    return user.groups.filter(name=group_name).exists() or user.is_superuser

def is_cashier(user):
    return in_group(user, "Cashier")

def is_manager(user):
    return in_group(user, "Manager")

@login_required
def dashboard(request):
    # Determine user role
    if request.user.is_superuser:
        role = 'admin'
    elif is_manager(request.user):
        role = 'manager'
    elif is_cashier(request.user):
        role = 'cashier'
    else:
        role = 'cashier'  # Default to cashier if no specific role

    # Common context
    context = {
        'role': role,
        'products': Product.objects.all(),
        'categories': Product.objects.values('category').distinct(),
    }

    # Branch-specific data for cashier and manager
    if role in ['cashier', 'manager']:
        try:
            branch = request.user.profile.branch
        except AttributeError:
            messages.error(request, "User profile or branch not set.")
            return redirect('pos:product_list')

        # Today's sales
        today = timezone.localdate()
        today_sales = Sale.objects.filter(branch=branch, created_at__date=today).aggregate(total=Sum('total'))['total'] or 0
        context['today_sales'] = today_sales

        # Low stock and near expiry
        low_stock_threshold = 10  # Hardcoded, adjust as needed
        expiry_days_threshold = 60  # Hardcoded, adjust as needed
        low_stocks = ProductStock.objects.filter(branch=branch, quantity__lte=low_stock_threshold)
        near_expiries = ProductStock.objects.filter(
            branch=branch,
            expiry_date__lte=today + timedelta(days=expiry_days_threshold),
            expiry_date__isnull=False
        )
        context.update({
            'low_stocks': low_stocks,
            'near_expiries': near_expiries,
            'sales_summary': Sale.objects.filter(branch=branch).aggregate(total=Sum('total'))['total'] or 0 if role == 'manager' else None
        })

    # Admin-specific data
    if role == 'admin':
        branches = Branch.objects.all()
        branch_sales = {
            b.name: Sale.objects.filter(branch=b).aggregate(total=Sum('total'))['total'] or 0
            for b in branches
        }
        # Mock notifications: combine low stock and expiry across all branches
        low_stock_threshold = 10
        expiry_days_threshold = 60
        today = timezone.localdate()
        low_stocks = ProductStock.objects.filter(quantity__lte=low_stock_threshold)
        near_expiries = ProductStock.objects.filter(
            expiry_date__lte=today + timedelta(days=expiry_days_threshold),
            expiry_date__isnull=False
        )
        notifications = []
        for stock in low_stocks:
            notifications.append({
                'message': f"Low stock: {stock.product.name} ({stock.quantity} units) at {stock.branch.name}",
                'created': today
            })
        for stock in near_expiries:
            notifications.append({
                'message': f"Near expiry: {stock.product.name} on {stock.expiry_date} at {stock.branch.name}",
                'created': today
            })
        context.update({
            'branch_sales': branch_sales,
            'notifications': notifications,
            'low_stocks': low_stocks,
            'near_expiries': near_expiries
        })

    return render(request, "pos/dashboard.html", context)

@login_required
def product_list(request):
    products = Product.objects.all()
    return render(request, "pos/product_list.html", {"products": products})

@login_required
@user_passes_test(lambda u: is_cashier(u) or is_manager(u) or u.is_superuser)
def product_add(request):
    # Cashiers can add new products
    if request.method == "POST":
        form = ProductForm(request.POST)
        stock_form = ProductStockForm(request.POST)
        if form.is_valid() and stock_form.is_valid():
            with transaction.atomic():
                product = form.save()
                stock = stock_form.save(commit=False)
                stock.product = product
                stock.save()
            messages.success(request, "Product and stock added.")
            return redirect("pos:product_list")
    else:
        form = ProductForm()
        stock_form = ProductStockForm()
    return render(request, "pos/product_add.html", {"form": form, "stock_form": stock_form})

@login_required
@user_passes_test(lambda u: is_cashier(u) or is_manager(u) or u.is_superuser)
def sale_create(request):
    """
    Basic sale creation without barcode. Frontend will POST items list as JSON or form fields.
    Supports pre-selected product from dashboard.
    """
    preselected_product = None
    if 'product' in request.GET:
        preselected_product = get_object_or_404(Product, pk=request.GET.get('product'))

    if request.method == "POST":
        # items posted as product_{id}_qty and product_{id}_price or we can accept a simple structure
        # For simplicity, expect form fields: branch, customer_phone, customer_name, notes
        form = SaleCreateForm(request.POST)
        items = []
        # collect items from POST: fields named item-0-product, item-0-price, item-0-qty ...
        index = 0
        while True:
            p_field = f"item-{index}-product_id"
            price_field = f"item-{index}-unit_price"
            qty_field = f"item-{index}-qty"
            if p_field not in request.POST:
                break
            pid = int(request.POST.get(p_field))
            unit_price = Decimal(request.POST.get(price_field))
            qty = int(request.POST.get(qty_field))
            product = get_object_or_404(Product, pk=pid)
            # enforce min price
            if unit_price < product.min_price:
                messages.error(request, f"Price for {product.name} cannot be lower than {product.min_price}")
                return redirect("pos:sale_create")
            items.append({"product": product, "unit_price": unit_price, "qty": qty})
            index += 1

        if not items:
            messages.error(request, "Add at least one item.")
            return redirect("pos:sale_create")

        if form.is_valid():
            branch = form.cleaned_data["branch"]
            phone = form.cleaned_data.get("customer_phone")
            name = form.cleaned_data.get("customer_name")
            notes = form.cleaned_data.get("notes")
            customer = None
            if phone:
                customer, _ = Customer.objects.get_or_create(phone=phone, defaults={"name": name or ""})
            total = sum((it["unit_price"] * it["qty"] for it in items))
            with transaction.atomic():
                sale = Sale.objects.create(branch=branch, cashier=request.user, customer=customer, total=total, cash_received=total, notes=notes)
                for it in items:
                    # choose a stock entry with earliest expiry for product in branch with qty>0
                    stock_qs = ProductStock.objects.filter(product=it["product"], branch=branch, quantity__gte=it["qty"]).order_by("expiry_date")
                    chosen_stock = stock_qs.first()
                    if not chosen_stock:
                        # try partial reduce from multiple lots (simple implementation: fail)
                        messages.error(request, f"Insufficient stock for {it['product'].name} in branch {branch.name}")
                        raise Exception("Insufficient stock")
                    # reduce quantity
                    chosen_stock.quantity -= it["qty"]
                    chosen_stock.save()
                    line_total = it["unit_price"] * it["qty"]
                    SaleItem.objects.create(sale=sale, product=it["product"], product_stock=chosen_stock, unit_price=it["unit_price"], qty=it["qty"], line_total=line_total)
                # optional email receipt to customer if email provided
                if customer and customer.email:
                    # provide receipt URL
                    receipt_url = request.build_absolute_uri(reverse("pos:receipt", kwargs={"sale_id": sale.id}))
                    send_mail(
                        subject=f"Your Receipt from {branch.name}",
                        message=f"Thank you for your purchase. View/print your receipt: {receipt_url}",
                        from_email=None,
                        recipient_list=[customer.email],
                        fail_silently=True,
                    )
            messages.success(request, "Sale recorded.")
            # Admin notifications will be via daily reports; we do not email per sale
            return redirect("pos:receipt", sale_id=sale.id)
    else:
        form = SaleCreateForm()
    products = Product.objects.all()
    return render(request, "pos/sale_create.html", {
        "form": form,
        "products": products,
        "preselected_product": preselected_product
    })

@login_required
def receipt_view(request, sale_id):
    sale = get_object_or_404(Sale, pk=sale_id)
    return render(request, "pos/receipt.html", {"sale": sale})

@login_required
def reports(request):
    # basic opening/closing balances per branch for days - simplified
    branches = Branch.objects.all()
    # For demo: compute today's opening and closing by sum of sales amounts. A robust implementation would use cash ledger.
    today = timezone.localdate()
    data = []
    for b in branches:
        day_sales = Sale.objects.filter(branch=b, created_at__date=today)
        total = sum(s.total for s in day_sales)
        # for demo, opening balance is assumed 0 (you can add cash ledger to track)
        data.append({"branch": b, "opening": 0, "sales": total, "closing": total})
    return render(request, "pos/reports.html", {"data": data})