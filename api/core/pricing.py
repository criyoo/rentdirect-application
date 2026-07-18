from decimal import Decimal, ROUND_HALF_UP


MONEY_PRECISION = Decimal("0.01")
REFUNDABLE_SECURITY_DEPOSIT_RATE = Decimal("0.10")
ADMINISTRATION_FEE_RATE = Decimal("0.10")


def quantize_money(amount: Decimal | int | float | str) -> Decimal:
    return Decimal(amount).quantize(MONEY_PRECISION, rounding=ROUND_HALF_UP)


def calculate_refundable_security_deposit(annual_rent: Decimal | int | float | str) -> Decimal:
    return quantize_money(Decimal(annual_rent) * REFUNDABLE_SECURITY_DEPOSIT_RATE)


def calculate_administration_fee(annual_rent: Decimal | int | float | str) -> Decimal:
    return quantize_money(Decimal(annual_rent) * ADMINISTRATION_FEE_RATE)


def calculate_deposit_amount(annual_rent: Decimal | int | float | str) -> Decimal:
    annual_rent_decimal = Decimal(annual_rent)
    return quantize_money(
        calculate_refundable_security_deposit(annual_rent_decimal)
        + calculate_administration_fee(annual_rent_decimal)
    )


def calculate_booking_total(annual_rent: Decimal | int | float | str) -> Decimal:
    annual_rent_decimal = quantize_money(annual_rent)
    return quantize_money(annual_rent_decimal + calculate_deposit_amount(annual_rent_decimal))


def resolve_booking_total(
    annual_rent: Decimal | int | float | str,
    stored_total_amount: Decimal | int | float | str | None,
) -> Decimal:
    calculated_total = calculate_booking_total(annual_rent)
    stored_total = Decimal(stored_total_amount or 0)
    return calculated_total if stored_total < calculated_total else quantize_money(stored_total)


def calculate_remaining_balance(
    total_amount: Decimal | int | float | str | None,
    paid_amount: Decimal | int | float | str | None,
) -> Decimal:
    total = Decimal(total_amount or 0)
    paid = Decimal(paid_amount or 0)
    return quantize_money(max(total - paid, Decimal("0")))
