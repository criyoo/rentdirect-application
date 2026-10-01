"""Property Inspection Officer (PIO) referral helpers.

Each agent profile owns a unique 8-character referral code. When a new PIO
registers with an existing PIO's code and completes identity verification, the
referrer earns a per-inspection bonus for every property the referred PIO
inspects, capped per referral.
"""

from __future__ import annotations

import secrets
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db.models import Count, Q, Sum

REFERRAL_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
REFERRAL_CODE_LENGTH = 8
REFERRAL_TREE_MAX_DEPTH = 5


def _decimal_setting(name: str, default: str) -> Decimal:
    try:
        return Decimal(str(getattr(settings, name, default) or default))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def referral_earning_amount() -> Decimal:
    return _decimal_setting("AGENT_REFERRAL_EARNING_NGN", "2000.00")


def referral_earning_cap() -> Decimal:
    return _decimal_setting("AGENT_REFERRAL_MAX_PER_REFERRAL_NGN", "10000.00")


def generate_referral_code() -> str:
    return "".join(secrets.choice(REFERRAL_CODE_ALPHABET) for _ in range(REFERRAL_CODE_LENGTH))


def generate_unique_referral_code() -> str:
    from .models import AgentProfile

    for _attempt in range(25):
        code = generate_referral_code()
        if not AgentProfile.objects.filter(referral_code=code).exists():
            return code
    raise RuntimeError("Could not allocate a unique PIO referral code.")


def resolve_referrer(code: str):
    """Return the AppUser that owns ``code`` or ``None``."""
    from .models import AgentProfile, AppUser

    normalized = (code or "").strip().upper()
    if not normalized:
        return None
    profile = (
        AgentProfile.objects.filter(
            referral_code__iexact=normalized,
            user__role=AppUser.Role.AGENT,
        )
        .select_related("user")
        .first()
    )
    return profile.user if profile else None


def award_referral_earning(inspection):
    """Award the referrer of ``inspection.agent`` for a submitted inspection.

    The referrer earns ``AGENT_REFERRAL_EARNING_NGN`` per submitted inspection,
    capped at ``AGENT_REFERRAL_MAX_PER_REFERRAL_NGN`` per referred PIO. Returns
    the created ``AgentReferralEarning`` or ``None``.
    """
    from .models import AgentProfile, AgentReferralEarning

    profile = (
        AgentProfile.objects.filter(user_id=inspection.agent_id)
        .only("verification_status", "referred_by")
        .first()
    )
    if not profile or not profile.referred_by_id:
        return None
    if profile.verification_status != AgentProfile.VerificationStatus.VERIFIED:
        return None

    earned = AgentReferralEarning.objects.filter(
        referrer_id=profile.referred_by_id,
        referred_id=inspection.agent_id,
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    remaining = referral_earning_cap() - earned
    if remaining <= 0:
        return None

    earning, _created = AgentReferralEarning.objects.get_or_create(
        inspection=inspection,
        defaults={
            "referrer_id": profile.referred_by_id,
            "referred_id": inspection.agent_id,
            "amount": min(referral_earning_amount(), remaining),
        },
    )
    return earning


def build_referral_tree(user) -> dict:
    """Referral payload for a PIO dashboard: own code, tree and earnings."""
    from .models import AgentProfile, AgentReferralEarning, AppUser, PropertyInspection

    profile, _created = AgentProfile.objects.get_or_create(
        user=user,
        defaults={"first_name": "", "last_name": ""},
    )
    if not profile.referral_code:
        profile.referral_code = generate_unique_referral_code()
        profile.save(update_fields=["referral_code", "updated_at"])

    referred_profiles = list(
        AgentProfile.objects.filter(
            user__role=AppUser.Role.AGENT,
            referred_by__isnull=False,
        )
        .select_related("user")
    )
    children_map: dict = defaultdict(list)
    for child in referred_profiles:
        children_map[child.referred_by_id].append(child)
    profiles_by_user_id = {p.user_id: p for p in referred_profiles}
    profiles_by_user_id[user.id] = profile

    user_ids = set(profiles_by_user_id)
    counts = {
        row["agent_id"]: row["total"]
        for row in PropertyInspection.objects.filter(
            agent_id__in=user_ids,
            status=PropertyInspection.Status.SUBMITTED,
        )
        .values("agent_id")
        .annotate(total=Count("id"))
    }

    earnings_by_referred = {
        row["referred"]: row["total"]
        for row in AgentReferralEarning.objects.filter(referrer=user)
        .values("referred")
        .annotate(total=Sum("amount"))
    }

    def node(node_user, depth: int, seen: set) -> dict:
        node_profile = profiles_by_user_id.get(node_user.id)
        entry = {
            "id": str(node_user.id),
            "name": node_user.name,
            "profile_photo_url": getattr(node_user, "profile_photo_url", None),
            "referral_code": node_profile.referral_code if node_profile else "",
            "is_verified": bool(
                node_profile
                and node_profile.verification_status == AgentProfile.VerificationStatus.VERIFIED
            ),
            "properties_inspected": int(counts.get(node_user.id, 0)),
            "earned_from_referral": str(earnings_by_referred.get(node_user.id, Decimal("0"))),
            "children": [],
        }
        if depth >= REFERRAL_TREE_MAX_DEPTH:
            return entry
        seen = seen | {node_user.id}
        for child_profile in children_map.get(node_user.id, []):
            child_user = child_profile.user
            if child_user.id in seen:
                continue
            entry["children"].append(node(child_user, depth + 1, seen))
        return entry

    earnings = list(
        AgentReferralEarning.objects.filter(referrer=user)
        .select_related("referred", "inspection")
        .order_by("-created_at")
    )
    totals = AgentReferralEarning.objects.filter(referrer=user).aggregate(
        total=Sum("amount"),
        paid=Sum(
            "amount",
            filter=Q(payout_status=AgentReferralEarning.PayoutStatus.PAID),
        ),
    )

    referrer = profile.referred_by
    return {
        "referral_code": profile.referral_code,
        "referred_by": (
            {
                "id": str(referrer.id),
                "name": referrer.name,
                "profile_photo_url": getattr(referrer, "profile_photo_url", None),
            }
            if referrer
            else None
        ),
        "metrics": {
            "total_referrals": len(children_map.get(user.id, [])),
            "total_referral_earned": str(totals["total"] or Decimal("0")),
            "total_referral_paid": str(totals["paid"] or Decimal("0")),
            "referral_earning_per_inspection": str(referral_earning_amount()),
            "referral_earning_cap": str(referral_earning_cap()),
        },
        "earnings": [
            {
                "id": str(earning.id),
                "referred_name": earning.referred.name,
                "amount": str(earning.amount),
                "payout_status": earning.payout_status,
                "created_at": earning.created_at.isoformat(),
            }
            for earning in earnings[:50]
        ],
        "tree": node(user, 0, {user.id}),
    }
