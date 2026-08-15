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

from .verification_records import get_verification_record_payload, store_verification_record_payload

logger = logging.getLogger(__name__)

MOBILE_MISMATCH_WARNING = "Warning: Mobile number does not match number register in NIN or BVN. Do you want to register this number?"
MOBILE_MISSING_WARNING = "Warning: You did not provide a contact number, please ensure you add a contact number in your profile"


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

    database_payload = get_verification_record_payload(
        provider="dikript",
        verification_type=verification_type,
        lookup_value=lookup_value,
    )
    if isinstance(database_payload, dict) and database_payload.get("status") and isinstance(database_payload.get("data"), dict):
        cache.set(cache_key, database_payload, timeout=getattr(settings, "DIKRIPT_LOOKUP_CACHE_TIMEOUT_SECONDS", 86400))
        return database_payload

    payload = dikript_get(path, query)
    if isinstance(payload, dict) and payload.get("status") and isinstance(payload.get("data"), dict):
        sanitized = json.loads(json.dumps(payload))
        data = sanitized.get("data")
        if isinstance(data, dict):
            data.pop("photo", None)
            data.pop("signature", None)
        sanitized = store_verification_record_payload(
            provider="dikript",
            verification_type=verification_type,
            lookup_value=lookup_value,
            payload=sanitized,
        )
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


def _mobile_verification_warning(input_data: dict[str, Any], nin_data: dict[str, Any], bvn_data: dict[str, Any]) -> str:
    mobile = input_data.get("mobile")
    if not _normalize_phone(mobile):
        return MOBILE_MISSING_WARNING
    if (
        not _phone_matches(mobile, nin_data.get("telephoneNo"))
        and not _phone_matches(mobile, bvn_data.get("phoneNumber1"))
    ):
        return MOBILE_MISMATCH_WARNING
    return ""


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


def _get_nin_middle_name(data: dict[str, Any]) -> str:
    """Get the middle name from NIN data, checking middleName first, then otherName."""
    middle_name = data.get("middleName")
    other_name = data.get("otherName")
    if _normalize_text(middle_name):
        return middle_name
    return other_name or ""


def _validate_nin_fields(input_data: dict[str, Any], data: dict[str, Any]) -> dict[str, str]:
    """Validate fields against NIN API response. Returns dict of mismatches.
    NIN fields: firstName, surname, middleName/otherName, telephoneNo, birthDate.
    No state_of_origin or lga check from NIN.
    Gender and nationality are checked in BVN, not NIN."""
    mismatches: dict[str, str] = {}

    for input_key, api_key, message in [
        ("first_name", "firstName", "First name does not match the NIN record."),
        ("last_name", "surname", "Last name does not match the NIN record."),
    ]:
        if not _required_text_match(input_data.get(input_key), data.get(api_key)):
            mismatches[input_key] = message

    # Check middleName first, then fall back to otherName for NIN
    nin_middle_name = _get_nin_middle_name(data)
    if not _optional_text_match(input_data.get("middle_name"), nin_middle_name):
        mismatches["middle_name"] = "Middle name does not match the NIN record."
    if _parse_date(input_data.get("date_of_birth")) != _parse_date(data.get("birthDate")):
        mismatches["date_of_birth"] = "Date of birth does not match the NIN record."

    return mismatches


def _validate_bvn_fields(
    input_data: dict[str, Any],
    data: dict[str, Any],
    *,
    skip_names: bool = False,
    skip_dob: bool = False,
    require_phone: bool = False,
) -> dict[str, str]:
    """Validate fields against BVN API response. Returns dict of mismatches.
    BVN fields: firstName, middleName, lastName, dateOfBirth, gender, stateOfOrigin,
    lgaOfOrigin, nationality, phoneNumber1.
    If skip_names is True, first/last/middle name checks are skipped (already passed NIN).
    If skip_dob is True, date_of_birth check is skipped (already passed NIN)."""
    mismatches: dict[str, str] = {}

    if not skip_names:
        for input_key, api_key, message in [
            ("first_name", "firstName", "First name does not match the BVN record."),
            ("last_name", "lastName", "Last name does not match the BVN record."),
        ]:
            if not _required_text_match(input_data.get(input_key), data.get(api_key)):
                mismatches[input_key] = message

        if not _optional_text_match(input_data.get("middle_name"), data.get("middleName")):
            mismatches["middle_name"] = "Middle name does not match the BVN record."

    if not skip_dob:
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
    if require_phone and _normalize_phone(input_data.get("mobile")) and not _phone_matches(input_data.get("mobile"), data.get("phoneNumber1")):
        mismatches["mobile"] = "Mobile number does not match the BVN record."

    return mismatches


def validate_nin_payload(input_data: dict[str, Any], data: dict[str, Any], *, defer_phone_mismatch: bool = False) -> tuple[dict[str, str], bool]:
    """Validate NIN payload. Returns (mismatches, phone_mismatch).
    Only checks: first_name, last_name, middle_name, date_of_birth.
    Phone is also checked - if it fails and defer_phone_mismatch is True, returns phone_mismatch=True instead."""
    mismatches = _validate_nin_fields(input_data, data)
    phone_mismatch = False

    if _normalize_phone(input_data.get("mobile")) and not _phone_matches(input_data.get("mobile"), data.get("telephoneNo")):
        if defer_phone_mismatch:
            phone_mismatch = True
            mismatches["mobile"] = "Mobile number does not match the NIN record."
        else:
            mismatches["mobile"] = "Mobile number does not match the NIN record."

    return mismatches, phone_mismatch


def validate_bvn_payload(input_data: dict[str, Any], data: dict[str, Any], *, skip_names: bool = False, skip_dob: bool = False, require_phone: bool = False) -> dict[str, str]:
    """Validate BVN payload. Returns mismatches dict."""
    return _validate_bvn_fields(input_data, data, skip_names=skip_names, skip_dob=skip_dob, require_phone=require_phone)


def _first_present(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return ""


def validate_cac_payload(input_data: dict[str, Any], data: dict[str, Any]) -> dict[str, str]:
    mismatches: dict[str, str] = {}

    company_name = _first_present(data, "companyName", "company_name")
    if not _company_names_match(input_data.get("company_name"), company_name):
        mismatches["company_name"] = "Company name does not match the CAC record."

    submitted_date = _first_present(input_data, "cac_registration_date", "date_of_registration", "registration_date")
    registration_date = _first_present(data, "registrationDate", "date_of_registration")
    if _parse_date(submitted_date) != _parse_date(registration_date):
        mismatches["cac_registration_date"] = "CAC registration date does not match the CAC record."

    registration_approved = data.get("registrationApproved")
    if registration_approved is not None and not _is_truthy(registration_approved):
        mismatches["cac_registration_number"] = "CAC registration has not been approved."

    if mismatches:
        raise ValidationError(mismatches)
    return mismatches


def _merge_field_mismatches(
    input_data: dict[str, Any],
    nin_mismatches: dict[str, str],
    bvn_mismatches: dict[str, str],
    nin_data: dict[str, Any],
    bvn_data: dict[str, Any],
) -> dict[str, str]:
    """Merge mismatches: a field only errors if it fails BOTH NIN and BVN.
    For fields only in one provider (e.g., gender, state from BVN), if they fail BVN they error.
    For phone, check NIN first, then BVN; error if both fail.
    State of origin is only validated through BVN, never NIN."""
    result: dict[str, str] = {}

    # Fields present in NIN validation
    nin_fields = {"first_name", "last_name", "middle_name", "date_of_birth"}

    for field in nin_fields:
        nin_failed = field in nin_mismatches
        bvn_failed = field in bvn_mismatches
        if nin_failed and bvn_failed:
            result[field] = bvn_mismatches[field]
        elif nin_failed:
            # Only NIN failed, keep NIN error
            result[field] = nin_mismatches[field]
        elif bvn_failed:
            # Only BVN failed (shouldn't happen for name/dob if NIN passed, but handle it)
            result[field] = bvn_mismatches[field]

    # Fields only in BVN validation (state_of_origin is BVN-only, never from NIN)
    bvn_only_fields = {"gender", "state_of_origin", "lga", "nationality"}
    for field in bvn_only_fields:
        if field in bvn_mismatches:
            result[field] = bvn_mismatches[field]

    return result


def verify_nin_and_bvn(input_data: dict[str, Any], nin_number: str, bvn_number: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Verify user identity against both NIN and BVN.

    Validation flow:
    A. NIN Validation: Validate first_name, last_name, middle_name, date_of_birth, mobile
       against NIN API response. State of origin is NOT validated against NIN.
    B. If all NIN fields pass, skip corresponding fields in BVN validation
       and only validate BVN-specific fields (gender, state_of_origin, lga, nationality).
       Mobile is cross-checked: if NIN phone matches, skip BVN phone check.
    C. If some NIN fields fail, check BVN for those fields too.
    D. Error is only thrown if a field fails BOTH NIN and BVN validation.

    Returns (nin_payload, bvn_payload) on success.
    Raises ValidationError with field-level errors on mismatch.
    """
    # Look up NIN
    nin_payload = dikript_lookup(
        verification_type="nin",
        path=settings.DIKRIPT_NIN_API_URL,
        lookup_value=nin_number,
        query={"nin": nin_number},
    )
    nin_data = nin_payload.get("data") if isinstance(nin_payload.get("data"), dict) else {}
    if not nin_payload.get("status") or not nin_data:
        message = extract_dikript_message(nin_payload) or "Invalid NIN. Please verify your NIN is correct."
        raise ValidationError({"nin_number": message})

    # Step A: Validate NIN fields (no state_of_origin or lga for NIN)
    nin_mismatches, nin_phone_mismatch = validate_nin_payload(
        input_data, nin_data, defer_phone_mismatch=True,
    )
    # Look up BVN
    bvn_payload = dikript_lookup(
        verification_type="bvn",
        path=settings.DIKRIPT_BVN_API_URL,
        lookup_value=bvn_number,
        query={"bvn": bvn_number},
    )
    bvn_data = bvn_payload.get("data") if isinstance(bvn_payload.get("data"), dict) else {}
    if not bvn_payload.get("status") or not bvn_data:
        message = extract_dikript_message(bvn_payload) or "Invalid BVN. Please verify your BVN is correct."
        raise ValidationError({"bvn_number": message})

    # Step B & C: Validate BVN fields
    # If all NIN fields (excluding mobile) passed, skip those in BVN
    nin_fields = {"first_name", "last_name", "middle_name", "date_of_birth"}
    nin_non_phone_errors = {k: v for k, v in nin_mismatches.items() if k != "mobile"}
    skip_names = all(field not in nin_non_phone_errors for field in {"first_name", "last_name", "middle_name"})
    skip_dob = "date_of_birth" not in nin_non_phone_errors

    bvn_mismatches = validate_bvn_payload(
        input_data, bvn_data,
        skip_names=skip_names,
        skip_dob=skip_dob,
        require_phone=nin_phone_mismatch,
    )

    # Merge: a field errors only if it fails BOTH NIN and BVN
    merged = _merge_field_mismatches(
        input_data, nin_mismatches, bvn_mismatches,
        nin_data, bvn_data,
    )

    if merged:
        raise ValidationError(merged)

    mobile_warning = _mobile_verification_warning(input_data, nin_data, bvn_data)
    if mobile_warning:
        nin_payload = {**nin_payload, "mobile_warning": mobile_warning}

    return nin_payload, bvn_payload


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
