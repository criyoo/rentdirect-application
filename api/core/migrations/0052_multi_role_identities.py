import uuid
from decimal import Decimal

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone

ROLE_CHOICES = [
    ("tenant", "Tenant"),
    ("landlord", "Landlord"),
    ("agent", "Property Inspection Officer"),
    ("admin", "Admin"),
]


def populate_verification_roles(apps, schema_editor):
    VerificationRequest = apps.get_model("core", "VerificationRequest")
    db_alias = schema_editor.connection.alias
    for request in (
        VerificationRequest.objects.using(db_alias).select_related("user").iterator()
    ):
        request.role = request.user.role
        request.save(update_fields=["role"])


def backfill_user_roles(apps, schema_editor):
    AppUser = apps.get_model("core", "AppUser")
    UserRole = apps.get_model("core", "UserRole")
    db_alias = schema_editor.connection.alias
    now = timezone.now()
    memberships = []
    for user in AppUser.objects.using(db_alias).iterator():
        memberships.append(
            UserRole(
                user_id=user.pk,
                role=user.role,
                status="active",
                account_frozen=user.account_frozen,
                account_frozen_at=user.account_frozen_at,
                account_frozen_until=user.account_frozen_until,
                account_freeze_fee_percentage=user.account_freeze_fee_percentage,
                created_at=now,
                updated_at=now,
            )
        )
    UserRole.objects.using(db_alias).bulk_create(memberships, batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0051_listing_category_shortlet_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserRole",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("role", models.CharField(choices=ROLE_CHOICES, max_length=20)),
                (
                    "status",
                    models.CharField(
                        choices=[("active", "Active"), ("suspended", "Suspended")],
                        default="active",
                        max_length=20,
                    ),
                ),
                ("account_frozen", models.BooleanField(default=False)),
                ("account_frozen_at", models.DateTimeField(blank=True, null=True)),
                ("account_frozen_until", models.DateTimeField(blank=True, null=True)),
                (
                    "account_freeze_fee_percentage",
                    models.DecimalField(
                        decimal_places=2, default=Decimal("10.00"), max_digits=5
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="role_memberships",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("user", "role"), name="core_userrole_user_role_uniq"
                    )
                ],
                "indexes": [
                    models.Index(
                        fields=["role", "status"], name="core_userrole_role_status_idx"
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="RoleAuditEvent",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("role", models.CharField(choices=ROLE_CHOICES, max_length=20)),
                (
                    "event",
                    models.CharField(
                        choices=[("activated", "Activated"), ("switched", "Switched")],
                        max_length=20,
                    ),
                ),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("user_agent", models.CharField(blank=True, default="", max_length=512)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="role_audit_events",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["user", "-created_at"], name="core_roleaudit_user_ct_idx"
                    )
                ],
            },
        ),
        migrations.RemoveConstraint(
            model_name="verificationrequest",
            name="core_verify_unique_user",
        ),
        migrations.AddField(
            model_name="verificationrequest",
            name="role",
            field=models.CharField(
                choices=ROLE_CHOICES, default="tenant", max_length=20
            ),
            preserve_default=False,
        ),
        migrations.RunPython(populate_verification_roles, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="verificationrequest",
            constraint=models.UniqueConstraint(
                fields=("user", "role"), name="core_verify_user_role_uniq"
            ),
        ),
        migrations.RunPython(backfill_user_roles, migrations.RunPython.noop),
    ]
