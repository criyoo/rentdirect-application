import json
from functools import lru_cache
from pathlib import Path
from typing import Any


SUBSCRIPTION_PRICING_PATH = Path(__file__).with_name("subscription-pricing.json")


@lru_cache(maxsize=1)
def get_subscription_pricing() -> dict[str, Any]:
    with SUBSCRIPTION_PRICING_PATH.open("r", encoding="utf-8") as pricing_file:
        return json.load(pricing_file)
