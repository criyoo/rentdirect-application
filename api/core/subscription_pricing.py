from copy import deepcopy
from typing import Any

from .financial_constants import SUBSCRIPTION_PRICING


def get_subscription_pricing() -> dict[str, Any]:
    return {role: deepcopy(plan_pricing) for role, plan_pricing in SUBSCRIPTION_PRICING.items()}
