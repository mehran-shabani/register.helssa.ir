import hashlib
import ipaddress
import logging
import uuid
from collections import OrderedDict

from django.conf import settings
from django.db.models import Count, Q
from django.db.models.functions import ExtractHour, TruncDate
from django.utils import timezone

from .datetime import format_tehran_jalali, format_tehran_jalali_date
from .models import VisitEvent

logger = logging.getLogger(__name__)


def get_client_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def hash_ip(ip):
    if not ip:
        return ""
    salt = getattr(settings, "ANALYTICS_IP_HASH_SALT", settings.SECRET_KEY)
    return hashlib.sha256(f"{salt}:{ip}".encode("utf-8")).hexdigest()


def mask_ip(ip):
    if not ip:
        return ""
    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:
        return ""
    if parsed.version == 4:
        parts = ip.split(".")
        return ".".join(parts[:3] + ["xxx"]) if getattr(settings, "ANALYTICS_MASK_IPV4_LAST_OCTET", True) else ip
    if not getattr(settings, "ANALYTICS_MASK_IPV6", True):
        return ip
    hextets = parsed.exploded.split(":")
    return ":".join(hextets[:4] + ["xxxx", "xxxx", "xxxx", "xxxx"])


def extract_utm_params(request):
    return {key: request.GET.get(key, "")[:120] for key in ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")}


def parse_user_agent(user_agent):
    ua = (user_agent or "").lower()
    is_bot = any(token in ua for token in ("bot", "crawler", "spider", "slurp", "bingpreview"))
    if is_bot:
        device_type = "bot"
    elif "ipad" in ua or "tablet" in ua:
        device_type = "tablet"
    elif "mobi" in ua or "iphone" in ua or "android" in ua:
        device_type = "mobile"
    elif ua:
        device_type = "desktop"
    else:
        device_type = "unknown"
    if "edg/" in ua:
        browser = "Edge"
    elif "chrome/" in ua and "chromium" not in ua:
        browser = "Chrome"
    elif "firefox/" in ua:
        browser = "Firefox"
    elif "safari/" in ua and "chrome/" not in ua:
        browser = "Safari"
    elif is_bot:
        browser = "Bot"
    else:
        browser = "Unknown"
    if "windows" in ua:
        os_name = "Windows"
    elif "android" in ua:
        os_name = "Android"
    elif "iphone" in ua or "ipad" in ua or "ios" in ua:
        os_name = "iOS"
    elif "mac os" in ua or "macintosh" in ua:
        os_name = "macOS"
    elif "linux" in ua:
        os_name = "Linux"
    else:
        os_name = "Unknown"
    return {"device_type": device_type, "browser": browser[:80], "os": os_name[:80], "is_bot": is_bot}


def _valid_uuid(value):
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError):
        return ""


def get_or_create_visitor_id(request, response=None):
    cookie_name = getattr(settings, "ANALYTICS_VISITOR_COOKIE_NAME", "helssa_vid")
    visitor_id = _valid_uuid(request.COOKIES.get(cookie_name))
    if not visitor_id:
        visitor_id = str(uuid.uuid4())
        request.COOKIES[cookie_name] = visitor_id
        setattr(request, "_analytics_visitor_cookie_needs_update", True)
    if response is not None and getattr(request, "_analytics_visitor_cookie_needs_update", False):
        response.set_cookie(cookie_name, visitor_id, max_age=getattr(settings, "ANALYTICS_VISITOR_COOKIE_MAX_AGE", 60 * 60 * 24 * 365), httponly=True, samesite="Lax", secure=getattr(settings, "SESSION_COOKIE_SECURE", False))
        setattr(request, "_analytics_visitor_cookie_needs_update", False)
    return visitor_id


def _safe_metadata(metadata):
    if not isinstance(metadata, dict):
        return {}
    blocked = {"mobile", "national_code", "first_name", "last_name", "phone", "raw", "data", "form", "post"}
    return {str(k): v for k, v in metadata.items() if str(k) not in blocked}


def _should_deduplicate_page_event(visitor_id, event_type, path, query_string):
    if event_type not in {VisitEvent.EVENT_PAGE_VIEW, VisitEvent.EVENT_FORM_VIEW}:
        return False
    window_seconds = getattr(settings, "ANALYTICS_PAGE_VIEW_DEDUP_SECONDS", 5 * 60)
    try:
        window_seconds = int(window_seconds)
    except (TypeError, ValueError):
        window_seconds = 0
    if window_seconds <= 0:
        return False
    since = timezone.now() - timezone.timedelta(seconds=window_seconds)
    return VisitEvent.objects.filter(
        visitor_id=visitor_id,
        event_type=event_type,
        path=path[:255],
        query_string=query_string,
        created_at__gte=since,
    ).exists()


def log_visit_event(request, event_type, response=None, patient=None, metadata=None, status_code=None):
    if not getattr(settings, "ANALYTICS_ENABLED", True):
        return None
    try:
        visitor_id = get_or_create_visitor_id(request, response=response)
        session = getattr(request, "session", None)
        ip = get_client_ip(request)
        user_agent = request.META.get("HTTP_USER_AGENT", "")
        ua_info = parse_user_agent(user_agent)
        raw_enabled = getattr(settings, "ANALYTICS_STORE_RAW_IP", False)
        query_string = request.META.get("QUERY_STRING", "")
        path = request.path[:255]
        if _should_deduplicate_page_event(visitor_id, event_type, path, query_string):
            return None
        return VisitEvent.objects.create(
            visitor_id=visitor_id,
            session_key=getattr(session, "session_key", "") or "",
            event_type=event_type,
            method=request.method[:10],
            path=path,
            query_string=query_string,
            referrer=request.META.get("HTTP_REFERER", ""),
            user_agent=user_agent,
            ip_hash=hash_ip(ip),
            masked_ip=mask_ip(ip),
            ip_address=ip if raw_enabled and ip else None,
            status_code=status_code if status_code is not None else getattr(response, "status_code", None),
            patient=patient,
            metadata=_safe_metadata(metadata),
            **ua_info,
            **extract_utm_params(request),
        )
    except Exception:
        logger.exception("Failed to log visit event %s.", event_type)
        return None


def get_visit_report_queryset(start_datetime, end_datetime, filters=None):
    qs = VisitEvent.objects.filter(created_at__gte=start_datetime, created_at__lte=end_datetime)
    filters = filters or {}
    for field in ("event_type", "path", "device_type", "utm_source", "utm_campaign", "ip_hash"):
        value = filters.get(field)
        if value:
            qs = qs.filter(**{field: value})
    if filters.get("is_bot") in {"true", "false"}:
        qs = qs.filter(is_bot=filters["is_bot"] == "true")
    return qs


def _percent(part, whole):
    return round((part / whole) * 100, 1) if whole else 0


def _top(queryset, field):
    return list(queryset.exclude(**{field: ""}).values(field).annotate(count=Count("id")).order_by("-count", field)[:10])


def _format_recent_events(queryset):
    events = list(queryset.order_by("-created_at")[:100])
    for event in events:
        event.created_at_jalali = format_tehran_jalali(event.created_at)
    return events


def get_visit_report_summary(queryset):
    metrics = queryset.aggregate(
        total_events=Count("id"),
        page_views=Count("id", filter=Q(event_type__in=[VisitEvent.EVENT_PAGE_VIEW, VisitEvent.EVENT_FORM_VIEW])),
        unique_visitors=Count("visitor_id", distinct=True),
        form_views=Count("id", filter=Q(event_type=VisitEvent.EVENT_FORM_VIEW)),
        submit_attempts=Count("id", filter=Q(event_type=VisitEvent.EVENT_FORM_SUBMIT_ATTEMPT)),
        successful_registrations=Count("id", filter=Q(event_type=VisitEvent.EVENT_FORM_SUBMIT_SUCCESS)),
        invalid_submits=Count("id", filter=Q(event_type=VisitEvent.EVENT_FORM_SUBMIT_INVALID)),
        error_submits=Count("id", filter=Q(event_type=VisitEvent.EVENT_FORM_SUBMIT_ERROR)),
        apk_downloads=Count("id", filter=Q(event_type=VisitEvent.EVENT_APK_DOWNLOAD)),
        bot_count=Count("id", filter=Q(is_bot=True)),
        mobile_count=Count("visitor_id", filter=Q(device_type="mobile"), distinct=True),
        desktop_count=Count("visitor_id", filter=Q(device_type="desktop"), distinct=True),
        tablet_count=Count("visitor_id", filter=Q(device_type="tablet"), distinct=True),
    )
    daily = OrderedDict((format_tehran_jalali_date(row["day"]), row["count"]) for row in queryset.annotate(day=TruncDate("created_at", tzinfo=timezone.get_current_timezone())).values("day").annotate(count=Count("id")).order_by("day") if row["day"])
    hourly = OrderedDict((f"{hour:02d}:00", 0) for hour in range(24))
    for row in queryset.annotate(hour=ExtractHour("created_at", tzinfo=timezone.get_current_timezone())).values("hour").annotate(count=Count("id")).order_by("hour"):
        if row["hour"] is not None:
            hourly[f"{row['hour']:02d}:00"] = row["count"]
    return {**metrics,
        "conversion_rate": _percent(metrics["successful_registrations"], metrics["form_views"]),
        "submit_success_rate": _percent(metrics["successful_registrations"], metrics["submit_attempts"]),
        "invalid_rate": _percent(metrics["invalid_submits"], metrics["submit_attempts"]),
        "top_paths": list(queryset.values("path").annotate(count=Count("id")).order_by("-count", "path")[:10]),
        "top_referrers": _top(queryset, "referrer"),
        "top_devices": _top(queryset, "device_type"),
        "top_browsers": _top(queryset, "browser"),
        "top_os": _top(queryset, "os"),
        "top_utm_sources": _top(queryset, "utm_source"),
        "top_utm_campaigns": _top(queryset, "utm_campaign"),
        "daily_counts": daily,
        "hourly_counts": hourly,
        "recent_events": _format_recent_events(queryset),
    }
