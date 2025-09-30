from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("pos.urls")),
    path("", RedirectView.as_view(pattern_name="pos:dashboard", permanent=False)),
]
