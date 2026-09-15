from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0035_subscription_vat_payments"),
    ]

    operations = [
        migrations.AlterField(
            model_name="paymentsettlement",
            name="purpose",
            field=models.CharField(
                choices=[
                    ("operations", "RentDirect Administration Fee"),
                    ("administration_fee_vat", "VAT on RentDirect Administration Fee"),
                    ("caution_fee", "Refundable Security Deposit"),
                    ("landlord_rent", "Rent Amount"),
                ],
                max_length=30,
            ),
        ),
    ]
