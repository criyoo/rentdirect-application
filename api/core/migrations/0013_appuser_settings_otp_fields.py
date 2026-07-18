from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0012_booking_renewal_reminder_sent_at_feedback_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="appuser",
            name="settings_otp_attempts",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="appuser",
            name="settings_otp_expires_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="appuser",
            name="settings_otp_hash",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
        migrations.AddField(
            model_name="appuser",
            name="settings_otp_purpose",
            field=models.CharField(blank=True, default="", max_length=40),
        ),
        migrations.AddField(
            model_name="appuser",
            name="settings_otp_target_email",
            field=models.EmailField(blank=True, default="", max_length=254),
        ),
    ]
