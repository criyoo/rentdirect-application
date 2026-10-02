from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0054_agentprofile_no_self_referral"),
    ]

    operations = [
        migrations.AddField(
            model_name="appuser",
            name="tenant_verification_attempts",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="appuser",
            name="landlord_verification_attempts",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AlterField(
            model_name="servicepayment",
            name="purpose",
            field=models.CharField(
                choices=[
                    ("agent_verification", "Property Inspection Officer Verification"),
                    ("tenant_verification", "Tenant Verification"),
                    ("landlord_verification", "Landlord Verification"),
                    ("lawyer_tenancy", "Lawyer Tenancy Agreement"),
                    ("in_person_verification", "In-Person Property Verification"),
                ],
                max_length=30,
            ),
        ),
    ]
