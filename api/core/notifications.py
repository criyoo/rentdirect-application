from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

RENTDIRECT_INFO_EMAIL = "info@rentdirect.homes"


def send_payment_confirmation_to_landlord(
    *,
    landlord_email: str,
    landlord_name: str,
    tenant_name: str,
    tenant_email: str,
    listing_title: str,
    amount: Decimal,
    transaction_id: str,
    payment_date: str,
    booking_id: str,
) -> None:
    """Email #1: When tenant makes a successful payment, notify landlord with tenant + RentDirect in CC."""
    subject = f"Rental Payment Received — {listing_title}"
    context = {
        "landlord_name": landlord_name,
        "tenant_name": tenant_name,
        "tenant_email": tenant_email,
        "listing_title": listing_title,
        "amount": f"₦{amount:,.2f}",
        "transaction_id": transaction_id,
        "payment_date": payment_date,
        "booking_id": booking_id,
    }
    text_body = (
        f"Dear {landlord_name},\n\n"
        f"Your tenant {tenant_name} ({tenant_email}) has made a rental payment "
        f"of {context['amount']} for {listing_title}.\n\n"
        f"Transaction ID: {transaction_id}\n"
        f"Date: {payment_date}\n"
        f"Booking Reference: {booking_id}\n\n"
        f"Funds will be held securely by RentDirect until all tenancy conditions are met.\n\n"
        f"Thank you for using RentDirect.\n"
        f"RentDirect Team"
    )
    html_body = _render_email_template(
        title="Rental Payment Received",
        heading="Payment Confirmation",
        body_html=(
            f"<p>Dear <strong>{landlord_name}</strong>,</p>"
            f"<p>Your tenant <strong>{tenant_name}</strong> ({tenant_email}) has made a rental payment for "
            f"<strong>{listing_title}</strong>.</p>"
            f"<table style='width:100%;border-collapse:collapse;margin:16px 0;'>"
            f"<tr><td style='padding:8px;border-bottom:1px solid #ddd;color:#666;'>Amount</td>"
            f"<td style='padding:8px;border-bottom:1px solid #ddd;font-weight:bold;'>{context['amount']}</td></tr>"
            f"<tr><td style='padding:8px;border-bottom:1px solid #ddd;color:#666;'>Transaction ID</td>"
            f"<td style='padding:8px;border-bottom:1px solid #ddd;'>{transaction_id}</td></tr>"
            f"<tr><td style='padding:8px;border-bottom:1px solid #ddd;color:#666;'>Date</td>"
            f"<td style='padding:8px;border-bottom:1px solid #ddd;'>{payment_date}</td></tr>"
            f"</table>"
            f"<p>Funds will be held securely by RentDirect until all tenancy conditions are met before "
            f"being transferred to your account.</p>"
            f"<p>Thank you for using RentDirect.</p>"
            f"<p><em>RentDirect Team</em></p>"
        ),
    )

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[landlord_email],
        cc=[tenant_email, RENTDIRECT_INFO_EMAIL],
        reply_to=[RENTDIRECT_INFO_EMAIL],
    )
    msg.attach_alternative(html_body, "text/html")
    msg.send(fail_silently=False)


def send_landlord_payout_notification(
    *,
    landlord_email: str,
    landlord_name: str,
    tenant_name: str,
    tenant_email: str,
    listing_title: str,
    amount: Decimal,
    bank_name: str,
    account_name: str,
    account_number: str,
    settlement_id: str,
) -> None:
    """Email #2: When a transfer to landlord account is triggered (recipient created)."""
    subject = f"Landlord Payout Initiated — {listing_title}"
    context = {
        "landlord_name": landlord_name,
        "tenant_name": tenant_name,
        "tenant_email": tenant_email,
        "listing_title": listing_title,
        "amount": f"₦{amount:,.2f}",
        "bank_name": bank_name,
        "account_name": account_name,
        "account_number": account_number,
        "settlement_id": settlement_id,
    }
    text_body = (
        f"Dear {landlord_name},\n\n"
        f"A payout of {context['amount']} for {listing_title} has been initiated to your account.\n\n"
        f"Bank: {bank_name}\n"
        f"Account Name: {account_name}\n"
        f"Account Number: {account_number}\n"
        f"Reference: {settlement_id}\n\n"
        f"This amount represents the rent due after RentDirect's service fees have been deducted.\n\n"
        f"Thank you for using RentDirect.\n"
        f"RentDirect Team"
    )
    html_body = _render_email_template(
        title="Landlord Payout Initiated",
        heading="Payout Notification",
        body_html=(
            f"<p>Dear <strong>{landlord_name}</strong>,</p>"
            f"<p>A payout for <strong>{listing_title}</strong> (tenant: {tenant_name}) "
            f"has been initiated to your bank account.</p>"
            f"<table style='width:100%;border-collapse:collapse;margin:16px 0;'>"
            f"<tr><td style='padding:8px;border-bottom:1px solid #ddd;color:#666;'>Amount</td>"
            f"<td style='padding:8px;border-bottom:1px solid #ddd;font-weight:bold;'>{context['amount']}</td></tr>"
            f"<tr><td style='padding:8px;border-bottom:1px solid #ddd;color:#666;'>Bank</td>"
            f"<td style='padding:8px;border-bottom:1px solid #ddd;'>{bank_name}</td></tr>"
            f"<tr><td style='padding:8px;border-bottom:1px solid #ddd;color:#666;'>Account Name</td>"
            f"<td style='padding:8px;border-bottom:1px solid #ddd;'>{account_name}</td></tr>"
            f"<tr><td style='padding:8px;border-bottom:1px solid #ddd;color:#666;'>Account Number</td>"
            f"<td style='padding:8px;border-bottom:1px solid #ddd;'>{account_number}</td></tr>"
            f"</table>"
            f"<p>This is the rent due after RentDirect's service fees have been deducted. "
            f"Funds should reflect in your account within 1–2 business days.</p>"
            f"<p>Thank you for using RentDirect.</p>"
            f"<p><em>RentDirect Team</em></p>"
        ),
    )

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[landlord_email],
        cc=[tenant_email, RENTDIRECT_INFO_EMAIL],
        reply_to=[RENTDIRECT_INFO_EMAIL],
    )
    msg.attach_alternative(html_body, "text/html")
    msg.send(fail_silently=False)


def send_rentdirect_internal_transfer_notification(
    *,
    purpose: str,
    amount: Decimal,
    bank_name: str,
    account_name: str,
    account_number: str,
    listing_title: str,
    tenant_name: str,
    tenant_email: str,
    landlord_name: str,
    landlord_email: str,
    settlement_id: str,
) -> None:
    """Email #3: When transfer is triggered to RentDirect accounts (Operations or Caution Fee)."""
    purpose_label = "RentDirect Operations Fee" if purpose == "operations" else "Tenant Caution Fee"
    subject = f"Internal Transfer Initiated — {purpose_label}"
    text_body = (
        f"An internal transfer has been initiated:\n\n"
        f"Purpose: {purpose_label}\n"
        f"Amount: ₦{amount:,.2f}\n"
        f"Bank: {bank_name}\n"
        f"Account Name: {account_name}\n"
        f"Account Number: {account_number}\n"
        f"Reference: {settlement_id}\n\n"
        f"Listing: {listing_title}\n"
        f"Tenant: {tenant_name} ({tenant_email})\n"
        f"Landlord: {landlord_name} ({landlord_email})\n"
        f"Date: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"RentDirect Finance"
    )
    html_body = _render_email_template(
        title="Internal Transfer Initiated",
        heading=purpose_label,
        body_html=(
            f"<p>An internal transfer has been initiated:</p>"
            f"<table style='width:100%;border-collapse:collapse;margin:16px 0;'>"
            f"<tr><td style='padding:8px;border-bottom:1px solid #ddd;color:#666;'>Purpose</td>"
            f"<td style='padding:8px;border-bottom:1px solid #ddd;font-weight:bold;'>{purpose_label}</td></tr>"
            f"<tr><td style='padding:8px;border-bottom:1px solid #ddd;color:#666;'>Amount</td>"
            f"<td style='padding:8px;border-bottom:1px solid #ddd;font-weight:bold;'>₦{amount:,.2f}</td></tr>"
            f"<tr><td style='padding:8px;border-bottom:1px solid #ddd;color:#666;'>Bank</td>"
            f"<td style='padding:8px;border-bottom:1px solid #ddd;'>{bank_name}</td></tr>"
            f"<tr><td style='padding:8px;border-bottom:1px solid #ddd;color:#666;'>Account Name</td>"
            f"<td style='padding:8px;border-bottom:1px solid #ddd;'>{account_name}</td></tr>"
            f"<tr><td style='padding:8px;border-bottom:1px solid #ddd;color:#666;'>Account Number</td>"
            f"<td style='padding:8px;border-bottom:1px solid #ddd;'>{account_number}</td></tr>"
            f"<tr><td style='padding:8px;border-bottom:1px solid #ddd;color:#666;'>Listing</td>"
            f"<td style='padding:8px;border-bottom:1px solid #ddd;'>{listing_title}</td></tr>"
            f"<tr><td style='padding:8px;border-bottom:1px solid #ddd;color:#666;'>Tenant</td>"
            f"<td style='padding:8px;border-bottom:1px solid #ddd;'>{tenant_name} ({tenant_email})</td></tr>"
            f"<tr><td style='padding:8px;border-bottom:1px solid #ddd;color:#666;'>Landlord</td>"
            f"<td style='padding:8px;border-bottom:1px solid #ddd;'>{landlord_name} ({landlord_email})</td></tr>"
            f"</table>"
            f"<p>RentDirect Finance</p>"
        ),
    )

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[RENTDIRECT_INFO_EMAIL],
        reply_to=[RENTDIRECT_INFO_EMAIL],
    )
    msg.attach_alternative(html_body, "text/html")
    msg.send(fail_silently=False)


def _render_email_template(*, title: str, heading: str, body_html: str) -> str:
    """Render a minimal HTML email template."""
    return (
        "<!DOCTYPE html>"
        "<html><head><meta charset='utf-8'>"
        f"<title>{title}</title>"
        "</head><body style='margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,\"Segoe UI\",Roboto,sans-serif;background:#f5f5f5;'>"
        "<table width='100%' cellpadding='0' cellspacing='0'><tr><td align='center' style='padding:32px 16px;'>"
        "<table width='560' cellpadding='0' cellspacing='0' style='max-width:560px;width:100%;background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);'>"
        "<tr><td style='padding:24px 32px;background:#1a1a2e;text-align:center;'>"
        f"<h1 style='margin:0;color:#ffffff;font-size:20px;font-weight:600;'>{heading}</h1>"
        "</td></tr>"
        "<tr><td style='padding:32px;font-size:15px;line-height:1.6;color:#333333;'>"
        f"{body_html}"
        "</td></tr>"
        "<tr><td style='padding:16px 32px;border-top:1px solid #eee;font-size:12px;color:#999;text-align:center;'>"
        "<p style='margin:0;'>RentDirect &mdash; Making Renting Simple</p>"
        "<p style='margin:4px 0 0;'>"
        f"<a href='mailto:{RENTDIRECT_INFO_EMAIL}' style='color:#1a1a2e;text-decoration:none;'>{RENTDIRECT_INFO_EMAIL}</a></p>"
        "</td></tr>"
        "</table></td></tr></table></body></html>"
    )
