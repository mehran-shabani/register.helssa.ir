from django import forms

from .models import Patient


class PatientRegistrationForm(forms.ModelForm):
    first_name = forms.CharField(required=True)
    last_name = forms.CharField(required=True)
    mobile = forms.CharField(required=True)

    class Meta:
        model = Patient
        fields = ["first_name", "last_name", "mobile"]

    def clean_mobile(self):
        mobile = self.cleaned_data["mobile"]

        if len(mobile) != 11:
            raise forms.ValidationError("شماره موبایل باید ۱۱ رقم باشد.")

        if not mobile.isdigit():
            raise forms.ValidationError("شماره موبایل فقط باید شامل عدد باشد.")

        if not mobile.startswith("09"):
            raise forms.ValidationError("شماره موبایل باید با 09 شروع شود.")

        if Patient.objects.filter(mobile=mobile).exists():
            raise forms.ValidationError("این شماره موبایل قبلاً ثبت شده است.")

        return mobile
