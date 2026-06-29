import json

from django.conf import settings
from django.contrib import messages
from django.db import DatabaseError, IntegrityError, transaction
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.templatetags.static import static

from .forms import (
    DUPLICATE_MOBILE_ERROR,
    DUPLICATE_NATIONAL_CODE_ERROR,
    PatientRegistrationForm,
)
from .analytics import log_visit_event
from .models import Patient, VisitEvent

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


def _log_analytics(request, event_type, **kwargs):
    try:
        log_visit_event(request, event_type, **kwargs)
    except Exception:
        pass


def _static_source_exists(path):
    """Return whether a project-level static asset has been provided."""

    return (settings.BASE_DIR / "patients" / "static" / path).exists()


def _absolute_static_url(request, path):
    """Build an absolute URL for a static asset that may use a relative STATIC_URL."""

    static_url = static(path)
    if not static_url.startswith("/"):
        static_url = f"/{static_url}"

    return request.build_absolute_uri(static_url)


def robots_txt(request):
    """Serve crawl instructions for search engines."""

    return HttpResponse(
        "User-agent: *\nAllow: /\nSitemap: https://register.helssa.ir/sitemap.xml\n",
        content_type="text/plain; charset=utf-8",
    )


def sitemap_xml(request):
    """Expose the canonical public landing page in an XML sitemap."""

    return HttpResponse(
        """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://register.helssa.ir/</loc>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>
</urlset>
""",
        content_type="application/xml; charset=utf-8",
    )


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
                form.add_error("mobile", DUPLICATE_MOBILE_ERROR)
                form.add_error("national_code", DUPLICATE_NATIONAL_CODE_ERROR)
            except DatabaseError:
                _log_analytics(
                    request,
                    VisitEvent.EVENT_FORM_SUBMIT_ERROR,
                    metadata={"error_type": "DatabaseError"},
                )
                form.add_error(None, SAVE_ERROR)
            else:
                _log_analytics(
                    request, VisitEvent.EVENT_FORM_SUBMIT_SUCCESS, patient=patient
                )
                messages.success(request, "ثبت‌نام شما با موفقیت انجام شد.")
                return redirect("patients:register")
        else:
            _log_analytics(
                request,
                VisitEvent.EVENT_FORM_SUBMIT_INVALID,
                metadata={"error_fields": list(form.errors.keys())},
            )
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

    registered_count = Patient.objects.count()
    stats = {
        "community_count": registered_count + COMMUNITY_BASE_COUNT,
        "base_count": COMMUNITY_BASE_COUNT,
    }

    return render(
        request,
        "patients/register.html",
        {
            "form": form,
            "share_meta": share_meta,
            "site_logo": site_logo,
            "stats": stats,
            "structured_data_json": json.dumps(
                structured_data, ensure_ascii=False
            ).replace("</", "<\\/"),
        },
    )


register = register_patient
