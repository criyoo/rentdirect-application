from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0003_adminuser_landlord_tenant_tenantprofile"),
    ]

    operations = [
        migrations.AddField(
            model_name="appuser",
            name="landlord_verification_profile",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="appuser",
            name="landlord_verification_type",
            field=models.CharField(blank=True, default="", max_length=20),
        ),
    ]
