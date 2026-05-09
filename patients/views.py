from django.contrib import messages
from django.shortcuts import redirect, render

from .forms import PatientRegistrationForm


def register_patient(request):
    """Display and process the patient registration form."""

    if request.method == "POST":
        form = PatientRegistrationForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "ثبت‌نام شما با موفقیت انجام شد.")
            return redirect("patients:register")
    else:
        form = PatientRegistrationForm()

    return render(request, "patients/register.html", {"form": form})


register = register_patient
