import json
import tempfile
import threading
import zipfile
from io import BytesIO
from pathlib import Path

import qrcode
import qrcode.image.svg
from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db import DatabaseError, IntegrityError, close_old_connections, transaction
from django.http import (
    FileResponse,
    Http404,
    HttpResponse,
    HttpResponseRedirect,
    JsonResponse,
)
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
from .models import APKUploadJob, Patient, VisitEvent

SUCCESS_MESSAGE = (
    "ثبت‌نام شما با موفقیت انجام شد. درمانگاه برای تکمیل فرآیند با شما تماس می‌گیرد."
)
FORM_ERROR_MESSAGE = "ثبت‌نام انجام نشد. لطفاً خطاهای فرم را اصلاح کنید."
SAVE_ERROR = "در ذخیره‌سازی اطلاعات مشکلی رخ داد. لطفاً دوباره تلاش کنید."
SITE_NAME = "درمانگاه ولیعصر صغاد | پزشک خانواده دکتر حسین شبانی"
CANONICAL_URL = "https://register.helssa.ir/"
ONLINE_VISIT_URL = "https://order.helssa.ir"
SOCIAL_PROFILE_URLS = ["https://ble.ir/helssaaa", "https://eitaa.ir/helssaaa"]
CONTACT_TELEPHONE = "+989961733668"
SHARE_TITLE = "ثبت‌نام پزشک خانواده و ویزیت آنلاین | درمانگاه ولیعصر صغاد"
SHARE_DESCRIPTION = (
    "در درمانگاه ولیعصر صغاد، ثبت‌نام پزشک خانواده دکتر حسین شبانی را آنلاین انجام دهید "
    "و برای پیگیری سلامت خانواده از امکان ویزیت آنلاین استفاده کنید."
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
    VisitEvent.EVENT_ONLINE_VISIT_CTA_CLICK,
    VisitEvent.EVENT_ONLINE_VISIT_CARD_CTA_CLICK,
}
ENGAGEMENT_METADATA_KEYS = {"section", "depth", "field_name", "cta_location"}


def _to_persian_digits(value):
    return str(value).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


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


def get_apk_download_url(request=None):
    """Return the relative public APK download URL used by page links."""

    return reverse("patients:download_helssa_apk")


def get_absolute_apk_download_url(request):
    """Build an absolute APK download URL for QR code payloads."""

    return request.build_absolute_uri(get_apk_download_url())


def get_configured_apk_download_path():
    """Return the exact APK path used for admin uploads and primary downloads."""

    return Path(getattr(settings, "APK_DOWNLOAD_PATH", APK_DOWNLOAD_PATH))


def get_apk_download_path():
    """Return the configured APK path, falling back to the newest APK in /down."""

    configured_path = get_configured_apk_download_path()
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


def _apk_upload_status_payload(job):
    return {
        "id": job.pk,
        "status": job.status,
        "status_label": job.get_status_display(),
        "original_filename": job.original_filename,
        "error_message": job.error_message,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


def _finalize_apk_upload_job(job_id):
    try:
        job = APKUploadJob.objects.get(pk=job_id)
        job.status = APKUploadJob.STATUS_PREPARING
        job.error_message = ""
        job.save(update_fields=["status", "error_message"])

        temp_path = Path(job.stored_path)
        if (
            not temp_path.exists()
            or not temp_path.is_file()
            or temp_path.stat().st_size == 0
        ):
            raise ValueError("فایل آپلودشده ناقص است یا روی سرور پیدا نشد.")
        if temp_path.suffix.lower() != ".apk":
            raise ValueError("فقط فایل با پسوند APK قابل آپلود است.")

        _validate_apk_file(temp_path)

        apk_path = get_configured_apk_download_path()
        apk_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.replace(apk_path)

        job.status = APKUploadJob.STATUS_COMPLETED
        job.stored_path = str(apk_path)
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "stored_path", "finished_at"])
    except Exception as exc:
        try:
            job = APKUploadJob.objects.get(pk=job_id)
            if job.stored_path:
                temp_path = Path(job.stored_path)
                if temp_path.exists() and temp_path.is_file():
                    temp_path.unlink()
        except Exception:
            pass
        APKUploadJob.objects.filter(pk=job_id).update(
            status=APKUploadJob.STATUS_FAILED,
            error_message=str(exc),
            finished_at=timezone.now(),
        )


def _validate_apk_file(path):
    """Validate that the temporary upload has the basic ZIP/APK structure."""

    invalid_message = "فایل انتخاب‌شده APK معتبر نیست."
    if not zipfile.is_zipfile(path):
        raise ValueError(invalid_message)

    try:
        with zipfile.ZipFile(path) as apk_zip:
            names = set(apk_zip.namelist())
            if "AndroidManifest.xml" not in names:
                raise ValueError(invalid_message)
    except zipfile.BadZipFile as exc:
        raise ValueError(invalid_message) from exc


def _start_apk_upload_finalizer(job_id):
    if getattr(settings, "APK_UPLOAD_FINALIZE_SYNCHRONOUS", False):
        _finalize_apk_upload_job(job_id)
        return

    def thread_target():
        try:
            _finalize_apk_upload_job(job_id)
        finally:
            close_old_connections()

    thread = threading.Thread(target=thread_target, daemon=True)
    thread.start()


def _save_uploaded_apk_to_temp(uploaded_file):
    download_dir = Path(getattr(settings, "APK_DOWNLOAD_DIR", APK_DOWNLOAD_DIR))
    temp_dir = download_dir / "tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    destination = None
    try:
        destination = tempfile.NamedTemporaryFile(
            mode="wb", suffix=".apk", prefix="apk-upload-", dir=temp_dir, delete=False
        )
        for chunk in uploaded_file.chunks():
            destination.write(chunk)
        destination.close()
        return Path(destination.name)
    except Exception:
        if destination is not None:
            destination.close()
            try:
                Path(destination.name).unlink(missing_ok=True)
            except Exception:
                pass
        raise


@staff_member_required
@require_POST
def admin_upload_helssa_apk(request):
    """Create an APK upload job, store the file temporarily, then finalize it."""

    is_ajax_upload = request.headers.get("x-requested-with") == "XMLHttpRequest"

    uploaded_file = request.FILES.get("apk_file")
    if not uploaded_file:
        error_message = "لطفاً یک فایل APK برای آپلود انتخاب کنید."
        if is_ajax_upload:
            return JsonResponse({"ok": False, "message": error_message}, status=400)
        messages.error(request, error_message)
        return HttpResponseRedirect(reverse("admin:index"))

    if not uploaded_file.name.lower().endswith(".apk"):
        error_message = "فقط فایل با پسوند APK قابل آپلود است."
        if is_ajax_upload:
            return JsonResponse({"ok": False, "message": error_message}, status=400)
        messages.error(request, error_message)
        return HttpResponseRedirect(reverse("admin:index"))

    job = APKUploadJob.objects.create(
        status=APKUploadJob.STATUS_UPLOADING,
        original_filename=Path(uploaded_file.name).name,
        created_by=request.user if request.user.is_authenticated else None,
    )
    try:
        temp_path = _save_uploaded_apk_to_temp(uploaded_file)
    except Exception as exc:
        job.status = APKUploadJob.STATUS_FAILED
        job.error_message = f"خطا در ذخیره فایل موقت: {exc}"
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error_message", "finished_at"])
        error_message = "ذخیره‌سازی فایل موقت با خطا مواجه شد."
        if is_ajax_upload:
            return JsonResponse({"ok": False, "message": error_message}, status=500)
        messages.error(request, error_message)
        return HttpResponseRedirect(reverse("admin:index"))

    job.status = APKUploadJob.STATUS_QUEUED
    job.stored_path = str(temp_path)
    job.save(update_fields=["status", "stored_path"])
    finalize_synchronously = getattr(settings, "APK_UPLOAD_FINALIZE_SYNCHRONOUS", True)
    if finalize_synchronously:
        _start_apk_upload_finalizer(job.pk)
        job.refresh_from_db(
            fields=["status", "error_message", "stored_path", "finished_at"]
        )
        if job.status == APKUploadJob.STATUS_FAILED:
            error_message = job.error_message or "فایل انتخاب‌شده APK معتبر نیست."
            if is_ajax_upload:
                return JsonResponse({"ok": False, "message": error_message}, status=400)
            messages.error(request, error_message)
            return HttpResponseRedirect(reverse("admin:index"))
    else:
        transaction.on_commit(lambda: _start_apk_upload_finalizer(job.pk))

    success_message = (
        "فایل APK با موفقیت آپلود و جایگزین شد."
        if finalize_synchronously
        else "فایل APK دریافت شد و در صف آماده‌سازی قرار گرفت."
    )
    if is_ajax_upload:
        return JsonResponse(
            {
                "ok": True,
                "message": success_message,
                "job": _apk_upload_status_payload(job),
                "status_url": reverse("admin_apk_upload_status", args=[job.pk]),
                "redirect_url": reverse("admin:index"),
            }
        )

    messages.success(request, success_message)
    return HttpResponseRedirect(reverse("admin:index"))


@staff_member_required
@require_GET
def admin_apk_upload_status(request, job_id):
    try:
        job = APKUploadJob.objects.get(pk=job_id)
    except APKUploadJob.DoesNotExist:
        return JsonResponse(
            {"ok": False, "message": "عملیات آپلود پیدا نشد."}, status=404
        )

    return JsonResponse({"ok": True, "job": _apk_upload_status_payload(job)})


@require_safe
def helssa_apk_qr_svg(request):
    """Return an SVG QR code that points to the APK download URL."""

    image = qrcode.make(
        get_absolute_apk_download_url(request),
        image_factory=qrcode.image.svg.SvgPathImage,
        box_size=12,
        border=2,
    )
    output = BytesIO()
    image.save(output)
    return HttpResponse(output.getvalue(), content_type="image/svg+xml; charset=utf-8")


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
        "telephone": CONTACT_TELEPHONE,
        "areaServed": "صغاد، آباده، فارس",
        "medicalSpecialty": "PrimaryCare",
        "description": SHARE_DESCRIPTION,
        "contactPoint": {
            "@type": "ContactPoint",
            "telephone": CONTACT_TELEPHONE,
            "contactType": "customer service",
            "availableLanguage": "fa-IR",
        },
        "sameAs": SOCIAL_PROFILE_URLS,
        "potentialAction": {
            "@type": "ReserveAction",
            "name": "ویزیت آنلاین",
            "target": {
                "@type": "EntryPoint",
                "urlTemplate": ONLINE_VISIT_URL,
                "inLanguage": "fa-IR",
                "actionPlatform": [
                    "https://schema.org/DesktopWebPlatform",
                    "https://schema.org/MobileWebPlatform",
                ],
            },
        },
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
            "contact_telephone": CONTACT_TELEPHONE,
            "contact_telephone_display": _to_persian_digits(CONTACT_TELEPHONE),
        },
    )


register = register_patient
