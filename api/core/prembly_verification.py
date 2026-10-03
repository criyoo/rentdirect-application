from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.cache import cache
from django.utils.dateparse import parse_date
from rest_framework.exceptions import APIException, ValidationError

from .verification_records import get_verification_record_payload, store_verification_record_payload

logger = logging.getLogger(__name__)

MOBILE_MISMATCH_WARNING = "Warning: Mobile number does not match number register in NIN or BVN. Do you want to register this number?"
MOBILE_MISSING_WARNING = "Warning: You did not provide a contact number, please ensure you add a contact number in your profile"


class PremblyVerificationUnavailable(APIException):
    status_code = 503
    default_detail = "Unable to verify the record right now. Try again later."
    default_code = "prembly_verification_unavailable"


class PremblyWebhookVerificationError(APIException):
    status_code = 401
    default_detail = "Invalid Prembly webhook signature."
    default_code = "prembly_webhook_verification_failed"


def _prembly_key() -> str:
    return str(
        getattr(settings, "PREMBLY_API_SECRET_KEY", "")
        or getattr(settings, "PREMBLY_API_KEY", "")
        or ""
    ).strip()


def _prembly_public_key() -> str:
    return str(getattr(settings, "PREMBLY_API_PUBLIC_KEY", "") or "").strip()


def _payload_bytes(raw_body: bytes | str) -> bytes:
    if isinstance(raw_body, bytes):
        return raw_body
    return str(raw_body or "").encode("utf-8")


def _header_value(headers: Any, name: str) -> str:
    if headers is None:
        return ""

    candidates = [
        name,
        name.lower(),
        name.upper(),
        name.title(),
        f"HTTP_{name.upper().replace('-', '_')}",
    ]
    for candidate in candidates:
        value = headers.get(candidate) if hasattr(headers, "get") else None
        if value not in (None, ""):
            return str(value).strip()

    if not hasattr(headers, "items"):
        return ""

    target = name.lower()
    for key, value in headers.items():
        normalized_key = str(key)
        if normalized_key.startswith("HTTP_"):
            normalized_key = normalized_key[5:]
        normalized_key = normalized_key.replace("_", "-").lower()
        if normalized_key == target and value not in (None, ""):
            return str(value).strip()
    return ""


def compute_prembly_webhook_signature(raw_body: bytes | str, *, public_key: str | None = None) -> str:
    signing_key = str(public_key if public_key is not None else _prembly_public_key()).strip()
    if not signing_key:
        logger.warning("Prembly webhook public key is not configured.")
        return ""
    expected_signature = hmac.new(
        signing_key.encode("utf-8"),
        msg=_payload_bytes(raw_body),
        digestmod=hashlib.sha256,
    ).digest()
    return base64.b64encode(expected_signature).decode("utf-8")


def verify_prembly_webhook_signature(*, raw_body: bytes | str, signature: str, public_key: str | None = None) -> bool:
    provided_signature = str(signature or "").strip()
    if not provided_signature:
        return False
    if provided_signature.lower().startswith("sha256="):
        provided_signature = provided_signature[7:].strip()
    try:
        provided_signature_bytes = provided_signature.encode("ascii")
    except UnicodeEncodeError:
        return False

    expected_signature = compute_prembly_webhook_signature(raw_body, public_key=public_key)
    return bool(expected_signature) and hmac.compare_digest(provided_signature_bytes, expected_signature.encode("ascii"))


def mark_prembly_webhook_token_processed(token: str) -> bool:
    token_value = str(token or "").strip()
    if not token_value:
        return False
    token_hash = hashlib.sha256(token_value.encode("utf-8")).hexdigest()
    cache_key = f"prembly_webhook_token:{token_hash}"
    return cache.add(
        cache_key,
        True,
        timeout=getattr(settings, "PREMBLY_WEBHOOK_TOKEN_CACHE_SECONDS", 60 * 60 * 24 * 7),
    )


def validate_prembly_webhook_request(*, headers: Any, raw_body: bytes | str, track_token: bool = True) -> dict[str, Any]:
    signature = _header_value(headers, "x-prembly-signature")
    token = _header_value(headers, "token")

    if not signature or not token:
        raise PremblyWebhookVerificationError(detail="Missing Prembly webhook security headers.")
    if not verify_prembly_webhook_signature(raw_body=raw_body, signature=signature):
        raise PremblyWebhookVerificationError()

    return {
        "token": token,
        "already_processed": track_token and not mark_prembly_webhook_token_processed(token),
    }


def _decode_response(raw_response: bytes, *, allow_empty: bool = False) -> dict[str, Any]:
    if not raw_response:
        if allow_empty:
            return {}
        raise PremblyVerificationUnavailable()

    try:
        payload = json.loads(raw_response.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning("Prembly verification returned invalid JSON.")
        raise PremblyVerificationUnavailable() from exc

    return payload if isinstance(payload, dict) else {}


def extract_prembly_message(payload: dict[str, Any]) -> str:
    return str(payload.get("message") or payload.get("detail") or payload.get("error") or "").strip()


def _payload_verified(payload: dict[str, Any]) -> bool:
    response_code = str(payload.get("response_code") or payload.get("code") or "").strip()
    if response_code and response_code not in {"00", "200"}:
        return False
    verification = payload.get("verification")
    if isinstance(verification, dict):
        status = str(verification.get("status") or "").strip().upper()
        if status and status != "VERIFIED":
            return False
    verification_status = str(payload.get("verification_status") or "").strip().lower()
    if verification_status and verification_status != "verified":
        return False
    return payload.get("status") is True


def _strip_sensitive_media(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            if str(key).lower() in {"photo", "signature", "base64image", "image"}:
                continue
            sanitized[key] = _strip_sensitive_media(item)
        return sanitized
    if isinstance(value, list):
        return [_strip_sensitive_media(item) for item in value]
    return value


def prembly_post(path: str, body: dict[str, Any]) -> dict[str, Any]:
    base_url = (getattr(settings, "PREMBLY_API_BASE_URL", "") or "").rstrip("/")
    api_key = _prembly_key()
    if not base_url or not api_key:
        logger.error("Prembly verification is not configured.")
        raise PremblyVerificationUnavailable()

    request = Request(
        url=f"{base_url}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-api-key": api_key,
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=getattr(settings, "PREMBLY_TIMEOUT_SECONDS", 10)) as response:
            return _decode_response(response.read())
    except HTTPError as exc:
        payload = _decode_response(exc.read(), allow_empty=True)
        message = extract_prembly_message(payload)
        if exc.code in {400, 404, 422} and message:
            return payload
        raise PremblyVerificationUnavailable(detail=message or None) from exc
    except URLError as exc:
        raise PremblyVerificationUnavailable() from exc


def prembly_lookup(*, verification_type: str, path: str, lookup_value: str, body: dict[str, Any], store_record: bool = True) -> dict[str, Any]:
    lookup_hash = hashlib.sha256(str(lookup_value).encode("utf-8")).hexdigest()
    cache_key = f"prembly_lookup:{verification_type}:{lookup_hash}"
    cached_payload = cache.get(cache_key)
    if isinstance(cached_payload, dict) and _payload_verified(cached_payload):
        return cached_payload

    database_payload = get_verification_record_payload(
        provider="prembly",
        verification_type=verification_type,
        lookup_value=lookup_value,
    )
    if isinstance(database_payload, dict) and _payload_verified(database_payload):
        cache.set(cache_key, database_payload, timeout=getattr(settings, "PREMBLY_LOOKUP_CACHE_TIMEOUT_SECONDS", 86400))
        return database_payload

    payload = prembly_post(path, body)
    if isinstance(payload, dict) and _payload_verified(payload):
        sanitized = _strip_sensitive_media(json.loads(json.dumps(payload)))
        if store_record:
            sanitized = store_verification_record_payload(
                provider="prembly",
                verification_type=verification_type,
                lookup_value=lookup_value,
                payload=sanitized,
            )
        cache.set(cache_key, sanitized, timeout=getattr(settings, "PREMBLY_LOOKUP_CACHE_TIMEOUT_SECONDS", 86400))
        return sanitized
    return payload


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _normalize_search_text(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


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
        not _phone_matches(mobile, nin_data.get("telephoneno"))
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


def _required_text_match(input_value: Any, api_value: Any) -> bool:
    return bool(_normalize_text(input_value)) and _normalize_text(input_value) == _normalize_text(api_value)


def _required_text_contains(input_value: Any, api_value: Any) -> bool:
    input_text = _normalize_text(input_value)
    return bool(input_text) and input_text in _normalize_text(api_value)


def _optional_text_match(input_value: Any, api_value: Any) -> bool:
    if not _normalize_text(input_value) or not _normalize_text(api_value):
        return True
    return _normalize_text(input_value) == _normalize_text(api_value)


def _contained_text_match(submitted_value: Any, api_value: Any) -> bool:
    submitted = _normalize_search_text(submitted_value)
    response = _normalize_search_text(api_value)
    return bool(submitted) and bool(response) and response in submitted


def _first_present(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return ""


def _get_payload_data(payload: dict[str, Any], *alternate_keys: str) -> dict[str, Any]:
    data = payload.get("data")
    if isinstance(data, dict):
        return data
    for key in alternate_keys:
        alternate = payload.get(key)
        if isinstance(alternate, dict):
            return alternate
    return {}


def _get_nin_middle_name(data: dict[str, Any]) -> str:
    return str(_first_present(data, "middlename", "middleName", "othername", "otherName", "pmiddlename"))


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
        "first_name": _check_field(input_data.get("first_name"), (_first_present(data, "firstname", "firstName"),), _match_text),
        "last_name": _check_field(input_data.get("last_name"), (_first_present(data, "surname", "lastName", "lastname"),), _match_text),
        "date_of_birth": _check_field(input_data.get("date_of_birth"), (_first_present(data, "birthdate", "birthDate"),), _match_date),
        "mobile": _check_field(input_data.get("mobile"), (_first_present(data, "telephoneno", "telephoneNo"),), _phone_matches),
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


def validate_nin_payload(
    input_data: dict[str, Any],
    data: dict[str, Any],
    *,
    defer_phone_mismatch: bool = False,
) -> tuple[dict[str, str], bool]:
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


def validate_bvn_payload(
    input_data: dict[str, Any],
    data: dict[str, Any],
    *,
    skip_names: bool = False,
    skip_dob: bool = False,
    require_phone: bool = False,
) -> dict[str, str]:
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


def verify_nin(input_data: dict[str, Any], nin_number: str) -> dict[str, Any]:
    nin_payload = prembly_lookup(
        verification_type="nin",
        path=settings.PREMBLY_NIN_API_URL,
        lookup_value=nin_number,
        body={"number_nin": nin_number},
        store_record=False,
    )
    nin_data = _get_payload_data(nin_payload, "nin_data")
    if not _payload_verified(nin_payload) or not nin_data:
        message = extract_prembly_message(nin_payload) or "Invalid NIN. Please verify your NIN is correct."
        raise ValidationError({"nin_number": message})
    if not _record_number_matches(nin_data, nin_number, "nin", "vNin"):
        raise ValidationError({"nin_number": "Submitted NIN does not match the verified record."})

    mismatches, phone_mismatch = validate_nin_payload(input_data, nin_data, defer_phone_mismatch=True)
    mismatches.pop("mobile", None)
    if mismatches:
        raise ValidationError(mismatches)
    nin_payload = store_verification_record_payload(
        provider="prembly",
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
    nin_payload = prembly_lookup(
        verification_type="nin",
        path=settings.PREMBLY_NIN_API_URL,
        lookup_value=nin_number,
        body={"number_nin": nin_number},
        store_record=False,
    )
    nin_data = _get_payload_data(nin_payload, "nin_data")
    if not _payload_verified(nin_payload) or not nin_data:
        message = extract_prembly_message(nin_payload) or "Invalid NIN. Please verify your NIN is correct."
        raise ValidationError({"nin_number": message})
    if not _record_number_matches(nin_data, nin_number, "nin", "vNin"):
        raise ValidationError({"nin_number": "Submitted NIN does not match the verified record."})

    bvn_payload = prembly_lookup(
        verification_type="bvn",
        path=settings.PREMBLY_BVN_API_URL,
        lookup_value=bvn_number,
        body={"number": bvn_number},
        store_record=False,
    )
    bvn_data = _get_payload_data(bvn_payload, "bvn_data")
    if not _payload_verified(bvn_payload) or not bvn_data:
        message = extract_prembly_message(bvn_payload) or "Invalid BVN. Please verify your BVN is correct."
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
        provider="prembly",
        verification_type="nin",
        lookup_value=nin_number,
        payload=nin_payload,
    )
    bvn_payload = store_verification_record_payload(
        provider="prembly",
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


def _split_cac_registration_number(registration_number: str, input_data: dict[str, Any]) -> tuple[str, str]:
    raw_value = str(registration_number or "").strip().upper()
    match = re.match(r"^(BN|RC|IT|LP|LLP)[\s/-]*(.+)$", raw_value)
    if match:
        company_type, number = match.groups()
    else:
        company_type = str(input_data.get("company_type") or input_data.get("cac_company_type") or getattr(settings, "PREMBLY_CAC_COMPANY_TYPE", "RC")).strip().upper()
        number = raw_value
    return re.sub(r"[^A-Z0-9]+", "", number), company_type or "RC"


def _select_cac_data(payload: dict[str, Any], input_data: dict[str, Any], registration_number: str) -> dict[str, Any]:
    data = payload.get("data")
    if isinstance(data, dict):
        return data
    if not isinstance(data, list):
        return {}

    lookup_digits = _normalize_digits(registration_number)
    input_company_name = input_data.get("company_name")
    for record in data:
        if not isinstance(record, dict):
            continue
        record_number = str(_first_present(record, "rc_number", "number") or "")
        if lookup_digits and lookup_digits != _normalize_digits(record_number):
            continue
        if input_company_name and not _company_names_match(input_company_name, record.get("company_name")):
            continue
        return record
    return next((record for record in data if isinstance(record, dict)), {})


def validate_cac_payload(input_data: dict[str, Any], data: dict[str, Any]) -> dict[str, str]:
    mismatches: dict[str, str] = {}

    if not _company_names_match(input_data.get("company_name"), data.get("company_name")):
        mismatches["company_name"] = "Company name does not match the CAC record."

    if not _required_text_match(_first_present(input_data, "state", "business_state"), data.get("state")):
        mismatches["state"] = "State does not match the CAC record."

    submitted_address = _first_present(input_data, "address", "business_address", "company_address", "head_office_address")
    if not _contained_text_match(submitted_address, data.get("address")):
        mismatches["address"] = "Business address does not match the CAC record."

    submitted_email = _first_present(input_data, "email_address", "company_email", "registration_email", "email")
    if not _required_text_match(submitted_email, data.get("email_address")):
        mismatches["email_address"] = "Company email does not match the CAC record."

    submitted_date = _first_present(input_data, "date_of_registration", "cac_registration_date", "registration_date")
    if _parse_date(submitted_date) != _parse_date(data.get("date_of_registration")):
        mismatches["date_of_registration"] = "CAC registration date does not match the CAC record."

    if _normalize_text(data.get("company_status")) != "active":
        mismatches["company_status"] = "Company status must be ACTIVE."

    if mismatches:
        raise ValidationError(mismatches)
    return mismatches


def verify_cac(input_data: dict[str, Any], registration_number: str) -> dict[str, Any]:
    lookup_number, company_type = _split_cac_registration_number(registration_number, input_data)
    body = {
        "rc_number": lookup_number,
        "company_type": company_type,
    }
    company_name = str(input_data.get("company_name") or "").strip()
    if company_name:
        body["company_name"] = company_name

    payload = prembly_lookup(
        verification_type="cac",
        path=settings.PREMBLY_CAC_API_URL,
        lookup_value=f"{company_type}:{lookup_number}",
        body=body,
    )
    data = _select_cac_data(payload, input_data, lookup_number)
    if not _payload_verified(payload) or not data:
        raise ValidationError({"cac_registration_number": extract_prembly_message(payload) or "No CAC record was found for this registration number."})
    validate_cac_payload(input_data, data)
    return payload
