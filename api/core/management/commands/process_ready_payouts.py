from django.core.management.base import BaseCommand

from core.models import Booking
from core.inspection_requests import process_inspection_timeouts
from core.views import (
    booking_is_fully_paid,
    booking_payout_balance_available,
    booking_payout_release_conditions_met,
    process_due_tenant_refunds,
    reconcile_processing_payment_settlements,
    trigger_booking_payouts_if_ready,
)


class Command(BaseCommand):
    help = "Process completed rent payments whose rental-progress payout conditions are now satisfied."

    def handle(self, *args, **options):
        reconcile_processing_payment_settlements()
        checked_count = 0
        ready_count = 0

        bookings = (
            Booking.objects
            .select_related("tenant", "listing", "listing__landlord")
            .filter(payments__status="completed")
            .exclude(status=Booking.Status.CANCELLED)
            .distinct()
            .order_by("created_at")
        )

        for booking in bookings:
            checked_count += 1
            if (
                not booking_is_fully_paid(booking)
                or not booking_payout_balance_available(booking)
                or not booking_payout_release_conditions_met(booking)
            ):
                continue
            ready_count += 1
            trigger_booking_payouts_if_ready(booking)

        refunds_processed = process_due_tenant_refunds()
        inspection_timeouts = process_inspection_timeouts()

        self.stdout.write(
            self.style.SUCCESS(
                f"Checked {checked_count} booking(s); processed {ready_count} payout-ready booking(s); "
                f"processed {refunds_processed} due tenant refund(s); "
                f"expired {inspection_timeouts['expired_requests']} inspection request(s); "
                f"reassigned {inspection_timeouts['reassigned_inspections']} timed-out inspection(s)."
            )
        )
