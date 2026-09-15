import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0034_account_freeze_fee_ten_percent"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscriptionpayment",
            name="vat_amount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name="subscriptionpayment",
            name="vat_rate",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=5),
        ),
        migrations.CreateModel(
            name="SubscriptionVATPayment",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("payer_name", models.CharField(max_length=255)),
                ("payer_email", models.EmailField(db_index=True, max_length=254)),
                (
                    "entity_type",
                    models.CharField(
                        choices=[("tenant", "Tenant"), ("landlord", "Landlord")],
                        db_index=True,
                        max_length=20,
                    ),
                ),
                ("subscription_fee_amount", models.DecimalField(decimal_places=2, max_digits=12)),
                ("amount_paid", models.DecimalField(decimal_places=2, max_digits=12)),
                ("vat_rate", models.DecimalField(decimal_places=2, max_digits=5)),
                ("vat_amount", models.DecimalField(decimal_places=2, max_digits=12)),
                ("currency", models.CharField(default="NGN", max_length=10)),
                ("transaction_id", models.CharField(max_length=120, unique=True)),
                ("provider_transaction_id", models.CharField(blank=True, db_index=True, default="", max_length=120)),
                ("provider", models.CharField(default="flutterwave", max_length=40)),
                ("paid_at", models.DateTimeField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "payer",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="subscription_vat_payments",
                        to="core.appuser",
                    ),
                ),
                (
                    "subscription_payment",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="vat_payment",
                        to="core.subscriptionpayment",
                    ),
                ),
            ],
            options={
                "ordering": ["-paid_at"],
                "indexes": [
                    models.Index(fields=["entity_type", "-paid_at"], name="core_subvat_role_paid_idx"),
                ],
            },
        ),
    ]
