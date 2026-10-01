from django.db import migrations, models
from django.db.models import Q


COMMERCIAL_PROPERTY_TYPES = (
    "Office",
    "Shop",
    "Retail Space",
    "Warehouse",
    "Commercial Property",
    "Industrial Property",
)


def migrate_listing_categories(apps, schema_editor):
    Listing = apps.get_model("core", "Listing")
    commercial_query = Q()
    for property_type in COMMERCIAL_PROPERTY_TYPES:
        commercial_query |= Q(property_type__iexact=property_type)
    Listing.objects.filter(commercial_query).update(category="commercial")


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0050_inspectionrequest"),
    ]

    operations = [
        migrations.AddField(
            model_name="listing",
            name="category",
            field=models.CharField(
                choices=[
                    ("residential", "Residential"),
                    ("commercial", "Commercial"),
                    ("shortlet", "Shortlet"),
                ],
                db_index=True,
                default="residential",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="listing",
            name="is_hidden",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="listing",
            name="shortlet_lister_role",
            field=models.CharField(
                blank=True,
                choices=[
                    ("owner", "Owner"),
                    ("tenant", "Tenant"),
                    ("property_manager", "Property manager"),
                    ("agent", "Agent"),
                    ("other", "Other"),
                ],
                default="",
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name="listing",
            name="shortlet_check_in_time",
            field=models.TimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="listing",
            name="shortlet_check_out_time",
            field=models.TimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="listing",
            name="minimum_stay_nights",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="listing",
            name="maximum_stay_nights",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="listing",
            name="cleaning_fee",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.RunPython(migrate_listing_categories, migrations.RunPython.noop),
    ]
