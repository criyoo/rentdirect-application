from django.db import migrations, models


def populate_listing_state_and_toilets(apps, schema_editor):
    Listing = apps.get_model("core", "Listing")

    for listing in Listing.objects.select_related("landlord").all():
        updated_fields = []

        if not listing.state:
            residence = getattr(listing.landlord, "residence", None) or {}
            state = residence.get("state", "") if isinstance(residence, dict) else ""
            if state:
                listing.state = state
                updated_fields.append("state")

        if listing.toilets is None:
            listing.toilets = listing.bathrooms
            updated_fields.append("toilets")

        if updated_fields:
            listing.save(update_fields=updated_fields)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0007_dedupe_verification_requests"),
    ]

    operations = [
        migrations.AddField(
            model_name="listing",
            name="state",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="listing",
            name="toilets",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.RunPython(populate_listing_state_and_toilets, migrations.RunPython.noop),
    ]
