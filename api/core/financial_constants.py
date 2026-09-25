from decimal import Decimal


MONEY_PRECISION = Decimal("0.01")
ZERO_AMOUNT = Decimal("0.00")
PERCENT_DENOMINATOR = Decimal("100")
MONEY_MINOR_UNIT_FACTOR = Decimal("100")
MONTHS_PER_YEAR = Decimal("12")

REFUNDABLE_SECURITY_DEPOSIT_RATE = Decimal("0.05")
CAUTION_FEE_RATE = Decimal("0.05")
LEGAL_FEE_MAX_RATE = Decimal("0.05")
ADMINISTRATION_FEE_RATE = Decimal("0.15")
ADMINISTRATION_FEE_VAT_RATE = Decimal("0.075")
LISTING_DEPOSIT_RATE = Decimal("0.30")
LISTING_TOTAL_MULTIPLIER = Decimal("1.20")
DEPOSIT_LISTING_HOLD_DAYS = 3
PAYMENT_CANCELLATION_ADMIN_FEE_RATE = Decimal("0.01")
CARD_PAYMENT_LIMIT_NGN = Decimal("7000000.00")
ACCOUNT_FREEZE_FEE_PERCENTAGE = Decimal("10.00")
DEFAULT_SUBSCRIPTION_VAT_RATE_PERCENT = Decimal("7.50")

FEATURED_PROPERTY_MONTHLY_FEE = Decimal("500.00")
FEATURED_PROPERTY_MONTHLY_DURATION_DAYS = 30
FEATURED_PROPERTY_MIN_DURATION_DAYS = 1
FEATURED_PROPERTY_MAX_DURATION_DAYS = 90

TENANT_MONTHLY_INCOME_TOP_BAND = Decimal("2000000")
TENANT_MONTHLY_INCOME_HIGH_BAND = Decimal("1200000")
TENANT_MONTHLY_INCOME_MID_BAND = Decimal("750000")
TENANT_MONTHLY_INCOME_STANDARD_BAND = Decimal("400000")

TENANT_SUBSCRIPTION_PLAN_PRICING = {
    "bronze": {"monthly": ZERO_AMOUNT, "yearly": ZERO_AMOUNT},
    "silver": {"monthly": Decimal("500.00"), "yearly": Decimal("5000.00")},
    "gold": {"monthly": Decimal("700.00"), "yearly": Decimal("7000.00")},
    "platinum": {"monthly": Decimal("1000.00"), "yearly": Decimal("10000.00")},
}

LANDLORD_SUBSCRIPTION_PLAN_PRICING = {
    "bronze": {"monthly": ZERO_AMOUNT, "yearly": ZERO_AMOUNT},
    "silver": {"monthly": Decimal("600.00"), "yearly": Decimal("6000.00")},
    "gold": {"monthly": Decimal("800.00"), "yearly": Decimal("8000.00")},
    "platinum": {"monthly": Decimal("1000.00"), "yearly": Decimal("10000.00")},
}

SUBSCRIPTION_PRICING = {
    "tenant": TENANT_SUBSCRIPTION_PLAN_PRICING,
    "landlord": LANDLORD_SUBSCRIPTION_PLAN_PRICING,
}
