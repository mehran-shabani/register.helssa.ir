from django.urls import path

from . import views

app_name = "patients"

urlpatterns = [
    path("", views.register_patient, name="register"),
    path("register/", views.register_patient, name="register_patient"),
]
