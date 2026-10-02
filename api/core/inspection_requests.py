"""In-person inspection request routing for Property Inspection Officers.

When a listing requests physical verification, the nearest verified PIOs are
notified (email + WhatsApp) and get 24 hours to accept. Acceptance claims the
inspection first-come-first-served; other pending requests are then marked
"taken". The accepting PIO has 48 hours to submit the report before the
inspection is released and re-offered through the same process.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


def accept_window_hours() -> int:
    return int(getattr(settings, "INSPECTION_REQUEST_ACCEPT_WINDOW_HOURS", 24) or 24)


def submission_deadline_hours() -> int:
    return int(getattr(settings, "INSPECTION_SUBMISSION_DEADLINE_HOURS", 48) or 48)


def inspection_submission_deadline(inspection) -> object:
    return inspection.claimed_at + timedelta(hours=submission_deadline_hours())


def _eligible_agents():
    from .models import AgentProfile, AppUser, ServicePayment
    from .roles import active_membership_or_legacy_q

    paid_agent_ids = ServicePayment.objects.filter(
        purpose=ServicePayment.Purpose.AGENT_VERIFICATION,
        status=ServicePayment.Status.COMPLETED,
    ).values_list("user_id", flat=True)
    return (
        AppUser.objects.filter(id__in=paid_agent_ids)
        .filter(active_membership_or_legacy_q(AppUser.Role.AGENT))
        .select_related("agent_profile")
        .exclude(agent_profile__isnull=True)
        .exclude(
            agent_profile__verification_status__in=[
                AgentProfile.VerificationStatus.INCOMPLETE,
                AgentProfile.VerificationStatus.PAYMENT_REQUIRED,
                AgentProfile.VerificationStatus.PENDING,
                AgentProfile.VerificationStatus.REJECTED,
            ]
        )
        .distinct()
    )


def _conflicted_agent_ids(listing) -> set:
    """PIOs conflicted out of inspecting this listing: its landlord or any
    user holding a booking on it."""
    from .models import Booking

    conflicted = {listing.landlord_id}
    conflicted.update(
        Booking.objects.filter(listing=listing).values_list("tenant_id", flat=True)
    )
    return conflicted


def nearest_agents_for_listing(listing):
    """Return verified PIOs closest to the listing: same city, then same state,
    then every eligible PIO so the listing is never left unoffered."""
    conflicted = _conflicted_agent_ids(listing)
    agents = _eligible_agents().exclude(id__in=conflicted)
    city = (listing.city or "").strip()
    state = (listing.state or "").strip()

    if city:
        matches = agents.filter(agent_profile__city__iexact=city)
        if matches.exists():
            return list(matches)
    if state:
        matches = agents.filter(agent_profile__state_of_origin__iexact=state)
        if matches.exists():
            return list(matches)
    return list(agents)


def notify_agents_for_listing(listing, *, exclude_agent_ids=(), round_number: int = 1):
    """Create inspection requests for the nearest PIOs and notify them.

    Skips agents that already hold an active (pending, unexpired) or accepted
    request for this listing.
    """
    from .models import InspectionRequest
    from .notifications import send_inspection_request_notification

    now = timezone.now()
    exclude = set(exclude_agent_ids or ())
    active_agent_ids = set(
        InspectionRequest.objects.filter(
            listing=listing,
            status__in=[InspectionRequest.Status.PENDING, InspectionRequest.Status.ACCEPTED],
            expires_at__gt=now,
        ).values_list("agent_id", flat=True)
    ) | set(
        InspectionRequest.objects.filter(
            listing=listing, status=InspectionRequest.Status.ACCEPTED
        ).values_list("agent_id", flat=True)
    )

    created = []
    for agent in nearest_agents_for_listing(listing):
        if agent.id in exclude or agent.id in active_agent_ids:
            continue
        request_obj = InspectionRequest.objects.create(
            listing=listing,
            agent=agent,
            round=round_number,
            expires_at=now + timedelta(hours=accept_window_hours()),
        )
        channels = send_inspection_request_notification(agent, listing, request_obj)
        if channels:
            request_obj.notified_channels = channels
            request_obj.save(update_fields=["notified_channels", "updated_at"])
        created.append(request_obj)
    return created


def mark_requests_resolved(listing, *, accepted_agent):
    """Accepted PIO's request -> accepted; every other pending request -> taken."""
    from .models import InspectionRequest

    now = timezone.now()
    InspectionRequest.objects.filter(
        listing=listing, agent=accepted_agent, status=InspectionRequest.Status.PENDING
    ).update(status=InspectionRequest.Status.ACCEPTED, accepted_at=now, updated_at=now)
    InspectionRequest.objects.filter(
        listing=listing, status=InspectionRequest.Status.PENDING
    ).exclude(agent=accepted_agent).update(status=InspectionRequest.Status.TAKEN, updated_at=now)


def active_pending_request(listing, agent):
    from .models import InspectionRequest

    return (
        InspectionRequest.objects.filter(
            listing=listing, agent=agent, status=InspectionRequest.Status.PENDING
        )
        .order_by("-created_at")
        .first()
    )


def listing_has_active_requests(listing) -> bool:
    from .models import InspectionRequest

    return InspectionRequest.objects.filter(
        listing=listing,
        status=InspectionRequest.Status.PENDING,
        expires_at__gt=timezone.now(),
    ).exists()


def expire_stale_requests() -> int:
    from .models import InspectionRequest

    return InspectionRequest.objects.filter(
        status=InspectionRequest.Status.PENDING,
        expires_at__lte=timezone.now(),
    ).update(status=InspectionRequest.Status.EXPIRED, updated_at=timezone.now())


def reassign_timed_out_inspections() -> int:
    """Release inspections not submitted within the 48-hour deadline and
    re-offer the listing to the nearest PIOs (excluding the timed-out PIO)."""
    from .models import InspectionRequest, PropertyInspection, VerificationRequest

    cutoff = timezone.now() - timedelta(hours=submission_deadline_hours())
    timed_out = (
        PropertyInspection.objects.select_related("listing", "agent")
        .filter(
            status__in=[PropertyInspection.Status.CLAIMED, PropertyInspection.Status.DRAFT],
            claimed_at__lt=cutoff,
        )
        .order_by("claimed_at")
    )
    count = 0
    for inspection in timed_out:
        with transaction.atomic():
            inspection = (
                PropertyInspection.objects.select_for_update()
                .select_related("listing", "agent")
                .get(pk=inspection.pk)
            )
            if inspection.status == PropertyInspection.Status.SUBMITTED:
                continue
            listing = inspection.listing
            timed_out_agent_id = inspection.agent_id
            inspection.delete()
            next_round = (
                InspectionRequest.objects.filter(listing=listing).order_by("-round")
                .values_list("round", flat=True)
                .first()
                or 1
            ) + 1
            try:
                notify_agents_for_listing(
                    listing,
                    exclude_agent_ids={timed_out_agent_id},
                    round_number=next_round,
                )
            except Exception:
                logger.exception(
                    "Failed to re-notify PIOs for listing %s after inspection timeout", listing.id
                )
            count += 1
    return count


def process_inspection_timeouts() -> dict:
    expired = expire_stale_requests()
    reassigned = reassign_timed_out_inspections()
    return {"expired_requests": expired, "reassigned_inspections": reassigned}
