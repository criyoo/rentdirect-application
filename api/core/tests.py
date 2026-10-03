import base64
import hashlib
import hmac
import json
import re
import uuid
from io import StringIO
from pathlib import Path
from datetime import date, timedelta
from decimal import Decimal
import tempfile
from unittest.mock import call, patch

from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.test.utils import override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core import flutterwave
from core.management.commands.seed_demo_data import Command as SeedDemoDataCommand
from core.flutterwave import FlutterwaveError
from core.inspection_checklist import INSPECTION_CHECKLIST_SCHEMA
from core.models import AgentProfile, AgentReferralEarning, AppUser, Booking, BvnVerificationRecord, CacVerificationRecord, CommunityChatMessage, Document, Feedback, FeaturedPayment, InspectionRequest, Listing, ListingImage, Message, NinVerificationRecord, Payment, PaymentSettlement, PendingRegistration, PropertyInspection, Review, RoleAuditEvent, ServicePayment, SubscriptionPayment, SubscriptionPaymentMethod, SubscriptionVATPayment, SupportChatMessage, TenancyAgreement, TenantProfile, UserRole, VerificationRequest
from core.referrals import award_referral_earning, generate_unique_referral_code, resolve_referrer
from core.roles import users_with_role
from core.payment_queue import TASK_PROCESS_READY_PAYOUTS, TASK_RECONCILE_PENDING_PAYMENTS, TASK_SEND_RENEWAL_REMINDERS, enqueue_payment_task
from core.prembly_verification import (
    PremblyWebhookVerificationError,
    validate_prembly_webhook_request,
    verify_prembly_webhook_signature,
)
from core.pricing import calculate_administration_fee_vat, calculate_booking_total, calculate_deposit_amount
from core.security import hash_otp
from core.serializers import ListingSerializer, UserSerializer
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


def make_landlord_listing_ready(landlord):
    landlord.landlord_verification_type = AppUser.LandlordVerificationType.INDIVIDUAL
    landlord.landlord_verification_profile = {
        "first_name": "Demo",
        "last_name": "Landlord",
        "date_of_birth": "1990-01-01",
        "country_of_birth": "Nigeria",
        "state_of_birth": "Lagos",
        "nationality": "Nigerian",
        "state_of_origin": "Lagos",
        "lga_of_origin": "Ikeja",
        "gender": "male",
        "email": landlord.email,
        "nin": "12345678901",
        "bvn": "12345678901",
        "residential_address": "1 Demo Street, Lagos",
    }
    landlord.save(update_fields=["landlord_verification_type", "landlord_verification_profile"])
    create_active_subscription(landlord)
    return landlord


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
            test_storage = FileSystemStorage(location=media_root)

            with override_settings(
                BASE_DIR=base_dir,
                MEDIA_ROOT=media_root,
                STORAGES=TEST_FILE_STORAGES,
                HOMEPAGE_VIDEO_SOURCE_PATH="uploads/seed/video/rentdirect.mp4",
            ), patch("core.views.default_storage", test_storage):
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
            test_storage = FileSystemStorage(location=media_root)

            with override_settings(
                BASE_DIR=base_dir,
                MEDIA_ROOT=media_root,
                STORAGES=TEST_FILE_STORAGES,
                HOMEPAGE_VIDEO_SOURCE_PATH="uploads/seed/video/rentdirect.mp4",
            ), patch("core.views.default_storage", test_storage):
                response = self.client.get("/api/v1/homepage-video", HTTP_RANGE="bytes=2-5")

                self.assertEqual(response.status_code, 206)
                self.assertEqual(response["Content-Type"], "video/mp4")
                self.assertEqual(response["Content-Range"], "bytes 2-5/10")
                self.assertEqual(response["Accept-Ranges"], "bytes")
                self.assertEqual(response["Content-Length"], "4")
                self.assertEqual(b"".join(response.streaming_content), b"2345")

    def test_homepage_video_redirects_to_remote_storage_url(self):
        with override_settings(HOMEPAGE_VIDEO_STORAGE_NAME="seed/video/rentdirect.mp4"), patch("core.views.default_storage") as storage:
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

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", WEB_PUBLIC_URL="https://rentdirect.homes")
    def test_register_defers_user_creation_until_otp_verified(self):
        email = "pending-user@example.com"
        response = self.client.post(
            "/api/v1/auth/register",
            {
                "name": "Pending User",
                "email": email,
                "password": "password-123",
                "role": AppUser.Role.TENANT,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        self.assertFalse(AppUser.objects.filter(email=email).exists())
        pending = PendingRegistration.objects.get(email=email)
        self.assertNotEqual(pending.password_hash, "password-123")
        self.assertTrue(pending.password_hash.startswith(("pbkdf2_", "md5$")))

        bad_response = self.client.post(
            "/api/v1/auth/register/verify",
            {"email": email, "otp_code": "ZZZZZZ"},
            format="json",
        )
        self.assertEqual(bad_response.status_code, 400, bad_response.json())
        self.assertFalse(AppUser.objects.filter(email=email).exists())

        code_match = re.search(r"code is ([A-Z0-9]{6})", mail.outbox[-1].body)
        self.assertIsNotNone(code_match)
        ok_response = self.client.post(
            "/api/v1/auth/register/verify",
            {"email": email, "otp_code": code_match.group(1)},
            format="json",
        )
        self.assertEqual(ok_response.status_code, 200, ok_response.json())
        user = AppUser.objects.get(email=email)
        self.assertTrue(user.email_verified)
        self.assertEqual(user.role, AppUser.Role.TENANT)
        self.assertTrue(user.check_password("password-123"))
        self.assertFalse(PendingRegistration.objects.filter(email=email).exists())
        self.assertIn(settings.ACCESS_COOKIE_NAME, ok_response.cookies)
        self.assertIn(settings.REFRESH_COOKIE_NAME, ok_response.cookies)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", WEB_PUBLIC_URL="https://rentdirect.homes")
    def test_register_rejects_existing_verified_email(self):
        email = "verified-user@example.com"
        AppUser.objects.create_user(
            email=email,
            password="password-123",
            name="Verified User",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        response = self.client.post(
            "/api/v1/auth/register",
            {
                "name": "Duplicate",
                "email": email,
                "password": "password-123",
                "role": AppUser.Role.TENANT,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.json())
        self.assertFalse(PendingRegistration.objects.filter(email=email).exists())

    def test_verify_registration_rejects_expired_pending_challenge(self):
        email = "expired-pending@example.com"
        PendingRegistration.objects.create(
            email=email,
            name="Expired Pending",
            role=AppUser.Role.TENANT,
            password_hash="pbkdf2_sha256$test",
            otp_hash=hash_otp(email, "ABCDEF"),
            otp_expires_at=timezone.now() - timedelta(minutes=1),
        )
        response = self.client.post(
            "/api/v1/auth/register/verify",
            {"email": email, "otp_code": "ABCDEF"},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.json())
        self.assertFalse(AppUser.objects.filter(email=email).exists())

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

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_verify_registration_creates_active_role_membership(self):
        email = "membership-user@example.com"
        response = self.client.post(
            "/api/v1/auth/register",
            {
                "name": "Membership User",
                "email": email,
                "password": "password-123",
                "role": AppUser.Role.TENANT,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.json())
        otp_match = re.search(r"\b([A-Z0-9]{6})\b", mail.outbox[-1].body)
        self.assertIsNotNone(otp_match)

        verify_response = self.client.post(
            "/api/v1/auth/register/verify",
            {"email": email, "otp_code": otp_match.group(1)},
            format="json",
        )

        self.assertEqual(verify_response.status_code, 200, verify_response.json())
        user = AppUser.objects.get(email=email)
        membership = UserRole.objects.get(user=user, role=AppUser.Role.TENANT)
        self.assertEqual(membership.status, UserRole.Status.ACTIVE)
        self.assertEqual(verify_response.json()["role"], AppUser.Role.TENANT)
        self.assertEqual(verify_response.json()["available_roles"], [AppUser.Role.TENANT])
        self.assertTrue(
            RoleAuditEvent.objects.filter(
                user=user,
                role=AppUser.Role.TENANT,
                event=RoleAuditEvent.Event.ACTIVATED,
            ).exists()
        )

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_register_duplicate_email_directs_to_sign_in(self):
        AppUser.objects.create_user(
            email="existing-multi@example.com",
            password="password-123",
            name="Existing Multi",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        response = self.client.post(
            "/api/v1/auth/register",
            {
                "name": "Duplicate",
                "email": "existing-multi@example.com",
                "password": "password-123",
                "role": AppUser.Role.LANDLORD,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.json())
        self.assertIn("Sign in to add another role", str(response.json()))

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_verify_registration_preserves_default_role_for_existing_identity(self):
        email = "unverified-multi@example.com"
        user = AppUser.objects.create_user(
            email=email,
            password="password-123",
            name="Unverified Multi",
            role=AppUser.Role.TENANT,
            email_verified=False,
        )
        response = self.client.post(
            "/api/v1/auth/register",
            {
                "name": "Unverified Multi",
                "email": email,
                "password": "password-123",
                "role": AppUser.Role.AGENT,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.json())
        otp_match = re.search(r"\b([A-Z0-9]{6})\b", mail.outbox[-1].body)
        self.assertIsNotNone(otp_match)

        verify_response = self.client.post(
            "/api/v1/auth/register/verify",
            {"email": email, "otp_code": otp_match.group(1)},
            format="json",
        )

        self.assertEqual(verify_response.status_code, 200, verify_response.json())
        self.assertEqual(verify_response.json()["role"], AppUser.Role.AGENT)
        self.assertEqual(
            set(verify_response.json()["available_roles"]),
            {AppUser.Role.TENANT, AppUser.Role.AGENT},
        )
        user.refresh_from_db()
        self.assertEqual(user.role, AppUser.Role.TENANT)
        self.assertTrue(
            UserRole.objects.filter(
                user=user, role=AppUser.Role.TENANT, status=UserRole.Status.ACTIVE
            ).exists()
        )
        self.assertTrue(
            UserRole.objects.filter(
                user=user, role=AppUser.Role.AGENT, status=UserRole.Status.ACTIVE
            ).exists()
        )

    def test_login_selects_requested_active_role_in_memory_only(self):
        user = AppUser.objects.create_user(
            email="multi-login@example.com",
            password="password-123",
            name="Multi Login",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        UserRole.objects.create(user=user, role=AppUser.Role.TENANT)
        UserRole.objects.create(user=user, role=AppUser.Role.LANDLORD)

        response = self.client.post(
            "/api/v1/auth/login",
            {"email": user.email, "password": "password-123", "role": "landlord"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json()["role"], AppUser.Role.LANDLORD)
        self.assertEqual(
            set(response.json()["available_roles"]),
            {AppUser.Role.TENANT, AppUser.Role.LANDLORD},
        )
        user.refresh_from_db()
        self.assertEqual(user.role, AppUser.Role.TENANT)

    def test_login_activates_requested_customer_role_for_existing_identity(self):
        user = AppUser.objects.create_user(
            email="single-login@example.com",
            password="password-123",
            name="Single Login",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        UserRole.objects.create(user=user, role=AppUser.Role.TENANT)

        response = self.client.post(
            "/api/v1/auth/login",
            {"email": user.email, "password": "password-123", "role": "agent"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json()["role"], AppUser.Role.AGENT)
        self.assertTrue(response.json()["role_activated"])
        self.assertEqual(
            set(response.json()["available_roles"]),
            {AppUser.Role.TENANT, AppUser.Role.AGENT},
        )
        self.assertTrue(
            UserRole.objects.filter(
                user=user, role=AppUser.Role.AGENT, status=UserRole.Status.ACTIVE
            ).exists()
        )
        self.assertTrue(AgentProfile.objects.filter(user=user).exists())
        self.assertTrue(
            RoleAuditEvent.objects.filter(
                user=user,
                role=AppUser.Role.AGENT,
                event=RoleAuditEvent.Event.ACTIVATED,
            ).exists()
        )
        user.refresh_from_db()
        self.assertEqual(user.role, AppUser.Role.TENANT)

    def test_login_activation_prefills_agent_profile_from_verified_tenant_identity(self):
        user = AppUser.objects.create_user(
            email="verified-tenant-pio@example.com",
            password="password-123",
            name="Verified Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
            nin_number="12345678901",
            mobile="08012345678",
            tenant_verification_profile={
                "first_name": "Subomi",
                "last_name": "Career",
                "date_of_birth": "1990-05-05",
                "gender": "female",
                "nationality": "Nigerian",
                "state_of_origin": "Lagos",
                "lga": "Ikeja",
                "country_of_birth": "Nigeria",
                "nin_number": "12345678901",
                "mobile": "08012345678",
            },
        )
        VerificationRequest.objects.create(
            user=user,
            role=AppUser.Role.TENANT,
            request_type=VerificationRequest.RequestType.IDENTIFICATION,
            status=VerificationRequest.Status.APPROVED,
            identity_verification_status=VerificationRequest.VerificationProgressStatus.VERIFIED,
            verification_method=VerificationRequest.Method.AUTOMATED,
        )

        response = self.client.post(
            "/api/v1/auth/login",
            {"email": user.email, "password": "password-123", "role": "agent"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.json())
        profile = AgentProfile.objects.get(user=user)
        self.assertEqual(profile.first_name, "Subomi")
        self.assertEqual(profile.last_name, "Career")
        self.assertEqual(profile.date_of_birth.isoformat(), "1990-05-05")
        self.assertEqual(profile.nin_number, "12345678901")
        self.assertEqual(profile.lga_of_origin, "Ikeja")
        self.assertEqual(profile.mobile, "08012345678")
        self.assertEqual(profile.gender, "female")

    def test_roles_endpoint_prefills_tenant_profile_from_verified_agent_identity(self):
        user = AppUser.objects.create_user(
            email="verified-agent-tenant@example.com",
            password="password-123",
            name="Verified Agent",
            role=AppUser.Role.AGENT,
            email_verified=True,
        )
        AgentProfile.objects.create(
            user=user,
            first_name="Subomi",
            last_name="Career",
            date_of_birth="1990-05-05",
            gender="female",
            nationality="Nigerian",
            state_of_origin="Lagos",
            lga_of_origin="Ikeja",
            mobile="08012345678",
            nin_number="12345678901",
            bvn_number="10987654321",
            verification_status=AgentProfile.VerificationStatus.VERIFIED,
        )
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            "/api/v1/users/me/roles",
            {"role": AppUser.Role.TENANT},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        user.refresh_from_db()
        tenant_profile = user.tenant_verification_profile or {}
        self.assertEqual(tenant_profile.get("first_name"), "Subomi")
        self.assertEqual(tenant_profile.get("last_name"), "Career")
        self.assertEqual(tenant_profile.get("date_of_birth"), "1990-05-05")
        self.assertEqual(tenant_profile.get("nin_number"), "12345678901")
        self.assertEqual(tenant_profile.get("lga"), "Ikeja")

    def test_login_rejects_suspended_role_membership(self):
        user = AppUser.objects.create_user(
            email="suspended-login@example.com",
            password="password-123",
            name="Suspended Login",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        UserRole.objects.create(user=user, role=AppUser.Role.TENANT)
        UserRole.objects.create(
            user=user, role=AppUser.Role.AGENT, status=UserRole.Status.SUSPENDED
        )

        response = self.client.post(
            "/api/v1/auth/login",
            {"email": user.email, "password": "password-123", "role": "agent"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            UserRole.objects.get(user=user, role=AppUser.Role.AGENT).status,
            UserRole.Status.SUSPENDED,
        )

    def test_login_rejects_unknown_or_admin_role_request(self):
        user = AppUser.objects.create_user(
            email="admin-role-login@example.com",
            password="password-123",
            name="Admin Role Login",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        UserRole.objects.create(user=user, role=AppUser.Role.TENANT)

        for requested in ("admin", "superuser"):
            response = self.client.post(
                "/api/v1/auth/login",
                {"email": user.email, "password": "password-123", "role": requested},
                format="json",
            )
            self.assertEqual(response.status_code, 403)

    def test_active_role_header_selects_in_memory_role_without_persisting(self):
        user = AppUser.objects.create_user(
            email="header-role@example.com",
            password="password-123",
            name="Header Role",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        UserRole.objects.create(user=user, role=AppUser.Role.TENANT)
        UserRole.objects.create(user=user, role=AppUser.Role.LANDLORD)
        token = str(RefreshToken.for_user(user).access_token)

        response = self.client.get(
            "/api/v1/users/me",
            HTTP_AUTHORIZATION=f"Bearer {token}",
            HTTP_X_RENTDIRECT_ROLE="landlord",
        )

        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json()["role"], AppUser.Role.LANDLORD)
        user.refresh_from_db()
        self.assertEqual(user.role, AppUser.Role.TENANT)

    def test_active_role_header_rejects_suspended_membership(self):
        user = AppUser.objects.create_user(
            email="suspended-role@example.com",
            password="password-123",
            name="Suspended Role",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        UserRole.objects.create(user=user, role=AppUser.Role.TENANT)
        UserRole.objects.create(
            user=user, role=AppUser.Role.LANDLORD, status=UserRole.Status.SUSPENDED
        )
        token = str(RefreshToken.for_user(user).access_token)

        response = self.client.get(
            "/api/v1/users/me",
            HTTP_AUTHORIZATION=f"Bearer {token}",
            HTTP_X_RENTDIRECT_ROLE="landlord",
        )

        self.assertEqual(response.status_code, 403)


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
            lga="Eti-Osa",
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
        self.assertEqual(public_payload["state"], "Lagos")
        self.assertIsNone(public_payload["latitude"])
        self.assertEqual(
            public_payload["property_document_verification_status"],
            VerificationRequest.VerificationProgressStatus.VERIFIED,
        )
        self.assertNotIn("landlord_email", public_payload)

        bronze_client = self.tenant_client_with_plan(SubscriptionPayment.PlanCode.BRONZE, "bronze-visibility")
        bronze_payload = bronze_client.get(f"/api/v1/listings/{listing.id}").json()
        self.assertEqual(bronze_payload["address"], "")
        self.assertEqual(bronze_payload["city"], "")
        self.assertEqual(bronze_payload["state"], listing.state)
        self.assertEqual(
            bronze_payload["property_document_verification_status"],
            VerificationRequest.VerificationProgressStatus.VERIFIED,
        )

        silver_client = self.tenant_client_with_plan(SubscriptionPayment.PlanCode.SILVER, "silver-visibility")
        silver_payload = silver_client.get(f"/api/v1/listings/{listing.id}").json()
        self.assertEqual(silver_payload["address"], "")
        self.assertEqual(silver_payload["city"], listing.city)
        self.assertEqual(silver_payload["state"], listing.state)
        self.assertEqual(
            silver_payload["property_document_verification_status"],
            VerificationRequest.VerificationProgressStatus.VERIFIED,
        )

        gold_client = self.tenant_client_with_plan(SubscriptionPayment.PlanCode.GOLD, "gold-visibility")
        gold_payload = gold_client.get(f"/api/v1/listings/{listing.id}").json()
        self.assertEqual(gold_payload["address"], "")
        self.assertEqual(gold_payload["city"], listing.city)
        self.assertEqual(
            gold_payload["property_document_verification_status"],
            VerificationRequest.VerificationProgressStatus.VERIFIED,
        )

        platinum_client = self.tenant_client_with_plan(
            SubscriptionPayment.PlanCode.PLATINUM,
            "platinum-visibility",
        )
        platinum_payload = platinum_client.get(f"/api/v1/listings/{listing.id}").json()
        self.assertEqual(platinum_payload["address"], "")
        self.assertEqual(platinum_payload["city"], listing.city)
        self.assertEqual(
            platinum_payload["property_document_verification_status"],
            VerificationRequest.VerificationProgressStatus.VERIFIED,
        )

        paid_tenant = AppUser.objects.get(email="listing-silver-visibility@example.com")
        Booking.objects.create(
            tenant=paid_tenant,
            listing=listing,
            start_date=date.today(),
            end_date=date.today() + timedelta(days=365),
            total_amount=calculate_booking_total(listing.price_per_year),
            paid_amount=calculate_deposit_amount(listing.price_per_year),
            deposit_paid_at=timezone.now(),
        )
        paid_payload = silver_client.get(f"/api/v1/listings/{listing.id}").json()
        self.assertEqual(paid_payload["address"], listing.address)
        self.assertEqual(paid_payload["city"], listing.city)
        self.assertEqual(paid_payload["state"], listing.state)

        full_paid_tenant = AppUser.objects.create_user(
            email="listing-full-paid@example.com",
            password="password-123",
            name="Full Paid Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        Booking.objects.create(
            tenant=full_paid_tenant,
            listing=listing,
            start_date=date.today(),
            end_date=date.today() + timedelta(days=365),
            total_amount=calculate_booking_total(listing.price_per_year),
            paid_amount=calculate_booking_total(listing.price_per_year),
            full_rent_paid_at=timezone.now(),
        )
        full_paid_client = APIClient()
        full_paid_client.force_authenticate(user=full_paid_tenant)
        full_paid_payload = full_paid_client.get(f"/api/v1/listings/{listing.id}").json()
        self.assertEqual(full_paid_payload["address"], listing.address)

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

    def test_landlord_can_retrieve_another_landlords_public_listing_detail(self):
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
            description="Public property details are visible to other landlords",
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

        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json()["title"], listing.title)
        self.assertEqual(response.json()["city"], "")
        self.assertEqual(response.json()["state"], listing.state)
        self.assertEqual(response.json()["address"], "")

        create_active_subscription(outsider, SubscriptionPayment.PlanCode.SILVER)
        subscribed_response = client.get(f"/api/v1/listings/{listing.id}")
        self.assertEqual(subscribed_response.status_code, 200, subscribed_response.json())
        self.assertEqual(subscribed_response.json()["city"], listing.city)
        self.assertEqual(subscribed_response.json()["state"], listing.state)
        self.assertEqual(subscribed_response.json()["address"], "")

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
            role=landlord.role,
            status=VerificationRequest.Status.APPROVED,
            identity_verification_status=VerificationRequest.VerificationProgressStatus.VERIFIED,
            property_document_verification_status=VerificationRequest.VerificationProgressStatus.VERIFIED,
        )
        make_landlord_listing_ready(landlord)
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
                "lga": "Eti-Osa",
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
                "property_verification_method": "in_person",
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
        self.assertEqual(str(listing.deposit_amount), "750000.00")
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
            VerificationRequest.VerificationProgressStatus.UNVERIFIED,
        )
        self.assertEqual(
            listing.physical_property_status,
            VerificationRequest.VerificationProgressStatus.UNVERIFIED,
        )
        self.assertTrue(listing.property_document_submission["in_person_verification_requested"])
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

    def test_landlord_listing_requires_in_person_verification(self):
        landlord = AppUser.objects.create_user(
            email="landlord-doc-required@example.com",
            password="password-123",
            name="Document Required Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        VerificationRequest.objects.create(
            user=landlord,
            role=landlord.role,
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
                "lga": "Eti-Osa",
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
        self.assertIn("property_verification_method", response.json())

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
            role=landlord.role,
            status=VerificationRequest.Status.APPROVED,
            identity_verification_status=VerificationRequest.VerificationProgressStatus.VERIFIED,
        )
        make_landlord_listing_ready(landlord)
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
                "lga": "Eti-Osa",
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
        self.assertEqual(str(listing.deposit_amount), "540000.00")
        self.assertEqual(listing.property_documents.count(), 0)
        self.assertTrue(listing.property_document_submission["in_person_verification_requested"])
        self.assertEqual(
            listing.physical_property_status,
            VerificationRequest.VerificationProgressStatus.UNVERIFIED,
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
            role=landlord.role,
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
                "lga": "Eti-Osa",
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
            lga="Eti-Osa",
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
        self.assertEqual(payload["lga"], "")
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
            lga="Ikeja",
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

    @staticmethod
    def _lifecycle_users(suffix="lifecycle"):
        landlord = AppUser.objects.create_user(
            email=f"{suffix}-landlord@example.com",
            password="password-123",
            name="Lifecycle Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        tenant = AppUser.objects.create_user(
            email=f"{suffix}-tenant@example.com",
            password="password-123",
            name="Lifecycle Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        return landlord, tenant

    @staticmethod
    def _lifecycle_listing(landlord, **overrides):
        defaults = {
            "landlord": landlord,
            "title": "Lifecycle Listing",
            "description": "Lifecycle listing description",
            "address": "10 Lifecycle Street",
            "city": "Abuja",
            "property_type": "Apartment",
            "bedrooms": 2,
            "bathrooms": 2,
            "price_per_year": 2000000,
        }
        defaults.update(overrides)
        return Listing.objects.create(**defaults)

    def test_listing_rental_badge_reflects_deposit_and_full_payment(self):
        landlord, tenant = self._lifecycle_users("badge")
        listing = self._lifecycle_listing(landlord)
        booking = Booking.objects.create(
            tenant=tenant,
            listing=listing,
            start_date=date.today(),
            end_date=date.today() + timedelta(days=365),
            total_amount=calculate_booking_total(listing.price_per_year),
        )

        self.assertEqual(ListingSerializer(listing).data["rental_badge"], "")

        booking.paid_amount = calculate_deposit_amount(listing.price_per_year)
        booking.save(update_fields=["paid_amount", "updated_at"])
        self.assertEqual(ListingSerializer(listing).data["rental_badge"], "let_agreed")

        booking.paid_amount = booking.total_amount
        booking.save(update_fields=["paid_amount", "updated_at"])
        self.assertEqual(ListingSerializer(listing).data["rental_badge"], "rented")

        # Completed tenancies no longer keep the badge.
        booking.status = Booking.Status.COMPLETED
        booking.save(update_fields=["status", "updated_at"])
        self.assertEqual(ListingSerializer(listing).data["rental_badge"], "")

        # An expired booking also no longer keeps the badge.
        booking.status = Booking.Status.ACTIVE
        booking.end_date = date.today() - timedelta(days=1)
        booking.save(update_fields=["status", "end_date", "updated_at"])
        self.assertEqual(ListingSerializer(listing).data["rental_badge"], "")

    def test_hidden_listing_excluded_from_public_search_and_featured(self):
        landlord, _tenant = self._lifecycle_users("hidden")
        listing = self._lifecycle_listing(landlord, featured=True, is_hidden=True)

        search_response = self.client.get("/api/v1/listings/search")
        self.assertEqual(search_response.status_code, 200)
        search_payload = search_response.json()
        search_results = (
            search_payload["results"] if isinstance(search_payload, dict) and "results" in search_payload else search_payload
        )
        self.assertEqual(search_results, [])
        self.assertEqual(self.client.get("/api/v1/featured/listings").json(), [])

        public_retrieve = self.client.get(f"/api/v1/listings/{listing.id}")
        self.assertEqual(public_retrieve.status_code, 404)

    def test_owner_landlord_list_includes_own_hidden_listings(self):
        landlord, _tenant = self._lifecycle_users("ownerlist")
        hidden_listing = self._lifecycle_listing(landlord, title="Owner Hidden", is_hidden=True)
        visible_listing = self._lifecycle_listing(landlord, title="Owner Visible")

        owner_client = APIClient()
        owner_client.force_authenticate(user=landlord)
        response = owner_client.get(f"/api/v1/listings?landlord_id={landlord.id}")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        results = payload["results"] if isinstance(payload, dict) and "results" in payload else payload
        self.assertEqual(
            {item["id"] for item in results},
            {str(hidden_listing.id), str(visible_listing.id)},
        )

        outsider = AppUser.objects.create_user(
            email="ownerlist-outsider@example.com",
            password="password-123",
            name="Outsider Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        outsider_client = APIClient()
        outsider_client.force_authenticate(user=outsider)
        outsider_response = outsider_client.get(f"/api/v1/listings?landlord_id={landlord.id}")
        self.assertEqual(outsider_response.status_code, 200)
        outsider_payload = outsider_response.json()
        outsider_results = (
            outsider_payload["results"] if isinstance(outsider_payload, dict) and "results" in outsider_payload else outsider_payload
        )
        self.assertEqual(len(outsider_results), 1)
        self.assertEqual(outsider_results[0]["title"], "Owner Visible")

    def test_listing_visibility_endpoint_owner_only(self):
        landlord, _tenant = self._lifecycle_users("visibility")
        other_landlord = AppUser.objects.create_user(
            email="visibility-other@example.com",
            password="password-123",
            name="Other Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        listing = self._lifecycle_listing(landlord)

        owner_client = APIClient()
        owner_client.force_authenticate(user=landlord)
        hide_response = owner_client.post(
            f"/api/v1/listings/{listing.id}/visibility", {"is_hidden": True}, format="json"
        )
        self.assertEqual(hide_response.status_code, 200, hide_response.json())
        self.assertTrue(hide_response.json()["is_hidden"])
        listing.refresh_from_db()
        self.assertTrue(listing.is_hidden)

        search_response = self.client.get("/api/v1/listings/search")
        search_payload = search_response.json()
        search_results = (
            search_payload["results"] if isinstance(search_payload, dict) and "results" in search_payload else search_payload
        )
        self.assertEqual(search_results, [])
        self.assertEqual(self.client.get(f"/api/v1/listings/{listing.id}").status_code, 404)

        unhide_response = owner_client.post(
            f"/api/v1/listings/{listing.id}/visibility", {"is_hidden": False}, format="json"
        )
        self.assertEqual(unhide_response.status_code, 200, unhide_response.json())
        self.assertFalse(unhide_response.json()["is_hidden"])

        other_client = APIClient()
        other_client.force_authenticate(user=other_landlord)
        forbidden_response = other_client.post(
            f"/api/v1/listings/{listing.id}/visibility", {"is_hidden": True}, format="json"
        )
        self.assertEqual(forbidden_response.status_code, 403)
        listing.refresh_from_db()
        self.assertFalse(listing.is_hidden)

    def test_listing_search_and_featured_filter_by_category(self):
        landlord, _tenant = self._lifecycle_users("category")
        self._lifecycle_listing(landlord, title="Home", category=Listing.Category.RESIDENTIAL)
        self._lifecycle_listing(landlord, title="Office Block", property_type="Office", category=Listing.Category.COMMERCIAL, featured=True)

        search_response = self.client.get("/api/v1/listings/search?category=commercial")
        self.assertEqual(search_response.status_code, 200)
        search_payload = search_response.json()
        search_results = (
            search_payload["results"] if isinstance(search_payload, dict) and "results" in search_payload else search_payload
        )
        self.assertEqual(len(search_results), 1)
        self.assertEqual(search_results[0]["title"], "Office Block")

        featured_response = self.client.get("/api/v1/featured/listings?category=residential")
        self.assertEqual(featured_response.status_code, 200)
        self.assertEqual(featured_response.json(), [])
        featured_commercial = self.client.get("/api/v1/featured/listings?category=commercial")
        self.assertEqual(featured_commercial.status_code, 200)
        self.assertEqual(len(featured_commercial.json()), 1)
        self.assertEqual(featured_commercial.json()[0]["title"], "Office Block")

    def test_shortlet_listing_requires_shortlet_fields(self):
        base_payload = {
            "title": "Shortlet Flat",
            "description": "Short stay flat",
            "address": "5 Shortlet Avenue",
            "city": "Lagos",
            "state": "Lagos",
            "property_type": "Apartment",
            "bedrooms": 1,
            "bathrooms": 1,
            "price_per_year": 3000000,
            "category": "shortlet",
        }

        serializer = ListingSerializer(data=base_payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn("nightly_rate", serializer.errors)
        self.assertIn("shortlet_lister_role", serializer.errors)
        self.assertIn("minimum_stay_nights", serializer.errors)

        serializer = ListingSerializer(
            data={
                **base_payload,
                "nightly_rate": "45000.00",
                "shortlet_lister_role": "owner",
                "minimum_stay_nights": 2,
                "maximum_stay_nights": 1,
            }
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("maximum_stay_nights", serializer.errors)

        serializer = ListingSerializer(
            data={
                **base_payload,
                "nightly_rate": "45000.00",
                "shortlet_lister_role": "owner",
                "minimum_stay_nights": 2,
                "maximum_stay_nights": 14,
                "cleaning_fee": "15000.00",
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)


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
        self.assertEqual(response.json()["tenant"], get_subscription_pricing()["tenant"])
        self.assertEqual(response.json()["landlord"], get_subscription_pricing()["landlord"])
        self.assertEqual(response.json()["vat_rate_percent"], 7.5)

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
        # Freeze state lives on the active role membership, not legacy AppUser fields.
        self.assertFalse(user.account_frozen)
        membership = UserRole.objects.get(user=user, role=AppUser.Role.LANDLORD)
        self.assertTrue(membership.is_frozen)
        self.assertEqual(membership.account_freeze_fee_percentage, Decimal("10.00"))
        self.assertTrue(membership.account_frozen_until)

        client.post("/api/v1/users/me/settings/request-otp", {"purpose": "account"}, format="json")
        unfreeze_otp = re.search(r"\b([A-Z0-9]{6})\b", mail.outbox[-1].body).group(1)
        response = client.delete("/api/v1/users/me/freeze", {"otp_code": unfreeze_otp}, format="json")

        self.assertEqual(response.status_code, 200, response.json())
        user.refresh_from_db()
        membership.refresh_from_db()
        self.assertFalse(user.account_frozen)
        self.assertFalse(membership.is_frozen)
        self.assertIsNone(membership.account_frozen_until)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_tenant_can_freeze_account_and_only_manage_it_until_unfrozen(self):
        user = AppUser.objects.create_user(
            email="freeze-tenant@example.com",
            password="password-123",
            name="Freeze Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)

        client.post("/api/v1/users/me/settings/request-otp", {"purpose": "account"}, format="json")
        freeze_otp = re.search(r"\b([A-Z0-9]{6})\b", mail.outbox[-1].body).group(1)
        response = client.post(
            "/api/v1/users/me/freeze",
            {"duration_months": 6, "otp_code": freeze_otp},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.json())
        user.refresh_from_db()
        membership = UserRole.objects.get(user=user, role=AppUser.Role.TENANT)
        self.assertTrue(membership.is_frozen)
        self.assertFalse(user.account_frozen)
        self.assertEqual(membership.account_freeze_fee_percentage, Decimal("10.00"))
        self.assertEqual(client.get("/api/v1/users/me").status_code, 200)
        self.assertEqual(client.get("/api/v1/users/subscription-pricing").status_code, 403)

        client.post("/api/v1/users/me/settings/request-otp", {"purpose": "account"}, format="json")
        unfreeze_otp = re.search(r"\b([A-Z0-9]{6})\b", mail.outbox[-1].body).group(1)
        response = client.delete("/api/v1/users/me/freeze", {"otp_code": unfreeze_otp}, format="json")

        self.assertEqual(response.status_code, 200, response.json())
        user.refresh_from_db()
        membership.refresh_from_db()
        self.assertFalse(user.account_frozen)
        self.assertFalse(membership.is_frozen)

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

    def test_user_role_membership_is_unique_per_role(self):
        user = AppUser.objects.create_user(
            email="unique-membership@example.com",
            password="password-123",
            name="Unique Membership",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        UserRole.objects.create(user=user, role=AppUser.Role.TENANT)
        with self.assertRaises(IntegrityError):
            UserRole.objects.create(user=user, role=AppUser.Role.TENANT)

    def test_user_can_hold_multiple_active_roles(self):
        user = AppUser.objects.create_user(
            email="multi-membership@example.com",
            password="password-123",
            name="Multi Membership",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        UserRole.objects.create(user=user, role=AppUser.Role.TENANT)
        UserRole.objects.create(user=user, role=AppUser.Role.LANDLORD)
        self.assertEqual(
            set(user.role_memberships.values_list("role", flat=True)),
            {AppUser.Role.TENANT, AppUser.Role.LANDLORD},
        )

    def test_activate_role_endpoint_creates_membership_and_audits(self):
        user = AppUser.objects.create_user(
            email="activate-landlord@example.com",
            password="password-123",
            name="Activate Landlord",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        UserRole.objects.create(user=user, role=AppUser.Role.TENANT)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            "/api/v1/users/me/roles", {"role": "landlord"}, format="json"
        )

        self.assertEqual(response.status_code, 201, response.json())
        self.assertEqual(response.json()["role"], AppUser.Role.LANDLORD)
        membership = UserRole.objects.get(user=user, role=AppUser.Role.LANDLORD)
        self.assertEqual(membership.status, UserRole.Status.ACTIVE)
        self.assertTrue(
            RoleAuditEvent.objects.filter(
                user=user, role=AppUser.Role.LANDLORD, event=RoleAuditEvent.Event.ACTIVATED
            ).exists()
        )
        user.refresh_from_db()
        self.assertEqual(user.role, AppUser.Role.TENANT)

    def test_activate_role_is_idempotent(self):
        user = AppUser.objects.create_user(
            email="idem-activate@example.com",
            password="password-123",
            name="Idem Activate",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        UserRole.objects.create(user=user, role=AppUser.Role.TENANT)
        UserRole.objects.create(user=user, role=AppUser.Role.LANDLORD)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            "/api/v1/users/me/roles", {"role": "landlord"}, format="json"
        )

        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(UserRole.objects.filter(user=user, role=AppUser.Role.LANDLORD).count(), 1)

    def test_activate_admin_role_rejected(self):
        user = AppUser.objects.create_user(
            email="activate-admin@example.com",
            password="password-123",
            name="Activate Admin",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            "/api/v1/users/me/roles", {"role": "admin"}, format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(UserRole.objects.filter(user=user, role=AppUser.Role.ADMIN).exists())

    def test_admin_identity_cannot_activate_customer_role(self):
        admin = AppUser.objects.create_superuser(
            email="admin-identity@example.com",
            password="password-123",
        )
        client = APIClient()
        client.force_authenticate(user=admin)

        response = client.post(
            "/api/v1/users/me/roles", {"role": "tenant"}, format="json"
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(UserRole.objects.filter(user=admin).exists())

    def test_activation_rejects_self_referral(self):
        agent = AppUser.objects.create_user(
            email="self-referral@example.com",
            password="password-123",
            name="Self Referral",
            role=AppUser.Role.AGENT,
            email_verified=True,
        )
        UserRole.objects.create(user=agent, role=AppUser.Role.AGENT)
        AgentProfile.objects.create(user=agent, first_name="Self", last_name="Referral")
        client = APIClient()
        client.force_authenticate(user=agent)

        response = client.post(
            "/api/v1/users/me/roles",
            {"role": "agent", "referral_code": agent.agent_profile.referral_code},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.json())
        self.assertIn("referral_code", response.json())

    def test_active_role_switch_returns_requested_role(self):
        user = AppUser.objects.create_user(
            email="switch-role@example.com",
            password="password-123",
            name="Switch Role",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        UserRole.objects.create(user=user, role=AppUser.Role.TENANT)
        UserRole.objects.create(user=user, role=AppUser.Role.LANDLORD)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            "/api/v1/users/me/active-role", {"role": "landlord"}, format="json"
        )

        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json()["role"], AppUser.Role.LANDLORD)
        user.refresh_from_db()
        self.assertEqual(user.role, AppUser.Role.TENANT)
        self.assertTrue(
            RoleAuditEvent.objects.filter(
                user=user, role=AppUser.Role.LANDLORD, event=RoleAuditEvent.Event.SWITCHED
            ).exists()
        )

    def test_active_role_switch_rejects_unauthorized_role(self):
        user = AppUser.objects.create_user(
            email="unauthorized-switch@example.com",
            password="password-123",
            name="Unauthorized Switch",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        UserRole.objects.create(user=user, role=AppUser.Role.TENANT)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            "/api/v1/users/me/active-role", {"role": "agent"}, format="json"
        )

        self.assertIn(response.status_code, {400, 403})
        user.refresh_from_db()
        self.assertEqual(user.role, AppUser.Role.TENANT)

    def test_users_with_role_excludes_suspended_default_membership(self):
        suspended_default = AppUser.objects.create_user(
            email="suspended-default-member@example.com",
            password="password-123",
            name="Suspended Default",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        UserRole.objects.create(
            user=suspended_default,
            role=AppUser.Role.TENANT,
            status=UserRole.Status.SUSPENDED,
        )
        active_tenant = AppUser.objects.create_user(
            email="active-tenant-member@example.com",
            password="password-123",
            name="Active Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        UserRole.objects.create(user=active_tenant, role=AppUser.Role.TENANT)

        queryset = users_with_role(AppUser.objects.all(), AppUser.Role.TENANT)
        self.assertIn(active_tenant, queryset)
        self.assertNotIn(suspended_default, queryset)

    def test_activate_role_cannot_unsuspend_membership(self):
        user = AppUser.objects.create_user(
            email="suspended-activate@example.com",
            password="password-123",
            name="Suspended Activate",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        UserRole.objects.create(user=user, role=AppUser.Role.TENANT)
        UserRole.objects.create(
            user=user, role=AppUser.Role.LANDLORD, status=UserRole.Status.SUSPENDED
        )
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            "/api/v1/users/me/roles", {"role": "landlord"}, format="json"
        )

        self.assertEqual(response.status_code, 403)
        membership = UserRole.objects.get(user=user, role=AppUser.Role.LANDLORD)
        self.assertEqual(membership.status, UserRole.Status.SUSPENDED)

    def test_activate_second_role_preserves_legacy_membership(self):
        user = AppUser.objects.create_user(
            email="pre-backfill-member@example.com",
            password="password-123",
            name="Pre Backfill",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        self.assertFalse(UserRole.objects.filter(user=user).exists())
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            "/api/v1/users/me/roles", {"role": "landlord"}, format="json"
        )

        self.assertEqual(response.status_code, 201, response.json())
        memberships = UserRole.objects.filter(user=user)
        self.assertEqual(memberships.count(), 2)
        for membership in memberships:
            self.assertEqual(membership.status, UserRole.Status.ACTIVE)
        user.refresh_from_db()
        self.assertEqual(user.role, AppUser.Role.TENANT)

    def test_verification_is_scoped_to_active_role(self):
        user = AppUser.objects.create_user(
            email="scoped-verification@example.com",
            password="password-123",
            name="Scoped Verification",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        UserRole.objects.create(user=user, role=AppUser.Role.TENANT)
        UserRole.objects.create(user=user, role=AppUser.Role.LANDLORD)
        VerificationRequest.objects.create(
            user=user,
            role=AppUser.Role.TENANT,
            status=VerificationRequest.Status.APPROVED,
        )

        user.active_role = AppUser.Role.TENANT
        self.assertTrue(user.is_verified)
        user.active_role = AppUser.Role.LANDLORD
        self.assertFalse(user.is_verified)
        self.assertTrue(
            VerificationRequest.objects.filter(
                user=user, role=AppUser.Role.TENANT
            ).exists()
        )
        self.assertFalse(
            VerificationRequest.objects.filter(
                user=user, role=AppUser.Role.LANDLORD
            ).exists()
        )

    def test_account_freeze_is_scoped_to_active_role(self):
        user = AppUser.objects.create_user(
            email="scoped-freeze@example.com",
            password="password-123",
            name="Scoped Freeze",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        tenant_membership = UserRole.objects.create(user=user, role=AppUser.Role.TENANT)
        landlord_membership = UserRole.objects.create(user=user, role=AppUser.Role.LANDLORD)
        tenant_membership.account_frozen = True
        tenant_membership.account_frozen_until = timezone.now() + timedelta(days=30)
        tenant_membership.save(update_fields=["account_frozen", "account_frozen_until"])

        from core.views import user_account_freeze_active

        self.assertTrue(user_account_freeze_active(user, AppUser.Role.TENANT))
        self.assertFalse(user_account_freeze_active(user, AppUser.Role.LANDLORD))
        self.assertFalse(landlord_membership.is_frozen)


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

    def test_payment_changelist_shows_tenant_details(self):
        landlord = AppUser.objects.create_user(
            email="payment-admin-landlord@example.com",
            password="password-123",
            name="Admin Payment Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        tenant = AppUser.objects.create_user(
            email="payment-admin-tenant@example.com",
            password="password-123",
            name="Admin Payment Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        listing = Listing.objects.create(
            landlord=landlord,
            title="Admin Payment Listing",
            description="Listing used for payment admin test",
            address="9 Admin Street",
            city="Lagos",
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=1200000,
        )
        booking = Booking.objects.create(
            tenant=tenant,
            listing=listing,
            start_date=date(2026, 7, 1),
            end_date=date(2027, 7, 1),
            total_amount=calculate_booking_total(listing.price_per_year),
        )
        Payment.objects.create(
            booking=booking,
            amount=100000,
            payment_method="bank",
            status="pending",
            transaction_id="ADMIN_PAYMENT_TXN_1",
            currency="NGN",
            provider="flutterwave",
        )

        response = self.client.get("/admin/core/payment/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ADMIN_PAYMENT_TXN_1")
        self.assertContains(response, "Admin Payment Tenant")
        self.assertContains(response, "payment-admin-tenant@example.com")
        self.assertContains(response, "Tenant Name")
        self.assertContains(response, "Tenant Email")


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

    def _pay_identity_verification(self, user, purpose):
        return ServicePayment.objects.create(
            user=user,
            purpose=purpose,
            amount=Decimal("500.00"),
            status=ServicePayment.Status.COMPLETED,
            transaction_id=f"SVCTEST{uuid.uuid4().hex[:16].upper()}",
            payment_date=timezone.now(),
        )

    def test_tenant_nin_lga_is_not_validated(self):
        from core.dikript_verification import validate_nin_payload as validate_dikript_nin_payload
        from core.prembly_verification import validate_nin_payload as validate_prembly_nin_payload

        input_data = {
            "first_name": "Christian",
            "middle_name": "Odezi",
            "last_name": "Aluya",
            "date_of_birth": "1977-02-06",
            "lga": "Isoko North",
            "mobile": "09080350066",
        }
        for validate_nin_payload, payload in (
            (validate_dikript_nin_payload, self._nin_payload()),
            (validate_prembly_nin_payload, self._prembly_nin_payload(phone="09080350066")),
        ):
            for lga_value in ("Surulere", ""):
                payload["data"]["self_origin_lga"] = lga_value
                mismatches, _ = validate_nin_payload(input_data, payload["data"])
                self.assertNotIn("lga", mismatches)

    def test_bvn_lga_is_not_validated(self):
        from core.dikript_verification import validate_bvn_payload as validate_dikript_bvn_payload
        from core.prembly_verification import validate_bvn_payload as validate_prembly_bvn_payload

        input_data = {
            "first_name": "Christian",
            "middle_name": "Odezi",
            "last_name": "Aluya",
            "date_of_birth": "1977-02-06",
            "gender": "Male",
            "lga": "Completely Different LGA",
            "nationality": "Nigerian",
            "state_of_origin": "Delta",
            "mobile": "09080350066",
        }
        for validate_bvn_payload, payload in (
            (validate_dikript_bvn_payload, self._bvn_payload()),
            (validate_prembly_bvn_payload, self._prembly_bvn_payload()),
        ):
            self.assertNotIn("lga", validate_bvn_payload(input_data, payload["data"]))

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

    def _nin_bvn_identity_input(self):
        return {
            "first_name": "Christian",
            "middle_name": "Odezi",
            "last_name": "Aluya",
            "date_of_birth": "1977-02-06",
            "gender": "Male",
            "nationality": "Nigerian",
            "state_of_origin": "Delta",
            "lga": "Isoko North",
            "mobile": "09080350066",
        }

    def test_verify_nin_stores_record_after_successful_match(self):
        from core.dikript_verification import verify_nin

        cache.clear()
        self.addCleanup(cache.clear)
        with patch("core.dikript_verification.dikript_get", return_value=self._nin_payload()):
            verify_nin(self._nin_bvn_identity_input(), "12345678901")

        nin_record = NinVerificationRecord.objects.get(provider="dikript", nin="12345678901")
        self.assertEqual(nin_record.response_payload["data"]["nin"], "12345678901")

    def test_verify_nin_does_not_store_record_when_matching_fails(self):
        from core.dikript_verification import verify_nin
        from rest_framework.exceptions import ValidationError

        cache.clear()
        self.addCleanup(cache.clear)
        input_data = self._nin_bvn_identity_input()
        input_data["first_name"] = "Wrong"
        with patch("core.dikript_verification.dikript_get", return_value=self._nin_payload()):
            with self.assertRaises(ValidationError):
                verify_nin(input_data, "12345678901")

        self.assertFalse(NinVerificationRecord.objects.filter(provider="dikript", nin="12345678901").exists())

    def test_verify_nin_and_bvn_stores_records_after_successful_match(self):
        from core.dikript_verification import verify_nin_and_bvn

        cache.clear()
        self.addCleanup(cache.clear)
        with patch("core.dikript_verification.dikript_get", side_effect=[self._nin_payload(), self._bvn_payload()]):
            verify_nin_and_bvn(self._nin_bvn_identity_input(), "12345678901", "22347235093")

        nin_record = NinVerificationRecord.objects.get(provider="dikript", nin="12345678901")
        bvn_record = BvnVerificationRecord.objects.get(provider="dikript", bvn="22347235093")
        self.assertEqual(nin_record.response_payload["data"]["nin"], "12345678901")
        self.assertEqual(bvn_record.response_payload["data"]["bvn"], "22347235093")

    def test_verify_nin_and_bvn_does_not_store_records_when_matching_fails(self):
        from core.dikript_verification import verify_nin_and_bvn
        from rest_framework.exceptions import ValidationError

        cache.clear()
        self.addCleanup(cache.clear)
        input_data = self._nin_bvn_identity_input()
        input_data["first_name"] = "Wrong"
        input_data["last_name"] = "Person"
        with patch("core.dikript_verification.dikript_get", side_effect=[self._nin_payload(), self._bvn_payload()]):
            with self.assertRaises(ValidationError):
                verify_nin_and_bvn(input_data, "12345678901", "22347235093")

        self.assertFalse(NinVerificationRecord.objects.filter(provider="dikript", nin="12345678901").exists())
        self.assertFalse(BvnVerificationRecord.objects.filter(provider="dikript", bvn="22347235093").exists())

    def test_prembly_verify_nin_and_bvn_does_not_store_records_when_matching_fails(self):
        from core.prembly_verification import verify_nin_and_bvn
        from rest_framework.exceptions import ValidationError

        cache.clear()
        self.addCleanup(cache.clear)
        input_data = self._nin_bvn_identity_input()
        input_data["first_name"] = "Wrong"
        input_data["last_name"] = "Person"
        with patch("core.prembly_verification.prembly_post", side_effect=[self._prembly_nin_payload(phone="09080350066"), self._prembly_bvn_payload()]):
            with self.assertRaises(ValidationError):
                verify_nin_and_bvn(input_data, "91231161558", "22347235093")

        self.assertFalse(NinVerificationRecord.objects.filter(provider="prembly", nin="91231161558").exists())
        self.assertFalse(BvnVerificationRecord.objects.filter(provider="prembly", bvn="22347235093").exists())

    def _dikript_joy_nin_payload(self):
        return {
            "status": True,
            "message": "Successful",
            "transactionRef": "NIN-REF",
            "data": {
                "firstName": "JOY",
                "middleName": "CHINWE",
                "surname": "TAIWO",
                "birthDate": "10-04-1988",
                "gender": "f",
                "telephoneNo": "08091234567",
                "nin": "80090664009",
                "birthcountry": "nigeria",
                "selfOriginLga": "",
                "selfOriginState": "",
                "selfOriginPlace": "",
            },
        }

    def _dikript_joy_bvn_payload(self):
        return {
            "status": True,
            "message": "Successful",
            "transactionRef": "BVN-REF",
            "data": {
                "bvn": "22425350362",
                "firstName": "JOY",
                "middleName": "CHINWE",
                "lastName": "TAIWO",
                "dateOfBirth": "10-Apr-1988",
                "phoneNumber1": "08095237164",
                "gender": "Female",
                "stateOfOrigin": "Lagos State",
                "lgaOfOrigin": "Surulere, Lagos State",
                "nationality": "Nigeria",
            },
        }

    def _prembly_joy_nin_payload(self):
        return {
            "status": True,
            "response_code": "00",
            "message": "National Identity Number (NIN) verification successful",
            "data": {
                "firstname": "JOY",
                "middlename": "CHINWE",
                "surname": "TAIWO",
                "birthdate": "10-04-1988",
                "gender": "f",
                "telephoneno": "08091234567",
                "nin": "80090664009",
                "birthcountry": "nigeria",
                "birthlga": "",
                "self_origin_lga": "",
                "self_origin_place": "",
            },
            "verification_status": "verified",
        }

    def _prembly_joy_bvn_payload(self):
        return {
            "status": True,
            "response_code": "00",
            "message": "Bank Verification Number (BVN) verification successful",
            "data": {
                "bvn": "22425350362",
                "firstName": "JOY",
                "middleName": "CHINWE",
                "lastName": "TAIWO",
                "dateOfBirth": "10-Apr-1988",
                "phoneNumber1": "08095237164",
                "gender": "Female",
                "stateOfOrigin": "Lagos State",
                "lgaOfOrigin": "Surulere, Lagos State",
                "nationality": "Nigeria",
            },
            "verification_status": "verified",
        }

    def _joy_identity_input(self):
        return {
            "first_name": "Joy",
            "middle_name": "",
            "last_name": "Taiwo",
            "date_of_birth": "1988-04-10",
            "gender": "female",
            "nationality": "Nigerian",
            "state_of_origin": "Lagos",
            "lga": "Surulere",
            "country_of_birth": "Nigeria",
            "mobile": "+2348091234567",
        }

    def _verify_joy(self, provider, input_data):
        if provider == "dikript":
            from core.dikript_verification import verify_nin_and_bvn

            with patch(
                "core.dikript_verification.dikript_lookup",
                side_effect=[self._dikript_joy_nin_payload(), self._dikript_joy_bvn_payload()],
            ):
                return verify_nin_and_bvn(dict(input_data), "80090664009", "22425350362")
        from core.prembly_verification import verify_nin_and_bvn

        with patch(
            "core.prembly_verification.prembly_post",
            side_effect=[self._prembly_joy_nin_payload(), self._prembly_joy_bvn_payload()],
        ):
            return verify_nin_and_bvn(dict(input_data), "80090664009", "22425350362")

    def test_verify_nin_and_bvn_full_match_returns_excellent_badge(self):
        cache.clear()
        self.addCleanup(cache.clear)
        for provider in ("dikript", "prembly"):
            nin_payload, bvn_payload = self._verify_joy(provider, self._joy_identity_input())
            self.assertEqual(nin_payload["verification_badge"], "Verification: Excellent", provider)
            self.assertEqual(bvn_payload["verification_badge"], "Verification: Excellent", provider)

    def test_verify_nin_and_bvn_mandatory_field_matches_on_either_record(self):
        cache.clear()
        self.addCleanup(cache.clear)
        # Phone only exists on the BVN record -> still passes mandatory checks.
        input_data = {**self._joy_identity_input(), "mobile": "08095237164"}
        for provider in ("dikript", "prembly"):
            nin_payload, _ = self._verify_joy(provider, input_data)
            self.assertEqual(nin_payload["verification_badge"], "Verification: Excellent", provider)

    def test_verify_nin_and_bvn_fails_when_mandatory_field_mismatches_both(self):
        from rest_framework.exceptions import ValidationError

        cache.clear()
        self.addCleanup(cache.clear)
        for field, value in (
            ("first_name", "Janet"),
            ("last_name", "Okafor"),
            ("gender", "male"),
            ("mobile", "08011112222"),
        ):
            input_data = {**self._joy_identity_input(), field: value}
            for provider in ("dikript", "prembly"):
                with self.assertRaises(ValidationError, msg=f"{provider} {field}"):
                    self._verify_joy(provider, input_data)

    def test_verify_nin_and_bvn_optional_mismatch_passes_with_good_badge(self):
        cache.clear()
        self.addCleanup(cache.clear)
        for field, value in (
            ("middle_name", "Chiamaka"),
            ("nationality", "Ghanaian"),
            ("lga", "Abeokuta"),
            ("state_of_origin", "Ogun"),
            ("country_of_birth", "Ghana"),
        ):
            input_data = {**self._joy_identity_input(), field: value}
            for provider in ("dikript", "prembly"):
                nin_payload, _ = self._verify_joy(provider, input_data)
                self.assertEqual(nin_payload["verification_badge"], "Verification: Good", f"{provider} {field}")

    def test_verify_nin_and_bvn_normalizes_phone_gender_dates_and_case(self):
        cache.clear()
        self.addCleanup(cache.clear)
        input_data = {
            **self._joy_identity_input(),
            "first_name": "joy",
            "last_name": "TAIWO",
            "date_of_birth": "10/04/1988",
            "gender": "F",
            "mobile": "  +234 809 123 4567 ",
        }
        for provider in ("dikript", "prembly"):
            nin_payload, _ = self._verify_joy(provider, input_data)
            self.assertEqual(nin_payload["verification_badge"], "Verification: Excellent", provider)

        for mobile in ("2348091234567", "08091234567", "+2348091234567"):
            input_data = {**self._joy_identity_input(), "mobile": mobile}
            for provider in ("dikript", "prembly"):
                self._verify_joy(provider, input_data)  # passes only without ValidationError

    def test_verify_nin_and_bvn_rejects_submitted_number_not_on_record(self):
        from rest_framework.exceptions import ValidationError

        cache.clear()
        self.addCleanup(cache.clear)
        from core.dikript_verification import verify_nin_and_bvn as dikript_verify

        with patch(
            "core.dikript_verification.dikript_lookup",
            side_effect=[self._dikript_joy_nin_payload(), self._dikript_joy_bvn_payload()],
        ):
            with self.assertRaises(ValidationError) as error:
                dikript_verify(self._joy_identity_input(), "80090664000", "22425350362")
        self.assertIn("nin_number", error.exception.detail)

        from core.prembly_verification import verify_nin_and_bvn as prembly_verify

        with patch(
            "core.prembly_verification.prembly_post",
            side_effect=[self._prembly_joy_nin_payload(), self._prembly_joy_bvn_payload()],
        ):
            with self.assertRaises(ValidationError) as error:
                prembly_verify(self._joy_identity_input(), "80090664009", "22425350360")
        self.assertIn("bvn_number", error.exception.detail)

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
        self._pay_identity_verification(user, ServicePayment.Purpose.TENANT_VERIFICATION)
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
        self.assertEqual(dikript_lookup_mock.call_count, 2)
        request = VerificationRequest.objects.get(user=user, role=user.role)
        profile = TenantProfile.objects.get(user=user)
        self.assertEqual(profile.status, TenantProfile.Status.APPROVED)
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
        self._pay_identity_verification(user, ServicePayment.Purpose.TENANT_VERIFICATION)
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
        request = VerificationRequest.objects.get(user=user, role=user.role)
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
        self._pay_identity_verification(user, ServicePayment.Purpose.TENANT_VERIFICATION)
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
        self._pay_identity_verification(user, ServicePayment.Purpose.TENANT_VERIFICATION)
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
        self.assertEqual(prembly_lookup_mock.call_count, 2)
        self.assertEqual(prembly_lookup_mock.call_args_list[0].kwargs["body"], {"number_nin": "91231161558"})

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
        self._pay_identity_verification(user, ServicePayment.Purpose.TENANT_VERIFICATION)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            "/api/v1/tenant-verification-requests/submit",
            {"document_ids": [], "request_type": "identification"},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        request = VerificationRequest.objects.get(user=user, role=user.role)
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
            role=user.role,
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
    def test_tenant_profile_submission_validates_bvn_fields(self, dikript_lookup_mock):
        dikript_lookup_mock.side_effect = [self._nin_payload(), self._bvn_payload()]
        user = AppUser.objects.create_user(
            email="tenant-dikript-fail@example.com",
            password="password-123",
            name="Tenant Dikript Fail",
            role=AppUser.Role.TENANT,
            email_verified=True,
            mobile="09080350066",
        )
        self._pay_identity_verification(user, ServicePayment.Purpose.TENANT_VERIFICATION)
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
                "gender": "Female",
                "nationality": "Nigerian",
                "state_of_origin": "Wrong State",
                "lga": "Isoko North",
                "employment_status": "Employed",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.json())
        self.assertIn("gender", response.json())
        self.assertEqual(dikript_lookup_mock.call_count, 2)

    @patch("core.dikript_verification.dikript_lookup")
    def test_tenant_profile_submission_charges_fee_after_verification(self, dikript_lookup_mock):
        dikript_lookup_mock.side_effect = [self._nin_payload(), self._bvn_payload()]
        user = AppUser.objects.create_user(
            email="tenant-unpaid@example.com",
            password="password-123",
            name="Tenant Unpaid",
            role=AppUser.Role.TENANT,
            email_verified=True,
            mobile="09080350066",
        )
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            "/api/v1/users/me/tenant-profile",
            self._complete_tenant_profile_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        payment_payload = response.json()["verification_payment"]
        self.assertEqual(payment_payload["amount"], "500.00")
        profile = TenantProfile.objects.get(user=user)
        self.assertEqual(profile.status, TenantProfile.Status.PENDING)
        verification = VerificationRequest.objects.get(user=user, role=AppUser.Role.TENANT)
        self.assertEqual(
            verification.identity_verification_status,
            VerificationRequest.VerificationProgressStatus.AWAITING_PAYMENT,
        )
        user.refresh_from_db()
        self.assertEqual(user.tenant_verification_attempts, 1)
        self.assertFalse(user.is_verified_for_role(AppUser.Role.TENANT))

        from core.views import complete_service_payment

        payment = ServicePayment.objects.get(id=payment_payload["id"])
        complete_service_payment(payment)
        verification.refresh_from_db()
        profile.refresh_from_db()
        self.assertEqual(
            verification.identity_verification_status,
            VerificationRequest.VerificationProgressStatus.VERIFIED,
        )
        self.assertEqual(profile.status, TenantProfile.Status.APPROVED)
        self.assertTrue(user.is_verified_for_role(AppUser.Role.TENANT))

    @patch("core.dikript_verification.dikript_lookup")
    def test_tenant_identity_extra_attempts_add_fee(self, dikript_lookup_mock):
        dikript_lookup_mock.side_effect = lambda **kwargs: (
            self._nin_payload() if kwargs["verification_type"] == "nin" else self._bvn_payload()
        )
        user = AppUser.objects.create_user(
            email="tenant-attempts@example.com",
            password="password-123",
            name="Tenant Attempts",
            role=AppUser.Role.TENANT,
            email_verified=True,
            mobile="09080350066",
        )
        client = APIClient()
        client.force_authenticate(user=user)
        payload = self._complete_tenant_profile_payload()
        payload["gender"] = "Female"

        for _ in range(3):
            response = client.post("/api/v1/users/me/tenant-profile", payload, format="json")
            self.assertEqual(response.status_code, 400, response.json())
            self.assertIn("gender", response.json())

        user.refresh_from_db()
        self.assertEqual(user.tenant_verification_attempts, 3)
        self.assertEqual(dikript_lookup_mock.call_count, 6)

        payload["gender"] = "Male"
        response = client.post("/api/v1/users/me/tenant-profile", payload, format="json")
        self.assertIn(response.status_code, (200, 201), response.json())
        user.refresh_from_db()
        self.assertEqual(user.tenant_verification_attempts, 4)
        self.assertEqual(dikript_lookup_mock.call_count, 8)

        payment = ServicePayment.objects.get(
            user=user, purpose=ServicePayment.Purpose.TENANT_VERIFICATION
        )
        self.assertEqual(payment.amount, Decimal("600.00"))
        verification = VerificationRequest.objects.get(user=user, role=AppUser.Role.TENANT)
        self.assertEqual(
            verification.identity_verification_status,
            VerificationRequest.VerificationProgressStatus.AWAITING_PAYMENT,
        )

    @patch("core.dikript_verification.dikript_lookup")
    def test_landlord_identification_charges_fee_after_verification(self, dikript_lookup_mock):
        dikript_lookup_mock.side_effect = [self._nin_payload(), self._bvn_payload()]
        user = AppUser.objects.create_user(
            email="landlord-unpaid@example.com",
            password="password-123",
            name="Landlord Unpaid",
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
        self.assertEqual(response.json()["verification_payment"]["amount"], "500.00")
        verification = VerificationRequest.objects.get(user=user, role=AppUser.Role.LANDLORD)
        self.assertEqual(
            verification.identity_verification_status,
            VerificationRequest.VerificationProgressStatus.AWAITING_PAYMENT,
        )

    def _verified_credential_holder(self, email="verified-holder@example.com"):
        holder = AppUser.objects.create_user(
            email=email,
            password="password-123",
            name="Verified Holder",
            role=AppUser.Role.TENANT,
            email_verified=True,
            nin_number="12345678901",
            bvn_number="22347235093",
        )
        VerificationRequest.objects.create(
            user=holder,
            role=AppUser.Role.TENANT,
            request_type=VerificationRequest.RequestType.IDENTIFICATION,
            status=VerificationRequest.Status.APPROVED,
            identity_verification_status=VerificationRequest.VerificationProgressStatus.VERIFIED,
            verification_method=VerificationRequest.Method.AUTOMATED,
        )
        return holder

    @patch("core.dikript_verification.dikript_lookup")
    def test_tenant_verification_rejects_credentials_linked_to_another_account(self, dikript_lookup_mock):
        self._verified_credential_holder()
        user = AppUser.objects.create_user(
            email="tenant-duplicate-credentials@example.com",
            password="password-123",
            name="Tenant Duplicate",
            role=AppUser.Role.TENANT,
            email_verified=True,
            mobile="09080350066",
        )
        self._pay_identity_verification(user, ServicePayment.Purpose.TENANT_VERIFICATION)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            "/api/v1/users/me/tenant-profile",
            self._complete_tenant_profile_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.json())
        self.assertIn("nin_number", response.json())
        self.assertFalse(dikript_lookup_mock.called)
        user.refresh_from_db()
        self.assertEqual(user.tenant_verification_attempts, 0)
        self.assertEqual(TenantProfile.objects.get(user=user).status, TenantProfile.Status.REJECTED)

    @patch("core.dikript_verification.dikript_lookup")
    def test_unverified_account_cannot_squat_on_credentials(self, dikript_lookup_mock):
        # A stored NIN/BVN without a completed verification must not block the
        # real owner from verifying under their own account.
        AppUser.objects.create_user(
            email="squatter@example.com",
            password="password-123",
            name="Squatter",
            role=AppUser.Role.TENANT,
            email_verified=True,
            nin_number="12345678901",
            bvn_number="22347235093",
        )
        dikript_lookup_mock.side_effect = [self._nin_payload(), self._bvn_payload()]
        user = AppUser.objects.create_user(
            email="tenant-real-owner@example.com",
            password="password-123",
            name="Real Owner",
            role=AppUser.Role.TENANT,
            email_verified=True,
            mobile="09080350066",
        )
        self._pay_identity_verification(user, ServicePayment.Purpose.TENANT_VERIFICATION)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            "/api/v1/users/me/tenant-profile",
            self._complete_tenant_profile_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        self.assertEqual(dikript_lookup_mock.call_count, 2)

    @patch("core.dikript_verification.dikript_lookup")
    def test_landlord_verification_rejects_credentials_linked_to_another_account(self, dikript_lookup_mock):
        self._verified_credential_holder()
        user = AppUser.objects.create_user(
            email="landlord-duplicate-credentials@example.com",
            password="password-123",
            name="Landlord Duplicate",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
            mobile="09080350066",
            landlord_verification_type=AppUser.LandlordVerificationType.INDIVIDUAL,
            landlord_verification_profile={
                "first_name": "Christian",
                "last_name": "Aluya",
                "date_of_birth": "1977-02-06",
                "nin": "12345678901",
                "bvn": "22347235093",
            },
        )
        self._pay_identity_verification(user, ServicePayment.Purpose.LANDLORD_VERIFICATION)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            "/api/v1/landlord-verification-requests/submit",
            {"document_ids": [], "request_type": "identification"},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.json())
        self.assertIn("nin_number", response.json())
        self.assertFalse(dikript_lookup_mock.called)

    @patch("core.dikript_verification.dikript_lookup")
    def test_verified_landlord_activating_tenant_awaits_payment(self, dikript_lookup_mock):
        user = AppUser.objects.create_user(
            email="landlord-turned-tenant@example.com",
            password="password-123",
            name="Landlord Turned Tenant",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
            mobile="09080350066",
            nin_number="12345678901",
            bvn_number="22347235093",
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
        VerificationRequest.objects.create(
            user=user,
            role=AppUser.Role.LANDLORD,
            request_type=VerificationRequest.RequestType.IDENTIFICATION,
            status=VerificationRequest.Status.APPROVED,
            identity_verification_status=VerificationRequest.VerificationProgressStatus.VERIFIED,
            verification_method=VerificationRequest.Method.AUTOMATED,
        )
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post("/api/v1/users/me/roles", {"role": "tenant"}, format="json")

        self.assertIn(response.status_code, (200, 201), response.json())
        self.assertFalse(dikript_lookup_mock.called)
        user.refresh_from_db()
        self.assertFalse(user.is_verified_for_role(AppUser.Role.TENANT))
        self.assertEqual(user.tenant_verification_attempts, 0)
        verification = VerificationRequest.objects.get(user=user, role=AppUser.Role.TENANT)
        self.assertEqual(
            verification.identity_verification_status,
            VerificationRequest.VerificationProgressStatus.AWAITING_PAYMENT,
        )
        payment = ServicePayment.objects.get(
            user=user, purpose=ServicePayment.Purpose.TENANT_VERIFICATION
        )
        self.assertEqual(payment.amount, Decimal("500.00"))
        self.assertEqual(
            user.tenant_verification_profile.get("nin_number"), "12345678901"
        )
        self.assertEqual(
            user.tenant_verification_profile.get("bvn_number"), "22347235093"
        )

    def test_service_payment_request_creates_tenant_verification_payment(self):
        user = AppUser.objects.create_user(
            email="tenant-pay-request@example.com",
            password="password-123",
            name="Tenant Pay Request",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)

        unpaid = client.post(
            "/api/v1/service-payments/request",
            {"purpose": "tenant_verification"},
            format="json",
        )
        self.assertEqual(unpaid.status_code, 400, unpaid.json())

        VerificationRequest.objects.create(
            user=user,
            role=AppUser.Role.TENANT,
            request_type=VerificationRequest.RequestType.IDENTIFICATION,
            status=VerificationRequest.Status.PENDING,
            identity_verification_status=VerificationRequest.VerificationProgressStatus.AWAITING_PAYMENT,
            verification_method=VerificationRequest.Method.AUTOMATED,
        )

        response = client.post(
            "/api/v1/service-payments/request",
            {"purpose": "tenant_verification"},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        self.assertEqual(response.json()["amount"], "500.00")
        self.assertEqual(response.json()["purpose"], "tenant_verification")
        self.assertEqual(response.json()["return_path"], "/verify")

        repeat = client.post(
            "/api/v1/service-payments/request",
            {"purpose": "tenant_verification"},
            format="json",
        )
        self.assertEqual(repeat.status_code, 200)
        self.assertEqual(repeat.json()["id"], response.json()["id"])

    def test_service_payment_request_tenant_rejects_other_roles(self):
        user = AppUser.objects.create_user(
            email="landlord-pay-request@example.com",
            password="password-123",
            name="Landlord Pay Request",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            "/api/v1/service-payments/request",
            {"purpose": "tenant_verification"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

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
        self._pay_identity_verification(user, ServicePayment.Purpose.LANDLORD_VERIFICATION)
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
        request = VerificationRequest.objects.get(user=user, role=user.role)
        self.assertEqual(response.json()["status"], VerificationRequest.Status.APPROVED)
        self.assertEqual(request.status, VerificationRequest.Status.APPROVED)
        self.assertEqual(request.identity_verification_status, VerificationRequest.VerificationProgressStatus.VERIFIED)
        self.assertEqual(request.verification_method, VerificationRequest.Method.AUTOMATED)
        self.assertIsNotNone(request.reviewed_at)

    @patch("core.views.verify_nin_and_bvn")
    def test_landlord_submit_reuses_agent_verified_identity(self, verify_mock):
        user = AppUser.objects.create_user(
            email="landlord-reuse-agent@example.com",
            password="password-123",
            name="Landlord Reuse Agent",
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
                "email": "landlord-reuse-agent@example.com",
                "nin": "12345678901",
                "bvn": "22347235093",
                "residential_address": "10 Marina Road",
            },
        )
        AgentProfile.objects.create(
            user=user,
            first_name="Christian",
            middle_name="Odezi",
            last_name="Aluya",
            date_of_birth="1977-02-06",
            gender="Male",
            nationality="Nigerian",
            state_of_origin="Delta",
            lga_of_origin="Isoko North",
            mobile="09080350066",
            nin_number="12345678901",
            bvn_number="22347235093",
            verification_status=AgentProfile.VerificationStatus.VERIFIED,
        )
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            "/api/v1/landlord-verification-requests/submit",
            {"document_ids": [], "request_type": "identification"},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        self.assertFalse(verify_mock.called)
        request = VerificationRequest.objects.get(user=user, role=user.role)
        self.assertEqual(request.status, VerificationRequest.Status.PENDING)
        self.assertEqual(
            request.identity_verification_status,
            VerificationRequest.VerificationProgressStatus.AWAITING_PAYMENT,
        )
        self.assertTrue(
            ServicePayment.objects.filter(
                user=user, purpose=ServicePayment.Purpose.LANDLORD_VERIFICATION
            ).exists()
        )
        user.refresh_from_db()
        self.assertEqual(user.nin_number, "12345678901")
        self.assertEqual(user.bvn_number, "22347235093")

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
        self._pay_identity_verification(user, ServicePayment.Purpose.LANDLORD_VERIFICATION)
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
        self._pay_identity_verification(user, ServicePayment.Purpose.LANDLORD_VERIFICATION)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            "/api/v1/landlord-verification-requests/submit",
            {"document_ids": [], "request_type": "identification"},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        request = VerificationRequest.objects.get(user=user, role=user.role)
        self.assertEqual(request.identity_verification_status, VerificationRequest.VerificationProgressStatus.VERIFIED)

    @patch("core.dikript_verification.dikript_lookup")
    def test_landlord_identification_fails_when_phone_matches_neither_nin_nor_bvn(self, dikript_lookup_mock):
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
        self._pay_identity_verification(user, ServicePayment.Purpose.LANDLORD_VERIFICATION)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            "/api/v1/landlord-verification-requests/submit",
            {"document_ids": [], "request_type": "identification"},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.json())
        self.assertIn("mobile", response.json())

    @patch("core.dikript_verification.dikript_lookup")
    def test_landlord_identification_fails_when_phone_is_missing(self, dikript_lookup_mock):
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
        self._pay_identity_verification(user, ServicePayment.Purpose.LANDLORD_VERIFICATION)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            "/api/v1/landlord-verification-requests/submit",
            {"document_ids": [], "request_type": "identification"},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.json())
        self.assertIn("mobile", response.json())
        self.assertEqual(dikript_lookup_mock.call_count, 2)

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
        self._pay_identity_verification(user, ServicePayment.Purpose.LANDLORD_VERIFICATION)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            "/api/v1/landlord-verification-requests/submit",
            {"document_ids": [], "request_type": "identification"},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        request = VerificationRequest.objects.get(user=user, role=user.role)
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
        self._pay_identity_verification(user, ServicePayment.Purpose.LANDLORD_VERIFICATION)
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
            role=user.role,
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
            role=user.role,
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
            role=user.role,
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

    @override_settings(PAYMENT_QUEUE_BACKEND="sync")
    @patch("core.views.reconcile_pending_customer_payments")
    def test_sync_queue_backend_runs_pending_payment_reconciliation_inline(self, reconcile_mock):
        reconcile_mock.return_value = {"checked": 1, "completed": 1, "pending": 0, "failed": 0}

        result = enqueue_payment_task(TASK_RECONCILE_PENDING_PAYMENTS, {"source": "test"})

        self.assertEqual(result, {"status": "ok", "result": reconcile_mock.return_value})
        reconcile_mock.assert_called_once_with()

    @override_settings(PAYMENT_QUEUE_BACKEND="sync")
    @patch("core.payment_queue.call_command")
    def test_sync_queue_backend_runs_renewal_reminder_task_inline(self, call_command_mock):
        result = enqueue_payment_task(TASK_SEND_RENEWAL_REMINDERS, {"source": "test"})

        self.assertEqual(result, {"status": "ok"})
        call_command_mock.assert_called_once_with("send_renewal_reminders")

    @patch("core.views.query_transaction")
    def test_reconciliation_completes_pending_subscription_payment(self, query_transaction_mock):
        from core.views import reconcile_pending_customer_payments

        tenant = AppUser.objects.create_user(
            email="payment-reconciliation@example.com",
            password="password-123",
            name="Payment Reconciliation",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        payment = SubscriptionPayment.objects.create(
            user=tenant,
            role=tenant.role,
            plan_code=SubscriptionPayment.PlanCode.SILVER,
            billing_cycle=SubscriptionPayment.BillingCycle.MONTHLY,
            amount="100.00",
            currency="NGN",
            status=SubscriptionPayment.Status.PENDING,
            provider="flutterwave",
            transaction_id="RECONCILE_SUBSCRIPTION_001",
            expires_at=timezone.now(),
        )
        query_transaction_mock.return_value = {
            "status": "success",
            "data": {
                "id": "reconciled-charge-001",
                "tx_ref": payment.transaction_id,
                "status": "successful",
                "amount": "100.00",
                "currency": "NGN",
                "customer": {"email": tenant.email},
            },
        }

        result = reconcile_pending_customer_payments()

        payment.refresh_from_db()
        self.assertEqual(result, {"checked": 1, "completed": 1, "pending": 0, "failed": 0})
        self.assertEqual(payment.status, SubscriptionPayment.Status.COMPLETED)
        self.assertEqual(payment.provider_charge_id, "reconciled-charge-001")

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
    def test_payout_bank_code_resolves_full_nigerian_bank_list(self):
        self.assertEqual(flutterwave.resolve_nigerian_payout_bank_code("Fairmoney Microfinance Bank"), "51318")
        self.assertEqual(flutterwave.resolve_nigerian_payout_bank_code("Kuda Bank"), "50211")
        self.assertEqual(flutterwave.resolve_nigerian_payout_bank_code("OPay Digital Services Limited (OPay)"), "100004")
        self.assertEqual(flutterwave.resolve_nigerian_payout_bank_code("Moniepoint MFB"), "50515")
        self.assertEqual(flutterwave.resolve_nigerian_payout_bank_code("Access Bank"), "044")
        self.assertEqual(flutterwave.resolve_nigerian_payout_bank_code("Zenith Bank Plc"), "057")
        self.assertEqual(
            flutterwave.nigerian_payout_bank_code_candidates("OPay Digital Services Limited (OPay)"),
            ["100004", "999992"],
        )

    @override_settings(
        FLUTTERWAVE_API_VERSION="v4",
        FLUTTERWAVE_CLIENT_ID="test-client-id",
        FLUTTERWAVE_CLIENT_SECRET="test-client-secret",
        FLUTTERWAVE_API_BASE_URL="https://developersandbox-api.flutterwave.com",
    )
    @patch("core.flutterwave.v4._request_json_v4")
    def test_update_charge_submits_authorization(self, request_mock):
        request_mock.return_value = {"status": "success", "data": {"id": "chg_123", "status": "succeeded"}}

        response = flutterwave.update_charge(
            charge_id="chg_123",
            authorization={"type": "pin", "pin": {"encrypted_pin": "cipher", "nonce": "nonce"}},
            idempotency_key="authorize-123",
        )

        self.assertEqual(response["data"]["status"], "succeeded")
        request_mock.assert_called_once_with(
            method="PUT",
            path="/charges/chg_123",
            payload={"authorization": {"type": "pin", "pin": {"encrypted_pin": "cipher", "nonce": "nonce"}}},
            idempotency_key="authorize-123",
        )

    @patch("core.flutterwave.v3.create_collection_subaccount")
    def test_collection_subaccount_retries_mobile_bank_code_alias(self, create_subaccount_mock):
        create_subaccount_mock.side_effect = [
            flutterwave.FlutterwaveError("Sorry we couldn't verify your account number."),
            {"status": "success", "data": {"id": "RS_OPAY_SUBACCOUNT"}},
        ]

        subaccount_id = flutterwave.get_or_create_collection_subaccount_id(
            bank_code="100004",
            account_number="9041487757",
            business_name="RentDirect Operations",
            business_mobile="08000000000",
        )

        self.assertEqual(subaccount_id, "RS_OPAY_SUBACCOUNT")
        self.assertEqual(
            [call.kwargs["bank_code"] for call in create_subaccount_mock.call_args_list],
            ["100004", "999992"],
        )

    @patch("core.flutterwave.v4._get_v4_access_token", return_value="test-access-token")
    def test_flutterwave_v4_get_headers_include_trace_id_without_idempotency_header(self, _get_token_mock):
        headers = flutterwave._build_v4_headers(
            method="GET",
            idempotency_key="recipient-lookup-trace",
        )

        self.assertEqual(headers["X-Trace-Id"], "recipient-lookup-trace")
        self.assertNotIn("X-Idempotency-Key", headers)

    @patch("core.flutterwave.v4._request_json_v4")
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

    @patch("core.flutterwave.v4._request_json_v4")
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

    @patch("core.flutterwave.v4._request_json_v4")
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

    @patch("core.flutterwave.v4._request_json_v4")
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

    @override_settings(
        FLUTTERWAVE_API_VERSION="v4",
        FLUTTERWAVE_CLIENT_ID="test-client-id",
        FLUTTERWAVE_CLIENT_SECRET="test-client-secret",
        FLUTTERWAVE_API_BASE_URL="https://developersandbox-api.flutterwave.com",
    )
    @patch("core.flutterwave.v4._request_json_v4")
    def test_customer_phone_payload_uses_numeric_three_digit_country_code(self, request_mock):
        request_mock.return_value = {"status": "success", "data": {"id": "customer_123"}}

        flutterwave.create_customer(
            email="tenant@example.com",
            full_name="Booking Tenant",
            phone_number="09080350066",
        )

        payload = request_mock.call_args.kwargs["payload"]
        self.assertEqual(payload["phone"], {"country_code": "234", "number": "9080350066"})

    @patch("core.flutterwave.v4._request_json_v4")
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

    @patch("core.flutterwave.v4._request_json_v4")
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
        FLUTTERWAVE_API_VERSION="v4",
        FLUTTERWAVE_CLIENT_ID="test-client-id",
        FLUTTERWAVE_CLIENT_SECRET="test-client-secret",
        FLUTTERWAVE_API_BASE_URL="https://developersandbox-api.flutterwave.com",
    )
    @patch("core.flutterwave.v3._request_json_v3")
    @patch("core.flutterwave.v4._request_json_v4")
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
        FLUTTERWAVE_API_VERSION="v4",
        FLUTTERWAVE_CLIENT_ID="test-client-id",
        FLUTTERWAVE_CLIENT_SECRET="test-client-secret",
        FLUTTERWAVE_API_BASE_URL="https://developersandbox-api.flutterwave.com",
    )
    @patch("core.flutterwave.v4._request_json_v4")
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


@override_settings(
    RENTDIRECT_VAT_HOLDING_BANK_CODE="101",
    RENTDIRECT_VAT_HOLDING_BANK_NAME="Providus",
    RENTDIRECT_VAT_HOLDING_ACCOUNT_NUMBER="1111111111",
    RENTDIRECT_VAT_HOLDING_ACCOUNT_NAME="RentDirect VAT Holding",
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
        TenantProfile.objects.create(
            user=self.tenant,
            first_name="Verified",
            last_name="Tenant",
            date_of_birth=date(1990, 1, 1),
            gender="Male",
            nationality="Nigeria",
            state_of_origin="Lagos",
            lga="Ikeja",
            employment_status="Employed",
            residence_country="Nigeria",
            residence_state="Lagos",
            residence_city="Ikeja",
            residence_lga="Ikeja",
            residence_address="1 Test Street",
            length_of_stay="2 years",
            housing_status="Rented",
            status=TenantProfile.Status.APPROVED,
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
        self.assertEqual(calculate_administration_fee_vat(self.listing.price_per_year), Decimal("11250.00"))
        self.assertEqual(response.json()["total_amount"], 1421250.0)
        self.assertEqual(response.json()["remaining_amount"], 1421250.0)

    def test_booking_create_reuses_viewing_only_booking(self):
        booking = Booking.objects.create(
            tenant=self.tenant,
            listing=self.listing,
            start_date=date(2026, 6, 19),
            end_date=date(2027, 6, 19),
            status=Booking.Status.PENDING,
            total_amount=None,
        )

        response = self.client.post(
            "/api/v1/bookings",
            {
                "listing_id": str(self.listing.id),
                "start_date": "2026-08-01",
                "end_date": "2027-08-01",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        self.assertEqual(response.json()["id"], str(booking.id))
        self.assertTrue(response.json()["rental_process_started"])
        booking.refresh_from_db()
        self.assertEqual(booking.start_date, date(2026, 8, 1))
        self.assertEqual(booking.end_date, date(2027, 8, 1))
        self.assertEqual(booking.total_amount, calculate_booking_total(self.listing.price_per_year))
        self.assertEqual(Booking.objects.filter(tenant=self.tenant, listing=self.listing).count(), 1)

    def test_payment_rejected_for_viewing_only_booking(self):
        booking = Booking.objects.create(
            tenant=self.tenant,
            listing=self.listing,
            start_date=date(2026, 6, 19),
            end_date=date(2027, 6, 19),
            status=Booking.Status.PENDING,
            total_amount=None,
        )

        response = self.client.post(
            "/api/v1/payments",
            {
                "booking_id": str(booking.id),
                "amount": "100000.00",
                "payment_method": "bank",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.json())
        self.assertFalse(Payment.objects.filter(booking=booking).exists())

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

    def test_tenant_without_completed_profile_cannot_create_booking(self):
        tenant = AppUser.objects.create_user(
            email="booking-incomplete-profile-tenant@example.com",
            password="password-123",
            name="Incomplete Profile Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        create_active_subscription(tenant, SubscriptionPayment.PlanCode.SILVER)
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
        self.assertEqual(booking_response.json()["remaining_amount"], 1421250.0)

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
        FLUTTERWAVE_API_VERSION="v4",
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
        self.assertEqual(payload["checkout"]["flutterwave"]["payment_options"], "banktransfer,account,ussd")
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
        FLUTTERWAVE_API_VERSION="v4",
        FLUTTERWAVE_CLIENT_ID="test-client-id",
        FLUTTERWAVE_CLIENT_SECRET="test-client-secret",
        FLUTTERWAVE_API_BASE_URL="https://f4bexperience.flutterwave.com",
        RENTDIRECT_VAT_HOLDING_BANK_CODE="101",
        RENTDIRECT_VAT_HOLDING_BANK_NAME="Providus",
        RENTDIRECT_VAT_HOLDING_ACCOUNT_NUMBER="1111111111",
        RENTDIRECT_VAT_HOLDING_ACCOUNT_NAME="RentDirect VAT Holding",
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
            {"status": "success", "data": {"id": "recipient_admin_vat"}},
            {"status": "success", "data": {"id": "recipient_caution"}},
            {"status": "success", "data": {"id": "recipient_landlord"}},
            {"status": "success", "data": {"id": "recipient_ops"}},
        ]
        create_bank_transfer_mock.side_effect = [
            {"status": "success", "data": {"id": "transfer_admin_vat", "status": "NEW"}},
            {"status": "success", "data": {"id": "transfer_caution", "status": "NEW"}},
            {"status": "success", "data": {"id": "transfer_landlord", "status": "NEW"}},
            {"status": "success", "data": {"id": "transfer_ops", "status": "NEW"}},
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
        self.assertIsNotNone(booking.deposit_paid_at)
        self.assertIsNone(booking.full_rent_paid_at)
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
        self.assertIsNotNone(booking.full_rent_paid_at)
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

        self.assertEqual(create_transfer_recipient_mock.call_count, 4)
        self.assertEqual(create_bank_transfer_mock.call_count, 4)
        self.assertEqual(len(mail.outbox), 6)
        landlord_transfer_emails = [message for message in mail.outbox if "Landlord Payout Initiated" in message.subject]
        internal_transfer_emails = [message for message in mail.outbox if "Internal Transfer Initiated" in message.subject]
        self.assertEqual(len(landlord_transfer_emails), 1)
        self.assertEqual(landlord_transfer_emails[0].to, [self.landlord.email])
        self.assertEqual(set(landlord_transfer_emails[0].cc), {self.tenant.email, "info@rentdirect.homes"})
        self.assertIn("₦1,200,000.00", landlord_transfer_emails[0].body)
        self.assertNotIn("₦1,440,000.00", landlord_transfer_emails[0].body)
        self.assertEqual(len(internal_transfer_emails), 3)
        for internal_email in internal_transfer_emails:
            self.assertEqual(internal_email.to, ["info@rentdirect.homes"])
            self.assertEqual(internal_email.cc, [])
        booking.refresh_from_db()
        self.assertIn("final_rent_payment_email_received", booking.tenant_rental_progress)
        self.assertNotIn("net_payment_notification_received", booking.landlord_rental_progress)
        settlements = PaymentSettlement.objects.filter(payment__transaction_id=final_payment_payload["payment"]["transaction_id"])
        self.assertEqual(
            str(settlements.get(purpose=PaymentSettlement.Purpose.OPERATIONS).amount),
            "150000.00",
        )
        self.assertEqual(
            str(settlements.get(purpose=PaymentSettlement.Purpose.CAUTION_FEE).amount),
            "60000.00",
        )
        self.assertEqual(
            str(settlements.get(purpose=PaymentSettlement.Purpose.ADMINISTRATION_FEE_VAT).amount),
            "11250.00",
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

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", FLUTTERWAVE_API_VERSION="v4")
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
            {"status": "success", "data": {"id": "recipient_admin_vat_worker"}},
            {"status": "success", "data": {"id": "recipient_caution_worker"}},
            {"status": "success", "data": {"id": "recipient_landlord_worker"}},
            {"status": "success", "data": {"id": "recipient_ops_worker"}},
        ]
        create_bank_transfer_mock.side_effect = [
            {"status": "success", "data": {"id": "transfer_admin_vat_worker", "status": "NEW"}},
            {"status": "success", "data": {"id": "transfer_caution_worker", "status": "NEW"}},
            {"status": "success", "data": {"id": "transfer_landlord_worker", "status": "NEW"}},
            {"status": "success", "data": {"id": "transfer_ops_worker", "status": "NEW"}},
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
        self.assertEqual(settlements.count(), 4)
        self.assertEqual(create_transfer_recipient_mock.call_count, 4)
        self.assertEqual(create_bank_transfer_mock.call_count, 4)
        self.assertSetEqual(
            set(settlements.values_list("status", flat=True)),
            {PaymentSettlement.Status.PROCESSING},
        )
        self.assertTrue(all(settlements.values_list("transfer_reference", flat=True)))
        self.assertEqual(len(mail.outbox), 4)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", FLUTTERWAVE_API_VERSION="v4")
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
            {"status": "success", "data": {"id": "recipient_existing_admin_vat"}},
            {"status": "success", "data": {"id": "recipient_existing_caution"}},
            {"status": "success", "data": {"id": "recipient_existing_landlord"}},
            {"status": "success", "data": {"id": "recipient_existing_ops"}},
        ]
        create_bank_transfer_mock.side_effect = [
            {"status": "success", "data": {"id": "transfer_existing_recipient_admin_vat", "status": "NEW"}},
            {"status": "success", "data": {"id": "transfer_existing_recipient_caution", "status": "NEW"}},
            {"status": "success", "data": {"id": "transfer_existing_recipient_landlord", "status": "NEW"}},
            {"status": "success", "data": {"id": "transfer_existing_recipient_ops", "status": "NEW"}},
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
        self.assertEqual(create_bank_transfer_mock.call_count, 4)
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
            {"status": "success", "data": {"id": "transfer_existing_recipient_admin_vat_retry", "status": "NEW"}},
            {"status": "success", "data": {"id": "transfer_existing_recipient_caution_retry", "status": "NEW"}},
            {"status": "success", "data": {"id": "transfer_existing_recipient_landlord_retry", "status": "NEW"}},
            {"status": "success", "data": {"id": "transfer_existing_recipient_ops_retry", "status": "NEW"}},
        ]

        call_command("process_ready_payouts")

        create_transfer_recipient_mock.assert_not_called()
        self.assertEqual(create_bank_transfer_mock.call_count, 4)

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
            {"status": "success", "data": {"id": "recipient_admin_vat_ok"}},
            {"status": "success", "data": {"id": "recipient_caution_failed"}},
            {"status": "success", "data": {"id": "recipient_landlord_ok"}},
            {"status": "success", "data": {"id": "recipient_ops_ok"}},
        ]
        create_bank_transfer_mock.side_effect = [
            {"status": "success", "data": {"id": "transfer_admin_vat_ok", "status": "NEW"}},
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

    def _landlord_as_tenant_client(self):
        UserRole.objects.create(user=self.landlord, role=AppUser.Role.TENANT)
        TenantProfile.objects.create(
            user=self.landlord,
            first_name="Booking",
            last_name="Landlord",
            date_of_birth=date(1990, 1, 1),
            gender="Male",
            nationality="Nigeria",
            state_of_origin="Lagos",
            lga="Ikeja",
            employment_status="Employed",
            residence_country="Nigeria",
            residence_state="Lagos",
            residence_city="Ikeja",
            residence_lga="Ikeja",
            residence_address="1 Test Street",
            length_of_stay="2 years",
            housing_status="Rented",
            status=TenantProfile.Status.APPROVED,
        )
        SubscriptionPayment.objects.create(
            user=self.landlord,
            role=AppUser.Role.TENANT,
            plan_code=SubscriptionPayment.PlanCode.SILVER,
            billing_cycle=SubscriptionPayment.BillingCycle.MONTHLY,
            amount=100,
            currency="NGN",
            status=SubscriptionPayment.Status.COMPLETED,
            transaction_id=f"SUBTESTSELF{self.landlord.id.hex[:20]}",
            payment_date=timezone.now(),
            expires_at=timezone.now() + timedelta(days=30),
        )
        token = str(RefreshToken.for_user(self.landlord).access_token)
        client = APIClient()
        client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {token}",
            HTTP_X_RENTDIRECT_ROLE="tenant",
        )
        return client

    def test_landlord_cannot_rent_own_listing(self):
        client = self._landlord_as_tenant_client()

        response = client.post(
            "/api/v1/bookings",
            {
                "listing_id": str(self.listing.id),
                "start_date": "2026-06-19",
                "end_date": "2027-06-19",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.json())
        self.assertIn("You cannot rent your own property.", str(response.json()))
        self.assertFalse(Booking.objects.filter(tenant=self.landlord).exists())

    def test_viewing_booked_rejects_listing_landlord(self):
        client = self._landlord_as_tenant_client()
        Message.objects.create(
            sender=self.landlord,
            receiver=self.landlord,
            sender_role=AppUser.Role.TENANT,
            receiver_role=AppUser.Role.LANDLORD,
            listing=self.listing,
            content="Interested in my own listing",
        )

        response = client.post(
            "/api/v1/messages/viewing-booked",
            {"listing_id": str(self.listing.id)},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.json())
        self.assertFalse(
            Booking.objects.filter(tenant=self.landlord, listing=self.listing).exists()
        )

    def test_landlord_cannot_review_own_listing(self):
        client = self._landlord_as_tenant_client()

        response = client.post(
            "/api/v1/reviews",
            {
                "listing_id": str(self.listing.id),
                "rating": 5,
                "comment": "Reviewing my own property.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.json())
        self.assertIn(
            "You cannot review your own property or landlord profile.",
            str(response.json()),
        )
        self.assertFalse(Review.objects.filter(tenant=self.landlord).exists())


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
        TenantProfile.objects.create(
            user=self.tenant,
            first_name="Verified",
            last_name="Tenant",
            date_of_birth=date(1990, 1, 1),
            gender="Male",
            nationality="Nigeria",
            state_of_origin="Lagos",
            lga="Ikeja",
            employment_status="Employed",
            residence_country="Nigeria",
            residence_state="Lagos",
            residence_city="Ikeja",
            residence_lga="Ikeja",
            residence_address="1 Test Street",
            length_of_stay="2 years",
            housing_status="Rented",
            status=TenantProfile.Status.APPROVED,
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
        self.assertEqual(self.listing.status, Listing.Status.AVAILABLE)

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
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Booking.Status.ACTIVE)

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

    def test_paid_listing_remains_public_until_tenant_key_confirmation(self):
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
        self.assertEqual(len(search_results), 1)
        self.assertEqual(search_results[0]["rental_badge"], "let_agreed")

        featured_response = self.client.get("/api/v1/featured/listings")
        self.assertEqual(featured_response.status_code, 200)
        self.assertEqual(len(featured_response.json()), 1)
        self.assertEqual(featured_response.json()[0]["rental_badge"], "let_agreed")

        public_landlord_listings_response = self.client.get(f"/api/v1/listings?landlord_id={self.landlord.id}")
        self.assertEqual(public_landlord_listings_response.status_code, 200)
        public_landlord_listings_payload = public_landlord_listings_response.json()
        public_landlord_listings = (
            public_landlord_listings_payload["results"]
            if isinstance(public_landlord_listings_payload, dict) and "results" in public_landlord_listings_payload
            else public_landlord_listings_payload
        )
        self.assertEqual(len(public_landlord_listings), 1)

        self.booking.paid_amount = calculate_booking_total(self.listing.price_per_year)
        self.booking.full_rent_paid_at = timezone.now()
        self.booking.end_date = timezone.localdate() + timedelta(days=30)
        self.booking.save(update_fields=["paid_amount", "full_rent_paid_at", "end_date", "updated_at"])

        full_payment_search_response = self.client.get("/api/v1/listings/search?city=Abuja")
        self.assertEqual(full_payment_search_response.status_code, 200)
        full_payment_search_payload = full_payment_search_response.json()
        full_payment_search_results = (
            full_payment_search_payload["results"]
            if isinstance(full_payment_search_payload, dict) and "results" in full_payment_search_payload
            else full_payment_search_payload
        )
        self.assertEqual(len(full_payment_search_results), 1)
        self.assertEqual(full_payment_search_results[0]["rental_badge"], "rented")
        self.assertEqual(len(self.client.get("/api/v1/featured/listings").json()), 1)

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
                "tenant_paid_rent_in_full",
                "check_in_inventory_completed",
                "tenant_collected_house_key",
            ],
        )

        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, Listing.Status.RENTED)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Booking.Status.ACTIVE)

        rented_search_response = self.client.get("/api/v1/listings/search?city=Abuja")
        self.assertEqual(rented_search_response.status_code, 200)
        rented_search_payload = rented_search_response.json()
        rented_search_results = (
            rented_search_payload["results"]
            if isinstance(rented_search_payload, dict) and "results" in rented_search_payload
            else rented_search_payload
        )
        self.assertEqual(rented_search_results, [])
        self.assertEqual(self.client.get("/api/v1/featured/listings").json(), [])

    def test_landlord_only_key_confirmation_does_not_rent_or_hide_listing(self):
        landlord_client = APIClient()
        landlord_client.force_authenticate(user=self.landlord)
        save_rental_progress_steps(
            self,
            landlord_client,
            self.booking.id,
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

        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, Listing.Status.AVAILABLE)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Booking.Status.PENDING)

        search_response = self.client.get("/api/v1/listings/search?city=Abuja")
        self.assertEqual(search_response.status_code, 200)
        search_payload = search_response.json()
        search_results = (
            search_payload["results"] if isinstance(search_payload, dict) and "results" in search_payload else search_payload
        )
        self.assertEqual(len(search_results), 1)
        self.assertEqual(search_results[0]["id"], str(self.listing.id))


class TenancyAgreementTests(TestCase):
    def setUp(self):
        self.landlord = AppUser.objects.create_user(
            email="agreement-landlord@example.com",
            password="password-123",
            name="Agreement Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
            mobile="+2348011111111",
            nin_number="11111111111",
        )
        self.landlord.landlord_verification_type = AppUser.LandlordVerificationType.INDIVIDUAL
        self.landlord.landlord_verification_profile = {
            "first_name": "Agreement",
            "last_name": "Landlord",
            "residential_address": "12 Landlord Close, Ikeja, Lagos",
            "contact_number": "+2348011111111",
            "nin": "11111111111",
        }
        self.landlord.save(update_fields=["landlord_verification_type", "landlord_verification_profile"])
        self.tenant = AppUser.objects.create_user(
            email="agreement-tenant@example.com",
            password="password-123",
            name="Agreement Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
            mobile="+2348022222222",
            nin_number="22222222222",
            tenant_verification_profile={"residence_address": "5 Tenant Avenue, Yaba, Lagos"},
        )
        self.listing = Listing.objects.create(
            landlord=self.landlord,
            title="2 Bedroom Apartment in Lekki",
            description="A listing used for tenancy agreement tests",
            address="8 Coastal Road",
            city="Lekki",
            state="Lagos",
            lga="Eti-Osa",
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=2500000,
            caution_fee=250000,
            service_charge=150000,
            legal_fee=125000,
            parking=True,
        )
        self.booking = Booking.objects.create(
            tenant=self.tenant,
            listing=self.listing,
            start_date=date(2026, 7, 1),
            end_date=date(2027, 7, 1),
            status=Booking.Status.CONFIRMED,
            total_amount=calculate_booking_total(self.listing.price_per_year),
        )
        self.api = APIClient()
        self.api.force_authenticate(user=self.landlord)
        self.url = f"/api/v1/bookings/{self.booking.id}/tenancy-agreement"

    def test_get_returns_persisted_party_property_and_booking_data(self):
        response = self.api.get(self.url)

        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        booking_payload = payload["booking"]
        self.assertEqual(booking_payload["id"], str(self.booking.id))
        self.assertEqual(booking_payload["listing_title"], "2 Bedroom Apartment in Lekki")
        self.assertEqual(booking_payload["tenant_name"], "Agreement Tenant")
        self.assertEqual(booking_payload["tenant_email"], "agreement-tenant@example.com")
        self.assertEqual(booking_payload["start_date"], "2026-07-01")
        self.assertEqual(booking_payload["end_date"], "2027-07-01")
        self.assertEqual(booking_payload["status"], "confirmed")
        self.assertEqual(float(booking_payload["rent_amount"]), 2500000.0)

        data = payload["data"]
        self.assertEqual(data["landlord"]["name"], "Agreement Landlord")
        self.assertEqual(data["landlord"]["address"], "12 Landlord Close, Ikeja, Lagos")
        self.assertEqual(data["landlord"]["phone"], "+2348011111111")
        self.assertNotIn("identificationNumber", data["landlord"])
        self.assertFalse(data["landlord"]["isCompany"])
        self.assertEqual(data["tenant"]["name"], "Agreement Tenant")
        self.assertEqual(data["tenant"]["email"], "agreement-tenant@example.com")
        self.assertEqual(data["tenant"]["address"], "5 Tenant Avenue, Yaba, Lagos")
        self.assertEqual(data["tenant"]["phone"], "+2348022222222")
        self.assertNotIn("identificationNumber", data["tenant"])
        self.assertEqual(data["property"]["state"], "Lagos")
        self.assertEqual(data["property"]["localGovernmentArea"], "Eti-Osa")
        self.assertIn("8 Coastal Road", data["property"]["fullAddress"])
        self.assertIn("Parking", data["property"]["ancillaryAreas"])
        self.assertFalse(data["property"]["isExcludedFromLagosTenancyLaw"])

        self.assertIsInstance(data["money"]["rentAmount"], int)
        self.assertEqual(data["money"]["rentAmount"], 2500000)
        self.assertEqual(data["money"]["securityDeposit"], 250000)
        self.assertEqual(data["money"]["serviceCharge"], 150000)
        self.assertNotIn("legalFee", data["money"])
        self.assertEqual(data["money"]["totalInitialAmount"], 2900000)
        self.assertEqual(data["money"]["rentAmountWords"], "Two Million Five Hundred Thousand Naira only")

        self.assertEqual(data["tenancy"]["termValue"], 1)
        self.assertEqual(data["tenancy"]["termUnit"], "year")
        self.assertTrue(data["tenancy"]["isFixedTerm"])
        self.assertFalse(data["tenancy"]["isCommercial"])
        self.assertNotIn("useType", data["tenancy"])
        self.assertIn("expires on 01 July 2027", data["termination"]["noticePeriodDescription"])
        self.assertIn("without any requirement", data["termination"]["noticePeriodDescription"])

        field_paths = {field["path"] for field in payload["fields"]}
        self.assertIn("landlord.address", field_paths)
        self.assertIn("money.securityDeposit", field_paths)
        self.assertNotIn("tenancy.useType", field_paths)
        self.assertFalse(any("identification" in path.lower() for path in field_paths))
        self.assertFalse(any("legalFee" in path for path in field_paths))
        self.assertEqual(payload["missing_fields"], [])
        self.assertTrue(payload["can_generate"])
        self.assertIsNone(payload["latest_agreement"])

    def test_workspace_includes_free_and_lawyer_agreement_options(self):
        response = self.api.get(self.url)

        self.assertEqual(response.status_code, 200, response.json())
        options = response.json()["agreement_options"]
        self.assertEqual(options["free"]["amount"], 0)
        self.assertTrue(options["free"]["landlord_pays"])
        self.assertEqual(options["lawyer"]["fee_rate"], "0.05")
        self.assertEqual(float(options["lawyer"]["amount"]), 125000.0)
        self.assertTrue(options["lawyer"]["landlord_pays"])
        self.assertIsNone(options["lawyer"]["payment"])

        payment = ServicePayment.objects.create(
            user=self.landlord,
            booking=self.booking,
            purpose=ServicePayment.Purpose.LAWYER_TENANCY,
            amount=125000,
            status=ServicePayment.Status.COMPLETED,
            transaction_id="SVC-TEST-LAWYER",
        )
        second_response = self.api.get(self.url)
        self.assertEqual(second_response.status_code, 200, second_response.json())
        payment_payload = second_response.json()["agreement_options"]["lawyer"]["payment"]
        self.assertEqual(payment_payload["id"], str(payment.id))
        self.assertEqual(payment_payload["status"], "completed")

    def test_tenant_allowed_and_unrelated_landlord_not_found(self):
        tenant_client = APIClient()
        tenant_client.force_authenticate(user=self.tenant)
        self.assertEqual(tenant_client.get(self.url).status_code, 200)

        other_landlord = AppUser.objects.create_user(
            email="other-landlord@example.com",
            password="password-123",
            name="Other Landlord",
            role=AppUser.Role.LANDLORD,
        )
        other_client = APIClient()
        other_client.force_authenticate(user=other_landlord)
        self.assertEqual(other_client.get(self.url).status_code, 404)

    def test_post_with_blank_required_field_returns_dotted_errors(self):
        response = self.api.post(self.url, {"data": {"landlord": {"address": ""}}}, format="json")

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(payload["errors"]["landlord.address"], "This field is required.")
        self.assertIn("landlord.address", payload["missing_fields"])
        self.assertFalse(TenancyAgreement.objects.filter(booking=self.booking).exists())

    def test_post_with_non_object_data_is_rejected(self):
        response = self.api.post(self.url, {"data": "not-an-object"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["data"], "Agreement data must be an object.")

    def test_successful_post_persists_hashed_immutable_review_version(self):
        response = self.api.post(
            self.url,
            {
                "data": {
                    "landlord": {"name": "Submitted Fake Name", "address": "99 Landlord Way, Lagos"},
                    "money": {"rentAmount": 1, "securityDeposit": 300000},
                    "handover": {"keysDescription": "Two sets of keys and one access card"},
                }
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        payload = response.json()
        record = TenancyAgreement.objects.get(booking=self.booking)
        self.assertEqual(record.version, 1)
        self.assertEqual(record.status, TenancyAgreement.Status.REVIEW)
        self.assertEqual(record.generated_by, self.landlord)
        self.assertIsNone(record.finalised_at)
        self.assertEqual(payload["latest_agreement"]["id"], str(record.id))
        self.assertEqual(payload["latest_agreement"]["version"], 1)

        rendered = record.rendered_content
        self.assertTrue(rendered.startswith("# TENANCY AGREEMENT"))
        self.assertIn("Agreement Landlord", rendered)
        self.assertNotIn("Submitted Fake Name", rendered)
        self.assertIn("5 Tenant Avenue, Yaba, Lagos", rendered)
        self.assertIn("8 Coastal Road", rendered)
        self.assertIn("99 Landlord Way, Lagos", rendered)
        self.assertIn("Two sets of keys and one access card", rendered)
        self.assertNotIn("{{", rendered)
        self.assertNotIn("}}", rendered)
        self.assertIn("used solely as a private residence", rendered)
        self.assertIn("# 30. SCHEDULE 2 — PAYMENT SUMMARY", rendered)
        self.assertIn("# 31. EXECUTION", rendered)
        self.assertNotIn("SCHEDULE 2 — COMMERCIAL TENANCY DETAILS", rendered)
        self.assertNotIn("lawful business or activity described above", rendered)
        self.assertNotIn("signage", rendered)
        self.assertNotIn("does not apply", rendered)
        self.assertNotIn("tenancy.useType", rendered)
        self.assertNotIn("11111111111", rendered)
        self.assertNotIn("22222222222", rendered)

        expected_hash = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
        self.assertEqual(record.document_hash, expected_hash)
        self.assertEqual(record.agreement_data["agreement"]["documentHash"], expected_hash)
        self.assertEqual(record.agreement_data["landlord"]["name"], "Agreement Landlord")
        self.assertEqual(record.agreement_data["money"]["rentAmount"], 2500000)
        self.assertEqual(record.agreement_data["money"]["securityDeposit"], 300000)
        self.assertEqual(record.agreement_data["money"]["totalInitialAmount"], 2950000)

    def test_second_post_creates_new_version_and_preserves_first(self):
        first_response = self.api.post(self.url, {"data": {}}, format="json")
        self.assertEqual(first_response.status_code, 201, first_response.json())
        first = TenancyAgreement.objects.get(booking=self.booking, version=1)
        first_hash = first.document_hash
        first_rendered = first.rendered_content

        second_response = self.api.post(
            self.url,
            {"data": {"handover": {"keysDescription": "One key set"}}},
            format="json",
        )
        self.assertEqual(second_response.status_code, 201, second_response.json())
        self.assertEqual(second_response.json()["latest_agreement"]["version"], 2)
        self.assertEqual(TenancyAgreement.objects.filter(booking=self.booking).count(), 2)

        first.refresh_from_db()
        self.assertEqual(first.document_hash, first_hash)
        self.assertEqual(first.rendered_content, first_rendered)
        self.assertEqual(
            TenancyAgreement.objects.get(booking=self.booking, version=2).status,
            TenancyAgreement.Status.REVIEW,
        )

    def _create_commercial_booking(self):
        office_listing = Listing.objects.create(
            landlord=self.landlord,
            title="Lekki Office Suite",
            description="Office space in Lekki",
            address="20 Office Close",
            city="Lekki",
            state="Lagos",
            lga="Eti-Osa",
            property_type="Office",
            bedrooms=0,
            bathrooms=1,
            price_per_year=8000000,
        )
        return Booking.objects.create(
            tenant=self.tenant,
            listing=office_listing,
            start_date=date(2026, 8, 1),
            end_date=date(2027, 8, 1),
            status=Booking.Status.CONFIRMED,
            total_amount=calculate_booking_total(office_listing.price_per_year),
        )

    def test_commercial_use_requires_business_description(self):
        office_booking = self._create_commercial_booking()
        office_url = f"/api/v1/bookings/{office_booking.id}/tenancy-agreement"

        get_response = self.api.get(office_url)
        self.assertEqual(get_response.status_code, 200, get_response.json())
        self.assertTrue(get_response.json()["data"]["tenancy"]["isCommercial"])
        self.assertNotIn("useType", get_response.json()["data"]["tenancy"])

        response = self.api.post(office_url, {"data": {}}, format="json")

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(payload["errors"]["commercial.businessDescription"], "This field is required.")
        self.assertIn("commercial.businessDescription", payload["missing_fields"])
        self.assertFalse(TenancyAgreement.objects.filter(booking=office_booking).exists())

    def test_commercial_generation_includes_commercial_schedule(self):
        office_booking = self._create_commercial_booking()
        office_url = f"/api/v1/bookings/{office_booking.id}/tenancy-agreement"

        response = self.api.post(
            office_url,
            {"data": {"commercial": {"businessDescription": "Software consultancy office"}}},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        rendered = TenancyAgreement.objects.get(booking=office_booking).rendered_content
        self.assertIn("lawful business or activity described above", rendered)
        self.assertIn("# 30. SCHEDULE 2 — COMMERCIAL TENANCY DETAILS", rendered)
        self.assertIn("# 31. SCHEDULE 3 — PAYMENT SUMMARY", rendered)
        self.assertIn("# 32. EXECUTION", rendered)
        self.assertIn("Software consultancy office", rendered)
        self.assertNotIn("private residence", rendered)
        self.assertNotIn("does not apply", rendered)
        self.assertNotIn("tenancy.useType", rendered)
        self.assertNotIn("11111111111", rendered)
        self.assertNotIn("22222222222", rendered)

    def test_lagos_excluded_area_sets_exclusion_notice(self):
        ikoyi_listing = Listing.objects.create(
            landlord=self.landlord,
            title="Ikoyi Office Suite",
            description="Office suite in Ikoyi",
            address="4 Ikoyi Crescent",
            city="Ikoyi",
            state="Lagos",
            lga="Eti-Osa",
            property_type="Office",
            bedrooms=0,
            bathrooms=1,
            price_per_year=8000000,
        )
        ikoyi_booking = Booking.objects.create(
            tenant=self.tenant,
            listing=ikoyi_listing,
            start_date=date(2026, 8, 1),
            end_date=date(2027, 8, 1),
            status=Booking.Status.CONFIRMED,
            total_amount=calculate_booking_total(ikoyi_listing.price_per_year),
        )

        response = self.api.get(f"/api/v1/bookings/{ikoyi_booking.id}/tenancy-agreement")

        self.assertEqual(response.status_code, 200, response.json())
        data = response.json()["data"]
        self.assertTrue(data["property"]["isExcludedFromLagosTenancyLaw"])
        self.assertTrue(data["tenancy"]["isCommercial"])
        self.assertNotIn("useType", data["tenancy"])
        notice = data["termination"]["noticePeriodDescription"]
        self.assertIn("excluded from the Lagos State Tenancy Law 2011", notice)
        self.assertIn("other applicable law", notice)

    def test_non_lagos_property_with_excluded_area_address_is_not_excluded(self):
        rivers_listing = Listing.objects.create(
            landlord=self.landlord,
            title="Port Harcourt Duplex",
            description="A duplex in Port Harcourt",
            address="10 Victoria Island Road",
            city="Port Harcourt",
            state="Rivers",
            lga="Port Harcourt",
            property_type="House",
            bedrooms=3,
            bathrooms=3,
            price_per_year=3000000,
        )
        rivers_booking = Booking.objects.create(
            tenant=self.tenant,
            listing=rivers_listing,
            start_date=date(2026, 9, 1),
            end_date=date(2027, 9, 1),
            status=Booking.Status.CONFIRMED,
            total_amount=calculate_booking_total(rivers_listing.price_per_year),
        )

        response = self.api.get(f"/api/v1/bookings/{rivers_booking.id}/tenancy-agreement")

        self.assertEqual(response.status_code, 200, response.json())
        data = response.json()["data"]
        self.assertFalse(data["property"]["isExcludedFromLagosTenancyLaw"])
        self.assertNotIn("excluded from the Lagos State Tenancy Law 2011", data["termination"]["noticePeriodDescription"])

    def test_monthly_frequency_derives_period_rent_and_first_period(self):
        response = self.api.post(
            self.url,
            {"data": {"payments": {"rentFrequency": "monthly"}}},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        record = TenancyAgreement.objects.get(booking=self.booking)
        self.assertEqual(record.agreement_data["payments"]["rentFrequency"], "monthly")
        self.assertEqual(record.agreement_data["money"]["rentAmount"], 208333.33)
        self.assertEqual(record.agreement_data["money"]["totalInitialAmount"], 608333.33)
        self.assertEqual(record.agreement_data["payments"]["firstRentPeriod"], "01 July 2026 to 01 August 2026")
        self.assertTrue(record.agreement_data["money"]["rentAmountWords"].endswith("Kobo only"))
        self.assertIn("208,333.33", record.rendered_content)

    def test_non_finite_numeric_value_is_rejected(self):
        response = self.api.post(
            self.url,
            {"data": {"money": {"securityDeposit": "Infinity"}}},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["errors"]["money.securityDeposit"], "Enter a valid number.")
        self.assertFalse(TenancyAgreement.objects.filter(booking=self.booking).exists())

    def test_rendered_output_sanitizes_submitted_template_values(self):
        response = self.api.post(
            self.url,
            {"data": {"handover": {"existingDefects": "<script>alert(1)</script> {{bad}} [click](javascript:alert(1))"}}},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        rendered = TenancyAgreement.objects.get(booking=self.booking).rendered_content
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("{{", rendered)
        self.assertNotIn("}}", rendered)
        self.assertNotIn("](javascript:", rendered)

    def test_cancelled_booking_returns_workspace_but_cannot_generate(self):
        self.booking.status = Booking.Status.CANCELLED
        self.booking.save(update_fields=["status", "updated_at"])

        get_response = self.api.get(self.url)
        self.assertEqual(get_response.status_code, 200, get_response.json())
        self.assertFalse(get_response.json()["can_generate"])

        post_response = self.api.post(self.url, {"data": {}}, format="json")
        self.assertEqual(post_response.status_code, 400)
        self.assertFalse(TenancyAgreement.objects.filter(booking=self.booking).exists())

    def _generate_agreement(self):
        response = self.api.post(self.url, {"data": {}}, format="json")
        self.assertEqual(response.status_code, 201, response.json())
        return TenancyAgreement.objects.get(booking=self.booking)

    def test_tenant_can_view_workspace_for_own_booking(self):
        self._generate_agreement()
        self.api.force_authenticate(user=self.tenant)
        response = self.api.get(self.url)
        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        self.assertEqual(payload["viewer_role"], "tenant")
        self.assertIsNone(payload["agreement_options"])
        self.assertFalse(payload["can_generate"])
        self.assertEqual(payload["fields"], [])

    def test_tenant_cannot_generate_agreement(self):
        self.api.force_authenticate(user=self.tenant)
        response = self.api.post(self.url, {"data": {}}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(TenancyAgreement.objects.filter(booking=self.booking).exists())

    def test_landlord_signing_records_signature_and_completes_progress_step(self):
        self._generate_agreement()
        response = self.api.post(
            f"{self.url}/sign",
            {"signatory_name": "Agreement Landlord", "signatory_capacity": "Landlord"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        self.assertTrue(payload["signed_by_landlord"])
        self.assertFalse(payload["signed_by_tenant"])
        self.assertFalse(payload["can_sign"])
        signatures = payload["data"]["signatures"]
        self.assertTrue(signatures["landlord"]["signatureId"])
        self.assertEqual(signatures["landlord"]["signatoryName"], "Agreement Landlord")
        self.assertTrue(signatures["landlord"]["signatureId"])

        agreement = TenancyAgreement.objects.get(booking=self.booking)
        self.assertEqual(agreement.agreement_data["signatures"]["landlord"]["signatureId"], signatures["landlord"]["signatureId"])

        self.booking.refresh_from_db()
        progress = self.booking.landlord_rental_progress
        self.assertIn("tenancy_agreement_signed", progress)
        self.assertNotIn("tenancy_agreement_signed", self.booking.tenant_rental_progress)

    def test_tenant_signing_records_signature_and_completes_tenant_progress_step(self):
        self._generate_agreement()
        self.api.force_authenticate(user=self.tenant)
        response = self.api.post(
            f"{self.url}/sign",
            {"signatory_name": "Agreement Tenant"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        self.assertTrue(payload["signed_by_tenant"])
        self.assertFalse(payload["signed_by_landlord"])

        self.booking.refresh_from_db()
        self.assertIn("tenancy_agreement_signed", self.booking.tenant_rental_progress)
        self.assertNotIn("tenancy_agreement_signed", self.booking.landlord_rental_progress)

    def test_both_parties_can_sign_same_version(self):
        self._generate_agreement()
        first = self.api.post(f"{self.url}/sign", {"signatory_name": "Agreement Landlord"}, format="json")
        self.assertEqual(first.status_code, 200, first.json())
        self.api.force_authenticate(user=self.tenant)
        second = self.api.post(f"{self.url}/sign", {"signatory_name": "Agreement Tenant"}, format="json")
        self.assertEqual(second.status_code, 200, second.json())
        payload = second.json()
        self.assertTrue(payload["signed_by_landlord"])
        self.assertTrue(payload["signed_by_tenant"])
        agreement = TenancyAgreement.objects.get(booking=self.booking)
        self.assertEqual(agreement.version, 1)
        self.assertEqual(agreement.status, TenancyAgreement.Status.FINAL)
        self.assertTrue(agreement.agreement_data["signatures"]["landlord"]["signatureId"])
        self.assertTrue(agreement.agreement_data["signatures"]["tenant"]["signatureId"])

    def test_duplicate_signature_attempt_is_rejected(self):
        self._generate_agreement()
        first = self.api.post(f"{self.url}/sign", {"signatory_name": "Agreement Landlord"}, format="json")
        self.assertEqual(first.status_code, 200, first.json())
        second = self.api.post(f"{self.url}/sign", {"signatory_name": "Agreement Landlord"}, format="json")
        self.assertEqual(second.status_code, 400)

    def test_signing_requires_generated_agreement(self):
        response = self.api.post(f"{self.url}/sign", {"signatory_name": "Agreement Landlord"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_signing_rejects_unrelated_users_and_missing_name(self):
        self._generate_agreement()
        outsider = AppUser.objects.create_user(
            email="agreement-outsider@example.com",
            password="password-123",
            name="Outsider",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        self.api.force_authenticate(user=outsider)
        response = self.api.post(f"{self.url}/sign", {"signatory_name": "Outsider"}, format="json")
        self.assertEqual(response.status_code, 404)

        self.api.force_authenticate(user=self.landlord)
        missing_name = self.api.post(f"{self.url}/sign", {"signatory_name": ""}, format="json")
        self.assertEqual(missing_name.status_code, 400)

    def test_counterpart_progress_mapping_uses_explicit_step_keys(self):
        """Landlord 'deposit notification' should map to tenant 'tenant_paid_deposit', not positional index."""
        from core.models import build_booking_progress_data, complete_booking_progress_step

        complete_booking_progress_step(self.booking, "tenant", "tenant_paid_deposit")
        landlord_data = build_booking_progress_data(self.booking, AppUser.Role.LANDLORD)
        steps = {step["key"]: step for step in landlord_data["steps"]}
        self.assertTrue(steps["deposit_payment_notification_received"]["counterpart_completed"])
        self.assertEqual(steps["deposit_payment_notification_received"]["counterpart_step_key"], "tenant_paid_deposit")

        # Choice counterpart: tenant sees landlord's selection on the transfer question.
        complete_booking_progress_step(self.booking, "landlord", "rentdirect_transfer_to_landlord", selected_value="no")
        tenant_data = build_booking_progress_data(self.booking, AppUser.Role.TENANT)
        tenant_steps = {step["key"]: step for step in tenant_data["steps"]}
        self.assertEqual(tenant_steps["rentdirect_transfer_to_landlord"]["counterpart_selected_value"], "no")


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
        self.assertNotIn("email", payload)
        self.assertNotIn("mobile", payload)
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
        self.assertIn(subscription.plan_code, SubscriptionPayment.PlanCode.values)
        self.assertEqual(subscription.billing_cycle, SubscriptionPayment.BillingCycle.MONTHLY)
        self.assertEqual(subscription.status, SubscriptionPayment.Status.COMPLETED)
        self.assertEqual(subscription.provider, "seed_demo")
        self.assertEqual(subscription.billing_reason, "seed_demo")
        expected_amount = get_subscription_pricing()[user.role][subscription.plan_code][subscription.billing_cycle]
        self.assertEqual(subscription.amount, Decimal(str(expected_amount)))
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

        self.assertIn("Seed demo landlord and tenant accounts already exist; refreshed homepage seed assets", out.getvalue())
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

    def test_seed_demo_preserves_listing_image_content_type(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "listing.webp"
            source_path.write_bytes(b"image")
            saved = {}

            class Field:
                name = ""

                def delete(self, save=False):
                    return None

                def save(self, name, content, save=False):
                    saved["name"] = name
                    saved["content_type"] = getattr(content, "content_type", "")

            instance = type("SeedImage", (), {"file": Field()})()
            SeedDemoDataCommand().replace_model_file(instance, "file", source_path)

        self.assertEqual(saved, {"name": "listing.webp", "content_type": "image/webp"})

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
                featured_listing = Listing.objects.filter(featured=True).first()
                featured_listing.featured = False
                featured_listing.save(update_fields=["featured", "updated_at"])
                featured_listing.images.all().delete()
                call_command("seed_demo_data")

        landlords = list(AppUser.objects.filter(role=AppUser.Role.LANDLORD))
        tenants = list(AppUser.objects.filter(role=AppUser.Role.TENANT))
        seed_users = [*landlords, *tenants]
        listings = Listing.objects.filter(landlord__in=landlords)

        self.assertEqual(len(landlords), 11)
        self.assertEqual(len(tenants), 6)
        self.assertEqual(listings.count(), 15)
        self.assertEqual(listings.filter(featured=True).count(), 4)
        self.assertEqual(VerificationRequest.objects.filter(user__in=seed_users).count(), 17)
        self.assertEqual(SubscriptionPayment.objects.filter(user__in=seed_users).count(), 17)
        self.assertEqual(TenantProfile.objects.filter(user__in=tenants).count(), 6)

        seeded_tenant_profile = TenantProfile.objects.get(user__email="criyo.career+jade@gmail.com")
        self.assertEqual(seeded_tenant_profile.financial_info["monthly_income_amount"], "500000")
        self.assertEqual(seeded_tenant_profile.financial_info["monthly_expenses"], "200,000")
        self.assertEqual(seeded_tenant_profile.financial_info["current_annual_rent"], "2500000")
        self.assertEqual(seeded_tenant_profile.financial_info["credit_commitment"], "0")
        self.assertEqual(seeded_tenant_profile.financial_info["outstanding_loans"], "0")
        self.assertNotIn("current_rent_amount", seeded_tenant_profile.financial_info)

        for user in seed_users:
            self.assert_seed_subscription(SubscriptionPayment.objects.get(user=user), user)
            verification = VerificationRequest.objects.get(user=user, role=user.role)
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
                            "lga": "Eti-Osa",
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
                            "lga": "Eti-Osa",
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
                            "lga": "Eti-Osa",
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
                            "lga": "Eti-Osa",
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
        FLUTTERWAVE_API_VERSION="v4",
        FLUTTERWAVE_CLIENT_ID="test-client-id",
        FLUTTERWAVE_CLIENT_SECRET="test-client-secret",
        FLUTTERWAVE_API_BASE_URL="https://developersandbox-api.flutterwave.com",
        FLUTTERWAVE_ENCRYPTION_KEY="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
        RENTDIRECT_OPERATING_SUBACCOUNT_ID="",
        RENTDIRECT_OPERATING_BANK_NAME="",
        RENTDIRECT_OPERATING_BANK_CODE="",
        RENTDIRECT_OPERATING_ACCOUNT_NUMBER="",
        RENTDIRECT_VAT_HOLDING_SUBACCOUNT_ID="",
        RENTDIRECT_VAT_HOLDING_BANK_NAME="",
        RENTDIRECT_VAT_HOLDING_BANK_CODE="",
        RENTDIRECT_VAT_HOLDING_ACCOUNT_NUMBER="",
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

    @override_settings(
        RENTDIRECT_OPERATING_SUBACCOUNT_ID="RS_SUBSCRIPTION_TEST",
        RENTDIRECT_VAT_HOLDING_SUBACCOUNT_ID="",
        RENTDIRECT_VAT_HOLDING_BANK_NAME="",
        RENTDIRECT_VAT_HOLDING_BANK_CODE="",
        RENTDIRECT_VAT_HOLDING_ACCOUNT_NUMBER="",
        RENTDIRECT_VAT_HOLDING_BUSINESS_MOBILE="",
    )
    def test_recurring_subscription_config_requires_vat_settlement_account(self):
        landlord = AppUser.objects.create_user(
            email="landlord-vat-config@example.com",
            password="password-123",
            name="VAT Config Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        client = APIClient()
        client.force_authenticate(user=landlord)

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
        self.assertEqual(str(payment.vat_amount), "0.00")
        self.assertEqual(response.json()["total_amount"], "0.00")
        self.assertFalse(SubscriptionVATPayment.objects.filter(subscription_payment=payment).exists())
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
        FLUTTERWAVE_API_VERSION="v3",
        FLUTTERWAVE_PUBLIC_KEY="test-public-key",
        FLUTTERWAVE_SECRET_KEY="test-secret-key",
        RENTDIRECT_OPERATING_SUBACCOUNT_ID="RS_SUBSCRIPTION_TEST",
        RENTDIRECT_OPERATING_BANK_NAME="FCMB",
        RENTDIRECT_OPERATING_BANK_CODE="214",
        RENTDIRECT_OPERATING_ACCOUNT_NUMBER="0000000000",
        RENTDIRECT_OPERATING_ACCOUNT_NAME="RentDirect Operations",
        RENTDIRECT_VAT_HOLDING_SUBACCOUNT_ID="RS_VAT_TEST",
        RENTDIRECT_VAT_HOLDING_BANK_NAME="Providus",
        RENTDIRECT_VAT_HOLDING_BANK_CODE="101",
        RENTDIRECT_VAT_HOLDING_ACCOUNT_NUMBER="1111111111",
        RENTDIRECT_VAT_HOLDING_ACCOUNT_NAME="RentDirect VAT Holding",
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
        expected_vat_display = "37.50"
        expected_total_display = "537.50"
        self.assertEqual(payment.status, SubscriptionPayment.Status.PENDING)
        self.assertEqual(str(payment.amount), expected_amount_display)
        self.assertEqual(str(payment.vat_rate), "7.50")
        self.assertEqual(str(payment.vat_amount), expected_vat_display)
        self.assertEqual(request_response.json()["total_amount"], expected_total_display)

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
                    "transaction_split_ratio": 40,
                    "transaction_charge_type": "flat",
                    "transaction_charge": 0,
                },
                {
                    "id": "RS_VAT_TEST",
                    "transaction_split_ratio": 3,
                    "transaction_charge_type": "flat",
                    "transaction_charge": 0,
                },
            ],
        )
        payment.refresh_from_db()
        self.assertEqual(payment.provider_payload["subscription_destination"]["subaccount_id"], "RS_SUBSCRIPTION_TEST")
        self.assertEqual(payment.provider_payload["subscription_destination"]["account_number"], "0000000000")
        self.assertEqual(payment.provider_payload["vat_destination"]["subaccount_id"], "RS_VAT_TEST")
        self.assertEqual(payment.provider_payload["vat_destination"]["account_number"], "1111111111")
        self.assertEqual(checkout_payload["checkout"]["flutterwave"]["amount"], 537.5)

        query_transaction_mock.return_value = {
            "status": "success",
            "data": {
                "id": "991",
                "tx_ref": payment.transaction_id,
                "status": "successful",
                "amount": expected_total_display,
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
        vat_payment = SubscriptionVATPayment.objects.get(subscription_payment=payment)
        self.assertEqual(vat_payment.payer_name, tenant.name)
        self.assertEqual(vat_payment.payer_email, tenant.email)
        self.assertEqual(vat_payment.entity_type, AppUser.Role.TENANT)
        self.assertEqual(str(vat_payment.subscription_fee_amount), expected_amount_display)
        self.assertEqual(str(vat_payment.vat_amount), expected_vat_display)
        self.assertEqual(str(vat_payment.amount_paid), expected_total_display)
        self.assertEqual(vat_payment.transaction_id, payment.transaction_id)
        self.assertEqual(vat_payment.provider_transaction_id, "991")
        self.assertEqual(vat_payment.paid_at, payment.payment_date)

        repeat_verify_response = client.get(
            "/api/v1/subscriptions/flutterwave/verify",
            {"reference": payment.transaction_id, "transaction_id": "991", "status": "successful"},
        )
        self.assertEqual(repeat_verify_response.status_code, 200, repeat_verify_response.json())
        self.assertEqual(SubscriptionVATPayment.objects.filter(subscription_payment=payment).count(), 1)

    @override_settings(
        FLUTTERWAVE_API_VERSION="v3",
        FLUTTERWAVE_PUBLIC_KEY="test-public-key",
        FLUTTERWAVE_SECRET_KEY="test-secret-key",
        RENTDIRECT_OPERATING_SUBACCOUNT_ID="",
        RENTDIRECT_OPERATING_BANK_NAME="FCMB",
        RENTDIRECT_OPERATING_BANK_CODE="",
        RENTDIRECT_OPERATING_ACCOUNT_NUMBER="0000000000",
        RENTDIRECT_OPERATING_ACCOUNT_NAME="RentDirect Operations",
        RENTDIRECT_OPERATING_BUSINESS_EMAIL="billing@rentdirect.homes",
        RENTDIRECT_OPERATING_BUSINESS_MOBILE="08000000000",
        RENTDIRECT_VAT_HOLDING_SUBACCOUNT_ID="",
        RENTDIRECT_VAT_HOLDING_BANK_NAME="Providus",
        RENTDIRECT_VAT_HOLDING_BANK_CODE="101",
        RENTDIRECT_VAT_HOLDING_ACCOUNT_NUMBER="1111111111",
        RENTDIRECT_VAT_HOLDING_ACCOUNT_NAME="RentDirect VAT Holding",
        RENTDIRECT_VAT_HOLDING_BUSINESS_EMAIL="tax@rentdirect.homes",
        RENTDIRECT_VAT_HOLDING_BUSINESS_MOBILE="08000000001",
        WEB_PUBLIC_URL="http://localhost:5173",
    )
    @patch("core.views.get_or_create_collection_subaccount_id", side_effect=["RS_CREATED_SUBSCRIPTION", "RS_CREATED_VAT"])
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
        self.assertEqual(
            subaccount_mock.call_args_list,
            [
                call(
                    bank_code="214",
                    account_number="0000000000",
                    business_name="RentDirect Operations",
                    business_email="billing@rentdirect.homes",
                    business_mobile="08000000000",
                    country="NG",
                    split_type="flat",
                    split_value="0",
                ),
                call(
                    bank_code="101",
                    account_number="1111111111",
                    business_name="RentDirect VAT Holding",
                    business_email="tax@rentdirect.homes",
                    business_mobile="08000000001",
                    country="NG",
                    split_type="flat",
                    split_value="0",
                ),
            ],
        )
        self.assertEqual(response.json()["checkout"]["flutterwave"]["subaccounts"][0]["id"], "RS_CREATED_SUBSCRIPTION")
        self.assertEqual(response.json()["checkout"]["flutterwave"]["subaccounts"][1]["id"], "RS_CREATED_VAT")

    @override_settings(
        FLUTTERWAVE_API_VERSION="v4",
        FLUTTERWAVE_CLIENT_ID="test-client-id",
        FLUTTERWAVE_CLIENT_SECRET="test-client-secret",
        FLUTTERWAVE_API_BASE_URL="https://developersandbox-api.flutterwave.com",
        RENTDIRECT_OPERATING_SUBACCOUNT_ID="RS_SUBSCRIPTION_TEST",
        RENTDIRECT_VAT_HOLDING_SUBACCOUNT_ID="RS_VAT_TEST",
        WEB_PUBLIC_URL="http://localhost:5173",
    )
    @patch("core.views.create_charge")
    @patch("core.views.create_dynamic_virtual_account")
    @patch("core.views.create_customer")
    def test_subscription_checkout_uses_v4_bank_transfer_flow(
        self,
        create_customer_mock,
        create_dynamic_virtual_account_mock,
        create_charge_mock,
    ):
        tenant = AppUser.objects.create_user(
            email="tenant-v4-subscription@example.com",
            password="password-123",
            name="V4 Subscription Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        payment = SubscriptionPayment.objects.create(
            user=tenant,
            role=tenant.role,
            plan_code=SubscriptionPayment.PlanCode.SILVER,
            billing_cycle=SubscriptionPayment.BillingCycle.MONTHLY,
            amount="100.00",
            vat_rate="7.50",
            vat_amount="7.50",
            currency="NGN",
            status=SubscriptionPayment.Status.PENDING,
            provider="flutterwave",
            transaction_id="SUBV4CHECKOUT001",
            expires_at=timezone.now() + timedelta(days=30),
        )
        create_customer_mock.return_value = {"status": "success", "data": {"id": "cus_v4_123"}}
        create_dynamic_virtual_account_mock.return_value = {
            "status": "success",
            "data": {
                "id": "vacct_v4_123",
                "account_number": "0123456789",
                "bank_name": "Flutterwave",
                "bank_code": "50515",
            },
        }

        client = APIClient()
        client.force_authenticate(user=tenant)
        response = client.post(
            f"/api/v1/subscriptions/{payment.id}/flutterwave/checkout",
            {"payment_method": {"type": "bank_transfer", "bank_transfer": {}}},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json()["checkout"]["checkout_mode"], "v4")
        self.assertEqual(
            response.json()["checkout"]["next_action"]["type"],
            "requires_bank_transfer",
        )
        create_dynamic_virtual_account_mock.assert_called_once()
        create_charge_mock.assert_not_called()
        payment.refresh_from_db()
        self.assertEqual(
            payment.provider_payload["charge"]["data"]["next_action"]["type"],
            "requires_bank_transfer",
        )

    @override_settings(
        FLUTTERWAVE_PUBLIC_KEY="test-public-key",
        FLUTTERWAVE_SECRET_KEY="test-secret-key",
        FLUTTERWAVE_API_VERSION="v4",
        FLUTTERWAVE_CLIENT_ID="test-client-id",
        FLUTTERWAVE_CLIENT_SECRET="test-client-secret",
        FLUTTERWAVE_API_BASE_URL="https://developersandbox-api.flutterwave.com",
        FLUTTERWAVE_ENCRYPTION_KEY="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
        RENTDIRECT_OPERATING_SUBACCOUNT_ID="RS_SUBSCRIPTION_TEST",
        RENTDIRECT_OPERATING_BANK_NAME="FCMB",
        RENTDIRECT_OPERATING_BANK_CODE="214",
        RENTDIRECT_OPERATING_ACCOUNT_NUMBER="0000000000",
        RENTDIRECT_OPERATING_ACCOUNT_NAME="RentDirect Operations",
        RENTDIRECT_VAT_HOLDING_SUBACCOUNT_ID="RS_VAT_TEST",
        RENTDIRECT_VAT_HOLDING_BANK_NAME="Providus",
        RENTDIRECT_VAT_HOLDING_BANK_CODE="101",
        RENTDIRECT_VAT_HOLDING_ACCOUNT_NUMBER="1111111111",
        RENTDIRECT_VAT_HOLDING_ACCOUNT_NAME="RentDirect VAT Holding",
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
                    "transaction_split_ratio": 40,
                    "transaction_charge_type": "flat",
                    "transaction_charge": 0,
                },
                {
                    "id": "RS_VAT_TEST",
                    "transaction_split_ratio": 3,
                    "transaction_charge_type": "flat",
                    "transaction_charge": 0,
                },
            ],
        )
        self.assertEqual(payment.provider_payload["subscription_destination"]["subaccount_id"], "RS_SUBSCRIPTION_TEST")
        self.assertEqual(payment.provider_payload["vat_destination"]["subaccount_id"], "RS_VAT_TEST")
        self.assertEqual(str(payment.vat_amount), "60.00")
        vat_payment = SubscriptionVATPayment.objects.get(subscription_payment=payment)
        self.assertEqual(vat_payment.entity_type, AppUser.Role.LANDLORD)
        self.assertEqual(str(vat_payment.amount_paid), "860.00")

    @override_settings(
        FLUTTERWAVE_PUBLIC_KEY="test-public-key",
        FLUTTERWAVE_SECRET_KEY="test-secret-key",
        FLUTTERWAVE_API_VERSION="v4",
        FLUTTERWAVE_CLIENT_ID="test-client-id",
        FLUTTERWAVE_CLIENT_SECRET="test-client-secret",
        FLUTTERWAVE_API_BASE_URL="https://developersandbox-api.flutterwave.com",
        RENTDIRECT_OPERATING_SUBACCOUNT_ID="RS_SUBSCRIPTION_TEST",
        RENTDIRECT_OPERATING_BANK_NAME="FCMB",
        RENTDIRECT_OPERATING_BANK_CODE="214",
        RENTDIRECT_OPERATING_ACCOUNT_NUMBER="0000000000",
        RENTDIRECT_OPERATING_ACCOUNT_NAME="RentDirect Operations",
        RENTDIRECT_VAT_HOLDING_SUBACCOUNT_ID="RS_VAT_TEST",
        RENTDIRECT_VAT_HOLDING_BANK_NAME="Providus",
        RENTDIRECT_VAT_HOLDING_BANK_CODE="101",
        RENTDIRECT_VAT_HOLDING_ACCOUNT_NUMBER="1111111111",
        RENTDIRECT_VAT_HOLDING_ACCOUNT_NAME="RentDirect VAT Holding",
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
                    "amount": str(kwargs["amount"]),
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
        self.assertEqual(create_charge_mock.call_args.kwargs["subaccounts"][1]["id"], "RS_VAT_TEST")
        self.assertEqual(create_charge_mock.call_args.kwargs["amount"], Decimal("215.00"))
        self.assertEqual(str(renewal.vat_amount), "15.00")
        self.assertEqual(SubscriptionVATPayment.objects.filter(subscription_payment=renewal).count(), 1)


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

    def test_review_update_rejected_after_identity_gains_listing_ownership(self):
        landlord = AppUser.objects.create_user(
            email="review-ownership-landlord@example.com",
            password="password-123",
            name="Review Ownership Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        tenant = AppUser.objects.create_user(
            email="review-ownership-tenant@example.com",
            password="password-123",
            name="Review Ownership Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        create_active_subscription(tenant, SubscriptionPayment.PlanCode.GOLD)
        listing = Listing.objects.create(
            landlord=landlord,
            title="Ownership Review Listing",
            description="Review me",
            address="20 Review Street",
            city="Lagos",
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=2000000,
        )
        review = Review.objects.create(
            listing=listing,
            landlord=landlord,
            tenant=tenant,
            rating=5,
            comment="Created before ownership changed.",
        )

        # The reviewing identity subsequently gains ownership of the listing
        # (multi-role account became its landlord) - updates must be rejected.
        listing.landlord = tenant
        listing.save(update_fields=["landlord"])

        client = APIClient()
        client.force_authenticate(user=tenant)
        response = client.patch(
            f"/api/v1/reviews/{review.id}",
            {
                "listing_id": str(listing.id),
                "rating": 1,
                "comment": "Updated after ownership change.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.json())
        self.assertIn("You cannot review your own property", str(response.json()))
        review.refresh_from_db()
        self.assertEqual(review.rating, 5)


class FeedbackTests(TestCase):
    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_feedback_submission_sends_plan_based_acknowledgement_email(self):
        response_times = {
            AppUser.Role.TENANT: {
                SubscriptionPayment.PlanCode.BRONZE: "up to 7 days",
                SubscriptionPayment.PlanCode.SILVER: "up to 3 days",
                SubscriptionPayment.PlanCode.GOLD: "up to 24 hours",
                SubscriptionPayment.PlanCode.PLATINUM: "up to 4 hours",
            },
            AppUser.Role.LANDLORD: {
                SubscriptionPayment.PlanCode.BRONZE: "up to 7 days",
                SubscriptionPayment.PlanCode.SILVER: "up to 5 days",
                SubscriptionPayment.PlanCode.GOLD: "up to 3 days",
                SubscriptionPayment.PlanCode.PLATINUM: "up to 24 hours",
            },
        }
        client = APIClient()

        for role, plan_response_times in response_times.items():
            for plan_code, response_time in plan_response_times.items():
                user = AppUser.objects.create_user(
                    email=f"feedback-{role}-{plan_code}@example.com",
                    password="password-123",
                    name=f"{plan_code.title()} Support User",
                    role=role,
                    email_verified=True,
                )
                create_active_subscription(user, plan_code)
                client.force_authenticate(user=user)

                response = client.post(
                    "/api/v1/feedback",
                    {
                        "name": user.name,
                        "topic": "Complaint: Response time",
                        "message": "Please confirm that my support request was received.",
                    },
                    format="json",
                )

                self.assertEqual(response.status_code, 201, response.json())
                email = mail.outbox[-1]
                self.assertEqual(email.to, [user.email])
                self.assertIn(response_time, email.body)
                self.assertIn("complaint", email.body.lower())

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
            role=tenant.role,
            status=VerificationRequest.Status.APPROVED,
        )
        TenantProfile.objects.create(
            user=tenant,
            first_name="Verified",
            last_name="Tenant",
            date_of_birth=date(1990, 1, 1),
            gender="Male",
            nationality="Nigeria",
            state_of_origin="Lagos",
            lga="Ikeja",
            employment_status="Employed",
            residence_country="Nigeria",
            residence_state="Lagos",
            residence_city="Ikeja",
            residence_lga="Ikeja",
            residence_address="1 Test Street",
            length_of_stay="2 years",
            housing_status="Rented",
            status=TenantProfile.Status.APPROVED,
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
        listing = Listing.objects.create(
            landlord=landlord,
            title="Bronze Access Listing",
            description="Listing for messaging",
            address="1 Access Street",
            city="Lagos",
            property_type="Apartment",
            bedrooms=1,
            bathrooms=1,
            price_per_year=1000000,
            status=Listing.Status.AVAILABLE,
        )

        client = APIClient()
        client.force_authenticate(user=tenant)
        response = client.post(
            "/api/v1/messages",
            {
                "receiver_id": str(landlord.id),
                "listing_id": str(listing.id),
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
        listing = Listing.objects.create(
            landlord=landlord,
            title="Silver Access Listing",
            description="Listing for messaging",
            address="2 Access Street",
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
                "content": "I would like to arrange a viewing.",
            },
            format="json",
        )
        conversations_response = client.get("/api/v1/messages")

        self.assertEqual(create_response.status_code, 201, create_response.json())
        self.assertEqual(conversations_response.status_code, 200, conversations_response.json())

    def test_tenant_without_completed_profile_cannot_contact_landlord(self):
        tenant = AppUser.objects.create_user(
            email="message-incomplete-profile-tenant@example.com",
            password="password-123",
            name="Incomplete Profile Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        VerificationRequest.objects.create(user=tenant, role=tenant.role, status=VerificationRequest.Status.APPROVED)
        landlord = self.create_landlord("message-incomplete-profile-landlord@example.com")
        create_active_subscription(tenant, SubscriptionPayment.PlanCode.SILVER)
        create_active_subscription(landlord, SubscriptionPayment.PlanCode.SILVER)
        listing = Listing.objects.create(
            landlord=landlord,
            title="Profile Gate Listing",
            description="Listing for messaging",
            address="3 Access Street",
            city="Lagos",
            property_type="Apartment",
            bedrooms=1,
            bathrooms=1,
            price_per_year=1000000,
            status=Listing.Status.AVAILABLE,
        )

        client = APIClient()
        client.force_authenticate(user=tenant)
        response = client.post(
            "/api/v1/messages",
            {
                "receiver_id": str(landlord.id),
                "listing_id": str(listing.id),
                "content": "I would like to arrange a viewing.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403, response.json())
        self.assertFalse(Message.objects.filter(sender=tenant, receiver=landlord).exists())

    def test_bronze_tenant_cannot_read_landlord_conversations(self):
        tenant = self.create_verified_tenant("message-bronze-history-tenant@example.com")
        landlord = self.create_landlord("message-bronze-history-landlord@example.com")
        create_active_subscription(tenant, SubscriptionPayment.PlanCode.BRONZE, days=14)
        Message.objects.create(
            sender=tenant,
            receiver=landlord,
            sender_role=AppUser.Role.TENANT,
            receiver_role=AppUser.Role.LANDLORD,
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
        listing = Listing.objects.create(
            landlord=landlord,
            title="Bronze Landlord Listing",
            description="Listing for messaging",
            address="4 Access Street",
            city="Lagos",
            property_type="Apartment",
            bedrooms=1,
            bathrooms=1,
            price_per_year=1000000,
            status=Listing.Status.AVAILABLE,
        )

        client = APIClient()
        client.force_authenticate(user=tenant)
        response = client.post(
            "/api/v1/messages",
            {
                "receiver_id": str(landlord.id),
                "listing_id": str(listing.id),
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
        listing = Listing.objects.create(
            landlord=landlord,
            title="Bronze Sender Listing",
            description="Listing for messaging",
            address="5 Access Street",
            city="Lagos",
            property_type="Apartment",
            bedrooms=1,
            bathrooms=1,
            price_per_year=1000000,
            status=Listing.Status.AVAILABLE,
        )

        client = APIClient()
        client.force_authenticate(user=landlord)
        response = client.post(
            "/api/v1/messages",
            {
                "receiver_id": str(tenant.id),
                "listing_id": str(listing.id),
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
            role=tenant.role,
            status=VerificationRequest.Status.APPROVED,
        )
        TenantProfile.objects.create(
            user=tenant,
            first_name="Verified",
            last_name="Tenant",
            date_of_birth=date(1990, 1, 1),
            gender="Male",
            nationality="Nigeria",
            state_of_origin="Lagos",
            lga="Ikeja",
            employment_status="Employed",
            residence_country="Nigeria",
            residence_state="Lagos",
            residence_city="Ikeja",
            residence_lga="Ikeja",
            residence_address="1 Test Street",
            length_of_stay="2 years",
            housing_status="Rented",
            status=TenantProfile.Status.APPROVED,
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
            sender_role=AppUser.Role.TENANT,
            receiver_role=AppUser.Role.LANDLORD,
            listing=listing,
            content="Viewing Availability: Tomorrow by 6 pm\n\nHi, can I view your house?",
        )
        Message.objects.create(
            sender=tenant,
            receiver=landlord,
            sender_role=AppUser.Role.TENANT,
            receiver_role=AppUser.Role.LANDLORD,
            listing=listing,
            content="Let me know if you are available",
        )
        latest_message = Message.objects.create(
            sender=tenant,
            receiver=landlord,
            sender_role=AppUser.Role.TENANT,
            receiver_role=AppUser.Role.LANDLORD,
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

    def test_landlord_enquiries_exclude_non_landlord_context_messages_on_their_listing(self):
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
            sender_role=AppUser.Role.TENANT,
            receiver_role=AppUser.Role.ADMIN,
            listing=listing,
            content="I sent this about the landlord listing.",
        )

        client = APIClient()
        client.force_authenticate(user=landlord)
        response = client.get("/api/v1/messages/enquiries")

        self.assertEqual(response.status_code, 200, response.json())
        # A tenant->admin message that merely references the listing is private
        # and must not surface in the landlord's persona inbox.
        self.assertEqual(response.json(), [])

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
        Message.objects.create(sender=tenant, receiver=landlord, sender_role=AppUser.Role.TENANT, receiver_role=AppUser.Role.LANDLORD, listing=listing, content="Tenant enquiry")
        reply = Message.objects.create(sender=landlord, receiver=tenant, sender_role=AppUser.Role.LANDLORD, receiver_role=AppUser.Role.TENANT, listing=listing, content="Landlord reply")
        Message.objects.create(sender=other_tenant, receiver=landlord, sender_role=AppUser.Role.TENANT, receiver_role=AppUser.Role.LANDLORD, listing=listing, content="Other tenant enquiry")

        client = APIClient()
        client.force_authenticate(user=landlord)
        response = client.get(f"/api/v1/messages/listing/{listing.id}?counterpart_id={tenant.id}")

        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        self.assertEqual([item["content"] for item in payload], ["Tenant enquiry", "Landlord reply"])
        self.assertEqual(payload[1]["id"], str(reply.id))

    def _viewing_booked_setup(self, email_prefix="viewing-booked"):
        landlord = AppUser.objects.create_user(
            email=f"{email_prefix}-landlord@example.com",
            password="password-123",
            name="Viewing Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        tenant = self.create_verified_tenant(
            f"{email_prefix}-tenant@example.com",
            name="Viewing Tenant",
        )
        create_active_subscription(tenant, SubscriptionPayment.PlanCode.SILVER)
        listing = Listing.objects.create(
            landlord=landlord,
            title="Viewing Booked Listing",
            description="Listing used for viewing booked tests",
            address="7 Viewing Street",
            city="Lagos",
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=1500000,
            status=Listing.Status.AVAILABLE,
        )
        return landlord, tenant, listing

    def test_tenant_can_mark_viewing_booked_after_messaging_landlord(self):
        landlord, tenant, listing = self._viewing_booked_setup()
        Message.objects.create(
            sender=tenant,
            receiver=landlord,
            sender_role=AppUser.Role.TENANT,
            receiver_role=AppUser.Role.LANDLORD,
            listing=listing,
            content="Viewing Availability: Saturday afternoon\n\nI would like to arrange a viewing.",
        )

        client = APIClient()
        client.force_authenticate(tenant)
        response = client.post(
            "/api/v1/messages/viewing-booked",
            {"listing_id": str(listing.id)},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        booking = Booking.objects.get(tenant=tenant, listing=listing)
        self.assertIsNone(booking.total_amount)
        self.assertIn("viewing_appointment_booked", booking.tenant_rental_progress)
        self.assertFalse(response.json()["rental_process_started"])

        landlord_client = APIClient()
        landlord_client.force_authenticate(landlord)
        bookings_response = landlord_client.get("/api/v1/bookings")
        self.assertEqual(bookings_response.status_code, 200, bookings_response.json())
        results = bookings_response.json()
        if isinstance(results, dict):
            results = results.get("results", [])
        booking_payload = next(item for item in results if item["id"] == str(booking.id))
        self.assertIsNotNone(booking_payload["tenant_screening_summary"])

        repeat_response = client.post(
            "/api/v1/messages/viewing-booked",
            {"listing_id": str(listing.id)},
            format="json",
        )
        self.assertEqual(repeat_response.status_code, 200, repeat_response.json())
        self.assertEqual(repeat_response.json()["id"], str(booking.id))
        self.assertEqual(Booking.objects.filter(tenant=tenant, listing=listing).count(), 1)

    def test_tenant_cannot_mark_viewing_booked_without_tenant_message(self):
        landlord, tenant, listing = self._viewing_booked_setup(email_prefix="viewing-no-message")
        Message.objects.create(
            sender=landlord,
            receiver=tenant,
            sender_role=AppUser.Role.LANDLORD,
            receiver_role=AppUser.Role.TENANT,
            listing=listing,
            content="Hello, let me know if you have questions about the listing.",
        )

        client = APIClient()
        client.force_authenticate(tenant)
        response = client.post(
            "/api/v1/messages/viewing-booked",
            {"listing_id": str(listing.id)},
            format="json",
        )

        self.assertEqual(response.status_code, 403, response.json())
        self.assertFalse(Booking.objects.filter(tenant=tenant, listing=listing).exists())

    def _role_context_listing(self, landlord, title="Role Context Listing"):
        return Listing.objects.create(
            landlord=landlord,
            title=title,
            description="Listing for messaging",
            address="7 Context Street",
            city="Lagos",
            property_type="Apartment",
            bedrooms=1,
            bathrooms=1,
            price_per_year=1000000,
            status=Listing.Status.AVAILABLE,
        )

    def _create_landlord(self, email):
        return AppUser.objects.create_user(
            email=email,
            password="password-123",
            name="Context Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )

    def test_messages_persist_role_context(self):
        tenant = self.create_verified_tenant("role-context-tenant@example.com")
        landlord = self._create_landlord("role-context-landlord@example.com")
        create_active_subscription(tenant, SubscriptionPayment.PlanCode.SILVER)
        create_active_subscription(landlord, SubscriptionPayment.PlanCode.SILVER)
        listing = self._role_context_listing(landlord)

        client = APIClient()
        client.force_authenticate(user=tenant)
        tenant_response = client.post(
            "/api/v1/messages",
            {
                "receiver_id": str(landlord.id),
                "listing_id": str(listing.id),
                "content": "Is this still available?",
            },
            format="json",
        )
        self.assertEqual(tenant_response.status_code, 201, tenant_response.json())
        tenant_message = Message.objects.get(id=tenant_response.json()["id"])
        self.assertEqual(tenant_message.sender_role, AppUser.Role.TENANT)
        self.assertEqual(tenant_message.receiver_role, AppUser.Role.LANDLORD)
        self.assertEqual(tenant_response.json()["sender_role"], AppUser.Role.TENANT)
        self.assertEqual(tenant_response.json()["receiver_role"], AppUser.Role.LANDLORD)

        client.force_authenticate(user=landlord)
        landlord_response = client.post(
            "/api/v1/messages",
            {
                "receiver_id": str(tenant.id),
                "listing_id": str(listing.id),
                "content": "Yes, it is available.",
            },
            format="json",
        )
        self.assertEqual(landlord_response.status_code, 201, landlord_response.json())
        landlord_message = Message.objects.get(id=landlord_response.json()["id"])
        self.assertEqual(landlord_message.sender_role, AppUser.Role.LANDLORD)
        self.assertEqual(landlord_message.receiver_role, AppUser.Role.TENANT)

    def test_messages_reject_invalid_counterparts(self):
        tenant = self.create_verified_tenant("invalid-counterpart-tenant@example.com")
        landlord = self._create_landlord("invalid-counterpart-landlord@example.com")
        other_landlord = self._create_landlord("invalid-counterpart-other@example.com")
        create_active_subscription(tenant, SubscriptionPayment.PlanCode.SILVER)
        create_active_subscription(landlord, SubscriptionPayment.PlanCode.SILVER)
        create_active_subscription(other_landlord, SubscriptionPayment.PlanCode.SILVER)
        listing = self._role_context_listing(landlord)

        client = APIClient()
        client.force_authenticate(user=tenant)
        response = client.post(
            "/api/v1/messages",
            {
                "receiver_id": str(other_landlord.id),
                "listing_id": str(listing.id),
                "content": "Wrong landlord",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.json())

        client.force_authenticate(user=landlord)
        response = client.post(
            "/api/v1/messages",
            {
                "receiver_id": str(tenant.id),
                "listing_id": str(self._role_context_listing(other_landlord).id),
                "content": "Not my listing",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.json())

        response = client.post(
            "/api/v1/messages",
            {
                "receiver_id": str(other_landlord.id),
                "listing_id": str(listing.id),
                "content": "Receiver is not a tenant",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.json())
        self.assertFalse(Message.objects.exists())

    def test_multi_role_user_cannot_message_own_listing(self):
        landlord = self._create_landlord("self-listing-sender@example.com")
        UserRole.objects.create(user=landlord, role=AppUser.Role.TENANT)
        TenantProfile.objects.create(
            user=landlord,
            first_name="Self",
            last_name="Listing",
            date_of_birth=date(1990, 1, 1),
            gender="Male",
            nationality="Nigeria",
            state_of_origin="Lagos",
            lga="Ikeja",
            employment_status="Employed",
            residence_country="Nigeria",
            residence_state="Lagos",
            residence_city="Ikeja",
            residence_lga="Ikeja",
            residence_address="1 Test Street",
            length_of_stay="2 years",
            housing_status="Rented",
            status=TenantProfile.Status.APPROVED,
        )
        VerificationRequest.objects.create(
            user=landlord,
            role=AppUser.Role.TENANT,
            status=VerificationRequest.Status.APPROVED,
        )
        SubscriptionPayment.objects.create(
            user=landlord,
            role=AppUser.Role.TENANT,
            plan_code=SubscriptionPayment.PlanCode.SILVER,
            billing_cycle=SubscriptionPayment.BillingCycle.MONTHLY,
            amount=100,
            currency="NGN",
            status=SubscriptionPayment.Status.COMPLETED,
            transaction_id=f"SUBTESTSELFTEN{landlord.id.hex[:20]}",
            payment_date=timezone.now(),
            expires_at=timezone.now() + timedelta(days=30),
        )
        listing = self._role_context_listing(landlord)
        token = str(RefreshToken.for_user(landlord).access_token)

        client = APIClient()
        client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {token}",
            HTTP_X_RENTDIRECT_ROLE=AppUser.Role.TENANT,
        )
        response = client.post(
            "/api/v1/messages",
            {
                "receiver_id": str(landlord.id),
                "listing_id": str(listing.id),
                "content": "Messaging my own listing",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.json())
        self.assertFalse(Message.objects.exists())

    def test_message_list_isolated_by_active_persona(self):
        user = self.create_verified_tenant("persona-isolation-user@example.com")
        UserRole.objects.create(user=user, role=AppUser.Role.TENANT)
        UserRole.objects.create(user=user, role=AppUser.Role.LANDLORD)
        create_active_subscription(user, SubscriptionPayment.PlanCode.SILVER)
        other_landlord = self._create_landlord("persona-isolation-landlord@example.com")
        other_tenant = self.create_verified_tenant("persona-isolation-tenant@example.com")
        their_listing = self._role_context_listing(other_landlord)
        own_listing = self._role_context_listing(user, title="Own Listing")
        Message.objects.create(
            sender=user,
            receiver=other_landlord,
            sender_role=AppUser.Role.TENANT,
            receiver_role=AppUser.Role.LANDLORD,
            listing=their_listing,
            content="Tenant persona enquiry",
        )
        Message.objects.create(
            sender=other_tenant,
            receiver=user,
            sender_role=AppUser.Role.TENANT,
            receiver_role=AppUser.Role.LANDLORD,
            listing=own_listing,
            content="Landlord persona enquiry",
        )

        client = APIClient()
        client.force_authenticate(user=user)
        tenant_response = client.get("/api/v1/messages")
        self.assertEqual(tenant_response.status_code, 200, tenant_response.json())
        tenant_results = tenant_response.json()
        tenant_results = (
            tenant_results["results"]
            if isinstance(tenant_results, dict) and "results" in tenant_results
            else tenant_results
        )
        self.assertEqual([item["content"] for item in tenant_results], ["Tenant persona enquiry"])

        token = str(RefreshToken.for_user(user).access_token)
        landlord_client = APIClient()
        landlord_client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {token}",
            HTTP_X_RENTDIRECT_ROLE=AppUser.Role.LANDLORD,
        )
        landlord_response = landlord_client.get("/api/v1/messages")
        self.assertEqual(landlord_response.status_code, 200, landlord_response.json())
        landlord_results = landlord_response.json()
        landlord_results = (
            landlord_results["results"]
            if isinstance(landlord_results, dict) and "results" in landlord_results
            else landlord_results
        )
        self.assertEqual(
            [item["content"] for item in landlord_results], ["Landlord persona enquiry"]
        )


class TenantPublicProfileTests(TestCase):
    def test_public_tenant_profile_reports_tenant_role_for_legacy_landlord(self):
        user = AppUser.objects.create_user(
            email="legacy-landlord-tenant@example.com",
            password="password-123",
            name="Legacy Landlord Tenant",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        UserRole.objects.create(user=user, role=AppUser.Role.TENANT)
        UserRole.objects.create(user=user, role=AppUser.Role.LANDLORD)
        TenantProfile.objects.create(
            user=user,
            status=TenantProfile.Status.APPROVED,
            first_name="Legacy",
            last_name="Landlord",
            date_of_birth=date(1990, 1, 1),
            gender="Male",
            nationality="Nigeria",
            state_of_origin="Lagos",
            lga="Ikeja",
            employment_status="Employed",
            residence_country="Nigeria",
            residence_state="Lagos",
            residence_city="Ikeja",
            residence_lga="Ikeja",
            residence_address="1 Test Street",
            length_of_stay="2 years",
            housing_status="Rented",
        )

        response = APIClient().get(f"/api/v1/users/tenants/{user.id}/public-profile")

        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        self.assertEqual(payload["role"], AppUser.Role.TENANT)
        self.assertTrue(payload["is_verified"])

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
            social_presence={
                "email": "hidden@example.com",
                "mobile": "08000000000",
                "linkedin_profile": "https://linkedin.com/in/jade",
            },
            criminal_declaration={"convicted_of_crime": False},
        )

        response = APIClient().get(f"/api/v1/users/tenants/{tenant.id}/public-profile")

        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        self.assertEqual(payload["name"], "Jade Bola Smith")
        self.assertTrue(payload["is_verified"])
        self.assertNotIn("email", payload)
        self.assertNotIn("mobile", payload)
        self.assertNotIn("email", payload["tenant_profile"]["social_presence"])
        self.assertNotIn("mobile", payload["tenant_profile"]["social_presence"])
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
        CommunityChatMessage.objects.create(sender=other_tenant, role=AppUser.Role.TENANT, content="Hello tenants.")
        CommunityChatMessage.objects.create(sender=landlord, role=AppUser.Role.LANDLORD, content="Hello landlords.")

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
        CommunityChatMessage.objects.create(sender=tenant, role=AppUser.Role.TENANT, content="Welcome tenants.")
        CommunityChatMessage.objects.create(sender=other_landlord, role=AppUser.Role.LANDLORD, content="Welcome landlords.")

        client = APIClient()
        client.force_authenticate(user=landlord)
        response = client.get("/api/v1/community-chat/messages")

        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        results = payload["results"] if isinstance(payload, dict) and "results" in payload else payload
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["content"], "Welcome landlords.")

    def test_community_history_isolated_by_stored_role_for_multi_role_sender(self):
        user = AppUser.objects.create_user(
            email="community-multi@example.com",
            password="password-123",
            name="Community Multi",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        UserRole.objects.create(user=user, role=AppUser.Role.TENANT)
        UserRole.objects.create(user=user, role=AppUser.Role.LANDLORD)
        self.activate_gold_subscription(user)
        SubscriptionPayment.objects.create(
            user=user,
            role=AppUser.Role.LANDLORD,
            plan_code=SubscriptionPayment.PlanCode.GOLD,
            billing_cycle=SubscriptionPayment.BillingCycle.MONTHLY,
            amount=100,
            currency="NGN",
            status=SubscriptionPayment.Status.COMPLETED,
            transaction_id=f"SUBTESTGOLDLL{user.id.hex[:20]}",
            payment_date=timezone.now(),
            expires_at=timezone.now() + timedelta(days=30),
        )
        CommunityChatMessage.objects.create(
            sender=user, role=AppUser.Role.TENANT, content="Tenant persona message."
        )
        CommunityChatMessage.objects.create(
            sender=user, role=AppUser.Role.LANDLORD, content="Landlord persona message."
        )

        client = APIClient()
        client.force_authenticate(user=user)
        tenant_response = client.get("/api/v1/community-chat/messages")
        self.assertEqual(tenant_response.status_code, 200, tenant_response.json())
        tenant_results = tenant_response.json()
        tenant_results = (
            tenant_results["results"]
            if isinstance(tenant_results, dict) and "results" in tenant_results
            else tenant_results
        )
        self.assertEqual([item["content"] for item in tenant_results], ["Tenant persona message."])

        token = str(RefreshToken.for_user(user).access_token)
        landlord_client = APIClient()
        landlord_client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {token}",
            HTTP_X_RENTDIRECT_ROLE=AppUser.Role.LANDLORD,
        )
        landlord_response = landlord_client.get("/api/v1/community-chat/messages")
        self.assertEqual(landlord_response.status_code, 200, landlord_response.json())
        landlord_results = landlord_response.json()
        landlord_results = (
            landlord_results["results"]
            if isinstance(landlord_results, dict) and "results" in landlord_results
            else landlord_results
        )
        self.assertEqual([item["content"] for item in landlord_results], ["Landlord persona message."])


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
        SupportChatMessage.objects.create(thread_user=tenant, thread_role=AppUser.Role.TENANT, sender=tenant, sender_role=AppUser.Role.TENANT, content="I need help.")
        SupportChatMessage.objects.create(thread_user=other_tenant, thread_role=AppUser.Role.TENANT, sender=admin, sender_role=AppUser.Role.ADMIN, content="Other tenant reply.")

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
        SupportChatMessage.objects.create(thread_user=landlord, thread_role=AppUser.Role.LANDLORD, sender=landlord, sender_role=AppUser.Role.LANDLORD, content="I need listing help.")
        SupportChatMessage.objects.create(thread_user=other_landlord, thread_role=AppUser.Role.LANDLORD, sender=other_landlord, sender_role=AppUser.Role.LANDLORD, content="Other landlord issue.")

        client = APIClient()
        client.force_authenticate(user=landlord)
        response = client.get("/api/v1/support-chat/messages")

        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        results = payload["results"] if isinstance(payload, dict) and "results" in payload else payload
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["content"], "I need listing help.")

    def test_support_history_isolated_by_thread_role(self):
        user = AppUser.objects.create_user(
            email="support-multi@example.com",
            password="password-123",
            name="Support Multi",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        UserRole.objects.create(user=user, role=AppUser.Role.TENANT)
        UserRole.objects.create(user=user, role=AppUser.Role.LANDLORD)
        admin = AppUser.objects.create_user(
            email="support-multi-admin@example.com",
            password="password-123",
            name="Support Admin",
            role=AppUser.Role.ADMIN,
            email_verified=True,
            is_staff=True,
        )
        SupportChatMessage.objects.create(
            thread_user=user,
            thread_role=AppUser.Role.TENANT,
            sender=user,
            sender_role=AppUser.Role.TENANT,
            content="Tenant thread message.",
        )
        SupportChatMessage.objects.create(
            thread_user=user,
            thread_role=AppUser.Role.LANDLORD,
            sender=user,
            sender_role=AppUser.Role.LANDLORD,
            content="Landlord thread message.",
        )
        SupportChatMessage.objects.create(
            thread_user=user,
            thread_role=AppUser.Role.LANDLORD,
            sender=admin,
            sender_role=AppUser.Role.ADMIN,
            content="Admin reply on landlord thread.",
        )

        client = APIClient()
        client.force_authenticate(user=user)
        tenant_response = client.get("/api/v1/support-chat/messages")
        self.assertEqual(tenant_response.status_code, 200, tenant_response.json())
        tenant_results = tenant_response.json()
        tenant_results = (
            tenant_results["results"]
            if isinstance(tenant_results, dict) and "results" in tenant_results
            else tenant_results
        )
        self.assertEqual(
            [item["content"] for item in tenant_results], ["Tenant thread message."]
        )

        token = str(RefreshToken.for_user(user).access_token)
        landlord_client = APIClient()
        landlord_client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {token}",
            HTTP_X_RENTDIRECT_ROLE=AppUser.Role.LANDLORD,
        )
        landlord_response = landlord_client.get("/api/v1/support-chat/messages")
        self.assertEqual(landlord_response.status_code, 200, landlord_response.json())
        landlord_results = landlord_response.json()
        landlord_results = (
            landlord_results["results"]
            if isinstance(landlord_results, dict) and "results" in landlord_results
            else landlord_results
        )
        self.assertEqual(
            [item["content"] for item in landlord_results],
            ["Admin reply on landlord thread.", "Landlord thread message."],
        )
        admin_message = next(
            item for item in landlord_results if item["content"] == "Admin reply on landlord thread."
        )
        self.assertEqual(admin_message["sender_role"], AppUser.Role.ADMIN)
        self.assertEqual(admin_message["thread_role"], AppUser.Role.LANDLORD)

    def test_admin_can_select_support_thread_role_with_validation(self):
        user = AppUser.objects.create_user(
            email="support-select@example.com",
            password="password-123",
            name="Support Select",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        UserRole.objects.create(user=user, role=AppUser.Role.TENANT)
        admin = AppUser.objects.create_user(
            email="support-select-admin@example.com",
            password="password-123",
            name="Support Admin",
            role=AppUser.Role.ADMIN,
            email_verified=True,
            is_staff=True,
        )
        SupportChatMessage.objects.create(
            thread_user=user,
            thread_role=AppUser.Role.TENANT,
            sender=user,
            sender_role=AppUser.Role.TENANT,
            content="Tenant thread only.",
        )

        client = APIClient()
        client.force_authenticate(user=admin)
        response = client.get(
            f"/api/v1/support-chat/messages?thread_user={user.id}&thread_role=landlord"
        )
        self.assertEqual(response.status_code, 403)

        response = client.get(
            f"/api/v1/support-chat/messages?thread_user={user.id}&thread_role=tenant"
        )
        self.assertEqual(response.status_code, 200, response.json())
        results = response.json()
        results = (
            results["results"]
            if isinstance(results, dict) and "results" in results
            else results
        )
        self.assertEqual([item["content"] for item in results], ["Tenant thread only."])
        self.assertEqual(results[0]["sender_role"], AppUser.Role.TENANT)

    def test_admin_can_list_support_threads_grouped_by_role(self):
        tenant = AppUser.objects.create_user(
            email="thread-tenant@example.com",
            password="password-123",
            name="Thread Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        agent = AppUser.objects.create_user(
            email="thread-agent@example.com",
            password="password-123",
            name="Thread Agent",
            role=AppUser.Role.AGENT,
            email_verified=True,
        )
        admin = AppUser.objects.create_user(
            email="thread-admin@example.com",
            password="password-123",
            name="Thread Admin",
            role=AppUser.Role.ADMIN,
            email_verified=True,
            is_staff=True,
        )
        SupportChatMessage.objects.create(thread_user=tenant, thread_role=AppUser.Role.TENANT, sender=tenant, sender_role=AppUser.Role.TENANT, content="Tenant help please.")
        SupportChatMessage.objects.create(thread_user=tenant, thread_role=AppUser.Role.TENANT, sender=admin, sender_role=AppUser.Role.ADMIN, content="Admin reply to tenant.")
        SupportChatMessage.objects.create(thread_user=agent, thread_role=AppUser.Role.AGENT, sender=agent, sender_role=AppUser.Role.AGENT, content="PIO help please.")

        client = APIClient()
        client.force_authenticate(user=admin)

        response = client.get("/api/v1/support-chat/messages/threads")
        self.assertEqual(response.status_code, 200, response.json())
        threads = response.json()
        self.assertEqual(len(threads), 2)
        by_user = {thread["thread_user_id"]: thread for thread in threads}
        tenant_thread = by_user[str(tenant.id)]
        self.assertEqual(tenant_thread["thread_role"], AppUser.Role.TENANT)
        self.assertEqual(tenant_thread["last_message"], "Admin reply to tenant.")
        self.assertTrue(tenant_thread["is_last_from_support"])
        self.assertEqual(tenant_thread["message_count"], 2)
        self.assertEqual(tenant_thread["user_email"], tenant.email)

        filtered = client.get("/api/v1/support-chat/messages/threads?thread_role=agent")
        self.assertEqual(filtered.status_code, 200, filtered.json())
        filtered_threads = filtered.json()
        self.assertEqual(len(filtered_threads), 1)
        self.assertEqual(filtered_threads[0]["thread_role"], AppUser.Role.AGENT)
        self.assertEqual(filtered_threads[0]["last_message"], "PIO help please.")
        self.assertFalse(filtered_threads[0]["is_last_from_support"])

    def test_non_admin_cannot_list_support_threads(self):
        tenant = AppUser.objects.create_user(
            email="thread-denied@example.com",
            password="password-123",
            name="Denied Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        client = APIClient()
        client.force_authenticate(user=tenant)
        response = client.get("/api/v1/support-chat/messages/threads")
        self.assertEqual(response.status_code, 403)


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
            role=landlord.role,
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
            sender_role=AppUser.Role.TENANT,
            receiver_role=AppUser.Role.LANDLORD,
            listing=listing_one,
            content="Is the apartment still available?",
        )
        outbound = Message.objects.create(
            sender=landlord,
            receiver=tenant,
            sender_role=AppUser.Role.LANDLORD,
            receiver_role=AppUser.Role.TENANT,
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
        self.assertNotIn("email", payload)
        self.assertNotIn("mobile", payload)
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
            tenant_rental_progress={"tenant_collected_house_key": timezone.now().isoformat()},
        )

        call_command("send_renewal_reminders")
        call_command("send_renewal_reminders")

        booking.refresh_from_db()
        self.assertIsNotNone(booking.renewal_reminder_sent_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("tenancy renewal reminder", mail.outbox[0].subject.lower())
        self.assertEqual(set(mail.outbox[0].to), {tenant.email, landlord.email})
        self.assertEqual(mail.outbox[0].cc, [settings.RENT_RENEWAL_EMAIL])

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        RENT_RENEWAL_WHATSAPP_NUMBER="+2348000000000",
    )
    @patch("core.management.commands.send_renewal_reminders.send_whatsapp_message")
    @patch("core.management.commands.send_renewal_reminders.send_whatsapp_alert_for_user")
    def test_command_notifies_tenant_landlord_and_internal_contacts(self, alert_mock, message_mock):
        tenant = AppUser.objects.create_user(
            email="renewal-whatsapp-tenant@example.com",
            password="password-123",
            name="Renewal WhatsApp Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
            whatsapp_number="+2348111111111",
        )
        landlord = AppUser.objects.create_user(
            email="renewal-whatsapp-landlord@example.com",
            password="password-123",
            name="Renewal WhatsApp Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
            whatsapp_number="+2348222222222",
        )
        listing = Listing.objects.create(
            landlord=landlord,
            title="Renewal WhatsApp Listing",
            description="Renewal whatsapp test",
            address="20 Renewal Close",
            city="Lagos",
            property_type="Apartment",
            bedrooms=1,
            bathrooms=1,
            price_per_year=1800000,
        )
        booking = Booking.objects.create(
            tenant=tenant,
            listing=listing,
            start_date=date.today() - timedelta(days=200),
            end_date=date.today() + timedelta(days=45),
            status=Booking.Status.ACTIVE,
            total_amount=calculate_booking_total(listing.price_per_year),
            tenant_rental_progress={"tenant_collected_house_key": timezone.now().isoformat()},
        )

        call_command("send_renewal_reminders")
        call_command("send_renewal_reminders")

        self.assertEqual(len(mail.outbox), 1)
        reminder_email = mail.outbox[0]
        self.assertIn("tenancy renewal reminder", reminder_email.subject.lower())
        self.assertEqual(set(reminder_email.to), {tenant.email, landlord.email})
        self.assertEqual(reminder_email.cc, [settings.RENT_RENEWAL_EMAIL])
        self.assertIn("re-listing", reminder_email.body.lower())
        self.assertEqual(alert_mock.call_count, 2)
        self.assertEqual(
            {call.args[0].id for call in alert_mock.call_args_list},
            {tenant.id, landlord.id},
        )
        message_mock.assert_called_once()
        self.assertEqual(message_mock.call_args.args[0], "+2348000000000")

        booking.refresh_from_db()
        self.assertIsNotNone(booking.renewal_reminder_sent_at)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_command_skips_bookings_without_tenant_key_confirmation(self):
        tenant = AppUser.objects.create_user(
            email="renewal-unconfirmed-tenant@example.com",
            password="password-123",
            name="Unconfirmed Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        landlord = AppUser.objects.create_user(
            email="renewal-unconfirmed-landlord@example.com",
            password="password-123",
            name="Unconfirmed Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        listing = Listing.objects.create(
            landlord=landlord,
            title="Unconfirmed Listing",
            description="No key confirmation",
            address="7 Pending Street",
            city="Abuja",
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=2000000,
        )
        booking = Booking.objects.create(
            tenant=tenant,
            listing=listing,
            start_date=date.today() - timedelta(days=180),
            end_date=date.today() + timedelta(days=30),
            status=Booking.Status.CONFIRMED,
            total_amount=calculate_booking_total(listing.price_per_year),
            landlord_rental_progress={"tenant_collected_house_key": timezone.now().isoformat()},
        )

        call_command("send_renewal_reminders")

        booking.refresh_from_db()
        self.assertIsNone(booking.renewal_reminder_sent_at)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_command_completes_expired_tenancies_and_relists(self):
        tenant = AppUser.objects.create_user(
            email="expired-tenant@example.com",
            password="password-123",
            name="Expired Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        landlord = AppUser.objects.create_user(
            email="expired-landlord@example.com",
            password="password-123",
            name="Expired Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        listing = Listing.objects.create(
            landlord=landlord,
            title="Expired Rental",
            description="Expired tenancy test",
            address="30 Expiry Road",
            city="Abuja",
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=1500000,
            status=Listing.Status.RENTED,
        )
        hidden_listing = Listing.objects.create(
            landlord=landlord,
            title="Hidden Expired Rental",
            description="Manually hidden listing",
            address="31 Expiry Road",
            city="Abuja",
            property_type="Flat",
            bedrooms=1,
            bathrooms=1,
            price_per_year=900000,
            status=Listing.Status.RENTED,
            is_hidden=True,
        )
        booking = Booking.objects.create(
            tenant=tenant,
            listing=listing,
            start_date=date.today() - timedelta(days=400),
            end_date=date.today() + timedelta(days=30),
            status=Booking.Status.ACTIVE,
            total_amount=calculate_booking_total(listing.price_per_year),
            tenant_rental_progress={"tenant_collected_house_key": timezone.now().isoformat()},
        )
        hidden_booking = Booking.objects.create(
            tenant=tenant,
            listing=hidden_listing,
            start_date=date.today() - timedelta(days=400),
            end_date=date.today() + timedelta(days=30),
            status=Booking.Status.ACTIVE,
            total_amount=calculate_booking_total(hidden_listing.price_per_year),
            tenant_rental_progress={"tenant_collected_house_key": timezone.now().isoformat()},
        )

        # Key-confirmed rented listings stay out of public search before expiry.
        search_response = self.client.get("/api/v1/listings/search?city=Abuja")
        self.assertEqual(search_response.status_code, 200)
        search_payload = search_response.json()
        search_results = search_payload["results"] if isinstance(search_payload, dict) and "results" in search_payload else search_payload
        self.assertEqual(search_results, [])

        # Move both bookings past their end dates, then run the scheduled command.
        yesterday = date.today() - timedelta(days=1)
        booking.end_date = yesterday
        booking.save(update_fields=["end_date", "updated_at"])
        hidden_booking.end_date = yesterday
        hidden_booking.save(update_fields=["end_date", "updated_at"])

        call_command("send_renewal_reminders")

        booking.refresh_from_db()
        listing.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.COMPLETED)
        self.assertEqual(listing.status, Listing.Status.AVAILABLE)
        self.assertFalse(listing.is_hidden)

        hidden_booking.refresh_from_db()
        hidden_listing.refresh_from_db()
        self.assertEqual(hidden_booking.status, Booking.Status.COMPLETED)
        self.assertEqual(hidden_listing.status, Listing.Status.AVAILABLE)
        self.assertTrue(hidden_listing.is_hidden)

        # The re-listed property returns to public search; the manually hidden one does not.
        search_response = self.client.get("/api/v1/listings/search?city=Abuja")
        self.assertEqual(search_response.status_code, 200)
        search_payload = search_response.json()
        search_results = search_payload["results"] if isinstance(search_payload, dict) and "results" in search_payload else search_payload
        self.assertEqual(len(search_results), 1)
        self.assertEqual(search_results[0]["id"], str(listing.id))
        self.assertEqual(search_results[0]["rental_badge"], "")


def build_complete_inspection_responses(**overrides):
    responses = {}
    for section in INSPECTION_CHECKLIST_SCHEMA["sections"]:
        for field in section["fields"]:
            key = field["key"]
            field_type = field["type"]
            options = [option["value"] for option in field.get("options", [])]
            if field_type == "select":
                responses[key] = options[0]
            elif field_type == "multiselect":
                neutral = next(
                    (candidate for candidate in ("none_observed", "none") if candidate in options),
                    options[0] if options else None,
                )
                responses[key] = [neutral] if neutral else []
            elif field_type == "number":
                responses[key] = 6.5
            elif field_type == "checkbox":
                responses[key] = True
            else:
                responses[key] = "Checked on site."
    responses.update(overrides)
    return responses


class ServicePaymentTests(TestCase):
    def setUp(self):
        self.landlord = AppUser.objects.create_user(
            email="svc-landlord@example.com",
            password="password-123",
            name="Service Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        self.other_landlord = AppUser.objects.create_user(
            email="svc-other-landlord@example.com",
            password="password-123",
            name="Other Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        self.tenant = AppUser.objects.create_user(
            email="svc-tenant@example.com",
            password="password-123",
            name="Service Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        self.agent = AppUser.objects.create_user(
            email="svc-agent@example.com",
            password="password-123",
            name="Service Agent",
            role=AppUser.Role.AGENT,
            email_verified=True,
        )
        self.listing = Listing.objects.create(
            landlord=self.landlord,
            title="Service Listing",
            description="Listing used for service payment tests",
            address="10 Service Road",
            city="Lagos",
            state="Lagos",
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=2500000,
        )
        self.booking = Booking.objects.create(
            tenant=self.tenant,
            listing=self.listing,
            start_date=date(2026, 7, 1),
            end_date=date(2027, 7, 1),
            status=Booking.Status.CONFIRMED,
            total_amount=calculate_booking_total(self.listing.price_per_year),
        )
        self.client = APIClient()

    def _set_agent_awaiting_verification_payment(self):
        VerificationRequest.objects.update_or_create(
            user=self.agent,
            role=AppUser.Role.AGENT,
            defaults={
                "request_type": VerificationRequest.RequestType.IDENTIFICATION,
                "status": VerificationRequest.Status.PENDING,
                "identity_verification_status": VerificationRequest.VerificationProgressStatus.AWAITING_PAYMENT,
                "submitted_at": timezone.now(),
            },
        )

    def test_agent_request_creates_500_payment_without_booking_or_subscription(self):
        self._set_agent_awaiting_verification_payment()
        self.client.force_authenticate(user=self.agent)
        response = self.client.post(
            "/api/v1/service-payments/request",
            {"purpose": "agent_verification"},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        payload = response.json()
        self.assertEqual(payload["purpose"], "agent_verification")
        self.assertEqual(payload["status"], "pending")
        self.assertEqual(Decimal(payload["amount"]), Decimal("500.00"))
        self.assertIsNone(payload["booking_id"])
        self.assertEqual(payload["return_path"], "/agents/verification")

        payment = ServicePayment.objects.get(id=payload["id"])
        self.assertEqual(payment.amount, Decimal("500.00"))
        self.assertIsNone(payment.booking)
        self.assertFalse(SubscriptionPayment.objects.filter(user=self.agent).exists())

        self.client.force_authenticate(user=self.tenant)
        forbidden = self.client.post(
            "/api/v1/service-payments/request",
            {"purpose": "agent_verification"},
            format="json",
        )
        self.assertEqual(forbidden.status_code, 403)

    def test_in_person_verification_fee_is_category_based(self):
        def _request_for(listing):
            listing.property_document_submission = {"in_person_verification_requested": True}
            listing.save(update_fields=["property_document_submission", "updated_at"])
            self.client.force_authenticate(user=self.landlord)
            return self.client.post(
                "/api/v1/service-payments/request",
                {"purpose": "in_person_verification", "listing_id": str(listing.id)},
                format="json",
            )

        residential = _request_for(self.listing)
        self.assertEqual(residential.status_code, 201, residential.json())
        self.assertEqual(Decimal(residential.json()["amount"]), Decimal("15000.00"))

        shortlet_listing = Listing.objects.create(
            landlord=self.landlord,
            title="Shortlet Listing",
            description="Shortlet service payment test",
            address="12 Shortlet Road",
            city="Lagos",
            state="Lagos",
            property_type="Apartment",
            bedrooms=1,
            bathrooms=1,
            price_per_year=900000,
            category=Listing.Category.SHORTLET,
        )
        shortlet = _request_for(shortlet_listing)
        self.assertEqual(shortlet.status_code, 201, shortlet.json())
        self.assertEqual(Decimal(shortlet.json()["amount"]), Decimal("15000.00"))

        commercial_listing = Listing.objects.create(
            landlord=self.landlord,
            title="Commercial Listing",
            description="Commercial service payment test",
            address="20 Commerce Way",
            city="Lagos",
            state="Lagos",
            property_type="Office",
            bedrooms=0,
            bathrooms=1,
            price_per_year=5000000,
            category=Listing.Category.COMMERCIAL,
        )
        commercial = _request_for(commercial_listing)
        self.assertEqual(commercial.status_code, 201, commercial.json())
        self.assertEqual(Decimal(commercial.json()["amount"]), Decimal("25000.00"))

    def test_lawyer_request_creates_five_percent_for_booking_landlord(self):
        original_total = self.booking.total_amount
        self.client.force_authenticate(user=self.landlord)
        response = self.client.post(
            "/api/v1/service-payments/request",
            {"purpose": "lawyer_tenancy", "booking_id": str(self.booking.id)},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        payload = response.json()
        self.assertEqual(payload["purpose"], "lawyer_tenancy")
        self.assertEqual(Decimal(payload["amount"]), Decimal("125000.00"))
        self.assertEqual(payload["booking_id"], str(self.booking.id))
        self.assertEqual(
            payload["return_path"], f"/landlord/tenancy-agreements/{self.booking.id}"
        )

        self.booking.refresh_from_db()
        self.assertEqual(self.booking.total_amount, original_total)

        self.client.force_authenticate(user=self.tenant)
        tenant_response = self.client.post(
            "/api/v1/service-payments/request",
            {"purpose": "lawyer_tenancy", "booking_id": str(self.booking.id)},
            format="json",
        )
        self.assertEqual(tenant_response.status_code, 403)

        self.client.force_authenticate(user=self.other_landlord)
        other_response = self.client.post(
            "/api/v1/service-payments/request",
            {"purpose": "lawyer_tenancy", "booking_id": str(self.booking.id)},
            format="json",
        )
        self.assertEqual(other_response.status_code, 403)

    def test_lawyer_request_rejected_for_cancelled_booking(self):
        self.booking.status = Booking.Status.CANCELLED
        self.booking.save(update_fields=["status", "updated_at"])

        self.client.force_authenticate(user=self.landlord)
        response = self.client.post(
            "/api/v1/service-payments/request",
            {"purpose": "lawyer_tenancy", "booking_id": str(self.booking.id)},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            ServicePayment.objects.filter(purpose=ServicePayment.Purpose.LAWYER_TENANCY).exists()
        )

    def test_pending_request_is_reused_and_completed_request_returned(self):
        self._set_agent_awaiting_verification_payment()
        self.client.force_authenticate(user=self.agent)
        first = self.client.post(
            "/api/v1/service-payments/request",
            {"purpose": "agent_verification"},
            format="json",
        )
        self.assertEqual(first.status_code, 201, first.json())

        second = self.client.post(
            "/api/v1/service-payments/request",
            {"purpose": "agent_verification"},
            format="json",
        )
        self.assertEqual(second.status_code, 200, second.json())
        self.assertEqual(second.json()["id"], first.json()["id"])
        self.assertEqual(ServicePayment.objects.filter(user=self.agent).count(), 1)

        payment = ServicePayment.objects.get(id=first.json()["id"])
        payment.status = ServicePayment.Status.COMPLETED
        payment.payment_date = timezone.now()
        payment.save(update_fields=["status", "payment_date", "updated_at"])

        third = self.client.post(
            "/api/v1/service-payments/request",
            {"purpose": "agent_verification"},
            format="json",
        )
        self.assertEqual(third.status_code, 200, third.json())
        self.assertEqual(third.json()["id"], str(payment.id))
        self.assertEqual(third.json()["status"], "completed")
        self.assertEqual(ServicePayment.objects.filter(user=self.agent).count(), 1)

    @override_settings(
        FLUTTERWAVE_PUBLIC_KEY="test-public-key",
        FLUTTERWAVE_SECRET_KEY="test-secret-key",
        WEB_PUBLIC_URL="http://localhost:5173",
        FLUTTERWAVE_WEBHOOK_URL="https://api.example.com/api/v1/payments/webhook/flutterwave",
    )
    def test_checkout_payload_contains_metadata_payer_and_amount(self):
        payment = ServicePayment.objects.create(
            user=self.agent,
            purpose=ServicePayment.Purpose.AGENT_VERIFICATION,
            amount=Decimal("500.00"),
            transaction_id="SVCTESTCHECKOUT01",
        )
        self.client.force_authenticate(user=self.agent)
        response = self.client.post(
            f"/api/v1/service-payments/{payment.id}/flutterwave/checkout", {}, format="json"
        )

        self.assertEqual(response.status_code, 200, response.json())
        checkout = response.json()["checkout"]
        self.assertEqual(checkout["checkout_mode"], "inline")
        flutterwave_payload = checkout["flutterwave"]
        self.assertEqual(flutterwave_payload["tx_ref"], payment.transaction_id)
        self.assertEqual(flutterwave_payload["amount"], 500.0)
        self.assertEqual(flutterwave_payload["currency"], "NGN")
        self.assertEqual(flutterwave_payload["customer"]["email"], self.agent.email)
        self.assertEqual(flutterwave_payload["meta"]["service_payment_id"], str(payment.id))
        self.assertEqual(flutterwave_payload["meta"]["purpose"], "agent_verification")
        self.assertEqual(flutterwave_payload["meta"]["customer_type"], "agent")
        self.assertIn(
            f"/service-payments/{payment.id}", flutterwave_payload["redirect_url"]
        )
        self.assertIn("webhook_url", flutterwave_payload)

    @override_settings(
        FLUTTERWAVE_PUBLIC_KEY="test-public-key",
        FLUTTERWAVE_SECRET_KEY="test-secret-key",
        WEB_PUBLIC_URL="http://localhost:5173",
    )
    @patch("core.views.query_transaction")
    def test_verify_rejects_mismatches_and_successful_payload_completes(self, query_transaction_mock):
        payment = ServicePayment.objects.create(
            user=self.agent,
            purpose=ServicePayment.Purpose.AGENT_VERIFICATION,
            amount=Decimal("500.00"),
            transaction_id="SVCTESTVERIFY01",
        )
        self.client.force_authenticate(user=self.agent)
        verify_url = "/api/v1/service-payments/flutterwave/verify"

        query_transaction_mock.return_value = {
            "status": "success",
            "data": {
                "id": "9001",
                "tx_ref": "OTHER_REFERENCE",
                "status": "successful",
                "amount": "500.00",
                "currency": "NGN",
                "customer": {"email": self.agent.email},
            },
        }
        response = self.client.get(
            verify_url, {"reference": payment.transaction_id, "transaction_id": "9001"}
        )
        self.assertEqual(response.status_code, 200, response.json())
        payment.refresh_from_db()
        self.assertEqual(payment.status, ServicePayment.Status.FAILED)

        payment.status = ServicePayment.Status.PENDING
        payment.save(update_fields=["status", "updated_at"])
        query_transaction_mock.return_value = {
            "status": "success",
            "data": {
                "id": "9001",
                "tx_ref": payment.transaction_id,
                "status": "successful",
                "amount": "9000.00",
                "currency": "NGN",
                "customer": {"email": self.agent.email},
            },
        }
        response = self.client.get(
            verify_url, {"reference": payment.transaction_id, "transaction_id": "9001"}
        )
        self.assertEqual(response.status_code, 200, response.json())
        payment.refresh_from_db()
        self.assertEqual(payment.status, ServicePayment.Status.FAILED)

        payment.status = ServicePayment.Status.PENDING
        payment.save(update_fields=["status", "updated_at"])
        query_transaction_mock.return_value = {
            "status": "success",
            "data": {
                "id": "9001",
                "tx_ref": payment.transaction_id,
                "status": "successful",
                "amount": "500.00",
                "currency": "NGN",
                "customer": {"email": self.agent.email},
            },
        }
        response = self.client.get(
            verify_url, {"reference": payment.transaction_id, "transaction_id": "9001"}
        )
        self.assertEqual(response.status_code, 200, response.json())
        payment.refresh_from_db()
        self.assertEqual(payment.status, ServicePayment.Status.COMPLETED)
        self.assertIsNotNone(payment.payment_date)

    @override_settings(
        ENFORCE_FLUTTERWAVE_WEBHOOK_SIGNATURE=False,
        FLUTTERWAVE_WEBHOOK_SECRET_HASH="",
    )
    def test_webhook_resolves_and_completes_service_payment(self):
        payment = ServicePayment.objects.create(
            user=self.agent,
            purpose=ServicePayment.Purpose.AGENT_VERIFICATION,
            amount=Decimal("500.00"),
            transaction_id="SVCTESTWEBHOOK01",
        )

        response = self.client.post(
            "/api/v1/payments/webhook/flutterwave",
            {
                "type": "charge.completed",
                "data": {
                    "tx_ref": payment.transaction_id,
                    "reference": payment.transaction_id,
                    "status": "successful",
                    "amount": 500.0,
                    "currency": "NGN",
                    "customer": {"email": self.agent.email},
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.json())
        payment.refresh_from_db()
        self.assertEqual(payment.status, ServicePayment.Status.COMPLETED)
        self.assertIsNotNone(payment.payment_date)
        self.assertIsNotNone(payment.webhook_data)


class AgentFeatureTests(TestCase):
    def setUp(self):
        self.landlord = AppUser.objects.create_user(
            email="agent-feature-landlord@example.com",
            password="password-123",
            name="Inspection Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        self.agent = AppUser.objects.create_user(
            email="agent-feature-agent@example.com",
            password="password-123",
            name="Inspection Agent",
            role=AppUser.Role.AGENT,
            email_verified=True,
        )
        self.other_agent = AppUser.objects.create_user(
            email="agent-feature-other@example.com",
            password="password-123",
            name="Other Agent",
            role=AppUser.Role.AGENT,
            email_verified=True,
        )
        self.listing = Listing.objects.create(
            landlord=self.landlord,
            title="Inspection Listing",
            description="Listing awaiting physical inspection",
            address="15 Inspection Close",
            city="Lagos",
            state="Lagos",
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=1800000,
            physical_property_status="pending",
            property_document_submission={"in_person_verification_requested": True},
        )
        self.client = APIClient()

    def _complete_agent_profile(self, agent=None):
        agent = agent or self.agent
        AgentProfile.objects.update_or_create(
            user=agent,
            defaults={
                "first_name": "Inspection",
                "last_name": "Agent",
                "date_of_birth": date(1992, 4, 10),
                "gender": "male",
                "country_of_birth": "Nigeria",
                "nationality": "Nigeria",
                "state_of_origin": "Lagos",
                "lga_of_origin": "Ikeja",
                "mobile": "08012345678",
                "state_of_residence": "Lagos",
                "city_of_residence": "Ikeja",
                "residential_address": "3 Agent Street, Lagos",
                "nin_number": "12345678901",
                "bvn_number": "10987654321",
                "bank_name": "Test Bank",
                "account_name": "Inspection Agent",
                "account_number": "0123456789",
            },
        )

    def _complete_verification_payment(self, agent=None):
        agent = agent or self.agent
        return ServicePayment.objects.create(
            user=agent,
            purpose=ServicePayment.Purpose.AGENT_VERIFICATION,
            amount=Decimal("500.00"),
            status=ServicePayment.Status.COMPLETED,
            transaction_id=f"SVCTEST{uuid.uuid4().hex[:16].upper()}",
            payment_date=timezone.now(),
        )

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_agent_registration_returns_agent_role(self):
        response = self.client.post(
            "/api/v1/auth/register",
            {
                "name": "New Agent",
                "email": "new-agent@example.com",
                "password": "password-123",
                "role": "agent",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.json())
        self.assertEqual(response.json()["role"], "agent")
        self.assertFalse(AppUser.objects.filter(email="new-agent@example.com").exists())
        self.assertEqual(PendingRegistration.objects.get(email="new-agent@example.com").role, AppUser.Role.AGENT)

        otp_match = re.search(r"\b([A-Z0-9]{6})\b", mail.outbox[-1].body)
        self.assertIsNotNone(otp_match)
        verify_response = self.client.post(
            "/api/v1/auth/register/verify",
            {"email": "new-agent@example.com", "otp_code": otp_match.group(1)},
            format="json",
        )
        self.assertEqual(verify_response.status_code, 200, verify_response.json())
        user = AppUser.objects.get(email="new-agent@example.com")
        self.assertEqual(user.role, AppUser.Role.AGENT)

    def test_profile_patch_validates_and_syncs_user_fields(self):
        self.client.force_authenticate(user=self.agent)

        invalid = self.client.patch(
            "/api/v1/agents/profile",
            {"nin_number": "123", "mobile": "12345"},
            format="json",
        )
        self.assertEqual(invalid.status_code, 400)

        response = self.client.patch(
            "/api/v1/agents/profile",
            {
                "first_name": "Inspection",
                "middle_name": "Middle",
                "last_name": "Agent",
                "date_of_birth": "1992-04-10",
                "gender": "male",
                "country_of_birth": "Nigeria",
                "nationality": "Nigeria",
                "state_of_origin": "Lagos",
                "lga_of_origin": "Ikeja",
                "mobile": "08012345678",
                "state_of_residence": "Lagos",
                "city_of_residence": "Ikeja",
                "residential_address": "3 Agent Street, Lagos",
                "nin_number": "12345678901",
                "bvn_number": "10987654321",
                "bank_name": "Test Bank",
                "account_name": "Inspection Agent",
                "account_number": "0123456789",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        self.assertEqual(payload["verification_status"], "payment_required")
        self.assertEqual(payload["email"], self.agent.email)

        self.agent.refresh_from_db()
        self.assertEqual(self.agent.name, "Inspection Middle Agent")
        self.assertEqual(self.agent.mobile, "08012345678")
        self.assertEqual(self.agent.nin_number, "12345678901")
        self.assertEqual(self.agent.bvn_number, "10987654321")
        self.assertEqual(self.agent.state_of_origin, "Lagos")

    @patch("core.views.verify_nin_and_bvn")
    def test_verify_charges_fee_after_verification_then_activates(self, verify_mock):
        verify_mock.return_value = {"nin": {"status": "verified"}, "bvn": {"status": "verified"}}
        self._complete_agent_profile()
        self.client.force_authenticate(user=self.agent)

        response = self.client.post("/api/v1/agents/verify", {}, format="json")
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json()["verification_status"], "payment_required")
        self.assertFalse(response.json()["is_verified"])
        payment_payload = response.json()["verification_payment"]
        self.assertEqual(payment_payload["amount"], "500.00")

        profile = AgentProfile.objects.get(user=self.agent)
        self.assertEqual(profile.verification_status, AgentProfile.VerificationStatus.PAYMENT_REQUIRED)
        self.assertIsNone(profile.verified_at)
        self.assertEqual(profile.verification_attempts, 1)

        verification = VerificationRequest.objects.get(user=self.agent, role=AppUser.Role.AGENT)
        self.assertEqual(verification.status, VerificationRequest.Status.PENDING)
        self.assertEqual(
            verification.identity_verification_status,
            VerificationRequest.VerificationProgressStatus.AWAITING_PAYMENT,
        )
        self.assertEqual(
            verification.verification_method, VerificationRequest.Method.AUTOMATED
        )

        from core.views import complete_service_payment

        complete_service_payment(ServicePayment.objects.get(id=payment_payload["id"]))
        verification.refresh_from_db()
        profile.refresh_from_db()
        self.assertEqual(
            verification.identity_verification_status,
            VerificationRequest.VerificationProgressStatus.VERIFIED,
        )
        self.assertEqual(profile.verification_status, AgentProfile.VerificationStatus.VERIFIED)
        self.assertIsNotNone(profile.verified_at)
        self.assertTrue(
            AppUser.objects.get(pk=self.agent.pk).is_verified_for_role(AppUser.Role.AGENT)
        )

        self.assertFalse(SubscriptionPayment.objects.filter(user=self.agent).exists())
        call_kwargs = verify_mock.call_args[0]
        self.assertEqual(call_kwargs[0]["lga"], "Ikeja")
        self.assertEqual(call_kwargs[1], "12345678901")
        self.assertEqual(call_kwargs[2], "10987654321")

        locked = self.client.patch(
            "/api/v1/agents/profile",
            {"nin_number": "99999999999", "account_number": "9999999999", "bank_name": "Other Bank"},
            format="json",
        )
        self.assertEqual(locked.status_code, 400)
        profile.refresh_from_db()
        self.assertEqual(profile.nin_number, "12345678901")
        self.assertEqual(profile.account_number, "0123456789")
        self.assertEqual(profile.bank_name, "Test Bank")

    @patch("core.views.verify_nin_and_bvn")
    def test_verify_reuses_landlord_verified_identity_without_provider_call(self, verify_mock):
        self.agent.landlord_verification_type = AppUser.LandlordVerificationType.INDIVIDUAL
        self.agent.landlord_verification_profile = {
            "first_name": "Inspection",
            "last_name": "Agent",
            "date_of_birth": "1992-04-10",
            "gender": "male",
            "country_of_birth": "Nigeria",
            "nationality": "Nigeria",
            "state_of_origin": "Lagos",
            "lga_of_origin": "Ikeja",
            "contact_number": "08012345678",
            "email": self.agent.email,
            "nin": "12345678901",
            "bvn": "10987654321",
            "residential_address": "3 Agent Street, Lagos",
        }
        self.agent.save(update_fields=["landlord_verification_type", "landlord_verification_profile"])
        VerificationRequest.objects.create(
            user=self.agent,
            role=AppUser.Role.LANDLORD,
            request_type=VerificationRequest.RequestType.IDENTIFICATION,
            status=VerificationRequest.Status.APPROVED,
            identity_verification_status=VerificationRequest.VerificationProgressStatus.VERIFIED,
            verification_method=VerificationRequest.Method.AUTOMATED,
        )
        self._complete_agent_profile()
        self._complete_verification_payment()
        self.client.force_authenticate(user=self.agent)

        response = self.client.post("/api/v1/agents/verify", {}, format="json")

        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json()["verification_status"], "verified")
        self.assertFalse(verify_mock.called)
        profile = AgentProfile.objects.get(user=self.agent)
        self.assertEqual(profile.verification_status, AgentProfile.VerificationStatus.VERIFIED)

    @patch("core.views.verify_nin_and_bvn")
    def test_verify_rejects_credentials_linked_to_another_account(self, verify_mock):
        holder = AppUser.objects.create_user(
            email="verified-holder@example.com",
            password="password-123",
            name="Verified Holder",
            role=AppUser.Role.TENANT,
            email_verified=True,
            nin_number="12345678901",
            bvn_number="10987654321",
        )
        VerificationRequest.objects.create(
            user=holder,
            role=AppUser.Role.TENANT,
            request_type=VerificationRequest.RequestType.IDENTIFICATION,
            status=VerificationRequest.Status.APPROVED,
            identity_verification_status=VerificationRequest.VerificationProgressStatus.VERIFIED,
            verification_method=VerificationRequest.Method.AUTOMATED,
        )
        self._complete_agent_profile()
        self._complete_verification_payment()
        self.client.force_authenticate(user=self.agent)

        response = self.client.post("/api/v1/agents/verify", {}, format="json")

        self.assertEqual(response.status_code, 400, response.json())
        self.assertIn("nin_number", response.json())
        self.assertFalse(verify_mock.called)
        profile = AgentProfile.objects.get(user=self.agent)
        self.assertNotEqual(profile.verification_status, AgentProfile.VerificationStatus.VERIFIED)
        self.assertEqual(profile.verification_attempts, 0)

    @patch("core.views.verify_nin_and_bvn")
    def test_verify_calls_provider_when_credentials_differ_from_verified_persona(self, verify_mock):
        verify_mock.return_value = {"nin": {"status": "verified"}, "bvn": {"status": "verified"}}
        self.agent.landlord_verification_type = AppUser.LandlordVerificationType.INDIVIDUAL
        self.agent.landlord_verification_profile = {
            "first_name": "Inspection",
            "last_name": "Agent",
            "date_of_birth": "1992-04-10",
            "gender": "male",
            "country_of_birth": "Nigeria",
            "nationality": "Nigeria",
            "state_of_origin": "Lagos",
            "lga_of_origin": "Ikeja",
            "contact_number": "08012345678",
            "email": self.agent.email,
            "nin": "99999999999",
            "bvn": "99999999999",
            "residential_address": "3 Agent Street, Lagos",
        }
        self.agent.save(update_fields=["landlord_verification_type", "landlord_verification_profile"])
        VerificationRequest.objects.create(
            user=self.agent,
            role=AppUser.Role.LANDLORD,
            request_type=VerificationRequest.RequestType.IDENTIFICATION,
            status=VerificationRequest.Status.APPROVED,
            identity_verification_status=VerificationRequest.VerificationProgressStatus.VERIFIED,
            verification_method=VerificationRequest.Method.AUTOMATED,
        )
        self._complete_agent_profile()
        self._complete_verification_payment()
        self.client.force_authenticate(user=self.agent)

        response = self.client.post("/api/v1/agents/verify", {}, format="json")

        self.assertEqual(response.status_code, 200, response.json())
        self.assertTrue(verify_mock.called)

    @patch("core.views.verify_nin_and_bvn")
    def test_verify_rejects_account_name_mismatched_to_bvn_record(self, verify_mock):
        verify_mock.return_value = {
            "nin": {"status": "verified"},
            "bvn": {
                "status": "verified",
                "data": {"firstName": "Different", "lastName": "Person"},
            },
        }
        self._complete_agent_profile()
        self._complete_verification_payment()
        self.client.force_authenticate(user=self.agent)

        response = self.client.post("/api/v1/agents/verify", {}, format="json")

        self.assertEqual(response.status_code, 400, response.json())
        self.assertIn("account_name", response.json())
        profile = AgentProfile.objects.get(user=self.agent)
        self.assertNotEqual(profile.verification_status, AgentProfile.VerificationStatus.VERIFIED)
        self.assertEqual(profile.verification_attempts, 1)

    @patch("core.views.verify_nin_and_bvn")
    def test_verify_accepts_account_name_matching_bvn_names(self, verify_mock):
        verify_mock.return_value = {
            "nin": {"status": "verified"},
            "bvn": {
                "status": "verified",
                "data": {"firstName": "Inspection", "lastName": "Agent"},
            },
        }
        self._complete_agent_profile()
        self._complete_verification_payment()
        self.client.force_authenticate(user=self.agent)

        response = self.client.post("/api/v1/agents/verify", {}, format="json")

        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json()["verification_status"], "verified")

    def test_unverified_agent_cannot_claim_pending_listing(self):
        self.client.force_authenticate(user=self.agent)
        response = self.client.post(
            "/api/v1/agent-inspections/claim",
            {"listing_id": str(self.listing.id)},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(PropertyInspection.objects.exists())

        dashboard = self.client.get("/api/v1/agents/dashboard")
        self.assertEqual(dashboard.status_code, 200, dashboard.json())
        self.assertEqual(dashboard.json()["available_inspections"], [])

    @patch("core.views.verify_nin_and_bvn")
    def test_verified_agent_claims_only_pending_in_person_listing_once(self, verify_mock):
        verify_mock.return_value = {}
        self._complete_agent_profile()
        self._complete_verification_payment()
        self.client.force_authenticate(user=self.agent)
        self.client.post("/api/v1/agents/verify", {}, format="json")

        dashboard = self.client.get("/api/v1/agents/dashboard")
        self.assertEqual(dashboard.status_code, 200, dashboard.json())
        available = dashboard.json()["available_inspections"]
        self.assertEqual(len(available), 1)
        self.assertEqual(available[0]["id"], str(self.listing.id))
        self.assertEqual(available[0]["title"], "Inspection Listing")
        self.assertEqual(available[0]["address"], "15 Inspection Close")
        self.assertEqual(available[0]["city"], "Lagos")
        self.assertEqual(available[0]["state"], "Lagos")

        response = self.client.post(
            "/api/v1/agent-inspections/claim",
            {"listing_id": str(self.listing.id)},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.json())
        self.assertEqual(response.json()["agent_id"], str(self.agent.id))
        self.assertEqual(response.json()["listing_id"], str(self.listing.id))
        self.assertEqual(response.json()["status"], "claimed")

        duplicate = self.client.post(
            "/api/v1/agent-inspections/claim",
            {"listing_id": str(self.listing.id)},
            format="json",
        )
        self.assertEqual(duplicate.status_code, 400)

        no_request_listing = Listing.objects.create(
            landlord=self.landlord,
            title="No Request Listing",
            description="Listing without in-person request",
            address="1 Plain Street",
            city="Lagos",
            state="Lagos",
            property_type="House",
            bedrooms=3,
            bathrooms=2,
            price_per_year=1200000,
            physical_property_status="pending",
        )
        rejected = self.client.post(
            "/api/v1/agent-inspections/claim",
            {"listing_id": str(no_request_listing.id)},
            format="json",
        )
        self.assertEqual(rejected.status_code, 400)

        non_pending_listing = Listing.objects.create(
            landlord=self.landlord,
            title="Verified Listing",
            description="Already verified listing",
            address="2 Verified Street",
            city="Lagos",
            state="Lagos",
            property_type="House",
            bedrooms=3,
            bathrooms=2,
            price_per_year=1200000,
            physical_property_status="verified",
            property_document_submission={"in_person_verification_requested": True},
        )
        non_pending = self.client.post(
            "/api/v1/agent-inspections/claim",
            {"listing_id": str(non_pending_listing.id)},
            format="json",
        )
        self.assertEqual(non_pending.status_code, 400)

    def _claim_as_verified_agent(self, agent=None, listing=None):
        agent = agent or self.agent
        listing = listing or self.listing
        self._complete_agent_profile(agent)
        self._complete_verification_payment(agent)
        profile = AgentProfile.objects.get(user=agent)
        profile.verification_status = AgentProfile.VerificationStatus.VERIFIED
        profile.verified_at = timezone.now()
        profile.save(update_fields=["verification_status", "verified_at", "updated_at"])
        self.client.force_authenticate(user=agent)
        response = self.client.post(
            "/api/v1/agent-inspections/claim",
            {"listing_id": str(listing.id)},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.json())
        return PropertyInspection.objects.get(id=response.json()["id"])

    def test_invalid_option_unknown_field_and_incomplete_submit_rejected(self):
        inspection = self._claim_as_verified_agent()

        invalid_option = self.client.patch(
            f"/api/v1/agent-inspections/{inspection.id}",
            {"responses": {"drainage_condition": "bogus"}},
            format="json",
        )
        self.assertEqual(invalid_option.status_code, 400)

        mixed_none = self.client.patch(
            f"/api/v1/agent-inspections/{inspection.id}",
            {"responses": {"external_issues": ["none_observed", "erosion"]}},
            format="json",
        )
        self.assertEqual(mixed_none.status_code, 400)

        unknown_field = self.client.patch(
            f"/api/v1/agent-inspections/{inspection.id}",
            {"responses": {"not_a_field": "x"}},
            format="json",
        )
        self.assertEqual(unknown_field.status_code, 400)

        incomplete = self.client.post(
            f"/api/v1/agent-inspections/{inspection.id}/submit",
            {"responses": {"drainage_condition": "verified"}},
            format="json",
        )
        self.assertEqual(incomplete.status_code, 400)
        inspection.refresh_from_db()
        self.assertEqual(inspection.status, PropertyInspection.Status.CLAIMED)

    def test_complete_submission_signs_off_and_report_is_immutable(self):
        inspection = self._claim_as_verified_agent()
        responses = build_complete_inspection_responses(
            overall_status="inspection_completed_with_issues",
            critical_red_flags=["suspected_fraud"],
            drainage_condition="issue_found",
        )

        response = self.client.post(
            f"/api/v1/agent-inspections/{inspection.id}/submit",
            {"responses": responses},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.json())
        inspection.refresh_from_db()
        self.listing.refresh_from_db()
        self.assertEqual(inspection.status, PropertyInspection.Status.SUBMITTED)
        self.assertEqual(inspection.overall_status, "inspection_completed_with_issues")
        self.assertIsNotNone(inspection.submitted_at)
        self.assertIsNotNone(inspection.signed_off_at)
        self.assertEqual(
            self.listing.physical_property_status,
            VerificationRequest.VerificationProgressStatus.PENDING,
        )
        analysis = inspection.analysis
        self.assertEqual(analysis["critical_red_flags"], ["suspected_fraud"])
        self.assertEqual(analysis["overall_status"], "inspection_completed_with_issues")
        self.assertEqual(analysis["total_item_count"], len(responses))
        self.assertEqual(analysis["completed_item_count"], len(responses))
        self.assertIn("drainage_condition", analysis["issue_item_keys"])

        update_after_submit = self.client.patch(
            f"/api/v1/agent-inspections/{inspection.id}",
            {"responses": {"drainage_condition": "issue_found"}},
            format="json",
        )
        self.assertEqual(update_after_submit.status_code, 400)
        inspection.refresh_from_db()
        self.assertEqual(inspection.responses["drainage_condition"], "issue_found")

    def test_clean_submission_without_red_flags_marks_listing_verified(self):
        clean_listing = Listing.objects.create(
            landlord=self.landlord,
            title="Clean Inspection Listing",
            description="Listing with a clean inspection",
            address="50 Clean Street",
            city="Lagos",
            state="Lagos",
            property_type="House",
            bedrooms=2,
            bathrooms=1,
            price_per_year=1000000,
            physical_property_status="pending",
            property_document_submission={"in_person_verification_requested": True},
        )
        inspection = self._claim_as_verified_agent(listing=clean_listing)
        responses = build_complete_inspection_responses(
            overall_status="inspection_completed",
            critical_red_flags=["none_observed"],
        )

        response = self.client.post(
            f"/api/v1/agent-inspections/{inspection.id}/submit",
            {"responses": responses},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.json())
        inspection.refresh_from_db()
        clean_listing.refresh_from_db()
        self.assertEqual(inspection.status, PropertyInspection.Status.SUBMITTED)
        self.assertEqual(inspection.analysis["critical_red_flags"], [])
        self.assertEqual(
            clean_listing.physical_property_status,
            VerificationRequest.VerificationProgressStatus.VERIFIED,
        )

    @override_settings(AGENT_INSPECTION_EARNING_NGN="15000.00")
    def test_dashboard_isolates_agents_and_sums_earnings(self):
        first = self._claim_as_verified_agent()
        self.client.post(
            f"/api/v1/agent-inspections/{first.id}/submit",
            {"responses": build_complete_inspection_responses()},
            format="json",
        )
        first.refresh_from_db()
        first.payout_status = PropertyInspection.PayoutStatus.PAID
        first.paid_out_at = timezone.now()
        first.save(update_fields=["payout_status", "paid_out_at", "updated_at"])

        second_listing = Listing.objects.create(
            landlord=self.landlord,
            title="Second Inspection Listing",
            description="Second pending inspection",
            address="20 Second Street",
            city="Lagos",
            state="Lagos",
            property_type="House",
            bedrooms=3,
            bathrooms=2,
            price_per_year=2000000,
            physical_property_status="pending",
            property_document_submission={"in_person_verification_requested": True},
        )
        second = self._claim_as_verified_agent(listing=second_listing)
        self.client.post(
            f"/api/v1/agent-inspections/{second.id}/submit",
            {"responses": build_complete_inspection_responses()},
            format="json",
        )

        other_listing = Listing.objects.create(
            landlord=self.landlord,
            title="Other Agent Listing",
            description="Claimed by another agent",
            address="30 Other Street",
            city="Lagos",
            state="Lagos",
            property_type="House",
            bedrooms=2,
            bathrooms=1,
            price_per_year=1000000,
            physical_property_status="pending",
            property_document_submission={"in_person_verification_requested": True},
        )
        PropertyInspection.objects.create(
            listing=other_listing,
            agent=self.other_agent,
            status=PropertyInspection.Status.SUBMITTED,
            earning_amount=Decimal("15000.00"),
        )

        response = self.client.get("/api/v1/agents/dashboard")
        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        metrics = payload["metrics"]
        self.assertEqual(metrics["properties_inspected"], 2)
        self.assertEqual(Decimal(metrics["total_amount_earned"]), Decimal("30000.00"))
        self.assertEqual(Decimal(metrics["total_amount_paid_out"]), Decimal("15000.00"))
        self.assertEqual(Decimal(metrics["pending_payout"]), Decimal("15000.00"))
        inspection_ids = {item["id"] for item in payload["inspections"]}
        self.assertEqual(inspection_ids, {str(first.id), str(second.id)})

        self.client.force_authenticate(user=self.other_agent)
        other_response = self.client.get("/api/v1/agents/dashboard")
        self.assertEqual(other_response.status_code, 200, other_response.json())
        other_metrics = other_response.json()["metrics"]
        self.assertEqual(other_metrics["properties_inspected"], 1)
        self.assertEqual(Decimal(other_metrics["total_amount_earned"]), Decimal("15000.00"))

    def test_pdf_returns_attachment_for_owner_and_admin_only(self):
        inspection = self._claim_as_verified_agent()
        self.client.post(
            f"/api/v1/agent-inspections/{inspection.id}/submit",
            {"responses": build_complete_inspection_responses()},
            format="json",
        )

        pdf_response = self.client.get(f"/api/v1/agent-inspections/{inspection.id}/pdf")
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response["Content-Type"], "application/pdf")
        self.assertTrue(pdf_response.content.startswith(b"%PDF"))

        self.client.force_authenticate(user=self.other_agent)
        forbidden = self.client.get(f"/api/v1/agent-inspections/{inspection.id}/pdf")
        self.assertIn(forbidden.status_code, {403, 404})

        admin = AppUser.objects.create_user(
            email="inspection-admin@example.com",
            password="password-123",
            name="Admin User",
            role=AppUser.Role.ADMIN,
            email_verified=True,
            is_staff=True,
        )
        self.client.force_authenticate(user=admin)
        admin_response = self.client.get(f"/api/v1/agent-inspections/{inspection.id}/pdf")
        self.assertEqual(admin_response.status_code, 200)
        self.assertTrue(admin_response.content.startswith(b"%PDF"))

        draft_listing = Listing.objects.create(
            landlord=self.landlord,
            title="Draft Inspection Listing",
            description="Unsubmitted inspection",
            address="40 Draft Street",
            city="Lagos",
            state="Lagos",
            property_type="House",
            bedrooms=2,
            bathrooms=1,
            price_per_year=1000000,
            physical_property_status="pending",
            property_document_submission={"in_person_verification_requested": True},
        )
        draft = self._claim_as_verified_agent(listing=draft_listing)
        draft_response = self.client.get(f"/api/v1/agent-inspections/{draft.id}/pdf")
        self.assertEqual(draft_response.status_code, 400)

    def test_agent_support_chat_history_is_isolated(self):
        admin = AppUser.objects.create_user(
            email="support-admin2@example.com",
            password="password-123",
            name="Support Admin",
            role=AppUser.Role.ADMIN,
            email_verified=True,
            is_staff=True,
        )
        SupportChatMessage.objects.create(
            thread_user=self.agent, thread_role=AppUser.Role.AGENT, sender=self.agent, sender_role=AppUser.Role.AGENT, content="Agent needs help."
        )
        SupportChatMessage.objects.create(
            thread_user=self.other_agent, thread_role=AppUser.Role.AGENT, sender=admin, sender_role=AppUser.Role.ADMIN, content="Other agent reply."
        )
        tenant = AppUser.objects.create_user(
            email="support-tenant3@example.com",
            password="password-123",
            name="Tenant User",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        SupportChatMessage.objects.create(
            thread_user=tenant, thread_role=AppUser.Role.TENANT, sender=tenant, sender_role=AppUser.Role.TENANT, content="Tenant message."
        )

        self.client.force_authenticate(user=self.agent)
        response = self.client.get("/api/v1/support-chat/messages")
        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        results = payload["results"] if isinstance(payload, dict) and "results" in payload else payload
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["content"], "Agent needs help.")

        self.client.force_authenticate(user=admin)
        for param in ("thread_user", "agent_id"):
            admin_response = self.client.get(
                "/api/v1/support-chat/messages", {param: str(self.agent.id)}
            )
            self.assertEqual(admin_response.status_code, 200, admin_response.json())
            admin_payload = admin_response.json()
            admin_results = (
                admin_payload["results"]
                if isinstance(admin_payload, dict) and "results" in admin_payload
                else admin_payload
            )
            self.assertEqual(len(admin_results), 1)
            self.assertEqual(admin_results[0]["content"], "Agent needs help.")


class AgentReferralTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.landlord = AppUser.objects.create_user(
            email="referral-landlord@example.com",
            password="password-123",
            name="Referral Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        self.referrer = AppUser.objects.create_user(
            email="referrer-pio@example.com",
            password="password-123",
            name="Referrer Pio",
            role=AppUser.Role.AGENT,
            email_verified=True,
        )
        self.referred = AppUser.objects.create_user(
            email="referred-pio@example.com",
            password="password-123",
            name="Referred Pio",
            role=AppUser.Role.AGENT,
            email_verified=True,
        )
        self.referrer_profile = AgentProfile.objects.create(
            user=self.referrer, first_name="Referrer", last_name="Pio"
        )
        self.referred_profile = AgentProfile.objects.create(
            user=self.referred,
            first_name="Referred",
            last_name="Pio",
            verification_status=AgentProfile.VerificationStatus.VERIFIED,
            referred_by=self.referrer,
        )

    def _submitted_inspection(self, agent, title):
        listing = Listing.objects.create(
            landlord=self.landlord,
            title=title,
            bedrooms=2,
            bathrooms=1,
            price_per_year=1000000,
        )
        return PropertyInspection.objects.create(
            listing=listing,
            agent=agent,
            status=PropertyInspection.Status.SUBMITTED,
            earning_amount=Decimal("100.00"),
        )

    def test_referral_code_generated_unique_8_chars(self):
        code = self.referrer_profile.referral_code
        self.assertEqual(len(code), 8)
        self.assertTrue(code.isalnum())
        codes = {generate_unique_referral_code() for _ in range(20)}
        self.assertEqual(len(codes), 20)
        self.assertNotIn(code, codes)

    def test_agent_profile_cannot_refer_itself(self):
        user = AppUser.objects.create_user(
            email="self-referral-pio@example.com",
            password="password-123",
            name="Self Referral Pio",
            role=AppUser.Role.AGENT,
            email_verified=True,
        )
        profile = AgentProfile(
            user=user,
            first_name="Self",
            last_name="Referral",
            referred_by=user,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                profile.save()

    def test_resolve_referrer_case_insensitive(self):
        code = self.referrer_profile.referral_code
        self.assertEqual(resolve_referrer(code.lower()).id, self.referrer.id)
        self.assertIsNone(resolve_referrer("ZZZZZZZZ"))
        self.assertIsNone(resolve_referrer(""))

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_registration_with_referral_code_links_referrer(self):
        response = self.client.post(
            "/api/v1/auth/register",
            {
                "name": "New Pio",
                "email": "new-pio@example.com",
                "password": "password-123",
                "role": "agent",
                "referral_code": self.referrer_profile.referral_code.lower(),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.json())
        self.assertEqual(
            PendingRegistration.objects.get(email="new-pio@example.com").referral_code,
            self.referrer_profile.referral_code,
        )

        otp_match = re.search(r"\b([A-Z0-9]{6})\b", mail.outbox[-1].body)
        verify_response = self.client.post(
            "/api/v1/auth/register/verify",
            {"email": "new-pio@example.com", "otp_code": otp_match.group(1)},
            format="json",
        )
        self.assertEqual(verify_response.status_code, 200, verify_response.json())
        profile = AgentProfile.objects.get(user__email="new-pio@example.com")
        self.assertEqual(profile.referred_by_id, self.referrer.id)
        self.assertEqual(len(profile.referral_code), 8)

    def test_registration_rejects_invalid_referral_code(self):
        response = self.client.post(
            "/api/v1/auth/register",
            {
                "name": "New Pio",
                "email": "new-pio@example.com",
                "password": "password-123",
                "role": "agent",
                "referral_code": "ZZZZZZZZ",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_registration_rejects_referral_code_for_non_agent(self):
        response = self.client.post(
            "/api/v1/auth/register",
            {
                "name": "New Tenant",
                "email": "new-tenant@example.com",
                "password": "password-123",
                "role": "tenant",
                "referral_code": self.referrer_profile.referral_code,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_award_referral_earning_per_inspection_and_cap(self):
        for index in range(7):
            award_referral_earning(self._submitted_inspection(self.referred, f"L{index}"))
        earnings = AgentReferralEarning.objects.filter(referrer=self.referrer)
        self.assertEqual(earnings.count(), 5)
        self.assertEqual(
            sum(e.amount for e in earnings), Decimal("10000.00")
        )

    def test_award_referral_earning_is_idempotent(self):
        inspection = self._submitted_inspection(self.referred, "Idem")
        award_referral_earning(inspection)
        award_referral_earning(inspection)
        self.assertEqual(
            AgentReferralEarning.objects.filter(inspection=inspection).count(), 1
        )

    def test_award_referral_earning_requires_verified_referred(self):
        self.referred_profile.verification_status = AgentProfile.VerificationStatus.PENDING
        self.referred_profile.save()
        award_referral_earning(self._submitted_inspection(self.referred, "Unverified"))
        self.assertEqual(AgentReferralEarning.objects.count(), 0)

    def test_award_referral_earning_requires_referrer(self):
        self.referred_profile.referred_by = None
        self.referred_profile.save()
        award_referral_earning(self._submitted_inspection(self.referred, "NoReferrer"))
        self.assertEqual(AgentReferralEarning.objects.count(), 0)

    def test_referrals_endpoint_returns_tree(self):
        for index in range(2):
            award_referral_earning(self._submitted_inspection(self.referred, f"T{index}"))
        self.client.force_authenticate(user=self.referrer)
        response = self.client.get("/api/v1/agents/referrals")
        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        self.assertEqual(payload["referral_code"], self.referrer_profile.referral_code)
        self.assertEqual(payload["metrics"]["total_referrals"], 1)
        self.assertEqual(payload["metrics"]["total_referral_earned"], "4000.00")
        children = payload["tree"]["children"]
        self.assertEqual(len(children), 1)
        self.assertEqual(children[0]["id"], str(self.referred.id))
        self.assertEqual(children[0]["properties_inspected"], 2)

    def test_referrals_endpoint_requires_agent_role(self):
        tenant = AppUser.objects.create_user(
            email="referral-tenant@example.com",
            password="password-123",
            name="Tenant",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        self.client.force_authenticate(user=tenant)
        response = self.client.get("/api/v1/agents/referrals")
        self.assertEqual(response.status_code, 403)

    def test_resolve_referrer_uses_active_agent_membership(self):
        # PIO identity is AgentProfile + active agent membership, independent of
        # the legacy AppUser.role.
        hybrid = AppUser.objects.create_user(
            email="hybrid-pio@example.com",
            password="password-123",
            name="Hybrid Pio",
            role=AppUser.Role.TENANT,
            email_verified=True,
        )
        membership = UserRole.objects.create(user=hybrid, role=AppUser.Role.AGENT)
        profile = AgentProfile.objects.create(
            user=hybrid, first_name="Hybrid", last_name="Pio"
        )
        self.assertEqual(resolve_referrer(profile.referral_code).id, hybrid.id)

        membership.status = UserRole.Status.SUSPENDED
        membership.save(update_fields=["status"])
        self.assertIsNone(resolve_referrer(profile.referral_code))


class InspectionRequestTests(TestCase):
    def setUp(self):
        self.landlord = AppUser.objects.create_user(
            email="insp-req-landlord@example.com",
            password="password-123",
            name="Request Landlord",
            role=AppUser.Role.LANDLORD,
            email_verified=True,
        )
        self.listing = Listing.objects.create(
            landlord=self.landlord,
            title="Request Listing",
            description="Listing awaiting physical inspection",
            address="15 Inspection Close",
            city="Lagos",
            state="Lagos",
            property_type="Apartment",
            bedrooms=2,
            bathrooms=2,
            price_per_year=1800000,
            physical_property_status="pending",
            property_document_submission={"in_person_verification_requested": True},
        )
        self.client = APIClient()

    def _verified_agent(self, email, *, city="Lagos", state="Lagos", whatsapp_number=""):
        agent = AppUser.objects.create_user(
            email=email,
            password="password-123",
            name=email.split("@")[0].title(),
            role=AppUser.Role.AGENT,
            email_verified=True,
        )
        AgentProfile.objects.create(
            user=agent,
            first_name="PIO",
            last_name="Officer",
            date_of_birth=date(1992, 4, 10),
            city_of_residence=city,
            state_of_residence=state,
            whatsapp_number=whatsapp_number,
            verification_status=AgentProfile.VerificationStatus.VERIFIED,
        )
        ServicePayment.objects.create(
            user=agent,
            purpose=ServicePayment.Purpose.AGENT_VERIFICATION,
            amount=Decimal("500.00"),
            status=ServicePayment.Status.COMPLETED,
            transaction_id=f"SVCTEST{uuid.uuid4().hex[:16].upper()}",
            payment_date=timezone.now(),
        )
        return agent

    def _claim(self, agent):
        client = APIClient()
        client.force_authenticate(user=agent)
        return client.post(
            "/api/v1/agent-inspections/claim",
            {"listing_id": str(self.listing.id)},
            format="json",
        )

    def test_listing_creation_notifies_nearest_agents(self):
        make_landlord_listing_ready(self.landlord)
        VerificationRequest.objects.create(
            user=self.landlord,
            role=AppUser.Role.LANDLORD,
            status=VerificationRequest.Status.APPROVED,
            identity_verification_status=VerificationRequest.VerificationProgressStatus.VERIFIED,
        )
        near_agent = self._verified_agent("near-pio@example.com", city="Lagos")
        self._verified_agent("far-pio@example.com", city="Abuja", state="FCT")

        client = APIClient()
        client.force_authenticate(user=self.landlord)
        gif = (
            b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x00"
            b"\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
        )
        response = client.post(
            "/api/v1/listings",
            {
                "title": "Nearby Inspection Listing",
                "description": "A listing that triggers PIO notifications",
                "address": "10 Close Street",
                "city": "Lagos",
                "state": "Lagos",
                "lga": "Eti-Osa",
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
                "cover_image": SimpleUploadedFile("cover.gif", gif, content_type="image/gif"),
                "images": SimpleUploadedFile("room.gif", gif, content_type="image/gif"),
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 201, response.json())
        listing = Listing.objects.get(title="Nearby Inspection Listing")
        requests = InspectionRequest.objects.filter(listing=listing)
        self.assertEqual(requests.count(), 1)
        self.assertEqual(requests.get().agent, near_agent)
        self.assertEqual(requests.get().status, InspectionRequest.Status.PENDING)
        self.assertIn("email", requests.get().notified_channels)
        self.assertTrue(
            any(message.to == [near_agent.email] for message in mail.outbox),
            "expected a request email to the nearest PIO",
        )

    def test_accept_request_marks_other_requests_taken(self):
        first = self._verified_agent("first-pio@example.com")
        second = self._verified_agent("second-pio@example.com")
        from core.inspection_requests import notify_agents_for_listing

        notify_agents_for_listing(self.listing)
        self.assertEqual(InspectionRequest.objects.filter(listing=self.listing).count(), 2)

        response = self._claim(first)
        self.assertEqual(response.status_code, 201, response.json())
        self.assertEqual(
            InspectionRequest.objects.get(listing=self.listing, agent=first).status,
            InspectionRequest.Status.ACCEPTED,
        )
        self.assertEqual(
            InspectionRequest.objects.get(listing=self.listing, agent=second).status,
            InspectionRequest.Status.TAKEN,
        )

        blocked = self._claim(second)
        self.assertEqual(blocked.status_code, 400)

        dashboard_client = APIClient()
        dashboard_client.force_authenticate(user=second)
        dashboard = dashboard_client.get("/api/v1/agents/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        requests_payload = dashboard.json()["inspection_requests"]
        taken = next(item for item in requests_payload if item["listing"]["id"] == str(self.listing.id))
        self.assertEqual(taken["status"], "taken")
        self.assertEqual(taken["status_display"], "Request Accepted")

    def test_expired_request_cannot_be_accepted(self):
        agent = self._verified_agent("late-pio@example.com")
        from core.inspection_requests import notify_agents_for_listing

        notify_agents_for_listing(self.listing)
        request_obj = InspectionRequest.objects.get(listing=self.listing, agent=agent)
        request_obj.expires_at = timezone.now() - timedelta(hours=1)
        request_obj.save(update_fields=["expires_at", "updated_at"])

        response = self._claim(agent)
        self.assertEqual(response.status_code, 400)
        request_obj.refresh_from_db()
        self.assertEqual(request_obj.status, InspectionRequest.Status.EXPIRED)
        self.assertFalse(PropertyInspection.objects.exists())

    def test_agent_without_request_blocked_while_requests_active(self):
        notified = self._verified_agent("notified-pio@example.com")
        outsider = self._verified_agent("outsider-pio@example.com", city="Abuja", state="FCT")
        from core.inspection_requests import notify_agents_for_listing

        notify_agents_for_listing(self.listing, exclude_agent_ids={outsider.id})
        self.assertTrue(
            InspectionRequest.objects.filter(listing=self.listing, agent=notified, status="pending").exists()
        )

        response = self._claim(outsider)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(PropertyInspection.objects.exists())

    def test_timed_out_inspection_is_reassigned(self):
        first = self._verified_agent("slow-pio@example.com")
        second = self._verified_agent("next-pio@example.com", whatsapp_number="08031112222")
        from core.inspection_requests import notify_agents_for_listing, process_inspection_timeouts

        notify_agents_for_listing(self.listing)
        response = self._claim(first)
        self.assertEqual(response.status_code, 201, response.json())
        inspection = PropertyInspection.objects.get(listing=self.listing)
        inspection.claimed_at = timezone.now() - timedelta(hours=49)
        inspection.save(update_fields=["claimed_at", "updated_at"])

        result = process_inspection_timeouts()

        self.assertEqual(result["reassigned_inspections"], 1)
        self.assertFalse(PropertyInspection.objects.filter(pk=inspection.pk).exists())
        round_two = InspectionRequest.objects.filter(listing=self.listing, round=2)
        self.assertTrue(round_two.filter(agent=second).exists())
        self.assertFalse(round_two.filter(agent=first).exists())
        self.assertTrue(
            any(message.to == [second.email] for message in mail.outbox),
            "expected reassignment email to the next PIO",
        )

        # The listing can be claimed again through the new request round.
        reclaim = self._claim(second)
        self.assertEqual(reclaim.status_code, 201, reclaim.json())

    def test_dashboard_includes_inspection_requests(self):
        agent = self._verified_agent("dash-pio@example.com")
        from core.inspection_requests import notify_agents_for_listing

        notify_agents_for_listing(self.listing)
        self.client.force_authenticate(user=agent)
        response = self.client.get("/api/v1/agents/dashboard")
        self.assertEqual(response.status_code, 200)
        requests_payload = response.json()["inspection_requests"]
        self.assertEqual(len(requests_payload), 1)
        self.assertEqual(requests_payload[0]["status"], "pending")
        self.assertEqual(requests_payload[0]["listing"]["id"], str(self.listing.id))
        self.assertIn(
            str(self.listing.id),
            [listing["id"] for listing in response.json()["available_inspections"]],
        )

    def test_claim_rejects_pio_who_owns_listing(self):
        UserRole.objects.create(user=self.landlord, role=AppUser.Role.AGENT)
        AgentProfile.objects.create(
            user=self.landlord,
            first_name="Owner",
            last_name="Pio",
            verification_status=AgentProfile.VerificationStatus.VERIFIED,
        )
        ServicePayment.objects.create(
            user=self.landlord,
            purpose=ServicePayment.Purpose.AGENT_VERIFICATION,
            amount=Decimal("500.00"),
            status=ServicePayment.Status.COMPLETED,
            transaction_id=f"SVCTEST{uuid.uuid4().hex[:16].upper()}",
            payment_date=timezone.now(),
        )

        token = str(RefreshToken.for_user(self.landlord).access_token)
        client = APIClient()
        client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_RENTDIRECT_ROLE="agent"
        )
        response = client.post(
            "/api/v1/agent-inspections/claim",
            {"listing_id": str(self.listing.id)},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn("ownership or tenancy interest", str(response.json()))
        self.assertFalse(
            PropertyInspection.objects.filter(agent=self.landlord).exists()
        )

    def test_claim_rejects_pio_with_booking_on_listing(self):
        agent = self._verified_agent("tenant-pio@example.com")
        Booking.objects.create(
            tenant=agent,
            listing=self.listing,
            start_date=date(2026, 8, 1),
            end_date=date(2027, 8, 1),
            status=Booking.Status.PENDING,
            total_amount=None,
        )

        response = self._claim(agent)

        self.assertEqual(response.status_code, 403)
        self.assertIn("ownership or tenancy interest", str(response.json()))

    def test_conflicted_pio_omitted_from_inspection_routing(self):
        conflicted = self._verified_agent("conflicted-pio@example.com", city="Lagos")
        clean = self._verified_agent("clean-pio@example.com", city="Lagos")
        Booking.objects.create(
            tenant=conflicted,
            listing=self.listing,
            start_date=date(2026, 8, 1),
            end_date=date(2027, 8, 1),
            status=Booking.Status.CONFIRMED,
            total_amount=None,
        )
        from core.inspection_requests import nearest_agents_for_listing

        agent_ids = {agent.id for agent in nearest_agents_for_listing(self.listing)}

        self.assertIn(clean.id, agent_ids)
        self.assertNotIn(conflicted.id, agent_ids)
        self.assertNotIn(self.landlord.id, agent_ids)
