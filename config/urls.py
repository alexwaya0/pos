from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("pos.urls")),
    path("", RedirectView.as_view(pattern_name="pos:dashboard", permanent=False)),
]



# Customizing Admin Site Appearance for Amigo POS™
ADMIN_SITE_HEADER = "Amigo POS™ Administration"
ADMIN_SITE_TITLE = "Amigo POS™ Admin"
ADMIN_INDEX_TITLE = "Welcome to Amigo POS™ Dashboard"