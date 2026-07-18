from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0019_supportchatmessage"),
    ]

    operations = [
        migrations.AlterField(
            model_name="subscriptionpayment",
            name="plan_code",
            field=models.CharField(
                choices=[
                    ("bronze", "Bronze"),
                    ("silver", "Silver"),
                    ("gold", "Gold"),
                    ("platinum", "Platinum"),
                ],
                max_length=20,
            ),
        ),
    ]
