from django.core.exceptions import DisallowedHost
from django.http import HttpResponseBadRequest, JsonResponse


HEALTHCHECK_PATHS = {"/", "/health", "/api/health", "/api/health/ready"}


class DisallowedHostMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path not in HEALTHCHECK_PATHS:
            try:
                request.get_host()
            except DisallowedHost:
                return HttpResponseBadRequest("Invalid host header")

        try:
            return self.get_response(request)
        except DisallowedHost:
            return HttpResponseBadRequest("Invalid host header")


class HealthCheckHostBypassMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path in HEALTHCHECK_PATHS:
            try:
                request.get_host()
            except DisallowedHost:
                return JsonResponse({"status": "ok"})
        return self.get_response(request)
