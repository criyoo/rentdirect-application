import json
from decimal import Decimal

from django.contrib.auth import authenticate
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers

from .profile_validation import (
    normalize_residence,
    normalize_state_of_origin,
    is_valid_mobile,
    is_valid_nin,
)
from .models import (
    AppUser,
    Booking,
    booking_progress_step_completed,
    booking_progress_step_selected_value,
    build_booking_progress_data,
    Document,
    CommunityChatMessage,
    Feedback,
    Favourite,
    FeaturedPayment,
    get_booking_progress_choice_options,
    get_booking_progress_field_name,
    get_booking_progress_steps,
    listing_has_deposit_secured_booking,
    Listing,
    ListingImage,
    Message,
    normalize_booking_progress,
    Payment,
    PaymentSettlement,
    Review,
    SubscriptionPayment,
    SupportChatMessage,
    TenantProfile,
    VerificationRequest,
)
from .pricing import calculate_booking_total, calculate_remaining_balance, resolve_booking_total
from .subscription_access import user_has_bronze_access
from .tenant_scoring import build_tenant_screening_summary


class UserSerializer(serializers.ModelSerializer):
    profile_photo_url = serializers.CharField(read_only=True)
    is_verified = serializers.BooleanField(read_only=True)

    class Meta:
        model = AppUser
        fields = [
            "id",
            "name",
            "email",
            "role",
            "email_verified",
            "profile_photo_url",
            "mobile",
            "nin_number",
            "bvn_number",
            "state_of_origin",
            "residence",
            "landlord_verification_type",
            "landlord_verification_profile",
            "tenant_verification_profile",
            "is_verified",
        ]
        read_only_fields = ["id", "role", "email_verified", "profile_photo_url", "tenant_verification_profile", "is_verified"]

    def validate_email(self, value):
        return value.strip().lower()

    def validate_mobile(self, value):
        value = value.strip()
        if value and not is_valid_mobile(value):
            raise serializers.ValidationError(
                "Enter an 11 digit mobile number starting with 07, 08, or 09, or a +234 number starting with 70, 71, 80, 81, 90, or 91."
            )
        return value

    def validate_nin_number(self, value):
        value = value.strip()
        if value and not is_valid_nin(value):
            raise serializers.ValidationError("NIN must be exactly 11 digits.")
        return value

    def validate_bvn_number(self, value):
        value = value.strip()
        if value and not is_valid_nin(value):
            raise serializers.ValidationError("BVN must be exactly 11 digits.")
        return value

    def validate_state_of_origin(self, value):
        try:
            return normalize_state_of_origin(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def validate_landlord_verification_type(self, value):
        value = value.strip().lower()
        if value and value not in {
            AppUser.LandlordVerificationType.INDIVIDUAL,
            AppUser.LandlordVerificationType.CORPORATE,
        }:
            raise serializers.ValidationError("Choose either individual or corporate.")
        return value

    def validate_landlord_verification_profile(self, value):
        if value in (None, ""):
            return None
        if not isinstance(value, dict):
            raise serializers.ValidationError("Verification profile must be a JSON object.")
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        instance = getattr(self, "instance", None)

        state_of_origin = attrs.get("state_of_origin", getattr(instance, "state_of_origin", "")).strip()
        residence = attrs.get("residence", getattr(instance, "residence", None))
        try:
            attrs["residence"] = normalize_residence(state_of_origin, residence)
        except ValueError as exc:
            raise serializers.ValidationError({"residence": str(exc)}) from exc

        role = attrs.get("role", getattr(instance, "role", ""))
        verification_type = attrs.get(
            "landlord_verification_type",
            getattr(instance, "landlord_verification_type", ""),
        )
        verification_profile = attrs.get(
            "landlord_verification_profile",
            getattr(instance, "landlord_verification_profile", None),
        )

        if role != AppUser.Role.LANDLORD:
            attrs["landlord_verification_type"] = ""
            attrs["landlord_verification_profile"] = None
        elif verification_profile and not verification_type:
            raise serializers.ValidationError(
                {"landlord_verification_type": "Select individual or corporate before saving verification details."}
            )
        elif isinstance(verification_profile, dict):
            profile_nin = str(verification_profile.get("nin") or "").strip()
            profile_bvn = str(verification_profile.get("bvn") or "").strip()
            if profile_nin:
                if not is_valid_nin(profile_nin):
                    raise serializers.ValidationError({"landlord_verification_profile": {"nin": "NIN must be exactly 11 digits."}})
                attrs.setdefault("nin_number", profile_nin)
            if profile_bvn:
                if not is_valid_nin(profile_bvn):
                    raise serializers.ValidationError({"landlord_verification_profile": {"bvn": "BVN must be exactly 11 digits."}})
                attrs.setdefault("bvn_number", profile_bvn)

        return attrs


class RegisterSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=160)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, max_length=256)
    role = serializers.ChoiceField(choices=[AppUser.Role.TENANT, AppUser.Role.LANDLORD])

    def validate_email(self, value):
        return value.strip().lower()


class VerifyRegistrationSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp_code = serializers.CharField(max_length=12)


class SettingsOtpRequestSerializer(serializers.Serializer):
    purpose = serializers.ChoiceField(choices=["profile", "password"])
    target_email = serializers.EmailField(required=False, allow_blank=True)

    def validate_target_email(self, value):
        return value.strip().lower()


class SettingsPasswordSerializer(serializers.Serializer):
    new_password = serializers.CharField(write_only=True, max_length=256)
    otp_code = serializers.CharField(max_length=12)


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        user = authenticate(username=attrs["email"].strip().lower(), password=attrs["password"])
        if not user:
            raise serializers.ValidationError("Invalid credentials")
        if not user.email_verified:
            raise serializers.ValidationError("Email verification required before login")
        attrs["user"] = user
        return attrs


class ListingImageSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = ListingImage
        fields = ["id", "file_url", "is_cover", "sort_order"]

    def get_file_url(self, obj):
        return obj.file.url if obj.file else ""


class AmenitiesField(serializers.ListField):
    child = serializers.CharField()

    def get_value(self, dictionary):
        if hasattr(dictionary, "getlist"):
            for key in [self.field_name, f"{self.field_name}[]"]:
                values = dictionary.getlist(key)
                if values:
                    return values if len(values) > 1 else values[0]
        return super().get_value(dictionary)

    def to_internal_value(self, data):
        if data in (serializers.empty, None, ""):
            return []

        if isinstance(data, str):
            raw = data.strip()
            if not raw:
                return []
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                data = [raw]
            else:
                if isinstance(parsed, str):
                    data = [parsed]
                elif isinstance(parsed, list):
                    data = parsed
                else:
                    self.fail("not_a_list", input_type=type(parsed).__name__)
        elif isinstance(data, tuple):
            data = list(data)

        items = super().to_internal_value(data)
        return [item.strip() for item in items if item.strip()]


class ListingSerializer(serializers.ModelSerializer):
    landlord_id = serializers.UUIDField(source="landlord.id", read_only=True)
    landlord_name = serializers.CharField(source="landlord.name", read_only=True)
    landlord_profile_photo_url = serializers.CharField(source="landlord.profile_photo_url", read_only=True)
    cover_image_url = serializers.CharField(read_only=True)
    image_urls = serializers.ListField(child=serializers.CharField(), read_only=True)
    images = ListingImageSerializer(many=True, read_only=True)
    amenities = AmenitiesField(required=False)

    class Meta:
        model = Listing
        fields = [
            "id",
            "title",
            "description",
            "address",
            "city",
            "state",
            "postal_code",
            "latitude",
            "longitude",
            "property_type",
            "bedrooms",
            "bathrooms",
            "toilets",
            "square_feet",
            "price_per_year",
            "deposit_amount",
            "utilities_included",
            "pet_friendly",
            "furnished",
            "amenities",
            "available_from",
            "status",
            "featured",
            "featured_until",
            "cover_image_url",
            "image_urls",
            "images",
            "landlord_id",
            "landlord_name",
            "landlord_profile_photo_url",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "featured", "featured_until", "created_at", "updated_at"]

    def validate(self, attrs):
        if attrs.get("price_per_year", Decimal("1")) <= 0:
            raise serializers.ValidationError({"price_per_year": "Price must be positive"})
        if attrs.get("bedrooms", 1) <= 0:
            raise serializers.ValidationError({"bedrooms": "Bedrooms must be positive"})
        if attrs.get("bathrooms", 1) <= 0:
            raise serializers.ValidationError({"bathrooms": "Bathrooms must be positive"})
        if attrs.get("toilets") is not None and attrs.get("toilets", 1) <= 0:
            raise serializers.ValidationError({"toilets": "Toilets must be positive"})
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        user = getattr(request, "user", None)
        user_has_bronze = False
        if getattr(user, "is_authenticated", False) and user.role == AppUser.Role.TENANT:
            cache_key = "_request_user_has_bronze_access"
            if cache_key not in self.context:
                self.context[cache_key] = user_has_bronze_access(user)
            user_has_bronze = self.context[cache_key]
        if user_has_bronze:
            data["address"] = ""
            data["city"] = ""
            data["postal_code"] = ""
            data["latitude"] = None
            data["longitude"] = None
        return data

    @transaction.atomic
    def create(self, validated_data):
        request = self.context["request"]
        validated_data.setdefault("amenities", [])
        listing = Listing.objects.create(landlord=request.user, **validated_data)
        cover = request.FILES.get("cover_image")
        if cover:
            ListingImage.objects.create(listing=listing, file=cover, is_cover=True, sort_order=0)
        for index, image in enumerate(request.FILES.getlist("images")[:9], start=1):
            ListingImage.objects.create(listing=listing, file=image, sort_order=index)
        return listing

    @transaction.atomic
    def update(self, instance, validated_data):
        request = self.context["request"]
        validated_data.setdefault("amenities", instance.amenities or [])

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        cover = request.FILES.get("cover_image")
        additional_images = request.FILES.getlist("images")[:9]

        if cover or additional_images:
            instance.images.all().delete()
            uploaded_images = ([cover] if cover else []) + additional_images
            for index, image in enumerate(uploaded_images):
                ListingImage.objects.create(
                    listing=instance,
                    file=image,
                    is_cover=index == 0,
                    sort_order=index,
                )

        return instance


class DocumentSerializer(serializers.ModelSerializer):
    user_id = serializers.UUIDField(source="owner.id", read_only=True)
    file_url = serializers.CharField(read_only=True)

    class Meta:
        model = Document
        fields = ["id", "title", "content_type", "file", "file_url", "user_id", "created_at"]
        read_only_fields = ["id", "file_url", "user_id", "created_at"]


class VerificationRequestSerializer(serializers.ModelSerializer):
    document_ids = serializers.ListField(child=serializers.UUIDField(), write_only=True, required=False)

    class Meta:
        model = VerificationRequest
        fields = [
            "id",
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
            "document_ids",
        ]
        read_only_fields = [
            "id",
            "status",
            "identity_verification_status",
            "property_document_verification_status",
            "verification_method",
            "confidence_score",
            "automated_decision",
            "submitted_at",
            "reviewed_at",
        ]

    def validate(self, attrs):
        attrs = super().validate(attrs)
        request_type = attrs.get("request_type", VerificationRequest.RequestType.GENERAL)
        physical_property_status = attrs.get(
            "physical_property_status",
            VerificationRequest.VerificationProgressStatus.UNVERIFIED,
        )

        if (
            request_type != VerificationRequest.RequestType.PROPERTY_DOCUMENTS
            and physical_property_status != VerificationRequest.VerificationProgressStatus.UNVERIFIED
        ):
            raise serializers.ValidationError(
                {"physical_property_status": "Physical property status can only be set for property document verification."}
            )

        return attrs


class BookingSerializer(serializers.ModelSerializer):
    tenant_id = serializers.UUIDField(source="tenant.id", read_only=True)
    tenant_name = serializers.CharField(source="tenant.name", read_only=True)
    tenant_email = serializers.EmailField(source="tenant.email", read_only=True)
    listing_id = serializers.UUIDField()
    listing_title = serializers.CharField(source="listing.title", read_only=True)
    listing_address = serializers.CharField(source="listing.address", read_only=True)
    listing_city = serializers.CharField(source="listing.city", read_only=True)
    listing_state = serializers.CharField(source="listing.state", read_only=True)
    listing_cover_image_url = serializers.CharField(source="listing.cover_image_url", read_only=True)
    landlord_id = serializers.UUIDField(source="listing.landlord.id", read_only=True)
    landlord_name = serializers.CharField(source="listing.landlord.name", read_only=True)
    total_amount = serializers.SerializerMethodField()
    remaining_amount = serializers.SerializerMethodField()
    landlord_collected_amount = serializers.SerializerMethodField()
    landlord_expecting_payment_amount = serializers.SerializerMethodField()
    payments = serializers.SerializerMethodField()
    rental_progress = serializers.SerializerMethodField()
    tenant_screening_summary = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = [
            "id",
            "tenant_id",
            "tenant_name",
            "tenant_email",
            "listing_id",
            "listing_title",
            "listing_address",
            "listing_city",
            "listing_state",
            "listing_cover_image_url",
            "landlord_id",
            "landlord_name",
            "start_date",
            "end_date",
            "status",
            "total_amount",
            "paid_amount",
            "remaining_amount",
            "landlord_collected_amount",
            "landlord_expecting_payment_amount",
            "payments",
            "rental_progress",
            "tenant_screening_summary",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "tenant_id",
            "status",
            "total_amount",
            "paid_amount",
            "remaining_amount",
            "landlord_collected_amount",
            "landlord_expecting_payment_amount",
            "payments",
            "created_at",
            "updated_at",
        ]

    def get_payments(self, obj):
        return PaymentSerializer(obj.payments.all(), many=True).data

    def get_total_amount(self, obj):
        return resolve_booking_total(obj.listing.price_per_year, obj.total_amount)

    def get_remaining_amount(self, obj):
        return calculate_remaining_balance(self.get_total_amount(obj), obj.paid_amount)

    def get_landlord_collected_amount(self, obj):
        if not self._request_user_can_view_landlord_financials(obj):
            return None
        return self._sum_landlord_rent_settlements(
            obj,
            statuses={
                PaymentSettlement.Status.RECIPIENT_CREATED,
                PaymentSettlement.Status.READY,
                PaymentSettlement.Status.PAID,
            },
        )

    def get_landlord_expecting_payment_amount(self, obj):
        if not self._request_user_can_view_landlord_financials(obj):
            return None
        return self._sum_landlord_rent_settlements(
            obj,
            exclude_statuses={
                PaymentSettlement.Status.RECIPIENT_CREATED,
                PaymentSettlement.Status.READY,
                PaymentSettlement.Status.PAID,
            },
        )

    def _request_user_can_view_landlord_financials(self, obj):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not getattr(user, "is_authenticated", False):
            return False
        return user.role == AppUser.Role.ADMIN or (
            user.role == AppUser.Role.LANDLORD and obj.listing.landlord_id == user.id
        )

    def _sum_landlord_rent_settlements(self, obj, *, statuses=None, exclude_statuses=None):
        settlements = (
            PaymentSettlement.objects
            .filter(
                payment__booking=obj,
                payment__status="completed",
                purpose=PaymentSettlement.Purpose.LANDLORD_RENT,
            )
        )
        if statuses is not None:
            settlements = settlements.filter(status__in=statuses)
        if exclude_statuses is not None:
            settlements = settlements.exclude(status__in=exclude_statuses)
        total = settlements.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        return total

    def get_rental_progress(self, obj):
        request = self.context.get("request")
        role = getattr(getattr(request, "user", None), "role", "")
        if role not in {AppUser.Role.TENANT, AppUser.Role.LANDLORD}:
            return None
        return build_booking_progress_data(obj, role)

    def get_tenant_screening_summary(self, obj):
        request = self.context.get("request")
        role = getattr(getattr(request, "user", None), "role", "")
        if role not in {AppUser.Role.LANDLORD, AppUser.Role.ADMIN}:
            return None

        try:
            tenant_profile = obj.tenant.tenant_profile
        except TenantProfile.DoesNotExist:
            tenant_profile = None
        return build_tenant_screening_summary(tenant_profile, obj.listing)

    def validate(self, attrs):
        if attrs["end_date"] <= attrs["start_date"]:
            raise serializers.ValidationError({"end_date": "End date must be after start date"})
        return attrs

    def create(self, validated_data):
        request = self.context["request"]
        if request.user.role == AppUser.Role.TENANT and user_has_bronze_access(request.user):
            raise serializers.ValidationError({"detail": "Renting property is not available on the Bronze free plan."})
        listing_id = validated_data.pop("listing_id")
        listing = Listing.objects.get(id=listing_id, status=Listing.Status.AVAILABLE)
        if listing_has_deposit_secured_booking(listing):
            raise serializers.ValidationError({"listing_id": "This property is no longer available for new rental applications."})
        return Booking.objects.create(
            tenant=self.context["request"].user,
            listing=listing,
            total_amount=calculate_booking_total(listing.price_per_year),
            **validated_data,
        )


class RentalProgressUpdateSerializer(serializers.Serializer):
    step_keys = serializers.ListField(child=serializers.CharField(), allow_empty=True, required=False)
    step_responses = serializers.DictField(child=serializers.CharField(), required=False)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        request = self.context["request"]
        booking = self.context["booking"]
        steps = get_booking_progress_steps(request.user.role)
        ordered_step_keys = [key for key, _label in steps]
        valid_step_keys = set(ordered_step_keys)
        step_keys = list(dict.fromkeys(attrs.get("step_keys", [])))
        step_responses = {
            str(key): str(value).strip().lower()
            for key, value in (attrs.get("step_responses") or {}).items()
        }

        if not step_keys and not step_responses:
            raise serializers.ValidationError("Select at least one new progress step to save.")

        invalid_step_keys = [key for key in step_keys if key not in valid_step_keys]
        invalid_step_keys.extend(key for key in step_responses if key not in valid_step_keys)
        if invalid_step_keys:
            raise serializers.ValidationError("One or more selected progress steps are invalid.")

        progress_field = get_booking_progress_field_name(request.user.role)
        current_progress = normalize_booking_progress(getattr(booking, progress_field, {}))
        completed_step_keys = {
            key
            for key in ordered_step_keys
            if booking_progress_step_completed(current_progress, key)
        }

        new_step_keys = []
        for key in step_keys:
            if get_booking_progress_choice_options(key):
                raise serializers.ValidationError({key: "Select Yes or No for this checklist item."})
            if key not in completed_step_keys:
                new_step_keys.append(key)

        new_step_responses: dict[str, str] = {}
        for key, value in step_responses.items():
            allowed_values = {option["value"] for option in get_booking_progress_choice_options(key)}
            if not allowed_values:
                raise serializers.ValidationError({key: "This checklist item does not accept Yes or No responses."})
            if value not in allowed_values:
                raise serializers.ValidationError({key: "Choose either Yes or No."})
            if key not in completed_step_keys:
                new_step_responses[key] = value

        if not new_step_keys and not new_step_responses:
            raise serializers.ValidationError("Select at least one new progress step to save.")

        if len(new_step_keys) + len(new_step_responses) > 1:
            raise serializers.ValidationError("Save one checklist step before moving to the next.")

        for index, step_key in enumerate(ordered_step_keys):
            if step_key not in set(new_step_keys) and step_key not in set(new_step_responses.keys()):
                continue

            missing_prerequisite = next(
                (
                    previous_key
                    for previous_key in ordered_step_keys[:index]
                    if previous_key not in completed_step_keys
                ),
                None,
            )
            if missing_prerequisite:
                raise serializers.ValidationError("Checklist steps must be completed in order.")

        attrs["step_keys"] = new_step_keys
        attrs["step_responses"] = new_step_responses
        return attrs

    def save(self, **kwargs):
        request = self.context["request"]
        booking = self.context["booking"]
        progress_field = get_booking_progress_field_name(request.user.role)
        current_progress = normalize_booking_progress(getattr(booking, progress_field, {})).copy()
        completed_at = timezone.now().isoformat()

        for key in self.validated_data.get("step_keys", []):
            current_progress.setdefault(key, completed_at)

        for key, value in self.validated_data.get("step_responses", {}).items():
            current_progress.setdefault(
                key,
                {
                    "value": value,
                    "completed_at": completed_at,
                },
            )

        setattr(booking, progress_field, current_progress)
        booking.save(update_fields=[progress_field, "updated_at"])
        return booking


class PaymentSerializer(serializers.ModelSerializer):
    booking_id = serializers.UUIDField()

    class Meta:
        model = Payment
        fields = [
            "id",
            "booking_id",
            "amount",
            "payment_method",
            "status",
            "transaction_id",
            "payment_date",
            "created_at",
            "bank_name",
            "card_last4",
            "virtual_account_reference",
            "virtual_account_number",
            "virtual_account_bank_name",
            "virtual_account_bank_code",
            "virtual_account_expiry",
            "currency",
            "provider",
        ]
        read_only_fields = [
            "id",
            "status",
            "transaction_id",
            "payment_date",
            "created_at",
            "currency",
            "provider",
            "virtual_account_reference",
            "virtual_account_number",
            "virtual_account_bank_name",
            "virtual_account_bank_code",
            "virtual_account_expiry",
        ]

    def validate_payment_method(self, value):
        normalized = value.strip().lower()
        if normalized not in {"card", "bank"}:
            raise serializers.ValidationError("Choose either card or bank.")
        return normalized


class FeaturedPaymentSerializer(serializers.ModelSerializer):
    listing_id = serializers.UUIDField()
    landlord_id = serializers.UUIDField(source="landlord.id", read_only=True)

    class Meta:
        model = FeaturedPayment
        fields = ["id", "listing_id", "landlord_id", "amount", "currency", "status", "provider", "transaction_id", "opay_order_no", "opay_cashier_url", "featured_duration_days", "expires_at", "payment_date", "created_at", "updated_at"]
        read_only_fields = ["id", "landlord_id", "amount", "currency", "status", "provider", "transaction_id", "opay_order_no", "opay_cashier_url", "expires_at", "payment_date", "created_at", "updated_at"]


class SubscriptionPaymentRequestSerializer(serializers.Serializer):
    plan_code = serializers.ChoiceField(choices=SubscriptionPayment.PlanCode.choices)
    billing_cycle = serializers.ChoiceField(choices=SubscriptionPayment.BillingCycle.choices)


class SubscriptionPaymentSerializer(serializers.ModelSerializer):
    user_id = serializers.UUIDField(source="user.id", read_only=True)

    class Meta:
        model = SubscriptionPayment
        fields = [
            "id",
            "user_id",
            "role",
            "plan_code",
            "billing_cycle",
            "amount",
            "currency",
            "status",
            "provider",
            "transaction_id",
            "cashier_url",
            "expires_at",
            "payment_date",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class ReviewSerializer(serializers.ModelSerializer):
    tenant_id = serializers.UUIDField(source="tenant.id", read_only=True)
    tenant_name = serializers.CharField(source="tenant.name", read_only=True)
    listing_id = serializers.UUIDField()
    listing_title = serializers.CharField(source="listing.title", read_only=True)
    landlord_id = serializers.UUIDField(source="landlord.id", read_only=True)

    class Meta:
        model = Review
        fields = [
            "id",
            "listing_id",
            "listing_title",
            "tenant_id",
            "tenant_name",
            "landlord_id",
            "rating",
            "comment",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "listing_title", "tenant_id", "tenant_name", "landlord_id", "created_at", "updated_at"]

    def validate_rating(self, value):
        if value < 1 or value > 5:
            raise serializers.ValidationError("Rating must be between 1 and 5")
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        instance = getattr(self, "instance", None)
        next_listing_id = attrs.get("listing_id")
        if instance is not None and next_listing_id and str(next_listing_id) != str(instance.listing_id):
            raise serializers.ValidationError({"listing_id": "Listing cannot be changed for an existing review."})
        return attrs


class FeedbackSerializer(serializers.ModelSerializer):
    user_id = serializers.UUIDField(source="user.id", read_only=True)

    class Meta:
        model = Feedback
        fields = ["id", "user_id", "name", "role", "topic", "message", "created_at", "updated_at"]
        read_only_fields = ["id", "user_id", "created_at", "updated_at"]
        extra_kwargs = {"role": {"required": False}}

    def validate_topic(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Feedback topic is required.")
        return value

    def validate_message(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Feedback message is required.")
        return value


class FavouriteSerializer(serializers.ModelSerializer):
    tenant_id = serializers.UUIDField(source="tenant.id", read_only=True)
    listing = ListingSerializer(read_only=True)
    listing_id = serializers.UUIDField(write_only=True)

    class Meta:
        model = Favourite
        fields = ["id", "tenant_id", "listing", "listing_id", "created_at"]
        read_only_fields = ["id", "tenant_id", "listing", "created_at"]


class MessageSerializer(serializers.ModelSerializer):
    sender_id = serializers.UUIDField(source="sender.id", read_only=True)
    receiver_id = serializers.UUIDField()
    listing_id = serializers.UUIDField(required=False, allow_null=True)

    class Meta:
        model = Message
        fields = ["id", "sender_id", "receiver_id", "listing_id", "content", "created_at"]
        read_only_fields = ["id", "sender_id", "created_at"]

    def create(self, validated_data):
        receiver_id = validated_data.pop("receiver_id")
        listing_id = validated_data.pop("listing_id", None)
        listing = Listing.objects.filter(id=listing_id).first() if listing_id else None
        return Message.objects.create(
            sender=self.context["request"].user,
            receiver=AppUser.objects.get(id=receiver_id),
            listing=listing,
            **validated_data,
        )


class CommunityChatMessageSerializer(serializers.ModelSerializer):
    sender_id = serializers.UUIDField(source="sender.id", read_only=True)
    sender_name = serializers.CharField(source="sender.name", read_only=True)
    sender_photo_url = serializers.CharField(source="sender.profile_photo_url", read_only=True)

    class Meta:
        model = CommunityChatMessage
        fields = ["id", "sender_id", "sender_name", "sender_photo_url", "content", "created_at"]
        read_only_fields = ["id", "sender_id", "sender_name", "sender_photo_url", "created_at"]


class SupportChatMessageSerializer(serializers.ModelSerializer):
    thread_user_id = serializers.UUIDField(source="thread_user.id", read_only=True)
    sender_id = serializers.UUIDField(source="sender.id", read_only=True)
    sender_name = serializers.CharField(source="sender.name", read_only=True)
    sender_role = serializers.CharField(source="sender.role", read_only=True)
    sender_photo_url = serializers.CharField(source="sender.profile_photo_url", read_only=True)
    is_support_message = serializers.SerializerMethodField()

    class Meta:
        model = SupportChatMessage
        fields = [
            "id",
            "thread_user_id",
            "sender_id",
            "sender_name",
            "sender_role",
            "sender_photo_url",
            "is_support_message",
            "content",
            "created_at",
        ]
        read_only_fields = fields

    def get_is_support_message(self, obj):
        return obj.sender_id != obj.thread_user_id


class TenantProfileSerializer(serializers.ModelSerializer):
    document_ids = serializers.ListField(child=serializers.UUIDField(), write_only=True, required=False)
    supporting_document_urls = serializers.SerializerMethodField()

    class Meta:
        model = TenantProfile
        fields = [
            "id", "status", "submitted_at", "updated_at",
            "first_name", "middle_name", "last_name", "date_of_birth", "gender",
            "nationality", "state_of_origin", "lga", "employment_status",
            "residence_country", "residence_state", "residence_city", "residence_lga",
            "residence_address", "length_of_stay", "housing_status",
            "employment_info", "financial_info", "guarantor_details", "landlord_info",
            "rental_history", "household_info", "social_presence", "criminal_declaration",
            "document_ids", "supporting_document_urls",
        ]
        read_only_fields = ["id", "status", "submitted_at", "updated_at", "supporting_document_urls"]
        extra_kwargs = {
            "residence_country": {"allow_blank": True, "required": False},
            "residence_state": {"allow_blank": True, "required": False},
            "residence_city": {"allow_blank": True, "required": False},
            "residence_lga": {"allow_blank": True, "required": False},
            "residence_address": {"allow_blank": True, "required": False},
            "length_of_stay": {"allow_blank": True, "required": False},
            "housing_status": {"allow_blank": True, "required": False},
        }

    def get_supporting_document_urls(self, obj):
        return [doc.file_url for doc in obj.supporting_documents.all()]

    def create(self, validated_data):
        doc_ids = validated_data.pop("document_ids", None)
        profile = TenantProfile.objects.create(**validated_data)
        if doc_ids:
            docs = Document.objects.filter(id__in=doc_ids, owner=validated_data["user"])
            profile.supporting_documents.set(docs)
        return profile

    def update(self, instance, validated_data):
        doc_ids = validated_data.pop("document_ids", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if doc_ids is not None:
            docs = Document.objects.filter(id__in=doc_ids, owner=instance.user)
            instance.supporting_documents.set(docs)
        return instance
