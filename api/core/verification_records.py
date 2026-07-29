from __future__ import annotations

import json
from typing import Any

from .models import BvnVerificationRecord, CacVerificationRecord, NinVerificationRecord

SENSITIVE_MEDIA_KEYS = {"base64image", "image", "photo", "signature"}

RECORD_MODEL_BY_TYPE = {
    "nin": (NinVerificationRecord, "nin"),
    "bvn": (BvnVerificationRecord, "bvn"),
    "cac": (CacVerificationRecord, "registration_number"),
}


def _normalize_lookup_value(value: Any) -> str:
    return str(value or "").strip()


def _record_model(verification_type: str):
    normalized_type = str(verification_type or "").strip().lower()
    try:
        return RECORD_MODEL_BY_TYPE[normalized_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported verification record type: {verification_type}") from exc


def sanitize_verification_payload(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            if str(key).lower() in SENSITIVE_MEDIA_KEYS:
                continue
            sanitized[key] = sanitize_verification_payload(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_verification_payload(item) for item in value]
    return value


def _json_safe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return sanitize_verification_payload(json.loads(json.dumps(payload)))


def get_verification_record_payload(
    *,
    provider: str,
    verification_type: str,
    lookup_value: Any,
) -> dict[str, Any] | None:
    model, lookup_field = _record_model(verification_type)
    normalized_provider = str(provider or "").strip().lower()
    normalized_lookup = _normalize_lookup_value(lookup_value)
    if not normalized_provider or not normalized_lookup:
        return None

    record = (
        model.objects
        .filter(provider=normalized_provider, **{lookup_field: normalized_lookup})
        .order_by("-updated_at")
        .first()
    )
    if not record or not isinstance(record.response_payload, dict):
        return None
    return _json_safe_payload(record.response_payload)


def store_verification_record_payload(
    *,
    provider: str,
    verification_type: str,
    lookup_value: Any,
    payload: dict[str, Any],
) -> dict[str, Any]:
    model, lookup_field = _record_model(verification_type)
    normalized_provider = str(provider or "").strip().lower()
    normalized_lookup = _normalize_lookup_value(lookup_value)
    sanitized_payload = _json_safe_payload(payload)
    if not normalized_provider or not normalized_lookup:
        return sanitized_payload

    model.objects.update_or_create(
        provider=normalized_provider,
        **{lookup_field: normalized_lookup},
        defaults={"response_payload": sanitized_payload},
    )
    return sanitized_payload
