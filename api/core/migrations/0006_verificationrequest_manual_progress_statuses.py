from django.db import migrations, models


def populate_manual_progress_statuses(apps, schema_editor):
    VerificationRequest = apps.get_model("core", "VerificationRequest")

    for request in VerificationRequest.objects.all():
        if request.status == "approved":
            mapped_status = "verified"
        elif request.status in {"pending", "under_review"}:
            mapped_status = "pending"
        else:
            mapped_status = "unverified"

        has_identification_documents = request.documents.filter(title__startswith="Landlord Identification:").exists()
        has_property_documents = request.documents.filter(title__startswith="Property Document:").exists()
        is_identification_request = request.request_type == "identification" or has_identification_documents
        is_property_request = (
            request.request_type == "property_documents"
            or has_property_documents
            or request.physical_property_status not in {"", "unverified", None}
        )

        request.identity_verification_status = "unverified"
        request.property_document_verification_status = "unverified"

        if is_identification_request:
            request.identity_verification_status = mapped_status

        if is_property_request:
            request.property_document_verification_status = mapped_status

        if not is_identification_request and not is_property_request:
            request.identity_verification_status = mapped_status
            request.property_document_verification_status = mapped_status

        if not request.physical_property_status:
            request.physical_property_status = "unverified"

        request.save(
            update_fields=[
                "identity_verification_status",
                "property_document_verification_status",
                "physical_property_status",
            ]
        )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_verificationrequest_request_type_and_physical_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="verificationrequest",
            name="identity_verification_status",
            field=models.CharField(
                choices=[("unverified", "Unverified"), ("pending", "Pending"), ("verified", "Verified")],
                default="unverified",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="verificationrequest",
            name="property_document_verification_status",
            field=models.CharField(
                choices=[("unverified", "Unverified"), ("pending", "Pending"), ("verified", "Verified")],
                default="unverified",
                max_length=20,
            ),
        ),
        migrations.RunPython(populate_manual_progress_statuses, migrations.RunPython.noop),
    ]
