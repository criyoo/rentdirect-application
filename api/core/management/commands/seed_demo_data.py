import glob
import json
import mimetypes
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.dateparse import parse_date

from core.models import AppUser, Document, Listing, ListingImage, TenantProfile, VerificationRequest
from core.profile_validation import is_valid_mobile, is_valid_nin, normalize_residence, normalize_state_of_origin
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
                    created_listings += self.seed_listings(user, data)
                elif role == AppUser.Role.TENANT:
                    self.seed_tenant_verification(user, data)
                    self.seed_tenant_profile(seed_key, user, data)

        self.stdout.write(self.style.SUCCESS(f"Seed complete. Created {created_users} users and {created_listings} listings."))

    def upsert_user(self, seed_key: str, data: dict, role: str, seed_path: Path):
        login = data.get("login") or {}
        profile = data.get("profile") or {}
        verification = data.get("verification") or {}
        email = (login.get("email") or profile.get("email") or verification.get("email") or data.get("email") or "").strip().lower()
        if not email:
            raise ValueError(f"Seed entry {seed_key} is missing an email address")

        name = (
            login.get("full_name")
            or profile.get("full_name")
            or profile.get("name")
            or data.get("full_name")
            or seed_key.replace("_", " ").title()
        ).strip()
        user, created = AppUser.objects.get_or_create(
            email=email,
            defaults={"name": name, "role": role, "email_verified": True},
        )

        user.name = name
        user.role = role
        user.email_verified = True
        user.mobile = (profile.get("mobile") or verification.get("mobile") or "").strip()
        user.nin_number = (profile.get("nin_number") or verification.get("nin_number") or verification.get("nin") or "").strip()
        user.bvn_number = (profile.get("bvn_number") or verification.get("bvn_number") or verification.get("bvn") or "").strip()
        if user.mobile and not is_valid_mobile(user.mobile):
            raise ValueError(f"Seed entry {seed_key} has an invalid mobile number")
        if user.nin_number and not is_valid_nin(user.nin_number):
            raise ValueError(f"Seed entry {seed_key} has an invalid NIN number")
        user.state_of_origin = normalize_state_of_origin(profile.get("state_of_origin") or verification.get("state_of_origin"))
        user.residence = normalize_residence(user.state_of_origin, profile.get("residence"))
        if role == AppUser.Role.TENANT:
            user.tenant_verification_profile = normalize_tenant_verification_profile(verification, user)
        elif role == AppUser.Role.LANDLORD:
            self.seed_landlord_profile_fields(seed_key, user, data, profile)
        password = login.get("password") or data.get("password")
        if password:
            user.set_password(password)

        photo_path = self.resolve_profile_photo_path(seed_key, data, login, profile, seed_path)
        if photo_path and photo_path.exists():
            self.replace_model_file(user, "profile_photo", photo_path)

        user.save()
        return user, created

    def seed_landlord_profile_fields(self, seed_key: str, user: AppUser, data: dict, profile: dict) -> None:
        verification_type = self.seed_text(
            profile.get("landlord_verification_type"),
            data.get("landlord_verification_type"),
        ).lower()
        if "landlord_verification_profile" in profile:
            verification_profile = profile.get("landlord_verification_profile")
        else:
            verification_profile = data.get("landlord_verification_profile")

        if not verification_type and not verification_profile:
            user.landlord_verification_type = ""
            user.landlord_verification_profile = None
            return

        valid_types = {
            AppUser.LandlordVerificationType.INDIVIDUAL,
            AppUser.LandlordVerificationType.CORPORATE,
        }
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

        if docs:
            request = VerificationRequest.objects.filter(user=user).order_by("-submitted_at").first()
            if not request:
                request = VerificationRequest.objects.create(
                    user=user,
                    status=VerificationRequest.Status.APPROVED,
                    identity_verification_status=VerificationRequest.VerificationProgressStatus.VERIFIED,
                    property_document_verification_status=VerificationRequest.VerificationProgressStatus.VERIFIED,
                    physical_property_status=VerificationRequest.VerificationProgressStatus.UNVERIFIED,
                    reviewed_at=timezone.now(),
                )
            else:
                request.status = VerificationRequest.Status.APPROVED
                request.identity_verification_status = VerificationRequest.VerificationProgressStatus.VERIFIED
                request.property_document_verification_status = VerificationRequest.VerificationProgressStatus.VERIFIED
                request.physical_property_status = VerificationRequest.VerificationProgressStatus.UNVERIFIED
                request.reviewed_at = request.reviewed_at or timezone.now()
                request.save(
                    update_fields=[
                        "status",
                        "identity_verification_status",
                        "property_document_verification_status",
                        "physical_property_status",
                        "reviewed_at",
                    ]
            )
            request.documents.set(docs)

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
        request.property_document_verification_status = VerificationRequest.VerificationProgressStatus.UNVERIFIED
        request.physical_property_status = VerificationRequest.VerificationProgressStatus.UNVERIFIED
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
        landlord_info = self.get_seed_dict(profile, "landlord_info")
        household_info = self.get_seed_dict(profile, "household_info")
        social_presence = self.get_seed_dict(profile, "social_presence")
        criminal_declaration = self.get_seed_dict(profile, "criminal_declaration")
        rental_history = self.get_seed_list(profile, "rental_history")

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

        for listing_key, listing_data in seed_listings:
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
            listing.price_per_year = listing_data.get("price_per_year") or 0
            listing.utilities_included = features.get("utilities_included", False)
            listing.pet_friendly = features.get("pet_friendly", False)
            listing.furnished = features.get("furnished", False)
            listing.amenities = features.get("amenities", [])
            listing.featured = features.get("feature_property_checkbox", True)
            listing.featured_until = None
            listing.status = Listing.Status.AVAILABLE
            listing.save()

            cover_path = self.resolve_path(listing_data.get("cover_image"))
            desired_image_names = set()
            if cover_path and cover_path.exists():
                self.ensure_listing_image(listing, cover_path, is_cover=True, sort_order=0)
                desired_image_names.add(self.build_seed_image_name(listing, cover_path))

            image_patterns = listing_data.get("additional_images") or []
            for index, image_path in enumerate(self.expand_patterns(image_patterns), start=1):
                self.ensure_listing_image(listing, image_path, is_cover=False, sort_order=index)
                desired_image_names.add(self.build_seed_image_name(listing, image_path))

            self.remove_stale_listing_images(listing, desired_image_names)

        Listing.objects.filter(landlord=user).exclude(seed_key="").exclude(seed_key__in=desired_listing_keys).delete()

        return created_listings

    def build_seed_image_name(self, listing: Listing, source_path: Path) -> str:
        return f"{listing.id}_{source_path.name}"

    def ensure_listing_image(self, listing: Listing, path: Path, *, is_cover: bool, sort_order: int) -> None:
        target_name = self.build_seed_image_name(listing, path)
        existing = {Path(image.file.name).name: image for image in listing.images.all() if image.file}
        match = existing.get(target_name)

        if match:
            updated = False
            if match.is_cover != is_cover:
                match.is_cover = is_cover
                updated = True
            if match.sort_order != sort_order:
                match.sort_order = sort_order
                updated = True
            self.replace_model_file(match, "file", path, target_name=target_name)
            if updated:
                match.save(update_fields=["file", "is_cover", "sort_order"])
            else:
                match.save(update_fields=["file"])
            return

        image = ListingImage(
            listing=listing,
            is_cover=is_cover,
            sort_order=sort_order,
        )
        self.replace_model_file(image, "file", path, target_name=target_name)
        image.save()

    def remove_stale_listing_images(self, listing: Listing, desired_image_names: set[str]) -> None:
        for image in listing.images.all():
            if not image.file:
                image.delete()
                continue
            if Path(image.file.name).name not in desired_image_names:
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

    def replace_model_file(self, instance, field_name: str, source_path: Path, *, target_name: str | None = None) -> None:
        field = getattr(instance, field_name)
        if field and field.name:
            field.delete(save=False)

        with source_path.open("rb") as fh:
            field.save(target_name or source_path.name, File(fh), save=False)
