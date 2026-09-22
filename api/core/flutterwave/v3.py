from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from typing import Any
from urllib.parse import urlencode

import requests
from django.conf import settings

from ..financial_constants import ZERO_AMOUNT
from .common import (
    REQUEST_TIMEOUT_SECONDS,
    FlutterwaveError,
    _extract_gateway_error_message,
    collection_subaccount_bank_code_candidates,
    extract_provider_data,
    format_customer_phone_number,
    normalize_decimal_amount,
    normalize_provider_transaction_id,
)


def payment_options_for_method(method: str | None) -> str:
    normalized = str(method or "").strip().lower()
    if normalized == "card":
        return "card"
    if normalized == "bank":
        return "banktransfer,account,ussd"
    return "card,banktransfer,account,ussd"


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
    subaccounts: list[dict[str, Any]] | None = None,
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
    if subaccounts:
        flutterwave_payload["subaccounts"] = subaccounts

    return {
        "checkout_mode": "inline",
        "redirect_url": redirect_url,
        "flutterwave": flutterwave_payload,
    }


def extract_subaccount_id(payload: dict[str, Any] | None) -> str:
    data = extract_provider_data(payload)
    for container in (data, payload or {}):
        for key in ("subaccount_id", "subAccountId", "account_id"):
            value = str(container.get(key) or "").strip()
            if value:
                return value
        value = str(container.get("id") or "").strip()
        if value.startswith("RS_"):
            return value
    return ""


def create_collection_subaccount(
    *,
    bank_code: str,
    account_number: str,
    business_name: str,
    business_email: str = "",
    business_mobile: str = "",
    country: str = "NG",
    split_type: str = "flat",
    split_value: str | Decimal = "0",
) -> dict[str, Any]:
    try:
        normalized_split_value = Decimal(str(split_value or ZERO_AMOUNT))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise FlutterwaveError("Flutterwave subaccount split value is invalid.") from exc

    payload: dict[str, Any] = {
        "account_bank": str(bank_code or "").strip(),
        "account_number": str(account_number or "").strip(),
        "business_name": str(business_name or "").strip(),
        "business_mobile": format_customer_phone_number(business_mobile or "") or str(business_mobile or "").strip(),
        "country": str(country or "NG").strip() or "NG",
        "split_type": str(split_type or "flat").strip() or "flat",
        "split_value": float(normalized_split_value),
    }
    missing_fields = [key for key in ("account_bank", "account_number", "business_name", "business_mobile") if not payload[key]]
    if missing_fields:
        raise FlutterwaveError(f"Flutterwave subaccount requires: {', '.join(missing_fields)}.")
    if business_email:
        payload["business_email"] = str(business_email).strip()
    response = _request_json_v3(method="POST", path="/subaccounts", payload=payload)
    if str(response.get("status") or "").lower() not in {"success", "successful"}:
        raise FlutterwaveError(
            _extract_gateway_error_message(
                json.dumps(response),
                "Flutterwave subaccount request failed.",
            )
        )
    return response


def list_collection_subaccounts(*, account_number: str = "") -> list[dict[str, Any]]:
    query = urlencode({"account_number": account_number}) if account_number else ""
    payload = _request_json_v3(method="GET", path=f"/subaccounts?{query}" if query else "/subaccounts")
    if str(payload.get("status") or "").lower() not in {"success", "successful"}:
        raise FlutterwaveError(
            _extract_gateway_error_message(
                json.dumps(payload),
                "Flutterwave subaccount lookup failed.",
            )
        )
    data = payload.get("data") if isinstance(payload, dict) else []
    if isinstance(data, dict):
        nested_data = data.get("data")
        if isinstance(nested_data, list):
            return [item for item in nested_data if isinstance(item, dict)]
        return [data]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def find_collection_subaccount(*, bank_code: str, account_number: str) -> dict[str, Any] | None:
    normalized_account_number = str(account_number or "").strip()
    normalized_bank_code = str(bank_code or "").strip()
    if not normalized_account_number:
        return None
    for subaccount in list_collection_subaccounts(account_number=normalized_account_number):
        subaccount_account_number = str(subaccount.get("account_number") or "").strip()
        subaccount_bank_code = str(
            subaccount.get("account_bank")
            or subaccount.get("bank_code")
            or subaccount.get("bank")
            or ""
        ).strip()
        if subaccount_account_number != normalized_account_number:
            continue
        if normalized_bank_code and subaccount_bank_code and subaccount_bank_code != normalized_bank_code:
            continue
        if extract_subaccount_id({"data": subaccount}):
            return subaccount
    return None


@lru_cache(maxsize=32)
def get_or_create_collection_subaccount_id(
    *,
    bank_code: str,
    account_number: str,
    business_name: str,
    business_email: str = "",
    business_mobile: str = "",
    country: str = "NG",
    split_type: str = "flat",
    split_value: str = "0",
) -> str:
    last_error: FlutterwaveError | None = None
    for candidate_bank_code in collection_subaccount_bank_code_candidates(bank_code):
        try:
            response = create_collection_subaccount(
                bank_code=candidate_bank_code,
                account_number=account_number,
                business_name=business_name,
                business_email=business_email,
                business_mobile=business_mobile,
                country=country,
                split_type=split_type,
                split_value=split_value,
            )
        except FlutterwaveError as exc:
            last_error = exc
            if "already exists" in str(exc).lower():
                try:
                    existing_subaccount = find_collection_subaccount(
                        bank_code=candidate_bank_code,
                        account_number=account_number,
                    )
                except FlutterwaveError as lookup_error:
                    last_error = lookup_error
                    continue
                subaccount_id = extract_subaccount_id({"data": existing_subaccount})
                if subaccount_id:
                    return subaccount_id
            continue

        subaccount_id = extract_subaccount_id(response)
        if subaccount_id:
            return subaccount_id
        last_error = FlutterwaveError("Flutterwave did not return a subscription subaccount id.")
        break

    if last_error:
        raise last_error
    raise FlutterwaveError("Flutterwave bank code is required to create a subscription subaccount.")


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
