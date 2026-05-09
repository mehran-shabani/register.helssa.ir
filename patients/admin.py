from django.contrib import admin

from .models import Patient


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ("first_name", "last_name", "mobile", "created_at")
    search_fields = ("mobile", "first_name", "last_name")
    ordering = ("-created_at",)
