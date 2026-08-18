import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import PurePath

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone

from .pricing import calculate_deposit_amount, resolve_booking_total

DEPOSIT_LISTING_HOLD_DAYS = 3


def _file_extension(filename: str) -> str:
    return PurePath(str(filename or "")).suffix.lower()


def _resource_upload_path(prefix: str, resource_ids: list[str], label: str, filename: str) -> str:
    safe_ids = [str(resource_id) for resource_id in resource_ids if resource_id]
    return "/".join([prefix, *safe_ids, f"{label}-{uuid.uuid4().hex}{_file_extension(filename)}"])


def profile_photo_upload_to(instance, filename: str) -> str:
    return _resource_upload_path("profiles", [instance.pk], "profile", filename)


def document_file_upload_to(instance, filename: str) -> str:
    return _resource_upload_path("documents", [instance.owner_id, instance.pk], "document", filename)


def listing_image_file_upload_to(instance, filename: str) -> str:
    listing = instance._state.fields_cache.get("listing")
    landlord_id = getattr(listing, "landlord_id", None)
    if not landlord_id and instance.listing_id:
        landlord_id = Listing.objects.filter(pk=instance.listing_id).values_list("landlord_id", flat=True).first()
    return _resource_upload_path("listings", [landlord_id, instance.listing_id, instance.pk], "listing-image", filename)


class AppUserManager(BaseUserManager):
    def create_user(self, email: str, password: str | None = None, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str | None = None, **extra_fields):
        extra_fields.setdefault("role", AppUser.Role.ADMIN)
        extra_fields.setdefault("name", "Admin")
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("email_verified", True)
        return self.create_user(email, password, **extra_fields)


class AppUser(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        TENANT = "tenant", "Tenant"
        LANDLORD = "landlord", "Landlord"
        ADMIN = "admin", "Admin"

    class LandlordVerificationType(models.TextChoices):
        INDIVIDUAL = "individual", "Individual"
        CORPORATE = "corporate", "Corporate"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=160)
    role = models.CharField(max_length=20, choices=Role.choices)
    email_verified = models.BooleanField(default=False)
    profile_photo = models.ImageField(upload_to=profile_photo_upload_to, blank=True, null=True, max_length=512)
    mobile = models.CharField(max_length=40, blank=True, default="")
    nin_number = models.CharField(max_length=80, blank=True, default="")
    bvn_number = models.CharField(max_length=80, blank=True, default="")
    state_of_origin = models.CharField(max_length=120, blank=True, default="")
    residence = models.JSONField(blank=True, null=True)
    landlord_verification_type = models.CharField(max_length=20, blank=True, default="")
    landlord_verification_profile = models.JSONField(blank=True, null=True)
    tenant_verification_profile = models.JSONField(blank=True, null=True)
    registration_otp_hash = models.CharField(max_length=128, blank=True, default="")
    registration_otp_expires_at = models.DateTimeField(null=True, blank=True)
    registration_otp_attempts = models.PositiveSmallIntegerField(default=0)
    settings_otp_hash = models.CharField(max_length=128, blank=True, default="")
    settings_otp_expires_at = models.DateTimeField(null=True, blank=True)
    settings_otp_attempts = models.PositiveSmallIntegerField(default=0)
    settings_otp_purpose = models.CharField(max_length=40, blank=True, default="")
    settings_otp_target_email = models.EmailField(blank=True, default="")
    account_frozen = models.BooleanField(default=False)
    account_frozen_at = models.DateTimeField(null=True, blank=True)
    account_frozen_until = models.DateTimeField(null=True, blank=True)
    account_freeze_fee_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=10)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = AppUserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["name", "role"]

    def __str__(self) -> str:
        return self.email

    @property
    def profile_photo_url(self) -> str:
        return self.profile_photo.url if self.profile_photo else ""

    @property
    def is_verified(self) -> bool:
        if self.role == self.Role.LANDLORD:
            return self.verification_requests.filter(
                identity_verification_status=VerificationRequest.VerificationProgressStatus.VERIFIED,
            ).exists()

        tenant_profile = getattr(self, "tenant_profile", None)
        if self.role == self.Role.TENANT and self.verification_requests.filter(
            identity_verification_status=VerificationRequest.VerificationProgressStatus.VERIFIED,
        ).exists():
            return True
        if tenant_profile and tenant_profile.status == TenantProfile.Status.APPROVED:
            return True

        return self.verification_requests.filter(status=VerificationRequest.Status.APPROVED).exists()

    @property
    def is_account_frozen(self) -> bool:
        if not self.account_frozen:
            return False
        if self.account_frozen_until and self.account_frozen_until <= timezone.now():
            return False
        return True

    class Meta:
        indexes = [
            models.Index(fields=["role", "created_at"], name="core_user_role_created_idx"),
            models.Index(fields=["email_verified"], name="core_user_verified_idx"),
        ]


class Tenant(AppUser):
    class Meta:
        proxy = True
        verbose_name = "Tenant"
        verbose_name_plural = "Tenants"


class Landlord(AppUser):
    class Meta:
        proxy = True
        verbose_name = "Landlord"
        verbose_name_plural = "Landlords"


class LandlordProfile(AppUser):
    class Meta:
        proxy = True
        verbose_name = "Landlord Profile"
        verbose_name_plural = "Landlord Profiles"


class AdminUser(AppUser):
    class Meta:
        proxy = True
        verbose_name = "Admin"
        verbose_name_plural = "Admins"


BOOKING_PROGRESS_STEP_DEFINITIONS = {
    AppUser.Role.LANDLORD: (
        ("viewing_appointment_booked", "Viewing appointment booked?"),
        ("house_viewed", "House Viewed?"),
        ("tenancy_agreement_signed", "Tenancy agreement signed?"),
        ("deposit_payment_notification_received", "Recieved email notification of rental deposit from Rentdirect?"),
        ("rental_payment_notification_received", "Received email notification of rental full payment from Rentdirect?"),
        ("check_in_inventory_completed", "Check-in house inventory completed?"),
        ("tenant_collected_house_key", "Tenant collected house Key?"),
        ("net_payment_notification_received", "Bank & Email notification of total rent amount received?"),
    ),
    AppUser.Role.TENANT: (
        ("viewing_appointment_booked", "Viewing appointment booked?"),
        ("house_viewed", "House Viewed?"),
        ("tenancy_agreement_signed", "Tenancy agreement signed?"),
        ("tenant_paid_deposit", "Tenant has paid Deposit?"),
        ("tenant_paid_rent_in_full", "Tenant has paid rent in full?"),
        ("check_in_inventory_completed", "Check-in house inventory completed?"),
        ("tenant_collected_house_key", "Tenant collected House Key?"),
        ("rentdirect_transfer_to_landlord", "Can RentDirect transfer rent amount to Landlord?"),
        ("final_rent_payment_email_received", "Email of rent payment to landlord received?"),
    ),
}

BOOKING_PROGRESS_CHOICE_OPTIONS = {
    "rentdirect_transfer_to_landlord": (
        {"value": "yes", "label": "Yes"},
        {"value": "no", "label": "No"},
    ),
}

BOOKING_PROGRESS_LEGACY_KEY_ALIASES = {
    "rentdirect_transfer_to_landlord": "landlord_payment_notification_received",
}

# Each progress item is displayed alongside its counterpart. Some items use
# different keys because the tenant and landlord see the milestone from a
# different perspective, so keep the relationship explicit instead of
# relying on list ordering.
BOOKING_PROGRESS_COUNTERPART_STEP_KEYS = {
    AppUser.Role.LANDLORD: {
        "viewing_appointment_booked": ("viewing_appointment_booked",),
        "house_viewed": ("house_viewed",),
        "tenancy_agreement_signed": ("tenancy_agreement_signed",),
        "deposit_payment_notification_received": ("tenant_paid_deposit",),
        "rental_payment_notification_received": ("tenant_paid_rent_in_full",),
        "check_in_inventory_completed": ("check_in_inventory_completed",),
        "tenant_collected_house_key": ("tenant_collected_house_key",),
        "net_payment_notification_received": (
            "final_rent_payment_email_received",
            "rentdirect_transfer_to_landlord",
        ),
    },
    AppUser.Role.TENANT: {
        "viewing_appointment_booked": ("viewing_appointment_booked",),
        "house_viewed": ("house_viewed",),
        "tenancy_agreement_signed": ("tenancy_agreement_signed",),
        "tenant_paid_deposit": ("deposit_payment_notification_received",),
        "tenant_paid_rent_in_full": ("rental_payment_notification_received",),
        "check_in_inventory_completed": ("check_in_inventory_completed",),
        "tenant_collected_house_key": ("tenant_collected_house_key",),
        "rentdirect_transfer_to_landlord": ("net_payment_notification_received",),
        "final_rent_payment_email_received": ("net_payment_notification_received",),
    },
}

TENANT_DEPOSIT_PROGRESS_KEY = "tenant_paid_deposit"
LANDLORD_DEPOSIT_PROGRESS_KEY = "deposit_payment_notification_received"

VERIFICATION_PROGRESS_STATUS_CHOICES = (
    ("unverified", "Unverified"),
    ("pending", "Pending"),
    ("verified", "Verified"),
)

BOOKING_PROGRESS_FIELD_BY_ROLE = {
    AppUser.Role.LANDLORD: "landlord_rental_progress",
    AppUser.Role.TENANT: "tenant_rental_progress",
}


def normalize_booking_progress(progress):
    return progress if isinstance(progress, dict) else {}


def get_booking_progress_steps(role: str):
    return BOOKING_PROGRESS_STEP_DEFINITIONS.get(role, ())


def get_booking_progress_choice_options(step_key: str):
    return BOOKING_PROGRESS_CHOICE_OPTIONS.get(step_key, ())


def get_booking_progress_counterpart_step_keys(role: str, step_key: str):
    return BOOKING_PROGRESS_COUNTERPART_STEP_KEYS.get(role, {}).get(step_key, ())


def get_booking_progress_value(progress, step_key: str):
    normalized_progress = normalize_booking_progress(progress)
    if step_key in normalized_progress:
        return normalized_progress.get(step_key)

    legacy_key = BOOKING_PROGRESS_LEGACY_KEY_ALIASES.get(step_key)
    if legacy_key:
        return normalized_progress.get(legacy_key)

    return None


def booking_progress_step_completed(progress, step_key: str) -> bool:
    value = get_booking_progress_value(progress, step_key)
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        selected_value = str(value.get("value") or "").strip()
        completed_at = str(value.get("completed_at") or "").strip()
        return bool(selected_value and completed_at)
    return False


def booking_progress_step_completed_at(progress, step_key: str) -> str | None:
    value = get_booking_progress_value(progress, step_key)
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        completed_at = str(value.get("completed_at") or "").strip()
        return completed_at or None
    return None


def booking_progress_step_selected_value(progress, step_key: str) -> str | None:
    value = get_booking_progress_value(progress, step_key)
    if isinstance(value, dict):
        selected_value = str(value.get("value") or "").strip().lower()
        return selected_value or None
    if isinstance(value, str) and step_key in BOOKING_PROGRESS_LEGACY_KEY_ALIASES:
        return "yes"
    return None


def deposit_secured_booking_queryset():
    now = timezone.now()
    deposit_due = models.ExpressionWrapper(
        models.F("listing__price_per_year")
        * models.Value(
            Decimal("0.20"),
            output_field=models.DecimalField(max_digits=4, decimal_places=2),
        ),
        output_field=models.DecimalField(max_digits=12, decimal_places=2),
    )
    calculated_total = models.ExpressionWrapper(
        models.F("listing__price_per_year")
        * models.Value(
            Decimal("1.20"),
            output_field=models.DecimalField(max_digits=4, decimal_places=2),
        ),
        output_field=models.DecimalField(max_digits=12, decimal_places=2),
    )
    queryset = (
        Booking.objects
        .exclude(status=Booking.Status.CANCELLED)
        .annotate(deposit_due=deposit_due, calculated_total=calculated_total)
    )
    full_rental_paid = (
        models.Q(total_amount__isnull=False, paid_amount__gte=models.F("total_amount"))
        | models.Q(total_amount__isnull=True, paid_amount__gte=models.F("calculated_total"))
    )
    active_full_rental = full_rental_paid & models.Q(end_date__gte=now.date())
    recent_deposit = (
        models.Q(paid_amount__gte=models.F("deposit_due"))
        & ~full_rental_paid
        & (
            models.Q(deposit_paid_at__gt=now - timedelta(days=DEPOSIT_LISTING_HOLD_DAYS))
            | models.Q(
                deposit_paid_at__isnull=True,
                updated_at__gt=now - timedelta(days=DEPOSIT_LISTING_HOLD_DAYS),
            )
        )
    )
    return (
        queryset
        .filter(active_full_rental | recent_deposit)
    )


def listing_has_deposit_secured_booking(listing) -> bool:
    return deposit_secured_booking_queryset().filter(listing=listing).exists()


def booking_progress_step_completed_by_any_party(booking, step_key: str) -> bool:
    tenant_progress = normalize_booking_progress(getattr(booking, "tenant_rental_progress", {}))
    landlord_progress = normalize_booking_progress(getattr(booking, "landlord_rental_progress", {}))
    return (
        booking_progress_step_completed(tenant_progress, step_key)
        or booking_progress_step_completed(landlord_progress, step_key)
    )


def infer_listing_rental_status(listing) -> str:
    if listing.status in {Listing.Status.DRAFT, Listing.Status.ARCHIVED}:
        return listing.status

    prefetched_bookings = getattr(listing, "_prefetched_objects_cache", {}).get("bookings")
    if prefetched_bookings is None:
        bookings = listing.bookings.exclude(status=Booking.Status.CANCELLED)
    else:
        bookings = [
            booking
            for booking in prefetched_bookings
            if booking.status != Booking.Status.CANCELLED
        ]

    if any(booking_progress_step_completed_by_any_party(booking, "tenant_collected_house_key") for booking in bookings):
        return Listing.Status.RENTED
    if any(booking_progress_step_completed_by_any_party(booking, "tenancy_agreement_signed") for booking in bookings):
        return Listing.Status.PROCESSING
    return listing.status


def sync_listing_status_from_rental_progress(listing) -> str:
    status = infer_listing_rental_status(listing)
    if status != listing.status:
        listing.status = status
        listing.save(update_fields=["status", "updated_at"])
    return status


def get_booking_progress_field_name(role: str) -> str:
    return BOOKING_PROGRESS_FIELD_BY_ROLE.get(role, "")


def booking_has_paid_full_rental_amount(booking) -> bool:
    listing = getattr(booking, "listing", None)
    annual_rent = getattr(listing, "price_per_year", None)
    if annual_rent is None:
        return False

    total_due = resolve_booking_total(annual_rent, getattr(booking, "total_amount", None))
    paid_amount = Decimal(getattr(booking, "paid_amount", 0) or 0)
    return paid_amount >= total_due


def booking_has_paid_rental_deposit(booking) -> bool:
    listing = getattr(booking, "listing", None)
    annual_rent = getattr(listing, "price_per_year", None)
    if annual_rent is None:
        return False

    paid_amount = Decimal(getattr(booking, "paid_amount", 0) or 0)
    deposit_due = calculate_deposit_amount(annual_rent)
    return paid_amount >= deposit_due or booking_has_paid_full_rental_amount(booking)


def complete_booking_progress_step(
    booking,
    role: str,
    step_key: str,
    *,
    completed_at: str | None = None,
    selected_value: str | None = None,
) -> None:
    """Persist a progress milestone for the actor only."""
    timestamp = completed_at or timezone.now().isoformat()
    current_field = get_booking_progress_field_name(role)
    current_progress = normalize_booking_progress(getattr(booking, current_field, {})).copy()

    if step_key not in current_progress:
        if get_booking_progress_choice_options(step_key):
            current_progress[step_key] = {
                "value": selected_value or "yes",
                "completed_at": timestamp,
            }
        else:
            current_progress[step_key] = timestamp

    setattr(booking, current_field, current_progress)
    booking.save(update_fields=[current_field, "updated_at"])


def build_booking_progress_data(booking, role: str) -> dict:
    steps = get_booking_progress_steps(role)
    rental_deposit_paid = booking_has_paid_rental_deposit(booking)
    full_rental_amount_paid = booking_has_paid_full_rental_amount(booking)
    field_name = get_booking_progress_field_name(role)
    progress = normalize_booking_progress(getattr(booking, field_name, {})) if field_name else {}
    counterpart_role = (
        AppUser.Role.LANDLORD
        if role == AppUser.Role.TENANT
        else AppUser.Role.TENANT
    )
    counterpart_field_name = get_booking_progress_field_name(counterpart_role)
    counterpart_progress = normalize_booking_progress(
        getattr(booking, counterpart_field_name, {})
    ) if counterpart_field_name else {}
    completed_count = 0
    step_items = []

    for key, label in steps:
        completed = booking_progress_step_completed(progress, key)
        completed_at = booking_progress_step_completed_at(progress, key)
        selected_value = booking_progress_step_selected_value(progress, key)
        counterpart_keys = get_booking_progress_counterpart_step_keys(role, key)
        counterpart_key = counterpart_keys[0] if counterpart_keys else None
        counterpart_completed = any(
            booking_progress_step_completed(counterpart_progress, counterpart_key)
            for counterpart_key in counterpart_keys
        )
        counterpart_completed_at = next(
            (
                booking_progress_step_completed_at(counterpart_progress, counterpart_key)
                for counterpart_key in counterpart_keys
                if booking_progress_step_completed_at(counterpart_progress, counterpart_key)
            ),
            None,
        )
        counterpart_selected_value = next(
            (
                booking_progress_step_selected_value(counterpart_progress, counterpart_key)
                for counterpart_key in counterpart_keys
                if booking_progress_step_selected_value(counterpart_progress, counterpart_key)
            ),
            None,
        )
        options = get_booking_progress_choice_options(key)
        if completed:
            completed_count += 1

        item = {
            "key": key,
            "label": label,
            "kind": "choice" if options else "boolean",
            "completed": completed,
            "completed_at": completed_at,
            "counterpart_completed": counterpart_completed,
            "counterpart_completed_at": counterpart_completed_at,
            "counterpart_step_key": counterpart_key,
        }
        if options:
            item["options"] = list(options)
            item["selected_value"] = selected_value
        if counterpart_selected_value:
            item["counterpart_selected_value"] = counterpart_selected_value

        step_items.append(item)

    total_steps = len(steps)
    progress_percent = round((completed_count / total_steps) * 100, 1) if total_steps else 0.0

    return {
        "role": role,
        "rental_deposit_paid": rental_deposit_paid,
        "full_rental_amount_paid": full_rental_amount_paid,
        "progress_percent": progress_percent,
        "completed_count": completed_count,
        "total_count": total_steps,
        "steps": step_items,
    }


class Listing(models.Model):
    class Status(models.TextChoices):
        AVAILABLE = "available", "Available"
        PROCESSING = "processing", "Processing"
        RENTED = "rented", "Rented"
        DRAFT = "draft", "Draft"
        ARCHIVED = "archived", "Archived"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    landlord = models.ForeignKey(AppUser, on_delete=models.CASCADE, related_name="listings")
    title = models.CharField(max_length=220)
    description = models.TextField()
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=120)
    state = models.CharField(max_length=120, blank=True, default="")
    postal_code = models.CharField(max_length=40, blank=True, default="")
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    property_type = models.CharField(max_length=80)
    bedrooms = models.PositiveSmallIntegerField()
    bathrooms = models.PositiveSmallIntegerField()
    toilets = models.PositiveSmallIntegerField(null=True, blank=True)
    square_feet = models.PositiveIntegerField(null=True, blank=True)
    price_per_year = models.DecimalField(max_digits=12, decimal_places=2)
    deposit_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    utilities_included = models.BooleanField(default=False)
    pet_friendly = models.BooleanField(default=False)
    parking = models.BooleanField(default=False)
    garage = models.BooleanField(default=False)
    garden = models.BooleanField(default=False)
    lift = models.BooleanField(default=False)
    balcony = models.BooleanField(default=False)
    smart_lock = models.BooleanField(default=False)
    pop_ceiling = models.BooleanField(default=False)
    electric_fence = models.BooleanField(default=False)
    fitted_kitchen = models.BooleanField(default=False)
    furnished = models.BooleanField(default=False)
    amenities = models.JSONField(default=list, blank=True)
    ownership_status = models.CharField(max_length=80, blank=True, default="")
    ownership_types = models.JSONField(default=list, blank=True)
    property_ownership_documents = models.JSONField(default=list, blank=True)
    property_documents = models.ManyToManyField("Document", blank=True, related_name="listing_property_documents")
    property_document_submission = models.JSONField(blank=True, null=True)
    property_document_verification_status = models.CharField(
        max_length=20,
        choices=VERIFICATION_PROGRESS_STATUS_CHOICES,
        default="unverified",
    )
    physical_property_status = models.CharField(
        max_length=20,
        choices=VERIFICATION_PROGRESS_STATUS_CHOICES,
        default="unverified",
    )
    minimum_rental_duration = models.CharField(max_length=80, blank=True, default="")
    maximum_occupancy = models.PositiveSmallIntegerField(null=True, blank=True)
    smoking_allowed = models.BooleanField(default=False)
    commercial_activities_allowed = models.BooleanField(default=False)
    short_let_allowed = models.BooleanField(default=False)
    student_tenants_allowed = models.BooleanField(default=False)
    expatriates_allowed = models.BooleanField(default=False)
    available_from = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.AVAILABLE)
    featured = models.BooleanField(default=False)
    featured_until = models.DateTimeField(null=True, blank=True)
    seed_key = models.CharField(max_length=120, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def cover_image_url(self) -> str:
        cover = self.images.filter(is_cover=True).first() or self.images.first()
        return cover.file.url if cover and cover.file else ""

    @property
    def image_urls(self) -> list[str]:
        return [image.file.url for image in self.images.all() if image.file]

    def __str__(self) -> str:
        return self.title

    class Meta:
        indexes = [
            models.Index(fields=["status", "-created_at"], name="core_listing_status_ct_idx"),
            models.Index(fields=["city", "status"], name="core_listing_city_status_idx"),
            models.Index(fields=["landlord", "-created_at"], name="core_listing_landlord_ct_idx"),
            models.Index(fields=["featured", "status"], name="core_listing_featured_idx"),
            models.Index(fields=["price_per_year"], name="core_listing_price_idx"),
            models.Index(fields=["landlord", "seed_key"], name="core_listing_landlord_seed_idx"),
        ]


class ListingImage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="images")
    file = models.ImageField(upload_to=listing_image_file_upload_to, max_length=512)
    is_cover = models.BooleanField(default=False)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "created_at"]


class Document(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(AppUser, on_delete=models.CASCADE, related_name="documents")
    title = models.CharField(max_length=160)
    content_type = models.CharField(max_length=120, blank=True, default="")
    file = models.FileField(upload_to=document_file_upload_to, max_length=512)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def file_url(self) -> str:
        return self.file.url if self.file else ""

    class Meta:
        indexes = [models.Index(fields=["owner", "-created_at"], name="core_doc_owner_created_idx")]


def _truncate_model_text(value: str, max_length: int | None) -> str:
    if not max_length or len(value) <= max_length:
        return value
    if max_length <= 3:
        return value[:max_length]
    return value[: max_length - 3].rstrip() + "..."


def build_listing_property_document_title(
    listing: Listing,
    file_name: str,
    document_types: list[str] | None = None,
) -> str:
    max_length = Document._meta.get_field("title").max_length
    prefix = f"Listing Property Document: {listing.id}"
    safe_file_name = str(file_name or "Property Document").strip() or "Property Document"
    document_type_text = ", ".join(str(item).strip() for item in document_types or [] if str(item).strip())
    full_title = " - ".join(part for part in (prefix, document_type_text, safe_file_name) if part)
    if not max_length or len(full_title) <= max_length:
        return full_title

    compact_title = f"{prefix} - {safe_file_name}"
    if len(compact_title) <= max_length:
        return compact_title

    remaining = max_length - len(prefix) - len(" - ")
    if remaining > 0:
        return f"{prefix} - {_truncate_model_text(safe_file_name, remaining)}"
    return _truncate_model_text(compact_title, max_length)


class VerificationRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        UNDER_REVIEW = "under_review", "Under review"

    class RequestType(models.TextChoices):
        GENERAL = "general", "General"
        IDENTIFICATION = "identification", "Identification"
        PROPERTY_DOCUMENTS = "property_documents", "Property Documents"

    class VerificationProgressStatus(models.TextChoices):
        UNVERIFIED = "unverified", "Unverified"
        PENDING = "pending", "Pending"
        VERIFIED = "verified", "Verified"

    class Method(models.TextChoices):
        MANUAL = "manual", "Manual"
        AUTOMATED = "automated", "Automated"
        HYBRID = "hybrid", "Hybrid"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(AppUser, on_delete=models.CASCADE, related_name="verification_requests")
    documents = models.ManyToManyField(Document, blank=True)
    request_type = models.CharField(max_length=30, choices=RequestType.choices, default=RequestType.GENERAL)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    identity_verification_status = models.CharField(
        max_length=20,
        choices=VerificationProgressStatus.choices,
        default=VerificationProgressStatus.UNVERIFIED,
    )
    property_document_verification_status = models.CharField(
        max_length=20,
        choices=VerificationProgressStatus.choices,
        default=VerificationProgressStatus.UNVERIFIED,
    )
    physical_property_status = models.CharField(
        max_length=20,
        choices=VerificationProgressStatus.choices,
        default=VerificationProgressStatus.UNVERIFIED,
    )
    verification_method = models.CharField(max_length=20, choices=Method.choices, default=Method.MANUAL)
    confidence_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    automated_decision = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True, default="")
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "-submitted_at"], name="core_verify_status_ct_idx"),
            models.Index(fields=["user", "-submitted_at"], name="core_verify_user_ct_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["user"], name="core_verify_unique_user"),
        ]


class VerificationRecordProvider(models.TextChoices):
    DIKRIPT = "dikript", "Dikript"
    PREMBLY = "prembly", "Prembly"


class _VerificationLookupRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.CharField(max_length=32, choices=VerificationRecordProvider.choices)
    response_payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class NinVerificationRecord(_VerificationLookupRecord):
    nin = models.CharField(max_length=80)

    def __str__(self) -> str:
        return f"{self.provider}: {self.nin}"

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(fields=["provider", "nin"], name="core_ninvr_provider_nin_uniq"),
        ]
        indexes = [
            models.Index(fields=["nin"], name="core_ninvr_nin_idx"),
            models.Index(fields=["provider", "-updated_at"], name="core_ninvr_provider_upd_idx"),
        ]


class BvnVerificationRecord(_VerificationLookupRecord):
    bvn = models.CharField(max_length=80)

    def __str__(self) -> str:
        return f"{self.provider}: {self.bvn}"

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(fields=["provider", "bvn"], name="core_bvnvr_provider_bvn_uniq"),
        ]
        indexes = [
            models.Index(fields=["bvn"], name="core_bvnvr_bvn_idx"),
            models.Index(fields=["provider", "-updated_at"], name="core_bvnvr_provider_upd_idx"),
        ]


class CacVerificationRecord(_VerificationLookupRecord):
    registration_number = models.CharField(max_length=120)

    def __str__(self) -> str:
        return f"{self.provider}: {self.registration_number}"

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(fields=["provider", "registration_number"], name="core_cacvr_provider_reg_uniq"),
        ]
        indexes = [
            models.Index(fields=["registration_number"], name="core_cacvr_reg_idx"),
            models.Index(fields=["provider", "-updated_at"], name="core_cacvr_provider_upd_idx"),
        ]


class TenantProfile(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        UNDER_REVIEW = "under_review", "Under review"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(AppUser, on_delete=models.CASCADE, related_name="tenant_profile")

    # Biodata
    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True, default="")
    last_name = models.CharField(max_length=100)
    date_of_birth = models.DateField()
    gender = models.CharField(max_length=20)
    nationality = models.CharField(max_length=100)
    state_of_origin = models.CharField(max_length=120)
    lga = models.CharField(max_length=120)
    employment_status = models.CharField(max_length=40)

    # Current Residence
    residence_country = models.CharField(max_length=100)
    residence_state = models.CharField(max_length=120)
    residence_city = models.CharField(max_length=120)
    residence_lga = models.CharField(max_length=120)
    residence_address = models.TextField()
    length_of_stay = models.CharField(max_length=100)
    housing_status = models.CharField(max_length=40)

    # JSON sections
    employment_info = models.JSONField(blank=True, null=True)
    financial_info = models.JSONField(blank=True, null=True)
    guarantor_details = models.JSONField(blank=True, null=True)
    landlord_info = models.JSONField(blank=True, null=True)
    rental_history = models.JSONField(blank=True, null=True)
    household_info = models.JSONField(blank=True, null=True)
    social_presence = models.JSONField(blank=True, null=True)
    criminal_declaration = models.JSONField(blank=True, null=True)

    # Supporting documents
    supporting_documents = models.ManyToManyField(Document, blank=True, related_name="tenant_profiles")

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "-submitted_at"], name="core_tenantprof_status_ct_idx"),
            models.Index(fields=["user"], name="core_tenantprof_user_idx"),
        ]

    def __str__(self) -> str:
        return f"TenantProfile({self.user.email})"


class Booking(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        ACTIVE = "active", "Active"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(AppUser, on_delete=models.CASCADE, related_name="bookings")
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="bookings")
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    deposit_paid_at = models.DateTimeField(null=True, blank=True)
    full_rent_paid_at = models.DateTimeField(null=True, blank=True)
    tenant_rental_progress = models.JSONField(default=dict, blank=True)
    landlord_rental_progress = models.JSONField(default=dict, blank=True)
    renewal_reminder_sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "-created_at"], name="core_booking_tenant_ct_idx"),
            models.Index(fields=["listing", "-created_at"], name="core_booking_listing_ct_idx"),
            models.Index(fields=["status", "-created_at"], name="core_booking_status_ct_idx"),
        ]


class Payment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="payments")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_method = models.CharField(max_length=40)
    status = models.CharField(max_length=30, default="pending")
    transaction_id = models.CharField(max_length=120, unique=True)
    provider = models.CharField(max_length=40, default="flutterwave")
    currency = models.CharField(max_length=10, default="NGN")
    bank_name = models.CharField(max_length=120, blank=True, default="")
    card_last4 = models.CharField(max_length=4, blank=True, default="")
    virtual_account_reference = models.CharField(max_length=120, blank=True, default="", db_index=True)
    virtual_account_id = models.CharField(max_length=120, blank=True, default="")
    virtual_account_number = models.CharField(max_length=40, blank=True, default="")
    virtual_account_bank_name = models.CharField(max_length=120, blank=True, default="")
    virtual_account_bank_code = models.CharField(max_length=40, blank=True, default="")
    virtual_account_expiry = models.DateTimeField(null=True, blank=True)
    virtual_account_payload = models.JSONField(blank=True, null=True)
    provider_payload = models.JSONField(blank=True, null=True)
    webhook_data = models.JSONField(blank=True, null=True)
    payment_date = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)


class PaymentSettlement(models.Model):
    class Purpose(models.TextChoices):
        OPERATIONS = "operations", "RentDirect Operations"
        CAUTION_FEE = "caution_fee", "Tenant Caution Fee"
        LANDLORD_RENT = "landlord_rent", "Landlord Rent"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RECIPIENT_CREATED = "recipient_created", "Recipient Created"
        READY = "ready", "Ready"
        PROCESSING = "processing", "Processing"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name="settlements")
    purpose = models.CharField(max_length=30, choices=Purpose.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, default="NGN")
    bank_name = models.CharField(max_length=120)
    bank_code = models.CharField(max_length=40, blank=True, default="")
    account_number = models.CharField(max_length=40)
    account_name = models.CharField(max_length=160, blank=True, default="")
    transfer_recipient_id = models.CharField(max_length=120, blank=True, default="")
    transfer_reference = models.CharField(max_length=120, blank=True, default="", db_index=True)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PENDING)
    provider_payload = models.JSONField(blank=True, null=True)
    transfer_payload = models.JSONField(blank=True, null=True)
    last_error = models.TextField(blank=True, default="")
    transferred_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["payment", "purpose"], name="core_payment_settlement_unique"),
        ]
        indexes = [
            models.Index(fields=["purpose", "status"], name="core_paysettle_purp_stat_idx"),
            models.Index(fields=["transfer_recipient_id"], name="core_paysettle_recipient_idx"),
        ]


class FeaturedPayment(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="featured_payments")
    landlord = models.ForeignKey(AppUser, on_delete=models.CASCADE, related_name="featured_payments")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, default="NGN")
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PENDING)
    provider = models.CharField(max_length=40, default="flutterwave")
    transaction_id = models.CharField(max_length=120, unique=True, null=True, blank=True)
    opay_order_no = models.CharField(max_length=120, blank=True, default="")
    opay_cashier_url = models.URLField(blank=True, default="")
    featured_duration_days = models.PositiveSmallIntegerField(default=30)
    expires_at = models.DateTimeField()
    provider_payload = models.JSONField(blank=True, null=True)
    webhook_data = models.JSONField(blank=True, null=True)
    payment_date = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["landlord", "-created_at"], name="core_featpay_landlord_ct_idx"),
            models.Index(fields=["listing", "status"], name="core_featpay_list_stat_idx"),
        ]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.sync_listing_state()

    def sync_listing_state(self) -> None:
        active_payment = None
        if self.status == self.Status.COMPLETED:
            active_payment = self
        else:
            active_payment = (
                type(self)
                .objects.filter(listing=self.listing, status=self.Status.COMPLETED)
                .exclude(pk=self.pk)
                .order_by("-expires_at", "-updated_at")
                .first()
            )

        next_featured = active_payment is not None
        next_featured_until = active_payment.expires_at if active_payment else None

        listing = self.listing
        updates = []
        if listing.featured != next_featured:
            listing.featured = next_featured
            updates.append("featured")
        if listing.featured_until != next_featured_until:
            listing.featured_until = next_featured_until
            updates.append("featured_until")

        if updates:
            updates.append("updated_at")
            listing.save(update_fields=updates)


class SubscriptionPaymentMethod(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(AppUser, on_delete=models.CASCADE, related_name="subscription_payment_methods")
    provider = models.CharField(max_length=40, default="flutterwave")
    provider_customer_id = models.CharField(max_length=120, db_index=True)
    provider_payment_method_id = models.CharField(max_length=120, unique=True)
    payment_type = models.CharField(max_length=40, default="card")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    card_first6 = models.CharField(max_length=6, blank=True, default="")
    card_last4 = models.CharField(max_length=4, blank=True, default="")
    card_network = models.CharField(max_length=40, blank=True, default="")
    card_expiry_month = models.PositiveSmallIntegerField(null=True, blank=True)
    card_expiry_year = models.PositiveSmallIntegerField(null=True, blank=True)
    provider_payload = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "status"], name="core_subpm_user_status_idx"),
            models.Index(fields=["provider_payment_method_id"], name="core_subpm_provider_idx"),
        ]

    def __str__(self) -> str:
        label = self.provider_payment_method_id
        if self.card_last4:
            label = f"{self.card_network or 'card'} ending {self.card_last4}"
        return f"{self.user.email} {label}"


class SubscriptionPayment(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    class BillingCycle(models.TextChoices):
        MONTHLY = "monthly", "Monthly"
        YEARLY = "yearly", "Yearly"

    class PlanCode(models.TextChoices):
        BRONZE = "bronze", "Bronze"
        SILVER = "silver", "Silver"
        GOLD = "gold", "Gold"
        PLATINUM = "platinum", "Platinum"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(AppUser, on_delete=models.CASCADE, related_name="subscription_payments")
    role = models.CharField(max_length=20, choices=AppUser.Role.choices)
    plan_code = models.CharField(max_length=20, choices=PlanCode.choices)
    billing_cycle = models.CharField(max_length=20, choices=BillingCycle.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, default="NGN")
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PENDING)
    provider = models.CharField(max_length=40, default="flutterwave")
    transaction_id = models.CharField(max_length=120, unique=True, null=True, blank=True)
    cashier_url = models.URLField(blank=True, default="")
    payment_method = models.ForeignKey(
        SubscriptionPaymentMethod,
        on_delete=models.SET_NULL,
        related_name="subscription_payments",
        null=True,
        blank=True,
    )
    provider_charge_id = models.CharField(max_length=120, blank=True, default="", db_index=True)
    recurring_enabled = models.BooleanField(default=False)
    billing_reason = models.CharField(max_length=30, blank=True, default="manual")
    renewed_from = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        related_name="renewal_payments",
        null=True,
        blank=True,
    )
    provider_payload = models.JSONField(blank=True, null=True)
    webhook_data = models.JSONField(blank=True, null=True)
    payment_date = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "-created_at"], name="core_subpay_user_ct_idx"),
            models.Index(fields=["status", "-created_at"], name="core_subpay_status_ct_idx"),
        ]


class Review(models.Model):
    class ReviewType(models.TextChoices):
        PROPERTY = "property", "Property"
        LANDLORD = "landlord", "Landlord"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="reviews")
    tenant = models.ForeignKey(AppUser, on_delete=models.CASCADE, related_name="reviews")
    landlord = models.ForeignKey(AppUser, on_delete=models.CASCADE, related_name="landlord_reviews")
    review_type = models.CharField(max_length=20, choices=ReviewType.choices, default=ReviewType.PROPERTY)
    rating = models.PositiveSmallIntegerField()
    comment = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["listing", "tenant", "review_type"], name="unique_listing_tenant_review_type")]


class Feedback(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(AppUser, on_delete=models.CASCADE, related_name="feedback_entries")
    name = models.CharField(max_length=160)
    role = models.CharField(max_length=20, choices=AppUser.Role.choices)
    topic = models.CharField(max_length=160)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "-created_at"], name="core_feedback_user_ct_idx"),
            models.Index(fields=["role", "-created_at"], name="core_feedback_role_ct_idx"),
        ]


class Favourite(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(AppUser, on_delete=models.CASCADE, related_name="favourites")
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="favourited_by")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "listing"], name="unique_tenant_listing_favourite")]
        indexes = [models.Index(fields=["tenant", "-created_at"], name="core_fav_tenant_ct_idx")]


class Message(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sender = models.ForeignKey(AppUser, on_delete=models.CASCADE, related_name="sent_messages")
    receiver = models.ForeignKey(AppUser, on_delete=models.CASCADE, related_name="received_messages")
    listing = models.ForeignKey(Listing, on_delete=models.SET_NULL, null=True, blank=True, related_name="messages")
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["sender", "-created_at"], name="core_msg_sender_ct_idx"),
            models.Index(fields=["receiver", "-created_at"], name="core_msg_receiver_ct_idx"),
            models.Index(fields=["listing", "created_at"], name="core_msg_listing_ct_idx"),
        ]


class CommunityChatMessage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sender = models.ForeignKey(AppUser, on_delete=models.CASCADE, related_name="community_chat_messages")
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["-created_at"], name="core_commchat_ct_idx"),
            models.Index(fields=["sender", "-created_at"], name="core_commchat_sender_ct_idx"),
        ]


class SupportChatMessage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    thread_user = models.ForeignKey(AppUser, on_delete=models.CASCADE, related_name="support_chat_threads")
    sender = models.ForeignKey(AppUser, on_delete=models.CASCADE, related_name="support_chat_messages")
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["thread_user", "-created_at"], name="core_supportchat_thread_ct_idx"),
            models.Index(fields=["sender", "-created_at"], name="core_supportchat_sender_ct_idx"),
        ]
