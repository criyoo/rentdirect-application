import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0015_appuser_bvn_number"),
    ]

    operations = [
        migrations.AddField(
            model_name="payment",
            name="virtual_account_bank_code",
            field=models.CharField(blank=True, default="", max_length=40),
        ),
        migrations.AddField(
            model_name="payment",
            name="virtual_account_bank_name",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="payment",
            name="virtual_account_expiry",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="payment",
            name="virtual_account_id",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="payment",
            name="virtual_account_number",
            field=models.CharField(blank=True, default="", max_length=40),
        ),
        migrations.AddField(
            model_name="payment",
            name="virtual_account_payload",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="payment",
            name="virtual_account_reference",
            field=models.CharField(blank=True, db_index=True, default="", max_length=120),
        ),
        migrations.CreateModel(
            name="PaymentSettlement",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                (
                    "purpose",
                    models.CharField(
                        choices=[
                            ("operations", "RentDirect Operations"),
                            ("caution_fee", "Tenant Caution Fee"),
                            ("landlord_rent", "Landlord Rent"),
                        ],
                        max_length=30,
                    ),
                ),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12)),
                ("currency", models.CharField(default="NGN", max_length=10)),
                ("bank_name", models.CharField(max_length=120)),
                ("bank_code", models.CharField(blank=True, default="", max_length=40)),
                ("account_number", models.CharField(max_length=40)),
                ("account_name", models.CharField(blank=True, default="", max_length=160)),
                ("transfer_recipient_id", models.CharField(blank=True, default="", max_length=120)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("recipient_created", "Recipient Created"),
                            ("ready", "Ready"),
                            ("paid", "Paid"),
                            ("failed", "Failed"),
                        ],
                        default="pending",
                        max_length=30,
                    ),
                ),
                ("provider_payload", models.JSONField(blank=True, null=True)),
                ("last_error", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "payment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="settlements",
                        to="core.payment",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="paymentsettlement",
            constraint=models.UniqueConstraint(fields=("payment", "purpose"), name="core_payment_settlement_unique"),
        ),
        migrations.AddIndex(
            model_name="paymentsettlement",
            index=models.Index(fields=["purpose", "status"], name="core_paysettle_purp_stat_idx"),
        ),
        migrations.AddIndex(
            model_name="paymentsettlement",
            index=models.Index(fields=["transfer_recipient_id"], name="core_paysettle_recipient_idx"),
        ),
    ]
