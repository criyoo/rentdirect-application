import base64
import hashlib
import hmac
import json
import re
from io import StringIO
from pathlib import Path
from datetime import date, timedelta
from decimal import Decimal
import tempfile
from unittest.mock import patch

from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test.utils import override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core import flutterwave
from core.management.commands.seed_demo_data import Command as SeedDemoDataCommand
from core.flutterwave import FlutterwaveError
from core.models import AppUser, Booking, BvnVerificationRecord, CacVerificationRecord, CommunityChatMessage, Document, Feedback, FeaturedPayment, Listing, ListingImage, Message, NinVerificationRecord, Payment, PaymentSettlement, Review, SubscriptionPayment, SubscriptionPaymentMethod, SupportChatMessage, TenantProfile, VerificationRequest
from core.payment_queue import TASK_PROCESS_READY_PAYOUTS, enqueue_payment_task
from core.prembly_verification import (
    PremblyWebhookVerificationError,
    validate_prembly_webhook_request,
    verify_prembly_webhook_signature,
)
from core.pricing import calculate_booking_total, calculate_deposit_amount
from core.security import hash_otp
from core.serializers import UserSerializer
from core.subscription_pricing import get_subscription_pricing
from core.tenant_scoring import build_tenant_screening_summary


TEST_FILE_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": settings.STORAGES["staticfiles"],
}


def save_rental_progress_steps(testcase, client, booking_id, *, step_keys=(), step_responses=None):
    response = None
    for step_key in step_keys:
        response = client.patch(
            f"/api/v1/bookings/{booking_id}/rental-progress",
            {"step_keys": [step_key]},
            format="json",
        )
        testcase.assertEqual(response.status_code, 200, response.json())
    for step_key, value in (step_responses or {}).items():
        response = client.patch(
            f"/api/v1/bookings/{booking_id}/rental-progress",
            {"step_responses": {step_key: value}},
            format="json",
        )
        testcase.assertEqual(response.status_code, 200, response.json())
    return response


def create_active_subscription(user, plan_code=SubscriptionPayment.PlanCode.SILVER, *, days=30):
    return SubscriptionPayment.objects.create(
        user=user,
        role=user.role,
        plan_code=plan_code,
        billing_cycle=SubscriptionPayment.BillingCycle.MONTHLY,
        amount=0 if plan_code == SubscriptionPayment.PlanCode.BRONZE else 100,
        currency="NGN",
        status=SubscriptionPayment.Status.COMPLETED,
        transaction_id=f"SUBTEST{plan_code[:3].upper()}{user.id.hex[:20]}",
        payment_date=timezone.now(),
        expires_at=timezone.now() + timedelta(days=days),
    )


class PremblyWebhookSecurityTests(TestCase):
    def _signature(self, raw_body: bytes, public_key: str) -> str:
        digest = hmac.new(public_key.encode("utf-8"), raw_body, hashlib.sha256).digest()
        return base64.b64encode(digest).decode("utf-8")

    @override_settings(PREMBLY_API_PUBLIC_KEY="test-prembly-public-key")
    def test_prembly_webhook_signature_verifies_raw_body(self):
        raw_body = b'{"status":"completed","data":{"session_id":"123"}}'
        signature = self._signature(raw_body, settings.PREMBLY_API_PUBLIC_KEY)

        self.assertTrue(verify_prembly_webhook_signature(raw_body=raw_body, signature=signature))
        self.assertFalse(verify_prembly_webhook_signature(raw_body=raw_body + b" ", signature=signature))

    @override_settings(PREMBLY_API_PUBLIC_KEY="")
    def test_prembly_webhook_signature_rejects_missing_public_key(self):
        raw_body = b'{"status":"completed"}'
        signature = self._signature(raw_body, "test-prembly-public-key")

        with self.assertLogs("core.prembly_verification", level="WARNING"):
            self.assertFalse(verify_prembly_webhook_signature(raw_body=raw_body, signature=signature))

    @override_settings(PREMBLY_API_PUBLIC_KEY="test-prembly-public-key", PREMBLY_WEBHOOK_TOKEN_CACHE_SECONDS=60)
    def test_prembly_webhook_request_requires_signature_and_tracks_token(self):
        raw_body = b'{"status":"completed","data":{"session_id":"123"}}'
        token = "prembly-token-123"
        cache.delete(f"prembly_webhook_token:{hashlib.sha256(token.encode('utf-8')).hexdigest()}")
        headers = {
            "x-prembly-signature": self._signature(raw_body, settings.PREMBLY_API_PUBLIC_KEY),
            "token": token,
        }

        validation = validate_prembly_webhook_request(headers=headers, raw_body=raw_body)
        duplicate_validation = validate_prembly_webhook_request(headers=headers, raw_body=raw_body)

        self.assertEqual(validation["token"], token)
        self.assertFalse(validation["already_processed"])
        self.assertTrue(duplicate_validation["already_processed"])

    @override_settings(PREMBLY_API_PUBLIC_KEY="test-prembly-public-key")
    def test_prembly_webhook_request_rejects_missing_or_invalid_security_headers(self):
        raw_body = b'{"status":"completed"}'

        with self.assertRaises(PremblyWebhookVerificationError):
            validate_prembly_webhook_request(headers={}, raw_body=raw_body)
        with self.assertRaises(PremblyWebhookVerificationError):
            validate_prembly_webhook_request(
                headers={
                    "x-prembly-signature": self._signature(raw_body, settings.PREMBLY_API_PUBLIC_KEY),
                    "token": "token-1",
                },
                raw_body=b'{"status":"tampered"}',
            )


class HealthTests(TestCase):
    def test_health_ready(self):
        response = self.client.get("/api/health/ready")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "healthy")
        self.assertEqual(response.json()["database"], "connected")

    def test_healthcheck_paths_bypass_disallowed_host_validation(self):
        for path in ["/", "/health", "/api/health", "/api/health/ready"]:
            with self.subTest(path=path):
                response = self.client.get(path, HTTP_HOST="18.202.161.240")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["status"], "ok")

    def test_invalid_host_returns_400_without_raising(self):
        self.client.raise_request_exception = False
        response = self.client.get("/dashboard/.git/config", HTTP_HOST="18.202.11.71")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content.decode(), "Invalid host header")

    def test_development_api_host_can_reach_admin(self):
        response = self.client.get("/admin/", HTTP_HOST="api.development.rentdirect.homes")
        self.assertEqual(response.status_code, 302)
        self.assertNotEqual(response.content.decode(), "Invalid host header")

    @patch(
        "core.views.database_healthcheck",
        return_value=(False, {"status": "unhealthy", "environment": "test", "database": "pending_migrations"}),
    )
    def test_health_ready_returns_503_when_database_is_not_ready(self, _healthcheck):
        response = self.client.get("/api/health/ready")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["database"], "pending_migrations")

    def test_homepage_video_serves_packaged_media_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            video_dir = base_dir / "uploads" / "seed" / "video"
            media_root = base_dir / "media-root"
            video_dir.mkdir(parents=True)
            (video_dir / "rentdirect.mp4").write_bytes(b"fake video")

            with override_settings(BASE_DIR=base_dir, MEDIA_ROOT=media_root, STORAGES=TEST_FILE_STORAGES):
                response = self.client.get("/api/v1/homepage-video")

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Content-Type"], "video/mp4")
                self.assertEqual(b"".join(response.streaming_content), b"fake video")

    def test_homepage_video_supports_range_requests(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            video_dir = base_dir / "uploads" / "seed" / "video"
            media_root = base_dir / "media-root"
            video_dir.mkdir(parents=True)
            (video_dir / "rentdirect.mp4").write_bytes(b"0123456789")

            with override_settings(BASE_DIR=base_dir, MEDIA_ROOT=media_root, STORAGES=TEST_FILE_STORAGES):
                response = self.client.get("/api/v1/homepage-video", HTTP_RANGE="bytes=2-5")

                self.assertEqual(response.status_code, 206)
                self.assertEqual(response["Content-Type"], "video/mp4")
                self.assertEqual(response["Content-Range"], "bytes 2-5/10")
                self.assertEqual(response["Accept-Ranges"], "bytes")
                self.assertEqual(response["Content-Length"], "4")
                self.assertEqual(b"".join(response.streaming_content), b"2345")

    def test_homepage_video_redirects_to_remote_storage_url(self):
        with patch("core.views.default_storage") as storage:
            storage.exists.return_value = True
            storage.path.side_effect = NotImplementedError
            storage.url.return_value = "https://media.example.com/seed/video/rentdirect.mp4"

            response = self.client.get("/api/v1/homepage-video")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://media.example.com/seed/video/rentdirect.mp4")
        self.assertEqual(response["Cache-Control"], "public, max-age=3600")


class AuthViewSetTests(TestCase):
    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", WEB_PUBLIC_URL="https://rentdirect.homes")
    def test_register_sends_branded_html_otp_email(self):
        response = self.client.post(
            "/api/v1/auth/register",
            {
                "name": "Email User",
                "email": "email-user@example.com",
                "password": "password-123",
                "role": AppUser.Role.TENANT,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.subject, "Your RentDirect verification code")
        self.assertEqual(message.to, ["email-user@example.com"])
        self.assertIn("Your RentDirect verification code is", message.body)
        self.assertIn("https://rentdirect.homes/register", message.body)
        html_body = message.alternatives[0][0]
        self.assertIn("Complete your RentDirect registration", html_body)
        self.assertIn("font-family:'Buenos Aires','Open Sans',Arial,Helvetica,sans-serif", html_body)
        self.assertIn("#2563EB", html_body)
        self.assertIn("#10B981", html_body)
        self.assertIn("email-user@example.com", html_body)

    def test_verify_registration_marks_user_verified_and_sets_auth_cookies(self):
        email = "verify-me@example.com"
        otp_code = "A1B2C3"
        AppUser.objects.create_user(
            email=email,
            password="password-123",
            name="Verify Me",
            role=AppUser.Role.LANDLORD,
            email_verified=False,
            registration_otp_hash=hash_otp(email, otp_code),
            registration_otp_expires_at=timezone.now() + timedelta(minutes=10),
        )

        response = self.client.post(
            "/api/v1/auth/register/verify",
            {"email": email, "otp_code": otp_code},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.json())
        verified_user = AppUser.objects.get(email=email)
        self.assertTrue(verified_user.email_verified)
        self.assertIn(settings.ACCESS_COOKIE_NAME, response.cookies)
        self.assertIn(settings.REFRESH_COOKIE_NAME, response.cookies)

    def test_login_ignores_stale_access_cookie_for_deleted_user(self):
        stale_user = AppUser.objects.create_user(
            email="stale-cookie@example.com",
            password="password-123",
            name="Stale Cookie",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        stale_access_token = str(RefreshToken.for_user(stale_user).access_token)
        stale_user.delete()
        AppUser.objects.create_user(
            email="active-login@example.com",
            password="password-123",
            name="Active Login",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        self.client.cookies[settings.ACCESS_COOKIE_NAME] = stale_access_token

        response = self.client.post(
            "/api/v1/auth/login",
            {"email": "active-login@example.com", "password": "password-123"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json()["email"], "active-login@example.com")
        self.assertIn(settings.ACCESS_COOKIE_NAME, response.cookies)
        self.assertIn(settings.REFRESH_COOKIE_NAME, response.cookies)


class ListingTests(TestCase):
    def tenant_client_with_plan(self, plan_code, suffix):
        tenant = AppUser.objects.create_user(
            email=f"listing-{suffix}@example.com",
            password="password-123",
            name="Listing Plan Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        create_active_subscription(tenant, plan_code)
        client = APIClient()
        client.force_authenticate(user=tenant)
        return client

    def test_public_listing_search_returns_available_listings(self):
        landlord = AppUser.objects.create_user(
            email="landlord@example.com",
            password="password-123",
            name="Demo Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        Listing.objects.create(
            landlord=landlord,
            title="Ikoyi Apartment",
            description="A bright apartment in Ikoyi",
            address="23 Gerald Road",
            city="Ikoyi",
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=2500000,
        )

        response = self.client.get("/api/v1/listings/search?city=Ikoyi")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        results = payload["results"] if isinstance(payload, dict) and "results" in payload else payload
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Ikoyi Apartment")

    def test_public_listing_search_supports_case_insensitive_type_and_exact_room_filters(self):
        landlord = AppUser.objects.create_user(
            email="landlord-search@example.com",
            password="password-123",
            name="Search Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        Listing.objects.create(
            landlord=landlord,
            title="Luxury Duplex",
            description="Spacious duplex in Lekki",
            address="14 Admiralty Way",
            city="Lekki",
            property_type="Duplex",
            bedrooms=4,
            bathrooms=3,
            price_per_year=5500000,
            furnished=True,
            pet_friendly=True,
            utilities_included=True,
        )
        Listing.objects.create(
            landlord=landlord,
            title="Small Flat",
            description="Compact flat in Lekki",
            address="2 Freedom Road",
            city="Lekki",
            property_type="Flat",
            bedrooms=1,
            bathrooms=1,
            price_per_year=1200000,
        )
        Listing.objects.create(
            landlord=landlord,
            title="Three Bed Duplex",
            description="Exact room match in Lekki",
            address="8 Admiralty Way",
            city="Lekki",
            property_type="Duplex",
            bedrooms=3,
            bathrooms=2,
            price_per_year=4300000,
            furnished=True,
            pet_friendly=True,
            utilities_included=True,
        )

        response = self.client.get(
            "/api/v1/listings/search?city=Lekki&property_type=duplex&bedrooms=3&bathrooms=2&furnished=true&pet_friendly=true&utilities_included=true"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        results = payload["results"] if isinstance(payload, dict) and "results" in payload else payload
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Three Bed Duplex")

    def test_public_listing_search_supports_state_and_toilet_filters(self):
        landlord = AppUser.objects.create_user(
            email="landlord-state@example.com",
            password="password-123",
            name="State Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
            residence={"state": "Lagos", "city": "Lekki", "address": "14 Admiralty Way"},
        )
        Listing.objects.create(
            landlord=landlord,
            title="Lagos Family House",
            description="Family house in Lagos",
            address="10 Freedom Way",
            city="Lekki",
            state="Lagos",
            property_type="House",
            bedrooms=4,
            bathrooms=4,
            toilets=5,
            price_per_year=6500000,
        )
        Listing.objects.create(
            landlord=landlord,
            title="Abuja Flat",
            description="Flat in Abuja",
            address="20 Aminu Kano Crescent",
            city="Wuse",
            state="FCT",
            property_type="Flat",
            bedrooms=2,
            bathrooms=2,
            toilets=2,
            price_per_year=2500000,
        )

        response = self.client.get("/api/v1/listings/search?state=Lagos&toilets=5")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        results = payload["results"] if isinstance(payload, dict) and "results" in payload else payload
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Lagos Family House")

    def test_public_listing_search_supports_distance_radius_with_stored_coordinates(self):
        landlord = AppUser.objects.create_user(
            email="landlord-distance@example.com",
            password="password-123",
            name="Distance Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        nearby_listing = Listing.objects.create(
            landlord=landlord,
            title="Victoria Island Apartment",
            description="Near the search point",
            address="10 Ozumba Mbadiwe",
            city="Victoria Island",
            state="Lagos",
            latitude=Decimal("6.428100"),
            longitude=Decimal("3.421900"),
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=3000000,
        )
        Listing.objects.create(
            landlord=landlord,
            title="Abuja Apartment",
            description="Outside the radius",
            address="22 Aminu Kano Crescent",
            city="Wuse",
            state="FCT",
            latitude=Decimal("9.076600"),
            longitude=Decimal("7.463700"),
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=3500000,
        )

        client = self.tenant_client_with_plan(SubscriptionPayment.PlanCode.SILVER, "stored-distance")
        response = client.get("/api/v1/listings/search?latitude=6.4281&longitude=3.4219&radius_km=5")

        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        results = payload["results"] if isinstance(payload, dict) and "results" in payload else payload
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], str(nearby_listing.id))
        self.assertLessEqual(results[0]["distance_km"], 5)

    def test_public_listing_search_supports_distance_radius_with_city_state_coordinates(self):
        landlord = AppUser.objects.create_user(
            email="landlord-city-distance@example.com",
            password="password-123",
            name="City Distance Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        listing = Listing.objects.create(
            landlord=landlord,
            title="Ikoyi Apartment",
            description="Uses city and state coordinates",
            address="12 Gerrard Road",
            city="Ikoyi",
            state="Lagos",
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=3000000,
        )

        client = self.tenant_client_with_plan(SubscriptionPayment.PlanCode.SILVER, "city-coordinates")
        response = client.get("/api/v1/listings/search?latitude=6.4541&longitude=3.4351&radius_km=2")

        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        results = payload["results"] if isinstance(payload, dict) and "results" in payload else payload
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], str(listing.id))
        self.assertEqual(results[0]["location_source"], "city_state")

    def test_public_listing_search_supports_distance_radius_from_origin_city_state(self):
        landlord = AppUser.objects.create_user(
            email="landlord-origin-distance@example.com",
            password="password-123",
            name="Origin Distance Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        ikoyi_listing = Listing.objects.create(
            landlord=landlord,
            title="Ikoyi Apartment",
            description="Near Apapa by distance",
            address="12 Gerrard Road",
            city="Ikoyi",
            state="Lagos",
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=3000000,
        )
        Listing.objects.create(
            landlord=landlord,
            title="Epe Apartment",
            description="Outside the selected radius",
            address="15 Marina Road",
            city="Epe",
            state="Lagos",
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=2500000,
        )

        client = self.tenant_client_with_plan(SubscriptionPayment.PlanCode.SILVER, "origin-distance")
        response = client.get("/api/v1/listings/search?origin_city=Apapa&origin_state=Lagos&radius_km=25")

        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        results = payload["results"] if isinstance(payload, dict) and "results" in payload else payload
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], str(ikoyi_listing.id))
        self.assertLessEqual(results[0]["distance_km"], 25)

    def test_public_listing_search_uses_city_as_origin_when_radius_has_no_coordinates(self):
        landlord = AppUser.objects.create_user(
            email="landlord-filter-origin-distance@example.com",
            password="password-123",
            name="Filter Origin Distance Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        ikoyi_listing = Listing.objects.create(
            landlord=landlord,
            title="Ikoyi Apartment",
            description="Near Apapa by distance",
            address="12 Gerrard Road",
            city="Ikoyi",
            state="Lagos",
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=3000000,
        )

        client = self.tenant_client_with_plan(SubscriptionPayment.PlanCode.SILVER, "filter-origin")
        response = client.get("/api/v1/listings/search?city=Apapa&state=Lagos&radius_km=25")

        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        results = payload["results"] if isinstance(payload, dict) and "results" in payload else payload
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], str(ikoyi_listing.id))
        self.assertLessEqual(results[0]["distance_km"], 25)

    def test_location_analytics_groups_available_listings(self):
        landlord = AppUser.objects.create_user(
            email="landlord-analytics@example.com",
            password="password-123",
            name="Analytics Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        Listing.objects.create(
            landlord=landlord,
            title="Ikoyi Apartment",
            description="Lagos listing",
            address="12 Gerrard Road",
            city="Ikoyi",
            state="Lagos",
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=2000000,
        )
        Listing.objects.create(
            landlord=landlord,
            title="Wuse Apartment",
            description="Abuja listing",
            address="20 Aminu Kano Crescent",
            city="Wuse",
            state="FCT",
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=4000000,
        )

        client = self.tenant_client_with_plan(SubscriptionPayment.PlanCode.SILVER, "analytics")
        response = client.get("/api/v1/listings/location-analytics")

        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        self.assertEqual(payload["total_listings"], 2)
        states = {item["name"]: item for item in payload["states"]}
        cities = {item["name"]: item for item in payload["cities"]}
        neighbourhoods = {item["name"]: item for item in payload["neighbourhoods"]}
        self.assertEqual(states["Lagos"]["listing_count"], 1)
        self.assertEqual(cities["Ikoyi"]["average_price_per_year"], 2000000)
        self.assertEqual(neighbourhoods["Gerrard Road"]["listing_count"], 1)
        self.assertEqual(neighbourhoods["Gerrard Road"]["average_price_per_year"], 2000000)

    def test_listing_nearest_amenities_returns_points_of_interest_by_category(self):
        landlord = AppUser.objects.create_user(
            email="landlord-amenities@example.com",
            password="password-123",
            name="Amenities Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        listing = Listing.objects.create(
            landlord=landlord,
            title="Lekki Apartment",
            description="Near Lekki amenities",
            address="1 Admiralty Way",
            city="Lekki",
            state="Lagos",
            latitude=Decimal("6.469800"),
            longitude=Decimal("3.585200"),
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=3500000,
        )

        client = self.tenant_client_with_plan(SubscriptionPayment.PlanCode.SILVER, "amenities")
        response = client.get(f"/api/v1/listings/{listing.id}/nearest-amenities?radius_km=15&limit=2")

        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        self.assertTrue(payload["location_available"])
        self.assertGreaterEqual(len(payload["amenities"]["schools"]), 1)
        self.assertGreaterEqual(len(payload["amenities"]["supermarkets"]), 1)

    def test_tenant_plan_tiers_control_location_and_property_verification_visibility(self):
        landlord = AppUser.objects.create_user(
            email="listing-visibility-landlord@example.com",
            password="password-123",
            name="Visibility Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        listing = Listing.objects.create(
            landlord=landlord,
            title="Visibility Listing",
            description="Plan visibility checks",
            address="10 Premium Location",
            city="Ikoyi",
            state="Lagos",
            postal_code="100001",
            latitude=Decimal("6.454100"),
            longitude=Decimal("3.435100"),
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=3000000,
            property_document_verification_status=VerificationRequest.VerificationProgressStatus.VERIFIED,
            physical_property_status=VerificationRequest.VerificationProgressStatus.VERIFIED,
        )

        public_payload = self.client.get(f"/api/v1/listings/{listing.id}").json()
        self.assertEqual(public_payload["address"], "")
        self.assertEqual(public_payload["city"], "")
        self.assertIsNone(public_payload["latitude"])
        self.assertIsNone(public_payload["property_document_verification_status"])

        bronze_client = self.tenant_client_with_plan(SubscriptionPayment.PlanCode.BRONZE, "bronze-visibility")
        bronze_payload = bronze_client.get(f"/api/v1/listings/{listing.id}").json()
        self.assertEqual(bronze_payload["address"], "")
        self.assertEqual(bronze_payload["city"], "")
        self.assertIsNone(bronze_payload["property_document_verification_status"])

        silver_client = self.tenant_client_with_plan(SubscriptionPayment.PlanCode.SILVER, "silver-visibility")
        silver_payload = silver_client.get(f"/api/v1/listings/{listing.id}").json()
        self.assertEqual(silver_payload["address"], listing.address)
        self.assertEqual(silver_payload["city"], listing.city)
        self.assertIsNone(silver_payload["property_document_verification_status"])

        gold_client = self.tenant_client_with_plan(SubscriptionPayment.PlanCode.GOLD, "gold-visibility")
        gold_payload = gold_client.get(f"/api/v1/listings/{listing.id}").json()
        self.assertEqual(gold_payload["address"], listing.address)
        self.assertEqual(
            gold_payload["property_document_verification_status"],
            VerificationRequest.VerificationProgressStatus.VERIFIED,
        )

        platinum_client = self.tenant_client_with_plan(
            SubscriptionPayment.PlanCode.PLATINUM,
            "platinum-visibility",
        )
        platinum_payload = platinum_client.get(f"/api/v1/listings/{listing.id}").json()
        self.assertEqual(platinum_payload["address"], listing.address)
        self.assertEqual(
            platinum_payload["property_document_verification_status"],
            VerificationRequest.VerificationProgressStatus.VERIFIED,
        )

    def test_bronze_tenant_cannot_use_paid_location_endpoints(self):
        landlord = AppUser.objects.create_user(
            email="listing-location-lock-landlord@example.com",
            password="password-123",
            name="Location Lock Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        listing = Listing.objects.create(
            landlord=landlord,
            title="Location Lock Listing",
            description="Location endpoints are gated",
            address="12 Locked Road",
            city="Ikoyi",
            state="Lagos",
            latitude=Decimal("6.454100"),
            longitude=Decimal("3.435100"),
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=3000000,
        )
        client = self.tenant_client_with_plan(SubscriptionPayment.PlanCode.BRONZE, "location-lock")

        distance_response = client.get(
            "/api/v1/listings/search?latitude=6.4541&longitude=3.4351&radius_km=5"
        )
        analytics_response = client.get("/api/v1/listings/location-analytics")
        amenities_response = client.get(f"/api/v1/listings/{listing.id}/nearest-amenities")
        cities_response = client.get("/api/v1/listings/cities")

        self.assertEqual(distance_response.status_code, 403)
        self.assertEqual(analytics_response.status_code, 403)
        self.assertEqual(amenities_response.status_code, 403)
        self.assertEqual(cities_response.status_code, 200)
        self.assertEqual(cities_response.json(), [])

    def test_landlord_cannot_retrieve_another_landlords_listing_detail(self):
        owner = AppUser.objects.create_user(
            email="owner@example.com",
            password="password-123",
            name="Owner Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        outsider = AppUser.objects.create_user(
            email="outsider@example.com",
            password="password-123",
            name="Outside Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        listing = Listing.objects.create(
            landlord=owner,
            title="Restricted Listing",
            description="Should not be visible to other landlords",
            address="1 Private Road",
            city="Ikoyi",
            state="Lagos",
            property_type="Apartment",
            bedrooms=3,
            bathrooms=3,
            toilets=3,
            price_per_year=4200000,
        )

        client = APIClient()
        client.force_authenticate(user=outsider)
        response = client.get(f"/api/v1/listings/{listing.id}")

        self.assertEqual(response.status_code, 404)

    def test_landlord_can_create_listing_with_multipart_amenities(self):
        landlord = AppUser.objects.create_user(
            email="landlord@example.com",
            password="password-123",
            name="Demo Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        VerificationRequest.objects.create(
            user=landlord,
            status=VerificationRequest.Status.APPROVED,
            identity_verification_status=VerificationRequest.VerificationProgressStatus.VERIFIED,
            property_document_verification_status=VerificationRequest.VerificationProgressStatus.VERIFIED,
        )
        client = APIClient()
        client.force_authenticate(user=landlord)

        cover_image = SimpleUploadedFile(
            "cover.gif",
            b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x00"
            b"\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;",
            content_type="image/gif",
        )
        additional_image = SimpleUploadedFile(
            "room.gif",
            b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x00"
            b"\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;",
            content_type="image/gif",
        )
        property_document = SimpleUploadedFile(
            "Office_Electric_Bill_EKEDC.pdf",
            b"property-document",
            content_type="application/pdf",
        )
        property_ownership_documents = [
            "Certificat of Occupancy (Cof)",
            "Deed of Assignment",
            "Governor's Consent",
        ]

        response = client.post(
            "/api/v1/listings",
            {
                "title": "Ikoyi Apartment",
                "description": "A bright apartment in Ikoyi",
                "address": "23 Gerald Road",
                "city": "Ikoyi",
                "state": "Lagos",
                "postal_code": "100021",
                "property_type": "Apartment",
                "bedrooms": 2,
                "bathrooms": 2,
                "toilets": 2,
                "price_per_year": "2500000",
                "amenities": ["gym", "parking"],
                "parking": "true",
                "garage": "true",
                "garden": "true",
                "lift": "true",
                "balcony": "true",
                "smart_lock": "true",
                "pop_ceiling": "true",
                "electric_fence": "true",
                "fitted_kitchen": "true",
                "ownership_types": ["Sole Owner"],
                "property_ownership_documents": property_ownership_documents,
                "property_verification_method": "documents",
                "property_documents": property_document,
                "minimum_rental_duration": "6 months",
                "maximum_occupancy": "4",
                "available_from": "2026-08-01",
                "smoking_allowed": "false",
                "commercial_activities_allowed": "false",
                "short_let_allowed": "true",
                "student_tenants_allowed": "true",
                "expatriates_allowed": "false",
                "cover_image": cover_image,
                "images": additional_image,
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 201, response.json())
        listing = Listing.objects.get(title="Ikoyi Apartment")
        self.assertEqual(listing.amenities, ["gym", "parking"])
        self.assertTrue(listing.parking)
        self.assertTrue(listing.garage)
        self.assertTrue(listing.garden)
        self.assertTrue(listing.lift)
        self.assertTrue(listing.balcony)
        self.assertTrue(listing.smart_lock)
        self.assertTrue(listing.pop_ceiling)
        self.assertTrue(listing.electric_fence)
        self.assertTrue(listing.fitted_kitchen)
        self.assertEqual(listing.ownership_types, ["Sole Owner"])
        self.assertEqual(listing.property_ownership_documents, property_ownership_documents)
        self.assertEqual(str(listing.deposit_amount), "500000.00")
        self.assertEqual(listing.property_documents.count(), 1)
        document = listing.property_documents.get()
        self.assertLessEqual(len(document.title), Document._meta.get_field("title").max_length)
        self.assertIn("Office_Electric_Bill_EKEDC.pdf", document.title)
        self.assertTrue(document.file.name.startswith(f"documents/{landlord.id}/{document.id}/document-"))
        self.assertRegex(document.file.name, r"/document-[0-9a-f]{32}\.pdf$")
        self.assertTrue(listing.images.filter(is_cover=True).exists())
        cover = listing.images.get(is_cover=True)
        self.assertTrue(cover.file.name.startswith(f"listings/{landlord.id}/{listing.id}/{cover.id}/listing-image-"))
        self.assertRegex(cover.file.name, r"/listing-image-[0-9a-f]{32}\.gif$")
        self.assertEqual(
            listing.property_document_verification_status,
            VerificationRequest.VerificationProgressStatus.PENDING,
        )
        self.assertEqual(listing.minimum_rental_duration, "6 months")
        self.assertEqual(listing.maximum_occupancy, 4)
        self.assertTrue(listing.short_let_allowed)
        self.assertTrue(listing.student_tenants_allowed)

    def test_resource_scoped_upload_paths_prevent_same_day_filename_clashes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with override_settings(MEDIA_ROOT=tmpdir, STORAGES=TEST_FILE_STORAGES):
                owner = AppUser.objects.create_user(
                    email="upload-owner@example.com",
                    password="password-123",
                    name="Upload Owner",
                    role=AppUser.Role.LANDLORD,
                    email_verified=True,
                )
                first = Document(owner=owner, title="First")
                first.file.save("same-name.pdf", SimpleUploadedFile("same-name.pdf", b"first"))
                first.save()
                second = Document(owner=owner, title="Second")
                second.file.save("same-name.pdf", SimpleUploadedFile("same-name.pdf", b"second"))
                second.save()

        self.assertNotEqual(first.file.name, second.file.name)
        self.assertTrue(first.file.name.startswith(f"documents/{owner.id}/{first.id}/document-"))
        self.assertTrue(second.file.name.startswith(f"documents/{owner.id}/{second.id}/document-"))
        self.assertRegex(first.file.name, r"/document-[0-9a-f]{32}\.pdf$")
        self.assertRegex(second.file.name, r"/document-[0-9a-f]{32}\.pdf$")

    def test_landlord_listing_requires_property_documents_or_in_person_verification(self):
        landlord = AppUser.objects.create_user(
            email="landlord-doc-required@example.com",
            password="password-123",
            name="Document Required Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        VerificationRequest.objects.create(
            user=landlord,
            status=VerificationRequest.Status.APPROVED,
            identity_verification_status=VerificationRequest.VerificationProgressStatus.VERIFIED,
        )
        client = APIClient()
        client.force_authenticate(user=landlord)
        cover_image = SimpleUploadedFile(
            "cover.gif",
            b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x00"
            b"\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;",
            content_type="image/gif",
        )
        additional_image = SimpleUploadedFile(
            "room.gif",
            b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x00"
            b"\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;",
            content_type="image/gif",
        )

        response = client.post(
            "/api/v1/listings",
            {
                "title": "No Document Listing",
                "description": "Should require property verification choice",
                "address": "23 Gerald Road",
                "city": "Ikoyi",
                "state": "Lagos",
                "postal_code": "100021",
                "property_type": "Apartment",
                "bedrooms": 2,
                "bathrooms": 2,
                "toilets": 2,
                "price_per_year": "2500000",
                "amenities": ["parking"],
                "ownership_types": ["Sole Owner"],
                "property_verification_method": "documents",
                "property_ownership_documents": ["Deed of Assignment"],
                "minimum_rental_duration": "6 months",
                "maximum_occupancy": "4",
                "available_from": "2026-08-01",
                "cover_image": cover_image,
                "images": additional_image,
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 400, response.json())
        self.assertIn("property_documents", response.json())

    def test_landlord_can_choose_in_person_verification_without_property_documents(self):
        landlord = AppUser.objects.create_user(
            email="landlord-in-person@example.com",
            password="password-123",
            name="In Person Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        VerificationRequest.objects.create(
            user=landlord,
            status=VerificationRequest.Status.APPROVED,
            identity_verification_status=VerificationRequest.VerificationProgressStatus.VERIFIED,
        )
        client = APIClient()
        client.force_authenticate(user=landlord)
        cover_image = SimpleUploadedFile(
            "cover.gif",
            b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x00"
            b"\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;",
            content_type="image/gif",
        )
        additional_image = SimpleUploadedFile(
            "room.gif",
            b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x00"
            b"\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;",
            content_type="image/gif",
        )

        response = client.post(
            "/api/v1/listings",
            {
                "title": "In Person Listing",
                "description": "Should not require uploaded property documents",
                "address": "45 Admiralty Road",
                "city": "Lekki",
                "state": "Lagos",
                "postal_code": "100022",
                "property_type": "Apartment",
                "bedrooms": 2,
                "bathrooms": 2,
                "toilets": 2,
                "price_per_year": "1800000",
                "amenities": ["parking"],
                "ownership_types": ["Sole Owner"],
                "property_verification_method": "in_person",
                "minimum_rental_duration": "6 months",
                "maximum_occupancy": "3",
                "available_from": "2026-08-01",
                "cover_image": cover_image,
                "images": additional_image,
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 201, response.json())
        listing = Listing.objects.get(title="In Person Listing")
        self.assertEqual(str(listing.deposit_amount), "360000.00")
        self.assertEqual(listing.property_documents.count(), 0)
        self.assertEqual(
            listing.physical_property_status,
            VerificationRequest.VerificationProgressStatus.PENDING,
        )

    def test_bronze_landlord_cannot_create_second_active_listing(self):
        landlord = AppUser.objects.create_user(
            email="bronze-limit-landlord@example.com",
            password="password-123",
            name="Bronze Limit Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        VerificationRequest.objects.create(
            user=landlord,
            status=VerificationRequest.Status.APPROVED,
            identity_verification_status=VerificationRequest.VerificationProgressStatus.VERIFIED,
            property_document_verification_status=VerificationRequest.VerificationProgressStatus.VERIFIED,
        )
        create_active_subscription(landlord, SubscriptionPayment.PlanCode.BRONZE, days=14)
        Listing.objects.create(
            landlord=landlord,
            title="Existing Bronze Listing",
            description="Existing listing",
            address="1 Bronze Road",
            city="Lagos",
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=2500000,
        )

        client = APIClient()
        client.force_authenticate(user=landlord)
        cover_image = SimpleUploadedFile(
            "cover.gif",
            b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x00"
            b"\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;",
            content_type="image/gif",
        )
        additional_image = SimpleUploadedFile(
            "room.gif",
            b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x00"
            b"\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;",
            content_type="image/gif",
        )
        response = client.post(
            "/api/v1/listings",
            {
                "title": "Second Bronze Listing",
                "description": "Should be blocked",
                "address": "2 Bronze Road",
                "city": "Lagos",
                "state": "Lagos",
                "postal_code": "100001",
                "property_type": "Apartment",
                "bedrooms": 2,
                "bathrooms": 2,
                "toilets": 2,
                "price_per_year": "2500000",
                "amenities": ["parking"],
                "ownership_types": ["Sole Owner"],
                "property_verification_method": "in_person",
                "minimum_rental_duration": "6 months",
                "maximum_occupancy": "4",
                "available_from": "2026-08-01",
                "cover_image": cover_image,
                "images": additional_image,
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 403, response.json())
        self.assertFalse(Listing.objects.filter(title="Second Bronze Listing").exists())

    def test_bronze_tenant_listing_detail_masks_location(self):
        landlord = AppUser.objects.create_user(
            email="location-mask-landlord@example.com",
            password="password-123",
            name="Location Mask Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        tenant = AppUser.objects.create_user(
            email="location-mask-tenant@example.com",
            password="password-123",
            name="Location Mask Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        create_active_subscription(tenant, SubscriptionPayment.PlanCode.BRONZE, days=14)
        listing = Listing.objects.create(
            landlord=landlord,
            title="Masked Location Listing",
            description="Location should be masked",
            address="12 Exact Street",
            city="Ikoyi",
            state="Lagos",
            postal_code="100001",
            latitude="6.450000",
            longitude="3.430000",
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=2500000,
        )

        client = APIClient()
        client.force_authenticate(user=tenant)
        response = client.get(f"/api/v1/listings/{listing.id}")

        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        self.assertEqual(payload["state"], "Lagos")
        self.assertEqual(payload["address"], "")
        self.assertEqual(payload["city"], "")
        self.assertEqual(payload["postal_code"], "")
        self.assertIsNone(payload["latitude"])
        self.assertIsNone(payload["longitude"])

    def test_landlord_can_update_existing_listing(self):
        landlord = AppUser.objects.create_user(
            email="editor@example.com",
            password="password-123",
            name="Editor Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        listing = Listing.objects.create(
            landlord=landlord,
            title="Original Title",
            description="Original description",
            address="10 Old Street",
            city="Lagos",
            postal_code="100001",
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=2500000,
            amenities=["parking"],
        )

        client = APIClient()
        client.force_authenticate(user=landlord)
        response = client.patch(
            f"/api/v1/listings/{listing.id}",
            {
                "title": "Updated Title",
                "description": "Updated description",
                "property_type": "Duplex",
                "bedrooms": 4,
                "bathrooms": 3,
                "square_feet": 3200,
                "price_per_year": "5000000",
                "amenities": ["gym", "parking"],
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 200, response.json())
        listing.refresh_from_db()
        self.assertEqual(Listing.objects.filter(landlord=landlord).count(), 1)
        self.assertEqual(listing.title, "Updated Title")
        self.assertEqual(listing.property_type, "Duplex")
        self.assertEqual(listing.bedrooms, 4)
        self.assertEqual(listing.bathrooms, 3)
        self.assertEqual(listing.square_feet, 3200)
        self.assertEqual(str(listing.price_per_year), "5000000.00")
        self.assertEqual(listing.amenities, ["gym", "parking"])


class UserSerializerValidationTests(TestCase):
    def test_rejects_invalid_mobile_nin_and_missing_origin_details(self):
        user = AppUser.objects.create_user(
            email="tenant@example.com",
            password="password-123",
            name="Tenant User",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        serializer = UserSerializer(
            user,
            data={
                "mobile": "12345",
                "nin_number": "123",
                "state_of_origin": "Others",
                "residence": {
                    "state": "Lagos",
                    "city": "Ikeja",
                    "address": "1 Allen Avenue",
                    "origin_country": "",
                    "origin_city": "",
                },
            },
            partial=True,
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("mobile", serializer.errors)
        self.assertIn("nin_number", serializer.errors)

    def test_rejects_missing_origin_details_when_state_is_others(self):
        user = AppUser.objects.create_user(
            email="tenant2@example.com",
            password="password-123",
            name="Tenant User 2",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        serializer = UserSerializer(
            user,
            data={
                "state_of_origin": "Others",
                "residence": {
                    "state": "Lagos",
                    "city": "Ikeja",
                    "address": "1 Allen Avenue",
                    "origin_country": "",
                    "origin_city": "",
                },
            },
            partial=True,
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("residence", serializer.errors)


class UserViewSetTests(TestCase):
    def test_authenticated_user_can_upload_profile_photo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with override_settings(MEDIA_ROOT=tmpdir, STORAGES=TEST_FILE_STORAGES):
                user = AppUser.objects.create_user(
                    email="photo-user@example.com",
                    password="password-123",
                    name="Photo User",
                    role=AppUser.Role.LANDLORD,
                    email_verified=True,
                )
                client = APIClient()
                client.force_authenticate(user=user)

                response = client.post(
                    "/api/v1/users/me/photo",
                    {
                        "file": SimpleUploadedFile(
                            "profile.jpg",
                            b"fake image content",
                            content_type="image/jpeg",
                        ),
                    },
                    format="multipart",
                )

                self.assertEqual(response.status_code, 200, response.json())
                user.refresh_from_db()
                self.assertTrue(user.profile_photo.name)
                self.assertTrue(user.profile_photo.name.startswith(f"profiles/{user.id}/profile-"))
                self.assertRegex(user.profile_photo.name, r"/profile-[0-9a-f]{32}\.jpg$")
                self.assertTrue(response.json()["profile_photo_url"])

    def test_subscription_pricing_endpoint_returns_shared_catalog(self):
        response = self.client.get("/api/v1/users/subscription-pricing")

        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json(), get_subscription_pricing())

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_authenticated_user_can_change_password(self):
        user = AppUser.objects.create_user(
            email="password-user@example.com",
            password="password-123",
            name="Password User",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)

        otp_response = client.post(
            "/api/v1/users/me/settings/request-otp",
            {
                "purpose": "password",
            },
            format="json",
        )

        self.assertEqual(otp_response.status_code, 200, otp_response.json())
        otp_match = re.search(r"\b([A-Z0-9]{6})\b", mail.outbox[0].body)
        self.assertIsNotNone(otp_match)

        response = client.post(
            "/api/v1/users/me/password",
            {
                "new_password": "new-password-456",
                "otp_code": otp_match.group(1),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.json())
        user.refresh_from_db()
        self.assertTrue(user.check_password("new-password-456"))
        self.assertEqual(user.settings_otp_hash, "")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_authenticated_user_can_update_settings_after_verifying_new_email(self):
        user = AppUser.objects.create_user(
            email="settings-user@example.com",
            password="password-123",
            name="Settings User",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)

        otp_response = client.post(
            "/api/v1/users/me/settings/request-otp",
            {
                "purpose": "profile",
                "target_email": "updated-settings-user@example.com",
            },
            format="json",
        )

        self.assertEqual(otp_response.status_code, 200, otp_response.json())
        self.assertEqual(mail.outbox[0].to, ["updated-settings-user@example.com"])
        otp_match = re.search(r"\b([A-Z0-9]{6})\b", mail.outbox[0].body)
        self.assertIsNotNone(otp_match)

        response = client.post(
            "/api/v1/users/me/settings",
            {
                "name": "Updated Settings User",
                "email": "updated-settings-user@example.com",
                "mobile": "08012345678",
                "state_of_origin": "Lagos",
                "residence": {
                    "state": "Lagos",
                    "city": "Lekki",
                    "address": "15 Admiralty Way",
                },
                "otp_code": otp_match.group(1),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.json())
        user.refresh_from_db()
        self.assertEqual(user.email, "updated-settings-user@example.com")
        self.assertEqual(user.name, "Settings User")
        self.assertEqual(user.settings_otp_hash, "")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_landlord_can_freeze_and_unfreeze_account_after_otp_verification(self):
        user = AppUser.objects.create_user(
            email="freeze-landlord@example.com",
            password="password-123",
            name="Freeze Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)

        client.post("/api/v1/users/me/settings/request-otp", {"purpose": "account"}, format="json")
        freeze_otp = re.search(r"\b([A-Z0-9]{6})\b", mail.outbox[-1].body).group(1)
        response = client.post(
            "/api/v1/users/me/freeze",
            {"duration_months": 3, "otp_code": freeze_otp},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.json())
        user.refresh_from_db()
        self.assertTrue(user.account_frozen)
        self.assertEqual(user.account_freeze_fee_percentage, Decimal("20.00"))
        self.assertTrue(user.account_frozen_until)

        client.post("/api/v1/users/me/settings/request-otp", {"purpose": "account"}, format="json")
        unfreeze_otp = re.search(r"\b([A-Z0-9]{6})\b", mail.outbox[-1].body).group(1)
        response = client.delete("/api/v1/users/me/freeze", {"otp_code": unfreeze_otp}, format="json")

        self.assertEqual(response.status_code, 200, response.json())
        user.refresh_from_db()
        self.assertFalse(user.account_frozen)
        self.assertIsNone(user.account_frozen_until)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_tenant_can_update_residence_and_guarantor_after_otp_verification(self):
        user = AppUser.objects.create_user(
            email="settings-tenant@example.com",
            password="password-123",
            name="Settings Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        TenantProfile.objects.create(
            user=user,
            first_name="Settings",
            middle_name="Test",
            last_name="Tenant",
            date_of_birth=date(1992, 3, 14),
            gender="Female",
            nationality="Nigerian",
            state_of_origin="Lagos",
            lga="Eti-Osa",
            employment_status="Employed",
            residence_country="Nigeria",
            residence_state="Lagos",
            residence_city="Lekki",
            residence_lga="Eti-Osa",
            residence_address="Old Address",
            length_of_stay="3 years",
            housing_status="Rented",
        )
        client = APIClient()
        client.force_authenticate(user=user)

        client.post("/api/v1/users/me/settings/request-otp", {"purpose": "profile"}, format="json")
        otp_code = re.search(r"\b([A-Z0-9]{6})\b", mail.outbox[-1].body).group(1)
        response = client.post(
            "/api/v1/users/me/settings",
            {
                "mobile": "08012345678",
                "residence": {"state": "Lagos", "city": "Ikoyi", "address": "New Address"},
                "guarantor_details": {
                    "full_name": "Guarantor Tenant",
                    "relationship": "Parent",
                    "email": "guarantor@example.com",
                    "mobile_number": "08087654321",
                    "occupation": "Engineer",
                    "employer": "Example Ltd",
                    "residential_address": "Guarantor Address",
                },
                "otp_code": otp_code,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.json())
        user.refresh_from_db()
        profile = TenantProfile.objects.get(user=user)
        self.assertEqual(profile.residence_city, "Ikoyi")
        self.assertEqual(profile.guarantor_details["full_name"], "Guarantor Tenant")
        self.assertEqual(user.tenant_verification_profile["guarantor_details"]["relationship"], "Parent")

    def test_landlord_can_save_identity_verification_details(self):
        user = AppUser.objects.create_user(
            email="identity-user@example.com",
            password="password-123",
            name="Identity User",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.patch(
            "/api/v1/users/me",
            {
                "landlord_verification_type": "individual",
                "landlord_verification_profile": {
                    "first_name": "Identity",
                    "last_name": "User",
                    "contact_number": "08012345678",
                    "email": "identity-user@example.com",
                    "nin": "12345678901",
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.json())
        user.refresh_from_db()
        self.assertEqual(user.landlord_verification_type, "individual")
        self.assertEqual(user.landlord_verification_profile["first_name"], "Identity")

    def test_landlord_can_save_profile_employment_details(self):
        user = AppUser.objects.create_user(
            email="profile-employment-user@example.com",
            password="password-123",
            name="Profile Employment User",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
            landlord_verification_type=AppUser.LandlordVerificationType.INDIVIDUAL,
        )
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.patch(
            "/api/v1/users/me",
            {
                "landlord_verification_type": "individual",
                "landlord_verification_profile": {
                    "first_name": "Profile",
                    "last_name": "Employment",
                    "contact_number": "08012345678",
                    "email": "profile-employment-user@example.com",
                    "nin": "12345678901",
                    "bvn": "10987654321",
                    "employment_status": "Employed",
                    "occupation": "Cloud Engineer",
                    "employer_name": "Conoco Philips",
                    "job_title": "Software Engineer",
                    "employment_type": "Full-time",
                    "work_address": "13 Ajose Adeogun, Victoria Island, Lagos",
                    "work_email": "profile.work@example.com",
                    "years_employed": "5",
                    "hr_contact_name": "Harriet Adams",
                    "hr_contact_number": "+2348091122334",
                    "hr_contact_email": "harriet@example.com",
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()["landlord_verification_profile"]
        self.assertEqual(payload["employment_status"], "Employed")
        self.assertEqual(payload["work_email"], "profile.work@example.com")
        self.assertEqual(payload["hr_contact_name"], "Harriet Adams")
        self.assertEqual(payload["hr_contact_number"], "+2348091122334")
        self.assertEqual(payload["hr_contact_email"], "harriet@example.com")
        self.assertNotIn("ownership_types", payload)
        self.assertNotIn("rental_preferences", payload)

    def test_landlord_can_save_corporate_identity_bank_and_id_details(self):
        user = AppUser.objects.create_user(
            email="corporate-identity-user@example.com",
            password="password-123",
            name="Corporate Identity User",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.patch(
            "/api/v1/users/me",
            {
                "landlord_verification_type": "corporate",
                "landlord_verification_profile": {
                    "company_name": "RentDirect Corporate Homes",
                    "cac_registration_number": "RC1234567",
                    "nin": "12345678901",
                    "bvn": "10987654321",
                    "bank_name": "OPay",
                    "account_name": "RentDirect Corporate Homes",
                    "account_number": "9041487757",
                    "corporate_banking_information": {
                        "bank_name": "OPay",
                        "account_name": "RentDirect Corporate Homes",
                        "account_number": "9041487757",
                    },
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.json())
        user.refresh_from_db()
        self.assertEqual(user.landlord_verification_type, "corporate")
        self.assertEqual(user.nin_number, "12345678901")
        self.assertEqual(user.bvn_number, "10987654321")
        self.assertEqual(user.landlord_verification_profile["bank_name"], "OPay")
        self.assertEqual(user.landlord_verification_profile["corporate_banking_information"]["account_number"], "9041487757")

    def test_my_favourites_returns_listing_payloads_for_current_tenant(self):
        tenant = AppUser.objects.create_user(
            email="tenant-favourite@example.com",
            password="password-123",
            name="Favourite Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        landlord = AppUser.objects.create_user(
            email="landlord-favourite@example.com",
            password="password-123",
            name="Favourite Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        listing = Listing.objects.create(
            landlord=landlord,
            title="Favourite Listing",
            description="Saved by the tenant",
            address="17 Admiralty Way",
            city="Lekki",
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=2200000,
        )
        other_listing = Listing.objects.create(
            landlord=landlord,
            title="Other Listing",
            description="Not favourited by this tenant",
            address="5 Bourdillon Road",
            city="Ikoyi",
            property_type="House",
            bedrooms=4,
            bathrooms=3,
            price_per_year=8200000,
        )

        favourite_tenant = APIClient()
        favourite_tenant.force_authenticate(user=tenant)
        favourite_tenant.post(f"/api/v1/users/me/favourites/{listing.id}")

        other_tenant = AppUser.objects.create_user(
            email="other-favourite@example.com",
            password="password-123",
            name="Other Favourite Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        other_client = APIClient()
        other_client.force_authenticate(user=other_tenant)
        other_client.post(f"/api/v1/users/me/favourites/{other_listing.id}")

        response = favourite_tenant.get("/api/v1/users/me/favourites")

        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["id"], str(listing.id))
        self.assertEqual(payload[0]["title"], "Favourite Listing")
        self.assertNotIn("listing", payload[0])


class AdminSiteTests(TestCase):
    def setUp(self):
        self.admin_user = AppUser.objects.create_superuser(
            email="admin@example.com",
            password="password-123",
        )
        self.client.force_login(self.admin_user)

    def test_admin_exposes_landlord_profiles_changelist(self):
        landlord = AppUser.objects.create_user(
            email="landlord-profile@example.com",
            password="password-123",
            name="Landlord Profile User",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
            landlord_verification_type=AppUser.LandlordVerificationType.INDIVIDUAL,
            landlord_verification_profile={"first_name": "Landlord", "last_name": "Profile"},
        )
        AppUser.objects.create_user(
            email="tenant-profile@example.com",
            password="password-123",
            name="Tenant Profile User",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )

        response = self.client.get("/admin/core/landlordprofile/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, landlord.email)
        self.assertNotContains(response, "tenant-profile@example.com")

    def test_landlord_change_form_shows_individual_verification_fields_only(self):
        landlord = AppUser.objects.create_user(
            email="landlord-verification@example.com",
            password="password-123",
            name="Identity Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
            landlord_verification_type=AppUser.LandlordVerificationType.INDIVIDUAL,
            landlord_verification_profile={
                "first_name": "Identity",
                "last_name": "Landlord",
                "country_of_birth": "Nigeria",
                "state_of_birth": "Lagos",
                "nin": "12345678901",
                "bvn": "10987654321",
                "employment_status": "Employed",
            },
        )

        response = self.client.get(f"/admin/core/landlord/{landlord.id}/change/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Landlord Verification Track")
        self.assertContains(response, 'name="country_of_birth"')
        self.assertContains(response, 'name="state_of_birth"')
        self.assertContains(response, 'name="nin"')
        self.assertContains(response, 'name="bvn"')
        self.assertNotContains(response, "Employment Information")
        self.assertNotContains(response, "Property Ownership Verification")
        self.assertNotContains(response, "Rental Preferences")

    def test_landlord_change_form_shows_corporate_verification_fields(self):
        landlord = AppUser.objects.create_user(
            email="corporate-verification@example.com",
            password="password-123",
            name="Corporate Verification",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
            landlord_verification_type=AppUser.LandlordVerificationType.CORPORATE,
            landlord_verification_profile={
                "company_name": "Verification Homes Limited",
                "business_state": "Lagos",
                "business_city": "Ikeja",
                "cac_registration_number": "RC123456",
                "cac_registration_date": "2026-04-02",
                "nin": "12345678901",
                "bvn": "10987654321",
            },
        )

        response = self.client.get(f"/admin/core/landlord/{landlord.id}/change/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Corporate Landlord Information")
        self.assertContains(response, 'name="company_name"')
        self.assertContains(response, 'name="cac_registration_date"')
        self.assertContains(response, 'name="nin"')
        self.assertContains(response, 'name="bvn"')
        self.assertNotContains(response, "Property Ownership Verification")

    def test_landlord_profile_change_form_shows_individual_profile_fields(self):
        landlord = AppUser.objects.create_user(
            email="individual-landlord@example.com",
            password="password-123",
            name="Ada Example",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
            landlord_verification_type=AppUser.LandlordVerificationType.INDIVIDUAL,
            landlord_verification_profile={
                "first_name": "Ada",
                "last_name": "Example",
                "preferred_contact_method": "email",
                "employment_status": "Employed",
                "occupation": "Architect",
                "work_email": "ada.work@example.com",
                "hr_contact_name": "HR Manager",
                "hr_contact_number": "+2348091122334",
                "hr_contact_email": "hr@example.com",
                "proof_of_address": ["Utility Bill"],
            },
        )

        response = self.client.get(f"/admin/core/landlordprofile/{landlord.id}/change/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Personal Information")
        self.assertContains(response, "Employment Information")
        self.assertContains(response, 'name="first_name"')
        self.assertContains(response, 'name="preferred_contact_method"')
        self.assertContains(response, 'name="employment_status"')
        self.assertContains(response, 'name="work_email"')
        self.assertContains(response, 'name="hr_contact_name"')
        self.assertContains(response, 'name="hr_contact_number"')
        self.assertContains(response, 'name="hr_contact_email"')
        self.assertNotContains(response, "Property Ownership Verification")
        self.assertNotContains(response, "Rental Preferences")
        self.assertNotContains(response, 'name="ownership_types"')
        self.assertNotContains(response, 'name="corp_members_allowed"')

    def test_landlord_profile_change_form_shows_corporate_profile_fields(self):
        landlord = AppUser.objects.create_user(
            email="corporate-landlord@example.com",
            password="password-123",
            name="Acme Admin",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
            landlord_verification_type=AppUser.LandlordVerificationType.CORPORATE,
            landlord_verification_profile={
                "company_name": "Acme Limited",
                "business_state": "Lagos",
                "business_city": "Ikeja",
                "contact_person_name": "Acme Admin",
                "cac_registration_number": "RC123456",
                "cac_registration_date": "2026-04-02",
            },
        )

        response = self.client.get(f"/admin/core/landlordprofile/{landlord.id}/change/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Corporate Landlord Information")
        self.assertContains(response, 'name="company_name"')
        self.assertContains(response, 'name="business_city"')
        self.assertContains(response, 'name="contact_person_name"')
        self.assertContains(response, 'name="cac_registration_number"')
        self.assertContains(response, 'name="cac_registration_date"')
        self.assertNotContains(response, "Property Ownership Verification")


class VerificationRequestViewSetTests(TestCase):
    def _nin_payload(self, nin="12345678901", phone="09080350066"):
        return {
            "status": True,
            "message": "Successful",
            "transactionRef": "NIN-REF",
            "data": {
                "firstName": "Christian",
                "middleName": "Odezi",
                "surname": "Aluya",
                "birthDate": "06-02-1977",
                "gender": "Male",
                "telephoneNo": phone,
                "nin": nin,
                "vNin": nin,
                "selfOriginState": "",
                "selfOriginLga": "",
            },
        }

    def _bvn_payload(self, bvn="22347235093", phone="09080350066"):
        return {
            "status": True,
            "message": "Successful",
            "transactionRef": "BVN-REF",
            "data": {
                "bvn": bvn,
                "firstName": "christian",
                "middleName": "odezi",
                "lastName": "aluya",
                "dateOfBirth": "06-Feb-1977",
                "gender": "Male",
                "lgaOfOrigin": "Isoko North",
                "nationality": "Nigeria",
                "phoneNumber1": phone,
                "stateOfOrigin": "Delta State",
            },
        }

    def _cac_payload(self, rc_number="9463122"):
        return {
            "status": True,
            "message": "Successful",
            "transactionRef": "CAC-REF",
            "data": {
                "companyName": "TCONNECT TECHNOLOGIES LIMITED",
                "rcNumber": rc_number,
                "registrationApproved": True,
                "registrationDate": "2026-04-02T23:30:53.626Z",
            },
        }

    def _prembly_nin_payload(self, nin="91231161558", phone="08099446062"):
        return {
            "status": True,
            "response_code": "00",
            "message": "National Identity Number (NIN) verification successful",
            "data": {
                "firstname": "CHRISTIAN",
                "middlename": "ODEZI",
                "surname": "ALUYA",
                "birthdate": "06-02-1977",
                "telephoneno": phone,
                "nin": nin,
            },
            "verification_status": "verified",
        }

    def _prembly_bvn_payload(self, bvn="22347235093", phone="09080350066"):
        return {
            "status": True,
            "response_code": "00",
            "message": "Bank Verification Number (BVN) verification successful",
            "data": {
                "bvn": bvn,
                "firstName": "christian",
                "middleName": "odezi",
                "lastName": "aluya",
                "dateOfBirth": "06-Feb-1977",
                "phoneNumber1": phone,
                "gender": "Male",
                "stateOfOrigin": "Delta State",
                "lgaOfOrigin": "Isoko North",
                "nationality": "Nigeria",
            },
            "verification_status": "verified",
        }

    def _prembly_cac_payload(self, rc_number="9629888"):
        return {
            "status": True,
            "response_code": "00",
            "message": "CAC Advanced Verification verification successful",
            "data": {
                "state": "LAGOS",
                "address": "Adekunle Lawal",
                "company_status": "ACTIVE",
                "email_address": "info@summitrockholdings.com",
                "rc_number": rc_number,
                "date_of_registration": "2026-06-23T12:54:18.188+00:00",
                "company_name": "SUMMITROCK LIMITED",
            },
            "verification_status": "verified",
        }

    def _complete_tenant_profile_payload(self):
        return {
            "nin_number": "12345678901",
            "bvn_number": "22347235093",
            "first_name": "Christian",
            "middle_name": "Odezi",
            "last_name": "Aluya",
            "date_of_birth": "1977-02-06",
            "gender": "Male",
            "nationality": "Nigerian",
            "state_of_origin": "Delta",
            "lga": "Isoko North",
            "employment_status": "Employed",
            "residence_country": "Nigeria",
            "residence_state": "Lagos",
            "residence_city": "Ikeja",
            "residence_lga": "Ikeja",
            "residence_address": "10 Marina Road",
            "length_of_stay": "3 years",
            "housing_status": "Rented",
            "financial_info": {
                "current_rent_amount": "1200000",
                "current_service_charge": "",
                "current_move_in_date": "2024-01-01",
                "expected_move_out_date": "2026-01-01",
                "reason_for_wanting_to_leave": "Need more space",
            },
            "employment_info": {
                "company_name": "Acme Limited",
                "company_contact_number": "09080350066",
                "industry": "Technology",
                "employment_type": "Full-time",
                "employment_start_date": "2020-01-01",
                "position_job_title": "Product Manager",
                "company_address": "22 Broad Street",
                "company_website": "https://acme.example",
                "hr_contact_name": "Ada Manager",
                "hr_email": "hr@acme.example",
                "hr_contact_phone": "09080350066",
            },
            "guarantor_details": {
                "full_name": "Jane Guarantor",
                "relationship": "Sibling",
                "email": "jane@example.com",
                "mobile_number": "09080350066",
                "occupation": "Accountant",
                "employer": "Audit House",
                "residential_address": "15 Guarantee Close",
            },
            "landlord_info": {
                "name": "Current Landlord",
                "mobile": "09080350066",
                "email": "landlord@example.com",
                "address": "10 Marina Road",
                "property_manager_name": "Property Manager",
                "property_manager_phone": "09080350066",
                "property_manager_email": "manager@example.com",
                "property_manager_address": "10 Marina Road",
            },
            "rental_history": [
                {
                    "property_address": "8 Old Street",
                    "annual_rent": "900000",
                    "service_charge": "90000",
                    "move_in_date": "2021-01-01",
                    "move_out_date": "2023-12-31",
                    "reason_for_leave": "Lease ended",
                }
            ],
            "household_info": {
                "marital_status": "Single",
                "number_of_adults": "1",
                "number_of_children": "0",
                "has_pets": False,
                "work_from_home": False,
                "commercial_activities_at_home": False,
                "has_smokers": False,
            },
            "criminal_declaration": {
                "convicted_of_crime": False,
                "evicted_from_property": False,
                "ongoing_tenancy_litigation": False,
                "rent_arrears_history": False,
                "legal_dispute_with_landlords": False,
            },
        }

    def _tenant_employment_document_ids(self, user):
        documents = [
            Document.objects.create(
                owner=user,
                title=title,
                file=SimpleUploadedFile(f"{title.lower().replace(' ', '-')}.pdf", b"test", content_type="application/pdf"),
            )
            for title in ("Employment Letter", "Staff ID")
        ]
        return [str(document.id) for document in documents]

    def test_dikript_lookup_stores_successful_nin_bvn_and_cac_records(self):
        from core.dikript_verification import dikript_lookup

        cache.clear()
        self.addCleanup(cache.clear)
        nin_payload = self._nin_payload()
        nin_payload["data"]["photo"] = "base64-photo"
        with patch("core.dikript_verification.dikript_get", side_effect=[nin_payload, self._bvn_payload(), self._cac_payload()]):
            dikript_lookup(verification_type="nin", path="/nin", lookup_value="12345678901", query={"nin": "12345678901"})
            dikript_lookup(verification_type="bvn", path="/bvn", lookup_value="22347235093", query={"bvn": "22347235093"})
            dikript_lookup(verification_type="cac", path="/cac", lookup_value="9463122", query={"regNumber": "9463122"})

        nin_record = NinVerificationRecord.objects.get(provider="dikript", nin="12345678901")
        bvn_record = BvnVerificationRecord.objects.get(provider="dikript", bvn="22347235093")
        cac_record = CacVerificationRecord.objects.get(provider="dikript", registration_number="9463122")
        self.assertEqual(nin_record.response_payload["data"]["nin"], "12345678901")
        self.assertNotIn("photo", nin_record.response_payload["data"])
        self.assertEqual(bvn_record.response_payload["data"]["bvn"], "22347235093")
        self.assertEqual(cac_record.response_payload["data"]["rcNumber"], "9463122")

    def test_dikript_lookup_uses_cache_before_database_or_api(self):
        from core.dikript_verification import dikript_lookup

        cache.clear()
        self.addCleanup(cache.clear)
        lookup_hash = hashlib.sha256("12345678901".encode("utf-8")).hexdigest()
        cache.set(f"dikript_lookup:nin:{lookup_hash}", self._nin_payload(nin="99999999999"))

        with (
            patch("core.dikript_verification.get_verification_record_payload") as record_lookup_mock,
            patch("core.dikript_verification.dikript_get") as dikript_get_mock,
        ):
            payload = dikript_lookup(
                verification_type="nin",
                path="/nin",
                lookup_value="12345678901",
                query={"nin": "12345678901"},
            )

        self.assertFalse(record_lookup_mock.called)
        self.assertFalse(dikript_get_mock.called)
        self.assertEqual(payload["data"]["nin"], "99999999999")

    def test_dikript_lookup_uses_database_when_cache_misses(self):
        from core.dikript_verification import dikript_lookup

        cache.clear()
        self.addCleanup(cache.clear)
        NinVerificationRecord.objects.create(
            provider="dikript",
            nin="12345678901",
            response_payload=self._nin_payload(nin="12345678901"),
        )

        with patch("core.dikript_verification.dikript_get") as dikript_get_mock:
            payload = dikript_lookup(
                verification_type="nin",
                path="/nin",
                lookup_value="12345678901",
                query={"nin": "12345678901"},
            )

        self.assertFalse(dikript_get_mock.called)
        self.assertEqual(payload["data"]["nin"], "12345678901")

    def test_prembly_lookup_uses_cache_before_database_or_api(self):
        from core.prembly_verification import prembly_lookup

        cache.clear()
        self.addCleanup(cache.clear)
        cached_payload = self._prembly_cac_payload()
        cached_payload["data"]["company_name"] = "CACHE COMPANY LIMITED"
        lookup_hash = hashlib.sha256("RC:9629888".encode("utf-8")).hexdigest()
        cache.set(f"prembly_lookup:cac:{lookup_hash}", cached_payload)

        with (
            patch("core.prembly_verification.get_verification_record_payload") as record_lookup_mock,
            patch("core.prembly_verification.prembly_post") as prembly_post_mock,
        ):
            payload = prembly_lookup(
                verification_type="cac",
                path="/cac",
                lookup_value="RC:9629888",
                body={"rc_number": "9629888", "company_type": "RC"},
            )

        self.assertFalse(record_lookup_mock.called)
        self.assertFalse(prembly_post_mock.called)
        self.assertEqual(payload["data"]["company_name"], "CACHE COMPANY LIMITED")

    def test_prembly_lookup_stores_and_reuses_successful_database_record(self):
        from core.prembly_verification import prembly_lookup

        cache.clear()
        self.addCleanup(cache.clear)
        with patch("core.prembly_verification.prembly_post", return_value=self._prembly_cac_payload()) as prembly_post_mock:
            payload = prembly_lookup(
                verification_type="cac",
                path="/cac",
                lookup_value="RC:9629888",
                body={"rc_number": "9629888", "company_type": "RC"},
            )

        self.assertEqual(prembly_post_mock.call_count, 1)
        self.assertEqual(payload["data"]["rc_number"], "9629888")
        record = CacVerificationRecord.objects.get(provider="prembly", registration_number="RC:9629888")
        self.assertEqual(record.response_payload["data"]["company_name"], "SUMMITROCK LIMITED")

        cache.clear()
        with patch("core.prembly_verification.prembly_post") as prembly_post_mock:
            payload = prembly_lookup(
                verification_type="cac",
                path="/cac",
                lookup_value="RC:9629888",
                body={"rc_number": "9629888", "company_type": "RC"},
            )

        self.assertFalse(prembly_post_mock.called)
        self.assertEqual(payload["data"]["rc_number"], "9629888")

    @patch("core.dikript_verification.dikript_lookup")
    def test_tenant_profile_submission_verifies_nin_and_bvn(self, dikript_lookup_mock):
        dikript_lookup_mock.side_effect = [self._nin_payload(), self._bvn_payload()]
        user = AppUser.objects.create_user(
            email="tenant-dikript@example.com",
            password="password-123",
            name="Tenant Dikript",
            role=AppUser.Role.TENANT,
            email_verified=True,
            mobile="09080350066",
        )
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            "/api/v1/users/me/tenant-profile",
            {
                "nin_number": "12345678901",
                "bvn_number": "22347235093",
                "first_name": "Christian",
                "middle_name": "Odezi",
                "last_name": "Aluya",
                "date_of_birth": "1977-02-06",
                "gender": "Male",
                "nationality": "Nigerian",
                "state_of_origin": "Delta",
                "lga": "Isoko North",
                "employment_status": "Employed",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        user.refresh_from_db()
        self.assertEqual(user.nin_number, "12345678901")
        self.assertEqual(user.bvn_number, "22347235093")
        self.assertEqual(user.tenant_verification_profile["first_name"], "Christian")
        self.assertEqual(user.tenant_verification_profile["date_of_birth"], "1977-02-06")
        self.assertEqual(user.tenant_verification_profile["nin_number"], "12345678901")
        self.assertEqual(user.tenant_verification_profile["bvn_number"], "22347235093")
        request = VerificationRequest.objects.get(user=user)
        profile = TenantProfile.objects.get(user=user)
        self.assertEqual(profile.status, TenantProfile.Status.PENDING)
        self.assertEqual(request.status, VerificationRequest.Status.APPROVED)
        self.assertEqual(request.identity_verification_status, VerificationRequest.VerificationProgressStatus.VERIFIED)
        self.assertEqual(request.verification_method, VerificationRequest.Method.AUTOMATED)
        self.assertIsNotNone(request.submitted_at)
        self.assertIsNotNone(request.reviewed_at)
        user.refresh_from_db()
        self.assertTrue(user.is_verified)

    @patch("core.dikript_verification.dikript_lookup")
    def test_complete_tenant_profile_submission_is_automatically_approved(self, dikript_lookup_mock):
        dikript_lookup_mock.side_effect = [self._nin_payload(), self._bvn_payload()]
        user = AppUser.objects.create_user(
            email="tenant-auto-approved@example.com",
            password="password-123",
            name="Tenant Auto Approved",
            role=AppUser.Role.TENANT,
            email_verified=True,
            mobile="09080350066",
        )
        client = APIClient()
        client.force_authenticate(user=user)
        payload = self._complete_tenant_profile_payload()
        payload["document_ids"] = self._tenant_employment_document_ids(user)

        response = client.post(
            "/api/v1/users/me/tenant-profile",
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        self.assertEqual(response.json()["status"], TenantProfile.Status.APPROVED)
        profile = TenantProfile.objects.get(user=user)
        self.assertEqual(profile.status, TenantProfile.Status.APPROVED)
        request = VerificationRequest.objects.get(user=user)
        self.assertEqual(request.status, VerificationRequest.Status.APPROVED)
        self.assertEqual(request.identity_verification_status, VerificationRequest.VerificationProgressStatus.VERIFIED)
        self.assertEqual(request.verification_method, VerificationRequest.Method.AUTOMATED)
        self.assertIsNotNone(request.reviewed_at)

    @patch("core.dikript_verification.dikript_lookup")
    def test_complete_tenant_profile_with_five_year_current_residence_does_not_require_rental_history(self, dikript_lookup_mock):
        dikript_lookup_mock.side_effect = [self._nin_payload(), self._bvn_payload()]
        user = AppUser.objects.create_user(
            email="tenant-five-year-residence@example.com",
            password="password-123",
            name="Tenant Five Year Residence",
            role=AppUser.Role.TENANT,
            email_verified=True,
            mobile="09080350066",
        )
        client = APIClient()
        client.force_authenticate(user=user)
        payload = self._complete_tenant_profile_payload()
        payload["financial_info"]["current_move_in_date"] = "2018-01-01"
        payload["rental_history"] = []
        payload["document_ids"] = self._tenant_employment_document_ids(user)

        response = client.post(
            "/api/v1/users/me/tenant-profile",
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        self.assertEqual(response.json()["status"], TenantProfile.Status.APPROVED)

    @override_settings(VERIFICATION_SERVICE="prembly")
    @patch("core.prembly_verification.prembly_lookup")
    def test_tenant_profile_submission_can_use_prembly_verification(self, prembly_lookup_mock):
        prembly_lookup_mock.side_effect = [self._prembly_nin_payload(), self._prembly_bvn_payload()]
        user = AppUser.objects.create_user(
            email="tenant-prembly@example.com",
            password="password-123",
            name="Tenant Prembly",
            role=AppUser.Role.TENANT,
            email_verified=True,
            mobile="09080350066",
        )
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            "/api/v1/users/me/tenant-profile",
            {
                "nin_number": "91231161558",
                "bvn_number": "22347235093",
                "first_name": "Christian",
                "middle_name": "Odezi",
                "last_name": "Aluya",
                "date_of_birth": "1977-02-06",
                "gender": "Male",
                "nationality": "Nigerian",
                "state_of_origin": "Delta",
                "lga": "Isoko North",
                "employment_status": "Employed",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        self.assertEqual(prembly_lookup_mock.call_args_list[0].kwargs["body"], {"number_nin": "91231161558"})
        self.assertEqual(prembly_lookup_mock.call_args_list[1].kwargs["body"], {"number": "22347235093"})

    @patch("core.dikript_verification.dikript_lookup")
    def test_tenant_identification_request_is_automated_without_manual_review(self, dikript_lookup_mock):
        dikript_lookup_mock.side_effect = [self._nin_payload(), self._bvn_payload()]
        user = AppUser.objects.create_user(
            email="tenant-automated-verification@example.com",
            password="password-123",
            name="Tenant Automated Verification",
            role=AppUser.Role.TENANT,
            email_verified=True,
            mobile="09080350066",
            tenant_verification_profile={
                "first_name": "Christian",
                "middle_name": "Odezi",
                "last_name": "Aluya",
                "date_of_birth": "1977-02-06",
                "gender": "Male",
                "nationality": "Nigerian",
                "state_of_origin": "Delta",
                "lga": "Isoko North",
                "employment_status": "Employed",
                "nin_number": "12345678901",
                "bvn_number": "22347235093",
            },
        )
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            "/api/v1/tenant-verification-requests/submit",
            {"document_ids": [], "request_type": "identification"},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        request = VerificationRequest.objects.get(user=user)
        self.assertEqual(response.json()["status"], VerificationRequest.Status.APPROVED)
        self.assertEqual(request.status, VerificationRequest.Status.APPROVED)
        self.assertEqual(request.identity_verification_status, VerificationRequest.VerificationProgressStatus.VERIFIED)
        self.assertEqual(request.verification_method, VerificationRequest.Method.AUTOMATED)
        self.assertIsNotNone(request.submitted_at)
        self.assertIsNotNone(request.reviewed_at)
        user.refresh_from_db()
        self.assertTrue(user.is_verified)

    @patch("core.dikript_verification.dikript_lookup")
    def test_tenant_profile_submission_reuses_preverified_tenant_identity(self, dikript_lookup_mock):
        user = AppUser.objects.create_user(
            email="seeded-tenant@example.com",
            password="password-123",
            name="Seeded Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
            mobile="09080350066",
            nin_number="12345678901",
            bvn_number="22347235093",
            tenant_verification_profile={
                "first_name": "Seeded",
                "last_name": "Tenant",
                "date_of_birth": "1990-01-01",
                "gender": "Female",
                "nationality": "Nigeria",
                "state_of_origin": "Oyo",
                "lga": "Ibadan Central",
                "employment_status": "Employed",
                "nin_number": "12345678901",
                "bvn_number": "22347235093",
            },
        )
        VerificationRequest.objects.create(
            user=user,
            request_type=VerificationRequest.RequestType.IDENTIFICATION,
            status=VerificationRequest.Status.APPROVED,
            identity_verification_status=VerificationRequest.VerificationProgressStatus.VERIFIED,
            verification_method=VerificationRequest.Method.AUTOMATED,
        )
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            "/api/v1/users/me/tenant-profile",
            {
                "first_name": "Seeded",
                "last_name": "Tenant",
                "date_of_birth": "1990-01-01",
                "gender": "Female",
                "nationality": "Nigeria",
                "state_of_origin": "Oyo",
                "lga": "Ibadan Central",
                "employment_status": "Employed",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        self.assertFalse(dikript_lookup_mock.called)

    @patch("core.dikript_verification.dikript_lookup")
    def test_tenant_profile_submission_rejects_mismatched_bvn(self, dikript_lookup_mock):
        dikript_lookup_mock.side_effect = [self._nin_payload(), self._bvn_payload()]
        user = AppUser.objects.create_user(
            email="tenant-dikript-fail@example.com",
            password="password-123",
            name="Tenant Dikript Fail",
            role=AppUser.Role.TENANT,
            email_verified=True,
            mobile="09080350066",
        )
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            "/api/v1/users/me/tenant-profile",
            {
                "nin_number": "12345678901",
                "bvn_number": "22347235093",
                "first_name": "Christian",
                "middle_name": "Odezi",
                "last_name": "Aluya",
                "date_of_birth": "1977-02-06",
                "gender": "Male",
                "nationality": "Nigerian",
                "state_of_origin": "Delta",
                "lga": "Wrong LGA",
                "employment_status": "Employed",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.json())
        self.assertIn("lga", response.json())
        self.assertFalse(TenantProfile.objects.filter(user=user).exists())

    @patch("core.dikript_verification.dikript_lookup")
    def test_landlord_individual_identification_verifies_nin_and_bvn(self, dikript_lookup_mock):
        dikript_lookup_mock.side_effect = [self._nin_payload(), self._bvn_payload()]
        user = AppUser.objects.create_user(
            email="landlord-dikript@example.com",
            password="password-123",
            name="Landlord Dikript",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
            mobile="09080350066",
            landlord_verification_type=AppUser.LandlordVerificationType.INDIVIDUAL,
            landlord_verification_profile={
                "first_name": "Christian",
                "middle_name": "Odezi",
                "last_name": "Aluya",
                "date_of_birth": "1977-02-06",
                "country_of_birth": "Nigeria",
                "state_of_birth": "Delta",
                "gender": "Male",
                "nationality": "Nigerian",
                "state_of_origin": "Delta",
                "lga_of_origin": "Isoko North",
                "contact_number": "09080350066",
                "email": "landlord-dikript@example.com",
                "nin": "12345678901",
                "bvn": "22347235093",
                "residential_address": "10 Marina Road",
            },
        )
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            "/api/v1/landlord-verification-requests/submit",
            {"document_ids": [], "request_type": "identification"},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        user.refresh_from_db()
        self.assertEqual(user.nin_number, "12345678901")
        self.assertEqual(user.bvn_number, "22347235093")
        request = VerificationRequest.objects.get(user=user)
        self.assertEqual(response.json()["status"], VerificationRequest.Status.APPROVED)
        self.assertEqual(request.status, VerificationRequest.Status.APPROVED)
        self.assertEqual(request.identity_verification_status, VerificationRequest.VerificationProgressStatus.VERIFIED)
        self.assertEqual(request.verification_method, VerificationRequest.Method.AUTOMATED)
        self.assertIsNotNone(request.reviewed_at)

    @patch("core.dikript_verification.dikript_lookup")
    def test_landlord_identification_ignores_bvn_phone_when_nin_phone_matches(self, dikript_lookup_mock):
        dikript_lookup_mock.side_effect = [
            self._nin_payload(phone="09080350066"),
            self._bvn_payload(phone="08011111111"),
        ]
        user = AppUser.objects.create_user(
            email="landlord-bvn-phone-optional@example.com",
            password="password-123",
            name="Landlord BVN Phone Optional",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
            mobile="09080350066",
            landlord_verification_type=AppUser.LandlordVerificationType.INDIVIDUAL,
            landlord_verification_profile={
                "first_name": "Christian",
                "middle_name": "Odezi",
                "last_name": "Aluya",
                "date_of_birth": "1977-02-06",
                "gender": "Male",
                "nationality": "Nigerian",
                "state_of_origin": "Delta",
                "lga_of_origin": "Isoko North",
                "contact_number": "09080350066",
                "nin": "12345678901",
                "bvn": "22347235093",
            },
        )
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            "/api/v1/landlord-verification-requests/submit",
            {"document_ids": [], "request_type": "identification"},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        self.assertEqual(dikript_lookup_mock.call_args_list[0].kwargs["verification_type"], "nin")
        self.assertEqual(dikript_lookup_mock.call_args_list[1].kwargs["verification_type"], "bvn")

    @patch("core.dikript_verification.dikript_lookup")
    def test_landlord_identification_accepts_bvn_phone_when_nin_phone_differs(self, dikript_lookup_mock):
        dikript_lookup_mock.side_effect = [
            self._nin_payload(phone="08011111111"),
            self._bvn_payload(phone="09080350066"),
        ]
        user = AppUser.objects.create_user(
            email="landlord-bvn-phone-fallback@example.com",
            password="password-123",
            name="Landlord BVN Phone Fallback",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
            mobile="09080350066",
            landlord_verification_type=AppUser.LandlordVerificationType.INDIVIDUAL,
            landlord_verification_profile={
                "first_name": "Christian",
                "middle_name": "Odezi",
                "last_name": "Aluya",
                "date_of_birth": "1977-02-06",
                "gender": "Male",
                "nationality": "Nigerian",
                "state_of_origin": "Delta",
                "lga_of_origin": "Isoko North",
                "contact_number": "09080350066",
                "nin": "12345678901",
                "bvn": "22347235093",
            },
        )
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            "/api/v1/landlord-verification-requests/submit",
            {"document_ids": [], "request_type": "identification"},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        request = VerificationRequest.objects.get(user=user)
        self.assertEqual(request.identity_verification_status, VerificationRequest.VerificationProgressStatus.VERIFIED)

    @patch("core.dikript_verification.dikript_lookup")
    def test_landlord_identification_rejects_phone_that_matches_neither_nin_nor_bvn(self, dikript_lookup_mock):
        dikript_lookup_mock.side_effect = [
            self._nin_payload(phone="08011111111"),
            self._bvn_payload(phone="08022222222"),
        ]
        user = AppUser.objects.create_user(
            email="landlord-phone-mismatch@example.com",
            password="password-123",
            name="Landlord Phone Mismatch",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
            mobile="09080350066",
            landlord_verification_type=AppUser.LandlordVerificationType.INDIVIDUAL,
            landlord_verification_profile={
                "first_name": "Christian",
                "middle_name": "Odezi",
                "last_name": "Aluya",
                "date_of_birth": "1977-02-06",
                "gender": "Male",
                "nationality": "Nigerian",
                "state_of_origin": "Delta",
                "lga_of_origin": "Isoko North",
                "contact_number": "09080350066",
                "nin": "12345678901",
                "bvn": "22347235093",
            },
        )
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            "/api/v1/landlord-verification-requests/submit",
            {"document_ids": [], "request_type": "identification"},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.json())
        self.assertEqual(response.json()["mobile"], "Mobile number does not match the NIN or BVN records.")

    @patch("core.dikript_verification.dikript_lookup")
    def test_landlord_identification_requires_phone_for_nin(self, dikript_lookup_mock):
        dikript_lookup_mock.side_effect = [self._nin_payload(), self._bvn_payload()]
        user = AppUser.objects.create_user(
            email="landlord-phone-required@example.com",
            password="password-123",
            name="Landlord Phone Required",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
            mobile="",
            landlord_verification_type=AppUser.LandlordVerificationType.INDIVIDUAL,
            landlord_verification_profile={
                "first_name": "Christian",
                "middle_name": "Odezi",
                "last_name": "Aluya",
                "date_of_birth": "1977-02-06",
                "gender": "Male",
                "nationality": "Nigerian",
                "state_of_origin": "Delta",
                "lga_of_origin": "Isoko North",
                "contact_number": "",
                "nin": "12345678901",
                "bvn": "22347235093",
            },
        )
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            "/api/v1/landlord-verification-requests/submit",
            {"document_ids": [], "request_type": "identification"},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.json())
        self.assertEqual(response.json()["mobile"], "Contact number is required for NIN verification.")
        self.assertEqual(dikript_lookup_mock.call_count, 1)

    @patch("core.dikript_verification.dikript_lookup")
    def test_landlord_corporate_identification_verifies_cac(self, dikript_lookup_mock):
        dikript_lookup_mock.return_value = self._cac_payload()
        user = AppUser.objects.create_user(
            email="corporate-dikript@example.com",
            password="password-123",
            name="Corporate Dikript",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
            landlord_verification_type=AppUser.LandlordVerificationType.CORPORATE,
            landlord_verification_profile={
                "company_name": "TConnect Technologies Ltd",
                "business_state": "Lagos",
                "business_city": "Ikeja",
                "business_address": "10 Marina Road",
                "company_phone_number": "09080350066",
                "company_email": "info@tconnect.example",
                "contact_person_name": "Christian Aluya",
                "contact_person_position": "Director",
                "cac_registration_number": "9463122",
                "cac_registration_date": "2026-04-02",
                "tax_identification_number": "TIN123456",
                "nin": "12345678901",
                "bvn": "22347235093",
                "bank_name": "OPay",
                "account_name": "TConnect Technologies Ltd",
                "account_number": "9041487757",
            },
        )
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            "/api/v1/landlord-verification-requests/submit",
            {"document_ids": [], "request_type": "identification"},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        request = VerificationRequest.objects.get(user=user)
        self.assertEqual(response.json()["status"], VerificationRequest.Status.APPROVED)
        self.assertEqual(request.status, VerificationRequest.Status.APPROVED)
        self.assertEqual(request.identity_verification_status, VerificationRequest.VerificationProgressStatus.VERIFIED)
        self.assertEqual(request.verification_method, VerificationRequest.Method.AUTOMATED)
        self.assertIsNotNone(request.reviewed_at)

    @override_settings(VERIFICATION_SERVICE="prembly")
    @patch("core.prembly_verification.prembly_lookup")
    def test_landlord_corporate_identification_can_use_prembly_cac(self, prembly_lookup_mock):
        prembly_lookup_mock.return_value = self._prembly_cac_payload()
        user = AppUser.objects.create_user(
            email="corporate-prembly@example.com",
            password="password-123",
            name="Corporate Prembly",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
            landlord_verification_type=AppUser.LandlordVerificationType.CORPORATE,
            landlord_verification_profile={
                "company_name": "Summitrock Ltd",
                "cac_registration_number": "RC9629888",
                "cac_registration_date": "2026-06-23",
                "state": "Lagos",
                "address": "8 Adekunle Lawal, Ikoyi",
                "email_address": "info@summitrockholdings.com",
            },
        )
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            "/api/v1/landlord-verification-requests/submit",
            {"document_ids": [], "request_type": "identification"},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        self.assertEqual(prembly_lookup_mock.call_args.kwargs["body"]["rc_number"], "9629888")
        self.assertEqual(prembly_lookup_mock.call_args.kwargs["body"]["company_type"], "RC")

    def test_submit_reuses_existing_verification_request(self):
        user = AppUser.objects.create_user(
            email="single-verification@example.com",
            password="password-123",
            name="Single Verification User",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        existing = VerificationRequest.objects.create(
            user=user,
            status=VerificationRequest.Status.PENDING,
        )
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            "/api/v1/landlord-verification-requests/submit",
            {
                "document_ids": [],
                "request_type": "identification",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        self.assertEqual(VerificationRequest.objects.filter(user=user).count(), 1)
        self.assertEqual(str(existing.id), response.json()["id"])

    def test_submit_rejects_property_document_request_type_for_landlord_identity_verification(self):
        user = AppUser.objects.create_user(
            email="verification-user@example.com",
            password="password-123",
            name="Verification User",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            "/api/v1/landlord-verification-requests/submit",
            {
                "document_ids": [],
                "request_type": "property_documents",
                "physical_property_status": "pending",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.json())
        self.assertIn("request_type", response.json())
        self.assertFalse(VerificationRequest.objects.filter(user=user).exists())

    def test_status_returns_each_landlord_verification_track(self):
        user = AppUser.objects.create_user(
            email="verification-status@example.com",
            password="password-123",
            name="Verification Status User",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)

        VerificationRequest.objects.create(
            user=user,
            status=VerificationRequest.Status.PENDING,
            identity_verification_status=VerificationRequest.VerificationProgressStatus.VERIFIED,
            property_document_verification_status=VerificationRequest.VerificationProgressStatus.PENDING,
            physical_property_status=VerificationRequest.VerificationProgressStatus.PENDING,
        )

        response = client.get("/api/v1/landlord-verification-requests/status")

        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        self.assertEqual(payload["identification"]["status"], "verified")
        self.assertEqual(payload["property_documents"]["status"], "pending")
        self.assertEqual(payload["physical_property"]["status"], "pending")

    def test_landlord_is_verified_requires_identity_verification_only(self):
        user = AppUser.objects.create_user(
            email="landlord-verified@example.com",
            password="password-123",
            name="Verified Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )

        VerificationRequest.objects.create(
            user=user,
            status=VerificationRequest.Status.PENDING,
            identity_verification_status=VerificationRequest.VerificationProgressStatus.VERIFIED,
            property_document_verification_status=VerificationRequest.VerificationProgressStatus.PENDING,
        )
        self.assertTrue(user.is_verified)

        VerificationRequest.objects.filter(user=user).update(
            property_document_verification_status=VerificationRequest.VerificationProgressStatus.VERIFIED,
            status=VerificationRequest.Status.APPROVED,
        )
        user.refresh_from_db()
        self.assertTrue(user.is_verified)


class PaymentQueueTests(TestCase):
    @override_settings(PAYMENT_QUEUE_BACKEND="sync")
    @patch("core.payment_queue.call_command")
    def test_sync_queue_backend_runs_ready_payout_task_inline(self, call_command_mock):
        result = enqueue_payment_task(TASK_PROCESS_READY_PAYOUTS, {"source": "test"})

        self.assertEqual(result, {"status": "ok"})
        call_command_mock.assert_called_once_with("process_ready_payouts")

    @override_settings(
        PAYMENT_QUEUE_BACKEND="rq",
        ENFORCE_FLUTTERWAVE_WEBHOOK_SIGNATURE=False,
        FLUTTERWAVE_WEBHOOK_SECRET_HASH="",
    )
    @patch("core.views.enqueue_flutterwave_webhook", return_value=None)
    def test_flutterwave_webhook_returns_queued_for_async_queue_backend(self, enqueue_mock):
        client = APIClient()
        response = client.post(
            "/api/v1/payments/webhook/flutterwave",
            {
                "event": "charge.completed",
                "data": {
                    "reference": "ASYNCQUEUEPAYMENT1",
                    "status": "successful",
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json(), {"status": "queued", "reference": "ASYNCQUEUEPAYMENT1"})
        enqueue_mock.assert_called_once()


class FlutterwaveTransferPayloadTests(TestCase):
    @patch("core.flutterwave._get_v4_access_token", return_value="test-access-token")
    def test_flutterwave_v4_get_headers_include_trace_id_without_idempotency_header(self, _get_token_mock):
        headers = flutterwave._build_v4_headers(
            method="GET",
            idempotency_key="recipient-lookup-trace",
        )

        self.assertEqual(headers["X-Trace-Id"], "recipient-lookup-trace")
        self.assertNotIn("X-Idempotency-Key", headers)

    @patch("core.flutterwave._request_json_v4")
    def test_transfer_recipient_reuses_existing_account(self, request_mock):
        request_mock.return_value = {
            "status": "success",
            "data": [
                {
                    "id": "recipient_existing",
                    "bank": {"account_number": "9041487757", "code": "100004"},
                },
            ],
        }

        recipient = flutterwave.create_transfer_recipient(
            full_name="RentDirect Operations",
            phone_number="08099446062",
            bank_name="Opay",
            bank_code="999992",
            account_number="9041487757",
            account_name="RentDirect Operations",
            idempotency_key="recipient-existing-key",
        )

        self.assertEqual(recipient["data"]["id"], "recipient_existing")
        request_mock.assert_called_once_with(
            method="GET",
            path="/transfers/recipients?size=50",
        )

    @patch("core.flutterwave._request_json_v4")
    def test_transfer_recipient_searches_all_recipient_pages(self, request_mock):
        request_mock.side_effect = [
            {
                "status": "success",
                "data": [],
                "meta": {"page_info": {"next": "next-recipient-page"}},
            },
            {
                "status": "success",
                "data": [
                    {
                        "id": "recipient_on_next_page",
                        "bank": {"account_number": "9041487757", "code": "100004"},
                    },
                ],
            },
        ]

        recipient = flutterwave.find_transfer_recipient(
            account_number="9041487757",
            bank_name="Opay",
            bank_code="999992",
        )

        self.assertEqual(recipient["data"]["id"], "recipient_on_next_page")
        self.assertEqual(
            request_mock.call_args_list[1].kwargs,
            {"method": "GET", "path": "/transfers/recipients?size=50&next=next-recipient-page"},
        )

    @patch("core.flutterwave._request_json_v4")
    def test_transfer_recipient_supports_cursor_pagination_payload(self, request_mock):
        request_mock.side_effect = [
            {
                "status": "success",
                "data": {"items": [], "cursor": {"next": "cursor-recipient-page"}},
            },
            {
                "status": "success",
                "data": {
                    "items": [
                        {
                            "id": "recipient_on_cursor_page",
                            "bank": {"account_number": "9041487757", "code": "100004"},
                        },
                    ],
                },
            },
        ]

        recipient = flutterwave.find_transfer_recipient(
            account_number="9041487757",
            bank_name="Opay",
            bank_code="999992",
        )

        self.assertEqual(recipient["data"]["id"], "recipient_on_cursor_page")
        self.assertEqual(
            request_mock.call_args_list[1].kwargs["path"],
            "/transfers/recipients?size=50&next=cursor-recipient-page",
        )

    @patch("core.flutterwave._request_json_v4")
    def test_transfer_recipient_recovers_from_existing_recipient_conflict(self, request_mock):
        request_mock.side_effect = [
            {"status": "success", "data": []},
            FlutterwaveError("Recipient already exists."),
            {
                "status": "success",
                "data": [
                    {
                        "id": "recipient_after_conflict",
                        "bank": {"account_number": "9041487757", "code": "100004"},
                    },
                ],
            },
        ]

        recipient = flutterwave.create_transfer_recipient(
            full_name="RentDirect Operations",
            phone_number="08099446062",
            bank_name="Opay",
            bank_code="999992",
            account_number="9041487757",
            account_name="RentDirect Operations",
            idempotency_key="recipient-conflict-key",
        )

        self.assertEqual(recipient["data"]["id"], "recipient_after_conflict")
        self.assertEqual(request_mock.call_args_list[1].kwargs["method"], "POST")

    @patch("core.flutterwave._request_json_v4")
    def test_customer_phone_payload_uses_numeric_three_digit_country_code(self, request_mock):
        request_mock.return_value = {"status": "success", "data": {"id": "customer_123"}}

        flutterwave.create_customer(
            email="tenant@example.com",
            full_name="Booking Tenant",
            phone_number="09080350066",
        )

        payload = request_mock.call_args.kwargs["payload"]
        self.assertEqual(payload["phone"], {"country_code": "234", "number": "9080350066"})

    @patch("core.flutterwave._request_json_v4")
    def test_transfer_recipient_payload_uses_flutterwave_ngn_bank_type(self, request_mock):
        request_mock.return_value = {"status": "success", "data": {"id": "recipient_123"}}

        flutterwave.create_transfer_recipient(
            full_name="RentDirect Operations",
            phone_number="08099446062",
            bank_name="PalmPay",
            bank_code="999992",
            account_number="9041487757",
            account_name="RentDirect Operations",
            idempotency_key="recipient-key-123",
        )

        payload = request_mock.call_args.kwargs["payload"]
        self.assertEqual(payload["type"], "bank_ngn")
        self.assertEqual(payload["bank"], {"account_number": "9041487757", "code": "100033"})
        self.assertNotIn("bank_name", payload["bank"])
        self.assertNotIn("name", payload)
        self.assertNotIn("phone", payload)
        self.assertNotIn("national_identification", payload)

    @patch("core.flutterwave._request_json_v4")
    def test_transfer_recipient_normalizes_moniepoint_bank_code(self, request_mock):
        request_mock.return_value = {"status": "success", "data": {"id": "recipient_123"}}

        flutterwave.create_transfer_recipient(
            full_name="RentDirect Operations",
            phone_number="08099446062",
            bank_name="Moniepoint",
            bank_code="090405",
            account_number="8099446062",
            account_name="RentDirect Operations",
            idempotency_key="recipient-key-123",
        )

        payload = request_mock.call_args.kwargs["payload"]
        self.assertEqual(payload["bank"], {"account_number": "8099446062", "code": "50515"})

    @override_settings(
        FLUTTERWAVE_CLIENT_ID="test-client-id",
        FLUTTERWAVE_CLIENT_SECRET="test-client-secret",
        FLUTTERWAVE_API_BASE_URL="https://developersandbox-api.flutterwave.com",
    )
    @patch("core.flutterwave._request_json_v3")
    @patch("core.flutterwave._request_json_v4")
    def test_bank_transfer_payload_uses_payment_instruction_with_recipient_id(self, request_v4_mock, request_v3_mock):
        request_v4_mock.return_value = {"status": "success", "data": {"id": "transfer_123", "status": "NEW"}}

        flutterwave.create_bank_transfer(
            amount=Decimal("40.00"),
            currency="NGN",
            reference="TRANSFERREF123",
            narration="RentDirect Tenant Caution Fee",
            recipient_id="rcb_B9aAgsdzzl",
            bank_name="PalmPay",
            bank_code="100033",
            account_number="9041487757",
            account_name="RentDirect Tenant Caution Holding",
            idempotency_key="TRANSFERREF123",
        )

        payload = request_v4_mock.call_args.kwargs["payload"]
        self.assertEqual(payload["action"], "instant")
        self.assertEqual(payload["reference"], "TRANSFERREF123")
        self.assertEqual(
            payload["payment_instruction"],
            {
                "source_currency": "NGN",
                "destination_currency": "NGN",
                "amount": {"value": 40.0, "applies_to": "destination_currency"},
                "recipient_id": "rcb_B9aAgsdzzl",
            },
        )
        self.assertNotIn("amount", payload)
        self.assertNotIn("recipient_id", payload)
        request_v3_mock.assert_not_called()

    @override_settings(
        FLUTTERWAVE_CLIENT_ID="test-client-id",
        FLUTTERWAVE_CLIENT_SECRET="test-client-secret",
        FLUTTERWAVE_API_BASE_URL="https://developersandbox-api.flutterwave.com",
    )
    @patch("core.flutterwave._request_json_v4")
    def test_retrieve_bank_transfer_fetches_current_v4_status(self, request_v4_mock):
        request_v4_mock.return_value = {
            "status": "success",
            "data": {"id": "transfer_123", "status": "SUCCESSFUL"},
        }

        response = flutterwave.retrieve_bank_transfer(transfer_id="transfer_123")

        self.assertEqual(response["data"]["status"], "SUCCESSFUL")
        request_v4_mock.assert_called_once_with(
            method="GET",
            path="/transfers/transfer_123",
        )


class BookingPaymentTests(TestCase):
    def setUp(self):
        self.landlord = AppUser.objects.create_user(
            email="booking-landlord@example.com",
            password="password-123",
            name="Booking Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
            landlord_verification_profile={
                "banking_information": {
                    "bank_name": "Monie Point",
                    "account_name": "Booking Landlord",
                    "account_number": "1234567890",
                }
            },
        )
        self.tenant = AppUser.objects.create_user(
            email="booking-tenant@example.com",
            password="password-123",
            name="Booking Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        self.listing = Listing.objects.create(
            landlord=self.landlord,
            title="Payment Ready Listing",
            description="A listing used for booking tests",
            address="5 Test Avenue",
            city="Lagos",
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=1200000,
        )
        create_active_subscription(self.tenant, SubscriptionPayment.PlanCode.SILVER)
        self.client = APIClient()
        self.client.force_authenticate(user=self.tenant)

    def test_booking_total_amount_includes_required_fees(self):
        response = self.client.post(
            "/api/v1/bookings",
            {
                "listing_id": str(self.listing.id),
                "start_date": "2026-06-19",
                "end_date": "2027-06-19",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        booking = Booking.objects.get(id=response.json()["id"])
        self.assertEqual(booking.total_amount, calculate_booking_total(self.listing.price_per_year))
        self.assertEqual(response.json()["total_amount"], 1440000.0)
        self.assertEqual(response.json()["remaining_amount"], 1440000.0)

    def test_bronze_tenant_cannot_create_booking(self):
        tenant = AppUser.objects.create_user(
            email="booking-bronze-tenant@example.com",
            password="password-123",
            name="Booking Bronze Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        create_active_subscription(tenant, SubscriptionPayment.PlanCode.BRONZE, days=14)
        client = APIClient()
        client.force_authenticate(user=tenant)

        response = client.post(
            "/api/v1/bookings",
            {
                "listing_id": str(self.listing.id),
                "start_date": "2026-06-19",
                "end_date": "2027-06-19",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403, response.json())
        self.assertFalse(Booking.objects.filter(tenant=tenant, listing=self.listing).exists())

    def test_bronze_tenant_cannot_start_rental_payment_for_existing_booking(self):
        tenant = AppUser.objects.create_user(
            email="payment-bronze-tenant@example.com",
            password="password-123",
            name="Payment Bronze Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        create_active_subscription(tenant, SubscriptionPayment.PlanCode.BRONZE, days=14)
        booking = Booking.objects.create(
            tenant=tenant,
            listing=self.listing,
            start_date=date(2026, 6, 19),
            end_date=date(2027, 6, 19),
            total_amount=calculate_booking_total(self.listing.price_per_year),
        )
        client = APIClient()
        client.force_authenticate(user=tenant)

        response = client.post(
            "/api/v1/payments",
            {
                "booking_id": str(booking.id),
                "amount": "100000.00",
                "payment_method": "bank",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403, response.json())
        self.assertFalse(Payment.objects.filter(booking=booking).exists())

    def test_tenant_can_cancel_pending_rental_payment(self):
        booking = Booking.objects.create(
            tenant=self.tenant,
            listing=self.listing,
            start_date=date(2026, 6, 19),
            end_date=date(2027, 6, 19),
            total_amount=calculate_booking_total(self.listing.price_per_year),
        )
        payment = Payment.objects.create(
            booking=booking,
            amount=100000,
            payment_method="bank",
            status="pending",
            transaction_id="BOOK_CANCEL_TEST",
            currency="NGN",
            provider="flutterwave",
        )

        response = self.client.post(f"/api/v1/payments/{payment.id}/cancel", {}, format="json")

        self.assertEqual(response.status_code, 200, response.json())
        payment.refresh_from_db()
        booking.refresh_from_db()
        self.assertEqual(payment.status, "cancelled")
        self.assertEqual(payment.provider_payload["cancellation"]["reason"], "cancelled_by_user")
        self.assertEqual(booking.status, Booking.Status.PENDING)
        self.assertEqual(booking.paid_amount, Decimal("0.00"))
        booking_response = self.client.get(f"/api/v1/bookings/listing/{self.listing.id}")
        self.assertEqual(booking_response.status_code, 200, booking_response.json())
        self.assertEqual(booking_response.json()["remaining_amount"], 1440000.0)

    def test_tenant_can_delete_cancelled_rental_payment_history(self):
        booking = Booking.objects.create(
            tenant=self.tenant,
            listing=self.listing,
            start_date=date(2026, 6, 19),
            end_date=date(2027, 6, 19),
            total_amount=calculate_booking_total(self.listing.price_per_year),
        )
        Payment.objects.create(
            booking=booking,
            amount=100000,
            payment_method="bank",
            status="cancelled",
            transaction_id="BOOK_DELETE_CANCELLED_TEST",
            currency="NGN",
            provider="flutterwave",
        )

        response = self.client.delete(f"/api/v1/bookings/{booking.id}")

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Booking.objects.filter(id=booking.id).exists())

    def test_tenant_cannot_delete_booking_with_pending_or_completed_payment(self):
        booking = Booking.objects.create(
            tenant=self.tenant,
            listing=self.listing,
            start_date=date(2026, 6, 19),
            end_date=date(2027, 6, 19),
            total_amount=calculate_booking_total(self.listing.price_per_year),
        )
        Payment.objects.create(
            booking=booking,
            amount=100000,
            payment_method="bank",
            status="pending",
            transaction_id="BOOK_DELETE_PENDING_TEST",
            currency="NGN",
            provider="flutterwave",
        )

        response = self.client.delete(f"/api/v1/bookings/{booking.id}")

        self.assertEqual(response.status_code, 400, response.json())
        self.assertTrue(Booking.objects.filter(id=booking.id).exists())

    @override_settings(
        FLUTTERWAVE_PUBLIC_KEY="test-public-key",
        FLUTTERWAVE_SECRET_KEY="test-secret-key",
        FLUTTERWAVE_CLIENT_ID="test-client-id",
        FLUTTERWAVE_CLIENT_SECRET="test-client-secret",
        FLUTTERWAVE_API_BASE_URL="https://f4bexperience.flutterwave.com",
        WEB_PUBLIC_URL="http://localhost:5173",
    )
    @patch("core.views.create_dynamic_virtual_account")
    @patch("core.views.create_customer")
    def test_bank_transfer_checkout_falls_back_when_virtual_accounts_are_forbidden(
        self,
        create_customer_mock,
        create_dynamic_virtual_account_mock,
    ):
        create_customer_mock.return_value = {"status": "success", "data": {"id": "cust_123"}}
        create_dynamic_virtual_account_mock.side_effect = FlutterwaveError("Forbidden")
        booking = Booking.objects.create(
            tenant=self.tenant,
            listing=self.listing,
            start_date=date(2026, 6, 19),
            end_date=date(2027, 6, 19),
            total_amount=calculate_booking_total(self.listing.price_per_year),
        )

        response = self.client.post(
            "/api/v1/payments",
            {
                "booking_id": str(booking.id),
                "amount": str(calculate_deposit_amount(self.listing.price_per_year)),
                "payment_method": "bank",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        payload = response.json()
        self.assertEqual(payload["payment"]["status"], "pending")
        self.assertEqual(payload["checkout"]["checkout_mode"], "inline")
        self.assertEqual(payload["checkout"]["flutterwave"]["payment_options"], "banktransfer,bank,ussd")
        payment = Payment.objects.get(id=payload["payment"]["id"])
        self.assertEqual(payment.provider_payload["checkout"]["checkout_mode"], "inline")
        self.assertEqual(payment.provider_payload["collection_mode"], "inline_bank_checkout")
        self.assertEqual(payment.virtual_account_number, "")

    def test_tenant_can_request_refund_for_completed_payment_before_key_collection(self):
        total_amount = calculate_booking_total(self.listing.price_per_year)
        booking = Booking.objects.create(
            tenant=self.tenant,
            listing=self.listing,
            start_date=date(2026, 6, 19),
            end_date=date(2027, 6, 19),
            status=Booking.Status.CONFIRMED,
            total_amount=total_amount,
            paid_amount=total_amount,
        )
        payment = Payment.objects.create(
            booking=booking,
            amount=total_amount,
            payment_method="bank",
            status="completed",
            transaction_id="BOOK_REFUND_TEST",
            currency="NGN",
            provider="flutterwave",
        )

        response = self.client.post(f"/api/v1/payments/{payment.id}/cancel", {}, format="json")

        self.assertEqual(response.status_code, 200, response.json())
        payment.refresh_from_db()
        booking.refresh_from_db()
        self.assertEqual(payment.status, "refund_requested")
        self.assertEqual(payment.provider_payload["cancellation"]["reason"], "refund_requested_by_tenant")
        self.assertEqual(payment.provider_payload["cancellation"]["refund_eta"], "3 to 5 working days")
        self.assertEqual(payment.provider_payload["cancellation"]["admin_fee_rate"], "0.01")
        self.assertEqual(booking.status, Booking.Status.CANCELLED)
        self.assertEqual(booking.paid_amount, Decimal("0.00"))

    def test_tenant_cannot_cancel_completed_payment_after_both_parties_confirm_key_collection(self):
        total_amount = calculate_booking_total(self.listing.price_per_year)
        booking = Booking.objects.create(
            tenant=self.tenant,
            listing=self.listing,
            start_date=date(2026, 6, 19),
            end_date=date(2027, 6, 19),
            status=Booking.Status.CONFIRMED,
            total_amount=total_amount,
            paid_amount=total_amount,
            tenant_rental_progress={"tenant_collected_house_key": timezone.now().isoformat()},
            landlord_rental_progress={"tenant_collected_house_key": timezone.now().isoformat()},
        )
        payment = Payment.objects.create(
            booking=booking,
            amount=total_amount,
            payment_method="bank",
            status="completed",
            transaction_id="BOOK_KEY_COLLECTED_TEST",
            currency="NGN",
            provider="flutterwave",
        )

        response = self.client.post(f"/api/v1/payments/{payment.id}/cancel", {}, format="json")

        self.assertEqual(response.status_code, 400, response.json())
        self.assertIn("cannot be cancelled", str(response.json()))
        payment.refresh_from_db()
        booking.refresh_from_db()
        self.assertEqual(payment.status, "completed")
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)
        booking_response = self.client.get(f"/api/v1/bookings/listing/{self.listing.id}")
        self.assertEqual(booking_response.status_code, 200, booking_response.json())
        self.assertTrue(booking_response.json()["tenant_key_collection_confirmed"])
        self.assertTrue(booking_response.json()["landlord_key_collection_confirmed"])
        self.assertTrue(booking_response.json()["keys_collected_confirmed"])

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        FLUTTERWAVE_PUBLIC_KEY="test-public-key",
        FLUTTERWAVE_SECRET_KEY="test-secret-key",
        FLUTTERWAVE_CLIENT_ID="test-client-id",
        FLUTTERWAVE_CLIENT_SECRET="test-client-secret",
        FLUTTERWAVE_API_BASE_URL="https://f4bexperience.flutterwave.com",
        WEB_PUBLIC_URL="http://localhost:5173",
    )
    @patch("core.views.find_transfer_recipient")
    @patch("core.views.create_bank_transfer")
    @patch("core.views.create_transfer_recipient")
    @patch("core.views.create_dynamic_virtual_account")
    @patch("core.views.create_customer")
    @patch("core.views.query_transaction")
    def test_payment_checkout_verification_updates_booking_balance_and_blocks_overpayment(
        self,
        query_transaction_mock,
        create_customer_mock,
        create_dynamic_virtual_account_mock,
        create_transfer_recipient_mock,
        create_bank_transfer_mock,
        find_transfer_recipient_mock,
    ):
        find_transfer_recipient_mock.return_value = None
        create_customer_mock.return_value = {"status": "success", "data": {"id": "cust_123"}}
        create_dynamic_virtual_account_mock.return_value = {
            "status": "success",
            "data": {
                "id": "va_123",
                "reference": "ignored",
                "account_number": "1234567890",
                "bank_name": "Flutterwave Bank",
                "bank_code": "000",
            },
        }
        create_transfer_recipient_mock.side_effect = [
            {"status": "success", "data": {"id": "recipient_ops"}},
            {"status": "success", "data": {"id": "recipient_caution"}},
            {"status": "success", "data": {"id": "recipient_landlord"}},
        ]
        create_bank_transfer_mock.side_effect = [
            {"status": "success", "data": {"id": "transfer_ops", "status": "NEW"}},
            {"status": "success", "data": {"id": "transfer_caution", "status": "NEW"}},
            {"status": "success", "data": {"id": "transfer_landlord", "status": "NEW"}},
        ]
        booking = Booking.objects.create(
            tenant=self.tenant,
            listing=self.listing,
            start_date=date(2026, 6, 19),
            end_date=date(2027, 6, 19),
            total_amount=calculate_booking_total(self.listing.price_per_year),
        )
        deposit_amount = calculate_deposit_amount(self.listing.price_per_year)
        total_amount = calculate_booking_total(self.listing.price_per_year)
        final_payment_amount = total_amount - deposit_amount

        payment_response = self.client.post(
            "/api/v1/payments",
            {
                "booking_id": str(booking.id),
                "amount": str(deposit_amount),
                "payment_method": "bank",
            },
            format="json",
        )

        self.assertEqual(payment_response.status_code, 201, payment_response.json())
        payment_payload = payment_response.json()
        self.assertEqual(payment_payload["payment"]["status"], "pending")
        self.assertEqual(payment_payload["payment"]["provider"], "flutterwave")
        self.assertEqual(payment_payload["checkout"]["checkout_mode"], "virtual_account")
        self.assertEqual(
            payment_payload["checkout"]["reference"],
            payment_payload["payment"]["transaction_id"],
        )
        self.assertEqual(payment_payload["checkout"]["virtual_account"]["account_number"], "1234567890")
        self.assertNotIn("subaccounts", payment_payload["checkout"]["flutterwave"])
        booking.refresh_from_db()
        self.assertEqual(str(booking.paid_amount), "0.00")
        self.assertEqual(booking.status, Booking.Status.PENDING)

        query_transaction_mock.return_value = {
            "status": "success",
            "data": {
                "id": "91234",
                "tx_ref": payment_payload["payment"]["transaction_id"],
                "status": "successful",
                "amount": str(deposit_amount),
                "currency": "NGN",
                "customer": {"email": self.tenant.email},
                "authorization": {"bank": "Test Bank", "last4": "4242"},
            },
        }

        verify_response = self.client.get(
            "/api/v1/payments/flutterwave/verify",
            {
                "reference": payment_payload["payment"]["transaction_id"],
                "transaction_id": "91234",
                "status": "successful",
            },
        )

        self.assertEqual(verify_response.status_code, 200, verify_response.json())
        self.assertEqual(verify_response.json()["status"], "completed")
        self.assertEqual(len(mail.outbox), 1)
        payment_email = mail.outbox[0]
        self.assertEqual(payment_email.to, [self.landlord.email])
        self.assertEqual(set(payment_email.cc), {self.tenant.email, "info@rentdirect.homes"})
        self.assertIn("Rental Payment Received", payment_email.subject)
        self.assertIn("₦1,200,000.00", payment_email.body)
        self.assertNotIn("₦240,000.00", payment_email.body)
        booking.refresh_from_db()
        self.assertEqual(booking.paid_amount, deposit_amount)
        self.assertEqual(booking.status, Booking.Status.PENDING)
        settlements = PaymentSettlement.objects.filter(payment__transaction_id=payment_payload["payment"]["transaction_id"])
        self.assertEqual(settlements.count(), 0)
        self.assertFalse(create_transfer_recipient_mock.called)

        landlord_client = APIClient()
        landlord_client.force_authenticate(user=self.landlord)
        save_rental_progress_steps(
            self,
            landlord_client,
            booking.id,
            step_keys=[
                "viewing_appointment_booked",
                "house_viewed",
                "tenancy_agreement_signed",
                "deposit_payment_notification_received",
                "rental_payment_notification_received",
                "check_in_inventory_completed",
                "tenant_collected_house_key",
            ],
        )
        self.assertFalse(create_transfer_recipient_mock.called)

        save_rental_progress_steps(
            self,
            self.client,
            booking.id,
            step_keys=[
                "viewing_appointment_booked",
                "house_viewed",
                "tenancy_agreement_signed",
                "tenant_paid_deposit",
                "tenant_paid_rent_in_full",
                "check_in_inventory_completed",
                "tenant_collected_house_key",
            ],
            step_responses={"rentdirect_transfer_to_landlord": "yes"},
        )
        self.assertFalse(create_transfer_recipient_mock.called)
        self.assertFalse(create_bank_transfer_mock.called)
        settlements = PaymentSettlement.objects.filter(payment__transaction_id=payment_payload["payment"]["transaction_id"])
        self.assertEqual(settlements.count(), 0)

        final_payment_response = self.client.post(
            "/api/v1/payments",
            {
                "booking_id": str(booking.id),
                "amount": str(final_payment_amount),
                "payment_method": "bank",
            },
            format="json",
        )
        self.assertEqual(final_payment_response.status_code, 201, final_payment_response.json())
        final_payment_payload = final_payment_response.json()
        query_transaction_mock.return_value = {
            "status": "success",
            "data": {
                "id": "91235",
                "tx_ref": final_payment_payload["payment"]["transaction_id"],
                "status": "successful",
                "amount": str(final_payment_amount),
                "currency": "NGN",
                "customer": {"email": self.tenant.email},
                "authorization": {"bank": "Test Bank", "last4": "4242"},
            },
        }
        final_verify_response = self.client.get(
            "/api/v1/payments/flutterwave/verify",
            {
                "reference": final_payment_payload["payment"]["transaction_id"],
                "transaction_id": "91235",
                "status": "successful",
            },
        )
        self.assertEqual(final_verify_response.status_code, 200, final_verify_response.json())
        booking.refresh_from_db()
        self.assertEqual(booking.paid_amount, total_amount)
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)
        self.assertEqual(PaymentSettlement.objects.filter(payment__booking=booking).count(), 0)
        self.assertFalse(create_transfer_recipient_mock.called)
        self.assertFalse(create_bank_transfer_mock.called)

        deposit_payment = Payment.objects.get(transaction_id=payment_payload["payment"]["transaction_id"])
        deposit_payment.payment_date = timezone.now() - timedelta(hours=26)
        deposit_payment.save(update_fields=["payment_date", "updated_at"])
        final_payment = Payment.objects.get(transaction_id=final_payment_payload["payment"]["transaction_id"])
        final_payment.payment_date = timezone.now() - timedelta(hours=25)
        final_payment.save(update_fields=["payment_date", "updated_at"])
        call_command("process_ready_payouts")

        self.assertEqual(create_transfer_recipient_mock.call_count, 3)
        self.assertEqual(create_bank_transfer_mock.call_count, 3)
        self.assertEqual(len(mail.outbox), 5)
        landlord_transfer_emails = [message for message in mail.outbox if "Landlord Payout Initiated" in message.subject]
        internal_transfer_emails = [message for message in mail.outbox if "Internal Transfer Initiated" in message.subject]
        self.assertEqual(len(landlord_transfer_emails), 1)
        self.assertEqual(landlord_transfer_emails[0].to, [self.landlord.email])
        self.assertEqual(set(landlord_transfer_emails[0].cc), {self.tenant.email, "info@rentdirect.homes"})
        self.assertIn("₦1,200,000.00", landlord_transfer_emails[0].body)
        self.assertNotIn("₦1,440,000.00", landlord_transfer_emails[0].body)
        self.assertEqual(len(internal_transfer_emails), 2)
        for internal_email in internal_transfer_emails:
            self.assertEqual(internal_email.to, ["info@rentdirect.homes"])
            self.assertEqual(internal_email.cc, [])
        booking.refresh_from_db()
        self.assertIn("final_rent_payment_email_received", booking.tenant_rental_progress)
        self.assertNotIn("net_payment_notification_received", booking.landlord_rental_progress)
        settlements = PaymentSettlement.objects.filter(payment__transaction_id=final_payment_payload["payment"]["transaction_id"])
        self.assertEqual(
            str(settlements.get(purpose=PaymentSettlement.Purpose.OPERATIONS).amount),
            "120000.00",
        )
        self.assertEqual(
            str(settlements.get(purpose=PaymentSettlement.Purpose.CAUTION_FEE).amount),
            "120000.00",
        )
        landlord_settlement = settlements.get(purpose=PaymentSettlement.Purpose.LANDLORD_RENT)
        self.assertEqual(str(landlord_settlement.amount), "1200000.00")
        self.assertEqual(landlord_settlement.bank_name, "Monie Point")
        self.assertEqual(landlord_settlement.account_number, "1234567890")
        self.assertSetEqual(
            set(settlements.values_list("status", flat=True)),
            {PaymentSettlement.Status.PROCESSING},
        )
        self.assertTrue(all(settlements.values_list("transfer_reference", flat=True)))
        self.assertFalse(any(settlements.values_list("transferred_at", flat=True)))

        booking_response = self.client.get(f"/api/v1/bookings/listing/{self.listing.id}")
        self.assertEqual(booking_response.status_code, 200, booking_response.json())
        self.assertEqual(booking_response.json()["remaining_amount"], 0.0)

        overpayment_response = self.client.post(
            "/api/v1/payments",
            {
                "booking_id": str(booking.id),
                "amount": "1.00",
                "payment_method": "card",
            },
            format="json",
        )

        self.assertEqual(overpayment_response.status_code, 400, overpayment_response.json())
        self.assertIn("amount", overpayment_response.json())

    def test_card_payment_above_flutterwave_limit_is_rejected_before_checkout(self):
        self.listing.price_per_year = 7000000
        self.listing.save(update_fields=["price_per_year", "updated_at"])
        total_amount = calculate_booking_total(self.listing.price_per_year)
        booking = Booking.objects.create(
            tenant=self.tenant,
            listing=self.listing,
            start_date=date(2026, 6, 19),
            end_date=date(2027, 6, 19),
            total_amount=total_amount,
        )

        response = self.client.post(
            "/api/v1/payments",
            {
                "booking_id": str(booking.id),
                "amount": str(total_amount),
                "payment_method": "card",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.json())
        self.assertIn("payment_method", response.json())
        self.assertIn("Bank Transfer", str(response.json()["payment_method"]))

    @patch("core.views.retrieve_bank_transfer")
    def test_ready_payout_worker_reconciles_processing_settlement_status(self, retrieve_bank_transfer_mock):
        retrieve_bank_transfer_mock.return_value = {
            "status": "success",
            "data": {
                "id": "transfer_reconcile_123",
                "status": "SUCCESSFUL",
            },
        }
        total_amount = calculate_booking_total(self.listing.price_per_year)
        booking = Booking.objects.create(
            tenant=self.tenant,
            listing=self.listing,
            start_date=date(2026, 6, 19),
            end_date=date(2027, 6, 19),
            total_amount=total_amount,
            paid_amount=total_amount,
        )
        payment = Payment.objects.create(
            booking=booking,
            amount=total_amount,
            payment_method="bank",
            status="completed",
            transaction_id="WORKERRECONCILESTATUS1",
            provider="flutterwave",
            currency="NGN",
            payment_date=timezone.now() - timedelta(hours=25),
        )
        settlement = PaymentSettlement.objects.create(
            payment=payment,
            purpose=PaymentSettlement.Purpose.OPERATIONS,
            amount=Decimal("120000.00"),
            currency="NGN",
            bank_name="Moniepoint",
            account_number="8099446062",
            account_name="RentDirect Operations",
            transfer_reference="WORKERRECONCILESTATUS1-OPERATIONS",
            status=PaymentSettlement.Status.PROCESSING,
            transfer_payload={
                "status": "success",
                "data": {"id": "transfer_reconcile_123", "status": "NEW"},
            },
        )

        call_command("process_ready_payouts")

        settlement.refresh_from_db()
        self.assertEqual(settlement.status, PaymentSettlement.Status.PAID)
        self.assertIsNotNone(settlement.transferred_at)
        self.assertEqual(settlement.transfer_payload["data"]["status"], "SUCCESSFUL")
        retrieve_bank_transfer_mock.assert_called_once_with(transfer_id="transfer_reconcile_123")

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        ENFORCE_FLUTTERWAVE_WEBHOOK_SIGNATURE=False,
        FLUTTERWAVE_WEBHOOK_SECRET_HASH="",
    )
    def test_flutterwave_transfer_webhook_marks_processing_settlement_paid(self):
        booking = Booking.objects.create(
            tenant=self.tenant,
            listing=self.listing,
            start_date=date(2026, 6, 19),
            end_date=date(2027, 6, 19),
            total_amount=calculate_booking_total(self.listing.price_per_year),
            paid_amount=calculate_booking_total(self.listing.price_per_year),
        )
        payment = Payment.objects.create(
            booking=booking,
            amount=calculate_booking_total(self.listing.price_per_year),
            payment_method="bank",
            status="completed",
            transaction_id="WEBHOOKTRANSFERPAYMENT",
            provider="flutterwave",
            currency="NGN",
        )
        settlement = PaymentSettlement.objects.create(
            payment=payment,
            purpose=PaymentSettlement.Purpose.LANDLORD_RENT,
            amount=self.listing.price_per_year,
            currency="NGN",
            bank_name="Monie Point",
            account_number="1234567890",
            account_name="Booking Landlord",
            transfer_reference="WEBHOOKTRANSFERPAYMENT-LANDLORDRENT",
            status=PaymentSettlement.Status.PROCESSING,
        )

        response = self.client.post(
            "/api/v1/payments/webhook/flutterwave",
            {
                "type": "transfer.disburse",
                "data": {
                    "reference": settlement.transfer_reference,
                    "status": "SUCCESSFUL",
                    "amount": float(settlement.amount),
                    "currency": "NGN",
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.json())
        settlement.refresh_from_db()
        self.assertEqual(settlement.status, PaymentSettlement.Status.PAID)
        self.assertIsNotNone(settlement.transferred_at)

    @override_settings(
        ENFORCE_FLUTTERWAVE_WEBHOOK_SIGNATURE=False,
        FLUTTERWAVE_WEBHOOK_SECRET_HASH="",
    )
    def test_flutterwave_transfer_webhook_stores_failure_reason(self):
        booking = Booking.objects.create(
            tenant=self.tenant,
            listing=self.listing,
            start_date=date(2026, 6, 19),
            end_date=date(2027, 6, 19),
            total_amount=calculate_booking_total(self.listing.price_per_year),
            paid_amount=calculate_booking_total(self.listing.price_per_year),
        )
        payment = Payment.objects.create(
            booking=booking,
            amount=calculate_booking_total(self.listing.price_per_year),
            payment_method="bank",
            status="completed",
            transaction_id="WEBHOOKTRANSFERFAILED",
            provider="flutterwave",
            currency="NGN",
        )
        settlement = PaymentSettlement.objects.create(
            payment=payment,
            purpose=PaymentSettlement.Purpose.LANDLORD_RENT,
            amount=self.listing.price_per_year,
            currency="NGN",
            bank_name="Monie Point",
            account_number="1234567890",
            account_name="Booking Landlord",
            transfer_reference="WEBHOOKTRANSFERFAILED-LANDLORDRENT",
            status=PaymentSettlement.Status.PROCESSING,
        )

        with self.assertLogs("core.views", level="ERROR") as logs:
            response = self.client.post(
                "/api/v1/payments/webhook/flutterwave",
                {
                    "type": "transfer.disburse",
                    "data": {
                        "reference": settlement.transfer_reference,
                        "status": "FAILED",
                        "amount": float(settlement.amount),
                        "currency": "NGN",
                        "processor_response": "Transfer rejected by beneficiary bank",
                    },
                },
                format="json",
            )

        self.assertEqual(response.status_code, 200, response.json())
        settlement.refresh_from_db()
        self.assertEqual(settlement.status, PaymentSettlement.Status.FAILED)
        self.assertEqual(settlement.last_error, "Transfer rejected by beneficiary bank")
        self.assertIn("Transfer rejected by beneficiary bank", "\n".join(logs.output))

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    @patch("core.views.find_transfer_recipient")
    @patch("core.views.create_bank_transfer")
    @patch("core.views.create_transfer_recipient")
    def test_ready_payout_worker_processes_completed_payments_after_progress_conditions(
        self,
        create_transfer_recipient_mock,
        create_bank_transfer_mock,
        find_transfer_recipient_mock,
    ):
        find_transfer_recipient_mock.return_value = None
        create_transfer_recipient_mock.side_effect = [
            {"status": "success", "data": {"id": "recipient_ops_worker"}},
            {"status": "success", "data": {"id": "recipient_caution_worker"}},
            {"status": "success", "data": {"id": "recipient_landlord_worker"}},
        ]
        create_bank_transfer_mock.side_effect = [
            {"status": "success", "data": {"id": "transfer_ops_worker", "status": "NEW"}},
            {"status": "success", "data": {"id": "transfer_caution_worker", "status": "NEW"}},
            {"status": "success", "data": {"id": "transfer_landlord_worker", "status": "NEW"}},
        ]
        total_amount = calculate_booking_total(self.listing.price_per_year)
        booking = Booking.objects.create(
            tenant=self.tenant,
            listing=self.listing,
            start_date=date(2026, 6, 19),
            end_date=date(2027, 6, 19),
            total_amount=total_amount,
            paid_amount=total_amount,
            tenant_rental_progress={
                "tenant_collected_house_key": timezone.now().isoformat(),
                "rentdirect_transfer_to_landlord": {
                    "value": "yes",
                    "completed_at": timezone.now().isoformat(),
                },
            },
            landlord_rental_progress={
                "tenant_collected_house_key": timezone.now().isoformat(),
            },
        )
        Payment.objects.create(
            booking=booking,
            amount=total_amount,
            payment_method="bank",
            status="completed",
            transaction_id="WORKERPAYOUTREADY1",
            provider="flutterwave",
            currency="NGN",
            payment_date=timezone.now() - timedelta(hours=25),
        )

        call_command("process_ready_payouts")

        settlements = PaymentSettlement.objects.filter(payment__transaction_id="WORKERPAYOUTREADY1")
        self.assertEqual(settlements.count(), 3)
        self.assertEqual(create_transfer_recipient_mock.call_count, 3)
        self.assertEqual(create_bank_transfer_mock.call_count, 3)
        self.assertSetEqual(
            set(settlements.values_list("status", flat=True)),
            {PaymentSettlement.Status.PROCESSING},
        )
        self.assertTrue(all(settlements.values_list("transfer_reference", flat=True)))
        self.assertEqual(len(mail.outbox), 3)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    @patch("core.views.find_transfer_recipient")
    @patch("core.views.create_bank_transfer")
    @patch("core.views.create_transfer_recipient")
    def test_ready_payout_worker_transfers_when_recipient_already_exists(
        self,
        create_transfer_recipient_mock,
        create_bank_transfer_mock,
        find_transfer_recipient_mock,
    ):
        find_transfer_recipient_mock.side_effect = [
            {"status": "success", "data": {"id": "recipient_existing_ops"}},
            {"status": "success", "data": {"id": "recipient_existing_caution"}},
            {"status": "success", "data": {"id": "recipient_existing_landlord"}},
        ]
        create_bank_transfer_mock.side_effect = [
            {"status": "success", "data": {"id": "transfer_existing_recipient_ops", "status": "NEW"}},
            {"status": "success", "data": {"id": "transfer_existing_recipient_caution", "status": "NEW"}},
            {"status": "success", "data": {"id": "transfer_existing_recipient_landlord", "status": "NEW"}},
        ]
        total_amount = calculate_booking_total(self.listing.price_per_year)
        booking = Booking.objects.create(
            tenant=self.tenant,
            listing=self.listing,
            start_date=date(2026, 6, 19),
            end_date=date(2027, 6, 19),
            total_amount=total_amount,
            paid_amount=total_amount,
            tenant_rental_progress={
                "tenant_collected_house_key": timezone.now().isoformat(),
                "rentdirect_transfer_to_landlord": {
                    "value": "yes",
                    "completed_at": timezone.now().isoformat(),
                },
            },
            landlord_rental_progress={
                "tenant_collected_house_key": timezone.now().isoformat(),
            },
        )
        payment = Payment.objects.create(
            booking=booking,
            amount=total_amount,
            payment_method="bank",
            status="completed",
            transaction_id="WORKEREXISTINGRECIPIENT1",
            provider="flutterwave",
            currency="NGN",
            payment_date=timezone.now() - timedelta(hours=25),
        )

        call_command("process_ready_payouts")

        settlements = PaymentSettlement.objects.filter(payment=payment)
        create_transfer_recipient_mock.assert_not_called()
        self.assertEqual(create_bank_transfer_mock.call_count, 3)
        self.assertSetEqual(
            set(settlements.values_list("status", flat=True)),
            {PaymentSettlement.Status.PROCESSING},
        )
        for settlement in settlements:
            self.assertTrue(settlement.transfer_recipient_id)
            self.assertEqual(settlement.provider_payload["status"], "success")

        # A retry after a transfer failure must reuse the persisted resolution and
        # initiate the transfer without attempting recipient creation again.
        settlements.update(status=PaymentSettlement.Status.READY)
        create_bank_transfer_mock.reset_mock()
        create_bank_transfer_mock.side_effect = [
            {"status": "success", "data": {"id": "transfer_existing_recipient_ops_retry", "status": "NEW"}},
            {"status": "success", "data": {"id": "transfer_existing_recipient_caution_retry", "status": "NEW"}},
            {"status": "success", "data": {"id": "transfer_existing_recipient_landlord_retry", "status": "NEW"}},
        ]

        call_command("process_ready_payouts")

        create_transfer_recipient_mock.assert_not_called()
        self.assertEqual(create_bank_transfer_mock.call_count, 3)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    @patch("core.views.find_transfer_recipient")
    @patch("core.views.create_bank_transfer")
    @patch("core.views.create_transfer_recipient")
    def test_ready_payout_worker_logs_and_stores_provider_failure_reason(
        self,
        create_transfer_recipient_mock,
        create_bank_transfer_mock,
        find_transfer_recipient_mock,
    ):
        find_transfer_recipient_mock.return_value = None
        create_transfer_recipient_mock.side_effect = [
            {"status": "success", "data": {"id": "recipient_caution_failed"}},
            {"status": "success", "data": {"id": "recipient_landlord_ok"}},
            {"status": "success", "data": {"id": "recipient_ops_ok"}},
        ]
        create_bank_transfer_mock.side_effect = [
            {
                "status": "success",
                "data": {
                    "id": "transfer_caution_failed",
                    "status": "FAILED",
                    "processor_response": "Beneficiary account number is invalid",
                },
            },
            {"status": "success", "data": {"id": "transfer_landlord_ok", "status": "NEW"}},
            {"status": "success", "data": {"id": "transfer_ops_ok", "status": "NEW"}},
        ]
        total_amount = calculate_booking_total(self.listing.price_per_year)
        booking = Booking.objects.create(
            tenant=self.tenant,
            listing=self.listing,
            start_date=date(2026, 6, 19),
            end_date=date(2027, 6, 19),
            total_amount=total_amount,
            paid_amount=total_amount,
            tenant_rental_progress={
                "tenant_collected_house_key": timezone.now().isoformat(),
                "rentdirect_transfer_to_landlord": {
                    "value": "yes",
                    "completed_at": timezone.now().isoformat(),
                },
            },
            landlord_rental_progress={
                "tenant_collected_house_key": timezone.now().isoformat(),
            },
        )
        Payment.objects.create(
            booking=booking,
            amount=total_amount,
            payment_method="bank",
            status="completed",
            transaction_id="WORKERPAYOUTFAILED1",
            provider="flutterwave",
            currency="NGN",
            payment_date=timezone.now() - timedelta(hours=25),
        )

        with self.assertLogs("core.views", level="ERROR") as logs:
            call_command("process_ready_payouts")

        failed_settlement = PaymentSettlement.objects.get(
            payment__transaction_id="WORKERPAYOUTFAILED1",
            purpose=PaymentSettlement.Purpose.CAUTION_FEE,
        )
        self.assertEqual(failed_settlement.status, PaymentSettlement.Status.FAILED)
        self.assertEqual(failed_settlement.last_error, "Beneficiary account number is invalid")
        self.assertIn("Beneficiary account number is invalid", "\n".join(logs.output))
        self.assertIn(str(failed_settlement.id), "\n".join(logs.output))

    def test_payment_settlement_admin_displays_failure_reason(self):
        from django.contrib import admin as django_admin

        from core.admin import PaymentSettlementAdmin

        booking = Booking.objects.create(
            tenant=self.tenant,
            listing=self.listing,
            start_date=date(2026, 6, 19),
            end_date=date(2027, 6, 19),
            total_amount=calculate_booking_total(self.listing.price_per_year),
        )
        payment = Payment.objects.create(
            booking=booking,
            amount=calculate_booking_total(self.listing.price_per_year),
            payment_method="bank",
            status="completed",
            transaction_id="ADMINFAILEDSETTLEMENT1",
            provider="flutterwave",
            currency="NGN",
        )
        settlement = PaymentSettlement.objects.create(
            payment=payment,
            purpose=PaymentSettlement.Purpose.LANDLORD_RENT,
            amount=self.listing.price_per_year,
            currency="NGN",
            bank_name="Monie Point",
            account_number="1234567890",
            account_name="Booking Landlord",
            status=PaymentSettlement.Status.FAILED,
            last_error="Transfer rejected by beneficiary bank",
        )

        rendered = PaymentSettlementAdmin(PaymentSettlement, django_admin.site).settlement_accounts(settlement)

        self.assertIn("Failure Reason", str(rendered))
        self.assertIn("Transfer rejected by beneficiary bank", str(rendered))

    @override_settings(
        RENTDIRECT_OPERATING_BANK_CODE="090405",
        RENTDIRECT_OPERATING_BANK_NAME="Moniepoint",
        RENTDIRECT_OPERATING_ACCOUNT_NUMBER="8099446062",
        RENTDIRECT_OPERATING_ACCOUNT_NAME="Christian Odezi Aluya",
    )
    def test_settlement_records_reset_stale_recipient_when_bank_code_changes(self):
        from core.views import ensure_payment_settlement_records

        total_amount = calculate_booking_total(self.listing.price_per_year)
        booking = Booking.objects.create(
            tenant=self.tenant,
            listing=self.listing,
            start_date=date(2026, 6, 19),
            end_date=date(2027, 6, 19),
            total_amount=total_amount,
            paid_amount=total_amount,
        )
        payment = Payment.objects.create(
            booking=booking,
            amount=total_amount,
            payment_method="bank",
            status="completed",
            transaction_id="STALEBANKCODE1",
            provider="flutterwave",
            currency="NGN",
        )
        settlement = PaymentSettlement.objects.create(
            payment=payment,
            purpose=PaymentSettlement.Purpose.OPERATIONS,
            amount=Decimal("120000.00"),
            currency="NGN",
            bank_name="Moniepoint",
            bank_code="090405",
            account_number="8099446062",
            account_name="Christian Odezi Aluya",
            transfer_recipient_id="stale_recipient",
            provider_payload={"data": {"id": "stale_recipient"}},
            transfer_payload={"status": "failed"},
            status=PaymentSettlement.Status.READY,
            last_error="Invalid bank code",
        )

        ensure_payment_settlement_records(payment)

        settlement.refresh_from_db()
        self.assertEqual(settlement.bank_code, "50515")
        self.assertEqual(settlement.transfer_recipient_id, "")
        self.assertIsNone(settlement.provider_payload)
        self.assertIsNone(settlement.transfer_payload)
        self.assertEqual(settlement.status, PaymentSettlement.Status.PENDING)
        self.assertEqual(settlement.last_error, "")


class BookingRentalProgressTests(TestCase):
    def setUp(self):
        self.landlord = AppUser.objects.create_user(
            email="progress-landlord@example.com",
            password="password-123",
            name="Progress Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        self.tenant = AppUser.objects.create_user(
            email="progress-tenant@example.com",
            password="password-123",
            name="Progress Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        create_active_subscription(self.tenant, SubscriptionPayment.PlanCode.SILVER)
        self.listing = Listing.objects.create(
            landlord=self.landlord,
            title="Progress Listing",
            description="A listing used for rental progress tests",
            address="11 Progress Lane",
            city="Abuja",
            state="FCT",
            property_type="Apartment",
            bedrooms=3,
            bathrooms=3,
            price_per_year=5000000,
        )
        self.booking = Booking.objects.create(
            tenant=self.tenant,
            listing=self.listing,
            start_date=date(2026, 6, 19),
            end_date=date(2027, 6, 19),
            total_amount=calculate_booking_total(self.listing.price_per_year),
        )

    def test_bronze_tenant_cannot_access_rental_progress_or_precise_booking_location(self):
        bronze_tenant = AppUser.objects.create_user(
            email="progress-bronze-tenant@example.com",
            password="password-123",
            name="Progress Bronze Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        create_active_subscription(bronze_tenant, SubscriptionPayment.PlanCode.BRONZE, days=14)
        bronze_booking = Booking.objects.create(
            tenant=bronze_tenant,
            listing=self.listing,
            start_date=date(2026, 7, 1),
            end_date=date(2027, 7, 1),
            total_amount=calculate_booking_total(self.listing.price_per_year),
        )
        client = APIClient()
        client.force_authenticate(user=bronze_tenant)

        progress_response = client.get(f"/api/v1/bookings/{bronze_booking.id}/rental-progress")
        bookings_response = client.get("/api/v1/bookings")

        self.assertEqual(progress_response.status_code, 403)
        bookings_payload = bookings_response.json()
        booking_results = (
            bookings_payload["results"]
            if isinstance(bookings_payload, dict) and "results" in bookings_payload
            else bookings_payload
        )
        booking_payload = next(item for item in booking_results if item["id"] == str(bronze_booking.id))
        self.assertIsNone(booking_payload["rental_progress"])
        self.assertEqual(booking_payload["listing_address"], "")
        self.assertEqual(booking_payload["listing_city"], "")

    def test_tenant_can_fetch_and_update_rental_progress(self):
        client = APIClient()
        client.force_authenticate(user=self.tenant)

        initial_response = client.get(f"/api/v1/bookings/{self.booking.id}/rental-progress")

        self.assertEqual(initial_response.status_code, 200, initial_response.json())
        self.assertEqual(initial_response.json()["landlord_name"], self.landlord.name)
        self.assertEqual(initial_response.json()["rental_progress"]["progress_percent"], 0.0)
        self.assertEqual(len(initial_response.json()["rental_progress"]["steps"]), 9)

        update_response = client.patch(
            f"/api/v1/bookings/{self.booking.id}/rental-progress",
            {"step_keys": ["viewing_appointment_booked"]},
            format="json",
        )

        self.assertEqual(update_response.status_code, 200, update_response.json())
        payload = update_response.json()
        self.assertEqual(payload["rental_progress"]["completed_count"], 1)
        self.assertEqual(payload["rental_progress"]["progress_percent"], 11.1)
        first_completed_at = next(
            step["completed_at"]
            for step in payload["rental_progress"]["steps"]
            if step["key"] == "viewing_appointment_booked"
        )
        self.assertIsNotNone(first_completed_at)

        next_response = client.patch(
            f"/api/v1/bookings/{self.booking.id}/rental-progress",
            {"step_keys": ["house_viewed"]},
            format="json",
        )

        self.assertEqual(next_response.status_code, 200, next_response.json())
        next_payload = next_response.json()
        self.assertEqual(next_payload["rental_progress"]["completed_count"], 2)
        self.assertEqual(next_payload["rental_progress"]["progress_percent"], 22.2)
        first_step = next(
            step
            for step in next_payload["rental_progress"]["steps"]
            if step["key"] == "viewing_appointment_booked"
        )
        self.assertEqual(first_step["completed_at"], first_completed_at)

    def test_tenant_choice_step_accepts_yes_or_no_response(self):
        client = APIClient()
        client.force_authenticate(user=self.tenant)

        response = save_rental_progress_steps(
            self,
            client,
            self.booking.id,
            step_keys=[
                "viewing_appointment_booked",
                "house_viewed",
                "tenancy_agreement_signed",
                "tenant_paid_deposit",
                "tenant_paid_rent_in_full",
                "check_in_inventory_completed",
                "tenant_collected_house_key",
            ],
            step_responses={"rentdirect_transfer_to_landlord": "yes"},
        )

        response_step = next(
            step
            for step in response.json()["rental_progress"]["steps"]
            if step["key"] == "rentdirect_transfer_to_landlord"
        )
        self.assertEqual(response_step["selected_value"], "yes")
        self.assertTrue(response_step["completed"])

    def test_rental_progress_updates_listing_status(self):
        client = APIClient()
        client.force_authenticate(user=self.tenant)

        save_rental_progress_steps(
            self,
            client,
            self.booking.id,
            step_keys=[
                "viewing_appointment_booked",
                "house_viewed",
                "tenancy_agreement_signed",
            ],
        )

        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, Listing.Status.PROCESSING)

        save_rental_progress_steps(
            self,
            client,
            self.booking.id,
            step_keys=[
                "tenant_paid_deposit",
                "tenant_paid_rent_in_full",
                "check_in_inventory_completed",
                "tenant_collected_house_key",
            ],
        )

        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, Listing.Status.RENTED)

    def test_rental_progress_steps_must_be_completed_in_order(self):
        client = APIClient()
        client.force_authenticate(user=self.tenant)

        response = client.patch(
            f"/api/v1/bookings/{self.booking.id}/rental-progress",
            {"step_keys": ["tenant_paid_deposit"]},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.json())
        self.assertIn("Checklist steps must be completed in order.", str(response.json()))

    def test_rental_progress_saves_one_step_at_a_time(self):
        client = APIClient()
        client.force_authenticate(user=self.tenant)

        response = client.patch(
            f"/api/v1/bookings/{self.booking.id}/rental-progress",
            {"step_keys": ["viewing_appointment_booked", "house_viewed"]},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.json())
        self.assertIn("Save one checklist step before moving to the next.", str(response.json()))

    def test_rental_progress_keeps_each_party_step_independent(self):
        client = APIClient()
        client.force_authenticate(user=self.landlord)

        response = save_rental_progress_steps(
            self,
            client,
            self.booking.id,
            step_keys=[
                "viewing_appointment_booked",
                "house_viewed",
                "tenancy_agreement_signed",
                "deposit_payment_notification_received",
            ],
        )

        payload = response.json()
        self.assertEqual(payload["tenant_name"], self.tenant.name)
        self.assertEqual(payload["rental_progress"]["role"], AppUser.Role.LANDLORD)
        self.assertEqual(payload["rental_progress"]["completed_count"], 4)

        self.booking.refresh_from_db()
        self.assertEqual(self.booking.tenant_rental_progress, {})
        self.assertSetEqual(
            set(self.booking.landlord_rental_progress.keys()),
            {"viewing_appointment_booked", "house_viewed", "tenancy_agreement_signed", "deposit_payment_notification_received"},
        )

        tenant_client = APIClient()
        tenant_client.force_authenticate(user=self.tenant)
        save_rental_progress_steps(
            self,
            tenant_client,
            self.booking.id,
            step_keys=[
                "viewing_appointment_booked",
                "house_viewed",
                "tenancy_agreement_signed",
                "tenant_paid_deposit",
            ],
        )
        self.booking.refresh_from_db()
        self.assertSetEqual(
            set(self.booking.landlord_rental_progress.keys()),
            {"viewing_appointment_booked", "house_viewed", "tenancy_agreement_signed", "deposit_payment_notification_received"},
        )
        tenant_response = tenant_client.get(f"/api/v1/bookings/{self.booking.id}/rental-progress")
        tenant_steps = {
            step["key"]: step
            for step in tenant_response.json()["rental_progress"]["steps"]
        }
        self.assertTrue(tenant_steps["tenant_paid_deposit"]["completed"])
        self.assertTrue(tenant_steps["tenant_paid_deposit"]["counterpart_completed"])

    def test_listing_is_hidden_from_public_search_and_featured_after_deposit_payment(self):
        self.listing.featured = True
        self.listing.save(update_fields=["featured", "updated_at"])

        unpaid_search_response = self.client.get("/api/v1/listings/search?city=Abuja")
        self.assertEqual(unpaid_search_response.status_code, 200)
        unpaid_search_payload = unpaid_search_response.json()
        unpaid_search_results = unpaid_search_payload["results"] if isinstance(unpaid_search_payload, dict) and "results" in unpaid_search_payload else unpaid_search_payload
        self.assertEqual(len(unpaid_search_results), 1)
        self.assertEqual(unpaid_search_results[0]["id"], str(self.listing.id))

        unpaid_featured_response = self.client.get("/api/v1/featured/listings")
        self.assertEqual(unpaid_featured_response.status_code, 200)
        self.assertEqual(len(unpaid_featured_response.json()), 1)

        self.booking.paid_amount = calculate_deposit_amount(self.listing.price_per_year)
        self.booking.save(update_fields=["paid_amount", "updated_at"])

        search_response = self.client.get("/api/v1/listings/search?city=Abuja")
        self.assertEqual(search_response.status_code, 200)
        search_payload = search_response.json()
        search_results = search_payload["results"] if isinstance(search_payload, dict) and "results" in search_payload else search_payload
        self.assertEqual(search_results, [])

        featured_response = self.client.get("/api/v1/featured/listings")
        self.assertEqual(featured_response.status_code, 200)
        self.assertEqual(featured_response.json(), [])

        self.booking.status = Booking.Status.CANCELLED
        self.booking.save(update_fields=["status", "updated_at"])

        relisted_response = self.client.get("/api/v1/listings/search?city=Abuja")
        self.assertEqual(relisted_response.status_code, 200)
        relisted_payload = relisted_response.json()
        relisted_results = relisted_payload["results"] if isinstance(relisted_payload, dict) and "results" in relisted_payload else relisted_payload
        self.assertEqual(len(relisted_results), 1)
        self.assertEqual(relisted_results[0]["id"], str(self.listing.id))


class TenantScreeningSummaryTests(TestCase):
    def setUp(self):
        self.landlord = AppUser.objects.create_user(
            email="screening-landlord@example.com",
            password="password-123",
            name="Screening Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        self.tenant = AppUser.objects.create_user(
            email="screening-tenant@example.com",
            password="password-123",
            name="Screening Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        self.listing = Listing.objects.create(
            landlord=self.landlord,
            title="Screening Listing",
            description="A listing used for tenant screening tests",
            address="18 Rating Close",
            city="Lagos",
            state="Lagos",
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=3600000,
        )
        self.booking = Booking.objects.create(
            tenant=self.tenant,
            listing=self.listing,
            start_date=date(2026, 6, 19),
            end_date=date(2027, 6, 19),
            total_amount=calculate_booking_total(self.listing.price_per_year),
        )
        TenantProfile.objects.create(
            user=self.tenant,
            first_name="Rated",
            middle_name="T",
            last_name="Tenant",
            date_of_birth=date(1992, 3, 14),
            gender="Female",
            nationality="Nigerian",
            state_of_origin="Lagos",
            lga="Eti-Osa",
            employment_status="Employed",
            residence_country="Nigeria",
            residence_state="Lagos",
            residence_city="Lekki",
            residence_lga="Eti-Osa",
            residence_address="55 Freedom Way",
            length_of_stay="3 years",
            housing_status="Rented",
            employment_info={
                "company_name": "Acme Limited",
                "company_contact_number": "08030000000",
                "employment_type": "Full-time",
                "employment_start_date": "2022-05-01",
                "position_job_title": "Product Manager",
                "company_address": "Victoria Island, Lagos",
                "hr_contact_name": "Jane HR",
                "hr_email": "hr@acme.example",
            },
            financial_info={
                "bank_name": "GTBank",
                "account_name": "Rated Tenant",
                "account_number": "0123456789",
                "monthly_income_amount": "1500000",
                "current_rent_amount": "250000",
                "monthly_expenses": "350000",
            },
            guarantor_details={
                "full_name": "John Sponsor",
                "relationship": "Parent",
                "email": "john@example.com",
                "mobile_number": "08035555555",
                "occupation": "Director",
                "employer": "Sponsor Group",
                "residential_address": "12 Sponsor Street, Abuja",
            },
            landlord_info={
                "name": "Former Landlord",
                "mobile": "08038888888",
                "email": "landlord@example.com",
                "address": "10 Marina, Lagos",
                "property_manager_name": "Estate Manager",
                "property_manager_phone": "08037777777",
            },
            rental_history=[
                {
                    "property_address": "10 Marina, Lagos",
                    "annual_rent": "1800000",
                    "move_in_date": "2023-01-01",
                    "move_out_date": "2025-01-01",
                    "reason_for_leave": "Needed a bigger apartment",
                }
            ],
            household_info={
                "number_of_adults": "2",
                "number_of_children": "1",
                "has_pets": False,
                "number_of_pets": "0",
                "work_from_home": True,
                "commercial_activities_at_home": False,
                "has_smokers": False,
            },
            criminal_declaration={
                "convicted_of_crime": False,
                "evicted_from_property": False,
                "ongoing_tenancy_litigation": False,
                "rent_arrears_history": False,
                "legal_dispute_with_landlords": False,
            },
            status=TenantProfile.Status.APPROVED,
        )

    def test_payment_capacity_uses_employed_net_monthly_income(self):
        profile = TenantProfile.objects.get(user=self.tenant)

        summary = build_tenant_screening_summary(profile, self.listing)
        payment_capacity = next(category for category in summary["categories"] if category["key"] == "payment_capacity")
        self.assertEqual(payment_capacity["score"], 80)

        profile.financial_info = {
            **profile.financial_info,
            "credit_commitment": "200000",
            "outstanding_loans": "650000",
        }
        profile.save(update_fields=["financial_info"])
        summary = build_tenant_screening_summary(profile, self.listing)
        payment_capacity = next(category for category in summary["categories"] if category["key"] == "payment_capacity")
        self.assertEqual(payment_capacity["score"], 38)

    def test_payment_capacity_uses_non_employed_annual_resources_and_outgoings(self):
        profile = TenantProfile.objects.get(user=self.tenant)
        profile.employment_status = "Student"
        profile.financial_info = {
            **profile.financial_info,
            "monthly_income_amount": "",
            "monthly_expenses": "",
            "average_annual_income": "7200000",
            "outgoing_expenses": "200000",
        }
        profile.save(update_fields=["employment_status", "financial_info"])

        summary = build_tenant_screening_summary(profile, self.listing)
        payment_capacity = next(category for category in summary["categories"] if category["key"] == "payment_capacity")
        self.assertEqual(payment_capacity["score"], 38)

    def test_landlord_booking_response_includes_screening_summary_only(self):
        client = APIClient()
        client.force_authenticate(user=self.landlord)

        response = client.get("/api/v1/bookings")

        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        results = payload["results"] if isinstance(payload, dict) and "results" in payload else payload
        self.assertEqual(len(results), 1)
        summary = results[0]["tenant_screening_summary"]
        self.assertIsNotNone(summary)
        self.assertGreater(summary["overall_score"], 0)
        self.assertEqual(len(summary["categories"]), 10)
        self.assertEqual(summary["categories"][0]["label"], "Identity Verification")
        self.assertIn("score", summary["categories"][0])
        self.assertNotIn("max_score", summary["categories"][0])
        self.assertNotIn("first_name", summary)
        self.assertNotIn("financial_info", summary)

    def test_tenant_booking_response_hides_screening_summary(self):
        client = APIClient()
        client.force_authenticate(user=self.tenant)

        response = client.get("/api/v1/bookings")

        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        results = payload["results"] if isinstance(payload, dict) and "results" in payload else payload
        self.assertEqual(results[0]["tenant_screening_summary"], None)

    def test_landlord_can_view_booked_tenant_profile(self):
        client = APIClient()
        client.force_authenticate(user=self.landlord)

        response = client.get(f"/api/v1/users/tenants/{self.tenant.id}/profile")

        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        self.assertEqual(payload["id"], str(self.tenant.id))
        self.assertEqual(payload["tenant_profile"]["first_name"], "Rated")
        self.assertEqual(payload["tenant_profile"]["employment_info"]["company_name"], "Acme Limited")
        self.assertNotIn("supporting_document_urls", payload["tenant_profile"])
        self.assertNotIn("account_number", payload["tenant_profile"]["financial_info"])

    def test_landlord_cannot_view_unbooked_tenant_profile(self):
        other_landlord = AppUser.objects.create_user(
            email="other-screening-landlord@example.com",
            password="password-123",
            name="Other Screening Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        client = APIClient()
        client.force_authenticate(user=other_landlord)

        response = client.get(f"/api/v1/users/tenants/{self.tenant.id}/profile")

        self.assertEqual(response.status_code, 403)


class SeedDemoTests(TestCase):
    def assert_seed_subscription(self, subscription, user):
        self.assertEqual(subscription.user, user)
        self.assertEqual(subscription.role, user.role)
        self.assertEqual(subscription.plan_code, SubscriptionPayment.PlanCode.PLATINUM)
        self.assertEqual(subscription.billing_cycle, SubscriptionPayment.BillingCycle.MONTHLY)
        self.assertEqual(subscription.status, SubscriptionPayment.Status.COMPLETED)
        self.assertEqual(subscription.provider, "seed_demo")
        self.assertEqual(subscription.billing_reason, "seed_demo")
        self.assertEqual(str(subscription.amount), "2000.00")
        self.assertEqual(subscription.provider_charge_id, subscription.transaction_id)
        self.assertFalse(subscription.recurring_enabled)
        self.assertTrue(subscription.provider_payload["dummy_payment"])
        self.assertTrue(subscription.provider_payload["gateway_bypassed"])
        self.assertGreater(subscription.expires_at, timezone.now())

    @override_settings(SEED_DEMO_ACCOUNTS=True, ENVIRONMENT="production")
    def test_seed_demo_skips_production_environment(self):
        call_command("seed_demo_data")

        self.assertEqual(AppUser.objects.count(), 0)
        self.assertEqual(VerificationRequest.objects.count(), 0)

    @override_settings(SEED_DEMO_ACCOUNTS=True)
    def test_seed_demo_creates_missing_seed_accounts_when_other_accounts_exist(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            landlord_seed_path = f"{temp_dir}/landlord.json"
            tenant_seed_path = f"{temp_dir}/tenants.json"
            Path(landlord_seed_path).write_text(json.dumps({"landlord": {"email": "seed-landlord@example.com"}}))
            Path(tenant_seed_path).write_text(json.dumps({"tenant": {"email": "seed-tenant@example.com"}}))
            AppUser.objects.create_user(
                email="manual-landlord@example.com",
                password="password-123",
                name="Manual Landlord",
                role=AppUser.Role.LANDLORD,
            )

            with override_settings(
                SEED_LANDLORD_DATA_PATH=landlord_seed_path,
                SEED_TENANT_DATA_PATH=tenant_seed_path,
            ):
                call_command("seed_demo_data")

        self.assertTrue(AppUser.objects.filter(email="seed-landlord@example.com", role=AppUser.Role.LANDLORD).exists())
        self.assertTrue(AppUser.objects.filter(email="seed-tenant@example.com", role=AppUser.Role.TENANT).exists())
        self.assertEqual(AppUser.objects.filter(role=AppUser.Role.LANDLORD).count(), 2)
        self.assertEqual(AppUser.objects.filter(role=AppUser.Role.TENANT).count(), 1)
        self.assertFalse(Listing.objects.exists())

    @override_settings(SEED_DEMO_ACCOUNTS=True)
    def test_seed_demo_skips_when_all_seed_accounts_exist(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            landlord_seed_path = f"{temp_dir}/landlord.json"
            tenant_seed_path = f"{temp_dir}/tenants.json"
            Path(landlord_seed_path).write_text(json.dumps({"landlord": {"email": "seed-landlord@example.com"}}))
            Path(tenant_seed_path).write_text(json.dumps({"tenant": {"email": "seed-tenant@example.com"}}))
            out = StringIO()

            with override_settings(
                SEED_LANDLORD_DATA_PATH=landlord_seed_path,
                SEED_TENANT_DATA_PATH=tenant_seed_path,
            ):
                call_command("seed_demo_data")
                call_command("seed_demo_data", stdout=out)

        self.assertIn("Seed demo landlord and tenant accounts already exist; skipping demo account seed", out.getvalue())
        self.assertEqual(AppUser.objects.filter(role=AppUser.Role.LANDLORD).count(), 1)
        self.assertEqual(AppUser.objects.filter(role=AppUser.Role.TENANT).count(), 1)

    @override_settings(SEED_DEMO_ACCOUNTS=True)
    def test_seed_demo_resolves_seed_assets_with_alternate_extensions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir) / "apps" / "api"
            cover_dir = base_dir / "seed_demo_data" / "landlord" / "christian" / "listings" / "02"
            cover_dir.mkdir(parents=True, exist_ok=True)
            expected_path = cover_dir / "cover_image.jpg"
            expected_path.write_bytes(b"jpg-bytes")

            with override_settings(BASE_DIR=base_dir):
                resolved = SeedDemoDataCommand().resolve_path("seed_demo_data/landlord/christian/listings/02/cover_image.webp")

        self.assertEqual(resolved, expected_path)

    @override_settings(SEED_DEMO_ACCOUNTS=True)
    def test_seed_demo_uploads_homepage_video_to_storage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir) / "apps" / "api"
            source_path = base_dir / "uploads" / "seed" / "video" / "rentdirect.mp4"
            media_root = Path(temp_dir) / "media"
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_bytes(b"homepage video")

            with override_settings(
                BASE_DIR=base_dir,
                MEDIA_ROOT=media_root,
                STORAGES=TEST_FILE_STORAGES,
                HOMEPAGE_VIDEO_SOURCE_PATH="uploads/seed/video/rentdirect.mp4",
                HOMEPAGE_VIDEO_STORAGE_NAME="seed/video/rentdirect.mp4",
            ):
                SeedDemoDataCommand().seed_homepage_video()

                self.assertEqual((media_root / "seed" / "video" / "rentdirect.mp4").read_bytes(), b"homepage video")

    @override_settings(SEED_DEMO_ACCOUNTS=True)
    def test_seed_demo_keeps_homepage_video_when_source_is_storage_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir) / "apps" / "api"
            source_path = base_dir / "uploads" / "seed" / "video" / "rentdirect.mp4"
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_bytes(b"homepage video")

            with override_settings(
                BASE_DIR=base_dir,
                MEDIA_ROOT=base_dir / "uploads",
                STORAGES=TEST_FILE_STORAGES,
                HOMEPAGE_VIDEO_SOURCE_PATH="uploads/seed/video/rentdirect.mp4",
                HOMEPAGE_VIDEO_STORAGE_NAME="seed/video/rentdirect.mp4",
            ):
                SeedDemoDataCommand().seed_homepage_video()

                self.assertEqual(source_path.read_bytes(), b"homepage video")

    @override_settings(SEED_DEMO_ACCOUNTS=True)
    def test_seed_demo_creates_default_landlords_tenants_and_featured_listings(self):
        with tempfile.TemporaryDirectory() as temp_media_root:
            with override_settings(MEDIA_ROOT=temp_media_root, STORAGES=TEST_FILE_STORAGES):
                call_command("seed_demo_data")
                call_command("seed_demo_data")

        landlords = list(AppUser.objects.filter(role=AppUser.Role.LANDLORD))
        tenants = list(AppUser.objects.filter(role=AppUser.Role.TENANT))
        seed_users = [*landlords, *tenants]
        listings = Listing.objects.filter(landlord__in=landlords)

        self.assertEqual(len(landlords), 4)
        self.assertEqual(len(tenants), 1)
        self.assertEqual(listings.count(), 4)
        self.assertEqual(listings.filter(featured=True).count(), 4)
        self.assertEqual(VerificationRequest.objects.filter(user__in=seed_users).count(), 5)
        self.assertEqual(SubscriptionPayment.objects.filter(user__in=seed_users).count(), 5)
        self.assertEqual(TenantProfile.objects.filter(user__in=tenants).count(), 1)

        seeded_tenant_profile = TenantProfile.objects.get(user__email="criyo.career+jade@gmail.com")
        self.assertEqual(seeded_tenant_profile.financial_info["monthly_income_amount"], "500000")
        self.assertEqual(seeded_tenant_profile.financial_info["monthly_expenses"], "200,000")
        self.assertEqual(seeded_tenant_profile.financial_info["current_annual_rent"], "2500000")
        self.assertEqual(seeded_tenant_profile.financial_info["credit_commitment"], "0")
        self.assertEqual(seeded_tenant_profile.financial_info["outstanding_loans"], "0")
        self.assertNotIn("current_rent_amount", seeded_tenant_profile.financial_info)

        for user in seed_users:
            self.assert_seed_subscription(SubscriptionPayment.objects.get(user=user), user)
            verification = VerificationRequest.objects.get(user=user)
            self.assertEqual(verification.status, VerificationRequest.Status.APPROVED)
            self.assertEqual(verification.identity_verification_status, VerificationRequest.VerificationProgressStatus.VERIFIED)
            self.assertEqual(verification.property_document_verification_status, VerificationRequest.VerificationProgressStatus.VERIFIED)
            self.assertEqual(verification.physical_property_status, VerificationRequest.VerificationProgressStatus.VERIFIED)
            self.assertEqual(verification.verification_method, VerificationRequest.Method.AUTOMATED)

        for listing in listings:
            self.assertEqual(listing.status, Listing.Status.AVAILABLE)
            self.assertEqual(listing.property_document_verification_status, VerificationRequest.VerificationProgressStatus.VERIFIED)
            self.assertEqual(listing.physical_property_status, VerificationRequest.VerificationProgressStatus.VERIFIED)
            self.assertEqual(listing.property_documents.count(), 1)
            self.assertGreater(listing.images.count(), 0)
            self.assertTrue(listing.cover_image_url)

        christian = AppUser.objects.get(email="criyo.career@gmail.com")
        client = APIClient()
        client.force_authenticate(user=christian)
        status_response = client.get("/api/v1/landlord-verification-requests/status")
        self.assertEqual(status_response.status_code, 200, status_response.json())
        status_payload = status_response.json()
        self.assertEqual(status_payload["identification"]["status"], "verified")
        self.assertEqual(status_payload["property_documents"]["status"], "verified")
        self.assertEqual(status_payload["physical_property"]["status"], "verified")
        self.assertEqual(status_payload["verification_method"], "automated")
        christian_listing = Listing.objects.get(landlord=christian, seed_key="01")
        title_max_length = Document._meta.get_field("title").max_length
        self.assertTrue(
            all(len(document.title) <= title_max_length for document in christian_listing.property_documents.all())
        )
        self.assertTrue(
            all(
                document.file.name.startswith(f"documents/{christian.id}/{document.id}/document-")
                for document in christian_listing.property_documents.all()
            )
        )
        self.assertTrue(
            all(
                image.file.name.startswith(f"listings/{christian.id}/{christian_listing.id}/{image.id}/listing-image-")
                for image in christian_listing.images.all()
            )
        )

        response = self.client.get("/api/v1/featured/listings")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 4)
        self.assertTrue(response.json()[0]["cover_image_url"])

    @override_settings(SEED_DEMO_ACCOUNTS=True)
    def test_seed_demo_removes_orphaned_listing_property_documents(self):
        with tempfile.TemporaryDirectory() as temp_media_root:
            with override_settings(MEDIA_ROOT=temp_media_root, STORAGES=TEST_FILE_STORAGES):
                call_command("seed_demo_data")
                listing = Listing.objects.get(landlord__email="criyo.career@gmail.com", seed_key="01")
                orphan = Document.objects.create(
                    owner=listing.landlord,
                    title=f"Listing Property Document: {listing.id} - stale failed upload",
                    content_type="application/pdf",
                )

                call_command("seed_demo_data", force=True)

                listing.refresh_from_db()

        self.assertFalse(Document.objects.filter(id=orphan.id).exists())
        self.assertEqual(listing.property_documents.count(), 1)

    @override_settings(SEED_DEMO_ACCOUNTS=True)
    def test_seed_demo_restores_listing_images_when_storage_files_already_exist(self):
        with tempfile.TemporaryDirectory() as temp_media_root:
            with override_settings(MEDIA_ROOT=temp_media_root, STORAGES=TEST_FILE_STORAGES):
                call_command("seed_demo_data")

                listing = Listing.objects.get(landlord__email="criyo.career@gmail.com", seed_key="01")
                original_image_names = list(listing.images.values_list("file", flat=True))
                ListingImage.objects.filter(listing=listing).delete()
                for image_name in original_image_names:
                    self.assertTrue((Path(temp_media_root) / image_name).exists())

                call_command("seed_demo_data", force=True)

                listing.refresh_from_db()
                image_names = list(listing.images.values_list("file", flat=True))

        self.assertGreater(len(image_names), 0)
        self.assertTrue(any(re.search(r"/listing-image-[0-9a-f]{32}\.jpg$", name) for name in image_names))
        self.assertTrue(listing.cover_image_url)

    @override_settings(SEED_DEMO_ACCOUNTS=True)
    def test_seed_demo_updates_existing_seeded_listing_instead_of_creating_duplicate(self):
        with tempfile.TemporaryDirectory() as temp_media_root:
            with override_settings(MEDIA_ROOT=temp_media_root, STORAGES=TEST_FILE_STORAGES):
                call_command("seed_demo_data")

                listing = Listing.objects.get(landlord__email="criyo.career@gmail.com", seed_key="01")
                original_id = listing.id
                listing.title = "Legacy Seeded Title"
                listing.seed_key = ""
                listing.save(update_fields=["title", "seed_key", "updated_at"])

                call_command("seed_demo_data", force=True)

        refreshed = Listing.objects.get(id=original_id)
        self.assertEqual(Listing.objects.filter(landlord__email="criyo.career@gmail.com").count(), 1)
        self.assertEqual(refreshed.seed_key, "01")
        self.assertEqual(refreshed.title, "Modern 4 bedroom Apartment")

    @override_settings(SEED_DEMO_ACCOUNTS=True)
    def test_seed_demo_updates_listing_when_seed_title_changes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            landlord_seed_path = f"{temp_dir}/landlord.json"
            tenant_seed_path = f"{temp_dir}/tenants.json"

            original_landlords = {
                "femi": {
                    "email": "seedfemi@example.com",
                    "password": "password-123",
                    "profile": {
                        "full_name": "Seed Femi",
                        "email": "seedfemi@example.com",
                        "mobile": "+234809848378",
                        "nin_number": "98376728472",
                        "state_of_origin": "Delta",
                        "residence": {"state": "Lagos", "city": "Ikoyi", "address": "8 Rumens Road"},
                    },
                    "verification": {"nin_number": "98376728472"},
                    "listings": {
                        "01": {
                            "title": "Original Seed Title",
                            "property_type": "Apartment",
                            "description": "Original description",
                            "address": "23 Gerald Road",
                            "city": "Ikoyi",
                            "postal_code": "100021",
                            "bedroom": 3,
                            "bathroom": 3,
                            "square_feet": 3000,
                            "price_per_year": 30000000,
                            "features": {"amenities": ["parking"]},
                        }
                    },
                }
            }
            updated_landlords = {
                "femi": {
                    **original_landlords["femi"],
                    "listings": {
                        "01": {
                            "title": "Updated Seed Title",
                            "property_type": "Duplex",
                            "description": "Updated description",
                            "address": "23 Gerald Road",
                            "city": "Ikoyi",
                            "postal_code": "100021",
                            "bedroom": 5,
                            "bathroom": 4,
                            "square_feet": 4800,
                            "price_per_year": 45000000,
                            "features": {"amenities": ["gym", "parking"]},
                        }
                    },
                }
            }

            Path(landlord_seed_path).write_text(json.dumps(original_landlords))
            Path(tenant_seed_path).write_text("{}")

            with override_settings(
                MEDIA_ROOT=temp_dir,
                STORAGES=TEST_FILE_STORAGES,
                SEED_LANDLORD_DATA_PATH=landlord_seed_path,
                SEED_TENANT_DATA_PATH=tenant_seed_path,
            ):
                call_command("seed_demo_data")
                listing = Listing.objects.get(landlord__email="seedfemi@example.com")
                original_id = listing.id

                Path(landlord_seed_path).write_text(json.dumps(updated_landlords))
                call_command("seed_demo_data", force=True)

        listing = Listing.objects.get(id=original_id)
        self.assertEqual(Listing.objects.filter(landlord__email="seedfemi@example.com").count(), 1)
        self.assertEqual(listing.title, "Updated Seed Title")
        self.assertEqual(listing.property_type, "Duplex")
        self.assertEqual(listing.bedrooms, 5)
        self.assertEqual(listing.bathrooms, 4)
        self.assertEqual(listing.square_feet, 4800)
        self.assertEqual(str(listing.price_per_year), "45000000.00")

    @override_settings(SEED_DEMO_ACCOUNTS=True)
    def test_seed_demo_removes_stale_seeded_listings_not_present_in_latest_seed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            landlord_seed_path = f"{temp_dir}/landlord.json"
            tenant_seed_path = f"{temp_dir}/tenants.json"

            initial_landlords = {
                "christian": {
                    "email": "seedchristian@example.com",
                    "password": "password-123",
                    "profile": {
                        "full_name": "Seed Christian",
                        "email": "seedchristian@example.com",
                        "mobile": "+234809848378",
                        "nin_number": "98376728472",
                        "state_of_origin": "Delta",
                        "residence": {"state": "Lagos", "city": "Ikoyi", "address": "8 Rumens Road"},
                    },
                    "verification": {"nin_number": "98376728472"},
                    "listings": {
                        "01": {
                            "title": "Listing One",
                            "property_type": "Apartment",
                            "description": "Listing one",
                            "address": "23 Gerald Road",
                            "city": "Ikoyi",
                            "postal_code": "100021",
                            "bedroom": 3,
                            "bathroom": 3,
                            "square_feet": 3000,
                            "price_per_year": 30000000,
                            "features": {"amenities": ["parking"]},
                        },
                        "02": {
                            "title": "Listing Two",
                            "property_type": "Apartment",
                            "description": "Listing two",
                            "address": "24 Gerald Road",
                            "city": "Ikoyi",
                            "postal_code": "100021",
                            "bedroom": 2,
                            "bathroom": 2,
                            "square_feet": 2000,
                            "price_per_year": 20000000,
                            "features": {"amenities": ["gym"]},
                        },
                    },
                }
            }

            updated_landlords = {
                "christian": {
                    **initial_landlords["christian"],
                    "listings": {
                        "01": initial_landlords["christian"]["listings"]["01"],
                    },
                }
            }

            Path(landlord_seed_path).write_text(json.dumps(initial_landlords))
            Path(tenant_seed_path).write_text("{}")

            with override_settings(
                MEDIA_ROOT=temp_dir,
                STORAGES=TEST_FILE_STORAGES,
                SEED_LANDLORD_DATA_PATH=landlord_seed_path,
                SEED_TENANT_DATA_PATH=tenant_seed_path,
            ):
                call_command("seed_demo_data")
                self.assertEqual(Listing.objects.filter(landlord__email="seedchristian@example.com").count(), 2)

                Path(landlord_seed_path).write_text(json.dumps(updated_landlords))
                call_command("seed_demo_data", force=True)

        listings = Listing.objects.filter(landlord__email="seedchristian@example.com").order_by("seed_key")
        self.assertEqual(listings.count(), 1)
        self.assertEqual(listings.first().seed_key, "01")


class FeaturedPaymentTests(TestCase):
    @override_settings(
        FLUTTERWAVE_PUBLIC_KEY="test-public-key",
        FLUTTERWAVE_SECRET_KEY="test-secret-key",
        WEB_PUBLIC_URL="http://localhost:5173",
    )
    @patch("core.views.query_transaction")
    def test_flutterwave_checkout_and_verification_mark_listing_featured(self, query_transaction_mock):
        landlord = AppUser.objects.create_user(
            email="landlord@example.com",
            password="password-123",
            name="Demo Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        listing = Listing.objects.create(
            landlord=landlord,
            title="Demo Listing",
            description="A bright apartment in Ikoyi",
            address="23 Gerald Road",
            city="Ikoyi",
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=2500000,
        )
        payment = FeaturedPayment.objects.create(
            listing=listing,
            landlord=landlord,
            amount="5000.00",
            featured_duration_days=30,
            expires_at=timezone.now() + timedelta(days=30),
            transaction_id="FEAT_TEST_MOCK_001",
        )

        client = APIClient()
        client.force_authenticate(user=landlord)
        response = client.post(f"/api/v1/featured/{payment.id}/flutterwave/checkout", {}, format="json")

        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        self.assertEqual(payload["payment"]["status"], "pending")
        self.assertEqual(payload["payment"]["provider"], "flutterwave")
        self.assertEqual(payload["checkout"]["checkout_mode"], "inline")
        self.assertEqual(payload["checkout"]["flutterwave"]["tx_ref"], payment.transaction_id)
        self.assertNotIn("subaccounts", payload["checkout"]["flutterwave"])

        payment.refresh_from_db()
        self.assertEqual(payment.status, "pending")
        self.assertIsNone(payment.payment_date)

        query_transaction_mock.return_value = {
            "status": "success",
            "data": {
                "id": "777",
                "tx_ref": payment.transaction_id,
                "status": "successful",
                "amount": "5000.00",
                "currency": "NGN",
                "customer": {"email": landlord.email},
            },
        }

        verify_response = client.get(
            "/api/v1/featured/flutterwave/verify",
            {
                "reference": payment.transaction_id,
                "transaction_id": "777",
                "status": "successful",
            },
        )

        self.assertEqual(verify_response.status_code, 200, verify_response.json())
        self.assertEqual(verify_response.json()["status"], "completed")
        payment.refresh_from_db()
        listing.refresh_from_db()
        self.assertEqual(payment.status, "completed")
        self.assertEqual(payment.provider, "flutterwave")
        self.assertIsNotNone(payment.payment_date)
        self.assertTrue(listing.featured)
        self.assertEqual(listing.featured_until, payment.expires_at)

    def test_manual_featured_payment_status_change_syncs_listing(self):
        landlord = AppUser.objects.create_user(
            email="landlord2@example.com",
            password="password-123",
            name="Second Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        listing = Listing.objects.create(
            landlord=landlord,
            title="Admin Managed Listing",
            description="A bright apartment in Victoria Island",
            address="12 Kofo Abayomi Street",
            city="Lagos",
            property_type="Apartment",
            bedrooms=3,
            bathrooms=3,
            price_per_year=4000000,
        )
        payment = FeaturedPayment.objects.create(
            listing=listing,
            landlord=landlord,
            amount="5000.00",
            featured_duration_days=30,
            expires_at=timezone.now() + timedelta(days=30),
            transaction_id="FEAT_TEST_ADMIN_001",
        )

        payment.status = FeaturedPayment.Status.COMPLETED
        payment.payment_date = timezone.now()
        payment.save(update_fields=["status", "payment_date", "updated_at"])

        listing.refresh_from_db()
        self.assertTrue(listing.featured)
        self.assertEqual(listing.featured_until, payment.expires_at)

        payment.status = FeaturedPayment.Status.CANCELLED
        payment.save(update_fields=["status", "updated_at"])

        listing.refresh_from_db()
        self.assertFalse(listing.featured)
        self.assertIsNone(listing.featured_until)

    def test_unfeature_endpoint_clears_featured_listing_without_payment_record(self):
        landlord = AppUser.objects.create_user(
            email="landlord3@example.com",
            password="password-123",
            name="Third Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        listing = Listing.objects.create(
            landlord=landlord,
            title="Seeded Featured Listing",
            description="Featured from seed data",
            address="40 Bourdillon Road",
            city="Ikoyi",
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=3500000,
            featured=True,
            featured_until=timezone.now() + timedelta(days=30),
        )

        client = APIClient()
        client.force_authenticate(user=landlord)
        response = client.delete(f"/api/v1/featured/{listing.id}/unfeature")

        self.assertEqual(response.status_code, 200, response.json())
        listing.refresh_from_db()
        self.assertFalse(listing.featured)
        self.assertIsNone(listing.featured_until)


class SubscriptionPaymentTests(TestCase):
    @override_settings(
        FLUTTERWAVE_CLIENT_ID="test-client-id",
        FLUTTERWAVE_CLIENT_SECRET="test-client-secret",
        FLUTTERWAVE_API_BASE_URL="https://developersandbox-api.flutterwave.com",
        FLUTTERWAVE_ENCRYPTION_KEY="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
        RENTDIRECT_SUBSCRIPTION_SUBACCOUNT_ID="",
        RENTDIRECT_SUBSCRIPTION_BANK_NAME="",
        RENTDIRECT_SUBSCRIPTION_BANK_CODE="",
        RENTDIRECT_SUBSCRIPTION_ACCOUNT_NUMBER="",
    )
    def test_recurring_subscription_config_requires_direct_settlement_account(self):
        tenant = AppUser.objects.create_user(
            email="tenant-recurring-config@example.com",
            password="password-123",
            name="Recurring Config Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        client = APIClient()
        client.force_authenticate(user=tenant)

        response = client.get("/api/v1/subscriptions/recurring/config")

        self.assertEqual(response.status_code, 200, response.json())
        self.assertFalse(response.json()["enabled"])
        self.assertFalse(response.json()["direct_settlement_configured"])

    def test_free_bronze_subscription_completes_immediately_for_14_days(self):
        landlord = AppUser.objects.create_user(
            email="landlord-free-subscription@example.com",
            password="password-123",
            name="Free Subscription Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )

        client = APIClient()
        client.force_authenticate(user=landlord)
        before = timezone.now()

        response = client.post(
            "/api/v1/subscriptions/request",
            {
                "plan_code": "bronze",
                "billing_cycle": "monthly",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        payment = SubscriptionPayment.objects.get(id=response.json()["id"])
        self.assertEqual(payment.status, SubscriptionPayment.Status.COMPLETED)
        self.assertEqual(payment.provider, "free")
        self.assertEqual(str(payment.amount), "0.00")
        self.assertIsNotNone(payment.payment_date)
        self.assertGreaterEqual(payment.expires_at, before + timedelta(days=14, seconds=-5))
        self.assertLessEqual(payment.expires_at, before + timedelta(days=14, seconds=5))

    def test_user_can_cancel_pending_subscription_payment(self):
        tenant = AppUser.objects.create_user(
            email="tenant-cancel-subscription@example.com",
            password="password-123",
            name="Cancel Subscription Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        payment = SubscriptionPayment.objects.create(
            user=tenant,
            role=tenant.role,
            plan_code=SubscriptionPayment.PlanCode.SILVER,
            billing_cycle=SubscriptionPayment.BillingCycle.MONTHLY,
            amount=5000,
            currency="NGN",
            status=SubscriptionPayment.Status.PENDING,
            provider="flutterwave",
            transaction_id="SUB_CANCEL_TEST",
            expires_at=timezone.now() + timedelta(days=30),
        )

        client = APIClient()
        client.force_authenticate(user=tenant)
        response = client.post(f"/api/v1/subscriptions/{payment.id}/cancel", {}, format="json")

        self.assertEqual(response.status_code, 200, response.json())
        payment.refresh_from_db()
        self.assertEqual(payment.status, SubscriptionPayment.Status.CANCELLED)
        self.assertEqual(payment.provider_payload["cancellation"]["reason"], "cancelled_by_user")

    def test_completed_subscription_payment_cannot_be_cancelled(self):
        tenant = AppUser.objects.create_user(
            email="tenant-cancel-completed-subscription@example.com",
            password="password-123",
            name="Cancel Completed Subscription Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        payment = create_active_subscription(tenant, SubscriptionPayment.PlanCode.SILVER)

        client = APIClient()
        client.force_authenticate(user=tenant)
        response = client.post(f"/api/v1/subscriptions/{payment.id}/cancel", {}, format="json")

        self.assertEqual(response.status_code, 400, response.json())
        payment.refresh_from_db()
        self.assertEqual(payment.status, SubscriptionPayment.Status.COMPLETED)

    @override_settings(
        FLUTTERWAVE_PUBLIC_KEY="test-public-key",
        FLUTTERWAVE_SECRET_KEY="test-secret-key",
        RENTDIRECT_SUBSCRIPTION_SUBACCOUNT_ID="RS_SUBSCRIPTION_TEST",
        RENTDIRECT_SUBSCRIPTION_BANK_NAME="FCMB",
        RENTDIRECT_SUBSCRIPTION_BANK_CODE="214",
        RENTDIRECT_SUBSCRIPTION_ACCOUNT_NUMBER="0000000000",
        RENTDIRECT_SUBSCRIPTION_ACCOUNT_NAME="RentDirect Subscription",
        WEB_PUBLIC_URL="http://localhost:5173",
    )
    @patch("core.views.query_transaction")
    def test_tenant_subscription_checkout_and_verification_complete_payment(self, query_transaction_mock):
        tenant = AppUser.objects.create_user(
            email="tenant-subscription@example.com",
            password="password-123",
            name="Subscription Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )

        client = APIClient()
        client.force_authenticate(user=tenant)

        request_response = client.post(
            "/api/v1/subscriptions/request",
            {
                "plan_code": "silver",
                "billing_cycle": "monthly",
            },
            format="json",
        )

        self.assertEqual(request_response.status_code, 201, request_response.json())
        payment = SubscriptionPayment.objects.get(id=request_response.json()["id"])
        expected_amount = get_subscription_pricing()["tenant"]["silver"]["monthly"]
        expected_amount_display = f"{expected_amount:.2f}"
        self.assertEqual(payment.status, SubscriptionPayment.Status.PENDING)
        self.assertEqual(str(payment.amount), expected_amount_display)

        checkout_response = client.post(f"/api/v1/subscriptions/{payment.id}/flutterwave/checkout", {}, format="json")

        self.assertEqual(checkout_response.status_code, 200, checkout_response.json())
        checkout_payload = checkout_response.json()
        self.assertEqual(checkout_payload["payment"]["status"], "pending")
        self.assertEqual(checkout_payload["checkout"]["checkout_mode"], "inline")
        self.assertEqual(checkout_payload["checkout"]["flutterwave"]["tx_ref"], payment.transaction_id)
        self.assertEqual(
            checkout_payload["checkout"]["flutterwave"]["subaccounts"],
            [
                {
                    "id": "RS_SUBSCRIPTION_TEST",
                    "transaction_charge_type": "flat",
                    "transaction_charge": 0,
                }
            ],
        )
        payment.refresh_from_db()
        self.assertEqual(payment.provider_payload["subscription_destination"]["subaccount_id"], "RS_SUBSCRIPTION_TEST")
        self.assertEqual(payment.provider_payload["subscription_destination"]["account_number"], "0000000000")

        query_transaction_mock.return_value = {
            "status": "success",
            "data": {
                "id": "991",
                "tx_ref": payment.transaction_id,
                "status": "successful",
                "amount": expected_amount_display,
                "currency": "NGN",
                "customer": {"email": tenant.email},
            },
        }

        verify_response = client.get(
            "/api/v1/subscriptions/flutterwave/verify",
            {
                "reference": payment.transaction_id,
                "transaction_id": "991",
                "status": "successful",
            },
        )

        self.assertEqual(verify_response.status_code, 200, verify_response.json())
        self.assertEqual(verify_response.json()["status"], "completed")

        payment.refresh_from_db()
        self.assertEqual(payment.status, SubscriptionPayment.Status.COMPLETED)
        self.assertEqual(payment.provider, "flutterwave")
        self.assertIsNotNone(payment.payment_date)

    @override_settings(
        FLUTTERWAVE_PUBLIC_KEY="test-public-key",
        FLUTTERWAVE_SECRET_KEY="test-secret-key",
        RENTDIRECT_SUBSCRIPTION_SUBACCOUNT_ID="",
        RENTDIRECT_SUBSCRIPTION_BANK_NAME="FCMB",
        RENTDIRECT_SUBSCRIPTION_BANK_CODE="",
        RENTDIRECT_SUBSCRIPTION_ACCOUNT_NUMBER="0000000000",
        RENTDIRECT_SUBSCRIPTION_ACCOUNT_NAME="RentDirect Subscription",
        RENTDIRECT_SUBSCRIPTION_BUSINESS_EMAIL="billing@rentdirect.homes",
        RENTDIRECT_SUBSCRIPTION_BUSINESS_MOBILE="08000000000",
        WEB_PUBLIC_URL="http://localhost:5173",
    )
    @patch("core.views.get_or_create_collection_subaccount_id", return_value="RS_CREATED_SUBSCRIPTION")
    def test_subscription_checkout_creates_flutterwave_subaccount_from_configured_account(self, subaccount_mock):
        tenant = AppUser.objects.create_user(
            email="tenant-subscription-subaccount@example.com",
            password="password-123",
            name="Subscription Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        payment = SubscriptionPayment.objects.create(
            user=tenant,
            role=tenant.role,
            plan_code=SubscriptionPayment.PlanCode.SILVER,
            billing_cycle=SubscriptionPayment.BillingCycle.MONTHLY,
            amount="200.00",
            currency="NGN",
            status=SubscriptionPayment.Status.PENDING,
            provider="flutterwave",
            transaction_id="SUBACCOUNTTEST001",
            expires_at=timezone.now() + timedelta(days=30),
        )

        client = APIClient()
        client.force_authenticate(user=tenant)
        response = client.post(f"/api/v1/subscriptions/{payment.id}/flutterwave/checkout", {}, format="json")

        self.assertEqual(response.status_code, 200, response.json())
        subaccount_mock.assert_called_once_with(
            bank_code="214",
            account_number="0000000000",
            business_name="RentDirect Subscription",
            business_email="billing@rentdirect.homes",
            business_mobile="08000000000",
            country="NG",
            split_type="flat",
            split_value="0",
        )
        self.assertEqual(response.json()["checkout"]["flutterwave"]["subaccounts"][0]["id"], "RS_CREATED_SUBSCRIPTION")

    @override_settings(
        FLUTTERWAVE_PUBLIC_KEY="test-public-key",
        FLUTTERWAVE_SECRET_KEY="test-secret-key",
        FLUTTERWAVE_CLIENT_ID="test-client-id",
        FLUTTERWAVE_CLIENT_SECRET="test-client-secret",
        FLUTTERWAVE_API_BASE_URL="https://developersandbox-api.flutterwave.com",
        FLUTTERWAVE_ENCRYPTION_KEY="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
        RENTDIRECT_SUBSCRIPTION_SUBACCOUNT_ID="RS_SUBSCRIPTION_TEST",
        RENTDIRECT_SUBSCRIPTION_BANK_NAME="FCMB",
        RENTDIRECT_SUBSCRIPTION_BANK_CODE="214",
        RENTDIRECT_SUBSCRIPTION_ACCOUNT_NUMBER="0000000000",
        RENTDIRECT_SUBSCRIPTION_ACCOUNT_NAME="RentDirect Subscription",
        WEB_PUBLIC_URL="http://localhost:5173",
    )
    @patch("core.views.create_charge")
    @patch("core.views.create_card_payment_method")
    @patch("core.views.create_customer")
    def test_landlord_can_start_recurring_subscription_with_new_saved_card(
        self,
        create_customer_mock,
        create_card_payment_method_mock,
        create_charge_mock,
    ):
        landlord = AppUser.objects.create_user(
            email="landlord-recurring-subscription@example.com",
            password="password-123",
            name="Recurring Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        create_customer_mock.return_value = {"status": "success", "data": {"id": "cus_recurring_123"}}
        create_card_payment_method_mock.return_value = {
            "status": "success",
            "data": {
                "id": "pmd_recurring_123",
                "customer_id": "cus_recurring_123",
                "type": "card",
                "card": {
                    "first6": "539983",
                    "last4": "8381",
                    "network": "mastercard",
                    "expiry_month": 8,
                    "expiry_year": 32,
                },
            },
        }

        def charge_response(**kwargs):
            return {
                "status": "success",
                "data": {
                    "id": "chg_recurring_123",
                    "reference": kwargs["reference"],
                    "status": "succeeded",
                    "amount": str(kwargs["amount"]),
                    "currency": kwargs["currency"],
                    "customer": {"email": landlord.email},
                    "payment_method": {
                        "id": "pmd_recurring_123",
                        "type": "card",
                        "card": {
                            "last4": "8381",
                            "network": "mastercard",
                        },
                    },
                },
            }

        create_charge_mock.side_effect = charge_response

        client = APIClient()
        client.force_authenticate(user=landlord)
        response = client.post(
            "/api/v1/subscriptions/request",
            {
                "plan_code": "gold",
                "billing_cycle": "monthly",
                "recurring": True,
                "card": {
                    "nonce": "abc123def456",
                    "encrypted_card_number": "encrypted-card",
                    "encrypted_expiry_month": "encrypted-month",
                    "encrypted_expiry_year": "encrypted-year",
                    "encrypted_cvv": "encrypted-cvv",
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        payload = response.json()
        self.assertEqual(payload["status"], SubscriptionPayment.Status.COMPLETED)
        self.assertTrue(payload["recurring_enabled"])
        self.assertEqual(payload["payment_method"]["card_last4"], "8381")
        payment = SubscriptionPayment.objects.get(id=payload["id"])
        self.assertEqual(payment.provider_charge_id, "chg_recurring_123")
        self.assertEqual(payment.billing_reason, "recurring_initial")
        self.assertEqual(payment.payment_method.provider_payment_method_id, "pmd_recurring_123")
        self.assertEqual(SubscriptionPaymentMethod.objects.filter(user=landlord).count(), 1)
        self.assertEqual(create_charge_mock.call_args.kwargs["recurring"], False)
        self.assertEqual(payment.provider_payload["recurring"]["gateway_recurring"], False)
        self.assertEqual(
            create_charge_mock.call_args.kwargs["subaccounts"],
            [
                {
                    "id": "RS_SUBSCRIPTION_TEST",
                    "transaction_charge_type": "flat",
                    "transaction_charge": 0,
                }
            ],
        )
        self.assertEqual(payment.provider_payload["subscription_destination"]["subaccount_id"], "RS_SUBSCRIPTION_TEST")

    @override_settings(
        FLUTTERWAVE_PUBLIC_KEY="test-public-key",
        FLUTTERWAVE_SECRET_KEY="test-secret-key",
        FLUTTERWAVE_CLIENT_ID="test-client-id",
        FLUTTERWAVE_CLIENT_SECRET="test-client-secret",
        FLUTTERWAVE_API_BASE_URL="https://developersandbox-api.flutterwave.com",
        RENTDIRECT_SUBSCRIPTION_SUBACCOUNT_ID="RS_SUBSCRIPTION_TEST",
        RENTDIRECT_SUBSCRIPTION_BANK_NAME="FCMB",
        RENTDIRECT_SUBSCRIPTION_BANK_CODE="214",
        RENTDIRECT_SUBSCRIPTION_ACCOUNT_NUMBER="0000000000",
        RENTDIRECT_SUBSCRIPTION_ACCOUNT_NAME="RentDirect Subscription",
        WEB_PUBLIC_URL="http://localhost:5173",
    )
    @patch("core.views.create_charge")
    def test_due_recurring_subscription_is_renewed_with_saved_payment_method(self, create_charge_mock):
        tenant = AppUser.objects.create_user(
            email="tenant-recurring-renewal@example.com",
            password="password-123",
            name="Recurring Renewal Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        payment_method = SubscriptionPaymentMethod.objects.create(
            user=tenant,
            provider_customer_id="cus_renewal_123",
            provider_payment_method_id="pmd_renewal_123",
            card_last4="4242",
            card_network="visa",
        )
        initial_payment = SubscriptionPayment.objects.create(
            user=tenant,
            role=tenant.role,
            plan_code=SubscriptionPayment.PlanCode.SILVER,
            billing_cycle=SubscriptionPayment.BillingCycle.MONTHLY,
            amount="200.00",
            currency="NGN",
            status=SubscriptionPayment.Status.COMPLETED,
            provider="flutterwave",
            transaction_id="SUBRECURINIT001",
            payment_date=timezone.now() - timedelta(days=31),
            expires_at=timezone.now() - timedelta(minutes=5),
            payment_method=payment_method,
            recurring_enabled=True,
            billing_reason="recurring_initial",
        )

        def charge_response(**kwargs):
            return {
                "status": "success",
                "data": {
                    "id": "chg_renewal_123",
                    "reference": kwargs["reference"],
                    "status": "succeeded",
                    "amount": "200.00",
                    "currency": kwargs["currency"],
                    "customer": {"email": tenant.email},
                },
            }

        create_charge_mock.side_effect = charge_response

        from core.views import process_due_subscription_renewals

        result = process_due_subscription_renewals()

        self.assertEqual(result, {"checked": 1, "renewed": 1, "failed": 0})
        renewal = SubscriptionPayment.objects.get(renewed_from=initial_payment)
        self.assertEqual(renewal.status, SubscriptionPayment.Status.COMPLETED)
        self.assertTrue(renewal.recurring_enabled)
        self.assertEqual(renewal.provider_charge_id, "chg_renewal_123")
        self.assertEqual(renewal.payment_method, payment_method)
        self.assertEqual(create_charge_mock.call_args.kwargs["payment_method_id"], "pmd_renewal_123")
        self.assertEqual(create_charge_mock.call_args.kwargs["recurring"], True)
        self.assertEqual(create_charge_mock.call_args.kwargs["subaccounts"][0]["id"], "RS_SUBSCRIPTION_TEST")


class DashboardTests(TestCase):
    def test_landlord_dashboard_listings_excludes_archived_properties(self):
        landlord = AppUser.objects.create_user(
            email="dashboard-landlord@example.com",
            password="password-123",
            name="Dashboard Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        available_listing = Listing.objects.create(
            landlord=landlord,
            title="Available Listing",
            description="Still active",
            address="1 Active Street",
            city="Lagos",
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=2500000,
            status=Listing.Status.AVAILABLE,
        )
        Listing.objects.create(
            landlord=landlord,
            title="Archived Listing",
            description="Removed listing",
            address="2 Archive Street",
            city="Lagos",
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=1500000,
            status=Listing.Status.ARCHIVED,
        )

        client = APIClient()
        client.force_authenticate(user=landlord)
        response = client.get(f"/api/v1/dashboard/landlord/{landlord.id}/listings")

        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["id"], str(available_listing.id))

    def test_landlord_bookings_include_collected_expecting_and_outstanding_payments(self):
        landlord = AppUser.objects.create_user(
            email="dashboard-payments-landlord@example.com",
            password="password-123",
            name="Dashboard Payments Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        tenant = AppUser.objects.create_user(
            email="dashboard-payments-tenant@example.com",
            password="password-123",
            name="Dashboard Payments Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        listing = Listing.objects.create(
            landlord=landlord,
            title="Dashboard Payment Listing",
            description="Dashboard payment test",
            address="3 Payment Street",
            city="Lagos",
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=1000000,
            status=Listing.Status.AVAILABLE,
        )
        booking = Booking.objects.create(
            tenant=tenant,
            listing=listing,
            start_date=date(2026, 6, 19),
            end_date=date(2027, 6, 19),
            total_amount=1200000,
            paid_amount=600000,
        )
        paid_payment = Payment.objects.create(
            booking=booking,
            amount=300000,
            payment_method="bank",
            status="completed",
            transaction_id="DASHBOARDPAYMENTPAID",
            provider="flutterwave",
            currency="NGN",
        )
        expected_payment = Payment.objects.create(
            booking=booking,
            amount=300000,
            payment_method="bank",
            status="completed",
            transaction_id="DASHBOARDPAYMENTPENDING",
            provider="flutterwave",
            currency="NGN",
        )
        PaymentSettlement.objects.create(
            payment=paid_payment,
            purpose=PaymentSettlement.Purpose.LANDLORD_RENT,
            amount=250000,
            currency="NGN",
            bank_name="Palm Pay",
            account_number="9041487757",
            status=PaymentSettlement.Status.PAID,
        )
        PaymentSettlement.objects.create(
            payment=expected_payment,
            purpose=PaymentSettlement.Purpose.LANDLORD_RENT,
            amount=250000,
            currency="NGN",
            bank_name="Palm Pay",
            account_number="9041487757",
            status=PaymentSettlement.Status.READY,
        )

        client = APIClient()
        client.force_authenticate(user=landlord)
        response = client.get("/api/v1/bookings")

        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        results = payload["results"] if isinstance(payload, dict) and "results" in payload else payload
        booking_payload = next(item for item in results if item["id"] == str(booking.id))
        self.assertEqual(booking_payload["landlord_rental_amount"], 1000000.0)
        self.assertEqual(booking_payload["landlord_collected_amount"], 250000.0)
        self.assertEqual(booking_payload["landlord_expecting_payment_amount"], 350000.0)
        self.assertEqual(booking_payload["landlord_balance_payment_amount"], 400000.0)
        self.assertEqual(booking_payload["remaining_amount"], 600000.0)


class PublicStatsTests(TestCase):
    def test_public_stats_returns_live_counts(self):
        landlord = AppUser.objects.create_user(
            email="stats-landlord@example.com",
            password="password-123",
            name="Stats Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        AppUser.objects.create_user(
            email="stats-tenant@example.com",
            password="password-123",
            name="Stats Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        Listing.objects.create(
            landlord=landlord,
            title="Public Stats Listing",
            description="Count me",
            address="3 Count Street",
            city="Abuja",
            property_type="Apartment",
            bedrooms=1,
            bathrooms=1,
            price_per_year=900000,
            status=Listing.Status.AVAILABLE,
        )
        Listing.objects.create(
            landlord=landlord,
            title="Archived Stats Listing",
            description="Do not count me",
            address="4 Hidden Street",
            city="Abuja",
            property_type="Apartment",
            bedrooms=1,
            bathrooms=1,
            price_per_year=950000,
            status=Listing.Status.ARCHIVED,
        )

        response = self.client.get("/api/v1/users/public-stats")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"properties": 1, "landlords": 1, "tenants": 1})


class ReviewTests(TestCase):
    def test_tenant_can_create_and_update_listing_review(self):
        landlord = AppUser.objects.create_user(
            email="review-landlord@example.com",
            password="password-123",
            name="Review Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        tenant = AppUser.objects.create_user(
            email="review-tenant@example.com",
            password="password-123",
            name="Review Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        create_active_subscription(tenant, SubscriptionPayment.PlanCode.GOLD)
        listing = Listing.objects.create(
            landlord=landlord,
            title="Review Listing",
            description="Review me",
            address="15 Review Street",
            city="Lagos",
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=2000000,
        )

        client = APIClient()
        client.force_authenticate(user=tenant)
        create_response = client.post(
            "/api/v1/reviews",
            {
                "listing_id": str(listing.id),
                "rating": 5,
                "comment": "Very responsive landlord.",
            },
            format="json",
        )

        self.assertEqual(create_response.status_code, 201, create_response.json())
        review_id = create_response.json()["id"]

        update_response = client.patch(
            f"/api/v1/reviews/{review_id}",
            {
                "listing_id": str(listing.id),
                "rating": 4,
                "comment": "Quick maintenance response.",
            },
            format="json",
        )

        self.assertEqual(update_response.status_code, 200, update_response.json())
        review = Review.objects.get(pk=review_id)
        self.assertEqual(review.rating, 4)
        self.assertEqual(review.comment, "Quick maintenance response.")
        self.assertEqual(review.review_type, Review.ReviewType.PROPERTY)

        public_response = self.client.get(f"/api/v1/reviews?landlord_id={landlord.id}")
        self.assertEqual(public_response.status_code, 200)
        self.assertEqual(len(public_response.json()), 1)

        landlord_review_response = client.post(
            "/api/v1/reviews",
            {
                "review_type": Review.ReviewType.LANDLORD,
                "listing_id": str(listing.id),
                "rating": 5,
                "comment": "Great landlord.",
            },
            format="json",
        )

        self.assertEqual(landlord_review_response.status_code, 201, landlord_review_response.json())

        property_reviews_response = self.client.get(f"/api/v1/reviews?listing_id={listing.id}&review_type={Review.ReviewType.PROPERTY}")
        landlord_reviews_response = self.client.get(f"/api/v1/reviews?listing_id={listing.id}&review_type={Review.ReviewType.LANDLORD}")
        self.assertEqual(len(property_reviews_response.json()), 1)
        self.assertEqual(property_reviews_response.json()[0]["comment"], "Quick maintenance response.")
        self.assertEqual(len(landlord_reviews_response.json()), 1)
        self.assertEqual(landlord_reviews_response.json()[0]["comment"], "Great landlord.")

    def test_silver_tenant_cannot_create_listing_review(self):
        landlord = AppUser.objects.create_user(
            email="review-bronze-landlord@example.com",
            password="password-123",
            name="Review Bronze Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        tenant = AppUser.objects.create_user(
            email="review-bronze-tenant@example.com",
            password="password-123",
            name="Review Bronze Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        create_active_subscription(tenant, SubscriptionPayment.PlanCode.SILVER)
        listing = Listing.objects.create(
            landlord=landlord,
            title="Bronze Review Listing",
            description="Review locked",
            address="18 Review Street",
            city="Lagos",
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=2000000,
        )

        client = APIClient()
        client.force_authenticate(user=tenant)
        response = client.post(
            "/api/v1/reviews",
            {
                "listing_id": str(listing.id),
                "rating": 5,
                "comment": "Locked review.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403, response.json())
        self.assertFalse(Review.objects.filter(listing=listing, tenant=tenant).exists())

    def test_review_update_cannot_move_review_to_a_different_listing(self):
        landlord = AppUser.objects.create_user(
            email="review-lock-landlord@example.com",
            password="password-123",
            name="Review Lock Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        tenant = AppUser.objects.create_user(
            email="review-lock-tenant@example.com",
            password="password-123",
            name="Review Lock Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        create_active_subscription(tenant, SubscriptionPayment.PlanCode.GOLD)
        listing_one = Listing.objects.create(
            landlord=landlord,
            title="Review Listing One",
            description="Review me",
            address="15 Review Street",
            city="Lagos",
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=2000000,
        )
        listing_two = Listing.objects.create(
            landlord=landlord,
            title="Review Listing Two",
            description="Review me too",
            address="16 Review Street",
            city="Lagos",
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=2100000,
        )
        review = Review.objects.create(
            listing=listing_one,
            landlord=landlord,
            tenant=tenant,
            rating=5,
            comment="Initial review.",
        )

        client = APIClient()
        client.force_authenticate(user=tenant)
        response = client.patch(
            f"/api/v1/reviews/{review.id}",
            {
                "listing_id": str(listing_two.id),
                "rating": 4,
                "comment": "Updated review.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.json())
        review.refresh_from_db()
        self.assertEqual(review.listing_id, listing_one.id)


class FeedbackTests(TestCase):
    def test_feedback_submission_uses_authenticated_user_role(self):
        tenant = AppUser.objects.create_user(
            email="feedback-tenant@example.com",
            password="password-123",
            name="Feedback Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )

        client = APIClient()
        client.force_authenticate(user=tenant)
        response = client.post(
            "/api/v1/feedback",
            {
                "name": "Feedback Tenant",
                "role": AppUser.Role.LANDLORD,
                "topic": "Search quality",
                "message": "Please improve search filters.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        feedback = Feedback.objects.get()
        self.assertEqual(feedback.role, AppUser.Role.TENANT)
        self.assertEqual(feedback.topic, "Search quality")

    def test_tenant_issue_priority_is_derived_from_active_plan(self):
        bronze_tenant = AppUser.objects.create_user(
            email="feedback-bronze-priority@example.com",
            password="password-123",
            name="Bronze Support Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        gold_tenant = AppUser.objects.create_user(
            email="feedback-gold-priority@example.com",
            password="password-123",
            name="Gold Support Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        platinum_tenant = AppUser.objects.create_user(
            email="feedback-platinum-priority@example.com",
            password="password-123",
            name="Platinum Support Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        create_active_subscription(bronze_tenant, SubscriptionPayment.PlanCode.BRONZE, days=14)
        create_active_subscription(gold_tenant, SubscriptionPayment.PlanCode.GOLD)
        create_active_subscription(platinum_tenant, SubscriptionPayment.PlanCode.PLATINUM)

        client = APIClient()
        for tenant, submitted_topic, expected_topic in [
            (bronze_tenant, "Priority Issue: Payment help", "Issue: Payment help"),
            (gold_tenant, "Issue: Payment help", "Priority Issue: Payment help"),
            (
                platinum_tenant,
                "Issue: Payment help",
                "Premium Rental Workflow: Payment help",
            ),
        ]:
            client.force_authenticate(user=tenant)
            response = client.post(
                "/api/v1/feedback",
                {
                    "name": tenant.name,
                    "topic": submitted_topic,
                    "message": "Please help with this rental.",
                },
                format="json",
            )
            self.assertEqual(response.status_code, 201, response.json())
            self.assertEqual(Feedback.objects.get(id=response.json()["id"]).topic, expected_topic)


class MessageSubscriptionAccessTests(TestCase):
    def create_verified_tenant(self, email):
        tenant = AppUser.objects.create_user(
            email=email,
            password="password-123",
            name="Verified Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        VerificationRequest.objects.create(
            user=tenant,
            status=VerificationRequest.Status.APPROVED,
        )
        return tenant

    def create_landlord(self, email):
        return AppUser.objects.create_user(
            email=email,
            password="password-123",
            name="Message Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )

    def test_bronze_tenant_cannot_contact_landlord(self):
        tenant = self.create_verified_tenant("message-bronze-tenant@example.com")
        landlord = self.create_landlord("message-landlord@example.com")
        create_active_subscription(tenant, SubscriptionPayment.PlanCode.BRONZE, days=14)
        create_active_subscription(landlord, SubscriptionPayment.PlanCode.SILVER)

        client = APIClient()
        client.force_authenticate(user=tenant)
        response = client.post(
            "/api/v1/messages",
            {
                "receiver_id": str(landlord.id),
                "content": "I would like to arrange a viewing.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403, response.json())
        self.assertFalse(Message.objects.filter(sender=tenant, receiver=landlord).exists())

    def test_silver_tenant_can_contact_landlord_and_read_conversation(self):
        tenant = self.create_verified_tenant("message-silver-access-tenant@example.com")
        landlord = self.create_landlord("message-silver-access-landlord@example.com")
        create_active_subscription(tenant, SubscriptionPayment.PlanCode.SILVER)
        create_active_subscription(landlord, SubscriptionPayment.PlanCode.SILVER)

        client = APIClient()
        client.force_authenticate(user=tenant)
        create_response = client.post(
            "/api/v1/messages",
            {
                "receiver_id": str(landlord.id),
                "content": "I would like to arrange a viewing.",
            },
            format="json",
        )
        conversations_response = client.get("/api/v1/messages")

        self.assertEqual(create_response.status_code, 201, create_response.json())
        self.assertEqual(conversations_response.status_code, 200, conversations_response.json())

    def test_bronze_tenant_cannot_read_landlord_conversations(self):
        tenant = self.create_verified_tenant("message-bronze-history-tenant@example.com")
        landlord = self.create_landlord("message-bronze-history-landlord@example.com")
        create_active_subscription(tenant, SubscriptionPayment.PlanCode.BRONZE, days=14)
        Message.objects.create(
            sender=tenant,
            receiver=landlord,
            content="An existing conversation.",
        )

        client = APIClient()
        client.force_authenticate(user=tenant)
        response = client.get("/api/v1/messages")

        self.assertEqual(response.status_code, 403, response.json())

    def test_tenant_cannot_contact_bronze_landlord(self):
        tenant = self.create_verified_tenant("message-silver-tenant@example.com")
        landlord = self.create_landlord("message-bronze-landlord@example.com")
        create_active_subscription(tenant, SubscriptionPayment.PlanCode.SILVER)
        create_active_subscription(landlord, SubscriptionPayment.PlanCode.BRONZE, days=14)

        client = APIClient()
        client.force_authenticate(user=tenant)
        response = client.post(
            "/api/v1/messages",
            {
                "receiver_id": str(landlord.id),
                "content": "Can I view this property?",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403, response.json())
        self.assertFalse(Message.objects.filter(sender=tenant, receiver=landlord).exists())

    def test_bronze_landlord_cannot_contact_tenant(self):
        landlord = self.create_landlord("message-bronze-sender-landlord@example.com")
        tenant = self.create_verified_tenant("message-receiver-tenant@example.com")
        create_active_subscription(landlord, SubscriptionPayment.PlanCode.BRONZE, days=14)
        create_active_subscription(tenant, SubscriptionPayment.PlanCode.SILVER)

        client = APIClient()
        client.force_authenticate(user=landlord)
        response = client.post(
            "/api/v1/messages",
            {
                "receiver_id": str(tenant.id),
                "content": "Following up on your enquiry.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403, response.json())
        self.assertFalse(Message.objects.filter(sender=landlord, receiver=tenant).exists())


class MessageEnquiryTests(TestCase):
    def create_verified_tenant(self, email, name="Verified Tenant"):
        tenant = AppUser.objects.create_user(
            email=email,
            password="password-123",
            name=name,
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        VerificationRequest.objects.create(
            user=tenant,
            status=VerificationRequest.Status.APPROVED,
        )
        return tenant

    def test_landlord_enquiries_include_tenant_messages_for_listing_without_images(self):
        landlord = AppUser.objects.create_user(
            email="christian-enquiries@example.com",
            password="password-123",
            name="Christian",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        tenant = AppUser.objects.create_user(
            email="jade-enquiries@example.com",
            password="password-123",
            name="Jade",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        listing = Listing.objects.create(
            landlord=landlord,
            title="Christian Listing",
            description="Listing without uploaded images",
            address="1 Enquiry Street",
            city="Lagos",
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=1500000,
            status=Listing.Status.AVAILABLE,
        )
        Message.objects.create(
            sender=tenant,
            receiver=landlord,
            listing=listing,
            content="Viewing Availability: Tomorrow by 6 pm\n\nHi, can I view your house?",
        )
        Message.objects.create(
            sender=tenant,
            receiver=landlord,
            listing=listing,
            content="Let me know if you are available",
        )
        latest_message = Message.objects.create(
            sender=tenant,
            receiver=landlord,
            listing=listing,
            content="I am still unable to see enquiries",
        )

        client = APIClient()
        client.force_authenticate(user=landlord)
        response = client.get("/api/v1/messages/enquiries")

        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["id"], str(latest_message.id))
        self.assertEqual(payload[0]["tenant_name"], "Jade")
        self.assertEqual(payload[0]["landlord_id"], str(landlord.id))
        self.assertEqual(payload[0]["landlord_name"], "Christian")
        self.assertEqual(payload[0]["listing_id"], str(listing.id))
        self.assertEqual(payload[0]["listing_cover_image_url"], "")
        self.assertEqual(payload[0]["last_message"], "I am still unable to see enquiries")
        self.assertEqual(payload[0]["message_count"], 3)

    def test_landlord_enquiries_include_messages_sent_through_contact_flow(self):
        landlord = AppUser.objects.create_user(
            email="contact-flow-landlord@example.com",
            password="password-123",
            name="Contact Flow Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        tenant = self.create_verified_tenant("contact-flow-tenant@example.com", name="Contact Flow Tenant")
        create_active_subscription(tenant, SubscriptionPayment.PlanCode.SILVER)
        create_active_subscription(landlord, SubscriptionPayment.PlanCode.SILVER)
        listing = Listing.objects.create(
            landlord=landlord,
            title="Contact Flow Listing",
            description="Listing with a tenant enquiry",
            address="3 Flow Street",
            city="Lagos",
            property_type="Apartment",
            bedrooms=1,
            bathrooms=1,
            price_per_year=1000000,
            status=Listing.Status.AVAILABLE,
        )

        client = APIClient()
        client.force_authenticate(user=tenant)
        create_response = client.post(
            "/api/v1/messages",
            {
                "receiver_id": str(landlord.id),
                "listing_id": str(listing.id),
                "content": "Viewing Availability: Saturday afternoon\n\nI would like to arrange a viewing.",
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, 201, create_response.json())

        client.force_authenticate(user=landlord)
        response = client.get("/api/v1/messages/enquiries")

        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["listing_id"], str(listing.id))
        self.assertEqual(payload[0]["tenant_id"], str(tenant.id))
        self.assertEqual(payload[0]["tenant_name"], "Contact Flow Tenant")
        self.assertEqual(payload[0]["last_message"], "Viewing Availability: Saturday afternoon\n\nI would like to arrange a viewing.")
        self.assertEqual(payload[0]["message_count"], 1)
        self.assertTrue(payload[0]["has_viewing_requested"])
        self.assertFalse(payload[0]["has_viewing_arranged"])

        Booking.objects.create(
            tenant=tenant,
            listing=listing,
            start_date=date(2026, 7, 1),
            end_date=date(2027, 7, 1),
            total_amount=calculate_booking_total(listing.price_per_year),
            tenant_rental_progress={
                "viewing_appointment_booked": timezone.now().isoformat(),
            },
        )

        arranged_response = client.get("/api/v1/messages/enquiries")
        self.assertEqual(arranged_response.status_code, 200, arranged_response.json())
        self.assertTrue(arranged_response.json()[0]["has_viewing_arranged"])

        viewing_requests_response = client.get(f"/api/v1/messages/listing/{listing.id}/viewing-requests")
        self.assertEqual(viewing_requests_response.status_code, 200, viewing_requests_response.json())
        viewing_requests = viewing_requests_response.json()
        self.assertEqual(len(viewing_requests), 1)
        self.assertEqual(viewing_requests[0]["tenant_id"], str(tenant.id))
        self.assertEqual(viewing_requests[0]["stage"], "Viewing arranged")
        self.assertEqual(viewing_requests[0]["rental_progress"]["completed_count"], 0)

    def test_landlord_enquiries_include_messages_attached_to_landlord_listing(self):
        landlord = AppUser.objects.create_user(
            email="attached-listing-landlord@example.com",
            password="password-123",
            name="Attached Listing Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        tenant = AppUser.objects.create_user(
            email="attached-listing-tenant@example.com",
            password="password-123",
            name="Attached Listing Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        admin = AppUser.objects.create_user(
            email="attached-listing-admin@example.com",
            password="password-123",
            name="Attached Listing Admin",
            role=AppUser.Role.ADMIN,
            email_verified=True,
        )
        listing = Listing.objects.create(
            landlord=landlord,
            title="Attached Listing",
            description="Message is tied to the listing owner",
            address="4 Attached Street",
            city="Lagos",
            property_type="Apartment",
            bedrooms=1,
            bathrooms=1,
            price_per_year=1000000,
            status=Listing.Status.AVAILABLE,
        )
        Message.objects.create(
            sender=tenant,
            receiver=admin,
            listing=listing,
            content="I sent this about the landlord listing.",
        )

        client = APIClient()
        client.force_authenticate(user=landlord)
        response = client.get("/api/v1/messages/enquiries")

        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["listing_id"], str(listing.id))
        self.assertEqual(payload[0]["tenant_id"], str(tenant.id))
        self.assertEqual(payload[0]["last_message"], "I sent this about the landlord listing.")

    def test_listing_thread_can_be_filtered_to_a_single_tenant_conversation(self):
        landlord = AppUser.objects.create_user(
            email="thread-landlord@example.com",
            password="password-123",
            name="Thread Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        tenant = AppUser.objects.create_user(
            email="thread-tenant@example.com",
            password="password-123",
            name="Thread Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        other_tenant = AppUser.objects.create_user(
            email="thread-other-tenant@example.com",
            password="password-123",
            name="Other Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        listing = Listing.objects.create(
            landlord=landlord,
            title="Shared Listing",
            description="Multiple tenant conversations",
            address="2 Thread Street",
            city="Lagos",
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=1500000,
            status=Listing.Status.AVAILABLE,
        )
        Message.objects.create(sender=tenant, receiver=landlord, listing=listing, content="Tenant enquiry")
        reply = Message.objects.create(sender=landlord, receiver=tenant, listing=listing, content="Landlord reply")
        Message.objects.create(sender=other_tenant, receiver=landlord, listing=listing, content="Other tenant enquiry")

        client = APIClient()
        client.force_authenticate(user=landlord)
        response = client.get(f"/api/v1/messages/listing/{listing.id}?counterpart_id={tenant.id}")

        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        self.assertEqual([item["content"] for item in payload], ["Tenant enquiry", "Landlord reply"])
        self.assertEqual(payload[1]["id"], str(reply.id))


class TenantPublicProfileTests(TestCase):
    def test_public_tenant_profile_exposes_screening_summary_without_private_contacts(self):
        tenant = AppUser.objects.create_user(
            email="public-tenant@example.com",
            password="password-123",
            name="Jade Bola Smith",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        TenantProfile.objects.create(
            user=tenant,
            status=TenantProfile.Status.APPROVED,
            first_name="Jade",
            middle_name="Bola",
            last_name="Smith",
            date_of_birth=date(1993, 4, 12),
            gender="Female",
            nationality="Nigerian",
            state_of_origin="Lagos",
            lga="Ikeja",
            employment_status="Employed",
            residence_country="Nigeria",
            residence_state="Lagos",
            residence_city="Ikoyi",
            residence_lga="Eti-Osa",
            residence_address="Hidden from public profile",
            length_of_stay="2 years",
            housing_status="Renting",
            household_info={"has_pets": False, "work_from_home": True},
            criminal_declaration={"convicted_of_crime": False},
        )

        response = APIClient().get(f"/api/v1/users/tenants/{tenant.id}/public-profile")

        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        self.assertEqual(payload["name"], "Jade Bola Smith")
        self.assertTrue(payload["is_verified"])
        self.assertNotIn("email", payload)
        self.assertNotIn("mobile", payload)
        self.assertEqual(payload["tenant_profile"]["first_name"], "Jade")
        self.assertIn("age", payload["tenant_profile"])
        self.assertNotIn("date_of_birth", payload["tenant_profile"])
        self.assertEqual(payload["tenant_profile"]["residence_city"], "Ikoyi")
        self.assertNotIn("residence_address", payload["tenant_profile"])
        self.assertNotIn("financial_info", payload["tenant_profile"])
        self.assertNotIn("guarantor_details", payload["tenant_profile"])


class CommunityChatMessageTests(TestCase):
    def activate_gold_subscription(self, user):
        return SubscriptionPayment.objects.create(
            user=user,
            role=user.role,
            plan_code=SubscriptionPayment.PlanCode.GOLD,
            billing_cycle=SubscriptionPayment.BillingCycle.MONTHLY,
            amount=100,
            currency="NGN",
            status=SubscriptionPayment.Status.COMPLETED,
            transaction_id=f"SUBTEST{user.id.hex[:20]}",
            payment_date=timezone.now(),
            expires_at=timezone.now() + timedelta(days=30),
        )

    def test_tenant_without_gold_subscription_cannot_list_community_chat_messages(self):
        tenant = AppUser.objects.create_user(
            email="community-no-gold-tenant@example.com",
            password="password-123",
            name="Community No Gold Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )

        client = APIClient()
        client.force_authenticate(user=tenant)
        response = client.get("/api/v1/community-chat/messages")

        self.assertEqual(response.status_code, 403, response.json())

    def test_gold_tenant_can_list_only_tenant_community_chat_messages(self):
        tenant = AppUser.objects.create_user(
            email="community-tenant@example.com",
            password="password-123",
            name="Community Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        other_tenant = AppUser.objects.create_user(
            email="community-other@example.com",
            password="password-123",
            name="Other Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        landlord = AppUser.objects.create_user(
            email="community-landlord-message@example.com",
            password="password-123",
            name="Community Landlord Message",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        self.activate_gold_subscription(tenant)
        CommunityChatMessage.objects.create(sender=other_tenant, content="Hello tenants.")
        CommunityChatMessage.objects.create(sender=landlord, content="Hello landlords.")

        client = APIClient()
        client.force_authenticate(user=tenant)
        response = client.get("/api/v1/community-chat/messages")

        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        results = payload["results"] if isinstance(payload, dict) and "results" in payload else payload
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["sender_name"], "Other Tenant")
        self.assertEqual(results[0]["content"], "Hello tenants.")

    def test_gold_landlord_can_list_only_landlord_community_chat_messages(self):
        landlord = AppUser.objects.create_user(
            email="community-landlord@example.com",
            password="password-123",
            name="Community Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        other_landlord = AppUser.objects.create_user(
            email="community-other-landlord@example.com",
            password="password-123",
            name="Other Community Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        tenant = AppUser.objects.create_user(
            email="community-hidden-tenant@example.com",
            password="password-123",
            name="Hidden Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        self.activate_gold_subscription(landlord)
        CommunityChatMessage.objects.create(sender=tenant, content="Welcome tenants.")
        CommunityChatMessage.objects.create(sender=other_landlord, content="Welcome landlords.")

        client = APIClient()
        client.force_authenticate(user=landlord)
        response = client.get("/api/v1/community-chat/messages")

        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        results = payload["results"] if isinstance(payload, dict) and "results" in payload else payload
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["content"], "Welcome landlords.")


class SupportChatMessageTests(TestCase):
    def test_tenant_can_list_only_their_support_chat_messages(self):
        tenant = AppUser.objects.create_user(
            email="support-chat-tenant@example.com",
            password="password-123",
            name="Support Chat Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        other_tenant = AppUser.objects.create_user(
            email="support-chat-other@example.com",
            password="password-123",
            name="Other Support Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        admin = AppUser.objects.create_user(
            email="support-admin@example.com",
            password="password-123",
            name="Support Admin",
            role=AppUser.Role.ADMIN,
            email_verified=True,
            is_staff=True,
        )
        SupportChatMessage.objects.create(thread_user=tenant, sender=tenant, content="I need help.")
        SupportChatMessage.objects.create(thread_user=other_tenant, sender=admin, content="Other tenant reply.")

        client = APIClient()
        client.force_authenticate(user=tenant)
        response = client.get("/api/v1/support-chat/messages")

        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        results = payload["results"] if isinstance(payload, dict) and "results" in payload else payload
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["content"], "I need help.")
        self.assertFalse(results[0]["is_support_message"])

    def test_landlord_can_list_only_their_support_chat_messages(self):
        landlord = AppUser.objects.create_user(
            email="support-chat-landlord@example.com",
            password="password-123",
            name="Support Chat Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        other_landlord = AppUser.objects.create_user(
            email="support-chat-other-landlord@example.com",
            password="password-123",
            name="Other Support Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        SupportChatMessage.objects.create(thread_user=landlord, sender=landlord, content="I need listing help.")
        SupportChatMessage.objects.create(thread_user=other_landlord, sender=other_landlord, content="Other landlord issue.")

        client = APIClient()
        client.force_authenticate(user=landlord)
        response = client.get("/api/v1/support-chat/messages")

        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        results = payload["results"] if isinstance(payload, dict) and "results" in payload else payload
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["content"], "I need listing help.")


class LandlordPublicProfileTests(TestCase):
    def test_public_landlord_profile_returns_metrics_and_reviews(self):
        landlord = AppUser.objects.create_user(
            email="public-landlord@example.com",
            password="password-123",
            name="Public Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
            mobile="08012345678",
        )
        landlord.landlord_verification_type = AppUser.LandlordVerificationType.INDIVIDUAL
        landlord.save(update_fields=["landlord_verification_type", "updated_at"])
        VerificationRequest.objects.create(
            user=landlord,
            status=VerificationRequest.Status.APPROVED,
            identity_verification_status=VerificationRequest.VerificationProgressStatus.VERIFIED,
            property_document_verification_status=VerificationRequest.VerificationProgressStatus.VERIFIED,
        )
        listing_one = Listing.objects.create(
            landlord=landlord,
            title="Public Listing One",
            description="One",
            address="1 Market Road",
            city="Lagos",
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=2500000,
        )
        Listing.objects.create(
            landlord=landlord,
            title="Public Listing Two",
            description="Two",
            address="2 Market Road",
            city="Lagos",
            property_type="Duplex",
            bedrooms=4,
            bathrooms=4,
            price_per_year=4500000,
        )
        Listing.objects.create(
            landlord=landlord,
            title="Public Listing Three",
            description="Three",
            address="3 Market Road",
            city="Lagos",
            property_type="Bungalow",
            bedrooms=3,
            bathrooms=2,
            price_per_year=3500000,
            status=Listing.Status.RENTED,
        )
        tenant = AppUser.objects.create_user(
            email="profile-tenant@example.com",
            password="password-123",
            name="Profile Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        Booking.objects.create(
            tenant=tenant,
            listing=listing_one,
            start_date=date.today() - timedelta(days=90),
            end_date=date.today() + timedelta(days=275),
            status=Booking.Status.CONFIRMED,
            total_amount=calculate_booking_total(listing_one.price_per_year),
        )
        completed_booking = Booking.objects.create(
            tenant=tenant,
            listing=listing_one,
            start_date=date.today() - timedelta(days=460),
            end_date=date.today() - timedelta(days=95),
            status=Booking.Status.COMPLETED,
            total_amount=calculate_booking_total(listing_one.price_per_year),
        )
        review = Review.objects.create(
            listing=listing_one,
            landlord=landlord,
            tenant=tenant,
            review_type=Review.ReviewType.LANDLORD,
            rating=5,
            comment="Excellent communication.",
        )
        Review.objects.create(
            listing=listing_one,
            landlord=landlord,
            tenant=tenant,
            review_type=Review.ReviewType.PROPERTY,
            rating=2,
            comment="Property needs work.",
        )
        inbound = Message.objects.create(
            sender=tenant,
            receiver=landlord,
            listing=listing_one,
            content="Is the apartment still available?",
        )
        outbound = Message.objects.create(
            sender=landlord,
            receiver=tenant,
            listing=listing_one,
            content="Yes, it is available.",
        )
        Message.objects.filter(pk=inbound.pk).update(created_at=timezone.now() - timedelta(hours=2))
        Message.objects.filter(pk=outbound.pk).update(created_at=timezone.now() - timedelta(hours=1))
        completed_booking.refresh_from_db()
        review.refresh_from_db()

        response = self.client.get(f"/api/v1/users/landlords/{landlord.id}/public-profile")

        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        self.assertEqual(payload["metrics"]["total_properties"], 3)
        self.assertEqual(payload["metrics"]["properties_rented"], 1)
        self.assertEqual(payload["metrics"]["properties_listed"], 2)
        self.assertEqual(payload["metrics"]["active_tenancies"], 1)
        self.assertEqual(payload["metrics"]["completed_tenancies"], 1)
        self.assertEqual(payload["metrics"]["reviews_count"], 1)
        self.assertFalse(payload["verification_badges"]["identity_verified"])
        self.assertIsNone(payload["verification_score"])
        self.assertEqual(payload["reviews"][0]["comment"], "Excellent communication.")

        create_active_subscription(tenant, SubscriptionPayment.PlanCode.PLATINUM)
        client = APIClient()
        client.force_authenticate(user=tenant)
        platinum_response = client.get(f"/api/v1/users/landlords/{landlord.id}/public-profile")

        self.assertEqual(platinum_response.status_code, 200, platinum_response.json())
        platinum_payload = platinum_response.json()
        self.assertTrue(platinum_payload["verification_badges"]["identity_verified"])
        self.assertTrue(platinum_payload["verification_badges"]["phone_verified"])
        self.assertTrue(platinum_payload["verification_badges"]["email_verified"])
        self.assertEqual(platinum_payload["verification_score"], 75)


class RenewalReminderCommandTests(TestCase):
    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_command_sends_renewal_reminder_once(self):
        tenant = AppUser.objects.create_user(
            email="renewal-tenant@example.com",
            password="password-123",
            name="Renewal Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        landlord = AppUser.objects.create_user(
            email="renewal-landlord@example.com",
            password="password-123",
            name="Renewal Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        listing = Listing.objects.create(
            landlord=landlord,
            title="Renewal Listing",
            description="Renewal test",
            address="14 Renewal Street",
            city="Abuja",
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=2100000,
        )
        booking = Booking.objects.create(
            tenant=tenant,
            listing=listing,
            start_date=date.today() - timedelta(days=180),
            end_date=date.today() + timedelta(days=60),
            status=Booking.Status.CONFIRMED,
            total_amount=calculate_booking_total(listing.price_per_year),
        )

        call_command("send_renewal_reminders")
        call_command("send_renewal_reminders")

        booking.refresh_from_db()
        self.assertIsNotNone(booking.renewal_reminder_sent_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("tenancy renewal reminder", mail.outbox[0].subject.lower())
