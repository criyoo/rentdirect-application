from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from decimal import Decimal
from typing import Any
from urllib.parse import quote, urlencode

import requests
from django.conf import settings

from .common import (
    REQUEST_TIMEOUT_SECONDS,
    FlutterwaveError,
    _extract_gateway_error_message,
    _normalize_account_number,
    ensure_v4_configured,
    extract_provider_data,
    format_customer_phone_number,
    nigerian_payout_bank_code_candidates,
    normalize_decimal_amount,
    normalize_provider_transaction_id,
    resolve_nigerian_payout_bank_code,
    should_use_v4,
)
from .v3 import _request_json_v3

logger = logging.getLogger(__name__)

_V4_ACCESS_TOKEN = ""
_V4_ACCESS_TOKEN_EXPIRES_AT = 0.0


def list_banks(*, country: str = "NG") -> list[dict[str, Any]]:
    ensure_v4_configured()
    payload = _request_json_v4(
        method="GET",
        path=f"/banks?country={quote(str(country or 'NG').strip() or 'NG', safe='')}",
    )
    data = (payload or {}).get("data")
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def create_customer(
    *,
    email: str,
    full_name: str,
    phone_number: str = "",
    metadata: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    ensure_v4_configured()
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


def create_card_payment_method(
    *,
    customer_id: str,
    encrypted_card: dict[str, Any],
    metadata: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    ensure_v4_configured()
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


def create_payment_method(
    *,
    customer_id: str,
    payment_method: dict[str, Any],
    metadata: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    ensure_v4_configured()
    if not isinstance(payment_method, dict) or not str(payment_method.get("type") or "").strip():
        raise FlutterwaveError("A valid Flutterwave v4 payment method is required.")
    payload = dict(payment_method)
    if customer_id:
        payload["customer_id"] = customer_id
    payload["meta"] = {key: str(value) for key, value in (metadata or {}).items()}
    return _request_json_v4(
        method="POST",
        path="/payment-methods",
        payload=payload,
        idempotency_key=idempotency_key,
    )


def update_charge(
    *,
    charge_id: str,
    authorization: dict[str, Any],
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    ensure_v4_configured()
    normalized_charge_id = str(charge_id or "").strip()
    if not normalized_charge_id:
        raise FlutterwaveError("Flutterwave charge id is required for authorization.")
    if not isinstance(authorization, dict) or not str(authorization.get("type") or "").strip():
        raise FlutterwaveError("A valid Flutterwave authorization payload is required.")
    return _request_json_v4(
        method="PUT",
        path=f"/charges/{quote(normalized_charge_id, safe='')}",
        payload={"authorization": authorization},
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
    subaccounts: list[dict[str, Any]] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    ensure_v4_configured()
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
    if subaccounts:
        payload["subaccounts"] = subaccounts

    return _request_json_v4(
        method="POST",
        path="/charges",
        payload=payload,
        idempotency_key=idempotency_key or reference,
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
    last_error = None
    bank_payload = {
        "account_number": account_number,
    }
    for candidate_bank_code in nigerian_payout_bank_code_candidates(bank_name, bank_code):
        try:
            existing_recipient = find_transfer_recipient(
                account_number=account_number,
                bank_name=bank_name,
                bank_code=candidate_bank_code,
            )
        except FlutterwaveError:
            existing_recipient = None
        if existing_recipient is not None:
            return existing_recipient

        payload = {
            "type": "bank_ngn",
            "bank": {**bank_payload, "code": candidate_bank_code},
        }
        if national_identification:
            payload["national_identification"] = national_identification
        if address:
            payload["address"] = address
        try:
            return _request_json_v4(
                method="POST",
                path="/transfers/recipients",
                payload=payload,
                idempotency_key=idempotency_key,
            )
        except FlutterwaveError as exc:
            last_error = exc
            if "recipient already exists" in str(exc).lower():
                try:
                    existing_recipient = find_transfer_recipient(
                        account_number=account_number,
                        bank_name=bank_name,
                        bank_code=candidate_bank_code,
                    )
                except FlutterwaveError:
                    existing_recipient = None
                if existing_recipient is not None:
                    return existing_recipient
            if "invalid bank code" not in str(exc).lower() and "bank.code" not in str(exc).lower():
                raise
    if last_error:
        raise last_error
    raise FlutterwaveError("Flutterwave transfer recipient requires a bank code.")


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
    bank_code = resolve_nigerian_payout_bank_code(bank_name, bank_code)
    if should_use_v4():
        if not recipient_id:
            raise FlutterwaveError("Flutterwave v4 bank transfers require a transfer recipient id.")
        payload: dict[str, Any] = {
            "action": "instant",
            "reference": reference,
            "narration": narration[:100],
            "payment_instruction": {
                "source_currency": currency,
                "destination_currency": currency,
                "amount": {
                    "value": float(normalize_decimal_amount(amount)),
                    "applies_to": "destination_currency",
                },
                "recipient_id": recipient_id,
            },
            "meta": {
                "account_name": account_name,
                "account_number": account_number,
                "bank_name": bank_name,
                "bank_code": bank_code,
            },
        }
        callback_url = str(getattr(settings, "FLUTTERWAVE_WEBHOOK_URL", "") or "").strip()
        if callback_url:
            payload["callback_url"] = callback_url
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


def retrieve_bank_transfer(*, transfer_id: str) -> dict[str, Any]:
    normalized_transfer_id = str(transfer_id or "").strip()
    if not normalized_transfer_id:
        raise FlutterwaveError("Flutterwave transfer id is required to retrieve a transfer.")

    path = f"/transfers/{quote(normalized_transfer_id, safe='')}"
    if should_use_v4():
        ensure_v4_configured()
        return _request_json_v4(method="GET", path=path)
    return _request_json_v3(method="GET", path=path)


def _transfer_recipient_matches(
    recipient: dict[str, Any],
    *,
    account_number: str,
    bank_codes: list[str],
) -> bool:
    bank = recipient.get("bank") if isinstance(recipient.get("bank"), dict) else {}
    recipient_account_number = _normalize_account_number(
        recipient.get("account_number")
        or recipient.get("accountNumber")
        or bank.get("account_number")
        or bank.get("accountNumber")
    )
    normalized_account_number = _normalize_account_number(account_number)
    if not normalized_account_number or recipient_account_number != normalized_account_number:
        return False

    recipient_bank_code = str(
        recipient.get("bank_code")
        or recipient.get("bankCode")
        or bank.get("code")
        or bank.get("bank_code")
        or ""
    ).strip()
    return bool(recipient_bank_code and bank_codes and recipient_bank_code in bank_codes)


def find_transfer_recipient(
    *,
    account_number: str,
    bank_name: str,
    bank_code: str = "",
) -> dict[str, Any] | None:
    candidate_bank_codes = nigerian_payout_bank_code_candidates(bank_name, bank_code)
    next_cursor = ""
    visited_cursors: set[str] = set()

    while True:
        query = {"size": 50}
        if next_cursor:
            query["next"] = next_cursor
        payload = _request_json_v4(
            method="GET",
            path=f"/transfers/recipients?{urlencode(query)}",
        )
        raw_data = payload.get("data") if isinstance(payload, dict) else None
        cursor_payload = raw_data if isinstance(raw_data, dict) else payload
        if isinstance(raw_data, list):
            recipients = raw_data
        elif isinstance(raw_data, dict):
            recipients = None
            for collection_key in ("items", "recipients", "results", "data"):
                if collection_key in raw_data:
                    recipients = raw_data[collection_key]
                    break
            if recipients is None and raw_data.get("id"):
                recipients = [raw_data]
        else:
            recipients = None
        if not isinstance(recipients, list):
            raise FlutterwaveError("Flutterwave returned an invalid transfer recipient list.")

        recipient = next(
            (
                item
                for item in recipients
                if isinstance(item, dict)
                and _transfer_recipient_matches(
                    item,
                    account_number=account_number,
                    bank_codes=candidate_bank_codes,
                )
            ),
            None,
        )
        if recipient is not None:
            return {"status": "success", "data": recipient}

        metadata = payload.get("meta") if isinstance(payload, dict) else None
        page_info = metadata.get("page_info") if isinstance(metadata, dict) else None
        cursor = cursor_payload.get("cursor") if isinstance(cursor_payload, dict) else None
        next_cursor = str(
            (cursor.get("next") if isinstance(cursor, dict) else None)
            or (page_info.get("next") if isinstance(page_info, dict) else None)
            or (metadata.get("next") if isinstance(metadata, dict) else None)
            or payload.get("next")
            or ""
        ).strip()
        if not next_cursor or next_cursor in visited_cursors:
            return None
        visited_cursors.add(next_cursor)


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


def _request_json_v4(
    *,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    response = None
    last_network_error: requests.RequestException | None = None
    request_idempotency_key = idempotency_key or uuid.uuid4().hex
    for _attempt in range(2):
        try:
            response = requests.request(
                method=method,
                url=f"{str(settings.FLUTTERWAVE_API_BASE_URL).rstrip('/')}{path}",
                json=payload,
                headers=_build_v4_headers(method=method, idempotency_key=request_idempotency_key),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            last_network_error = exc
            continue
        if response.status_code < 500:
            break
    if response is None:
        raise FlutterwaveError("Unable to reach Flutterwave payment services right now.") from last_network_error
    if response.status_code >= 400:
        raise FlutterwaveError(_extract_gateway_error_message(response.text, "Flutterwave request failed."))
    try:
        return response.json()
    except json.JSONDecodeError as exc:
        raise FlutterwaveError("Flutterwave returned an invalid response.") from exc


def _build_v4_headers(*, method: str, idempotency_key: str | None = None) -> dict[str, str]:
    trace_id = idempotency_key or hashlib.sha256(str(time.time()).encode("utf-8")).hexdigest()
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_get_v4_access_token()}",
        "User-Agent": "RentDirectPayments/1.0",
        "X-Trace-Id": trace_id[:255],
    }
    if method != "GET":
        headers["X-Idempotency-Key"] = trace_id[:255]
    return headers


def _split_phone_number(phone_number: str) -> dict[str, str]:
    normalized = str(phone_number or "").strip()
    if normalized.startswith("+234"):
        return {"country_code": "234", "number": normalized[4:]}
    if normalized.startswith("+"):
        return {"country_code": normalized[1:4], "number": normalized[4:]}
    return {"country_code": "234", "number": "".join(character for character in normalized if character.isdigit())}


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
