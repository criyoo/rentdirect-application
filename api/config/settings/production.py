import os

os.environ["DJANGO_ENV"] = "production"
os.environ["DJANGO_DEBUG"] = "False"

from .base import *  # noqa: F403,F401

DEBUG = False
ENVIRONMENT = "production"
ENFORCE_PRODUCTION_HARDENING = True
ENFORCE_FLUTTERWAVE_WEBHOOK_SIGNATURE = env_bool(  # noqa: F405
    "ENFORCE_FLUTTERWAVE_WEBHOOK_SIGNATURE",
    True,
)
REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"] = [  # noqa: F405
    "core.throttling.AnonBurstRateThrottle",
    "core.throttling.BurstRateThrottle",
    "core.throttling.SustainedRateThrottle",
]
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {  # noqa: F405
    "burst": "60/min",
    "sustained": "2000/day",
    "auth_burst": "10/min",
    "auth_sustained": "100/day",
    "webhook": "120/min",
}

if SECRET_KEY == "dev-secret-key":  # noqa: F405
    raise RuntimeError("DJANGO_SECRET_KEY or JWT_SECRET_KEY must be set in production")

ALLOWED_HOSTS = env_list(  # noqa: F405
    "DJANGO_ALLOWED_HOSTS",
    "api.rentdirect.homes,rentdirect.homes,www.rentdirect.homes",
)
CORS_ALLOWED_ORIGINS = env_list(  # noqa: F405
    "CORS_ALLOWED_ORIGINS",
    "https://rentdirect.homes,https://www.rentdirect.homes",
)
CSRF_TRUSTED_ORIGINS = env_list(  # noqa: F405
    "CSRF_TRUSTED_ORIGINS",
    "https://rentdirect.homes,https://www.rentdirect.homes,https://api.rentdirect.homes",
)

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = env_bool("USE_X_FORWARDED_HOST", False)  # noqa: F405
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)  # noqa: F405
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", True)  # noqa: F405
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", True)  # noqa: F405
SESSION_COOKIE_SAMESITE = os.environ.get("SESSION_COOKIE_SAMESITE", "Lax")
CSRF_COOKIE_SAMESITE = os.environ.get("CSRF_COOKIE_SAMESITE", "Lax")
SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 31536000)  # noqa: F405
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", True)  # noqa: F405
SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", True)  # noqa: F405

SEED_DEMO_ACCOUNTS = env_bool("SEED_DEMO_ACCOUNTS", False)  # noqa: F405

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "ERROR")},
}

# Production payout balance delay (24 hours)
FLUTTERWAVE_PAYOUT_BALANCE_DELAY_MINUTES = env_payout_delay_minutes(24 * 60)  # noqa: F405