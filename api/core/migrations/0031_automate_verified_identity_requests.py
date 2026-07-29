from django.db import migrations
from django.utils import timezone


def approve_verified_identity_requests(apps, schema_editor):
    VerificationRequest = apps.get_model("core", "VerificationRequest")
    verified_requests = VerificationRequest.objects.filter(identity_verification_status="verified")
    for verification in verified_requests.iterator():
        update_fields = []
        if verification.status != "approved":
            verification.status = "approved"
            update_fields.append("status")
        if verification.verification_method != "automated":
            verification.verification_method = "automated"
            update_fields.append("verification_method")
        if verification.reviewed_at is None:
            verification.reviewed_at = verification.submitted_at or timezone.now()
            update_fields.append("reviewed_at")
        if update_fields:
            verification.save(update_fields=update_fields)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0030_verification_lookup_records"),
    ]

    operations = [
        migrations.RunPython(approve_verified_identity_requests, migrations.RunPython.noop),
    ]
