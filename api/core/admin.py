from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm
from django.utils import timezone
from django.utils.html import format_html_join

from .models import AdminUser, AppUser, Booking, Document, Feedback, Favourite, FeaturedPayment, Landlord, LandlordProfile, Listing, ListingImage, Message, Payment, PaymentSettlement, Review, SubscriptionPayment, Tenant, TenantProfile, VerificationRequest


PREFERRED_CONTACT_METHOD_CHOICES = (
    ("email", "Email"),
    ("sms", "SMS"),
    ("call", "Call"),
    ("whatsapp", "Whatsapp"),
)

PROOF_OF_ADDRESS_CHOICES = (
    ("Utility Bill", "Utility Bill"),
    ("Bank Statement", "Bank Statement"),
    ("Tenancy Agreement", "Tenancy Agreement"),
)

OWNERSHIP_TYPE_CHOICES = (
    ("Sole Owner", "Sole Owner"),
    ("Joint Owner", "Joint Owner"),
    ("Family Property Representative", "Family Property Representative"),
    ("Attorney/Power of Attorney Holder", "Attorney/Power of Attorney Holder"),
    ("Property Manager", "Property Manager"),
    ("Trustee", "Trustee"),
    ("Mortgage Holder in Possession", "Mortgage Holder in Possession"),
    ("Developer-Owned Property", "Developer-Owned Property"),
)

KYC_TYPE_CHOICES = (
    ("National ID (NIN)", "National ID (NIN)"),
    ("International Passport", "International Passport"),
    ("Driver's License", "Driver's License"),
    ("Voter's Card", "Voter's Card"),
)


def _as_dict(value):
    return value if isinstance(value, dict) else {}


def _as_string_list(value):
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _build_full_name(first_name, middle_name, last_name):
    return " ".join(part for part in [first_name.strip(), middle_name.strip(), last_name.strip()] if part)


def _split_full_name(value):
    parts = [part for part in str(value).strip().split() if part]
    return (
        parts[0] if parts else "",
        " ".join(parts[1:-1]) if len(parts) > 2 else "",
        parts[-1] if len(parts) > 1 else "",
    )


def _build_residence_payload(state, city, address, origin_country, origin_city):
    payload = {
        "state": state.strip(),
        "city": city.strip(),
        "address": address.strip(),
        "origin_country": origin_country.strip(),
        "origin_city": origin_city.strip(),
    }
    if not any(payload.values()):
        return None
    return payload


class LandlordProfileAdminForm(UserChangeForm):
    first_name = forms.CharField(required=False, label="First Name")
    middle_name = forms.CharField(required=False, label="Middle Name")
    last_name = forms.CharField(required=False, label="Last Name")
    date_of_birth = forms.DateField(
        required=False,
        label="Date of Birth",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    gender = forms.CharField(required=False, label="Gender")
    nationality = forms.CharField(required=False, label="Nationality")
    lga_of_origin = forms.CharField(required=False, label="LGA")
    preferred_contact_method = forms.ChoiceField(
        required=False,
        label="Preferred Contact Method",
        choices=(("", "---------"), *PREFERRED_CONTACT_METHOD_CHOICES),
    )
    bio = forms.CharField(required=False, label="Bio/About Me", widget=forms.Textarea(attrs={"rows": 4}))
    phone_number = forms.CharField(required=False, label="Phone Number")
    whatsapp_number = forms.CharField(required=False, label="WhatsApp Number")
    email_address = forms.EmailField(required=False, label="Email Address")
    id_type = forms.ChoiceField(
        required=False,
        label="ID Type",
        choices=(("", "---------"), *KYC_TYPE_CHOICES),
    )
    id_number = forms.CharField(required=False, label="ID Number")
    id_expiry_date = forms.DateField(
        required=False,
        label="Expiry Date",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    residential_country = forms.CharField(required=False, label="Country")
    residential_state = forms.CharField(required=False, label="State")
    residential_city = forms.CharField(required=False, label="City")
    residential_address = forms.CharField(required=False, label="Address", widget=forms.Textarea(attrs={"rows": 4}))
    proof_of_address = forms.MultipleChoiceField(
        required=False,
        label="Proof of Address",
        choices=PROOF_OF_ADDRESS_CHOICES,
        widget=forms.CheckboxSelectMultiple,
    )
    ownership_types = forms.MultipleChoiceField(
        required=False,
        label="Ownership Type",
        choices=OWNERSHIP_TYPE_CHOICES,
        widget=forms.CheckboxSelectMultiple,
    )
    bank_name = forms.CharField(required=False, label="Bank Name")
    account_name = forms.CharField(required=False, label="Account Name")
    account_number = forms.CharField(required=False, label="Account Number")
    minimum_lease_duration = forms.CharField(
        required=False,
        label="Minimum Lease Duration",
        widget=forms.TextInput(attrs={"type": "number", "min": 1}),
    )
    maximum_occupancy = forms.CharField(
        required=False,
        label="Maximum Occupancy",
        widget=forms.TextInput(attrs={"type": "number", "min": 1}),
    )
    pets_allowed = forms.BooleanField(required=False, label="Pets Allowed")
    smoking_allowed = forms.BooleanField(required=False, label="Smoking Allowed")
    commercial_activities_allowed = forms.BooleanField(required=False, label="Commercial Activities Allowed")
    short_let_allowed = forms.BooleanField(required=False, label="Short-let Allowed")
    student_tenants_allowed = forms.BooleanField(required=False, label="Student Tenants Allowed")
    corp_members_allowed = forms.BooleanField(required=False, label="Corp Members Allowed")
    expatriates_allowed = forms.BooleanField(required=False, label="Expatriates Allowed")
    emergency_first_name = forms.CharField(required=False, label="First Name")
    emergency_middle_name = forms.CharField(required=False, label="Middle Name")
    emergency_last_name = forms.CharField(required=False, label="Last Name")
    emergency_phone_number = forms.CharField(required=False, label="Phone Number")
    emergency_email = forms.EmailField(required=False, label="Email")
    emergency_relationship = forms.CharField(required=False, label="Relationship")
    emergency_address = forms.CharField(required=False, label="Address", widget=forms.Textarea(attrs={"rows": 4}))
    residence_state = forms.CharField(required=False, label="Residence State")
    residence_city = forms.CharField(required=False, label="Residence City")
    residence_address = forms.CharField(required=False, label="Residence Address", widget=forms.Textarea(attrs={"rows": 3}))
    origin_country = forms.CharField(required=False, label="Country of Origin")
    origin_city = forms.CharField(required=False, label="City of Origin")
    company_name = forms.CharField(required=False, label="Company Name")
    business_state = forms.CharField(required=False, label="State")
    business_city = forms.CharField(required=False, label="City")
    business_address = forms.CharField(required=False, label="Business Address", widget=forms.Textarea(attrs={"rows": 4}))
    company_phone_number = forms.CharField(required=False, label="Company Phone Number")
    company_email = forms.EmailField(required=False, label="Company Email")
    contact_person_name = forms.CharField(required=False, label="Contact Person Name")
    contact_person_position = forms.CharField(required=False, label="Contact Person Position")
    cac_registration_number = forms.CharField(required=False, label="CAC Registration Number")
    tax_identification_number = forms.CharField(required=False, label="Tax Identification Number")

    class Meta(UserChangeForm.Meta):
        model = LandlordProfile
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        profile = _as_dict(getattr(self.instance, "landlord_verification_profile", None))
        kyc = _as_dict(profile.get("kyc"))
        residential_information = _as_dict(profile.get("residential_information"))
        banking_information = _as_dict(profile.get("banking_information"))
        corporate_banking_information = _as_dict(profile.get("corporate_banking_information"))
        rental_preferences = _as_dict(profile.get("rental_preferences"))
        emergency_contact = _as_dict(profile.get("emergency_contact"))
        residence = _as_dict(getattr(self.instance, "residence", None))
        first_name, middle_name, last_name = _split_full_name(getattr(self.instance, "name", ""))

        self.initial.update(
            {
                "first_name": str(profile.get("first_name") or first_name),
                "middle_name": str(profile.get("middle_name") or middle_name),
                "last_name": str(profile.get("last_name") or last_name),
                "date_of_birth": profile.get("date_of_birth", ""),
                "gender": str(profile.get("gender", "")),
                "nationality": str(profile.get("nationality", "")),
                "lga_of_origin": str(profile.get("lga_of_origin", "")),
                "preferred_contact_method": str(profile.get("preferred_contact_method", "")),
                "bio": str(profile.get("bio") or profile.get("about_me") or ""),
                "phone_number": str(profile.get("contact_number") or getattr(self.instance, "mobile", "")),
                "whatsapp_number": str(profile.get("whatsapp_number", "")),
                "email_address": str(profile.get("email") or getattr(self.instance, "email", "")),
                "id_type": str(kyc.get("id_type", "")),
                "id_number": str(kyc.get("id_number") or profile.get("nin") or getattr(self.instance, "nin_number", "")),
                "id_expiry_date": kyc.get("expiry_date", ""),
                "residential_country": str(residential_information.get("country", "")),
                "residential_state": str(residential_information.get("state", "")),
                "residential_city": str(residential_information.get("city", "")),
                "residential_address": str(residential_information.get("address", "")),
                "proof_of_address": _as_string_list(profile.get("proof_of_address")),
                "ownership_types": _as_string_list(profile.get("ownership_types")),
                "bank_name": str(profile.get("bank_name") or banking_information.get("bank_name") or corporate_banking_information.get("bank_name") or ""),
                "account_name": str(profile.get("account_name") or banking_information.get("account_name") or corporate_banking_information.get("account_name") or ""),
                "account_number": str(profile.get("account_number") or banking_information.get("account_number") or corporate_banking_information.get("account_number") or ""),
                "minimum_lease_duration": str(rental_preferences.get("minimum_lease_duration", "")),
                "maximum_occupancy": str(rental_preferences.get("maximum_occupancy", "")),
                "pets_allowed": bool(rental_preferences.get("pets_allowed")),
                "smoking_allowed": bool(rental_preferences.get("smoking_allowed")),
                "commercial_activities_allowed": bool(rental_preferences.get("commercial_activities_allowed")),
                "short_let_allowed": bool(rental_preferences.get("short_let_allowed")),
                "student_tenants_allowed": bool(rental_preferences.get("student_tenants_allowed")),
                "corp_members_allowed": bool(rental_preferences.get("corp_members_allowed")),
                "expatriates_allowed": bool(rental_preferences.get("expatriates_allowed")),
                "emergency_first_name": str(emergency_contact.get("first_name", "")),
                "emergency_middle_name": str(emergency_contact.get("middle_name", "")),
                "emergency_last_name": str(emergency_contact.get("last_name", "")),
                "emergency_phone_number": str(emergency_contact.get("phone_number", "")),
                "emergency_email": str(emergency_contact.get("email", "")),
                "emergency_relationship": str(emergency_contact.get("relationship", "")),
                "emergency_address": str(emergency_contact.get("address", "")),
                "residence_state": str(residence.get("state", "")),
                "residence_city": str(residence.get("city", "")),
                "residence_address": str(residence.get("address", "")),
                "origin_country": str(residence.get("origin_country", "")),
                "origin_city": str(residence.get("origin_city", "")),
                "company_name": str(profile.get("company_name", "")),
                "business_state": str(profile.get("business_state") or residence.get("state", "")),
                "business_city": str(profile.get("business_city") or residence.get("city", "")),
                "business_address": str(profile.get("business_address") or residence.get("address", "")),
                "company_phone_number": str(profile.get("company_phone_number") or getattr(self.instance, "mobile", "")),
                "company_email": str(profile.get("company_email") or getattr(self.instance, "email", "")),
                "contact_person_name": str(profile.get("contact_person_name") or getattr(self.instance, "name", "")),
                "contact_person_position": str(profile.get("contact_person_position", "")),
                "cac_registration_number": str(profile.get("cac_registration_number", "")),
                "tax_identification_number": str(profile.get("tax_identification_number", "")),
            }
        )

    def save(self, commit=True):
        user = super().save(commit=False)
        profile = dict(_as_dict(user.landlord_verification_profile))
        verification_type = user.landlord_verification_type

        individual_fields = {
            "first_name",
            "middle_name",
            "last_name",
            "date_of_birth",
            "gender",
            "nationality",
            "state_of_origin",
            "lga_of_origin",
            "preferred_contact_method",
            "bio",
            "phone_number",
            "whatsapp_number",
            "email_address",
            "id_type",
            "id_number",
            "id_expiry_date",
            "residential_country",
            "residential_state",
            "residential_city",
            "residential_address",
            "proof_of_address",
            "ownership_types",
            "bank_name",
            "account_name",
            "account_number",
            "minimum_lease_duration",
            "maximum_occupancy",
            "pets_allowed",
            "smoking_allowed",
            "commercial_activities_allowed",
            "short_let_allowed",
            "student_tenants_allowed",
            "corp_members_allowed",
            "expatriates_allowed",
            "emergency_first_name",
            "emergency_middle_name",
            "emergency_last_name",
            "emergency_phone_number",
            "emergency_email",
            "emergency_relationship",
            "emergency_address",
        }
        corporate_fields = {
            "company_name",
            "business_state",
            "business_city",
            "business_address",
            "company_phone_number",
            "company_email",
            "contact_person_name",
            "contact_person_position",
            "cac_registration_number",
            "tax_identification_number",
            "bank_name",
            "account_name",
            "account_number",
        }
        residence_fields = {"residence_state", "residence_city", "residence_address", "origin_country", "origin_city"}

        if verification_type == AppUser.LandlordVerificationType.INDIVIDUAL or individual_fields.intersection(self.changed_data):
            first_name = self.cleaned_data.get("first_name", "").strip()
            middle_name = self.cleaned_data.get("middle_name", "").strip()
            last_name = self.cleaned_data.get("last_name", "").strip()
            phone_number = self.cleaned_data.get("phone_number", "").strip()
            email_address = self.cleaned_data.get("email_address", "").strip().lower()
            id_type = self.cleaned_data.get("id_type", "").strip()
            id_number = self.cleaned_data.get("id_number", "").strip()
            bio = self.cleaned_data.get("bio", "").strip()

            profile.update(
                {
                    "first_name": first_name,
                    "middle_name": middle_name,
                    "last_name": last_name,
                    "date_of_birth": self.cleaned_data.get("date_of_birth").isoformat() if self.cleaned_data.get("date_of_birth") else "",
                    "gender": self.cleaned_data.get("gender", "").strip(),
                    "nationality": self.cleaned_data.get("nationality", "").strip(),
                    "state_of_origin": self.cleaned_data.get("state_of_origin", "").strip(),
                    "lga_of_origin": self.cleaned_data.get("lga_of_origin", "").strip(),
                    "preferred_contact_method": self.cleaned_data.get("preferred_contact_method", "").strip(),
                    "bio": bio,
                    "about_me": bio,
                    "contact_number": phone_number,
                    "whatsapp_number": self.cleaned_data.get("whatsapp_number", "").strip(),
                    "email": email_address,
                    "proof_of_address": list(self.cleaned_data.get("proof_of_address", [])),
                    "ownership_types": list(self.cleaned_data.get("ownership_types", [])),
                    "kyc": {
                        "id_type": id_type,
                        "id_number": id_number,
                        "expiry_date": self.cleaned_data.get("id_expiry_date").isoformat() if self.cleaned_data.get("id_expiry_date") else "",
                    },
                    "residential_information": {
                        "country": self.cleaned_data.get("residential_country", "").strip(),
                        "state": self.cleaned_data.get("residential_state", "").strip(),
                        "city": self.cleaned_data.get("residential_city", "").strip(),
                        "address": self.cleaned_data.get("residential_address", "").strip(),
                    },
                    "banking_information": {
                        "bank_name": self.cleaned_data.get("bank_name", "").strip(),
                        "account_name": self.cleaned_data.get("account_name", "").strip(),
                        "account_number": self.cleaned_data.get("account_number", "").strip(),
                    },
                    "rental_preferences": {
                        "minimum_lease_duration": self.cleaned_data.get("minimum_lease_duration", "").strip(),
                        "maximum_occupancy": self.cleaned_data.get("maximum_occupancy", "").strip(),
                        "pets_allowed": self.cleaned_data.get("pets_allowed", False),
                        "smoking_allowed": self.cleaned_data.get("smoking_allowed", False),
                        "commercial_activities_allowed": self.cleaned_data.get("commercial_activities_allowed", False),
                        "short_let_allowed": self.cleaned_data.get("short_let_allowed", False),
                        "student_tenants_allowed": self.cleaned_data.get("student_tenants_allowed", False),
                        "corp_members_allowed": self.cleaned_data.get("corp_members_allowed", False),
                        "expatriates_allowed": self.cleaned_data.get("expatriates_allowed", False),
                    },
                    "emergency_contact": {
                        "first_name": self.cleaned_data.get("emergency_first_name", "").strip(),
                        "middle_name": self.cleaned_data.get("emergency_middle_name", "").strip(),
                        "last_name": self.cleaned_data.get("emergency_last_name", "").strip(),
                        "phone_number": self.cleaned_data.get("emergency_phone_number", "").strip(),
                        "email": self.cleaned_data.get("emergency_email", "").strip().lower(),
                        "relationship": self.cleaned_data.get("emergency_relationship", "").strip(),
                        "address": self.cleaned_data.get("emergency_address", "").strip(),
                    },
                }
            )

            full_name = _build_full_name(first_name, middle_name, last_name)
            if full_name:
                user.name = full_name
            if email_address:
                user.email = email_address
            user.mobile = phone_number
            user.state_of_origin = self.cleaned_data.get("state_of_origin", "").strip()
            if id_type == "National ID (NIN)" and id_number:
                user.nin_number = id_number
                profile["nin"] = id_number

        if verification_type == AppUser.LandlordVerificationType.CORPORATE or corporate_fields.intersection(self.changed_data):
            profile.update(
                {
                    "company_name": self.cleaned_data.get("company_name", "").strip(),
                    "business_state": self.cleaned_data.get("business_state", "").strip(),
                    "business_city": self.cleaned_data.get("business_city", "").strip(),
                    "business_address": self.cleaned_data.get("business_address", "").strip(),
                    "company_phone_number": self.cleaned_data.get("company_phone_number", "").strip(),
                    "company_email": self.cleaned_data.get("company_email", "").strip().lower(),
                    "contact_person_name": self.cleaned_data.get("contact_person_name", "").strip(),
                    "contact_person_position": self.cleaned_data.get("contact_person_position", "").strip(),
                    "cac_registration_number": self.cleaned_data.get("cac_registration_number", "").strip(),
                    "tax_identification_number": self.cleaned_data.get("tax_identification_number", "").strip(),
                    "nin": self.cleaned_data.get("nin_number", "").strip(),
                    "bvn": self.cleaned_data.get("bvn_number", "").strip(),
                    "bank_name": self.cleaned_data.get("bank_name", "").strip(),
                    "account_name": self.cleaned_data.get("account_name", "").strip(),
                    "account_number": self.cleaned_data.get("account_number", "").strip(),
                    "corporate_banking_information": {
                        "bank_name": self.cleaned_data.get("bank_name", "").strip(),
                        "account_name": self.cleaned_data.get("account_name", "").strip(),
                        "account_number": self.cleaned_data.get("account_number", "").strip(),
                    },
                }
            )

        if residence_fields.intersection(self.changed_data):
            user.residence = _build_residence_payload(
                self.cleaned_data.get("residence_state", ""),
                self.cleaned_data.get("residence_city", ""),
                self.cleaned_data.get("residence_address", ""),
                self.cleaned_data.get("origin_country", ""),
                self.cleaned_data.get("origin_city", ""),
            )

        user.landlord_verification_profile = profile or None

        if commit:
            user.save()
            self.save_m2m()
        return user


@admin.register(AppUser)
class AppUserAdmin(UserAdmin):
    model = AppUser
    list_display = ("email", "name", "role", "email_verified", "is_active", "created_at")
    list_filter = ("role", "email_verified", "is_active")
    ordering = ("email",)
    search_fields = ("email", "name")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Profile", {"fields": ("name", "role", "mobile", "profile_photo", "nin_number", "state_of_origin", "residence")}),
        ("Verification", {"fields": ("email_verified",)}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "created_at", "updated_at")}),
    )
    readonly_fields = ("created_at", "updated_at")
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "name", "role", "password1", "password2")}),
    )

    def get_model_perms(self, request):
        return {}


class RoleAdminMixin:
    role = ""

    def get_queryset(self, request):
        return super().get_queryset(request).filter(role=self.role)

    def save_model(self, request, obj, form, change):
        obj.role = self.role
        super().save_model(request, obj, form, change)

    def get_model_perms(self, request):
        return {
            "add": self.has_add_permission(request),
            "change": self.has_change_permission(request),
            "delete": self.has_delete_permission(request),
            "view": self.has_view_permission(request),
        }


@admin.register(Tenant)
class TenantAdmin(RoleAdminMixin, AppUserAdmin):
    role = AppUser.Role.TENANT
    list_display = ("email", "name", "email_verified", "is_active", "created_at")
    list_filter = ("email_verified", "is_active")


@admin.register(Landlord)
class LandlordAdmin(RoleAdminMixin, AppUserAdmin):
    role = AppUser.Role.LANDLORD
    list_display = ("email", "name", "email_verified", "is_active", "created_at")
    list_filter = ("email_verified", "is_active")


@admin.register(LandlordProfile)
class LandlordProfileAdmin(RoleAdminMixin, AppUserAdmin):
    form = LandlordProfileAdminForm
    role = AppUser.Role.LANDLORD
    list_display = ("email", "name", "landlord_track", "has_profile_details", "email_verified", "updated_at")
    list_filter = ("landlord_verification_type", "email_verified", "is_active")
    search_fields = ("email", "name", "mobile", "nin_number")
    readonly_fields = AppUserAdmin.readonly_fields + ("property_document_summary",)

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return self.add_fieldsets

        common = [
            (None, {"fields": ("password",)}),
            ("Landlord Account", {"fields": ("landlord_verification_type", "profile_photo", "email_verified")}),
        ]
        individual = [
            (
                "Personal Information",
                {
                    "fields": (
                        ("first_name", "middle_name", "last_name"),
                        ("date_of_birth", "gender"),
                        ("nationality", "state_of_origin", "lga_of_origin"),
                        "preferred_contact_method",
                        "bio",
                    )
                },
            ),
            ("Contact Information", {"fields": (("phone_number", "whatsapp_number", "email_address"),)}),
            ("Identity Verification (KYC)", {"fields": (("id_type", "id_number", "id_expiry_date"),)}),
            (
                "Residential Information",
                {
                    "fields": (
                        ("residential_country", "residential_state", "residential_city"),
                        "residential_address",
                        "proof_of_address",
                    )
                },
            ),
            (
                "Property Ownership Verification",
                {"fields": ("ownership_types", "property_document_summary")},
            ),
            ("Banking Information", {"fields": (("bank_name", "account_name", "account_number"),)}),
            (
                "Rental Preferences",
                {
                    "fields": (
                        ("minimum_lease_duration", "maximum_occupancy"),
                        ("pets_allowed", "smoking_allowed", "commercial_activities_allowed"),
                        ("short_let_allowed", "student_tenants_allowed", "corp_members_allowed", "expatriates_allowed"),
                    )
                },
            ),
            (
                "Emergency Contact",
                {
                    "fields": (
                        ("emergency_first_name", "emergency_middle_name", "emergency_last_name"),
                        ("emergency_phone_number", "emergency_email", "emergency_relationship"),
                        "emergency_address",
                    )
                },
            ),
        ]
        corporate = [
            (
                "Account Information",
                {
                    "fields": (
                        "name",
                        ("email", "mobile"),
                        ("nin_number", "bvn_number", "state_of_origin"),
                    )
                },
            ),
            (
                "Residential Information",
                {
                    "fields": (
                        ("residence_state", "residence_city"),
                        "residence_address",
                        ("origin_country", "origin_city"),
                    )
                },
            ),
            (
                "Corporate Landlord Information",
                {
                    "fields": (
                        "company_name",
                        ("business_state", "business_city"),
                        "business_address",
                        ("company_phone_number", "company_email"),
                        ("contact_person_name", "contact_person_position"),
                        ("cac_registration_number", "tax_identification_number"),
                        "property_document_summary",
                    )
                },
            ),
            ("Corporate Banking Information", {"fields": (("bank_name", "account_name", "account_number"),)}),
        ]
        footer = [
            ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
            ("Important dates", {"fields": ("last_login", "created_at", "updated_at")}),
        ]

        if obj.landlord_verification_type == AppUser.LandlordVerificationType.INDIVIDUAL:
            return common + individual + footer
        if obj.landlord_verification_type == AppUser.LandlordVerificationType.CORPORATE:
            return common + corporate + footer
        return common + corporate + individual + footer

    @admin.display(ordering="landlord_verification_type", description="Track")
    def landlord_track(self, obj):
        if not obj.landlord_verification_type:
            return "Not set"
        return dict(AppUser.LandlordVerificationType.choices).get(
            obj.landlord_verification_type,
            obj.landlord_verification_type,
        )

    @admin.display(boolean=True, description="Profile")
    def has_profile_details(self, obj):
        return bool(obj.landlord_verification_profile)

    @admin.display(description="Ownership Documents")
    def property_document_summary(self, obj):
        profile = _as_dict(obj.landlord_verification_profile)
        submission = _as_dict(profile.get("property_document_submission"))
        document_types = _as_string_list(submission.get("document_types"))
        lines = []

        if document_types:
            lines.append(f"Selected document types: {', '.join(document_types)}")
        if submission.get("in_person_verification_requested"):
            lines.append("In-person verification requested.")
        submitted_at = submission.get("submitted_at")
        if submitted_at:
            lines.append(f"Submitted at: {submitted_at}")
        uploaded_document_count = submission.get("uploaded_document_count")
        if uploaded_document_count not in (None, ""):
            lines.append(f"Uploaded documents: {uploaded_document_count}")

        if not lines:
            return "No ownership documents submitted yet."

        return format_html_join("<br>", "{}", ((line,) for line in lines))


@admin.register(AdminUser)
class AdminUserAdmin(RoleAdminMixin, AppUserAdmin):
    role = AppUser.Role.ADMIN
    list_display = ("email", "name", "email_verified", "is_active", "created_at")
    list_filter = ("email_verified", "is_active")


class ListingImageInline(admin.TabularInline):
    model = ListingImage
    extra = 0


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = ("title", "city", "landlord", "price_per_year", "status", "featured", "created_at")
    list_filter = ("status", "featured", "city", "property_type")
    search_fields = ("title", "description", "address", "city", "landlord__email")
    inlines = [ListingImageInline]


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("owner_email", "title")
    search_fields = ("owner__email", "owner__name", "title")
    autocomplete_fields = ("owner",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("owner")

    @admin.display(ordering="owner__email", description="Email")
    def owner_email(self, obj):
        return obj.owner.email


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("tenant_email", "start_date", "end_date", "status", "total_amount")
    list_filter = ("status", "start_date", "end_date")
    search_fields = ("tenant__email", "tenant__name", "listing__title")
    autocomplete_fields = ("tenant", "listing")
    ordering = ("-created_at",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("tenant", "listing")

    @admin.display(ordering="tenant__email", description="Tenant Email")
    def tenant_email(self, obj):
        return obj.tenant.email


@admin.register(VerificationRequest)
class VerificationRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user_email",
        "user_role",
        "submitted_at",
        "reviewed_at",
    )
    list_display_links = ("id", "user_email")
    list_filter = (
        "identity_verification_status",
        "property_document_verification_status",
        "physical_property_status",
        "verification_method",
        "submitted_at",
    )
    search_fields = ("id", "user__email", "user__name", "notes")
    autocomplete_fields = ("user",)
    filter_horizontal = ("documents",)
    readonly_fields = ("submitted_at", "reviewed_at", "confidence_score", "automated_decision")
    ordering = ("-submitted_at",)
    fields = (
        "user",
        "documents",
        "identity_verification_status",
        "property_document_verification_status",
        "physical_property_status",
        "verification_method",
        "confidence_score",
        "automated_decision",
        "notes",
        "submitted_at",
        "reviewed_at",
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user")

    def save_model(self, request, obj, form, change):
        status_values = {
            obj.identity_verification_status,
            obj.property_document_verification_status,
            obj.physical_property_status,
        }
        if (
            obj.identity_verification_status == VerificationRequest.VerificationProgressStatus.VERIFIED
            and obj.property_document_verification_status == VerificationRequest.VerificationProgressStatus.VERIFIED
        ):
            obj.status = VerificationRequest.Status.APPROVED
            obj.reviewed_at = timezone.now()
        elif VerificationRequest.VerificationProgressStatus.PENDING in status_values:
            obj.status = VerificationRequest.Status.PENDING
            obj.reviewed_at = None
        else:
            obj.status = VerificationRequest.Status.REJECTED
            obj.reviewed_at = timezone.now()

        super().save_model(request, obj, form, change)

    @admin.display(ordering="user__email", description="User Email")
    def user_email(self, obj):
        return obj.user.email

    @admin.display(ordering="user__role", description="Role")
    def user_role(self, obj):
        return obj.user.role


@admin.register(FeaturedPayment)
class FeaturedPaymentAdmin(admin.ModelAdmin):
    list_display = ("id", "listing", "landlord", "amount", "currency", "status", "provider", "expires_at", "payment_date", "created_at")
    list_filter = ("status", "provider", "currency", "created_at")
    search_fields = ("transaction_id", "listing__title", "landlord__email", "landlord__name")
    list_editable = ("status",)
    autocomplete_fields = ("listing", "landlord")
    readonly_fields = ("transaction_id", "opay_order_no", "opay_cashier_url", "created_at", "updated_at")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("id", "booking", "amount", "currency", "status", "provider", "virtual_account_bank_name", "virtual_account_number", "payment_date")
    list_filter = ("status", "provider", "currency", "created_at")
    search_fields = ("transaction_id", "virtual_account_number", "booking__tenant__email", "booking__listing__title")
    readonly_fields = ("transaction_id", "virtual_account_payload", "provider_payload", "webhook_data", "created_at", "updated_at")


@admin.register(PaymentSettlement)
class PaymentSettlementAdmin(admin.ModelAdmin):
    list_display = ("id", "payment", "purpose", "amount", "currency", "bank_name", "account_number", "status", "transfer_reference", "transferred_at")
    list_filter = ("purpose", "status", "currency", "created_at", "transferred_at")
    search_fields = ("payment__transaction_id", "transfer_recipient_id", "transfer_reference", "bank_name", "account_number", "account_name")
    readonly_fields = ("provider_payload", "transfer_payload", "last_error", "created_at", "updated_at")


@admin.register(SubscriptionPayment)
class SubscriptionPaymentAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "role", "plan_code", "billing_cycle", "amount", "currency", "status", "provider", "expires_at", "payment_date", "created_at")
    list_filter = ("role", "plan_code", "billing_cycle", "status", "provider", "currency", "created_at")
    search_fields = ("transaction_id", "user__email", "user__name")
    list_editable = ("status",)
    autocomplete_fields = ("user",)
    readonly_fields = ("transaction_id", "cashier_url", "created_at", "updated_at")


@admin.register(TenantProfile)
class TenantProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "first_name", "last_name", "employment_status", "status", "submitted_at")
    list_filter = ("status", "employment_status", "gender", "submitted_at")
    search_fields = ("user__email", "first_name", "last_name", "state_of_origin")
    readonly_fields = ("submitted_at", "updated_at")


admin.site.register(Review)
admin.site.register(Feedback)
admin.site.register(Favourite)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("sender", "listing")
    search_fields = ("sender__email", "sender__name", "listing__title")
    autocomplete_fields = ("sender", "receiver", "listing")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("sender", "receiver", "listing")
