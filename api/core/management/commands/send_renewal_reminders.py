from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import Booking
from core.views import subtract_calendar_months


class Command(BaseCommand):
    help = "Send tenancy renewal reminder emails to tenants three calendar months before tenancy expiration."

    def handle(self, *args, **options):
        today = timezone.now().date()
        sent_count = 0

        bookings = (
            Booking.objects
            .select_related("tenant", "listing")
            .filter(
                status__in=[Booking.Status.CONFIRMED, Booking.Status.ACTIVE],
                renewal_reminder_sent_at__isnull=True,
            )
            .order_by("end_date")
        )

        for booking in bookings:
            reminder_date = subtract_calendar_months(booking.end_date, 3)
            if reminder_date > today:
                continue

            send_mail(
                "RentDirect tenancy renewal reminder",
                (
                    f"Hello {booking.tenant.name},\n\n"
                    f"This is a reminder that your tenancy for {booking.listing.title} is due to expire on "
                    f"{booking.end_date:%B %d, %Y}. You are now within three months of the tenancy end date.\n\n"
                    "If you would like to renew, please contact your landlord and make the necessary arrangements early.\n\n"
                    "Regards,\nRentDirect"
                ),
                settings.DEFAULT_FROM_EMAIL,
                [booking.tenant.email],
                fail_silently=False,
            )

            with transaction.atomic():
                current_booking = Booking.objects.select_for_update().get(pk=booking.pk)
                if current_booking.renewal_reminder_sent_at is not None:
                    continue
                current_booking.renewal_reminder_sent_at = timezone.now()
                current_booking.save(update_fields=["renewal_reminder_sent_at", "updated_at"])
                sent_count += 1

        self.stdout.write(self.style.SUCCESS(f"Sent {sent_count} renewal reminder(s)."))
