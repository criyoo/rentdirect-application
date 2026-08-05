from __future__ import annotations

from decimal import Decimal, InvalidOperation


BENCHMARK_SCORE_CAP = 100

CATEGORY_LABELS = {
    "identity_verification": "Identity Verification",
    "income_verification": "Income Verification",
    "income_band": "Income Band",
    "current_landlord_details": "Current Landlord Details",
    "rental_history": "Rental History",
    "guarantor_verification": "Guarantor Verification",
    "quality_of_guarantor": "Quality of Guarantor",
    "payment_capacity": "Payment Capacity",
    "household_information": "Household Information",
    "criminal_legal_declaration": "Criminal & Legal Declaration",
}

TRUSTED_GUARANTOR_RELATIONSHIPS = {
    "parent",
    "guardian",
    "spouse",
    "sibling",
    "employer",
    "manager",
    "director",
}


def _has_value(value) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return True
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return str(value).strip() != ""


def _as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value) -> list:
    return value if isinstance(value, list) else []


def _completion_ratio(data: dict, keys: list[str] | tuple[str, ...]) -> float:
    if not keys:
        return 0.0
    completed = sum(1 for key in keys if _has_value(data.get(key)))
    return completed / len(keys)


def _scale_score(ratio: float, *, floor: int = 0) -> int:
    if ratio <= 0:
        return 0
    return min(BENCHMARK_SCORE_CAP, max(floor, round(BENCHMARK_SCORE_CAP * ratio)))


def _to_decimal(value) -> Decimal | None:
    if value is None:
        return None

    if isinstance(value, Decimal):
        return value

    if isinstance(value, (int, float)):
        return Decimal(str(value))

    normalized = str(value).strip()
    if not normalized:
        return None

    cleaned = "".join(char for char in normalized if char.isdigit() or char in {".", "-"})
    if not cleaned or cleaned in {".", "-", "-."}:
        return None

    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _first_decimal(financial_info: dict, *field_names: str) -> Decimal | None:
    """Return the first supplied numeric value from a list of field aliases."""
    for field_name in field_names:
        value = _to_decimal(financial_info.get(field_name))
        if value is not None:
            return value
    return None


def _get_identity_verification_score(profile) -> int:
    if not profile:
        return 0

    if profile.status == profile.Status.APPROVED:
        return BENCHMARK_SCORE_CAP

    required_fields = [
        "first_name",
        "last_name",
        "date_of_birth",
        "gender",
        "nationality",
        "state_of_origin",
        "lga",
        "residence_country",
        "residence_state",
        "residence_city",
        "residence_address",
    ]
    ratio = sum(1 for field in required_fields if _has_value(getattr(profile, field, None))) / len(required_fields)

    if profile.status in {profile.Status.PENDING, profile.Status.UNDER_REVIEW}:
        return _scale_score(0.45 + (ratio * 0.4), floor=40)

    if profile.status == profile.Status.REJECTED:
        return _scale_score(ratio * 0.45)

    return _scale_score(ratio * 0.5)


def _get_income_verification_score(profile) -> int:
    if not profile:
        return 0

    employment_info = _as_dict(profile.employment_info)
    financial_info = _as_dict(profile.financial_info)
    employment_ratio = _completion_ratio(
        employment_info,
        [
            "company_name",
            "company_contact_number",
            "employment_type",
            "employment_start_date",
            "position_job_title",
            "company_address",
            "hr_contact_name",
            "hr_email",
        ],
    )
    financial_fields = [
        "bank_name",
        "account_name",
        "account_number",
        "monthly_income_amount",
        "monthly_expenses",
    ]
    financial_completed = sum(1 for field_name in financial_fields if _has_value(financial_info.get(field_name)))
    if _has_value(financial_info.get("current_annual_rent")) or _has_value(financial_info.get("current_rent_amount")):
        financial_completed += 1
    financial_ratio = financial_completed / (len(financial_fields) + 1)
    combined_ratio = (employment_ratio + financial_ratio) / 2

    if combined_ratio >= 0.85:
        return BENCHMARK_SCORE_CAP
    if combined_ratio >= 0.65:
        return 76
    if combined_ratio >= 0.4:
        return 58
    if combined_ratio > 0:
        return 32
    return 0


def _get_income_band_score(profile) -> int:
    if not profile:
        return 0

    income = _to_decimal(_as_dict(profile.financial_info).get("monthly_income_amount"))
    if income is None or income <= 0:
        return 0
    if income >= Decimal("2000000"):
        return BENCHMARK_SCORE_CAP
    if income >= Decimal("1200000"):
        return 68
    if income >= Decimal("750000"):
        return 60
    if income >= Decimal("400000"):
        return 48
    return 30


def _get_current_landlord_details_score(profile) -> int:
    if not profile:
        return 0

    landlord_info = _as_dict(profile.landlord_info)
    ratio = _completion_ratio(
        landlord_info,
        [
            "name",
            "mobile",
            "email",
            "address",
            "property_manager_name",
            "property_manager_phone",
        ],
    )

    if ratio >= 0.9:
        return BENCHMARK_SCORE_CAP
    if ratio >= 0.65:
        return 70
    if ratio >= 0.4:
        return 50
    if ratio > 0:
        return 28
    return 0


def _entry_completion_ratio(entry: dict, keys: list[str] | tuple[str, ...]) -> float:
    if not isinstance(entry, dict):
        return 0.0
    return _completion_ratio(entry, keys)


def _get_rental_history_score(profile) -> int:
    if not profile:
        return 0

    history_entries = _as_list(profile.rental_history)
    if not history_entries:
        return 0

    ratios = [
        _entry_completion_ratio(
            entry,
            ["property_address", "annual_rent", "move_in_date", "move_out_date", "reason_for_leave"],
        )
        for entry in history_entries
    ]
    average_ratio = sum(ratios) / len(ratios)

    if average_ratio >= 0.9:
        return BENCHMARK_SCORE_CAP
    if average_ratio >= 0.65:
        return 68
    if average_ratio >= 0.4:
        return 50
    return 25


def _get_guarantor_verification_score(profile) -> int:
    if not profile:
        return 0

    guarantor_details = _as_dict(profile.guarantor_details)
    ratio = _completion_ratio(
        guarantor_details,
        [
            "full_name",
            "relationship",
            "email",
            "mobile_number",
            "occupation",
            "employer",
            "residential_address",
        ],
    )

    if ratio >= 0.9:
        return BENCHMARK_SCORE_CAP
    if ratio >= 0.7:
        return 78
    if ratio >= 0.45:
        return 56
    if ratio > 0:
        return 34
    return 0


def _get_quality_of_guarantor_score(profile) -> int:
    if not profile:
        return 0

    guarantor_details = _as_dict(profile.guarantor_details)
    if not guarantor_details:
        return 0

    relationship = str(guarantor_details.get("relationship") or "").strip().lower()
    score = 0

    if relationship in TRUSTED_GUARANTOR_RELATIONSHIPS:
        score += 22
    elif relationship:
        score += 12

    if _has_value(guarantor_details.get("occupation")):
        score += 16
    if _has_value(guarantor_details.get("employer")):
        score += 16
    if _has_value(guarantor_details.get("residential_address")):
        score += 14
    if _has_value(guarantor_details.get("mobile_number")) and _has_value(guarantor_details.get("email")):
        score += 12

    if _has_value(guarantor_details.get("full_name")):
        score += 10

    return min(BENCHMARK_SCORE_CAP, score)


def _get_payment_capacity_score(profile, listing) -> int:
    if not profile or not listing:
        return 0

    financial_info = _as_dict(profile.financial_info)
    yearly_rent = _to_decimal(getattr(listing, "price_per_year", None))
    if yearly_rent is None or yearly_rent <= 0:
        return 0

    employment_status = str(getattr(profile, "employment_status", "") or "").strip().lower()
    if employment_status == "employed":
        monthly_income = _first_decimal(financial_info, "monthly_income_amount")
        if monthly_income is None or monthly_income <= 0:
            return 0

        monthly_outgoings = sum(
            (
                _first_decimal(financial_info, field_name) or Decimal("0")
                for field_name in ("monthly_expenses", "credit_commitment", "outstanding_loans")
            ),
            Decimal("0"),
        )
        available_monthly_income = monthly_income - monthly_outgoings
        if available_monthly_income <= 0:
            return 0

        monthly_rent = yearly_rent / Decimal("12")
        if monthly_rent <= 0:
            return 0
        capacity_ratio = available_monthly_income / monthly_rent
    else:
        average_monthly_income = _first_decimal(
            financial_info,
            "average_monthly_income",
            "monthly_income_amount",
        )
        average_annual_income = _first_decimal(financial_info, "average_annual_income")
        savings = _first_decimal(financial_info, "savings")

        if average_monthly_income is not None and average_monthly_income > 0:
            annual_resources = average_monthly_income * Decimal("12")
        elif average_annual_income is not None and average_annual_income > 0:
            annual_resources = average_annual_income
        elif savings is not None and savings > 0:
            annual_resources = savings
        else:
            return 0

        annual_outgoings = _first_decimal(financial_info, "annual_outgoing_expenses")
        if annual_outgoings is None:
            monthly_outgoings = _first_decimal(
                financial_info,
                "outgoing_expenses",
                "monthly_expenses",
            ) or Decimal("0")
            annual_outgoings = monthly_outgoings * Decimal("12")

        available_annual_resources = annual_resources - annual_outgoings
        if available_annual_resources <= 0:
            return 0
        capacity_ratio = available_annual_resources / yearly_rent

    if capacity_ratio >= Decimal("4"):
        return BENCHMARK_SCORE_CAP
    if capacity_ratio >= Decimal("3"):
        return 80
    if capacity_ratio >= Decimal("2.5"):
        return 72
    if capacity_ratio >= Decimal("2"):
        return 64
    if capacity_ratio >= Decimal("1.5"):
        return 52
    if capacity_ratio >= Decimal("1"):
        return 38
    return 18


def _get_household_information_score(profile) -> int:
    if not profile:
        return 0

    household_info = _as_dict(profile.household_info)
    ratio = _completion_ratio(
        household_info,
        [
            "number_of_adults",
            "number_of_children",
            "has_pets",
            "number_of_pets",
            "work_from_home",
            "commercial_activities_at_home",
            "has_smokers",
        ],
    )

    if ratio >= 0.9:
        return BENCHMARK_SCORE_CAP
    if ratio >= 0.65:
        return 74
    if ratio >= 0.4:
        return 54
    if ratio > 0:
        return 30
    return 0


def _get_criminal_legal_declaration_score(profile) -> int:
    if not profile:
        return 0

    declaration = _as_dict(profile.criminal_declaration)
    keys = [
        "convicted_of_crime",
        "evicted_from_property",
        "ongoing_tenancy_litigation",
        "rent_arrears_history",
        "legal_dispute_with_landlords",
    ]
    answered_values = [declaration.get(key) for key in keys if key in declaration]
    if not answered_values:
        return 0

    answered_ratio = len(answered_values) / len(keys)
    if answered_ratio < 1:
        return _scale_score(answered_ratio * 0.6)

    issue_count = sum(1 for value in answered_values if bool(value))
    if issue_count == 0:
        return BENCHMARK_SCORE_CAP
    if issue_count == 1:
        return 72
    if issue_count == 2:
        return 48
    return 24


def build_tenant_screening_summary(tenant_profile, listing) -> dict:
    category_scores = [
        ("identity_verification", _get_identity_verification_score(tenant_profile)),
        ("income_verification", _get_income_verification_score(tenant_profile)),
        ("income_band", _get_income_band_score(tenant_profile)),
        ("current_landlord_details", _get_current_landlord_details_score(tenant_profile)),
        ("rental_history", _get_rental_history_score(tenant_profile)),
        ("guarantor_verification", _get_guarantor_verification_score(tenant_profile)),
        ("quality_of_guarantor", _get_quality_of_guarantor_score(tenant_profile)),
        ("payment_capacity", _get_payment_capacity_score(tenant_profile, listing)),
        ("household_information", _get_household_information_score(tenant_profile)),
        ("criminal_legal_declaration", _get_criminal_legal_declaration_score(tenant_profile)),
    ]

    total_score = sum(score for _key, score in category_scores)
    category_count = len(category_scores)
    overall_score = round(total_score / category_count, 1) if category_count else 0.0

    return {
        "overall_score": overall_score,
        "categories": [
            {
                "key": key,
                "label": CATEGORY_LABELS[key],
                "score": score,
            }
            for key, score in category_scores
        ],
    }
