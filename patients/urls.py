from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = "patients"

urlpatterns = [
    path("", views.register_patient, name="register"),
    path(
        "order/",
        RedirectView.as_view(url="https://order.helssa.ir", permanent=False),
        name="order_redirect",
    ),
    path(
        "blog/",
        RedirectView.as_view(url="https://api.medogram.ir/blog/", permanent=True),
        name="blog_redirect",
    ),
    path(
        "register/",
        RedirectView.as_view(url="/", permanent=True, query_string=True),
        name="register_patient",
    ),
    path("robots.txt", views.robots_txt, name="robots_txt"),
    path("sitemap.xml", views.sitemap_xml, name="sitemap_xml"),
    path("analytics/event/", views.analytics_event, name="analytics_event"),
    path("down/helssa.apk", views.download_helssa_apk, name="download_helssa_apk"),
    path("down/helssa-qr.svg", views.helssa_apk_qr_svg, name="helssa_apk_qr_svg"),
]
