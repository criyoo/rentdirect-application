from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0013_appuser_settings_otp_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="SubscriptionPayment",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("role", models.CharField(choices=[("tenant", "Tenant"), ("landlord", "Landlord"), ("admin", "Admin")], max_length=20)),
                ("plan_code", models.CharField(choices=[("bronze", "Bronze"), ("silver", "Silver"), ("gold", "Gold")], max_length=20)),
                ("billing_cycle", models.CharField(choices=[("monthly", "Monthly"), ("yearly", "Yearly")], max_length=20)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12)),
                ("currency", models.CharField(default="NGN", max_length=10)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("completed", "Completed"), ("failed", "Failed"), ("cancelled", "Cancelled")], default="pending", max_length=30)),
                ("provider", models.CharField(default="flutterwave", max_length=40)),
                ("transaction_id", models.CharField(blank=True, max_length=120, null=True, unique=True)),
                ("cashier_url", models.URLField(blank=True, default="")),
                ("provider_payload", models.JSONField(blank=True, null=True)),
                ("webhook_data", models.JSONField(blank=True, null=True)),
                ("payment_date", models.DateTimeField(blank=True, null=True)),
                ("expires_at", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="subscription_payments", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "indexes": [
                    models.Index(fields=["user", "-created_at"], name="core_subpay_user_ct_idx"),
                    models.Index(fields=["status", "-created_at"], name="core_subpay_status_ct_idx"),
                ],
            },
        ),
    ]
