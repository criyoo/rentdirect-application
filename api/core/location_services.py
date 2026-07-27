from __future__ import annotations

import math
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable


@dataclass(frozen=True)
class CoordinateResult:
    latitude: float
    longitude: float
    source: str


def _normalise_location(value: str | None) -> str:
    normalized = re.sub(r"[^a-z0-9\s]", " ", str(value or "").lower())
    normalized = re.sub(r"\b(state|province|territory|lga|local government area)\b", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


STATE_ALIASES = {
    "abuja": "fct",
    "federal capital": "fct",
    "federal capital territory": "fct",
}


def _normalise_state(value: str | None) -> str:
    normalized = _normalise_location(value)
    if "fct" in normalized.split():
        return "fct"
    return STATE_ALIASES.get(normalized, normalized)


STATE_COORDINATES: dict[str, tuple[float, float]] = {
    "abia": (5.5320, 7.4860),
    "adamawa": (9.3265, 12.3984),
    "akwa ibom": (5.0377, 7.9128),
    "anambra": (6.2209, 6.9360),
    "bauchi": (10.3158, 9.8442),
    "bayelsa": (4.8678, 5.8987),
    "benue": (7.3369, 8.7404),
    "borno": (11.8846, 13.1520),
    "cross river": (5.8702, 8.5988),
    "delta": (5.7040, 5.9339),
    "ebonyi": (6.2649, 8.0137),
    "edo": (6.5438, 5.8987),
    "ekiti": (7.7190, 5.3110),
    "enugu": (6.5244, 7.5183),
    "fct": (9.0765, 7.3986),
    "gombe": (10.2904, 11.1714),
    "imo": (5.5720, 7.0588),
    "jigawa": (12.2280, 9.5616),
    "kaduna": (10.5105, 7.4165),
    "kano": (12.0022, 8.5920),
    "katsina": (12.9855, 7.6171),
    "kebbi": (12.4539, 4.1975),
    "kogi": (7.7337, 6.6906),
    "kwara": (8.9669, 4.3874),
    "lagos": (6.5244, 3.3792),
    "nasarawa": (8.4998, 8.1997),
    "niger": (9.9309, 5.5983),
    "ogun": (7.1608, 3.3480),
    "ondo": (7.2508, 5.2103),
    "osun": (7.5629, 4.5200),
    "oyo": (7.3775, 3.9470),
    "plateau": (9.2182, 9.5179),
    "rivers": (4.8156, 7.0498),
    "sokoto": (13.0059, 5.2476),
    "taraba": (8.8929, 11.3771),
    "yobe": (11.7480, 11.9608),
    "zamfara": (12.1704, 6.6641),
}


CITY_COORDINATES: dict[tuple[str, str], tuple[float, float]] = {
    ("aba", "abia"): (5.1216, 7.3733),
    ("umuahia", "abia"): (5.5320, 7.4860),
    ("yola", "adamawa"): (9.2035, 12.4954),
    ("uyo", "akwa ibom"): (5.0389, 7.9095),
    ("awka", "anambra"): (6.2100, 7.0741),
    ("onitsha", "anambra"): (6.1667, 6.7833),
    ("bauchi", "bauchi"): (10.3158, 9.8442),
    ("yenagoa", "bayelsa"): (4.9247, 6.2642),
    ("makurdi", "benue"): (7.7322, 8.5391),
    ("maiduguri", "borno"): (11.8311, 13.1510),
    ("calabar", "cross river"): (4.9757, 8.3417),
    ("asaba", "delta"): (6.2049, 6.6959),
    ("warri", "delta"): (5.5167, 5.7500),
    ("abakaliki", "ebonyi"): (6.3249, 8.1137),
    ("benin", "edo"): (6.3350, 5.6037),
    ("benin city", "edo"): (6.3350, 5.6037),
    ("ado ekiti", "ekiti"): (7.6210, 5.2215),
    ("enugu", "enugu"): (6.5244, 7.5183),
    ("abuja", "fct"): (9.0765, 7.3986),
    ("asokoro", "fct"): (9.0477, 7.5246),
    ("garki", "fct"): (9.0266, 7.4898),
    ("gwarinpa", "fct"): (9.1091, 7.4043),
    ("jabi", "fct"): (9.0663, 7.4326),
    ("kubwa", "fct"): (9.1538, 7.3220),
    ("lugbe", "fct"): (8.9837, 7.3546),
    ("maitama", "fct"): (9.0944, 7.4951),
    ("wuse", "fct"): (9.0766, 7.4637),
    ("gombe", "gombe"): (10.2897, 11.1673),
    ("owerri", "imo"): (5.4850, 7.0351),
    ("dutse", "jigawa"): (11.7562, 9.3389),
    ("kaduna", "kaduna"): (10.5105, 7.4165),
    ("zaria", "kaduna"): (11.1113, 7.7227),
    ("kano", "kano"): (12.0022, 8.5920),
    ("katsina", "katsina"): (12.9855, 7.6171),
    ("birnin kebbi", "kebbi"): (12.4539, 4.1975),
    ("lokoja", "kogi"): (7.8023, 6.7333),
    ("ilorin", "kwara"): (8.4799, 4.5418),
    ("ajah", "lagos"): (6.4698, 3.5852),
    ("badagry", "lagos"): (6.4150, 2.8813),
    ("epe", "lagos"): (6.5841, 3.9834),
    ("ikeja", "lagos"): (6.6018, 3.3515),
    ("ikoyi", "lagos"): (6.4541, 3.4351),
    ("lagos", "lagos"): (6.5244, 3.3792),
    ("lekki", "lagos"): (6.4698, 3.5852),
    ("surulere", "lagos"): (6.5013, 3.3580),
    ("victoria island", "lagos"): (6.4281, 3.4219),
    ("vi", "lagos"): (6.4281, 3.4219),
    ("yaba", "lagos"): (6.5158, 3.3898),
    ("lafia", "nasarawa"): (8.4920, 8.5153),
    ("minna", "niger"): (9.6139, 6.5569),
    ("abeokuta", "ogun"): (7.1475, 3.3619),
    ("akure", "ondo"): (7.2571, 5.2058),
    ("osogbo", "osun"): (7.7827, 4.5418),
    ("ibadan", "oyo"): (7.3775, 3.9470),
    ("jos", "plateau"): (9.8965, 8.8583),
    ("port harcourt", "rivers"): (4.8156, 7.0498),
    ("sokoto", "sokoto"): (13.0059, 5.2476),
    ("jalingo", "taraba"): (8.8937, 11.3596),
    ("damaturu", "yobe"): (11.7460, 11.9668),
    ("gusau", "zamfara"): (12.1704, 6.6641),
}


AMENITY_POINTS: tuple[dict[str, str | float], ...] = (
    {"category": "schools", "name": "University of Lagos", "city": "Yaba", "state": "Lagos", "latitude": 6.5158, "longitude": 3.3898},
    {"category": "schools", "name": "Lagos Business School", "city": "Lekki", "state": "Lagos", "latitude": 6.4667, "longitude": 3.5865},
    {"category": "schools", "name": "American International School Lagos", "city": "Victoria Island", "state": "Lagos", "latitude": 6.4264, "longitude": 3.4225},
    {"category": "schools", "name": "University of Abuja", "city": "Abuja", "state": "FCT", "latitude": 8.9820, "longitude": 7.1790},
    {"category": "schools", "name": "Nile University of Nigeria", "city": "Abuja", "state": "FCT", "latitude": 9.0192, "longitude": 7.3975},
    {"category": "schools", "name": "University of Ibadan", "city": "Ibadan", "state": "Oyo", "latitude": 7.4452, "longitude": 3.8964},
    {"category": "hospitals", "name": "Lagos University Teaching Hospital", "city": "Idi-Araba", "state": "Lagos", "latitude": 6.5161, "longitude": 3.3606},
    {"category": "hospitals", "name": "Reddington Hospital", "city": "Victoria Island", "state": "Lagos", "latitude": 6.4319, "longitude": 3.4215},
    {"category": "hospitals", "name": "Evercare Hospital Lekki", "city": "Lekki", "state": "Lagos", "latitude": 6.4480, "longitude": 3.5075},
    {"category": "hospitals", "name": "National Hospital Abuja", "city": "Abuja", "state": "FCT", "latitude": 9.0387, "longitude": 7.4698},
    {"category": "hospitals", "name": "University College Hospital", "city": "Ibadan", "state": "Oyo", "latitude": 7.4030, "longitude": 3.9020},
    {"category": "transport_hubs", "name": "Murtala Muhammed Airport", "city": "Ikeja", "state": "Lagos", "latitude": 6.5774, "longitude": 3.3212},
    {"category": "transport_hubs", "name": "Ikeja Bus Terminal", "city": "Ikeja", "state": "Lagos", "latitude": 6.6059, "longitude": 3.3479},
    {"category": "transport_hubs", "name": "Berger Bus Stop", "city": "Lagos", "state": "Lagos", "latitude": 6.6426, "longitude": 3.3792},
    {"category": "transport_hubs", "name": "Nnamdi Azikiwe International Airport", "city": "Abuja", "state": "FCT", "latitude": 9.0068, "longitude": 7.2632},
    {"category": "transport_hubs", "name": "Jabi Motor Park", "city": "Abuja", "state": "FCT", "latitude": 9.0661, "longitude": 7.4183},
    {"category": "supermarkets", "name": "The Palms Shopping Mall", "city": "Lekki", "state": "Lagos", "latitude": 6.4350, "longitude": 3.4669},
    {"category": "supermarkets", "name": "Novare Lekki Mall", "city": "Lekki", "state": "Lagos", "latitude": 6.4655, "longitude": 3.6020},
    {"category": "supermarkets", "name": "Jabi Lake Mall", "city": "Abuja", "state": "FCT", "latitude": 9.0776, "longitude": 7.4286},
    {"category": "supermarkets", "name": "Grand Square Abuja", "city": "Abuja", "state": "FCT", "latitude": 9.0614, "longitude": 7.4924},
    {"category": "supermarkets", "name": "Dugbe Market", "city": "Ibadan", "state": "Oyo", "latitude": 7.3878, "longitude": 3.8794},
    {"category": "other", "name": "Lekki Conservation Centre", "city": "Lekki", "state": "Lagos", "latitude": 6.4410, "longitude": 3.5356},
    {"category": "other", "name": "Tafawa Balewa Square", "city": "Lagos Island", "state": "Lagos", "latitude": 6.4434, "longitude": 3.4010},
    {"category": "other", "name": "Millennium Park", "city": "Abuja", "state": "FCT", "latitude": 9.0820, "longitude": 7.4914},
    {"category": "other", "name": "Agodi Gardens", "city": "Ibadan", "state": "Oyo", "latitude": 7.4249, "longitude": 3.9060},
)


AMENITY_CATEGORIES = ("schools", "hospitals", "transport_hubs", "supermarkets", "other")


def decimal_from_float(value: float) -> Decimal:
    return Decimal(str(round(value, 6)))


def resolve_city_state_coordinates(city: str | None, state: str | None) -> CoordinateResult | None:
    city_key = _normalise_location(city)
    state_key = _normalise_state(state)

    if city_key and state_key:
        coords = CITY_COORDINATES.get((city_key, state_key))
        if coords:
            return CoordinateResult(coords[0], coords[1], "city_state")

    if city_key:
        city_matches = {coords for (known_city, _known_state), coords in CITY_COORDINATES.items() if known_city == city_key}
        if len(city_matches) == 1:
            latitude, longitude = next(iter(city_matches))
            return CoordinateResult(latitude, longitude, "city")

    if state_key:
        coords = STATE_COORDINATES.get(state_key)
        if coords:
            return CoordinateResult(coords[0], coords[1], "state")

    city_as_state = _normalise_state(city)
    coords = STATE_COORDINATES.get(city_as_state)
    if coords:
        return CoordinateResult(coords[0], coords[1], "state")

    return None


def coordinates_for_listing(listing) -> CoordinateResult | None:
    if getattr(listing, "latitude", None) is not None and getattr(listing, "longitude", None) is not None:
        return CoordinateResult(float(listing.latitude), float(listing.longitude), "listing_coordinates")
    return resolve_city_state_coordinates(getattr(listing, "city", ""), getattr(listing, "state", ""))


def haversine_distance_km(latitude: float, longitude: float, target_latitude: float, target_longitude: float) -> float:
    earth_radius_km = 6371.0088
    lat1 = math.radians(latitude)
    lat2 = math.radians(target_latitude)
    delta_lat = math.radians(target_latitude - latitude)
    delta_lon = math.radians(target_longitude - longitude)

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return earth_radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def attach_distance_to_listing(listing, latitude: float, longitude: float) -> tuple[object, float] | None:
    coordinates = coordinates_for_listing(listing)
    if coordinates is None:
        return None
    distance_km = haversine_distance_km(latitude, longitude, coordinates.latitude, coordinates.longitude)
    listing._distance_km = round(distance_km, 2)
    listing._location_source = coordinates.source
    return listing, distance_km


def listing_neighbourhood(listing) -> str:
    city = str(getattr(listing, "city", "") or "").strip()
    if city:
        return city

    address = str(getattr(listing, "address", "") or "").strip()
    if not address:
        return "Not specified"

    first_part = address.split(",")[0].strip()
    first_part = re.sub(r"^\d+[a-z]?\s+", "", first_part, flags=re.IGNORECASE).strip()
    return first_part or "Not specified"


def nearest_amenities_for_coordinates(
    latitude: float,
    longitude: float,
    *,
    limit_per_category: int = 3,
    max_distance_km: float = 25,
    categories: Iterable[str] = AMENITY_CATEGORIES,
) -> dict[str, list[dict[str, str | float]]]:
    selected_categories = tuple(categories)
    grouped: dict[str, list[dict[str, str | float]]] = {category: [] for category in selected_categories}

    for point in AMENITY_POINTS:
        category = str(point["category"])
        if category not in grouped:
            continue
        distance_km = haversine_distance_km(
            latitude,
            longitude,
            float(point["latitude"]),
            float(point["longitude"]),
        )
        if distance_km > max_distance_km:
            continue
        grouped[category].append(
            {
                "name": str(point["name"]),
                "category": category,
                "city": str(point["city"]),
                "state": str(point["state"]),
                "latitude": float(point["latitude"]),
                "longitude": float(point["longitude"]),
                "distance_km": round(distance_km, 2),
            }
        )

    for category in selected_categories:
        grouped[category] = sorted(grouped[category], key=lambda item: float(item["distance_km"]))[:limit_per_category]

    return grouped
