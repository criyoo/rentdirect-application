from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0031_automate_verified_identity_requests"),
    ]

    operations = [
        migrations.AddField(
            model_name="listing",
            name="parking",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="listing",
            name="garage",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="listing",
            name="garden",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="listing",
            name="lift",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="listing",
            name="balcony",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="listing",
            name="smart_lock",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="listing",
            name="pop_ceiling",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="listing",
            name="electric_fence",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="listing",
            name="fitted_kitchen",
            field=models.BooleanField(default=False),
        ),
    ]
