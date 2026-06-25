from .analytics import log_visit_event
from .models import VisitEvent


class PublicVisitTrackingMiddleware:
    SKIP_PREFIXES = ("/admin/", "/static/", "/media/", "/favicon")
    TRACKED_GET_PATHS = ("/", "/register/")
    FORM_GET_PATHS = ("/register/",)

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if self._should_track(request):
            event_type = VisitEvent.EVENT_FORM_VIEW if request.path in self.FORM_GET_PATHS else VisitEvent.EVENT_PAGE_VIEW
            log_visit_event(request, event_type, response=response, metadata={"page_view": True})
        elif getattr(request, "_analytics_visitor_cookie_needs_update", False):
            from .analytics import get_or_create_visitor_id

            get_or_create_visitor_id(request, response=response)
        return response

    def _should_track(self, request):
        if request.method != "GET":
            return False
        if any(request.path.startswith(prefix) for prefix in self.SKIP_PREFIXES):
            return False
        return request.path in self.TRACKED_GET_PATHS
