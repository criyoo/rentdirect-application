from django.db import migrations, models
from django.db.models import Count


PROGRESS_ORDER = {
    "unverified": 0,
    "pending": 1,
    "verified": 2,
}


def merge_progress_status(current_status, candidate_status):
    current = current_status or "unverified"
    candidate = candidate_status or "unverified"
    if PROGRESS_ORDER.get(candidate, 0) > PROGRESS_ORDER.get(current, 0):
        return candidate
    return current


def progress_from_legacy_status(status):
    if status == "approved":
        return "verified"
    if status in {"pending", "under_review"}:
        return "pending"
    return "unverified"


def derive_overall_status(identity_status, property_document_status, physical_property_status):
    if identity_status == "verified" and property_document_status == "verified":
        return "approved"
    if "pending" in {identity_status, property_document_status, physical_property_status}:
        return "pending"
    return "rejected"


def dedupe_verification_requests(apps, schema_editor):
    VerificationRequest = apps.get_model("core", "VerificationRequest")

    duplicate_user_ids = (
        VerificationRequest.objects.values("user_id")
        .annotate(total=Count("id"))
        .filter(total__gt=1)
        .values_list("user_id", flat=True)
    )

    for user_id in duplicate_user_ids:
        requests = list(
            VerificationRequest.objects.filter(user_id=user_id)
            .prefetch_related("documents")
            .order_by("-submitted_at", "-id")
        )
        canonical = requests[0]
        duplicates = requests[1:]

        identity_status = canonical.identity_verification_status or "unverified"
        property_document_status = canonical.property_document_verification_status or "unverified"
        physical_property_status = canonical.physical_property_status or "unverified"
        submitted_at = canonical.submitted_at
        reviewed_at = canonical.reviewed_at
        request_type = canonical.request_type
        verification_method = canonical.verification_method
        confidence_score = canonical.confidence_score
        automated_decision = canonical.automated_decision or ""
        notes = canonical.notes or ""
        document_ids = set(canonical.documents.values_list("id", flat=True))

        for item in duplicates:
            identity_status = merge_progress_status(identity_status, item.identity_verification_status)
            property_document_status = merge_progress_status(
                property_document_status,
                item.property_document_verification_status,
            )
            physical_property_status = merge_progress_status(physical_property_status, item.physical_property_status)

            legacy_progress = progress_from_legacy_status(item.status)
            if item.request_type == "identification":
                identity_status = merge_progress_status(identity_status, legacy_progress)
            elif item.request_type == "property_documents":
                property_document_status = merge_progress_status(property_document_status, legacy_progress)

            if item.submitted_at and (submitted_at is None or item.submitted_at > submitted_at):
                submitted_at = item.submitted_at
                request_type = item.request_type
            if item.reviewed_at and (reviewed_at is None or item.reviewed_at > reviewed_at):
                reviewed_at = item.reviewed_at
            if not automated_decision and item.automated_decision:
                automated_decision = item.automated_decision
            if confidence_score is None and item.confidence_score is not None:
                confidence_score = item.confidence_score
            if not notes and item.notes:
                notes = item.notes
            document_ids.update(item.documents.values_list("id", flat=True))

        canonical.request_type = request_type or "general"
        canonical.status = derive_overall_status(
            identity_status,
            property_document_status,
            physical_property_status,
        )
        canonical.identity_verification_status = identity_status
        canonical.property_document_verification_status = property_document_status
        canonical.physical_property_status = physical_property_status
        canonical.verification_method = verification_method
        canonical.confidence_score = confidence_score
        canonical.automated_decision = automated_decision
        canonical.notes = notes
        canonical.submitted_at = submitted_at
        canonical.reviewed_at = reviewed_at
        canonical.save(
            update_fields=[
                "request_type",
                "status",
                "identity_verification_status",
                "property_document_verification_status",
                "physical_property_status",
                "verification_method",
                "confidence_score",
                "automated_decision",
                "notes",
                "submitted_at",
                "reviewed_at",
            ]
        )
        if document_ids:
            canonical.documents.set(list(document_ids))
        for item in duplicates:
            item.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_verificationrequest_manual_progress_statuses"),
    ]

    operations = [
        migrations.RunPython(dedupe_verification_requests, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="verificationrequest",
            constraint=models.UniqueConstraint(fields=("user",), name="core_verify_unique_user"),
        ),
    ]
