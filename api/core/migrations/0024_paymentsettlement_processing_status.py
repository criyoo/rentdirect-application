from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0023_listing_property_verification_preferences"),
    ]

    operations = [
        migrations.AlterField(
            model_name="paymentsettlement",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("recipient_created", "Recipient Created"),
                    ("ready", "Ready"),
                    ("processing", "Processing"),
                    ("paid", "Paid"),
                    ("failed", "Failed"),
                ],
                default="pending",
                max_length=30,
            ),
        ),
    ]
