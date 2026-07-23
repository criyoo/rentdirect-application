from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0022_subscription_recurring_payments"),
    ]

    operations = [
        migrations.AddField(
            model_name="listing",
            name="commercial_activities_allowed",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="listing",
            name="expatriates_allowed",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="listing",
            name="maximum_occupancy",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="listing",
            name="minimum_rental_duration",
            field=models.CharField(blank=True, default="", max_length=80),
        ),
        migrations.AddField(
            model_name="listing",
            name="ownership_status",
            field=models.CharField(blank=True, default="", max_length=80),
        ),
        migrations.AddField(
            model_name="listing",
            name="ownership_types",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="listing",
            name="physical_property_status",
            field=models.CharField(
                choices=[("unverified", "Unverified"), ("pending", "Pending"), ("verified", "Verified")],
                default="unverified",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="listing",
            name="property_document_submission",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="listing",
            name="property_document_verification_status",
            field=models.CharField(
                choices=[("unverified", "Unverified"), ("pending", "Pending"), ("verified", "Verified")],
                default="unverified",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="listing",
            name="property_documents",
            field=models.ManyToManyField(blank=True, related_name="listing_property_documents", to="core.document"),
        ),
        migrations.AddField(
            model_name="listing",
            name="property_ownership_documents",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="listing",
            name="short_let_allowed",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="listing",
            name="smoking_allowed",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="listing",
            name="student_tenants_allowed",
            field=models.BooleanField(default=False),
        ),
    ]
