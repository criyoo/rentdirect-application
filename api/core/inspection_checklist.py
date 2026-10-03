from __future__ import annotations

import math
from typing import Any

from rest_framework.exceptions import ValidationError


def _options(*values: str) -> list[dict[str, str]]:
    return [{"value": value, "label": value.replace("_", " ").title()} for value in values]


COMMON_STATUS_OPTIONS = _options(
    "verified",
    "pass_good",
    "issue_found",
    "not_applicable",
    "unable_to_verify",
    "requires_investigation",
)


def _label(key: str) -> str:
    return key.replace("_", " ").capitalize()


def _field(
    key: str,
    field_type: str,
    *,
    required: bool = True,
    options: list[dict[str, str]] | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    field: dict[str, Any] = {
        "key": key,
        "label": label or _label(key),
        "type": field_type,
        "required": required,
    }
    if options is not None:
        field["options"] = options
    return field


def _select(key: str, values: list[str] | tuple[str, ...], *, required: bool = True) -> dict[str, Any]:
    return _field(key, "select", required=required, options=_options(*values))


def _status(key: str, *, required: bool = True) -> dict[str, Any]:
    return _field(key, "select", required=required, options=COMMON_STATUS_OPTIONS)


def _multi(key: str, values: list[str] | tuple[str, ...], *, required: bool = True) -> dict[str, Any]:
    return _field(key, "multiselect", required=required, options=_options(*values))


def _text(key: str, *, required: bool = False) -> dict[str, Any]:
    return _field(key, "text", required=required)


def _textarea(key: str, *, required: bool = False) -> dict[str, Any]:
    return _field(key, "textarea", required=required)


def _number(key: str, *, required: bool = False) -> dict[str, Any]:
    return _field(key, "number", required=required)


def _checkbox(key: str, *, required: bool = True) -> dict[str, Any]:
    return _field(key, "checkbox", required=required)


INSPECTION_CHECKLIST_SCHEMA: dict[str, Any] = {
    "sections": [
        {
            "key": "exterior_structure",
            "title": "Exterior & structural condition",
            "fields": [
                _status("drainage_condition"),
                _select(
                    "flood_evidence",
                    ["none_observed", "minor_evidence", "major_evidence", "unable_to_verify"],
                ),
                _select("flood_history", ["none_reported", "reported_once", "recurrent", "unknown"]),
                _select("road_access", ["good", "moderate", "difficult", "seasonal"]),
                _multi(
                    "external_issues",
                    [
                        "erosion",
                        "standing_water",
                        "none_observed",
                    ],
                ),
                _textarea("structure_comments"),
            ],
        },
        {
            "key": "utilities",
            "title": "Utilities & connectivity",
            "fields": [
                _select("power_reliability", ["reliable", "variable", "poor", "unknown"]),
                _select("water_reliability", ["reliable", "variable", "poor", "unknown"]),
                _status("water_quality"),
                _field(
                    "internet_gsm_strength",
                    "select",
                    options=_options("none", "weak", "good", "strong", "excellent"),
                    label="Internet (GSM) strength",
                ),
                _textarea("utility_comments"),
            ],
        },
        {
            "key": "safety_security",
            "title": "Health Safety",
            "fields": [
                _multi(
                    "environmental_health",
                    [
                        "mould",
                        "dampness",
                        "open_sewage",
                        "bad_odour",
                        "noise",
                        "none_observed",
                    ],
                ),
            ],
        },
        {
            "key": "location_accessibility",
            "title": "Environment & accessibility",
            "fields": [
                _select("noise_level", ["low", "moderate", "high", "varies"]),
                _multi(
                    "nearby_amenities",
                    [
                        "public_transport",
                        "market",
                        "supermarket",
                        "hospital",
                        "pharmacy",
                        "police",
                        "park",
                        "bank_atm",
                        "none",
                    ],
                ),
                _multi(
                    "accessibility_features",
                    [
                        "ground_floor",
                        "elevator",
                        "stairs",
                        "accessible_parking",
                        "wide_doors",
                        "none",
                    ],
                ),
                _textarea("neighbourhood_comments"),
            ],
        },
        {
            "key": "final_assessment",
            "title": "Final assessment & sign-off",
            "fields": [
                _select(
                    "documentation_assessment",
                    ["verified", "partially_verified", "unverified", "requires_legal_review"],
                ),
                _select(
                    "physical_condition",
                    ["good", "fair", "requires_maintenance", "requires_specialist"],
                ),
                _select("utilities_assessment", ["reliable", "variable", "poor", "unknown"]),
                _select(
                    "accessibility_assessment",
                    ["good", "moderate", "difficult", "requires_specialist"],
                ),
                _select(
                    "environmental_risk",
                    ["low_observed_risk", "some_concerns", "significant_concerns", "requires_specialist"],
                ),
                _select(
                    "occupant_experience",
                    ["positive", "mixed", "negative", "insufficient_information"],
                ),
                _select(
                    "overall_status",
                    [
                        "inspection_completed",
                        "inspection_completed_with_issues",
                        "further_investigation_required",
                        "specialist_or_legal_verification_required",
                    ],
                ),
                _multi(
                    "critical_red_flags",
                    [
                        "ownership_unestablished",
                        "suspected_fraud",
                        "title_dispute",
                        "active_litigation",
                        "severe_structural_damage",
                        "major_flood_risk",
                        "unsafe_electrical",
                        "no_legal_authority",
                        "severe_access_problem",
                        "undisclosed_financial_liability",
                        "none_observed",
                    ],
                ),
                _textarea("final_recommendation", required=True),
                _checkbox("inspector_declaration"),
            ],
        },
    ]
}

_ALL_FIELDS: dict[str, dict[str, Any]] = {
    field["key"]: field for section in INSPECTION_CHECKLIST_SCHEMA["sections"] for field in section["fields"]
}

ISSUE_SELECT_VALUES = {"issue_found", "requires_investigation"}
ISSUE_OPTION_VALUES = {
    "issue_found",
    "requires_investigation",
    "requires_specialist",
    "requires_legal_review",
    "major_evidence",
    "major",
    "high",
    "poor",
    "difficult",
    "material",
    "negative",
    "significant_concerns",
    "incidents_reported",
    "recurrent",
    "unverified",
    "not_available",
    "major_differences",
    "further_investigation_required",
    "specialist_or_legal_verification_required",
    "inspection_completed_with_issues",
}
EXCLUDED_ANALYSIS_VALUES = {"none", "none_observed"}

FINAL_CATEGORY_KEYS = [
    "documentation_assessment",
    "physical_condition",
    "utilities_assessment",
    "accessibility_assessment",
    "environmental_risk",
    "occupant_experience",
]


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip()) or value == []


def validate_inspection_responses(
    responses: Any,
    require_complete: bool = False,
) -> dict[str, Any]:
    if not isinstance(responses, dict):
        raise ValidationError("Inspection responses must be an object.")

    unknown_keys = sorted(set(responses.keys()) - set(_ALL_FIELDS.keys()))
    if unknown_keys:
        raise ValidationError({key: "Unknown checklist field." for key in unknown_keys})

    cleaned: dict[str, Any] = {}
    errors: dict[str, Any] = {}

    for key, field in _ALL_FIELDS.items():
        field_type = field["type"]
        value = responses.get(key)
        missing = key not in responses or _is_blank(value)

        if missing:
            if require_complete and field.get("required"):
                errors[key] = "This field is required."
            continue

        if field_type == "select":
            if not isinstance(value, str):
                errors[key] = "Expected a single option value."
                continue
            valid = {option["value"] for option in field.get("options", [])}
            if value not in valid:
                errors[key] = "Invalid option."
                continue
            cleaned[key] = value
        elif field_type == "multiselect":
            if not isinstance(value, list):
                errors[key] = "Expected a list of option values."
                continue
            deduped: list[str] = []
            invalid = False
            valid = {option["value"] for option in field.get("options", [])}
            for item in value:
                if not isinstance(item, str) or item not in valid:
                    invalid = True
                    break
                if item not in deduped:
                    deduped.append(item)
            if invalid:
                errors[key] = "Invalid option."
                continue
            if len(deduped) > 1 and EXCLUDED_ANALYSIS_VALUES.intersection(deduped):
                errors[key] = "Choose None on its own."
                continue
            if require_complete and field.get("required") and not deduped:
                errors[key] = "This field is required."
                continue
            cleaned[key] = deduped
        elif field_type == "number":
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                errors[key] = "Expected a number."
                continue
            if not math.isfinite(numeric):
                errors[key] = "Expected a finite number."
                continue
            if key == "gps_latitude" and not -90 <= numeric <= 90:
                errors[key] = "Latitude must be between -90 and 90."
                continue
            if key == "gps_longitude" and not -180 <= numeric <= 180:
                errors[key] = "Longitude must be between -180 and 180."
                continue
            cleaned[key] = numeric
        elif field_type == "checkbox":
            if not isinstance(value, bool):
                errors[key] = "Expected a true/false value."
                continue
            if require_complete and field.get("required") and value is not True:
                errors[key] = "This declaration must be accepted."
                continue
            cleaned[key] = value
        else:  # text/textarea
            if not isinstance(value, str):
                errors[key] = "Expected text."
                continue
            cleaned[key] = value.strip()

    if errors:
        raise ValidationError(errors)
    return cleaned


def build_inspection_analysis(responses: dict[str, Any]) -> dict[str, Any]:
    total_item_count = len(_ALL_FIELDS)
    completed_item_count = sum(
        1 for key in _ALL_FIELDS if key in responses and not _is_blank(responses[key])
    )

    issue_item_keys: list[str] = []
    for key, field in _ALL_FIELDS.items():
        value = responses.get(key)
        if _is_blank(value):
            continue
        if field["type"] == "select" and value in ISSUE_OPTION_VALUES:
            issue_item_keys.append(key)
        elif field["type"] == "multiselect":
            meaningful = [item for item in value if item not in EXCLUDED_ANALYSIS_VALUES]
            if key == "critical_red_flags":
                continue
            if key in {"external_issues", "environmental_health", "payment_red_flags"} and meaningful:
                issue_item_keys.append(key)

    critical_red_flags = [
        item
        for item in responses.get("critical_red_flags", []) or []
        if item != "none_observed"
    ]
    specialist_assessments = [
        item
        for item in responses.get("specialist_assessments", []) or []
        if item != "none"
    ]

    analysis: dict[str, Any] = {
        "completed_item_count": completed_item_count,
        "total_item_count": total_item_count,
        "issue_item_keys": issue_item_keys,
        "critical_red_flags": critical_red_flags,
        "overall_status": responses.get("overall_status", ""),
        "specialist_assessments": specialist_assessments,
        "final_recommendation": responses.get("final_recommendation", ""),
    }
    for key in FINAL_CATEGORY_KEYS:
        analysis[key] = responses.get(key, "")
    return analysis
