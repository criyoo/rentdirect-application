from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="listing",
            name="seed_key",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddIndex(
            model_name="listing",
            index=models.Index(fields=["landlord", "seed_key"], name="core_listing_landlord_seed_idx"),
        ),
    ]
