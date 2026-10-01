import logging
import re

import requests
from django.conf import settings


logger = logging.getLogger(__name__)

_WHATSAPP_RECIPIENT_RE = re.compile(r"[^\d]")


def normalize_whatsapp_number(value: str) -> str:
    """Return an E.164-style digits string for a WhatsApp recipient."""
    digits = _WHATSAPP_RECIPIENT_RE.sub("", value or "")
    if not digits:
        return ""
    # Nigerian local numbers (e.g. 0803...) -> international format.
    if digits.startswith("0") and len(digits) == 11:
        digits = f"234{digits[1:]}"
    elif digits.startswith("00"):
        digits = digits[2:]
    return digits


def is_whatsapp_configured() -> bool:
    provider = getattr(settings, "WHATSAPP_PROVIDER", "").strip().lower()
    if provider == "twilio":
        return all(
            [
                getattr(settings, "TWILIO_ACCOUNT_SID", ""),
                getattr(settings, "TWILIO_AUTH_TOKEN", ""),
                getattr(settings, "TWILIO_WHATSAPP_FROM", ""),
            ]
        )
    if provider == "whatsapp_cloud":
        return all(
            [
                getattr(settings, "WHATSAPP_CLOUD_ACCESS_TOKEN", ""),
                getattr(settings, "WHATSAPP_CLOUD_PHONE_NUMBER_ID", ""),
            ]
        )
    return False


def _send_via_twilio(recipient: str, body: str) -> None:
    sender = normalize_whatsapp_number(settings.TWILIO_WHATSAPP_FROM)
    requests.post(
        f"https://api.twilio.com/2010-04-01/Accounts/{settings.TWILIO_ACCOUNT_SID}/Messages.json",
        data={"From": f"whatsapp:+{sender}", "To": f"whatsapp:+{recipient}", "Body": body},
        auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
        timeout=settings.WHATSAPP_TIMEOUT_SECONDS,
    ).raise_for_status()


def _send_via_whatsapp_cloud(recipient: str, body: str) -> None:
    url = (
        f"{settings.WHATSAPP_CLOUD_API_BASE_URL.rstrip('/')}/"
        f"{settings.WHATSAPP_CLOUD_API_VERSION}/{settings.WHATSAPP_CLOUD_PHONE_NUMBER_ID}/messages"
    )
    requests.post(
        url,
        json={
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "text",
            "text": {"preview_url": False, "body": body},
        },
        headers={"Authorization": f"Bearer {settings.WHATSAPP_CLOUD_ACCESS_TOKEN}"},
        timeout=settings.WHATSAPP_TIMEOUT_SECONDS,
    ).raise_for_status()


def send_whatsapp_message(recipient_number: str, body: str) -> bool:
    """Send a WhatsApp text alert. Returns True on success, False when skipped/failed."""
    recipient = normalize_whatsapp_number(recipient_number)
    if not recipient or not body:
        return False
    if not is_whatsapp_configured():
        return False
    provider = settings.WHATSAPP_PROVIDER
    try:
        if provider == "twilio":
            _send_via_twilio(recipient, body)
        elif provider == "whatsapp_cloud":
            _send_via_whatsapp_cloud(recipient, body)
        else:
            return False
        return True
    except Exception:
        logger.exception("Failed to send WhatsApp alert to %s", recipient)
        return False


def send_whatsapp_alert_for_user(user, body: str) -> bool:
    """Send a WhatsApp alert to a user's configured WhatsApp number."""
    number = getattr(user, "whatsapp_number", "") or ""
    return send_whatsapp_message(number, body)
