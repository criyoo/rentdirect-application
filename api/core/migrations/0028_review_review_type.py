from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0027_appuser_account_freeze"),
    ]

    operations = [
        migrations.AddField(
            model_name="review",
            name="review_type",
            field=models.CharField(
                choices=[("property", "Property"), ("landlord", "Landlord")],
                default="property",
                max_length=20,
            ),
        ),
        migrations.RemoveConstraint(
            model_name="review",
            name="unique_listing_tenant_review",
        ),
        migrations.AddConstraint(
            model_name="review",
            constraint=models.UniqueConstraint(
                fields=("listing", "tenant", "review_type"),
                name="unique_listing_tenant_review_type",
            ),
        ),
    ]
