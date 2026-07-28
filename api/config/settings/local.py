import os

os.environ["DJANGO_ENV"] = "local"
os.environ["DJANGO_DEBUG"] = "True"

from .base import *  # noqa: F403,F401

DEBUG = True
ENVIRONMENT = "local"
ENFORCE_PRODUCTION_HARDENING = False
ENFORCE_FLUTTERWAVE_WEBHOOK_SIGNATURE = env_bool(  # noqa: F405
    "ENFORCE_FLUTTERWAVE_WEBHOOK_SIGNATURE",
    False,
)

ALLOWED_HOSTS = env_list(  # noqa: F405
    "DJANGO_ALLOWED_HOSTS",
    "localhost,127.0.0.1,0.0.0.0,backend,api",
)
CORS_ALLOWED_ORIGINS = env_list(  # noqa: F405
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:3600,http://127.0.0.1:3600,http://localhost:3000,http://127.0.0.1:3000",
)
CSRF_TRUSTED_ORIGINS = env_list(  # noqa: F405
    "CSRF_TRUSTED_ORIGINS",
    "http://localhost:3600,http://127.0.0.1:3600,http://localhost:3000,http://127.0.0.1:3000",
)

SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", False)  # noqa: F405
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", False)  # noqa: F405
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", False)  # noqa: F405
SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 0)  # noqa: F405
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", False)  # noqa: F405
SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", False)  # noqa: F405

EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend",
)

SEED_DEMO_ACCOUNTS = env_bool("SEED_DEMO_ACCOUNTS", True)  # noqa: F405


# Local development payout balance delay (10 minutes for testing)
FLUTTERWAVE_PAYOUT_BALANCE_DELAY_MINUTES = env_payout_delay_minutes(10)  # noqa: F405
