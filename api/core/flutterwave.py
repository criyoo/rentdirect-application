from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

_V4_ACCESS_TOKEN = ""
_V4_ACCESS_TOKEN_EXPIRES_AT = 0.0
REQUEST_TIMEOUT_SECONDS = 30


class FlutterwaveError(ValueError):
    pass


def append_query_params(url: str, **params: Any) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key, value in params.items():
        if value is not None and str(value).strip():
            query[key] = str(value)
    return urlunparse(parsed._replace(query=urlencode(query)))


def normalize_decimal_amount(value: Any) -> Decimal:
    return Decimal(str(value or "0")).quantize(Decimal("0.01"))


def normalize_provider_transaction_id(value: Any) -> str | None:
    normalized = str(value or "").strip()
    if not normalized or normalized.lower() in {"null", "none", "undefined"}:
        return None
    return normalized


def payment_options_for_method(method: str | None) -> str:
    normalized = str(method or "").strip().lower()
    if normalized == "card":
        return "card"
    if normalized == "bank":
        return "banktransfer,bank,ussd"
    return "card,banktransfer,bank,ussd"


def resolve_checkout_public_key() -> str:
    return str(
        getattr(settings, "FLUTTERWAVE_PUBLIC_KEY", "")
        or getattr(settings, "FLUTTERWAVE_CLIENT_ID", "")
        or ""
    ).strip()


def build_checkout_payload(
    *,
    reference: str,
    amount: Decimal,
    currency: str,
    email: str,
    redirect_url: str,
    payment_method: str | None,
    title: str,
    description: str,
    metadata: dict[str, Any] | None = None,
    customer_name: str | None = None,
    customer_phone: str | None = None,
    webhook_url: str | None = None,
) -> dict[str, Any]:
    public_key = resolve_checkout_public_key()
    if not public_key:
        raise FlutterwaveError("Flutterwave checkout is not configured on the server.")

    customer = {
        "email": email,
        "name": (customer_name or email.split("@", 1)[0]).strip(),
    }
    phone_number = format_customer_phone_number(customer_phone or "")
    if phone_number:
        customer["phone_number"] = phone_number

    flutterwave_payload: dict[str, Any] = {
        "client_id": public_key,
        "tx_ref": reference,
        "amount": float(normalize_decimal_amount(amount)),
        "currency": currency,
        "payment_options": payment_options_for_method(payment_method),
        "redirect_url": redirect_url,
        "customer": customer,
        "customizations": {
            "title": title,
            "description": description,
        },
        "meta": {key: str(value) for key, value in (metadata or {}).items()},
    }
    if webhook_url:
        flutterwave_payload["webhook_url"] = webhook_url

    return {
        "checkout_mode": "inline",
        "redirect_url": redirect_url,
        "flutterwave": flutterwave_payload,
    }


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
        try:
            payload = _query_transaction_v4(reference=reference, transaction_id=transaction_id)
            if payload is not None:
                return payload
        except FlutterwaveError:
            if not str(getattr(settings, "FLUTTERWAVE_SECRET_KEY", "") or "").strip():
                raise

    return _query_transaction_v3(reference=reference, transaction_id=transaction_id)


def should_use_v4() -> bool:
    return bool(
        str(getattr(settings, "FLUTTERWAVE_CLIENT_ID", "") or "").strip()
        and str(getattr(settings, "FLUTTERWAVE_CLIENT_SECRET", "") or "").strip()
        and str(getattr(settings, "FLUTTERWAVE_API_BASE_URL", "") or "").strip()
    )


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


def extract_next_action_url(payload: dict[str, Any] | None) -> str:
    data = extract_provider_data(payload)
    next_action = data.get("next_action") if isinstance(data.get("next_action"), dict) else {}
    redirect_url = next_action.get("redirect_url")
    if isinstance(redirect_url, dict):
        return str(redirect_url.get("url") or "").strip()
    return str(redirect_url or "").strip()


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


def _query_transaction_v3(*, reference: str, transaction_id: str | None = None) -> dict[str, Any] | None:
    secret_key = str(getattr(settings, "FLUTTERWAVE_SECRET_KEY", "") or "").strip()
    if not secret_key:
        raise FlutterwaveError("Flutterwave v3 secret key is not configured on the server.")

    base_url = str(
        getattr(settings, "FLUTTERWAVE_V3_API_BASE_URL", "")
        or "https://api.flutterwave.com/v3"
    ).rstrip("/")
    normalized_transaction_id = normalize_provider_transaction_id(transaction_id)
    if normalized_transaction_id:
        verify_url = f"{base_url}/transactions/{normalized_transaction_id}/verify"
    else:
        verify_url = f"{base_url}/transactions/verify_by_reference?{urlencode({'tx_ref': reference})}"

    try:
        response = requests.get(
            verify_url,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {secret_key}",
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise FlutterwaveError("Unable to reach Flutterwave payment services right now.") from exc

    if response.status_code >= 400:
        raise FlutterwaveError(_extract_gateway_error_message(response.text, "Flutterwave payment verification failed."))

    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise FlutterwaveError("Flutterwave returned an invalid payment verification response.") from exc

    if payload.get("status") != "success":
        return None
    data = payload.get("data") or {}
    if not isinstance(data, dict) or not data:
        return None

    return {
        "status": payload.get("status"),
        "message": payload.get("message"),
        "data": {
            **data,
            "tx_ref": str(data.get("tx_ref") or reference).strip(),
            "reference": str(data.get("tx_ref") or reference).strip(),
        },
    }


def _query_transaction_v4(*, reference: str, transaction_id: str | None = None) -> dict[str, Any] | None:
    normalized_transaction_id = normalize_provider_transaction_id(transaction_id)
    if normalized_transaction_id:
        payload = _request_json_v4(
            method="GET",
            path=f"/charges/{normalized_transaction_id}",
        )
        if payload.get("status") != "success":
            return None
        return payload

    payload = _request_json_v4(
        method="GET",
        path=f"/charges?{urlencode({'reference': reference, 'size': 10})}",
    )
    if payload.get("status") != "success":
        return None

    data = payload.get("data") or []
    if not isinstance(data, list):
        return payload

    matching_charge = next(
        (
            item
            for item in data
            if str((item or {}).get("tx_ref") or (item or {}).get("reference") or "").strip() == reference
        ),
        None,
    )
    if matching_charge is None:
        return None

    return {
        "status": payload.get("status"),
        "message": payload.get("message"),
        "data": matching_charge,
    }


def create_customer(
    *,
    email: str,
    full_name: str,
    phone_number: str = "",
    metadata: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    name_parts = [part for part in str(full_name or "").strip().split() if part]
    first_name = name_parts[0] if name_parts else str(email).split("@", 1)[0]
    last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else first_name
    payload: dict[str, Any] = {
        "email": email,
        "name": {
            "first": first_name,
            "last": last_name,
        },
        "meta": {key: str(value) for key, value in (metadata or {}).items()},
    }
    formatted_phone = format_customer_phone_number(phone_number)
    if formatted_phone:
        payload["phone"] = _split_phone_number(formatted_phone)

    try:
        return _request_json_v4(
            method="POST",
            path="/customers",
            payload=payload,
            idempotency_key=idempotency_key,
        )
    except FlutterwaveError as exc:
        if "customer already exists" not in str(exc).lower():
            raise
        existing_customer = find_customer_by_email(email)
        if not existing_customer:
            raise
        return {
            "status": "success",
            "message": "Customer already exists",
            "data": existing_customer,
        }


def create_card_payment_method(
    *,
    customer_id: str,
    encrypted_card: dict[str, Any],
    metadata: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    required_fields = (
        "encrypted_card_number",
        "encrypted_expiry_month",
        "encrypted_expiry_year",
        "encrypted_cvv",
        "nonce",
    )
    card_payload = {field: str(encrypted_card.get(field) or "").strip() for field in required_fields}
    missing_fields = [field for field, value in card_payload.items() if not value]
    if missing_fields:
        raise FlutterwaveError(f"Encrypted card payload is missing: {', '.join(missing_fields)}.")

    payload: dict[str, Any] = {
        "type": "card",
        "card": card_payload,
        "meta": {key: str(value) for key, value in (metadata or {}).items()},
    }
    if customer_id:
        payload["customer_id"] = customer_id

    return _request_json_v4(
        method="POST",
        path="/payment-methods",
        payload=payload,
        idempotency_key=idempotency_key,
    )


def create_charge(
    *,
    amount: Decimal,
    currency: str,
    reference: str,
    customer_id: str,
    payment_method_id: str,
    redirect_url: str = "",
    recurring: bool = False,
    metadata: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "reference": reference,
        "currency": currency,
        "customer_id": customer_id,
        "payment_method_id": payment_method_id,
        "amount": float(normalize_decimal_amount(amount)),
        "meta": {key: str(value) for key, value in (metadata or {}).items()},
    }
    if redirect_url:
        payload["redirect_url"] = redirect_url
    if recurring:
        payload["recurring"] = True

    return _request_json_v4(
        method="POST",
        path="/charges",
        payload=payload,
        idempotency_key=idempotency_key or reference,
    )


def find_customer_by_email(email: str) -> dict[str, Any] | None:
    normalized_email = str(email or "").strip().lower()
    if not normalized_email:
        return None

    payload = _request_json_v4(
        method="GET",
        path=f"/customers?{urlencode({'email': normalized_email})}",
    )
    data = payload.get("data") or []
    if not isinstance(data, list):
        return None
    return next(
        (
            customer
            for customer in data
            if isinstance(customer, dict)
            and str(customer.get("email") or "").strip().lower() == normalized_email
        ),
        None,
    )


def create_dynamic_virtual_account(
    *,
    reference: str,
    customer_id: str,
    amount: Decimal,
    currency: str,
    narration: str,
    expiry_seconds: int,
    bvn: str = "",
    nin: str = "",
    metadata: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    payload = {
        "reference": reference,
        "customer_id": customer_id,
        "amount": float(normalize_decimal_amount(amount)),
        "currency": currency,
        "account_type": "dynamic",
        "expiry": expiry_seconds,
        "meta": {key: str(value) for key, value in (metadata or {}).items()},
        "narration": narration[:100],
    }
    if str(bvn or "").strip():
        payload["bvn"] = str(bvn).strip()
    if str(nin or "").strip():
        payload["nin"] = str(nin).strip()
    return _request_json_v4(
        method="POST",
        path="/virtual-accounts",
        payload=payload,
        idempotency_key=idempotency_key,
    )


def create_transfer_recipient(
    *,
    full_name: str,
    phone_number: str,
    bank_name: str,
    account_number: str,
    bank_code: str = "",
    account_name: str = "",
    address: dict[str, Any] | None = None,
    national_identification: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    name_parts = [part for part in str(full_name or account_name or "RentDirect Recipient").strip().split() if part]
    first_name = name_parts[0] if name_parts else "RentDirect"
    last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else "Recipient"
    bank_payload = {
        "account_number": account_number,
        "account_name": account_name or full_name,
        "bank_name": bank_name,
        "country": "NG",
        "currency": "NGN",
    }
    if bank_code:
        bank_payload["code"] = bank_code
        bank_payload["bank_code"] = bank_code

    payload = {
        "name": {
            "first": first_name,
            "last": last_name,
        },
        "phone": _split_phone_number(format_customer_phone_number(phone_number or "08000000000")),
        "national_identification": national_identification or {"type": "bvn", "number": "00000000000"},
        "address": address or {
            "line1": "RentDirect",
            "city": "Lagos",
            "state": "Lagos",
            "country": "NG",
        },
        "bank": bank_payload,
    }
    return _request_json_v4(
        method="POST",
        path="/transfers/recipients",
        payload=payload,
        idempotency_key=idempotency_key,
    )


def create_bank_transfer(
    *,
    amount: Decimal,
    currency: str,
    reference: str,
    narration: str,
    recipient_id: str = "",
    bank_name: str = "",
    bank_code: str = "",
    account_number: str = "",
    account_name: str = "",
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    if recipient_id and should_use_v4():
        try:
            payload: dict[str, Any] = {
                "amount": float(normalize_decimal_amount(amount)),
                "currency": currency,
                "reference": reference,
                "narration": narration[:100],
                "recipient_id": recipient_id,
                "recipient": {"id": recipient_id},
                "meta": {
                    "account_name": account_name,
                    "account_number": account_number,
                    "bank_name": bank_name,
                    "bank_code": bank_code,
                },
            }
            response = _request_json_v4(
                method="POST",
                path="/transfers",
                payload=payload,
                idempotency_key=idempotency_key or reference,
            )
            status = str(response.get("status") or "").lower()
            if status and status not in {"success", "successful"}:
                raise FlutterwaveError(_extract_gateway_error_message(json.dumps(response), "Flutterwave transfer request failed."))
            return response
        except FlutterwaveError:
            if not bank_code:
                raise

    if not bank_code:
        raise FlutterwaveError("Flutterwave bank transfer requires a bank code for v3 payout fallback.")

    response = _request_json_v3(
        method="POST",
        path="/transfers",
        payload={
            "account_bank": bank_code,
            "account_number": account_number,
            "amount": float(normalize_decimal_amount(amount)),
            "narration": narration[:100],
            "currency": currency,
            "reference": reference,
            "debit_currency": currency,
        },
    )
    if str(response.get("status") or "").lower() not in {"success", "successful"}:
        raise FlutterwaveError(_extract_gateway_error_message(json.dumps(response), "Flutterwave transfer request failed."))
    return response


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
    }


def _request_json_v4(
    *,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    response = requests.request(
        method=method,
        url=f"{str(settings.FLUTTERWAVE_API_BASE_URL).rstrip('/')}{path}",
        json=payload,
        headers=_build_v4_headers(method=method, idempotency_key=idempotency_key),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code >= 400:
        raise FlutterwaveError(_extract_gateway_error_message(response.text, "Flutterwave request failed."))
    try:
        return response.json()
    except json.JSONDecodeError as exc:
        raise FlutterwaveError("Flutterwave returned an invalid response.") from exc


def _request_json_v3(*, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    secret_key = str(getattr(settings, "FLUTTERWAVE_SECRET_KEY", "") or "").strip()
    if not secret_key:
        raise FlutterwaveError("Flutterwave v3 secret key is not configured on the server.")

    response = requests.request(
        method=method,
        url=f"{str(settings.FLUTTERWAVE_V3_API_BASE_URL).rstrip('/')}{path}",
        json=payload,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {secret_key}",
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code >= 400:
        raise FlutterwaveError(_extract_gateway_error_message(response.text, "Flutterwave request failed."))
    try:
        return response.json()
    except json.JSONDecodeError as exc:
        raise FlutterwaveError("Flutterwave returned an invalid response.") from exc


def _build_v4_headers(*, method: str, idempotency_key: str | None = None) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_get_v4_access_token()}",
        "User-Agent": "RentDirectPayments/1.0",
    }
    if method != "GET":
        key = idempotency_key or hashlib.sha256(str(time.time()).encode("utf-8")).hexdigest()
        headers["X-Idempotency-Key"] = key[:255]
        headers["X-Trace-Id"] = key[:255]
    return headers


def _split_phone_number(phone_number: str) -> dict[str, str]:
    normalized = str(phone_number or "").strip()
    if normalized.startswith("+234"):
        return {"country_code": "+234", "number": normalized[4:]}
    if normalized.startswith("+"):
        return {"country_code": normalized[:4], "number": normalized[4:]}
    return {"country_code": "+234", "number": "".join(character for character in normalized if character.isdigit())}


def _get_v4_access_token() -> str:
    global _V4_ACCESS_TOKEN
    global _V4_ACCESS_TOKEN_EXPIRES_AT

    current_time = time.time()
    if _V4_ACCESS_TOKEN and current_time < _V4_ACCESS_TOKEN_EXPIRES_AT:
        return _V4_ACCESS_TOKEN

    response = requests.post(
        str(settings.FLUTTERWAVE_TOKEN_URL),
        data={
            "client_id": settings.FLUTTERWAVE_CLIENT_ID,
            "client_secret": settings.FLUTTERWAVE_CLIENT_SECRET,
            "grant_type": "client_credentials",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code >= 400:
        raise FlutterwaveError(_extract_gateway_error_message(response.text, "Flutterwave authentication failed."))

    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise FlutterwaveError("Flutterwave returned an invalid authentication response.") from exc

    access_token = str(payload.get("access_token") or "").strip()
    expires_in = int(payload.get("expires_in") or 0)
    if not access_token or expires_in <= 0:
        raise FlutterwaveError("Flutterwave did not return a valid access token.")

    _V4_ACCESS_TOKEN = access_token
    _V4_ACCESS_TOKEN_EXPIRES_AT = current_time + max(expires_in - 30, 30)
    return _V4_ACCESS_TOKEN


def _extract_gateway_error_message(body: str, fallback: str) -> str:
    normalized_body = str(body or "").strip()
    if not normalized_body:
        return fallback
    try:
        payload = json.loads(normalized_body)
    except json.JSONDecodeError:
        return normalized_body

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
