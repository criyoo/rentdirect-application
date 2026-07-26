from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0026_ensure_resource_file_column_lengths"),
    ]

    operations = [
        migrations.AddField(
            model_name="appuser",
            name="account_frozen",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="appuser",
            name="account_frozen_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="appuser",
            name="account_frozen_until",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="appuser",
            name="account_freeze_fee_percentage",
            field=models.DecimalField(decimal_places=2, default=Decimal("20"), max_digits=5),
        ),
    ]
