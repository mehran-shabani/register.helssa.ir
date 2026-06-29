from django.conf import settings

from .analytics import log_visit_event
from .models import VisitEvent


class PublicVisitTrackingMiddleware:
    SKIP_PREFIXES = ("/admin/", "/static/", "/media/", "/favicon")
    TRACKED_GET_PATHS = ("/",)
    FORM_GET_PATHS = ()

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if self._should_track(request):
            form_paths = tuple(
                getattr(settings, "ANALYTICS_FORM_GET_PATHS", self.FORM_GET_PATHS)
            )
            event_type = (
                VisitEvent.EVENT_FORM_VIEW
                if request.path in form_paths
                else VisitEvent.EVENT_PAGE_VIEW
            )
            log_visit_event(
                request, event_type, response=response, metadata={"page_view": True}
            )
        elif getattr(request, "_analytics_visitor_cookie_needs_update", False):
            from .analytics import get_or_create_visitor_id

            get_or_create_visitor_id(request, response=response)
        return response

    def _should_track(self, request):
        if request.method != "GET":
            return False
        if any(request.path.startswith(prefix) for prefix in self.SKIP_PREFIXES):
            return False
        tracked_paths = tuple(
            getattr(settings, "ANALYTICS_TRACKED_GET_PATHS", self.TRACKED_GET_PATHS)
        )
        return request.path in tracked_paths
