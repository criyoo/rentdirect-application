import hashlib
import hmac
import logging
import time

import requests
from django.conf import settings


logger = logging.getLogger(__name__)

DOCUSEAL_MAX_WEBHOOK_AGE_SECONDS = 5 * 60


def is_docuseal_configured() -> bool:
    return bool(getattr(settings, "DOCUSEAL_API_BASE_URL", "") and getattr(settings, "DOCUSEAL_API_KEY", ""))


def _api_headers() -> dict[str, str]:
    return {"X-Auth-Token": settings.DOCUSEAL_API_KEY}


def create_submission(*, name: str, document_name: str, document_content: str, submitters: list[dict]) -> dict:
    """Create a DocuSeal submission built from the generated agreement markdown.

    ``submitters`` items accept keys: role, name, email, fields (list of
    field dicts as accepted by DocuSeal's submission builder).
    """
    payload = {
        "name": name,
        "send_email": False,
        "documents": [{"name": document_name, "html": document_content}],
        "submitters": submitters,
    }
    if getattr(settings, "DOCUSEAL_WEBHOOK_URL", ""):
        payload["webhook_url"] = settings.DOCUSEAL_WEBHOOK_URL
    response = requests.post(
        f"{settings.DOCUSEAL_API_BASE_URL.rstrip('/')}/submissions",
        json=payload,
        headers=_api_headers(),
        timeout=settings.DOCUSEAL_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def get_submission(submission_id: int) -> dict:
    response = requests.get(
        f"{settings.DOCUSEAL_API_BASE_URL.rstrip('/')}/submissions/{submission_id}",
        headers=_api_headers(),
        timeout=settings.DOCUSEAL_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def _extract_signature_header(value: str) -> tuple[str | None, str | None]:
    """Parse DocuSeal webhook signature headers.

    Supports ``t=<ts>,sha256=<hex>`` style and plain ``<ts>.<hex>`` formats.
    """
    value = (value or "").strip()
    if not value:
        return None, None
    parts: dict[str, str] = {}
    for segment in value.split(","):
        if "=" in segment:
            key, _, val = segment.partition("=")
            parts[key.strip()] = val.strip()
    if parts.get("sha256"):
        return parts.get("t"), parts["sha256"]
    if "." in value:
        timestamp, _, signature = value.partition(".")
        return timestamp or None, signature or None
    return None, None


def verify_webhook_signature(request) -> bool:
    """Verify the HMAC signature of a DocuSeal webhook request."""
    secret = getattr(settings, "DOCUSEAL_WEBHOOK_SECRET", "")
    if not secret:
        return False
    header = (
        request.headers.get("X-Docuseal-Signature")
        or request.headers.get("X-DocuSeal-Signature")
        or request.headers.get("Docuseal-Signature")
        or ""
    )
    timestamp, signature = _extract_signature_header(header)
    if not timestamp or not signature:
        return False
    try:
        age = abs(time.time() - int(timestamp))
    except (TypeError, ValueError):
        return False
    if age > DOCUSEAL_MAX_WEBHOOK_AGE_SECONDS:
        return False
    raw_body = request.body or b""
    candidates = [
        f"{timestamp}.{raw_body.decode('utf-8', errors='surrogateescape')}",
        raw_body.decode("utf-8", errors="surrogateescape"),
    ]
    for candidate in candidates:
        expected = hmac.new(secret.encode(), candidate.encode(), hashlib.sha256).hexdigest()
        if hmac.compare_digest(expected, signature):
            return True
    return False


def signature_placeholder(role: str) -> str:
    """Marker rendered into the generated document marking a signer's box."""
    return f"{{{{signature;role={role}}}}}"
