from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm
from django.db.models import OuterRef, Prefetch, Subquery
from django.utils.html import format_html, format_html_join
from django.utils import timezone

from .models import AdminUser, AppUser, Booking, Document, Feedback, Favourite, FeaturedPayment, Landlord, LandlordProfile, Listing, ListingImage, Message, Payment, PaymentSettlement, Review, SubscriptionPayment, SubscriptionPaymentMethod, Tenant, TenantProfile, VerificationRequest, infer_listing_rental_status, sync_listing_status_from_rental_progress


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

KYC_TYPE_CHOICES = (
    ("National ID (NIN)", "National ID (NIN)"),
    ("International Passport", "International Passport"),
    ("Driver's License", "Driver's License"),
    ("Voter's Card", "Voter's Card"),
)

EMPLOYMENT_STATUS_CHOICES = (
    ("Employed", "Employed"),
    ("Self Employed", "Self Employed"),
    ("Business Owner", "Business Owner"),
    ("Freelancer", "Freelancer"),
    ("Retired", "Retired"),
    ("Unemployed", "Unemployed"),
    ("Student", "Student"),
)

EMPLOYMENT_TYPE_CHOICES = (
    ("Permanent", "Permanent"),
    ("Contract", "Contract"),
    ("Full-time", "Full-time"),
    ("Part-time", "Part-time"),
    ("Temporary", "Temporary"),
)

YES_NO_CHOICES = (
    ("", "---------"),
    ("Yes", "Yes"),
    ("No", "No"),
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
    country_of_birth = forms.CharField(required=False, label="Country of Birth")
    state_of_birth = forms.CharField(required=False, label="State of Birth")
    gender = forms.CharField(required=False, label="Gender")
    nationality = forms.CharField(required=False, label="Nationality")
    lga_of_origin = forms.CharField(required=False, label="LGA")
    preferred_contact_method = forms.ChoiceField(
        required=False,
        label="Preferred Contact Method",
        choices=(("", "---------"), *PREFERRED_CONTACT_METHOD_CHOICES),
    )
    employment_status = forms.ChoiceField(
        required=False,
        label="Employment Status",
        choices=(("", "---------"), *EMPLOYMENT_STATUS_CHOICES),
    )
    occupation = forms.CharField(required=False, label="Occupation")
    employer_name = forms.CharField(required=False, label="Employer Name")
    job_title = forms.CharField(required=False, label="Job Title")
    employment_type = forms.ChoiceField(
        required=False,
        label="Employment Type",
        choices=(("", "---------"), *EMPLOYMENT_TYPE_CHOICES),
    )
    work_address = forms.CharField(required=False, label="Work Address", widget=forms.Textarea(attrs={"rows": 3}))
    work_email = forms.EmailField(required=False, label="Work Email")
    years_employed = forms.CharField(
        required=False,
        label="Years Employed",
        widget=forms.TextInput(attrs={"type": "number", "min": 0}),
    )
    hr_contact_name = forms.CharField(required=False, label="HR Contact Name")
    hr_contact_number = forms.CharField(required=False, label="HR Contact Number")
    hr_contact_email = forms.EmailField(required=False, label="HR Contact Email")
    profession = forms.CharField(required=False, label="Profession")
    trading_name = forms.CharField(required=False, label="Trading Name")
    nature_of_work = forms.CharField(required=False, label="Nature of Work")
    years_self_employed = forms.CharField(
        required=False,
        label="Years Self-Employed",
        widget=forms.TextInput(attrs={"type": "number", "min": 0}),
    )
    business_website = forms.CharField(required=False, label="Business Website")
    business_name = forms.CharField(required=False, label="Business Name")
    business_registration_number = forms.CharField(required=False, label="Business Registration Number")
    industry = forms.CharField(required=False, label="Industry")
    position_in_business = forms.CharField(required=False, label="Position in Business")
    years_in_business = forms.CharField(
        required=False,
        label="Years in Business",
        widget=forms.TextInput(attrs={"type": "number", "min": 0}),
    )
    company_website = forms.CharField(required=False, label="Company Website")
    primary_service = forms.CharField(required=False, label="Primary Service")
    platform_used = forms.CharField(required=False, label="Platform Used")
    years_freelancing = forms.CharField(
        required=False,
        label="Years Freelancing",
        widget=forms.TextInput(attrs={"type": "number", "min": 0}),
    )
    portfolio_website = forms.CharField(required=False, label="Portfolio Website")
    previous_occupation = forms.CharField(required=False, label="Previous Occupation")
    previous_employer = forms.CharField(required=False, label="Previous Employer")
    retirement_year = forms.CharField(
        required=False,
        label="Retirement Year",
        widget=forms.TextInput(attrs={"type": "number", "min": 1900}),
    )
    pension_provider = forms.CharField(required=False, label="Pension Provider")
    currently_seeking_employment = forms.ChoiceField(
        required=False,
        label="Currently Seeking Employment?",
        choices=YES_NO_CHOICES,
    )
    source_of_income = forms.CharField(required=False, label="Source of Income")
    institution = forms.CharField(required=False, label="Institution")
    course_of_study = forms.CharField(required=False, label="Course of Study")
    level = forms.CharField(required=False, label="Level")
    graduation_year = forms.CharField(
        required=False,
        label="Expected Graduation Year",
        widget=forms.TextInput(attrs={"type": "number", "min": 1900}),
    )
    sponsorship_source = forms.CharField(required=False, label="Sponsorship Source")
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
    bank_name = forms.CharField(required=False, label="Bank Name")
    account_name = forms.CharField(required=False, label="Account Name")
    account_number = forms.CharField(required=False, label="Account Number")
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
    cac_registration_date = forms.DateField(
        required=False,
        label="CAC Registration Date",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
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
        emergency_contact = _as_dict(profile.get("emergency_contact"))
        residence = _as_dict(getattr(self.instance, "residence", None))
        first_name, middle_name, last_name = _split_full_name(getattr(self.instance, "name", ""))

        self.initial.update(
            {
                "first_name": str(profile.get("first_name") or first_name),
                "middle_name": str(profile.get("middle_name") or middle_name),
                "last_name": str(profile.get("last_name") or last_name),
                "date_of_birth": profile.get("date_of_birth", ""),
                "country_of_birth": str(profile.get("country_of_birth", "")),
                "state_of_birth": str(profile.get("state_of_birth", "")),
                "gender": str(profile.get("gender", "")),
                "nationality": str(profile.get("nationality", "")),
                "lga_of_origin": str(profile.get("lga_of_origin", "")),
                "preferred_contact_method": str(profile.get("preferred_contact_method", "")),
                "employment_status": str(profile.get("employment_status", "")),
                "occupation": str(profile.get("occupation", "")),
                "employer_name": str(profile.get("employer_name", "")),
                "job_title": str(profile.get("job_title", "")),
                "employment_type": str(profile.get("employment_type", "")),
                "work_address": str(profile.get("work_address", "")),
                "work_email": str(profile.get("work_email", "")),
                "years_employed": str(profile.get("years_employed", "")),
                "hr_contact_name": str(profile.get("hr_contact_name", "")),
                "hr_contact_number": str(profile.get("hr_contact_number", "")),
                "hr_contact_email": str(profile.get("hr_contact_email") or profile.get("hr_email") or ""),
                "profession": str(profile.get("profession", "")),
                "trading_name": str(profile.get("trading_name", "")),
                "nature_of_work": str(profile.get("nature_of_work", "")),
                "years_self_employed": str(profile.get("years_self_employed", "")),
                "business_website": str(profile.get("business_website", "")),
                "business_name": str(profile.get("business_name", "")),
                "business_registration_number": str(profile.get("business_registration_number", "")),
                "industry": str(profile.get("industry", "")),
                "position_in_business": str(profile.get("position_in_business", "")),
                "years_in_business": str(profile.get("years_in_business", "")),
                "company_website": str(profile.get("company_website", "")),
                "primary_service": str(profile.get("primary_service", "")),
                "platform_used": str(profile.get("platform_used", "")),
                "years_freelancing": str(profile.get("years_freelancing", "")),
                "portfolio_website": str(profile.get("portfolio_website", "")),
                "previous_occupation": str(profile.get("previous_occupation", "")),
                "previous_employer": str(profile.get("previous_employer", "")),
                "retirement_year": str(profile.get("retirement_year", "")),
                "pension_provider": str(profile.get("pension_provider", "")),
                "currently_seeking_employment": str(profile.get("currently_seeking_employment", "")),
                "source_of_income": str(profile.get("source_of_income", "")),
                "institution": str(profile.get("institution", "")),
                "course_of_study": str(profile.get("course_of_study", "")),
                "level": str(profile.get("level", "")),
                "graduation_year": str(profile.get("graduation_year", "")),
                "sponsorship_source": str(profile.get("sponsorship_source", "")),
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
                "residential_address": str(residential_information.get("address") or profile.get("residential_address") or ""),
                "proof_of_address": _as_string_list(profile.get("proof_of_address")),
                "bank_name": str(profile.get("bank_name") or banking_information.get("bank_name") or corporate_banking_information.get("bank_name") or ""),
                "account_name": str(profile.get("account_name") or banking_information.get("account_name") or corporate_banking_information.get("account_name") or ""),
                "account_number": str(profile.get("account_number") or banking_information.get("account_number") or corporate_banking_information.get("account_number") or ""),
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
                "cac_registration_date": profile.get("cac_registration_date", ""),
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
            "employment_status",
            "occupation",
            "employer_name",
            "job_title",
            "employment_type",
            "work_address",
            "work_email",
            "years_employed",
            "hr_contact_name",
            "hr_contact_number",
            "hr_contact_email",
            "profession",
            "trading_name",
            "nature_of_work",
            "years_self_employed",
            "business_website",
            "business_name",
            "business_registration_number",
            "industry",
            "position_in_business",
            "years_in_business",
            "company_website",
            "primary_service",
            "platform_used",
            "years_freelancing",
            "portfolio_website",
            "previous_occupation",
            "previous_employer",
            "retirement_year",
            "pension_provider",
            "currently_seeking_employment",
            "source_of_income",
            "institution",
            "course_of_study",
            "level",
            "graduation_year",
            "sponsorship_source",
            "business_address",
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
            "bank_name",
            "account_name",
            "account_number",
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
            "cac_registration_date",
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
                    "employment_status": self.cleaned_data.get("employment_status", "").strip(),
                    "occupation": self.cleaned_data.get("occupation", "").strip(),
                    "employer_name": self.cleaned_data.get("employer_name", "").strip(),
                    "job_title": self.cleaned_data.get("job_title", "").strip(),
                    "employment_type": self.cleaned_data.get("employment_type", "").strip(),
                    "work_address": self.cleaned_data.get("work_address", "").strip(),
                    "work_email": self.cleaned_data.get("work_email", "").strip().lower(),
                    "years_employed": self.cleaned_data.get("years_employed", "").strip(),
                    "hr_contact_name": self.cleaned_data.get("hr_contact_name", "").strip(),
                    "hr_contact_number": self.cleaned_data.get("hr_contact_number", "").strip(),
                    "hr_contact_email": self.cleaned_data.get("hr_contact_email", "").strip().lower(),
                    "profession": self.cleaned_data.get("profession", "").strip(),
                    "trading_name": self.cleaned_data.get("trading_name", "").strip(),
                    "nature_of_work": self.cleaned_data.get("nature_of_work", "").strip(),
                    "years_self_employed": self.cleaned_data.get("years_self_employed", "").strip(),
                    "business_website": self.cleaned_data.get("business_website", "").strip(),
                    "business_name": self.cleaned_data.get("business_name", "").strip(),
                    "business_registration_number": self.cleaned_data.get("business_registration_number", "").strip(),
                    "industry": self.cleaned_data.get("industry", "").strip(),
                    "position_in_business": self.cleaned_data.get("position_in_business", "").strip(),
                    "years_in_business": self.cleaned_data.get("years_in_business", "").strip(),
                    "company_website": self.cleaned_data.get("company_website", "").strip(),
                    "primary_service": self.cleaned_data.get("primary_service", "").strip(),
                    "platform_used": self.cleaned_data.get("platform_used", "").strip(),
                    "years_freelancing": self.cleaned_data.get("years_freelancing", "").strip(),
                    "portfolio_website": self.cleaned_data.get("portfolio_website", "").strip(),
                    "previous_occupation": self.cleaned_data.get("previous_occupation", "").strip(),
                    "previous_employer": self.cleaned_data.get("previous_employer", "").strip(),
                    "retirement_year": self.cleaned_data.get("retirement_year", "").strip(),
                    "pension_provider": self.cleaned_data.get("pension_provider", "").strip(),
                    "currently_seeking_employment": self.cleaned_data.get("currently_seeking_employment", "").strip(),
                    "source_of_income": self.cleaned_data.get("source_of_income", "").strip(),
                    "institution": self.cleaned_data.get("institution", "").strip(),
                    "course_of_study": self.cleaned_data.get("course_of_study", "").strip(),
                    "level": self.cleaned_data.get("level", "").strip(),
                    "graduation_year": self.cleaned_data.get("graduation_year", "").strip(),
                    "sponsorship_source": self.cleaned_data.get("sponsorship_source", "").strip(),
                    "business_address": self.cleaned_data.get("business_address", "").strip(),
                    "bio": bio,
                    "about_me": bio,
                    "contact_number": phone_number,
                    "whatsapp_number": self.cleaned_data.get("whatsapp_number", "").strip(),
                    "email": email_address,
                    "proof_of_address": list(self.cleaned_data.get("proof_of_address", [])),
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
                    "cac_registration_date": self.cleaned_data.get("cac_registration_date").isoformat() if self.cleaned_data.get("cac_registration_date") else "",
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


class LandlordIdentityVerificationAdminForm(LandlordProfileAdminForm):
    nin = forms.CharField(required=False, label="National Identification Number (NIN)")
    bvn = forms.CharField(required=False, label="Bank Verification Number (BVN)")

    class Meta(UserChangeForm.Meta):
        model = Landlord
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        profile = _as_dict(getattr(self.instance, "landlord_verification_profile", None))
        self.initial.update(
            {
                "nin": str(profile.get("nin") or getattr(self.instance, "nin_number", "")),
                "bvn": str(profile.get("bvn") or getattr(self.instance, "bvn_number", "")),
            }
        )

    def save(self, commit=True):
        user = UserChangeForm.save(self, commit=False)
        profile = dict(_as_dict(user.landlord_verification_profile))
        verification_type = user.landlord_verification_type

        if verification_type == AppUser.LandlordVerificationType.INDIVIDUAL:
            first_name = self.cleaned_data.get("first_name", "").strip()
            middle_name = self.cleaned_data.get("middle_name", "").strip()
            last_name = self.cleaned_data.get("last_name", "").strip()
            contact_number = self.cleaned_data.get("phone_number", "").strip()
            email_address = self.cleaned_data.get("email_address", "").strip().lower()
            nin = self.cleaned_data.get("nin", "").strip()
            bvn = self.cleaned_data.get("bvn", "").strip()
            residential_address = self.cleaned_data.get("residential_address", "").strip()
            residential_information = dict(_as_dict(profile.get("residential_information")))
            residential_information["address"] = residential_address
            banking_information = dict(_as_dict(profile.get("banking_information")))
            banking_information.update(
                {
                    "bank_name": self.cleaned_data.get("bank_name", "").strip(),
                    "account_name": self.cleaned_data.get("account_name", "").strip(),
                    "account_number": self.cleaned_data.get("account_number", "").strip(),
                }
            )
            kyc = dict(_as_dict(profile.get("kyc")))
            kyc.update(
                {
                    "id_type": "National ID (NIN)" if nin else "",
                    "id_number": nin,
                    "expiry_date": kyc.get("expiry_date", ""),
                }
            )

            profile.update(
                {
                    "first_name": first_name,
                    "middle_name": middle_name,
                    "last_name": last_name,
                    "date_of_birth": self.cleaned_data.get("date_of_birth").isoformat() if self.cleaned_data.get("date_of_birth") else "",
                    "country_of_birth": self.cleaned_data.get("country_of_birth", "").strip(),
                    "state_of_birth": self.cleaned_data.get("state_of_birth", "").strip(),
                    "gender": self.cleaned_data.get("gender", "").strip(),
                    "nationality": self.cleaned_data.get("nationality", "").strip(),
                    "state_of_origin": self.cleaned_data.get("state_of_origin", "").strip(),
                    "lga_of_origin": self.cleaned_data.get("lga_of_origin", "").strip(),
                    "contact_number": contact_number,
                    "email": email_address,
                    "nin": nin,
                    "bvn": bvn,
                    "residential_address": residential_address,
                    "bank_name": banking_information["bank_name"],
                    "account_name": banking_information["account_name"],
                    "account_number": banking_information["account_number"],
                    "kyc": kyc,
                    "residential_information": residential_information,
                    "banking_information": banking_information,
                }
            )

            full_name = _build_full_name(first_name, middle_name, last_name)
            if full_name:
                user.name = full_name
            if email_address:
                user.email = email_address
            user.mobile = contact_number
            user.state_of_origin = self.cleaned_data.get("state_of_origin", "").strip()
            user.nin_number = nin
            user.bvn_number = bvn

        if verification_type == AppUser.LandlordVerificationType.CORPORATE:
            nin = self.cleaned_data.get("nin", "").strip()
            bvn = self.cleaned_data.get("bvn", "").strip()
            profile.update(
                {
                    "company_name": self.cleaned_data.get("company_name", "").strip(),
                    "business_state": self.cleaned_data.get("business_state", "").strip(),
                    "business_city": self.cleaned_data.get("business_city", "").strip(),
                    "business_address": self.cleaned_data.get("business_address", "").strip(),
                    "company_phone_number": self.cleaned_data.get("phone_number", "").strip()
                    or self.cleaned_data.get("company_phone_number", "").strip(),
                    "company_email": self.cleaned_data.get("email_address", "").strip().lower()
                    or self.cleaned_data.get("company_email", "").strip().lower(),
                    "contact_person_name": self.cleaned_data.get("contact_person_name", "").strip(),
                    "contact_person_position": self.cleaned_data.get("contact_person_position", "").strip(),
                    "cac_registration_number": self.cleaned_data.get("cac_registration_number", "").strip(),
                    "cac_registration_date": self.cleaned_data.get("cac_registration_date").isoformat() if self.cleaned_data.get("cac_registration_date") else "",
                    "tax_identification_number": self.cleaned_data.get("tax_identification_number", "").strip(),
                    "nin": nin,
                    "bvn": bvn,
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
            user.mobile = profile["company_phone_number"]
            if profile["company_email"]:
                user.email = profile["company_email"]
            user.nin_number = nin
            user.bvn_number = bvn

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
    form = LandlordIdentityVerificationAdminForm
    role = AppUser.Role.LANDLORD
    list_display = ("email", "name", "email_verified", "is_active", "created_at")
    list_filter = ("email_verified", "is_active")

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return self.add_fieldsets

        common = [
            (None, {"fields": ("password",)}),
            ("Landlord Verification Track", {"fields": ("landlord_verification_type", "profile_photo", "email_verified")}),
        ]
        individual = [
            (
                "Personal Information",
                {
                    "fields": (
                        ("first_name", "middle_name", "last_name"),
                        ("date_of_birth", "country_of_birth", "state_of_birth"),
                        ("nationality", "state_of_origin", "lga_of_origin"),
                        ("gender", "phone_number", "email_address"),
                    )
                },
            ),
            (
                "Identity Verification (KYC)",
                {
                    "fields": (
                        ("nin", "bvn"),
                        ("bank_name", "account_name", "account_number"),
                    )
                },
            ),
            ("Residential Address", {"fields": ("residential_address",)}),
        ]
        corporate = [
            (
                "Corporate Landlord Information",
                {
                    "fields": (
                        "company_name",
                        ("business_state", "business_city"),
                        "business_address",
                        ("company_phone_number", "company_email"),
                        ("contact_person_name", "contact_person_position"),
                        ("cac_registration_number", "cac_registration_date", "tax_identification_number"),
                        ("nin", "bvn"),
                        ("bank_name", "account_name", "account_number"),
                    )
                },
            ),
        ]
        footer = [
            ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
            ("Important dates", {"fields": ("last_login", "created_at", "updated_at")}),
        ]

        if obj.landlord_verification_type == AppUser.LandlordVerificationType.CORPORATE:
            return common + corporate + footer
        return common + individual + footer


@admin.register(LandlordProfile)
class LandlordProfileAdmin(RoleAdminMixin, AppUserAdmin):
    form = LandlordProfileAdminForm
    role = AppUser.Role.LANDLORD
    list_display = ("email", "name", "landlord_track", "has_profile_details", "email_verified", "updated_at")
    list_filter = ("landlord_verification_type", "email_verified", "is_active")
    search_fields = ("email", "name", "mobile", "nin_number")
    readonly_fields = AppUserAdmin.readonly_fields

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
            (
                "Employment Information",
                {
                    "fields": (
                        ("employment_status", "occupation"),
                        ("employer_name", "job_title", "employment_type"),
                        ("years_employed", "work_email"),
                        "work_address",
                        ("hr_contact_name", "hr_contact_number", "hr_contact_email"),
                        ("profession", "trading_name"),
                        ("nature_of_work", "years_self_employed"),
                        ("business_name", "business_registration_number"),
                        ("industry", "position_in_business", "years_in_business"),
                        ("business_website", "company_website"),
                        ("primary_service", "platform_used", "years_freelancing"),
                        "portfolio_website",
                        ("previous_occupation", "previous_employer"),
                        ("retirement_year", "pension_provider"),
                        ("currently_seeking_employment", "source_of_income"),
                        ("institution", "course_of_study"),
                        ("level", "graduation_year", "sponsorship_source"),
                        "business_address",
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
            ("Banking Information", {"fields": (("bank_name", "account_name", "account_number"),)}),
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
                        ("cac_registration_number", "cac_registration_date", "tax_identification_number"),
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
        return common + individual + footer

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
    list_display = (
        "title",
        "city",
        "landlord",
        "price_per_year",
        "rental_status",
        "property_document_verification_status",
        "physical_property_status",
        "featured",
        "created_at",
    )
    list_filter = (
        "status",
        "property_document_verification_status",
        "physical_property_status",
        "featured",
        "city",
        "property_type",
    )
    search_fields = ("title", "description", "address", "city", "landlord__email")
    filter_horizontal = ("property_documents",)
    inlines = [ListingImageInline]

    def get_queryset(self, request):
        bookings = Booking.objects.exclude(status=Booking.Status.CANCELLED)
        return super().get_queryset(request).select_related("landlord").prefetch_related(
            Prefetch("bookings", queryset=bookings),
        )

    @admin.display(ordering="status", description="Status")
    def rental_status(self, obj):
        return dict(Listing.Status.choices).get(infer_listing_rental_status(obj), obj.status)


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

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        sync_listing_status_from_rental_progress(obj.listing)

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
        if obj.identity_verification_status == VerificationRequest.VerificationProgressStatus.VERIFIED:
            obj.status = VerificationRequest.Status.APPROVED
            obj.reviewed_at = timezone.now()
        elif obj.identity_verification_status == VerificationRequest.VerificationProgressStatus.PENDING:
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
    list_display = ("landlord_email", "payment", "tenant_email", "created_at")
    list_display_links = ("payment",)
    list_filter = ("created_at",)
    search_fields = (
        "payment__transaction_id",
        "payment__booking__tenant__email",
        "payment__booking__listing__landlord__email",
    )
    ordering = ("-created_at",)

    def get_queryset(self, request):
        representative_settlement = (
            PaymentSettlement.objects.filter(payment_id=OuterRef("payment_id"))
            .order_by("created_at", "purpose", "id")
            .values("id")[:1]
        )
        return (
            super()
            .get_queryset(request)
            .select_related("payment", "payment__booking", "payment__booking__tenant", "payment__booking__listing", "payment__booking__listing__landlord")
            .filter(id=Subquery(representative_settlement))
        )

    def get_fields(self, request, obj=None):
        if obj:
            return ("landlord_email", "payment", "tenant_email", "created_at", "settlement_accounts")
        return super().get_fields(request, obj)

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return ("landlord_email", "payment", "tenant_email", "created_at", "settlement_accounts")
        return ("provider_payload", "transfer_payload", "last_error", "created_at", "updated_at")

    @admin.display(ordering="payment__booking__listing__landlord__email", description="Landlord")
    def landlord_email(self, obj):
        return obj.payment.booking.listing.landlord.email

    @admin.display(ordering="payment__booking__tenant__email", description="Tenant")
    def tenant_email(self, obj):
        return obj.payment.booking.tenant.email

    @admin.display(description="Payment Settlement Accounts")
    def settlement_accounts(self, obj):
        settlements = obj.payment.settlements.order_by("purpose", "created_at")
        return format_html(
            '<table style="width: 100%; border-collapse: collapse;">'
            "<thead>"
            "<tr>"
            '<th style="text-align: left; padding: 6px; border-bottom: 1px solid #ddd;">ID</th>'
            '<th style="text-align: left; padding: 6px; border-bottom: 1px solid #ddd;">Purpose</th>'
            '<th style="text-align: left; padding: 6px; border-bottom: 1px solid #ddd;">Amount</th>'
            '<th style="text-align: left; padding: 6px; border-bottom: 1px solid #ddd;">Currency</th>'
            '<th style="text-align: left; padding: 6px; border-bottom: 1px solid #ddd;">Bank Name</th>'
            '<th style="text-align: left; padding: 6px; border-bottom: 1px solid #ddd;">Account Number</th>'
            '<th style="text-align: left; padding: 6px; border-bottom: 1px solid #ddd;">Status</th>'
            '<th style="text-align: left; padding: 6px; border-bottom: 1px solid #ddd;">Failure Reason</th>'
            '<th style="text-align: left; padding: 6px; border-bottom: 1px solid #ddd;">Transfer Reference</th>'
            '<th style="text-align: left; padding: 6px; border-bottom: 1px solid #ddd;">Transferred At</th>'
            "</tr>"
            "</thead>"
            "<tbody>{}</tbody>"
            "</table>",
            format_html_join(
                "",
                "<tr>"
                '<td style="padding: 6px; border-bottom: 1px solid #eee;">{}</td>'
                '<td style="padding: 6px; border-bottom: 1px solid #eee;">{}</td>'
                '<td style="padding: 6px; border-bottom: 1px solid #eee;">{}</td>'
                '<td style="padding: 6px; border-bottom: 1px solid #eee;">{}</td>'
                '<td style="padding: 6px; border-bottom: 1px solid #eee;">{}</td>'
                '<td style="padding: 6px; border-bottom: 1px solid #eee;">{}</td>'
                '<td style="padding: 6px; border-bottom: 1px solid #eee;">{}</td>'
                '<td style="padding: 6px; border-bottom: 1px solid #eee;">{}</td>'
                '<td style="padding: 6px; border-bottom: 1px solid #eee;">{}</td>'
                '<td style="padding: 6px; border-bottom: 1px solid #eee;">{}</td>'
                "</tr>",
                (
                    (
                        settlement.id,
                        settlement.get_purpose_display(),
                        settlement.amount,
                        settlement.currency,
                        settlement.bank_name,
                        settlement.account_number,
                        settlement.get_status_display(),
                        settlement.last_error or "-",
                        settlement.transfer_reference or "-",
                        self._format_datetime(settlement.transferred_at),
                    )
                    for settlement in settlements
                ),
            ),
        )

    def _format_datetime(self, value):
        if value is None:
            return "-"
        return timezone.localtime(value).strftime("%Y-%m-%d %H:%M:%S")


@admin.register(SubscriptionPayment)
class SubscriptionPaymentAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "role", "plan_code", "billing_cycle", "amount", "currency", "status", "provider", "recurring_enabled", "billing_reason", "expires_at", "payment_date", "created_at")
    list_filter = ("role", "plan_code", "billing_cycle", "status", "provider", "currency", "recurring_enabled", "billing_reason", "created_at")
    search_fields = ("transaction_id", "provider_charge_id", "user__email", "user__name", "payment_method__provider_payment_method_id")
    list_editable = ("status",)
    autocomplete_fields = ("user", "payment_method", "renewed_from")
    readonly_fields = ("transaction_id", "provider_charge_id", "cashier_url", "provider_payload", "webhook_data", "created_at", "updated_at")


@admin.register(SubscriptionPaymentMethod)
class SubscriptionPaymentMethodAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "provider", "payment_type", "status", "card_network", "card_last4", "card_expiry_month", "card_expiry_year", "created_at")
    list_filter = ("provider", "payment_type", "status", "card_network", "created_at")
    search_fields = ("provider_customer_id", "provider_payment_method_id", "user__email", "user__name", "card_last4")
    autocomplete_fields = ("user",)
    readonly_fields = ("provider_customer_id", "provider_payment_method_id", "provider_payload", "created_at", "updated_at")


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
