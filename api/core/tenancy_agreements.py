"""Tenancy agreement drafting, validation and rendering.

Renders the packaged Nigeria tenancy agreement Markdown template using a small
stdlib-only Handlebars-style engine, builds the structured agreement payload
from persisted landlord/tenant/listing/booking records and persists each
generated version as an immutable ``TenancyAgreement`` row.
"""

import copy
import hashlib
import math
import re
import uuid
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django.utils.html import strip_tags
from rest_framework.exceptions import ValidationError

from .models import (
    AppUser,
    Booking,
    TenancyAgreement,
    complete_booking_progress_step,
    sync_listing_status_from_rental_progress,
)

TEMPLATE_VERSION = "1.1.0"
TEMPLATE_PATH = Path(__file__).resolve().parent / "legal" / "nigeria_tenancy_agreement_template.md"
TEMPLATE_DOCUMENT_MARKER = "# TENANCY AGREEMENT"
TEMPLATE_NOTES_MARKER = "## APPLICATION IMPLEMENTATION NOTES"
MAX_TEXT_LENGTH = 5000

LAGOS_EXCLUDED_AREA_MARKERS = ("apapa", "ikeja gra", "ikoyi", "victoria island")
COMMERCIAL_PROPERTY_TYPE_MARKERS = ("commercial", "office", "shop", "retail", "warehouse", "business", "industrial")
POSITIVE_NUMBER_PATHS = frozenset({
    "property.inspectionNoticeHours",
    "fees.securityDepositRefundDays",
    "maintenance.maximumRestorationDays",
    "dispute.arbitratorCount",
})
MONEY_PATH_PREFIX = "money."

DOCUMENT_HASH_PLACEHOLDER = "Stored separately in the RentDirect audit record"
SIGNING_PROVIDER_LABEL = "RentDirect review workflow"
PAYMENT_METHOD_LABEL = "RentDirect electronic payment platform"
POSSESSION_TRIGGER_DEFAULT = "receipt of the agreed initial payment and physical handover of the Premises"

_MISSING = object()


def _string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _lookup(data: Any, path: str, default: Any = _MISSING) -> Any:
    current = data
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part, _MISSING)
        else:
            return default
        if current is _MISSING:
            return default
    return current


def _set_path(data: dict, path: str, value: Any) -> None:
    keys = path.split(".")
    cursor = data
    for key in keys[:-1]:
        child = cursor.get(key)
        if not isinstance(child, dict):
            child = {}
            cursor[key] = child
        cursor = child
    cursor[keys[-1]] = value


def _first_nonblank(*values: Any) -> str:
    for value in values:
        text = _string(value)
        if text:
            return text
    return ""


def _amount_decimal(value: Any) -> Decimal:
    if isinstance(value, bool):
        return Decimal("0")
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, AttributeError):
        return Decimal("0")
    return amount if amount.is_finite() else Decimal("0")


def _json_amount(value: Decimal) -> int | float:
    quantized = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(quantized) if quantized == quantized.to_integral_value() else float(quantized)


def _format_date_human(value: date | None) -> str:
    return value.strftime("%d %B %Y") if isinstance(value, date) else ""


def _format_date_input(value: date | None) -> str:
    return value.isoformat() if isinstance(value, date) else ""


def _add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(day.day, monthrange(year, month)[1]))


def _describe_term(start: date | None, end: date | None) -> tuple[int, str]:
    if not isinstance(start, date) or not isinstance(end, date) or end < start:
        return 0, "days"

    for months in range(1, 361):
        aligned = _add_months(start, months)
        if aligned == end or aligned == end + timedelta(days=1):
            if months % 12 == 0:
                years = months // 12
                return years, "year" if years == 1 else "years"
            return months, "month" if months == 1 else "months"
        if aligned > end:
            break

    days = (end - start).days + 1
    return days, "day" if days == 1 else "days"


_NAIRA_ONES = (
    "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
    "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
    "Seventeen", "Eighteen", "Nineteen",
)
_NAIRA_TENS = ("", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety")


def _three_digit_words(number: int) -> str:
    parts = []
    if number >= 100:
        parts.append(f"{_NAIRA_ONES[number // 100]} Hundred")
        number %= 100
    if number >= 20:
        parts.append(_NAIRA_TENS[number // 10])
        number %= 10
    if number:
        parts.append(_NAIRA_ONES[number])
    return " ".join(part for part in parts if part)


def naira_amount_in_words(amount: Any) -> str:
    try:
        value = Decimal(str(amount)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return ""
    if value < 0:
        value = abs(value)

    naira = int(value)
    kobo = int((value - naira) * 100)

    groups = []
    remainder = naira
    for scale, label in ((10**9, "Billion"), (10**6, "Million"), (10**3, "Thousand")):
        if remainder >= scale:
            group, remainder = divmod(remainder, scale)
            group_words = _three_digit_words(group % 1000)
            if group_words:
                groups.append(f"{group_words} {label}")
    if remainder:
        groups.append(_three_digit_words(remainder))

    words = " ".join(groups) if groups else "Zero"
    result = f"{words} Naira"
    if kobo:
        result += f" and {_three_digit_words(kobo)} Kobo"
    return f"{result} only"


_FORM_FIELDS: list[dict[str, Any]] = [
    {"path": "landlord.address", "section": "Parties", "label": "Landlord address", "type": "textarea", "required": True},
    {"path": "landlord.phone", "section": "Parties", "label": "Landlord phone", "type": "text", "required": True},
    {"path": "tenant.address", "section": "Parties", "label": "Tenant address", "type": "textarea", "required": True},
    {"path": "tenant.phone", "section": "Parties", "label": "Tenant phone", "type": "text", "required": True},

    {"path": "property.state", "section": "Property", "label": "State", "type": "text", "required": True},
    {"path": "property.localGovernmentArea", "section": "Property", "label": "Local government area", "type": "text", "required": True},
    {"path": "property.fullAddress", "section": "Property", "label": "Full property address", "type": "textarea", "required": True},
    {"path": "property.type", "section": "Property", "label": "Property type", "type": "text", "required": True},
    {"path": "property.unitDescription", "section": "Property", "label": "Unit / apartment / shop description", "type": "text", "required": True},
    {"path": "property.floor", "section": "Property", "label": "Floor", "type": "text", "required": False},
    {"path": "property.roomsDescription", "section": "Property", "label": "Rooms description", "type": "text", "required": True},
    {"path": "property.ancillaryAreas", "section": "Property", "label": "Parking / ancillary areas", "type": "text", "required": False},
    {"path": "property.reference", "section": "Property", "label": "Title / property reference", "type": "text", "required": False},
    {"path": "property.inspectionNoticeHours", "section": "Property", "label": "Inspection notice (hours)", "type": "number", "required": True, "help_text": "Minimum hours of prior notice before a non-emergency inspection."},

    {"path": "tenancy.permittedUse", "section": "Tenancy", "label": "Permitted use", "type": "textarea", "required": True},
    {"path": "tenancy.possessionTrigger", "section": "Tenancy", "label": "Possession trigger", "type": "textarea", "required": True, "help_text": "When the tenant's right to occupy the premises begins."},

    {"path": "payments.rentFrequency", "section": "Payments", "label": "Rent frequency", "type": "select", "required": True, "options": [{"value": "monthly", "label": "Monthly"}, {"value": "quarterly", "label": "Quarterly"}, {"value": "half-yearly", "label": "Half-yearly"}, {"value": "yearly", "label": "Yearly"}]},
    {"path": "payments.rentDueDate", "section": "Payments", "label": "Rent due date", "type": "date", "required": True},
    {"path": "payments.paymentMethodDescription", "section": "Payments", "label": "Payment method", "type": "text", "required": True},
    {"path": "payments.latePaymentInterestEnabled", "section": "Payments", "label": "Late-payment interest applies", "type": "checkbox", "required": False},
    {"path": "payments.latePaymentInterestRate", "section": "Payments", "label": "Late-payment interest rate", "type": "text", "required": False, "help_text": "Required when late-payment interest is enabled, for example 10%."},

    {"path": "money.securityDeposit", "section": "Charges", "label": "Security / caution deposit (NGN)", "type": "number", "required": False},
    {"path": "money.serviceCharge", "section": "Charges", "label": "Service charge (NGN)", "type": "number", "required": False},
    {"path": "money.facilityCharge", "section": "Charges", "label": "Facility / estate charge (NGN)", "type": "number", "required": False},
    {"path": "money.agencyFee", "section": "Charges", "label": "Agency / commission fee (NGN)", "type": "number", "required": False},
    {"path": "money.otherFeesTotal", "section": "Charges", "label": "Other agreed charges (NGN)", "type": "number", "required": False},

    {"path": "fees.securityDepositRefundDays", "section": "Responsibilities", "label": "Security deposit refund period (days)", "type": "number", "required": True},
    {"path": "fees.utilitiesResponsibility", "section": "Responsibilities", "label": "Utilities responsibility", "type": "textarea", "required": True},
    {"path": "fees.taxesAndStatutoryCharges", "section": "Responsibilities", "label": "Taxes and statutory charges", "type": "textarea", "required": True},
    {"path": "fees.stampingRegistrationResponsibility", "section": "Responsibilities", "label": "Stamping / registration responsibility", "type": "textarea", "required": True},
    {"path": "maintenance.landlordResponsibilities", "section": "Responsibilities", "label": "Landlord maintenance responsibilities", "type": "textarea", "required": True},
    {"path": "maintenance.tenantResponsibilities", "section": "Responsibilities", "label": "Tenant maintenance responsibilities", "type": "textarea", "required": True},
    {"path": "maintenance.rentAbatementRule", "section": "Responsibilities", "label": "Rent abatement rule", "type": "textarea", "required": True},
    {"path": "maintenance.maximumRestorationDays", "section": "Responsibilities", "label": "Maximum restoration period (days)", "type": "number", "required": True},

    {"path": "renewal.renewalOption", "section": "Renewal & dispute", "label": "Renewal option", "type": "text", "required": True},
    {"path": "renewal.noticeMonths", "section": "Renewal & dispute", "label": "Renewal notice (months)", "type": "number", "required": True},
    {"path": "renewal.specialRenewalNotice", "section": "Renewal & dispute", "label": "Special renewal notice", "type": "textarea", "required": False},
    {"path": "dispute.arbitrationEnabled", "section": "Renewal & dispute", "label": "Arbitration clause applies", "type": "checkbox", "required": False},
    {"path": "dispute.arbitrationVenue", "section": "Renewal & dispute", "label": "Arbitration seat / venue", "type": "text", "required": False, "help_text": "Required when arbitration is enabled."},
    {"path": "dispute.arbitratorCount", "section": "Renewal & dispute", "label": "Number of arbitrators", "type": "number", "required": False, "help_text": "Required when arbitration is enabled."},
    {"path": "dispute.appointingAuthority", "section": "Renewal & dispute", "label": "Appointing authority", "type": "text", "required": False, "help_text": "Required when arbitration is enabled."},

    {"path": "handover.dateFormatted", "section": "Handover", "label": "Handover date", "type": "date", "required": True},
    {"path": "handover.electricityMeterReading", "section": "Handover", "label": "Electricity meter reading", "type": "text", "required": False},
    {"path": "handover.waterMeterReading", "section": "Handover", "label": "Water meter reading", "type": "text", "required": False},
    {"path": "handover.gasMeterReading", "section": "Handover", "label": "Gas meter reading", "type": "text", "required": False},
    {"path": "handover.otherMeterReadings", "section": "Handover", "label": "Other meter readings", "type": "text", "required": False},
    {"path": "handover.keysDescription", "section": "Handover", "label": "Keys / access devices provided", "type": "text", "required": False},
    {"path": "handover.inventoryDescription", "section": "Handover", "label": "Furniture / fixtures / fittings", "type": "textarea", "required": False},
    {"path": "handover.existingDefects", "section": "Handover", "label": "Existing defects / exclusions", "type": "textarea", "required": False},

    {"path": "commercial.businessDescription", "section": "Commercial", "label": "Business / trade description", "type": "textarea", "required": False, "help_text": "Required for commercial tenancies."},
    {"path": "commercial.signageRules", "section": "Commercial", "label": "Permitted signage", "type": "textarea", "required": False},
    {"path": "commercial.operatingHours", "section": "Commercial", "label": "Opening / operating hours", "type": "text", "required": False},
    {"path": "commercial.customerAccessRules", "section": "Commercial", "label": "Customer / public access rules", "type": "textarea", "required": False},
    {"path": "commercial.licensingResponsibilities", "section": "Commercial", "label": "Licences / permits responsibility", "type": "textarea", "required": False},
    {"path": "commercial.fitOutPeriod", "section": "Commercial", "label": "Fit-out period", "type": "text", "required": False},
    {"path": "commercial.fitOutRules", "section": "Commercial", "label": "Fit-out works permitted", "type": "textarea", "required": False},
    {"path": "commercial.reinstatementRules", "section": "Commercial", "label": "Reinstatement obligation", "type": "textarea", "required": False},
    {"path": "commercial.serviceChargeMechanism", "section": "Commercial", "label": "Service charge mechanism", "type": "textarea", "required": False},
    {"path": "commercial.insuranceRequirements", "section": "Commercial", "label": "Insurance requirements", "type": "textarea", "required": False},
    {"path": "commercial.assignmentRules", "section": "Commercial", "label": "Assignment / change of control provisions", "type": "textarea", "required": False},
]


def agreement_form_fields() -> list[dict[str, Any]]:
    return [dict(field) for field in _FORM_FIELDS]


def _lagos_excluded(data: dict) -> bool:
    state = _string(_lookup(data, "property.state", "")).casefold()
    if state not in ("lagos", "lagos state"):
        return False
    location_text = " ".join(
        _string(_lookup(data, path, ""))
        for path in ("property.localGovernmentArea", "property.fullAddress")
    ).casefold()
    return any(marker in location_text for marker in LAGOS_EXCLUDED_AREA_MARKERS)


def _notice_period_description(end_date_formatted: str, excluded: bool) -> str:
    text = (
        f"This is a fixed-term tenancy that expires on {end_date_formatted} without any requirement "
        "for renewal; any mandatory statutory notices required by applicable law before lawful "
        "recovery of possession remain unaffected."
    )
    if excluded:
        text += (
            " The Premises are located in an area expressly excluded from the Lagos State Tenancy "
            "Law 2011 (Apapa, Ikeja GRA, Ikoyi or Victoria Island), so that Law does not apply and "
            "other applicable law governs."
        )
    return text


RENT_FREQUENCY_DIVISORS = {
    "yearly": Decimal("1"),
    "half-yearly": Decimal("2"),
    "quarterly": Decimal("4"),
    "monthly": Decimal("12"),
}
RENT_FREQUENCY_MONTHS = {"yearly": 12, "half-yearly": 6, "quarterly": 3, "monthly": 1}


def _first_rent_period(frequency: str, start: date | None, end: date | None) -> str:
    if not isinstance(start, date):
        return ""
    months = RENT_FREQUENCY_MONTHS.get(frequency, 12)
    period_end = _add_months(start, months)
    if isinstance(end, date) and period_end > end:
        period_end = end
    return f"{_format_date_human(start)} to {_format_date_human(period_end)}"


def _refresh_derived_fields(data: dict, *, annual_rent: Decimal, booking_start, booking_end) -> None:
    tenancy = data["tenancy"]
    is_commercial = bool(tenancy.get("isCommercial"))
    tenancy["isCommercial"] = is_commercial
    tenancy["useTypeLabel"] = "Commercial Tenancy" if is_commercial else "Residential Tenancy"

    property_data = data["property"]
    excluded = _lagos_excluded(data)
    property_data["isExcludedFromLagosTenancyLaw"] = excluded
    data["termination"]["noticePeriodDescription"] = _notice_period_description(
        _string(tenancy.get("endDateFormatted")), excluded
    )

    payments = data["payments"]
    frequency = _string(payments.get("rentFrequency")).casefold()
    divisor = RENT_FREQUENCY_DIVISORS.get(frequency, Decimal("1"))
    payments["firstRentPeriod"] = _first_rent_period(frequency, booking_start, booking_end)

    money = data["money"]
    period_rent = (annual_rent / divisor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    money["rentAmount"] = _json_amount(period_rent)
    money["rentAmountWords"] = naira_amount_in_words(period_rent)
    total = period_rent + sum(
        (_amount_decimal(money.get(key)) for key in (
            "securityDeposit", "serviceCharge", "facilityCharge",
            "agencyFee", "otherFeesTotal",
        )),
        Decimal("0"),
    )
    money["totalInitialAmount"] = _json_amount(total)

    agreement = data["agreement"]
    agreement["templateVersion"] = TEMPLATE_VERSION
    agreement["signingProvider"] = SIGNING_PROVIDER_LABEL
    agreement["status"] = "REVIEW"
    if not _string(agreement.get("documentHash")):
        agreement["documentHash"] = DOCUMENT_HASH_PLACEHOLDER


def _landlord_party_data(landlord: AppUser) -> dict[str, Any]:
    profile = landlord.landlord_verification_profile if isinstance(landlord.landlord_verification_profile, dict) else {}
    residence = landlord.residence if isinstance(landlord.residence, dict) else {}
    residential_information = profile.get("residential_information") if isinstance(profile.get("residential_information"), dict) else {}
    is_company = landlord.landlord_verification_type == AppUser.LandlordVerificationType.CORPORATE

    if is_company:
        name = _first_nonblank(profile.get("company_name"), landlord.name)
    else:
        name = _string(landlord.name)

    return {
        "name": name,
        "address": _first_nonblank(
            profile.get("residential_address"),
            profile.get("business_address"),
            residential_information.get("address"),
            residence.get("address"),
        ),
        "email": _string(landlord.email),
        "phone": _first_nonblank(
            profile.get("contact_number"),
            profile.get("company_phone_number"),
            landlord.mobile,
        ),
        "isCompany": is_company,
    }


def _tenant_party_data(tenant: AppUser) -> dict[str, Any]:
    profile = tenant.tenant_verification_profile if isinstance(tenant.tenant_verification_profile, dict) else {}
    residence = tenant.residence if isinstance(tenant.residence, dict) else {}
    residential_information = profile.get("residential_information") if isinstance(profile.get("residential_information"), dict) else {}
    tenant_profile = getattr(tenant, "tenant_profile", None)

    return {
        "name": _string(tenant.name),
        "address": _first_nonblank(
            profile.get("residence_address"),
            residential_information.get("address"),
            residence.get("address"),
            getattr(tenant_profile, "residence_address", ""),
        ),
        "email": _string(tenant.email),
        "phone": _first_nonblank(profile.get("mobile"), tenant.mobile),
        "isCompany": False,
    }


def _base_agreement_data(booking: Booking, agreement_id: uuid.UUID, generated_at) -> dict[str, Any]:
    listing = booking.listing
    landlord = listing.landlord
    tenant = booking.tenant

    property_type = _string(listing.property_type)
    is_commercial = any(marker in property_type.casefold() for marker in COMMERCIAL_PROPERTY_TYPE_MARKERS)

    full_address = ", ".join(
        part for part in (_string(listing.address), _string(listing.city), _string(listing.state)) if part
    )
    ancillary = [
        label
        for enabled, label in (
            (listing.parking, "Parking"),
            (listing.garage, "Garage"),
            (listing.garden, "Garden"),
            (listing.balcony, "Balcony"),
            (listing.boys_quarters, "Boys' quarters"),
        )
        if enabled
    ]
    room_parts = []
    if listing.bedrooms:
        room_parts.append(f"{listing.bedrooms} bedroom{'s' if listing.bedrooms != 1 else ''}")
    if listing.bathrooms:
        room_parts.append(f"{listing.bathrooms} bathroom{'s' if listing.bathrooms != 1 else ''}")
    if listing.toilets:
        room_parts.append(f"{listing.toilets} toilet{'s' if listing.toilets != 1 else ''}")

    start = booking.start_date
    end = booking.end_date
    term_value, term_unit = _describe_term(start, end)
    start_formatted = _format_date_human(start)
    end_formatted = _format_date_human(end)

    rent_amount = _json_amount(_amount_decimal(listing.price_per_year or 0))
    security_deposit = _json_amount(_amount_decimal(listing.caution_fee or 0))
    service_charge = _json_amount(_amount_decimal(listing.service_charge or 0))

    return {
        "agreement": {
            "id": str(agreement_id),
            "dateFormatted": _format_date_human(generated_at.date() if generated_at else date.today()),
            "templateVersion": TEMPLATE_VERSION,
            "generatedAt": generated_at.isoformat() if generated_at else "",
            "finalisedAt": "",
            "documentHash": DOCUMENT_HASH_PLACEHOLDER,
            "signingProvider": SIGNING_PROVIDER_LABEL,
            "status": "REVIEW",
        },
        "property": {
            "state": _string(listing.state),
            "localGovernmentArea": _string(listing.lga),
            "fullAddress": full_address,
            "type": property_type,
            "unitDescription": _string(listing.title),
            "floor": str(listing.floor_number) if listing.floor_number is not None else "",
            "roomsDescription": ", ".join(room_parts),
            "ancillaryAreas": ", ".join(ancillary),
            "reference": str(listing.id),
            "inspectionNoticeHours": 48,
            "isExcludedFromLagosTenancyLaw": False,
        },
        "landlord": _landlord_party_data(landlord),
        "tenant": _tenant_party_data(tenant),
        "tenancy": {
            "useTypeLabel": "Commercial Tenancy" if is_commercial else "Residential Tenancy",
            "permittedUse": (
                "The tenant's lawful commercial business as described in this agreement"
                if is_commercial
                else "Private residential use"
            ),
            "termValue": term_value,
            "termUnit": term_unit,
            "startDateFormatted": start_formatted,
            "endDateFormatted": end_formatted,
            "possessionTrigger": POSSESSION_TRIGGER_DEFAULT,
            "isFixedTerm": True,
            "isCommercial": is_commercial,
        },
        "payments": {
            "rentFrequency": "yearly",
            "rentDueDate": _format_date_input(start),
            "firstRentPeriod": f"{start_formatted} to {end_formatted}" if start_formatted else "",
            "paymentMethodDescription": PAYMENT_METHOD_LABEL,
            "latePaymentInterestEnabled": False,
            "latePaymentInterestRate": "",
            "initialPaymentDueDate": _format_date_input(start),
        },
        "money": {
            "rentAmount": rent_amount,
            "rentAmountWords": naira_amount_in_words(rent_amount),
            "securityDeposit": security_deposit,
            "serviceCharge": service_charge,
            "facilityCharge": 0,
            "agencyFee": 0,
            "otherFeesTotal": 0,
            "totalInitialAmount": 0,
        },
        "fees": {
            "securityDepositFrequency": "once",
            "securityDepositRefundable": "Yes",
            "securityDepositRefundDays": 30,
            "serviceChargeFrequency": "annual",
            "serviceChargeRefundable": "No",
            "facilityChargeFrequency": "annual",
            "facilityChargeRefundable": "No",
            "agencyFeeFrequency": "once",
            "agencyFeePayer": "as agreed",
            "otherFeesFrequency": "as agreed",
            "otherFeesPayer": "as agreed",
            "otherFeesRefundable": "No",
            "utilitiesResponsibility": "The Tenant shall pay consumption-based utilities; the Landlord shall pay structural or ownership charges required by law",
            "taxesAndStatutoryCharges": "as required by law",
            "stampingRegistrationResponsibility": "as agreed and subject to applicable law",
        },
        "maintenance": {
            "landlordResponsibilities": "Structural, external and common-area repairs, except damage caused by the Tenant",
            "tenantResponsibilities": "Interior upkeep, cleanliness and minor non-structural repairs, fair wear and tear excepted",
            "rentAbatementRule": "as required by law / agreed",
            "maximumRestorationDays": 90,
        },
        "termination": {
            "noticePeriodDescription": _notice_period_description(end_formatted, False),
            "preExpiryInspectionDays": 30,
            "holdingOverRateDescription": "reasonable use and occupation rate, subject to applicable law",
        },
        "renewal": {
            "renewalOption": "by mutual written agreement",
            "noticeMonths": 3,
            "specialRenewalNotice": "",
        },
        "dispute": {
            "arbitrationEnabled": False,
            "arbitrationVenue": "Lagos, Nigeria",
            "arbitratorCount": 1,
            "appointingAuthority": "as agreed or competent authority under applicable law",
        },
        "handover": {
            "dateFormatted": _format_date_input(start),
            "electricityMeterReading": "",
            "waterMeterReading": "",
            "gasMeterReading": "",
            "otherMeterReadings": "",
            "keysDescription": "",
            "inventoryDescription": "",
            "existingDefects": "",
        },
        "commercial": {
            "businessDescription": "",
            "signageRules": "Signage only with the Landlord's prior written consent and in compliance with applicable planning rules.",
            "operatingHours": "Reasonable business hours that do not cause nuisance to neighbouring occupiers.",
            "customerAccessRules": "Customer and public access subject to applicable building and estate rules.",
            "licensingResponsibilities": "The Tenant shall obtain and maintain all licences and permits required for the Tenant's business.",
            "fitOutPeriod": "As agreed in writing between the Parties.",
            "fitOutRules": "Non-structural fit-out works only, with the Landlord's prior written approval.",
            "reinstatementRules": "The Premises shall be reinstated to their prior condition at expiry, fair wear and tear excepted, unless otherwise agreed in writing.",
            "serviceChargeMechanism": "Service charges shall be applied as stated in the payment schedule and accounted for where required by applicable law.",
            "insuranceRequirements": "Each Party shall maintain insurance appropriate to its interest and obligations under applicable law.",
            "assignmentRules": "Assignment, subletting or change of control only with the Landlord's prior written consent, subject to applicable law.",
        },
        "specialConditions": [],
        "witnesses": [],
        "signatures": {
            "landlord": {"signedAtFormatted": "", "signatureId": "", "signatoryName": "", "signatoryCapacity": ""},
            "tenant": {"signedAtFormatted": "", "signatureId": "", "signatoryName": "", "signatoryCapacity": ""},
        },
    }


def _coerce_override_value(field: dict[str, Any], raw: Any) -> Any:
    field_type = field["type"]
    if field_type == "checkbox":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)):
            return raw != 0
        normalized = _string(raw).casefold()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
        return _MISSING
    if field_type == "number":
        if isinstance(raw, bool):
            return _MISSING
        if isinstance(raw, (int, float)):
            numeric = float(raw)
        else:
            text = _string(raw)
            if not text:
                return _MISSING
            try:
                numeric = float(text)
            except ValueError:
                return raw
        if not math.isfinite(numeric):
            return raw
        return int(numeric) if numeric.is_integer() else numeric
    return _string(raw)


def _apply_overrides(data: dict, overrides: dict[str, Any]) -> None:
    for field in _FORM_FIELDS:
        raw = _lookup(overrides, field["path"])
        if raw is _MISSING:
            continue
        value = _coerce_override_value(field, raw)
        if value is _MISSING:
            continue
        _set_path(data, field["path"], value)


def build_agreement_draft(
    booking: Booking,
    overrides: dict[str, Any] | None = None,
    *,
    agreement_id: uuid.UUID | None = None,
    generated_at=None,
) -> dict[str, Any]:
    generated_at = generated_at or timezone.now()
    data = _base_agreement_data(booking, agreement_id or uuid.uuid4(), generated_at)
    if isinstance(overrides, dict):
        _apply_overrides(data, overrides)
    _refresh_derived_fields(
        data,
        annual_rent=_amount_decimal(booking.listing.price_per_year or 0),
        booking_start=booking.start_date,
        booking_end=booking.end_date,
    )
    return data


def _is_blank_for_field(value: Any, field: dict[str, Any]) -> bool:
    if field["type"] == "number":
        if value is None or value == "":
            return True
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return False
        return field["path"] in POSITIVE_NUMBER_PATHS and numeric <= 0
    if isinstance(value, bool):
        return False
    return _string(value) == ""


def agreement_missing_fields(data: dict[str, Any]) -> list[str]:
    missing = [
        field["path"]
        for field in _FORM_FIELDS
        if field["required"] and _is_blank_for_field(_lookup(data, field["path"], None), field)
    ]

    if _lookup(data, "payments.latePaymentInterestEnabled") is True:
        rate_field = next(field for field in _FORM_FIELDS if field["path"] == "payments.latePaymentInterestRate")
        if _is_blank_for_field(_lookup(data, "payments.latePaymentInterestRate"), rate_field):
            missing.append("payments.latePaymentInterestRate")

    if _lookup(data, "dispute.arbitrationEnabled") is True:
        for path in ("dispute.arbitrationVenue", "dispute.arbitratorCount", "dispute.appointingAuthority"):
            field = next(field for field in _FORM_FIELDS if field["path"] == path)
            if _is_blank_for_field(_lookup(data, path), field):
                missing.append(path)

    if _lookup(data, "tenancy.isCommercial") is True:
        field = next(field for field in _FORM_FIELDS if field["path"] == "commercial.businessDescription")
        if _is_blank_for_field(_lookup(data, "commercial.businessDescription"), field):
            missing.append("commercial.businessDescription")

    return missing


def _agreement_errors(data: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {path: "This field is required." for path in agreement_missing_fields(data)}

    for field in _FORM_FIELDS:
        path = field["path"]
        value = _lookup(data, path, None)
        if _is_blank_for_field(value, field):
            continue

        if field["type"] == "number":
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                errors.setdefault(path, "Enter a valid number.")
                continue
            if not math.isfinite(numeric):
                errors.setdefault(path, "Enter a valid number.")
            elif numeric < 0:
                errors.setdefault(path, "Enter a non-negative number.")
            elif path in POSITIVE_NUMBER_PATHS and numeric <= 0:
                errors.setdefault(path, "Enter a number greater than zero.")
            continue

        if field["type"] == "select":
            allowed = {option["value"] for option in field.get("options", [])}
            if _string(value) not in allowed:
                errors.setdefault(path, "Select a valid choice.")
            continue

        if field["type"] == "date":
            try:
                date.fromisoformat(_string(value))
            except ValueError:
                errors.setdefault(path, "Enter a valid date (YYYY-MM-DD).")
            continue

        if isinstance(value, str) and len(value.strip()) > MAX_TEXT_LENGTH:
            errors.setdefault(path, f"Ensure this value has at most {MAX_TEXT_LENGTH} characters.")

    return errors


_IF_BLOCK_RE = re.compile(r"\{\{#if\s+([A-Za-z_][\w.]*)\s*\}\}(.*?)\{\{/if\}\}", re.DOTALL)
_EACH_BLOCK_RE = re.compile(r"\{\{#each\s+([A-Za-z_][\w.]*)\s*\}\}(.*?)\{\{/each\}\}", re.DOTALL)
_VARIABLE_RE = re.compile(r"\{\{\s*([A-Za-z_][\w.@]*)\s*\}\}")
_THIS_VARIABLE_RE = re.compile(r"\{\{\s*this\.([\w.]+)\s*\}\}")
_INDEX_VARIABLE_RE = re.compile(r"\{\{\s*@indexPlusOne\s*\}\}")


def _load_template() -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    start = template.find(TEMPLATE_DOCUMENT_MARKER)
    if start == -1:
        raise ValueError("Tenancy agreement template is missing the document heading.")
    body = template[start:]
    notes_index = body.find(TEMPLATE_NOTES_MARKER)
    if notes_index != -1:
        body = body[:notes_index]
    return body.rstrip() + "\n"


def _sanitize_template_value(text: str) -> str:
    cleaned = strip_tags(text)
    cleaned = cleaned.replace("{{", "{ {").replace("}}", "} }")
    return cleaned.replace("](", "] (")


def _format_template_value(value: Any, path: str) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (int, float, Decimal)):
        numeric = float(value)
        if path.startswith(MONEY_PATH_PREFIX):
            return f"{numeric:,.2f}"
        return str(int(numeric)) if numeric.is_integer() else str(value)
    return _sanitize_template_value(str(value))


def _render_if_block(match: re.Match, data: dict) -> str:
    body = match.group(2)
    if "{{else}}" in body:
        truthy_branch, falsy_branch = body.split("{{else}}", 1)
    else:
        truthy_branch, falsy_branch = body, ""
    value = _lookup(data, match.group(1), None)
    return truthy_branch if value else falsy_branch


def _render_each_block(match: re.Match, data: dict) -> str:
    items = _lookup(data, match.group(1), None)
    if not isinstance(items, list):
        return ""
    body = match.group(2)
    rendered_items = []
    for index, item in enumerate(items):
        chunk = _INDEX_VARIABLE_RE.sub(str(index + 1), body)
        chunk = _THIS_VARIABLE_RE.sub(
            lambda item_match: _format_template_value(_lookup(item, item_match.group(1), None), f"this.{item_match.group(1)}"),
            chunk,
        )
        rendered_items.append(chunk)
    return "".join(rendered_items)


def render_tenancy_agreement(data: dict[str, Any]) -> str:
    text = _load_template()

    for _ in range(10):
        updated = _IF_BLOCK_RE.sub(lambda match: _render_if_block(match, data), text)
        updated = _EACH_BLOCK_RE.sub(lambda match: _render_each_block(match, data), updated)
        if updated == text:
            break
        text = updated

    def render_variable(match: re.Match) -> str:
        name = match.group(1)
        if name == "else" or name.startswith(("#", "/")):
            return match.group(0)
        return _format_template_value(_lookup(data, name, None), name)

    text = _VARIABLE_RE.sub(render_variable, text)
    if "{{" in text or "}}" in text:
        raise ValueError("Unresolved template placeholder in tenancy agreement.")
    return text


def generate_tenancy_agreement(*, booking: Booking, generated_by: AppUser, submitted_data: dict[str, Any]) -> TenancyAgreement:
    with transaction.atomic():
        locked_booking = Booking.objects.select_for_update().get(pk=booking.pk)
        latest = (
            TenancyAgreement.objects.filter(booking=locked_booking)
            .order_by("-version")
            .first()
        )
        record_id = uuid.uuid4()
        generated_at = timezone.now()
        data = build_agreement_draft(
            locked_booking,
            submitted_data or {},
            agreement_id=record_id,
            generated_at=generated_at,
        )

        errors = _agreement_errors(data)
        if errors:
            raise ValidationError({"errors": errors, "missing_fields": agreement_missing_fields(data)})

        rendered_content = render_tenancy_agreement(data)
        document_hash = hashlib.sha256(rendered_content.encode("utf-8")).hexdigest()
        data["agreement"]["documentHash"] = document_hash

        return TenancyAgreement.objects.create(
            id=record_id,
            booking=locked_booking,
            generated_by=generated_by,
            version=(latest.version + 1) if latest else 1,
            template_version=TEMPLATE_VERSION,
            status=TenancyAgreement.Status.REVIEW,
            agreement_data=data,
            rendered_content=rendered_content,
            document_hash=document_hash,
            generated_at=generated_at,
        )


TENANCY_AGREEMENT_SIGNATURE_DEFAULT_CAPACITIES = {
    "landlord": "Landlord",
    "tenant": "Tenant",
}


def signature_role_for_user(booking: Booking, user: AppUser | None) -> str | None:
    if user is None:
        return None
    role = getattr(user, "role", None)
    if role == AppUser.Role.TENANT and user.id == booking.tenant_id:
        return "tenant"
    if role == AppUser.Role.LANDLORD and user.id == booking.listing.landlord_id:
        return "landlord"
    return None


def signature_block_signed(signatures: Any, role: str) -> bool:
    if not isinstance(signatures, dict):
        return False
    block = signatures.get(role)
    return isinstance(block, dict) and bool(block.get("signatureId"))


def sign_tenancy_agreement(
    *,
    booking: Booking,
    signer: AppUser,
    signatory_name: str,
    signatory_capacity: str = "",
) -> TenancyAgreement:
    """Electronically sign the latest RentDirect tenancy agreement for a booking.

    Records the signature evidence in ``agreement_data.signatures``, re-renders
    the document so the signature block is populated, refreshes the document
    hash, marks the agreement final once both parties signed and completes the
    signer's ``tenancy_agreement_signed`` rental progress step.
    """
    name = (signatory_name or "").strip()
    if not name:
        raise ValidationError({"signatory_name": "Enter your legal name to sign the agreement."})
    if len(name) > 160:
        raise ValidationError({"signatory_name": "Enter a name of at most 160 characters."})
    capacity = (signatory_capacity or "").strip()[:160]

    with transaction.atomic():
        locked_booking = (
            Booking.objects.select_for_update()
            .select_related("tenant", "listing", "listing__landlord")
            .get(pk=booking.pk)
        )
        role = signature_role_for_user(locked_booking, signer)
        if role is None:
            raise PermissionDenied("Only the tenant or landlord on this booking can sign the agreement.")

        agreement = (
            TenancyAgreement.objects.select_for_update()
            .filter(booking=locked_booking)
            .order_by("-version")
            .first()
        )
        if agreement is None:
            raise ValidationError(
                "There is no RentDirect digital tenancy agreement for this booking. "
                "Confirm the tenancy agreement manually in the rental progress checklist."
            )

        data = copy.deepcopy(agreement.agreement_data or {})
        signatures = data.get("signatures")
        if not isinstance(signatures, dict):
            signatures = {}
            data["signatures"] = signatures
        if signature_block_signed(signatures, role):
            raise ValidationError("This agreement has already been signed for your role.")

        signed_at = timezone.now()
        signatures[role] = {
            "signedAtFormatted": signed_at.strftime("%d %B %Y, %H:%M UTC"),
            "signatureId": f"SIG-{uuid.uuid4().hex[:16].upper()}",
            "signatoryName": name,
            "signatoryCapacity": capacity or TENANCY_AGREEMENT_SIGNATURE_DEFAULT_CAPACITIES[role],
        }

        agreement_meta = data.get("agreement")
        if isinstance(agreement_meta, dict):
            agreement_meta["documentHash"] = DOCUMENT_HASH_PLACEHOLDER
        rendered_content = render_tenancy_agreement(data)
        document_hash = hashlib.sha256(rendered_content.encode("utf-8")).hexdigest()
        if isinstance(agreement_meta, dict):
            agreement_meta["documentHash"] = document_hash

        agreement.agreement_data = data
        agreement.rendered_content = rendered_content
        agreement.document_hash = document_hash
        update_fields = ["agreement_data", "rendered_content", "document_hash"]

        if (
            signature_block_signed(signatures, "landlord")
            and signature_block_signed(signatures, "tenant")
            and agreement.status != TenancyAgreement.Status.FINAL
        ):
            agreement.status = TenancyAgreement.Status.FINAL
            agreement.finalised_at = signed_at
            update_fields += ["status", "finalised_at"]
        agreement.save(update_fields=update_fields)

        complete_booking_progress_step(
            locked_booking,
            signer.role,
            "tenancy_agreement_signed",
            completed_at=signed_at.isoformat(),
        )
        sync_listing_status_from_rental_progress(locked_booking.listing)
        return agreement


def serialize_tenancy_agreement(record: TenancyAgreement | None) -> dict[str, Any] | None:
    if record is None:
        return None
    return {
        "id": str(record.id),
        "booking_id": str(record.booking_id),
        "version": record.version,
        "template_version": record.template_version,
        "status": record.status,
        "agreement_data": record.agreement_data,
        "rendered_content": record.rendered_content,
        "document_hash": record.document_hash,
        "generated_at": record.generated_at.isoformat() if record.generated_at else None,
        "finalised_at": record.finalised_at.isoformat() if record.finalised_at else None,
    }
