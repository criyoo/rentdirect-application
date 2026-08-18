from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0032_listing_feature_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="booking",
            name="deposit_paid_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="booking",
            name="full_rent_paid_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
