import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0021_paymentsettlement_transfer_tracking"),
    ]

    operations = [
        migrations.CreateModel(
            name="SubscriptionPaymentMethod",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("provider", models.CharField(default="flutterwave", max_length=40)),
                ("provider_customer_id", models.CharField(db_index=True, max_length=120)),
                ("provider_payment_method_id", models.CharField(max_length=120, unique=True)),
                ("payment_type", models.CharField(default="card", max_length=40)),
                (
                    "status",
                    models.CharField(
                        choices=[("active", "Active"), ("inactive", "Inactive")],
                        default="active",
                        max_length=20,
                    ),
                ),
                ("card_first6", models.CharField(blank=True, default="", max_length=6)),
                ("card_last4", models.CharField(blank=True, default="", max_length=4)),
                ("card_network", models.CharField(blank=True, default="", max_length=40)),
                ("card_expiry_month", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("card_expiry_year", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("provider_payload", models.JSONField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="subscription_payment_methods",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.AddField(
            model_name="subscriptionpayment",
            name="billing_reason",
            field=models.CharField(blank=True, default="manual", max_length=30),
        ),
        migrations.AddField(
            model_name="subscriptionpayment",
            name="payment_method",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="subscription_payments",
                to="core.subscriptionpaymentmethod",
            ),
        ),
        migrations.AddField(
            model_name="subscriptionpayment",
            name="provider_charge_id",
            field=models.CharField(blank=True, db_index=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="subscriptionpayment",
            name="recurring_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="subscriptionpayment",
            name="renewed_from",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="renewal_payments",
                to="core.subscriptionpayment",
            ),
        ),
        migrations.AddIndex(
            model_name="subscriptionpaymentmethod",
            index=models.Index(fields=["user", "status"], name="core_subpm_user_status_idx"),
        ),
        migrations.AddIndex(
            model_name="subscriptionpaymentmethod",
            index=models.Index(fields=["provider_payment_method_id"], name="core_subpm_provider_idx"),
        ),
    ]
