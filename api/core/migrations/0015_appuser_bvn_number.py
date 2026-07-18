from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0014_subscriptionpayment"),
    ]

    operations = [
        migrations.AddField(
            model_name="appuser",
            name="bvn_number",
            field=models.CharField(blank=True, default="", max_length=80),
        ),
    ]
