import json
import logging
import re
import time
import uuid
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings
from django.core.cache import cache
from django.db.models import Avg, Case, Count, F, IntegerField, Q, Value, When
from django.http import StreamingHttpResponse
from django.utils.decorators import method_decorator
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from .ai_knowledge import site_content_for_text, site_content_for_topic
from .financial_constants import (
    ADMINISTRATION_FEE_RATE,
    ADMINISTRATION_FEE_VAT_RATE,
    CARD_PAYMENT_LIMIT_NGN,
    DEFAULT_SUBSCRIPTION_VAT_RATE_PERCENT,
    FEATURED_PROPERTY_MONTHLY_FEE,
    LISTING_DEPOSIT_RATE,
    REFUNDABLE_SECURITY_DEPOSIT_RATE,
)
from .location_services import CITY_COORDINATES, STATE_COORDINATES
from .models import Listing, deposit_secured_booking_queryset
from .permissions import AllowAnyUnlessFrozen
from .pricing import (
    calculate_administration_fee,
    calculate_administration_fee_vat,
    calculate_refundable_security_deposit,
    quantize_money,
)
from .serializers import PublicAiListingSerializer
from .subscription_pricing import get_subscription_pricing
from .throttling import production_ratelimit

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Sally, the AI assistant for the RentDirect rental marketplace in Nigeria.

Your job is to help users find rental properties and answer general questions about the RentDirect platform.

RULES:
1. Never invent properties, prices, availability, landlords, or locations.
2. Always use the search_properties tool when the user asks about properties to rent, and get_listing_stats when the user asks how many properties are listed or about marketplace counts/availability. Never estimate or invent numbers — report only what the tools return.
3. Only describe properties returned by the tools. Never claim a property is available unless the tool result shows it.
4. Only discuss non-sensitive public information. Never reveal personal data, payment details, passwords, or internal system details. Never quote street addresses or precise landmarks — you can mention the city, area or state, but the exact location is only revealed on RentDirect once the user subscribes or pays for that listing.
5. If required information is missing (e.g. location), ask a short clarifying question.
6. Preserve filters from earlier in the conversation when the user refines their request (e.g. "only furnished", "cheaper ones").
7. Property prices are per year in Nigerian Naira (₦). "₦2m" means 2000000, "₦500k" means 500000.
8. For questions about RentDirect itself, prefer the live tools: get_pricing_and_fees for prices, fees, subscription plans, and rental charges; get_listing_stats for listing counts. Use get_marketplace_info only for narrative topics — about, how_it_works, verification, search_and_features, messaging_and_support, faqs.
9. Keep answers short and friendly. When properties are found, briefly summarise what matched (count, general price range, locations). The app renders the property cards and images separately, so never paste raw JSON, listing IDs, or per-property spec lists — do not quote individual listing prices, deposits, or feature lists in your reply; the cards show those. When answering questions about RentDirect, summarise the tool content conversationally in your own words — do not recite it verbatim.
10. Reply in plain text only — the chat UI does not render markdown. Do not use **, __, #, `, or other markdown syntax.
11. Sound like a helpful human, not a brochure. Use contractions, vary sentence length, acknowledge what the user just said, and be honest when something isn't available ("I don't see any 3-bed flats in Lekki right now, but there are 2-bed ones"). End with at most one short natural follow-up — never a menu of options.
12. Listings carry trust and cost data you can use: a verified flag, reviews/ratings, neighbourhood/area and landmark, fees (service charge, caution fee, legal fee), nightly rate for short-lets, furnishing level, power/water supply, and security features. For "best rated", "most popular", "cheapest", or "verified only" requests use the sort/verified_only filters. When asked what a property costs to move in, call get_property_details — it returns estimated_move_in_cost_ngn and fees_breakdown_ngn.
"""

TOOL_LIST = [
    {
        "type": "function",
        "function": {
            "name": "search_properties",
            "description": "Search available rental properties on the RentDirect marketplace. Returns matching public listings.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Free-text search over title, description and address."},
                    "city": {"type": "string", "description": "City or area name, e.g. 'Lekki', 'Ikeja', 'Wuse'."},
                    "state": {"type": "string", "description": "Nigerian state, e.g. 'Lagos', 'FCT', 'Rivers'."},
                    "min_price": {"type": "number", "description": "Minimum yearly rent in NGN."},
                    "max_price": {"type": "number", "description": "Maximum yearly rent in NGN."},
                    "bedrooms": {"type": "integer", "description": "Number of bedrooms."},
                    "bathrooms": {"type": "integer", "description": "Number of bathrooms."},
                    "toilets": {"type": "integer", "description": "Number of toilets."},
                    "property_type": {
                        "type": "string",
                        "description": "Property type, e.g. flat, apartment, house, studio, penthouse, villa, townhouse, duplex, self-contain.",
                    },
                    "lga": {"type": "string", "description": "Local Government Area, e.g. 'Eti-Osa', 'Ikeja'."},
                    "area": {"type": "string", "description": "Neighbourhood, estate or landmark, e.g. 'Lekki Phase 1', 'GRA'."},
                    "amenity": {"type": "string", "description": "A specific amenity or feature keyword, e.g. 'pool', 'gym', 'inverter'."},
                    "pet_friendly": {"type": "boolean"},
                    "furnished": {"type": "boolean"},
                    "utilities_included": {"type": "boolean"},
                    "parking": {"type": "boolean"},
                    "garage": {"type": "boolean"},
                    "garden": {"type": "boolean"},
                    "lift": {"type": "boolean", "description": "Elevator."},
                    "balcony": {"type": "boolean"},
                    "smart_lock": {"type": "boolean"},
                    "pop_ceiling": {"type": "boolean"},
                    "electric_fence": {"type": "boolean"},
                    "fitted_kitchen": {"type": "boolean"},
                    "smoking_allowed": {"type": "boolean"},
                    "short_let_allowed": {"type": "boolean"},
                    "student_tenants_allowed": {"type": "boolean"},
                    "expatriates_allowed": {"type": "boolean"},
                    "commercial_activities_allowed": {"type": "boolean"},
                    "furnishing_level": {"type": "string", "description": "unfurnished, semi_furnished or fully_furnished."},
                    "air_conditioning": {"type": "boolean"},
                    "internet": {"type": "boolean"},
                    "boys_quarters": {"type": "boolean", "description": "BQ / boys quarters."},
                    "prepaid_meter": {"type": "boolean"},
                    "gated_estate": {"type": "boolean"},
                    "security_guard": {"type": "boolean"},
                    "cctv": {"type": "boolean"},
                    "wheelchair_accessible": {"type": "boolean"},
                    "negotiable": {"type": "boolean", "description": "Rent marked negotiable by the landlord."},
                    "power_supply": {"type": "string", "description": "24_hours, grid_with_backup, grid_only or limited."},
                    "water_supply": {"type": "string", "description": "constant, borehole, public_mains, tanker or irregular."},
                    "min_bedrooms": {"type": "integer", "description": "At least this many bedrooms (range queries like '3-5 bedrooms')."},
                    "max_bedrooms": {"type": "integer"},
                    "max_nightly_rate": {"type": "number", "description": "Maximum nightly rate in NGN — for short-let queries."},
                    "min_occupancy": {"type": "integer", "description": "Minimum maximum-occupancy the listing must allow."},
                    "available_by": {"type": "string", "description": "ISO date; listing must be available on or before this date."},
                    "available_now": {"type": "boolean", "description": "Only listings available immediately."},
                    "verified_only": {"type": "boolean", "description": "Only listings verified by RentDirect."},
                    "sort": {
                        "type": "string",
                        "description": (
                            "Result ordering: featured (default), newest, price_low, price_high, "
                            "verified (verified listings first), rating (best reviewed first), "
                            "popular (most booked/enquired first)."
                        ),
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_property_details",
            "description": "Get public details for one marketplace listing by its id.",
            "parameters": {
                "type": "object",
                "properties": {"listing_id": {"type": "string", "description": "Listing UUID."}},
                "required": ["listing_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_listing_stats",
            "description": (
                "Get live marketplace counts: total available listings and breakdowns by state, city, "
                "and property type. Use for 'how many properties are listed' and similar count questions. "
                "Pass a state or city to scope the breakdown to that location."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "state": {"type": "string", "description": "Optional state to scope counts to, e.g. 'Lagos' or 'Delta'"},
                    "city": {"type": "string", "description": "Optional city to scope counts to"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pricing_and_fees",
            "description": (
                "Get live RentDirect pricing: subscription plans and prices per role, rental charges "
                "(administration fee, VAT, refundable deposit), featured listing fee, card payment "
                "limit, payment methods, and what each plan unlocks."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_marketplace_info",
            "description": (
                "Get non-sensitive RentDirect site content: the About page, how the platform works, "
                "verification, search features, FAQs, and support contacts. "
                "Not for prices, fees, or subscription plans — use get_pricing_and_fees. "
                "Not for listing counts — use get_listing_stats or search_properties."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": (
                            "Content topic: about, how_it_works, verification, fees_and_payments, "
                            "search_and_features, messaging_and_support, or faqs."
                        ),
                    },
                },
            },
        },
    },
]


def _public_listings_queryset():
    qs = (
        Listing.objects.select_related("landlord")
        .prefetch_related("images")
        .filter(status=Listing.Status.AVAILABLE)
    )
    return qs.exclude(id__in=deposit_secured_booking_queryset().values("listing_id"))


def _to_decimal(value):
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _to_int(value):
    if value is None or value == "":
        return None
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _to_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return None


def _listing_summary(listing) -> dict:
    summary = {
        "id": str(listing.id),
        "title": listing.title,
        "city": listing.city,
        "state": listing.state,
        "lga": listing.lga,
        "area": listing.area,
        "property_type": listing.property_type,
        "bedrooms": listing.bedrooms,
        "bathrooms": listing.bathrooms,
        "toilets": listing.toilets,
        "price_per_year": float(listing.price_per_year or 0),
        "deposit_amount": float(listing.deposit_amount) if listing.deposit_amount is not None else None,
        "furnished": listing.furnished,
        "furnishing_level": listing.furnishing_level,
        "pet_friendly": listing.pet_friendly,
        "parking": listing.parking,
        "utilities_included": listing.utilities_included,
        "negotiable": listing.negotiable,
        "nightly_rate": float(listing.nightly_rate) if listing.nightly_rate is not None else None,
        "available_from": listing.available_from.isoformat() if listing.available_from else None,
        "featured": listing.featured,
        "verified": _listing_is_verified(listing),
    }
    avg_rating = getattr(listing, "_avg_rating", None)
    if avg_rating is not None:
        summary["average_rating"] = round(float(avg_rating), 1)
        summary["review_count"] = getattr(listing, "_review_count", 0)
    booking_count = getattr(listing, "_booking_count", None)
    if booking_count is not None:
        summary["booking_count"] = booking_count
    return summary


def _listing_is_verified(listing) -> bool:
    return (
        listing.physical_property_status == "verified"
        or listing.property_document_verification_status == "verified"
    )


def search_properties_tool(arguments: dict) -> dict:
    """Execute a filtered search over public listings. Returns summaries for the LLM."""
    qs = _public_listings_queryset()

    query = str(arguments.get("query") or "").strip()
    city = str(arguments.get("city") or "").strip()
    state = str(arguments.get("state") or "").strip()
    min_price = _to_decimal(arguments.get("min_price"))
    max_price = _to_decimal(arguments.get("max_price"))
    bedrooms = _to_int(arguments.get("bedrooms"))
    bathrooms = _to_int(arguments.get("bathrooms"))
    toilets = _to_int(arguments.get("toilets"))
    property_type = str(arguments.get("property_type") or "").strip()
    lga = str(arguments.get("lga") or "").strip()
    amenity = str(arguments.get("amenity") or "").strip()

    applied_filters = {}
    if query:
        applied_filters["query"] = query
        qs = qs.filter(Q(title__icontains=query) | Q(description__icontains=query) | Q(address__icontains=query))
    if city:
        applied_filters["city"] = city
        qs = qs.filter(Q(city__icontains=city) | Q(address__icontains=city))
    if state:
        applied_filters["state"] = state
        # New listings store "Federal Capital Territory"; older data and users say "FCT".
        state_terms = {state}
        if state.lower() in {"fct", "abuja"}:
            state_terms.add("Federal Capital Territory")
        elif state.lower() == "federal capital territory":
            state_terms.update({"FCT", "Abuja"})
        state_query = Q()
        for term in state_terms:
            state_query |= (
                Q(state__icontains=term)
                | Q(address__icontains=term)
                | Q(landlord__residence__state__icontains=term)
            )
        qs = qs.filter(state_query)
    if min_price is not None:
        applied_filters["min_price"] = float(min_price)
        qs = qs.filter(price_per_year__gte=min_price)
    if max_price is not None:
        applied_filters["max_price"] = float(max_price)
        qs = qs.filter(price_per_year__lte=max_price)
    if bedrooms is not None:
        applied_filters["bedrooms"] = bedrooms
        qs = qs.filter(bedrooms=bedrooms)
    if bathrooms is not None:
        applied_filters["bathrooms"] = bathrooms
        qs = qs.filter(bathrooms=bathrooms)
    if toilets is not None:
        applied_filters["toilets"] = toilets
        qs = qs.filter(toilets=toilets)
    if property_type:
        applied_filters["property_type"] = property_type
        qs = qs.filter(Q(property_type__iexact=property_type) | Q(property_type__icontains=property_type))
    if lga:
        applied_filters["lga"] = lga
        qs = qs.filter(Q(lga__icontains=lga) | Q(address__icontains=lga) | Q(city__icontains=lga))
    area = str(arguments.get("area") or "").strip()
    if area:
        applied_filters["area"] = area
        qs = qs.filter(
            Q(area__icontains=area)
            | Q(nearest_landmark__icontains=area)
            | Q(address__icontains=area)
            | Q(city__icontains=area)
        )
    if amenity:
        applied_filters["amenity"] = amenity
        qs = qs.filter(
            Q(amenities__icontains=amenity)
            | Q(description__icontains=amenity)
            | Q(title__icontains=amenity)
        )
    for key in (
        "pet_friendly", "furnished", "utilities_included", "parking",
        "garage", "garden", "lift", "balcony", "smart_lock", "pop_ceiling",
        "electric_fence", "fitted_kitchen", "smoking_allowed", "short_let_allowed",
        "student_tenants_allowed", "expatriates_allowed", "commercial_activities_allowed",
        "air_conditioning", "internet", "boys_quarters", "prepaid_meter",
        "gated_estate", "security_guard", "cctv", "wheelchair_accessible", "negotiable",
    ):
        flag = _to_bool(arguments.get(key))
        if flag is True:
            applied_filters[key] = True
            qs = qs.filter(**{key: True})
    for key in ("furnishing_level", "power_supply", "water_supply"):
        value = str(arguments.get(key) or "").strip().lower().replace(" ", "_").replace("-", "_")
        if value:
            applied_filters[key] = value
            qs = qs.filter(**{key: value})

    min_bedrooms = _to_int(arguments.get("min_bedrooms"))
    max_bedrooms = _to_int(arguments.get("max_bedrooms"))
    if min_bedrooms is not None:
        applied_filters["min_bedrooms"] = min_bedrooms
        qs = qs.filter(bedrooms__gte=min_bedrooms)
    if max_bedrooms is not None:
        applied_filters["max_bedrooms"] = max_bedrooms
        qs = qs.filter(bedrooms__lte=max_bedrooms)
    max_nightly_rate = _to_decimal(arguments.get("max_nightly_rate"))
    if max_nightly_rate is not None:
        applied_filters["max_nightly_rate"] = float(max_nightly_rate)
        qs = qs.filter(short_let_allowed=True, nightly_rate__lte=max_nightly_rate)

    min_occupancy = _to_int(arguments.get("min_occupancy"))
    if min_occupancy is not None:
        applied_filters["min_occupancy"] = min_occupancy
        qs = qs.filter(maximum_occupancy__gte=min_occupancy)

    available_by = str(arguments.get("available_by") or "").strip()
    if available_by:
        applied_filters["available_by"] = available_by
        qs = qs.filter(Q(available_from__isnull=True) | Q(available_from__lte=available_by))
    if arguments.get("available_now") is True or str(arguments.get("available_now") or "").lower() == "true":
        from django.utils import timezone
        applied_filters["available_now"] = True
        qs = qs.filter(Q(available_from__isnull=True) | Q(available_from__lte=timezone.localdate()))

    if _to_bool(arguments.get("verified_only")):
        applied_filters["verified_only"] = True
        qs = qs.filter(
            Q(physical_property_status="verified")
            | Q(property_document_verification_status="verified")
        )

    sort = str(arguments.get("sort") or "").strip().lower()
    if sort == "verified":
        applied_filters["sort"] = "verified"
        qs = qs.annotate(
            _verified=Case(
                When(
                    Q(physical_property_status="verified")
                    | Q(property_document_verification_status="verified"),
                    then=Value(1),
                ),
                default=Value(0),
                output_field=IntegerField(),
            )
        ).order_by("-_verified", "-featured", "-created_at")
    elif sort == "rating":
        applied_filters["sort"] = "rating"
        qs = qs.annotate(
            _avg_rating=Avg("reviews__rating"),
            _review_count=Count("reviews"),
        ).order_by(F("_avg_rating").desc(nulls_last=True), "-_review_count", "-created_at")
    elif sort == "popular":
        applied_filters["sort"] = "popular"
        qs = qs.annotate(_booking_count=Count("bookings")).order_by("-_booking_count", "-featured", "-created_at")
    elif sort == "price_low":
        applied_filters["sort"] = "price_low"
        qs = qs.order_by("price_per_year", "-created_at")
    elif sort == "price_high":
        applied_filters["sort"] = "price_high"
        qs = qs.order_by("-price_per_year", "-created_at")
    elif sort == "newest":
        applied_filters["sort"] = "newest"
        qs = qs.order_by("-created_at")
    else:
        qs = qs.order_by("-featured", "-created_at")
    total = qs.count()
    limit = max(1, int(getattr(settings, "AI_CHAT_SEARCH_LIMIT", 12)))
    listings = list(qs[:limit])
    return {
        "total_count": total,
        "returned_count": len(listings),
        "listings": [_listing_summary(listing) for listing in listings],
        "listing_objects": listings,
        "filters": applied_filters,
    }


def get_property_details_tool(arguments: dict) -> dict:
    listing = (
        _public_listings_queryset()
        .filter(id=str(arguments.get("listing_id") or "").strip())
        .first()
    )
    if listing is None:
        return {"found": False}
    summary = _listing_summary(listing)
    summary.update(
        {
            "found": True,
            "description": listing.description,
            # Precise location is withheld from the assistant — it unlocks for
            # subscribed users or tenants who paid for this listing on-site.
            "exact_location_note": "Street address and landmark are only revealed on RentDirect after subscribing or paying for this listing.",
            "square_feet": listing.square_feet,
            "service_charge_ngn": float(listing.service_charge) if listing.service_charge is not None else None,
            "amenities": listing.amenities,
            "features": {
                "garage": listing.garage,
                "garden": listing.garden,
                "lift": listing.lift,
                "balcony": listing.balcony,
                "smart_lock": listing.smart_lock,
                "pop_ceiling": listing.pop_ceiling,
                "electric_fence": listing.electric_fence,
                "fitted_kitchen": listing.fitted_kitchen,
                "air_conditioning": listing.air_conditioning,
                "internet": listing.internet,
                "boys_quarters": listing.boys_quarters,
                "prepaid_meter": listing.prepaid_meter,
                "gated_estate": listing.gated_estate,
                "security_guard": listing.security_guard,
                "cctv": listing.cctv,
                "wheelchair_accessible": listing.wheelchair_accessible,
                "power_supply": listing.power_supply,
                "water_supply": listing.water_supply,
                "floor_number": listing.floor_number,
                "total_floors": listing.total_floors,
                "parking_spaces": listing.parking_spaces,
                "year_built": listing.year_built,
                "pet_policy": listing.pet_policy,
                "video_tour_url": listing.video_tour_url,
            },
            "rules": {
                "minimum_rental_duration": listing.minimum_rental_duration,
                "maximum_rental_duration": listing.maximum_rental_duration,
                "maximum_occupancy": listing.maximum_occupancy,
                "smoking_allowed": listing.smoking_allowed,
                "short_let_allowed": listing.short_let_allowed,
                "student_tenants_allowed": listing.student_tenants_allowed,
                "expatriates_allowed": listing.expatriates_allowed,
                "commercial_activities_allowed": listing.commercial_activities_allowed,
            },
            "landlord_name": listing.landlord.name,
        }
    )
    # Estimated move-in cost: rent + platform charges + listing fees — lets Sally
    # answer "what will it cost to move in?" with real numbers.
    if listing.price_per_year is not None:
        rent = Decimal(listing.price_per_year)
        admin_fee = calculate_administration_fee(rent)
        admin_vat = calculate_administration_fee_vat(rent)
        security_deposit = calculate_refundable_security_deposit(rent)
        listing_fees = {
            "service_charge": listing.service_charge,
            "caution_fee": listing.caution_fee,
            "legal_fee": listing.legal_fee,
        }
        extras = sum(Decimal(v) for v in listing_fees.values() if v is not None)
        summary["fees_breakdown_ngn"] = {
            "annual_rent": float(rent),
            "administration_fee": float(admin_fee),
            "vat_on_administration_fee": float(admin_vat),
            "refundable_security_deposit": float(security_deposit),
            **{k: float(v) if v is not None else None for k, v in listing_fees.items()},
        }
        summary["estimated_move_in_cost_ngn"] = float(
            quantize_money(rent + admin_fee + admin_vat + security_deposit + extras)
        )
    return summary


def get_listing_stats_tool(arguments: dict) -> dict:
    """Live marketplace counts for 'how many properties are listed' questions."""
    qs = _public_listings_queryset()
    state = str(arguments.get("state") or "").strip()
    city = str(arguments.get("city") or "").strip()
    if state:
        state_terms = {state}
        if state.lower() in {"fct", "abuja"}:
            state_terms.add("Federal Capital Territory")
        elif state.lower() == "federal capital territory":
            state_terms.update({"FCT", "Abuja"})
        state_query = Q()
        for term in state_terms:
            state_query |= Q(state__icontains=term)
        qs = qs.filter(state_query)
    if city:
        qs = qs.filter(city__icontains=city)
    by_state = list(
        qs.exclude(state="")
        .values("state")
        .annotate(count=Count("id"))
        .order_by("-count", "state")
    )
    by_city = list(
        qs.exclude(city="")
        .values("city", "state")
        .annotate(count=Count("id"))
        .order_by("-count", "city")
    )
    by_type = list(
        qs.exclude(property_type="")
        .values("property_type")
        .annotate(count=Count("id"))
        .order_by("-count", "property_type")
    )
    return {
        "total_available": qs.count(),
        "scope": {key: value for key, value in {"state": state, "city": city}.items() if value},
        "by_state": by_state,
        "by_city": by_city,
        "by_property_type": by_type,
    }


def get_pricing_and_fees_tool(_arguments: dict) -> dict:
    """Live pricing from financial_constants — never hardcoded in prompts or copy."""
    plans = {
        role: {
            plan: {
                "monthly_ngn": float(amounts["monthly"]),
                "yearly_ngn": float(amounts["yearly"]),
            }
            for plan, amounts in role_plans.items()
        }
        for role, role_plans in get_subscription_pricing().items()
    }
    return {
        "currency": "NGN",
        "rental_charges": {
            "administration_fee_percent_of_annual_rent": float(ADMINISTRATION_FEE_RATE * 100),
            "vat_on_administration_fee_percent": float(ADMINISTRATION_FEE_VAT_RATE * 100),
            "refundable_security_deposit_percent": float(REFUNDABLE_SECURITY_DEPOSIT_RATE * 100),
            "listing_deposit_percent": float(LISTING_DEPOSIT_RATE * 100),
        },
        "subscription_plans": plans,
        "subscription_vat_percent": float(DEFAULT_SUBSCRIPTION_VAT_RATE_PERCENT),
        "featured_listing_monthly_fee_ngn": float(FEATURED_PROPERTY_MONTHLY_FEE),
        "card_payment_limit_ngn": float(CARD_PAYMENT_LIMIT_NGN),
        "plan_requirements": {
            "tenant": "Silver or higher is required to contact landlords, apply to rent, make rental payments, and track rental progress.",
            "landlord": "Silver or higher is required to create property listings.",
        },
        "payment_methods": "Card or bank transfer via Flutterwave",
        "billing": "Subscriptions and payments are managed from the Billing page.",
    }


def _execute_tool(name: str, arguments: dict) -> dict:
    if name == "search_properties":
        return search_properties_tool(arguments)
    if name == "get_property_details":
        return get_property_details_tool(arguments)
    if name == "get_listing_stats":
        return get_listing_stats_tool(arguments)
    if name == "get_pricing_and_fees":
        return get_pricing_and_fees_tool(arguments)
    if name == "get_marketplace_info":
        return site_content_for_topic(str(arguments.get("topic") or ""))
    return {"error": f"Unknown tool: {name}"}


def _plain_text(text: str) -> str:
    """Strip markdown formatting — the chat UI renders replies as plain text."""
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"(\*\*|__)(.*?)\1", r"\2", text)
    text = re.sub(r"(\*|_)(.*?)\1", r"\2", text)
    text = re.sub(r"~~(.*?)~~", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    return text.strip()


def _provider_ready() -> bool:
    return bool(
        getattr(settings, "AI_CHAT_BASE_URL", "").strip()
        and getattr(settings, "AI_CHAT_MODEL", "").strip()
    )


def _chat_models() -> list:
    """Primary model followed by configured fallbacks, de-duplicated."""
    models = []
    for model in [getattr(settings, "AI_CHAT_MODEL", ""), *getattr(settings, "AI_CHAT_FALLBACK_MODELS", [])]:
        model = str(model).strip()
        if model and model not in models:
            models.append(model)
    return models


def _chat_completion(messages: list) -> dict:
    base_url = settings.AI_CHAT_BASE_URL.rstrip("/")
    headers = {"Content-Type": "application/json"}
    if getattr(settings, "AI_CHAT_API_KEY", ""):
        headers["Authorization"] = f"Bearer {settings.AI_CHAT_API_KEY}"
    if "openrouter.ai" in base_url:
        headers["HTTP-Referer"] = getattr(settings, "WEB_PUBLIC_URL", "")
        headers["X-Title"] = "RentDirect"
    payload = {
        "messages": messages,
        "tools": TOOL_LIST,
        "tool_choice": "auto",
        "temperature": 0.2,
    }
    if getattr(settings, "AI_CHAT_REASONING", False):
        payload["reasoning"] = {"enabled": True}
    last_error = None
    for model in _chat_models():
        try:
            response = requests.post(
                f"{base_url}/chat/completions",
                json={**payload, "model": model},
                headers=headers,
                timeout=getattr(settings, "AI_CHAT_TIMEOUT_SECONDS", 45),
            )
            response.raise_for_status()
            data = response.json()
            if "choices" not in data:
                raise RuntimeError(f"AI provider returned no choices: {data}")
            return data["choices"][0]["message"]
        except Exception as exc:
            last_error = exc
            logger.warning("AI chat model %s failed: %s", model, exc)
    if last_error is not None:
        raise last_error
    raise RuntimeError("No AI chat models configured.")


def _chat_payload(messages: list) -> dict:
    payload = {
        "messages": messages,
        "tools": TOOL_LIST,
        "tool_choice": "auto",
        "temperature": 0.3,
    }
    if getattr(settings, "AI_CHAT_REASONING", False):
        payload["reasoning"] = {"enabled": True}
    return payload


def _chat_headers() -> dict:
    base_url = settings.AI_CHAT_BASE_URL.rstrip("/")
    headers = {"Content-Type": "application/json"}
    if getattr(settings, "AI_CHAT_API_KEY", ""):
        headers["Authorization"] = f"Bearer {settings.AI_CHAT_API_KEY}"
    if "openrouter.ai" in base_url:
        headers["HTTP-Referer"] = getattr(settings, "WEB_PUBLIC_URL", "")
        headers["X-Title"] = "RentDirect"
    return headers


def _iter_chat_completion(messages: list):
    """Stream one completion round. Yields content deltas; returns the assembled message.

    Tool-call deltas are accumulated silently. If a model fails before producing
    any content the next configured model is tried; once content has been
    delivered we stop retrying so the client never sees duplicated text.
    """
    base_url = settings.AI_CHAT_BASE_URL.rstrip("/")
    headers = _chat_headers()
    payload = {**_chat_payload(messages), "stream": True}
    timeout = getattr(settings, "AI_CHAT_TIMEOUT_SECONDS", 45)
    last_error = None
    for model in _chat_models():
        content_parts = []
        tool_calls_acc: dict[int, dict] = {}
        reasoning = None
        try:
            with requests.post(
                f"{base_url}/chat/completions",
                json={**payload, "model": model},
                headers=headers,
                timeout=timeout,
                stream=True,
            ) as response:
                response.raise_for_status()
                # Decode SSE bytes as UTF-8 ourselves — providers often omit a
                # charset, which makes requests guess ISO-8859-1 and mangle ₦/em-dashes.
                for raw_line in response.iter_lines(decode_unicode=False):
                    if not raw_line:
                        continue
                    line = raw_line.decode("utf-8", errors="replace")
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    if chunk.get("error"):
                        raise RuntimeError(f"AI provider stream error: {chunk['error']}")
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    text = delta.get("content")
                    if text:
                        content_parts.append(text)
                        yield text
                    for tool_call in delta.get("tool_calls") or []:
                        index = tool_call.get("index", 0)
                        slot = tool_calls_acc.setdefault(
                            index,
                            {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                        )
                        if tool_call.get("id"):
                            slot["id"] += tool_call["id"]
                        function = tool_call.get("function") or {}
                        if function.get("name"):
                            slot["function"]["name"] += function["name"]
                        if function.get("arguments"):
                            slot["function"]["arguments"] += function["arguments"]
                    if delta.get("reasoning_details"):
                        reasoning = delta["reasoning_details"]
            message = {"role": "assistant", "content": "".join(content_parts)}
            if tool_calls_acc:
                message["tool_calls"] = [tool_calls_acc[i] for i in sorted(tool_calls_acc)]
            if reasoning:
                message["reasoning_details"] = reasoning
            return message
        except Exception as exc:
            if content_parts:
                raise
            last_error = exc
            logger.warning("AI chat model %s stream failed: %s", model, exc)
    if last_error is not None:
        raise last_error
    raise RuntimeError("No AI chat models configured.")


_SESSION_KEY_PREFIX = "ai_chat_session:"


def _chat_session_ttl() -> int:
    return max(300, int(getattr(settings, "AI_CHAT_SESSION_TTL_SECONDS", 7200)))


def _load_chat_session(session_id: str) -> dict:
    if not session_id or not re.fullmatch(r"[0-9a-f]{32}", session_id):
        return {}
    data = cache.get(f"{_SESSION_KEY_PREFIX}{session_id}")
    return data if isinstance(data, dict) else {}


def _save_chat_session(session_id: str, session: dict) -> None:
    cache.set(f"{_SESSION_KEY_PREFIX}{session_id}", session, timeout=_chat_session_ttl())


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


def _stream_text_events(text: str, chunk_size: int = 4, delay: float = 0.02):
    """Stream generated fallback text in small chunks so it types like the LLM path."""
    for index in range(0, len(text), chunk_size):
        yield _sse({"type": "delta", "text": text[index:index + chunk_size]})
        if delay:
            time.sleep(delay)


# Popular neighbourhoods/areas missing from CITY_COORDINATES — map them to
# (city, state) so the fallback search still narrows correctly.
_AREA_TO_CITY_STATE = {
    # Lagos
    "sangotedo": ("Lagos", "Lagos"), "ikate": ("Lekki", "Lagos"),
    "agungi": ("Lekki", "Lagos"), "osapa london": ("Lekki", "Lagos"),
    "chevron": ("Lekki", "Lagos"), "orchid": ("Lekki", "Lagos"),
    "vgc": ("Lekki", "Lagos"), "awoyaya": ("Lekki", "Lagos"),
    "abijo": ("Lekki", "Lagos"), "lakowe": ("Lekki", "Lagos"),
    "oniru": ("Victoria Island", "Lagos"), "banana island": ("Ikoyi", "Lagos"),
    "parkview": ("Ikoyi", "Lagos"), "dolphin estate": ("Ikoyi", "Lagos"),
    "obalende": ("Lagos Island", "Lagos"), "onikan": ("Lagos Island", "Lagos"),
    "ogba": ("Ikeja", "Lagos"), "ojodu": ("Ikeja", "Lagos"),
    "maryland": ("Ikeja", "Lagos"), "magodo": ("Kosofe", "Lagos"),
    "ketu": ("Kosofe", "Lagos"), "ojota": ("Kosofe", "Lagos"),
    "gbagada": ("Shomolu", "Lagos"), "festac": ("Amuwo-Odofin", "Lagos"),
    "amuwo odofin": ("Amuwo-Odofin", "Lagos"), "satellite town": ("Ojo", "Lagos"),
    "ejigbo": ("Oshodi-Isolo", "Lagos"), "ikotun": ("Alimosho", "Lagos"),
    "egbeda": ("Alimosho", "Lagos"), "iyana ipaja": ("Alimosho", "Lagos"),
    "abule egba": ("Ifako-Ijaiye", "Lagos"), "ilupeju": ("Mushin", "Lagos"),
    "anthony": ("Shomolu", "Lagos"), "ogudu": ("Kosofe", "Lagos"),
    "palmgrove": ("Shomolu", "Lagos"), "ebute metta": ("Lagos Mainland", "Lagos"),
    "bariga": ("Shomolu", "Lagos"), "oworonshoki": ("Kosofe", "Lagos"),
    # FCT / Abuja
    "wuse 2": ("Abuja", "FCT"), "life camp": ("Abuja", "FCT"),
    "katampe": ("Abuja", "FCT"), "jahi": ("Abuja", "FCT"),
    "kado": ("Abuja", "FCT"), "durumi": ("Abuja", "FCT"),
    "gudu": ("Abuja", "FCT"), "apo": ("Abuja", "FCT"),
    "lokogoma": ("Abuja", "FCT"), "galadimawa": ("Abuja", "FCT"),
    "guzape": ("Abuja", "FCT"), "wuye": ("Abuja", "FCT"),
    "mpape": ("Abuja", "FCT"), "dawaki": ("Abuja", "FCT"),
    "zuba": ("Abuja", "FCT"), "karmo": ("Abuja", "FCT"),
    "nyanya": ("Karu", "Nasarawa"), "karu": ("Karu", "Nasarawa"),
    "mararaba": ("Karu", "Nasarawa"), "masaka": ("Karu", "Nasarawa"),
    # Port Harcourt ("GRA" alone is ambiguous — exists in many cities, so it's left out)
    "trans amadi": ("Port Harcourt", "Rivers"),
    "woji": ("Port Harcourt", "Rivers"), "rumuola": ("Port Harcourt", "Rivers"),
    "rumuokoro": ("Port Harcourt", "Rivers"), "choba": ("Port Harcourt", "Rivers"),
    "ada george": ("Port Harcourt", "Rivers"), "eliozu": ("Port Harcourt", "Rivers"),
    "d line": ("Port Harcourt", "Rivers"), "diobu": ("Port Harcourt", "Rivers"),
    "oyigbo": ("Oyigbo", "Rivers"), "eleme": ("Eleme", "Rivers"),
}


def _fallback_filters(text: str) -> dict:
    """Best-effort keyword extraction used when no AI provider is configured."""
    normalized = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    filters = {}

    # Multi-word area names first ("Osapa London", "Wuse 2") before generic city match.
    for area, (city, state) in sorted(_AREA_TO_CITY_STATE.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{re.escape(area)}\b", normalized):
            filters["city"] = city
            filters["state"] = state
            break

    city_hits = [
        (city, state)
        for (city, state) in CITY_COORDINATES
        if re.search(rf"\b{re.escape(city)}\b", normalized)
    ]
    if city_hits:
        # Prefer a real city over a name that is both a city and a state (e.g. Lagos).
        city, state = max(city_hits, key=lambda hit: (hit[0] != hit[1], len(hit[0])))
        if city != state and "city" not in filters:
            filters["city"] = city.title()
        filters["state"] = "FCT" if state == "fct" else state.title()
    elif "state" not in filters:
        for state_name in STATE_COORDINATES:
            if re.search(rf"\b{re.escape(state_name)}\b", normalized):
                filters["state"] = "FCT" if state_name == "fct" else state_name.title()
                break
        if "abuja" in normalized and "state" not in filters:
            filters["state"] = "FCT"

    bedrooms = re.search(r"(\d+)\s*(?:bedroom|bed|br)\b", normalized)
    if bedrooms:
        filters["bedrooms"] = int(bedrooms.group(1))
    bathrooms = re.search(r"(\d+)\s*(?:bathroom|bath)\b", normalized)
    if bathrooms:
        filters["bathrooms"] = int(bathrooms.group(1))

    price_match = re.search(r"(\d+(?:\.\d+)?)\s*(m|million|k|thousand)\b", normalized)
    if price_match:
        amount = float(price_match.group(1))
        amount *= 1_000_000 if price_match.group(2) in {"m", "million"} else 1_000
        filters["max_price"] = amount
    else:
        bare_amount = re.search(r"(?:under|below|less than|max(?:imum)?|up to)\s*(?:₦|ngn|n)?\s*(\d{5,})", normalized)
        if bare_amount:
            filters["max_price"] = float(bare_amount.group(1))

    # "50k per night" is a nightly-rate cap, not a yearly-rent cap.
    if "max_price" in filters and re.search(r"\b(?:per\s*night|nightly|a\s*night|per\s*day|daily)\b", normalized):
        filters["max_nightly_rate"] = filters.pop("max_price")
        filters["short_let_allowed"] = True

    for prop_type in ("self contain", "self-contain", "apartment", "penthouse", "townhouse", "flat", "house", "studio", "villa", "duplex"):
        if re.search(rf"\b{re.escape(prop_type)}\b", normalized):
            filters["property_type"] = prop_type
            break

    if re.search(r"\bfurnished\b", normalized):
        filters["furnished"] = True
    if re.search(r"\bpet", normalized):
        filters["pet_friendly"] = True
    if re.search(r"\bparking\b", normalized):
        filters["parking"] = True
    if re.search(r"\butilities\b", normalized):
        filters["utilities_included"] = True

    _BOOLEAN_KEYWORDS = [
        (r"\b(?:lift|elevator)\b", "lift"),
        (r"\bgarage\b", "garage"),
        (r"\bgarden\b", "garden"),
        (r"\bbalcony\b", "balcony"),
        (r"\bsmart\s*lock\b", "smart_lock"),
        (r"\bpop\s*(?:ceiling)?\b", "pop_ceiling"),
        (r"\belectric\s*fence\b", "electric_fence"),
        (r"\bfitted\s*kitchen\b", "fitted_kitchen"),
        (r"\bsmoking\b", "smoking_allowed"),
        (r"\bshort[\s-]?let\b", "short_let_allowed"),
        (r"\bstudent", "student_tenants_allowed"),
        (r"\bexpat", "expatriates_allowed"),
        (r"\bcommercial\b", "commercial_activities_allowed"),
        (r"\bair\s*condition(?:ing|er|ers)?\b|\ba/?c\b", "air_conditioning"),
        (r"\b(?:wi-?fi|internet|fibre|fiber)\b", "internet"),
        (r"\b(?:bq|boys\s*quarters?)\b", "boys_quarters"),
        (r"\bprepaid\s*meter\b", "prepaid_meter"),
        (r"\bgated\b", "gated_estate"),
        (r"\bsecurity\s*(?:guard|man|post)\b|\b24\s*(?:hours?|hrs?|/7)\s*security\b", "security_guard"),
        (r"\bcctv\b", "cctv"),
        (r"\bwheelchair\b", "wheelchair_accessible"),
        (r"\bnegotiable\b", "negotiable"),
    ]
    for pattern, key in _BOOLEAN_KEYWORDS:
        if re.search(pattern, normalized):
            filters[key] = True

    if re.search(r"\bsemi[\s-]?furnished\b", normalized):
        filters["furnishing_level"] = "semi_furnished"
    elif re.search(r"\b(?:fully\s*furnished|furnished)\b", normalized):
        filters["furnishing_level"] = "fully_furnished"
    elif re.search(r"\bunfurnished\b", normalized):
        filters["furnishing_level"] = "unfurnished"

    if re.search(r"\b(?:24\s*(?:hours?|hrs?|/7)\s*(?:light|power|electricity)|constant\s*(?:light|power|electricity))\b", normalized):
        filters["power_supply"] = "24_hours"

    if "furnishing_level" in filters:
        filters.pop("furnished", None)

    for pattern, keyword in (
        (r"\b(?:swimming\s*)?pool\b", "pool"),
        (r"\bgym\b", "gym"),
        (r"\binverter\b", "inverter"),
        (r"\bgenerator\b", "generator"),
        (r"\bborehole\b", "borehole"),
    ):
        if re.search(pattern, normalized):
            filters["amenity"] = keyword
            break

    if re.search(r"\bverified\b", normalized):
        filters["verified_only"] = True
    if re.search(r"\b(?:best|top|highest)\s*rated\b|\bhighly\s*rated\b", normalized):
        filters["sort"] = "rating"
    elif re.search(r"\bmost\s*(?:popular|booked|viewed)\b|\bpopular\b", normalized):
        filters["sort"] = "popular"
    elif re.search(r"\bcheapest\b|\blowest\s*price\b", normalized):
        filters["sort"] = "price_low"
    elif re.search(r"\b(?:newest|latest|newly\s*listed)\b", normalized):
        filters["sort"] = "newest"
    if re.search(r"\b(?:available\s*now|move\s*in\s*(?:now|immediately|today)|immediate)\b", normalized):
        filters["available_now"] = True

    return filters


_LISTING_WORD_RE = re.compile(
    r"\b(?:propert\w*|listing\w*|home\w*|house\w*|housing|flat\w*|apartment\w*|rental\w*|unit\w*|accommodation\w*)"
)
_COUNT_QUESTION_RE = re.compile(r"\b(?:how many|how may|number of)\b")
_COUNT_LISTING_RE = _LISTING_WORD_RE
_COUNT_EXCLUSION_RE = re.compile(
    r"\bhow\s+ma[yn]+\s+(?:bed|bath|toilet|room|floor|people|guest|occupant|bedroom|bathroom)"
)
_BROWSE_QUESTION_RE = re.compile(
    r"\b(?:what|which|any|show|see|browse|search|find|look(?:ing)? for|have|got|available|offer|listed|for rent)\b"
)
_HOW_TO_RE = re.compile(r"^how\s+(?:do|does|can|to|is|are|would|should)\b")
_LANDLORD_HOWTO_RE = re.compile(
    r"\b(?:list|add|create|post|put up|register)\b.{0,25}\b(?:my|own)\b.{0,20}"
    r"(?:propert|listing|house|flat|apartment)"
)
_SPECIFIC_LISTING_RE = re.compile(
    r"\b(?:this|that|the|it)\s+(?:property|listing|house|flat|apartment)\b"
    r"|\b(?:property|listing)\s+(?:id|details)\b"
)


def _is_count_question(normalized: str) -> bool:
    if _COUNT_EXCLUSION_RE.search(normalized):
        return False
    has_listing_ref = bool(
        _LISTING_WORD_RE.search(normalized)
        or re.search(r"\d\s*-?\s*bed", normalized)
    )
    return bool(_COUNT_QUESTION_RE.search(normalized) and has_listing_ref)


_GLOBAL_SCOPE_RE = re.compile(
    r"\b(?:all (?:of )?(?:the )?states?|across all|everywhere|anywhere|in total|total number|"
    r"overall|on rentdirect|in rentdirect|nationwide|whole country|countrywide)\b"
)
_REFINEMENT_RE = re.compile(
    r"\b(?:only|just|also|instead|rather|what about|how about|any of|cheaper|"
    r"narrow|prefer|filter|those|them|these|still|excluding|except|without)\b"
)


def _merge_search_filters(prior_filters: dict | None, new_filters: dict, normalized: str) -> dict:
    """Merge stored session filters on explicit refinements only ("only
    furnished ones", "any cheaper?"). A fresh standalone query, count
    question, or global-scope phrasing resets them so stale constraints
    (e.g. an earlier Delta search) don't leak into new questions."""
    if not prior_filters:
        return dict(new_filters or {})
    if (
        _GLOBAL_SCOPE_RE.search(normalized)
        or _is_count_question(normalized)
        or not _REFINEMENT_RE.search(normalized)
    ):
        return dict(new_filters or {})
    return {**dict(prior_filters), **dict(new_filters or {})}


def _is_browse_question(normalized: str) -> bool:
    if _HOW_TO_RE.match(normalized) or _LANDLORD_HOWTO_RE.search(normalized):
        return False
    if _SPECIFIC_LISTING_RE.search(normalized):
        return False
    return bool(_BROWSE_QUESTION_RE.search(normalized) and _LISTING_WORD_RE.search(normalized))


_PRICING_QUESTION_RE = re.compile(
    r"\b(?:fee|fees|cost|price|pricing|subscribe|subscription|plan|charge|deposit|how much|payment|pay)\b"
)
_GREETING_RE = re.compile(
    r"^(?:hi|hello|hey|hiya|yo|good\s+(?:morning|afternoon|evening)|howdy)\b"
)
_THANKS_RE = re.compile(
    r"^(?:thank|thanks|thank you|appreciated|appreciate|cheers|nice|great|awesome|perfect)\b"
)


def _factual_intent(normalized: str) -> str | None:
    """Map a factual question to the tool that owns the data, or None for narrative chat."""
    if _is_count_question(normalized):
        return "get_listing_stats"
    if _PRICING_QUESTION_RE.search(normalized):
        return "get_pricing_and_fees"
    if _is_browse_question(normalized) or _fallback_filters(normalized):
        return "search_properties"
    return None


def _plan_prices_line(role: str, plans: dict) -> str:
    return ", ".join(
        f"{plan.title()} at ₦{amounts['monthly_ngn']:,.0f}/month or ₦{amounts['yearly_ngn']:,.0f}/year"
        if amounts["monthly_ngn"]
        else f"{plan.title()} is free"
        for plan, amounts in plans.get(role, {}).items()
    )


def _pricing_reply(normalized: str, user_messages: list | None = None) -> str:
    """Build a fallback pricing answer scoped to what was actually asked."""
    pricing = get_pricing_and_fees_tool({})
    plans = pricing["subscription_plans"]
    charges = pricing["rental_charges"]

    wants_subscription = bool(
        re.search(r"subscri|plan|bronze|silver|gold|platinum", normalized)
    )
    wants_rental_fees = bool(
        re.search(r"deposit|admin|vat|service fee|checkout|rental", normalized)
    )

    # Role scope: from this message, else carry it over from earlier user turns
    # (e.g. "I asked only for subscription fees" after a tenant question).
    asks_tenant = "tenant" in normalized
    asks_landlord = "landlord" in normalized
    if not asks_tenant and not asks_landlord:
        for earlier in user_messages or []:
            if earlier.get("role") != "user":
                continue
            text = str(earlier.get("content") or "").lower()
            if "tenant" in text:
                asks_tenant = True
            if "landlord" in text:
                asks_landlord = True

    parts = []
    if wants_subscription or not wants_rental_fees:
        if asks_landlord and not asks_tenant:
            parts.append(f"For landlords, {_plan_prices_line('landlord', plans)}.")
            parts.append(pricing["plan_requirements"]["landlord"])
        elif asks_tenant and not asks_landlord:
            parts.append(f"For tenants, {_plan_prices_line('tenant', plans)}.")
            parts.append(pricing["plan_requirements"]["tenant"])
        else:
            parts.append(f"For tenants, {_plan_prices_line('tenant', plans)}.")
            parts.append(f"For landlords, {_plan_prices_line('landlord', plans)}.")
            parts.append(
                f"{pricing['plan_requirements']['tenant']} "
                f"{pricing['plan_requirements']['landlord']}"
            )
        vat = pricing["subscription_vat_percent"]
        if vat:
            parts.append(f"Paid plans add {vat:g}% VAT.")
    if wants_rental_fees:
        parts.append(
            f"When you rent, there's a "
            f"{charges['administration_fee_percent_of_annual_rent']:g}% administration fee "
            f"(plus {charges['vat_on_administration_fee_percent']:g}% VAT on it) and a "
            f"{charges['refundable_security_deposit_percent']:g}% refundable security deposit — "
            "you'll see the full breakdown before paying."
        )
    reply = " ".join(parts)
    if re.search(r"\b(?:only|just|asked)\b", normalized):
        reply = f"Ah, fair enough — just that bit then: {reply}"
    return reply


def _fallback_chat(user_messages: list, prior_filters: dict | None = None) -> dict:
    """Rule-based assistant used when no AI provider is configured/reachable."""
    last_user_message = next(
        (m["content"] for m in reversed(user_messages) if m.get("role") == "user"),
        "",
    )
    normalized = re.sub(r"\s+", " ", last_user_message.lower()).strip()
    if _GREETING_RE.match(normalized):
        return {
            "reply": (
                "Hi there! I'm Sally — happy to help you find a place or answer anything about "
                "RentDirect. What are you looking for?"
            ),
            "listings": [],
            "listing_objects": [],
            "filters": {},
        }
    if _THANKS_RE.match(normalized):
        return {
            "reply": "You're welcome! Anything else you'd like to check — more properties, fees, or how things work?",
            "listings": [],
            "listing_objects": [],
            "filters": {},
        }
    filters = _fallback_filters(last_user_message)
    if _is_count_question(normalized):
        # Count questions are a fresh scope — never merge prior filters.
        non_location = {k: v for k, v in filters.items() if k not in ("state", "city")}
        if non_location:
            # e.g. "how many 3 bedroom flats are listed" — count the matching search.
            result = search_properties_tool(filters)
            total = result["total_count"]
            noun = "property" if total == 1 else "properties"
            label_parts = []
            if filters.get("bedrooms"):
                label_parts.append(f"{filters['bedrooms']}-bedroom")
            if filters.get("property_type"):
                label_parts.append(str(filters["property_type"]).replace("-", " "))
            what = f"{' '.join(label_parts)} {noun}" if label_parts else noun
            where_bits = [str(v) for v in (filters.get("city"), filters.get("state")) if v]
            where = f" in {', '.join(where_bits)}" if where_bits else " on RentDirect"
            reply = f"Right now there {'is' if total == 1 else 'are'} {total} {what} listed{where}."
            if total:
                reply += " Want me to show them to you?"
            return {
                "reply": reply,
                "listings": result["listings"],
                "listing_objects": result["listing_objects"],
                "filters": result["filters"],
                "total_count": result["total_count"],
            }
        stats = get_listing_stats_tool(
            {k: filters[k] for k in ("state", "city") if filters.get(k)}
        )
        total = stats["total_available"]
        noun = "property" if total == 1 else "properties"
        scope = stats["scope"]
        in_where = f" in {scope.get('city') or scope.get('state')}" if scope else ""
        reply = f"Right now there {'is' if total == 1 else 'are'} {total} {noun} listed{in_where}."
        if not scope:
            top_states = [row["state"] for row in stats["by_state"][:3]]
            if top_states:
                reply += f" Most of them are in {', '.join(top_states)}."
            reply = reply.replace("listed.", "listed on RentDirect.")
        elif stats["by_city"] and scope.get("state"):
            cities = ", ".join(row["city"] for row in stats["by_city"])
            reply += f" Cities with listings there: {cities}."
        if total:
            reply += " Tell me a location, budget, or bedroom count and I'll pull up the ones that fit."
        return {"reply": reply, "listings": [], "listing_objects": [], "filters": {}}
    if filters:
        # Refinements keep earlier constraints ("only furnished", "cheaper ones").
        filters = _merge_search_filters(prior_filters, filters, normalized)
        result = search_properties_tool(filters)
        count = result["total_count"]
        if count:
            label_parts = []
            if filters.get("bedrooms"):
                label_parts.append(f"{filters['bedrooms']}-bedroom")
            if filters.get("property_type"):
                label_parts.append(str(filters["property_type"]).replace("-", " "))
            noun = "property" if count == 1 else "properties"
            what = f"{' '.join(label_parts)} {noun}" if label_parts else noun
            where_bits = [str(v) for v in (filters.get("city"), filters.get("state")) if v]
            where = f" in {', '.join(where_bits)}" if where_bits else ""
            reply = (
                f"I found {count} {what}{where} — "
                f"{'it is' if count == 1 else 'they are'} in the results below. "
                "Want me to narrow it down by budget or features?"
            )
        else:
            reply = (
                "Hmm, nothing matches that right now — try widening the location or budget "
                "and I'll take another look."
            )
        return {
            "reply": reply,
            "listings": result["listings"],
            "listing_objects": result["listing_objects"],
            "filters": result["filters"],
            "total_count": result["total_count"],
        }
    if _PRICING_QUESTION_RE.search(normalized):
        return {
            "reply": _pricing_reply(normalized, user_messages),
            "listings": [],
            "listing_objects": [],
            "filters": {},
        }
    if _is_browse_question(normalized):
        result = search_properties_tool(_merge_search_filters(prior_filters, {}, normalized))
        total = result["total_count"]
        if total:
            noun = "property" if total == 1 else "properties"
            reply = (
                f"Here's what we've got — {total} {noun} listed right now"
                f"{', the latest are below' if total > 1 else ', it is below'}. "
                "Tell me a location or budget and I'll narrow it down for you."
            )
        else:
            reply = "Looks like there aren't any listings right now — worth checking back soon, new ones come in."
        return {
            "reply": reply,
            "listings": result["listings"],
            "listing_objects": result["listing_objects"],
            "filters": result["filters"],
            "total_count": result["total_count"],
        }
    info_text = site_content_for_text(last_user_message)
    if info_text:
        return {
            "reply": info_text,
            "listings": [],
            "listing_objects": [],
            "filters": {},
        }
    return {
        "reply": (
            "I can help you find a rental — just tell me the location, bedrooms, and budget, "
            "like \"2 bedroom flat in Lagos under ₦2m\". Or ask me anything about how "
            "RentDirect works, fees, or verification."
        ),
        "listings": [],
        "listing_objects": [],
        "filters": {},
    }


def _record_search_result(result: dict, collected: dict, filters: dict) -> int:
    """Collect listing ids and applied filters from a search_properties result."""
    filters.update(result.get("filters") or {})
    for summary in result.get("listings") or []:
        collected.setdefault(summary["id"], summary)
    return int(result.get("total_count") or 0)


def _inject_grounding_tool(conversation: list, tool_name: str, arguments: dict) -> dict:
    """Run a data tool server-side and inject the result so the reply can only
    phrase real facts — used when the model answered a factual question without
    calling any tool."""
    result = _execute_tool(tool_name, arguments)
    conversation.append(
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": f"grounding_{tool_name}",
                    "type": "function",
                    "function": {"name": tool_name, "arguments": json.dumps(arguments)},
                }
            ],
        }
    )
    conversation.append(
        {
            "role": "tool",
            "tool_call_id": f"grounding_{tool_name}",
            "content": json.dumps(
                {k: v for k, v in result.items() if k != "listing_objects"},
                default=str,
            ),
        }
    )
    return result


def run_ai_chat(user_messages: list, prior_filters: dict | None = None) -> dict:
    """Run the LLM tool-calling loop. Falls back to keyword search without a provider."""
    if not _provider_ready():
        result = _fallback_chat(user_messages, prior_filters)
        result["mode"] = "limited"
        result["total_count"] = int(result.get("total_count") or 0)
        return result

    conversation = [{"role": "system", "content": SYSTEM_PROMPT}, *user_messages]
    collected: dict[str, dict] = {}
    filters: dict = {}
    total_count = 0
    reply = ""
    tool_ran = False
    grounding_done = False
    last_text = user_messages[-1]["content"] if user_messages else ""
    intent = _factual_intent(re.sub(r"\s+", " ", last_text.lower()).strip())

    try:
        max_rounds = max(1, int(getattr(settings, "AI_CHAT_MAX_TOOL_ROUNDS", 4)))
        for _round in range(max_rounds + 1):
            message = _chat_completion(conversation)
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                if intent and not tool_ran and not grounding_done:
                    # Factual question answered without data — ground it ourselves.
                    grounding_done = True
                    arguments = {}
                    extracted = _fallback_filters(last_text)
                    norm_text = re.sub(r"\s+", " ", last_text.lower()).strip()
                    if intent == "get_listing_stats" and any(
                        k not in ("state", "city") for k in extracted
                    ):
                        # "how many 3-bed flats" — stats can't filter specs; count via search.
                        intent = "search_properties"
                    if intent == "search_properties":
                        arguments = _merge_search_filters(prior_filters, extracted, norm_text)
                    elif intent == "get_listing_stats":
                        arguments = {k: extracted[k] for k in ("state", "city") if extracted.get(k)}
                    result = _inject_grounding_tool(conversation, intent, arguments)
                    if intent == "search_properties":
                        total_count = _record_search_result(result, collected, filters)
                    tool_ran = True
                    continue
                reply = (message.get("content") or "").strip()
                break
            tool_ran = True
            assistant_message = {
                "role": "assistant",
                "content": message.get("content") or "",
                "tool_calls": tool_calls,
            }
            if message.get("reasoning_details"):
                assistant_message["reasoning_details"] = message["reasoning_details"]
            conversation.append(assistant_message)
            for call in tool_calls:
                function = call.get("function") or {}
                name = function.get("name") or ""
                try:
                    arguments = json.loads(function.get("arguments") or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                result = _execute_tool(name, arguments)
                if name == "search_properties":
                    total_count = _record_search_result(result, collected, filters)
                conversation.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id") or name,
                        "content": json.dumps(
                            {k: v for k, v in result.items() if k != "listing_objects"},
                            default=str,
                        ),
                    }
                )
    except Exception:
        logger.exception("AI chat provider call failed; using fallback assistant.")
        result = _fallback_chat(user_messages, prior_filters)
        result["mode"] = "limited"
        result["total_count"] = int(result.get("total_count") or 0)
        return result

    reply = _plain_text(reply)
    if not reply:
        reply = "Here's what I found on RentDirect for you."

    listing_objects = []
    if collected:
        objects = {
            str(listing.id): listing
            for listing in _public_listings_queryset().filter(id__in=list(collected.keys()))
        }
        listing_objects = [objects[key] for key in collected.keys() if key in objects]

    return {
        "reply": reply,
        "listings": [_listing_summary(listing) for listing in listing_objects],
        "listing_objects": listing_objects,
        "filters": filters,
        "total_count": total_count,
        "mode": "ai",
    }


def _stream_completion_events(conversation: list):
    """Yield SSE delta events for one completion round; return the message."""
    stream = _iter_chat_completion(conversation)
    try:
        while True:
            yield _sse({"type": "delta", "text": next(stream)})
    except StopIteration as stop:
        return stop.value


def iter_ai_chat_events(user_messages: list, prior_filters: dict, session_id: str, final: dict):
    """SSE event generator: streams the assistant reply live, then a done event.

    Fills ``final`` with reply/filters so the caller can persist session state.
    """
    yield _sse({"type": "session", "session_id": session_id})
    final["filters"] = {}

    def done(reply: str, result: dict, mode: str) -> str:
        final["reply"] = reply
        final["filters"] = result.get("filters") or {}
        return _sse(
            {
                "type": "done",
                "reply": reply,
                "listings": PublicAiListingSerializer(
                    result.get("listing_objects") or [], many=True
                ).data,
                "filters": result.get("filters") or {},
                "total_count": int(result.get("total_count") or 0),
                "mode": mode,
                "session_id": session_id,
            }
        )

    if not _provider_ready():
        result = _fallback_chat(user_messages, prior_filters)
        reply = result["reply"]
        yield from _stream_text_events(reply)
        yield done(reply, result, "limited")
        return

    conversation = [{"role": "system", "content": SYSTEM_PROMPT}, *user_messages]
    collected: dict[str, dict] = {}
    filters: dict = {}
    total_count = 0
    reply = ""
    tool_ran = False
    grounding_done = False
    last_text = user_messages[-1]["content"] if user_messages else ""
    intent = _factual_intent(re.sub(r"\s+", " ", last_text.lower()).strip())

    try:
        max_rounds = max(1, int(getattr(settings, "AI_CHAT_MAX_TOOL_ROUNDS", 4)))
        for _round in range(max_rounds + 1):
            # Each streamed round starts a fresh text segment in the UI.
            yield _sse({"type": "segment"})
            message = yield from _stream_completion_events(conversation)
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                if intent and not tool_ran and not grounding_done:
                    # Ungrounded factual answer — run the data tool ourselves
                    # and let the model rephrase from real results.
                    grounding_done = True
                    arguments = {}
                    extracted = _fallback_filters(last_text)
                    norm_text = re.sub(r"\s+", " ", last_text.lower()).strip()
                    if intent == "get_listing_stats" and any(
                        k not in ("state", "city") for k in extracted
                    ):
                        # "how many 3-bed flats" — stats can't filter specs; count via search.
                        intent = "search_properties"
                    if intent == "search_properties":
                        arguments = _merge_search_filters(prior_filters, extracted, norm_text)
                    elif intent == "get_listing_stats":
                        arguments = {k: extracted[k] for k in ("state", "city") if extracted.get(k)}
                    result = _inject_grounding_tool(conversation, intent, arguments)
                    if intent == "search_properties":
                        total_count = _record_search_result(result, collected, filters)
                        yield _sse(
                            {
                                "type": "listings",
                                "listings": PublicAiListingSerializer(
                                    result.get("listing_objects") or [], many=True
                                ).data,
                                "total_count": total_count,
                                "filters": result.get("filters") or {},
                            }
                        )
                    tool_ran = True
                    continue
                reply = (message.get("content") or "").strip()
                break
            tool_ran = True
            assistant_message = {
                "role": "assistant",
                "content": message.get("content") or "",
                "tool_calls": tool_calls,
            }
            if message.get("reasoning_details"):
                assistant_message["reasoning_details"] = message["reasoning_details"]
            conversation.append(assistant_message)
            for call in tool_calls:
                function = call.get("function") or {}
                name = function.get("name") or ""
                try:
                    arguments = json.loads(function.get("arguments") or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                result = _execute_tool(name, arguments)
                if name == "search_properties":
                    total_count = _record_search_result(result, collected, filters)
                    yield _sse(
                        {
                            "type": "listings",
                            "listings": PublicAiListingSerializer(
                                result.get("listing_objects") or [], many=True
                            ).data,
                            "total_count": total_count,
                            "filters": result.get("filters") or {},
                        }
                    )
                conversation.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id") or name,
                        "content": json.dumps(
                            {k: v for k, v in result.items() if k != "listing_objects"},
                            default=str,
                        ),
                    }
                )
    except Exception:
        logger.exception("AI chat stream failed; using fallback assistant.")
        yield _sse({"type": "segment"})
        result = _fallback_chat(user_messages, prior_filters)
        reply = result["reply"]
        yield from _stream_text_events(reply)
        yield done(reply, result, "limited")
        return

    reply = _plain_text(reply)
    if not reply:
        reply = "Here's what I found on RentDirect for you."

    listing_objects = []
    if collected:
        objects = {
            str(listing.id): listing
            for listing in _public_listings_queryset().filter(id__in=list(collected.keys()))
        }
        listing_objects = [objects[key] for key in collected.keys() if key in objects]

    result = {
        "listing_objects": listing_objects,
        "filters": filters,
        "total_count": total_count,
    }
    yield done(reply, result, "ai")


def _validated_messages(payload) -> list:
    """Legacy contract: a full client-supplied history.

    Client-supplied assistant turns are dropped — only the server may author
    assistant messages (a forged assistant turn is a prompt-injection vector).
    New clients should send {message, session_id} instead.
    """
    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise ValidationError({"messages": "Provide a list of chat messages."})
    max_messages = max(1, int(getattr(settings, "AI_CHAT_MAX_MESSAGES", 20)))
    max_chars = max(200, int(getattr(settings, "AI_CHAT_MAX_MESSAGE_CHARS", 2000)))
    cleaned = []
    for item in messages[-max_messages:]:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()[:max_chars]
        if item.get("role") == "user" and content:
            cleaned.append({"role": "user", "content": content})
    if not cleaned:
        raise ValidationError({"messages": "The last message must be a user message."})
    return cleaned


def _resolve_chat_context(payload) -> tuple[str, dict, list]:
    """Resolve (session_id, session, user_messages) for either contract.

    New contract: {message, session_id?} — history lives server-side.
    Legacy: {messages: [...]} — assistant turns stripped, no persistence.
    """
    max_chars = max(200, int(getattr(settings, "AI_CHAT_MAX_MESSAGE_CHARS", 2000)))
    if isinstance(payload.get("message"), str) and payload["message"].strip():
        message = payload["message"].strip()[:max_chars]
        session_id = str(payload.get("session_id") or "").strip()
        session = _load_chat_session(session_id)
        if session_id and not session:
            session_id = ""  # expired/unknown id — start a fresh session
        if not session_id:
            session_id = uuid.uuid4().hex
            session = {"messages": [], "filters": {}}
        history = list(session.get("messages") or [])
        return session_id, session, [*history, {"role": "user", "content": message}]
    return "", {"messages": [], "filters": {}}, _validated_messages(payload)


@method_decorator(
    production_ratelimit(key="ip", rate="30/m", method="POST", block=True),
    name="create",
)
@method_decorator(
    production_ratelimit(key="ip", rate="30/m", method="POST", block=True),
    name="stream",
)
class AiChatViewSet(viewsets.ViewSet):
    """Public read-only AI assistant endpoints: POST /api/v1/chat and /api/v1/chat/stream"""

    permission_classes = [AllowAnyUnlessFrozen]

    def _persist_session(self, session_id: str, session: dict, user_messages: list, reply: str, filters: dict) -> None:
        if not session_id:
            return
        max_messages = max(1, int(getattr(settings, "AI_CHAT_MAX_MESSAGES", 20)))
        messages = [*user_messages]
        if reply:
            messages.append({"role": "assistant", "content": reply})
        session["messages"] = messages[-max_messages:]
        if filters:
            session["filters"] = filters
        _save_chat_session(session_id, session)

    def create(self, request):
        session_id, session, user_messages = _resolve_chat_context(request.data)
        result = run_ai_chat(user_messages, prior_filters=session.get("filters"))
        self._persist_session(
            session_id, session, user_messages, result["reply"], result.get("filters") or {}
        )
        serializer = PublicAiListingSerializer(result["listing_objects"], many=True)
        return Response(
            {
                "reply": result["reply"],
                "listings": serializer.data,
                "filters": result["filters"],
                "total_count": result.get("total_count") or 0,
                "mode": result.get("mode") or "ai",
                "session_id": session_id or None,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["post"], url_path="stream")
    def stream(self, request):
        session_id, session, user_messages = _resolve_chat_context(request.data)
        if not session_id:
            session_id = uuid.uuid4().hex
        prior_filters = session.get("filters") or {}
        final: dict = {}

        def events():
            try:
                yield from iter_ai_chat_events(user_messages, prior_filters, session_id, final)
            except Exception:
                logger.exception("AI chat stream failed unexpectedly.")
                yield _sse(
                    {
                        "type": "done",
                        "reply": "Sorry, I hit a snag answering that. Please try again.",
                        "listings": [],
                        "filters": {},
                        "total_count": 0,
                        "mode": "limited",
                        "session_id": session_id,
                    }
                )
            finally:
                self._persist_session(
                    session_id,
                    session,
                    user_messages,
                    final.get("reply") or "",
                    final.get("filters") or {},
                )

        response = StreamingHttpResponse(events(), content_type="text/event-stream")
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response
