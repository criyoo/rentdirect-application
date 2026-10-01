"""Match available listings against a tenant's saved property search requirement.

Each criterion the tenant actually provided contributes weighted points; the
final match score is achieved / possible * 100 so partially-filled requirements
score fairly. Used by the tenant dashboard matches endpoint and by Sally's
match_search_requirement tool.
"""

from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from .models import Listing

TOP_MATCH_LIMIT = 3

# (requirement field, listing field, human label) — checked flags mean "must have".
BOOLEAN_REQUIREMENT_FIELDS = (
    ("pet_friendly", "pet_friendly", "Pet friendly"),
    ("furnished", "furnished", "Furnished"),
    ("utilities_included", "utilities_included", "Utilities included"),
    ("parking", "parking", "Parking"),
    ("garage", "garage", "Garage"),
    ("garden", "garden", "Garden"),
    ("lift", "lift", "Lift"),
    ("balcony", "balcony", "Balcony"),
    ("fitted_kitchen", "fitted_kitchen", "Fitted kitchen"),
    ("air_conditioning", "air_conditioning", "Air conditioning"),
    ("internet", "internet", "Internet"),
    ("boys_quarters", "boys_quarters", "Boys quarters"),
    ("prepaid_meter", "prepaid_meter", "Prepaid meter"),
    ("gated_estate", "gated_estate", "Gated estate"),
    ("security_guard", "security_guard", "Security guard"),
    ("cctv", "cctv", "CCTV"),
    ("wheelchair_accessible", "wheelchair_accessible", "Wheelchair accessible"),
    ("smoking_allowed", "smoking_allowed", "Smoking allowed"),
    ("short_let_allowed", "short_let_allowed", "Short-let allowed"),
    ("student_tenants_allowed", "student_tenants_allowed", "Students allowed"),
    ("expatriates_allowed", "expatriates_allowed", "Expatriates allowed"),
    ("commercial_activities_allowed", "commercial_activities_allowed", "Commercial use allowed"),
    ("negotiable", "negotiable", "Negotiable rent"),
)

_FCT_TERMS = {"fct", "abuja", "federal capital territory"}


def _norm(value) -> str:
    return str(value or "").strip().lower()


def _location_term_matches(requirement_value: str, *listing_values) -> bool:
    term = _norm(requirement_value)
    if not term:
        return False
    candidates = {_norm(value) for value in listing_values if value}
    if term in candidates:
        return True
    return any(term in candidate or candidate in term for candidate in candidates)


def public_listings_queryset():
    return (
        Listing.objects.select_related("landlord")
        .prefetch_related("images", "bookings")
        .filter(status=Listing.Status.AVAILABLE, is_hidden=False)
    )


def _location_filter_q(requirement) -> Q | None:
    """Hard location filter: every location field the tenant set must match."""
    condition = Q()
    has_location = False

    state = _norm(requirement.preferred_state)
    if state:
        terms = {requirement.preferred_state}
        if state in _FCT_TERMS:
            terms |= _FCT_TERMS
        state_q = Q()
        for term in terms:
            state_q |= Q(state__icontains=term) | Q(address__icontains=term)
        condition &= state_q
        has_location = True

    city = _norm(requirement.preferred_city)
    if city:
        condition &= (
            Q(city__icontains=city)
            | Q(area__icontains=city)
            | Q(address__icontains=city)
        )
        has_location = True

    lga = _norm(requirement.preferred_lga)
    if lga:
        condition &= Q(lga__icontains=lga) | Q(address__icontains=lga) | Q(city__icontains=lga)
        has_location = True

    areas = [a.strip() for a in str(requirement.preferred_areas or "").split(",") if a.strip()]
    if areas:
        areas_q = Q()
        for area in areas:
            areas_q |= (
                Q(area__icontains=area)
                | Q(nearest_landmark__icontains=area)
                | Q(address__icontains=area)
                | Q(city__icontains=area)
            )
        condition &= areas_q
        has_location = True

    return condition if has_location else None


def _strict_requirement_q(requirement) -> Q:
    """Exact-match filter over the tenant's non-location criteria — used to count
    listings outside the saved location that still satisfy the requirement."""
    condition = Q()
    if requirement.min_budget is not None:
        condition &= Q(price_per_year__gte=requirement.min_budget)
    if requirement.max_budget is not None:
        condition &= Q(price_per_year__lte=requirement.max_budget)
    if requirement.max_nightly_budget is not None:
        condition &= Q(short_let_allowed=True) & Q(nightly_rate__lte=requirement.max_nightly_budget)
    if _norm(requirement.property_type):
        condition &= (
            Q(property_type__iexact=requirement.property_type)
            | Q(property_type__icontains=requirement.property_type)
        )
    if requirement.min_bedrooms is not None:
        condition &= Q(bedrooms__gte=requirement.min_bedrooms)
    if requirement.max_bedrooms is not None:
        condition &= Q(bedrooms__lte=requirement.max_bedrooms)
    if requirement.min_bathrooms is not None:
        condition &= Q(bathrooms__gte=requirement.min_bathrooms)
    if requirement.min_toilets is not None:
        condition &= Q(toilets__gte=requirement.min_toilets)
    for field in ("furnishing_level", "power_supply", "water_supply"):
        value = _norm(getattr(requirement, field))
        if value:
            condition &= Q(**{field: value})
    for field, listing_field, _label in BOOLEAN_REQUIREMENT_FIELDS:
        if getattr(requirement, field):
            condition &= Q(**{listing_field: True})
    for amenity in (requirement.preferred_amenities or []):
        term = str(amenity).strip()
        if term:
            condition &= (
                Q(amenities__icontains=term)
                | Q(description__icontains=term)
                | Q(title__icontains=term)
            )
    if requirement.move_in_date is not None:
        condition &= Q(available_from__isnull=True) | Q(available_from__lte=requirement.move_in_date)
    if requirement.occupants is not None:
        condition &= Q(maximum_occupancy__gte=requirement.occupants)
    return condition


def requirement_has_criteria(requirement) -> bool:
    if not requirement:
        return False
    if any(
        _norm(getattr(requirement, field))
        for field in ("preferred_state", "preferred_city", "preferred_lga", "preferred_areas",
                      "property_type", "furnishing_level", "power_supply", "water_supply", "notes")
    ):
        return True
    if any(
        getattr(requirement, field) is not None
        for field in ("min_budget", "max_budget", "max_nightly_budget", "min_bedrooms",
                      "max_bedrooms", "min_bathrooms", "min_toilets", "move_in_date", "occupants")
    ):
        return True
    if requirement.preferred_amenities:
        return True
    return any(getattr(requirement, field) for field, _listing_field, _label in BOOLEAN_REQUIREMENT_FIELDS)


def score_listing_for_requirement(requirement, listing) -> tuple[float, list[str]]:
    """Return (score 0-100, human-readable match reasons)."""
    possible = 0.0
    achieved = 0.0
    reasons: list[str] = []

    def score(points: float, earned: float, reason: str | None = None):
        nonlocal possible, achieved
        possible += points
        achieved += earned
        if reason and earned > 0:
            reasons.append(reason)

    # --- Location ---
    if _norm(requirement.preferred_state):
        terms = {requirement.preferred_state}
        if _norm(requirement.preferred_state) in _FCT_TERMS:
            terms |= _FCT_TERMS
        hit = any(_location_term_matches(t, listing.state, listing.address) for t in terms)
        score(10, 10 if hit else 0, f"Located in {listing.state}" if hit else None)
    if _norm(requirement.preferred_city):
        hit = _location_term_matches(requirement.preferred_city, listing.city, listing.address, listing.area)
        score(15, 15 if hit else 0, f"City matches {listing.city}" if hit else None)
    if _norm(requirement.preferred_lga):
        hit = _location_term_matches(requirement.preferred_lga, listing.lga, listing.city, listing.address)
        score(5, 5 if hit else 0, f"LGA matches {listing.lga}" if hit else None)
    areas = [a.strip() for a in str(requirement.preferred_areas or "").split(",") if a.strip()]
    if areas:
        hit = any(
            _location_term_matches(area, listing.area, listing.nearest_landmark, listing.address, listing.city)
            for area in areas
        )
        score(8, 8 if hit else 0, f"Preferred area ({listing.area or listing.city})" if hit else None)

    # --- Budget ---
    price = Decimal(listing.price_per_year or 0)
    if requirement.min_budget is not None:
        hit = price >= requirement.min_budget
        score(4, 4 if hit else 0)
    if requirement.max_budget is not None:
        if price <= requirement.max_budget:
            score(15, 15, f"Within budget at {price:,.0f}/year")
        elif requirement.negotiable and listing.negotiable and price <= requirement.max_budget * Decimal("1.15"):
            score(15, 7.5, "Slightly above budget but negotiable")
        else:
            score(15, 0)
    if requirement.max_nightly_budget is not None:
        nightly = listing.nightly_rate
        hit = bool(listing.short_let_allowed) and nightly is not None and nightly <= requirement.max_nightly_budget
        score(8, 8 if hit else 0, f"Short-let nightly rate {nightly:,.0f}" if hit else None)

    # --- Specification ---
    if _norm(requirement.property_type):
        hit = _location_term_matches(requirement.property_type, listing.property_type)
        score(10, 10 if hit else 0, f"{listing.property_type} property type" if hit else None)
    if requirement.min_bedrooms is not None or requirement.max_bedrooms is not None:
        bedrooms = listing.bedrooms or 0
        low = requirement.min_bedrooms or 0
        high = requirement.max_bedrooms if requirement.max_bedrooms is not None else bedrooms
        hit = low <= bedrooms <= high
        score(12, 12 if hit else 0, f"{bedrooms} bedrooms" if hit else None)
    if requirement.min_bathrooms is not None:
        hit = (listing.bathrooms or 0) >= requirement.min_bathrooms
        score(6, 6 if hit else 0, f"{listing.bathrooms} bathrooms" if hit else None)
    if requirement.min_toilets is not None:
        hit = (listing.toilets or 0) >= requirement.min_toilets
        score(4, 4 if hit else 0, f"{listing.toilets} toilets" if hit else None)
    if _norm(requirement.furnishing_level):
        hit = _norm(listing.furnishing_level) == _norm(requirement.furnishing_level)
        score(5, 5 if hit else 0, f"{listing.furnishing_level.replace('_', ' ')}" if hit else None)
    if _norm(requirement.power_supply):
        hit = _norm(listing.power_supply) == _norm(requirement.power_supply)
        score(5, 5 if hit else 0, "Matching power supply" if hit else None)
    if _norm(requirement.water_supply):
        hit = _norm(listing.water_supply) == _norm(requirement.water_supply)
        score(5, 5 if hit else 0, "Matching water supply" if hit else None)

    # --- Required features ---
    checked = [(f, lf, label) for f, lf, label in BOOLEAN_REQUIREMENT_FIELDS if getattr(requirement, f)]
    if checked:
        per_flag = 24.0 / len(checked)
        matched_labels = []
        for _field, listing_field, label in checked:
            if getattr(listing, listing_field):
                achieved += per_flag
                matched_labels.append(label)
        possible += 24
        if matched_labels:
            reasons.append("Has " + ", ".join(matched_labels[:6]) + ("…" if len(matched_labels) > 6 else ""))

    # --- Preferred amenities ---
    amenities = [str(a).strip().lower() for a in (requirement.preferred_amenities or []) if str(a).strip()]
    if amenities:
        haystack = " ".join(
            [str(a).lower() for a in (listing.amenities or [])]
            + [listing.title or "", listing.description or ""]
        )
        hits = [a for a in amenities if a in haystack]
        score(10, 10 * len(hits) / len(amenities), f"Amenities: {', '.join(hits[:5])}" if hits else None)

    # --- Timing & occupancy ---
    if requirement.move_in_date is not None:
        available = listing.available_from is None or listing.available_from <= requirement.move_in_date
        score(8, 8 if available else 0, "Available by move-in date" if available else None)
    if requirement.occupants is not None:
        capacity = listing.maximum_occupancy
        hit = capacity is None or capacity >= requirement.occupants
        score(6, 6 if hit else 0, f"Fits {requirement.occupants} occupant(s)" if hit else None)

    if possible == 0:
        return 50.0, ["Available listing"]
    return round(achieved * 100 / possible, 1), reasons


def top_matches_for_requirement(requirement, queryset=None, limit: int = TOP_MATCH_LIMIT) -> dict:
    """Score available listings and return the best `limit` matches.

    Saved location fields act as a hard filter — only listings inside the
    tenant's location are recommended. ``outside_location_count`` reports how
    many listings elsewhere still satisfy the rest of the requirement.
    """
    empty = {"matches": [], "in_location_count": 0, "outside_location_count": 0}
    if not requirement_has_criteria(requirement):
        return empty
    qs = queryset if queryset is not None else public_listings_queryset()

    location_q = _location_filter_q(requirement)
    if location_q is not None:
        in_location_qs = qs.filter(location_q)
        outside_location_count = (
            qs.exclude(pk__in=in_location_qs.values("pk"))
            .filter(_strict_requirement_q(requirement))
            .count()
        )
    else:
        in_location_qs = qs
        outside_location_count = 0

    scored = []
    for listing in in_location_qs:
        score, reasons = score_listing_for_requirement(requirement, listing)
        scored.append({
            "listing": listing,
            "match_score": score,
            "match_reasons": reasons,
            "_sort": (score, bool(listing.featured), listing.created_at or timezone.now()),
        })
    scored.sort(key=lambda item: item["_sort"], reverse=True)
    for item in scored:
        item.pop("_sort", None)
    return {
        "matches": scored[: max(1, limit)],
        "in_location_count": len(scored),
        "outside_location_count": outside_location_count,
    }


def requirement_to_search_filters(requirement) -> dict:
    """Translate a saved requirement into search_properties tool arguments."""
    filters: dict = {}
    if _norm(requirement.preferred_city):
        filters["city"] = requirement.preferred_city
    if _norm(requirement.preferred_state):
        filters["state"] = requirement.preferred_state
    if _norm(requirement.preferred_lga):
        filters["lga"] = requirement.preferred_lga
    areas = [a.strip() for a in str(requirement.preferred_areas or "").split(",") if a.strip()]
    if areas:
        filters["area"] = areas[0]
    if requirement.min_budget is not None:
        filters["min_price"] = float(requirement.min_budget)
    if requirement.max_budget is not None:
        filters["max_price"] = float(requirement.max_budget)
    if requirement.max_nightly_budget is not None:
        filters["max_nightly_rate"] = float(requirement.max_nightly_budget)
    if _norm(requirement.property_type):
        filters["property_type"] = requirement.property_type
    if requirement.min_bedrooms is not None:
        filters["min_bedrooms"] = requirement.min_bedrooms
    if requirement.max_bedrooms is not None:
        filters["max_bedrooms"] = requirement.max_bedrooms
    if requirement.min_bathrooms is not None:
        filters["bathrooms"] = requirement.min_bathrooms
    if requirement.min_toilets is not None:
        filters["toilets"] = requirement.min_toilets
    if _norm(requirement.furnishing_level):
        filters["furnishing_level"] = requirement.furnishing_level
    if _norm(requirement.power_supply):
        filters["power_supply"] = requirement.power_supply
    if _norm(requirement.water_supply):
        filters["water_supply"] = requirement.water_supply
    for field, _listing_field, _label in BOOLEAN_REQUIREMENT_FIELDS:
        if getattr(requirement, field):
            filters[field] = True
    amenities = [a for a in (requirement.preferred_amenities or []) if str(a).strip()]
    if amenities:
        filters["amenity"] = str(amenities[0]).strip()
    if requirement.move_in_date is not None:
        filters["available_by"] = requirement.move_in_date.isoformat()
    if requirement.occupants is not None:
        filters["min_occupancy"] = requirement.occupants
    return filters


_LOCATION_FILTER_KEYS = {"city", "state", "lga", "area"}


def requirement_search_filters_without_location(requirement) -> dict:
    """Search-filters dict with the location fields removed — lets Sally show
    matches outside the saved location when the tenant asks for them."""
    return {
        key: value
        for key, value in requirement_to_search_filters(requirement).items()
        if key not in _LOCATION_FILTER_KEYS
    }


def requirement_summary(requirement) -> dict:
    """Compact human/LLM-readable dict of the saved requirement."""
    summary: dict = {}
    for field in ("preferred_state", "preferred_city", "preferred_lga", "preferred_areas",
                  "property_type", "furnishing_level", "power_supply", "water_supply", "notes"):
        value = _norm(getattr(requirement, field))
        if value:
            summary[field] = getattr(requirement, field)
    for field in ("min_budget", "max_budget", "max_nightly_budget"):
        value = getattr(requirement, field)
        if value is not None:
            summary[field] = float(value)
    for field in ("min_bedrooms", "max_bedrooms", "min_bathrooms", "min_toilets", "occupants"):
        value = getattr(requirement, field)
        if value is not None:
            summary[field] = value
    if requirement.move_in_date is not None:
        summary["move_in_date"] = requirement.move_in_date.isoformat()
    if requirement.preferred_amenities:
        summary["preferred_amenities"] = requirement.preferred_amenities
    required = [label for field, _lf, label in BOOLEAN_REQUIREMENT_FIELDS if getattr(requirement, field)]
    if required:
        summary["required_features"] = required
    summary["updated_at"] = requirement.updated_at.isoformat() if requirement.updated_at else None
    return summary
