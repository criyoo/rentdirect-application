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

from .verification_records import get_verification_record_payload, sanitize_verification_payload, store_verification_record_payload

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


def dikript_lookup(*, verification_type: str, path: str, lookup_value: str, query: dict[str, Any], store_record: bool = True) -> dict[str, Any]:
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
        if store_record:
            sanitized = store_verification_record_payload(
                provider="dikript",
                verification_type=verification_type,
                lookup_value=lookup_value,
                payload=sanitized,
            )
        else:
            sanitized = sanitize_verification_payload(sanitized)
        cache.set(cache_key, sanitized, timeout=getattr(settings, "DIKRIPT_LOOKUP_CACHE_TIMEOUT_SECONDS", 86400))
        return sanitized
    return payload


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _normalize_region(value: Any) -> str:
    normalized = _normalize_text(value)
    normalized = re.sub(r"\bstate\b", "", normalized)
    return " ".join(normalized.split())


def _normalize_nationality(value: Any) -> str:
    normalized = _normalize_text(value)
    if normalized == "nigerian":
        return "nigeria"
    return normalized


def _normalize_gender(value: Any) -> str:
    normalized = _normalize_text(value)
    if normalized in {"male", "m"}:
        return "male"
    if normalized in {"female", "f"}:
        return "female"
    return normalized


def _normalize_digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _normalize_phone(value: Any) -> str:
    """Canonical Nigerian local format: +2349012374637 -> 09012374637."""
    digits = _normalize_digits(value)
    if digits.startswith("234"):
        digits = digits[3:]
    digits = digits.lstrip("0")
    return f"0{digits}" if digits else ""


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
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y", "%d-%B-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw_value[:20], fmt).date()
        except ValueError:
            continue
    return parse_date(raw_value[:10])


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


def _required_text_contains(input_value: Any, api_value: Any) -> bool:
    input_text = _normalize_text(input_value)
    return bool(input_text) and input_text in _normalize_text(api_value)


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


CHECK_MATCH = "match"
CHECK_MISMATCH = "mismatch"
CHECK_UNAVAILABLE = "unavailable"

# Mandatory fields must match at least one provider; a field fails only when
# it mismatches BOTH the NIN and the BVN record.
MANDATORY_IDENTITY_FIELDS = ("first_name", "last_name", "date_of_birth", "mobile", "gender")
# Optional fields never fail verification; they only influence the confidence badge.
OPTIONAL_IDENTITY_FIELDS = ("middle_name", "nationality", "lga", "state_of_origin", "country_of_birth")

VERIFICATION_BADGE_EXCELLENT = "Verification: Excellent"
VERIFICATION_BADGE_GOOD = "Verification: Good"

_MANDATORY_ERROR_MESSAGES = {
    "first_name": "First name does not match the NIN or BVN records.",
    "last_name": "Last name does not match the NIN or BVN records.",
    "date_of_birth": "Date of birth does not match the NIN or BVN records.",
    "mobile": "Mobile number does not match the NIN or BVN records.",
    "gender": "Gender does not match the NIN or BVN records.",
}

_NIN_MANDATORY_ERROR_MESSAGES = {
    "first_name": "First name does not match the NIN record.",
    "last_name": "Last name does not match the NIN record.",
    "date_of_birth": "Date of birth does not match the NIN record.",
    "gender": "Gender does not match the NIN record.",
    "mobile": "Mobile number does not match the NIN record.",
}

_BVN_MANDATORY_ERROR_MESSAGES = {
    "first_name": "First name does not match the BVN record.",
    "last_name": "Last name does not match the BVN record.",
    "date_of_birth": "Date of birth does not match the BVN record.",
    "gender": "Gender does not match the BVN record.",
    "mobile": "Mobile number does not match the BVN record.",
}


def _check_field(input_value: Any, api_values: tuple, matcher, *, input_optional: bool = False) -> str:
    """Compare a submitted value against provider values.

    Returns 'match' when the input matches any returned value, 'unavailable'
    when the field cannot be checked (no provider value, or the input is an
    optional field that was left blank), and 'mismatch' otherwise."""
    present_values = [value for value in api_values if _normalize_text(value)]
    if not present_values or (input_optional and not _normalize_text(input_value)):
        return CHECK_UNAVAILABLE
    return CHECK_MATCH if any(matcher(input_value, value) for value in present_values) else CHECK_MISMATCH


def _match_text(input_value: Any, api_value: Any) -> bool:
    return _normalize_text(input_value) == _normalize_text(api_value)


def _match_date(input_value: Any, api_value: Any) -> bool:
    parsed_input = _parse_date(input_value)
    parsed_api = _parse_date(api_value)
    if parsed_input is None:
        return parsed_api is None
    return parsed_input == parsed_api


def _match_gender(input_value: Any, api_value: Any) -> bool:
    return _normalize_gender(input_value) == _normalize_gender(api_value)


def _match_nationality(input_value: Any, api_value: Any) -> bool:
    return _normalize_nationality(input_value) == _normalize_nationality(api_value)


def _match_region(input_value: Any, api_value: Any) -> bool:
    return _normalize_region(input_value) == _normalize_region(api_value)


def _match_contains(input_value: Any, api_value: Any) -> bool:
    input_text = _normalize_text(input_value)
    api_text = _normalize_text(api_value)
    return input_text == api_text or input_text in api_text


def _nin_field_checks(input_data: dict[str, Any], data: dict[str, Any]) -> dict[str, str]:
    """Return field -> match/mismatch/unavailable for the NIN record."""
    return {
        "first_name": _check_field(input_data.get("first_name"), (_first_present(data, "firstName", "firstname"),), _match_text),
        "last_name": _check_field(input_data.get("last_name"), (_first_present(data, "surname", "lastName", "lastname"),), _match_text),
        "date_of_birth": _check_field(input_data.get("date_of_birth"), (_first_present(data, "birthDate", "birthdate"),), _match_date),
        "mobile": _check_field(input_data.get("mobile"), (_first_present(data, "telephoneNo", "telephoneno"),), _phone_matches),
        "gender": _check_field(input_data.get("gender"), (data.get("gender"),), _match_gender),
        "middle_name": _check_field(input_data.get("middle_name"), (_get_nin_middle_name(data),), _match_text, input_optional=True),
        "nationality": _check_field(input_data.get("nationality"), (_first_present(data, "nationality", "birthcountry"),), _match_nationality, input_optional=True),
        "lga": _check_field(input_data.get("lga"), (_first_present(data, "self_origin_lga", "selfOriginLga", "birthlga"),), _match_contains, input_optional=True),
        "state_of_origin": _check_field(input_data.get("state_of_origin"), (_first_present(data, "self_origin_state", "selfOriginState", "birthstate"),), _match_region, input_optional=True),
        "country_of_birth": _check_field(
            _first_present(input_data, "country_of_birth", "place_of_birth"),
            (_first_present(data, "birthcountry", "self_origin_place", "placeOfBirth"),),
            _match_text,
            input_optional=True,
        ),
    }


def _bvn_field_checks(input_data: dict[str, Any], data: dict[str, Any]) -> dict[str, str]:
    """Return field -> match/mismatch/unavailable for the BVN record."""
    return {
        "first_name": _check_field(input_data.get("first_name"), (_first_present(data, "firstName", "firstname"),), _match_text),
        "last_name": _check_field(input_data.get("last_name"), (_first_present(data, "lastName", "surname"),), _match_text),
        "date_of_birth": _check_field(input_data.get("date_of_birth"), (_first_present(data, "dateOfBirth", "birthDate", "birthdate"),), _match_date),
        "mobile": _check_field(input_data.get("mobile"), (data.get("phoneNumber1"), data.get("phoneNumber2")), _phone_matches),
        "gender": _check_field(input_data.get("gender"), (data.get("gender"),), _match_gender),
        "middle_name": _check_field(input_data.get("middle_name"), (_first_present(data, "middleName", "middlename"),), _match_text, input_optional=True),
        "nationality": _check_field(input_data.get("nationality"), (data.get("nationality"),), _match_nationality, input_optional=True),
        "lga": _check_field(input_data.get("lga"), (data.get("lgaOfOrigin"),), _match_contains, input_optional=True),
        "state_of_origin": _check_field(input_data.get("state_of_origin"), (data.get("stateOfOrigin"),), _match_region, input_optional=True),
        "country_of_birth": _check_field(
            _first_present(input_data, "country_of_birth", "place_of_birth"),
            (_first_present(data, "birthcountry", "placeOfBirth"),),
            _match_text,
            input_optional=True,
        ),
    }


def _record_number_matches(data: dict[str, Any], submitted: str, *keys: str) -> bool:
    """True when the record carries no number or the digits equal the submitted one."""
    recorded = _normalize_digits(_first_present(data, *keys))
    return not recorded or recorded == _normalize_digits(submitted)


def _merge_identity_checks(nin_checks: dict[str, str], bvn_checks: dict[str, str]) -> tuple[dict[str, str], str]:
    """Merge NIN/BVN field checks. A mandatory field errors only when it
    mismatches BOTH records; optional fields that match neither record
    downgrade the confidence badge instead of failing verification."""
    errors: dict[str, str] = {}
    for field in MANDATORY_IDENTITY_FIELDS:
        nin_result = nin_checks.get(field)
        bvn_result = bvn_checks.get(field)
        if CHECK_MATCH in (nin_result, bvn_result):
            continue
        if nin_result == CHECK_MISMATCH and bvn_result == CHECK_MISMATCH:
            errors[field] = _MANDATORY_ERROR_MESSAGES[field]

    badge = VERIFICATION_BADGE_EXCELLENT
    for field in OPTIONAL_IDENTITY_FIELDS:
        nin_result = nin_checks.get(field)
        bvn_result = bvn_checks.get(field)
        if CHECK_MATCH in (nin_result, bvn_result):
            continue
        if CHECK_MISMATCH in (nin_result, bvn_result):
            badge = VERIFICATION_BADGE_GOOD
            break

    return errors, badge


def validate_nin_payload(input_data: dict[str, Any], data: dict[str, Any], *, defer_phone_mismatch: bool = False) -> tuple[dict[str, str], bool]:
    """Validate NIN payload. Returns (mismatches, phone_mismatch).
    Checks the mandatory fields the NIN record provides: first_name, last_name,
    date_of_birth, gender and mobile. Phone defers to a warning when
    defer_phone_mismatch is True."""
    checks = _nin_field_checks(input_data, data)
    mismatches: dict[str, str] = {}
    phone_mismatch = False
    for field in MANDATORY_IDENTITY_FIELDS:
        if checks.get(field) != CHECK_MISMATCH:
            continue
        if field == "gender" and not _normalize_text(input_data.get("gender")):
            continue
        if field == "mobile" and defer_phone_mismatch:
            phone_mismatch = True
        mismatches[field] = _NIN_MANDATORY_ERROR_MESSAGES[field]
    return mismatches, phone_mismatch


def validate_bvn_payload(input_data: dict[str, Any], data: dict[str, Any], *, skip_names: bool = False, skip_dob: bool = False, require_phone: bool = False) -> dict[str, str]:
    """Validate BVN payload. Returns mismatches dict for mandatory fields."""
    checks = _bvn_field_checks(input_data, data)
    mismatches: dict[str, str] = {}
    skipped = set()
    if skip_names:
        skipped.update({"first_name", "last_name", "middle_name"})
    if skip_dob:
        skipped.add("date_of_birth")
    for field in MANDATORY_IDENTITY_FIELDS:
        if field in skipped or checks.get(field) != CHECK_MISMATCH:
            continue
        if field == "mobile" and not require_phone:
            continue
        mismatches[field] = _BVN_MANDATORY_ERROR_MESSAGES[field]
    return mismatches


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


def verify_nin(input_data: dict[str, Any], nin_number: str) -> dict[str, Any]:
    nin_payload = dikript_lookup(
        verification_type="nin",
        path=settings.DIKRIPT_NIN_API_URL,
        lookup_value=nin_number,
        query={"nin": nin_number},
        store_record=False,
    )
    nin_data = nin_payload.get("data") if isinstance(nin_payload.get("data"), dict) else {}
    if not nin_payload.get("status") or not nin_data:
        message = extract_dikript_message(nin_payload) or "Invalid NIN. Please verify your NIN is correct."
        raise ValidationError({"nin_number": message})
    if not _record_number_matches(nin_data, nin_number, "nin", "vNin"):
        raise ValidationError({"nin_number": "Submitted NIN does not match the verified record."})

    mismatches, phone_mismatch = validate_nin_payload(input_data, nin_data, defer_phone_mismatch=True)
    mismatches.pop("mobile", None)
    if mismatches:
        raise ValidationError(mismatches)
    nin_payload = store_verification_record_payload(
        provider="dikript",
        verification_type="nin",
        lookup_value=nin_number,
        payload=nin_payload,
    )
    if phone_mismatch:
        nin_payload = {**nin_payload, "mobile_warning": MOBILE_MISMATCH_WARNING.replace("NIN or BVN", "NIN")}

    return nin_payload


def verify_nin_and_bvn(input_data: dict[str, Any], nin_number: str, bvn_number: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Verify user identity against both NIN and BVN.

    Mandatory fields (first/last name, date of birth, mobile, gender) are
    checked against both records and fail only when they mismatch BOTH.
    Optional fields (middle name, nationality, LGA, state of origin, place of
    birth) never fail verification; they only downgrade the returned
    ``verification_badge`` from Excellent to Good.

    Returns (nin_payload, bvn_payload) on success.
    Raises ValidationError with field-level errors on mandatory mismatch.
    """
    nin_payload = dikript_lookup(
        verification_type="nin",
        path=settings.DIKRIPT_NIN_API_URL,
        lookup_value=nin_number,
        query={"nin": nin_number},
        store_record=False,
    )
    nin_data = nin_payload.get("data") if isinstance(nin_payload.get("data"), dict) else {}
    if not nin_payload.get("status") or not nin_data:
        message = extract_dikript_message(nin_payload) or "Invalid NIN. Please verify your NIN is correct."
        raise ValidationError({"nin_number": message})
    if not _record_number_matches(nin_data, nin_number, "nin", "vNin"):
        raise ValidationError({"nin_number": "Submitted NIN does not match the verified record."})

    bvn_payload = dikript_lookup(
        verification_type="bvn",
        path=settings.DIKRIPT_BVN_API_URL,
        lookup_value=bvn_number,
        query={"bvn": bvn_number},
        store_record=False,
    )
    bvn_data = bvn_payload.get("data") if isinstance(bvn_payload.get("data"), dict) else {}
    if not bvn_payload.get("status") or not bvn_data:
        message = extract_dikript_message(bvn_payload) or "Invalid BVN. Please verify your BVN is correct."
        raise ValidationError({"bvn_number": message})
    if not _record_number_matches(bvn_data, bvn_number, "bvn"):
        raise ValidationError({"bvn_number": "Submitted BVN does not match the verified record."})

    errors, badge = _merge_identity_checks(
        _nin_field_checks(input_data, nin_data),
        _bvn_field_checks(input_data, bvn_data),
    )
    if errors:
        raise ValidationError(errors)

    nin_payload = store_verification_record_payload(
        provider="dikript",
        verification_type="nin",
        lookup_value=nin_number,
        payload=nin_payload,
    )
    bvn_payload = store_verification_record_payload(
        provider="dikript",
        verification_type="bvn",
        lookup_value=bvn_number,
        payload=bvn_payload,
    )

    nin_payload = {**nin_payload, "verification_badge": badge}
    bvn_payload = {**bvn_payload, "verification_badge": badge}

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
