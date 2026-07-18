from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


def backfill_review_updated_at(apps, schema_editor):
    Review = apps.get_model("core", "Review")
    Review.objects.filter(updated_at__isnull=True).update(updated_at=models.F("created_at"))


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0011_featuredpayment_provider_payload_payment_created_at_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="booking",
            name="renewal_reminder_sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="review",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, null=True),
            preserve_default=False,
        ),
        migrations.RunPython(backfill_review_updated_at, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="review",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.CreateModel(
            name="Feedback",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=160)),
                ("role", models.CharField(choices=[("tenant", "Tenant"), ("landlord", "Landlord"), ("admin", "Admin")], max_length=20)),
                ("topic", models.CharField(max_length=160)),
                ("message", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="feedback_entries", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "indexes": [
                    models.Index(fields=["user", "-created_at"], name="core_feedback_user_ct_idx"),
                    models.Index(fields=["role", "-created_at"], name="core_feedback_role_ct_idx"),
                ],
            },
        ),
    ]
