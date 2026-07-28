import os

os.environ["DJANGO_ENV"] = "test"
os.environ["DJANGO_DEBUG"] = "True"
os.environ.setdefault("DJANGO_SECRET_KEY", "test-secret-key")

from .base import *  # noqa: F403,F401

DEBUG = True
ENVIRONMENT = "test"
ENFORCE_PRODUCTION_HARDENING = False
ENFORCE_FLUTTERWAVE_WEBHOOK_SIGNATURE = False

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "test.sqlite3",  # noqa: F405
    }
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "rentdirect-tests",
    }
}

MIDDLEWARE = [  # noqa: F405
    middleware
    for middleware in MIDDLEWARE  # noqa: F405
    if middleware != "whitenoise.middleware.WhiteNoiseMiddleware"
]

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
PAYMENT_QUEUE_BACKEND = "sync"
PAYMENT_QUEUE_REDIS_URL = ""
PAYMENT_QUEUE_URL = ""
SEED_DEMO_ACCOUNTS = False
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
