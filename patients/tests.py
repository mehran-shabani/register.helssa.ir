from django.test import TestCase
from django.urls import reverse

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

    def test_required_field_messages_are_persian(self):
        form = PatientRegistrationForm(data={})

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["first_name"], ["وارد کردن نام الزامی است."])
        self.assertEqual(
            form.errors["last_name"], ["وارد کردن نام خانوادگی الزامی است."]
        )
        self.assertEqual(
            form.errors["mobile"], ["وارد کردن شماره موبایل الزامی است."]
        )


class RegisterPatientViewTests(TestCase):
    def test_get_register_patient_displays_empty_form(self):
        response = self.client.get(reverse("patients:register"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "patients/register.html")
        self.assertIsInstance(response.context["form"], PatientRegistrationForm)
        self.assertFalse(response.context["form"].is_bound)

    def test_register_template_uses_persian_labels_and_submit_text(self):
        response = self.client.get(reverse("patients:register"))

        self.assertContains(response, "ثبت‌نام بیماران")
        self.assertContains(response, "نام")
        self.assertContains(response, "نام خانوادگی")
        self.assertContains(response, "شماره موبایل")
        self.assertContains(response, "ارسال فرم")

    def test_invalid_post_preserves_submitted_values(self):
        response = self.client.post(
            reverse("patients:register"),
            data={
                "first_name": "علی",
                "last_name": "احمدی",
                "mobile": "08123456789",
            },
        )

        self.assertContains(response, 'value="علی"')
        self.assertContains(response, 'value="احمدی"')
        self.assertContains(response, 'value="08123456789"')

    def test_post_valid_form_saves_patient_redirects_and_adds_success_message(self):
        response = self.client.post(
            reverse("patients:register"),
            data={
                "first_name": "Ali",
                "last_name": "Ahmadi",
                "mobile": "09123456789",
            },
        )

        self.assertRedirects(response, reverse("patients:register"))
        self.assertTrue(
            Patient.objects.filter(
                first_name="Ali",
                last_name="Ahmadi",
                mobile="09123456789",
            ).exists()
        )

        messages = list(response.wsgi_request._messages)
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), "ثبت‌نام شما با موفقیت انجام شد.")

    def test_post_invalid_form_renders_errors_without_saving_patient(self):
        response = self.client.post(
            reverse("patients:register"),
            data={
                "first_name": "Ali",
                "last_name": "Ahmadi",
                "mobile": "08123456789",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Patient.objects.exists())
        self.assertContains(response, "شماره موبایل باید با 09 شروع شود.")
        self.assertTrue(response.context["form"].is_bound)
