from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0016_payment_virtual_account_paymentsettlement"),
    ]

    operations = [
        migrations.AddField(
            model_name="appuser",
            name="tenant_verification_profile",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
