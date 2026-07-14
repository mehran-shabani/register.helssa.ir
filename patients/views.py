import json
from io import BytesIO
from pathlib import Path

import qrcode
import qrcode.image.svg
from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db import DatabaseError, IntegrityError, transaction
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_safe

from .forms import (
    DUPLICATE_MOBILE_ERROR,
    DUPLICATE_NATIONAL_CODE_ERROR,
    PatientRegistrationForm,
)
from .analytics import log_visit_event
from .models import Patient, VisitEvent

SUCCESS_MESSAGE = (
    "ثبت‌نام شما با موفقیت انجام شد. درمانگاه برای تکمیل فرآیند با شما تماس می‌گیرد."
)
FORM_ERROR_MESSAGE = "ثبت‌نام انجام نشد. لطفاً خطاهای فرم را اصلاح کنید."
SAVE_ERROR = "در ذخیره‌سازی اطلاعات مشکلی رخ داد. لطفاً دوباره تلاش کنید."
SITE_NAME = "سامانه ثبت نام پزشک خانواده دکتر حسین شبانی"
CANONICAL_URL = "https://register.helssa.ir/"
SHARE_TITLE = "ثبت‌نام پزشک خانواده صغاد | دکتر حسین شبانی | درمانگاه ولیعصر"
SHARE_DESCRIPTION = (
    "ثبت‌نام اینترنتی پزشک خانواده دکتر حسین شبانی در درمانگاه ولیعصر صغاد؛ "
    "تعرفه دولتی، پیگیری سلامت خانواده و پاسخگویی آنلاین برای ثبت‌نام‌شدگان."
)
SHARE_IMAGE_PATH = "patients/images/share-logo.png"
SITE_LOGO_PATH = "patients/images/site-logo.png"
COMMUNITY_BASE_COUNT = 1008
APK_DOWNLOAD_FILENAME = "helssa.apk"
APK_DOWNLOAD_DIR = settings.BASE_DIR / "down"
APK_DOWNLOAD_PATH = APK_DOWNLOAD_DIR / APK_DOWNLOAD_FILENAME
ENGAGEMENT_EVENT_TYPES = {
    VisitEvent.EVENT_HERO_CTA_CLICK,
    VisitEvent.EVENT_STICKY_CTA_CLICK,
    VisitEvent.EVENT_SECTION_VIEW,
    VisitEvent.EVENT_FORM_START,
    VisitEvent.EVENT_FIELD_COMPLETE,
    VisitEvent.EVENT_SCROLL_DEPTH,
}
ENGAGEMENT_METADATA_KEYS = {"section", "depth", "field_name", "cta_location"}


def _log_analytics(request, event_type, **kwargs):
    try:
        return log_visit_event(request, event_type, **kwargs)
    except Exception:
        return None


def _static_source_exists(path):
    """Return whether a project-level static asset has been provided."""

    return (settings.BASE_DIR / "patients" / "static" / path).exists()


def _absolute_static_url(request, path):
    """Build an absolute URL for a static asset that may use a relative STATIC_URL."""

    static_url = static(path)
    if not static_url.startswith("/"):
        static_url = f"/{static_url}"

    return request.build_absolute_uri(static_url)


def get_apk_download_url(request):
    """Build the public APK download URL used by links and QR codes."""

    return request.build_absolute_uri(reverse("patients:download_helssa_apk"))


def get_apk_download_path():
    """Return the configured APK path, falling back to the newest APK in /down."""

    configured_path = Path(getattr(settings, "APK_DOWNLOAD_PATH", APK_DOWNLOAD_PATH))
    if configured_path.exists() and configured_path.is_file():
        return configured_path

    download_dir = Path(getattr(settings, "APK_DOWNLOAD_DIR", APK_DOWNLOAD_DIR))
    if not download_dir.exists() or not download_dir.is_dir():
        return configured_path

    apk_files = [path for path in download_dir.glob("*.apk") if path.is_file()]
    if not apk_files:
        return configured_path

    return max(apk_files, key=lambda path: (path.stat().st_mtime, path.name))


def _serve_apk_file(request, *, log_download=False):
    apk_path = get_apk_download_path()
    download_filename = apk_path.name

    if not apk_path.exists() or not apk_path.is_file():
        if log_download:
            _log_analytics(
                request,
                VisitEvent.EVENT_APK_DOWNLOAD,
                metadata={"filename": download_filename, "result": "missing"},
                status_code=404,
            )
        raise Http404("فایل اپلیکیشن هنوز روی سرور قرار نگرفته است.")

    response = FileResponse(
        apk_path.open("rb"),
        as_attachment=True,
        filename=download_filename,
        content_type="application/vnd.android.package-archive",
    )
    if log_download:
        _log_analytics(
            request,
            VisitEvent.EVENT_APK_DOWNLOAD,
            response=response,
            metadata={"filename": download_filename, "result": "download"},
        )
    return response


@require_safe
def download_helssa_apk(request):
    """Serve the Helssa Android APK and log successful download requests."""

    return _serve_apk_file(request, log_download=True)


@staff_member_required
@require_safe
def admin_download_helssa_apk(request):
    """Serve the APK from an authenticated admin-only URL."""

    return _serve_apk_file(request)


@require_safe
def helssa_apk_qr_svg(request):
    """Return an SVG QR code that points to the APK download URL."""

    image = qrcode.make(
        get_apk_download_url(request),
        image_factory=qrcode.image.svg.SvgPathImage,
        box_size=12,
        border=2,
    )
    output = BytesIO()
    image.save(output)
    return HttpResponse(
        output.getvalue(), content_type="image/svg+xml; charset=utf-8"
    )


def robots_txt(request):
    """Serve crawl instructions for search engines."""

    sitemap_url = f"{CANONICAL_URL}sitemap.xml"
    return HttpResponse(
        f"User-agent: *\nAllow: /\nSitemap: {sitemap_url}\n",
        content_type="text/plain; charset=utf-8",
    )


def sitemap_xml(request):
    """Expose the canonical public landing page in an XML sitemap."""

    return HttpResponse(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{CANONICAL_URL}</loc>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>
</urlset>
""",
        content_type="application/xml; charset=utf-8",
    )


def _safe_engagement_metadata(value):
    if not isinstance(value, dict):
        return {}

    metadata = {}
    for key in ENGAGEMENT_METADATA_KEYS:
        raw_value = value.get(key)
        if raw_value is None:
            continue
        metadata[key] = str(raw_value)[:80]
    return metadata


@require_POST
def analytics_event(request):
    """Log client-side engagement events without storing form values."""

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"ok": False, "error": "invalid_json"}, status=400)

    event_type = payload.get("event_type")
    if event_type not in ENGAGEMENT_EVENT_TYPES:
        return JsonResponse({"ok": False, "error": "invalid_event"}, status=400)

    event = _log_analytics(
        request,
        event_type,
        metadata=_safe_engagement_metadata(payload.get("metadata", {})),
    )
    return JsonResponse({"ok": True, "logged": event is not None})


def register_patient(request):
    """Display and process the patient registration form."""

    if request.method == "POST":
        _log_analytics(request, VisitEvent.EVENT_FORM_SUBMIT_ATTEMPT)
        form = PatientRegistrationForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    patient = form.save()
            except IntegrityError:
                _log_analytics(
                    request,
                    VisitEvent.EVENT_FORM_SUBMIT_ERROR,
                    metadata={"error_type": "IntegrityError"},
                )
                messages.error(request, FORM_ERROR_MESSAGE)
                form.add_error("mobile", DUPLICATE_MOBILE_ERROR)
                form.add_error("national_code", DUPLICATE_NATIONAL_CODE_ERROR)
            except DatabaseError:
                _log_analytics(
                    request,
                    VisitEvent.EVENT_FORM_SUBMIT_ERROR,
                    metadata={"error_type": "DatabaseError"},
                )
                messages.error(request, SAVE_ERROR)
                form.add_error(None, SAVE_ERROR)
            else:
                _log_analytics(
                    request, VisitEvent.EVENT_FORM_SUBMIT_SUCCESS, patient=patient
                )
                messages.success(request, SUCCESS_MESSAGE)
                return redirect("patients:register")
        else:
            _log_analytics(
                request,
                VisitEvent.EVENT_FORM_SUBMIT_INVALID,
                metadata={"error_fields": list(form.errors.keys())},
            )
            messages.error(request, FORM_ERROR_MESSAGE)
    else:
        form = PatientRegistrationForm()

    share_meta = {
        "site_name": SITE_NAME,
        "title": SHARE_TITLE,
        "description": SHARE_DESCRIPTION,
        "url": CANONICAL_URL,
        "image": (
            _absolute_static_url(request, SHARE_IMAGE_PATH)
            if _static_source_exists(SHARE_IMAGE_PATH)
            else ""
        ),
        "image_width": "1200",
        "image_height": "630",
    }
    site_logo = None
    if _static_source_exists(SITE_LOGO_PATH):
        site_logo = {
            "url": _absolute_static_url(request, SITE_LOGO_PATH),
            "alt": f"لوگوی {SITE_NAME}",
        }

    structured_data = {
        "@context": "https://schema.org",
        "@type": "MedicalClinic",
        "name": "درمانگاه ولیعصر صغاد - پزشک خانواده دکتر حسین شبانی",
        "url": CANONICAL_URL,
        "areaServed": "صغاد، آباده، فارس",
        "medicalSpecialty": "PrimaryCare",
        "description": SHARE_DESCRIPTION,
        "physician": {
            "@type": "Physician",
            "name": "دکتر حسین شبانی",
        },
        "employee": {
            "@type": "Person",
            "name": "دکتر حسین شبانی",
        },
        "inLanguage": "fa-IR",
    }

    now = timezone.localtime()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timezone.timedelta(days=1)
    registered_count = Patient.objects.count()
    stats = {
        "community_count": registered_count + COMMUNITY_BASE_COUNT,
        "base_count": COMMUNITY_BASE_COUNT,
        "today_count": Patient.objects.filter(
            created_at__gte=today_start,
            created_at__lt=today_end,
        ).count(),
    }

    return render(
        request,
        "patients/register.html",
        {
            "form": form,
            "share_meta": share_meta,
            "site_logo": site_logo,
            "stats": stats,
            "apk_download": {
                "url": get_apk_download_url(request),
                "filename": APK_DOWNLOAD_FILENAME,
                "qr_url": request.build_absolute_uri(
                    reverse("patients:helssa_apk_qr_svg")
                ),
            },
            "structured_data_json": json.dumps(
                structured_data, ensure_ascii=False
            ).replace("</", "<\\/"),
        },
    )


register = register_patient
