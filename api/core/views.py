import base64
import binascii
import logging
import math
import re
import uuid
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import requests
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files.storage import default_storage
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models import Avg, Q, Sum
from django.db.utils import IntegrityError, OperationalError, ProgrammingError
from django.http import FileResponse, Http404, HttpResponse, HttpResponseRedirect, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.html import escape
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated as DRFIsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from .models import (
    AgentProfile,
    AppUser,
    build_booking_progress_data,
    booking_progress_step_completed,
    booking_progress_step_completed_by_any_party,
    booking_progress_step_selected_value,
    complete_booking_progress_step,
    Booking,
    CommunityChatMessage,
    Document,
    Feedback,
    Favourite,
    FeaturedPayment,
    Listing,
    Message,
    Payment,
    InspectionRequest,
    PaymentSettlement,
    PendingRegistration,
    PropertyInspection,
    RepresentativeKyc,
    Review,
    RoleAuditEvent,
    ServicePayment,
    SubscriptionPayment,
    SubscriptionPaymentMethod,
    SubscriptionVATPayment,
    SupportChatMessage,
    TenancyAgreement,
    TenantProfile,
    TenantRefund,
    TenantSearchRequirement,
    UserRole,
    VerificationRequest,
)
from .flutterwave import (
    FlutterwaveError,
    build_checkout_payload,
    create_card_payment_method,
    create_charge,
    create_customer,
    create_payment_method,
    update_charge,
    create_bank_transfer,
    create_dynamic_virtual_account,
    list_banks,
    create_transfer_recipient,
    extract_customer_email,
    extract_next_action_url,
    extract_payment_channel_details,
    extract_payment_method_card_details,
    extract_payment_state,
    extract_provider_data,
    extract_provider_transaction_id,
    extract_resource_id,
    extract_reference,
    extract_virtual_account_details,
    find_transfer_recipient,
    flutterwave_api_version,
    get_or_create_collection_subaccount_id,
    map_redirect_status,
    normalize_decimal_amount,
    query_transaction,
    retrieve_bank_transfer,
    resolve_nigerian_payout_bank_code,
    should_use_v4,
    verify_webhook_signature,
)
from .financial_constants import (
    ACCOUNT_FREEZE_FEE_PERCENTAGE,
    ADMINISTRATION_FEE_RATE,
    ADMINISTRATION_FEE_VAT_RATE,
    CARD_PAYMENT_LIMIT_NGN,
    DEFAULT_SUBSCRIPTION_VAT_RATE_PERCENT,
    DEPOSIT_LISTING_HOLD_DAYS,
    FEATURED_PROPERTY_MAX_DURATION_DAYS,
    FEATURED_PROPERTY_MIN_DURATION_DAYS,
    FEATURED_PROPERTY_MONTHLY_DURATION_DAYS,
    FEATURED_PROPERTY_MONTHLY_FEE,
    AGENT_VERIFICATION_FEE,
    IDENTITY_VERIFICATION_ATTEMPTS_PER_PAYMENT,
    LANDLORD_VERIFICATION_FEE,
    TENANT_VERIFICATION_FEE,
    IN_PERSON_VERIFICATION_FEE,
    LAWYER_SERVICE_FEE_RATE,
    LISTING_DEPOSIT_RATE,
    MONEY_MINOR_UNIT_FACTOR,
    MONEY_PRECISION,
    PAYMENT_CANCELLATION_ADMIN_FEE_RATE,
    PERCENT_DENOMINATOR,
    REFUNDABLE_CAUTION_FEE_RATE,
    TENANT_REFUND_FEE_CAP_NGN,
    TENANT_REFUND_FEE_RATE,
    TENANT_REFUND_PROCESSING_DELAY_HOURS,
    ZERO_AMOUNT,
)
from .banks import normalize_bank_name_key
from .verification_service import verify_cac, verify_nin, verify_nin_and_bvn
from .notifications import (
    send_feedback_acknowledgement,
    send_landlord_payout_notification,
    send_payment_confirmation_to_landlord,
    send_rentdirect_internal_transfer_notification,
)
from .permissions import (
    AllowAnyUnlessFrozen,
    IsAdminRole,
    IsAuthenticatedUnlessFrozen,
    IsLandlordOrAdmin,
)
from .roles import (
    ACTIVE_ROLE_HEADER,
    CUSTOMER_ROLES,
    activate_customer_role,
    active_role_membership,
    apply_active_role,
    available_roles,
    has_active_role,
    identity_credentials_verified,
    identity_verification_attempts_used,
    identity_verification_payment_required,
    prefill_role_identity,
    record_role_event,
    require_identity_verification_payment,
    require_unique_identity_credentials,
    role_bound_user,
    track_identity_verification_attempt,
    users_with_role,
    verified_identity_matches,
)

AllowAny = AllowAnyUnlessFrozen
IsAuthenticated = IsAuthenticatedUnlessFrozen
from .payment_queue import enqueue_booking_payout_check, enqueue_flutterwave_webhook
from .pricing import (
    calculate_administration_fee,
    calculate_administration_fee_vat,
    calculate_deposit_amount,
    calculate_featured_property_fee,
    calculate_refundable_caution_fee,
    calculate_remaining_balance,
    quantize_money,
    resolve_booking_total,
)
from .docuseal import (
    create_submission as create_docuseal_submission,
    get_submission as get_docuseal_submission,
    is_docuseal_configured,
    verify_webhook_signature as verify_docuseal_webhook_signature,
)
from .security import OTP_MAX_ATTEMPTS, OTP_TTL_MINUTES, contains_contact_info, generate_otp, hash_otp, otp_matches
from .profile_validation import is_valid_mobile, is_valid_nin
from .tenancy_agreements import (
    agreement_form_fields,
    agreement_missing_fields,
    build_agreement_draft,
    generate_tenancy_agreement,
    render_tenancy_agreement,
    serialize_tenancy_agreement,
    sign_tenancy_agreement,
    signature_block_signed,
    signature_role_for_user,
)
from .whatsapp import send_whatsapp_alert_for_user, send_whatsapp_message
from .tenant_verification import normalize_tenant_verification_profile
from .throttling import production_ratelimit
from .community_chat import COMMUNITY_CHAT_ROLES, user_has_active_community_chat_subscription
from .subscription_access import (
    active_plan_code_for,
    support_response_time_for,
    user_has_bronze_access,
    user_has_completed_tenant_profile,
    user_has_gold_access,
    user_has_platinum_access,
    user_has_silver_access,
)
from .location_services import (
    AMENITY_CATEGORIES,
    attach_distance_to_listing,
    coordinates_for_listing,
    listing_neighbourhood,
    nearest_amenities_for_coordinates,
    resolve_city_state_coordinates,
)
from .image_optimization import optimize_profile_image
from .inspection_checklist import (
    INSPECTION_CHECKLIST_SCHEMA,
    build_inspection_analysis,
    validate_inspection_responses,
)
from .inspection_reports import build_inspection_report_pdf
from .inspection_requests import (
    mark_requests_resolved,
    notify_agents_for_listing,
    process_inspection_timeouts,
)
from .referrals import award_referral_earning, build_referral_tree, resolve_referrer
from .serializers import (
    AGENT_PROFILE_REQUIRED_FIELDS,
    agent_profile_is_complete,
    AgentInspectionListingSerializer,
    AgentProfileSerializer,
    BookingSerializer,
    CommunityChatMessageSerializer,
    DocumentSerializer,
    FeedbackSerializer,
    FavouriteSerializer,
    FeaturedPaymentSerializer,
    InspectionRequestSerializer,
    ListingSerializer,
    LoginSerializer,
    MessageSerializer,
    PaymentSerializer,
    PropertyInspectionSerializer,
    RegisterSerializer,
    RepresentativeKycSerializer,
    ReviewSerializer,
    RentalProgressUpdateSerializer,
    ServicePaymentRequestSerializer,
    ServicePaymentSerializer,
    SettingsOtpRequestSerializer,
    SettingsPasswordSerializer,
    SubscriptionPaymentRequestSerializer,
    SubscriptionPaymentSerializer,
    SubscriptionPaymentMethodSerializer,
    SupportChatMessageSerializer,
    TenantProfileSerializer,
    TenantRefundRequestSerializer,
    TenantRefundSerializer,
    TenantSearchRequirementSerializer,
    UserSerializer,
    VerifyRegistrationSerializer,
    VerificationRequestSerializer,
)
from .subscription_pricing import get_subscription_pricing
from .property_matching import top_matches_for_requirement

User = get_user_model()
OPEN_PAYMENT_STATUSES = {"pending", "processing"}
FAILED_PAYMENT_STATUSES = {"failed", "cancelled"}
REFUND_REQUESTED_PAYMENT_STATUS = "refund_requested"
SETTINGS_OTP_PURPOSE_PROFILE = "profile"
SETTINGS_OTP_PURPOSE_PASSWORD = "password"
SETTINGS_OTP_PURPOSE_ACCOUNT = "account"
SETTINGS_PROFILE_MUTABLE_FIELDS = {
    "email",
    "mobile",
    "whatsapp_number",
    "residence",
    "landlord_verification_profile",
}

AGENT_SETTINGS_MUTABLE_FIELDS = {
    "residential_address",
    "city",
    "bank_name",
    "bank_code",
    "account_name",
    "account_number",
}


def build_booking_payment_reference() -> str:
    return f"BOOK{uuid.uuid4().hex[:20].upper()}"


def build_subscription_payment_reference() -> str:
    return f"SUB{uuid.uuid4().hex[:20].upper()}"


def is_valid_flutterwave_reference(reference: str) -> bool:
    normalized = str(reference or "").strip()
    return 6 <= len(normalized) <= 42 and all(character.isalnum() or character == "-" for character in normalized)


def extract_mobile_verification_warning(value: Any) -> str:
    if isinstance(value, dict):
        warning = str(value.get("mobile_warning") or "").strip()
        if warning:
            return warning
        for nested_value in value.values():
            warning = extract_mobile_verification_warning(nested_value)
            if warning:
                return warning
    elif isinstance(value, (list, tuple)):
        for nested_value in value:
            warning = extract_mobile_verification_warning(nested_value)
            if warning:
                return warning
    return ""


def verify_tenant_identity_or_raise(user, profile_data: dict, nin_number: str, bvn_number: str) -> dict:
    identity_data = {
        "first_name": profile_data.get("first_name"),
        "middle_name": profile_data.get("middle_name"),
        "last_name": profile_data.get("last_name"),
        "date_of_birth": profile_data.get("date_of_birth"),
        "gender": profile_data.get("gender"),
        "nationality": profile_data.get("nationality"),
        "state_of_origin": profile_data.get("state_of_origin"),
        "lga": profile_data.get("lga"),
        "mobile": profile_data.get("mobile") or getattr(user, "mobile", ""),
    }
    if not nin_number:
        raise ValidationError({"nin_number": "NIN is required."})
    if not bvn_number:
        raise ValidationError({"bvn_number": "BVN is required."})
    require_unique_identity_credentials(user, nin_number, bvn_number)
    require_identity_verification_payment(user, AppUser.Role.TENANT)
    track_identity_verification_attempt(user, AppUser.Role.TENANT)
    nin_payload, bvn_payload = verify_nin_and_bvn(identity_data, nin_number, bvn_number)
    return {"nin": nin_payload, "bvn": bvn_payload}


def tenant_verified_identity_matches(user, profile_data: dict, nin_number: str, bvn_number: str = "") -> bool:
    submitted_profile = normalize_tenant_verification_profile(
        {
            **profile_data,
            "nin_number": nin_number,
            "bvn_number": bvn_number,
        },
        user,
    )
    if VerificationRequest.objects.filter(
        user=user,
        role=AppUser.Role.TENANT,
        identity_verification_status=VerificationRequest.VerificationProgressStatus.VERIFIED,
    ).exists():
        stored_profile = normalize_tenant_verification_profile(user.tenant_verification_profile, user)
        if stored_profile:
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
            if all(
                str(stored_profile.get(field_name) or "").strip().lower()
                == str(submitted_profile.get(field_name) or "").strip().lower()
                for field_name in identity_fields
            ):
                return True
    # The same credentials may already be verified under another persona
    # (e.g. a verified landlord or PIO activating the tenant role).
    return verified_identity_matches(
        user, submitted_profile, credential_fields=("nin_number", "bvn_number")
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
        submitted_identity = {
            **identity_data,
            "nin_number": nin_number,
            "bvn_number": bvn_number,
        }
        if verified_identity_matches(user, submitted_identity, credential_fields=("nin_number", "bvn_number")):
            # Same credentials already verified under another persona.
            payloads = {"nin": {}, "bvn": {}}
        else:
            require_unique_identity_credentials(user, nin_number, bvn_number)
            require_identity_verification_payment(user, AppUser.Role.LANDLORD)
            track_identity_verification_attempt(user, AppUser.Role.LANDLORD)
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
        require_identity_verification_payment(user, AppUser.Role.LANDLORD)
        track_identity_verification_attempt(user, AppUser.Role.LANDLORD)
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

    action_url = build_otp_email_action_url(
        "/agents/register" if user.role == AppUser.Role.AGENT else "/register"
    )
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

    if purpose == SETTINGS_OTP_PURPOSE_PROFILE:
        purpose_label = "account settings update"
        headline = "Confirm your settings update"
    elif purpose == SETTINGS_OTP_PURPOSE_ACCOUNT:
        purpose_label = "account security change"
        headline = "Confirm your account change"
    else:
        purpose_label = "password change"
        headline = "Confirm your password change"
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
    send_whatsapp_alert_for_user(
        user,
        f"Your RentDirect verification code is {otp_code}. It expires in {OTP_TTL_MINUTES} minutes. Do not share this code with anyone.",
    )


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


def _append_update_fields(update_fields: list[str], *field_names: str) -> None:
    for field_name in field_names:
        if field_name not in update_fields:
            update_fields.append(field_name)


def _has_submitted_value(value) -> bool:
    if isinstance(value, bool):
        return True
    if value is None:
        return False
    return bool(str(value).strip())


def _profile_has_fields(profile: dict, fields: tuple[str, ...]) -> bool:
    return all(_has_submitted_value(profile.get(field_name)) for field_name in fields)


def _profile_has_nested_fields(profile: dict | None, fields: tuple[str, ...]) -> bool:
    if not isinstance(profile, dict):
        return False
    return _profile_has_fields(profile, fields)


def _profile_has_any_nested_field(profile: dict | None, fields: tuple[str, ...]) -> bool:
    if not isinstance(profile, dict):
        return False
    return any(_has_submitted_value(profile.get(field_name)) for field_name in fields)


def _profile_has_nested_field_or_alias(profile: dict | None, field_name: str, *aliases: str) -> bool:
    if not isinstance(profile, dict):
        return False
    return any(_has_submitted_value(profile.get(candidate)) for candidate in (field_name, *aliases))


TENANT_PROFILE_REQUIRED_FIELDS = (
    "first_name",
    "middle_name",
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
TENANT_PROFILE_REQUIRED_CURRENT_RESIDENCE_FINANCIAL_FIELDS = (
    "current_annual_rent",
    "current_move_in_date",
    "expected_move_out_date",
    "reason_for_wanting_to_leave",
)
TENANT_PROFILE_REQUIRED_EMPLOYMENT_FIELDS = (
    "company_name",
    "company_contact_number",
    "industry",
    "employment_type",
    "employment_start_date",
    "position_job_title",
    "company_address",
    "company_website",
    "hr_contact_name",
    "hr_email",
    "hr_contact_phone",
)
TENANT_PROFILE_REQUIRED_FINANCIAL_VERIFICATION_FIELDS = (
    "bank_name",
    "bank_address",
    "account_name",
    "account_number",
    "business_name",
    "business_address",
    "business_type",
)
TENANT_PROFILE_FINANCIAL_INCOME_FIELDS = (
    "average_monthly_income",
    "average_annual_income",
    "savings",
    "monthly_income_amount",
)
TENANT_PROFILE_FINANCIAL_OUTGOING_FIELDS = (
    "outgoing_expenses",
    "annual_outgoing_expenses",
    "monthly_expenses",
)
TENANT_PROFILE_REQUIRED_GUARANTOR_FIELDS = (
    "full_name",
    "relationship",
    "email",
    "mobile_number",
    "occupation",
    "employer",
    "residential_address",
)
TENANT_PROFILE_REQUIRED_LANDLORD_FIELDS = (
    "name",
    "mobile",
    "email",
    "address",
    "property_manager_name",
    "property_manager_phone",
    "property_manager_email",
    "property_manager_address",
)
TENANT_PROFILE_REQUIRED_HOUSEHOLD_FIELDS = (
    "marital_status",
    "number_of_adults",
    "number_of_children",
    "has_pets",
    "work_from_home",
    "commercial_activities_at_home",
    "has_smokers",
)
TENANT_PROFILE_REQUIRED_CRIMINAL_FIELDS = (
    "convicted_of_crime",
    "evicted_from_property",
    "ongoing_tenancy_litigation",
    "rent_arrears_history",
    "legal_dispute_with_landlords",
)
TENANT_PROFILE_REQUIRED_RENTAL_HISTORY_FIELDS = (
    "property_address",
    "annual_rent",
    "service_charge",
    "move_in_date",
    "move_out_date",
    "reason_for_leave",
)
TENANT_PROFILE_EMPLOYMENT_DOCUMENT_LABELS = {
    "employment_letter": ("employment letter",),
    "staff_id": ("staff id", "staff id card"),
    "payslip": ("payslip", "pay slip"),
}
LANDLORD_INDIVIDUAL_REQUIRED_PROFILE_FIELDS = (
    "first_name",
    "last_name",
    "date_of_birth",
    "country_of_birth",
    "state_of_birth",
    "nationality",
    "state_of_origin",
    "lga_of_origin",
    "gender",
    "email",
    "nin",
    "bvn",
    "residential_address",
)
LANDLORD_CORPORATE_REQUIRED_PROFILE_FIELDS = (
    "company_name",
    "business_state",
    "business_city",
    "business_address",
    "company_email",
    "contact_person_name",
    "contact_person_position",
    "cac_registration_number",
    "cac_registration_date",
    "tax_identification_number",
    "nin",
    "bvn",
    "bank_name",
    "account_name",
    "account_number",
)


def _parse_iso_date(value) -> date | None:
    if isinstance(value, date):
        return value
    raw_value = str(value or "").strip()
    if not raw_value:
        return None
    try:
        return date.fromisoformat(raw_value[:10])
    except ValueError:
        return None


def _is_at_least_five_years_ago(value) -> bool:
    parsed_date = _parse_iso_date(value)
    if parsed_date is None:
        return False
    today = timezone.localdate()
    try:
        threshold = today.replace(year=today.year - 5)
    except ValueError:
        threshold = today.replace(year=today.year - 5, day=28)
    return parsed_date <= threshold


def _normalise_document_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _tenant_profile_employment_document_type_count(profile: TenantProfile) -> int:
    matched_document_types = set()
    for document_title in profile.supporting_documents.values_list("title", flat=True):
        normalized_title = _normalise_document_title(document_title)
        for document_type, labels in TENANT_PROFILE_EMPLOYMENT_DOCUMENT_LABELS.items():
            if any(label in normalized_title for label in labels):
                matched_document_types.add(document_type)
    return len(matched_document_types)


def _tenant_profile_requires_rental_history(profile: TenantProfile) -> bool:
    financial_info = profile.financial_info if isinstance(profile.financial_info, dict) else {}
    return not _is_at_least_five_years_ago(financial_info.get("current_move_in_date"))


def tenant_profile_has_mandatory_fields(profile: TenantProfile) -> bool:
    if not all(_has_submitted_value(getattr(profile, field_name, None)) for field_name in TENANT_PROFILE_REQUIRED_FIELDS):
        return False

    financial_info = profile.financial_info if isinstance(profile.financial_info, dict) else {}
    if not _profile_has_nested_field_or_alias(financial_info, "current_annual_rent", "current_rent_amount"):
        return False
    if not _profile_has_nested_fields(financial_info, TENANT_PROFILE_REQUIRED_CURRENT_RESIDENCE_FINANCIAL_FIELDS[1:]):
        return False

    if str(profile.employment_status or "").strip().lower() == "employed":
        if not _profile_has_nested_fields(profile.employment_info, TENANT_PROFILE_REQUIRED_EMPLOYMENT_FIELDS):
            return False
        if _tenant_profile_employment_document_type_count(profile) < 2:
            return False
    elif (
        not _profile_has_nested_fields(financial_info, TENANT_PROFILE_REQUIRED_FINANCIAL_VERIFICATION_FIELDS)
        or not _profile_has_any_nested_field(financial_info, TENANT_PROFILE_FINANCIAL_INCOME_FIELDS)
        or not _profile_has_any_nested_field(financial_info, TENANT_PROFILE_FINANCIAL_OUTGOING_FIELDS)
    ):
        return False

    if not _profile_has_nested_fields(profile.guarantor_details, TENANT_PROFILE_REQUIRED_GUARANTOR_FIELDS):
        return False
    if not _profile_has_nested_fields(profile.landlord_info, TENANT_PROFILE_REQUIRED_LANDLORD_FIELDS):
        return False
    if not _profile_has_nested_fields(profile.household_info, TENANT_PROFILE_REQUIRED_HOUSEHOLD_FIELDS):
        return False
    if profile.household_info.get("has_pets") and not _has_submitted_value(profile.household_info.get("number_of_pets")):
        return False
    if not _profile_has_nested_fields(profile.criminal_declaration, TENANT_PROFILE_REQUIRED_CRIMINAL_FIELDS):
        return False

    if not _tenant_profile_requires_rental_history(profile):
        return True

    rental_history = profile.rental_history if isinstance(profile.rental_history, list) else []
    return any(
        isinstance(item, dict) and _profile_has_fields(item, TENANT_PROFILE_REQUIRED_RENTAL_HISTORY_FIELDS)
        for item in rental_history
    )


def landlord_profile_has_mandatory_fields(user: AppUser) -> bool:
    profile = user.landlord_verification_profile if isinstance(user.landlord_verification_profile, dict) else {}
    if user.landlord_verification_type == AppUser.LandlordVerificationType.INDIVIDUAL:
        return _profile_has_fields(profile, LANDLORD_INDIVIDUAL_REQUIRED_PROFILE_FIELDS)
    if user.landlord_verification_type == AppUser.LandlordVerificationType.CORPORATE:
        return _profile_has_fields(profile, LANDLORD_CORPORATE_REQUIRED_PROFILE_FIELDS)
    return False


def sync_tenant_profile_approval(user: AppUser, profile: TenantProfile) -> VerificationRequest:
    if profile.status != TenantProfile.Status.APPROVED:
        profile.status = TenantProfile.Status.APPROVED
        profile.save(update_fields=["status", "updated_at"])

    verified_at = timezone.now()
    verification, _ = VerificationRequest.objects.get_or_create(
        user=user,
        role=AppUser.Role.TENANT,
        defaults={
            "request_type": VerificationRequest.RequestType.IDENTIFICATION,
            "status": VerificationRequest.Status.APPROVED,
            "identity_verification_status": VerificationRequest.VerificationProgressStatus.VERIFIED,
            "verification_method": VerificationRequest.Method.AUTOMATED,
            "submitted_at": verified_at,
            "reviewed_at": verified_at,
        },
    )
    verification.request_type = VerificationRequest.RequestType.IDENTIFICATION
    verification.submitted_at = verified_at
    verification.identity_verification_status = VerificationRequest.VerificationProgressStatus.VERIFIED
    verification.verification_method = VerificationRequest.Method.AUTOMATED
    verification.status = VerificationRequest.Status.APPROVED
    verification.reviewed_at = verified_at
    verification.save(
        update_fields=[
            "request_type",
            "submitted_at",
            "status",
            "identity_verification_status",
            "verification_method",
            "reviewed_at",
        ]
    )
    return verification


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


def build_service_payment_reference() -> str:
    return f"SVC{uuid.uuid4().hex[:20].upper()}"


def build_service_payment_return_url(payment: ServicePayment) -> str:
    return f"{frontend_site_origin()}/service-payments/{payment.id}"


def lawyer_service_fee_for_booking(booking: Booking) -> Decimal:
    return quantize_money(Decimal(booking.listing.price_per_year or 0) * LAWYER_SERVICE_FEE_RATE)


def build_service_checkout(payment: ServicePayment) -> dict:
    user = payment.user
    purpose_label = {
        ServicePayment.Purpose.AGENT_VERIFICATION: "Property Inspection Officer Identity Verification",
        ServicePayment.Purpose.TENANT_VERIFICATION: "Tenant Identity Verification",
        ServicePayment.Purpose.LANDLORD_VERIFICATION: "Landlord Identity Verification",
    }.get(payment.purpose, "Lawyer-prepared Tenancy Agreement")
    metadata = {
        "service_payment_id": str(payment.id),
        "purpose": payment.purpose,
        "customer_type": user.role,
    }
    if payment.booking_id:
        metadata["booking_id"] = str(payment.booking_id)
        metadata["listing_id"] = str(payment.booking.listing_id)
    return build_checkout_payload(
        reference=payment.transaction_id,
        amount=payment.amount,
        currency=payment.currency,
        email=user.email,
        redirect_url=build_service_payment_return_url(payment),
        payment_method="card",
        title=f"RentDirect {purpose_label}",
        description=f"{purpose_label} service payment",
        metadata=metadata,
        customer_name=user.name,
        customer_phone=user.mobile,
        webhook_url=build_flutterwave_webhook_url(),
    )


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


PUBLIC_CONTACT_KEYS = frozenset({"email", "mobile", "mobile_number", "phone", "phone_number"})


def strip_public_contact_details(value):
    if isinstance(value, dict):
        return {
            key: strip_public_contact_details(item)
            for key, item in value.items()
            if str(key).strip().lower() not in PUBLIC_CONTACT_KEYS
        }
    if isinstance(value, list):
        return [strip_public_contact_details(item) for item in value]
    return value


def build_landlord_public_profile_payload(landlord: AppUser, viewer=None) -> dict:
    listings = (
        Listing.objects
        .filter(landlord=landlord)
        .exclude(status=Listing.Status.ARCHIVED)
        .order_by("-created_at")
    )
    bookings = Booking.objects.filter(listing__landlord=landlord)
    reviews = (
        Review.objects
        .filter(landlord=landlord, review_type=Review.ReviewType.LANDLORD)
        .select_related("tenant", "listing")
        .order_by("-created_at")
    )
    review_stats = reviews.aggregate(average_rating=Avg("rating"))
    average_rating = float(review_stats["average_rating"] or 0)
    review_count = reviews.count()
    active_tenancies = bookings.filter(status__in=[Booking.Status.CONFIRMED, Booking.Status.ACTIVE]).count()
    completed_tenancies = bookings.filter(status=Booking.Status.COMPLETED).count()
    successful_rentals = bookings.filter(
        status__in=[Booking.Status.CONFIRMED, Booking.Status.ACTIVE, Booking.Status.COMPLETED],
    ).count()
    total_applications = bookings.count()
    latest_verification = VerificationRequest.objects.filter(
        user=landlord, role=AppUser.Role.LANDLORD
    ).order_by("-submitted_at").first()
    average_response_seconds = calculate_landlord_average_response_seconds(landlord)
    years_on_platform = round(max((timezone.now().date() - landlord.created_at.date()).days / 365.25, 0), 1)
    total_properties = listings.count()
    properties_rented = listings.filter(status=Listing.Status.RENTED).count()

    identity_verified = bool(
        latest_verification
        and latest_verification.identity_verification_status == VerificationRequest.VerificationProgressStatus.VERIFIED
    )
    house_ownership_verified = bool(
        listings.filter(property_document_verification_status=VerificationRequest.VerificationProgressStatus.VERIFIED).exists()
    )
    phone_verified = bool((landlord.mobile or "").strip())
    email_verified = bool(landlord.email_verified)

    viewer_is_authenticated = getattr(viewer, "is_authenticated", False)
    can_view_verification_badges = viewer_is_authenticated and (
        viewer.role == AppUser.Role.ADMIN
        or (viewer.role == AppUser.Role.LANDLORD and viewer.id == landlord.id)
        or (viewer.role == AppUser.Role.TENANT and user_has_platinum_access(viewer))
    )
    verification_badges = {
        "identity_verified": identity_verified if can_view_verification_badges else False,
        "house_ownership_verified": house_ownership_verified if can_view_verification_badges else False,
        "phone_verified": phone_verified if can_view_verification_badges else False,
        "email_verified": email_verified if can_view_verification_badges else False,
    }
    verification_score = (
        round(sum(verification_badges.values()) / len(verification_badges) * 100)
        if can_view_verification_badges
        else None
    )

    payload = {
        "id": str(landlord.id),
        "display_name": resolve_landlord_display_name(landlord),
        "subtitle": resolve_landlord_subtitle(landlord),
        "full_name": landlord.name,
        "role": landlord.role,
        "landlord_verification_type": landlord.landlord_verification_type,
        "profile_photo_url": landlord.profile_photo_url,
        "verification_badges": verification_badges,
        "verification_score": verification_score,
        "metrics": {
            "total_properties": total_properties,
            "properties_rented": properties_rented,
            "properties_listed": total_properties - properties_rented,
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
    return strip_public_contact_details(payload)


def build_tenant_public_profile_payload(tenant: AppUser) -> dict:
    profile = TenantProfile.objects.filter(user=tenant).first()
    profile_payload = None
    if profile:
        today = timezone.now().date()
        tenant_age = today.year - profile.date_of_birth.year - (
            (today.month, today.day) < (profile.date_of_birth.month, profile.date_of_birth.day)
        )
        profile_payload = {
            "status": profile.status,
            "first_name": profile.first_name,
            "middle_name": profile.middle_name,
            "last_name": profile.last_name,
            "age": tenant_age,
            "gender": profile.gender,
            "nationality": profile.nationality,
            "state_of_origin": profile.state_of_origin,
            "lga": profile.lga,
            "employment_status": profile.employment_status,
            "residence_country": profile.residence_country,
            "residence_state": profile.residence_state,
            "residence_city": profile.residence_city,
            "residence_lga": profile.residence_lga,
            "length_of_stay": profile.length_of_stay,
            "housing_status": profile.housing_status,
            "household_info": profile.household_info,
            "social_presence": profile.social_presence,
            "criminal_declaration": profile.criminal_declaration,
        }

    enquiry_count = Message.objects.filter(
        sender=tenant,
        sender_role=AppUser.Role.TENANT,
        receiver_role=AppUser.Role.LANDLORD,
    ).count()
    application_count = Booking.objects.filter(tenant=tenant).count()
    completed_tenancies = Booking.objects.filter(tenant=tenant, status=Booking.Status.COMPLETED).count()
    years_on_platform = round(max((timezone.now().date() - tenant.created_at.date()).days / 365.25, 0), 1)

    payload = {
        "id": str(tenant.id),
        "name": tenant.name,
        "role": AppUser.Role.TENANT,
        "profile_photo_url": tenant.profile_photo_url,
        "state_of_origin": tenant.state_of_origin,
        "residence": tenant.residence,
        "is_verified": tenant.is_verified_for_role(AppUser.Role.TENANT),
        "email_verified": tenant.email_verified,
        "tenant_profile": profile_payload,
        "metrics": {
            "enquiries_sent": enquiry_count,
            "applications_submitted": application_count,
            "completed_tenancies": completed_tenancies,
            "years_on_platform": years_on_platform,
        },
    }
    return strip_public_contact_details(payload)


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
        narration=str(getattr(settings, "RENTDIRECT_OPERATING_ACCOUNT_NAME", "") or "RentDirect"),
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
        try:
            return ensure_booking_virtual_account(payment), "dynamic_virtual_account", []
        except FlutterwaveError as exc:
            if "forbidden" not in str(exc).lower():
                raise
            cleared_fields = clear_payment_virtual_account_fields(payment)
            return build_booking_checkout(payment), "inline_bank_checkout", cleared_fields

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


def json_decimal(value: Decimal) -> float | int:
    return int(value) if value == value.to_integral_value() else float(value)


def decimal_setting(name: str, default: str) -> Decimal:
    try:
        return Decimal(str(getattr(settings, name, default) or default))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def subscription_vat_rate() -> Decimal:
    return decimal_setting(
        "SUBSCRIPTION_VAT_RATE_PERCENT",
        str(DEFAULT_SUBSCRIPTION_VAT_RATE_PERCENT),
    ).quantize(MONEY_PRECISION)


def calculate_subscription_vat(subscription_fee: Decimal) -> Decimal:
    fee = Decimal(str(subscription_fee))
    if fee <= ZERO_AMOUNT:
        return ZERO_AMOUNT
    return (fee * subscription_vat_rate() / PERCENT_DENOMINATOR).quantize(
        MONEY_PRECISION,
        rounding=ROUND_HALF_UP,
    )


def apply_subscription_vat(payment: SubscriptionPayment, *, save: bool = True) -> SubscriptionPayment:
    next_rate = subscription_vat_rate() if payment.amount > ZERO_AMOUNT else ZERO_AMOUNT
    next_vat_amount = calculate_subscription_vat(payment.amount)
    update_fields = []
    if payment.vat_rate != next_rate:
        payment.vat_rate = next_rate
        update_fields.append("vat_rate")
    if payment.vat_amount != next_vat_amount:
        payment.vat_amount = next_vat_amount
        update_fields.append("vat_amount")
    if save and update_fields and payment.pk:
        update_fields.append("updated_at")
        payment.save(update_fields=update_fields)
    return payment


def resolve_subscription_payment_account() -> dict:
    return resolve_account_payload(
        bank_name=getattr(settings, "RENTDIRECT_OPERATING_BANK_NAME", ""),
        bank_code=getattr(settings, "RENTDIRECT_OPERATING_BANK_CODE", ""),
        account_number=getattr(settings, "RENTDIRECT_OPERATING_ACCOUNT_NUMBER", ""),
        account_name=getattr(settings, "RENTDIRECT_OPERATING_ACCOUNT_NAME", ""),
    )


def resolve_vat_payment_account() -> dict:
    return resolve_account_payload(
        bank_name=getattr(settings, "RENTDIRECT_VAT_HOLDING_BANK_NAME", ""),
        bank_code=getattr(settings, "RENTDIRECT_VAT_HOLDING_BANK_CODE", ""),
        account_number=getattr(settings, "RENTDIRECT_VAT_HOLDING_ACCOUNT_NUMBER", ""),
        account_name=getattr(settings, "RENTDIRECT_VAT_HOLDING_ACCOUNT_NAME", ""),
    )


def collection_account_configured(*, subaccount_id: str, account: dict, business_mobile: str) -> bool:
    if str(subaccount_id or "").strip():
        return True
    return bool(
        account["bank_name"]
        and account["bank_code"]
        and account["account_number"]
        and str(business_mobile or "").strip()
    )


def subscription_direct_settlement_configured() -> bool:
    return collection_account_configured(
        subaccount_id=getattr(settings, "RENTDIRECT_OPERATING_SUBACCOUNT_ID", ""),
        account=resolve_subscription_payment_account(),
        business_mobile=getattr(settings, "RENTDIRECT_OPERATING_BUSINESS_MOBILE", ""),
    ) and collection_account_configured(
        subaccount_id=getattr(settings, "RENTDIRECT_VAT_HOLDING_SUBACCOUNT_ID", ""),
        account=resolve_vat_payment_account(),
        business_mobile=getattr(settings, "RENTDIRECT_VAT_HOLDING_BUSINESS_MOBILE", ""),
    )


def resolve_subscription_subaccount_id(account: dict) -> str:
    configured_subaccount_id = str(getattr(settings, "RENTDIRECT_OPERATING_SUBACCOUNT_ID", "") or "").strip()
    if should_use_v4():
        if not configured_subaccount_id and getattr(settings, "FLUTTERWAVE_V4_ALLOW_UNSPLIT_CHECKOUT", False):
            return ""
        if not configured_subaccount_id:
            raise FlutterwaveError(
                "Flutterwave v4 requires RENTDIRECT_OPERATING_SUBACCOUNT_ID for subscription settlement."
            )
        return configured_subaccount_id
    if not configured_subaccount_id:
        missing_fields = [
            label
            for label, value in {
                "bank_name": account["bank_name"],
                "bank_code": account["bank_code"],
                "account_number": account["account_number"],
                "business_mobile": getattr(settings, "RENTDIRECT_OPERATING_BUSINESS_MOBILE", ""),
            }.items()
            if not str(value or "").strip()
        ]
        if missing_fields:
            raise FlutterwaveError(
                "RentDirect operating payout account is not configured: "
                + ", ".join(missing_fields)
            )
        configured_subaccount_id = get_or_create_collection_subaccount_id(
            bank_code=account["bank_code"],
            account_number=account["account_number"],
            business_name=account["account_name"] or "RentDirect Operations",
            business_email=getattr(settings, "RENTDIRECT_OPERATING_BUSINESS_EMAIL", ""),
            business_mobile=getattr(settings, "RENTDIRECT_OPERATING_BUSINESS_MOBILE", ""),
            country=getattr(settings, "RENTDIRECT_OPERATING_SUBACCOUNT_COUNTRY", "NG"),
            split_type=getattr(settings, "RENTDIRECT_OPERATING_SUBACCOUNT_SPLIT_TYPE", "flat"),
            split_value=str(getattr(settings, "RENTDIRECT_OPERATING_SUBACCOUNT_SPLIT_VALUE", "0") or "0"),
        )
    return configured_subaccount_id


def resolve_vat_subaccount_id(account: dict) -> str:
    configured_subaccount_id = str(getattr(settings, "RENTDIRECT_VAT_HOLDING_SUBACCOUNT_ID", "") or "").strip()
    if should_use_v4():
        if not configured_subaccount_id and getattr(settings, "FLUTTERWAVE_V4_ALLOW_UNSPLIT_CHECKOUT", False):
            return ""
        if not configured_subaccount_id:
            raise FlutterwaveError(
                "Flutterwave v4 requires RENTDIRECT_VAT_HOLDING_SUBACCOUNT_ID for VAT settlement."
            )
        return configured_subaccount_id
    if not configured_subaccount_id:
        missing_fields = [
            label
            for label, value in {
                "bank_name": account["bank_name"],
                "bank_code": account["bank_code"],
                "account_number": account["account_number"],
                "business_mobile": getattr(settings, "RENTDIRECT_VAT_HOLDING_BUSINESS_MOBILE", ""),
            }.items()
            if not str(value or "").strip()
        ]
        if missing_fields:
            raise FlutterwaveError(
                "RentDirect VAT holding payout account is not configured: "
                + ", ".join(missing_fields)
            )
        configured_subaccount_id = get_or_create_collection_subaccount_id(
            bank_code=account["bank_code"],
            account_number=account["account_number"],
            business_name=account["account_name"] or "RentDirect VAT Holding",
            business_email=getattr(settings, "RENTDIRECT_VAT_HOLDING_BUSINESS_EMAIL", ""),
            business_mobile=getattr(settings, "RENTDIRECT_VAT_HOLDING_BUSINESS_MOBILE", ""),
            country=getattr(settings, "RENTDIRECT_VAT_HOLDING_SUBACCOUNT_COUNTRY", "NG"),
            split_type="flat",
            split_value="0",
        )
    return configured_subaccount_id


def subscription_split_ratios(payment: SubscriptionPayment) -> tuple[int, int]:
    fee_minor_units = max(int((payment.amount * MONEY_MINOR_UNIT_FACTOR).to_integral_value(rounding=ROUND_HALF_UP)), 1)
    vat_minor_units = max(int((payment.vat_amount * 100).to_integral_value(rounding=ROUND_HALF_UP)), 1)
    divisor = math.gcd(fee_minor_units, vat_minor_units)
    return fee_minor_units // divisor, vat_minor_units // divisor


def build_subscription_subaccount_payload(payment: SubscriptionPayment) -> tuple[list[dict], dict]:
    apply_subscription_vat(payment)
    subscription_account = resolve_subscription_payment_account()
    vat_account = resolve_vat_payment_account()
    subscription_subaccount_id = resolve_subscription_subaccount_id(subscription_account)
    vat_subaccount_id = resolve_vat_subaccount_id(vat_account)
    if should_use_v4() and (not subscription_subaccount_id or not vat_subaccount_id):
        return [], {
            "subscription": {
                **subscription_account,
                "subaccount_id": "",
                "direct_settlement": False,
            },
            "vat": {
                **vat_account,
                "subaccount_id": "",
                "vat_rate": str(payment.vat_rate),
                "vat_amount": str(payment.vat_amount),
                "direct_settlement": False,
            },
        }
    subscription_ratio, vat_ratio = subscription_split_ratios(payment)

    transaction_charge_type = str(
        getattr(settings, "RENTDIRECT_OPERATING_TRANSACTION_CHARGE_TYPE", "flat") or "flat"
    ).strip() or "flat"
    transaction_charge = decimal_setting("RENTDIRECT_OPERATING_TRANSACTION_CHARGE", "0")
    subaccounts = [
        {
            "id": subscription_subaccount_id,
            "transaction_split_ratio": subscription_ratio,
            "transaction_charge_type": transaction_charge_type,
            "transaction_charge": json_decimal(transaction_charge),
        },
        {
            "id": vat_subaccount_id,
            "transaction_split_ratio": vat_ratio,
            "transaction_charge_type": "flat",
            "transaction_charge": 0,
        },
    ]
    destinations = {
        "subscription": {
            **subscription_account,
            "subaccount_id": subscription_subaccount_id,
            "transaction_split_ratio": subscription_ratio,
            "transaction_charge_type": transaction_charge_type,
            "transaction_charge": str(transaction_charge),
            "direct_settlement": True,
        },
        "vat": {
            **vat_account,
            "subaccount_id": vat_subaccount_id,
            "transaction_split_ratio": vat_ratio,
            "vat_rate": str(payment.vat_rate),
            "vat_amount": str(payment.vat_amount),
            "direct_settlement": True,
        },
    }
    return subaccounts, destinations


def build_subscription_checkout(payment: SubscriptionPayment, *, subaccounts: list[dict] | None = None) -> dict:
    if subaccounts is None:
        subaccounts, _destinations = build_subscription_subaccount_payload(payment)
    return build_checkout_payload(
        reference=payment.transaction_id or build_subscription_payment_reference(),
        amount=payment.total_amount,
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
            "payment_purpose": "subscription",
            "subscription_subaccount_id": subaccounts[0]["id"],
            "vat_subaccount_id": subaccounts[1]["id"],
            "subscription_fee_amount": str(payment.amount),
            "vat_rate": str(payment.vat_rate),
            "vat_amount": str(payment.vat_amount),
        },
        customer_name=payment.user.name,
        customer_phone=payment.user.mobile,
        webhook_url=build_flutterwave_webhook_url(),
        subaccounts=subaccounts,
    )


def build_v4_subscription_charge(payment: SubscriptionPayment, payment_method: dict) -> tuple[dict, dict]:
    if not should_use_v4():
        raise FlutterwaveError("Flutterwave v4 checkout is not enabled.")
    if not isinstance(payment_method, dict):
        raise ValidationError({"payment_method": "A payment method is required for Flutterwave v4 checkout."})

    method_type = str(payment_method.get("type") or "").strip().lower()
    if method_type not in {"card", "bank_account", "bank_transfer", "ussd", "opay"}:
        raise ValidationError({"payment_method": "Unsupported Flutterwave v4 payment method."})

    customer_response = create_customer(
        email=payment.user.email,
        full_name=payment.user.name,
        phone_number=payment.user.mobile,
        metadata={
            "user_id": str(payment.user_id),
            "role": payment.role,
            "purpose": "subscription_checkout",
        },
        idempotency_key=f"sub-v4-customer-{payment.user_id}",
    )
    customer_id = extract_resource_id(customer_response)
    if not customer_id:
        raise FlutterwaveError("Flutterwave did not return a customer id for this payment.")

    if method_type == "bank_transfer":
        virtual_account_response = create_dynamic_virtual_account(
            reference=payment.transaction_id or build_subscription_payment_reference(),
            customer_id=customer_id,
            amount=payment.total_amount,
            currency=payment.currency,
            expiry_seconds=settings.FLUTTERWAVE_VIRTUAL_ACCOUNT_EXPIRY_SECONDS,
            narration=str(getattr(settings, "RENTDIRECT_OPERATING_ACCOUNT_NAME", "") or "RentDirect"),
            bvn=str(getattr(payment.user, "bvn_number", "") or "").strip(),
            nin=str(getattr(payment.user, "nin_number", "") or "").strip(),
            metadata={
                "subscription_payment_id": str(payment.id),
                "payment_purpose": "subscription",
            },
            idempotency_key=f"sub-v4-bank-transfer-{payment.id}",
        )
        account_details = extract_virtual_account_details(virtual_account_response)
        if not account_details["account_number"]:
            raise FlutterwaveError("Flutterwave did not return a virtual account for this payment.")
        if account_details["status"] and account_details["status"] != "active":
            raise FlutterwaveError("Flutterwave virtual account is not active yet. Please try again.")
        charge_payload = {
            "status": "success",
            "data": {
                "id": account_details["id"] or payment.transaction_id,
                "reference": payment.transaction_id,
                "tx_ref": payment.transaction_id,
                "status": "pending",
                "amount": str(payment.total_amount),
                "currency": payment.currency,
                "customer": {"email": payment.user.email},
                "payment_type": "bank_transfer",
                "next_action": {
                    "type": "requires_bank_transfer",
                    "requires_bank_transfer": {
                        "account_number": account_details["account_number"],
                        "account_bank_name": account_details["bank_name"],
                        "account_name": account_details["account_name"] or str(getattr(settings, "RENTDIRECT_OPERATING_ACCOUNT_NAME", "") or "RentDirect"),
                        "account_type": account_details["account_type"] or "dynamic",
                        "account_expiration_datetime": account_details["account_expiration_datetime"] or (
                            timezone.now() + timedelta(seconds=settings.FLUTTERWAVE_VIRTUAL_ACCOUNT_EXPIRY_SECONDS)
                        ).isoformat(),
                        "amount": str(payment.total_amount),
                        "currency": payment.currency,
                        "note": account_details["note"],
                    },
                },
            },
        }
        payment.provider_payload = update_payment_provider_payload(
            payment.provider_payload,
            charge_payload,
            api_version="v4",
            payment_method_type=method_type,
            virtual_account=account_details,
        )
        payment.provider = "flutterwave"
        payment.save(update_fields=["provider_payload", "provider", "updated_at"])
        return charge_payload, {}

    if method_type == "card":
        card = payment_method.get("card")
        if not isinstance(card, dict):
            raise ValidationError({"payment_method": {"card": "Encrypted card details are required."}})
        payment_method_response = create_card_payment_method(
            customer_id=customer_id,
            encrypted_card=card,
            metadata={"payment_id": str(payment.id), "purpose": "subscription_checkout"},
            idempotency_key=f"sub-v4-card-{payment.id}",
        )
    else:
        method_payload: dict[str, Any] = {"type": method_type}
        if method_type == "bank_account":
            method_payload["bank_account"] = {}
        elif method_type == "opay":
            method_payload["opay"] = {}
        elif method_type == "ussd":
            ussd_details = payment_method.get("ussd") if isinstance(payment_method.get("ussd"), dict) else {}
            account_bank = str(ussd_details.get("account_bank") or "").strip()
            if not account_bank:
                raise ValidationError({"payment_method": {"ussd": "Select your bank to continue."}})
            method_payload["ussd"] = {"account_bank": account_bank}
        payment_method_response = create_payment_method(
            customer_id=customer_id,
            payment_method=method_payload,
            metadata={"payment_id": str(payment.id), "purpose": "subscription_checkout"},
            idempotency_key=f"sub-v4-method-{method_type}-{payment.id}",
        )

    payment_method_id = extract_resource_id(payment_method_response)
    if not payment_method_id:
        raise FlutterwaveError("Flutterwave did not return a payment method id for this payment.")

    subaccounts, destinations = build_subscription_subaccount_payload(payment)
    charge_payload = create_charge(
        reference=payment.transaction_id or build_subscription_payment_reference(),
        amount=payment.total_amount,
        currency=payment.currency,
        customer_id=customer_id,
        payment_method_id=payment_method_id,
        redirect_url=build_subscription_payment_return_url(payment),
        metadata={
            "subscription_payment_id": str(payment.id),
            "user_id": str(payment.user_id),
            "customer_type": payment.role,
            "plan_code": payment.plan_code,
            "billing_cycle": payment.billing_cycle,
            "payment_purpose": "subscription",
            "subscription_fee_amount": str(payment.amount),
            "vat_rate": str(payment.vat_rate),
            "vat_amount": str(payment.vat_amount),
        },
        subaccounts=subaccounts,
        idempotency_key=f"{payment.transaction_id}-v4-charge",
    )
    payment.provider_charge_id = extract_provider_transaction_id(charge_payload) or payment.provider_charge_id
    payment.provider_payload = update_payment_provider_payload(
        payment.provider_payload,
        charge_payload,
        api_version="v4",
        payment_method_type=method_type,
        subscription_destination=destinations["subscription"],
        vat_destination=destinations["vat"],
    )
    payment.provider = "flutterwave"
    payment.save(update_fields=["provider_charge_id", "provider_payload", "provider", "updated_at"])
    return charge_payload, destinations


def subscription_duration_days(billing_cycle: str) -> int:
    return 30 if billing_cycle == SubscriptionPayment.BillingCycle.MONTHLY else 365


def user_account_freeze_active(user: AppUser, role: str | None = None, *, now=None) -> bool:
    now = now or timezone.now()
    membership = active_role_membership(user, role)
    if membership is not None:
        return bool(
            membership.account_frozen
            and (not membership.account_frozen_until or membership.account_frozen_until > now)
        )
    return bool(
        getattr(user, "account_frozen", False)
        and (not user.account_frozen_until or user.account_frozen_until > now)
    )


def subscription_renewal_amount_for(payment: SubscriptionPayment, *, now=None) -> Decimal:
    if not user_account_freeze_active(payment.user, payment.role, now=now):
        return payment.amount

    monthly_amount = get_subscription_pricing().get(payment.role, {}).get(payment.plan_code, {}).get(
        SubscriptionPayment.BillingCycle.MONTHLY,
        payment.amount,
    )
    membership = active_role_membership(payment.user, payment.role)
    fee_source = membership if membership is not None else payment.user
    percentage = Decimal(str(fee_source.account_freeze_fee_percentage or ACCOUNT_FREEZE_FEE_PERCENTAGE))
    return (Decimal(str(monthly_amount)) * percentage / PERCENT_DENOMINATOR).quantize(MONEY_PRECISION)


def ensure_flutterwave_recurring_configured() -> None:
    ensure_flutterwave_recurring_charge_configured()
    if not flutterwave_encryption_key_is_configured():
        raise ValidationError("Flutterwave card encryption is not configured on the server.")
    if not subscription_direct_settlement_configured():
        raise ValidationError("RentDirect operating and VAT holding payout accounts are not configured.")


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


def charge_subscription_with_payment_method(payment: SubscriptionPayment, *, source: str, use_recurring_flow: bool = True) -> SubscriptionPayment:
    if not payment.payment_method:
        raise ValidationError("A saved card is required for recurring subscription charges.")
    ensure_flutterwave_recurring_charge_configured()
    if not payment.transaction_id:
        payment.transaction_id = build_subscription_payment_reference()
        payment.save(update_fields=["transaction_id", "updated_at"])

    payment_method = payment.payment_method
    subaccounts, destinations = build_subscription_subaccount_payload(payment)
    charge_payload = create_charge(
        reference=payment.transaction_id,
        amount=payment.total_amount,
        currency=payment.currency,
        customer_id=payment_method.provider_customer_id,
        payment_method_id=payment_method.provider_payment_method_id,
        redirect_url=build_subscription_payment_return_url(payment),
        recurring=use_recurring_flow,
        metadata={
            "subscription_payment_id": str(payment.id),
            "user_id": str(payment.user_id),
            "customer_type": payment.role,
            "plan_code": payment.plan_code,
            "billing_cycle": payment.billing_cycle,
            "billing_reason": payment.billing_reason,
            "payment_purpose": "subscription",
            "subscription_subaccount_id": subaccounts[0]["id"],
            "vat_subaccount_id": subaccounts[1]["id"],
            "subscription_fee_amount": str(payment.amount),
            "vat_rate": str(payment.vat_rate),
            "vat_amount": str(payment.vat_amount),
        },
        subaccounts=subaccounts,
        idempotency_key=f"{payment.transaction_id}-recurring-charge",
    )
    payment.provider_charge_id = extract_provider_transaction_id(charge_payload)
    payment.provider_payload = update_payment_provider_payload(
        payment.provider_payload,
        charge_payload,
        subscription_destination=destinations["subscription"],
        vat_destination=destinations["vat"],
        recurring={
            "source": source,
            "charged_at": timezone.now().isoformat(),
            "gateway_recurring": use_recurring_flow,
        },
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
        account_frozen = user_account_freeze_active(payment.user, payment.role, now=now)
        renewal_billing_cycle = SubscriptionPayment.BillingCycle.MONTHLY if account_frozen else payment.billing_cycle
        renewal_amount = subscription_renewal_amount_for(payment, now=now)
        renewal_vat_amount = calculate_subscription_vat(renewal_amount)
        renewal = SubscriptionPayment.objects.create(
            user=payment.user,
            role=payment.role,
            plan_code=payment.plan_code,
            billing_cycle=renewal_billing_cycle,
            amount=renewal_amount,
            vat_rate=subscription_vat_rate(),
            vat_amount=renewal_vat_amount,
            currency=payment.currency,
            provider="flutterwave",
            status=SubscriptionPayment.Status.PENDING,
            transaction_id=build_subscription_payment_reference(),
            expires_at=payment.expires_at + timedelta(days=subscription_duration_days(renewal_billing_cycle)),
            payment_method=payment.payment_method,
            recurring_enabled=True,
            billing_reason="account_freeze_renewal" if account_frozen else "recurring_renewal",
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
    bank_code = resolve_nigerian_payout_bank_code(bank_name, bank_code)
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
    cumulative_paid = ZERO_AMOUNT

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
    valid_initial_deposit = paid_amount == ZERO_AMOUNT and normalized_amount == deposit_amount
    valid_full_balance = normalized_amount == remaining_balance
    if not (valid_initial_deposit or valid_full_balance):
        raise ValidationError(
            {
                "amount": (
                    "Payment must be either the required deposit "
                    f"({deposit_amount}) or the full remaining balance ({remaining_balance})."
                )
            }
        )

    if payment_method == "card" and booking_payments_card_limit_exceeded(normalized_amount):
        raise ValidationError(
            {
                "payment_method": (
                    f"Flutterwave card payments are limited to NGN {CARD_PAYMENT_LIMIT_NGN:,.0f} per transaction. "
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
            "target_amount": calculate_administration_fee(annual_rent),
            **resolve_account_payload(
                bank_name=settings.RENTDIRECT_OPERATING_BANK_NAME,
                bank_code=settings.RENTDIRECT_OPERATING_BANK_CODE,
                account_number=settings.RENTDIRECT_OPERATING_ACCOUNT_NUMBER,
                account_name=settings.RENTDIRECT_OPERATING_ACCOUNT_NAME,
            ),
        },
        {
            "purpose": PaymentSettlement.Purpose.ADMINISTRATION_FEE_VAT,
            "target_amount": calculate_administration_fee_vat(annual_rent),
            **resolve_account_payload(
                bank_name=settings.RENTDIRECT_VAT_HOLDING_BANK_NAME,
                bank_code=settings.RENTDIRECT_VAT_HOLDING_BANK_CODE,
                account_number=settings.RENTDIRECT_VAT_HOLDING_ACCOUNT_NUMBER,
                account_name=settings.RENTDIRECT_VAT_HOLDING_ACCOUNT_NAME,
            ),
        },
        {
            "purpose": PaymentSettlement.Purpose.CAUTION_FEE,
            "target_amount": calculate_refundable_caution_fee(annual_rent),
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
        ).exclude(payment=payment).aggregate(total=Sum("amount"))["total"] or ZERO_AMOUNT
        amount = normalize_decimal_amount(max(spec["target_amount"] - normalize_decimal_amount(already_paid), ZERO_AMOUNT))
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


def booking_key_collection_confirmed_by_tenant(booking: Booking) -> bool:
    tenant_progress = booking.tenant_rental_progress if isinstance(booking.tenant_rental_progress, dict) else {}
    return booking_progress_step_completed(tenant_progress, "tenant_collected_house_key")


def booking_key_collection_confirmed_by_landlord(booking: Booking) -> bool:
    landlord_progress = booking.landlord_rental_progress if isinstance(booking.landlord_rental_progress, dict) else {}
    return booking_progress_step_completed(landlord_progress, "tenant_collected_house_key")


def booking_key_collection_confirmed_by_both_parties(booking: Booking) -> bool:
    return booking_key_collection_confirmed_by_tenant(booking) and booking_key_collection_confirmed_by_landlord(booking)


def booking_payout_balance_available(booking: Booking, now=None) -> bool:
    _completion_payment, paid_at = get_booking_full_payment_completion(booking)
    if not paid_at:
        return False
    payout_balance_delay = timedelta(
        minutes=max(int(getattr(settings, "FLUTTERWAVE_PAYOUT_BALANCE_DELAY_MINUTES", 24 * 60)), 0)
    )
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


def extract_settlement_failure_reason(payload: dict | None, fallback: str = "Flutterwave transfer failed.") -> str:
    if not isinstance(payload, dict):
        return fallback

    data = extract_provider_data(payload)
    containers = [data, payload]
    for container in containers:
        if not isinstance(container, dict):
            continue
        for key in (
            "failure_reason",
            "failed_reason",
            "reason",
            "processor_response",
            "gateway_response",
            "complete_message",
            "message",
            "detail",
            "description",
        ):
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        error = container.get("error")
        if isinstance(error, str) and error.strip():
            return error.strip()
        if isinstance(error, dict):
            for key in ("message", "detail", "reason"):
                value = error.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

    status_value = str(data.get("status") or payload.get("status") or "").strip()
    if status_value:
        return f"{fallback.rstrip('.')} with provider status: {status_value}."
    return fallback


def sync_payment_settlement_transfer(settlement: PaymentSettlement, payload: dict | None) -> PaymentSettlement:
    next_status = map_transfer_status_to_settlement_status(payload)
    settlement.transfer_payload = payload
    settlement.last_error = "" if next_status != PaymentSettlement.Status.FAILED else extract_settlement_failure_reason(payload)
    settlement.status = next_status
    update_fields = ["transfer_payload", "last_error", "status", "updated_at"]
    if next_status == PaymentSettlement.Status.PAID and settlement.transferred_at is None:
        settlement.transferred_at = timezone.now()
        update_fields.append("transferred_at")
    settlement.save(update_fields=update_fields)
    if next_status == PaymentSettlement.Status.FAILED:
        logger.error(
            "Payment settlement transfer failed from webhook. settlement_id=%s payment_id=%s purpose=%s reference=%s reason=%s payload=%s",
            settlement.id,
            settlement.payment_id,
            settlement.purpose,
            settlement.transfer_reference or "-",
            settlement.last_error,
            payload,
        )
    return settlement


def reconcile_processing_payment_settlements(payment: Payment | None = None) -> int:
    settlements = (
        PaymentSettlement.objects
        .filter(status=PaymentSettlement.Status.PROCESSING)
        .exclude(transfer_reference="")
        .select_related("payment")
        .order_by("updated_at")
    )
    if payment is not None:
        settlements = settlements.filter(payment_id=payment.pk)

    reconciled_count = 0
    for settlement in settlements:
        transfer_id = extract_resource_id(settlement.transfer_payload)
        if not transfer_id:
            logger.warning(
                "Payment settlement status reconciliation skipped because provider transfer id is missing. settlement_id=%s reference=%s",
                settlement.id,
                settlement.transfer_reference,
            )
            continue

        try:
            transfer_payload = retrieve_bank_transfer(transfer_id=transfer_id)
        except FlutterwaveError as exc:
            logger.warning(
                "Payment settlement status reconciliation failed. settlement_id=%s reference=%s transfer_id=%s reason=%s",
                settlement.id,
                settlement.transfer_reference,
                transfer_id,
                exc,
            )
            continue

        sync_payment_settlement_transfer(settlement, transfer_payload)
        reconciled_count += 1

    return reconciled_count


def calculate_tenant_refund_fee(amount: Decimal) -> Decimal:
    fee = (normalize_decimal_amount(amount) * TENANT_REFUND_FEE_RATE).quantize(MONEY_PRECISION, rounding=ROUND_HALF_UP)
    return min(fee, TENANT_REFUND_FEE_CAP_NGN)


def resolve_payment_refund_bank(payment: Payment) -> str:
    bank_name = str(payment.bank_name or "").strip()
    if bank_name:
        return bank_name
    for payload in (payment.provider_payload, payment.webhook_data):
        extracted_bank, _card_last4 = extract_payment_channel_details(payload)
        if extracted_bank:
            return extracted_bank
    return ""


def map_transfer_status_to_refund_status(payload: dict | None) -> str:
    provider_state = extract_payment_state(payload)
    if provider_state == "completed":
        return TenantRefund.Status.PAID
    if provider_state in {"failed", "cancelled"}:
        return TenantRefund.Status.FAILED
    return TenantRefund.Status.PROCESSING


def sync_tenant_refund_transfer(refund: TenantRefund, payload: dict | None) -> TenantRefund:
    next_status = map_transfer_status_to_refund_status(payload)
    refund.transfer_payload = payload
    refund.last_error = "" if next_status != TenantRefund.Status.FAILED else extract_settlement_failure_reason(payload, "Flutterwave refund transfer failed.")
    refund.status = next_status
    update_fields = ["transfer_payload", "last_error", "status", "updated_at"]
    if next_status == TenantRefund.Status.PAID and refund.transferred_at is None:
        refund.transferred_at = timezone.now()
        update_fields.append("transferred_at")
    refund.save(update_fields=update_fields)
    if next_status == TenantRefund.Status.FAILED:
        logger.error(
            "Tenant refund transfer failed from webhook. refund_id=%s payment_id=%s reference=%s reason=%s payload=%s",
            refund.id,
            refund.payment_id,
            refund.transfer_reference or "-",
            refund.last_error,
            payload,
        )
    return refund


def build_refund_transfer_reference(payment: Payment, refund: TenantRefund) -> str:
    base_reference = payment.transaction_id or str(payment.id)
    return f"{base_reference}-TREFUND-{str(refund.id)[:8].upper()}"[:120]


def process_due_tenant_refunds(now=None) -> int:
    now = now or timezone.now()

    # Reconcile refunds that already have a transfer in flight.
    for refund in (
        TenantRefund.objects
        .filter(status=TenantRefund.Status.PROCESSING)
        .exclude(transfer_reference="")
        .order_by("updated_at")
    ):
        transfer_id = extract_resource_id(refund.transfer_payload)
        if not transfer_id:
            continue
        try:
            sync_tenant_refund_transfer(refund, retrieve_bank_transfer(transfer_id=transfer_id))
        except FlutterwaveError as exc:
            logger.warning(
                "Tenant refund reconciliation failed. refund_id=%s reference=%s reason=%s",
                refund.id,
                refund.transfer_reference,
                exc,
            )

    due_refunds = (
        TenantRefund.objects
        .select_related("payment", "booking", "tenant")
        .filter(status=TenantRefund.Status.SCHEDULED, process_at__lte=now)
        .order_by("process_at")
    )

    processed = 0
    for refund in due_refunds:
        if not should_use_v4():
            refund.status = TenantRefund.Status.READY
            refund.last_error = ""
            refund.save(update_fields=["status", "last_error", "updated_at"])
            continue

        if not refund.transfer_recipient_id:
            recipient_response = None
            recipient_lookup_error = None
            try:
                recipient_response = find_transfer_recipient(
                    account_number=refund.account_number,
                    bank_name=refund.bank_name,
                    bank_code=refund.bank_code,
                )
            except FlutterwaveError as exc:
                recipient_lookup_error = exc

            if recipient_response is None and recipient_lookup_error is None:
                try:
                    recipient_response = create_transfer_recipient(
                        full_name=refund.account_name or refund.tenant.name or "Tenant Refund",
                        phone_number=refund.tenant.mobile,
                        bank_name=refund.bank_name,
                        bank_code=refund.bank_code,
                        account_number=refund.account_number,
                        account_name=refund.account_name,
                        idempotency_key=f"{refund.payment.transaction_id}-refund-recipient",
                    )
                except FlutterwaveError as exc:
                    if "recipient already exists" not in str(exc).lower():
                        recipient_lookup_error = exc

            if recipient_lookup_error is not None:
                refund.status = TenantRefund.Status.SCHEDULED
                refund.last_error = str(recipient_lookup_error)
                refund.save(update_fields=["status", "last_error", "updated_at"])
                logger.error(
                    "Tenant refund recipient lookup/creation failed. refund_id=%s payment_id=%s reason=%s",
                    refund.id,
                    refund.payment_id,
                    refund.last_error,
                )
                continue

            if recipient_response is not None:
                refund.transfer_recipient_id = extract_resource_id(recipient_response)
                refund.provider_payload = recipient_response
                refund.status = TenantRefund.Status.READY if refund.transfer_recipient_id else TenantRefund.Status.SCHEDULED
                refund.last_error = "" if refund.transfer_recipient_id else "Flutterwave did not return a transfer recipient id."
                refund.save(update_fields=["transfer_recipient_id", "provider_payload", "status", "last_error", "updated_at"])
                if not refund.transfer_recipient_id:
                    continue

        transfer_reference = refund.transfer_reference or build_refund_transfer_reference(refund.payment, refund)
        try:
            transfer_response = create_bank_transfer(
                amount=refund.refund_amount,
                currency=refund.currency,
                reference=transfer_reference,
                narration="RentDirect Tenant Refund",
                recipient_id=refund.transfer_recipient_id,
                bank_name=refund.bank_name,
                bank_code=refund.bank_code,
                account_number=refund.account_number,
                account_name=refund.account_name,
                idempotency_key=transfer_reference,
            )
        except FlutterwaveError as exc:
            refund.status = TenantRefund.Status.READY
            refund.transfer_reference = transfer_reference
            refund.last_error = str(exc)
            refund.save(update_fields=["status", "transfer_reference", "last_error", "updated_at"])
            logger.exception(
                "Tenant refund transfer request failed. refund_id=%s payment_id=%s reference=%s reason=%s",
                refund.id,
                refund.payment_id,
                transfer_reference,
                refund.last_error,
            )
            continue

        refund.transfer_reference = transfer_reference
        sync_tenant_refund_transfer(refund, transfer_response)
        processed += 1

    return processed


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
            destination_changed = any(
                str(getattr(settlement, field) or "") != str(defaults[field] or "")
                for field in ("bank_name", "bank_code", "account_number", "account_name")
            )
            if destination_changed:
                defaults.update(
                    {
                        "transfer_recipient_id": "",
                        "provider_payload": None,
                        "transfer_payload": None,
                        "status": PaymentSettlement.Status.PENDING,
                        "last_error": "",
                    }
                )
            PaymentSettlement.objects.filter(pk=settlement.pk).update(**defaults, updated_at=timezone.now())


logger = logging.getLogger(__name__)


def _settlement_recipient_already_exists(settlement: PaymentSettlement) -> bool:
    provider_payload = settlement.provider_payload
    if not isinstance(provider_payload, dict):
        return False
    recipient_resolution = provider_payload.get("recipient_resolution")
    return (
        isinstance(recipient_resolution, dict)
        and recipient_resolution.get("status") == "already_exists"
    )


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
        if not should_use_v4():
            settlement.status = PaymentSettlement.Status.READY
            settlement.last_error = ""
            settlement.save(update_fields=["status", "last_error", "updated_at"])
        elif settlement.transfer_recipient_id:
            if settlement.status == PaymentSettlement.Status.RECIPIENT_CREATED:
                settlement.status = PaymentSettlement.Status.READY
                settlement.save(update_fields=["status", "updated_at"])
        else:
            recipient_response = None
            recipient_lookup_error = None
            try:
                recipient_response = find_transfer_recipient(
                    account_number=settlement.account_number,
                    bank_name=settlement.bank_name,
                    bank_code=settlement.bank_code,
                )
            except FlutterwaveError as exc:
                recipient_lookup_error = exc

            if recipient_response is None and recipient_lookup_error is None and not _settlement_recipient_already_exists(settlement):
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
                    if "recipient already exists" not in str(exc).lower():
                        recipient_lookup_error = exc
                    else:
                        provider_payload = (
                            dict(settlement.provider_payload)
                            if isinstance(settlement.provider_payload, dict)
                            else {}
                        )
                        provider_payload["recipient_resolution"] = {
                            "status": "already_exists",
                            "account_number": settlement.account_number,
                            "bank_code": settlement.bank_code,
                        }
                        settlement.provider_payload = provider_payload
                        settlement.status = PaymentSettlement.Status.READY
                        settlement.last_error = ""
                        settlement.save(update_fields=["provider_payload", "status", "last_error", "updated_at"])

            if recipient_lookup_error is not None and not _settlement_recipient_already_exists(settlement):
                settlement.status = PaymentSettlement.Status.FAILED
                settlement.last_error = str(recipient_lookup_error)
                settlement.save(update_fields=["status", "last_error", "updated_at"])
                logger.error(
                    "Payment settlement recipient lookup/creation failed. settlement_id=%s payment_id=%s booking_id=%s purpose=%s bank_name=%s account_number=%s reason=%s",
                    settlement.id,
                    payment.id,
                    payment.booking_id,
                    settlement.purpose,
                    settlement.bank_name,
                    settlement.account_number,
                    settlement.last_error,
                )
                continue

            if recipient_response is not None:
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
                    logger.error(
                        "Payment settlement recipient creation returned no recipient id. settlement_id=%s payment_id=%s booking_id=%s purpose=%s bank_name=%s account_number=%s reason=%s payload=%s",
                        settlement.id,
                        payment.id,
                        payment.booking_id,
                        settlement.purpose,
                        settlement.bank_name,
                        settlement.account_number,
                        settlement.last_error,
                        recipient_response,
                    )
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
            logger.exception(
                "Payment settlement transfer request failed. settlement_id=%s payment_id=%s booking_id=%s purpose=%s reference=%s bank_name=%s account_number=%s reason=%s",
                settlement.id,
                payment.id,
                payment.booking_id,
                settlement.purpose,
                transfer_reference,
                settlement.bank_name,
                settlement.account_number,
                settlement.last_error,
            )
            continue

        settlement.transfer_reference = transfer_reference
        settlement.transfer_payload = transfer_response
        settlement.status = map_transfer_status_to_settlement_status(transfer_response)
        settlement.last_error = (
            extract_settlement_failure_reason(transfer_response)
            if settlement.status == PaymentSettlement.Status.FAILED
            else ""
        )
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
        if settlement.status == PaymentSettlement.Status.FAILED:
            logger.error(
                "Payment settlement transfer failed. settlement_id=%s payment_id=%s booking_id=%s purpose=%s reference=%s bank_name=%s account_number=%s reason=%s payload=%s",
                settlement.id,
                payment.id,
                payment.booking_id,
                settlement.purpose,
                transfer_reference,
                settlement.bank_name,
                settlement.account_number,
                settlement.last_error,
                transfer_response,
            )

        # Send settlement notification emails after successful recipient creation
        try:
            booking = payment.booking
            listing = booking.listing
            landlord = listing.landlord
            tenant = booking.tenant

            if (
                settlement.purpose == PaymentSettlement.Purpose.LANDLORD_RENT
                and settlement.status != PaymentSettlement.Status.FAILED
            ):
                # Email #2: Notify landlord of payout, CC tenant and RentDirect
                send_landlord_payout_notification(
                    landlord_email=landlord.email,
                    landlord_name=landlord.name,
                    tenant_name=tenant.name,
                    tenant_email=tenant.email,
                    listing_title=listing.title,
                    rental_amount=listing.price_per_year,
                    bank_name=settlement.bank_name,
                    account_name=settlement.account_name,
                    account_number=settlement.account_number,
                    settlement_id=str(settlement.id),
                    landlord_whatsapp_number=landlord.whatsapp_number,
                )
                complete_booking_progress_step(
                    booking,
                    AppUser.Role.TENANT,
                    "final_rent_payment_email_received",
                )
            elif settlement.purpose in (
                PaymentSettlement.Purpose.OPERATIONS,
                PaymentSettlement.Purpose.ADMINISTRATION_FEE_VAT,
                PaymentSettlement.Purpose.CAUTION_FEE,
            ):
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


def enqueue_booking_payout_check_safely(booking_id) -> None:
    try:
        enqueue_booking_payout_check(booking_id)
    except Exception:
        logger.exception("Failed to enqueue payout check for booking %s", booking_id)


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
        previous_paid_amount = normalize_decimal_amount(booking.paid_amount)
        remaining_balance = calculate_remaining_balance(total_amount, previous_paid_amount)
        if Decimal(payment.amount) > remaining_balance:
            payment.status = "failed"
            payment.provider_payload = update_payment_provider_payload(
                payment.provider_payload,
                None,
                verification_error="amount_exceeds_remaining_balance",
            )
            payment.save(update_fields=["status", "provider_payload", "updated_at"])
            return payment

        payment_completed_at = timezone.now()
        booking.total_amount = total_amount
        booking.paid_amount = previous_paid_amount + payment.amount
        if (
            booking.deposit_paid_at is None
            and previous_paid_amount < calculate_deposit_amount(booking.listing.price_per_year)
            and booking.paid_amount >= calculate_deposit_amount(booking.listing.price_per_year)
        ):
            booking.deposit_paid_at = payment_completed_at
        if booking.full_rent_paid_at is None and previous_paid_amount < total_amount and booking.paid_amount >= total_amount:
            booking.full_rent_paid_at = payment_completed_at
        booking.status = (
            Booking.Status.CONFIRMED
            if calculate_remaining_balance(total_amount, booking.paid_amount) <= 0
            else Booking.Status.PENDING
        )

        payment.status = "completed"
        payment.payment_date = payment_completed_at
        payment.save(update_fields=["status", "payment_date", "updated_at"])
        booking.save(
            update_fields=[
                "total_amount",
                "paid_amount",
                "deposit_paid_at",
                "full_rent_paid_at",
                "status",
                "updated_at",
            ]
        )

        # Email #1: Notify landlord of successful tenant payment, CC tenant and RentDirect
        try:
            send_payment_confirmation_to_landlord(
                landlord_email=payment.booking.listing.landlord.email,
                landlord_name=payment.booking.listing.landlord.name,
                tenant_name=payment.booking.tenant.name,
                tenant_email=payment.booking.tenant.email,
                listing_title=payment.booking.listing.title,
                rental_amount=payment.booking.listing.price_per_year,
                transaction_id=payment.transaction_id,
                payment_date=payment.payment_date.strftime("%Y-%m-%d %H:%M:%S"),
                booking_id=str(payment.booking_id),
                landlord_whatsapp_number=payment.booking.listing.landlord.whatsapp_number,
                tenant_whatsapp_number=payment.booking.tenant.whatsapp_number,
            )
        except Exception:
            logger.exception("Failed to send payment confirmation email for payment %s", payment.id)

        transaction.on_commit(lambda: enqueue_booking_payout_check_safely(payment.booking_id))
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
    with transaction.atomic():
        payment.save(update_fields=["status", "payment_date", "expires_at", "webhook_data", "updated_at"])
        if payment.vat_amount > 0:
            SubscriptionVATPayment.objects.get_or_create(
                subscription_payment=payment,
                defaults={
                    "payer": payment.user,
                    "payer_name": payment.user.name or payment.user.email.split("@", 1)[0],
                    "payer_email": payment.user.email,
                    "entity_type": payment.role,
                    "subscription_fee_amount": payment.amount,
                    "amount_paid": payment.total_amount,
                    "vat_rate": payment.vat_rate,
                    "vat_amount": payment.vat_amount,
                    "currency": payment.currency,
                    "transaction_id": payment.transaction_id or str(payment.id),
                    "provider_transaction_id": payment.provider_charge_id,
                    "provider": payment.provider,
                    "paid_at": payment.payment_date,
                },
            )
    return payment


def sync_booking_payment(payment: Payment, *, transaction_id: str | None = None, provider_status: str | None = None, payload=None, source: str) -> Payment:
    redirect_state = map_redirect_status(provider_status)
    if payment.status == REFUND_REQUESTED_PAYMENT_STATUS:
        return payment
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
    if not isinstance(charge_data, dict):
        charge_data = {}
    provider_state = extract_payment_state(charge_payload)
    provider_amount_value = charge_data.get("amount")
    if isinstance(provider_amount_value, dict):
        provider_amount_value = provider_amount_value.get("value")
    actual_reference = extract_reference(charge_payload)
    actual_amount = normalize_decimal_amount(provider_amount_value)
    actual_currency = str(charge_data.get("currency") or "").upper()
    actual_email = extract_customer_email(charge_payload).lower()
    expected_email = payment.user.email.strip().lower()
    verification_errors: list[str] = []
    verification_warnings: list[str] = []

    if actual_reference:
        if actual_reference != (payment.transaction_id or ""):
            verification_errors.append("reference_mismatch")
    elif provider_state == "completed":
        verification_errors.append("reference_missing")
    if provider_amount_value not in (None, ""):
        if actual_amount != normalize_decimal_amount(payment.total_amount):
            verification_errors.append("amount_mismatch")
    elif provider_state == "completed":
        verification_errors.append("amount_missing")
    if actual_currency:
        if actual_currency != payment.currency.upper():
            verification_errors.append("currency_mismatch")
    elif provider_state == "completed":
        verification_errors.append("currency_missing")
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

    next_state = provider_state
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


def complete_service_payment(payment: ServicePayment, *, webhook_data=None) -> ServicePayment:
    payment.status = ServicePayment.Status.COMPLETED
    payment.payment_date = timezone.now()
    if webhook_data is not None:
        payment.webhook_data = webhook_data
    payment.save(update_fields=["status", "payment_date", "webhook_data", "updated_at"])
    if payment.purpose == ServicePayment.Purpose.IN_PERSON_VERIFICATION and payment.listing_id:
        # Paid in-person verification moves the listing into the inspection queue.
        Listing.objects.filter(pk=payment.listing_id).update(
            physical_property_status=VerificationRequest.VerificationProgressStatus.PENDING,
            updated_at=timezone.now(),
        )
        listing = Listing.objects.filter(pk=payment.listing_id).first()
        if listing is not None:
            try:
                notify_agents_for_listing(listing)
            except Exception:
                logger.exception(
                    "Failed to notify PIOs for paid in-person verification on listing %s", listing.id
                )
    return payment


def sync_service_payment(payment: ServicePayment, *, transaction_id: str | None = None, provider_status: str | None = None, payload=None, source: str) -> ServicePayment:
    redirect_state = map_redirect_status(provider_status)
    if payment.status == ServicePayment.Status.COMPLETED:
        return payment
    if payload is None and redirect_state in {ServicePayment.Status.CANCELLED, ServicePayment.Status.FAILED} and not transaction_id:
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
    if not isinstance(charge_data, dict):
        charge_data = {}
    provider_state = extract_payment_state(charge_payload)
    provider_amount_value = charge_data.get("amount")
    if isinstance(provider_amount_value, dict):
        provider_amount_value = provider_amount_value.get("value")
    actual_reference = extract_reference(charge_payload)
    actual_amount = normalize_decimal_amount(provider_amount_value)
    actual_currency = str(charge_data.get("currency") or "").upper()
    actual_email = extract_customer_email(charge_payload).lower()
    expected_email = payment.user.email.strip().lower()
    verification_errors: list[str] = []
    verification_warnings: list[str] = []

    if actual_reference:
        if actual_reference != (payment.transaction_id or ""):
            verification_errors.append("reference_mismatch")
    elif provider_state == "completed":
        verification_errors.append("reference_missing")
    if provider_amount_value not in (None, ""):
        if actual_amount != normalize_decimal_amount(payment.amount):
            verification_errors.append("amount_mismatch")
    elif provider_state == "completed":
        verification_errors.append("amount_missing")
    if actual_currency:
        if actual_currency != payment.currency.upper():
            verification_errors.append("currency_mismatch")
    elif provider_state == "completed":
        verification_errors.append("currency_missing")
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

    next_state = provider_state
    if verification_errors:
        next_state = ServicePayment.Status.FAILED

    if next_state == ServicePayment.Status.COMPLETED:
        payment.save(update_fields=["provider_payload", "provider", "webhook_data", "updated_at"])
        return complete_service_payment(
            payment,
            webhook_data=charge_payload if source == "webhook" else payment.webhook_data,
        )

    payment.status = (
        ServicePayment.Status.CANCELLED
        if next_state == ServicePayment.Status.CANCELLED
        else ServicePayment.Status.FAILED
        if next_state == ServicePayment.Status.FAILED
        else ServicePayment.Status.PENDING
    )
    payment.save(update_fields=["status", "provider_payload", "provider", "webhook_data", "updated_at"])
    return payment


def reconcile_pending_customer_payments(*, limit: int = 100) -> dict[str, int]:
    limit = max(int(limit), 1)
    candidates = list(
        Payment.objects.select_related("booking", "booking__tenant", "booking__listing", "booking__listing__landlord")
        .filter(provider="flutterwave", status__in=["pending", "processing"])
        .order_by("created_at")[:limit]
    )
    candidates.extend(
        FeaturedPayment.objects.select_related("listing", "landlord")
        .filter(provider="flutterwave", status=FeaturedPayment.Status.PENDING)
        .exclude(transaction_id__isnull=True)
        .exclude(transaction_id="")
        .order_by("created_at")[:limit]
    )
    candidates.extend(
        SubscriptionPayment.objects.select_related("user")
        .filter(provider="flutterwave", status=SubscriptionPayment.Status.PENDING)
        .exclude(transaction_id__isnull=True)
        .exclude(transaction_id="")
        .order_by("created_at")[:limit]
    )
    candidates.extend(
        ServicePayment.objects.select_related("user", "booking")
        .filter(provider="flutterwave", status=ServicePayment.Status.PENDING)
        .exclude(transaction_id__isnull=True)
        .exclude(transaction_id="")
        .order_by("created_at")[:limit]
    )
    candidates.sort(key=lambda payment: payment.created_at)

    checked = completed = pending = failed = 0
    for payment in candidates[:limit]:
        checked += 1
        try:
            if isinstance(payment, Payment):
                reconciled = sync_booking_payment(payment, source="reconciliation")
            elif isinstance(payment, FeaturedPayment):
                reconciled = sync_featured_payment(payment, source="reconciliation")
            elif isinstance(payment, ServicePayment):
                reconciled = sync_service_payment(payment, source="reconciliation")
            else:
                reconciled = sync_subscription_payment(payment, source="reconciliation")
        except FlutterwaveError:
            pending += 1
            continue

        if reconciled.status == "completed":
            completed += 1
        elif reconciled.status in FAILED_PAYMENT_STATUSES:
            failed += 1
        else:
            pending += 1

    return {
        "checked": checked,
        "completed": completed,
        "pending": pending,
        "failed": failed,
    }


def ensure_supported_subscription_role(user: AppUser) -> None:
    if user.role not in {AppUser.Role.TENANT, AppUser.Role.LANDLORD}:
        raise PermissionDenied("Subscriptions are available only to tenants and landlords.")


def _activate_role_after_credentials(user, role: str, request=None, referral_code: str = "") -> bool:
    """Activate a customer persona once credentials are verified.

    Password and Google sign-in prove control of the identity, so a requested
    customer role that has no membership yet is activated here instead of
    dead-ending the sign-in. ``activate_customer_role`` still rejects admin
    accounts and suspended memberships. Returns True when a membership was
    newly activated.
    """
    role = str(role or "").strip().lower()
    if role not in CUSTOMER_ROLES or has_active_role(user, role):
        return False
    _membership, activated = activate_customer_role(user, role)
    if not activated:
        return False
    if role == AppUser.Role.AGENT:
        agent_profile, _ = AgentProfile.objects.get_or_create(
            user=user,
            defaults={"first_name": "", "last_name": ""},
        )
        referrer = resolve_referrer(referral_code) if referral_code else None
        if referrer and referrer.id != user.id and agent_profile.referred_by_id is None:
            agent_profile.referred_by = referrer
            agent_profile.save(update_fields=["referred_by", "updated_at"])
    prefill_role_identity(user, role)
    record_role_event(user, role, RoleAuditEvent.Event.ACTIVATED, request)
    return True


@method_decorator(production_ratelimit(key="ip", rate="10/m", method="POST", block=True), name="register")
@method_decorator(production_ratelimit(key="ip", rate="10/m", method="POST", block=True), name="verify_registration")
@method_decorator(production_ratelimit(key="ip", rate="10/m", method="POST", block=True), name="login")
@method_decorator(production_ratelimit(key="ip", rate="10/m", method="POST", block=True), name="google_exchange")
@method_decorator(production_ratelimit(key="ip", rate="30/m", method="POST", block=True), name="refresh")
class AuthViewSet(viewsets.ViewSet):
    permission_classes = [AllowAny]

    @action(detail=False, methods=["post"], url_path="register", authentication_classes=[])
    def register(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        email = data["email"].strip().lower()
        existing = User.objects.filter(email=email).first()
        if existing and existing.email_verified:
            raise ValidationError({"email": "Email already registered. Sign in to add another role."})

        otp = generate_otp()
        expires_at = timezone.now() + timedelta(minutes=OTP_TTL_MINUTES)
        # Sign-up credentials are held on PendingRegistration only; the AppUser
        # record is created after OTP verification succeeds.
        pending = PendingRegistration(
            email=email,
            name=data["name"],
            role=data["role"],
            password_hash=make_password(data["password"]),
            otp_hash=hash_otp(email, otp),
            otp_expires_at=expires_at,
            otp_attempts=0,
            referral_code=data.get("referral_code") or "",
        )
        send_registration_email(pending, otp)
        with transaction.atomic():
            PendingRegistration.objects.filter(email=email).delete()
            pending.save()
        return Response(
            {
                "email": pending.email,
                "role": pending.role,
                "expires_in_seconds": OTP_TTL_MINUTES * 60,
                "message": "Verification code sent to email.",
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=["post"], url_path="register/verify", authentication_classes=[])
    def verify_registration(self, request):
        serializer = VerifyRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].strip().lower()
        code = serializer.validated_data["otp_code"]
        user = User.objects.filter(email=email).first()
        pending = PendingRegistration.objects.filter(email=email).first()

        if pending is None and user is not None and user.registration_otp_hash:
            # In-flight registration created before pending challenges existed.
            return self._verify_legacy_registration(request, user, code)

        if user is not None and user.email_verified:
            return Response({"detail": "Email is already verified"}, status=400)
        if pending is None:
            return Response({"detail": "Registration not found"}, status=404)
        if pending.otp_attempts >= OTP_MAX_ATTEMPTS:
            return Response({"detail": "Too many invalid verification attempts"}, status=429)
        if not pending.otp_expires_at or pending.otp_expires_at < timezone.now():
            return Response({"detail": "Verification code has expired"}, status=400)
        if not otp_matches(pending.otp_hash, email, code):
            pending.otp_attempts += 1
            pending.save(update_fields=["otp_attempts", "updated_at"])
            remaining = max(OTP_MAX_ATTEMPTS - pending.otp_attempts, 0)
            return Response({"detail": f"Invalid verification code. {remaining} attempts remaining."}, status=400)

        with transaction.atomic():
            if user is None:
                user = User(email=email, role=pending.role)
            # An existing (unverified) identity keeps its default role; the
            # pending registration's role is added as a separate membership.
            user.name = pending.name
            user.password = pending.password_hash
            user.email_verified = True
            user.registration_otp_hash = ""
            user.registration_otp_expires_at = None
            user.registration_otp_attempts = 0
            user.save()
            activate_customer_role(user, pending.role)
            if pending.role == AppUser.Role.AGENT:
                agent_profile, _ = AgentProfile.objects.get_or_create(
                    user=user,
                    defaults={"first_name": "", "last_name": ""},
                )
                referrer = resolve_referrer(pending.referral_code)
                if referrer and referrer.id != user.id and agent_profile.referred_by_id is None:
                    agent_profile.referred_by = referrer
                    agent_profile.save(update_fields=["referred_by", "updated_at"])
            pending.delete()

        prefill_role_identity(user, pending.role)
        record_role_event(user, pending.role, RoleAuditEvent.Event.ACTIVATED, request)
        apply_active_role(user, pending.role)
        response = Response(UserSerializer(user, context={"request": request}).data)
        set_auth_cookies(response, user)
        return response

    def _verify_legacy_registration(self, request, user, code):
        email = user.email
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
        if user.role in CUSTOMER_ROLES:
            activate_customer_role(user, user.role)
        response = Response(UserSerializer(user, context={"request": request}).data)
        set_auth_cookies(response, user)
        return response

    @action(detail=False, methods=["post"], url_path="login", authentication_classes=[])
    def login(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        requested_role = str(serializer.validated_data.get("role") or "").strip().lower()
        role_activated = _activate_role_after_credentials(user, requested_role, request)
        apply_active_role(user, requested_role or None)
        payload = UserSerializer(user, context={"request": request}).data
        if role_activated:
            payload["role_activated"] = True
        response = Response(payload)
        set_auth_cookies(response, user)
        return response

    @action(detail=False, methods=["get"], url_path="google/start", authentication_classes=[])
    def google_start(self, request):
        if not settings.GOOGLE_OAUTH_CLIENT_ID:
            return Response({"detail": "Google sign-in is not configured."}, status=503)
        return Response(
            {
                "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
                "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI or "postmessage",
            }
        )

    @action(detail=False, methods=["post"], url_path="google/exchange", authentication_classes=[])
    def google_exchange(self, request):
        if not settings.GOOGLE_OAUTH_CLIENT_ID or not settings.GOOGLE_OAUTH_CLIENT_SECRET:
            return Response({"detail": "Google sign-in is not configured."}, status=503)
        code = str(request.data.get("code") or "").strip()
        if not code:
            raise ValidationError({"code": "Google authorization code is required."})

        allowed_redirect_uris = {"postmessage"}
        if settings.GOOGLE_OAUTH_REDIRECT_URI:
            allowed_redirect_uris.add(settings.GOOGLE_OAUTH_REDIRECT_URI)
        redirect_uri = str(request.data.get("redirect_uri") or "postmessage").strip()
        if redirect_uri not in allowed_redirect_uris:
            raise ValidationError({"redirect_uri": "Unsupported redirect URI."})

        try:
            token_response = requests.post(
                settings.GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
                    "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
                timeout=15,
            )
        except requests.RequestException:
            logger.exception("Google token exchange request failed")
            return Response({"detail": "Google sign-in is temporarily unavailable."}, status=502)
        if token_response.status_code != 200:
            return Response({"detail": "Google authorization failed."}, status=400)

        tokens = token_response.json()
        access_token = tokens.get("access_token")
        if not access_token:
            return Response({"detail": "Google authorization failed."}, status=400)

        try:
            profile_response = requests.get(
                settings.GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=15,
            )
        except requests.RequestException:
            logger.exception("Google userinfo request failed")
            return Response({"detail": "Google sign-in is temporarily unavailable."}, status=502)
        if profile_response.status_code != 200:
            return Response({"detail": "Could not retrieve your Google profile."}, status=400)

        profile = profile_response.json()
        email = str(profile.get("email") or "").strip().lower()
        email_verified = profile.get("email_verified")
        if not email:
            return Response({"detail": "Google did not return an email address."}, status=400)
        if email_verified in (False, "false"):
            return Response({"detail": "Your Google account email is not verified."}, status=400)

        user = User.objects.filter(email=email).first()
        created = False
        role_activated = False
        if user is None:
            requested_role = str(request.data.get("role") or "").strip().lower()
            role = requested_role if requested_role in {
                AppUser.Role.TENANT,
                AppUser.Role.LANDLORD,
                AppUser.Role.AGENT,
            } else AppUser.Role.TENANT
            name = str(profile.get("name") or "").strip() or email.split("@")[0]
            user = User(email=email, name=name, role=role, email_verified=True)
            user.set_unusable_password()
            user.save()
            activate_customer_role(user, role)
            if role == AppUser.Role.AGENT:
                agent_profile = AgentProfile(user=user, first_name="", last_name="")
                referrer = resolve_referrer(str(request.data.get("referral_code") or ""))
                if referrer and referrer.id != user.id:
                    agent_profile.referred_by = referrer
                agent_profile.save()
            created = True
            record_role_event(user, role, RoleAuditEvent.Event.ACTIVATED, request)
            # Clear any pending registration challenge for this email.
            PendingRegistration.objects.filter(email=email).delete()
        else:
            # Existing accounts keep their registered roles; a verified Google
            # identity is sufficient proof of email ownership, so a requested
            # customer role is activated for the identity like a password login.
            PendingRegistration.objects.filter(email=email).delete()
            if not user.email_verified:
                user.email_verified = True
                user.registration_otp_hash = ""
                user.registration_otp_expires_at = None
                user.registration_otp_attempts = 0
                user.save(
                    update_fields=[
                        "email_verified",
                        "registration_otp_hash",
                        "registration_otp_expires_at",
                        "registration_otp_attempts",
                        "updated_at",
                    ]
                )
            requested_role = str(request.data.get("role") or "").strip().lower()
            role_activated = _activate_role_after_credentials(
                user,
                requested_role,
                request,
                str(request.data.get("referral_code") or ""),
            )
            apply_active_role(user, requested_role or None)

        payload = UserSerializer(user, context={"request": request}).data
        payload["is_new_user"] = created
        if role_activated:
            payload["role_activated"] = True
        response = Response(payload)
        set_auth_cookies(response, user)
        return response

    @action(detail=False, methods=["post"], url_path="logout", permission_classes=[AllowAny], authentication_classes=[])
    def logout(self, request):
        response = Response({"message": "Logged out successfully"})
        clear_auth_cookies(response)
        return response

    @action(detail=False, methods=["post"], url_path="refresh", authentication_classes=[])
    def refresh(self, request):
        raw = request.COOKIES.get(settings.REFRESH_COOKIE_NAME) or request.data.get("refresh_token")
        if not raw:
            return Response({"detail": "Refresh token required"}, status=401)
        try:
            refresh = RefreshToken(raw)
            user = User.objects.get(id=refresh["user_id"])
        except Exception:
            return Response({"detail": "Invalid refresh token"}, status=401)
        apply_active_role(user, request.META.get(ACTIVE_ROLE_HEADER))
        response = Response(UserSerializer(user, context={"request": request}).data)
        set_auth_cookies(response, user)
        return response


class UserViewSet(viewsets.GenericViewSet):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_permissions(self):
        if self.action in {"me", "request_settings_otp", "update_settings", "password", "freeze_account"}:
            return [DRFIsAuthenticated()]
        return super().get_permissions()

    @action(detail=False, methods=["get", "patch", "delete"], url_path="me")
    def me(self, request):
        if request.method == "DELETE":
            ensure_valid_settings_otp(
                request.user,
                purpose=SETTINGS_OTP_PURPOSE_ACCOUNT,
                target_email=request.user.email.strip().lower(),
                code=str(request.data.get("otp_code", "")),
            )
            request.user.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        if request.method == "PATCH":
            serializer = self.get_serializer(request.user, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
        else:
            prefill_role_identity(request.user, request.user.role)
        return Response(self.get_serializer(request.user).data)

    @action(detail=False, methods=["post"], url_path="me/photo")
    def upload_photo(self, request):
        upload = request.FILES.get("file")
        if not upload:
            raise ValidationError({"file": "Profile photo is required."})
        if upload.size > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
            raise ValidationError({"file": "File is too large"})
        request.user.profile_photo = optimize_profile_image(upload)
        request.user.save(update_fields=["profile_photo", "updated_at"])
        return Response(self.get_serializer(request.user).data)

    @action(detail=False, methods=["get"], url_path="public-stats", permission_classes=[AllowAny])
    def public_stats(self, request):
        return Response(
            {
                "properties": Listing.objects.filter(status=Listing.Status.AVAILABLE, is_hidden=False).count(),
                "landlords": users_with_role(User.objects.all(), AppUser.Role.LANDLORD).count(),
                "tenants": users_with_role(User.objects.all(), AppUser.Role.TENANT).count(),
            }
        )

    @action(detail=False, methods=["get"], url_path="subscription-pricing", permission_classes=[AllowAny])
    def subscription_pricing(self, request):
        return Response(
            {
                **get_subscription_pricing(),
                "vat_rate_percent": json_decimal(subscription_vat_rate()),
            }
        )

    @action(detail=False, methods=["post"], url_path="me/settings/request-otp")
    def request_settings_otp(self, request):
        serializer = SettingsOtpRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        purpose = serializer.validated_data["purpose"]
        current_email = request.user.email.strip().lower()
        target_email = serializer.validated_data.get("target_email", "").strip().lower()

        if purpose in {SETTINGS_OTP_PURPOSE_PASSWORD, SETTINGS_OTP_PURPOSE_ACCOUNT}:
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
        tenant_profile_payload = {}
        guarantor_details = request.data.get("guarantor_details", None)
        has_guarantor_update = "guarantor_details" in request.data

        if has_guarantor_update:
            if request.user.role != AppUser.Role.TENANT:
                raise ValidationError({"guarantor_details": "Guarantor details are only available for tenant accounts."})
            if guarantor_details is not None and not isinstance(guarantor_details, dict):
                raise ValidationError({"guarantor_details": "Guarantor details must be a JSON object."})
            tenant_profile_payload["guarantor_details"] = guarantor_details

        residence = request.data.get("residence")
        if request.user.role == AppUser.Role.TENANT and isinstance(residence, dict):
            tenant_profile_payload.update(
                {
                    "residence_state": str(residence.get("state") or "").strip(),
                    "residence_city": str(residence.get("city") or "").strip(),
                    "residence_address": str(residence.get("address") or "").strip(),
                }
            )

        agent_profile_payload: dict[str, str] = {}
        agent_profile_update = request.data.get("agent_profile", None)
        if agent_profile_update is not None:
            if request.user.role != AppUser.Role.AGENT:
                raise ValidationError({"agent_profile": "Payout details are only available for property inspection officer accounts."})
            if not isinstance(agent_profile_update, dict):
                raise ValidationError({"agent_profile": "PIO profile must be a JSON object."})
            for field_name in AGENT_SETTINGS_MUTABLE_FIELDS:
                if field_name in agent_profile_update:
                    agent_profile_payload[field_name] = str(agent_profile_update.get(field_name) or "").strip()

            account_number = agent_profile_payload.get("account_number")
            if account_number and not (account_number.isdigit() and len(account_number) == 10):
                raise ValidationError({"agent_profile": {"account_number": "Nigerian account number must be exactly 10 digits."}})
            account_name = agent_profile_payload.get("account_name")
            if account_name and not re.fullmatch(r"[A-Za-z][A-Za-z\s'\-.]*", account_name):
                raise ValidationError({"agent_profile": {"account_name": "Account name must contain letters only."}})

        if not payload and not tenant_profile_payload and not agent_profile_payload:
            raise ValidationError({"detail": "No settings changes were provided."})

        serializer = None
        if payload:
            serializer = self.get_serializer(request.user, data=payload, partial=True)
            serializer.is_valid(raise_exception=True)

        tenant_profile = None
        tenant_profile_serializer = None
        if tenant_profile_payload and request.user.role == AppUser.Role.TENANT:
            tenant_profile = TenantProfile.objects.filter(user=request.user).first()
            if tenant_profile:
                tenant_profile_serializer = TenantProfileSerializer(
                    tenant_profile,
                    data=tenant_profile_payload,
                    partial=True,
                )
                tenant_profile_serializer.is_valid(raise_exception=True)

        target_email = (
            serializer.validated_data.get("email", request.user.email)
            if serializer
            else request.user.email
        ).strip().lower()
        ensure_valid_settings_otp(
            request.user,
            purpose=SETTINGS_OTP_PURPOSE_PROFILE,
            target_email=target_email,
            code=str(request.data.get("otp_code", "")),
        )

        with transaction.atomic():
            updated_user = serializer.save() if serializer else request.user
            if tenant_profile_serializer:
                tenant_profile_serializer.save()

            if request.user.role == AppUser.Role.AGENT:
                agent_profile = AgentProfile.objects.filter(user=updated_user).first()
                if agent_profile is not None:
                    if agent_profile_payload:
                        for field_name, value in agent_profile_payload.items():
                            setattr(agent_profile, field_name, value)
                        agent_profile.save(update_fields=[*agent_profile_payload.keys(), "updated_at"])
                    sync_updates: list[str] = []
                    for user_field in ("mobile", "whatsapp_number"):
                        value = getattr(updated_user, user_field, "") or ""
                        if value and getattr(agent_profile, user_field, "") != value:
                            setattr(agent_profile, user_field, value)
                            sync_updates.append(user_field)
                    if sync_updates:
                        agent_profile.save(update_fields=[*sync_updates, "updated_at"])

            if has_guarantor_update:
                verification_profile = dict(updated_user.tenant_verification_profile or {})
                verification_profile["guarantor_details"] = guarantor_details
                updated_user.tenant_verification_profile = verification_profile

            update_fields = ["updated_at"]
            if has_guarantor_update:
                update_fields.append("tenant_verification_profile")
            if not updated_user.email_verified:
                updated_user.email_verified = True
                update_fields.append("email_verified")
            updated_user.save(update_fields=update_fields)

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

    @action(detail=False, methods=["post", "delete"], url_path="me/freeze")
    def freeze_account(self, request):
        if request.user.role not in {AppUser.Role.TENANT, AppUser.Role.LANDLORD}:
            raise PermissionDenied("Only tenant and landlord accounts can be frozen.")

        membership = active_role_membership(request.user)
        if membership is None:
            membership, _ = UserRole.objects.get_or_create(
                user=request.user,
                role=request.user.role,
                defaults={"status": UserRole.Status.ACTIVE},
            )
            if membership.status != UserRole.Status.ACTIVE:
                raise PermissionDenied("This role is not active for your account.")
            setattr(request.user, f"_active_membership_{request.user.role}", membership)

        if request.method == "DELETE":
            ensure_valid_settings_otp(
                request.user,
                purpose=SETTINGS_OTP_PURPOSE_ACCOUNT,
                target_email=request.user.email.strip().lower(),
                code=str(request.data.get("otp_code", "")),
            )
            membership.account_frozen = False
            membership.account_frozen_until = None
            membership.save(update_fields=["account_frozen", "account_frozen_until", "updated_at"])
            clear_settings_otp(request.user, save=False)
            request.user.save(
                update_fields=[
                    "settings_otp_hash",
                    "settings_otp_expires_at",
                    "settings_otp_attempts",
                    "settings_otp_purpose",
                    "settings_otp_target_email",
                    "updated_at",
                ]
            )
            return Response(self.get_serializer(request.user).data)

        try:
            duration_months = int(request.data.get("duration_months") or 3)
        except (TypeError, ValueError) as exc:
            raise ValidationError({"duration_months": "Choose a valid freeze duration."}) from exc
        if duration_months not in {3, 6, 12}:
            raise ValidationError({"duration_months": "Choose a freeze duration of 3, 6, or 12 months."})

        ensure_valid_settings_otp(
            request.user,
            purpose=SETTINGS_OTP_PURPOSE_ACCOUNT,
            target_email=request.user.email.strip().lower(),
            code=str(request.data.get("otp_code", "")),
        )

        membership.account_frozen = True
        membership.account_frozen_at = timezone.now()
        membership.account_frozen_until = timezone.now() + timedelta(days=30 * duration_months)
        membership.account_freeze_fee_percentage = ACCOUNT_FREEZE_FEE_PERCENTAGE
        membership.save(
            update_fields=[
                "account_frozen",
                "account_frozen_at",
                "account_frozen_until",
                "account_freeze_fee_percentage",
                "updated_at",
            ]
        )
        clear_settings_otp(request.user, save=False)
        request.user.save(
            update_fields=[
                "settings_otp_hash",
                "settings_otp_expires_at",
                "settings_otp_attempts",
                "settings_otp_purpose",
                "settings_otp_target_email",
                "updated_at",
            ]
        )
        return Response(self.get_serializer(request.user).data)

    @action(detail=False, methods=["get", "post"], url_path="me/roles")
    def roles(self, request):
        user = request.user
        if request.method == "GET":
            return Response(
                {
                    "roles": available_roles(user),
                    "active_role": getattr(user, "active_role", None) or user.role,
                }
            )

        role = str(request.data.get("role") or "").strip().lower()
        if role not in CUSTOMER_ROLES:
            raise ValidationError({"role": "Choose a valid role."})
        if getattr(user, "role", None) == AppUser.Role.ADMIN or getattr(user, "active_role", None) == AppUser.Role.ADMIN:
            raise PermissionDenied("This role is not active for your account.")
        if not user.email_verified:
            raise ValidationError({"detail": "Verify your email address before adding a role."})

        referrer = None
        if role == AppUser.Role.AGENT:
            referral_code = str(request.data.get("referral_code") or "").strip().upper()
            if referral_code:
                referrer = resolve_referrer(referral_code)
                if referrer is None:
                    raise ValidationError({"referral_code": "This referral code is not recognised."})
                if referrer.id == user.id:
                    raise ValidationError({"referral_code": "You cannot refer yourself."})

        _membership, activated = activate_customer_role(user, role)
        if role == AppUser.Role.AGENT:
            agent_profile, _ = AgentProfile.objects.get_or_create(
                user=user,
                defaults={"first_name": "", "last_name": ""},
            )
            if referrer and agent_profile.referred_by_id is None:
                agent_profile.referred_by = referrer
                agent_profile.save(update_fields=["referred_by", "updated_at"])

        prefill_role_identity(user, role)
        apply_active_role(user, role)
        if activated:
            record_role_event(user, role, RoleAuditEvent.Event.ACTIVATED, request)
        return Response(
            self.get_serializer(user).data,
            status=status.HTTP_201_CREATED if activated else status.HTTP_200_OK,
        )

    @action(detail=False, methods=["post"], url_path="me/active-role")
    def active_role(self, request):
        user = request.user
        role = str(request.data.get("role") or "").strip().lower()
        if not role:
            raise ValidationError({"role": "This field is required."})
        apply_active_role(user, role)
        record_role_event(user, role, RoleAuditEvent.Event.SWITCHED, request)
        return Response(self.get_serializer(user).data)

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
        whatsapp_number = str(data.pop("whatsapp_number", "") or "").strip()
        if whatsapp_number and not is_valid_mobile(whatsapp_number):
            raise ValidationError({"whatsapp_number": "Enter a valid mobile number."})
        data["user"] = request.user.id
        if request.method == "POST" and not profile:
            serializer = TenantProfileSerializer(data=data)
            serializer.is_valid(raise_exception=True)
            mobile_warning = ""
            try:
                if not tenant_verified_identity_matches(request.user, serializer.validated_data, nin_number, bvn_number):
                    verification_payloads = verify_tenant_identity_or_raise(request.user, serializer.validated_data, nin_number, bvn_number)
                    mobile_warning = extract_mobile_verification_warning(verification_payloads)
            except APIException:
                rejected_profile = serializer.save(user=request.user)
                rejected_profile.status = TenantProfile.Status.REJECTED
                rejected_profile.save(update_fields=["status", "updated_at"])
                raise
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
                if verification_profile.get("whatsapp_number"):
                    request.user.whatsapp_number = verification_profile["whatsapp_number"]
                request.user.save(update_fields=["nin_number", "bvn_number", "tenant_verification_profile", "whatsapp_number", "updated_at"])
                new_profile = serializer.save(user=request.user)
            vr = sync_tenant_profile_approval(request.user, new_profile)
            if new_profile.supporting_documents.exists():
                vr.documents.set(new_profile.supporting_documents.all())
            response_data = TenantProfileSerializer(new_profile).data
            if mobile_warning:
                response_data["mobile_warning"] = mobile_warning
            return Response(response_data, status=201)

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
        mobile_warning = ""
        try:
            if not tenant_verified_identity_matches(request.user, merged_profile_data, nin_number, bvn_number):
                verification_payloads = verify_tenant_identity_or_raise(request.user, merged_profile_data, nin_number, bvn_number)
                mobile_warning = extract_mobile_verification_warning(verification_payloads)
        except APIException:
            rejected_profile = serializer.save()
            rejected_profile.status = TenantProfile.Status.REJECTED
            rejected_profile.save(update_fields=["status", "updated_at"])
            raise
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
            if verification_profile.get("whatsapp_number"):
                request.user.whatsapp_number = verification_profile["whatsapp_number"]
            request.user.save(update_fields=["nin_number", "bvn_number", "tenant_verification_profile", "whatsapp_number", "updated_at"])
            updated_profile = serializer.save()
        vr = sync_tenant_profile_approval(request.user, updated_profile)
        if updated_profile.supporting_documents.exists():
            vr.documents.set(updated_profile.supporting_documents.all())
        response_data = TenantProfileSerializer(updated_profile).data
        if mobile_warning:
            response_data["mobile_warning"] = mobile_warning
        return Response(response_data)

    @action(detail=False, methods=["get", "put"], url_path="me/search-requirement")
    def search_requirement(self, request):
        requirement = TenantSearchRequirement.objects.filter(user=request.user).first()
        if request.method == "GET":
            if not requirement:
                return Response({"detail": "No search requirement found."}, status=404)
            return Response(TenantSearchRequirementSerializer(requirement).data)

        if request.user.role != AppUser.Role.TENANT:
            raise PermissionDenied("Only tenant accounts can save a property search requirement.")
        created = requirement is None
        serializer = (
            TenantSearchRequirementSerializer(requirement, data=request.data, partial=True)
            if requirement
            else TenantSearchRequirementSerializer(data=request.data)
        )
        serializer.is_valid(raise_exception=True)
        requirement = serializer.save() if requirement else serializer.save(user=request.user)
        return Response(
            TenantSearchRequirementSerializer(requirement).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @action(detail=False, methods=["get"], url_path="me/search-requirement/matches")
    def search_requirement_matches(self, request):
        requirement = TenantSearchRequirement.objects.filter(user=request.user).first()
        if not requirement:
            return Response({"detail": "No search requirement found."}, status=404)
        try:
            limit = int(request.query_params.get("limit") or 3)
        except (TypeError, ValueError):
            limit = 3
        result = top_matches_for_requirement(requirement, limit=min(24, max(1, limit)))
        return Response(
            {
                "matches": [
                    {
                        "listing": ListingSerializer(match["listing"], context={"request": request}).data,
                        "match_score": match["match_score"],
                        "match_reasons": match["match_reasons"],
                    }
                    for match in result["matches"]
                ],
                "in_location_count": result["in_location_count"],
                "outside_location_count": result["outside_location_count"],
            }
        )

    @action(detail=False, methods=["get"], url_path="tenants/(?P<tenant_id>[^/.]+)/profile")
    def tenant_profile_detail(self, request, tenant_id=None):
        tenant = get_object_or_404(
            users_with_role(User.objects.all(), AppUser.Role.TENANT),
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

        response_data = {
            "id": tenant.id,
            "name": tenant.name,
            "profile_photo_url": tenant.profile_photo_url,
            "state_of_origin": tenant.state_of_origin,
            "residence": tenant.residence,
            "is_verified": tenant.is_verified,
            "tenant_profile": profile_payload,
        }
        can_view_private_contacts = request.user.role == AppUser.Role.ADMIN or request.user.id == tenant.id
        if can_view_private_contacts:
            response_data.update({"email": tenant.email, "mobile": tenant.mobile})
        return Response(response_data)

    @action(detail=False, methods=["get"], url_path="tenants/(?P<tenant_id>[^/.]+)/public-profile", permission_classes=[AllowAny])
    def tenant_public_profile(self, request, tenant_id=None):
        tenant = get_object_or_404(
            users_with_role(User.objects.all(), AppUser.Role.TENANT),
            id=tenant_id,
        )
        return Response(build_tenant_public_profile_payload(tenant))

    @action(detail=False, methods=["get"], url_path="landlords/(?P<landlord_id>[^/.]+)/public-profile", permission_classes=[AllowAny])
    def landlord_public_profile(self, request, landlord_id=None):
        landlord = get_object_or_404(
            users_with_role(User.objects.all(), AppUser.Role.LANDLORD),
            id=landlord_id,
        )
        return Response(build_landlord_public_profile_payload(landlord, request.user))


class ListingViewSet(viewsets.ModelViewSet):
    serializer_class = ListingSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_permissions(self):
        if self.action in {"create", "update", "partial_update", "destroy", "visibility"}:
            return [IsLandlordOrAdmin()]
        return [AllowAny()]

    def get_queryset(self):
        qs = Listing.objects.select_related("landlord").prefetch_related("images", "property_documents", "bookings")
        if self.action == "retrieve":
            user = self.request.user
            is_admin = getattr(user, "is_authenticated", False) and user.role == AppUser.Role.ADMIN
            is_landlord = getattr(user, "is_authenticated", False) and user.role == AppUser.Role.LANDLORD
            if is_landlord:
                public_listing_ids = (
                    Listing.objects.filter(status=Listing.Status.AVAILABLE, is_hidden=False)
                    .values("id")
                )
                qs = qs.filter(Q(landlord=user) | Q(id__in=public_listing_ids))
            elif not is_admin:
                qs = qs.filter(status=Listing.Status.AVAILABLE, is_hidden=False)
        landlord_id = self.request.query_params.get("landlord_id")
        if landlord_id:
            qs = qs.filter(landlord_id=landlord_id)
            user = self.request.user
            can_manage_requested_landlord = (
                getattr(user, "is_authenticated", False)
                and (
                    user.role == AppUser.Role.ADMIN
                    or (user.role == AppUser.Role.LANDLORD and str(user.id) == str(landlord_id))
                )
            )
            if not can_manage_requested_landlord:
                qs = qs.filter(status=Listing.Status.AVAILABLE, is_hidden=False)
        elif self.action in {"list", "search", "nearby", "cities", "featured_listings", "location_analytics"}:
            qs = qs.filter(status=Listing.Status.AVAILABLE, is_hidden=False)
        featured = self.request.query_params.get("featured")
        if featured is not None:
            qs = qs.filter(featured=str(featured).lower() == "true")
        q = self.request.query_params.get("q")
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q) | Q(city__icontains=q) | Q(address__icontains=q))
        return qs.order_by("-featured", "-created_at")

    def perform_create(self, serializer):
        if self.request.user.role == AppUser.Role.LANDLORD and user_account_freeze_active(self.request.user):
            raise PermissionDenied("Frozen landlord accounts cannot list properties.")
        if self.request.user.role == "landlord" and not self.request.user.is_verified:
            raise PermissionDenied("Your account identity must be verified before listing properties.")
        if self.request.user.role == AppUser.Role.LANDLORD and not landlord_profile_has_mandatory_fields(self.request.user):
            raise PermissionDenied("Complete your landlord profile before listing properties.")
        if self.request.user.role == AppUser.Role.LANDLORD and user_has_bronze_access(self.request.user):
            raise PermissionDenied("A subscription plan is required to create listings.")
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

    @action(detail=True, methods=["post"], url_path="visibility")
    def visibility(self, request, pk=None):
        listing = self.get_object()
        if request.user.role != AppUser.Role.ADMIN and listing.landlord_id != request.user.id:
            raise PermissionDenied("Forbidden")
        is_hidden = request.data.get("is_hidden")
        if not isinstance(is_hidden, bool):
            raise ValidationError({"is_hidden": "Provide a boolean value."})
        listing.is_hidden = is_hidden
        listing.save(update_fields=["is_hidden", "updated_at"])
        return Response(self.get_serializer(listing).data)

    @action(detail=False, methods=["get", "post"], url_path="representative-kyc")
    def representative_kyc(self, request):
        if request.user.role != AppUser.Role.LANDLORD:
            raise PermissionDenied("Only landlords can manage representative KYC links.")

        if request.method == "GET":
            kycs = (
                RepresentativeKyc.objects
                .select_related("listing", "landlord")
                .filter(landlord=request.user)
                .order_by("-created_at")[:20]
            )
            return Response(RepresentativeKycSerializer(kycs, many=True).data)

        listing_id = str(request.data.get("listing_id") or "").strip()
        listing = None
        if listing_id:
            listing = self.get_queryset().filter(pk=listing_id, landlord=request.user).first()
            if listing is None:
                raise ValidationError({"listing_id": "Listing not found."})

        return_url = str(request.data.get("return_url") or "").strip()
        kyc = RepresentativeKyc.objects.create(
            landlord=request.user,
            listing=listing,
            ownership_type=str(request.data.get("ownership_type") or "").strip()[:120],
            return_url=return_url[:255],
        )
        return Response(RepresentativeKycSerializer(kyc).data, status=status.HTTP_201_CREATED)

    @staticmethod
    def _can_access_location_features(request):
        user = request.user
        if not getattr(user, "is_authenticated", False):
            return False
        if user.role == AppUser.Role.ADMIN:
            return True
        return user_has_silver_access(user)

    @action(detail=False, methods=["get"], url_path="cities", permission_classes=[AllowAny])
    def cities(self, request):
        if not self._can_access_location_features(request):
            return Response([])
        qs = self.get_queryset().exclude(city="")
        state = (request.query_params.get("state") or "").strip()
        if state:
            qs = qs.filter(state__iexact=state)
        cities = qs.values_list("city", flat=True).distinct().order_by("city")
        return Response(list(cities))

    def _distance_query_params(self, request):
        latitude = request.query_params.get("latitude") or request.query_params.get("lat")
        longitude = (
            request.query_params.get("longitude")
            or request.query_params.get("lng")
            or request.query_params.get("lon")
        )
        radius_km = request.query_params.get("radius_km") or request.query_params.get("radius")
        origin_city = (
            request.query_params.get("origin_city")
            or request.query_params.get("location_city")
            or request.query_params.get("from_city")
        )
        origin_state = (
            request.query_params.get("origin_state")
            or request.query_params.get("location_state")
            or request.query_params.get("from_state")
        )

        if latitude is None and longitude is None and radius_km is None and origin_city is None and origin_state is None:
            return None
        if radius_km is None:
            raise ValidationError({"location": "radius_km is required for distance search."})

        try:
            radius_value = float(radius_km)
        except (TypeError, ValueError):
            raise ValidationError({"radius_km": "Radius must be a valid number."})
        if radius_value <= 0 or radius_value > 200:
            raise ValidationError({"radius_km": "Radius must be greater than 0 and no more than 200 km."})

        if latitude is not None or longitude is not None:
            if latitude is None or longitude is None:
                raise ValidationError({"location": "Both latitude and longitude are required for distance search."})
            try:
                latitude_value = float(latitude)
                longitude_value = float(longitude)
            except (TypeError, ValueError):
                raise ValidationError({"location": "latitude and longitude must be valid numbers."})

            if not -90 <= latitude_value <= 90:
                raise ValidationError({"latitude": "Latitude must be between -90 and 90."})
            if not -180 <= longitude_value <= 180:
                raise ValidationError({"longitude": "Longitude must be between -180 and 180."})

            return latitude_value, longitude_value, radius_value, False

        using_filter_location_as_origin = False
        if origin_city is None and origin_state is None:
            fallback_city = (request.query_params.get("city") or "").strip()
            fallback_state = (request.query_params.get("state") or "").strip()
            if fallback_city or fallback_state:
                origin_city = fallback_city
                origin_state = fallback_state
                using_filter_location_as_origin = True

        if origin_city or origin_state:
            coordinates = resolve_city_state_coordinates(origin_city, origin_state)
            if coordinates is None:
                raise ValidationError({"location": "Could not resolve the selected city or state for distance search."})
            return coordinates.latitude, coordinates.longitude, radius_value, using_filter_location_as_origin

        raise ValidationError({"location": "latitude and longitude, or origin_city/origin_state, are required for distance search."})

    def _filter_by_distance(self, qs, latitude: float, longitude: float, radius_km: float):
        matches = []
        for listing in qs:
            distance_match = attach_distance_to_listing(listing, latitude, longitude)
            if distance_match is None:
                continue
            listing, distance = distance_match
            if distance <= radius_km:
                matches.append(listing)

        return sorted(
            matches,
            key=lambda listing: (
                getattr(listing, "_distance_km", 0),
                not bool(getattr(listing, "featured", False)),
                -getattr(getattr(listing, "created_at", None), "timestamp", lambda: 0)(),
            ),
        )

    def _location_group_payload(self, listings, group_by: str):
        groups = {}
        for listing in listings:
            state = str(getattr(listing, "state", "") or "Not specified").strip() or "Not specified"
            city = str(getattr(listing, "city", "") or "Not specified").strip() or "Not specified"
            if group_by == "states":
                key = (state,)
                name = state
                metadata = {}
            elif group_by == "cities":
                key = (state, city)
                name = city
                metadata = {"state": state}
            else:
                neighbourhood = listing_neighbourhood(listing)
                key = (state, city, neighbourhood)
                name = neighbourhood
                metadata = {"state": state, "city": city}

            price = Decimal(getattr(listing, "price_per_year", 0) or 0)
            group = groups.setdefault(
                key,
                {
                    "name": name,
                    "listing_count": 0,
                    "min_price_per_year": price,
                    "max_price_per_year": price,
                    "total_price_per_year": ZERO_AMOUNT,
                    **metadata,
                },
            )
            group["listing_count"] += 1
            group["total_price_per_year"] += price
            group["min_price_per_year"] = min(group["min_price_per_year"], price)
            group["max_price_per_year"] = max(group["max_price_per_year"], price)

        payload = []
        for group in groups.values():
            listing_count = group.pop("listing_count")
            total_price = group.pop("total_price_per_year")
            payload.append(
                {
                    **group,
                    "listing_count": listing_count,
                    "average_price_per_year": round(float(total_price / listing_count), 0) if listing_count else 0,
                    "min_price_per_year": round(float(group["min_price_per_year"]), 0),
                    "max_price_per_year": round(float(group["max_price_per_year"]), 0),
                }
            )
        return sorted(payload, key=lambda item: (-item["listing_count"], item["name"]))[:20]

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
        category = request.query_params.get("category")
        distance_params = self._distance_query_params(request)
        if distance_params and not self._can_access_location_features(request):
            raise PermissionDenied("Distance and map-based property search is available from the Silver plan.")
        using_filter_location_as_origin = False
        if distance_params:
            latitude, longitude, radius_km, using_filter_location_as_origin = distance_params
        for key in ["pet_friendly", "furnished", "utilities_included"]:
            value = request.query_params.get(key)
            if value is not None:
                qs = qs.filter(**{key: str(value).lower() == "true"})
        if query:
            qs = qs.filter(Q(title__icontains=query) | Q(description__icontains=query) | Q(address__icontains=query))
        if city and not using_filter_location_as_origin:
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
        if category:
            qs = qs.filter(category=category)
        if distance_params:
            qs = self._filter_by_distance(qs, latitude, longitude, radius_km)
        page = self.paginate_queryset(qs)
        serializer = self.get_serializer(page if page is not None else qs, many=True)
        return self.get_paginated_response(serializer.data) if page is not None else Response(serializer.data)

    @action(detail=False, methods=["get"], url_path="nearby", permission_classes=[AllowAny])
    def nearby(self, request):
        return self.search(request)

    @action(detail=False, methods=["get"], url_path="location-analytics", permission_classes=[AllowAny])
    def location_analytics(self, request):
        if not self._can_access_location_features(request):
            raise PermissionDenied("Property location analytics is available from the Silver plan.")
        qs = self.get_queryset()
        state = (request.query_params.get("state") or "").strip()
        city = (request.query_params.get("city") or "").strip()
        if state:
            qs = qs.filter(
                Q(state__icontains=state)
                | Q(address__icontains=state)
                | Q(landlord__residence__state__icontains=state)
            )
        if city:
            qs = qs.filter(Q(city__icontains=city) | Q(address__icontains=city))

        listings = list(qs)
        return Response(
            {
                "total_listings": len(listings),
                "states": self._location_group_payload(listings, "states"),
                "cities": self._location_group_payload(listings, "cities"),
                "neighbourhoods": self._location_group_payload(listings, "neighbourhoods"),
            }
        )

    @action(detail=True, methods=["get"], url_path="nearest-amenities", permission_classes=[AllowAny])
    def nearest_amenities(self, request, pk=None):
        if not self._can_access_location_features(request):
            raise PermissionDenied("Property location and nearby amenities are available from the Silver plan.")
        listing = self.get_object()
        coordinates = coordinates_for_listing(listing)
        categories_payload = {category: [] for category in AMENITY_CATEGORIES}
        if coordinates is None:
            return Response(
                {
                    "listing_id": str(listing.id),
                    "location_available": False,
                    "location_source": None,
                    "radius_km": None,
                    "amenities": categories_payload,
                }
            )

        limit = request.query_params.get("limit", 3)
        radius_km = request.query_params.get("radius_km", 25)
        try:
            limit_value = max(1, min(int(limit), 10))
            radius_value = max(1.0, min(float(radius_km), 100.0))
        except (TypeError, ValueError):
            raise ValidationError({"amenities": "limit and radius_km must be valid numbers."})

        return Response(
            {
                "listing_id": str(listing.id),
                "location_available": True,
                "location_source": coordinates.source,
                "latitude": coordinates.latitude,
                "longitude": coordinates.longitude,
                "radius_km": radius_value,
                "amenities": nearest_amenities_for_coordinates(
                    coordinates.latitude,
                    coordinates.longitude,
                    limit_per_category=limit_value,
                    max_distance_km=radius_value,
                ),
            }
        )


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
            queryset = queryset.filter(role=self.user_role)
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
            verification = VerificationRequest.objects.create(
                user=user,
                role=self.user_role or getattr(user, "active_role", None) or user.role,
            )
        return verification

    def serialize_submission_response(self, verification, mobile_warning: str = ""):
        message = (
            "Verification approved automatically."
            if verification.status == VerificationRequest.Status.APPROVED
            else "Verification submitted for manual review."
        )
        response_data = {
            "id": verification.id,
            "request_type": verification.request_type,
            "status": verification.status,
            "identity_verification_status": verification.identity_verification_status,
            "property_document_verification_status": verification.property_document_verification_status,
            "physical_property_status": verification.physical_property_status,
            "message": message,
        }
        if mobile_warning:
            response_data["mobile_warning"] = mobile_warning
        return response_data

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

        mobile_warning = self.apply_submission(request, verification, request_type, physical_property_status, update_fields) or ""

        verification.save(update_fields=update_fields)
        if docs:
            verification.documents.add(*docs)
        return Response(self.serialize_submission_response(verification, mobile_warning), status=201)

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
                "user_role": item.role,
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
                mobile_warning = extract_mobile_verification_warning(verify_landlord_identity_or_raise(request.user))
                verification.identity_verification_status = VerificationRequest.VerificationProgressStatus.VERIFIED
                verification.verification_method = VerificationRequest.Method.AUTOMATED
                verification.status = VerificationRequest.Status.APPROVED
                verification.reviewed_at = timezone.now()
                _append_update_fields(update_fields, "identity_verification_status", "verification_method", "status", "reviewed_at")
                return mobile_warning
            else:
                verification.identity_verification_status = VerificationRequest.VerificationProgressStatus.PENDING
                _append_update_fields(update_fields, "identity_verification_status")

        if request_type == VerificationRequest.RequestType.PROPERTY_DOCUMENTS:
            verification.property_document_verification_status = VerificationRequest.VerificationProgressStatus.PENDING
            verification.physical_property_status = physical_property_status
            _append_update_fields(update_fields, "property_document_verification_status", "physical_property_status")


class TenantVerificationRequestViewSet(VerificationRequestBaseViewSet):
    user_role = AppUser.Role.TENANT

    def validate_submission(self, request, request_type, physical_property_status):
        if request_type == VerificationRequest.RequestType.PROPERTY_DOCUMENTS:
            raise ValidationError({"request_type": "Tenant verification requests do not accept property documents."})

    def apply_submission(self, request, verification, request_type, physical_property_status, update_fields):
        if request_type == VerificationRequest.RequestType.PROPERTY_DOCUMENTS:
            raise ValidationError({"request_type": "Tenant verification requests do not accept property documents."})

        if request_type == VerificationRequest.RequestType.IDENTIFICATION:
            profile = TenantProfile.objects.filter(user=request.user).first()
            profile_data = normalize_tenant_verification_profile(request.user.tenant_verification_profile, request.user)
            if profile:
                profile_data = normalize_tenant_verification_profile(
                    {
                        **profile_data,
                        "first_name": profile.first_name,
                        "middle_name": profile.middle_name,
                        "last_name": profile.last_name,
                        "date_of_birth": profile.date_of_birth,
                        "gender": profile.gender,
                        "nationality": profile.nationality,
                        "state_of_origin": profile.state_of_origin,
                        "lga": profile.lga,
                        "employment_status": profile.employment_status,
                    },
                    request.user,
                )
            nin_number = str(profile_data.get("nin_number") or request.user.nin_number or "").strip()
            bvn_number = str(profile_data.get("bvn_number") or request.user.bvn_number or "").strip()
            if tenant_verified_identity_matches(request.user, profile_data, nin_number, bvn_number):
                mobile_warning = ""
            else:
                mobile_warning = extract_mobile_verification_warning(
                    verify_tenant_identity_or_raise(request.user, profile_data, nin_number, bvn_number)
                )
            request.user.nin_number = nin_number
            request.user.bvn_number = bvn_number
            request.user.tenant_verification_profile = normalize_tenant_verification_profile(
                {
                    **profile_data,
                    "nin_number": nin_number,
                    "bvn_number": bvn_number,
                },
                request.user,
            )
            request.user.save(update_fields=["nin_number", "bvn_number", "tenant_verification_profile", "updated_at"])
            if profile and profile.status != TenantProfile.Status.APPROVED:
                profile.status = TenantProfile.Status.APPROVED
                profile.save(update_fields=["status", "updated_at"])
            verification.identity_verification_status = VerificationRequest.VerificationProgressStatus.VERIFIED
            verification.verification_method = VerificationRequest.Method.AUTOMATED
            verification.status = VerificationRequest.Status.APPROVED
            verification.reviewed_at = timezone.now()
            _append_update_fields(update_fields, "identity_verification_status", "verification_method", "status", "reviewed_at")
            return mobile_warning


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
        if self.request.user.role != AppUser.Role.TENANT:
            raise PermissionDenied("Only tenants can rent properties.")
        if not self.request.user.is_verified:
            raise PermissionDenied("Your account must be verified before renting a property. Please submit your NIN for verification.")
        if not user_has_completed_tenant_profile(self.request.user):
            raise PermissionDenied("Complete your tenant profile before renting a property.")
        if not user_has_silver_access(self.request.user):
            raise PermissionDenied("Renting property is available from the Silver plan.")
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        booking = self.get_object()
        if request.user.role != AppUser.Role.TENANT:
            raise PermissionDenied("Only tenants can delete cancelled rental payment history.")

        payment_statuses = set(booking.payments.values_list("status", flat=True))
        has_completed_payment = bool(payment_statuses & {"completed", REFUND_REQUESTED_PAYMENT_STATUS})
        has_open_payment = bool(payment_statuses & OPEN_PAYMENT_STATUSES)
        has_cancelled_payment = bool(payment_statuses & FAILED_PAYMENT_STATUSES)
        paid_amount = normalize_decimal_amount(booking.paid_amount)
        can_delete_history = (
            paid_amount == ZERO_AMOUNT
            and not has_completed_payment
            and not has_open_payment
            and (booking.status == Booking.Status.CANCELLED or has_cancelled_payment)
        )
        if not can_delete_history:
            raise ValidationError("Only cancelled rental payment history with no pending or completed payments can be deleted.")

        return super().destroy(request, *args, **kwargs)

    @action(detail=False, methods=["get"], url_path="listing/(?P<listing_id>[^/.]+)")
    def listing(self, request, listing_id=None):
        booking = self.get_queryset().filter(listing_id=listing_id).first()
        if not booking:
            return Response({"detail": "No booking found."}, status=404)
        return Response(self.get_serializer(booking).data)

    @action(detail=True, methods=["get", "patch"], url_path="rental-progress")
    def rental_progress(self, request, pk=None):
        booking = self.get_object()

        if request.user.role == AppUser.Role.TENANT and not request.user.is_verified:
            raise PermissionDenied("Your account must be verified before accessing rental progress. Please submit your NIN for verification.")
        if request.user.role == AppUser.Role.TENANT and not user_has_completed_tenant_profile(request.user):
            raise PermissionDenied("Complete your tenant profile before accessing rental progress.")
        if request.user.role == AppUser.Role.TENANT and not user_has_silver_access(request.user):
            raise PermissionDenied("Rental progress tracking is available from the Silver plan.")

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
            enqueue_booking_payout_check_safely(booking.pk)
            booking = self.get_queryset().get(pk=booking.pk)

        return Response(self.get_serializer(booking).data)

    @action(detail=True, methods=["get", "post"], url_path="refunds")
    def refunds(self, request, pk=None):
        booking = self.get_object()

        if request.method == "GET":
            refunds = booking.refunds.select_related("payment").order_by("-created_at")
            return Response(TenantRefundSerializer(refunds, many=True).data)

        if request.user.role != AppUser.Role.TENANT or booking.tenant_id != request.user.id:
            raise PermissionDenied("Only the tenant on this booking can request a refund.")
        if booking_progress_step_completed_by_any_party(booking, "tenant_collected_house_key"):
            raise ValidationError(
                "Refunds can only be requested before the property keys have been handed over to you."
            )

        serializer = TenantRefundRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        payment = booking.payments.filter(
            pk=data["payment_id"],
            status__in=("completed", REFUND_REQUESTED_PAYMENT_STATUS),
        ).first()
        if payment is None:
            raise ValidationError({"payment_id": "Only a completed payment on this booking can be refunded."})

        open_statuses = {
            TenantRefund.Status.SCHEDULED,
            TenantRefund.Status.RECIPIENT_CREATED,
            TenantRefund.Status.READY,
            TenantRefund.Status.PROCESSING,
            TenantRefund.Status.PAID,
        }
        if payment.refunds.filter(status__in=open_statuses).exists():
            raise ValidationError({"payment_id": "A refund has already been requested for this payment."})

        bank_name = str(data["bank_name"] or "").strip()
        allowed_bank = resolve_payment_refund_bank(payment)
        if allowed_bank and normalize_bank_name_key(bank_name) != normalize_bank_name_key(allowed_bank):
            raise ValidationError(
                {
                    "bank_name": (
                        f"Refunds can only be sent to the {allowed_bank} account used for this payment."
                    )
                }
            )

        fee_amount = calculate_tenant_refund_fee(payment.amount)
        refund_amount = normalize_decimal_amount(payment.amount - fee_amount)
        if refund_amount <= ZERO_AMOUNT:
            raise ValidationError({"payment_id": "Refundable amount must be greater than zero."})

        with transaction.atomic():
            booking = Booking.objects.select_for_update().get(pk=booking.pk)
            payment = Payment.objects.select_for_update().get(pk=payment.pk)
            if payment.status not in ("completed", REFUND_REQUESTED_PAYMENT_STATUS):
                raise ValidationError({"payment_id": "Payment can no longer be refunded."})
            if payment.refunds.filter(status__in=open_statuses).exists():
                raise ValidationError({"payment_id": "A refund has already been requested for this payment."})
            if booking_progress_step_completed_by_any_party(booking, "tenant_collected_house_key"):
                raise ValidationError(
                    "Refunds can only be requested before the property keys have been handed over to you."
                )

            refund = TenantRefund.objects.create(
                booking=booking,
                payment=payment,
                tenant=request.user,
                amount=payment.amount,
                fee_amount=fee_amount,
                refund_amount=refund_amount,
                currency=payment.currency,
                reason=str(data.get("reason") or "").strip(),
                bank_name=bank_name,
                bank_code=resolve_nigerian_payout_bank_code(bank_name, data.get("bank_code") or ""),
                account_number=data["account_number"],
                account_name=str(data.get("account_name") or "").strip(),
                process_at=timezone.now() + timedelta(hours=TENANT_REFUND_PROCESSING_DELAY_HOURS),
            )

            if payment.status == "completed":
                payment.status = REFUND_REQUESTED_PAYMENT_STATUS
                payment.provider_payload = update_payment_provider_payload(
                    payment.provider_payload,
                    None,
                    refund={
                        "refund_id": str(refund.id),
                        "requested_at": timezone.now().isoformat(),
                        "refund_status": "scheduled",
                        "process_at": refund.process_at.isoformat(),
                        "fee_amount": str(fee_amount),
                        "refund_amount": str(refund_amount),
                    },
                )
                payment.save(update_fields=["status", "provider_payload", "updated_at"])

                booking.paid_amount = max(
                    normalize_decimal_amount(booking.paid_amount) - normalize_decimal_amount(payment.amount),
                    ZERO_AMOUNT,
                )
                booking.status = Booking.Status.CANCELLED
                booking.save(update_fields=["paid_amount", "status", "updated_at"])

        return Response(TenantRefundSerializer(refund).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get", "post"], url_path="tenancy-agreement")
    def tenancy_agreement(self, request, pk=None):
        booking = self.get_object()
        viewer_role = signature_role_for_user(booking, request.user)
        if viewer_role is None and request.user.role != AppUser.Role.ADMIN:
            raise PermissionDenied("Only the tenant or landlord on this booking can access the tenancy agreement.")

        latest = booking.tenancy_agreements.order_by("-version").first()

        if request.method == "POST":
            if viewer_role != "landlord":
                raise PermissionDenied("Only landlords can generate tenancy agreements.")
            if booking.status == Booking.Status.CANCELLED:
                raise ValidationError("A tenancy agreement cannot be generated for a cancelled booking.")
            submitted_data = request.data.get("data", {})
            if not isinstance(submitted_data, dict):
                raise ValidationError({"data": "Agreement data must be an object."})
            record = generate_tenancy_agreement(
                booking=booking,
                generated_by=request.user,
                submitted_data=submitted_data,
            )
            return Response(
                self._tenancy_agreement_workspace(booking, latest=record, data=record.agreement_data),
                status=status.HTTP_201_CREATED,
            )

        if latest:
            data = latest.agreement_data
        elif viewer_role == "landlord":
            data = build_agreement_draft(booking)
        else:
            data = {}
        return Response(self._tenancy_agreement_workspace(booking, latest=latest, data=data))

    @action(detail=True, methods=["post"], url_path="tenancy-agreement/sign")
    def sign_tenancy_agreement(self, request, pk=None):
        booking = self.get_object()
        agreement = sign_tenancy_agreement(
            booking=booking,
            signer=request.user,
            signatory_name=str(request.data.get("signatory_name") or ""),
            signatory_capacity=str(request.data.get("signatory_capacity") or ""),
        )
        return Response(
            self._tenancy_agreement_workspace(booking, latest=agreement, data=agreement.agreement_data)
        )

    @action(detail=True, methods=["post"], url_path="tenancy-agreement/docuseal")
    def tenancy_agreement_docuseal(self, request, pk=None):
        booking = self.get_object()
        viewer_role = signature_role_for_user(booking, request.user)
        if viewer_role is None:
            raise PermissionDenied("Only the tenant or landlord on this booking can sign the tenancy agreement.")
        if not is_docuseal_configured():
            return Response({"detail": "Electronic signing is not configured."}, status=503)
        agreement = (
            TenancyAgreement.objects.select_for_update()
            .filter(booking=booking)
            .order_by("-version")
            .first()
        )
        if agreement is None:
            raise ValidationError("Generate the tenancy agreement before requesting signatures.")

        data = agreement.agreement_data or {}
        signatures = data.get("signatures") if isinstance(data.get("signatures"), dict) else {}
        if signature_block_signed(signatures, viewer_role):
            return Response(
                self._tenancy_agreement_workspace(booking, latest=agreement, data=data)
            )

        if agreement.docuseal_submission_id is None:
            try:
                submission = create_docuseal_submission(
                    name=f"Tenancy Agreement — {booking.listing.title} (Booking {booking.id})",
                    document_name=f"tenancy-agreement-{agreement.id}.html",
                    document_content=_docuseal_agreement_html(agreement),
                    submitters=[
                        {
                            "role": DOCUSEAL_ROLE_LANDLORD,
                            "name": booking.listing.landlord.name or booking.listing.landlord.email,
                            "email": booking.listing.landlord.email,
                            "send_email": False,
                            "send_sms": False,
                        },
                        {
                            "role": DOCUSEAL_ROLE_TENANT,
                            "name": booking.tenant.name or booking.tenant.email,
                            "email": booking.tenant.email,
                            "send_email": False,
                            "send_sms": False,
                        },
                    ],
                )
            except requests.RequestException:
                logger.exception("DocuSeal submission creation failed for booking %s", booking.id)
                return Response({"detail": "Could not start electronic signing. Please try again."}, status=502)

            submitters = _docuseal_submitter_map(submission)
            submission_id = _docuseal_submission_id(submission)
            data["docuseal"] = {
                "status": "pending",
                "submitters": submitters,
            }
            agreement.agreement_data = data
            agreement.docuseal_submission_id = submission_id
            agreement.save(update_fields=["agreement_data", "docuseal_submission_id", "updated_at"])

        return Response(
            self._tenancy_agreement_workspace(booking, latest=agreement, data=agreement.agreement_data)
        )

    def _tenancy_agreement_workspace(self, booking, *, latest, data):
        viewer_role = signature_role_for_user(booking, self.request.user)
        is_landlord = viewer_role == "landlord"
        signatures = data.get("signatures") if isinstance(data, dict) else None
        if not isinstance(signatures, dict):
            signatures = {}
        signed_by_tenant = signature_block_signed(signatures, "tenant")
        signed_by_landlord = signature_block_signed(signatures, "landlord")
        lawyer_payment = (
            ServicePayment.objects.filter(
                booking=booking,
                purpose=ServicePayment.Purpose.LAWYER_TENANCY,
            )
            .order_by("-created_at")
            .first()
        )
        return {
            "agreement_options": (
                {
                    "free": {
                        "label": "RentDirect Tenancy Agreement",
                        "amount": 0,
                        "landlord_pays": True,
                    },
                    "lawyer": {
                        "label": "Lawyer-prepared Tenancy Agreement",
                        "fee_rate": str(LAWYER_SERVICE_FEE_RATE),
                        "amount": float(lawyer_service_fee_for_booking(booking)),
                        "landlord_pays": True,
                        "payment": (
                            ServicePaymentSerializer(lawyer_payment, context={"request": self.request}).data
                            if lawyer_payment
                            else None
                        ),
                    },
                }
                if is_landlord
                else None
            ),
            "booking": {
                "id": str(booking.id),
                "listing_title": booking.listing.title,
                "tenant_name": booking.tenant.name,
                "tenant_email": booking.tenant.email,
                "start_date": booking.start_date.isoformat() if booking.start_date else None,
                "end_date": booking.end_date.isoformat() if booking.end_date else None,
                "status": booking.status,
                "rent_amount": float(booking.listing.price_per_year or 0),
            },
            "data": data,
            "fields": agreement_form_fields() if is_landlord else [],
            "missing_fields": agreement_missing_fields(data) if is_landlord else [],
            "can_generate": is_landlord and booking.status != Booking.Status.CANCELLED,
            "latest_agreement": serialize_tenancy_agreement(latest),
            "docuseal": self._docuseal_workspace_block(booking, latest, data, viewer_role, signatures),
            "viewer_role": viewer_role,
            "signatures": signatures,
            "signed_by_tenant": signed_by_tenant,
            "signed_by_landlord": signed_by_landlord,
            "can_sign": bool(
                latest
                and viewer_role
                and not signature_block_signed(signatures, viewer_role)
            ),
        }

    def _docuseal_workspace_block(self, booking, latest, data, viewer_role, signatures):
        docuseal_meta = data.get("docuseal") if isinstance(data, dict) else None
        submitters = docuseal_meta.get("submitters") if isinstance(docuseal_meta, dict) else None
        if not isinstance(submitters, dict):
            submitters = {}
        signed = signature_block_signed(signatures, viewer_role) if viewer_role else False
        # The embedded signing URL is signer-specific — only expose it to the
        # matching party and only while they still need to sign.
        embed_src = ""
        if viewer_role and not signed:
            embed_src = str(
                (submitters.get(DOCUSEAL_ROLE_TENANT if viewer_role == "tenant" else DOCUSEAL_ROLE_LANDLORD) or {})
                .get("embed_src")
                or ""
            )
        return {
            "enabled": is_docuseal_configured(),
            "submission_id": latest.docuseal_submission_id if latest else None,
            "status": docuseal_meta.get("status", "") if isinstance(docuseal_meta, dict) else "",
            "embed_src": embed_src,
            "documents": docuseal_meta.get("documents", []) if isinstance(docuseal_meta, dict) else [],
        }


DOCUSEAL_ROLE_LANDLORD = "Landlord"
DOCUSEAL_ROLE_TENANT = "Tenant"


def _docuseal_agreement_html(agreement: TenancyAgreement) -> str:
    rendered = agreement.rendered_content or ""
    body_parts = []
    for line in rendered.split("\n"):
        body_parts.append(f"<p>{escape(line)}</p>" if line.strip() else "")
    signature_section = (
        "<div style='page-break-before:always;'>"
        "<h2>Signatures</h2>"
        "<p>Executed by the parties:</p>"
        "<table style='width:100%;border-collapse:collapse;'>"
        "<tr><td style='padding:12px 8px;width:50%;vertical-align:bottom;'>"
        f"<field name='landlord_signature' type='signature' role='{DOCUSEAL_ROLE_LANDLORD}' required='true' "
        "style='width:220px;height:64px;'></field>"
        "<p style='margin:4px 0 0;border-top:1px solid #333;padding-top:4px;'>Landlord Signature</p></td>"
        "<td style='padding:12px 8px;width:50%;vertical-align:bottom;'>"
        f"<field name='tenant_signature' type='signature' role='{DOCUSEAL_ROLE_TENANT}' required='true' "
        "style='width:220px;height:64px;'></field>"
        "<p style='margin:4px 0 0;border-top:1px solid #333;padding-top:4px;'>Tenant Signature</p></td>"
        "</tr></table>"
        "</div>"
    )
    return (
        "<html><body style='font-family:Georgia,serif;font-size:14px;line-height:1.6;color:#111;'>"
        + "".join(body_parts)
        + signature_section
        + "</body></html>"
    )


def _docuseal_submission_id(submission) -> int | None:
    if isinstance(submission, dict):
        return submission.get("id")
    if isinstance(submission, list) and submission:
        first = submission[0]
        if isinstance(first, dict):
            return first.get("submission_id") or first.get("id")
    return None


def _docuseal_submitter_map(submission) -> dict[str, dict]:
    submitters = submission.get("submitters") if isinstance(submission, dict) else submission
    if not isinstance(submitters, list):
        submitters = []
    result: dict[str, dict] = {}
    for submitter in submitters:
        if not isinstance(submitter, dict):
            continue
        role = str(submitter.get("role") or "").strip()
        if not role:
            continue
        result[role] = {
            "id": submitter.get("id"),
            "slug": submitter.get("slug"),
            "embed_src": submitter.get("embed_src") or "",
            "email": submitter.get("email") or "",
            "signed_at": submitter.get("completed_at"),
        }
    return result


def _docuseal_role_for_email(agreement: TenancyAgreement, email: str) -> str | None:
    email = (email or "").strip().lower()
    if not email:
        return None
    booking = agreement.booking
    if email == (booking.tenant.email or "").strip().lower():
        return "tenant"
    if email == (booking.listing.landlord.email or "").strip().lower():
        return "landlord"
    return None


@api_view(["POST"])
@permission_classes([AllowAny])
def docuseal_webhook(request):
    if not verify_docuseal_webhook_signature(request):
        return Response({"detail": "Invalid webhook signature."}, status=401)

    payload = request.data if isinstance(request.data, dict) else {}
    event_type = str(payload.get("event_type") or "")
    event_data = payload.get("data")
    if not isinstance(event_data, dict):
        event_data = {}

    submission_id = event_data.get("submission_id") or event_data.get("id")
    if isinstance(event_data.get("submission"), dict):
        submission_id = event_data["submission"].get("id") or submission_id
    agreement = (
        TenancyAgreement.objects.filter(docuseal_submission_id=submission_id)
        .select_related("booking", "booking__tenant", "booking__listing", "booking__listing__landlord")
        .order_by("-version")
        .first()
    ) if submission_id else None
    if agreement is None:
        return Response({"status": "ignored"})

    if event_type == "form.completed":
        role = str(event_data.get("role") or "").strip().lower()
        if role not in {"tenant", "landlord"}:
            role = _docuseal_role_for_email(agreement, str(event_data.get("email") or ""))
        if role:
            data = agreement.agreement_data or {}
            meta = data.setdefault("docuseal", {})
            submitters = meta.setdefault("submitters", {})
            submitter_key = DOCUSEAL_ROLE_TENANT if role == "tenant" else DOCUSEAL_ROLE_LANDLORD
            submitter = submitters.setdefault(submitter_key, {})
            submitter["signed_at"] = event_data.get("completed_at") or timezone.now().isoformat()
            agreement.agreement_data = data
            agreement.save(update_fields=["agreement_data", "updated_at"])
            signer = agreement.booking.tenant if role == "tenant" else agreement.booking.listing.landlord
            if not signature_block_signed((data.get("signatures") or {}), role):
                try:
                    sign_tenancy_agreement(
                        booking=agreement.booking,
                        signer=signer,
                        signatory_name=signer.name or signer.email,
                    )
                except ValidationError:
                    logger.exception("DocuSeal signature recording failed for agreement %s", agreement.id)
    elif event_type == "submission.completed":
        data = agreement.agreement_data or {}
        meta = data.setdefault("docuseal", {})
        meta["status"] = "completed"
        documents = event_data.get("documents")
        if isinstance(documents, list):
            meta["documents"] = [
                {"name": doc.get("name"), "url": doc.get("url")}
                for doc in documents
                if isinstance(doc, dict)
            ]
        if event_data.get("combined_document_url"):
            meta["combined_document_url"] = event_data["combined_document_url"]
        if event_data.get("audit_log_url"):
            meta["audit_log_url"] = event_data["audit_log_url"]
        agreement.agreement_data = data
        agreement.save(update_fields=["agreement_data", "updated_at"])
    elif event_type in {"submission.expired", "submission.archived"}:
        data = agreement.agreement_data or {}
        meta = data.setdefault("docuseal", {})
        meta["status"] = "expired" if event_type == "submission.expired" else "archived"
        agreement.agreement_data = data
        agreement.save(update_fields=["agreement_data", "updated_at"])

    return Response({"status": "ok"})


def process_flutterwave_webhook_event(body: dict) -> dict:
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
                return {"response": {"status": "ok", "reference": transfer_reference}, "status_code": 200}
            refund = TenantRefund.objects.select_related("payment", "tenant").filter(transfer_reference=transfer_reference).first()
            if refund:
                sync_tenant_refund_transfer(refund, body)
                return {"response": {"status": "ok", "reference": transfer_reference}, "status_code": 200}

    reference = extract_reference(body)
    provider_transaction_id = extract_provider_transaction_id(body)
    if not reference and not provider_transaction_id:
        return {"response": {"status": "ok"}, "status_code": 200}

    payment = Payment.objects.select_related("booking", "booking__listing", "booking__tenant").filter(transaction_id=reference).first()
    featured = FeaturedPayment.objects.select_related("listing", "landlord").filter(transaction_id=reference).first()
    subscription_filter = Q()
    if reference:
        subscription_filter |= Q(transaction_id=reference)
    if provider_transaction_id:
        subscription_filter |= Q(provider_charge_id=provider_transaction_id)
    subscription = (
        SubscriptionPayment.objects.select_related("user")
        .filter(subscription_filter)
        .first()
        if subscription_filter
        else None
    )
    service_payment = (
        ServicePayment.objects.select_related("user", "booking").filter(transaction_id=reference).first()
    )
    settlement = PaymentSettlement.objects.select_related(
        "payment",
        "payment__booking",
        "payment__booking__tenant",
        "payment__booking__listing",
        "payment__booking__listing__landlord",
    ).filter(transfer_reference=reference).first()
    if settlement and not payment and not featured and not subscription and not service_payment:
        sync_payment_settlement_transfer(settlement, body)
        return {"response": {"status": "ok", "reference": reference}, "status_code": 200}
    if not payment and not featured and not subscription and not service_payment:
        return {"response": {"status": "error", "message": "Payment not found"}, "status_code": 404}

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
        if service_payment:
            sync_service_payment(
                service_payment,
                transaction_id=provider_transaction_id or None,
                payload=body,
                source="webhook",
            )
    except FlutterwaveError as exc:
        return {"response": {"status": "error", "message": str(exc)}, "status_code": 502}

    return {"response": {"status": "ok", "reference": reference}, "status_code": 200}


def flutterwave_webhook_queue_reference(body: dict) -> str:
    transfer_data = body.get("data") if isinstance(body, dict) else {}
    if isinstance(transfer_data, dict):
        for key in ("reference", "transfer_reference", "tx_ref", "txRef", "flw_ref", "flwRef", "id"):
            value = str(transfer_data.get(key) or "").strip()
            if value:
                return value
    return extract_reference(body) or extract_provider_transaction_id(body)


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
        if request.user.role != AppUser.Role.TENANT:
            raise PermissionDenied("Only tenants can make rental payments.")
        if not request.user.is_verified:
            raise PermissionDenied("Your account must be verified before making rental payments. Please submit your NIN for verification.")
        if not user_has_completed_tenant_profile(request.user):
            raise PermissionDenied("Complete your tenant profile before making rental payments.")
        if not user_has_silver_access(request.user):
            raise PermissionDenied("Rental payments are available from the Silver plan.")
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        booking = Booking.objects.select_related("listing", "tenant").get(
            id=serializer.validated_data["booking_id"],
            tenant=request.user,
        )
        if booking.total_amount is None:
            raise ValidationError("Start the rental process with Rent Now before making a payment.")
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
        if request.user.role == AppUser.Role.TENANT and not request.user.is_verified:
            raise PermissionDenied("Your account must be verified before making rental payments. Please submit your NIN for verification.")
        if request.user.role == AppUser.Role.TENANT and not user_has_completed_tenant_profile(request.user):
            raise PermissionDenied("Complete your tenant profile before making rental payments.")
        if request.user.role == AppUser.Role.TENANT and not user_has_silver_access(request.user):
            raise PermissionDenied("Rental payments are available from the Silver plan.")
        payment = self.get_object()
        if payment.status not in OPEN_PAYMENT_STATUSES:
            raise ValidationError("Payment is no longer pending.")
        if payment.payment_method == "card" and booking_payments_card_limit_exceeded(payment.amount):
            raise ValidationError(
                {
                    "payment_method": (
                        f"Flutterwave card payments are limited to NGN {CARD_PAYMENT_LIMIT_NGN:,.0f} per transaction. "
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
        if payment.status == REFUND_REQUESTED_PAYMENT_STATUS:
            raise ValidationError("Refund has already been requested for this payment.")

        if payment.status == "completed":
            booking = payment.booking
            if booking_key_collection_confirmed_by_both_parties(booking):
                raise ValidationError(
                    "Sorry transaction cannot be cancelled. Landlord will need to approve refund. "
                    "Status shows Tenant and Landlord have confirmed collection of keys to the property."
                )

            admin_fee = normalize_decimal_amount(payment.amount * PAYMENT_CANCELLATION_ADMIN_FEE_RATE)
            refund_amount = normalize_decimal_amount(payment.amount - admin_fee)
            with transaction.atomic():
                booking = Booking.objects.select_for_update().get(pk=payment.booking_id)
                payment = Payment.objects.select_for_update().get(pk=payment.pk)
                if payment.status != "completed":
                    raise ValidationError("Payment can no longer be cancelled.")
                if booking_key_collection_confirmed_by_both_parties(booking):
                    raise ValidationError(
                        "Sorry transaction cannot be cancelled. Landlord will need to approve refund. "
                        "Status shows Tenant and Landlord have confirmed collection of keys to the property."
                    )
                payment.status = REFUND_REQUESTED_PAYMENT_STATUS
                payment.provider_payload = update_payment_provider_payload(
                    payment.provider_payload,
                    None,
                    cancellation={
                        "cancelled_at": timezone.now().isoformat(),
                        "reason": "refund_requested_by_tenant",
                        "refund_status": "requested",
                        "refund_eta": "3 to 5 working days",
                        "admin_fee_rate": str(PAYMENT_CANCELLATION_ADMIN_FEE_RATE),
                        "admin_fee_amount": str(admin_fee),
                        "refund_amount": str(refund_amount),
                    },
                )
                payment.save(update_fields=["status", "provider_payload", "updated_at"])

                booking.paid_amount = max(normalize_decimal_amount(booking.paid_amount) - normalize_decimal_amount(payment.amount), ZERO_AMOUNT)
                booking.status = Booking.Status.CANCELLED
                booking.save(update_fields=["paid_amount", "status", "updated_at"])
            return Response(self.get_serializer(payment).data)

        if payment.status not in OPEN_PAYMENT_STATUSES:
            raise ValidationError("Payment is no longer pending.")

        with transaction.atomic():
            payment = Payment.objects.select_for_update().get(pk=payment.pk)
            if payment.status not in OPEN_PAYMENT_STATUSES:
                raise ValidationError("Payment can no longer be cancelled.")
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
        reference = flutterwave_webhook_queue_reference(body)
        if not reference:
            return Response({"status": "ok"})

        try:
            result = enqueue_flutterwave_webhook(body)
        except Exception as exc:
            logger.exception("Failed to enqueue Flutterwave webhook payment task.")
            return Response({"status": "error", "message": str(exc)}, status=503)
        if result is not None:
            return Response(result["response"], status=result["status_code"])

        return Response({"status": "queued", "reference": reference})


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
        direct_settlement_configured = subscription_direct_settlement_configured()
        api_version = flutterwave_api_version()
        encryption_key_configured = flutterwave_encryption_key_is_configured()
        enabled = api_version == "v4" and encryption_key_configured and direct_settlement_configured
        return Response(
            {
                "enabled": enabled,
                "api_version": api_version,
                "encryption_key": encryption_key if api_version == "v4" and encryption_key_configured else "",
                "direct_settlement_configured": direct_settlement_configured,
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
        vat_rate = subscription_vat_rate() if not is_free_plan else ZERO_AMOUNT
        vat_amount = calculate_subscription_vat(amount_decimal)
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
                vat_rate=vat_rate,
                vat_amount=vat_amount,
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
            payment.vat_rate = vat_rate
            payment.vat_amount = vat_amount
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
                    "vat_rate",
                    "vat_amount",
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
                payment = charge_subscription_with_payment_method(
                    payment,
                    source="recurring_initial",
                    use_recurring_flow=False,
                )
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

        try:
            if flutterwave_api_version() == "v4":
                charge_payload, _destinations = build_v4_subscription_charge(
                    payment,
                    request.data.get("payment_method") or {"type": "bank_transfer", "bank_transfer": {"account_type": "dynamic"}},
                )
                payment = sync_subscription_payment(payment, payload=charge_payload, source="v4")
                charge_data = extract_provider_data(charge_payload)
                next_action = charge_data.get("next_action") if isinstance(charge_data, dict) else {}
                checkout = {
                    "checkout_mode": "v4",
                    "redirect_url": extract_next_action_url(charge_payload),
                    "next_action": next_action if isinstance(next_action, dict) else {},
                    "charge": charge_payload,
                }
                payment.provider_payload = update_payment_provider_payload(
                    payment.provider_payload,
                    None,
                    checkout=checkout,
                    return_url=build_subscription_payment_return_url(payment),
                )
                payment.save(update_fields=["transaction_id", "provider_payload", "updated_at"])
            else:
                subaccounts, destinations = build_subscription_subaccount_payload(payment)
                checkout = build_subscription_checkout(payment, subaccounts=subaccounts)
                payment.provider_payload = update_payment_provider_payload(
                    payment.provider_payload,
                    None,
                    checkout=checkout,
                    return_url=build_subscription_payment_return_url(payment),
                    subscription_destination=destinations["subscription"],
                    vat_destination=destinations["vat"],
                )
                payment.provider = "flutterwave"
                payment.save(update_fields=["transaction_id", "provider_payload", "provider", "updated_at"])
        except FlutterwaveError as exc:
            payment.provider_payload = update_payment_provider_payload(
                payment.provider_payload,
                None,
                charge={},
                checkout={},
            )
            payment.save(update_fields=["provider_payload", "updated_at"])
            return Response({"detail": str(exc)}, status=502)
        return Response({"payment": self.get_serializer(payment).data, "checkout": checkout})

    @action(detail=False, methods=["get"], url_path="flutterwave/banks")
    def flutterwave_banks(self, request):
        try:
            return Response({"banks": list_banks(country="NG")})
        except FlutterwaveError as exc:
            return Response({"detail": str(exc)}, status=502)

    @action(detail=True, methods=["post"], url_path="flutterwave/authorize")
    def flutterwave_authorize(self, request, pk=None):
        payment = self.get_queryset().get(id=pk)
        if payment.status != SubscriptionPayment.Status.PENDING:
            raise ValidationError("Payment is no longer pending.")
        if flutterwave_api_version() != "v4":
            raise ValidationError("Flutterwave authorization is only available in v4 mode.")
        try:
            charge_payload = update_charge(
                charge_id=payment.provider_charge_id,
                authorization=request.data.get("authorization") or {},
                idempotency_key=f"{payment.transaction_id}-authorization-{uuid.uuid4().hex}",
            )
            payment = sync_subscription_payment(payment, payload=charge_payload, source="v4_authorization")
        except FlutterwaveError as exc:
            return Response({"detail": str(exc)}, status=502)
        return Response(self.get_serializer(payment).data)

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
        days = max(
            FEATURED_PROPERTY_MIN_DURATION_DAYS,
            min(
                int(request.data.get("featured_duration_days", FEATURED_PROPERTY_MONTHLY_DURATION_DAYS)),
                FEATURED_PROPERTY_MAX_DURATION_DAYS,
            ),
        )
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
                amount=calculate_featured_property_fee(days),
                featured_duration_days=days,
                expires_at=timezone.now() + timedelta(days=days),
                transaction_id=f"FEAT_{uuid.uuid4().hex[:20].upper()}",
            )
        else:
            payment.featured_duration_days = days
            payment.amount = calculate_featured_property_fee(days)
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
        days = max(
            FEATURED_PROPERTY_MIN_DURATION_DAYS,
            min(
                int(request.data.get("featured_duration_days", FEATURED_PROPERTY_MONTHLY_DURATION_DAYS)),
                FEATURED_PROPERTY_MAX_DURATION_DAYS,
            ),
        )
        payment.featured_duration_days = days
        payment.amount = calculate_featured_property_fee(days)
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
        qs = (
            Listing.objects.filter(featured=True, status=Listing.Status.AVAILABLE, is_hidden=False)
            .prefetch_related("images", "bookings")
            .order_by("-updated_at")
        )
        category = request.query_params.get("category")
        if category:
            qs = qs.filter(category=category)
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
        review_type = (self.request.query_params.get("review_type") or "").strip()
        mine = (self.request.query_params.get("mine") or "").strip().lower() == "true"

        if listing_id:
            queryset = queryset.filter(listing_id=listing_id)
        if landlord_id:
            queryset = queryset.filter(landlord_id=landlord_id)
        if review_type:
            queryset = queryset.filter(review_type=review_type)
        if mine:
            if not getattr(self.request.user, "is_authenticated", False):
                return queryset.none()
            queryset = queryset.filter(tenant=self.request.user)

        return queryset

    def perform_create(self, serializer):
        if self.request.user.role != AppUser.Role.TENANT:
            raise PermissionDenied("Only tenants can submit reviews.")

        listing = get_object_or_404(Listing, id=self.request.data.get("listing_id"))
        # Same-identity gate: a landlord cannot review their own property.
        if listing.landlord_id == self.request.user.id:
            raise ValidationError({"detail": "You cannot review your own property or landlord profile."})
        if not user_has_gold_access(self.request.user):
            raise PermissionDenied("Landlord and property reviews are available from the Gold plan.")

        review_type = serializer.validated_data.get("review_type") or Review.ReviewType.PROPERTY
        if Review.objects.filter(listing=listing, tenant=self.request.user, review_type=review_type).exists():
            target = "landlord" if review_type == Review.ReviewType.LANDLORD else "property"
            raise ValidationError({"detail": f"You already reviewed this {target}. Edit the existing review instead."})
        serializer.save(tenant=self.request.user, landlord=listing.landlord, listing=listing)

    def perform_update(self, serializer):
        review = self.get_object()
        if self.request.user.role != AppUser.Role.ADMIN and review.tenant_id != self.request.user.id:
            raise PermissionDenied("Forbidden")
        if (
            self.request.user.role != AppUser.Role.ADMIN
            and review.listing.landlord_id == self.request.user.id
        ):
            raise ValidationError({"detail": "You cannot review your own property or landlord profile."})
        if self.request.user.role == AppUser.Role.TENANT and not user_has_gold_access(self.request.user):
            raise PermissionDenied("Landlord and property reviews are available from the Gold plan.")
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
        topic = (self.request.data.get("topic") or "").strip()
        if self.request.user.role == AppUser.Role.TENANT:
            normalized_issue_topic = re.sub(
                r"^(?:Premium Rental Workflow|Priority Issue|Issue)\s*:\s*",
                "",
                topic,
                flags=re.IGNORECASE,
            ).strip()
            is_issue = normalized_issue_topic != topic
            if is_issue:
                if user_has_platinum_access(self.request.user):
                    support_prefix = "Premium Rental Workflow"
                elif user_has_gold_access(self.request.user):
                    support_prefix = "Priority Issue"
                else:
                    support_prefix = "Issue"
                topic = f"{support_prefix}: {normalized_issue_topic or 'General support'}"
        feedback = serializer.save(
            user=self.request.user,
            name=(self.request.data.get("name") or self.request.user.name or "").strip() or self.request.user.name,
            role=self.request.user.role,
            topic=topic,
        )
        request_type = "complaint" if topic.lower().startswith("complaint:") else (
            "issue" if re.match(r"^(?:premium rental workflow|priority issue|issue):", topic, flags=re.IGNORECASE) else "feedback"
        )
        try:
            send_feedback_acknowledgement(
                recipient_email=self.request.user.email,
                recipient_name=feedback.name,
                request_type=request_type,
                topic=feedback.topic,
                message=feedback.message,
                plan_code=str(active_plan_code_for(self.request.user)),
                response_time=support_response_time_for(self.request.user),
                feedback_id=str(feedback.id),
                whatsapp_number=self.request.user.whatsapp_number,
            )
        except Exception:
            logger.exception("Unable to send feedback acknowledgement email for %s", feedback.id)


class MessageViewSet(viewsets.ModelViewSet):
    serializer_class = MessageSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if self.request.user.role == AppUser.Role.TENANT and not self.request.user.is_verified:
            raise PermissionDenied("Your account must be verified before accessing landlord conversations. Please submit your NIN for verification.")
        if self.request.user.role == AppUser.Role.TENANT and not user_has_completed_tenant_profile(self.request.user):
            raise PermissionDenied("Complete your tenant profile before accessing landlord conversations.")
        if self.request.user.role == AppUser.Role.TENANT and not user_has_silver_access(self.request.user):
            raise PermissionDenied("Landlord conversations and enquiries are available from the Silver plan.")
        role = self.request.user.role
        filters = (
            Q(sender=self.request.user, sender_role=role)
            | Q(receiver=self.request.user, receiver_role=role)
        )
        if role == AppUser.Role.LANDLORD:
            filters |= Q(listing__landlord=self.request.user) & (
                Q(sender_role=AppUser.Role.LANDLORD)
                | Q(receiver_role=AppUser.Role.LANDLORD)
            )

        return (
            Message.objects.filter(filters)
            .select_related("sender", "receiver", "listing", "listing__landlord")
            .prefetch_related("listing__images")
            .order_by("-created_at")
        )

    def _conversation_counterpart(self, msg):
        if self.request.user.role == AppUser.Role.LANDLORD:
            if msg.sender_role == AppUser.Role.TENANT:
                return msg.sender
            if msg.receiver_role == AppUser.Role.TENANT:
                return msg.receiver

        return msg.receiver if msg.sender_id == self.request.user.id else msg.sender

    def _conversation_counterpart_role(self, msg):
        counterpart = self._conversation_counterpart(msg)
        return msg.sender_role if counterpart.id == msg.sender_id else msg.receiver_role

    def _viewing_arranged_for(self, *, tenant_user, listing):
        if not tenant_user or not listing:
            return False

        booking = (
            Booking.objects
            .filter(tenant=tenant_user, listing=listing)
            .exclude(status=Booking.Status.CANCELLED)
            .order_by("-created_at")
            .first()
        )
        if not booking:
            return False

        return (
            booking_progress_step_completed(booking.tenant_rental_progress, "viewing_appointment_booked")
            or booking_progress_step_completed(booking.landlord_rental_progress, "viewing_appointment_booked")
        )

    def _rental_stage_for(self, booking, *, has_viewing_requested):
        if not booking:
            return "Viewing requested" if has_viewing_requested else "Message received"

        stage_checks = [
            ("tenant_collected_house_key", "Keys collected"),
            ("check_in_inventory_completed", "Inventory completed"),
            ("tenant_paid_rent_in_full", "Rent paid in full"),
            ("rental_payment_notification_received", "Rent paid in full"),
            ("tenant_paid_deposit", "Deposit paid"),
            ("deposit_payment_notification_received", "Deposit paid"),
            ("tenancy_agreement_signed", "Agreement signed"),
            ("house_viewed", "House viewed"),
            ("viewing_appointment_booked", "Viewing arranged"),
        ]
        for step_key, label in stage_checks:
            if (
                booking_progress_step_completed(booking.tenant_rental_progress, step_key)
                or booking_progress_step_completed(booking.landlord_rental_progress, step_key)
            ):
                return label
        return "Viewing requested" if has_viewing_requested else booking.get_status_display()

    def perform_create(self, serializer):
        if self.request.user.role == "tenant" and not self.request.user.is_verified:
            raise PermissionDenied("Your account must be verified before contacting landlords. Please submit your NIN for verification.")
        if self.request.user.role == AppUser.Role.TENANT and not user_has_completed_tenant_profile(self.request.user):
            raise PermissionDenied("Complete your tenant profile before contacting landlords.")
        receiver_id = serializer.validated_data.get("receiver_id")
        receiver = AppUser.objects.filter(id=receiver_id).first()
        if receiver is None:
            raise ValidationError({"receiver_id": "Receiver not found."})
        if self.request.user.role == AppUser.Role.TENANT and has_active_role(receiver, AppUser.Role.LANDLORD):
            if not user_has_silver_access(self.request.user):
                raise PermissionDenied("Contacting landlords is available from the Silver plan.")
            if user_has_bronze_access(role_bound_user(receiver, AppUser.Role.LANDLORD)):
                raise PermissionDenied("Landlord is unable to receive messages at this time until fully verified.")
        if self.request.user.role == AppUser.Role.LANDLORD and has_active_role(receiver, AppUser.Role.TENANT) and user_has_bronze_access(self.request.user):
            raise PermissionDenied("Contacting tenants is not available on the Bronze free plan.")
        if contains_contact_info(serializer.validated_data.get("content", "")):
            raise ValidationError("Phone numbers, emails, and social media handles are not allowed. Please use chat only.")
        serializer.save()

    @action(detail=False, methods=["get"], url_path="listing/(?P<listing_id>[^/.]+)")
    def listing_thread(self, request, listing_id=None):
        qs = self.get_queryset().filter(listing_id=listing_id).order_by("created_at")
        counterpart_id = (request.query_params.get("counterpart_id") or "").strip()
        if counterpart_id:
            qs = qs.filter(Q(sender_id=counterpart_id) | Q(receiver_id=counterpart_id))
        return Response(self.get_serializer(qs, many=True).data)

    @action(detail=False, methods=["get"], url_path="enquiries")
    def enquiries(self, request):
        latest = {}
        conversation_meta = {}
        for msg in self.get_queryset():
            counterpart_user = self._conversation_counterpart(msg)
            if request.user.role == AppUser.Role.LANDLORD and self._conversation_counterpart_role(msg) != AppUser.Role.TENANT:
                continue
            counterpart = str(counterpart_user.id)
            listing_key = str(msg.listing_id or "")
            conversation_key = f"{counterpart}:{listing_key}"
            meta = conversation_meta.setdefault(
                conversation_key,
                {"message_count": 0, "has_viewing_requested": False},
            )
            meta["message_count"] += 1
            if "viewing availability:" in msg.content.lower():
                meta["has_viewing_requested"] = True
            if conversation_key not in latest:
                latest[conversation_key] = msg

        results = []
        for msg in latest.values():
            conversation_counterpart = self._conversation_counterpart(msg)
            counterpart_id = str(conversation_counterpart.id)
            listing_id = str(msg.listing_id or "")
            conversation_key = f"{counterpart_id}:{listing_id}"
            listing = msg.listing
            counterpart_user = msg.receiver if msg.sender_id == request.user.id else msg.sender
            landlord_user = listing.landlord if listing else (
                request.user if request.user.role == AppUser.Role.LANDLORD else counterpart_user
            )
            tenant_user = conversation_counterpart if request.user.role == AppUser.Role.LANDLORD else (
                request.user if request.user.role == AppUser.Role.TENANT else counterpart_user
            )
            meta = conversation_meta.get(conversation_key, {})
            results.append({
                "id": str(msg.id),
                "listing_id": listing_id,
                "listing_title": listing.title if listing else "Unknown Property",
                "listing_address": listing.address if listing else "",
                "listing_city": listing.city if listing else "",
                "listing_cover_image_url": listing.cover_image_url if listing else "",
                "landlord_id": str(landlord_user.id) if landlord_user else "",
                "landlord_name": landlord_user.name if landlord_user else "Landlord",
                "landlord_profile_photo_url": landlord_user.profile_photo_url if landlord_user else None,
                "tenant_id": str(tenant_user.id) if tenant_user else "",
                "tenant_name": tenant_user.name if tenant_user else "Tenant",
                "tenant_profile_photo_url": tenant_user.profile_photo_url if tenant_user else None,
                "tenant_email": tenant_user.email if tenant_user else "",
                "last_message": msg.content,
                "last_message_time": msg.created_at,
                "message_count": meta.get("message_count", 1),
                "has_viewing_requested": meta.get("has_viewing_requested", False),
                "has_viewing_arranged": self._viewing_arranged_for(tenant_user=tenant_user, listing=listing),
                "has_rental_agreed": False,
            })

        results.sort(key=lambda r: r["last_message_time"], reverse=True)
        return Response(results)

    @action(detail=False, methods=["get"], url_path="listing/(?P<listing_id>[^/.]+)/viewing-requests")
    def listing_viewing_requests(self, request, listing_id=None):
        listing = get_object_or_404(Listing.objects.select_related("landlord"), id=listing_id)
        if request.user.role != AppUser.Role.ADMIN and listing.landlord_id != request.user.id:
            raise PermissionDenied("Only the property landlord can view tenant requests for this listing.")

        messages = (
            Message.objects
            .filter(listing=listing)
            .filter(Q(sender_role=AppUser.Role.TENANT) | Q(receiver_role=AppUser.Role.TENANT))
            .select_related("sender", "receiver")
            .order_by("-created_at")
        )
        grouped = {}
        for msg in messages:
            tenant = msg.sender if msg.sender_role == AppUser.Role.TENANT else msg.receiver
            tenant_key = str(tenant.id)
            entry = grouped.setdefault(
                tenant_key,
                {
                    "tenant": tenant,
                    "latest_message": msg,
                    "message_count": 0,
                    "has_viewing_requested": False,
                },
            )
            entry["message_count"] += 1
            if "viewing availability:" in msg.content.lower():
                entry["has_viewing_requested"] = True
            if msg.created_at > entry["latest_message"].created_at:
                entry["latest_message"] = msg

        results = []
        for entry in grouped.values():
            if not entry["has_viewing_requested"]:
                continue

            tenant = entry["tenant"]
            booking = (
                Booking.objects
                .filter(tenant=tenant, listing=listing)
                .exclude(status=Booking.Status.CANCELLED)
                .order_by("-created_at")
                .first()
            )
            results.append({
                "tenant_id": str(tenant.id),
                "tenant_name": tenant.name,
                "tenant_email": tenant.email,
                "tenant_profile_photo_url": tenant.profile_photo_url,
                "listing_id": str(listing.id),
                "booking_id": str(booking.id) if booking else "",
                "booking_status": booking.status if booking else "",
                "stage": self._rental_stage_for(booking, has_viewing_requested=entry["has_viewing_requested"]),
                "rental_progress": build_booking_progress_data(booking, AppUser.Role.LANDLORD) if booking else None,
                "last_message": entry["latest_message"].content,
                "last_message_time": entry["latest_message"].created_at,
                "message_count": entry["message_count"],
                "has_viewing_requested": entry["has_viewing_requested"],
                "has_viewing_arranged": self._viewing_arranged_for(tenant_user=tenant, listing=listing),
            })

        results.sort(key=lambda item: item["last_message_time"], reverse=True)
        return Response(results)

    @action(detail=False, methods=["post"], url_path="viewing-booked")
    def viewing_booked(self, request):
        if request.user.role != AppUser.Role.TENANT:
            raise PermissionDenied("Only tenants can mark a viewing as booked.")

        listing_id = str(request.data.get("listing_id") or "").strip()
        if not listing_id:
            raise ValidationError({"listing_id": "This field is required."})
        listing = get_object_or_404(Listing.objects.select_related("landlord"), id=listing_id)
        # Payer/payee same-identity gate, matching BookingSerializer.create.
        if listing.landlord_id == request.user.id:
            raise ValidationError({"listing_id": "You cannot rent your own property."})

        has_tenant_message = self.get_queryset().filter(
            listing=listing,
            sender=request.user,
            sender_role=AppUser.Role.TENANT,
            receiver=listing.landlord,
            receiver_role=AppUser.Role.LANDLORD,
        ).exists()
        if not has_tenant_message:
            raise PermissionDenied("Message the landlord about this listing before marking a viewing as booked.")

        with transaction.atomic():
            locked_listing = Listing.objects.select_for_update().get(pk=listing.pk)
            booking = (
                Booking.objects.select_for_update()
                .filter(tenant=request.user, listing=locked_listing)
                .exclude(status=Booking.Status.CANCELLED)
                .order_by("-created_at")
                .first()
            )
            created = booking is None
            if created:
                today = timezone.localdate()
                start_date = max(today, locked_listing.available_from or today)
                booking = Booking.objects.create(
                    tenant=request.user,
                    listing=locked_listing,
                    start_date=start_date,
                    end_date=start_date + timedelta(days=365),
                    status=Booking.Status.PENDING,
                    total_amount=None,
                )
            complete_booking_progress_step(
                booking,
                AppUser.Role.TENANT,
                "viewing_appointment_booked",
            )

        return Response(
            BookingSerializer(booking, context={"request": request}).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @action(detail=False, methods=["get"], url_path="conversations")
    def conversations(self, request):
        latest = {}
        for msg in self.get_queryset():
            counterpart_user = self._conversation_counterpart(msg)
            counterpart = str(counterpart_user.id)
            if counterpart not in latest:
                latest[counterpart] = msg
        return Response([
            {
                "counterpart_id": key,
                "counterpart_name": counterpart_user.name,
                "counterpart_role": msg.sender_role if counterpart_user.id == msg.sender_id else msg.receiver_role,
                "counterpart_profile_photo_url": counterpart_user.profile_photo_url,
                "last_message": {"id": msg.id, "content": msg.content, "created_at": msg.created_at},
                "listing_id": msg.listing_id,
            }
            for key, msg in latest.items()
            for counterpart_user in [self._conversation_counterpart(msg)]
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
            .filter(role=self.request.user.role)
            .order_by("-created_at")
        )


class ServicePaymentViewSet(viewsets.GenericViewSet, mixins.ListModelMixin):
    serializer_class = ServicePaymentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = ServicePayment.objects.select_related("user", "booking", "booking__listing", "listing").order_by("-created_at")
        if self.request.user.role != AppUser.Role.ADMIN:
            queryset = queryset.filter(user=self.request.user)
        purpose = self.request.query_params.get("purpose")
        if purpose:
            queryset = queryset.filter(purpose=purpose)
        booking_id = self.request.query_params.get("booking_id")
        if booking_id:
            queryset = queryset.filter(booking_id=booking_id)
        listing_id = self.request.query_params.get("listing_id")
        if listing_id:
            queryset = queryset.filter(listing_id=listing_id)
        return queryset

    def retrieve(self, request, pk=None):
        payment = get_object_or_404(self.get_queryset(), id=pk)
        return Response(self.get_serializer(payment).data)

    @action(detail=False, methods=["post"], url_path="request")
    def request_service_payment(self, request):
        serializer = ServicePaymentRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        purpose = serializer.validated_data["purpose"]
        booking_id = serializer.validated_data.get("booking_id")
        listing_id = serializer.validated_data.get("listing_id")

        with transaction.atomic():
            user = AppUser.objects.select_for_update().get(id=request.user.id)

            booking = None
            listing = None
            verification_roles = {
                ServicePayment.Purpose.AGENT_VERIFICATION: (
                    AppUser.Role.AGENT,
                    "Only property inspection officers can request PIO verification payments.",
                    AGENT_VERIFICATION_FEE,
                ),
                ServicePayment.Purpose.TENANT_VERIFICATION: (
                    AppUser.Role.TENANT,
                    "Only tenants can request tenant verification payments.",
                    TENANT_VERIFICATION_FEE,
                ),
                ServicePayment.Purpose.LANDLORD_VERIFICATION: (
                    AppUser.Role.LANDLORD,
                    "Only landlords can request landlord verification payments.",
                    LANDLORD_VERIFICATION_FEE,
                ),
            }
            if purpose in verification_roles:
                verification_role, denied_message, verification_fee = verification_roles[purpose]
                if request.user.role != verification_role:
                    raise PermissionDenied(denied_message)
                if booking_id:
                    raise ValidationError({"booking_id": "Identity verification is not linked to a booking."})
                if (
                    request.user.is_verified_for_role(verification_role)
                    or identity_credentials_verified(request.user, verification_role)
                ):
                    raise ValidationError("Your identity is already verified; no verification payment is required.")
                amount = quantize_money(verification_fee)
            elif purpose == ServicePayment.Purpose.LAWYER_TENANCY:
                if request.user.role != AppUser.Role.LANDLORD:
                    raise PermissionDenied("Only landlords can request lawyer tenancy agreement payments.")
                if not booking_id:
                    raise ValidationError({"booking_id": "A booking is required for a lawyer tenancy agreement."})
                booking = get_object_or_404(
                    Booking.objects.select_for_update().select_related("listing", "listing__landlord"),
                    id=booking_id,
                )
                if booking.listing.landlord_id != user.id:
                    raise PermissionDenied("You can only request a lawyer service for your own booking.")
                if booking.status == Booking.Status.CANCELLED:
                    raise ValidationError("A lawyer service cannot be requested for a cancelled booking.")
                amount = lawyer_service_fee_for_booking(booking)
            elif purpose == ServicePayment.Purpose.IN_PERSON_VERIFICATION:
                if request.user.role != AppUser.Role.LANDLORD:
                    raise PermissionDenied("Only landlords can request in-person verification payments.")
                if not listing_id:
                    raise ValidationError({"listing_id": "A listing is required for in-person verification."})
                listing = get_object_or_404(Listing.objects.select_for_update(), id=listing_id)
                if listing.landlord_id != user.id:
                    raise PermissionDenied("You can only request verification for your own listing.")
                submission = listing.property_document_submission or {}
                if not submission.get("in_person_verification_requested"):
                    raise ValidationError("In-person verification was not selected for this listing.")
                amount = quantize_money(IN_PERSON_VERIFICATION_FEE)
            else:
                raise ValidationError({"purpose": "Unsupported service payment purpose."})

            existing_filter = {"user": user, "purpose": purpose, "booking": booking}
            if purpose == ServicePayment.Purpose.IN_PERSON_VERIFICATION:
                existing_filter["listing"] = listing
            existing = (
                ServicePayment.objects.filter(**existing_filter)
                .order_by("-created_at")
            )
            completed = existing.filter(status=ServicePayment.Status.COMPLETED).first()
            if completed:
                # A completed identity verification payment covers a fixed
                # number of attempts. Once those are used, a new payment is
                # required.
                if purpose in verification_roles:
                    completed_count = existing.filter(status=ServicePayment.Status.COMPLETED).count()
                    attempts_used = identity_verification_attempts_used(user, verification_roles[purpose][0])
                    if attempts_used < completed_count * IDENTITY_VERIFICATION_ATTEMPTS_PER_PAYMENT:
                        return Response(self.get_serializer(completed).data)
                else:
                    return Response(self.get_serializer(completed).data)
            pending = existing.filter(status=ServicePayment.Status.PENDING).first()
            if pending:
                return Response(self.get_serializer(pending).data)

            payment = ServicePayment.objects.create(
                user=user,
                booking=booking,
                listing=listing,
                purpose=purpose,
                amount=amount,
                transaction_id=build_service_payment_reference(),
            )
            return Response(self.get_serializer(payment).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="flutterwave/checkout")
    def flutterwave_checkout(self, request, pk=None):
        payment = get_object_or_404(self.get_queryset(), id=pk)
        if payment.status != ServicePayment.Status.PENDING:
            raise ValidationError("Payment is not pending")

        checkout = build_service_checkout(payment)
        payment.provider_payload = update_payment_provider_payload(
            payment.provider_payload,
            None,
            checkout=checkout,
            return_url=build_service_payment_return_url(payment),
        )
        payment.provider = "flutterwave"
        payment.save(update_fields=["provider_payload", "provider", "updated_at"])
        return Response({"payment": self.get_serializer(payment).data, "checkout": checkout})

    @action(detail=False, methods=["get"], url_path="flutterwave/verify")
    def flutterwave_verify(self, request):
        reference = (request.query_params.get("reference") or request.query_params.get("tx_ref") or "").strip()
        if not reference:
            raise ValidationError({"reference": "Payment reference is required."})

        payment = get_object_or_404(self.get_queryset(), transaction_id=reference)
        try:
            payment = sync_service_payment(
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
        block_production_mock("Simulated service payment")
        payment = get_object_or_404(self.get_queryset(), id=pk)
        complete_service_payment(
            payment,
            webhook_data={"eventType": "MOCK.TRANSACTION.SUCCESS", "source": "simulate_pay"},
        )
        return Response(self.get_serializer(payment).data)


class AgentViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def _require_agent(self, request):
        if request.user.role != AppUser.Role.AGENT:
            raise PermissionDenied("Only property inspection officers can access these services.")

    def _profile(self, user) -> AgentProfile:
        profile, _created = AgentProfile.objects.get_or_create(
            user=user,
            defaults={"first_name": "", "last_name": ""},
        )
        prefill_role_identity(user, AppUser.Role.AGENT)
        profile.refresh_from_db()
        return profile

    @action(detail=False, methods=["get", "patch"], url_path="profile")
    def profile(self, request):
        self._require_agent(request)
        profile = self._profile(request.user)
        if request.method == "GET":
            return Response(AgentProfileSerializer(profile, context={"request": request}).data)

        serializer = AgentProfileSerializer(
            profile, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        profile = serializer.save()

        user = request.user
        user_updates: list[str] = []
        name_parts = [profile.first_name, profile.middle_name, profile.last_name]
        display_name = " ".join(part for part in name_parts if part).strip()
        if display_name and user.name != display_name:
            user.name = display_name
            user_updates.append("name")
        for user_field, profile_field in (
            ("mobile", "mobile"),
            ("whatsapp_number", "whatsapp_number"),
            ("nin_number", "nin_number"),
            ("bvn_number", "bvn_number"),
            ("state_of_origin", "state_of_origin"),
        ):
            value = getattr(profile, profile_field, "")
            if value and getattr(user, user_field) != value:
                setattr(user, user_field, value)
                user_updates.append(user_field)
        if user_updates:
            user_updates.append("updated_at")
            user.save(update_fields=user_updates)
        return Response(AgentProfileSerializer(profile, context={"request": request}).data)

    @action(detail=False, methods=["post"], url_path="verify")
    def verify(self, request):
        self._require_agent(request)
        profile = self._profile(request.user)
        if profile.verification_status == AgentProfile.VerificationStatus.VERIFIED:
            return Response(AgentProfileSerializer(profile, context={"request": request}).data)

        missing = [
            field
            for field in AGENT_PROFILE_REQUIRED_FIELDS
            if not _has_submitted_value(getattr(profile, field, None))
        ]
        if missing:
            raise ValidationError(
                {"profile": f"Complete your PIO profile before verification. Missing: {', '.join(missing)}."}
            )

        identity_data = {
            "first_name": profile.first_name,
            "middle_name": profile.middle_name,
            "last_name": profile.last_name,
            "date_of_birth": profile.date_of_birth.isoformat() if profile.date_of_birth else None,
            "gender": profile.gender,
            "country_of_birth": profile.country_of_birth,
            "nationality": profile.nationality,
            "state_of_origin": profile.state_of_origin,
            "lga": profile.lga_of_origin,
            "mobile": profile.mobile,
        }
        submitted_identity = {
            **identity_data,
            "nin_number": profile.nin_number,
            "bvn_number": profile.bvn_number,
        }
        if verified_identity_matches(
            request.user, submitted_identity, credential_fields=("nin_number", "bvn_number")
        ):
            # Same credentials already verified under another persona — no
            # provider call, no fee, and no paid attempt consumed.
            verification_payloads = {}
        else:
            require_unique_identity_credentials(request.user, profile.nin_number, profile.bvn_number)
            require_identity_verification_payment(request.user, AppUser.Role.AGENT)
            try:
                verification_payloads = verify_nin_and_bvn(identity_data, profile.nin_number, profile.bvn_number)
            except ValidationError:
                profile.verification_attempts += 1
                profile.save(update_fields=["verification_attempts", "updated_at"])
                raise

        verified_at = timezone.now()
        update_fields = ["verification_status", "verified_at", "updated_at"]
        if verification_payloads:
            profile.verification_attempts += 1
            update_fields.insert(0, "verification_attempts")
        profile.verification_status = AgentProfile.VerificationStatus.VERIFIED
        profile.verified_at = verified_at
        profile.save(update_fields=update_fields)

        verification, _ = VerificationRequest.objects.get_or_create(
            user=request.user,
            role=AppUser.Role.AGENT,
            defaults={
                "request_type": VerificationRequest.RequestType.IDENTIFICATION,
            },
        )
        verification.request_type = VerificationRequest.RequestType.IDENTIFICATION
        verification.submitted_at = verified_at
        verification.identity_verification_status = VerificationRequest.VerificationProgressStatus.VERIFIED
        verification.verification_method = VerificationRequest.Method.AUTOMATED
        verification.status = VerificationRequest.Status.APPROVED
        verification.reviewed_at = verified_at
        verification.save(
            update_fields=[
                "request_type",
                "submitted_at",
                "status",
                "identity_verification_status",
                "verification_method",
                "reviewed_at",
            ]
        )

        user = request.user
        user.nin_number = profile.nin_number
        user.bvn_number = profile.bvn_number
        user.save(update_fields=["nin_number", "bvn_number", "updated_at"])

        data = AgentProfileSerializer(profile, context={"request": request}).data
        mobile_warning = extract_mobile_verification_warning(verification_payloads)
        if mobile_warning:
            data["mobile_warning"] = mobile_warning
        return Response(data)

    @action(detail=False, methods=["get"], url_path="referrals")
    def referrals(self, request):
        self._require_agent(request)
        return Response(build_referral_tree(request.user))

    @action(detail=False, methods=["get"], url_path="dashboard")
    def dashboard(self, request):
        self._require_agent(request)
        profile = self._profile(request.user)
        verification_payment = (
            ServicePayment.objects.filter(
                user=request.user, purpose=ServicePayment.Purpose.AGENT_VERIFICATION
            )
            .order_by("-created_at")
            .first()
        )
        own_inspections = (
            PropertyInspection.objects.select_related("listing", "listing__landlord")
            .filter(agent=request.user)
            .order_by("-created_at")
        )
        if profile.verification_status == AgentProfile.VerificationStatus.VERIFIED:
            now = timezone.now()
            available_listings = (
                Listing.objects.filter(
                    physical_property_status=VerificationRequest.VerificationProgressStatus.PENDING,
                    property_document_submission__in_person_verification_requested=True,
                )
                .exclude(inspection__isnull=False)
                .exclude(
                    inspection_requests__status=InspectionRequest.Status.PENDING,
                    inspection_requests__expires_at__gt=now,
                )
                .exclude(
                    inspection_requests__status=InspectionRequest.Status.ACCEPTED,
                )
                .select_related("landlord")
                .prefetch_related("images")
                .order_by("-created_at")
            )
            offered_listings = (
                Listing.objects.filter(
                    physical_property_status=VerificationRequest.VerificationProgressStatus.PENDING,
                    property_document_submission__in_person_verification_requested=True,
                    inspection_requests__agent=request.user,
                    inspection_requests__status=InspectionRequest.Status.PENDING,
                    inspection_requests__expires_at__gt=now,
                )
                .exclude(inspection__isnull=False)
                .select_related("landlord")
                .prefetch_related("images")
                .order_by("-created_at")
            )
            available_listings = (available_listings | offered_listings).distinct()
        else:
            available_listings = Listing.objects.none()
        inspection_requests = (
            InspectionRequest.objects.filter(agent=request.user)
            .select_related("listing", "listing__landlord")
            .prefetch_related("listing__images")
            .order_by("-created_at")[:20]
        )
        submitted = own_inspections.filter(status=PropertyInspection.Status.SUBMITTED)
        totals = submitted.aggregate(
            total_earned=Sum("earning_amount"),
            total_paid=Sum("earning_amount", filter=Q(payout_status=PropertyInspection.PayoutStatus.PAID)),
            pending_payout=Sum(
                "earning_amount", filter=Q(payout_status=PropertyInspection.PayoutStatus.PENDING)
            ),
        )
        return Response(
            {
                "profile": AgentProfileSerializer(profile, context={"request": request}).data,
                "verification_payment": (
                    ServicePaymentSerializer(verification_payment, context={"request": request}).data
                    if verification_payment
                    else None
                ),
                "available_inspections": AgentInspectionListingSerializer(
                    available_listings, many=True, context={"request": request}
                ).data,
                "inspection_requests": InspectionRequestSerializer(
                    inspection_requests, many=True, context={"request": request}
                ).data,
                "inspections": PropertyInspectionSerializer(
                    own_inspections, many=True, context={"request": request}
                ).data,
                "metrics": {
                    "properties_inspected": submitted.count(),
                    "total_amount_earned": str(totals["total_earned"] or ZERO_AMOUNT),
                    "total_amount_paid_out": str(totals["total_paid"] or ZERO_AMOUNT),
                    "pending_payout": str(totals["pending_payout"] or ZERO_AMOUNT),
                },
            }
        )


class AgentInspectionViewSet(viewsets.GenericViewSet, mixins.ListModelMixin, mixins.RetrieveModelMixin):
    serializer_class = PropertyInspectionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = PropertyInspection.objects.select_related(
            "listing", "listing__landlord", "agent"
        ).prefetch_related("evidence_documents").order_by("-created_at")
        if self.request.user.role == AppUser.Role.ADMIN:
            return queryset
        return queryset.filter(agent=self.request.user)

    def _require_agent(self, request):
        if request.user.role != AppUser.Role.AGENT:
            raise PermissionDenied("Only property inspection officers can manage property inspections.")

    @action(detail=False, methods=["get"], url_path="checklist")
    def checklist(self, request):
        return Response(INSPECTION_CHECKLIST_SCHEMA)

    @action(detail=False, methods=["post"], url_path="claim")
    def claim(self, request):
        self._require_agent(request)
        listing_id = request.data.get("listing_id")
        if not listing_id:
            raise ValidationError({"listing_id": "A listing is required."})
        listing = get_object_or_404(Listing, id=listing_id)
        # Conflict of interest: the PIO must not be the listing's landlord or a tenant of it.
        if listing.landlord_id == request.user.id or Booking.objects.filter(
            tenant=request.user, listing=listing
        ).exists():
            raise PermissionDenied(
                "You cannot inspect a property in which you have an ownership or tenancy interest."
            )
        profile = AgentProfile.objects.filter(user=request.user).first()
        if not profile or profile.verification_status != AgentProfile.VerificationStatus.VERIFIED:
            raise PermissionDenied("Complete PIO verification before claiming inspections.")

        submission = (
            listing.property_document_submission
            if isinstance(listing.property_document_submission, dict)
            else {}
        )
        if not submission.get("in_person_verification_requested"):
            raise ValidationError("This listing has not requested an in-person inspection.")
        if listing.physical_property_status != VerificationRequest.VerificationProgressStatus.PENDING:
            raise ValidationError("This listing is not awaiting a physical inspection.")

        own_request = (
            InspectionRequest.objects.filter(listing=listing, agent=request.user)
            .order_by("-created_at")
            .first()
        )
        if own_request is not None:
            if own_request.status == InspectionRequest.Status.PENDING and own_request.expires_at <= timezone.now():
                own_request.status = InspectionRequest.Status.EXPIRED
                own_request.save(update_fields=["status", "updated_at"])
                raise ValidationError("This inspection request has expired.")
            if own_request.status != InspectionRequest.Status.PENDING:
                raise ValidationError("This inspection request is no longer available.")
        elif listing.inspection_requests.filter(
            status=InspectionRequest.Status.PENDING, expires_at__gt=timezone.now()
        ).exists():
            raise PermissionDenied(
                "This inspection was offered to the PIOs closest to the property."
            )

        earning_amount = decimal_setting("AGENT_INSPECTION_EARNING_NGN", "0.00")
        try:
            with transaction.atomic():
                inspection = PropertyInspection.objects.create(
                    listing=listing,
                    agent=request.user,
                    earning_amount=earning_amount,
                )
                mark_requests_resolved(listing, accepted_agent=request.user)
        except IntegrityError:
            raise ValidationError("This listing already has an inspection assigned.")
        return Response(
            self.get_serializer(inspection, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    def partial_update(self, request, pk=None):
        inspection = self.get_object()
        if request.user.role != AppUser.Role.ADMIN and inspection.agent_id != request.user.id:
            raise PermissionDenied("You can only update your own inspections.")
        if inspection.status == PropertyInspection.Status.SUBMITTED:
            raise ValidationError("Submitted inspections cannot be modified.")
        serializer = self.get_serializer(inspection, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="submit")
    def submit(self, request, pk=None):
        submitted_responses = request.data.get("responses")
        if submitted_responses is not None and not isinstance(submitted_responses, dict):
            raise ValidationError({"responses": "Responses must be an object."})

        with transaction.atomic():
            inspection = get_object_or_404(
                PropertyInspection.objects.select_for_update()
                .select_related("listing", "listing__landlord", "agent"),
                id=pk,
            )
            if inspection.agent_id != request.user.id:
                raise PermissionDenied("You can only submit your own inspections.")
            if inspection.status == PropertyInspection.Status.SUBMITTED:
                raise ValidationError("This inspection has already been submitted.")

            responses = dict(inspection.responses or {})
            if submitted_responses is not None:
                responses.update(submitted_responses)
            responses = validate_inspection_responses(responses, require_complete=True)
            analysis = build_inspection_analysis(responses)

            now = timezone.now()
            inspection.responses = responses
            inspection.analysis = analysis
            inspection.overall_status = responses.get("overall_status", "")
            inspection.status = PropertyInspection.Status.SUBMITTED
            inspection.submitted_at = now
            inspection.signed_off_at = now
            inspection.save(
                update_fields=[
                    "responses",
                    "analysis",
                    "overall_status",
                    "status",
                    "submitted_at",
                    "signed_off_at",
                    "updated_at",
                ]
            )

            if (
                inspection.overall_status
                in {
                    "inspection_completed",
                    "inspection_completed_with_issues",
                }
                and not analysis["critical_red_flags"]
            ):
                listing = Listing.objects.select_for_update().get(pk=inspection.listing_id)
                listing.physical_property_status = VerificationRequest.VerificationProgressStatus.VERIFIED
                listing.save(update_fields=["physical_property_status", "updated_at"])

            award_referral_earning(inspection)

        return Response(self.get_serializer(inspection, context={"request": request}).data)

    @action(detail=True, methods=["get"], url_path="pdf")
    def pdf(self, request, pk=None):
        inspection = get_object_or_404(
            PropertyInspection.objects.select_related("listing", "listing__landlord", "agent")
            .prefetch_related("evidence_documents"),
            id=pk,
        )
        if request.user.role != AppUser.Role.ADMIN and inspection.agent_id != request.user.id:
            raise PermissionDenied("You can only download your own inspection reports.")
        if inspection.status != PropertyInspection.Status.SUBMITTED:
            raise ValidationError("The inspection report is available after submission.")
        content = build_inspection_report_pdf(inspection, INSPECTION_CHECKLIST_SCHEMA)
        response = HttpResponse(content, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="inspection-{inspection.id}.pdf"'
        return response


class SupportChatMessageViewSet(viewsets.GenericViewSet, mixins.ListModelMixin):
    serializer_class = SupportChatMessageSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = SupportChatMessage.objects.select_related("thread_user", "sender").order_by("-created_at")
        if self.request.user.role in {AppUser.Role.TENANT, AppUser.Role.LANDLORD, AppUser.Role.AGENT}:
            return queryset.filter(thread_user=self.request.user, thread_role=self.request.user.role)

        thread_user_id = (
            self.request.query_params.get("user_id")
            or self.request.query_params.get("tenant_id")
            or self.request.query_params.get("landlord_id")
            or self.request.query_params.get("agent_id")
            or self.request.query_params.get("thread_user")
        )
        if thread_user_id:
            thread_user = AppUser.objects.filter(id=thread_user_id).first()
            if thread_user is None:
                return queryset.none()
            thread_role = (
                self.request.query_params.get("thread_role")
                or self.request.query_params.get("active_role")
                or thread_user.role
            )
            if not has_active_role(thread_user, thread_role):
                raise PermissionDenied("The selected role is not active for this account.")
            return queryset.filter(thread_user_id=thread_user_id, thread_role=thread_role)
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
            "total_landlords": users_with_role(User.objects.all(), AppUser.Role.LANDLORD).count(),
            "total_tenants": users_with_role(User.objects.all(), AppUser.Role.TENANT).count(),
            "total_agents": users_with_role(User.objects.all(), AppUser.Role.AGENT).count(),
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
def financial_config(request):
    return Response(
        {
            "refundable_caution_fee_rate": str(REFUNDABLE_CAUTION_FEE_RATE),
            "administration_fee_rate": str(ADMINISTRATION_FEE_RATE),
            "administration_fee_vat_rate": str(ADMINISTRATION_FEE_VAT_RATE),
            "listing_deposit_rate": str(LISTING_DEPOSIT_RATE),
            "listing_deposit_hold_days": DEPOSIT_LISTING_HOLD_DAYS,
            "payment_cancellation_admin_fee_rate": str(PAYMENT_CANCELLATION_ADMIN_FEE_RATE),
            "card_payment_limit": str(CARD_PAYMENT_LIMIT_NGN),
            "account_freeze_fee_percentage": str(ACCOUNT_FREEZE_FEE_PERCENTAGE),
            "subscription_vat_rate_percent": str(DEFAULT_SUBSCRIPTION_VAT_RATE_PERCENT),
            "featured_property_monthly_fee": str(FEATURED_PROPERTY_MONTHLY_FEE),
            "featured_property_monthly_duration_days": FEATURED_PROPERTY_MONTHLY_DURATION_DAYS,
            "featured_property_min_duration_days": FEATURED_PROPERTY_MIN_DURATION_DAYS,
            "featured_property_max_duration_days": FEATURED_PROPERTY_MAX_DURATION_DAYS,
        }
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def representative_kyc_public_detail(request, token):
    kyc = get_object_or_404(
        RepresentativeKyc.objects.select_related("landlord", "listing"),
        token=token,
    )
    return Response(
        {
            "token": str(kyc.token),
            "status": kyc.status,
            "ownership_type": kyc.ownership_type,
            "landlord_name": kyc.landlord.name or kyc.landlord.email,
            "listing_title": kyc.listing.title if kyc.listing else "",
            "name": kyc.name,
            "email": kyc.email,
            "phone": kyc.phone,
            "return_url": kyc.return_url,
            "submitted_at": kyc.submitted_at,
            "verified_at": kyc.verified_at,
        }
    )


@api_view(["POST"])
@permission_classes([AllowAny])
def representative_kyc_public_submit(request, token):
    kyc = get_object_or_404(RepresentativeKyc, token=token)
    if kyc.status in {RepresentativeKyc.Status.SUBMITTED, RepresentativeKyc.Status.VERIFIED}:
        return Response(
            {"status": kyc.status, "return_url": kyc.return_url, "detail": "This KYC has already been submitted."}
        )

    name = str(request.data.get("name") or "").strip()
    phone = str(request.data.get("phone") or "").strip()
    nin_number = str(request.data.get("nin_number") or "").strip()
    if not name:
        raise ValidationError({"name": "Representative name is required."})
    if not phone:
        raise ValidationError({"phone": "Representative phone number is required."})
    if nin_number and not is_valid_nin(nin_number):
        raise ValidationError({"nin_number": "Enter a valid 11-digit NIN."})

    date_of_birth = str(request.data.get("date_of_birth") or "").strip() or None
    kyc.name = name
    kyc.email = str(request.data.get("email") or "").strip()
    kyc.phone = phone
    kyc.nin_number = nin_number
    if date_of_birth:
        kyc.date_of_birth = date_of_birth
    if request.FILES.get("passport_photo"):
        kyc.passport_photo = request.FILES["passport_photo"]
    if request.FILES.get("id_document"):
        kyc.id_document = request.FILES["id_document"]
    kyc.submitted_at = timezone.now()

    verification_payload: dict[str, Any] | None = None
    if nin_number:
        first_name, _, last_name = name.partition(" ")
        identity_data = {
            "first_name": first_name,
            "last_name": last_name,
            "date_of_birth": date_of_birth,
            "mobile": phone,
        }
        try:
            verification_payload = verify_nin(identity_data, nin_number)
            kyc.status = RepresentativeKyc.Status.VERIFIED
            kyc.verified_at = timezone.now()
        except APIException as exc:
            verification_payload = {"error": str(getattr(exc, "detail", exc))}
            kyc.status = RepresentativeKyc.Status.SUBMITTED
        except Exception as exc:
            verification_payload = {"error": str(exc)}
            kyc.status = RepresentativeKyc.Status.SUBMITTED
    else:
        kyc.status = RepresentativeKyc.Status.SUBMITTED

    kyc.verification_payload = verification_payload
    kyc.save()

    return Response(
        {
            "status": kyc.status,
            "return_url": kyc.return_url,
            "detail": "KYC verification completed." if kyc.status == RepresentativeKyc.Status.VERIFIED else "KYC submitted and pending verification.",
        }
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def homepage_video(request):
    storage_response = homepage_video_storage_response(request)
    if storage_response is not None:
        return storage_response

    video_path = homepage_video_source_path()
    if video_path is None:
        raise Http404("Homepage video not found")

    return homepage_video_file_response(request, video_path)


def homepage_video_storage_response(request):
    storage_name = str(getattr(settings, "HOMEPAGE_VIDEO_STORAGE_NAME", "") or "").strip()
    if not storage_name:
        return None

    try:
        if not default_storage.exists(storage_name):
            return None

        try:
            video_path = Path(default_storage.path(storage_name))
        except (AttributeError, NotImplementedError):
            video_url = default_storage.url(storage_name)
            if video_url.startswith("//"):
                video_url = f"{request.scheme}:{video_url}"

            response = HttpResponseRedirect(video_url)
            response["Cache-Control"] = "public, max-age=3600"
            return response

        if video_path.exists():
            return homepage_video_file_response(request, video_path)
    except Exception:
        logger.exception("Could not resolve homepage video from configured storage.")

    return None


def homepage_video_source_path() -> Path | None:
    source_paths = []
    source_path = str(getattr(settings, "HOMEPAGE_VIDEO_SOURCE_PATH", "") or "").strip()
    if source_path:
        path = Path(source_path)
        source_paths.append(path if path.is_absolute() else settings.BASE_DIR / path)

    source_paths.append(settings.BASE_DIR / "media" / "video" / "rentdirect.mp4")

    for path in source_paths:
        if path.exists():
            return path

    return None


def homepage_video_file_response(request, video_path: Path):
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
