"""Public site content served to the AI assistant.

Condensed, non-sensitive copies of the About page, How-it-works page,
tenant/landlord guides and support FAQs so the assistant can answer general
questions without inventing facts. Anything derivable — prices, fees, listing
counts — is generated from the live constants/database rather than duplicated
here, so this file only holds narrative copy that has no other source.
"""

from .financial_constants import (
    ADMINISTRATION_FEE_RATE,
    ADMINISTRATION_FEE_VAT_RATE,
    REFUNDABLE_CAUTION_FEE_RATE,
)
from .subscription_pricing import get_subscription_pricing

PLATFORM_OVERVIEW = (
    "RentDirect is a Nigerian rental marketplace that connects verified landlords "
    "directly with verified tenants — no unnecessary middlemen, hidden fees, or "
    "unclear processes. Users can browse verified listings, communicate securely, "
    "apply, pay, and track the full rental journey in one place."
)


def _plan_prices(role: str) -> str:
    """e.g. 'Bronze free, Silver ₦500/month or ₦5,000/year, ...' — from live pricing."""
    parts = []
    for plan, amounts in get_subscription_pricing().get(role, {}).items():
        monthly, yearly = amounts["monthly"], amounts["yearly"]
        if monthly:
            parts.append(f"{plan.title()} ₦{monthly:,.0f}/month or ₦{yearly:,.0f}/year")
        else:
            parts.append(f"{plan.title()} free")
    return ", ".join(parts)


def _fees_content() -> str:
    """Fees topic built from financial_constants so numbers never drift from checkout."""
    admin_pct = float(ADMINISTRATION_FEE_RATE * 100)
    vat_pct = float(ADMINISTRATION_FEE_VAT_RATE * 100)
    deposit_pct = float(REFUNDABLE_CAUTION_FEE_RATE * 100)
    return (
        f"Fees and payments: Rent is priced per year in Naira. At checkout tenants pay the rent plus an "
        f"administration fee of {admin_pct:g}% of the annual rent (plus {vat_pct:g}% VAT on the fee) and a "
        f"refundable caution fee of {deposit_pct:g}% — all shown before payment. Payments are made "
        f"securely by card or bank transfer through Flutterwave, with payment history, receipts, and "
        f"balances in the dashboard. Subscription plans — tenants: {_plan_prices('tenant')}. Landlords: "
        f"{_plan_prices('landlord')}. Tenants need Silver or higher to contact landlords, apply to rent, "
        f"pay rent, and track rental progress; landlords need Silver or higher to create listings. "
        f"Location analytics, radius, and map-based search are available from Silver. Subscriptions and "
        f"payments are managed from Billing. Landlords can promote listings through Featured placement."
    )


SITE_KNOWLEDGE = [
    {
        "topic": "about",
        "keywords": ["about", "mission", "vision", "who", "why", "company", "rentdirect", "scam", "fraud", "trust"],
        "content": (
            "About RentDirect: RentDirect was created to fix the difficult Nigerian rental process — "
            "multiple agents, hidden fees, inspection charges, fake listings, and rental scams for tenants; "
            "and limited visibility into applicants, third-party dependence, and fraudulent applicants for landlords. "
            "Mission: to create the most transparent, trusted, and efficient rental marketplace where verified "
            "landlords connect directly with verified tenants. "
            "Trust features: identity verification for landlords and tenants, property ownership verification, "
            "verified contact information, tenant screening, secure document management, transparent communication "
            "records, digital tenancy records, and rental history tracking. "
            "Benefits for tenants: avoid intermediary costs and inspection-fee surprises, rent from verified "
            "landlords, apply online and track status in real time, build a rental reputation. "
            "Benefits for landlords: access verified quality tenants, manage listings and applications directly, "
            "reduce vacancy periods, simplify screening, and build reputation through verification and reviews. "
            "Vision: renting a property should be as transparent and straightforward as booking a hotel room online."
        ),
    },
    {
        "topic": "how_it_works",
        "keywords": ["how", "work", "process", "steps", "journey", "use", "start"],
        "content": (
            "How RentDirect works: "
            "Tenants — create an account (Tenant role), confirm email, complete identity verification, build a "
            "verified profile (employment, financial, rental history, guarantor details), search listings by "
            "location/budget/rooms/features, subscribe to a plan (Silver or higher is required to contact "
            "landlords, apply, pay rent, and track rental progress), contact landlords and arrange viewings "
            "directly, select 'Rent This Property' to apply, pay deposit and rent securely, then follow the "
            "rental progress checklist to move-in. "
            "Landlords — create an account (Landlord role), complete identity and property verification, "
            "subscribe to a plan (Silver or higher is required to create listings), add accurate listing "
            "details with photos and availability, receive enquiries, review verified applicant "
            "profiles, communicate directly, accept applications, and track bookings, payments, and tenancy "
            "milestones from the dashboard."
        ),
    },
    {
        "topic": "verification",
        "keywords": ["verif", "verify", "nin", "bvn", "identity", "screening", "approval"],
        "content": (
            "Verification: Tenant and landlord verification typically takes 1-2 business days; property document "
            "verification may take longer when additional checks are required. Tenants complete identity "
            "verification (NIN and BVN) from the dashboard before completing their detailed profile and before "
            "contacting landlords directly. Landlords choose Individual or Corporate verification and upload "
            "identification documents. Property ownership can be verified by uploading ownership documents or "
            "requesting an in-person inspection by an authorised RentDirect agent or lawyer. Landlords must be "
            "verified before creating listings."
        ),
    },
    {
        "topic": "fees_and_payments",
        "keywords": ["fee", "cost", "charge", "pay", "payment", "price", "deposit", "service", "subscription", "plan", "card", "transfer"],
        "content": _fees_content,
    },
    {
        "topic": "search_and_features",
        "keywords": ["search", "filter", "find", "location", "map", "radius", "favourite", "save"],
        "content": (
            "Searching on RentDirect: users can filter available listings by state, city, property type, price, "
            "bedrooms, bathrooms, toilets, and features such as furnished, pet friendly, parking, and utilities "
            "included. Radius and map-based search plus location analytics are available from the Silver plan. "
            "Tenants can save favourites to compare options later."
        ),
    },
    {
        "topic": "messaging_and_support",
        "keywords": ["support", "help", "contact", "message", "chat", "enquiry", "report", "complaint", "issue", "phone", "email"],
        "content": (
            "Communication and support: tenants and landlords communicate through secure in-app messaging and "
            "enquiries on each listing. Support options: phone +234 800 736 8347, email support@rentdirect.homes, "
            "and the Support Chat page. The Support page contains FAQs; the Issues page handles account, payment, "
            "technical, or rental workflow problems; the Complaint page is for urgent concerns such as suspected "
            "fraud, suspicious listings, conduct issues, or payment concerns. Feedback can also be sent via the "
            "Feedback page."
        ),
    },
    {
        "topic": "faqs",
        "keywords": ["faq", "question", "register", "sign up", "account", "profile", "listing", "enquiry"],
        "content": (
            "Frequently asked questions: "
            "Q: How long does verification take? A: Tenant and landlord verification typically takes 1-2 business "
            "days; property document verification may take longer. "
            "Q: Can a landlord list more than one property? A: Yes, verified landlords can manage multiple listings "
            "from one dashboard. "
            "Q: Do I need a subscription to rent a property? A: Yes — tenants need Silver or higher to contact "
            "landlords, apply, pay rent, and track rental progress. Bronze (free) covers browsing, verification, "
            "and building your profile. Landlords need Silver or higher to create listings. "
            "Q: How do I register as a tenant? A: Choose 'Find a home', select the tenant registration option, "
            "create an account, and verify your email with the one-time code. "
            "Q: How do I register as a landlord? A: Choose 'List a property', select landlord registration, create "
            "an account, and verify your email. "
            "Q: Why can I not create a listing yet? A: Landlords must complete identity verification before "
            "creating a property listing. "
            "Q: How do I find a property and contact a landlord? A: Use Search to filter listings, open a property "
            "to review details, and send an enquiry once eligible; complete tenant verification first. "
            "Q: Where can I track rent payments and rental progress? A: Billing shows payments and subscriptions; "
            "active bookings and milestones are on the dashboard and Rental Progress page. "
            "Q: How do I report a suspicious property or landlord? A: Use the Complaint page for urgent concerns or "
            "the Issues page for account and platform problems."
        ),
    },
]


def _entry_content(entry: dict) -> str:
    content = entry["content"]
    return content() if callable(content) else content


def site_content_for_topic(topic: str) -> dict:
    normalized = str(topic or "").strip().lower()
    if not normalized:
        return {
            "overview": PLATFORM_OVERVIEW,
            "topics": [entry["topic"] for entry in SITE_KNOWLEDGE],
        }
    for entry in SITE_KNOWLEDGE:
        if normalized == entry["topic"] or normalized in entry["keywords"] or entry["topic"] in normalized:
            return {"topic": entry["topic"], "content": _entry_content(entry)}
    for entry in SITE_KNOWLEDGE:
        if any(keyword in normalized for keyword in entry["keywords"]):
            return {"topic": entry["topic"], "content": _entry_content(entry)}
    return {
        "overview": PLATFORM_OVERVIEW,
        "topics": [entry["topic"] for entry in SITE_KNOWLEDGE],
    }


def site_content_for_text(text: str) -> str:
    """Keyword match used by the no-provider fallback. Returns matching content or ''."""
    normalized = str(text or "").lower()
    scored = []
    for entry in SITE_KNOWLEDGE:
        score = sum(1 for keyword in entry["keywords"] if keyword in normalized)
        if score:
            scored.append((score, _entry_content(entry)))
    if not scored:
        return ""
    scored.sort(key=lambda item: -item[0])
    return "\n\n".join(content for _score, content in scored[:2])
