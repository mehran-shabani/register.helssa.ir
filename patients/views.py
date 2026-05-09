from django.shortcuts import render

from .forms import PatientRegistrationForm


def register(request):
    """Render the patient registration page."""

    form = PatientRegistrationForm()
    return render(request, "patients/register.html", {"form": form})
