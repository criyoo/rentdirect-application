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
                _status("boundary_condition"),
                _status("drainage_condition"),
                _select(
                    "flood_evidence",
                    ["none_observed", "minor_evidence", "major_evidence", "unable_to_verify"],
                ),
                _select("flood_history", ["none_reported", "reported_once", "recurrent", "unknown"]),
                _select("road_access", ["good", "moderate", "difficult", "seasonal"]),
                _select(
                    "structural_condition",
                    ["good", "fair", "requires_maintenance", "requires_specialist"],
                ),
                _status("roof_condition"),
                _status("walls_floors_condition"),
                _status("doors_windows_condition"),
                _multi(
                    "external_issues",
                    [
                        "encroachment",
                        "erosion",
                        "standing_water",
                        "waste_accumulation",
                        "overgrown_vegetation",
                        "pest_breeding_area",
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
                _multi(
                    "power_sources",
                    [
                        "grid",
                        "shared_transformer",
                        "dedicated_transformer",
                        "generator",
                        "solar",
                        "inverter",
                        "ups",
                        "none",
                    ],
                ),
                _select("power_reliability", ["reliable", "variable", "poor", "unknown"]),
                _select(
                    "electricity_meter",
                    ["prepaid", "postpaid", "shared", "none", "unable_to_verify"],
                ),
                _status("electrical_safety"),
                _multi(
                    "water_sources",
                    ["public", "estate", "borehole", "well", "tanker", "vendor", "rainwater", "none"],
                ),
                _select("water_reliability", ["reliable", "variable", "poor", "unknown"]),
                _status("water_quality"),
                _status("plumbing_condition"),
                _status("drainage_sewage_condition"),
                _status("utility_debts"),
                _multi(
                    "internet_mobile",
                    ["mtn", "airtel", "glo", "9mobile", "4g", "5g", "fibre", "fixed_wireless", "none"],
                ),
                _textarea("utility_comments"),
            ],
        },
        {
            "key": "interior",
            "title": "Interior rooms, fixtures & appliances",
            "fields": [
                _status("kitchen_condition"),
                _status("bathroom_condition"),
                _status("bedroom_condition"),
                _status("living_area_condition"),
                _status("ventilation_natural_light"),
                _select("damp_mould", ["none_observed", "minor", "major", "unable_to_verify"]),
                _select("pest_evidence", ["none_observed", "minor", "major", "unable_to_verify"]),
                _multi(
                    "appliances_present",
                    [
                        "refrigerator",
                        "freezer",
                        "cooker",
                        "oven",
                        "microwave",
                        "washing_machine",
                        "water_heater",
                        "air_conditioners",
                        "fans",
                        "generator",
                        "inverter",
                        "solar",
                        "pump",
                        "none",
                    ],
                ),
                _status("appliances_condition"),
                _textarea("interior_comments"),
            ],
        },
        {
            "key": "safety_security",
            "title": "Safety & security",
            "fields": [
                _multi(
                    "security_features",
                    [
                        "guards",
                        "cctv",
                        "access_control",
                        "perimeter_wall",
                        "electric_fence",
                        "burglar_proofing",
                        "security_doors",
                        "alarm",
                        "intercom",
                        "security_lighting",
                        "none",
                    ],
                ),
                _status("locks_access"),
                _multi(
                    "fire_safety_equipment",
                    [
                        "extinguishers",
                        "fire_alarms",
                        "smoke_detectors",
                        "hose_reels",
                        "hydrants",
                        "emergency_exits",
                        "emergency_lighting",
                        "assembly_point",
                        "none",
                    ],
                ),
                _select("fire_electrical_risk", ["low", "moderate", "high", "requires_specialist"]),
                _multi(
                    "environmental_health",
                    [
                        "mould",
                        "dampness",
                        "cockroaches",
                        "rats",
                        "mosquitoes",
                        "termites",
                        "open_sewage",
                        "bad_odour",
                        "pollution",
                        "dumpsite",
                        "noise",
                        "none_observed",
                    ],
                ),
                _select("security_history", ["no_reported_incident", "incidents_reported", "unknown"]),
                _status("emergency_access"),
                _textarea("safety_comments"),
            ],
        },
        {
            "key": "location_accessibility",
            "title": "Location, environment & accessibility",
            "fields": [
                _select("road_condition", ["good", "fair", "poor", "seasonal"]),
                _select("flood_risk", ["low", "moderate", "high", "unknown"]),
                _select("noise_level", ["low", "moderate", "high", "varies"]),
                _select("neighbourhood_security", ["good", "fair", "poor", "unknown"]),
                _select("waste_cleanliness", ["good", "fair", "poor", "unknown"]),
                _multi(
                    "nearby_amenities",
                    [
                        "public_transport",
                        "market",
                        "supermarket",
                        "school",
                        "hospital",
                        "pharmacy",
                        "police",
                        "fire_station",
                        "place_of_worship",
                        "park",
                        "bank_atm",
                        "none",
                    ],
                ),
                _multi(
                    "accessibility_features",
                    [
                        "ground_floor",
                        "ramp",
                        "elevator",
                        "accessible_parking",
                        "accessible_bathroom",
                        "handrails",
                        "wide_doors",
                        "none",
                    ],
                ),
                _textarea("neighbourhood_comments"),
            ],
        },
        {
            "key": "transaction_community",
            "title": "Transaction & community checks",
            "fields": [
                _select(
                    "property_availability",
                    ["verified_vacant", "verified_occupied", "not_available", "unable_to_verify"],
                ),
                _select(
                    "advertised_details_accuracy",
                    ["accurate", "minor_differences", "major_differences", "unable_to_verify"],
                ),
                _select("fees_disclosed", ["yes", "partially", "no", "unable_to_verify"]),
                _multi(
                    "payment_red_flags",
                    [
                        "payment_before_inspection",
                        "pressure_to_pay",
                        "cash_only",
                        "account_name_mismatch",
                        "no_receipt",
                        "multiple_agents",
                        "different_prices",
                        "duplicate_listing",
                        "none_observed",
                    ],
                ),
                _select(
                    "owner_agent_authority",
                    ["verified", "partially_verified", "unverified", "requires_legal_review"],
                ),
                _multi(
                    "community_sources",
                    [
                        "landlord",
                        "current_tenant",
                        "previous_tenant",
                        "neighbour",
                        "estate_manager",
                        "security_personnel",
                        "none",
                    ],
                ),
                _select("community_findings", ["positive", "mixed", "negative", "insufficient_information"]),
                _select("contradictions", ["none", "minor", "material", "unable_to_verify"]),
                _textarea("transaction_comments"),
            ],
        },
        {
            "key": "evidence_limitations",
            "title": "Evidence, readings & limitations",
            "fields": [
                _multi(
                    "evidence_captured",
                    [
                        "property_photos",
                        "videos",
                        "room_photos",
                        "meter_photos",
                        "document_photos",
                        "gps",
                        "inspector_selfie",
                        "property_entrance",
                        "road_condition",
                        "drainage",
                        "flood_evidence",
                        "damage_evidence",
                        "neighbourhood",
                    ],
                ),
                _text("electricity_meter_reading"),
                _text("water_meter_reading"),
                _number("gps_latitude"),
                _number("gps_longitude"),
                _textarea("areas_not_inspected"),
                _textarea("documents_not_provided"),
                _textarea("limitations"),
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
                _multi(
                    "specialist_assessments",
                    [
                        "lawyer",
                        "surveyor",
                        "structural_engineer",
                        "electrician",
                        "plumber",
                        "environmental_specialist",
                        "fire_safety_specialist",
                        "none",
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
