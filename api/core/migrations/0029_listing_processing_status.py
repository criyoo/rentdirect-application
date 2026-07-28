from django.db import migrations, models


def _step_completed(progress, step_key):
    if not isinstance(progress, dict):
        return False
    value = progress.get(step_key)
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        completed_at = str(value.get("completed_at") or "").strip()
        selected_value = str(value.get("value") or "").strip()
        return bool(completed_at or selected_value)
    return False


def _booking_has_step_completed(booking, step_key):
    return (
        _step_completed(booking.tenant_rental_progress, step_key)
        or _step_completed(booking.landlord_rental_progress, step_key)
    )


def sync_existing_listing_statuses(apps, schema_editor):
    Listing = apps.get_model("core", "Listing")
    Booking = apps.get_model("core", "Booking")

    for listing in Listing.objects.exclude(status__in=["draft", "archived"]).iterator():
        bookings = Booking.objects.filter(listing=listing).exclude(status="cancelled")
        if any(_booking_has_step_completed(booking, "tenant_collected_house_key") for booking in bookings):
            next_status = "rented"
        elif any(_booking_has_step_completed(booking, "tenancy_agreement_signed") for booking in bookings):
            next_status = "processing"
        else:
            continue

        if listing.status != next_status:
            listing.status = next_status
            listing.save(update_fields=["status"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0028_review_review_type"),
    ]

    operations = [
        migrations.AlterField(
            model_name="listing",
            name="status",
            field=models.CharField(
                choices=[
                    ("available", "Available"),
                    ("processing", "Processing"),
                    ("rented", "Rented"),
                    ("draft", "Draft"),
                    ("archived", "Archived"),
                ],
                default="available",
                max_length=20,
            ),
        ),
        migrations.RunPython(sync_existing_listing_statuses, migrations.RunPython.noop),
    ]
