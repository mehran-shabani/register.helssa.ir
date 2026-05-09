from django import forms


class PatientRegistrationForm(forms.Form):
    """Basic patient registration form placeholder."""

    first_name = forms.CharField(label="First name", max_length=100)
    last_name = forms.CharField(label="Last name", max_length=100)
    national_id = forms.CharField(label="National ID", max_length=20)
    phone_number = forms.CharField(label="Phone number", max_length=20)
