from datetime import date, datetime
from typing import Any


TENANT_VERIFICATION_PROFILE_FIELDS = (
    "first_name",
    "middle_name",
    "last_name",
    "country_of_birth",
    "date_of_birth",
    "gender",
    "nationality",
    "state_of_origin",
    "lga",
    "email",
    "mobile",
    "employment_status",
    "nin_number",
    "bvn_number",
)

TENANT_VERIFICATION_FIELD_ALIASES = {
    "nin": "nin_number",
    "bvn": "bvn_number",
}


def normalize_tenant_verification_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()

    raw_value = str(value or "").strip()
    if not raw_value:
        return ""

    for date_format in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw_value, date_format).date().isoformat()
        except ValueError:
            continue

    return raw_value


def normalize_tenant_verification_profile(raw_profile: dict | None, user=None) -> dict:
    source = dict(raw_profile or {})
    for alias, canonical_key in TENANT_VERIFICATION_FIELD_ALIASES.items():
        if source.get(alias) and not source.get(canonical_key):
            source[canonical_key] = source[alias]

    if user is not None:
        source.setdefault("email", getattr(user, "email", ""))
        source.setdefault("mobile", getattr(user, "mobile", ""))
        source.setdefault("nin_number", getattr(user, "nin_number", ""))
        source.setdefault("bvn_number", getattr(user, "bvn_number", ""))
        source.setdefault("state_of_origin", getattr(user, "state_of_origin", ""))

    normalized = {}
    for field_name in TENANT_VERIFICATION_PROFILE_FIELDS:
        value = source.get(field_name)
        if field_name == "date_of_birth":
            value = normalize_tenant_verification_date(value)
        else:
            value = str(value or "").strip()
        if value != "":
            normalized[field_name] = value

    return normalized
