import os
import ssl
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote_plus

import dj_database_url


BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


def database_url() -> str:
    explicit = os.environ.get("DATABASE_URL", "").strip()
    if explicit:
        return explicit
    host = os.environ.get("POSTGRES_HOST", "").strip()
    name = os.environ.get("POSTGRES_DB", "").strip()
    user = os.environ.get("POSTGRES_USER", "").strip()
    password = os.environ.get("POSTGRES_PASSWORD", "")
    port = os.environ.get("POSTGRES_PORT", "5432").strip() or "5432"
    if host and name and user:
        return f"postgresql://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{name}"
    return f"sqlite:///{BASE_DIR / 'db.sqlite3'}"


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", os.environ.get("JWT_SECRET_KEY", "dev-secret-key"))
DEBUG = env_bool("DJANGO_DEBUG", False)
ENVIRONMENT = os.environ.get("DJANGO_ENV", os.environ.get("ENVIRONMENT", "development" if DEBUG else "production")).lower()
ENFORCE_PRODUCTION_HARDENING = env_bool(
    "ENFORCE_PRODUCTION_HARDENING",
    ENVIRONMENT in {"prod", "production"},
)
ENFORCE_FLUTTERWAVE_WEBHOOK_SIGNATURE = env_bool(
    "ENFORCE_FLUTTERWAVE_WEBHOOK_SIGNATURE",
    ENFORCE_PRODUCTION_HARDENING,
)

if not DEBUG and SECRET_KEY == "dev-secret-key":
    raise RuntimeError("DJANGO_SECRET_KEY or JWT_SECRET_KEY must be set when DEBUG is disabled")

DJANGO_ALLOWED_HOSTS = env_list(
    "DJANGO_ALLOWED_HOSTS",
    "localhost,127.0.0.1,api.rentdirect.homes,api.development.rentdirect.homes",
)
ALLOWED_HOSTS = DJANGO_ALLOWED_HOSTS

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "django_filters",
    "storages",
    "core",
]

MIDDLEWARE = [
    "core.middleware.DisallowedHostMiddleware",
    "core.middleware.HealthCheckHostBypassMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": dj_database_url.parse(
        database_url(),
        conn_max_age=env_int("DB_CONN_MAX_AGE", 600),
        ssl_require=env_bool("DATABASE_SSL_REQUIRE", not DEBUG),
    )
}

def cache_url() -> str:
    return os.environ.get("VALKEY_URL", os.environ.get("REDIS_URL", "")).strip()


def cache_config() -> dict:
    url = cache_url()
    if not url:
        return {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "rentdirect-local",
        }

    options = {"CLIENT_CLASS": "django_redis.client.DefaultClient"}
    auth_token = os.environ.get("VALKEY_AUTH_TOKEN", "").strip()
    if auth_token:
        options["PASSWORD"] = auth_token
    if url.startswith("rediss://"):
        options["CONNECTION_POOL_KWARGS"] = {"ssl_cert_reqs": ssl.CERT_NONE}

    return {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": url,
        "OPTIONS": options,
    }


CACHES = {
    "default": cache_config()
}

AUTH_USER_MODEL = "core.AppUser"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/uploads/"
MEDIA_ROOT = BASE_DIR / "uploads"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
if ENVIRONMENT == "test":
    STORAGES["staticfiles"] = {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}

AWS_STORAGE_BUCKET_NAME = os.environ.get("AWS_STORAGE_BUCKET_NAME", "").strip()
AWS_S3_REGION_NAME = os.environ.get("AWS_S3_REGION_NAME", os.environ.get("AWS_REGION", "eu-west-1")).strip()
AWS_S3_CUSTOM_DOMAIN = os.environ.get("AWS_S3_CUSTOM_DOMAIN", "").strip()
AWS_S3_ENDPOINT_URL = os.environ.get("AWS_S3_ENDPOINT_URL", "").strip() or None
AWS_S3_URL_PROTOCOL = os.environ.get("AWS_S3_URL_PROTOCOL", "").strip()
if AWS_STORAGE_BUCKET_NAME:
    s3_options = {
        "bucket_name": AWS_STORAGE_BUCKET_NAME,
        "region_name": AWS_S3_REGION_NAME or None,
        "custom_domain": AWS_S3_CUSTOM_DOMAIN or None,
        "endpoint_url": AWS_S3_ENDPOINT_URL,
        "default_acl": None,
        "file_overwrite": False,
        "querystring_auth": False,
    }
    if AWS_S3_URL_PROTOCOL:
        s3_options["url_protocol"] = AWS_S3_URL_PROTOCOL
    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": s3_options,
    }
    media_domain = AWS_S3_CUSTOM_DOMAIN or f"{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com"
    protocol = AWS_S3_URL_PROTOCOL or "https"
    MEDIA_URL = f"{protocol}://{media_domain}/"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["core.authentication.CookieJWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 20,
}

if ENFORCE_PRODUCTION_HARDENING:
    REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"] = [
        "core.throttling.AnonBurstRateThrottle",
        "core.throttling.BurstRateThrottle",
        "core.throttling.SustainedRateThrottle",
    ]
    REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {
        "burst": "60/min",
        "sustained": "2000/day",
        "auth_burst": "10/min",
        "auth_sustained": "100/day",
        "webhook": "120/min",
    }

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env_int("ACCESS_TOKEN_LIFETIME_MINUTES", 60)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env_int("REFRESH_TOKEN_LIFETIME_DAYS", 7)),
    "SIGNING_KEY": SECRET_KEY,
}

CORS_ALLOWED_ORIGINS = env_list(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:3600,http://localhost:3000,https://development.rentdirect.homes,https://rentdirect.homes,https://www.rentdirect.homes",
)
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = env_list(
    "CSRF_TRUSTED_ORIGINS",
    "http://localhost:3600,http://localhost:3000,https://development.rentdirect.homes,https://rentdirect.homes,https://www.rentdirect.homes",
)

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", not DEBUG)
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", not DEBUG)
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", not DEBUG)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = os.environ.get("SESSION_COOKIE_SAMESITE", "Lax")
CSRF_COOKIE_SAMESITE = os.environ.get("CSRF_COOKIE_SAMESITE", "Lax")
SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 31536000 if not DEBUG else 0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", not DEBUG)
SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", not DEBUG)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"

COOKIE_DOMAIN = os.environ.get("COOKIE_DOMAIN", "")
API_PUBLIC_URL = os.environ.get("API_PUBLIC_URL", "https://api.rentdirect.homes").rstrip("/")
WEB_PUBLIC_URL = os.environ.get(
    "WEB_PUBLIC_URL",
    "https://rentdirect.homes"
    if ENVIRONMENT in {"prod", "production"}
    else "https://development.rentdirect.homes"
    if ENVIRONMENT in {"dev", "development", "staging"}
    else "http://localhost:3600",
).rstrip("/")
ACCESS_COOKIE_NAME = "access_token"
REFRESH_COOKIE_NAME = "refresh_token"
MAX_UPLOAD_SIZE_MB = env_int("MAX_UPLOAD_SIZE_MB", 12)

DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "noreply@rentdirect.homes")
SERVER_EMAIL = os.environ.get("SERVER_EMAIL", DEFAULT_FROM_EMAIL)
EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtpout.secureserver.net")
EMAIL_PORT = env_int("EMAIL_PORT", 587)
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
EMAIL_TIMEOUT = env_int("EMAIL_TIMEOUT", 30)
FLUTTERWAVE_PAYOUT_RELEASE_WATCH_INTERVAL_SECONDS = env_int("FLUTTERWAVE_PAYOUT_RELEASE_WATCH_INTERVAL_SECONDS", 900)
SUBSCRIPTION_RENEWAL_WATCH_INTERVAL_SECONDS = env_int("SUBSCRIPTION_RENEWAL_WATCH_INTERVAL_SECONDS", 3600)

FLUTTERWAVE_PUBLIC_KEY = os.environ.get("FLUTTERWAVE_PUBLIC_KEY", "FLWPUBK_TEST-9b1b489ab095ab2f68b2e14d47c96258-X").strip()
FLUTTERWAVE_SECRET_KEY = os.environ.get("FLUTTERWAVE_SECRET_KEY", "FLWSECK_TEST-f9a953ad24cd5e312cbc9c12e42d4795-X").strip()
FLUTTERWAVE_ENCRYPTION_KEY = os.environ.get("FLUTTERWAVE_ENCRYPTION_KEY", "FLWSECK_TESTe4df9d93eb9d").strip()
FLUTTERWAVE_TRANSFER_PIN = os.environ.get("FLUTTERWAVE_TRANSFER_PIN", "").strip()
FLUTTERWAVE_CLIENT_ID = os.environ.get("FLUTTERWAVE_CLIENT_ID", "3b6a2d1e-471b-4fc8-81a8-d23d16f2b400").strip()
FLUTTERWAVE_CLIENT_SECRET = os.environ.get("FLUTTERWAVE_CLIENT_SECRET", "pw4JNiqIvFfbS8iXRFvNQZUCfUZjjWCp").strip()
FLUTTERWAVE_WEBHOOK_SECRET_HASH = os.environ.get("FLUTTERWAVE_WEBHOOK_SECRET_HASH", "").strip()
FLUTTERWAVE_V3_API_BASE_URL = os.environ.get("FLUTTERWAVE_V3_API_BASE_URL", "https://api.flutterwave.com/v3").strip()
FLUTTERWAVE_API_BASE_URL = os.environ.get("FLUTTERWAVE_API_BASE_URL", "https://developersandbox-api.flutterwave.com").strip()
FLUTTERWAVE_TOKEN_URL = os.environ.get(
    "FLUTTERWAVE_TOKEN_URL",
    "https://idp.flutterwave.com/realms/flutterwave/protocol/openid-connect/token",
).strip()
FLUTTERWAVE_WEBHOOK_URL = os.environ.get("FLUTTERWAVE_WEBHOOK_URL", "").strip()
FLUTTERWAVE_VIRTUAL_ACCOUNT_EXPIRY_SECONDS = env_int("FLUTTERWAVE_VIRTUAL_ACCOUNT_EXPIRY_SECONDS", 24 * 60 * 60)
FLUTTERWAVE_PAYOUT_BALANCE_DELAY_HOURS = env_int("FLUTTERWAVE_PAYOUT_BALANCE_DELAY_HOURS", 24)
USE_TEST_PAYOUT_ACCOUNT_DEFAULTS = ENVIRONMENT not in {"prod", "production"}
RENTDIRECT_OPERATING_BANK_NAME = os.environ.get(
    "RENTDIRECT_OPERATING_BANK_NAME",
    os.environ.get(
        "RENTDIRECT_OPERATING_BANK",
        os.environ.get("FLUTTERWAVE_SETTLEMENT_BANK_NAME", "Opay" if USE_TEST_PAYOUT_ACCOUNT_DEFAULTS else ""),
    ),
).strip()
RENTDIRECT_OPERATING_BANK_CODE = os.environ.get("RENTDIRECT_OPERATING_BANK_CODE", "").strip()
RENTDIRECT_OPERATING_ACCOUNT_NUMBER = os.environ.get(
    "RENTDIRECT_OPERATING_ACCOUNT_NUMBER",
    os.environ.get(
        "RENTDIRECT_OPERATING_ACCOUNT",
        os.environ.get("FLUTTERWAVE_SETTLEMENT_ACCOUNT_NUMBER", "9041487757" if USE_TEST_PAYOUT_ACCOUNT_DEFAULTS else ""),
    ),
).strip()
RENTDIRECT_OPERATING_ACCOUNT_NAME = os.environ.get("RENTDIRECT_OPERATING_ACCOUNT_NAME", "RentDirect Operations").strip()
TENANT_CAUTION_HOLDING_BANK_NAME = os.environ.get(
    "TENANT_CAUTION_HOLDING_BANK_NAME",
    "Monie Point" if USE_TEST_PAYOUT_ACCOUNT_DEFAULTS else "",
).strip()
TENANT_CAUTION_HOLDING_BANK_CODE = os.environ.get("TENANT_CAUTION_HOLDING_BANK_CODE", "").strip()
TENANT_CAUTION_HOLDING_ACCOUNT_NUMBER = os.environ.get(
    "TENANT_CAUTION_HOLDING_ACCOUNT_NUMBER",
    "5900387715" if USE_TEST_PAYOUT_ACCOUNT_DEFAULTS else "",
).strip()
TENANT_CAUTION_HOLDING_ACCOUNT_NAME = os.environ.get("TENANT_CAUTION_HOLDING_ACCOUNT_NAME", "RentDirect Tenant Caution Holding").strip()

DIKRIPT_API_BASE_URL = os.environ.get("DIKRIPT_API_BASE_URL", "https://api.dikript.com").strip()
DIKRIPT_NIN_API_URL = os.environ.get("DIKRIPT_NIN_API_URL", "/dikript/verification/api/v1/getnin").strip()
DIKRIPT_BVN_API_URL = os.environ.get("DIKRIPT_BVN_API_URL", "/dikript/verification/api/v1/getbvn").strip()
DIKRIPT_CAC_API_URL = os.environ.get("DIKRIPT_CAC_API_URL", "/dikript/verification/api/v1/getcacbasic").strip()
DIKRIPT_PUBLIC_KEY = os.environ.get("DIKRIPT_PUBLIC_KEY", "").strip()
DIKRIPT_SECRET_KEY = os.environ.get("DIKRIPT_SECRET_KEY", "").strip()
DIKRIPT_TIMEOUT_SECONDS = env_int("DIKRIPT_TIMEOUT_SECONDS", 10)
DIKRIPT_LOOKUP_CACHE_TIMEOUT_SECONDS = env_int("DIKRIPT_LOOKUP_CACHE_TIMEOUT_SECONDS", 60 * 60 * 24)

SEED_DEMO_ACCOUNTS = env_bool("SEED_DEMO_ACCOUNTS", ENVIRONMENT in {"dev", "development", "local"})
SEED_LANDLORD_DATA_PATH = os.environ.get("SEED_LANDLORD_DATA_PATH", "seed_demo_data/landlord/landlord.json")
SEED_TENANT_DATA_PATH = os.environ.get("SEED_TENANT_DATA_PATH", "seed_demo_data/tenants/tenants.json")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}
