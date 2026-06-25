from django.conf import settings
from django.contrib import messages
from django.db import DatabaseError, IntegrityError, transaction
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
SHARE_TITLE = SITE_NAME
SHARE_DESCRIPTION = (
    "ثبت‌نام اینترنتی طرح پزشک خانواده دکتر حسین شبانی در درمانگاه ولیعصر صغاد؛ "
    "خدمات درمانی با تعرفه دولتی، پیگیری سلامت خانواده و پاسخگویی آنلاین."
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
                _log_analytics(request, VisitEvent.EVENT_FORM_SUBMIT_SUCCESS, patient=patient)
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
        "url": request.build_absolute_uri(request.path),
        "image": _absolute_static_url(request, SHARE_IMAGE_PATH),
        "image_width": "1200",
        "image_height": "630",
    }
    site_logo = None
    if _static_source_exists(SITE_LOGO_PATH):
        site_logo = {
            "url": _absolute_static_url(request, SITE_LOGO_PATH),
            "alt": f"لوگوی {SITE_NAME}",
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
        },
    )


register = register_patient
