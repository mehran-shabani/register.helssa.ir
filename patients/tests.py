from django.test import TestCase

from .forms import PatientRegistrationForm
from .models import Patient


class PatientRegistrationFormTests(TestCase):
    def test_valid_registration_form(self):
        form = PatientRegistrationForm(
            data={
                "first_name": "Ali",
                "last_name": "Ahmadi",
                "mobile": "09123456789",
            }
        )

        self.assertTrue(form.is_valid())

    def test_mobile_must_be_exactly_eleven_digits(self):
        form = PatientRegistrationForm(
            data={
                "first_name": "Ali",
                "last_name": "Ahmadi",
                "mobile": "0912345678",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors["mobile"],
            ["شماره موبایل باید ۱۱ رقم باشد."],
        )

    def test_mobile_must_contain_only_digits(self):
        form = PatientRegistrationForm(
            data={
                "first_name": "Ali",
                "last_name": "Ahmadi",
                "mobile": "0912345678a",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors["mobile"],
            ["شماره موبایل فقط باید شامل عدد باشد."],
        )

    def test_mobile_must_start_with_09(self):
        form = PatientRegistrationForm(
            data={
                "first_name": "Ali",
                "last_name": "Ahmadi",
                "mobile": "08123456789",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors["mobile"],
            ["شماره موبایل باید با 09 شروع شود."],
        )

    def test_mobile_must_be_unique(self):
        Patient.objects.create(
            first_name="Existing",
            last_name="Patient",
            mobile="09123456789",
        )
        form = PatientRegistrationForm(
            data={
                "first_name": "Ali",
                "last_name": "Ahmadi",
                "mobile": "09123456789",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors["mobile"],
            ["این شماره موبایل قبلاً ثبت شده است."],
        )
