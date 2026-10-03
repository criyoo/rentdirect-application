"""Multi-role identity helpers.

``AppUser.role`` remains the immutable legacy/default role. An authenticated
request may act under a different persona only when an ACTIVE ``UserRole``
membership exists for it; the validated role is then applied to the in-memory
user object (``user.role``/``user.active_role``) and is never persisted back to
``AppUser.role``. Accounts without any membership rows fall back to the legacy
role so pre-migration data and tests keep working.
"""

from __future__ import annotations

import copy
import uuid
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from .financial_constants import (
    IDENTITY_VERIFICATION_EXTRA_ATTEMPT_FEE,
    IDENTITY_VERIFICATION_FEE,
    IDENTITY_VERIFICATION_FREE_ATTEMPTS,
    MONEY_PRECISION,
)
from .models import (
    AgentProfile,
    AppUser,
    RoleAuditEvent,
    ServicePayment,
    TenantProfile,
    UserRole,
    VerificationRequest,
)
from .tenant_verification import normalize_tenant_verification_date, normalize_tenant_verification_profile

CUSTOMER_ROLES = {AppUser.Role.TENANT, AppUser.Role.LANDLORD, AppUser.Role.AGENT}
ACTIVE_ROLE_HEADER = "HTTP_X_RENTDIRECT_ROLE"
INACTIVE_ROLE_MESSAGE = "This role is not active for your account."


def _role_order(role: str) -> int:
    choices = list(AppUser.Role.values)
    return choices.index(role) if role in choices else len(choices)


def available_roles(user) -> list[str]:
    if user is None:
        return []
    # Admin is exclusive: it can never share an account with another persona,
    # even if stray membership rows exist.
    if user.role == AppUser.Role.ADMIN:
        return [AppUser.Role.ADMIN]

    memberships = list(
        UserRole.objects.filter(user_id=user.pk).values_list("role", "status")
    )
    if not memberships:
        roles = {user.role} if user.role else set()
    else:
        roles = {
            role
            for role, membership_status in memberships
            if membership_status == UserRole.Status.ACTIVE
        }
    roles &= CUSTOMER_ROLES
    return sorted(roles, key=_role_order)


def has_active_role(user, role: str) -> bool:
    role = str(role or "").strip().lower()
    if not role:
        return False
    return role in available_roles(user)


def active_role_membership(user, role: str | None = None):
    if user is None or not getattr(user, "pk", None):
        return None
    target = str(
        role or getattr(user, "active_role", None) or getattr(user, "role", "") or ""
    ).strip().lower()
    if not target:
        return None
    cache_key = f"_active_membership_{target}"
    if hasattr(user, cache_key):
        return getattr(user, cache_key)
    membership = (
        UserRole.objects.filter(
            user_id=user.pk,
            role=target,
            status=UserRole.Status.ACTIVE,
        )
        .first()
    )
    setattr(user, cache_key, membership)
    return membership


def apply_active_role(user, requested_role: str | None = None):
    """Validate and apply the request-scoped persona in memory.

    Raises ``PermissionDenied`` when ``requested_role`` is not an active role
    for the account. Returns the resolved role.
    """
    if user is None:
        return None
    requested = str(requested_role or "").strip().lower()
    roles = available_roles(user)
    if requested:
        if requested not in roles:
            raise PermissionDenied(INACTIVE_ROLE_MESSAGE)
        role = requested
    else:
        current = getattr(user, "role", "")
        role = current if current in roles or not roles else roles[0]
    # In-memory only: AppUser.role is never saved from this path.
    user.role = role
    user.active_role = role
    return role


def activate_customer_role(user, role: str):
    """Create a missing customer ``UserRole`` membership atomically.

    Suspended memberships are administrative suspensions and are never
    reactivated here. When an account has no membership rows at all and a
    different role is being added, the legacy/default customer role first gets
    an ACTIVE membership so the original role is preserved for
    programmatically-created or pre-backfill users.

    Returns ``(membership, activated)`` where ``activated`` is False when the
    membership already existed in the ACTIVE state.
    """
    role = str(role or "").strip().lower()
    if role not in CUSTOMER_ROLES or getattr(user, "role", None) == AppUser.Role.ADMIN:
        raise PermissionDenied(INACTIVE_ROLE_MESSAGE)
    with transaction.atomic():
        if role != user.role and not UserRole.objects.filter(user_id=user.pk).exists():
            legacy = UserRole.objects.create(
                user_id=user.pk, role=user.role, status=UserRole.Status.ACTIVE
            )
            setattr(user, f"_active_membership_{user.role}", legacy)
        membership = UserRole.objects.filter(user_id=user.pk, role=role).first()
        if membership is None:
            membership = UserRole.objects.create(
                user_id=user.pk, role=role, status=UserRole.Status.ACTIVE
            )
            activated = True
        elif membership.status != UserRole.Status.ACTIVE:
            raise PermissionDenied(INACTIVE_ROLE_MESSAGE)
        else:
            activated = False
        setattr(user, f"_active_membership_{role}", membership)
    return membership, activated


def role_bound_user(user, role: str):
    """Return a detached copy of ``user`` bound to ``role`` (validated via
    ``apply_active_role``) for role-scoped reads such as subscription checks,
    without mutating or persisting the original user's default role."""
    bound = copy.copy(user)
    apply_active_role(bound, role)
    return bound


def role_audit_context(request) -> dict:
    forwarded_for = str(request.META.get("HTTP_X_FORWARDED_FOR") or "")
    ip_address = forwarded_for.split(",")[0].strip() if forwarded_for else request.META.get("REMOTE_ADDR", "")
    return {
        "ip_address": ip_address or None,
        "user_agent": str(request.META.get("HTTP_USER_AGENT") or "")[:512],
    }


def record_role_event(user, role: str, event: str, request=None) -> RoleAuditEvent:
    context = role_audit_context(request) if request is not None else {}
    return RoleAuditEvent.objects.create(user=user, role=role, event=event, **context)


def users_with_role(queryset, role: str):
    return queryset.filter(active_membership_or_legacy_q(role)).distinct()


IDENTITY_FIELDS = (
    "first_name",
    "middle_name",
    "last_name",
    "date_of_birth",
    "gender",
    "nationality",
    "state_of_origin",
    "lga",
    "mobile",
    "whatsapp_number",
    "country_of_birth",
    "email",
    "nin_number",
    "bvn_number",
    "city",
    "state_of_residence",
    "residential_address",
    "employment_status",
)


def _merge_identity(target: dict, source: dict) -> None:
    for key, value in source.items():
        if key not in IDENTITY_FIELDS:
            continue
        text = str(value or "").strip()
        if text and not str(target.get(key) or "").strip():
            target[key] = normalize_tenant_verification_date(text) if key == "date_of_birth" else text


def _identity_verified(user, role: str) -> bool:
    return VerificationRequest.objects.filter(
        user_id=user.pk,
        role=role,
        identity_verification_status__in=(
            VerificationRequest.VerificationProgressStatus.AWAITING_PAYMENT,
            VerificationRequest.VerificationProgressStatus.VERIFIED,
        ),
    ).exists()


def verified_identity_data(user) -> dict:
    """Canonical identity fields from personas already verified for this identity.

    Keys are canonical (``lga``, ``nin_number``, ``bvn_number``, ...); callers
    map them onto each persona's storage shape. Only verified sources are
    merged, so the result can be trusted for skip-reverification checks.
    """
    data: dict = {}
    if user is None or not getattr(user, "pk", None):
        return data

    agent_profile = AgentProfile.objects.filter(user_id=user.pk).first()
    if agent_profile and agent_profile.verification_status == AgentProfile.VerificationStatus.VERIFIED:
        _merge_identity(
            data,
            {
                "first_name": agent_profile.first_name,
                "middle_name": agent_profile.middle_name,
                "last_name": agent_profile.last_name,
                "date_of_birth": agent_profile.date_of_birth,
                "gender": agent_profile.gender,
                "nationality": agent_profile.nationality,
                "state_of_origin": agent_profile.state_of_origin,
                "lga": agent_profile.lga_of_origin,
                "mobile": agent_profile.mobile,
                "whatsapp_number": agent_profile.whatsapp_number,
                "country_of_birth": agent_profile.country_of_birth,
                "email": user.email,
                "nin_number": agent_profile.nin_number,
                "bvn_number": agent_profile.bvn_number,
                "city": agent_profile.city_of_residence,
                "state_of_residence": agent_profile.state_of_residence,
                "residential_address": agent_profile.residential_address,
            },
        )

    if (
        user.landlord_verification_type == AppUser.LandlordVerificationType.INDIVIDUAL
        and _identity_verified(user, AppUser.Role.LANDLORD)
    ):
        profile = user.landlord_verification_profile if isinstance(user.landlord_verification_profile, dict) else {}
        residence = profile.get("residential_information")
        residence = residence if isinstance(residence, dict) else {}
        _merge_identity(
            data,
            {
                "first_name": profile.get("first_name"),
                "middle_name": profile.get("middle_name"),
                "last_name": profile.get("last_name"),
                "date_of_birth": profile.get("date_of_birth"),
                "gender": profile.get("gender"),
                "nationality": profile.get("nationality"),
                "state_of_origin": profile.get("state_of_origin"),
                "lga": profile.get("lga_of_origin"),
                "mobile": profile.get("contact_number") or user.mobile,
                "whatsapp_number": profile.get("whatsapp_number"),
                "country_of_birth": profile.get("country_of_birth"),
                "email": profile.get("email"),
                "nin_number": profile.get("nin") or user.nin_number,
                "bvn_number": profile.get("bvn") or user.bvn_number,
                "city": residence.get("city"),
                "state_of_residence": residence.get("state"),
                "residential_address": profile.get("residential_address") or residence.get("address"),
                "employment_status": profile.get("employment_status"),
            },
        )

    if _identity_verified(user, AppUser.Role.TENANT):
        _merge_identity(data, normalize_tenant_verification_profile(user.tenant_verification_profile, user))
        tenant_profile = TenantProfile.objects.filter(user_id=user.pk).first()
        if tenant_profile is not None:
            _merge_identity(
                data,
                {
                    "city": tenant_profile.residence_city,
                    "state_of_residence": tenant_profile.residence_state,
                    "residential_address": tenant_profile.residence_address,
                    "employment_status": tenant_profile.employment_status,
                },
            )

    return data


def prefill_identity_data(user) -> dict:
    """Verified identity plus user-held credentials for form prefill.

    ``AppUser.nin_number``/``bvn_number`` are only persisted after a successful
    provider verification, so they are safe defaults even without a verified
    persona record.
    """
    data = verified_identity_data(user)
    if user is not None:
        _merge_identity(
            data,
            {
                "nin_number": getattr(user, "nin_number", ""),
                "bvn_number": getattr(user, "bvn_number", ""),
                "mobile": getattr(user, "mobile", ""),
                "whatsapp_number": getattr(user, "whatsapp_number", ""),
                "state_of_origin": getattr(user, "state_of_origin", ""),
                "email": getattr(user, "email", ""),
            },
        )
    return data


def verified_identity_matches(user, submitted: dict, credential_fields=("nin_number",)) -> bool:
    """True when ``submitted`` identity data matches an already-verified persona.

    Every required credential must be present and equal; all other fields
    present non-empty in both are compared (dates normalized). Used to skip a
    repeat provider lookup when the same credentials are re-submitted under a
    different persona.
    """
    snapshot = verified_identity_data(user)
    if not snapshot:
        return False
    for field_name in credential_fields:
        expected = str(snapshot.get(field_name) or "").strip()
        provided = str(submitted.get(field_name) or "").strip()
        if not expected or not provided or expected.lower() != provided.lower():
            return False
    compared = 0
    for key, value in submitted.items():
        provided = str(value or "").strip()
        expected = str(snapshot.get(key) or "").strip()
        if not provided or not expected:
            continue
        compared += 1
        if key == "date_of_birth":
            if normalize_tenant_verification_date(provided) != normalize_tenant_verification_date(expected):
                return False
        elif provided.lower() != expected.lower():
            return False
    return compared > 0


def _parse_identity_date(value):
    normalized = normalize_tenant_verification_date(value)
    try:
        return date.fromisoformat(normalized) if normalized else None
    except ValueError:
        return None


AGENT_IDENTITY_FIELD_MAP = {
    "first_name": "first_name",
    "middle_name": "middle_name",
    "last_name": "last_name",
    "date_of_birth": "date_of_birth",
    "gender": "gender",
    "nationality": "nationality",
    "state_of_origin": "state_of_origin",
    "lga": "lga_of_origin",
    "mobile": "mobile",
    "whatsapp_number": "whatsapp_number",
    "country_of_birth": "country_of_birth",
    "city": "city_of_residence",
    "state_of_residence": "state_of_residence",
    "residential_address": "residential_address",
    "nin_number": "nin_number",
    "bvn_number": "bvn_number",
}

LANDLORD_IDENTITY_FIELD_MAP = {
    "first_name": "first_name",
    "middle_name": "middle_name",
    "last_name": "last_name",
    "date_of_birth": "date_of_birth",
    "gender": "gender",
    "nationality": "nationality",
    "state_of_origin": "state_of_origin",
    "lga": "lga_of_origin",
    "mobile": "contact_number",
    "whatsapp_number": "whatsapp_number",
    "country_of_birth": "country_of_birth",
    "email": "email",
    "nin_number": "nin",
    "bvn_number": "bvn",
    "residential_address": "residential_address",
    "employment_status": "employment_status",
}


def prefill_agent_profile(user, profile: AgentProfile) -> bool:
    """Copy verified identity fields into empty ``AgentProfile`` fields."""
    if profile is None or profile.verification_status == AgentProfile.VerificationStatus.VERIFIED:
        return False
    missing = [
        field_name
        for field_name in AGENT_IDENTITY_FIELD_MAP.values()
        if not str(getattr(profile, field_name, "") or "").strip()
    ]
    if not missing:
        return False
    data = prefill_identity_data(user)
    if not data:
        return False

    update_fields: list[str] = []
    for source_key, field_name in AGENT_IDENTITY_FIELD_MAP.items():
        if field_name not in missing:
            continue
        value = data.get(source_key)
        if not value:
            continue
        if field_name == "date_of_birth":
            parsed = _parse_identity_date(value)
            if parsed is None:
                continue
            profile.date_of_birth = parsed
        else:
            setattr(profile, field_name, str(value).strip())
        update_fields.append(field_name)

    if not update_fields:
        return False

    from .serializers import sync_agent_profile_status

    previous_status = profile.verification_status
    sync_agent_profile_status(profile)
    if profile.verification_status != previous_status:
        update_fields.append("verification_status")
    update_fields.append("updated_at")
    profile.save(update_fields=update_fields)
    return True


def prefill_tenant_verification_profile(user) -> bool:
    from .tenant_verification import TENANT_VERIFICATION_PROFILE_FIELDS

    profile = dict(user.tenant_verification_profile or {})
    missing = [key for key in TENANT_VERIFICATION_PROFILE_FIELDS if not str(profile.get(key) or "").strip()]
    if not missing:
        return False
    data = prefill_identity_data(user)
    if not data:
        return False

    changed = False
    for key in missing:
        value = data.get(key)
        if value:
            profile[key] = normalize_tenant_verification_date(value) if key == "date_of_birth" else str(value).strip()
            changed = True
    if not changed:
        return False
    user.tenant_verification_profile = normalize_tenant_verification_profile(profile, user)
    user.save(update_fields=["tenant_verification_profile", "updated_at"])
    return True


def prefill_landlord_verification_profile(user) -> bool:
    if user.landlord_verification_type == AppUser.LandlordVerificationType.CORPORATE:
        return False
    profile = dict(user.landlord_verification_profile or {})
    missing = [
        key
        for key in LANDLORD_IDENTITY_FIELD_MAP.values()
        if not str(profile.get(key) or "").strip()
    ]
    if not missing:
        return False
    data = prefill_identity_data(user)
    if not data:
        return False

    changed = False
    for source_key, key in LANDLORD_IDENTITY_FIELD_MAP.items():
        if key not in missing:
            continue
        value = data.get(source_key)
        if not value:
            continue
        profile[key] = normalize_tenant_verification_date(value) if key == "date_of_birth" else str(value).strip()
        changed = True

    residence = dict(profile.get("residential_information") or {})
    if data.get("city") and not str(residence.get("city") or "").strip():
        residence["city"] = str(data["city"]).strip()
        changed = True
    if data.get("state_of_residence") and not str(residence.get("state") or "").strip():
        residence["state"] = str(data["state_of_residence"]).strip()
        changed = True
    if data.get("residential_address") and not str(residence.get("address") or "").strip():
        residence["address"] = str(data["residential_address"]).strip()
        changed = True
    if residence:
        profile["residential_information"] = residence

    if not changed:
        return False
    update_fields = ["landlord_verification_profile", "updated_at"]
    user.landlord_verification_profile = profile
    if not user.landlord_verification_type:
        user.landlord_verification_type = AppUser.LandlordVerificationType.INDIVIDUAL
        update_fields.append("landlord_verification_type")
    user.save(update_fields=update_fields)
    return True


IDENTITY_CREDENTIAL_FIELDS = ("nin_number", "bvn_number")

VERIFICATION_PAYMENT_PURPOSES = {
    AppUser.Role.TENANT: ServicePayment.Purpose.TENANT_VERIFICATION,
    AppUser.Role.LANDLORD: ServicePayment.Purpose.LANDLORD_VERIFICATION,
    AppUser.Role.AGENT: ServicePayment.Purpose.AGENT_VERIFICATION,
}

# Provider-attempt counters per role (the agent profile tracks its own).
_VERIFICATION_ATTEMPT_FIELD = {
    AppUser.Role.TENANT: "tenant_verification_attempts",
    AppUser.Role.LANDLORD: "landlord_verification_attempts",
}


def verified_credentials(user) -> set[str]:
    """Credential types verified under any persona of this identity."""
    data = verified_identity_data(user)
    return {
        field_name
        for field_name in IDENTITY_CREDENTIAL_FIELDS
        if str(data.get(field_name) or "").strip()
    }


def identity_credentials_verified(user, role: str) -> bool:
    """True when every credential the role requires (NIN + BVN) is already
    verified under this identity, so no provider call or fee is needed."""
    role = str(role or "").strip().lower()
    return role in CUSTOMER_ROLES and set(IDENTITY_CREDENTIAL_FIELDS) <= verified_credentials(user)


def identity_credentials_linked_to_other_user(user, nin_number: str = "", bvn_number: str = "") -> bool:
    """True when a submitted NIN or BVN is already linked to a different
    account — blocks referral/identity farming through extra email accounts.

    A credential only counts as "linked" when its holder actually passed
    identity verification (a VERIFIED ``VerificationRequest`` for any of
    their personas). Unverified copies of ``nin_number``/``bvn_number`` —
    e.g. an agent profile PATCH syncing to ``AppUser`` — must not let anyone
    squat on another person's credentials.
    """
    credentials = {
        str(value or "").strip().lower()
        for value in (nin_number, bvn_number)
        if str(value or "").strip()
    }
    if not credentials:
        return False
    user_pk = getattr(user, "pk", None)
    credential_q = Q(nin_number__in=credentials) | Q(bvn_number__in=credentials)
    verified_holder_ids = VerificationRequest.objects.filter(
        identity_verification_status__in=(
            VerificationRequest.VerificationProgressStatus.AWAITING_PAYMENT,
            VerificationRequest.VerificationProgressStatus.VERIFIED,
        )
    ).values("user_id")
    return (
        AppUser.objects.filter(credential_q, pk__in=verified_holder_ids)
        .exclude(pk=user_pk)
        .exists()
        or AgentProfile.objects.filter(credential_q, user_id__in=verified_holder_ids)
        .exclude(user_id=user_pk)
        .exists()
    )


def require_unique_identity_credentials(user, nin_number: str = "", bvn_number: str = "") -> None:
    """Reject a verification whose NIN/BVN already belongs to another user."""
    if identity_credentials_linked_to_other_user(user, nin_number, bvn_number):
        raise ValidationError(
            {"nin_number": "This NIN or BVN is already linked to another account."}
        )


def identity_verification_attempts_used(user, role: str) -> int:
    role = str(role or "").strip().lower()
    if role == AppUser.Role.AGENT:
        profile = AgentProfile.objects.filter(user_id=user.pk).first()
        return profile.verification_attempts if profile else 0
    field_name = _VERIFICATION_ATTEMPT_FIELD.get(role)
    return getattr(user, field_name, 0) if field_name else 0


def track_identity_verification_attempt(user, role: str) -> None:
    """Consume one paid verification attempt (tenant/landlord counter fields;
    the agent path increments ``AgentProfile.verification_attempts`` itself)."""
    field_name = _VERIFICATION_ATTEMPT_FIELD.get(str(role or "").strip().lower())
    if field_name is None:
        return
    setattr(user, field_name, (getattr(user, field_name, 0) or 0) + 1)
    user.save(update_fields=[field_name, "updated_at"])


def identity_verification_extra_attempt_fee(user, role) -> Decimal:
    """₦100 surcharge for each provider attempt beyond the three free ones."""
    extra_attempts = max(
        0, identity_verification_attempts_used(user, role) - IDENTITY_VERIFICATION_FREE_ATTEMPTS
    )
    return (IDENTITY_VERIFICATION_EXTRA_ATTEMPT_FEE * extra_attempts).quantize(MONEY_PRECISION)


def identity_verification_fee_amount(user, role) -> Decimal:
    """The ₦500 verification fee plus any extra-attempt surcharges."""
    return (
        IDENTITY_VERIFICATION_FEE + identity_verification_extra_attempt_fee(user, role)
    ).quantize(MONEY_PRECISION)


def completed_identity_verification_payment(user, role) -> bool:
    purpose = VERIFICATION_PAYMENT_PURPOSES.get(str(role or "").strip().lower())
    return bool(purpose) and ServicePayment.objects.filter(
        user_id=user.pk, purpose=purpose, status=ServicePayment.Status.COMPLETED
    ).exists()


def pending_identity_verification_payment(user, role):
    purpose = VERIFICATION_PAYMENT_PURPOSES.get(str(role or "").strip().lower())
    if purpose is None:
        return None
    return (
        ServicePayment.objects.filter(
            user_id=user.pk, purpose=purpose, status=ServicePayment.Status.PENDING
        )
        .order_by("-created_at")
        .first()
    )


def ensure_identity_verification_payment(user, role: str) -> ServicePayment | None:
    """Get-or-create the pending verification payment, keeping the amount in
    sync with the ₦500 fee plus any extra-attempt surcharges."""
    role = str(role or "").strip().lower()
    purpose = VERIFICATION_PAYMENT_PURPOSES.get(role)
    if purpose is None:
        return None
    amount = identity_verification_fee_amount(user, role)
    payment = pending_identity_verification_payment(user, role)
    if payment is None:
        return ServicePayment.objects.create(
            user=user,
            purpose=purpose,
            amount=amount,
            transaction_id=f"SVC{uuid.uuid4().hex[:20].upper()}",
        )
    if payment.amount != amount:
        payment.amount = amount
        payment.save(update_fields=["amount", "updated_at"])
    return payment


def identity_verification_fee_due(user, role: str) -> bool:
    """True when a verification passed but its payment is still outstanding."""
    return VerificationRequest.objects.filter(
        user_id=user.pk,
        role=str(role or "").strip().lower(),
        identity_verification_status=VerificationRequest.VerificationProgressStatus.AWAITING_PAYMENT,
    ).exists()


def identity_verification_payment_required(user, role: str) -> bool:
    """Whether the UI should route the user to the verification payment page."""
    role = str(role or "").strip().lower()
    if role not in VERIFICATION_PAYMENT_PURPOSES or user.is_verified_for_role(role):
        return False
    return (
        pending_identity_verification_payment(user, role) is not None
        or identity_verification_fee_due(user, role)
    )


def finalize_identity_verification(user, role) -> bool:
    """Mark an awaiting-payment identity verification verified after payment."""
    role = str(role or "").strip().lower()
    verification = (
        VerificationRequest.objects.filter(
            user_id=user.pk,
            role=role,
            identity_verification_status=VerificationRequest.VerificationProgressStatus.AWAITING_PAYMENT,
        )
        .order_by("-submitted_at")
        .first()
    )
    if verification is None:
        return False
    now = timezone.now()
    verification.identity_verification_status = VerificationRequest.VerificationProgressStatus.VERIFIED
    verification.status = VerificationRequest.Status.APPROVED
    verification.reviewed_at = now
    verification.save(
        update_fields=["identity_verification_status", "status", "reviewed_at"]
    )
    if role == AppUser.Role.TENANT:
        TenantProfile.objects.filter(user_id=user.pk).exclude(
            status=TenantProfile.Status.REJECTED
        ).update(status=TenantProfile.Status.APPROVED)
    elif role == AppUser.Role.AGENT:
        profile = AgentProfile.objects.filter(user_id=user.pk).first()
        if profile and profile.verification_status != AgentProfile.VerificationStatus.VERIFIED:
            profile.verification_status = AgentProfile.VerificationStatus.VERIFIED
            profile.verified_at = now
            profile.save(update_fields=["verification_status", "verified_at", "updated_at"])
    return True


def _persona_credential_values(user, role: str) -> tuple[str, str]:
    """The (nin, bvn) a persona has on record, mapped to canonical fields."""
    if role == AppUser.Role.AGENT:
        profile = AgentProfile.objects.filter(user_id=user.pk).first()
        if profile is None:
            return "", ""
        return str(profile.nin_number or ""), str(profile.bvn_number or "")
    if role == AppUser.Role.LANDLORD:
        profile = user.landlord_verification_profile if isinstance(user.landlord_verification_profile, dict) else {}
        return str(profile.get("nin") or ""), str(profile.get("bvn") or "")
    if role == AppUser.Role.TENANT:
        profile = normalize_tenant_verification_profile(user.tenant_verification_profile, user)
        return str(profile.get("nin_number") or ""), str(profile.get("bvn_number") or "")
    return "", ""


def auto_verify_role_identity(user, role: str) -> bool:
    """Mark a persona's identity verified without a provider call or fee when
    the identity's NIN+BVN are already verified under another persona.

    Only applies when the persona's own credential fields are empty (they get
    prefilled from the verified identity) or match it exactly — a persona that
    carries different credentials must go through provider verification."""
    role = str(role or "").strip().lower()
    if user is None or not getattr(user, "pk", None):
        return False
    if role not in CUSTOMER_ROLES or not identity_credentials_verified(user, role):
        return False
    if role == AppUser.Role.LANDLORD and user.landlord_verification_type == AppUser.LandlordVerificationType.CORPORATE:
        # Corporate landlord identity is CAC-based, not NIN/BVN.
        return False

    identity = verified_identity_data(user)
    persona_nin, persona_bvn = _persona_credential_values(user, role)
    for persona_value, field_name in ((persona_nin, "nin_number"), (persona_bvn, "bvn_number")):
        persona_value = persona_value.strip()
        verified_value = str(identity.get(field_name) or "").strip()
        if persona_value and verified_value and persona_value.lower() != verified_value.lower():
            return False

    verified_at = timezone.now()
    changed = False

    if role == AppUser.Role.AGENT:
        profile, _ = AgentProfile.objects.get_or_create(user=user)
        if profile.verification_status not in (
            AgentProfile.VerificationStatus.VERIFIED,
            AgentProfile.VerificationStatus.PAYMENT_REQUIRED,
        ):
            profile.verification_status = AgentProfile.VerificationStatus.PAYMENT_REQUIRED
            profile.save(update_fields=["verification_status", "updated_at"])
            changed = True

    verification = (
        VerificationRequest.objects.filter(user=user, role=role)
        .order_by("-submitted_at")
        .first()
    )
    if verification is None:
        verification = VerificationRequest.objects.create(
            user=user,
            role=role,
            request_type=VerificationRequest.RequestType.IDENTIFICATION,
        )
    # An admin rejection on this persona is respected; it is never auto-approved.
    # The persona activates only after the verification fee is paid, so the
    # request is parked at AWAITING_PAYMENT rather than VERIFIED.
    if verification.status != VerificationRequest.Status.REJECTED and (
        verification.identity_verification_status
        not in (
            VerificationRequest.VerificationProgressStatus.AWAITING_PAYMENT,
            VerificationRequest.VerificationProgressStatus.VERIFIED,
        )
    ):
        if not verification.request_type:
            verification.request_type = VerificationRequest.RequestType.IDENTIFICATION
        verification.identity_verification_status = (
            VerificationRequest.VerificationProgressStatus.AWAITING_PAYMENT
        )
        verification.verification_method = VerificationRequest.Method.AUTOMATED
        # Stay PENDING so is_verified_for_role does not count the unpaid
        # persona as verified; payment completion approves it.
        verification.status = VerificationRequest.Status.PENDING
        verification.reviewed_at = verified_at
        ensure_identity_verification_payment(user, role)
        verification.save(
            update_fields=[
                "request_type",
                "identity_verification_status",
                "verification_method",
                "status",
                "reviewed_at",
            ]
        )
        changed = True

    user_updates: list[str] = []
    for field_name in IDENTITY_CREDENTIAL_FIELDS:
        value = str(identity.get(field_name) or "").strip()
        if value and getattr(user, field_name, "") != value:
            setattr(user, field_name, value)
            user_updates.append(field_name)
    if user_updates:
        user_updates.append("updated_at")
        user.save(update_fields=user_updates)
        changed = True
    return changed


def prefill_role_identity(user, role: str) -> bool:
    """Prefill a persona's verification/profile fields from verified identity
    and mark the persona verified when its required credentials already are."""
    role = str(role or "").strip().lower()
    if user is None:
        return False
    if role == AppUser.Role.TENANT:
        prefilled = prefill_tenant_verification_profile(user)
    elif role == AppUser.Role.LANDLORD:
        prefilled = prefill_landlord_verification_profile(user)
    elif role == AppUser.Role.AGENT:
        profile = AgentProfile.objects.filter(user_id=user.pk).first()
        prefilled = prefill_agent_profile(user, profile)
    else:
        return False
    auto_verified = auto_verify_role_identity(user, role)
    return prefilled or auto_verified


def active_membership_or_legacy_q(role: str, prefix: str = "") -> Q:
    """Match users holding an ACTIVE membership for ``role``.

    Users with no membership rows at all match on their legacy ``AppUser.role``
    so pre-migration accounts keep working. Users whose only membership for the
    role is suspended do not match.
    """
    return Q(
        **{
            f"{prefix}role_memberships__role": role,
            f"{prefix}role_memberships__status": UserRole.Status.ACTIVE,
        }
    ) | (
        Q(**{f"{prefix}role": role})
        & Q(**{f"{prefix}role_memberships__isnull": True})
    )
