from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.cache import cache
from django.utils.dateparse import parse_date
from rest_framework.exceptions import APIException, ValidationError

logger = logging.getLogger(__name__)


class DikriptVerificationUnavailable(APIException):
    status_code = 503
    default_detail = "Unable to verify the record right now. Try again later."
    default_code = "dikript_verification_unavailable"


class DikriptPhoneMismatch(Exception):
    def __init__(self, payload: dict[str, Any]):
        self.payload = payload
        super().__init__("Mobile number does not match the NIN record.")


def _dikript_key() -> str:
    return getattr(settings, "DIKRIPT_SECRET_KEY", "") or getattr(settings, "DIKRIPT_PUBLIC_KEY", "")


def _decode_response(raw_response: bytes, *, allow_empty: bool = False) -> dict[str, Any]:
    if not raw_response:
        if allow_empty:
            return {}
        raise DikriptVerificationUnavailable()

    try:
        return json.loads(raw_response.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning("Dikript verification returned invalid JSON.")
        raise DikriptVerificationUnavailable() from exc


def extract_dikript_message(payload: dict[str, Any]) -> str:
    return str(payload.get("message") or payload.get("error") or "").strip()


def dikript_get(path: str, query: dict[str, Any]) -> dict[str, Any]:
    base_url = (getattr(settings, "DIKRIPT_API_BASE_URL", "") or "").rstrip("/")
    api_key = _dikript_key()
    if not base_url or not api_key:
        logger.error("Dikript verification is not configured.")
        raise DikriptVerificationUnavailable()

    request = Request(
        url=f"{base_url}{path}?{urlencode(query)}",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-api-key": api_key,
        },
        method="GET",
    )

    try:
        with urlopen(request, timeout=getattr(settings, "DIKRIPT_TIMEOUT_SECONDS", 10)) as response:
            return _decode_response(response.read())
    except HTTPError as exc:
        payload = _decode_response(exc.read(), allow_empty=True)
        message = extract_dikript_message(payload)
        if exc.code in {400, 404} and message:
            return payload
        raise DikriptVerificationUnavailable(detail=message or None) from exc
    except URLError as exc:
        raise DikriptVerificationUnavailable() from exc


def dikript_lookup(*, verification_type: str, path: str, lookup_value: str, query: dict[str, Any]) -> dict[str, Any]:
    lookup_hash = hashlib.sha256(str(lookup_value).encode("utf-8")).hexdigest()
    cache_key = f"dikript_lookup:{verification_type}:{lookup_hash}"
    cached_payload = cache.get(cache_key)
    if isinstance(cached_payload, dict) and cached_payload.get("status") and isinstance(cached_payload.get("data"), dict):
        return cached_payload

    payload = dikript_get(path, query)
    if isinstance(payload, dict) and payload.get("status") and isinstance(payload.get("data"), dict):
        sanitized = json.loads(json.dumps(payload))
        data = sanitized.get("data")
        if isinstance(data, dict):
            data.pop("photo", None)
            data.pop("signature", None)
        cache.set(cache_key, sanitized, timeout=getattr(settings, "DIKRIPT_LOOKUP_CACHE_TIMEOUT_SECONDS", 86400))
        return sanitized
    return payload


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().upper().split())


def _normalize_region(value: Any) -> str:
    normalized = _normalize_text(value)
    normalized = re.sub(r"\bSTATE\b", "", normalized)
    return " ".join(normalized.split())


def _normalize_nationality(value: Any) -> str:
    normalized = _normalize_text(value)
    if normalized == "NIGERIAN":
        return "NIGERIA"
    return normalized


def _normalize_gender(value: Any) -> str:
    normalized = _normalize_text(value)
    return normalized[:1]


def _normalize_digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _normalize_phone(value: Any) -> str:
    digits = _normalize_digits(value)
    if digits.startswith("234"):
        digits = digits[3:]
    if digits.startswith("0"):
        digits = digits[1:]
    return digits


def _phone_matches(input_value: Any, api_value: Any) -> bool:
    input_phone = _normalize_phone(input_value)
    api_phone = _normalize_phone(api_value)
    return bool(input_phone) and bool(api_phone) and input_phone == api_phone


def _parse_date(value: Any):
    raw_value = str(value or "").strip()
    if not raw_value:
        return None
    parsed = parse_date(raw_value[:10])
    if parsed:
        return parsed
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw_value[:20], fmt).date()
        except ValueError:
            continue
    return None


def _company_name_key(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    normalized = re.sub(r"\b(limited|ltd|plc|llc|incorporated|inc)\b", " ", normalized)
    return " ".join(normalized.split())


def _company_names_match(left: Any, right: Any) -> bool:
    left_key = _company_name_key(left)
    right_key = _company_name_key(right)
    if not left_key or not right_key:
        return False
    if left_key == right_key or left_key in right_key or right_key in left_key:
        return True
    return SequenceMatcher(a=left_key, b=right_key).ratio() >= 0.8


def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes"}


def _required_text_match(input_value: Any, api_value: Any) -> bool:
    return bool(_normalize_text(input_value)) and _normalize_text(input_value) == _normalize_text(api_value)


def _optional_text_match(input_value: Any, api_value: Any) -> bool:
    if not _normalize_text(input_value) or not _normalize_text(api_value):
        return True
    return _normalize_text(input_value) == _normalize_text(api_value)


def _raise_mismatches(mismatches: dict[str, str]) -> None:
    if mismatches:
        raise ValidationError(mismatches)


def validate_nin_payload(input_data: dict[str, Any], data: dict[str, Any], *, defer_phone_mismatch: bool = False) -> bool:
    mismatches: dict[str, str] = {}
    phone_mismatch = False
    checks = [
        ("first_name", "firstName", "First name does not match the NIN record."),
        ("last_name", "surname", "Last name does not match the NIN record."),
    ]
    for input_key, api_key, message in checks:
        if not _required_text_match(input_data.get(input_key), data.get(api_key)):
            mismatches[input_key] = message

    if not _optional_text_match(input_data.get("middle_name"), data.get("middleName")):
        mismatches["middle_name"] = "Middle name does not match the NIN record."
    if _parse_date(input_data.get("date_of_birth")) != _parse_date(data.get("birthDate")):
        mismatches["date_of_birth"] = "Date of birth does not match the NIN record."
    if _normalize_gender(input_data.get("gender")) != _normalize_gender(data.get("gender")):
        mismatches["gender"] = "Gender does not match the NIN record."
    if not _normalize_phone(input_data.get("mobile")):
        mismatches["mobile"] = "Contact number is required for NIN verification."
    elif not _phone_matches(input_data.get("mobile"), data.get("telephoneNo")):
        if defer_phone_mismatch:
            phone_mismatch = True
        else:
            mismatches["mobile"] = "Mobile number does not match the NIN record."
    if _normalize_region(data.get("selfOriginLga")) and _normalize_region(input_data.get("lga")) != _normalize_region(data.get("selfOriginLga")):
        mismatches["lga"] = "LGA does not match the NIN record."
    if _normalize_region(data.get("selfOriginState")) and _normalize_region(input_data.get("state_of_origin")) != _normalize_region(data.get("selfOriginState")):
        mismatches["state_of_origin"] = "State of origin does not match the NIN record."

    _raise_mismatches(mismatches)
    return phone_mismatch


def validate_bvn_payload(input_data: dict[str, Any], data: dict[str, Any], *, validate_phone: bool = False) -> None:
    mismatches: dict[str, str] = {}
    checks = [
        ("first_name", "firstName", "First name does not match the BVN record."),
        ("last_name", "lastName", "Last name does not match the BVN record."),
    ]
    for input_key, api_key, message in checks:
        if not _required_text_match(input_data.get(input_key), data.get(api_key)):
            mismatches[input_key] = message

    if not _optional_text_match(input_data.get("middle_name"), data.get("middleName")):
        mismatches["middle_name"] = "Middle name does not match the BVN record."
    if _parse_date(input_data.get("date_of_birth")) != _parse_date(data.get("dateOfBirth")):
        mismatches["date_of_birth"] = "Date of birth does not match the BVN record."
    if _normalize_gender(input_data.get("gender")) != _normalize_gender(data.get("gender")):
        mismatches["gender"] = "Gender does not match the BVN record."
    if _normalize_region(input_data.get("lga")) != _normalize_region(data.get("lgaOfOrigin")):
        mismatches["lga"] = "LGA does not match the BVN record."
    if _normalize_nationality(input_data.get("nationality")) != _normalize_nationality(data.get("nationality")):
        mismatches["nationality"] = "Nationality does not match the BVN record."
    if _normalize_region(input_data.get("state_of_origin")) != _normalize_region(data.get("stateOfOrigin")):
        mismatches["state_of_origin"] = "State of origin does not match the BVN record."
    if validate_phone and not _phone_matches(input_data.get("mobile"), data.get("phoneNumber1")):
        mismatches["mobile"] = "Mobile number does not match the BVN record."

    _raise_mismatches(mismatches)


def validate_cac_payload(input_data: dict[str, Any], data: dict[str, Any]) -> None:
    mismatches: dict[str, str] = {}
    if not _is_truthy(data.get("registrationApproved")):
        mismatches["cac_registration_number"] = "CAC has not approved this registration record."
    if not _company_names_match(input_data.get("company_name"), data.get("companyName")):
        mismatches["company_name"] = "Company name does not match the CAC record."
    if _normalize_digits(input_data.get("cac_registration_number")) != _normalize_digits(data.get("rcNumber")):
        mismatches["cac_registration_number"] = "Registration number does not match the CAC record."
    if _parse_date(input_data.get("cac_registration_date")) != _parse_date(data.get("registrationDate")):
        mismatches["cac_registration_date"] = "Registration date does not match the CAC record."

    _raise_mismatches(mismatches)


def verify_nin(input_data: dict[str, Any], nin_number: str, *, defer_phone_mismatch: bool = False) -> dict[str, Any]:
    payload = dikript_lookup(
        verification_type="nin",
        path=settings.DIKRIPT_NIN_API_URL,
        lookup_value=_normalize_digits(nin_number),
        query={"nin": _normalize_digits(nin_number)},
    )
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    if not payload.get("status") or not data:
        raise ValidationError({"nin_number": extract_dikript_message(payload) or "No NIN record was found for this number."})
    returned_nin = _normalize_digits(data.get("nin") or data.get("vNin") or data.get("VNin") or data.get("NIN"))
    if returned_nin and returned_nin != _normalize_digits(nin_number):
        raise ValidationError({"nin_number": "NIN does not match the NIN record."})
    phone_mismatch = validate_nin_payload(input_data, data, defer_phone_mismatch=defer_phone_mismatch)
    if phone_mismatch:
        raise DikriptPhoneMismatch(payload)
    return payload


def verify_bvn(input_data: dict[str, Any], bvn_number: str, *, validate_phone: bool = False) -> dict[str, Any]:
    payload = dikript_lookup(
        verification_type="bvn",
        path=settings.DIKRIPT_BVN_API_URL,
        lookup_value=_normalize_digits(bvn_number),
        query={"bvn": _normalize_digits(bvn_number)},
    )
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    if not payload.get("status") or not data:
        raise ValidationError({"bvn_number": extract_dikript_message(payload) or "No BVN record was found for this number."})
    returned_bvn = _normalize_digits(data.get("bvn"))
    if returned_bvn and returned_bvn != _normalize_digits(bvn_number):
        raise ValidationError({"bvn_number": "BVN does not match the BVN record."})
    validate_bvn_payload(input_data, data, validate_phone=validate_phone)
    return payload


def verify_nin_and_bvn(input_data: dict[str, Any], nin_number: str, bvn_number: str) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        nin_payload = verify_nin(input_data, nin_number, defer_phone_mismatch=True)
        return nin_payload, verify_bvn(input_data, bvn_number)
    except DikriptPhoneMismatch as exc:
        try:
            bvn_payload = verify_bvn(input_data, bvn_number, validate_phone=True)
        except ValidationError as bvn_error:
            detail = bvn_error.detail
            if isinstance(detail, dict) and "mobile" in detail:
                detail["mobile"] = "Mobile number does not match the NIN or BVN records."
            raise ValidationError(detail) from bvn_error
        return exc.payload, bvn_payload


def verify_cac(input_data: dict[str, Any], registration_number: str) -> dict[str, Any]:
    lookup_value = re.sub(r"[^A-Z0-9]+", "", str(registration_number or "").upper())
    payload = dikript_lookup(
        verification_type="cac",
        path=settings.DIKRIPT_CAC_API_URL,
        lookup_value=lookup_value,
        query={"regNumber": lookup_value},
    )
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    if not payload.get("status") or not data:
        raise ValidationError({"cac_registration_number": extract_dikript_message(payload) or "No CAC record was found for this registration number."})
    validate_cac_payload(input_data, data)
    return payload
