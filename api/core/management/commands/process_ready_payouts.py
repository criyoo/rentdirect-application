from django.core.management.base import BaseCommand

from core.models import Booking
from core.views import booking_payout_release_conditions_met, trigger_booking_payouts_if_ready


class Command(BaseCommand):
    help = "Process completed rent payments whose rental-progress payout conditions are now satisfied."

    def handle(self, *args, **options):
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
            if not booking_payout_release_conditions_met(booking):
                continue
            ready_count += 1
            trigger_booking_payouts_if_ready(booking)

        self.stdout.write(
            self.style.SUCCESS(
                f"Checked {checked_count} booking(s); processed {ready_count} payout-ready booking(s)."
            )
        )
