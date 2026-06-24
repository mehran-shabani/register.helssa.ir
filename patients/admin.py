import ast
import logging
from datetime import datetime, timezone as datetime_timezone
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from bidi.algorithm import get_display

from django import forms
from django.core.exceptions import ImproperlyConfigured
from django.http import FileResponse
from django.conf import settings
from django.contrib import admin, messages
from django.db.models import Exists, OuterRef
from django.utils.html import format_html, format_html_join
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from arabic_reshaper import reshape

from .datetime import format_tehran_jalali
from .models import SMSMessageLog, Patient
from .sms import build_patient_name_token, send_done_sms
from .sms_logs import create_sms_message_log

logger = logging.getLogger(__name__)


PDF_FONT_NAME = "DejaVuSans"
PDF_FONT_BOLD_NAME = "DejaVuSans-Bold"
DEFAULT_PDF_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
DEFAULT_PDF_FONT_BOLD_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
PDF_REPORT_MAX_PATIENTS = getattr(settings, "PATIENTS_PDF_REPORT_MAX_PATIENTS", 500)


def _pdf_font_path(setting_name: str, default_path: str) -> str:
    return getattr(settings, setting_name, default_path)


def _register_pdf_fonts() -> None:
    registered_fonts = set(pdfmetrics.getRegisteredFontNames())
    font_paths = (
        (PDF_FONT_NAME, _pdf_font_path("PDF_FONT_PATH", DEFAULT_PDF_FONT_PATH)),
        (
            PDF_FONT_BOLD_NAME,
            _pdf_font_path("PDF_FONT_BOLD_PATH", DEFAULT_PDF_FONT_BOLD_PATH),
        ),
    )

    for font_name, font_path in font_paths:
        if font_name in registered_fonts:
            continue
        if not Path(font_path).is_file():
            raise ImproperlyConfigured(
                f"PDF font file for {font_name} was not found at {font_path}. "
                f"Install the DejaVu font package or configure {font_name} "
                "with PDF_FONT_PATH/PDF_FONT_BOLD_PATH in Django settings."
            )
        pdfmetrics.registerFont(TTFont(font_name, font_path))


def _rtl_text(value) -> str:
    if value in (None, ""):
        value = "-"
    return escape(get_display(reshape(str(value))))


def build_patients_pdf(patients):
    _register_pdf_fonts()
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=1.2 * cm,
        leftMargin=1.2 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
        title="گزارش بیماران",
    )
    title_style = ParagraphStyle(
        "PersianTitle",
        fontName=PDF_FONT_BOLD_NAME,
        fontSize=16,
        alignment=TA_CENTER,
        leading=24,
        spaceAfter=12,
    )
    cell_style = ParagraphStyle(
        "PersianCell",
        fontName=PDF_FONT_NAME,
        fontSize=10,
        alignment=TA_RIGHT,
        leading=16,
    )
    header_style = ParagraphStyle(
        "PersianHeader",
        parent=cell_style,
        fontName=PDF_FONT_BOLD_NAME,
    )

    rows = [
        [
            Paragraph(_rtl_text("زمان ثبت"), header_style),
            Paragraph(_rtl_text("کد ملی"), header_style),
            Paragraph(_rtl_text("موبایل"), header_style),
            Paragraph(_rtl_text("نام خانوادگی"), header_style),
            Paragraph(_rtl_text("نام"), header_style),
            Paragraph(_rtl_text("ردیف"), header_style),
        ]
    ]
    for index, patient in enumerate(patients, start=1):
        rows.append(
            [
                Paragraph(
                    _rtl_text(format_tehran_jalali(patient.created_at)), cell_style
                ),
                Paragraph(_rtl_text(patient.national_code), cell_style),
                Paragraph(_rtl_text(patient.mobile), cell_style),
                Paragraph(_rtl_text(patient.last_name), cell_style),
                Paragraph(_rtl_text(patient.first_name), cell_style),
                Paragraph(_rtl_text(index), cell_style),
            ]
        )

    table = Table(
        rows,
        repeatRows=1,
        colWidths=[4.2 * cm, 3.2 * cm, 3.2 * cm, 4 * cm, 4 * cm, 1.6 * cm],
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAF2F8")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1F2D3D")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#BFC9D1")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.white, colors.HexColor("#F8FAFC")],
                ),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )

    story = [
        Paragraph(_rtl_text("گزارش بیماران انتخاب‌شده"), title_style),
        Spacer(1, 0.2 * cm),
        table,
    ]
    document.build(story)
    buffer.seek(0)
    return buffer


class PatientAdminForm(forms.ModelForm):
    class Meta:
        model = Patient
        fields = "__all__"
        widgets = {
            "national_code": forms.TextInput(
                attrs={
                    "class": "vTextField",
                    "data-copy-national-code": "true",
                    "dir": "ltr",
                    "inputmode": "numeric",
                    "maxlength": "10",
                }
            )
        }


SMS_RESPONSE_LABELS = {
    "messageid": "شناسه پیامک",
    "message": "متن پیام",
    "status": "کد وضعیت",
    "statustext": "وضعیت سرویس",
    "sender": "فرستنده",
    "receptor": "گیرنده",
    "date": "زمان سرویس",
    "cost": "هزینه",
}


def _format_sms_response_value(key, value) -> object:
    if key != "date":
        return value

    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return value

    return format_tehran_jalali(
        datetime.fromtimestamp(timestamp, tz=datetime_timezone.utc)
    )


def _parse_sms_response(response) -> object:
    if not response:
        return []

    try:
        parsed_response = ast.literal_eval(response)
    except (ValueError, SyntaxError):
        return response

    if isinstance(parsed_response, dict):
        return [parsed_response]

    if isinstance(parsed_response, list):
        return [item for item in parsed_response if isinstance(item, dict)]

    return response


def format_sms_response(response):
    parsed_response = _parse_sms_response(response)
    if not parsed_response:
        return "-"

    if isinstance(parsed_response, str):
        return format_html(
            '<div style="white-space: pre-wrap; direction: rtl; text-align: right;">{}</div>',
            parsed_response,
        )

    cards = []
    for item in parsed_response:
        rows = []
        for key, label in SMS_RESPONSE_LABELS.items():
            value = item.get(key)
            if value in (None, ""):
                continue
            value = _format_sms_response_value(key, value)
            rows.append(
                format_html(
                    '<div style="display: grid; grid-template-columns: minmax(96px, 128px) minmax(0, 1fr); gap: 10px; padding: 9px 0; border-bottom: 1px solid rgba(128,128,128,.18);">'
                    '<strong style="color: #8aa0b2; font-weight: 700;">{}</strong>'
                    '<span style="white-space: pre-wrap; overflow-wrap: break-word; word-break: normal; direction: rtl; text-align: right;">{}</span>'
                    "</div>",
                    label,
                    value,
                )
            )

        cards.append(
            format_html(
                '<div style="box-sizing: border-box; width: min(100%, 720px); min-width: min(100%, 360px); padding: 10px 14px; border: 1px solid rgba(128,128,128,.24); border-radius: 8px; line-height: 1.9; direction: rtl; text-align: right;">{}</div>',
                format_html_join("", "{}", ((row,) for row in rows)),
            )
        )

    return format_html_join("", "{}", ((card,) for card in cards))


class SMSMessageLogInline(admin.TabularInline):
    model = SMSMessageLog
    extra = 0
    can_delete = False
    fields = (
        "created_at_jalali",
        "template",
        "token",
        "status",
        "formatted_response",
        "formatted_error",
    )
    readonly_fields = fields
    ordering = ("-created_at",)

    @admin.display(description="زمان ارسال", ordering="created_at")
    def created_at_jalali(self, obj):
        return format_tehran_jalali(obj.created_at)

    @admin.display(description="پاسخ سرویس")
    def formatted_response(self, obj):
        return format_sms_response(obj.response)

    @admin.display(description="خطا")
    def formatted_error(self, obj):
        if not obj.error:
            return "-"
        return format_html(
            '<div style="white-space: pre-wrap; overflow-wrap: break-word; word-break: normal; direction: rtl; text-align: right;">{}</div>',
            obj.error,
        )

    def has_add_permission(self, _request, _obj=None) -> bool:
        return False

    def has_delete_permission(self, _request, _obj=None) -> bool:
        return False


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    form = PatientAdminForm
    list_display = (
        "first_name",
        "last_name",
        "national_code",
        "sms_sent_indicator",
        "created_at_jalali",
    )
    search_fields = ("mobile", "national_code", "first_name", "last_name")
    ordering = ("-created_at",)
    actions = ("download_patients_pdf_report", "send_done_sms_to_patients")
    inlines = (SMSMessageLogInline,)

    class Media:
        css = {"all": ("patients/admin/copy_national_code.css",)}
        js = ("patients/admin/copy_national_code.js",)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        successful_done_sms_logs = SMSMessageLog.objects.filter(
            patient=OuterRef("pk"),
            status=SMSMessageLog.STATUS_SUCCESS,
            template=getattr(settings, "KAVENEGAR_DONE_TEMPLATE", ""),
        )
        return queryset.annotate(
            has_successful_done_sms=Exists(successful_done_sms_logs)
        )

    @admin.display(
        description="پیامک انجام شد",
        boolean=True,
        ordering="has_successful_done_sms",
    )
    def sms_sent_indicator(self, obj):
        return getattr(obj, "has_successful_done_sms", False)

    @admin.display(description="زمان ثبت", ordering="created_at")
    def created_at_jalali(self, obj):
        return format_tehran_jalali(obj.created_at)

    @admin.action(description="دانلود گزارش PDF بیماران انتخاب‌شده")
    def download_patients_pdf_report(self, request, queryset):
        selected_count = queryset.count()
        if selected_count > PDF_REPORT_MAX_PATIENTS:
            self.message_user(
                request,
                f"حداکثر {PDF_REPORT_MAX_PATIENTS} بیمار را برای گزارش PDF انتخاب کنید.",
                messages.ERROR,
            )
            return None

        patients = list(
            queryset.order_by("last_name", "first_name", "id").only(
                "first_name",
                "last_name",
                "mobile",
                "national_code",
                "created_at",
            )
        )
        logger.info(
            "Admin user %s exported a patients PDF report with %s records.",
            getattr(request.user, "pk", None),
            selected_count,
        )
        pdf_buffer = build_patients_pdf(patients)
        return FileResponse(
            pdf_buffer,
            as_attachment=True,
            filename="selected-patients-report.pdf",
            content_type="application/pdf",
        )

    @admin.action(description="ارسال پیامک انجام شد برای بیماران انتخاب‌شده")
    def send_done_sms_to_patients(self, request, queryset):
        api_key = getattr(settings, "KAVENEGAR_API_KEY", "")
        template = getattr(settings, "KAVENEGAR_DONE_TEMPLATE", "")
        if not api_key or not template:
            self.message_user(
                request,
                "تنظیمات سامانه پیامک (KAVENEGAR_API_KEY یا "
                "KAVENEGAR_DONE_TEMPLATE) پیکربندی نشده است.",
                messages.ERROR,
            )
            return

        sent_count = 0
        failed_count = 0

        for patient in queryset:
            token = build_patient_name_token(patient)

            try:
                response = send_done_sms(patient.mobile, token)
            except Exception as exc:
                failed_count += 1
                create_sms_message_log(patient, template, token, error=exc)
                logger.exception(
                    "Failed to send Kavenegar done SMS to patient %s.", patient.pk
                )
            else:
                sent_count += 1
                create_sms_message_log(patient, template, token, response=response)

        if sent_count:
            self.message_user(
                request,
                f"پیامک انجام شد برای {sent_count} بیمار ارسال شد.",
                messages.SUCCESS,
            )

        if failed_count:
            self.message_user(
                request,
                f"ارسال پیامک انجام شد برای {failed_count} بیمار ناموفق بود.",
                messages.ERROR,
            )


@admin.register(SMSMessageLog)
class SMSMessageLogAdmin(admin.ModelAdmin):
    list_display = ("patient", "mobile", "template", "status", "created_at_jalali")
    list_filter = ("status", "template", "created_at")
    search_fields = (
        "patient__first_name",
        "patient__last_name",
        "mobile",
        "template",
        "token",
    )
    readonly_fields = (
        "patient",
        "mobile",
        "template",
        "token",
        "status",
        "formatted_response",
        "formatted_error",
        "created_at_jalali",
    )
    fields = readonly_fields
    ordering = ("-created_at",)

    @admin.display(description="زمان ارسال", ordering="created_at")
    def created_at_jalali(self, obj):
        return format_tehran_jalali(obj.created_at)

    @admin.display(description="پاسخ سرویس")
    def formatted_response(self, obj):
        return format_sms_response(obj.response)

    @admin.display(description="خطا")
    def formatted_error(self, obj):
        if not obj.error:
            return "-"
        return format_html(
            '<div style="white-space: pre-wrap; overflow-wrap: break-word; word-break: normal; direction: rtl; text-align: right;">{}</div>',
            obj.error,
        )

    def has_add_permission(self, _request) -> bool:
        return False

    def has_delete_permission(self, _request, _obj=None) -> bool:
        return False
