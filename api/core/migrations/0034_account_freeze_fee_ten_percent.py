from decimal import Decimal

from django.db import migrations, models


def set_existing_freeze_fees_to_ten_percent(apps, schema_editor):
    AppUser = apps.get_model("core", "AppUser")
    AppUser.objects.filter(account_freeze_fee_percentage=Decimal("20")).update(
        account_freeze_fee_percentage=Decimal("10")
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0033_booking_payment_timestamps"),
    ]

    operations = [
        migrations.AlterField(
            model_name="appuser",
            name="account_freeze_fee_percentage",
            field=models.DecimalField(decimal_places=2, default=10, max_digits=5),
        ),
        migrations.RunPython(set_existing_freeze_fees_to_ten_percent, migrations.RunPython.noop),
    ]
