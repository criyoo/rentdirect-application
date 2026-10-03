from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0055_identity_verification_fees"),
    ]

    operations = [
        migrations.AddField(
            model_name="representativekyc",
            name="country_of_birth",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="representativekyc",
            name="place_of_birth",
            field=models.CharField(blank=True, default="", max_length=160),
        ),
        migrations.AddField(
            model_name="representativekyc",
            name="nationality",
            field=models.CharField(blank=True, default="", max_length=80),
        ),
        migrations.AddField(
            model_name="representativekyc",
            name="state_of_origin",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="representativekyc",
            name="lga_of_origin",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="representativekyc",
            name="state_of_residence",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="representativekyc",
            name="city_of_residence",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="representativekyc",
            name="residential_address",
            field=models.TextField(blank=True, default=""),
        ),
    ]
