from decimal import Decimal, ROUND_HALF_UP

from .financial_constants import (
    ADMINISTRATION_FEE_RATE,
    ADMINISTRATION_FEE_VAT_RATE,
    FEATURED_PROPERTY_MONTHLY_DURATION_DAYS,
    FEATURED_PROPERTY_MONTHLY_FEE,
    LISTING_DEPOSIT_RATE,
    MONEY_PRECISION,
    REFUNDABLE_SECURITY_DEPOSIT_RATE,
    ZERO_AMOUNT,
)


def quantize_money(amount: Decimal | int | float | str) -> Decimal:
    return Decimal(amount).quantize(MONEY_PRECISION, rounding=ROUND_HALF_UP)


def calculate_refundable_security_deposit(annual_rent: Decimal | int | float | str) -> Decimal:
    return quantize_money(Decimal(annual_rent) * REFUNDABLE_SECURITY_DEPOSIT_RATE)


def calculate_administration_fee(annual_rent: Decimal | int | float | str) -> Decimal:
    return quantize_money(Decimal(annual_rent) * ADMINISTRATION_FEE_RATE)


def calculate_administration_fee_vat(annual_rent: Decimal | int | float | str) -> Decimal:
    return quantize_money(calculate_administration_fee(annual_rent) * ADMINISTRATION_FEE_VAT_RATE)


def calculate_deposit_amount(annual_rent: Decimal | int | float | str) -> Decimal:
    annual_rent_decimal = Decimal(annual_rent)
    return quantize_money(
        calculate_refundable_security_deposit(annual_rent_decimal)
        + calculate_administration_fee(annual_rent_decimal)
        + calculate_administration_fee_vat(annual_rent_decimal)
    )


def calculate_listing_deposit_amount(annual_rent: Decimal | int | float | str) -> Decimal:
    return quantize_money(Decimal(annual_rent) * LISTING_DEPOSIT_RATE)


def calculate_featured_property_fee(days: int) -> Decimal:
    return quantize_money(
        (FEATURED_PROPERTY_MONTHLY_FEE / Decimal(FEATURED_PROPERTY_MONTHLY_DURATION_DAYS)) * Decimal(days)
    )


def calculate_booking_total(annual_rent: Decimal | int | float | str) -> Decimal:
    annual_rent_decimal = quantize_money(annual_rent)
    return quantize_money(annual_rent_decimal + calculate_deposit_amount(annual_rent_decimal))


def resolve_booking_total(
    annual_rent: Decimal | int | float | str,
    stored_total_amount: Decimal | int | float | str | None,
) -> Decimal:
    calculated_total = calculate_booking_total(annual_rent)
    stored_total = Decimal(stored_total_amount or ZERO_AMOUNT)
    return calculated_total if stored_total < calculated_total else quantize_money(stored_total)


def calculate_remaining_balance(
    total_amount: Decimal | int | float | str | None,
    paid_amount: Decimal | int | float | str | None,
) -> Decimal:
    total = Decimal(total_amount or ZERO_AMOUNT)
    paid = Decimal(paid_amount or ZERO_AMOUNT)
    return quantize_money(max(total - paid, ZERO_AMOUNT))
