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
    booking_has_paid_rental_deposit,
    build_listing_property_document_title,
    booking_progress_step_completed,
    booking_progress_step_selected_value,
    build_booking_progress_data,
    complete_booking_progress_step,
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
    SubscriptionPaymentMethod,
    SupportChatMessage,
    sync_listing_status_from_rental_progress,
    TenantProfile,
    VerificationRequest,
)
from .pricing import calculate_booking_total, calculate_remaining_balance, resolve_booking_total
from .subscription_access import user_has_gold_access, user_has_silver_access
from .tenant_scoring import build_tenant_screening_summary
from .location_services import decimal_from_float, resolve_city_state_coordinates
from .image_optimization import optimize_listing_image


class UserSerializer(serializers.ModelSerializer):
    profile_photo_url = serializers.CharField(read_only=True)
    is_verified = serializers.BooleanField(read_only=True)
    account_frozen = serializers.SerializerMethodField()

    def get_account_frozen(self, obj):
        return obj.is_account_frozen

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
            "account_frozen",
            "account_frozen_at",
            "account_frozen_until",
            "account_freeze_fee_percentage",
        ]
        read_only_fields = [
            "id",
            "role",
            "email_verified",
            "profile_photo_url",
            "tenant_verification_profile",
            "is_verified",
            "account_frozen",
            "account_frozen_at",
            "account_frozen_until",
            "account_freeze_fee_percentage",
        ]

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

            profile_name = " ".join(
                str(verification_profile.get(part) or "").strip()
                for part in ("first_name", "middle_name", "last_name")
            ).strip()
            if profile_name:
                attrs.setdefault("name", " ".join(profile_name.split()))

            profile_mobile = str(verification_profile.get("contact_number") or "").strip()
            if profile_mobile:
                if not is_valid_mobile(profile_mobile):
                    raise serializers.ValidationError({"landlord_verification_profile": {"contact_number": "Enter a valid mobile number."}})
                attrs.setdefault("mobile", profile_mobile)

            profile_state_of_origin = str(verification_profile.get("state_of_origin") or "").strip()
            if profile_state_of_origin:
                try:
                    attrs.setdefault("state_of_origin", normalize_state_of_origin(profile_state_of_origin))
                except ValueError as exc:
                    raise serializers.ValidationError({"landlord_verification_profile": {"state_of_origin": str(exc)}}) from exc

            profile_residential_information = verification_profile.get("residential_information")
            if isinstance(profile_residential_information, dict):
                profile_residence = {
                    "state": str(profile_residential_information.get("state") or "").strip(),
                    "city": str(profile_residential_information.get("city") or "").strip(),
                    "address": str(profile_residential_information.get("address") or "").strip(),
                }
                if all(profile_residence.values()):
                    try:
                        attrs.setdefault(
                            "residence",
                            normalize_residence(
                                attrs.get("state_of_origin", getattr(instance, "state_of_origin", "")),
                                profile_residence,
                            ),
                        )
                    except ValueError as exc:
                        raise serializers.ValidationError({"landlord_verification_profile": {"residential_information": str(exc)}}) from exc

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
    purpose = serializers.ChoiceField(choices=["profile", "password", "account"])
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
    PROPERTY_VERIFICATION_METHOD_DOCUMENTS = "documents"
    PROPERTY_VERIFICATION_METHOD_IN_PERSON = "in_person"
    DEPOSIT_RATE = Decimal("0.20")

    landlord_id = serializers.UUIDField(source="landlord.id", read_only=True)
    landlord_name = serializers.CharField(source="landlord.name", read_only=True)
    landlord_email = serializers.EmailField(source="landlord.email", read_only=True)
    landlord_profile_photo_url = serializers.CharField(source="landlord.profile_photo_url", read_only=True)
    cover_image_url = serializers.CharField(read_only=True)
    image_urls = serializers.ListField(child=serializers.CharField(), read_only=True)
    images = ListingImageSerializer(many=True, read_only=True)
    amenities = AmenitiesField(required=False)
    ownership_types = AmenitiesField(required=False)
    property_ownership_documents = AmenitiesField(required=False)
    property_documents = serializers.SerializerMethodField()
    distance_km = serializers.SerializerMethodField()
    location_source = serializers.SerializerMethodField()
    property_verification_method = serializers.ChoiceField(
        choices=[PROPERTY_VERIFICATION_METHOD_DOCUMENTS, PROPERTY_VERIFICATION_METHOD_IN_PERSON],
        write_only=True,
        required=False,
    )

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
            "distance_km",
            "location_source",
            "property_type",
            "bedrooms",
            "bathrooms",
            "toilets",
            "square_feet",
            "price_per_year",
            "deposit_amount",
            "utilities_included",
            "pet_friendly",
            "parking",
            "garage",
            "garden",
            "lift",
            "balcony",
            "smart_lock",
            "pop_ceiling",
            "electric_fence",
            "fitted_kitchen",
            "furnished",
            "amenities",
            "ownership_status",
            "ownership_types",
            "property_ownership_documents",
            "property_documents",
            "property_document_submission",
            "property_document_verification_status",
            "physical_property_status",
            "property_verification_method",
            "minimum_rental_duration",
            "maximum_occupancy",
            "smoking_allowed",
            "commercial_activities_allowed",
            "short_let_allowed",
            "student_tenants_allowed",
            "expatriates_allowed",
            "available_from",
            "status",
            "featured",
            "featured_until",
            "cover_image_url",
            "image_urls",
            "images",
            "landlord_id",
            "landlord_name",
            "landlord_email",
            "landlord_profile_photo_url",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "featured",
            "featured_until",
            "property_documents",
            "property_document_submission",
            "property_document_verification_status",
            "physical_property_status",
            "distance_km",
            "location_source",
            "created_at",
            "updated_at",
        ]

    @classmethod
    def calculate_deposit_amount(cls, price_per_year):
        return (Decimal(price_per_year) * cls.DEPOSIT_RATE).quantize(Decimal("0.01"))

    def validate(self, attrs):
        price_per_year = attrs.get("price_per_year")
        if price_per_year is not None and price_per_year <= 0:
            raise serializers.ValidationError({"price_per_year": "Price must be positive"})
        if attrs.get("bedrooms", 1) <= 0:
            raise serializers.ValidationError({"bedrooms": "Bedrooms must be positive"})
        if attrs.get("bathrooms", 1) <= 0:
            raise serializers.ValidationError({"bathrooms": "Bathrooms must be positive"})
        if attrs.get("toilets") is not None and attrs.get("toilets", 1) <= 0:
            raise serializers.ValidationError({"toilets": "Toilets must be positive"})
        if attrs.get("maximum_occupancy") is not None and attrs.get("maximum_occupancy", 1) <= 0:
            raise serializers.ValidationError({"maximum_occupancy": "Maximum occupancy must be positive"})

        existing_latitude = getattr(self.instance, "latitude", None)
        existing_longitude = getattr(self.instance, "longitude", None)
        location_changed = "city" in attrs or "state" in attrs
        if attrs.get("latitude") is None and attrs.get("longitude") is None and (
            existing_latitude is None or existing_longitude is None or location_changed
        ):
            city = attrs.get("city") or getattr(self.instance, "city", "")
            state = attrs.get("state") or getattr(self.instance, "state", "")
            coordinates = resolve_city_state_coordinates(city, state)
            if coordinates:
                attrs["latitude"] = decimal_from_float(coordinates.latitude)
                attrs["longitude"] = decimal_from_float(coordinates.longitude)

        price_for_deposit = price_per_year or getattr(self.instance, "price_per_year", None)
        if price_for_deposit is not None:
            attrs["deposit_amount"] = self.calculate_deposit_amount(price_for_deposit)

        request = self.context.get("request")
        if (
            request
            and request.method == "POST"
            and getattr(request.user, "role", None) == AppUser.Role.LANDLORD
        ):
            errors = {}
            required_text_fields = {
                "title": "Title",
                "description": "Description",
                "address": "Address",
                "city": "City",
                "state": "State",
                "postal_code": "Postal code",
                "property_type": "Property type",
                "minimum_rental_duration": "Minimum rental duration",
            }
            for field, label in required_text_fields.items():
                if not str(attrs.get(field) or "").strip():
                    errors[field] = f"{label} is required."

            required_number_fields = {
                "bedrooms": "Bedrooms",
                "bathrooms": "Bathrooms",
                "toilets": "Toilets",
                "price_per_year": "Price per year",
                "deposit_amount": "Deposit amount",
                "maximum_occupancy": "Maximum occupancy",
            }
            for field, label in required_number_fields.items():
                if attrs.get(field) is None:
                    errors[field] = f"{label} is required."

            if attrs.get("available_from") is None:
                errors["available_from"] = "Available date is required."
            if not attrs.get("amenities"):
                errors["amenities"] = "Add at least one amenity."
            if not attrs.get("ownership_types"):
                errors["ownership_types"] = "Select at least one ownership type."
            if not request.FILES.get("cover_image"):
                errors["cover_image"] = "Cover image is required."
            if not request.FILES.getlist("images"):
                errors["images"] = "Upload at least one additional image."

            verification_method = attrs.get("property_verification_method") or request.data.get("property_verification_method")
            property_documents = request.FILES.getlist("property_documents")
            if verification_method == self.PROPERTY_VERIFICATION_METHOD_DOCUMENTS:
                if not attrs.get("property_ownership_documents"):
                    errors["property_ownership_documents"] = "Select at least one property ownership document type."
                if not property_documents:
                    errors["property_documents"] = "Upload at least one property document."
            elif verification_method != self.PROPERTY_VERIFICATION_METHOD_IN_PERSON:
                errors["property_verification_method"] = "Choose document upload or in-person property verification."

            if errors:
                raise serializers.ValidationError(errors)
        return attrs

    def get_property_documents(self, obj):
        return [
            {
                "id": str(document.id),
                "title": document.title,
                "content_type": document.content_type,
                "file_url": document.file_url,
                "created_at": document.created_at,
            }
            for document in obj.property_documents.all()
        ]

    def get_distance_km(self, obj):
        distance = getattr(obj, "_distance_km", None)
        return distance if distance is not None else None

    def get_location_source(self, obj):
        return getattr(obj, "_location_source", None)

    def _tenant_has_paid_for_listing(self, user, listing):
        cache_key = "_request_user_paid_listing_ids"
        if cache_key not in self.context:
            paid_listing_ids = set()
            bookings = (
                Booking.objects
                .filter(tenant=user)
                .exclude(status=Booking.Status.CANCELLED)
                .select_related("listing")
            )
            for booking in bookings:
                if booking_has_paid_rental_deposit(booking):
                    paid_listing_ids.add(booking.listing_id)
            self.context[cache_key] = paid_listing_ids
        return listing.id in self.context[cache_key]

    def _apply_property_document_submission(self, listing, verification_method: str):
        request = self.context["request"]
        uploaded_documents = []
        property_files = request.FILES.getlist("property_documents")

        for upload in property_files:
            uploaded_documents.append(
                Document.objects.create(
                    owner=request.user,
                    title=build_listing_property_document_title(
                        listing,
                        upload.name,
                        listing.property_ownership_documents,
                    ),
                    file=upload,
                    content_type=getattr(upload, "content_type", ""),
                )
            )

        if uploaded_documents:
            listing.property_documents.add(*uploaded_documents)

        if verification_method or uploaded_documents:
            listing.property_document_submission = {
                "document_types": listing.property_ownership_documents or [],
                "ownership_types": listing.ownership_types or [],
                "in_person_verification_requested": verification_method == self.PROPERTY_VERIFICATION_METHOD_IN_PERSON,
                "uploaded_document_count": len(uploaded_documents),
                "submitted_at": timezone.now().isoformat(),
            }
            listing.property_document_verification_status = VerificationRequest.VerificationProgressStatus.PENDING
            listing.physical_property_status = (
                VerificationRequest.VerificationProgressStatus.PENDING
                if verification_method == self.PROPERTY_VERIFICATION_METHOD_IN_PERSON
                else VerificationRequest.VerificationProgressStatus.UNVERIFIED
            )
            listing.save(
                update_fields=[
                    "property_document_submission",
                    "property_document_verification_status",
                    "physical_property_status",
                    "updated_at",
                ]
            )

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        user = getattr(request, "user", None)
        is_authenticated = getattr(user, "is_authenticated", False)
        is_listing_owner = (
            is_authenticated
            and user.role == AppUser.Role.LANDLORD
            and instance.landlord_id == user.id
        )
        is_admin = is_authenticated and user.role == AppUser.Role.ADMIN
        is_tenant = is_authenticated and user.role == AppUser.Role.TENANT

        tenant_has_paid_for_listing = is_tenant and self._tenant_has_paid_for_listing(user, instance)
        can_view_precise_location = is_admin or is_listing_owner or tenant_has_paid_for_listing
        can_view_city_state = is_authenticated and user.role in {
            AppUser.Role.TENANT,
            AppUser.Role.LANDLORD,
            AppUser.Role.ADMIN,
        }
        can_view_property_verification = is_admin or is_listing_owner
        if is_tenant:
            gold_cache_key = "_request_user_has_gold_access"
            if gold_cache_key not in self.context:
                self.context[gold_cache_key] = user_has_gold_access(user)
            can_view_property_verification = self.context[gold_cache_key]

        if not can_view_city_state:
            data["address"] = ""
            data["city"] = ""
            data["postal_code"] = ""
            data["latitude"] = None
            data["longitude"] = None
        elif not can_view_precise_location:
            data["address"] = ""
            data["postal_code"] = ""
            data["latitude"] = None
            data["longitude"] = None
        if not can_view_property_verification:
            data["property_document_verification_status"] = None
            data["physical_property_status"] = None
        if not (is_admin or is_listing_owner):
            data["ownership_status"] = ""
            data["ownership_types"] = []
            data["property_ownership_documents"] = []
            data["property_documents"] = []
            data["property_document_submission"] = None
            data.pop("landlord_email", None)
        return data

    @transaction.atomic
    def create(self, validated_data):
        request = self.context["request"]
        property_verification_method = validated_data.pop("property_verification_method", "")
        validated_data.setdefault("amenities", [])
        validated_data.setdefault("ownership_types", [])
        validated_data.setdefault("property_ownership_documents", [])
        listing = Listing.objects.create(landlord=request.user, **validated_data)
        cover = request.FILES.get("cover_image")
        if cover:
            ListingImage.objects.create(listing=listing, file=optimize_listing_image(cover), is_cover=True, sort_order=0)
        for index, image in enumerate(request.FILES.getlist("images")[:9], start=1):
            ListingImage.objects.create(listing=listing, file=optimize_listing_image(image), sort_order=index)
        self._apply_property_document_submission(listing, property_verification_method)
        return listing

    @transaction.atomic
    def update(self, instance, validated_data):
        request = self.context["request"]
        property_verification_method = validated_data.pop("property_verification_method", "")
        validated_data.setdefault("amenities", instance.amenities or [])
        validated_data.setdefault("ownership_types", instance.ownership_types or [])
        validated_data.setdefault("property_ownership_documents", instance.property_ownership_documents or [])

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
                    file=optimize_listing_image(image),
                    is_cover=index == 0,
                    sort_order=index,
                )

        self._apply_property_document_submission(instance, property_verification_method)
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
    landlord_rental_amount = serializers.SerializerMethodField()
    landlord_collected_amount = serializers.SerializerMethodField()
    landlord_expecting_payment_amount = serializers.SerializerMethodField()
    landlord_balance_payment_amount = serializers.SerializerMethodField()
    payments = serializers.SerializerMethodField()
    rental_progress = serializers.SerializerMethodField()
    tenant_screening_summary = serializers.SerializerMethodField()
    tenant_key_collection_confirmed = serializers.SerializerMethodField()
    landlord_key_collection_confirmed = serializers.SerializerMethodField()
    keys_collected_confirmed = serializers.SerializerMethodField()

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
            "landlord_rental_amount",
            "landlord_collected_amount",
            "landlord_expecting_payment_amount",
            "landlord_balance_payment_amount",
            "payments",
            "rental_progress",
            "tenant_key_collection_confirmed",
            "landlord_key_collection_confirmed",
            "keys_collected_confirmed",
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
            "landlord_rental_amount",
            "landlord_collected_amount",
            "landlord_expecting_payment_amount",
            "landlord_balance_payment_amount",
            "payments",
            "tenant_key_collection_confirmed",
            "landlord_key_collection_confirmed",
            "keys_collected_confirmed",
            "created_at",
            "updated_at",
        ]

    def get_payments(self, obj):
        return PaymentSerializer(obj.payments.all(), many=True).data

    def get_total_amount(self, obj):
        return resolve_booking_total(obj.listing.price_per_year, obj.total_amount)

    def get_remaining_amount(self, obj):
        if obj.status == Booking.Status.CANCELLED:
            return Decimal("0.00")
        return calculate_remaining_balance(self.get_total_amount(obj), obj.paid_amount)

    def get_landlord_rental_amount(self, obj):
        if not self._request_user_can_view_landlord_financials(obj):
            return None
        return self._landlord_rent_amount(obj)

    def get_landlord_collected_amount(self, obj):
        if not self._request_user_can_view_landlord_financials(obj):
            return None
        collected = self._sum_landlord_rent_settlements(obj, statuses={PaymentSettlement.Status.PAID})
        return min(collected, self._landlord_rent_amount(obj))

    def get_landlord_expecting_payment_amount(self, obj):
        if not self._request_user_can_view_landlord_financials(obj):
            return None
        paid_rent = self._tenant_paid_landlord_rent_amount(obj)
        collected = self.get_landlord_collected_amount(obj) or Decimal("0.00")
        return max(paid_rent - collected, Decimal("0.00"))

    def get_landlord_balance_payment_amount(self, obj):
        if not self._request_user_can_view_landlord_financials(obj):
            return None
        return max(self._landlord_rent_amount(obj) - self._tenant_paid_landlord_rent_amount(obj), Decimal("0.00"))

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

    def _landlord_rent_amount(self, obj):
        return Decimal(obj.listing.price_per_year or 0)

    def _tenant_paid_landlord_rent_amount(self, obj):
        paid_amount = Decimal(obj.paid_amount or 0)
        return min(max(paid_amount, Decimal("0.00")), self._landlord_rent_amount(obj))

    def get_rental_progress(self, obj):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        role = getattr(user, "role", "")
        if role not in {AppUser.Role.TENANT, AppUser.Role.LANDLORD}:
            return None
        if role == AppUser.Role.TENANT and not user_has_silver_access(user):
            return None
        return build_booking_progress_data(obj, role)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if (
            getattr(user, "is_authenticated", False)
            and user.role == AppUser.Role.TENANT
            and not user_has_silver_access(user)
        ):
            data["listing_address"] = ""
            data["listing_city"] = ""
        return data

    def get_tenant_key_collection_confirmed(self, obj):
        progress = obj.tenant_rental_progress if isinstance(obj.tenant_rental_progress, dict) else {}
        return booking_progress_step_completed(progress, "tenant_collected_house_key")

    def get_landlord_key_collection_confirmed(self, obj):
        progress = obj.landlord_rental_progress if isinstance(obj.landlord_rental_progress, dict) else {}
        return booking_progress_step_completed(progress, "tenant_collected_house_key")

    def get_keys_collected_confirmed(self, obj):
        return self.get_tenant_key_collection_confirmed(obj) and self.get_landlord_key_collection_confirmed(obj)

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
        if request.user.role != AppUser.Role.TENANT:
            raise serializers.ValidationError({"detail": "Only tenants can rent properties."})
        if not user_has_silver_access(request.user):
            raise serializers.ValidationError({"detail": "Renting property is available from the Silver plan."})
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
        completed_at = timezone.now().isoformat()

        for key in self.validated_data.get("step_keys", []):
            complete_booking_progress_step(
                booking,
                request.user.role,
                key,
                completed_at=completed_at,
            )

        for key, value in self.validated_data.get("step_responses", {}).items():
            complete_booking_progress_step(
                booking,
                request.user.role,
                key,
                completed_at=completed_at,
                selected_value=value,
            )
        sync_listing_status_from_rental_progress(booking.listing)
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
    recurring = serializers.BooleanField(required=False, default=False)
    payment_method_id = serializers.UUIDField(required=False)
    card = serializers.DictField(required=False)

    def validate_card(self, value):
        required_fields = {
            "encrypted_card_number",
            "encrypted_expiry_month",
            "encrypted_expiry_year",
            "encrypted_cvv",
            "nonce",
        }
        missing_fields = [field for field in required_fields if not str(value.get(field) or "").strip()]
        if missing_fields:
            raise serializers.ValidationError(f"Encrypted card payload is missing: {', '.join(sorted(missing_fields))}.")
        return {field: str(value.get(field) or "").strip() for field in required_fields}

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if attrs.get("recurring"):
            has_existing_method = bool(attrs.get("payment_method_id"))
            has_card = bool(attrs.get("card"))
            if not has_existing_method and not has_card:
                raise serializers.ValidationError({"card": "Card details are required to enable recurring payments."})
            if has_existing_method and has_card:
                raise serializers.ValidationError({"card": "Choose a saved card or submit a new card, not both."})
        return attrs


class SubscriptionPaymentMethodSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionPaymentMethod
        fields = [
            "id",
            "provider",
            "payment_type",
            "status",
            "card_last4",
            "card_network",
            "card_expiry_month",
            "card_expiry_year",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class SubscriptionPaymentSerializer(serializers.ModelSerializer):
    user_id = serializers.UUIDField(source="user.id", read_only=True)
    payment_method = SubscriptionPaymentMethodSerializer(read_only=True)
    next_action_url = serializers.SerializerMethodField()

    def get_next_action_url(self, obj):
        payload = obj.provider_payload if isinstance(obj.provider_payload, dict) else {}
        charge_payload = payload.get("charge") if isinstance(payload.get("charge"), dict) else payload
        try:
            from .flutterwave import extract_next_action_url
        except ImportError:
            return ""
        return extract_next_action_url(charge_payload)

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
            "provider_charge_id",
            "recurring_enabled",
            "billing_reason",
            "payment_method",
            "next_action_url",
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
            "review_type",
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
        next_review_type = attrs.get("review_type")
        if instance is not None and next_review_type and next_review_type != instance.review_type:
            raise serializers.ValidationError({"review_type": "Review type cannot be changed for an existing review."})
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

    def validate_financial_info(self, value):
        if not isinstance(value, dict):
            return value

        normalized = dict(value)
        if not normalized.get("current_annual_rent") and normalized.get("current_rent_amount"):
            normalized["current_annual_rent"] = normalized["current_rent_amount"]
        normalized.pop("current_rent_amount", None)
        return normalized

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        financial_info = dict(representation.get("financial_info") or {})
        if not financial_info.get("current_annual_rent") and financial_info.get("current_rent_amount"):
            financial_info["current_annual_rent"] = financial_info["current_rent_amount"]
        financial_info.pop("current_rent_amount", None)
        representation["financial_info"] = financial_info
        return representation

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
            instance.supporting_documents.add(*docs)
        return instance
