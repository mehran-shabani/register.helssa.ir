from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = "patients"

urlpatterns = [
    path("", views.register_patient, name="register"),
    path(
        "register/",
        RedirectView.as_view(url="/", permanent=True),
        name="register_patient",
    ),
    path("robots.txt", views.robots_txt, name="robots_txt"),
    path("sitemap.xml", views.sitemap_xml, name="sitemap_xml"),
]
