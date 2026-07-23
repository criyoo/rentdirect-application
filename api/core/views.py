import base64
import binascii
import logging
import re
import uuid
from calendar import monthrange
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models import Avg, Q, Sum
from django.db.utils import OperationalError, ProgrammingError
from django.http import FileResponse, Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.html import escape
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from .models import (
    AppUser,
    booking_progress_step_completed,
    booking_progress_step_selected_value,
    Booking,
    CommunityChatMessage,
    deposit_secured_booking_queryset,
    Document,
    Feedback,
    Favourite,
    FeaturedPayment,
    Listing,
    Message,
    Payment,
    PaymentSettlement,
    Review,
    SubscriptionPayment,
    SubscriptionPaymentMethod,
    SupportChatMessage,
    TenantProfile,
    VerificationRequest,
)
from .flutterwave import (
    FlutterwaveError,
    build_checkout_payload,
    create_card_payment_method,
    create_charge,
    create_customer,
    create_bank_transfer,
    create_dynamic_virtual_account,
    create_transfer_recipient,
    extract_customer_email,
    extract_next_action_url,
    extract_payment_channel_details,
    extract_payment_method_card_details,
    extract_payment_state,
    extract_provider_transaction_id,
    extract_resource_id,
    extract_reference,
    extract_virtual_account_details,
    map_redirect_status,
    normalize_decimal_amount,
    query_transaction,
    should_use_v4,
    verify_webhook_signature,
)
from .dikript import verify_cac, verify_nin_and_bvn
from .notifications import (
    send_landlord_payout_notification,
    send_payment_confirmation_to_landlord,
    send_rentdirect_internal_transfer_notification,
)
from .permissions import IsAdminRole, IsLandlordOrAdmin
from .pricing import calculate_deposit_amount, calculate_remaining_balance, resolve_booking_total
from .security import OTP_MAX_ATTEMPTS, OTP_TTL_MINUTES, contains_contact_info, generate_otp, hash_otp, otp_matches
from .tenant_verification import normalize_tenant_verification_profile
from .throttling import production_ratelimit
from .community_chat import COMMUNITY_CHAT_ROLES, user_has_active_community_chat_subscription
from .subscription_access import user_has_bronze_access
from .serializers import (
    BookingSerializer,
    CommunityChatMessageSerializer,
    DocumentSerializer,
    FeedbackSerializer,
    FavouriteSerializer,
    FeaturedPaymentSerializer,
    ListingSerializer,
    LoginSerializer,
    MessageSerializer,
    PaymentSerializer,
    RegisterSerializer,
    ReviewSerializer,
    RentalProgressUpdateSerializer,
    SettingsOtpRequestSerializer,
    SettingsPasswordSerializer,
    SubscriptionPaymentRequestSerializer,
    SubscriptionPaymentSerializer,
    SubscriptionPaymentMethodSerializer,
    SupportChatMessageSerializer,
    TenantProfileSerializer,
    UserSerializer,
    VerifyRegistrationSerializer,
    VerificationRequestSerializer,
)
from .subscription_pricing import get_subscription_pricing

User = get_user_model()
FEATURED_PROPERTY_FEE = Decimal("5000.00")
OPEN_PAYMENT_STATUSES = {"pending", "processing"}
FAILED_PAYMENT_STATUSES = {"failed", "cancelled"}
SETTINGS_OTP_PURPOSE_PROFILE = "profile"
SETTINGS_OTP_PURPOSE_PASSWORD = "password"
SETTINGS_PROFILE_MUTABLE_FIELDS = {
    "name",
    "email",
    "mobile",
    "nin_number",
    "bvn_number",
    "state_of_origin",
    "residence",
    "landlord_verification_profile",
}


def build_booking_payment_reference() -> str:
    return f"BOOK{uuid.uuid4().hex[:20].upper()}"


def build_subscription_payment_reference() -> str:
    return f"SUB{uuid.uuid4().hex[:20].upper()}"


def is_valid_flutterwave_reference(reference: str) -> bool:
    normalized = str(reference or "").strip()
    return 6 <= len(normalized) <= 42 and all(character.isalnum() or character == "-" for character in normalized)


def verify_tenant_identity_or_raise(user, profile_data: dict, nin_number: str, bvn_number: str) -> tuple[dict, dict]:
    identity_data = {
        "first_name": profile_data.get("first_name"),
        "middle_name": profile_data.get("middle_name"),
        "last_name": profile_data.get("last_name"),
        "date_of_birth": profile_data.get("date_of_birth"),
        "gender": profile_data.get("gender"),
        "nationality": profile_data.get("nationality"),
        "state_of_origin": profile_data.get("state_of_origin"),
        "lga": profile_data.get("lga"),
        "mobile": getattr(user, "mobile", ""),
    }
    if not nin_number:
        raise ValidationError({"nin_number": "NIN is required."})
    if not bvn_number:
        raise ValidationError({"bvn_number": "BVN is required."})
    return verify_nin_and_bvn(identity_data, nin_number, bvn_number)


def tenant_verified_identity_matches(user, profile_data: dict, nin_number: str, bvn_number: str) -> bool:
    if not VerificationRequest.objects.filter(
        user=user,
        identity_verification_status=VerificationRequest.VerificationProgressStatus.VERIFIED,
    ).exists():
        return False

    stored_profile = normalize_tenant_verification_profile(user.tenant_verification_profile, user)
    if not stored_profile:
        return False

    submitted_profile = normalize_tenant_verification_profile(
        {
            **profile_data,
            "nin_number": nin_number,
            "bvn_number": bvn_number,
        },
        user,
    )
    identity_fields = (
        "first_name",
        "middle_name",
        "last_name",
        "date_of_birth",
        "gender",
        "nationality",
        "state_of_origin",
        "lga",
        "mobile",
        "nin_number",
        "bvn_number",
    )
    return all(
        str(stored_profile.get(field_name) or "").strip().lower()
        == str(submitted_profile.get(field_name) or "").strip().lower()
        for field_name in identity_fields
    )


def verify_landlord_identity_or_raise(user) -> dict[str, dict]:
    verification_type = user.landlord_verification_type
    profile = user.landlord_verification_profile if isinstance(user.landlord_verification_profile, dict) else {}
    if verification_type == AppUser.LandlordVerificationType.INDIVIDUAL:
        identity_data = {
            "first_name": profile.get("first_name"),
            "middle_name": profile.get("middle_name"),
            "last_name": profile.get("last_name"),
            "date_of_birth": profile.get("date_of_birth"),
            "gender": profile.get("gender"),
            "nationality": profile.get("nationality"),
            "state_of_origin": profile.get("state_of_origin"),
            "lga": profile.get("lga_of_origin"),
            "mobile": profile.get("contact_number") or user.mobile,
        }
        nin_number = str(profile.get("nin") or user.nin_number or "").strip()
        bvn_number = str(profile.get("bvn") or user.bvn_number or "").strip()
        if not nin_number:
            raise ValidationError({"nin": "NIN is required."})
        if not bvn_number:
            raise ValidationError({"bvn": "BVN is required."})
        nin_payload, bvn_payload = verify_nin_and_bvn(identity_data, nin_number, bvn_number)
        payloads = {
            "nin": nin_payload,
            "bvn": bvn_payload,
        }
        user.nin_number = nin_number
        user.bvn_number = bvn_number
        user.save(update_fields=["nin_number", "bvn_number", "updated_at"])
        return payloads
    if verification_type == AppUser.LandlordVerificationType.CORPORATE:
        registration_number = str(profile.get("cac_registration_number") or "").strip()
        if not registration_number:
            raise ValidationError({"cac_registration_number": "CAC registration number is required."})
        return {"cac": verify_cac(profile, registration_number)}
    return {}


def database_healthcheck() -> tuple[bool, dict[str, str]]:
    try:
        connection.ensure_connection()
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")

        executor = MigrationExecutor(connection)
        if executor.migration_plan(executor.loader.graph.leaf_nodes()):
            return False, {
                "status": "unhealthy",
                "environment": settings.ENVIRONMENT,
                "database": "pending_migrations",
            }
    except (OperationalError, ProgrammingError):
        return False, {
            "status": "unhealthy",
            "environment": settings.ENVIRONMENT,
            "database": "unavailable",
        }

    return True, {
        "status": "healthy",
        "environment": settings.ENVIRONMENT,
        "database": "connected",
    }


def set_auth_cookies(response: Response, user) -> None:
    refresh = RefreshToken.for_user(user)
    access = refresh.access_token
    secure = settings.ENVIRONMENT in {"prod", "production", "staging"}
    cookie_domain = settings.COOKIE_DOMAIN or None
    response.set_cookie(settings.ACCESS_COOKIE_NAME, str(access), httponly=True, secure=secure, samesite="Lax", domain=cookie_domain, max_age=60 * int(settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds() / 60))
    response.set_cookie(settings.REFRESH_COOKIE_NAME, str(refresh), httponly=True, secure=secure, samesite="Lax", domain=cookie_domain, max_age=60 * 60 * 24 * 7)


def clear_auth_cookies(response: Response) -> None:
    cookie_domain = settings.COOKIE_DOMAIN or None
    response.delete_cookie(settings.ACCESS_COOKIE_NAME, domain=cookie_domain, path="/")
    response.delete_cookie(settings.REFRESH_COOKIE_NAME, domain=cookie_domain, path="/")


def send_registration_email(user, otp_code: str) -> None:
    from django.core.mail import send_mail

    action_url = build_otp_email_action_url("/register")
    body = build_otp_email_plain_body(
        code=otp_code,
        label="verification",
        action_url=action_url,
    )
    html_body = build_otp_email_html_body(
        email=user.email,
        code=otp_code,
        eyebrow="Email verification",
        headline="Complete your RentDirect registration",
        intro="Use this verification code to finish creating your account.",
        cta_label="Return to email verification",
        action_url=action_url,
    )
    send_mail(
        "Your RentDirect verification code",
        body,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=False,
        html_message=html_body,
    )


def send_settings_otp_email(target_email: str, otp_code: str, purpose: str) -> None:
    from django.core.mail import send_mail

    purpose_label = "account settings update" if purpose == SETTINGS_OTP_PURPOSE_PROFILE else "password change"
    headline = "Confirm your settings update" if purpose == SETTINGS_OTP_PURPOSE_PROFILE else "Confirm your password change"
    intro = f"Use this code to confirm your {purpose_label}."
    action_url = build_otp_email_action_url("/dashboard/settings")
    body = build_otp_email_plain_body(
        code=otp_code,
        label=purpose_label,
        action_url=action_url,
    )
    html_body = build_otp_email_html_body(
        email=target_email,
        code=otp_code,
        eyebrow="Account security",
        headline=headline,
        intro=intro,
        cta_label="Return to settings",
        action_url=action_url,
    )
    send_mail(
        "Your RentDirect settings verification code",
        body,
        settings.DEFAULT_FROM_EMAIL,
        [target_email],
        fail_silently=False,
        html_message=html_body,
    )


def build_otp_email_action_url(path: str) -> str:
    return f"{frontend_site_origin()}{path}"


def build_otp_email_plain_body(*, code: str, label: str, action_url: str) -> str:
    return (
        f"Your RentDirect {label} code is {code}.\n\n"
        f"It expires in {OTP_TTL_MINUTES} minutes. Do not share this code with anyone.\n\n"
        f"Return to RentDirect: {action_url}\n\n"
        "RentDirect Support\n"
        "Email: info@rentdirect.homes\n"
        "Website: https://rentdirect.homes"
    )


def build_otp_email_html_body(
    *,
    email: str,
    code: str,
    eyebrow: str,
    headline: str,
    intro: str,
    cta_label: str,
    action_url: str,
) -> str:
    safe_email = escape(email)
    safe_code = escape(code)
    safe_eyebrow = escape(eyebrow)
    safe_headline = escape(headline)
    safe_intro = escape(intro)
    safe_cta_label = escape(cta_label)
    safe_action_url = escape(action_url)

    return f"""\
<!doctype html>
<html>
  <body style="margin:0;background:#EEF5FF;padding:0;font-family:'Buenos Aires','Open Sans',Arial,Helvetica,sans-serif;color:#0F172A;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#EEF5FF;padding:32px 16px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:640px;overflow:hidden;border-radius:28px;background:#FFFFFF;border:1px solid rgba(37,99,235,0.18);box-shadow:0 24px 70px rgba(15,23,42,0.12);">
            <tr>
              <td style="padding:0;background:#1E40AF;">
                <div style="padding:30px 28px;background:linear-gradient(135deg,#1E40AF 0%,#2563EB 54%,#10B981 100%);">
                  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                    <tr>
                      <td style="vertical-align:middle;">
                        <div style="display:inline-block;border-radius:18px;background:#FFFFFF;padding:12px 14px;color:#1E40AF;font-size:18px;font-weight:900;letter-spacing:0;">RentDirect</div>
                      </td>
                      <td align="right" style="vertical-align:middle;">
                        <span style="display:inline-block;border-radius:999px;background:rgba(255,255,255,0.16);border:1px solid rgba(255,255,255,0.38);padding:8px 12px;color:#FFFFFF;font-size:11px;font-weight:800;letter-spacing:0.14em;text-transform:uppercase;">{safe_eyebrow}</span>
                      </td>
                    </tr>
                  </table>
                  <h1 style="margin:28px 0 0;color:#FFFFFF;font-size:32px;line-height:1.08;font-weight:900;letter-spacing:0;">{safe_headline}</h1>
                  <p style="margin:14px 0 0;color:#DBEAFE;font-size:15px;line-height:1.7;">{safe_intro}</p>
                </div>
              </td>
            </tr>
            <tr>
              <td style="padding:30px 28px 8px;background:#FFFFFF;">
                <p style="margin:0;color:#475569;font-size:14px;line-height:1.7;">This code was requested for <strong style="color:#0F172A;">{safe_email}</strong>.</p>
                <div style="margin:24px 0;border-radius:22px;background:#F8FBFF;border:1px solid #DBEAFE;padding:22px;text-align:center;">
                  <p style="margin:0 0 10px;color:#1E40AF;font-size:11px;font-weight:800;letter-spacing:0.18em;text-transform:uppercase;">Your secure code</p>
                  <div style="color:#0F172A;font-size:40px;line-height:1;font-weight:900;letter-spacing:0.18em;">{safe_code}</div>
                  <p style="margin:12px 0 0;color:#64748B;font-size:12px;">Expires in {OTP_TTL_MINUTES} minutes.</p>
                </div>
                <table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 auto 22px;">
                  <tr>
                    <td style="border-radius:999px;background:#10B981;">
                      <a href="{safe_action_url}" style="display:inline-block;padding:14px 22px;color:#FFFFFF;text-decoration:none;font-size:14px;font-weight:900;">{safe_cta_label}</a>
                    </td>
                  </tr>
                </table>
                <p style="margin:0;color:#64748B;font-size:12px;line-height:1.7;text-align:center;">If the button does not work, copy and paste this link into your browser:<br><a href="{safe_action_url}" style="color:#2563EB;text-decoration:none;">{safe_action_url}</a></p>
              </td>
            </tr>
            <tr>
              <td style="padding:26px 28px 30px;background:#0F172A;border-top:1px solid rgba(255,255,255,0.08);">
                <p style="margin:0;color:#FFFFFF;font-size:14px;font-weight:900;">RentDirect Support</p>
                <p style="margin:8px 0 0;color:#CBD5E1;font-size:12px;line-height:1.7;">Simple, direct renting for tenants and landlords.<br>Email: <a href="mailto:info@rentdirect.homes" style="color:#93C5FD;text-decoration:none;">info@rentdirect.homes</a> · Web: <a href="https://rentdirect.homes" style="color:#93C5FD;text-decoration:none;">rentdirect.homes</a></p>
                <p style="margin:18px 0 0;color:#94A3B8;font-size:11px;line-height:1.6;">For your security, RentDirect will never ask you to share this code by phone, chat, or social media.</p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""


def clear_settings_otp(user, *, save: bool = True) -> None:
    user.settings_otp_hash = ""
    user.settings_otp_expires_at = None
    user.settings_otp_attempts = 0
    user.settings_otp_purpose = ""
    user.settings_otp_target_email = ""
    if save:
        user.save(
            update_fields=[
                "settings_otp_hash",
                "settings_otp_expires_at",
                "settings_otp_attempts",
                "settings_otp_purpose",
                "settings_otp_target_email",
                "updated_at",
            ]
        )


def begin_settings_otp_challenge(user, *, purpose: str, target_email: str) -> None:
    otp_code = generate_otp()
    user.settings_otp_hash = hash_otp(target_email, otp_code)
    user.settings_otp_expires_at = timezone.now() + timedelta(minutes=OTP_TTL_MINUTES)
    user.settings_otp_attempts = 0
    user.settings_otp_purpose = purpose
    user.settings_otp_target_email = target_email
    user.save(
        update_fields=[
            "settings_otp_hash",
            "settings_otp_expires_at",
            "settings_otp_attempts",
            "settings_otp_purpose",
            "settings_otp_target_email",
            "updated_at",
        ]
    )
    send_settings_otp_email(target_email, otp_code, purpose)


def ensure_valid_settings_otp(user, *, purpose: str, target_email: str, code: str) -> None:
    normalized_target = target_email.strip().lower()
    normalized_code = code.strip().upper()

    if not normalized_code:
        raise ValidationError({"otp_code": "Verification code is required."})
    if user.settings_otp_purpose != purpose or user.settings_otp_target_email.strip().lower() != normalized_target:
        raise ValidationError({"otp_code": "Request a new verification code before continuing."})
    if user.settings_otp_attempts >= OTP_MAX_ATTEMPTS:
        raise ValidationError({"otp_code": "Too many invalid verification attempts. Request a new code."})
    if not user.settings_otp_expires_at or user.settings_otp_expires_at < timezone.now():
        raise ValidationError({"otp_code": "Verification code has expired. Request a new code."})
    if not otp_matches(user.settings_otp_hash, normalized_target, normalized_code):
        user.settings_otp_attempts += 1
        user.save(update_fields=["settings_otp_attempts", "updated_at"])
        remaining = max(OTP_MAX_ATTEMPTS - user.settings_otp_attempts, 0)
        raise ValidationError({"otp_code": f"Invalid verification code. {remaining} attempts remaining."})


def frontend_site_origin() -> str:
    return settings.WEB_PUBLIC_URL.rstrip("/")


def block_production_mock(feature: str) -> None:
    if settings.ENFORCE_PRODUCTION_HARDENING:
        raise ValidationError(f"{feature} is disabled in production.")


def verification_progress_to_legacy_status(progress_status: str) -> str:
    if progress_status == VerificationRequest.VerificationProgressStatus.VERIFIED:
        return VerificationRequest.Status.APPROVED
    if progress_status == VerificationRequest.VerificationProgressStatus.PENDING:
        return VerificationRequest.Status.PENDING
    return VerificationRequest.Status.REJECTED


def build_flutterwave_webhook_url() -> str | None:
    explicit = settings.FLUTTERWAVE_WEBHOOK_URL.strip()
    if explicit:
        return explicit
    api_public_url = settings.API_PUBLIC_URL.rstrip("/")
    if not api_public_url or "localhost" in api_public_url or "127.0.0.1" in api_public_url:
        return None
    return f"{api_public_url}/api/v1/payments/webhook/flutterwave"


def build_booking_payment_return_url(payment: Payment) -> str:
    return f"{frontend_site_origin()}/rent/{payment.booking.listing_id}"


def build_featured_payment_return_url(payment: FeaturedPayment) -> str:
    return f"{frontend_site_origin()}/dashboard/featured-properties/pay/{payment.id}"


def build_subscription_payment_return_url(payment: SubscriptionPayment) -> str:
    return f"{frontend_site_origin()}/billing/subscriptions/pay/{payment.id}"


def exclude_deposit_secured_listings(queryset):
    return queryset.exclude(id__in=deposit_secured_booking_queryset().values("listing_id"))


def subtract_calendar_months(value, months: int):
    year = value.year
    month = value.month - months
    while month <= 0:
        month += 12
        year -= 1
    day = min(value.day, monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def resolve_landlord_profile_payload(landlord: AppUser) -> dict:
    if isinstance(landlord.landlord_verification_profile, dict):
        return landlord.landlord_verification_profile
    return {}


def resolve_landlord_display_name(landlord: AppUser) -> str:
    profile = resolve_landlord_profile_payload(landlord)
    if landlord.landlord_verification_type == AppUser.LandlordVerificationType.CORPORATE:
        company_information = profile.get("company_information") or {}
        company_name = str(company_information.get("registered_company_name") or profile.get("company_name") or "").strip()
        if company_name:
            return company_name
    return landlord.name


def resolve_landlord_subtitle(landlord: AppUser) -> str:
    if landlord.landlord_verification_type == AppUser.LandlordVerificationType.CORPORATE:
        profile = resolve_landlord_profile_payload(landlord)
        representative = str(profile.get("contact_person_name") or landlord.name or "").strip()
        return representative or "Corporate landlord"
    return "Individual landlord"


def calculate_landlord_average_response_seconds(landlord: AppUser) -> float | None:
    landlord_id = landlord.id
    pending_replies = {}
    response_durations: list[float] = []
    message_rows = (
        Message.objects
        .filter(Q(sender=landlord) | Q(receiver=landlord))
        .order_by("created_at")
        .values_list("sender_id", "receiver_id", "listing_id", "created_at")
    )

    for sender_id, receiver_id, listing_id, created_at in message_rows:
        counterpart_id = receiver_id if sender_id == landlord_id else sender_id
        conversation_key = (str(counterpart_id), str(listing_id or ""))

        if receiver_id == landlord_id:
            pending_replies.setdefault(conversation_key, created_at)
            continue

        if sender_id == landlord_id and conversation_key in pending_replies:
            started_at = pending_replies.pop(conversation_key)
            duration_seconds = (created_at - started_at).total_seconds()
            if duration_seconds >= 0:
                response_durations.append(duration_seconds)

    if not response_durations:
        return None

    return sum(response_durations) / len(response_durations)


def format_average_response_time(seconds: float | None) -> str:
    if seconds is None:
        return "No replies yet"
    if seconds < 3600:
        minutes = max(int(round(seconds / 60)), 1)
        return f"{minutes} min"
    if seconds < 86400:
        hours = round(seconds / 3600, 1)
        return f"{hours} hrs"
    days = round(seconds / 86400, 1)
    return f"{days} days"


def build_landlord_public_profile_payload(landlord: AppUser) -> dict:
    listings = (
        Listing.objects
        .filter(landlord=landlord)
        .exclude(status=Listing.Status.ARCHIVED)
        .order_by("-created_at")
    )
    bookings = Booking.objects.filter(listing__landlord=landlord)
    reviews = Review.objects.filter(landlord=landlord).select_related("tenant", "listing").order_by("-created_at")
    review_stats = reviews.aggregate(average_rating=Avg("rating"))
    average_rating = float(review_stats["average_rating"] or 0)
    review_count = reviews.count()
    active_tenancies = bookings.filter(status__in=[Booking.Status.CONFIRMED, Booking.Status.ACTIVE]).count()
    completed_tenancies = bookings.filter(status=Booking.Status.COMPLETED).count()
    successful_rentals = bookings.filter(
        status__in=[Booking.Status.CONFIRMED, Booking.Status.ACTIVE, Booking.Status.COMPLETED],
    ).count()
    total_applications = bookings.count()
    latest_verification = VerificationRequest.objects.filter(user=landlord).order_by("-submitted_at").first()
    average_response_seconds = calculate_landlord_average_response_seconds(landlord)
    years_on_platform = round(max((timezone.now().date() - landlord.created_at.date()).days / 365.25, 0), 1)

    identity_verified = bool(
        latest_verification
        and latest_verification.identity_verification_status == VerificationRequest.VerificationProgressStatus.VERIFIED
    )
    house_ownership_verified = bool(
        listings.filter(property_document_verification_status=VerificationRequest.VerificationProgressStatus.VERIFIED).exists()
    )
    phone_verified = bool((landlord.mobile or "").strip())
    email_verified = bool(landlord.email_verified)

    return {
        "id": str(landlord.id),
        "display_name": resolve_landlord_display_name(landlord),
        "subtitle": resolve_landlord_subtitle(landlord),
        "full_name": landlord.name,
        "role": landlord.role,
        "landlord_verification_type": landlord.landlord_verification_type,
        "profile_photo_url": landlord.profile_photo_url,
        "verification_badges": {
            "identity_verified": identity_verified,
            "house_ownership_verified": house_ownership_verified,
            "phone_verified": phone_verified,
            "email_verified": email_verified,
        },
        "metrics": {
            "properties_listed": listings.count(),
            "active_tenancies": active_tenancies,
            "completed_tenancies": completed_tenancies,
            "average_rating": round(average_rating, 1) if review_count else 0.0,
            "tenant_satisfaction_score": round((average_rating / 5) * 100, 1) if review_count else 0.0,
            "average_response_time": format_average_response_time(average_response_seconds),
            "application_approval_rate": round((successful_rentals / total_applications) * 100, 1) if total_applications else 0.0,
            "years_on_platform": years_on_platform,
            "successful_rentals": successful_rentals,
            "reviews_count": review_count,
        },
        "listings": [
            {
                "id": str(listing.id),
                "title": listing.title,
                "status": listing.status,
            }
            for listing in listings[:20]
        ],
        "reviews": [
            {
                "id": str(review.id),
                "rating": review.rating,
                "comment": review.comment,
                "created_at": review.created_at,
                "tenant_name": review.tenant.name,
                "listing_id": str(review.listing_id),
                "listing_title": review.listing.title,
            }
            for review in reviews[:10]
        ],
    }


def build_booking_checkout(payment: Payment) -> dict:
    booking = payment.booking
    return build_checkout_payload(
        reference=payment.transaction_id,
        amount=payment.amount,
        currency=payment.currency,
        email=booking.tenant.email,
        redirect_url=build_booking_payment_return_url(payment),
        payment_method=payment.payment_method,
        title="RentDirect Rental Payment",
        description=f"Payment for {booking.listing.title}",
        metadata={
            "payment_id": str(payment.id),
            "booking_id": str(booking.id),
            "listing_id": str(booking.listing_id),
            "customer_type": "tenant",
        },
        customer_name=booking.tenant.name,
        customer_phone=booking.tenant.mobile,
        webhook_url=build_flutterwave_webhook_url(),
    )


def build_booking_virtual_account_payload(payment: Payment) -> dict:
    stored_account_details = {}
    if isinstance(payment.virtual_account_payload, dict):
        stored_account_details = extract_virtual_account_details(
            payment.virtual_account_payload.get("virtual_account")
        )
    checkout = build_booking_checkout(payment)
    account = {
        "reference": payment.virtual_account_reference or stored_account_details.get("reference") or payment.transaction_id,
        "account_number": payment.virtual_account_number,
        "bank_name": payment.virtual_account_bank_name or stored_account_details.get("bank_name", ""),
        "bank_code": payment.virtual_account_bank_code or stored_account_details.get("bank_code", ""),
        "expires_at": payment.virtual_account_expiry.isoformat() if payment.virtual_account_expiry else None,
    }
    return {
        "checkout_mode": "virtual_account",
        "reference": payment.transaction_id,
        "amount": float(normalize_decimal_amount(payment.amount)),
        "currency": payment.currency,
        "virtual_account": account,
        "redirect_url": checkout.get("redirect_url", ""),
        "flutterwave": checkout.get("flutterwave"),
    }


def clear_payment_virtual_account_fields(payment: Payment) -> list[str]:
    fields = [
        "virtual_account_reference",
        "virtual_account_id",
        "virtual_account_number",
        "virtual_account_bank_name",
        "virtual_account_bank_code",
    ]
    changed_fields = []
    for field in fields:
        if getattr(payment, field):
            setattr(payment, field, "")
            changed_fields.append(field)
    if payment.virtual_account_payload is not None:
        payment.virtual_account_payload = None
        changed_fields.append("virtual_account_payload")
    if payment.virtual_account_expiry is not None:
        payment.virtual_account_expiry = None
        changed_fields.append("virtual_account_expiry")
    return changed_fields


def ensure_booking_virtual_account(payment: Payment) -> dict:
    if payment.virtual_account_number:
        return build_booking_virtual_account_payload(payment)

    if not is_valid_flutterwave_reference(payment.transaction_id):
        payment.transaction_id = build_booking_payment_reference()
        payment.save(update_fields=["transaction_id", "updated_at"])

    booking = payment.booking
    customer_response = create_customer(
        email=booking.tenant.email,
        full_name=booking.tenant.name,
        phone_number=booking.tenant.mobile,
        metadata={
            "user_id": str(booking.tenant_id),
            "booking_id": str(booking.id),
            "payment_id": str(payment.id),
        },
        idempotency_key=f"{payment.transaction_id}-customer",
    )
    customer_id = extract_resource_id(customer_response)
    if not customer_id:
        raise FlutterwaveError("Flutterwave did not return a customer id for this payment.")

    virtual_account_response = create_dynamic_virtual_account(
        reference=payment.transaction_id,
        customer_id=customer_id,
        amount=payment.amount,
        currency=payment.currency,
        expiry_seconds=settings.FLUTTERWAVE_VIRTUAL_ACCOUNT_EXPIRY_SECONDS,
        bvn=booking.tenant.bvn_number,
        nin=booking.tenant.nin_number,
        narration=f"RentDirect {booking.tenant.name}",
        metadata={
            "payment_id": str(payment.id),
            "booking_id": str(booking.id),
            "listing_id": str(booking.listing_id),
            "tenant_id": str(booking.tenant_id),
            "landlord_id": str(booking.listing.landlord_id),
            "customer_type": "tenant",
        },
        idempotency_key=f"{payment.transaction_id}-virtual-account",
    )
    account_details = extract_virtual_account_details(virtual_account_response)
    if not account_details["account_number"]:
        raise FlutterwaveError("Flutterwave did not return a virtual account number for this payment.")

    payment.virtual_account_reference = account_details["reference"] or payment.transaction_id
    payment.virtual_account_id = account_details["id"]
    payment.virtual_account_number = account_details["account_number"]
    payment.virtual_account_bank_name = account_details["bank_name"]
    payment.virtual_account_bank_code = account_details["bank_code"]
    payment.virtual_account_expiry = timezone.now() + timedelta(seconds=settings.FLUTTERWAVE_VIRTUAL_ACCOUNT_EXPIRY_SECONDS)
    payment.virtual_account_payload = {
        "customer": customer_response,
        "virtual_account": virtual_account_response,
    }
    payment.save(
        update_fields=[
            "virtual_account_reference",
            "virtual_account_id",
            "virtual_account_number",
            "virtual_account_bank_name",
            "virtual_account_bank_code",
            "virtual_account_expiry",
            "virtual_account_payload",
            "updated_at",
        ]
    )
    return build_booking_virtual_account_payload(payment)


def prepare_booking_payment_checkout(payment: Payment) -> tuple[dict, str, list[str]]:
    if payment.payment_method == "bank":
        return ensure_booking_virtual_account(payment), "dynamic_virtual_account", []

    cleared_fields = clear_payment_virtual_account_fields(payment)
    return build_booking_checkout(payment), "inline_checkout", cleared_fields


def build_featured_checkout(payment: FeaturedPayment) -> dict:
    listing = payment.listing
    return build_checkout_payload(
        reference=payment.transaction_id or f"FEAT_{uuid.uuid4().hex[:20].upper()}",
        amount=payment.amount,
        currency=payment.currency,
        email=payment.landlord.email,
        redirect_url=build_featured_payment_return_url(payment),
        payment_method="card",
        title="RentDirect Featured Listing",
        description=f"Featured placement for {listing.title}",
        metadata={
            "featured_payment_id": str(payment.id),
            "listing_id": str(listing.id),
            "customer_type": "landlord",
        },
        customer_name=payment.landlord.name,
        customer_phone=payment.landlord.mobile,
        webhook_url=build_flutterwave_webhook_url(),
    )


def build_subscription_checkout(payment: SubscriptionPayment) -> dict:
    return build_checkout_payload(
        reference=payment.transaction_id or build_subscription_payment_reference(),
        amount=payment.amount,
        currency=payment.currency,
        email=payment.user.email,
        redirect_url=build_subscription_payment_return_url(payment),
        payment_method=None,
        title="RentDirect Subscription",
        description=f"{payment.role.title()} {payment.plan_code.title()} plan",
        metadata={
            "subscription_payment_id": str(payment.id),
            "user_id": str(payment.user_id),
            "customer_type": payment.role,
            "plan_code": payment.plan_code,
            "billing_cycle": payment.billing_cycle,
        },
        customer_name=payment.user.name,
        customer_phone=payment.user.mobile,
        webhook_url=build_flutterwave_webhook_url(),
    )


def subscription_duration_days(billing_cycle: str) -> int:
    return 30 if billing_cycle == SubscriptionPayment.BillingCycle.MONTHLY else 365


def ensure_flutterwave_recurring_configured() -> None:
    ensure_flutterwave_recurring_charge_configured()
    if not flutterwave_encryption_key_is_configured():
        raise ValidationError("Flutterwave card encryption is not configured on the server.")


def ensure_flutterwave_recurring_charge_configured() -> None:
    if not should_use_v4():
        raise ValidationError("Flutterwave recurring card payments require v4 client credentials.")


def flutterwave_encryption_key_is_configured() -> bool:
    encryption_key = str(getattr(settings, "FLUTTERWAVE_ENCRYPTION_KEY", "") or "").strip()
    if not encryption_key:
        return False
    try:
        decoded_key = base64.b64decode(encryption_key, validate=True)
    except (ValueError, binascii.Error):
        return False
    return len(decoded_key) in {16, 24, 32}


def upsert_subscription_payment_method(
    *,
    user: AppUser,
    customer_id: str,
    payment_method_response: dict,
) -> SubscriptionPaymentMethod:
    card_details = extract_payment_method_card_details(payment_method_response)
    provider_payment_method_id = card_details["id"]
    if not provider_payment_method_id:
        raise FlutterwaveError("Flutterwave did not return a payment method id.")

    existing_method = SubscriptionPaymentMethod.objects.filter(
        provider_payment_method_id=provider_payment_method_id,
    ).first()
    if existing_method and existing_method.user_id != user.id:
        raise ValidationError("This payment method belongs to another account.")

    stored_customer_id = card_details["customer_id"] or customer_id
    payment_method, _ = SubscriptionPaymentMethod.objects.update_or_create(
        provider_payment_method_id=provider_payment_method_id,
        defaults={
            "user": user,
            "provider": "flutterwave",
            "provider_customer_id": stored_customer_id,
            "payment_type": card_details["type"] or "card",
            "status": SubscriptionPaymentMethod.Status.ACTIVE,
            "card_first6": card_details["first6"],
            "card_last4": card_details["last4"],
            "card_network": card_details["network"],
            "card_expiry_month": card_details["expiry_month"] or None,
            "card_expiry_year": card_details["expiry_year"] or None,
            "provider_payload": payment_method_response,
        },
    )
    return payment_method


def resolve_subscription_payment_method(user: AppUser, validated_data: dict) -> SubscriptionPaymentMethod:
    payment_method_id = validated_data.get("payment_method_id")
    if payment_method_id:
        return get_object_or_404(
            SubscriptionPaymentMethod,
            id=payment_method_id,
            user=user,
            provider="flutterwave",
            status=SubscriptionPaymentMethod.Status.ACTIVE,
        )

    encrypted_card = validated_data.get("card")
    if not encrypted_card:
        raise ValidationError({"card": "Card details are required to enable recurring payments."})

    ensure_flutterwave_recurring_configured()
    customer_response = create_customer(
        email=user.email,
        full_name=user.name,
        phone_number=user.mobile,
        metadata={"user_id": str(user.id), "role": user.role, "purpose": "subscription_recurring"},
        idempotency_key=f"sub-recurring-customer-{user.id}",
    )
    customer_id = extract_resource_id(customer_response)
    if not customer_id:
        raise FlutterwaveError("Flutterwave did not return a customer id for recurring payments.")

    payment_method_response = create_card_payment_method(
        customer_id=customer_id,
        encrypted_card=encrypted_card,
        metadata={"user_id": str(user.id), "role": user.role, "purpose": "subscription_recurring"},
        idempotency_key=f"sub-recurring-card-{user.id}-{encrypted_card.get('nonce')}",
    )
    return upsert_subscription_payment_method(
        user=user,
        customer_id=customer_id,
        payment_method_response=payment_method_response,
    )


def charge_subscription_with_payment_method(payment: SubscriptionPayment, *, source: str) -> SubscriptionPayment:
    if not payment.payment_method:
        raise ValidationError("A saved card is required for recurring subscription charges.")
    ensure_flutterwave_recurring_charge_configured()
    if not payment.transaction_id:
        payment.transaction_id = build_subscription_payment_reference()
        payment.save(update_fields=["transaction_id", "updated_at"])

    payment_method = payment.payment_method
    charge_payload = create_charge(
        reference=payment.transaction_id,
        amount=payment.amount,
        currency=payment.currency,
        customer_id=payment_method.provider_customer_id,
        payment_method_id=payment_method.provider_payment_method_id,
        redirect_url=build_subscription_payment_return_url(payment),
        recurring=True,
        metadata={
            "subscription_payment_id": str(payment.id),
            "user_id": str(payment.user_id),
            "customer_type": payment.role,
            "plan_code": payment.plan_code,
            "billing_cycle": payment.billing_cycle,
            "billing_reason": payment.billing_reason,
        },
        idempotency_key=f"{payment.transaction_id}-recurring-charge",
    )
    payment.provider_charge_id = extract_provider_transaction_id(charge_payload)
    payment.provider_payload = update_payment_provider_payload(
        payment.provider_payload,
        charge_payload,
        recurring={"source": source, "charged_at": timezone.now().isoformat()},
    )
    payment.provider = "flutterwave"
    payment.save(update_fields=["provider_charge_id", "provider_payload", "provider", "updated_at"])
    return sync_subscription_payment(payment, payload=charge_payload, source=source)


def process_due_subscription_renewals(*, now=None) -> dict[str, int]:
    now = now or timezone.now()
    due_payments = (
        SubscriptionPayment.objects.select_related("user", "payment_method")
        .filter(
            status=SubscriptionPayment.Status.COMPLETED,
            recurring_enabled=True,
            amount__gt=0,
            expires_at__lte=now,
            payment_method__status=SubscriptionPaymentMethod.Status.ACTIVE,
        )
        .filter(renewal_payments__isnull=True)
        .order_by("expires_at", "created_at")
    )

    checked = 0
    renewed = 0
    failed = 0
    for payment in due_payments:
        checked += 1
        renewal = SubscriptionPayment.objects.create(
            user=payment.user,
            role=payment.role,
            plan_code=payment.plan_code,
            billing_cycle=payment.billing_cycle,
            amount=payment.amount,
            currency=payment.currency,
            provider="flutterwave",
            status=SubscriptionPayment.Status.PENDING,
            transaction_id=build_subscription_payment_reference(),
            expires_at=payment.expires_at + timedelta(days=subscription_duration_days(payment.billing_cycle)),
            payment_method=payment.payment_method,
            recurring_enabled=True,
            billing_reason="recurring_renewal",
            renewed_from=payment,
        )
        try:
            renewal = charge_subscription_with_payment_method(renewal, source="recurring_renewal")
        except (FlutterwaveError, ValidationError) as exc:
            renewal.status = SubscriptionPayment.Status.FAILED
            renewal.recurring_enabled = False
            renewal.provider_payload = update_payment_provider_payload(
                renewal.provider_payload,
                None,
                recurring_error={"message": str(exc), "failed_at": timezone.now().isoformat()},
            )
            renewal.save(update_fields=["status", "recurring_enabled", "provider_payload", "updated_at"])
            payment.recurring_enabled = False
            payment.save(update_fields=["recurring_enabled", "updated_at"])
            failed += 1
            continue

        if renewal.status == SubscriptionPayment.Status.COMPLETED:
            renewed += 1
        else:
            failed += 1

    return {"checked": checked, "renewed": renewed, "failed": failed}


def verify_flutterwave_request_signature(request) -> Response | None:
    signature = (
        request.headers.get("verif-hash")
        or request.headers.get("Verif-Hash")
        or request.headers.get("X-Flutterwave-Signature")
        or ""
    )
    if settings.ENFORCE_FLUTTERWAVE_WEBHOOK_SIGNATURE and not settings.FLUTTERWAVE_WEBHOOK_SECRET_HASH:
        return Response({"status": "error", "message": "Webhook verification unavailable"}, status=503)
    if not settings.FLUTTERWAVE_WEBHOOK_SECRET_HASH:
        return None
    if verify_webhook_signature(raw_body=request.body, signature=signature):
        return None
    return Response({"status": "error", "message": "Invalid signature"}, status=400)


def update_payment_provider_payload(current_payload, incoming_payload: dict | None, **extra) -> dict:
    payload = current_payload.copy() if isinstance(current_payload, dict) else {}
    if incoming_payload:
        payload["charge"] = incoming_payload
    for key, value in extra.items():
        if value is not None:
            payload[key] = value
    return payload


def resolve_account_payload(*, bank_name: str, account_number: str, account_name: str = "", bank_code: str = "") -> dict:
    bank_name = str(bank_name or "").strip()
    bank_code = str(bank_code or "").strip()
    if not bank_code:
        normalized_bank_name = bank_name.lower().replace(" ", "").replace("-", "")
        bank_code = {
            "opay": "100004",
            "paycom": "100004",
            "palmpay": "100033",
            "moniepoint": "50515",
            "moniepointmfb": "50515",
            "moniepointmicrofinancebank": "50515",
        }.get(normalized_bank_name, "")
    return {
        "bank_name": bank_name,
        "bank_code": bank_code,
        "account_number": str(account_number or "").strip(),
        "account_name": str(account_name or "").strip(),
    }


def resolve_landlord_payout_account(landlord: AppUser) -> dict:
    profile = resolve_landlord_profile_payload(landlord)
    banking_information = profile.get("banking_information") if isinstance(profile.get("banking_information"), dict) else {}
    corporate_banking = (
        profile.get("corporate_banking_information")
        if isinstance(profile.get("corporate_banking_information"), dict)
        else {}
    )
    for candidate in (banking_information, corporate_banking, profile):
        account = resolve_account_payload(
            bank_name=candidate.get("bank_name", ""),
            bank_code=candidate.get("bank_code", ""),
            account_number=candidate.get("account_number", ""),
            account_name=candidate.get("account_name", ""),
        )
        if account["bank_name"] and account["account_number"]:
            return account

    return resolve_account_payload(bank_name="", account_number="", account_name=landlord.name)


CARD_PAYMENT_LIMIT_NGN = Decimal("7000000.00")


def booking_payments_card_limit_exceeded(amount: Decimal) -> bool:
    return normalize_decimal_amount(amount) > CARD_PAYMENT_LIMIT_NGN


def completed_booking_payment_queryset(booking: Booking):
    return (
        Payment.objects
        .filter(booking=booking, status="completed")
        .order_by("payment_date", "created_at", "id")
    )


def get_booking_full_payment_completion(booking: Booking) -> tuple[Payment | None, object | None]:
    total_due = resolve_booking_total(booking.listing.price_per_year, booking.total_amount)
    cumulative_paid = Decimal("0")

    for completed_payment in completed_booking_payment_queryset(booking):
        cumulative_paid += normalize_decimal_amount(completed_payment.amount)
        if cumulative_paid >= total_due:
            paid_at = completed_payment.payment_date or completed_payment.updated_at or completed_payment.created_at
            return completed_payment, paid_at

    return None, None


def booking_is_fully_paid(booking: Booking) -> bool:
    completion_payment, _completed_at = get_booking_full_payment_completion(booking)
    return completion_payment is not None


def validate_booking_payment_amount(booking: Booking, amount: Decimal, payment_method: str) -> None:
    normalized_amount = normalize_decimal_amount(amount)
    total_amount = resolve_booking_total(booking.listing.price_per_year, booking.total_amount)
    remaining_balance = calculate_remaining_balance(total_amount, booking.paid_amount)

    if normalized_amount <= 0:
        raise ValidationError({"amount": "Amount must be greater than zero."})
    if normalized_amount > remaining_balance:
        raise ValidationError({"amount": "Amount exceeds the remaining balance."})

    deposit_amount = calculate_deposit_amount(booking.listing.price_per_year)
    paid_amount = normalize_decimal_amount(booking.paid_amount)
    valid_initial_deposit = paid_amount == Decimal("0.00") and normalized_amount == deposit_amount
    valid_full_balance = normalized_amount == remaining_balance
    if not (valid_initial_deposit or valid_full_balance):
        raise ValidationError(
            {
                "amount": (
                    "Payment must be either the 20% deposit "
                    f"({deposit_amount}) or the full remaining balance ({remaining_balance})."
                )
            }
        )

    if payment_method == "card" and booking_payments_card_limit_exceeded(normalized_amount):
        raise ValidationError(
            {
                "payment_method": (
                    "Flutterwave card payments are limited to NGN 7,000,000 per transaction. "
                    "Please use Bank Transfer for this payment."
                )
            }
        )


def build_payment_settlement_specs(payment: Payment) -> list[dict]:
    annual_rent = normalize_decimal_amount(payment.booking.listing.price_per_year)
    landlord_account = resolve_landlord_payout_account(payment.booking.listing.landlord)
    target_specs = [
        {
            "purpose": PaymentSettlement.Purpose.OPERATIONS,
            "target_amount": normalize_decimal_amount(annual_rent * Decimal("0.10")),
            **resolve_account_payload(
                bank_name=settings.RENTDIRECT_OPERATING_BANK_NAME,
                bank_code=settings.RENTDIRECT_OPERATING_BANK_CODE,
                account_number=settings.RENTDIRECT_OPERATING_ACCOUNT_NUMBER,
                account_name=settings.RENTDIRECT_OPERATING_ACCOUNT_NAME,
            ),
        },
        {
            "purpose": PaymentSettlement.Purpose.CAUTION_FEE,
            "target_amount": normalize_decimal_amount(annual_rent * Decimal("0.10")),
            **resolve_account_payload(
                bank_name=settings.TENANT_CAUTION_HOLDING_BANK_NAME,
                bank_code=settings.TENANT_CAUTION_HOLDING_BANK_CODE,
                account_number=settings.TENANT_CAUTION_HOLDING_ACCOUNT_NUMBER,
                account_name=settings.TENANT_CAUTION_HOLDING_ACCOUNT_NAME,
            ),
        },
        {
            "purpose": PaymentSettlement.Purpose.LANDLORD_RENT,
            "target_amount": annual_rent,
            **landlord_account,
        },
    ]

    specs = []
    for spec in target_specs:
        already_paid = PaymentSettlement.objects.filter(
            payment__booking=payment.booking,
            purpose=spec["purpose"],
            status=PaymentSettlement.Status.PAID,
        ).exclude(payment=payment).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        amount = normalize_decimal_amount(max(spec["target_amount"] - normalize_decimal_amount(already_paid), Decimal("0")))
        if amount <= 0:
            continue
        specs.append({**spec, "amount": amount})

    missing_accounts = [
        spec["purpose"]
        for spec in specs
        if not spec["amount"] or not spec["bank_name"] or not spec["account_number"]
    ]
    if missing_accounts:
        raise FlutterwaveError(f"Missing payout account details for: {', '.join(missing_accounts)}")
    return specs


def booking_payout_release_conditions_met(booking: Booking) -> bool:
    tenant_progress = booking.tenant_rental_progress if isinstance(booking.tenant_rental_progress, dict) else {}
    landlord_progress = booking.landlord_rental_progress if isinstance(booking.landlord_rental_progress, dict) else {}
    return (
        booking_progress_step_completed(tenant_progress, "tenant_collected_house_key")
        and booking_progress_step_completed(landlord_progress, "tenant_collected_house_key")
        and booking_progress_step_selected_value(tenant_progress, "rentdirect_transfer_to_landlord") == "yes"
    )


def booking_payout_balance_available(booking: Booking, now=None) -> bool:
    _completion_payment, paid_at = get_booking_full_payment_completion(booking)
    if not paid_at:
        return False
    payout_balance_delay = timedelta(hours=max(int(getattr(settings, "FLUTTERWAVE_PAYOUT_BALANCE_DELAY_HOURS", 24)), 0))
    return (now or timezone.now()) >= paid_at + payout_balance_delay


def build_settlement_transfer_reference(payment: Payment, settlement: PaymentSettlement) -> str:
    base_reference = payment.transaction_id or str(payment.id)
    suffix = settlement.purpose.upper().replace("_", "")
    return f"{base_reference}-{suffix}"[:120]


def map_transfer_status_to_settlement_status(payload: dict | None) -> str:
    provider_state = extract_payment_state(payload)
    if provider_state == "completed":
        return PaymentSettlement.Status.PAID
    if provider_state in {"failed", "cancelled"}:
        return PaymentSettlement.Status.FAILED
    return PaymentSettlement.Status.PROCESSING


def sync_payment_settlement_transfer(settlement: PaymentSettlement, payload: dict | None) -> PaymentSettlement:
    next_status = map_transfer_status_to_settlement_status(payload)
    settlement.transfer_payload = payload
    settlement.last_error = "" if next_status != PaymentSettlement.Status.FAILED else "Flutterwave transfer failed."
    settlement.status = next_status
    update_fields = ["transfer_payload", "last_error", "status", "updated_at"]
    if next_status == PaymentSettlement.Status.PAID and settlement.transferred_at is None:
        settlement.transferred_at = timezone.now()
        update_fields.append("transferred_at")
    settlement.save(update_fields=update_fields)
    return settlement


def ensure_payment_settlement_records(payment: Payment) -> None:
    PaymentSettlement.objects.filter(payment__booking=payment.booking).exclude(payment=payment).exclude(
        status=PaymentSettlement.Status.PAID,
    ).delete()

    for spec in build_payment_settlement_specs(payment):
        defaults = {
            "amount": spec["amount"],
            "currency": payment.currency,
            "bank_name": spec["bank_name"],
            "bank_code": spec["bank_code"],
            "account_number": spec["account_number"],
            "account_name": spec["account_name"],
        }
        settlement, created = PaymentSettlement.objects.get_or_create(
            payment=payment,
            purpose=spec["purpose"],
            defaults=defaults,
        )
        if not created and settlement.status != PaymentSettlement.Status.PAID:
            PaymentSettlement.objects.filter(pk=settlement.pk).update(**defaults, updated_at=timezone.now())


logger = logging.getLogger(__name__)


def trigger_payment_settlements(payment: Payment) -> None:
    if payment.status != "completed" or not booking_payout_release_conditions_met(payment.booking):
        return

    completion_payment, _full_payment_completed_at = get_booking_full_payment_completion(payment.booking)
    if not completion_payment or completion_payment.pk != payment.pk:
        return
    if not booking_payout_balance_available(payment.booking):
        return

    ensure_payment_settlement_records(payment)
    for settlement in PaymentSettlement.objects.filter(payment=payment).order_by("purpose"):
        if settlement.status in {PaymentSettlement.Status.PAID, PaymentSettlement.Status.PROCESSING} and settlement.transfer_reference:
            continue
        if settlement.transfer_recipient_id:
            if settlement.status == PaymentSettlement.Status.RECIPIENT_CREATED:
                settlement.status = PaymentSettlement.Status.READY
                settlement.save(update_fields=["status", "updated_at"])
        else:
            try:
                recipient_response = create_transfer_recipient(
                    full_name=settlement.account_name or settlement.get_purpose_display(),
                    phone_number=payment.booking.listing.landlord.mobile or payment.booking.tenant.mobile,
                    bank_name=settlement.bank_name,
                    bank_code=settlement.bank_code,
                    account_number=settlement.account_number,
                    account_name=settlement.account_name,
                    idempotency_key=f"{payment.transaction_id}-{settlement.purpose}-recipient",
                )
            except FlutterwaveError as exc:
                settlement.status = PaymentSettlement.Status.FAILED
                settlement.last_error = str(exc)
                settlement.save(update_fields=["status", "last_error", "updated_at"])
                continue

            settlement.transfer_recipient_id = extract_resource_id(recipient_response)
            settlement.provider_payload = recipient_response
            settlement.status = (
                PaymentSettlement.Status.READY
                if settlement.transfer_recipient_id
                else PaymentSettlement.Status.PENDING
            )
            settlement.last_error = "" if settlement.transfer_recipient_id else "Flutterwave did not return a transfer recipient id."
            settlement.save(
                update_fields=[
                    "transfer_recipient_id",
                    "provider_payload",
                    "status",
                    "last_error",
                    "updated_at",
                ]
            )
            if not settlement.transfer_recipient_id:
                continue

        transfer_reference = settlement.transfer_reference or build_settlement_transfer_reference(payment, settlement)
        try:
            transfer_response = create_bank_transfer(
                amount=settlement.amount,
                currency=settlement.currency,
                reference=transfer_reference,
                narration=f"RentDirect {settlement.get_purpose_display()}",
                recipient_id=settlement.transfer_recipient_id,
                bank_name=settlement.bank_name,
                bank_code=settlement.bank_code,
                account_number=settlement.account_number,
                account_name=settlement.account_name,
                idempotency_key=transfer_reference,
            )
        except FlutterwaveError as exc:
            settlement.status = PaymentSettlement.Status.READY
            settlement.transfer_reference = transfer_reference
            settlement.last_error = str(exc)
            settlement.save(update_fields=["status", "transfer_reference", "last_error", "updated_at"])
            continue

        settlement.transfer_reference = transfer_reference
        settlement.transfer_payload = transfer_response
        settlement.status = map_transfer_status_to_settlement_status(transfer_response)
        settlement.last_error = ""
        settlement_update_fields = [
            "transfer_reference",
            "transfer_payload",
            "status",
            "last_error",
            "updated_at",
        ]
        if settlement.status == PaymentSettlement.Status.PAID:
            settlement.transferred_at = timezone.now()
            settlement_update_fields.append("transferred_at")
        settlement.save(update_fields=settlement_update_fields)

        # Send settlement notification emails after successful recipient creation
        try:
            booking = payment.booking
            listing = booking.listing
            landlord = listing.landlord
            tenant = booking.tenant

            if settlement.purpose == PaymentSettlement.Purpose.LANDLORD_RENT:
                # Email #2: Notify landlord of payout, CC tenant and RentDirect
                send_landlord_payout_notification(
                    landlord_email=landlord.email,
                    landlord_name=landlord.name,
                    tenant_name=tenant.name,
                    tenant_email=tenant.email,
                    listing_title=listing.title,
                    amount=settlement.amount,
                    bank_name=settlement.bank_name,
                    account_name=settlement.account_name,
                    account_number=settlement.account_number,
                    settlement_id=str(settlement.id),
                )
            elif settlement.purpose in (PaymentSettlement.Purpose.OPERATIONS, PaymentSettlement.Purpose.CAUTION_FEE):
                # Email #3: Notify only RentDirect for internal transfers
                send_rentdirect_internal_transfer_notification(
                    purpose=settlement.purpose,
                    amount=settlement.amount,
                    bank_name=settlement.bank_name,
                    account_name=settlement.account_name,
                    account_number=settlement.account_number,
                    listing_title=listing.title,
                    tenant_name=tenant.name,
                    tenant_email=tenant.email,
                    landlord_name=landlord.name,
                    landlord_email=landlord.email,
                    settlement_id=str(settlement.id),
                )
        except Exception:
            logger.exception(
                "Failed to send settlement notification email for settlement %s (purpose=%s)",
                settlement.id,
                settlement.purpose,
            )


def trigger_booking_payouts_if_ready(booking: Booking) -> None:
    if not booking_payout_release_conditions_met(booking):
        return

    completion_payment, _full_payment_completed_at = get_booking_full_payment_completion(booking)
    if not completion_payment:
        return
    trigger_payment_settlements(
        Payment.objects
        .select_related("booking", "booking__tenant", "booking__listing", "booking__listing__landlord")
        .get(pk=completion_payment.pk)
    )


def update_booking_after_completed_payment(payment: Payment) -> Payment:
    with transaction.atomic():
        payment = (
            Payment.objects
            .select_for_update()
            .select_related("booking", "booking__tenant", "booking__listing", "booking__listing__landlord")
            .get(pk=payment.pk)
        )
        if payment.status == "completed":
            return payment

        booking = Booking.objects.select_for_update().select_related("listing").get(pk=payment.booking_id)
        total_amount = resolve_booking_total(booking.listing.price_per_year, booking.total_amount)
        remaining_balance = calculate_remaining_balance(total_amount, booking.paid_amount)
        if Decimal(payment.amount) > remaining_balance:
            payment.status = "failed"
            payment.provider_payload = update_payment_provider_payload(
                payment.provider_payload,
                None,
                verification_error="amount_exceeds_remaining_balance",
            )
            payment.save(update_fields=["status", "provider_payload", "updated_at"])
            return payment

        booking.total_amount = total_amount
        booking.paid_amount = (booking.paid_amount or Decimal("0")) + payment.amount
        booking.status = (
            Booking.Status.CONFIRMED
            if calculate_remaining_balance(total_amount, booking.paid_amount) <= 0
            else Booking.Status.PENDING
        )
        booking.save(update_fields=["total_amount", "paid_amount", "status", "updated_at"])

        payment.status = "completed"
        payment.payment_date = timezone.now()
        payment.save(update_fields=["status", "payment_date", "updated_at"])

        # Email #1: Notify landlord of successful tenant payment, CC tenant and RentDirect
        try:
            send_payment_confirmation_to_landlord(
                landlord_email=payment.booking.listing.landlord.email,
                landlord_name=payment.booking.listing.landlord.name,
                tenant_name=payment.booking.tenant.name,
                tenant_email=payment.booking.tenant.email,
                listing_title=payment.booking.listing.title,
                amount=payment.amount,
                transaction_id=payment.transaction_id,
                payment_date=payment.payment_date.strftime("%Y-%m-%d %H:%M:%S"),
                booking_id=str(payment.booking_id),
            )
        except Exception:
            logger.exception("Failed to send payment confirmation email for payment %s", payment.id)

        trigger_payment_settlements(payment)
        return payment


def complete_featured_payment(payment: FeaturedPayment, *, webhook_data=None) -> FeaturedPayment:
    payment.status = FeaturedPayment.Status.COMPLETED
    payment.payment_date = timezone.now()
    if webhook_data is not None:
        payment.webhook_data = webhook_data
    payment.save(update_fields=["status", "payment_date", "webhook_data", "updated_at"])
    return payment


def complete_subscription_payment(payment: SubscriptionPayment, *, webhook_data=None) -> SubscriptionPayment:
    duration_days = 30 if payment.billing_cycle == SubscriptionPayment.BillingCycle.MONTHLY else 365
    payment.status = SubscriptionPayment.Status.COMPLETED
    payment.payment_date = timezone.now()
    payment.expires_at = payment.payment_date + timedelta(days=duration_days)
    if webhook_data is not None:
        payment.webhook_data = webhook_data
    payment.save(update_fields=["status", "payment_date", "expires_at", "webhook_data", "updated_at"])
    return payment


def sync_booking_payment(payment: Payment, *, transaction_id: str | None = None, provider_status: str | None = None, payload=None, source: str) -> Payment:
    redirect_state = map_redirect_status(provider_status)
    if payment.status == "completed":
        return payment
    if payload is None and redirect_state in FAILED_PAYMENT_STATUSES and not transaction_id:
        payment.status = redirect_state
        payment.provider_payload = update_payment_provider_payload(
            payment.provider_payload,
            None,
            redirect={"status": provider_status, "source": source},
        )
        payment.save(update_fields=["status", "provider_payload", "updated_at"])
        return payment

    charge_payload = payload
    if charge_payload is None:
        charge_payload = query_transaction(reference=payment.transaction_id, transaction_id=transaction_id)
    if charge_payload is None:
        return payment

    charge_data = charge_payload.get("data") or {}
    actual_reference = extract_reference(charge_payload)
    actual_amount = normalize_decimal_amount(charge_data.get("amount"))
    actual_currency = str(charge_data.get("currency") or "").upper()
    actual_email = extract_customer_email(charge_payload).lower()
    expected_email = payment.booking.tenant.email.strip().lower()
    verification_errors: list[str] = []
    verification_warnings: list[str] = []

    if actual_reference != payment.transaction_id:
        verification_errors.append("reference_mismatch")
    if actual_amount != normalize_decimal_amount(payment.amount):
        verification_errors.append("amount_mismatch")
    if actual_currency and actual_currency != payment.currency.upper():
        verification_errors.append("currency_mismatch")
    if actual_email and actual_email != expected_email:
        verification_warnings.append("customer_email_mismatch")

    bank_name, card_last4 = extract_payment_channel_details(charge_payload)
    provider_payload = update_payment_provider_payload(
        payment.provider_payload,
        charge_payload,
        verification={
            "source": source,
            "provider_status": extract_payment_state(charge_payload),
            "provider_transaction_id": extract_provider_transaction_id(charge_payload),
            "errors": verification_errors,
            "warnings": verification_warnings,
            "verified_at": timezone.now().isoformat(),
        },
    )
    payment.provider_payload = provider_payload
    payment.provider = "flutterwave"
    payment.webhook_data = charge_payload if source == "webhook" else payment.webhook_data
    if bank_name:
        payment.bank_name = bank_name
    if card_last4:
        payment.card_last4 = card_last4

    next_state = extract_payment_state(charge_payload)
    if verification_errors:
        next_state = "failed"

    update_fields = ["provider_payload", "provider", "webhook_data", "bank_name", "card_last4", "updated_at"]
    if next_state == "completed":
        payment.save(update_fields=update_fields)
        return update_booking_after_completed_payment(payment)

    payment.status = next_state
    update_fields.append("status")
    payment.save(update_fields=update_fields)
    return payment


def sync_featured_payment(payment: FeaturedPayment, *, transaction_id: str | None = None, provider_status: str | None = None, payload=None, source: str) -> FeaturedPayment:
    redirect_state = map_redirect_status(provider_status)
    if payment.status == FeaturedPayment.Status.COMPLETED:
        return payment
    if payload is None and redirect_state in {FeaturedPayment.Status.CANCELLED, FeaturedPayment.Status.FAILED} and not transaction_id:
        payment.status = redirect_state
        payment.provider_payload = update_payment_provider_payload(
            payment.provider_payload,
            None,
            redirect={"status": provider_status, "source": source},
        )
        payment.save(update_fields=["status", "provider_payload", "updated_at"])
        return payment

    charge_payload = payload
    if charge_payload is None:
        charge_payload = query_transaction(reference=payment.transaction_id or "", transaction_id=transaction_id)
    if charge_payload is None:
        return payment

    charge_data = charge_payload.get("data") or {}
    actual_reference = extract_reference(charge_payload)
    actual_amount = normalize_decimal_amount(charge_data.get("amount"))
    actual_currency = str(charge_data.get("currency") or "").upper()
    actual_email = extract_customer_email(charge_payload).lower()
    expected_email = payment.landlord.email.strip().lower()
    verification_errors: list[str] = []
    verification_warnings: list[str] = []

    if actual_reference != (payment.transaction_id or ""):
        verification_errors.append("reference_mismatch")
    if actual_amount != normalize_decimal_amount(payment.amount):
        verification_errors.append("amount_mismatch")
    if actual_currency and actual_currency != payment.currency.upper():
        verification_errors.append("currency_mismatch")
    if actual_email and actual_email != expected_email:
        verification_warnings.append("customer_email_mismatch")

    payment.provider_payload = update_payment_provider_payload(
        payment.provider_payload,
        charge_payload,
        verification={
            "source": source,
            "provider_status": extract_payment_state(charge_payload),
            "provider_transaction_id": extract_provider_transaction_id(charge_payload),
            "errors": verification_errors,
            "warnings": verification_warnings,
            "verified_at": timezone.now().isoformat(),
        },
    )
    payment.provider = "flutterwave"
    if source == "webhook":
        payment.webhook_data = charge_payload

    next_state = extract_payment_state(charge_payload)
    if verification_errors:
        next_state = FeaturedPayment.Status.FAILED

    if next_state == FeaturedPayment.Status.COMPLETED:
        payment.save(update_fields=["provider_payload", "provider", "webhook_data", "updated_at"])
        return complete_featured_payment(payment, webhook_data=charge_payload if source == "webhook" else payment.webhook_data)

    payment.status = (
        FeaturedPayment.Status.CANCELLED
        if next_state == FeaturedPayment.Status.CANCELLED
        else FeaturedPayment.Status.FAILED
        if next_state == FeaturedPayment.Status.FAILED
        else FeaturedPayment.Status.PENDING
    )
    payment.save(update_fields=["status", "provider_payload", "provider", "webhook_data", "updated_at"])
    return payment


def sync_subscription_payment(payment: SubscriptionPayment, *, transaction_id: str | None = None, provider_status: str | None = None, payload=None, source: str) -> SubscriptionPayment:
    redirect_state = map_redirect_status(provider_status)
    if payment.status == SubscriptionPayment.Status.COMPLETED:
        return payment
    if payload is None and redirect_state in {SubscriptionPayment.Status.CANCELLED, SubscriptionPayment.Status.FAILED} and not transaction_id:
        payment.status = redirect_state
        payment.provider_payload = update_payment_provider_payload(
            payment.provider_payload,
            None,
            redirect={"status": provider_status, "source": source},
        )
        payment.save(update_fields=["status", "provider_payload", "updated_at"])
        return payment

    charge_payload = payload
    if charge_payload is None:
        charge_payload = query_transaction(reference=payment.transaction_id or "", transaction_id=transaction_id)
    if charge_payload is None:
        return payment

    charge_data = charge_payload.get("data") or {}
    actual_reference = extract_reference(charge_payload)
    actual_amount = normalize_decimal_amount(charge_data.get("amount"))
    actual_currency = str(charge_data.get("currency") or "").upper()
    actual_email = extract_customer_email(charge_payload).lower()
    expected_email = payment.user.email.strip().lower()
    verification_errors: list[str] = []
    verification_warnings: list[str] = []

    if actual_reference != (payment.transaction_id or ""):
        verification_errors.append("reference_mismatch")
    if actual_amount != normalize_decimal_amount(payment.amount):
        verification_errors.append("amount_mismatch")
    if actual_currency and actual_currency != payment.currency.upper():
        verification_errors.append("currency_mismatch")
    if actual_email and actual_email != expected_email:
        verification_warnings.append("customer_email_mismatch")

    payment.provider_payload = update_payment_provider_payload(
        payment.provider_payload,
        charge_payload,
        verification={
            "source": source,
            "provider_status": extract_payment_state(charge_payload),
            "provider_transaction_id": extract_provider_transaction_id(charge_payload),
            "errors": verification_errors,
            "warnings": verification_warnings,
            "verified_at": timezone.now().isoformat(),
        },
    )
    payment.provider = "flutterwave"
    payment.provider_charge_id = extract_provider_transaction_id(charge_payload) or payment.provider_charge_id
    if source == "webhook":
        payment.webhook_data = charge_payload

    next_state = extract_payment_state(charge_payload)
    if verification_errors:
        next_state = SubscriptionPayment.Status.FAILED

    if next_state == SubscriptionPayment.Status.COMPLETED:
        payment.save(update_fields=["provider_payload", "provider", "provider_charge_id", "webhook_data", "updated_at"])
        return complete_subscription_payment(
            payment,
            webhook_data=charge_payload if source == "webhook" else payment.webhook_data,
        )

    payment.status = (
        SubscriptionPayment.Status.CANCELLED
        if next_state == SubscriptionPayment.Status.CANCELLED
        else SubscriptionPayment.Status.FAILED
        if next_state == SubscriptionPayment.Status.FAILED
        else SubscriptionPayment.Status.PENDING
    )
    payment.save(update_fields=["status", "provider_payload", "provider", "provider_charge_id", "webhook_data", "updated_at"])
    return payment


def ensure_supported_subscription_role(user: AppUser) -> None:
    if user.role not in {AppUser.Role.TENANT, AppUser.Role.LANDLORD}:
        raise PermissionDenied("Subscriptions are available only to tenants and landlords.")


@method_decorator(production_ratelimit(key="ip", rate="10/m", method="POST", block=True), name="register")
@method_decorator(production_ratelimit(key="ip", rate="10/m", method="POST", block=True), name="verify_registration")
@method_decorator(production_ratelimit(key="ip", rate="10/m", method="POST", block=True), name="login")
@method_decorator(production_ratelimit(key="ip", rate="30/m", method="POST", block=True), name="refresh")
class AuthViewSet(viewsets.ViewSet):
    permission_classes = [AllowAny]

    @action(detail=False, methods=["post"], url_path="register")
    def register(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        existing = User.objects.filter(email=data["email"]).first()
        if existing and existing.email_verified:
            raise ValidationError({"email": "Email already registered"})

        otp = generate_otp()
        expires_at = timezone.now() + timedelta(minutes=OTP_TTL_MINUTES)
        user = existing or User(email=data["email"], role=data["role"])
        user.name = data["name"]
        user.role = data["role"]
        user.set_password(data["password"])
        user.email_verified = False
        user.registration_otp_hash = hash_otp(user.email, otp)
        user.registration_otp_expires_at = expires_at
        user.registration_otp_attempts = 0
        user.save()
        send_registration_email(user, otp)
        return Response(
            {
                "email": user.email,
                "role": user.role,
                "expires_in_seconds": OTP_TTL_MINUTES * 60,
                "message": "Verification code sent to email.",
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=["post"], url_path="register/verify")
    def verify_registration(self, request):
        serializer = VerifyRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].strip().lower()
        code = serializer.validated_data["otp_code"]
        user = User.objects.filter(email=email).first()
        if not user:
            return Response({"detail": "Registration not found"}, status=404)
        if user.email_verified:
            return Response({"detail": "Email is already verified"}, status=400)
        if user.registration_otp_attempts >= OTP_MAX_ATTEMPTS:
            return Response({"detail": "Too many invalid verification attempts"}, status=429)
        if not user.registration_otp_expires_at or user.registration_otp_expires_at < timezone.now():
            return Response({"detail": "Verification code has expired"}, status=400)
        if not otp_matches(user.registration_otp_hash, email, code):
            user.registration_otp_attempts += 1
            user.save(update_fields=["registration_otp_attempts", "updated_at"])
            remaining = max(OTP_MAX_ATTEMPTS - user.registration_otp_attempts, 0)
            return Response({"detail": f"Invalid verification code. {remaining} attempts remaining."}, status=400)
        user.email_verified = True
        user.registration_otp_hash = ""
        user.registration_otp_expires_at = None
        user.registration_otp_attempts = 0
        user.save(update_fields=["email_verified", "registration_otp_hash", "registration_otp_expires_at", "registration_otp_attempts", "updated_at"])
        response = Response(UserSerializer(user).data)
        set_auth_cookies(response, user)
        return response

    @action(detail=False, methods=["post"], url_path="login")
    def login(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        response = Response(UserSerializer(user).data)
        set_auth_cookies(response, user)
        return response

    @action(detail=False, methods=["post"], url_path="logout", permission_classes=[IsAuthenticated])
    def logout(self, request):
        response = Response({"message": "Logged out successfully"})
        clear_auth_cookies(response)
        return response

    @action(detail=False, methods=["post"], url_path="refresh")
    def refresh(self, request):
        raw = request.COOKIES.get(settings.REFRESH_COOKIE_NAME) or request.data.get("refresh_token")
        if not raw:
            return Response({"detail": "Refresh token required"}, status=401)
        try:
            refresh = RefreshToken(raw)
            user = User.objects.get(id=refresh["user_id"])
        except Exception:
            return Response({"detail": "Invalid refresh token"}, status=401)
        response = Response(UserSerializer(user).data)
        set_auth_cookies(response, user)
        return response


class UserViewSet(viewsets.GenericViewSet):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    @action(detail=False, methods=["get", "patch"], url_path="me")
    def me(self, request):
        if request.method == "PATCH":
            serializer = self.get_serializer(request.user, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
        return Response(self.get_serializer(request.user).data)

    @action(detail=False, methods=["post"], url_path="me/photo")
    def upload_photo(self, request):
        upload = request.FILES.get("file")
        if not upload:
            raise ValidationError({"file": "Profile photo is required."})
        if upload.size > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
            raise ValidationError({"file": "File is too large"})
        request.user.profile_photo = upload
        request.user.save(update_fields=["profile_photo", "updated_at"])
        return Response(self.get_serializer(request.user).data)

    @action(detail=False, methods=["get"], url_path="public-stats", permission_classes=[AllowAny])
    def public_stats(self, request):
        return Response(
            {
                "properties": exclude_deposit_secured_listings(Listing.objects.filter(status=Listing.Status.AVAILABLE)).count(),
                "landlords": User.objects.filter(role="landlord").count(),
                "tenants": User.objects.filter(role="tenant").count(),
            }
        )

    @action(detail=False, methods=["get"], url_path="subscription-pricing", permission_classes=[AllowAny])
    def subscription_pricing(self, request):
        return Response(get_subscription_pricing())

    @action(detail=False, methods=["post"], url_path="me/settings/request-otp")
    def request_settings_otp(self, request):
        serializer = SettingsOtpRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        purpose = serializer.validated_data["purpose"]
        current_email = request.user.email.strip().lower()
        target_email = serializer.validated_data.get("target_email", "").strip().lower()

        if purpose == SETTINGS_OTP_PURPOSE_PASSWORD:
            target_email = current_email
        else:
            target_email = target_email or current_email
            if target_email != current_email and User.objects.filter(email=target_email).exclude(pk=request.user.pk).exists():
                raise ValidationError({"target_email": "Email already registered."})

        begin_settings_otp_challenge(request.user, purpose=purpose, target_email=target_email)
        return Response(
            {
                "purpose": purpose,
                "target_email": target_email,
                "expires_in_seconds": OTP_TTL_MINUTES * 60,
                "message": "Verification code sent successfully.",
            }
        )

    @action(detail=False, methods=["post"], url_path="me/settings")
    def update_settings(self, request):
        payload = {
            field: request.data.get(field)
            for field in SETTINGS_PROFILE_MUTABLE_FIELDS
            if field in request.data
        }
        if not payload:
            raise ValidationError({"detail": "No settings changes were provided."})

        serializer = self.get_serializer(request.user, data=payload, partial=True)
        serializer.is_valid(raise_exception=True)

        target_email = serializer.validated_data.get("email", request.user.email).strip().lower()
        ensure_valid_settings_otp(
            request.user,
            purpose=SETTINGS_OTP_PURPOSE_PROFILE,
            target_email=target_email,
            code=str(request.data.get("otp_code", "")),
        )

        updated_user = serializer.save()
        if not updated_user.email_verified:
            updated_user.email_verified = True
            updated_user.save(update_fields=["email_verified", "updated_at"])
        clear_settings_otp(updated_user)
        return Response(self.get_serializer(updated_user).data)

    @action(detail=False, methods=["get"], url_path="me/favourites")
    def my_favourites(self, request):
        favourites = Favourite.objects.filter(tenant=request.user).select_related("listing").prefetch_related("listing__images").order_by("-created_at")
        serializer = ListingSerializer([favourite.listing for favourite in favourites], many=True, context={"request": request})
        return Response(serializer.data)

    @action(detail=False, methods=["post"], url_path="me/password")
    def change_password(self, request):
        serializer = SettingsPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_password = serializer.validated_data["new_password"]

        try:
            validate_password(new_password, request.user)
        except DjangoValidationError as exc:
            raise ValidationError({"new_password": list(exc.messages)}) from exc

        ensure_valid_settings_otp(
            request.user,
            purpose=SETTINGS_OTP_PURPOSE_PASSWORD,
            target_email=request.user.email.strip().lower(),
            code=serializer.validated_data["otp_code"],
        )

        request.user.set_password(new_password)
        clear_settings_otp(request.user, save=False)
        request.user.save(
            update_fields=[
                "password",
                "settings_otp_hash",
                "settings_otp_expires_at",
                "settings_otp_attempts",
                "settings_otp_purpose",
                "settings_otp_target_email",
                "updated_at",
            ]
        )
        return Response({"ok": True, "message": "Password updated successfully."})

    @action(detail=False, methods=["post", "delete"], url_path="me/favourites/(?P<listing_id>[^/.]+)")
    def manage_favourite(self, request, listing_id=None):
        listing = get_object_or_404(Listing, id=listing_id)
        if request.method == "POST":
            favourite, created = Favourite.objects.get_or_create(tenant=request.user, listing=listing)
            serializer = FavouriteSerializer(favourite)
            return Response(serializer.data, status=201 if created else 200)
        elif request.method == "DELETE":
            favourite = get_object_or_404(Favourite, tenant=request.user, listing=listing)
            favourite.delete()
            return Response(status=204)

    @action(detail=False, methods=["get", "post", "put"], url_path="me/tenant-profile")
    def tenant_profile(self, request):
        profile = TenantProfile.objects.filter(user=request.user).first()
        if request.method == "GET":
            if not profile:
                return Response({"detail": "No tenant profile found."}, status=404)
            serializer = TenantProfileSerializer(profile)
            return Response(serializer.data)

        data = request.data.copy()
        nin_number = str(data.pop("nin_number", request.user.nin_number) or "").strip()
        bvn_number = str(data.pop("bvn_number", request.user.bvn_number) or "").strip()
        for verification_only_field in ("country_of_birth", "email", "mobile"):
            data.pop(verification_only_field, None)
        data["user"] = request.user.id
        if request.method == "POST":
            if profile:
                return Response({"detail": "Tenant profile already exists. Use PUT to update."}, status=400)
            serializer = TenantProfileSerializer(data=data)
            serializer.is_valid(raise_exception=True)
            if not tenant_verified_identity_matches(request.user, serializer.validated_data, nin_number, bvn_number):
                verify_tenant_identity_or_raise(request.user, serializer.validated_data, nin_number, bvn_number)
            verification_profile = normalize_tenant_verification_profile(
                {
                    **request.data,
                    **serializer.validated_data,
                    "email": request.data.get("email") or request.user.email,
                    "mobile": request.data.get("mobile") or request.user.mobile,
                    "nin_number": nin_number,
                    "bvn_number": bvn_number,
                },
                request.user,
            )
            with transaction.atomic():
                request.user.nin_number = nin_number
                request.user.bvn_number = bvn_number
                request.user.tenant_verification_profile = verification_profile
                request.user.save(update_fields=["nin_number", "bvn_number", "tenant_verification_profile", "updated_at"])
                new_profile = serializer.save(user=request.user)
            vr, created = VerificationRequest.objects.get_or_create(
                user=request.user,
                defaults={
                    "request_type": VerificationRequest.RequestType.IDENTIFICATION,
                    "status": VerificationRequest.Status.PENDING,
                    "identity_verification_status": VerificationRequest.VerificationProgressStatus.VERIFIED,
                    "verification_method": VerificationRequest.Method.AUTOMATED,
                },
            )
            vr.request_type = VerificationRequest.RequestType.IDENTIFICATION
            vr.identity_verification_status = VerificationRequest.VerificationProgressStatus.VERIFIED
            vr.verification_method = VerificationRequest.Method.AUTOMATED
            if not created and vr.status != VerificationRequest.Status.APPROVED:
                vr.status = VerificationRequest.Status.PENDING
                vr.reviewed_at = None
            vr.save(update_fields=["request_type", "status", "identity_verification_status", "verification_method", "reviewed_at"])
            if new_profile.supporting_documents.exists():
                vr.documents.set(new_profile.supporting_documents.all())
            return Response(serializer.data, status=201)

        # PUT
        if not profile:
            return Response({"detail": "No tenant profile found."}, status=404)
        serializer = TenantProfileSerializer(profile, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        merged_profile_data = {
            "first_name": profile.first_name,
            "middle_name": profile.middle_name,
            "last_name": profile.last_name,
            "date_of_birth": profile.date_of_birth,
            "gender": profile.gender,
            "nationality": profile.nationality,
            "state_of_origin": profile.state_of_origin,
            "lga": profile.lga,
            **serializer.validated_data,
        }
        if not tenant_verified_identity_matches(request.user, merged_profile_data, nin_number, bvn_number):
            verify_tenant_identity_or_raise(request.user, merged_profile_data, nin_number, bvn_number)
        verification_profile = normalize_tenant_verification_profile(
            {
                **request.data,
                **merged_profile_data,
                "email": request.data.get("email") or request.user.email,
                "mobile": request.data.get("mobile") or request.user.mobile,
                "nin_number": nin_number,
                "bvn_number": bvn_number,
            },
            request.user,
        )
        with transaction.atomic():
            request.user.nin_number = nin_number
            request.user.bvn_number = bvn_number
            request.user.tenant_verification_profile = verification_profile
            request.user.save(update_fields=["nin_number", "bvn_number", "tenant_verification_profile", "updated_at"])
            serializer.save()
        return Response(serializer.data)

    @action(detail=False, methods=["get"], url_path="tenants/(?P<tenant_id>[^/.]+)/profile")
    def tenant_profile_detail(self, request, tenant_id=None):
        tenant = get_object_or_404(
            User.objects.filter(role=AppUser.Role.TENANT),
            id=tenant_id,
        )

        has_booking_access = Booking.objects.filter(
            tenant=tenant,
            listing__landlord=request.user,
        ).exists()
        can_view = (
            request.user.role == AppUser.Role.ADMIN
            or request.user.id == tenant.id
            or (request.user.role == AppUser.Role.LANDLORD and has_booking_access)
        )
        if not can_view:
            raise PermissionDenied("You do not have access to this tenant profile.")

        profile = TenantProfile.objects.filter(user=tenant).prefetch_related("supporting_documents").first()
        profile_payload = None
        if profile:
            profile_payload = TenantProfileSerializer(profile).data
            profile_payload.pop("supporting_document_urls", None)
            financial_info = dict(profile_payload.get("financial_info") or {})
            for key in ("bank_name", "account_name", "account_number"):
                financial_info.pop(key, None)
            profile_payload["financial_info"] = financial_info

        return Response(
            {
                "id": tenant.id,
                "name": tenant.name,
                "email": tenant.email,
                "mobile": tenant.mobile,
                "profile_photo_url": tenant.profile_photo_url,
                "state_of_origin": tenant.state_of_origin,
                "residence": tenant.residence,
                "is_verified": tenant.is_verified,
                "tenant_profile": profile_payload,
            }
        )

    @action(detail=False, methods=["get"], url_path="landlords/(?P<landlord_id>[^/.]+)/public-profile", permission_classes=[AllowAny])
    def landlord_public_profile(self, request, landlord_id=None):
        landlord = get_object_or_404(
            User.objects.filter(role=AppUser.Role.LANDLORD),
            id=landlord_id,
        )
        return Response(build_landlord_public_profile_payload(landlord))


class ListingViewSet(viewsets.ModelViewSet):
    serializer_class = ListingSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_permissions(self):
        if self.action in {"create", "update", "partial_update", "destroy"}:
            return [IsLandlordOrAdmin()]
        return [AllowAny()]

    def get_queryset(self):
        qs = Listing.objects.select_related("landlord").prefetch_related("images", "property_documents")
        if (
            self.action == "retrieve"
            and getattr(self.request.user, "is_authenticated", False)
            and self.request.user.role == AppUser.Role.LANDLORD
        ):
            qs = qs.filter(landlord=self.request.user)
        landlord_id = self.request.query_params.get("landlord_id")
        if landlord_id:
            qs = qs.filter(landlord_id=landlord_id)
        elif self.action in {"list", "search", "cities", "featured_listings"}:
            qs = qs.filter(status=Listing.Status.AVAILABLE)
            qs = exclude_deposit_secured_listings(qs)
        featured = self.request.query_params.get("featured")
        if featured is not None:
            qs = qs.filter(featured=str(featured).lower() == "true")
        q = self.request.query_params.get("q")
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q) | Q(city__icontains=q) | Q(address__icontains=q))
        return qs.order_by("-featured", "-created_at")

    def perform_create(self, serializer):
        if self.request.user.role == "landlord" and not self.request.user.is_verified:
            raise PermissionDenied("Your account identity must be verified before listing properties.")
        if self.request.user.role == AppUser.Role.LANDLORD and user_has_bronze_access(self.request.user):
            active_listing_count = Listing.objects.filter(landlord=self.request.user).exclude(status=Listing.Status.ARCHIVED).count()
            if active_listing_count >= 1:
                raise PermissionDenied("Bronze free plan allows one active property listing.")
        serializer.save()

    def perform_update(self, serializer):
        listing = self.get_object()
        if self.request.user.role != "admin" and listing.landlord_id != self.request.user.id:
            raise PermissionDenied("Forbidden")
        serializer.save()

    def perform_destroy(self, instance):
        if self.request.user.role != "admin" and instance.landlord_id != self.request.user.id:
            raise PermissionDenied("Forbidden")
        instance.status = Listing.Status.ARCHIVED
        instance.save(update_fields=["status", "updated_at"])

    @action(detail=False, methods=["get"], url_path="cities", permission_classes=[AllowAny])
    def cities(self, request):
        if (
            getattr(request.user, "is_authenticated", False)
            and request.user.role == AppUser.Role.TENANT
            and user_has_bronze_access(request.user)
        ):
            return Response([])
        qs = self.get_queryset().exclude(city="")
        state = (request.query_params.get("state") or "").strip()
        if state:
            qs = qs.filter(state__iexact=state)
        cities = qs.values_list("city", flat=True).distinct().order_by("city")
        return Response(list(cities))

    @action(detail=False, methods=["get"], url_path="search", permission_classes=[AllowAny])
    def search(self, request):
        qs = self.get_queryset()
        query = request.query_params.get("query") or request.query_params.get("q")
        city = request.query_params.get("city")
        state = request.query_params.get("state")
        min_price = request.query_params.get("min_price")
        max_price = request.query_params.get("max_price")
        bedrooms = request.query_params.get("bedrooms")
        bathrooms = request.query_params.get("bathrooms")
        toilets = request.query_params.get("toilets")
        property_type = request.query_params.get("property_type")
        for key in ["pet_friendly", "furnished", "utilities_included"]:
            value = request.query_params.get(key)
            if value is not None:
                qs = qs.filter(**{key: str(value).lower() == "true"})
        if query:
            qs = qs.filter(Q(title__icontains=query) | Q(description__icontains=query) | Q(address__icontains=query))
        if city:
            qs = qs.filter(Q(city__icontains=city) | Q(address__icontains=city))
        if state:
            qs = qs.filter(
                Q(state__icontains=state)
                | Q(address__icontains=state)
                | Q(landlord__residence__state__icontains=state)
            )
        if min_price:
            qs = qs.filter(price_per_year__gte=min_price)
        if max_price:
            qs = qs.filter(price_per_year__lte=max_price)
        if bedrooms:
            qs = qs.filter(bedrooms=bedrooms)
        if bathrooms:
            qs = qs.filter(bathrooms=bathrooms)
        if toilets:
            qs = qs.filter(toilets=toilets)
        if property_type:
            qs = qs.filter(property_type__iexact=property_type)
        page = self.paginate_queryset(qs)
        serializer = self.get_serializer(page or qs, many=True)
        return self.get_paginated_response(serializer.data) if page is not None else Response(serializer.data)

    @action(detail=False, methods=["get"], url_path="nearby", permission_classes=[AllowAny])
    def nearby(self, request):
        return self.search(request)


class DocumentViewSet(viewsets.ModelViewSet):
    serializer_class = DocumentSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Document.objects.filter(owner=self.request.user).order_by("-created_at")

    def perform_create(self, serializer):
        upload = self.request.FILES.get("file")
        if upload and upload.size > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
            raise ValidationError({"file": "File is too large"})
        serializer.save(owner=self.request.user, content_type=getattr(upload, "content_type", ""))


class VerificationRequestBaseViewSet(viewsets.GenericViewSet):
    serializer_class = VerificationRequestSerializer
    permission_classes = [IsAuthenticated]
    user_role = None

    def get_queryset(self):
        queryset = VerificationRequest.objects.select_related("user").order_by("-submitted_at")
        if self.user_role:
            queryset = queryset.filter(user__role=self.user_role)
        if getattr(self.request.user, "role", None) == AppUser.Role.ADMIN:
            return queryset
        return queryset.filter(user=self.request.user)

    def ensure_user_role(self, request):
        if self.user_role and request.user.role != self.user_role:
            raise PermissionDenied("This verification request endpoint is not available for your account type.")

    def get_latest_for_user(self, user):
        return self.get_queryset().filter(user=user).order_by("-submitted_at").first()

    def build_empty_status_response(self):
        return Response({
            "status": VerificationRequest.VerificationProgressStatus.UNVERIFIED,
            "submitted_at": None,
            "verification_method": None,
            "confidence_score": None,
            "automated_decision": None,
            "estimated_completion": None,
            "identification": {
                "status": VerificationRequest.VerificationProgressStatus.UNVERIFIED,
                "submitted_at": None,
            },
            "property_documents": {
                "status": VerificationRequest.VerificationProgressStatus.UNVERIFIED,
                "submitted_at": None,
            },
            "physical_property": {
                "status": VerificationRequest.VerificationProgressStatus.UNVERIFIED,
                "submitted_at": None,
            },
        })

    def build_status_response(self, latest):
        if not latest:
            return self.build_empty_status_response()

        identification_status = latest.identity_verification_status or VerificationRequest.VerificationProgressStatus.UNVERIFIED
        property_document_status = (
            latest.property_document_verification_status or VerificationRequest.VerificationProgressStatus.UNVERIFIED
        )
        physical_property_status = latest.physical_property_status or VerificationRequest.VerificationProgressStatus.UNVERIFIED
        overall_progress = VerificationRequest.VerificationProgressStatus.UNVERIFIED
        if identification_status == VerificationRequest.VerificationProgressStatus.VERIFIED:
            overall_progress = VerificationRequest.VerificationProgressStatus.VERIFIED
        elif (
            identification_status == VerificationRequest.VerificationProgressStatus.PENDING
            or property_document_status == VerificationRequest.VerificationProgressStatus.PENDING
            or physical_property_status == VerificationRequest.VerificationProgressStatus.PENDING
        ):
            overall_progress = VerificationRequest.VerificationProgressStatus.PENDING

        return Response({
            "status": verification_progress_to_legacy_status(overall_progress),
            "submitted_at": latest.submitted_at,
            "verification_method": latest.verification_method,
            "confidence_score": latest.confidence_score,
            "automated_decision": latest.automated_decision,
            "estimated_completion": "Within 3-5 business days" if overall_progress == "pending" else None,
            "identification": {
                "status": identification_status,
                "submitted_at": latest.submitted_at if identification_status != VerificationRequest.VerificationProgressStatus.UNVERIFIED else None,
            },
            "property_documents": {
                "status": property_document_status,
                "submitted_at": latest.submitted_at if property_document_status != VerificationRequest.VerificationProgressStatus.UNVERIFIED else None,
            },
            "physical_property": {
                "status": physical_property_status,
                "submitted_at": latest.submitted_at if physical_property_status != VerificationRequest.VerificationProgressStatus.UNVERIFIED else None,
            },
        })

    def get_documents(self, user, doc_ids):
        docs = Document.objects.filter(owner=user, id__in=doc_ids)
        if len(doc_ids) != docs.count():
            raise ValidationError({"document_ids": "Invalid document ids"})
        return docs

    def get_or_create_user_verification(self, user):
        verification = self.get_queryset().filter(user=user).order_by("-submitted_at").first()
        if not verification:
            verification = VerificationRequest.objects.create(user=user)
        return verification

    def serialize_submission_response(self, verification):
        return {
            "id": verification.id,
            "request_type": verification.request_type,
            "status": verification.status,
            "identity_verification_status": verification.identity_verification_status,
            "property_document_verification_status": verification.property_document_verification_status,
            "physical_property_status": verification.physical_property_status,
            "message": "Verification submitted for manual review.",
        }

    @action(detail=False, methods=["get"], url_path="status")
    def status(self, request):
        self.ensure_user_role(request)
        return self.build_status_response(self.get_latest_for_user(request.user))

    @action(detail=False, methods=["post"], url_path="submit")
    def submit(self, request):
        self.ensure_user_role(request)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        doc_ids = serializer.validated_data.get("document_ids", [])
        request_type = serializer.validated_data.get("request_type", VerificationRequest.RequestType.GENERAL)
        physical_property_status = serializer.validated_data.get(
            "physical_property_status",
            VerificationRequest.VerificationProgressStatus.UNVERIFIED,
        )
        self.validate_submission(request, request_type, physical_property_status)
        docs = self.get_documents(request.user, doc_ids)
        verification = self.get_or_create_user_verification(request.user)

        verification.request_type = request_type
        verification.status = VerificationRequest.Status.PENDING
        verification.reviewed_at = None
        verification.submitted_at = timezone.now()
        update_fields = ["request_type", "status", "reviewed_at", "submitted_at", "updated_at"] if hasattr(verification, "updated_at") else ["request_type", "status", "reviewed_at", "submitted_at"]

        self.apply_submission(request, verification, request_type, physical_property_status, update_fields)

        verification.save(update_fields=update_fields)
        if docs:
            verification.documents.add(*docs)
        return Response(self.serialize_submission_response(verification), status=201)

    def apply_submission(self, request, verification, request_type, physical_property_status, update_fields):
        raise NotImplementedError

    def validate_submission(self, request, request_type, physical_property_status):
        return None

    @action(detail=False, methods=["get"], url_path="pending", permission_classes=[IsAdminRole])
    def pending(self, request):
        limit = int(request.query_params.get("limit", 20))
        offset = int(request.query_params.get("offset", 0))
        queryset = self.get_queryset().filter(status=VerificationRequest.Status.PENDING)
        items = queryset[offset:offset + limit]
        return Response([
            {
                "id": item.id,
                "user_id": item.user_id,
                "user_email": item.user.email,
                "user_name": item.user.name,
                "user_role": item.user.role,
                "request_type": item.request_type,
                "status": item.status,
                "verification_method": item.verification_method,
                "confidence_score": item.confidence_score,
                "automated_decision": item.automated_decision,
                "submitted_at": item.submitted_at,
                "estimated_completion": "Within 3-5 business days",
            }
            for item in items
        ])

    @action(detail=True, methods=["post"], url_path="approve", permission_classes=[IsAdminRole])
    def approve(self, request, pk=None):
        item = get_object_or_404(self.get_queryset(), id=pk)
        item.status = VerificationRequest.Status.APPROVED
        if item.request_type == VerificationRequest.RequestType.IDENTIFICATION:
            item.identity_verification_status = VerificationRequest.VerificationProgressStatus.VERIFIED
        elif item.request_type == VerificationRequest.RequestType.PROPERTY_DOCUMENTS:
            item.property_document_verification_status = VerificationRequest.VerificationProgressStatus.VERIFIED
        item.reviewed_at = timezone.now()
        update_fields = ["status", "reviewed_at"]
        if item.request_type == VerificationRequest.RequestType.IDENTIFICATION:
            update_fields.append("identity_verification_status")
        elif item.request_type == VerificationRequest.RequestType.PROPERTY_DOCUMENTS:
            update_fields.append("property_document_verification_status")
        item.save(update_fields=update_fields)
        return Response({"ok": True})

    @action(detail=True, methods=["post"], url_path="reject", permission_classes=[IsAdminRole])
    def reject(self, request, pk=None):
        item = get_object_or_404(self.get_queryset(), id=pk)
        item.status = VerificationRequest.Status.REJECTED
        if item.request_type == VerificationRequest.RequestType.IDENTIFICATION:
            item.identity_verification_status = VerificationRequest.VerificationProgressStatus.UNVERIFIED
        elif item.request_type == VerificationRequest.RequestType.PROPERTY_DOCUMENTS:
            item.property_document_verification_status = VerificationRequest.VerificationProgressStatus.UNVERIFIED
        item.notes = request.data.get("reason", request.query_params.get("reason", ""))
        item.reviewed_at = timezone.now()
        update_fields = ["status", "notes", "reviewed_at"]
        if item.request_type == VerificationRequest.RequestType.IDENTIFICATION:
            update_fields.append("identity_verification_status")
        elif item.request_type == VerificationRequest.RequestType.PROPERTY_DOCUMENTS:
            update_fields.append("property_document_verification_status")
        item.save(update_fields=update_fields)
        return Response({"ok": True})

    @action(detail=False, methods=["get"], url_path="metrics", permission_classes=[IsAdminRole])
    def metrics(self, request):
        queryset = self.get_queryset()
        total = queryset.count()
        approved = queryset.filter(status=VerificationRequest.Status.APPROVED).count()
        pending = queryset.filter(status=VerificationRequest.Status.PENDING).count()
        manual_reviews = queryset.filter(verification_method=VerificationRequest.Method.MANUAL).count()
        return Response({
            "total_verifications": total,
            "approved_verifications": approved,
            "pending_verifications": pending,
            "rejected_verifications": queryset.filter(status=VerificationRequest.Status.REJECTED).count(),
            "automated_approvals": queryset.filter(verification_method=VerificationRequest.Method.AUTOMATED).count(),
            "manual_reviews": manual_reviews,
            "average_processing_time_hours": 0,
            "success_rate": approved / total if total else 0,
            "last_updated": timezone.now(),
        })


class LandlordVerificationRequestViewSet(VerificationRequestBaseViewSet):
    user_role = AppUser.Role.LANDLORD

    def validate_submission(self, request, request_type, physical_property_status):
        if request_type == VerificationRequest.RequestType.PROPERTY_DOCUMENTS:
            raise ValidationError({"request_type": "Property document verification is submitted from each listing."})

    def apply_submission(self, request, verification, request_type, physical_property_status, update_fields):
        if request_type == VerificationRequest.RequestType.PROPERTY_DOCUMENTS:
            raise ValidationError({"request_type": "Property document verification is submitted from each listing."})

        if request_type == VerificationRequest.RequestType.IDENTIFICATION:
            if request.user.role == AppUser.Role.LANDLORD and request.user.landlord_verification_profile:
                verify_landlord_identity_or_raise(request.user)
                verification.identity_verification_status = VerificationRequest.VerificationProgressStatus.VERIFIED
                verification.verification_method = VerificationRequest.Method.AUTOMATED
                update_fields.extend(["identity_verification_status", "verification_method"])
            else:
                verification.identity_verification_status = VerificationRequest.VerificationProgressStatus.PENDING
                update_fields.append("identity_verification_status")

        if request_type == VerificationRequest.RequestType.PROPERTY_DOCUMENTS:
            verification.property_document_verification_status = VerificationRequest.VerificationProgressStatus.PENDING
            verification.physical_property_status = physical_property_status
            update_fields.extend(["property_document_verification_status", "physical_property_status"])


class TenantVerificationRequestViewSet(VerificationRequestBaseViewSet):
    user_role = AppUser.Role.TENANT

    def validate_submission(self, request, request_type, physical_property_status):
        if request_type == VerificationRequest.RequestType.PROPERTY_DOCUMENTS:
            raise ValidationError({"request_type": "Tenant verification requests do not accept property documents."})

    def apply_submission(self, request, verification, request_type, physical_property_status, update_fields):
        if request_type == VerificationRequest.RequestType.PROPERTY_DOCUMENTS:
            raise ValidationError({"request_type": "Tenant verification requests do not accept property documents."})

        if request_type == VerificationRequest.RequestType.IDENTIFICATION:
            verification.identity_verification_status = VerificationRequest.VerificationProgressStatus.PENDING
            update_fields.append("identity_verification_status")


class BookingViewSet(viewsets.ModelViewSet):
    serializer_class = BookingSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Booking.objects.select_related("listing", "listing__landlord", "tenant", "tenant__tenant_profile").prefetch_related("payments")
        if self.request.user.role == "tenant":
            return qs.filter(tenant=self.request.user).order_by("-created_at")
        if self.request.user.role == "landlord":
            return qs.filter(listing__landlord=self.request.user).order_by("-created_at")
        return qs.order_by("-created_at")

    def perform_create(self, serializer):
        if self.request.user.role == AppUser.Role.TENANT and user_has_bronze_access(self.request.user):
            raise PermissionDenied("Renting property is not available on the Bronze free plan.")
        serializer.save()

    @action(detail=False, methods=["get"], url_path="listing/(?P<listing_id>[^/.]+)")
    def listing(self, request, listing_id=None):
        booking = self.get_queryset().filter(listing_id=listing_id).first()
        if not booking:
            return Response({"detail": "No booking found."}, status=404)
        return Response(self.get_serializer(booking).data)

    @action(detail=True, methods=["get", "patch"], url_path="rental-progress")
    def rental_progress(self, request, pk=None):
        booking = self.get_object()

        if request.method == "PATCH":
            serializer = RentalProgressUpdateSerializer(
                data=request.data,
                context={"request": request, "booking": booking},
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()
            booking = (
                self.get_queryset()
                .select_related("tenant", "listing", "listing__landlord")
                .get(pk=booking.pk)
            )
            trigger_booking_payouts_if_ready(booking)
            booking = self.get_queryset().get(pk=booking.pk)

        return Response(self.get_serializer(booking).data)


@method_decorator(production_ratelimit(key="ip", rate="120/m", method="POST", block=True), name="flutterwave_webhook")
class PaymentViewSet(viewsets.ModelViewSet):
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if self.request.user.role == "admin":
            return Payment.objects.select_related("booking", "booking__listing", "booking__tenant").order_by("-payment_date")
        return (
            Payment.objects.select_related("booking", "booking__listing", "booking__tenant")
            .filter(booking__tenant=self.request.user)
            .order_by("-payment_date")
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        booking = Booking.objects.select_related("listing", "tenant").get(
            id=serializer.validated_data["booking_id"],
            tenant=request.user,
        )
        amount = serializer.validated_data["amount"]
        payment_method = serializer.validated_data["payment_method"]
        validate_booking_payment_amount(booking, amount, payment_method)

        payment = (
            Payment.objects.filter(booking=booking, status__in=OPEN_PAYMENT_STATUSES)
            .order_by("-updated_at")
            .first()
        )
        created = payment is None
        if payment is None:
            payment = Payment.objects.create(
                booking=booking,
                amount=amount,
                payment_method=payment_method,
                transaction_id=build_booking_payment_reference(),
                currency="NGN",
                provider="flutterwave",
                status="pending",
                payment_date=timezone.now(),
            )
        else:
            amount_changed = normalize_decimal_amount(payment.amount) != normalize_decimal_amount(amount)
            method_changed = payment.payment_method != payment_method
            if amount_changed:
                payment.transaction_id = build_booking_payment_reference()
                clear_payment_virtual_account_fields(payment)
            elif method_changed:
                clear_payment_virtual_account_fields(payment)
            payment.amount = amount
            payment.payment_method = payment_method
            payment.provider = "flutterwave"
            payment.status = "pending"

        try:
            checkout, collection_mode, cleared_checkout_fields = prepare_booking_payment_checkout(payment)
        except FlutterwaveError as exc:
            return Response({"detail": str(exc)}, status=502)
        payment.provider_payload = update_payment_provider_payload(
            payment.provider_payload,
            None,
            checkout=checkout,
            return_url=build_booking_payment_return_url(payment),
            collection_mode=collection_mode,
        )
        payment.save(
            update_fields=list(dict.fromkeys([
                "amount",
                "payment_method",
                "provider",
                "status",
                "transaction_id",
                "virtual_account_reference",
                "virtual_account_id",
                "virtual_account_number",
                "virtual_account_bank_name",
                "virtual_account_bank_code",
                "virtual_account_expiry",
                "virtual_account_payload",
                "provider_payload",
                "updated_at",
                *cleared_checkout_fields,
            ]))
        )

        return Response(
            {
                "payment": self.get_serializer(payment).data,
                "checkout": checkout,
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="flutterwave/checkout")
    def flutterwave_checkout(self, request, pk=None):
        payment = self.get_object()
        if payment.status not in OPEN_PAYMENT_STATUSES:
            raise ValidationError("Payment is no longer pending.")
        if payment.payment_method == "card" and booking_payments_card_limit_exceeded(payment.amount):
            raise ValidationError(
                {
                    "payment_method": (
                        "Flutterwave card payments are limited to NGN 7,000,000 per transaction. "
                        "Please use Bank Transfer for this payment."
                    )
                }
            )

        try:
            checkout, collection_mode, cleared_checkout_fields = prepare_booking_payment_checkout(payment)
        except FlutterwaveError as exc:
            return Response({"detail": str(exc)}, status=502)
        payment.provider_payload = update_payment_provider_payload(
            payment.provider_payload,
            None,
            checkout=checkout,
            return_url=build_booking_payment_return_url(payment),
            collection_mode=collection_mode,
        )
        payment.save(update_fields=list(dict.fromkeys(["provider_payload", "updated_at", *cleared_checkout_fields])))
        return Response({"payment": self.get_serializer(payment).data, "checkout": checkout})

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        payment = self.get_object()
        if payment.status not in OPEN_PAYMENT_STATUSES:
            raise ValidationError("Payment is no longer pending.")

        payment.status = "cancelled"
        payment.provider_payload = update_payment_provider_payload(
            payment.provider_payload,
            None,
            cancellation={
                "cancelled_at": timezone.now().isoformat(),
                "reason": "cancelled_by_user",
            },
        )
        payment.save(update_fields=["status", "provider_payload", "updated_at"])
        return Response(self.get_serializer(payment).data)

    @action(detail=False, methods=["get"], url_path="flutterwave/verify")
    def flutterwave_verify(self, request):
        reference = (request.query_params.get("reference") or request.query_params.get("tx_ref") or "").strip()
        if not reference:
            raise ValidationError({"reference": "Payment reference is required."})

        payment = get_object_or_404(self.get_queryset(), transaction_id=reference)
        try:
            payment = sync_booking_payment(
                payment,
                transaction_id=request.query_params.get("transaction_id"),
                provider_status=request.query_params.get("status"),
                source="status",
            )
        except FlutterwaveError as exc:
            return Response({"detail": str(exc)}, status=502)

        return Response(self.get_serializer(payment).data)

    @action(detail=False, methods=["post"], url_path="webhook/flutterwave", permission_classes=[AllowAny], authentication_classes=[])
    def flutterwave_webhook(self, request):
        signature_error = verify_flutterwave_request_signature(request)
        if signature_error is not None:
            return signature_error

        body = request.data
        transfer_data = body.get("data") if isinstance(body, dict) else {}
        if isinstance(transfer_data, dict):
            transfer_reference = str(transfer_data.get("reference") or transfer_data.get("transfer_reference") or "").strip()
            if transfer_reference:
                settlement = PaymentSettlement.objects.select_related(
                    "payment",
                    "payment__booking",
                    "payment__booking__tenant",
                    "payment__booking__listing",
                    "payment__booking__listing__landlord",
                ).filter(transfer_reference=transfer_reference).first()
                if settlement:
                    sync_payment_settlement_transfer(settlement, body)
                    return Response({"status": "ok", "reference": transfer_reference})

        reference = extract_reference(body)
        provider_transaction_id = extract_provider_transaction_id(body)
        if not reference and not provider_transaction_id:
            return Response({"status": "ok"})

        payment = Payment.objects.select_related("booking", "booking__listing", "booking__tenant").filter(transaction_id=reference).first()
        featured = FeaturedPayment.objects.select_related("listing", "landlord").filter(transaction_id=reference).first()
        subscription = (
            SubscriptionPayment.objects.select_related("user")
            .filter(Q(transaction_id=reference) | Q(provider_charge_id=provider_transaction_id))
            .first()
        )
        settlement = PaymentSettlement.objects.select_related(
            "payment",
            "payment__booking",
            "payment__booking__tenant",
            "payment__booking__listing",
            "payment__booking__listing__landlord",
        ).filter(transfer_reference=reference).first()
        if settlement and not payment and not featured and not subscription:
            sync_payment_settlement_transfer(settlement, body)
            return Response({"status": "ok", "reference": reference})
        if not payment and not featured and not subscription:
            return Response({"status": "error", "message": "Payment not found"}, status=404)

        try:
            if payment:
                sync_booking_payment(
                    payment,
                    transaction_id=provider_transaction_id or None,
                    payload=body,
                    source="webhook",
                )
            if featured:
                sync_featured_payment(
                    featured,
                    transaction_id=provider_transaction_id or None,
                    payload=body,
                    source="webhook",
                )
            if subscription:
                sync_subscription_payment(
                    subscription,
                    transaction_id=provider_transaction_id or None,
                    payload=body,
                    source="webhook",
                )
        except FlutterwaveError as exc:
            return Response({"status": "error", "message": str(exc)}, status=502)

        return Response({"status": "ok", "reference": reference})


class SubscriptionPaymentViewSet(viewsets.GenericViewSet, mixins.ListModelMixin):
    serializer_class = SubscriptionPaymentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        ensure_supported_subscription_role(self.request.user)
        return SubscriptionPayment.objects.select_related("user").filter(user=self.request.user).order_by("-created_at")

    def retrieve(self, request, pk=None):
        payment = self.get_queryset().get(id=pk)
        return Response(self.get_serializer(payment).data)

    @action(detail=False, methods=["get"], url_path="recurring/config")
    def recurring_config(self, request):
        ensure_supported_subscription_role(request.user)
        encryption_key = str(getattr(settings, "FLUTTERWAVE_ENCRYPTION_KEY", "") or "").strip()
        enabled = should_use_v4() and flutterwave_encryption_key_is_configured()
        return Response(
            {
                "enabled": enabled,
                "encryption_key": encryption_key if enabled else "",
            }
        )

    @action(detail=False, methods=["get"], url_path="payment-methods")
    def payment_methods(self, request):
        ensure_supported_subscription_role(request.user)
        queryset = SubscriptionPaymentMethod.objects.filter(user=request.user).order_by("-updated_at")
        return Response(SubscriptionPaymentMethodSerializer(queryset, many=True).data)

    @action(detail=False, methods=["post"], url_path="request")
    def request_subscription(self, request):
        ensure_supported_subscription_role(request.user)
        serializer = SubscriptionPaymentRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        plan_code = serializer.validated_data["plan_code"]
        billing_cycle = serializer.validated_data["billing_cycle"]
        recurring_requested = bool(serializer.validated_data.get("recurring"))

        try:
            amount_value = get_subscription_pricing()[request.user.role][plan_code][billing_cycle]
        except KeyError as exc:
            raise ValidationError("Selected subscription plan is unavailable.") from exc

        amount_decimal = Decimal(str(amount_value))
        is_free_plan = amount_decimal == 0
        if recurring_requested and is_free_plan:
            raise ValidationError("Recurring payments are available only for paid subscription plans.")
        try:
            payment_method = resolve_subscription_payment_method(request.user, serializer.validated_data) if recurring_requested else None
        except FlutterwaveError as exc:
            return Response({"detail": str(exc)}, status=502)
        duration_days = 14 if is_free_plan else 30 if billing_cycle == SubscriptionPayment.BillingCycle.MONTHLY else 365
        next_status = SubscriptionPayment.Status.COMPLETED if is_free_plan else SubscriptionPayment.Status.PENDING
        next_provider = "free" if is_free_plan else "flutterwave"
        next_payment_date = timezone.now() if is_free_plan else None
        payment = (
            SubscriptionPayment.objects.filter(
                user=request.user,
                plan_code=plan_code,
                billing_cycle=billing_cycle,
                status=SubscriptionPayment.Status.PENDING,
            )
            .order_by("-updated_at")
            .first()
        )
        created = payment is None
        if payment is None:
            payment = SubscriptionPayment.objects.create(
                user=request.user,
                role=request.user.role,
                plan_code=plan_code,
                billing_cycle=billing_cycle,
                amount=amount_decimal,
                currency="NGN",
                provider=next_provider,
                status=next_status,
                transaction_id=build_subscription_payment_reference(),
                payment_date=next_payment_date,
                expires_at=timezone.now() + timedelta(days=duration_days),
                payment_method=payment_method,
                recurring_enabled=recurring_requested,
                billing_reason="recurring_initial" if recurring_requested else "manual",
            )
        else:
            payment.role = request.user.role
            payment.amount = amount_decimal
            payment.currency = "NGN"
            payment.provider = next_provider
            payment.status = next_status
            payment.transaction_id = payment.transaction_id or build_subscription_payment_reference()
            payment.cashier_url = ""
            payment.payment_method = payment_method
            payment.provider_charge_id = ""
            payment.recurring_enabled = recurring_requested
            payment.billing_reason = "recurring_initial" if recurring_requested else "manual"
            payment.provider_payload = None
            payment.webhook_data = None
            payment.payment_date = next_payment_date
            payment.expires_at = timezone.now() + timedelta(days=duration_days)
            payment.save(
                update_fields=[
                    "role",
                    "amount",
                    "currency",
                    "provider",
                    "status",
                    "transaction_id",
                    "cashier_url",
                    "payment_method",
                    "provider_charge_id",
                    "recurring_enabled",
                    "billing_reason",
                    "provider_payload",
                    "webhook_data",
                    "payment_date",
                    "expires_at",
                    "updated_at",
                ]
            )

        if recurring_requested:
            try:
                payment = charge_subscription_with_payment_method(payment, source="recurring_initial")
            except (FlutterwaveError, ValidationError) as exc:
                payment.status = SubscriptionPayment.Status.FAILED
                payment.recurring_enabled = False
                payment.provider_payload = update_payment_provider_payload(
                    payment.provider_payload,
                    None,
                    recurring_error={"message": str(exc), "failed_at": timezone.now().isoformat()},
                )
                payment.save(update_fields=["status", "recurring_enabled", "provider_payload", "updated_at"])
                response_status = 400 if isinstance(exc, ValidationError) else 502
                return Response({"detail": str(exc), "payment": self.get_serializer(payment).data}, status=response_status)

        return Response(self.get_serializer(payment).data, status=201 if created else 200)

    @action(detail=True, methods=["post"], url_path="disable-recurring")
    def disable_recurring(self, request, pk=None):
        payment = self.get_queryset().get(id=pk)
        if not payment.recurring_enabled:
            return Response(self.get_serializer(payment).data)

        payment.recurring_enabled = False
        payment.provider_payload = update_payment_provider_payload(
            payment.provider_payload,
            None,
            recurring_disabled={
                "disabled_at": timezone.now().isoformat(),
                "reason": "disabled_by_user",
            },
        )
        payment.save(update_fields=["recurring_enabled", "provider_payload", "updated_at"])
        return Response(self.get_serializer(payment).data)

    @action(detail=True, methods=["post"], url_path="flutterwave/checkout")
    def flutterwave_checkout(self, request, pk=None):
        payment = self.get_queryset().get(id=pk)
        if payment.status != SubscriptionPayment.Status.PENDING:
            raise ValidationError("Payment is not pending")
        if payment.recurring_enabled:
            raise ValidationError("Recurring subscription payments are charged with the saved card.")

        if not payment.transaction_id:
            payment.transaction_id = build_subscription_payment_reference()

        checkout = build_subscription_checkout(payment)
        payment.provider_payload = update_payment_provider_payload(
            payment.provider_payload,
            None,
            checkout=checkout,
            return_url=build_subscription_payment_return_url(payment),
        )
        payment.provider = "flutterwave"
        payment.save(update_fields=["transaction_id", "provider_payload", "provider", "updated_at"])
        return Response({"payment": self.get_serializer(payment).data, "checkout": checkout})

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        payment = self.get_queryset().get(id=pk)
        if payment.status != SubscriptionPayment.Status.PENDING:
            raise ValidationError("Payment is no longer pending.")

        payment.status = SubscriptionPayment.Status.CANCELLED
        payment.cashier_url = ""
        payment.provider_payload = update_payment_provider_payload(
            payment.provider_payload,
            None,
            cancellation={
                "cancelled_at": timezone.now().isoformat(),
                "reason": "cancelled_by_user",
            },
        )
        payment.save(update_fields=["status", "cashier_url", "provider_payload", "updated_at"])
        return Response(self.get_serializer(payment).data)

    @action(detail=False, methods=["get"], url_path="flutterwave/verify")
    def flutterwave_verify(self, request):
        ensure_supported_subscription_role(request.user)
        reference = (request.query_params.get("reference") or request.query_params.get("tx_ref") or "").strip()
        if not reference:
            raise ValidationError({"reference": "Payment reference is required."})

        payment = get_object_or_404(self.get_queryset(), transaction_id=reference)
        try:
            payment = sync_subscription_payment(
                payment,
                transaction_id=request.query_params.get("transaction_id"),
                provider_status=request.query_params.get("status"),
                source="status",
            )
        except FlutterwaveError as exc:
            return Response({"detail": str(exc)}, status=502)

        return Response(self.get_serializer(payment).data)


class FeaturedViewSet(viewsets.GenericViewSet, mixins.ListModelMixin):
    serializer_class = FeaturedPaymentSerializer

    def get_permissions(self):
        if self.action == "listings":
            return [AllowAny()]
        return [IsLandlordOrAdmin()]

    def get_queryset(self):
        qs = FeaturedPayment.objects.select_related("listing", "landlord")
        if self.request.user.role != "admin":
            qs = qs.filter(landlord=self.request.user)
        return qs.order_by("-created_at")

    def retrieve(self, request, pk=None):
        payment = self.get_queryset().get(id=pk)
        return Response(self.get_serializer(payment).data)

    @action(detail=False, methods=["post"], url_path="request")
    def request_featured(self, request):
        listing = Listing.objects.get(id=request.data.get("listing_id"))
        if request.user.role != "admin" and listing.landlord_id != request.user.id:
            raise PermissionDenied("You can only feature your own properties")
        if listing.featured:
            raise ValidationError("Property is already featured")
        days = max(1, min(int(request.data.get("featured_duration_days", 30)), 90))
        payment = (
            FeaturedPayment.objects.filter(
                listing=listing,
                landlord=listing.landlord,
                status=FeaturedPayment.Status.PENDING,
            )
            .order_by("-created_at")
            .first()
        )
        created = payment is None
        if payment is None:
            payment = FeaturedPayment.objects.create(
                listing=listing,
                landlord=listing.landlord,
                amount=(FEATURED_PROPERTY_FEE / Decimal("30")) * Decimal(days),
                featured_duration_days=days,
                expires_at=timezone.now() + timedelta(days=days),
                transaction_id=f"FEAT_{uuid.uuid4().hex[:20].upper()}",
            )
        else:
            payment.featured_duration_days = days
            payment.amount = (FEATURED_PROPERTY_FEE / Decimal("30")) * Decimal(days)
            payment.expires_at = timezone.now() + timedelta(days=days)
            payment.save(update_fields=["featured_duration_days", "amount", "expires_at", "updated_at"])
        return Response(self.get_serializer(payment).data, status=201 if created else 200)

    @action(detail=True, methods=["post"], url_path="flutterwave/checkout")
    def flutterwave_checkout(self, request, pk=None):
        payment = self.get_queryset().get(id=pk)
        if payment.status != FeaturedPayment.Status.PENDING:
            raise ValidationError("Payment is not pending")

        if not payment.transaction_id:
            payment.transaction_id = f"FEAT_{uuid.uuid4().hex[:20].upper()}"

        checkout = build_featured_checkout(payment)
        payment.provider_payload = update_payment_provider_payload(
            payment.provider_payload,
            None,
            checkout=checkout,
            return_url=build_featured_payment_return_url(payment),
        )
        payment.opay_cashier_url = checkout.get("redirect_url", "")
        payment.provider = "flutterwave"
        payment.save(update_fields=["transaction_id", "provider_payload", "opay_cashier_url", "provider", "updated_at"])
        return Response({"payment": self.get_serializer(payment).data, "checkout": checkout})

    @action(detail=False, methods=["get"], url_path="flutterwave/verify")
    def flutterwave_verify(self, request):
        reference = (request.query_params.get("reference") or request.query_params.get("tx_ref") or "").strip()
        if not reference:
            raise ValidationError({"reference": "Payment reference is required."})

        payment = get_object_or_404(self.get_queryset(), transaction_id=reference)
        try:
            payment = sync_featured_payment(
                payment,
                transaction_id=request.query_params.get("transaction_id"),
                provider_status=request.query_params.get("status"),
                source="status",
            )
        except FlutterwaveError as exc:
            return Response({"detail": str(exc)}, status=502)

        return Response(self.get_serializer(payment).data)

    @action(detail=True, methods=["post"], url_path="pay")
    def simulate_pay(self, request, pk=None):
        block_production_mock("Simulated featured payment")
        payment = self.get_queryset().get(id=pk)
        complete_featured_payment(
            payment,
            webhook_data={"eventType": "MOCK.TRANSACTION.SUCCESS", "source": "simulate_pay"},
        )
        return Response(self.get_serializer(payment).data)

    @action(detail=False, methods=["get"], url_path="payments")
    def payments(self, request):
        return Response(self.get_serializer(self.get_queryset(), many=True).data)

    @action(detail=True, methods=["put"], url_path="update-duration")
    def update_duration(self, request, pk=None):
        payment = self.get_queryset().get(id=pk)
        if payment.status != FeaturedPayment.Status.PENDING:
            raise ValidationError("Can only update duration for pending payments")
        days = min(int(request.data.get("featured_duration_days", 30)), 90)
        payment.featured_duration_days = days
        payment.amount = (FEATURED_PROPERTY_FEE / Decimal("30")) * Decimal(days)
        payment.expires_at = timezone.now() + timedelta(days=days)
        payment.save()
        return Response(self.get_serializer(payment).data)

    def unfeature(self, request, pk=None):
        listing = Listing.objects.get(id=pk)
        if request.user.role != "admin" and listing.landlord_id != request.user.id:
            raise PermissionDenied("You can only unfeature your own properties")

        active_payments = FeaturedPayment.objects.filter(listing=listing).exclude(
            status__in=[FeaturedPayment.Status.CANCELLED, FeaturedPayment.Status.FAILED]
        )
        for payment in active_payments:
            payment.status = FeaturedPayment.Status.CANCELLED
            payment.save(update_fields=["status", "updated_at"])

        updates = []
        if listing.featured:
            listing.featured = False
            updates.append("featured")
        if listing.featured_until is not None:
            listing.featured_until = None
            updates.append("featured_until")

        if updates:
            updates.append("updated_at")
            listing.save(update_fields=updates)

        return Response({"ok": True})

    @action(detail=False, methods=["get"], url_path="listings", permission_classes=[AllowAny])
    def listings(self, request):
        qs = exclude_deposit_secured_listings(
            Listing.objects.filter(featured=True, status=Listing.Status.AVAILABLE)
        ).prefetch_related("images").order_by("-updated_at")
        return Response(ListingSerializer(qs, many=True, context={"request": request}).data)


class FavouriteViewSet(viewsets.ModelViewSet):
    serializer_class = FavouriteSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Favourite.objects.filter(tenant=self.request.user).select_related("listing").prefetch_related("listing__images").order_by("-created_at")

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.user)


class ReviewViewSet(viewsets.ModelViewSet):
    serializer_class = ReviewSerializer
    pagination_class = None

    def get_permissions(self):
        if self.action in {"list", "retrieve"}:
            return [AllowAny()]
        return [IsAuthenticated()]

    def get_queryset(self):
        queryset = Review.objects.select_related("listing", "tenant", "landlord").order_by("-updated_at", "-created_at")
        listing_id = (self.request.query_params.get("listing_id") or "").strip()
        landlord_id = (self.request.query_params.get("landlord_id") or "").strip()
        mine = (self.request.query_params.get("mine") or "").strip().lower() == "true"

        if listing_id:
            queryset = queryset.filter(listing_id=listing_id)
        if landlord_id:
            queryset = queryset.filter(landlord_id=landlord_id)
        if mine:
            if not getattr(self.request.user, "is_authenticated", False):
                return queryset.none()
            queryset = queryset.filter(tenant=self.request.user)

        return queryset

    def perform_create(self, serializer):
        if self.request.user.role != AppUser.Role.TENANT:
            raise PermissionDenied("Only tenants can submit reviews.")
        if user_has_bronze_access(self.request.user):
            raise PermissionDenied("Reviews are not available on the Bronze free plan.")

        listing = get_object_or_404(Listing, id=self.request.data.get("listing_id"))
        if Review.objects.filter(listing=listing, tenant=self.request.user).exists():
            raise ValidationError({"detail": "You already reviewed this property. Edit the existing review instead."})
        serializer.save(tenant=self.request.user, landlord=listing.landlord, listing=listing)

    def perform_update(self, serializer):
        review = self.get_object()
        if self.request.user.role != AppUser.Role.ADMIN and review.tenant_id != self.request.user.id:
            raise PermissionDenied("Forbidden")
        if self.request.user.role == AppUser.Role.TENANT and user_has_bronze_access(self.request.user):
            raise PermissionDenied("Reviews are not available on the Bronze free plan.")
        serializer.save()

    def perform_destroy(self, instance):
        if self.request.user.role != AppUser.Role.ADMIN and instance.tenant_id != self.request.user.id:
            raise PermissionDenied("Forbidden")
        instance.delete()


class FeedbackViewSet(viewsets.ModelViewSet):
    serializer_class = FeedbackSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = Feedback.objects.select_related("user").order_by("-created_at")
        if self.request.user.role != AppUser.Role.ADMIN:
            queryset = queryset.filter(user=self.request.user)
        return queryset

    def perform_create(self, serializer):
        serializer.save(
            user=self.request.user,
            name=(self.request.data.get("name") or self.request.user.name or "").strip() or self.request.user.name,
            role=self.request.user.role,
        )


class MessageViewSet(viewsets.ModelViewSet):
    serializer_class = MessageSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            Message.objects.filter(Q(sender=self.request.user) | Q(receiver=self.request.user))
            .select_related("sender", "receiver")
            .order_by("-created_at")
        )

    def perform_create(self, serializer):
        if self.request.user.role == "tenant" and not self.request.user.is_verified:
            raise PermissionDenied("Your account must be verified before contacting landlords. Please submit your NIN for verification.")
        receiver_id = serializer.validated_data.get("receiver_id")
        receiver = AppUser.objects.filter(id=receiver_id).first()
        if receiver is None:
            raise ValidationError({"receiver_id": "Receiver not found."})
        if self.request.user.role == AppUser.Role.TENANT and receiver.role == AppUser.Role.LANDLORD:
            if user_has_bronze_access(self.request.user):
                raise PermissionDenied("Contacting landlords is not available on the Bronze free plan.")
            if user_has_bronze_access(receiver):
                raise PermissionDenied("This landlord cannot receive tenant messages on the Bronze free plan.")
        if self.request.user.role == AppUser.Role.LANDLORD and receiver.role == AppUser.Role.TENANT and user_has_bronze_access(self.request.user):
            raise PermissionDenied("Contacting tenants is not available on the Bronze free plan.")
        if contains_contact_info(serializer.validated_data.get("content", "")):
            raise ValidationError("Phone numbers, emails, and social media handles are not allowed. Please use chat only.")
        serializer.save()

    @action(detail=False, methods=["get"], url_path="listing/(?P<listing_id>[^/.]+)")
    def listing_thread(self, request, listing_id=None):
        qs = self.get_queryset().filter(listing_id=listing_id).order_by("created_at")
        return Response(self.get_serializer(qs, many=True).data)

    @action(detail=False, methods=["get"], url_path="conversations")
    def conversations(self, request):
        latest = {}
        for msg in self.get_queryset():
            counterpart = str(msg.receiver_id if msg.sender_id == request.user.id else msg.sender_id)
            if counterpart not in latest:
                latest[counterpart] = msg
        return Response([
            {
                "counterpart_id": key,
                "counterpart_name": counterpart.name,
                "counterpart_role": counterpart.role,
                "counterpart_profile_photo_url": counterpart.profile_photo_url,
                "last_message": {"id": msg.id, "content": msg.content, "created_at": msg.created_at},
                "listing_id": msg.listing_id,
            }
            for key, msg in latest.items()
            for counterpart in [msg.receiver if msg.sender_id == request.user.id else msg.sender]
        ])


class CommunityChatMessageViewSet(viewsets.GenericViewSet, mixins.ListModelMixin):
    serializer_class = CommunityChatMessageSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if self.request.user.role not in COMMUNITY_CHAT_ROLES:
            raise PermissionDenied("Only tenant and landlord accounts can access community chat.")
        if not user_has_active_community_chat_subscription(self.request.user):
            raise PermissionDenied("Community chat is available only to active Gold or Platinum subscription accounts.")
        return (
            CommunityChatMessage.objects.select_related("sender")
            .filter(sender__role=self.request.user.role)
            .order_by("-created_at")
        )


class SupportChatMessageViewSet(viewsets.GenericViewSet, mixins.ListModelMixin):
    serializer_class = SupportChatMessageSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = SupportChatMessage.objects.select_related("thread_user", "sender").order_by("-created_at")
        if self.request.user.role in {AppUser.Role.TENANT, AppUser.Role.LANDLORD}:
            return queryset.filter(thread_user=self.request.user)

        thread_user_id = (
            self.request.query_params.get("user_id")
            or self.request.query_params.get("tenant_id")
            or self.request.query_params.get("landlord_id")
        )
        if thread_user_id:
            return queryset.filter(thread_user_id=thread_user_id)
        return queryset


class DashboardViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=["get"], url_path="landlord/(?P<landlord_id>[^/.]+)/listings")
    def landlord_listings(self, request, landlord_id=None):
        if request.user.role != "admin" and str(request.user.id) != str(landlord_id):
            raise PermissionDenied("Forbidden")
        qs = (
            Listing.objects.filter(landlord_id=landlord_id)
            .exclude(status=Listing.Status.ARCHIVED)
            .prefetch_related("images")
            .order_by("-created_at")
        )
        return Response(ListingSerializer(qs, many=True, context={"request": request}).data)


class AdminViewSet(viewsets.ViewSet):
    permission_classes = [IsAdminRole]

    @action(detail=False, methods=["post"], url_path="register", permission_classes=[AllowAny])
    def register(self, request):
        if User.objects.filter(role="admin").exists():
            return Response({"detail": "Only existing admins can create new admin accounts"}, status=403)
        user = User.objects.create_user(
            email=request.data.get("email"),
            password=request.data.get("password"),
            name=request.data.get("name", "Admin"),
            role="admin",
            email_verified=True,
            is_staff=True,
        )
        return Response({"message": "Admin user created successfully", "user_id": user.id, "email": user.email, "role": user.role}, status=201)

    @action(detail=False, methods=["get"], url_path="stats")
    def stats(self, request):
        return Response({
            "total_users": User.objects.count(),
            "total_landlords": User.objects.filter(role="landlord").count(),
            "total_tenants": User.objects.filter(role="tenant").count(),
            "total_admins": User.objects.filter(role="admin").count(),
            "total_listings": Listing.objects.count(),
            "active_listings": Listing.objects.filter(status="available").count(),
            "total_verifications": VerificationRequest.objects.count(),
            "pending_verifications": VerificationRequest.objects.filter(status="pending").count(),
            "total_revenue": Payment.objects.filter(status="completed").aggregate(total=Sum("amount"))["total"] or 0,
            "last_updated": timezone.now(),
        })

    @action(detail=False, methods=["get"], url_path="users")
    def users(self, request):
        qs = User.objects.all().order_by("-created_at")
        role = request.query_params.get("role")
        if role:
            qs = qs.filter(role=role)
        return Response(UserSerializer(qs[: int(request.query_params.get("limit", 50))], many=True).data)

    @action(detail=False, methods=["get"], url_path="listings")
    def listings(self, request):
        qs = Listing.objects.prefetch_related("images").order_by("-created_at")
        listing_status = request.query_params.get("status")
        if listing_status:
            qs = qs.filter(status=listing_status)
        return Response(ListingSerializer(qs[: int(request.query_params.get("limit", 50))], many=True, context={"request": request}).data)


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    ok, payload = database_healthcheck()
    return JsonResponse(payload, status=200 if ok else 503)


@api_view(["GET"])
@permission_classes([AllowAny])
def homepage_video(request):
    video_path = settings.BASE_DIR / "media" / "video" / "rentdirect.mp4"
    if not video_path.exists():
        raise Http404("Homepage video not found")

    file_size = video_path.stat().st_size
    range_header = request.headers.get("Range", "")

    if range_header:
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
        if not match:
            response = HttpResponse(status=416)
            response["Content-Range"] = f"bytes */{file_size}"
            response["Accept-Ranges"] = "bytes"
            return response

        start_text, end_text = match.groups()
        if not start_text and not end_text:
            response = HttpResponse(status=416)
            response["Content-Range"] = f"bytes */{file_size}"
            response["Accept-Ranges"] = "bytes"
            return response

        if start_text:
            start = int(start_text)
            end = int(end_text) if end_text else file_size - 1
        else:
            suffix_length = int(end_text)
            start = max(file_size - suffix_length, 0)
            end = file_size - 1

        end = min(end, file_size - 1)
        if start >= file_size or start > end:
            response = HttpResponse(status=416)
            response["Content-Range"] = f"bytes */{file_size}"
            response["Accept-Ranges"] = "bytes"
            return response

        content_length = end - start + 1

        def stream_video_range():
            with video_path.open("rb") as video_file:
                video_file.seek(start)
                remaining = content_length
                while remaining > 0:
                    chunk = video_file.read(min(8192, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        response = StreamingHttpResponse(stream_video_range(), status=206, content_type="video/mp4")
        response["Content-Length"] = str(content_length)
        response["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        response["Accept-Ranges"] = "bytes"
        response["Cache-Control"] = "public, max-age=3600"
        return response

    response = FileResponse(video_path.open("rb"), content_type="video/mp4")
    response["Content-Length"] = str(file_size)
    response["Accept-Ranges"] = "bytes"
    response["Cache-Control"] = "public, max-age=3600"
    return response
