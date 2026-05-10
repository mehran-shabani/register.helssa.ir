from unittest.mock import patch

from django.db import DatabaseError, IntegrityError
from django.test import TestCase
from django.urls import reverse

from .forms import DUPLICATE_MOBILE_ERROR, PatientRegistrationForm
from .models import Patient


class PatientModelTests(TestCase):
    def test_mobile_field_is_unique(self):
        self.assertTrue(Patient._meta.get_field("mobile").unique)


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
            ["شماره را ۱۱ رقمی وارد کنید."],
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
            ["فقط عدد وارد کنید."],
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
            ["شماره موبایل با 09 شروع شود."],
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
            [DUPLICATE_MOBILE_ERROR],
        )

    def test_required_field_messages_are_persian(self):
        form = PatientRegistrationForm(data={})

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["first_name"], ["نام را وارد کنید."])
        self.assertEqual(
            form.errors["last_name"], ["نام خانوادگی را وارد کنید."]
        )
        self.assertEqual(
            form.errors["mobile"], ["شماره موبایل را وارد کنید."]
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

    def test_register_template_uses_rtl_persian_html_attributes(self):
        response = self.client.get(reverse("patients:register"))

        self.assertContains(response, '<html lang="fa" dir="rtl">')

    def test_register_form_uses_persian_placeholders_and_ltr_mobile(self):
        response = self.client.get(reverse("patients:register"))

        self.assertContains(response, 'autocomplete="given-name"')
        self.assertContains(response, 'placeholder="مثلاً علی"')
        self.assertContains(response, 'autocomplete="family-name"')
        self.assertContains(response, 'placeholder="مثلاً رضایی"')
        self.assertContains(response, 'autocomplete="tel"')
        self.assertContains(response, 'aria-describedby="mobile-help"')
        self.assertContains(response, 'dir="ltr"')
        self.assertContains(response, 'inputmode="numeric"')
        self.assertContains(response, 'maxlength="11"')
        self.assertContains(response, 'placeholder="09123456789"')
        self.assertContains(
            response, "شماره موبایل باید ۱۱ رقمی و با 09 شروع شود."
        )

    def test_register_template_styles_messages_as_alert_cards(self):
        response = self.client.get(reverse("patients:register"))

        self.assertContains(response, 'class="message-stack"', count=0)

        response = self.client.post(
            reverse("patients:register"),
            data={
                "first_name": "Ali",
                "last_name": "Ahmadi",
                "mobile": "09123456789",
            },
            follow=True,
        )

        self.assertContains(response, 'class="message-stack"')
        self.assertContains(response, 'message-card message-card--success')
        self.assertContains(response, 'class="message-card__icon"')
        self.assertContains(response, "✓")

    def test_field_errors_render_below_each_field(self):
        response = self.client.post(
            reverse("patients:register"),
            data={"first_name": "", "last_name": "", "mobile": "08123456789"},
        )

        self.assertContains(response, 'aria-label="خطاهای نام"')
        self.assertContains(response, "نام را وارد کنید.")
        self.assertContains(response, 'aria-label="خطاهای نام خانوادگی"')
        self.assertContains(response, "نام خانوادگی را وارد کنید.")
        self.assertContains(response, 'aria-label="خطاهای شماره موبایل"')
        self.assertContains(response, "شماره موبایل با 09 شروع شود.")

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
        self.assertContains(response, "شماره موبایل با 09 شروع شود.")
        self.assertTrue(response.context["form"].is_bound)

    def test_post_handles_duplicate_mobile_integrity_error(self):
        with patch.object(
            PatientRegistrationForm,
            "save",
            side_effect=IntegrityError(
                "UNIQUE constraint failed: patients_patient.mobile"
            ),
        ):
            response = self.client.post(
                reverse("patients:register"),
                data={
                    "first_name": "Ali",
                    "last_name": "Ahmadi",
                    "mobile": "09123456789",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Patient.objects.exists())
        self.assertContains(response, DUPLICATE_MOBILE_ERROR)
        self.assertEqual(
            response.context["form"].errors["mobile"], [DUPLICATE_MOBILE_ERROR]
        )

    def test_post_handles_generic_database_save_error(self):
        with patch.object(
            PatientRegistrationForm,
            "save",
            side_effect=DatabaseError("database unavailable"),
        ):
            response = self.client.post(
                reverse("patients:register"),
                data={
                    "first_name": "Ali",
                    "last_name": "Ahmadi",
                    "mobile": "09123456789",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Patient.objects.exists())
        self.assertContains(
            response, "در ذخیره‌سازی اطلاعات مشکلی رخ داد. لطفاً دوباره تلاش کنید."
        )
