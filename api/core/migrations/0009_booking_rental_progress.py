from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_listing_state_and_toilets"),
    ]

    operations = [
        migrations.AddField(
            model_name="booking",
            name="landlord_rental_progress",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="booking",
            name="tenant_rental_progress",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
