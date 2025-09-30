from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.db import transaction
from django.utils import timezone
from django.core.mail import send_mail
from django.urls import reverse
from decimal import Decimal
from django.db.models import Sum, F, ExpressionWrapper, DecimalField
from .models import Branch, Product, ProductStock, Customer, Sale, SaleItem
from .forms import ProductForm, ProductStockForm, SaleCreateForm
from datetime import timedelta, datetime

def in_group(user, group_name):
    return user.groups.filter(name=group_name).exists() or user.is_superuser

def is_cashier(user):
    return in_group(user, "Cashier")

def is_manager(user):
    return in_group(user, "Manager")

@login_required
def dashboard(request):
    if request.user.is_superuser:
        role = 'admin'
    elif is_manager(request.user):
        role = 'manager'
    elif is_cashier(request.user):
        role = 'cashier'
    else:
        role = 'cashier'

    context = {
        'role': role,
        'products': Product.objects.all(),
        'categories': Product.objects.values('category').distinct(),
    }

    if role in ['cashier', 'manager']:
        try:
            branch = request.user.profile.branch
        except AttributeError:
            messages.error(request, "User profile or branch not set.")
            return redirect('pos:product_list')

        today = timezone.localdate()
        today_sales = Sale.objects.filter(branch=branch, created_at__date=today).aggregate(total=Sum('total'))['total'] or 0
        low_stock_threshold = 10
        expiry_days_threshold = 60
        low_stocks = ProductStock.objects.filter(branch=branch, quantity__lte=low_stock_threshold)
        near_expiries = ProductStock.objects.filter(
            branch=branch,
            expiry_date__lte=today + timedelta(days=expiry_days_threshold),
            expiry_date__isnull=False
        )
        context.update({
            'today_sales': today_sales,
            'low_stocks': low_stocks,
            'near_expiries': near_expiries,
            'sales_summary': Sale.objects.filter(branch=branch).aggregate(total=Sum('total'))['total'] or 0 if role == 'manager' else None
        })

    if role == 'admin':
        branches = Branch.objects.all()
        branch_sales = {
            b.name: Sale.objects.filter(branch=b).aggregate(total=Sum('total'))['total'] or 0
            for b in branches
        }
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
                'message': f"Low stock: {stock.product.name} ({stock.quantity} units, Batch: {stock.batch}) at {stock.branch.name}",
                'created': today
            })
        for stock in near_expiries:
            notifications.append({
                'message': f"Near expiry: {stock.product.name} (Batch: {stock.batch}) on {stock.expiry_date} at {stock.branch.name}",
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
    preselected_product = None
    if 'product' in request.GET:
        preselected_product = get_object_or_404(Product, pk=request.GET.get('product'))

    if request.method == "POST":
        form = SaleCreateForm(request.POST)
        items = []
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
                    stock_qs = ProductStock.objects.filter(product=it["product"], branch=branch, quantity__gte=it["qty"]).order_by("expiry_date")
                    chosen_stock = stock_qs.first()
                    if not chosen_stock:
                        messages.error(request, f"Insufficient stock for {it['product'].name} in branch {branch.name}")
                        raise Exception("Insufficient stock")
                    chosen_stock.quantity -= it["qty"]
                    chosen_stock.save()
                    line_total = it["unit_price"] * it["qty"]
                    SaleItem.objects.create(sale=sale, product=it["product"], product_stock=chosen_stock, unit_price=it["unit_price"], qty=it["qty"], line_total=line_total)
                if customer and customer.email:
                    receipt_url = request.build_absolute_uri(reverse("pos:receipt", kwargs={"sale_id": sale.id}))
                    send_mail(
                        subject=f"Your Receipt from {branch.name}",
                        message=f"Thank you for your purchase. View/print your receipt: {receipt_url}",
                        from_email=None,
                        recipient_list=[customer.email],
                        fail_silently=True,
                    )
            messages.success(request, "Sale recorded.")
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
    branches = Branch.objects.all()
    today = timezone.localdate()
    low_stock_threshold = 10
    expiry_days_threshold = 60

    date_range = request.GET.get('date-range', 'today')
    branch_id = request.GET.get('branch', '')
    alert_type = request.GET.get('alert_type', '')
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')

    if date_range == 'week':
        start_date = today - timedelta(days=7)
        end_date = today
    elif date_range == 'month':
        start_date = today - timedelta(days=30)
        end_date = today
    elif date_range == 'custom' and start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            messages.error(request, "Invalid date format. Using today's data.")
            start_date = today
            end_date = today
    else:
        start_date = today
        end_date = today

    selected_branches = branches
    if branch_id:
        selected_branches = branches.filter(id=branch_id)

    data = []
    for branch in selected_branches:
        sales_qs = Sale.objects.filter(branch=branch, created_at__date__gte=start_date, created_at__date__lte=end_date)
        total = sales_qs.aggregate(total=Sum('total'))['total'] or 0
        data.append({"branch": branch, "opening": 0, "sales": total, "closing": total})

    total_sales = sum(row['sales'] for row in data)

    sale_items_qs = SaleItem.objects.filter(sale__branch__in=selected_branches, sale__created_at__date__gte=start_date, sale__created_at__date__lte=end_date)

    total_profit = sale_items_qs.aggregate(
        profit=Sum(ExpressionWrapper(F('line_total') - F('qty') * F('product_stock__unit_cost'), output_field=DecimalField()))
    )['profit'] or Decimal('0.00')

    most_selling = sale_items_qs.values('product__name').annotate(total_qty=Sum('qty'), total_revenue=Sum('line_total')).order_by('-total_qty')[:5]

    sold_per_product = sale_items_qs.values('product__id', 'product__name').annotate(sold=Sum('qty')).order_by('product__name')
    stock_report = []
    for item in sold_per_product:
        product_id = item['product__id']
        closing = ProductStock.objects.filter(product_id=product_id, branch__in=selected_branches).aggregate(total=Sum('quantity'))['total'] or 0
        opening = closing + item['sold']
        stock_report.append({
            'product_name': item['product__name'],
            'opening': opening,
            'sold': item['sold'],
            'closing': closing
        })

    low_stocks = ProductStock.objects.filter(quantity__lte=low_stock_threshold, branch__in=selected_branches)
    near_expiries = ProductStock.objects.filter(
        expiry_date__lte=today + timedelta(days=expiry_days_threshold),
        expiry_date__isnull=False,
        branch__in=selected_branches
    )

    if alert_type == 'low_stock':
        near_expiries = ProductStock.objects.none()
    elif alert_type == 'expiry':
        low_stocks = ProductStock.objects.none()

    notifications = []
    if request.user.is_superuser:
        for stock in low_stocks:
            notifications.append({
                'message': f"Low stock: {stock.product.name} ({stock.quantity} units, Batch: {stock.batch}) at {stock.branch.name}",
                'created': today
            })
        for stock in near_expiries:
            notifications.append({
                'message': f"Near expiry: {stock.product.name} (Batch: {stock.batch}) on {stock.expiry_date} at {stock.branch.name}",
                'created': today
            })

    context = {
        'data': data,
        'branches': branches,
        'low_stocks': low_stocks,
        'near_expiries': near_expiries,
        'notifications': notifications,
        'role': 'admin' if request.user.is_superuser else 'manager' if is_manager(request.user) else 'cashier',
        'total_sales': total_sales,
        'total_profit': total_profit,
        'most_selling': most_selling,
        'stock_report': stock_report,
        'start_date': start_date.strftime('%Y-%m-%d'),
        'end_date': end_date.strftime('%Y-%m-%d'),
    }
    return render(request, "pos/reports.html", context)