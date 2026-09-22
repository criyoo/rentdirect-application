from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from django.conf import settings

from ..financial_constants import MONEY_PRECISION, ZERO_AMOUNT

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 30


class FlutterwaveError(ValueError):
    pass


NIGERIAN_PAYOUT_BANK_CODES_BY_NAME = {
    "accessbank": "044",
    "ecobank": "050",
    "fidelitybank": "070",
    "firstbank": "011",
    "firstbankofnigeria": "011",
    "firstcitymonumentbank": "214",
    "firstcitymonumentbankplc": "214",
    "fcmb": "214",
    "gtbank": "058",
    "guarantytrustbank": "058",
    "opay": "100004",
    "paycom": "100004",
    "opaydigitalservices": "100004",
    "palmpay": "100033",
    "moniepoint": "50515",
    "moniepointmfb": "50515",
    "moniepointmicrofinancebank": "50515",
    "providus": "101",
    "providusbank": "101",
    "providusbankplc": "101",
    "sterlingbank": "232",
    "uba": "033",
    "unitedbankforafrica": "033",
    "wemabank": "035",
    "zenithbank": "057",
}

NIGERIAN_PAYOUT_BANK_CODE_CANDIDATES_BY_NAME = {
    "opay": ("100004", "999992"),
    "paycom": ("100004", "999992"),
    "opaydigitalservices": ("100004", "999992"),
    "palmpay": ("100033",),
    "moniepoint": ("50515", "090405"),
    "moniepointmfb": ("50515", "090405"),
    "moniepointmicrofinancebank": ("50515", "090405"),
    "firstcitymonumentbank": ("214",),
    "firstcitymonumentbankplc": ("214",),
    "fcmb": ("214",),
}


def normalize_bank_name_key(bank_name: str) -> str:
    return "".join(character for character in str(bank_name or "").lower() if character.isalnum())


def resolve_nigerian_payout_bank_code(bank_name: str, bank_code: str = "") -> str:
    normalized_bank_name = normalize_bank_name_key(bank_name)
    configured_bank_code = str(bank_code or "").strip()
    return NIGERIAN_PAYOUT_BANK_CODES_BY_NAME.get(normalized_bank_name, configured_bank_code)


def nigerian_payout_bank_code_candidates(bank_name: str, bank_code: str = "") -> list[str]:
    normalized_bank_name = normalize_bank_name_key(bank_name)
    configured_bank_code = str(bank_code or "").strip()
    known_candidates = NIGERIAN_PAYOUT_BANK_CODE_CANDIDATES_BY_NAME.get(normalized_bank_name)
    if known_candidates:
        candidates = list(known_candidates)
    else:
        candidates = [resolve_nigerian_payout_bank_code(bank_name, configured_bank_code)]
    if configured_bank_code and (not known_candidates or configured_bank_code in known_candidates):
        candidates.append(configured_bank_code)
    return list(dict.fromkeys(candidate for candidate in candidates if candidate))


def collection_subaccount_bank_code_candidates(bank_code: str) -> list[str]:
    normalized_bank_code = str(bank_code or "").strip()
    known_candidates = {
        "100004": ("100004", "999992"),
        "999992": ("999992", "100004"),
        "50515": ("50515", "090405"),
        "090405": ("090405", "50515"),
    }.get(normalized_bank_code, (normalized_bank_code,))
    return list(dict.fromkeys(candidate for candidate in known_candidates if candidate))


def append_query_params(url: str, **params: Any) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key, value in params.items():
        if value is not None and str(value).strip():
            query[key] = str(value)
    return urlunparse(parsed._replace(query=urlencode(query)))


def normalize_decimal_amount(value: Any) -> Decimal:
    return Decimal(str(value or ZERO_AMOUNT)).quantize(MONEY_PRECISION)


def normalize_provider_transaction_id(value: Any) -> str | None:
    normalized = str(value or "").strip()
    if not normalized or normalized.lower() in {"null", "none", "undefined"}:
        return None
    return normalized


def verify_webhook_signature(*, raw_body: bytes, signature: str) -> bool:
    secret_hash = str(getattr(settings, "FLUTTERWAVE_WEBHOOK_SECRET_HASH", "") or "").strip()
    if not secret_hash:
        logger.warning("Flutterwave webhook secret hash is not configured.")
        return False
    if not signature:
        return False
    if hmac.compare_digest(secret_hash, signature):
        return True
    expected_base64_signature = base64.b64encode(
        hmac.new(secret_hash.encode("utf-8"), msg=raw_body, digestmod=hashlib.sha256).digest()
    ).decode("utf-8")
    if hmac.compare_digest(expected_base64_signature, signature):
        return True
    expected_hex_signature = hmac.new(
        secret_hash.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected_hex_signature, signature)


def query_transaction(*, reference: str, transaction_id: str | None = None) -> dict[str, Any] | None:
    if should_use_v4():
        ensure_v4_configured()
        from .v4 import _query_transaction_v4
        return _query_transaction_v4(reference=reference, transaction_id=transaction_id)
    from .v3 import _query_transaction_v3
    return _query_transaction_v3(reference=reference, transaction_id=transaction_id)


def flutterwave_api_version() -> str:
    raw_version = str(getattr(settings, "FLUTTERWAVE_API_VERSION", "v3") or "v3").strip().lower()
    version = raw_version if raw_version.startswith("v") else f"v{raw_version}"
    if version not in {"v3", "v4"}:
        raise FlutterwaveError("FLUTTERWAVE_API_VERSION must be either v3 or v4.")
    return version


def should_use_v4() -> bool:
    return flutterwave_api_version() == "v4"


def ensure_v4_configured() -> None:
    if not should_use_v4():
        raise FlutterwaveError("Flutterwave v4 is not enabled.")
    missing = [
        name
        for name, value in {
            "FLUTTERWAVE_CLIENT_ID": getattr(settings, "FLUTTERWAVE_CLIENT_ID", ""),
            "FLUTTERWAVE_CLIENT_SECRET": getattr(settings, "FLUTTERWAVE_CLIENT_SECRET", ""),
            "FLUTTERWAVE_API_BASE_URL": getattr(settings, "FLUTTERWAVE_API_BASE_URL", ""),
        }.items()
        if not str(value or "").strip()
    ]
    if missing:
        raise FlutterwaveError(f"Flutterwave v4 is missing configuration: {', '.join(missing)}.")


def extract_provider_data(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {}
    data = payload.get("data") or {}
    if isinstance(data, list):
        return data[0] if data else {}
    return data if isinstance(data, dict) else {}


def extract_reference(payload: dict[str, Any] | None) -> str:
    data = extract_provider_data(payload)
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}

    for container in (data, meta, payload or {}):
        for key in ("tx_ref", "txRef", "reference", "flw_ref", "flwRef"):
            value = str(container.get(key) or "").strip()
            if value:
                return value
    return ""


def extract_customer_email(payload: dict[str, Any] | None) -> str:
    data = extract_provider_data(payload)
    customer = data.get("customer") if isinstance(data.get("customer"), dict) else {}
    billing_details = data.get("billing_details") if isinstance(data.get("billing_details"), dict) else {}

    for container in (billing_details, customer, data):
        value = str(container.get("email") or container.get("customer_email") or "").strip()
        if value:
            return value
    return ""


def extract_provider_transaction_id(payload: dict[str, Any] | None) -> str:
    data = extract_provider_data(payload)
    return str(data.get("id") or "").strip()


def extract_payment_state(payload: dict[str, Any] | None) -> str:
    status_value = str(extract_provider_data(payload).get("status") or (payload or {}).get("status") or "").strip().lower()
    if status_value in {"success", "successful", "succeeded", "completed"}:
        return "completed"
    if status_value in {"cancelled", "canceled"}:
        return "cancelled"
    if status_value in {"failed", "failure", "abandoned", "expired"}:
        return "failed"
    if status_value in {"pending", "processing", "ongoing", "authorized", "active"}:
        return "processing"
    return "pending"


def map_redirect_status(status: str | None) -> str | None:
    normalized = str(status or "").strip().lower()
    if normalized in {"success", "successful", "succeeded", "completed"}:
        return "completed"
    if normalized in {"cancelled", "canceled"}:
        return "cancelled"
    if normalized in {"failed", "failure", "abandoned", "expired"}:
        return "failed"
    if normalized in {"pending", "processing", "ongoing", "authorized", "active"}:
        return "processing"
    return None


def extract_payment_channel_details(payload: dict[str, Any] | None) -> tuple[str, str]:
    data = extract_provider_data(payload)
    authorization = data.get("authorization") if isinstance(data.get("authorization"), dict) else {}
    card = data.get("card") if isinstance(data.get("card"), dict) else {}
    payment_method = data.get("payment_method") if isinstance(data.get("payment_method"), dict) else {}
    payment_method_card = payment_method.get("card") if isinstance(payment_method.get("card"), dict) else {}

    bank_name = str(
        authorization.get("bank")
        or authorization.get("issuer")
        or card.get("issuer")
        or card.get("bank")
        or payment_method_card.get("issuer")
        or payment_method_card.get("bank")
        or payment_method_card.get("network")
        or ""
    ).strip()
    card_last4 = str(
        authorization.get("last4")
        or authorization.get("last_4digits")
        or card.get("last4")
        or card.get("last_4digits")
        or payment_method_card.get("last4")
        or payment_method_card.get("last_4digits")
        or ""
    ).strip()
    return bank_name, card_last4[-4:]


_URL_FIELD_NAMES = ("redirect_url", "authorization_url", "checkout_url", "url", "link")


def _find_url_field(value: Any, depth: int = 0) -> str:
    if depth > 4:
        return ""
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped.startswith(("http://", "https://")) else ""
    if not isinstance(value, dict):
        return ""
    for key in _URL_FIELD_NAMES:
        found = _find_url_field(value.get(key), depth + 1)
        if found:
            return found
    for child in value.values():
        if isinstance(child, dict):
            found = _find_url_field(child, depth + 1)
            if found:
                return found
    return ""


def extract_next_action_url(payload: dict[str, Any] | None) -> str:
    data = extract_provider_data(payload)
    next_action = data.get("next_action") if isinstance(data.get("next_action"), dict) else {}
    found = _find_url_field(next_action)
    if found:
        return found
    # The charge's top-level redirect_url is the merchant return URL, not a customer action.
    return _find_url_field({key: data.get(key) for key in _URL_FIELD_NAMES if key != "redirect_url"})


def extract_payment_instruction(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = extract_provider_data(payload)
    next_action = data.get("next_action") if isinstance(data.get("next_action"), dict) else {}
    instruction = next_action.get("payment_instruction")
    return instruction if isinstance(instruction, dict) else {}


def extract_payment_method_card_details(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = extract_provider_data(payload)
    payment_method = data.get("payment_method") if isinstance(data.get("payment_method"), dict) else {}
    card = data.get("card") if isinstance(data.get("card"), dict) else {}
    if not card and isinstance(payment_method.get("card"), dict):
        card = payment_method["card"]

    return {
        "id": str(
            data.get("id")
            or data.get("payment_method_id")
            or payment_method.get("id")
            or ""
        ).strip(),
        "customer_id": str(data.get("customer_id") or payment_method.get("customer_id") or "").strip(),
        "type": str(data.get("type") or payment_method.get("type") or "card").strip(),
        "first6": str(card.get("first6") or card.get("first_6digits") or "").strip()[:6],
        "last4": str(card.get("last4") or card.get("last_4digits") or "").strip()[-4:],
        "network": str(card.get("network") or card.get("brand") or "").strip(),
        "expiry_month": card.get("expiry_month"),
        "expiry_year": card.get("expiry_year"),
    }


def format_customer_phone_number(phone_number: str) -> str:
    digits = "".join(character for character in str(phone_number or "") if character.isdigit())
    if not digits:
        return ""
    if digits.startswith("234"):
        return f"+{digits}" if len(digits) == 13 else ""
    if digits.startswith("0"):
        return f"+234{digits[1:]}" if len(digits) == 11 else ""
    return f"+234{digits}" if len(digits) == 10 else ""


def extract_resource_id(payload: dict[str, Any] | None) -> str:
    data = extract_provider_data(payload)
    for container in (data, payload or {}):
        for key in ("id", "customer_id", "account_id", "recipient_id", "uuid"):
            value = str(container.get(key) or "").strip()
            if value:
                return value
    return ""


def extract_virtual_account_details(payload: dict[str, Any] | None) -> dict[str, str]:
    data = extract_provider_data(payload)
    account = data.get("account") if isinstance(data.get("account"), dict) else {}
    bank = data.get("bank") if isinstance(data.get("bank"), dict) else {}
    return {
        "id": str(data.get("id") or data.get("account_id") or data.get("virtual_account_id") or "").strip(),
        "account_number": str(
            data.get("account_number")
            or data.get("accountNumber")
            or account.get("account_number")
            or account.get("number")
            or ""
        ).strip(),
        "bank_name": str(
            data.get("bank_name")
            or data.get("account_bank_name")
            or bank.get("name")
            or account.get("bank_name")
            or ""
        ).strip(),
        "bank_code": str(data.get("bank_code") or bank.get("code") or account.get("bank_code") or "").strip(),
        "reference": str(data.get("reference") or data.get("tx_ref") or "").strip(),
        "account_name": str(
            data.get("account_name")
            or data.get("account_display_name")
            or account.get("account_name")
            or ""
        ).strip(),
        "account_type": str(data.get("account_type") or "").strip(),
        "status": str(data.get("status") or "").strip(),
        "account_expiration_datetime": str(
            data.get("account_expiration_datetime")
            or data.get("expiry_datetime")
            or data.get("expires_at")
            or ""
        ).strip(),
        "note": str(data.get("note") or "").strip(),
    }


def _normalize_account_number(value: Any) -> str:
    return "".join(character for character in str(value or "") if character.isdigit())


def _extract_gateway_error_message(body: str, fallback: str) -> str:
    normalized_body = str(body or "").strip()
    if not normalized_body:
        return fallback
    try:
        payload = json.loads(normalized_body)
    except json.JSONDecodeError:
        if "<html" in normalized_body.lower() or "<!doctype" in normalized_body.lower():
            return fallback
        return normalized_body[:500]

    if isinstance(payload, dict):
        validation_errors = payload.get("validation_errors")
        if not isinstance(validation_errors, list):
            error_payload = payload.get("error")
            validation_errors = (
                error_payload.get("validation_errors")
                if isinstance(error_payload, dict)
                else None
            )
        if isinstance(validation_errors, list) and validation_errors:
            messages = []
            for item in validation_errors:
                if not isinstance(item, dict):
                    continue
                field_name = str(item.get("field_name") or item.get("field") or "").strip()
                message = str(item.get("message") or "").strip()
                if field_name and message:
                    messages.append(f"{field_name} {message}")
                elif message:
                    messages.append(message)
            if messages:
                return f"Request is not valid: {'; '.join(messages)}"
        for key in ("message", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        error = payload.get("error")
        if isinstance(error, dict):
            nested_message = error.get("message")
            if isinstance(nested_message, str) and nested_message.strip():
                return nested_message.strip()
    return normalized_body
