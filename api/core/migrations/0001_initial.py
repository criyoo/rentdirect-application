# Generated for the RentDirect server-based rewrite.
import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.CreateModel(
            name="AppUser",
            fields=[
                ("password", models.CharField(max_length=128, verbose_name="password")),
                ("last_login", models.DateTimeField(blank=True, null=True, verbose_name="last login")),
                ("is_superuser", models.BooleanField(default=False, help_text="Designates that this user has all permissions without explicitly assigning them.", verbose_name="superuser status")),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("email", models.EmailField(max_length=254, unique=True)),
                ("name", models.CharField(max_length=160)),
                ("role", models.CharField(choices=[("tenant", "Tenant"), ("landlord", "Landlord"), ("admin", "Admin")], max_length=20)),
                ("email_verified", models.BooleanField(default=False)),
                ("profile_photo", models.ImageField(blank=True, null=True, upload_to="profiles/%Y/%m/")),
                ("mobile", models.CharField(blank=True, default="", max_length=40)),
                ("nin_number", models.CharField(blank=True, default="", max_length=80)),
                ("state_of_origin", models.CharField(blank=True, default="", max_length=120)),
                ("residence", models.JSONField(blank=True, null=True)),
                ("registration_otp_hash", models.CharField(blank=True, default="", max_length=128)),
                ("registration_otp_expires_at", models.DateTimeField(blank=True, null=True)),
                ("registration_otp_attempts", models.PositiveSmallIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
                ("is_staff", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("groups", models.ManyToManyField(blank=True, help_text="The groups this user belongs to. A user will get all permissions granted to each of their groups.", related_name="user_set", related_query_name="user", to="auth.group", verbose_name="groups")),
                ("user_permissions", models.ManyToManyField(blank=True, help_text="Specific permissions for this user.", related_name="user_set", related_query_name="user", to="auth.permission", verbose_name="user permissions")),
            ],
            options={
                "indexes": [
                    models.Index(fields=["role", "created_at"], name="core_user_role_created_idx"),
                    models.Index(fields=["email_verified"], name="core_user_verified_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="Listing",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("title", models.CharField(max_length=220)),
                ("description", models.TextField()),
                ("address", models.CharField(max_length=255)),
                ("city", models.CharField(max_length=120)),
                ("postal_code", models.CharField(blank=True, default="", max_length=40)),
                ("latitude", models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ("longitude", models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ("property_type", models.CharField(max_length=80)),
                ("bedrooms", models.PositiveSmallIntegerField()),
                ("bathrooms", models.PositiveSmallIntegerField()),
                ("square_feet", models.PositiveIntegerField(blank=True, null=True)),
                ("price_per_year", models.DecimalField(decimal_places=2, max_digits=12)),
                ("deposit_amount", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("utilities_included", models.BooleanField(default=False)),
                ("pet_friendly", models.BooleanField(default=False)),
                ("furnished", models.BooleanField(default=False)),
                ("amenities", models.JSONField(blank=True, default=list)),
                ("available_from", models.DateField(blank=True, null=True)),
                ("status", models.CharField(choices=[("available", "Available"), ("rented", "Rented"), ("draft", "Draft"), ("archived", "Archived")], default="available", max_length=20)),
                ("featured", models.BooleanField(default=False)),
                ("featured_until", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("landlord", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="listings", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "indexes": [
                    models.Index(fields=["status", "-created_at"], name="core_listing_status_ct_idx"),
                    models.Index(fields=["city", "status"], name="core_listing_city_status_idx"),
                    models.Index(fields=["landlord", "-created_at"], name="core_listing_landlord_ct_idx"),
                    models.Index(fields=["featured", "status"], name="core_listing_featured_idx"),
                    models.Index(fields=["price_per_year"], name="core_listing_price_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="Document",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("title", models.CharField(max_length=160)),
                ("content_type", models.CharField(blank=True, default="", max_length=120)),
                ("file", models.FileField(upload_to="documents/%Y/%m/")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="documents", to=settings.AUTH_USER_MODEL)),
            ],
            options={"indexes": [models.Index(fields=["owner", "-created_at"], name="core_doc_owner_created_idx")]},
        ),
        migrations.CreateModel(
            name="Booking",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("start_date", models.DateField()),
                ("end_date", models.DateField()),
                ("status", models.CharField(choices=[("pending", "Pending"), ("confirmed", "Confirmed"), ("active", "Active"), ("completed", "Completed"), ("cancelled", "Cancelled")], default="pending", max_length=20)),
                ("total_amount", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("paid_amount", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("listing", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="bookings", to="core.listing")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="bookings", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "indexes": [
                    models.Index(fields=["tenant", "-created_at"], name="core_booking_tenant_ct_idx"),
                    models.Index(fields=["listing", "-created_at"], name="core_booking_listing_ct_idx"),
                    models.Index(fields=["status", "-created_at"], name="core_booking_status_ct_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="Favourite",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("listing", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="favourited_by", to="core.listing")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="favourites", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "indexes": [models.Index(fields=["tenant", "-created_at"], name="core_fav_tenant_ct_idx")],
                "constraints": [models.UniqueConstraint(fields=("tenant", "listing"), name="unique_tenant_listing_favourite")],
            },
        ),
        migrations.CreateModel(
            name="FeaturedPayment",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12)),
                ("currency", models.CharField(default="NGN", max_length=10)),
                ("status", models.CharField(
                    choices=[
                        ("pending", "Pending"),
                        ("completed", "Completed"),
                        ("failed", "Failed"),
                        ("cancelled", "Cancelled"),
                    ],
                    default="pending",
                    max_length=30,
                )),
                ("provider", models.CharField(default="opay", max_length=40)),
                ("transaction_id", models.CharField(blank=True, max_length=120, null=True, unique=True)),
                ("opay_order_no", models.CharField(blank=True, default="", max_length=120)),
                ("opay_cashier_url", models.URLField(blank=True, default="")),
                ("featured_duration_days", models.PositiveSmallIntegerField(default=30)),
                ("expires_at", models.DateTimeField()),
                ("webhook_data", models.JSONField(blank=True, null=True)),
                ("payment_date", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("landlord", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="featured_payments", to=settings.AUTH_USER_MODEL)),
                ("listing", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="featured_payments", to="core.listing")),
            ],
            options={
                "indexes": [
                    models.Index(fields=["landlord", "-created_at"], name="core_featpay_landlord_ct_idx"),
                    models.Index(fields=["listing", "status"], name="core_featpay_list_stat_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="ListingImage",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("file", models.ImageField(upload_to="listings/%Y/%m/")),
                ("is_cover", models.BooleanField(default=False)),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("listing", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="images", to="core.listing")),
            ],
            options={"ordering": ["sort_order", "created_at"]},
        ),
        migrations.CreateModel(
            name="Message",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("content", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("listing", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="messages", to="core.listing")),
                ("receiver", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="received_messages", to=settings.AUTH_USER_MODEL)),
                ("sender", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="sent_messages", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "indexes": [
                    models.Index(fields=["sender", "-created_at"], name="core_msg_sender_ct_idx"),
                    models.Index(fields=["receiver", "-created_at"], name="core_msg_receiver_ct_idx"),
                    models.Index(fields=["listing", "created_at"], name="core_msg_listing_ct_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="Payment",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12)),
                ("payment_method", models.CharField(max_length=40)),
                ("status", models.CharField(default="pending", max_length=30)),
                ("transaction_id", models.CharField(max_length=120, unique=True)),
                ("provider", models.CharField(default="opay", max_length=40)),
                ("currency", models.CharField(default="NGN", max_length=10)),
                ("bank_name", models.CharField(blank=True, default="", max_length=120)),
                ("card_last4", models.CharField(blank=True, default="", max_length=4)),
                ("webhook_data", models.JSONField(blank=True, null=True)),
                ("payment_date", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("booking", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="payments", to="core.booking")),
            ],
        ),
        migrations.CreateModel(
            name="Review",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("rating", models.PositiveSmallIntegerField()),
                ("comment", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("landlord", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="landlord_reviews", to=settings.AUTH_USER_MODEL)),
                ("listing", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="reviews", to="core.listing")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="reviews", to=settings.AUTH_USER_MODEL)),
            ],
            options={"constraints": [models.UniqueConstraint(fields=("listing", "tenant"), name="unique_listing_tenant_review")]},
        ),
        migrations.CreateModel(
            name="VerificationRequest",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected"), ("under_review", "Under review")], default="pending", max_length=20)),
                ("verification_method", models.CharField(choices=[("manual", "Manual"), ("automated", "Automated"), ("hybrid", "Hybrid")], default="manual", max_length=20)),
                ("confidence_score", models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ("automated_decision", models.TextField(blank=True, default="")),
                ("notes", models.TextField(blank=True, default="")),
                ("submitted_at", models.DateTimeField(auto_now_add=True)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("documents", models.ManyToManyField(blank=True, to="core.document")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="verification_requests", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "indexes": [
                    models.Index(fields=["status", "-submitted_at"], name="core_verify_status_ct_idx"),
                    models.Index(fields=["user", "-submitted_at"], name="core_verify_user_ct_idx"),
                ],
            },
        ),
    ]
