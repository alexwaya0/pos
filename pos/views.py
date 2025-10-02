# Updated views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.db import transaction
from django.utils import timezone
from django.core.mail import send_mail
from django.urls import reverse
from django.http import JsonResponse
from decimal import Decimal
from django.db.models import Sum, F, ExpressionWrapper, DecimalField, Count, Min
from .models import Branch, Product, ProductStock, Customer, Sale, SaleItem
from .forms import ProductForm, ProductStockForm, SaleCreateForm
from datetime import timedelta, datetime
import numpy as np

def in_group(user, group_name):
    return user.groups.filter(name=group_name).exists() or user.is_superuser

def is_cashier(user):
    return in_group(user, "Cashier")

def is_manager(user):
    return in_group(user, "Manager")

def get_user_display_name(user):
    return user.first_name or user.username

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
        'user_display_name': get_user_display_name(request.user),
        'products': Product.objects.all(),
        'categories': Product.objects.values('category').distinct().annotate(count=Count('id')),
    }

    today = timezone.localdate()
    low_stock_threshold = 10
    expiry_days_threshold = 60

    if role in ['cashier', 'manager']:
        try:
            branch = request.user.profile.branch
        except AttributeError:
            messages.error(request, "User profile or branch not set.")
            return redirect('pos:product_list')

        today_sales = Sale.objects.filter(branch=branch, created_at__date=today).aggregate(total=Sum('total'))['total'] or 0
        low_stocks = ProductStock.objects.filter(branch=branch, quantity__lte=low_stock_threshold)
        near_expiries = ProductStock.objects.filter(
            branch=branch,
            expiry_date__lte=today + timedelta(days=expiry_days_threshold),
            expiry_date__isnull=False
        )
        prescriptions_today = Sale.objects.filter(branch=branch, created_at__date=today).count()  # Proxy for prescriptions

        # Last 7 days sales for chart
        end_date = today
        start_date = end_date - timedelta(days=6)
        daily_sales = []
        current_date = start_date
        while current_date <= end_date:
            day_sales = Sale.objects.filter(
                branch=branch,
                created_at__date=current_date
            ).aggregate(total=Sum('total'))['total'] or 0
            daily_sales.append(float(day_sales))
            current_date += timedelta(days=1)
        sales_trend_data = daily_sales  # For line chart
        sales_labels = [d.strftime('%a') for d in (start_date + timedelta(n) for n in range(7))]

        recent_sales = Sale.objects.filter(branch=branch).select_related('branch', 'customer').prefetch_related('items__product').order_by('-created_at')[:10]

        context.update({
            'today_sales': today_sales,
            'low_stocks': low_stocks,
            'near_expiries': near_expiries,
            'prescriptions_today': prescriptions_today,
            'low_stock_count': low_stocks.count(),
            'sales_trend_data': sales_trend_data,
            'sales_labels': sales_labels,
            'recent_sales': recent_sales,
        })

        if role == 'manager':
            sales_summary = Sale.objects.filter(branch=branch).aggregate(total=Sum('total'))['total'] or 0
            context['sales_summary'] = sales_summary

    if role == 'admin':
        today_sales = Sale.objects.filter(created_at__date=today).aggregate(total=Sum('total'))['total'] or 0
        low_stocks = ProductStock.objects.filter(quantity__lte=low_stock_threshold)
        near_expiries = ProductStock.objects.filter(
            expiry_date__lte=today + timedelta(days=expiry_days_threshold),
            expiry_date__isnull=False
        )
        prescriptions_today = Sale.objects.filter(created_at__date=today).count()

        # Last 7 days sales for chart (all branches)
        end_date = today
        start_date = end_date - timedelta(days=6)
        daily_sales = []
        current_date = start_date
        while current_date <= end_date:
            day_sales = Sale.objects.filter(
                created_at__date=current_date
            ).aggregate(total=Sum('total'))['total'] or 0
            daily_sales.append(float(day_sales))
            current_date += timedelta(days=1)
        sales_trend_data = daily_sales
        sales_labels = [d.strftime('%a') for d in (start_date + timedelta(n) for n in range(7))]

        branches = Branch.objects.all()
        branch_sales = {
            b.name: Sale.objects.filter(branch=b).aggregate(total=Sum('total'))['total'] or 0
            for b in branches
        }

        recent_sales = Sale.objects.select_related('branch', 'customer').prefetch_related('items__product').order_by('-created_at')[:10]

        context.update({
            'today_sales': today_sales,
            'branch_sales': branch_sales,
            'low_stocks': low_stocks,
            'near_expiries': near_expiries,
            'prescriptions_today': prescriptions_today,
            'low_stock_count': low_stocks.count(),
            'sales_trend_data': sales_trend_data,
            'sales_labels': sales_labels,
            'recent_sales': recent_sales,
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
                        sale.delete()  # Rollback sale
                        return redirect("pos:sale_create")
                    # New check: Prevent sales at a loss
                    if it["unit_price"] < chosen_stock.unit_cost:
                        messages.error(request, f"Cannot sell {it['product'].name} at a loss. Selling price KSh {it['unit_price']} < cost KSh {chosen_stock.unit_cost}")
                        sale.delete()  # Rollback sale
                        return redirect("pos:sale_create")
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
        "preselected_product": preselected_product,
        "user_display_name": get_user_display_name(request.user)
    })

@login_required
def receipt_view(request, sale_id):
    sale = get_object_or_404(Sale, pk=sale_id)
    # Consume any pending messages to prevent them from displaying on this page
    messages.get_messages(request)
    if request.method == 'POST':
        # Handle close action, redirect back to sale_create
        return redirect('pos:sale_create')
    return render(request, "pos/receipt.html", {
        "sale": sale,
        "cashier_display_name": get_user_display_name(sale.cashier) if sale.cashier else 'Unknown'
    })

@login_required
def get_notifications(request):
    if not request.user.is_superuser:
        return JsonResponse({'notifications': [], 'unread_count': 0})
    today = timezone.localdate()
    low_stock_threshold = 10
    expiry_days_threshold = 60
    low_stocks = ProductStock.objects.filter(quantity__lte=low_stock_threshold)
    near_expiries = ProductStock.objects.filter(
        expiry_date__lte=today + timedelta(days=expiry_days_threshold),
        expiry_date__isnull=False
    )
    notifications = []
    for stock in low_stocks:
        notifications.append({
            'id': f"low_{stock.id}_{today}",
            'message': f"Low stock: {stock.product.name} ({stock.quantity} units, Batch: {stock.batch}) at {stock.branch.name}",
            'created': today.isoformat(),
            'type': 'low_stock'
        })
    for stock in near_expiries:
        notifications.append({
            'id': f"exp_{stock.id}_{today}",
            'message': f"Near expiry: {stock.product.name} (Batch: {stock.batch}) on {stock.expiry_date} at {stock.branch.name}",
            'created': today.isoformat(),
            'type': 'expiry'
        })
    return JsonResponse({'notifications': notifications})

@login_required
def reports(request):
    branches = Branch.objects.all()
    today = timezone.localdate()
    low_stock_threshold = 10
    expiry_days_threshold = 60

    date_range = request.GET.get('date-range', 'week')
    branch_id = request.GET.get('branch', '')
    alert_type = request.GET.get('alert_type', '')
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')

    if date_range == 'today':
        start_date = today
        end_date = today
    elif date_range == 'week':
        start_date = today - timedelta(days=6)
        end_date = today
    elif date_range == 'month':
        start_date = today - timedelta(days=30)
        end_date = today
    elif date_range == 'all_time':
        min_date = Sale.objects.aggregate(min_date=Min('created_at__date'))['min_date']
        # Practical limit: 2 years back to avoid excessive loops
        earliest_possible = today - timedelta(days=730)
        start_date = max(min_date, earliest_possible) if min_date else today
        end_date = today
    elif date_range == 'custom' and start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            messages.error(request, "Invalid date format. Using last 7 days data.")
            start_date = today - timedelta(days=6)
            end_date = today
    else:
        start_date = today - timedelta(days=6)
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

    total_cogs = total_sales - total_profit

    total_inventory_cost = ProductStock.objects.filter(branch__in=selected_branches).aggregate(
        cost=Sum(ExpressionWrapper(F('quantity') * F('unit_cost'), output_field=DecimalField()))
    )['cost'] or Decimal('0.00')

    beginning_cost = total_inventory_cost + total_cogs
    avg_inventory_cost = (beginning_cost + total_inventory_cost) / 2 if beginning_cost + total_inventory_cost > 0 else Decimal('0.00')
    inventory_turnover = total_cogs / avg_inventory_cost if avg_inventory_cost > 0 else 0
    inventory_turnover = round(float(inventory_turnover), 2)

    most_selling = sale_items_qs.values('product__name').annotate(total_qty=Sum('qty'), total_revenue=Sum('line_total')).order_by('-total_qty')[:5]

    sold_per_product = sale_items_qs.values('product__id', 'product__name').annotate(sold=Sum('qty')).order_by('product__name')
    stock_report = []
    for item in sold_per_product:
        product_id = item['product__id']
        closing = ProductStock.objects.filter(product_id=product_id, branch__in=selected_branches).aggregate(total=Sum('quantity'))['total'] or 0
        opening = closing + item['sold']
        sold_qs = sale_items_qs.filter(product_id=product_id)
        cogs = sold_qs.aggregate(
            cogs=Sum(ExpressionWrapper(F('qty') * F('product_stock__unit_cost'), output_field=DecimalField()))
        )['cogs'] or Decimal('0.00')
        closing_cost = ProductStock.objects.filter(product_id=product_id, branch__in=selected_branches).aggregate(
            cost=Sum(ExpressionWrapper(F('quantity') * F('unit_cost'), output_field=DecimalField()))
        )['cost'] or Decimal('0.00')
        opening_cost = closing_cost + cogs
        avg_cost = (opening_cost + closing_cost) / 2 if opening_cost + closing_cost > 0 else Decimal('0.00')
        turnover = float(cogs) / float(avg_cost) if avg_cost > 0 else 0
        stock_report.append({
            'product_name': item['product__name'],
            'opening': opening,
            'sold': item['sold'],
            'closing': closing,
            'turnover': round(turnover, 2)
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

    daily_data = []
    current_date = start_date
    while current_date <= end_date:
        sales_qs = Sale.objects.filter(branch__in=selected_branches, created_at__date=current_date)
        total_sales_day = sales_qs.aggregate(Sum('total'))['total__sum'] or Decimal('0.00')
        items_qs = SaleItem.objects.filter(sale__in=sales_qs)
        total_profit_day = items_qs.aggregate(
            profit=Sum(ExpressionWrapper(F('line_total') - F('qty') * F('product_stock__unit_cost'), output_field=DecimalField()))
        )['profit'] or Decimal('0.00')
        daily_data.append({'date': current_date, 'sales': total_sales_day, 'profit': total_profit_day})
        current_date += timedelta(days=1)

    sales_array = np.array([float(day['sales']) for day in daily_data])
    if len(sales_array) > 1:
        days = np.arange(len(sales_array))
        coef = np.polyfit(days, sales_array, 1)
        trend_sales = [coef[0] * x + coef[1] for x in days]
    else:
        trend_sales = sales_array.tolist()

    profits_array = np.array([float(day['profit']) for day in daily_data])
    if len(profits_array) > 1:
        days = np.arange(len(profits_array))
        coef = np.polyfit(days, profits_array, 1)
        trend_profits = [coef[0] * x + coef[1] for x in days]
    else:
        trend_profits = profits_array.tolist()

    context = {
        'data': data,
        'branches': branches,
        'low_stocks': low_stocks,
        'near_expiries': near_expiries,
        'role': 'admin' if request.user.is_superuser else 'manager' if is_manager(request.user) else 'cashier',
        'user_display_name': get_user_display_name(request.user),
        'total_sales': total_sales,
        'total_profit': total_profit,
        'inventory_turnover': inventory_turnover,
        'most_selling': most_selling,
        'stock_report': stock_report,
        'daily_data': daily_data,
        'trend_sales': [round(val, 2) for val in trend_sales],
        'trend_profits': [round(val, 2) for val in trend_profits],
        'start_date': start_date,
        'end_date': end_date,
        'date_range': date_range,
    }

    # Check for AJAX request for real-time updates
    x_requested_with = request.META.get('HTTP_X_REQUESTED_WITH', '')
    if x_requested_with == 'XMLHttpRequest':
        daily_serial = [
            {
                'date': d['date'].strftime('%b %d'),
                'sales': float(d['sales']),
                'profit': float(d['profit'])
            }
            for d in daily_data
        ]
        most_serial = [
            {
                'name': m['product__name'],
                'revenue': float(m['total_revenue'])
            }
            for m in most_selling
        ]
        trend_sales_list = [round(float(v), 2) for v in trend_sales]
        trend_profits_list = [round(float(v), 2) for v in trend_profits]
        data = {
            'daily_data': daily_serial,
            'trend_sales': trend_sales_list,
            'trend_profits': trend_profits_list,
            'most_selling': most_serial,
        }
        return JsonResponse(data)

    return render(request, "pos/reports.html", context)