import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0029_listing_processing_status"),
    ]

    operations = [
        migrations.CreateModel(
            name="BvnVerificationRecord",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("provider", models.CharField(choices=[("dikript", "Dikript"), ("prembly", "Prembly")], max_length=32)),
                ("response_payload", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("bvn", models.CharField(max_length=80)),
            ],
            options={
                "ordering": ["-updated_at"],
            },
        ),
        migrations.CreateModel(
            name="CacVerificationRecord",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("provider", models.CharField(choices=[("dikript", "Dikript"), ("prembly", "Prembly")], max_length=32)),
                ("response_payload", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("registration_number", models.CharField(max_length=120)),
            ],
            options={
                "ordering": ["-updated_at"],
            },
        ),
        migrations.CreateModel(
            name="NinVerificationRecord",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("provider", models.CharField(choices=[("dikript", "Dikript"), ("prembly", "Prembly")], max_length=32)),
                ("response_payload", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("nin", models.CharField(max_length=80)),
            ],
            options={
                "ordering": ["-updated_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="bvnverificationrecord",
            constraint=models.UniqueConstraint(fields=("provider", "bvn"), name="core_bvnvr_provider_bvn_uniq"),
        ),
        migrations.AddConstraint(
            model_name="cacverificationrecord",
            constraint=models.UniqueConstraint(fields=("provider", "registration_number"), name="core_cacvr_provider_reg_uniq"),
        ),
        migrations.AddConstraint(
            model_name="ninverificationrecord",
            constraint=models.UniqueConstraint(fields=("provider", "nin"), name="core_ninvr_provider_nin_uniq"),
        ),
        migrations.AddIndex(
            model_name="bvnverificationrecord",
            index=models.Index(fields=["bvn"], name="core_bvnvr_bvn_idx"),
        ),
        migrations.AddIndex(
            model_name="bvnverificationrecord",
            index=models.Index(fields=["provider", "-updated_at"], name="core_bvnvr_provider_upd_idx"),
        ),
        migrations.AddIndex(
            model_name="cacverificationrecord",
            index=models.Index(fields=["registration_number"], name="core_cacvr_reg_idx"),
        ),
        migrations.AddIndex(
            model_name="cacverificationrecord",
            index=models.Index(fields=["provider", "-updated_at"], name="core_cacvr_provider_upd_idx"),
        ),
        migrations.AddIndex(
            model_name="ninverificationrecord",
            index=models.Index(fields=["nin"], name="core_ninvr_nin_idx"),
        ),
        migrations.AddIndex(
            model_name="ninverificationrecord",
            index=models.Index(fields=["provider", "-updated_at"], name="core_ninvr_provider_upd_idx"),
        ),
    ]
