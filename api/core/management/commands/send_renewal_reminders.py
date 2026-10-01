from django.conf import settings
from django.core.mail import EmailMessage
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import Booking, Listing, booking_progress_step_completed, normalize_booking_progress
from core.views import subtract_calendar_months
from core.whatsapp import send_whatsapp_alert_for_user, send_whatsapp_message


class Command(BaseCommand):
    help = "Send tenancy renewal reminders to the tenant, landlord, and RentDirect three calendar months before tenancy expiration."

    def handle(self, *args, **options):
        today = timezone.now().date()
        completed_count = self.complete_expired_tenancies(today)
        sent_count = 0
        internal_email = getattr(settings, "RENT_RENEWAL_EMAIL", "").strip()
        internal_whatsapp_number = getattr(settings, "RENT_RENEWAL_WHATSAPP_NUMBER", "").strip()

        bookings = (
            Booking.objects
            .select_related("tenant", "listing", "listing__landlord")
            .filter(
                status__in=[Booking.Status.CONFIRMED, Booking.Status.ACTIVE],
                renewal_reminder_sent_at__isnull=True,
            )
            .order_by("end_date")
        )

        for booking in bookings:
            tenant_progress = normalize_booking_progress(booking.tenant_rental_progress)
            if not booking_progress_step_completed(tenant_progress, "tenant_collected_house_key"):
                continue
            reminder_date = subtract_calendar_months(booking.end_date, 3)
            if reminder_date > today:
                continue

            landlord = booking.listing.landlord
            recipients = []
            for email in (booking.tenant.email, landlord.email):
                if email and email not in recipients:
                    recipients.append(email)
            cc = [internal_email] if internal_email and internal_email not in recipients else []

            EmailMessage(
                "RentDirect tenancy renewal reminder",
                (
                    f"Hello,\n\n"
                    f"This is a reminder that the tenancy for {booking.listing.title} is due to expire on "
                    f"{booking.end_date:%B %d, %Y}. The listing will be eligible for re-listing at tenancy expiration.\n\n"
                    f"Tenant: {booking.tenant.name} ({booking.tenant.email})\n\n"
                    "If the tenant would like to renew, please make the necessary arrangements early.\n\n"
                    "Regards,\nRentDirect"
                ),
                settings.DEFAULT_FROM_EMAIL,
                recipients,
                cc=cc,
            ).send(fail_silently=False)
            whatsapp_message = (
                f"RentDirect: The tenancy for {booking.listing.title} expires on "
                f"{booking.end_date:%B %d, %Y}. The listing will be eligible for re-listing at tenancy expiration."
            )
            send_whatsapp_alert_for_user(booking.tenant, whatsapp_message)
            send_whatsapp_alert_for_user(landlord, whatsapp_message)
            if internal_whatsapp_number:
                send_whatsapp_message(internal_whatsapp_number, whatsapp_message)

            with transaction.atomic():
                current_booking = Booking.objects.select_for_update().get(pk=booking.pk)
                if current_booking.renewal_reminder_sent_at is not None:
                    continue
                current_booking.renewal_reminder_sent_at = timezone.now()
                current_booking.save(update_fields=["renewal_reminder_sent_at", "updated_at"])
                sent_count += 1

        self.stdout.write(self.style.SUCCESS(f"Completed {completed_count} expired booking(s)."))
        self.stdout.write(self.style.SUCCESS(f"Sent {sent_count} renewal reminder(s)."))

    def complete_expired_tenancies(self, today):
        """Mark expired key-confirmed bookings completed and make their listings available again."""
        completed_count = 0
        expired_bookings = (
            Booking.objects
            .select_related("listing", "listing__landlord")
            .filter(
                status__in=[Booking.Status.CONFIRMED, Booking.Status.ACTIVE],
                end_date__lt=today,
            )
            .order_by("end_date")
        )

        for booking in expired_bookings:
            tenant_progress = normalize_booking_progress(booking.tenant_rental_progress)
            if not booking_progress_step_completed(tenant_progress, "tenant_collected_house_key"):
                continue

            with transaction.atomic():
                current_booking = (
                    Booking.objects
                    .select_for_update()
                    .select_related("listing")
                    .get(pk=booking.pk)
                )
                if current_booking.status not in {Booking.Status.CONFIRMED, Booking.Status.ACTIVE}:
                    continue
                current_booking.status = Booking.Status.COMPLETED
                current_booking.save(update_fields=["status", "updated_at"])

                listing = current_booking.listing
                if listing.status == Listing.Status.RENTED:
                    has_active_key_confirmed_booking = any(
                        booking_progress_step_completed(
                            normalize_booking_progress(other.tenant_rental_progress),
                            "tenant_collected_house_key",
                        )
                        for other in listing.bookings.exclude(
                            status__in=[Booking.Status.CANCELLED, Booking.Status.COMPLETED]
                        ).filter(end_date__gte=today)
                    )
                    if not has_active_key_confirmed_booking:
                        listing.status = Listing.Status.AVAILABLE
                        listing.save(update_fields=["status", "updated_at"])

            completed_count += 1

        return completed_count
