from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0004_appuser_landlord_verification_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="verificationrequest",
            name="physical_property_status",
            field=models.CharField(
                choices=[("unverified", "Unverified"), ("pending", "Pending"), ("verified", "Verified")],
                default="unverified",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="verificationrequest",
            name="request_type",
            field=models.CharField(
                choices=[
                    ("general", "General"),
                    ("identification", "Identification"),
                    ("property_documents", "Property Documents"),
                ],
                default="general",
                max_length=30,
            ),
        ),
    ]
