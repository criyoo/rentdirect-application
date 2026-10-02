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

from django.db import transaction
from django.db.models import Q
from rest_framework.exceptions import PermissionDenied

from .models import AppUser, RoleAuditEvent, UserRole

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
