import glob
import json
import mimetypes
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.dateparse import parse_date

from core.models import (
    AppUser,
    Document,
    Listing,
    ListingImage,
    SubscriptionPayment,
    TenantProfile,
    VerificationRequest,
    build_listing_property_document_title,
)
from core.profile_validation import is_valid_mobile, is_valid_nin, normalize_residence, normalize_state_of_origin
from core.subscription_pricing import get_subscription_pricing
from core.tenant_verification import normalize_tenant_verification_date, normalize_tenant_verification_profile


class Command(BaseCommand):
    help = "Seed development landlords, tenants, listings, images, and verification records."

    def handle(self, *args, **options):
        if settings.ENVIRONMENT in {"prod", "production"}:
            self.stdout.write("Production environment detected; skipping demo account seed")
            return

        if not settings.SEED_DEMO_ACCOUNTS:
            self.stdout.write("SEED_DEMO_ACCOUNTS is false; skipping")
            return

        seed_specs = [
            (settings.SEED_LANDLORD_DATA_PATH, AppUser.Role.LANDLORD),
            (settings.SEED_TENANT_DATA_PATH, AppUser.Role.TENANT),
        ]

        created_users = 0
        created_listings = 0

        self.seed_homepage_video()

        for path_value, role in seed_specs:
            seed_path = self.resolve_path(path_value)
            if not seed_path or not seed_path.exists():
                self.stdout.write(f"Seed file not found: {path_value}")
                continue

            payload = json.loads(seed_path.read_text())
            for seed_key, data in payload.items():
                user, created = self.upsert_user(seed_key, data, role, seed_path)
                if created:
                    created_users += 1

                if role == AppUser.Role.LANDLORD:
                    self.seed_verification(user, data)
                    self.seed_landlord_subscription(seed_key, user, data)
                    created_listings += self.seed_listings(user, data)
                elif role == AppUser.Role.TENANT:
                    self.seed_tenant_verification(user, data)
                    self.seed_tenant_profile(seed_key, user, data)
                    self.seed_tenant_subscription(seed_key, user, data)

        self.stdout.write(self.style.SUCCESS(f"Seed complete. Created {created_users} users and {created_listings} listings."))

    def seed_homepage_video(self) -> None:
        storage_name = str(getattr(settings, "HOMEPAGE_VIDEO_STORAGE_NAME", "") or "").strip()
        source_path_value = str(getattr(settings, "HOMEPAGE_VIDEO_SOURCE_PATH", "") or "").strip()
        if not storage_name or not source_path_value:
            return

        source_path = self.resolve_path(source_path_value)
        if not source_path or not source_path.exists() or not source_path.is_file():
            self.stdout.write(f"Homepage video source not found: {source_path_value}")
            return

        destination_path = None
        try:
            destination_path = Path(default_storage.path(storage_name))
        except (AttributeError, NotImplementedError):
            pass
        if destination_path and source_path.resolve() == destination_path.resolve():
            return

        if default_storage.exists(storage_name):
            default_storage.delete(storage_name)

        with source_path.open("rb") as fh:
            default_storage.save(storage_name, File(fh))

    def upsert_user(self, seed_key: str, data: dict, role: str, seed_path: Path):
        registration = self.get_seed_dict(data, "registration_credentials")
        login = self.get_seed_dict(data, "login", "login_credentials")
        profile = data.get("profile") or {}
        verification = data.get("verification") or {}
        profile_personal = self.get_seed_dict(profile, "personal_information")
        landlord_identification = self.get_seed_dict(verification, "landlord_identification")
        landlord_identification_personal = self.get_seed_dict(landlord_identification, "personal_information")
        identity_and_bank_verification = self.get_seed_dict(profile, "identity_and_bank_verification")
        email = self.seed_text(
            login.get("email"),
            registration.get("email"),
            profile.get("email"),
            profile_personal.get("email"),
            verification.get("email"),
            landlord_identification_personal.get("email"),
            data.get("email"),
        ).lower()
        if not email:
            raise ValueError(f"Seed entry {seed_key} is missing an email address")

        name = (
            login.get("full_name")
            or registration.get("full_name")
            or profile.get("full_name")
            or profile.get("name")
            or data.get("full_name")
            or self.build_full_name_from_seed(profile_personal)
            or self.build_full_name_from_seed(landlord_identification_personal)
            or seed_key.replace("_", " ").title()
        ).strip()
        user, created = AppUser.objects.get_or_create(
            email=email,
            defaults={"name": name, "role": role, "email_verified": True},
        )

        user.name = name
        user.role = role
        user.email_verified = True
        user.mobile = self.seed_text(
            profile.get("mobile"),
            profile_personal.get("contact_number"),
            verification.get("mobile"),
            landlord_identification_personal.get("contact_number"),
            profile_personal.get("phone_number"),
        )
        user.nin_number = self.seed_text(
            profile.get("nin_number"),
            profile_personal.get("national_identity_number"),
            identity_and_bank_verification.get("id_number")
            if self.seed_text(identity_and_bank_verification.get("id_type")) == "National ID (NIN)"
            else "",
            verification.get("nin_number"),
            verification.get("nin"),
            landlord_identification_personal.get("national_identity_number"),
        )
        user.bvn_number = self.seed_text(
            profile.get("bvn_number"),
            profile_personal.get("bank_verification_number"),
            verification.get("bvn_number"),
            verification.get("bvn"),
            landlord_identification_personal.get("bank_verification_number"),
        )
        if user.mobile and not is_valid_mobile(user.mobile):
            raise ValueError(f"Seed entry {seed_key} has an invalid mobile number")
        if user.nin_number and not is_valid_nin(user.nin_number):
            raise ValueError(f"Seed entry {seed_key} has an invalid NIN number")
        user.state_of_origin = normalize_state_of_origin(
            self.seed_text(
                profile.get("state_of_origin"),
                profile_personal.get("state_of_origin"),
                verification.get("state_of_origin"),
                landlord_identification_personal.get("state_of_origin"),
            )
        )
        user.residence = normalize_residence(
            user.state_of_origin,
            profile.get("residence")
            or self.get_seed_dict(profile, "residential_information")
            or self.build_residence_from_current_residence(self.get_seed_dict(profile, "current_residence")),
        )
        if role == AppUser.Role.TENANT:
            user.tenant_verification_profile = normalize_tenant_verification_profile(verification, user)
        elif role == AppUser.Role.LANDLORD:
            self.seed_landlord_profile_fields(seed_key, user, data, profile)
        password = login.get("password") or registration.get("password") or data.get("password")
        if password:
            user.set_password(password)

        photo_path = self.resolve_profile_photo_path(seed_key, data, login, profile, seed_path)
        if photo_path and photo_path.exists():
            self.replace_model_file(user, "profile_photo", photo_path)

        user.save()
        return user, created

    def seed_landlord_profile_fields(self, seed_key: str, user: AppUser, data: dict, profile: dict) -> None:
        verification_type, verification_profile = self.build_landlord_verification_profile(data, profile)

        if not verification_type and not verification_profile:
            user.landlord_verification_type = ""
            user.landlord_verification_profile = None
            return

        valid_types = {
            AppUser.LandlordVerificationType.INDIVIDUAL,
            AppUser.LandlordVerificationType.CORPORATE,
        }
        verification_type = self.normalize_landlord_verification_type(verification_type)
        if verification_type not in valid_types:
            raise ValueError(f"Seed entry {seed_key} has an invalid landlord verification type")
        if not isinstance(verification_profile, dict):
            raise ValueError(f"Seed entry {seed_key} landlord_verification_profile must be an object")

        verification_profile = dict(verification_profile)
        kyc = self.get_seed_dict(verification_profile, "kyc")
        profile_nin = self.seed_text(verification_profile.get("nin"))
        kyc_id_number = self.seed_text(kyc.get("id_number"))
        if not profile_nin and self.seed_text(kyc.get("id_type")) == "National ID (NIN)":
            profile_nin = kyc_id_number
            verification_profile["nin"] = profile_nin
        profile_bvn = self.seed_text(verification_profile.get("bvn"))

        if profile_nin:
            if not is_valid_nin(profile_nin):
                raise ValueError(f"Seed entry {seed_key} has an invalid landlord profile NIN number")
            user.nin_number = profile_nin
        if profile_bvn:
            if not is_valid_nin(profile_bvn):
                raise ValueError(f"Seed entry {seed_key} has an invalid landlord profile BVN number")
            user.bvn_number = profile_bvn

        user.landlord_verification_type = verification_type
        user.landlord_verification_profile = verification_profile

    def build_landlord_verification_profile(self, data: dict, profile: dict) -> tuple[str, dict | None]:
        if "landlord_verification_profile" in profile:
            verification_profile = profile.get("landlord_verification_profile")
        else:
            verification_profile = data.get("landlord_verification_profile")
        verification_type = self.seed_text(
            profile.get("landlord_verification_type"),
            data.get("landlord_verification_type"),
        )
        if verification_profile:
            return verification_type, verification_profile

        verification = data.get("verification") or {}
        landlord_identification = self.get_seed_dict(verification, "landlord_identification")
        verification_personal = self.get_seed_dict(landlord_identification, "personal_information")
        profile_personal = self.get_seed_dict(profile, "personal_information")
        employment_information = self.get_seed_dict(profile, "employment_information", "employment_info")
        identity_and_bank = self.get_seed_dict(profile, "identity_and_bank_verification")
        residential_information = self.get_seed_dict(profile, "residential_information")
        emergency_contact = self.get_seed_dict(profile, "emergency_contact")
        if not any([
            landlord_identification,
            verification_personal,
            profile_personal,
            employment_information,
            identity_and_bank,
            residential_information,
            emergency_contact,
        ]):
            return verification_type, None

        verification_type = self.seed_text(
            verification_type,
            landlord_identification.get("type"),
            AppUser.LandlordVerificationType.INDIVIDUAL,
        )
        kyc_id_type = self.seed_text(identity_and_bank.get("id_type"))
        nin = self.seed_text(
            identity_and_bank.get("id_number") if kyc_id_type == "National ID (NIN)" else "",
            profile_personal.get("national_identity_number"),
            verification_personal.get("national_identity_number"),
        )
        bvn = self.seed_text(
            profile_personal.get("bank_verification_number"),
            verification_personal.get("bank_verification_number"),
            identity_and_bank.get("bank_verification_number"),
            identity_and_bank.get("bvn"),
        )
        bio = self.seed_text(profile_personal.get("bio_about_me"), profile_personal.get("bio"), profile_personal.get("about_me"))
        payload = {
            "first_name": self.seed_text(profile_personal.get("first_name"), verification_personal.get("first_name")),
            "middle_name": self.seed_text(profile_personal.get("middle_name"), verification_personal.get("middle_name")),
            "last_name": self.seed_text(profile_personal.get("last_name"), verification_personal.get("last_name")),
            "date_of_birth": self.seed_text(profile_personal.get("date_of_birth"), verification_personal.get("date_of_birth")),
            "gender": self.seed_text(profile_personal.get("gender"), verification_personal.get("gender")),
            "nationality": self.seed_text(profile_personal.get("nationality"), verification_personal.get("nationality")),
            "country_of_birth": self.seed_text(profile_personal.get("country_of_birth"), verification_personal.get("country_of_birth")),
            "state_of_birth": self.seed_text(profile_personal.get("state_of_birth"), verification_personal.get("state_of_birth")),
            "state_of_origin": self.seed_text(profile_personal.get("state_of_origin"), verification_personal.get("state_of_origin")),
            "lga_of_origin": self.seed_text(profile_personal.get("lga_of_origin"), verification_personal.get("lga_of_origin")),
            "preferred_contact_method": self.seed_text(profile_personal.get("preferred_contact_method")),
            "bio": bio,
            "about_me": bio,
            "contact_number": self.seed_text(profile_personal.get("contact_number"), verification_personal.get("contact_number"), profile_personal.get("phone_number")),
            "whatsapp_number": self.seed_text(profile_personal.get("whatsapp_number")),
            "email": self.seed_text(profile_personal.get("email"), verification_personal.get("email")),
            "employment_status": self.seed_text(employment_information.get("employment_status"), profile_personal.get("employment_status"), verification_personal.get("employment_status")),
            "occupation": self.seed_text(employment_information.get("occupation"), profile_personal.get("occupation"), verification_personal.get("occupation")),
            "employer_name": self.seed_text(employment_information.get("employer_name")),
            "job_title": self.seed_text(employment_information.get("job_title")),
            "employment_type": self.seed_text(employment_information.get("employment_type")),
            "work_address": self.seed_text(employment_information.get("work_address")),
            "work_email": self.seed_text(
                employment_information.get("work_email"),
                employment_information.get("work_email_address"),
                profile_personal.get("work_email"),
                verification_personal.get("work_email"),
            ),
            "years_employed": self.seed_text(employment_information.get("years_employed")),
            "hr_contact_name": self.seed_text(employment_information.get("hr_contact_name")),
            "hr_contact_number": self.seed_text(
                employment_information.get("hr_contact_number"),
                employment_information.get("hr_contact_phone"),
                employment_information.get("hr_phone"),
            ),
            "hr_contact_email": self.seed_text(
                employment_information.get("hr_contact_email"),
                employment_information.get("hr_email"),
                employment_information.get("hr_contact_mail"),
            ),
            "profession": self.seed_text(employment_information.get("profession")),
            "trading_name": self.seed_text(employment_information.get("trading_name")),
            "nature_of_work": self.seed_text(employment_information.get("nature_of_work")),
            "years_self_employed": self.seed_text(employment_information.get("years_self_employed")),
            "business_website": self.seed_text(employment_information.get("business_website")),
            "business_name": self.seed_text(employment_information.get("business_name")),
            "business_registration_number": self.seed_text(employment_information.get("business_registration_number")),
            "industry": self.seed_text(employment_information.get("industry")),
            "position_in_business": self.seed_text(employment_information.get("position_in_business")),
            "years_in_business": self.seed_text(employment_information.get("years_in_business")),
            "company_website": self.seed_text(employment_information.get("company_website")),
            "primary_service": self.seed_text(employment_information.get("primary_service")),
            "platform_used": self.seed_text(employment_information.get("platform_used")),
            "years_freelancing": self.seed_text(employment_information.get("years_freelancing")),
            "portfolio_website": self.seed_text(employment_information.get("portfolio_website")),
            "previous_occupation": self.seed_text(employment_information.get("previous_occupation")),
            "previous_employer": self.seed_text(employment_information.get("previous_employer")),
            "retirement_year": self.seed_text(employment_information.get("retirement_year")),
            "pension_provider": self.seed_text(employment_information.get("pension_provider")),
            "currently_seeking_employment": self.seed_text(employment_information.get("currently_seeking_employment")),
            "source_of_income": self.seed_text(employment_information.get("source_of_income")),
            "institution": self.seed_text(employment_information.get("institution")),
            "course_of_study": self.seed_text(employment_information.get("course_of_study")),
            "level": self.seed_text(employment_information.get("level")),
            "graduation_year": self.seed_text(employment_information.get("graduation_year")),
            "sponsorship_source": self.seed_text(employment_information.get("sponsorship_source")),
            "business_address": self.seed_text(employment_information.get("business_address")),
            "nin": nin,
            "bvn": bvn,
            "kyc": {
                "id_type": kyc_id_type or ("National ID (NIN)" if nin else ""),
                "id_number": self.seed_text(identity_and_bank.get("id_number"), nin),
                "expiry_date": self.seed_text(identity_and_bank.get("expiry_date")),
            },
            "residential_information": {
                "country": self.seed_text(residential_information.get("country")),
                "state": self.seed_text(residential_information.get("state")),
                "city": self.seed_text(residential_information.get("city")),
                "address": self.seed_text(residential_information.get("address"), verification_personal.get("residential_address")),
            },
            "proof_of_address": self.get_seed_list(residential_information, "proof_of_address"),
            "banking_information": {
                "bank_name": self.seed_text(identity_and_bank.get("bank_name"), profile_personal.get("bank_name"), verification_personal.get("bank_name")),
                "account_name": self.seed_text(identity_and_bank.get("account_name"), profile_personal.get("account_name"), verification_personal.get("account_name")),
                "account_number": self.seed_text(identity_and_bank.get("account_number"), profile_personal.get("account_number"), verification_personal.get("account_number")),
            },
            "emergency_contact": {
                "first_name": self.seed_text(emergency_contact.get("first_name")),
                "middle_name": self.seed_text(emergency_contact.get("middle_name")),
                "last_name": self.seed_text(emergency_contact.get("last_name")),
                "phone_number": self.seed_text(emergency_contact.get("phone_number")),
                "email": self.seed_text(emergency_contact.get("email")),
                "relationship": self.seed_text(emergency_contact.get("relationship")),
                "address": self.seed_text(emergency_contact.get("address")),
            },
        }
        return verification_type, payload

    def normalize_landlord_verification_type(self, value: str) -> str:
        text = self.seed_text(value).lower()
        text = text.replace(" landlord", "").replace("_landlord", "").strip()
        if text in {"individual", "personal"}:
            return AppUser.LandlordVerificationType.INDIVIDUAL
        if text in {"corporate", "company", "business"}:
            return AppUser.LandlordVerificationType.CORPORATE
        return text

    def resolve_profile_photo_path(self, seed_key: str, data: dict, login: dict, profile: dict, seed_path: Path) -> Path | None:
        for raw_photo in (
            profile.get("photo"),
            profile.get("profile_photo"),
            login.get("photo"),
            login.get("profile_photo"),
            data.get("photo"),
            data.get("profile_photo"),
        ):
            photo_path = self.resolve_path(raw_photo)
            if photo_path and photo_path.exists():
                return photo_path

        return self.resolve_path_with_alternate_extension([seed_path.parent / seed_key])

    def seed_verification(self, user: AppUser, data: dict) -> None:
        verification = data.get("verification") or {}
        docs = []

        for label, raw_path in verification.items():
            if not label.endswith("_document"):
                continue
            path = self.resolve_path(raw_path)
            if not path or not path.exists():
                continue

            title = path.stem.replace("_", " ").title()
            content_type = mimetypes.guess_type(path.name)[0] or ""
            doc, _ = Document.objects.get_or_create(
                owner=user,
                title=title,
                defaults={"content_type": content_type},
            )
            self.replace_model_file(doc, "file", path)
            doc.content_type = content_type
            doc.save()
            docs.append(doc)

        for raw_path in self.iter_landlord_identity_document_paths(data):
            path = self.resolve_path(raw_path)
            if not path or not path.exists():
                continue

            title = path.stem.replace("_", " ").title()
            content_type = mimetypes.guess_type(path.name)[0] or ""
            doc, _ = Document.objects.get_or_create(
                owner=user,
                title=title,
                defaults={"content_type": content_type},
            )
            self.replace_model_file(doc, "file", path)
            doc.content_type = content_type
            doc.save()
            if doc not in docs:
                docs.append(doc)

        if not docs and not verification and not user.landlord_verification_profile:
            return

        request, _ = VerificationRequest.objects.get_or_create(
            user=user,
            defaults={
                "request_type": VerificationRequest.RequestType.IDENTIFICATION,
            },
        )
        request.request_type = VerificationRequest.RequestType.IDENTIFICATION
        request.status = VerificationRequest.Status.APPROVED
        request.identity_verification_status = VerificationRequest.VerificationProgressStatus.VERIFIED
        request.property_document_verification_status = VerificationRequest.VerificationProgressStatus.VERIFIED
        request.physical_property_status = VerificationRequest.VerificationProgressStatus.VERIFIED
        request.verification_method = VerificationRequest.Method.AUTOMATED
        request.reviewed_at = request.reviewed_at or timezone.now()
        request.save(
            update_fields=[
                "request_type",
                "status",
                "identity_verification_status",
                "property_document_verification_status",
                "physical_property_status",
                "verification_method",
                "reviewed_at",
            ]
        )
        request.documents.set(docs)

    def seed_landlord_subscription(self, seed_key: str, user: AppUser, data: dict) -> None:
        subscription_plan = data.get("subscription_plan")
        if subscription_plan is None:
            return
        if not isinstance(subscription_plan, dict):
            raise ValueError(f"Seed entry {seed_key} subscription_plan must be an object")

        plan_code = self.normalize_seed_subscription_plan(
            self.seed_text(subscription_plan.get("plan"), subscription_plan.get("plan_code"))
        )
        billing_cycle = self.normalize_seed_subscription_billing_cycle(
            self.seed_text(
                subscription_plan.get("billing_cycle"),
                subscription_plan.get("billing_type"),
                subscription_plan.get("billing"),
            )
        )
        status = self.normalize_seed_subscription_status(
            self.seed_text(subscription_plan.get("subscription_status"), subscription_plan.get("status"))
        )

        if status != SubscriptionPayment.Status.COMPLETED:
            raise ValueError(f"Seed entry {seed_key} subscription_status must be active")

        try:
            amount_value = get_subscription_pricing()[AppUser.Role.LANDLORD][plan_code][billing_cycle]
        except KeyError as exc:
            raise ValueError(f"Seed entry {seed_key} has an unavailable landlord subscription plan") from exc

        now = timezone.now()
        transaction_id = f"SEED-SUB-{user.id.hex}"
        payment, _ = SubscriptionPayment.objects.get_or_create(
            transaction_id=transaction_id,
            defaults={
                "user": user,
                "role": user.role,
                "plan_code": plan_code,
                "billing_cycle": billing_cycle,
                "amount": Decimal(str(amount_value)),
                "currency": "NGN",
                "status": status,
                "provider": "seed_demo",
                "payment_date": now,
                "expires_at": now + timedelta(days=self.seed_subscription_duration_days(billing_cycle)),
            },
        )

        payment.user = user
        payment.role = user.role
        payment.plan_code = plan_code
        payment.billing_cycle = billing_cycle
        payment.amount = Decimal(str(amount_value))
        payment.currency = "NGN"
        payment.status = status
        payment.provider = "seed_demo"
        payment.cashier_url = ""
        payment.payment_method = None
        payment.provider_charge_id = transaction_id
        payment.recurring_enabled = False
        payment.billing_reason = "seed_demo"
        payment.renewed_from = None
        payment.provider_payload = {
            "source": "seed_demo_data",
            "seed_key": seed_key,
            "dummy_payment": True,
            "gateway_bypassed": True,
        }
        payment.webhook_data = None
        payment.payment_date = now
        payment.expires_at = now + timedelta(days=self.seed_subscription_duration_days(billing_cycle))
        payment.save(
            update_fields=[
                "user",
                "role",
                "plan_code",
                "billing_cycle",
                "amount",
                "currency",
                "status",
                "provider",
                "cashier_url",
                "payment_method",
                "provider_charge_id",
                "recurring_enabled",
                "billing_reason",
                "renewed_from",
                "provider_payload",
                "webhook_data",
                "payment_date",
                "expires_at",
                "updated_at",
            ]
        )

    def normalize_seed_subscription_plan(self, value: str) -> str:
        plan_code = self.seed_text(value).lower().replace(" ", "_")
        valid_plan_codes = {choice[0] for choice in SubscriptionPayment.PlanCode.choices}
        if plan_code not in valid_plan_codes:
            raise ValueError(f"Subscription plan must be one of: {', '.join(sorted(valid_plan_codes))}")
        return plan_code

    def normalize_seed_subscription_billing_cycle(self, value: str) -> str:
        billing_cycle = self.seed_text(value).lower().replace(" ", "_")
        aliases = {
            "month": SubscriptionPayment.BillingCycle.MONTHLY,
            "monthly": SubscriptionPayment.BillingCycle.MONTHLY,
            "montly": SubscriptionPayment.BillingCycle.MONTHLY,
            "year": SubscriptionPayment.BillingCycle.YEARLY,
            "annual": SubscriptionPayment.BillingCycle.YEARLY,
            "annually": SubscriptionPayment.BillingCycle.YEARLY,
            "yearly": SubscriptionPayment.BillingCycle.YEARLY,
        }
        normalized_cycle = aliases.get(billing_cycle, billing_cycle)
        valid_cycles = {choice[0] for choice in SubscriptionPayment.BillingCycle.choices}
        if normalized_cycle not in valid_cycles:
            raise ValueError(f"Subscription billing cycle must be one of: {', '.join(sorted(valid_cycles))}")
        return normalized_cycle

    def normalize_seed_subscription_status(self, value: str) -> str:
        status = self.seed_text(value).lower().replace(" ", "_") or "active"
        aliases = {
            "active": SubscriptionPayment.Status.COMPLETED,
            "completed": SubscriptionPayment.Status.COMPLETED,
        }
        normalized_status = aliases.get(status, status)
        valid_statuses = {choice[0] for choice in SubscriptionPayment.Status.choices}
        if normalized_status not in valid_statuses:
            raise ValueError(f"Subscription status must be one of: active, {', '.join(sorted(valid_statuses))}")
        return normalized_status

    def seed_subscription_duration_days(self, billing_cycle: str) -> int:
        return 30 if billing_cycle == SubscriptionPayment.BillingCycle.MONTHLY else 365

    def seed_tenant_subscription(self, seed_key: str, user: AppUser, data: dict) -> None:
        subscription_plan = data.get("subscription_plan")
        if subscription_plan is None:
            return
        if not isinstance(subscription_plan, dict):
            raise ValueError(f"Seed entry {seed_key} subscription_plan must be an object")

        plan_code = self.normalize_seed_subscription_plan(
            self.seed_text(subscription_plan.get("plan"), subscription_plan.get("plan_code"))
        )
        billing_cycle = self.normalize_seed_subscription_billing_cycle(
            self.seed_text(
                subscription_plan.get("billing_cycle"),
                subscription_plan.get("billing_type"),
                subscription_plan.get("billing"),
            )
        )
        status = self.normalize_seed_subscription_status(
            self.seed_text(subscription_plan.get("subscription_status"), subscription_plan.get("status"))
        )

        if status != SubscriptionPayment.Status.COMPLETED:
            raise ValueError(f"Seed entry {seed_key} subscription_status must be active")

        try:
            amount_value = get_subscription_pricing()[AppUser.Role.TENANT][plan_code][billing_cycle]
        except KeyError as exc:
            raise ValueError(f"Seed entry {seed_key} has an unavailable tenant subscription plan") from exc

        now = timezone.now()
        transaction_id = f"SEED-SUB-{user.id.hex}"
        payment, _ = SubscriptionPayment.objects.get_or_create(
            transaction_id=transaction_id,
            defaults={
                "user": user,
                "role": user.role,
                "plan_code": plan_code,
                "billing_cycle": billing_cycle,
                "amount": Decimal(str(amount_value)),
                "currency": "NGN",
                "status": status,
                "provider": "seed_demo",
                "payment_date": now,
                "expires_at": now + timedelta(days=self.seed_subscription_duration_days(billing_cycle)),
            },
        )

        payment.user = user
        payment.role = user.role
        payment.plan_code = plan_code
        payment.billing_cycle = billing_cycle
        payment.amount = Decimal(str(amount_value))
        payment.currency = "NGN"
        payment.status = status
        payment.provider = "seed_demo"
        payment.cashier_url = ""
        payment.payment_method = None
        payment.provider_charge_id = transaction_id
        payment.recurring_enabled = False
        payment.billing_reason = "seed_demo"
        payment.renewed_from = None
        payment.provider_payload = {
            "source": "seed_demo_data",
            "seed_key": seed_key,
            "dummy_payment": True,
            "gateway_bypassed": True,
        }
        payment.webhook_data = None
        payment.payment_date = now
        payment.expires_at = now + timedelta(days=self.seed_subscription_duration_days(billing_cycle))
        payment.save(
            update_fields=[
                "user",
                "role",
                "plan_code",
                "billing_cycle",
                "amount",
                "currency",
                "status",
                "provider",
                "cashier_url",
                "payment_method",
                "provider_charge_id",
                "recurring_enabled",
                "billing_reason",
                "renewed_from",
                "provider_payload",
                "webhook_data",
                "payment_date",
                "expires_at",
                "updated_at",
            ]
        )

    def seed_tenant_verification(self, user: AppUser, data: dict) -> None:
        verification = data.get("verification") or {}
        if not verification:
            return

        request, _ = VerificationRequest.objects.get_or_create(
            user=user,
            defaults={
                "request_type": VerificationRequest.RequestType.IDENTIFICATION,
            },
        )
        request.request_type = VerificationRequest.RequestType.IDENTIFICATION
        request.status = VerificationRequest.Status.APPROVED
        request.identity_verification_status = VerificationRequest.VerificationProgressStatus.VERIFIED
        request.property_document_verification_status = VerificationRequest.VerificationProgressStatus.VERIFIED
        request.physical_property_status = VerificationRequest.VerificationProgressStatus.VERIFIED
        request.verification_method = VerificationRequest.Method.AUTOMATED
        request.reviewed_at = request.reviewed_at or timezone.now()
        request.save(
            update_fields=[
                "request_type",
                "status",
                "identity_verification_status",
                "property_document_verification_status",
                "physical_property_status",
                "verification_method",
                "reviewed_at",
            ]
        )

    def seed_tenant_profile(self, seed_key: str, user: AppUser, data: dict) -> None:
        payload = self.build_tenant_profile_payload(seed_key, user, data)
        if not payload:
            return

        profile, created = TenantProfile.objects.get_or_create(
            user=user,
            defaults=payload,
        )
        if created:
            return

        for field_name, value in payload.items():
            setattr(profile, field_name, value)
        profile.save(update_fields=[*payload.keys(), "updated_at"])

    def build_tenant_profile_payload(self, seed_key: str, user: AppUser, data: dict) -> dict:
        profile = data.get("profile") or {}
        if not profile:
            return {}

        verification = data.get("verification") or {}
        personal = self.get_seed_dict(profile, "personal_information")
        current_residence = self.get_seed_dict(profile, "current_residence")
        employment_info = self.get_seed_dict(profile, "employment_info", "employment_information")
        financial_info = self.get_seed_dict(profile, "financial_info", "financial_verification")
        guarantor_details = self.get_seed_dict(profile, "guarantor_details")
        landlord_info = self.normalize_tenant_landlord_info(
            self.get_seed_dict(profile, "landlord_info", "current_landlord_information")
        )
        household_info = self.normalize_tenant_household_info(
            self.get_seed_dict(profile, "household_info", "household_information")
        )
        social_presence = self.get_seed_dict(profile, "social_presence")
        criminal_declaration = self.get_seed_dict(profile, "criminal_declaration")
        rental_history = self.build_tenant_rental_history(profile, current_residence)

        current_financial_defaults = {
            "current_rent_amount": self.first_seed_value(
                current_residence.get("current_rent_amount"),
                current_residence.get("annual_rent"),
            ),
            "current_service_charge": self.first_seed_value(
                current_residence.get("current_service_charge"),
                current_residence.get("service_charge"),
            ),
            "current_move_in_date": self.normalized_seed_date_string(
                self.first_seed_value(
                    current_residence.get("current_move_in_date"),
                    current_residence.get("move_in_date"),
                )
            ),
            "expected_move_out_date": self.normalized_seed_date_string(
                current_residence.get("expected_move_out_date")
            ),
            "reason_for_wanting_to_leave": self.first_seed_value(
                current_residence.get("reason_for_wanting_to_leave"),
                current_residence.get("reason_for_leaving"),
            ),
        }
        for field_name, value in current_financial_defaults.items():
            if self.has_seed_value(value) and not self.has_seed_value(financial_info.get(field_name)):
                financial_info[field_name] = value

        payload = {
            "first_name": self.seed_text(personal.get("first_name"), profile.get("first_name"), verification.get("first_name")),
            "middle_name": self.seed_text(personal.get("middle_name"), profile.get("middle_name"), verification.get("middle_name")),
            "last_name": self.seed_text(personal.get("last_name"), profile.get("last_name"), verification.get("last_name")),
            "date_of_birth": self.parse_tenant_profile_date(
                self.first_seed_value(personal.get("date_of_birth"), profile.get("date_of_birth"), verification.get("date_of_birth")),
                seed_key,
                "date_of_birth",
            ),
            "gender": self.seed_text(personal.get("gender"), profile.get("gender"), verification.get("gender")),
            "nationality": self.seed_text(personal.get("nationality"), profile.get("nationality"), verification.get("nationality")),
            "state_of_origin": self.seed_text(personal.get("state_of_origin"), profile.get("state_of_origin"), verification.get("state_of_origin")),
            "lga": self.seed_text(personal.get("lga"), profile.get("lga"), verification.get("lga")),
            "employment_status": self.seed_text(personal.get("employment_status"), profile.get("employment_status"), verification.get("employment_status")),
            "residence_country": self.seed_text(current_residence.get("residence_country"), current_residence.get("country")),
            "residence_state": self.seed_text(current_residence.get("residence_state"), current_residence.get("state")),
            "residence_city": self.seed_text(current_residence.get("residence_city"), current_residence.get("city")),
            "residence_lga": self.seed_text(current_residence.get("residence_lga"), current_residence.get("lga")),
            "residence_address": self.seed_text(current_residence.get("residence_address"), current_residence.get("address")),
            "length_of_stay": self.seed_text(current_residence.get("length_of_stay")),
            "housing_status": self.seed_text(current_residence.get("housing_status")),
            "employment_info": employment_info,
            "financial_info": financial_info,
            "guarantor_details": guarantor_details,
            "landlord_info": landlord_info,
            "rental_history": rental_history,
            "household_info": household_info,
            "social_presence": social_presence,
            "criminal_declaration": criminal_declaration,
            "status": self.seed_tenant_profile_status(profile.get("status")),
        }

        missing_fields = [
            field_name
            for field_name in (
                "first_name",
                "last_name",
                "date_of_birth",
                "gender",
                "nationality",
                "state_of_origin",
                "lga",
                "employment_status",
                "residence_country",
                "residence_state",
                "residence_city",
                "residence_lga",
                "residence_address",
                "length_of_stay",
                "housing_status",
            )
            if not self.has_seed_value(payload.get(field_name))
        ]
        if missing_fields:
            raise ValueError(f"Tenant seed profile {seed_key} is missing: {', '.join(missing_fields)}")

        return payload

    def build_full_name_from_seed(self, source: dict) -> str:
        return " ".join(
            part
            for part in (
                self.seed_text(source.get("first_name")),
                self.seed_text(source.get("middle_name")),
                self.seed_text(source.get("last_name")),
            )
            if part
        )

    def iter_landlord_identity_document_paths(self, data: dict):
        profile = data.get("profile") or {}
        verification = data.get("verification") or {}
        profile_personal = self.get_seed_dict(profile, "personal_information")
        identity_and_bank = self.get_seed_dict(profile, "identity_and_bank_verification")
        landlord_identification = self.get_seed_dict(verification, "landlord_identification")
        landlord_identification_personal = self.get_seed_dict(landlord_identification, "personal_information")
        seen = set()
        for raw_path in (
            profile_personal.get("identity_document"),
            identity_and_bank.get("identity_document"),
            landlord_identification_personal.get("identity_document"),
        ):
            raw_text = self.seed_text(raw_path)
            if raw_text and raw_text not in seen:
                seen.add(raw_text)
                yield raw_text

    def build_residence_from_current_residence(self, current_residence: dict) -> dict:
        if not current_residence:
            return {}
        return {
            "state": self.seed_text(current_residence.get("residence_state"), current_residence.get("state")),
            "city": self.seed_text(current_residence.get("residence_city"), current_residence.get("city")),
            "address": self.seed_text(current_residence.get("residence_address"), current_residence.get("address")),
        }

    def normalize_tenant_landlord_info(self, landlord_info: dict) -> dict:
        if not landlord_info:
            return {}

        normalized = dict(landlord_info)
        aliases = {
            "name": ("full_name", "landlord_name"),
            "mobile": ("phone", "phone_number", "mobile_number", "landlord_phone"),
            "property_manager_phone": ("property_manager_mobile", "property_manager_phone_number", "property_manager_mobile_number"),
        }
        for canonical_key, alias_keys in aliases.items():
            if self.has_seed_value(normalized.get(canonical_key)):
                continue
            for alias_key in alias_keys:
                if self.has_seed_value(normalized.get(alias_key)):
                    normalized[canonical_key] = normalized[alias_key]
                    break

        for alias_key in ("full_name", "landlord_name", "phone", "phone_number", "mobile_number", "landlord_phone"):
            normalized.pop(alias_key, None)
        for alias_key in ("property_manager_mobile", "property_manager_phone_number", "property_manager_mobile_number"):
            normalized.pop(alias_key, None)
        return normalized

    def normalize_tenant_household_info(self, household_info: dict) -> dict:
        if not household_info:
            return {}

        normalized = dict(household_info)
        aliases = {
            "has_smokers": ("any_smokers", "smokers", "has_any_smokers"),
            "has_pets": ("pets",),
        }
        for canonical_key, alias_keys in aliases.items():
            if self.has_seed_value(normalized.get(canonical_key)):
                continue
            for alias_key in alias_keys:
                if self.has_seed_value(normalized.get(alias_key)):
                    normalized[canonical_key] = normalized[alias_key]
                    break

        for alias_key in ("any_smokers", "smokers", "has_any_smokers", "pets"):
            normalized.pop(alias_key, None)
        return normalized

    def build_tenant_rental_history(self, profile: dict, current_residence: dict) -> list[dict]:
        raw_history = profile.get("rental_history")
        if raw_history is None:
            return []

        same_as_current_residence = False
        history_items = []
        if isinstance(raw_history, list):
            history_items = raw_history
        elif isinstance(raw_history, dict):
            same_as_current_residence = bool(raw_history.get("same_as_current_residence"))
            history_items = raw_history.get("properties") or []
            if not isinstance(history_items, list):
                raise ValueError("rental_history.properties must be an array")
        else:
            raise ValueError("rental_history must be an array or object")

        rental_history = []
        if same_as_current_residence:
            current_residence_history = self.build_current_residence_rental_history_entry(current_residence)
            if any(self.has_seed_value(value) for value in current_residence_history.values()):
                rental_history.append(current_residence_history)

        for item in history_items:
            if not isinstance(item, dict):
                raise ValueError("rental_history entries must be objects")
            normalized_item = self.normalize_tenant_rental_history_item(item)
            if any(self.has_seed_value(value) for value in normalized_item.values()):
                rental_history.append(normalized_item)

        return rental_history

    def build_current_residence_rental_history_entry(self, current_residence: dict) -> dict:
        return {
            "property_address": self.seed_text(
                current_residence.get("property_address"),
                current_residence.get("residence_address"),
                current_residence.get("address"),
            ),
            "annual_rent": self.seed_text(
                current_residence.get("annual_rent"),
                current_residence.get("current_rent_amount"),
            ),
            "service_charge": self.seed_text(
                current_residence.get("service_charge"),
                current_residence.get("current_service_charge"),
            ),
            "move_in_date": self.normalized_seed_date_string(
                self.first_seed_value(
                    current_residence.get("move_in_date"),
                    current_residence.get("current_move_in_date"),
                )
            ),
            "move_out_date": self.normalized_seed_date_string(
                self.first_seed_value(
                    current_residence.get("move_out_date"),
                    current_residence.get("expected_move_out_date"),
                )
            ),
            "reason_for_leave": self.seed_text(
                current_residence.get("reason_for_leave"),
                current_residence.get("reason_for_leaving"),
                current_residence.get("reason_for_wanting_to_leave"),
            ),
        }

    def normalize_tenant_rental_history_item(self, item: dict) -> dict:
        normalized = dict(item)
        field_aliases = {
            "property_address": ("address", "residence_address"),
            "annual_rent": ("rent", "current_rent_amount"),
            "service_charge": ("current_service_charge",),
            "move_in_date": ("current_move_in_date",),
            "move_out_date": ("expected_move_out_date",),
            "reason_for_leave": ("reason_for_leaving", "reason_for_wanting_to_leave"),
        }
        for canonical_key, alias_keys in field_aliases.items():
            if self.has_seed_value(normalized.get(canonical_key)):
                continue
            for alias_key in alias_keys:
                if self.has_seed_value(normalized.get(alias_key)):
                    normalized[canonical_key] = normalized[alias_key]
                    break

        for date_key in ("move_in_date", "move_out_date"):
            if self.has_seed_value(normalized.get(date_key)):
                normalized[date_key] = self.normalized_seed_date_string(normalized[date_key])
        return normalized

    def get_seed_dict(self, source: dict, *field_names: str) -> dict:
        for field_name in field_names:
            value = source.get(field_name)
            if value is None:
                continue
            if not isinstance(value, dict):
                raise ValueError(f"{field_name} must be an object")
            return dict(value)
        return {}

    def get_seed_list(self, source: dict, field_name: str) -> list:
        value = source.get(field_name)
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError(f"{field_name} must be an array")
        return value

    def get_seed_path_values(self, source: dict, *field_names: str) -> list:
        values = []
        for field_name in field_names:
            value = source.get(field_name)
            if not self.has_seed_value(value):
                continue
            if isinstance(value, list):
                values.extend(value)
            else:
                values.append(value)
        return values

    def first_seed_value(self, *values):
        for value in values:
            if self.has_seed_value(value):
                return value.strip() if isinstance(value, str) else value
        return ""

    def has_seed_value(self, value) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return value.strip() != ""
        return True

    def seed_text(self, *values) -> str:
        value = self.first_seed_value(*values)
        return str(value).strip()

    def seed_bool(self, *values, default: bool = False) -> bool:
        value = self.first_seed_value(*values)
        if value == "":
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        return bool(value)

    def seed_optional_int(self, value) -> int | None:
        if not self.has_seed_value(value):
            return None
        return int(value)

    def seed_decimal(self, value, *, default: Decimal | None = None) -> Decimal | None:
        if not self.has_seed_value(value):
            return default
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"Invalid decimal seed value: {value}") from exc

    def calculate_seed_deposit_amount(self, price_per_year: Decimal) -> Decimal:
        return (price_per_year * Decimal("0.20")).quantize(Decimal("0.01"))

    def normalized_seed_date_string(self, value) -> str:
        if not self.has_seed_value(value):
            return ""
        return normalize_tenant_verification_date(value)

    def parse_tenant_profile_date(self, value, seed_key: str, field_name: str):
        normalized_value = self.normalized_seed_date_string(value)
        parsed_value = parse_date(normalized_value)
        if not parsed_value:
            raise ValueError(f"Tenant seed profile {seed_key} has an invalid {field_name}")
        return parsed_value

    def parse_listing_date(self, value, seed_key: str, field_name: str) -> date | None:
        if not self.has_seed_value(value):
            return None
        if isinstance(value, date):
            return value

        raw_value = str(value).strip()
        parsed_value = parse_date(raw_value)
        if parsed_value:
            return parsed_value

        for date_format in ("%d/%m/%Y", "%m/%d/%Y"):
            try:
                return datetime.strptime(raw_value, date_format).date()
            except ValueError:
                continue
        raise ValueError(f"Listing seed {seed_key} has an invalid {field_name}")

    def seed_tenant_profile_status(self, value) -> str:
        status = self.seed_text(value) or TenantProfile.Status.APPROVED
        valid_statuses = {choice[0] for choice in TenantProfile.Status.choices}
        if status not in valid_statuses:
            raise ValueError(f"Tenant profile status must be one of: {', '.join(sorted(valid_statuses))}")
        return status

    def seed_listings(self, user: AppUser, data: dict) -> int:
        created_listings = 0
        seed_listings = list((data.get("listings") or {}).items())
        desired_listing_keys = {listing_key for listing_key, _ in seed_listings}
        existing_seedless = list(
            Listing.objects.filter(landlord=user, seed_key="")
            .order_by("created_at", "title")
        )
        used_listing_ids = set()

        for listing_key, raw_listing_data in seed_listings:
            listing_data = self.normalize_listing_seed_data(raw_listing_data)
            title = (listing_data.get("title") or listing_key.replace("_", " ").title()).strip()
            listing = Listing.objects.filter(landlord=user, seed_key=listing_key).first()
            if not listing:
                legacy_match = (
                    Listing.objects.filter(landlord=user, title=title)
                    .exclude(id__in=used_listing_ids)
                    .order_by("created_at")
                    .first()
                )
                if legacy_match:
                    listing = legacy_match
                else:
                    listing = next((item for item in existing_seedless if item.id not in used_listing_ids), None)

            if listing:
                used_listing_ids.add(listing.id)
                if listing.seed_key != listing_key:
                    listing.seed_key = listing_key
            else:
                listing = Listing(
                    landlord=user,
                    title=title,
                    seed_key=listing_key,
                )
                created_listings += 1

            features = listing_data.get("features") or {}
            rental_preferences = listing_data.get("rental_preferences") or {}
            property_verification = listing_data.get("property_verification") or {}
            price_per_year = self.seed_decimal(listing_data.get("price_per_year"), default=Decimal("0"))
            verification_method = self.resolve_listing_verification_method(property_verification)
            listing.title = title
            listing.description = listing_data.get("description", "")
            listing.address = listing_data.get("address", "")
            listing.city = listing_data.get("city", "")
            listing.state = listing_data.get("state") or (user.residence or {}).get("state", "")
            listing.postal_code = listing_data.get("postal_code", "")
            listing.property_type = listing_data.get("property_type", "Apartment")
            listing.bedrooms = listing_data.get("bedrooms") or listing_data.get("bedroom") or 1
            listing.bathrooms = listing_data.get("bathrooms") or listing_data.get("bathroom") or 1
            listing.toilets = listing_data.get("toilets") or listing.bathrooms
            listing.square_feet = listing_data.get("square_feet")
            listing.price_per_year = price_per_year
            listing.deposit_amount = self.calculate_seed_deposit_amount(price_per_year)
            listing.utilities_included = self.seed_bool(features.get("utilities_included"))
            listing.pet_friendly = self.seed_bool(features.get("pet_friendly"), rental_preferences.get("pets_allowed"))
            listing.furnished = self.seed_bool(features.get("furnished"))
            listing.amenities = features.get("amenities", [])
            listing.ownership_status = ""
            listing.ownership_types = self.get_seed_list(property_verification, "ownership_types")
            listing.property_ownership_documents = self.get_seed_list(property_verification, "ownership_documents") or self.get_seed_list(
                property_verification,
                "property_ownership_documents",
            )
            listing.property_document_submission = self.build_listing_property_document_submission(
                listing,
                verification_method,
                uploaded_document_count=0,
            )
            listing.property_document_verification_status = (
                VerificationRequest.VerificationProgressStatus.VERIFIED
            )
            listing.physical_property_status = (
                VerificationRequest.VerificationProgressStatus.VERIFIED
            )
            listing.minimum_rental_duration = self.seed_text(
                rental_preferences.get("minimum_rental_duration"),
                rental_preferences.get("minimum_lease_duration"),
            )
            listing.maximum_occupancy = self.seed_optional_int(rental_preferences.get("maximum_occupancy"))
            listing.smoking_allowed = self.seed_bool(rental_preferences.get("smoking_allowed"))
            listing.commercial_activities_allowed = self.seed_bool(rental_preferences.get("commercial_activities_allowed"))
            listing.short_let_allowed = self.seed_bool(rental_preferences.get("short_let_allowed"))
            listing.student_tenants_allowed = self.seed_bool(rental_preferences.get("student_tenants_allowed"))
            listing.expatriates_allowed = self.seed_bool(rental_preferences.get("expatriates_allowed"))
            listing.available_from = self.parse_listing_date(listing_data.get("available_from"), listing_key, "available_from")
            listing.featured = self.seed_bool(features.get("feature_property_checkbox"), default=True)
            listing.featured_until = None
            listing.status = Listing.Status.AVAILABLE
            listing.save()

            uploaded_property_documents = self.sync_listing_property_documents(
                user,
                listing,
                property_verification,
                verification_method,
            )
            if listing.property_document_submission:
                listing.property_document_submission["uploaded_document_count"] = uploaded_property_documents
                listing.save(update_fields=["property_document_submission", "updated_at"])

            cover_path = self.resolve_path(listing_data.get("cover_image"))
            desired_image_ids = set()
            if cover_path and cover_path.exists():
                desired_image_ids.add(self.ensure_listing_image(listing, cover_path, is_cover=True, sort_order=0))

            image_patterns = listing_data.get("additional_images") or []
            for index, image_path in enumerate(self.expand_patterns(image_patterns), start=1):
                if cover_path and cover_path.exists() and image_path.resolve() == cover_path.resolve():
                    continue
                desired_image_ids.add(self.ensure_listing_image(listing, image_path, is_cover=False, sort_order=index))

            self.remove_stale_listing_images(listing, desired_image_ids)

        Listing.objects.filter(landlord=user).exclude(seed_key="").exclude(seed_key__in=desired_listing_keys).delete()

        return created_listings

    def normalize_listing_seed_data(self, listing_data: dict) -> dict:
        normalized = dict(listing_data)
        property_information = self.get_seed_dict(listing_data, "property_information")
        if property_information:
            normalized.update(property_information)

        property_verification = self.get_seed_dict(
            listing_data,
            "property_ownership_verification",
            "property_ownership verification",
            "property_verification",
        )
        normalized["property_verification"] = property_verification

        rental_preferences = self.get_seed_dict(listing_data, "rental_preferences")
        images = self.get_seed_dict(listing_data, "images")
        features = {
            **self.get_seed_dict(listing_data, "features"),
            **self.get_seed_dict(rental_preferences, "features"),
            **self.get_seed_dict(listing_data, "feature_property"),
        }

        normalized["features"] = features
        normalized["rental_preferences"] = rental_preferences
        if images.get("cover_image") and not normalized.get("cover_image"):
            normalized["cover_image"] = images["cover_image"]
        if images.get("additional_images") and not normalized.get("additional_images"):
            normalized["additional_images"] = images["additional_images"]
        return normalized

    def resolve_listing_verification_method(self, property_verification: dict) -> str:
        method = property_verification.get("property_verification_method") or property_verification.get("verification_method")
        if isinstance(method, dict):
            if method.get("upload_documents"):
                return "documents"
            if method.get("in_person_verification"):
                return "in_person"
            return ""

        normalized = self.seed_text(method).lower().replace("-", "_").replace(" ", "_")
        if normalized in {"documents", "upload_documents", "document_upload"}:
            return "documents"
        if normalized in {"in_person", "in_person_verification", "physical", "physical_verification"}:
            return "in_person"
        return ""

    def build_listing_property_document_submission(self, listing: Listing, verification_method: str, *, uploaded_document_count: int) -> dict | None:
        if not verification_method and not listing.ownership_types and not listing.property_ownership_documents:
            return None
        return {
            "document_types": listing.property_ownership_documents or [],
            "ownership_types": listing.ownership_types or [],
            "in_person_verification_requested": verification_method == "in_person",
            "uploaded_document_count": uploaded_document_count,
            "submitted_at": timezone.now().isoformat(),
        }

    def sync_listing_property_documents(self, user: AppUser, listing: Listing, property_verification: dict, verification_method: str) -> int:
        title_prefix = f"Listing Property Document: {listing.id}"
        existing_documents = list(listing.property_documents.all())
        listing.property_documents.clear()
        for document in existing_documents:
            if document.title.startswith(title_prefix):
                document.file.delete(save=False)
                document.delete()
        for document in Document.objects.filter(owner=user, title__startswith=title_prefix):
            document.file.delete(save=False)
            document.delete()

        raw_paths = self.get_seed_path_values(
            property_verification,
            "property_documents",
            "documents",
            "property_document",
        )

        if verification_method != "documents" and not raw_paths:
            return 0

        property_paths = []
        for raw_path in raw_paths:
            raw_text = str(raw_path)
            if any(marker in raw_text for marker in ("*", "{")):
                property_paths.extend(self.expand_patterns([raw_text]))
                continue
            path = self.resolve_path(raw_text)
            if path and path.exists() and path.is_file():
                property_paths.append(path)

        uploaded_documents = []
        for path in property_paths:
            content_type = mimetypes.guess_type(path.name)[0] or ""
            document = Document(
                owner=user,
                title=build_listing_property_document_title(
                    listing,
                    path.name,
                    listing.property_ownership_documents,
                ),
                content_type=content_type,
            )
            self.replace_model_file(document, "file", path)
            document.save()
            uploaded_documents.append(document)

        if uploaded_documents:
            listing.property_documents.add(*uploaded_documents)
        return len(uploaded_documents)

    def ensure_listing_image(self, listing: Listing, path: Path, *, is_cover: bool, sort_order: int) -> str:
        match = listing.images.filter(is_cover=is_cover, sort_order=sort_order).first()

        if match:
            updated = False
            if match.is_cover != is_cover:
                match.is_cover = is_cover
                updated = True
            if match.sort_order != sort_order:
                match.sort_order = sort_order
                updated = True
            self.replace_model_file(match, "file", path)
            if updated:
                match.save(update_fields=["file", "is_cover", "sort_order"])
            else:
                match.save(update_fields=["file"])
            return str(match.id)

        image = ListingImage(
            listing=listing,
            is_cover=is_cover,
            sort_order=sort_order,
        )
        self.replace_model_file(image, "file", path)
        image.save()
        return str(image.id)

    def remove_stale_listing_images(self, listing: Listing, desired_image_ids: set[str]) -> None:
        for image in listing.images.all():
            if not image.file:
                image.delete()
                continue
            if str(image.id) not in desired_image_ids:
                image.file.delete(save=False)
                image.delete()

    def expand_patterns(self, patterns: list[str]) -> list[Path]:
        files = []
        seen = set()
        for pattern in patterns:
            for path in self.resolve_glob(pattern):
                if path.name not in seen and path.is_file():
                    files.append(path)
                    seen.add(path.name)
        return files

    def resolve_glob(self, raw_pattern: str) -> list[Path]:
        cleaned = raw_pattern.replace("{*.*}", "*.*").replace("{*}", "*")
        expanded = self._expand_braces(cleaned)
        for pattern in expanded:
            candidates = self.resolve_candidates(pattern)
            for candidate in candidates:
                matches = [Path(item) for item in sorted(glob.glob(str(candidate)))]
                if matches:
                    return matches
        return []

    def _expand_braces(self, pattern: str) -> list[str]:
        import re
        m = re.search(r'\{([^}]+)\}', pattern)
        if not m:
            return [pattern]
        prefix, suffix = pattern[:m.start()], pattern[m.end():]
        options = m.group(1).split(",")
        results = []
        for opt in options:
            results.extend(self._expand_braces(prefix + opt + suffix))
        return results

    def resolve_path(self, raw_path: str | None) -> Path | None:
        if not raw_path:
            return None
        candidates = self.resolve_candidates(raw_path)
        for candidate in candidates:
            if candidate.exists():
                return candidate

        fallback = self.resolve_path_with_alternate_extension(candidates)
        if fallback is not None:
            return fallback

        return candidates[0]

    def resolve_path_with_alternate_extension(self, candidates: list[Path]) -> Path | None:
        for candidate in candidates:
            parent = candidate.parent
            if not parent.exists():
                continue

            matches = sorted(
                path
                for path in parent.glob(f"{candidate.stem}.*")
                if path.is_file()
            )
            if matches:
                return matches[0]

        return None

    def resolve_candidates(self, raw_path: str) -> list[Path]:
        raw = Path(raw_path)
        candidates = []
        repo_root = settings.BASE_DIR.parent.parent

        if raw.is_absolute():
            candidates.append(raw)
        else:
            candidates.append(settings.BASE_DIR / raw)
            candidates.append(settings.BASE_DIR.parent / raw)
            candidates.append(repo_root / raw)

            raw_text = raw.as_posix()
            if "seed_demo_data/" in raw_text:
                _, suffix = raw_text.split("seed_demo_data/", 1)
                candidates.append(settings.BASE_DIR / "seed_demo_data" / suffix)

            for prefix in ("apps/api/", "api/"):
                if prefix in raw_text:
                    _, suffix = raw_text.split(prefix, 1)
                    candidates.append(settings.BASE_DIR / suffix)

        unique_candidates = []
        seen = set()
        for candidate in candidates:
            key = str(candidate)
            if key not in seen:
                unique_candidates.append(candidate)
                seen.add(key)
        return unique_candidates

    def replace_model_file(self, instance, field_name: str, source_path: Path) -> None:
        field = getattr(instance, field_name)

        if field and field.name:
            field.delete(save=False)

        with source_path.open("rb") as fh:
            field.save(source_path.name, File(fh), save=False)
