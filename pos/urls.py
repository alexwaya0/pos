from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

app_name = "pos"

urlpatterns = [
    path("accounts/login/", auth_views.LoginView.as_view(template_name="pos/login.html"), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", views.dashboard, name="dashboard"),
    path("products/", views.product_list, name="product_list"),
    path("products/add/", views.product_add, name="product_add"),
    path("sales/new/", views.sale_create, name="sale_create"),
    path("receipt/<int:sale_id>/", views.receipt_view, name="receipt"),
    path("reports/", views.reports, name="reports"),
]
