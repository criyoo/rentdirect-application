from django.core.exceptions import DisallowedHost
from django.http import HttpResponseBadRequest, JsonResponse


class DisallowedHostMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            return self.get_response(request)
        except DisallowedHost:
            return HttpResponseBadRequest("Invalid host header")


class HealthCheckHostBypassMiddleware:
    HEALTHCHECK_PATHS = {"/", "/health", "/api/health", "/api/health/ready"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path in self.HEALTHCHECK_PATHS:
            return JsonResponse({"status": "ok"})
        return self.get_response(request)
