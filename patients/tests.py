from datetime import datetime, timezone as datetime_timezone
from pathlib import Path
from unittest.mock import Mock, patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.db import DatabaseError, IntegrityError
from django.test import TestCase, override_settings
from django.urls import reverse
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.pdfbase.pdfmetrics import Font

from .admin import (
    PatientAdmin,
    PatientAdminForm,
    build_patients_pdf,
    SMSMessageLogAdmin,
    SMSMessageLogInline,
    format_sms_response,
)
from .datetime import (
    format_tehran_jalali,
    format_tehran_jalali_input,
    parse_tehran_jalali_datetime,
    to_english_digits,
)
from .forms import (
    DUPLICATE_MOBILE_ERROR,
    DUPLICATE_NATIONAL_CODE_ERROR,
    PatientRegistrationForm,
)
from .views import (
    COMMUNITY_BASE_COUNT,
    SHARE_DESCRIPTION,
    SHARE_IMAGE_PATH,
    SHARE_TITLE,
    SITE_LOGO_PATH,
    SITE_NAME,
)
from .models import SMSMessageLog, Patient
from .sms import (
    KavenegarSMSConfigurationError,
    build_patient_name_token,
    send_done_sms,
    send_register_sms,
)


def register_test_pdf_fonts():
    registered_fonts = set(pdfmetrics.getRegisteredFontNames())
    if "DejaVuSans" not in registered_fonts:
        pdfmetrics.registerFont(Font("DejaVuSans", "Helvetica", "WinAnsiEncoding"))
    if "DejaVuSans-Bold" not in registered_fonts:
        pdfmetrics.registerFont(
            Font("DejaVuSans-Bold", "Helvetica-Bold", "WinAnsiEncoding")
        )
    registerFontFamily(
        "DejaVuSans",
        normal="DejaVuSans",
        bold="DejaVuSans-Bold",
        italic="DejaVuSans",
        boldItalic="DejaVuSans-Bold",
    )


class PatientModelTests(TestCase):
    def test_mobile_field_is_unique(self):
        self.assertTrue(Patient._meta.get_field("mobile").unique)


class PersianDateTimeFormatTests(TestCase):
    def test_format_tehran_jalali_converts_utc_to_tehran_and_jalali(self):
        value = datetime(2026, 3, 20, 20, 45, 10, tzinfo=datetime_timezone.utc)

        self.assertEqual(format_tehran_jalali(value), "۱۴۰۵/۰۱/۰۱ ۰۰:۱۵:۱۰")

    def test_format_tehran_jalali_handles_naive_datetime(self):
        value = datetime(2026, 3, 20, 20, 45, 10)

        self.assertEqual(format_tehran_jalali(value), "۱۴۰۴/۱۲/۲۹ ۲۰:۴۵:۱۰")

    def test_jalali_input_format_and_parser_accept_persian_digits(self):
        value = datetime(2026, 6, 26, 5, 30, tzinfo=datetime_timezone.utc)

        self.assertEqual(format_tehran_jalali_input(value), "۱۴۰۵/۰۴/۰۵ ۰۹:۰۰")
        self.assertEqual(to_english_digits("۱۴۰۵/۰۴/۰۵ ۰۹:۰۰"), "1405/04/05 09:00")
        self.assertEqual(
            parse_tehran_jalali_datetime("۱۴۰۵/۰۴/۰۵ ۰۹:۰۰").astimezone(
                datetime_timezone.utc
            ),
            value,
        )

    def test_jalali_input_parser_accepts_dash_and_defaults_seconds(self):
        parsed = parse_tehran_jalali_datetime("1405-04-05 09:00")

        self.assertEqual(parsed.second, 0)
        self.assertEqual(format_tehran_jalali(parsed), "۱۴۰۵/۰۴/۰۵ ۰۹:۰۰:۰۰")


class PatientRegistrationFormTests(TestCase):
    def test_valid_registration_form(self):
        form = PatientRegistrationForm(
            data={
                "first_name": "Ali",
                "last_name": "Ahmadi",
                "national_code": "1234567890",
                "mobile": "09123456789",
            }
        )

        self.assertTrue(form.is_valid())

    def test_national_code_must_be_exactly_ten_digits(self):
        form = PatientRegistrationForm(
            data={
                "first_name": "Ali",
                "last_name": "Ahmadi",
                "national_code": "123456789",
                "mobile": "09123456789",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["national_code"], ["کد ملی را ۱۰ رقمی وارد کنید."])

    def test_national_code_must_contain_only_digits(self):
        form = PatientRegistrationForm(
            data={
                "first_name": "Ali",
                "last_name": "Ahmadi",
                "national_code": "123456789a",
                "mobile": "09123456789",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors["national_code"], ["کد ملی باید فقط شامل عدد باشد."]
        )

    def test_national_code_must_be_unique(self):
        Patient.objects.create(
            first_name="Existing",
            last_name="Patient",
            national_code="1234567890",
            mobile="09111111111",
        )
        form = PatientRegistrationForm(
            data={
                "first_name": "Ali",
                "last_name": "Ahmadi",
                "national_code": "1234567890",
                "mobile": "09123456789",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["national_code"], [DUPLICATE_NATIONAL_CODE_ERROR])

    def test_mobile_must_be_exactly_eleven_digits(self):
        form = PatientRegistrationForm(
            data={
                "first_name": "Ali",
                "last_name": "Ahmadi",
                "national_code": "1234567890",
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
                "national_code": "1234567890",
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
                "national_code": "1234567890",
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
            national_code="1111111111",
        )
        form = PatientRegistrationForm(
            data={
                "first_name": "Ali",
                "last_name": "Ahmadi",
                "national_code": "1234567890",
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
        self.assertEqual(form.errors["last_name"], ["نام خانوادگی را وارد کنید."])
        self.assertEqual(form.errors["national_code"], ["کد ملی را وارد کنید."])
        self.assertEqual(form.errors["mobile"], ["شماره موبایل را وارد کنید."])


class KavenegarRegisterSMSTests(TestCase):
    def test_patient_name_token_replaces_spaces_inside_first_and_last_name(self):
        patient = Patient(first_name="علی رضا", last_name="کاوه نگار")

        self.assertEqual(build_patient_name_token(patient), "علی_رضا_کاوه_نگار")

    @override_settings(
        KAVENEGAR_API_KEY="test-api-key",
        KAVENEGAR_REGISTER_TEMPLATE="register-template",
    )
    def test_send_register_sms_uses_configured_template_as_template_token(self):
        api = Mock()
        api.verify_lookup.return_value = {"return": {"status": 200}}

        with patch("patients.sms._build_kavenegar_api", return_value=api) as build_api:
            result = send_register_sms("09123456789", "Ali_Ahmadi")

        self.assertEqual(result, {"return": {"status": 200}})
        build_api.assert_called_once_with("test-api-key")
        api.verify_lookup.assert_called_once_with(
            {
                "receptor": "09123456789",
                "template": "register-template",
                "token": "Ali_Ahmadi",
            }
        )

    @override_settings(
        KAVENEGAR_API_KEY="test-api-key",
        KAVENEGAR_DONE_TEMPLATE="done-template",
    )
    def test_send_done_sms_uses_configured_done_template(self):
        api = Mock()
        api.verify_lookup.return_value = {"return": {"status": 200}}

        with patch("patients.sms._build_kavenegar_api", return_value=api) as build_api:
            result = send_done_sms("09123456789", "Ali_Ahmadi")

        self.assertEqual(result, {"return": {"status": 200}})
        build_api.assert_called_once_with("test-api-key")
        api.verify_lookup.assert_called_once_with(
            {
                "receptor": "09123456789",
                "template": "done-template",
                "token": "Ali_Ahmadi",
            }
        )

    @override_settings(KAVENEGAR_API_KEY="test-api-key", KAVENEGAR_REGISTER_TEMPLATE="")
    def test_send_register_sms_requires_configured_template(self):
        with self.assertRaises(KavenegarSMSConfigurationError):
            send_register_sms("09123456789", "Ali_Ahmadi")

    @override_settings(KAVENEGAR_API_KEY="")
    def test_send_register_sms_requires_api_key(self):
        with self.assertRaises(KavenegarSMSConfigurationError):
            send_register_sms("09123456789", "Ali_Ahmadi")

    @override_settings(
        KAVENEGAR_API_KEY="test-api-key",
        KAVENEGAR_REGISTER_TEMPLATE="register-template",
    )
    def test_patient_creation_signal_sends_register_sms_after_commit(self):
        with patch("patients.signals.send_register_sms") as send_sms:
            with self.captureOnCommitCallbacks(execute=True):
                patient = Patient.objects.create(
                    first_name="Ali",
                    last_name="Ahmadi",
                    mobile="09123456789",
                )

        send_sms.assert_called_once_with("09123456789", "Ali_Ahmadi")
        self.assertEqual(SMSMessageLog.objects.count(), 1)
        sms_log = SMSMessageLog.objects.get()
        self.assertEqual(sms_log.patient, patient)
        self.assertEqual(sms_log.mobile, "09123456789")
        self.assertEqual(sms_log.template, "register-template")
        self.assertEqual(sms_log.token, "Ali_Ahmadi")
        self.assertEqual(sms_log.status, SMSMessageLog.STATUS_SUCCESS)

    def test_sms_message_log_preserves_history_when_patient_is_deleted(self):
        patient = Patient.objects.create(
            first_name="Ali",
            last_name="Ahmadi",
            mobile="09123456789",
            national_code="1111111111",
        )
        sms_log = SMSMessageLog.objects.create(
            patient=patient,
            mobile=patient.mobile,
            template="done-template",
            token="Ali_Ahmadi",
            status=SMSMessageLog.STATUS_SUCCESS,
        )

        patient.delete()
        sms_log.refresh_from_db()

        self.assertIsNone(sms_log.patient)
        self.assertEqual(sms_log.mobile, "09123456789")

    @override_settings(
        KAVENEGAR_API_KEY="test-api-key", KAVENEGAR_DONE_TEMPLATE="done-template"
    )
    def test_admin_action_sends_done_sms_to_selected_patients(self):
        user = get_user_model().objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="password",
        )
        self.client.force_login(user)
        patient = Patient.objects.create(
            first_name="Ali",
            last_name="Ahmadi",
            mobile="09123456789",
            national_code="1111111111",
        )

        with patch("patients.admin.send_done_sms") as send_sms:
            response = self.client.post(
                reverse("admin:patients_patient_changelist"),
                {
                    "action": "send_done_sms_to_patients",
                    "_selected_action": [str(patient.pk)],
                    "index": "0",
                },
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        send_sms.assert_called_once_with("09123456789", "Ali_Ahmadi")
        sms_log = SMSMessageLog.objects.get(patient=patient)
        self.assertEqual(sms_log.template, "done-template")
        self.assertEqual(sms_log.token, "Ali_Ahmadi")
        self.assertEqual(sms_log.status, SMSMessageLog.STATUS_SUCCESS)
        self.assertIn(
            "پیامک انجام شد برای 1 بیمار ارسال شد.",
            [message.message for message in get_messages(response.wsgi_request)],
        )

    @override_settings(KAVENEGAR_API_KEY="", KAVENEGAR_DONE_TEMPLATE="")
    def test_admin_action_validates_kavenegar_settings_before_patient_loop(self):
        user = get_user_model().objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="password",
        )
        self.client.force_login(user)
        patient = Patient.objects.create(
            first_name="Ali",
            last_name="Ahmadi",
            mobile="09123456789",
            national_code="1111111111",
        )

        with patch("patients.admin.send_done_sms") as send_sms:
            response = self.client.post(
                reverse("admin:patients_patient_changelist"),
                {
                    "action": "send_done_sms_to_patients",
                    "_selected_action": [str(patient.pk)],
                    "index": "0",
                },
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        send_sms.assert_not_called()
        self.assertFalse(SMSMessageLog.objects.exists())
        self.assertIn(
            "تنظیمات سامانه پیامک (KAVENEGAR_API_KEY یا "
            "KAVENEGAR_DONE_TEMPLATE) پیکربندی نشده است.",
            [message.message for message in get_messages(response.wsgi_request)],
        )

    def test_admin_action_downloads_pdf_report_for_selected_patients(self):
        register_test_pdf_fonts()
        user = get_user_model().objects.create_superuser(
            username="admin-pdf",
            email="admin-pdf@example.com",
            password="password",
        )
        self.client.force_login(user)
        patient = Patient.objects.create(
            first_name="Ali",
            last_name="Ahmadi",
            mobile="09123456789",
            national_code="1111111111",
        )

        response = self.client.post(
            reverse("admin:patients_patient_changelist"),
            {
                "action": "download_patients_pdf_report",
                "_selected_action": [str(patient.pk)],
                "index": "0",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("selected-patients-report.pdf", response["Content-Disposition"])
        content = b"".join(response.streaming_content)
        self.assertTrue(content.startswith(b"%PDF"))

    def test_build_patients_pdf_returns_pdf_buffer(self):
        register_test_pdf_fonts()
        patient = Patient.objects.create(
            first_name="علی",
            last_name="احمدی",
            mobile="09123456789",
            national_code="1111111111",
        )

        pdf_buffer = build_patients_pdf([patient])

        self.assertTrue(pdf_buffer.getvalue().startswith(b"%PDF"))

    def test_patient_admin_list_shows_national_code_instead_of_mobile(self):
        model_admin = PatientAdmin(Patient, admin.site)

        self.assertEqual(
            model_admin.list_display,
            (
                "first_name",
                "last_name",
                "national_code",
                "sms_sent_indicator",
                "created_at_jalali",
            ),
        )
        self.assertNotIn("mobile", model_admin.list_display)
        self.assertIn("mobile", model_admin.get_fields(request=Mock()))

    def test_patient_admin_national_code_field_has_copy_button_assets(self):
        form = PatientAdminForm()
        national_code_field = form.fields["national_code"]
        model_admin = PatientAdmin(Patient, admin.site)
        media = str(model_admin.media)

        self.assertEqual(
            national_code_field.widget.attrs["data-copy-national-code"], "true"
        )
        self.assertEqual(national_code_field.widget.attrs["maxlength"], "10")
        self.assertIn("copy_national_code.css", media)
        self.assertIn("copy_national_code.js", media)

    @override_settings(KAVENEGAR_DONE_TEMPLATE="done-template")
    def test_patient_admin_marks_patients_with_successful_done_sms(self):
        user = get_user_model().objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="password",
        )
        patient = Patient.objects.create(
            first_name="Ali",
            last_name="Ahmadi",
            mobile="09123456789",
            national_code="1111111111",
        )
        SMSMessageLog.objects.create(
            patient=patient,
            mobile=patient.mobile,
            template="done-template",
            token="Ali_Ahmadi",
            status=SMSMessageLog.STATUS_SUCCESS,
        )
        request = Mock(user=user)
        model_admin = PatientAdmin(Patient, admin.site)

        patient_from_admin = model_admin.get_queryset(request).get(pk=patient.pk)

        self.assertTrue(model_admin.sms_sent_indicator(patient_from_admin))

    @override_settings(KAVENEGAR_DONE_TEMPLATE="done-template")
    def test_patient_admin_does_not_mark_patients_without_successful_done_sms(self):
        user = get_user_model().objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="password",
        )
        patient = Patient.objects.create(
            first_name="Ali",
            last_name="Ahmadi",
            mobile="09123456789",
            national_code="1111111111",
        )
        SMSMessageLog.objects.create(
            patient=patient,
            mobile=patient.mobile,
            template="done-template",
            token="Ali_Ahmadi",
            status=SMSMessageLog.STATUS_FAILED,
        )
        request = Mock(user=user)
        model_admin = PatientAdmin(Patient, admin.site)

        patient_from_admin = model_admin.get_queryset(request).get(pk=patient.pk)

        self.assertFalse(model_admin.sms_sent_indicator(patient_from_admin))

    @override_settings(KAVENEGAR_DONE_TEMPLATE="done-template")
    def test_patient_admin_ignores_successful_non_done_sms(self):
        user = get_user_model().objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="password",
        )
        patient = Patient.objects.create(
            first_name="Ali",
            last_name="Ahmadi",
            mobile="09123456789",
            national_code="1111111111",
        )
        SMSMessageLog.objects.create(
            patient=patient,
            mobile=patient.mobile,
            template="register-template",
            token="Ali_Ahmadi",
            status=SMSMessageLog.STATUS_SUCCESS,
        )
        request = Mock(user=user)
        model_admin = PatientAdmin(Patient, admin.site)

        patient_from_admin = model_admin.get_queryset(request).get(pk=patient.pk)

        self.assertFalse(model_admin.sms_sent_indicator(patient_from_admin))

    def test_admin_created_at_uses_jalali_date_and_tehran_time(self):
        model_admin = PatientAdmin(Patient, admin.site)
        patient = Patient(
            first_name="Ali",
            last_name="Ahmadi",
            mobile="09123456789",
            created_at=datetime(2026, 3, 20, 20, 45, 10, tzinfo=datetime_timezone.utc),
        )

        self.assertEqual(model_admin.created_at_jalali(patient), "۱۴۰۵/۰۱/۰۱ ۰۰:۱۵:۱۰")

    def test_sms_log_admin_created_at_uses_jalali_date_and_tehran_time(self):
        model_admin = SMSMessageLogAdmin(SMSMessageLog, admin.site)
        sms_log = SMSMessageLog(
            mobile="09123456789",
            template="done-template",
            token="Ali_Ahmadi",
            status=SMSMessageLog.STATUS_SUCCESS,
            created_at=datetime(2026, 6, 15, 8, 30, 5, tzinfo=datetime_timezone.utc),
        )

        self.assertEqual(model_admin.created_at_jalali(sms_log), "۱۴۰۵/۰۳/۲۵ ۱۲:۰۰:۰۵")

    def test_sms_response_is_formatted_for_admin_display(self):
        response = repr(
            [
                {
                    "messageid": 1540699584,
                    "message": "درخواست شما\nثبت شد",
                    "status": 5,
                    "statustext": "ارسال به مخابرات",
                    "sender": "10004347",
                    "receptor": "09164521571",
                    "date": 1781688729,
                    "cost": 2910,
                }
            ]
        )

        formatted_response = str(format_sms_response(response))

        self.assertIn("شناسه پیامک", formatted_response)
        self.assertIn("1540699584", formatted_response)
        self.assertIn("متن پیام", formatted_response)
        self.assertIn("درخواست شما\nثبت شد", formatted_response)
        self.assertIn("وضعیت سرویس", formatted_response)
        self.assertIn("ارسال به مخابرات", formatted_response)
        self.assertIn("زمان سرویس", formatted_response)
        self.assertIn("۱۴۰۵/۰۳/۲۷ ۱۳:۰۲:۰۹", formatted_response)
        self.assertIn("min-width: min(100%, 360px)", formatted_response)
        self.assertIn("overflow-wrap: break-word", formatted_response)
        self.assertIn("word-break: normal", formatted_response)
        self.assertNotIn("overflow-wrap: anywhere", formatted_response)
        self.assertNotIn("messageid", formatted_response)

    def test_sms_response_preserves_unparseable_text(self):
        formatted_response = str(format_sms_response("raw error response"))

        self.assertIn("raw error response", formatted_response)

    def test_sms_message_log_admin_views_do_not_allow_add_or_delete(self):
        user = get_user_model().objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="password",
        )
        request = Mock(user=user)
        inline = SMSMessageLogInline(Patient, admin.site)
        model_admin = SMSMessageLogAdmin(SMSMessageLog, admin.site)

        self.assertFalse(inline.has_add_permission(request))
        self.assertFalse(inline.has_delete_permission(request))
        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_delete_permission(request))

    def test_sms_message_log_admin_hides_raw_response_fields(self):
        request = Mock(user=Mock())
        model_admin = SMSMessageLogAdmin(SMSMessageLog, admin.site)

        fields = model_admin.get_fields(request)

        self.assertIn("formatted_response", fields)
        self.assertIn("formatted_error", fields)
        self.assertNotIn("response", fields)
        self.assertNotIn("error", fields)

    @override_settings(KAVENEGAR_API_KEY="test-api-key")
    def test_patient_update_signal_does_not_send_register_sms(self):
        patient = Patient.objects.create(
            first_name="Ali",
            last_name="Ahmadi",
            mobile="09123456789",
            national_code="1111111111",
        )

        with patch("patients.signals.send_register_sms") as send_sms:
            with self.captureOnCommitCallbacks(execute=True):
                patient.first_name = "Reza"
                patient.save()

        send_sms.assert_not_called()


class RegisterPatientViewTests(TestCase):
    def test_get_register_patient_displays_empty_form(self):
        response = self.client.get(reverse("patients:register"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "patients/register.html")
        self.assertIsInstance(response.context["form"], PatientRegistrationForm)
        self.assertFalse(response.context["form"].is_bound)

    def test_register_template_includes_animated_registration_stats(self):
        Patient.objects.create(
            first_name="Ali",
            last_name="Ahmadi",
            national_code="1234567890",
            mobile="09123456789",
        )
        Patient.objects.create(
            first_name="Reza",
            last_name="Karimi",
            national_code="1234567891",
            mobile="09123456780",
        )

        response = self.client.get(reverse("patients:register"))

        self.assertEqual(
            response.context["stats"]["community_count"], COMMUNITY_BASE_COUNT + 2
        )
        self.assertContains(
            response, f'data-counter data-target="{COMMUNITY_BASE_COUNT + 2}"'
        )
        self.assertContains(response, "افراد ثبت‌نام‌کرده تا کنون")
        self.assertNotContains(response, "ثبت‌نام‌شده در سایت")
        self.assertNotContains(response, "جامعه همراه طرح")
        self.assertContains(response, "چرا دکتر شبانی؟")
        self.assertContains(response, "تعرفه دولتی")

    def test_register_template_uses_persian_labels_and_submit_text(self):
        response = self.client.get(reverse("patients:register"))

        self.assertContains(response, SITE_NAME)
        self.assertContains(response, "نام")
        self.assertContains(response, "نام خانوادگی")
        self.assertContains(response, "شماره موبایل")
        self.assertContains(response, ">ثبت‌نام</button>")

    def test_register_template_includes_standard_copyright_footer(self):
        response = self.client.get(reverse("patients:register"))

        self.assertContains(response, '<footer class="site-footer')
        self.assertContains(response, "&copy; 2026 Helssa. All rights reserved.")

    def test_register_template_includes_share_preview_metadata(self):
        response = self.client.get(reverse("patients:register"))

        share_image_url = f"http://testserver/static/{SHARE_IMAGE_PATH}"
        self.assertContains(response, f"<title>{SHARE_TITLE}</title>")
        self.assertContains(
            response, f'<meta name="description" content="{SHARE_DESCRIPTION}">'
        )
        self.assertContains(
            response, f'<meta property="og:site_name" content="{SITE_NAME}">'
        )
        self.assertContains(
            response, f'<meta property="og:title" content="{SHARE_TITLE}">'
        )
        self.assertContains(
            response,
            f'<meta property="og:description" content="{SHARE_DESCRIPTION}">',
        )
        self.assertContains(
            response, '<meta property="og:url" content="http://testserver/">'
        )
        self.assertContains(
            response, f'<meta property="og:image" content="{share_image_url}">'
        )
        self.assertContains(
            response, '<meta property="og:image:type" content="image/png">'
        )
        self.assertContains(
            response, '<meta name="twitter:card" content="summary_large_image">'
        )
        self.assertContains(
            response, f'<meta name="twitter:image" content="{share_image_url}">'
        )

    def test_logo_instructions_document_required_image_files(self):
        instructions = Path("logo.md").read_text(encoding="utf-8")

        self.assertIn(SHARE_IMAGE_PATH, instructions)
        self.assertIn(SITE_LOGO_PATH, instructions)
        self.assertIn("1200×630", instructions)
        self.assertIn("512×512", instructions)
        self.assertIn(SITE_NAME, instructions)
        self.assertIn(SHARE_DESCRIPTION, instructions)

    def test_missing_site_logo_does_not_render_broken_image(self):
        logo_path = Path("patients/static") / SITE_LOGO_PATH
        hidden_logo_path = logo_path.with_suffix(".hidden-for-test")
        logo_path.rename(hidden_logo_path)
        try:
            response = self.client.get(reverse("patients:register"))
        finally:
            hidden_logo_path.rename(logo_path)

        self.assertNotContains(response, 'class="hero__logo"')
        self.assertNotContains(response, '<link rel="icon" type="image/png"')

    def test_site_logo_renders_after_file_is_provided(self):
        logo_path = Path("patients/static") / SITE_LOGO_PATH
        logo_path.parent.mkdir(parents=True, exist_ok=True)
        logo_existed = logo_path.exists()
        original_logo = logo_path.read_bytes() if logo_existed else None
        logo_path.write_bytes(b"\x89PNG\r\n\x1a\n")
        try:
            response = self.client.get(reverse("patients:register"))
        finally:
            if logo_existed:
                logo_path.write_bytes(original_logo)
            else:
                logo_path.unlink(missing_ok=True)

        site_logo_url = f"http://testserver/static/{SITE_LOGO_PATH}"
        self.assertContains(response, 'class="hero__logo reveal"')
        self.assertContains(response, f'src="{site_logo_url}"')
        self.assertContains(response, f'href="{site_logo_url}"')

    def test_register_form_disables_submit_button_after_submit_with_javascript(self):
        response = self.client.get(reverse("patients:register"))

        self.assertContains(response, "data-registration-form")
        self.assertContains(response, "data-submit-button")
        self.assertContains(response, 'data-submitting-text="در حال ثبت..."')
        self.assertContains(response, "submitButton.disabled = true")

    def test_register_button_has_disabled_styles(self):
        css = Path("patients/static/patients/css/style.css").read_text()

        self.assertIn(".form-card button:disabled", css)
        self.assertIn("cursor: not-allowed", css)
        self.assertIn("--color-button-disabled", css)

    def test_register_template_uses_decorative_inline_svg_icons(self):
        response = self.client.get(reverse("patients:register"))

        self.assertContains(response, 'class="icon form-field__icon"', count=4)
        self.assertContains(response, 'focusable="false"')
        self.assertContains(response, 'aria-hidden="true"')

    def test_register_styles_use_short_motion_and_reduced_motion_override(self):
        css = Path("patients/static/patients/css/style.css").read_text()

        self.assertIn("@keyframes form-card-enter", css)
        self.assertIn("animation: form-card-enter 320ms ease-out both", css)
        self.assertIn("transition: background 0.2s ease", css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)
        self.assertIn("transition-duration: 1ms !important", css)
        self.assertIn("animation: none", css)

    def test_register_template_uses_rtl_persian_html_attributes(self):
        response = self.client.get(reverse("patients:register"))

        self.assertContains(response, '<html lang="fa" dir="rtl">')

    def test_register_form_uses_persian_placeholders_and_ltr_mobile(self):
        response = self.client.get(reverse("patients:register"))

        self.assertContains(response, 'autocomplete="given-name"')
        self.assertContains(response, 'placeholder="مثلاً علی"')
        self.assertContains(response, 'autocomplete="family-name"')
        self.assertContains(response, 'placeholder="مثلاً رضایی"')
        self.assertContains(response, 'autocomplete="off"')
        self.assertContains(response, 'aria-describedby="national-code-help"')
        self.assertContains(response, 'maxlength="10"')
        self.assertContains(response, 'placeholder="1234567890"')
        self.assertContains(response, 'autocomplete="tel"')
        self.assertContains(response, 'aria-describedby="mobile-help"')
        self.assertContains(response, 'dir="ltr"')
        self.assertContains(response, 'inputmode="numeric"')
        self.assertContains(response, 'maxlength="11"')
        self.assertContains(response, 'placeholder="09123456789"')
        self.assertContains(response, "شماره موبایل باید ۱۱ رقمی و با 09 شروع شود.")

    def test_register_template_styles_messages_as_alert_cards(self):
        response = self.client.get(reverse("patients:register"))

        self.assertContains(response, 'class="message-stack"', count=0)

        response = self.client.post(
            reverse("patients:register"),
            data={
                "first_name": "Ali",
                "last_name": "Ahmadi",
                "national_code": "1234567890",
                "mobile": "09123456789",
            },
            follow=True,
        )

        self.assertContains(response, 'class="message-stack"')
        self.assertContains(response, "message-card message-card--success")
        self.assertContains(response, 'class="message-card__icon"')
        self.assertContains(response, 'class="icon icon--status"')
        self.assertContains(response, 'aria-hidden="true"')
        self.assertNotContains(response, "✓")

    def test_field_errors_render_below_each_field(self):
        response = self.client.post(
            reverse("patients:register"),
            data={
                "first_name": "",
                "last_name": "",
                "national_code": "",
                "mobile": "08123456789",
            },
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
                "national_code": "1234567890",
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
                "national_code": "1234567890",
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
                "national_code": "1234567890",
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
                    "national_code": "1234567890",
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
                    "national_code": "1234567890",
                    "mobile": "09123456789",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Patient.objects.exists())
        self.assertContains(
            response, "در ذخیره‌سازی اطلاعات مشکلی رخ داد. لطفاً دوباره تلاش کنید."
        )


class VisitAnalyticsTests(TestCase):
    def test_get_register_creates_page_view_event(self):
        from .models import VisitEvent

        response = self.client.get(reverse("patients:register"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            VisitEvent.objects.filter(
                event_type=VisitEvent.EVENT_PAGE_VIEW, path="/"
            ).count(),
            1,
        )
        self.assertIn("helssa_vid", response.cookies)

    def test_get_register_alias_creates_form_view_event(self):
        from .models import VisitEvent

        response = self.client.get(reverse("patients:register_patient"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            VisitEvent.objects.filter(
                event_type=VisitEvent.EVENT_FORM_VIEW, path="/register/"
            ).count(),
            1,
        )
        self.assertIn("helssa_vid", response.cookies)

    def test_invalid_post_creates_attempt_and_invalid_events_without_values(self):
        from .models import VisitEvent

        self.client.post(
            reverse("patients:register"),
            data={
                "first_name": "Ali",
                "last_name": "Ahmadi",
                "national_code": "1234567890",
                "mobile": "08123456789",
            },
        )

        self.assertTrue(
            VisitEvent.objects.filter(
                event_type=VisitEvent.EVENT_FORM_SUBMIT_ATTEMPT
            ).exists()
        )
        invalid = VisitEvent.objects.get(
            event_type=VisitEvent.EVENT_FORM_SUBMIT_INVALID
        )
        self.assertEqual(invalid.metadata, {"error_fields": ["mobile"]})
        self.assertNotIn("08123456789", str(invalid.metadata))

    def test_valid_post_creates_attempt_and_success_events(self):
        from .models import VisitEvent

        self.client.post(
            reverse("patients:register"),
            data={
                "first_name": "Ali",
                "last_name": "Ahmadi",
                "national_code": "1234567890",
                "mobile": "09123456789",
            },
        )

        self.assertTrue(
            VisitEvent.objects.filter(
                event_type=VisitEvent.EVENT_FORM_SUBMIT_ATTEMPT
            ).exists()
        )
        success = VisitEvent.objects.get(
            event_type=VisitEvent.EVENT_FORM_SUBMIT_SUCCESS
        )
        self.assertEqual(success.patient.mobile, "09123456789")

    def test_logging_failure_never_crashes_registration(self):
        with patch("patients.views.log_visit_event", side_effect=Exception("boom")):
            response = self.client.post(
                reverse("patients:register"),
                data={
                    "first_name": "Ali",
                    "last_name": "Ahmadi",
                    "national_code": "1234567890",
                    "mobile": "09123456789",
                },
            )

        self.assertRedirects(response, reverse("patients:register"))
        self.assertTrue(Patient.objects.exists())

    def test_valid_post_sets_generated_visitor_cookie_on_redirect(self):
        response = self.client.post(
            reverse("patients:register"),
            data={
                "first_name": "Ali",
                "last_name": "Ahmadi",
                "national_code": "1234567890",
                "mobile": "09123456789",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("helssa_vid", response.cookies)

    def test_summary_counts_known_events(self):
        from .analytics import get_visit_report_summary
        from .models import VisitEvent

        VisitEvent.objects.create(
            visitor_id="00000000-0000-0000-0000-000000000001",
            event_type=VisitEvent.EVENT_FORM_VIEW,
            method="GET",
            path="/",
            status_code=200,
        )
        VisitEvent.objects.create(
            visitor_id="00000000-0000-0000-0000-000000000002",
            event_type=VisitEvent.EVENT_FORM_SUBMIT_ATTEMPT,
            method="POST",
            path="/register/",
            referrer="https://example.com",
        )
        VisitEvent.objects.create(
            visitor_id="00000000-0000-0000-0000-000000000002",
            event_type=VisitEvent.EVENT_FORM_SUBMIT_SUCCESS,
            method="POST",
            path="/register/",
            referrer="https://example.com",
        )

        summary = get_visit_report_summary(VisitEvent.objects.all())

        self.assertEqual(summary["total_events"], 3)
        self.assertEqual(summary["page_views"], 1)
        self.assertEqual(summary["unique_visitors"], 2)
        self.assertEqual(summary["form_views"], 1)
        self.assertEqual(summary["submit_attempts"], 1)
        self.assertEqual(summary["successful_registrations"], 1)
        self.assertEqual(summary["top_paths"][0]["path"], "/register/")
        self.assertEqual(summary["top_referrers"][0]["referrer"], "https://example.com")

    def test_visit_pdf_builder_returns_non_empty_pdf(self):
        from .admin import build_visit_events_pdf
        from .analytics import get_visit_report_summary
        from .models import VisitEvent
        from django.utils import timezone

        register_test_pdf_fonts()
        event = VisitEvent.objects.create(
            visitor_id="00000000-0000-0000-0000-000000000001",
            event_type=VisitEvent.EVENT_FORM_VIEW,
            method="GET",
            path="/",
            status_code=200,
        )
        queryset = VisitEvent.objects.all()
        pdf = build_visit_events_pdf(
            queryset,
            get_visit_report_summary(queryset),
            event.created_at,
            timezone.now(),
        )

        self.assertGreater(len(pdf.getvalue()), 100)
        self.assertTrue(pdf.getvalue().startswith(b"%PDF"))

    def test_admin_report_does_not_expose_raw_editable_details(self):
        from .models import VisitEvent, VisitReport
        from .admin import VisitReportAdmin

        model_admin = VisitReportAdmin(VisitReport, admin.site)
        request = Mock(user=Mock())

        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_change_permission(request, VisitEvent()))
        self.assertFalse(model_admin.has_delete_permission(request, VisitEvent()))

    @patch("patients.admin.timezone.now")
    def test_visit_report_default_range_is_last_three_hours(self, mocked_now):
        from .admin import _parse_report_range
        from django.test import RequestFactory
        from django.utils import timezone

        mocked_now.return_value = datetime(
            2026, 3, 21, 8, 30, tzinfo=datetime_timezone.utc
        )
        request = RequestFactory().get("/admin/patients/visitreport/")
        request.user = Mock()

        start_dt, end_dt, start_value, end_value, selected_range = _parse_report_range(
            request
        )

        self.assertEqual(selected_range, "custom")
        self.assertEqual(end_dt, mocked_now.return_value)
        self.assertEqual(
            start_dt, mocked_now.return_value - timezone.timedelta(hours=3)
        )
        self.assertEqual(start_value, "۱۴۰۵/۰۱/۰۱ ۰۹:۰۰")
        self.assertEqual(end_value, "۱۴۰۵/۰۱/۰۱ ۱۲:۰۰")

    @patch("patients.admin.timezone.now")
    def test_visit_report_today_shortcut_uses_tehran_day(self, mocked_now):
        from .admin import _parse_report_range
        from django.test import RequestFactory

        mocked_now.return_value = datetime(
            2026, 3, 21, 8, 30, tzinfo=datetime_timezone.utc
        )
        request = RequestFactory().get(
            "/admin/patients/visitreport/", {"range": "today"}
        )
        request.user = Mock()

        start_dt, end_dt, _start_value, _end_value, selected_range = (
            _parse_report_range(request)
        )

        self.assertEqual(selected_range, "today")
        self.assertEqual(format_tehran_jalali(start_dt), "۱۴۰۵/۰۱/۰۱ ۰۰:۰۰:۰۰")
        self.assertEqual(end_dt, mocked_now.return_value)

    def test_visit_report_summary_daily_counts_are_jalali_tehran_dates(self):
        from .analytics import get_visit_report_summary
        from .models import VisitEvent

        event = VisitEvent.objects.create(
            visitor_id="00000000-0000-0000-0000-000000000001",
            event_type=VisitEvent.EVENT_FORM_VIEW,
            method="GET",
            path="/",
            status_code=200,
        )
        VisitEvent.objects.filter(pk=event.pk).update(
            created_at=datetime(2026, 3, 20, 20, 45, tzinfo=datetime_timezone.utc)
        )

        summary = get_visit_report_summary(VisitEvent.objects.all())

        self.assertEqual(list(summary["daily_counts"].keys()), ["۱۴۰۵/۰۱/۰۱"])

    def test_visit_report_template_contains_shortcuts_and_print_button(self):
        user = get_user_model().objects.create_superuser(
            "admin", "admin@example.com", "pass"
        )
        self.client.force_login(user)

        response = self.client.get(reverse("admin:patients_visitreport_changelist"))

        self.assertContains(response, "امروز")
        self.assertContains(response, "دیروز")
        self.assertContains(response, "یک هفته قبل")
        self.assertContains(response, "یک ماه قبل")
        self.assertContains(response, "گزارش کل")
        self.assertContains(response, "window.print()")
        self.assertContains(response, "بازه گزارش:")
        self.assertContains(response, 'type="text" name="start_date"')
        self.assertContains(response, "فرمت نمونه: ۱۴۰۵/۰۴/۰۵ ۰۹:۰۰")
        self.assertNotContains(response, 'type="datetime-local"')

    def test_visit_report_today_shortcut_renders_without_admin_lookup_errors(self):
        user = get_user_model().objects.create_superuser(
            "range-admin", "range@example.com", "pass"
        )
        self.client.force_login(user)

        response = self.client.get(
            reverse("admin:patients_visitreport_changelist"), {"range": "today"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="?range=today"')
        self.assertContains(response, 'href="export-pdf/?range=today"')
