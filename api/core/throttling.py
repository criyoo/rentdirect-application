from django.conf import settings
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle


class BurstRateThrottle(UserRateThrottle):
    scope = "burst"


class SustainedRateThrottle(UserRateThrottle):
    scope = "sustained"


class AnonBurstRateThrottle(AnonRateThrottle):
    scope = "burst"


class AuthBurstRateThrottle(AnonRateThrottle):
    scope = "auth_burst"


class AuthSustainedRateThrottle(AnonRateThrottle):
    scope = "auth_sustained"


class WebhookRateThrottle(AnonRateThrottle):
    scope = "webhook"


def production_ratelimit(*args, **kwargs):
    def decorator(func):
        if not getattr(settings, "ENFORCE_PRODUCTION_HARDENING", False):
            return func

        from django_ratelimit.decorators import ratelimit

        return ratelimit(*args, **kwargs)(func)

    return decorator
