from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0020_subscriptionpayment_platinum_plan"),
    ]

    operations = [
        migrations.AddField(
            model_name="paymentsettlement",
            name="transfer_reference",
            field=models.CharField(blank=True, db_index=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="paymentsettlement",
            name="transfer_payload",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="paymentsettlement",
            name="transferred_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
