import re


NIGERIAN_STATES = [
    "Abia",
    "Adamawa",
    "Akwa Ibom",
    "Anambra",
    "Bauchi",
    "Bayelsa",
    "Benue",
    "Borno",
    "Cross River",
    "Delta",
    "Ebonyi",
    "Edo",
    "Ekiti",
    "Enugu",
    "Gombe",
    "Imo",
    "Jigawa",
    "Kaduna",
    "Kano",
    "Katsina",
    "Kebbi",
    "Kogi",
    "Kwara",
    "Lagos",
    "Nasarawa",
    "Niger",
    "Ogun",
    "Ondo",
    "Osun",
    "Oyo",
    "Plateau",
    "Rivers",
    "Sokoto",
    "Taraba",
    "Yobe",
    "Zamfara",
    "Federal Capital Territory",
]

STATE_OF_ORIGIN_OPTIONS = [*NIGERIAN_STATES, "Others"]
STATE_OF_ORIGIN_MAP = {option.casefold(): option for option in STATE_OF_ORIGIN_OPTIONS}
RESIDENCE_KEYS = ["state", "city", "address", "origin_country", "origin_state", "origin_city"]

LOCAL_MOBILE_RE = re.compile(r"^0[789]\d{9}$")
INTL_MOBILE_RE = re.compile(r"^\+234(70|71|80|81|90|91)\d{7}$")
NIN_RE = re.compile(r"^\d{11}$")


def is_valid_mobile(value: str) -> bool:
    return bool(LOCAL_MOBILE_RE.fullmatch(value) or INTL_MOBILE_RE.fullmatch(value))


def is_valid_nin(value: str) -> bool:
    return bool(NIN_RE.fullmatch(value))


def normalize_state_of_origin(value: str | None) -> str:
    normalized = (value or "").strip()
    if not normalized:
        return ""

    match = STATE_OF_ORIGIN_MAP.get(normalized.casefold())
    if not match:
        raise ValueError("Choose a valid Nigerian state or Others.")
    return match


def normalize_residence(state_of_origin: str, residence) -> dict | None:
    if residence in ("", None):
        residence = {}
    if not isinstance(residence, dict):
        raise ValueError("Residence must be an object.")

    normalized = {key: str(residence.get(key, "")).strip() for key in RESIDENCE_KEYS}

    # Keep the old origin_city key working while supporting origin_state going forward.
    if not normalized["origin_state"] and normalized["origin_city"]:
        normalized["origin_state"] = normalized["origin_city"]
    if not normalized["origin_city"] and normalized["origin_state"]:
        normalized["origin_city"] = normalized["origin_state"]

    residency_fields = [normalized["state"], normalized["city"], normalized["address"]]
    if any(residency_fields) and not all(residency_fields):
        raise ValueError("Residence state, city, and address must all be provided together.")

    if state_of_origin == "Others":
        if not normalized["origin_country"] or not normalized["origin_state"]:
            raise ValueError("Country and state are required when state of origin is Others.")
    else:
        normalized["origin_country"] = ""
        normalized["origin_state"] = ""
        normalized["origin_city"] = ""

    return normalized if any(normalized.values()) else None
