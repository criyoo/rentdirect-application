# RentDirect VAT Processing and Payment Destinations

## 1. Purpose and scope

This document describes how RentDirect calculates, collects, records, splits, and transfers VAT for:

1. Paid tenant and landlord subscriptions.
2. Rental-booking administration fees.

It also documents the destination accounts used by the application and the operational checks required before enabling Flutterwave payments.

The implementation is in the `apps/api` Django application. The web application displays the rate and payment breakdown returned by the API; it does not calculate or settle VAT.

## 2. VAT rate and monetary rules

The configured subscription VAT rate is read from:

```text
SUBSCRIPTION_VAT_RATE_PERCENT
```

The default is `7.5`. The backend stores the rate in a two-decimal `DecimalField`, so API/database values may appear as `7.50`. The web payment review page normalizes the display to `7.5%`.

All VAT amounts are calculated with `Decimal` arithmetic and rounded to two monetary decimal places using `ROUND_HALF_UP`.

### 2.1 Paid subscriptions

For a paid subscription:

```text
subscription VAT = subscription fee × 7.5%
total charged     = subscription fee + subscription VAT
```

Example:

```text
Subscription fee:  NGN 1,000.00
VAT at 7.5%:       NGN    75.00
Total charged:     NGN 1,075.00
```

Relevant implementation:

- `apps/api/core/views.py::subscription_vat_rate`
- `apps/api/core/views.py::calculate_subscription_vat`
- `apps/api/core/views.py::apply_subscription_vat`
- `apps/api/core/models.py::SubscriptionPayment`

### 2.2 Free Bronze subscriptions

A free Bronze subscription has:

```text
vat_rate   = 0.00
vat_amount = 0.00
```

It is completed immediately and does not create a `SubscriptionVATPayment` record.

### 2.3 Rental bookings

Rental VAT is applied only to RentDirect's administration fee, not to the landlord's rent amount or the refundable caution/security deposit.

The current rental pricing constants are:

```text
Refundable caution/security deposit = annual rent × 10%
RentDirect administration fee       = annual rent × 10%
VAT on administration fee            = administration fee × 7.5%
```

Therefore, the effective VAT on annual rent is `0.75%`:

```text
annual rent × 10% × 7.5% = annual rent × 0.75%
```

Example for annual rent of NGN 1,200,000.00:

```text
Landlord rent:                 NGN 1,200,000.00
Refundable caution deposit:    NGN   120,000.00
Administration fee:            NGN   120,000.00
VAT on administration fee:     NGN     9,000.00
Total booking amount:          NGN 1,449,000.00
```

Relevant implementation:

- `apps/api/core/pricing.py`
- `apps/api/core/pricing.py::calculate_administration_fee`
- `apps/api/core/pricing.py::calculate_administration_fee_vat`
- `apps/api/core/pricing.py::calculate_deposit_amount`
- `apps/api/core/pricing.py::calculate_booking_total`

## 3. Account destinations

Account values are configuration and must not be hard-coded in source code or copied into public documentation. The application reads them from environment variables managed through the local environment or deployment secret store.

### 3.1 Operating account

The operating account receives RentDirect's administration-fee portion.

Configuration variables:

```text
RENTDIRECT_OPERATING_BANK_NAME
RENTDIRECT_OPERATING_BANK_CODE
RENTDIRECT_OPERATING_ACCOUNT_NUMBER
RENTDIRECT_OPERATING_ACCOUNT_NAME
RENTDIRECT_OPERATING_SUBACCOUNT_ID
RENTDIRECT_OPERATING_BUSINESS_EMAIL
RENTDIRECT_OPERATING_BUSINESS_MOBILE
RENTDIRECT_OPERATING_SUBACCOUNT_COUNTRY
RENTDIRECT_OPERATING_SUBACCOUNT_SPLIT_TYPE
RENTDIRECT_OPERATING_SUBACCOUNT_SPLIT_VALUE
RENTDIRECT_OPERATING_TRANSACTION_CHARGE_TYPE
RENTDIRECT_OPERATING_TRANSACTION_CHARGE
```

The destination is resolved by `resolve_subscription_payment_account()` for subscriptions and directly from the same settings in `build_payment_settlement_specs()` for rental bookings.

### 3.2 VAT holding account

The VAT holding account receives the VAT portion that RentDirect has collected for remittance and tax administration.

Configuration variables:

```text
RENTDIRECT_VAT_HOLDING_BANK_NAME
RENTDIRECT_VAT_HOLDING_BANK_CODE
RENTDIRECT_VAT_HOLDING_ACCOUNT_NUMBER
RENTDIRECT_VAT_HOLDING_ACCOUNT_NAME
RENTDIRECT_VAT_HOLDING_SUBACCOUNT_ID
RENTDIRECT_VAT_HOLDING_BUSINESS_EMAIL
RENTDIRECT_VAT_HOLDING_BUSINESS_MOBILE
RENTDIRECT_VAT_HOLDING_SUBACCOUNT_COUNTRY
```

The destination is resolved by `resolve_vat_payment_account()` and is used for both subscription VAT and rental administration-fee VAT.

### 3.3 Tenant caution holding account

This is not a VAT account. It receives the refundable caution/security deposit for rental bookings.

Configuration variables:

```text
TENANT_CAUTION_HOLDING_BANK_NAME
TENANT_CAUTION_HOLDING_BANK_CODE
TENANT_CAUTION_HOLDING_ACCOUNT_NUMBER
TENANT_CAUTION_HOLDING_ACCOUNT_NAME
```

### 3.4 Landlord payout account

The landlord's rent is paid to the account stored in the landlord's profile. The resolver checks these profile locations in order:

1. `banking_information`.
2. `corporate_banking_information`.
3. The legacy/top-level profile fields.

The resolved fields are:

```text
bank_name
bank_code
account_number
account_name
```

The landlord account is used only for the landlord-rent settlement. It is not used for VAT.

## 4. Subscription VAT flow

### 4.1 Create the pending payment

The authenticated user requests a plan through:

```text
POST /api/v1/subscriptions/request
```

The backend:

1. Resolves the plan and billing cycle price.
2. Calculates VAT for paid plans.
3. Sets `SubscriptionPayment.amount` to the subscription fee.
4. Sets `SubscriptionPayment.vat_rate` and `SubscriptionPayment.vat_amount`.
5. Exposes `total_amount` as `amount + vat_amount`.
6. Creates a `pending` Flutterwave payment for paid plans.
7. Completes free Bronze subscriptions immediately.

The payment serializer exposes:

```text
amount
vat_rate
vat_amount
total_amount
currency
status
transaction_id
```

### 4.2 Build the Flutterwave checkout

The payment-review page calls:

```text
POST /api/v1/subscriptions/<payment-id>/flutterwave/checkout
```

The backend then:

1. Re-applies the current VAT calculation to prevent stale values.
2. Resolves the operating account and VAT holding account.
3. Uses configured Flutterwave subaccount IDs when available.
4. In v3 mode, creates or reuses collection subaccounts when IDs are absent; in v4 mode, existing subaccount IDs are required for direct splitting unless the development-only unsplit checkout setting is enabled.
5. Calculates the subscription-fee and VAT split ratios from the exact minor-unit amounts.
6. Builds the checkout for `payment.total_amount`.
7. Adds subscription and VAT metadata to the Flutterwave payload.
8. Stores the checkout payload and destination metadata on `SubscriptionPayment.provider_payload`.

The two Flutterwave collection subaccounts are:

| Split | Destination | Source configuration |
| --- | --- | --- |
| Subscription fee | RentDirect operating account | `RENTDIRECT_OPERATING_*` |
| VAT | RentDirect VAT holding account | `RENTDIRECT_VAT_HOLDING_*` |

The VAT destination is marked in provider metadata with:

```text
vat_rate
vat_amount
subaccount_id
transaction_split_ratio
direct_settlement = true
```

The subscription checkout is a direct collection split. It is not processed by the rental booking payout scheduler.

### 4.3 Collection subaccount creation

When `FLUTTERWAVE_API_VERSION=v3` and a subaccount ID is not configured, `get_or_create_collection_subaccount_id()` calls Flutterwave's v3 collection subaccount endpoint.

When `FLUTTERWAVE_API_VERSION=v4`, the application does not create collection subaccounts through v3. Production requires both configured subaccount IDs. Local/development can explicitly allow an unsplit checkout with `FLUTTERWAVE_V4_ALLOW_UNSPLIT_CHECKOUT`; that mode is for testing only and does not perform the operating/VAT split at collection time.

The account must be valid for the Flutterwave environment being used. Sandbox credentials require Flutterwave-supported sandbox test bank accounts; production credentials require the real account to be valid with the selected bank code.

The application also handles known mobile-bank code aliases while creating collection subaccounts:

- OPay: primary configured code and the supported alternate code.
- Moniepoint: primary configured code and its supported alternate code.

The created subaccount ID is cached in-process by the Flutterwave helper. A configured `*_SUBACCOUNT_ID` avoids creating the subaccount during checkout.

### 4.4 Payment completion and VAT record

Flutterwave can notify the API through:

```text
POST /api/v1/payments/webhook/flutterwave
```

The webhook signature is checked using `FLUTTERWAVE_WEBHOOK_SECRET_HASH` when signature enforcement is enabled. The webhook is queued for processing.

The payment-review page can also verify the redirect result through:

```text
GET /api/v1/subscriptions/flutterwave/verify?reference=<transaction-id>&transaction_id=<provider-id>&status=<provider-status>
```

`sync_subscription_payment()` verifies the provider reference, amount, currency, and customer email. On successful verification it calls `complete_subscription_payment()`.

`complete_subscription_payment()` runs inside a database transaction and:

1. Marks the subscription payment `completed`.
2. Sets the payment date and subscription expiry.
3. Creates one `SubscriptionVATPayment` record when `vat_amount > 0`.
4. Uses the subscription payment as the unique VAT record key.
5. Stores payer, plan payment, total amount paid, VAT rate, VAT amount, currency, transaction ID, provider transaction ID, and paid time.

The one-to-one relationship plus `get_or_create()` makes repeated webhook or redirect verification idempotent.

## 5. Recurring subscription VAT flow

Recurring subscription payments use the saved Flutterwave payment method and the v4 charge flow.

Before recurring payments are enabled, the API requires:

- Flutterwave v4 client credentials.
- A configured Flutterwave encryption key.
- A configured operating settlement destination.
- A configured VAT holding settlement destination.

The recurring charge uses the same two direct-settlement subaccounts and includes the same VAT metadata. On a successful charge it calls `sync_subscription_payment()`, which records the VAT through the same `complete_subscription_payment()` path.

If either direct-settlement destination is missing, recurring configuration is reported as disabled and a recurring charge is not started.

## 6. Rental-booking VAT settlement flow

Rental payments are collected for the booking total. The initial payment does not immediately transfer the administration fee, VAT, caution deposit, or landlord rent to their final bank accounts.

After a booking is fully paid, the payout scheduler waits for all release conditions:

1. The booking is fully paid.
2. The tenant confirms the key-collection progress step.
3. The landlord confirms the key-collection progress step.
4. The tenant selects `yes` for `rentdirect_transfer_to_landlord`.
5. The configured Flutterwave payout-balance delay has elapsed since the payment completing the booking.
6. The booking is not cancelled.

The delay is controlled by:

```text
FLUTTERWAVE_PAYOUT_BALANCE_DELAY_MINUTES
```

The backend default is 1,440 minutes (24 hours). Environment files may override it for development or testing; the example environment currently contains a short test value. Production must use the intended operational hold period.

### 6.1 Settlement records

`ensure_payment_settlement_records()` creates one `PaymentSettlement` per destination:

| Purpose | Amount | Destination |
| --- | ---: | --- |
| `operations` | Annual rent × 10% | `RENTDIRECT_OPERATING_*` account |
| `administration_fee_vat` | Annual rent × 10% × 7.5% | `RENTDIRECT_VAT_HOLDING_*` account |
| `caution_fee` | Annual rent × 10% | `TENANT_CAUTION_HOLDING_*` account |
| `landlord_rent` | Annual rent | Landlord profile bank account |

If a booking is paid in multiple payments, the target amount is reduced by already-paid settlement amounts for the same booking and purpose. This prevents duplicate VAT or fee transfers.

The VAT settlement is a `PaymentSettlement` record, not a `SubscriptionVATPayment` record. `SubscriptionVATPayment` is only for subscription VAT.

### 6.2 Transfer processing

`trigger_payment_settlements()` processes each settlement independently:

1. Finds or creates a Flutterwave transfer recipient.
2. Stores the recipient/provider response.
3. Creates the bank transfer with an idempotent settlement reference.
4. Stores the transfer payload and provider status.
5. Marks the settlement `processing`, `paid`, or `failed`.
6. Records the transfer time when the provider reports success.
7. Sends an internal transfer notification for the operating, VAT, and caution destinations.
8. Sends a landlord payout notification for the landlord-rent destination.

The scheduled/manual command is:

```text
python manage.py process_ready_payouts
```

It first reconciles processing transfers, then checks eligible bookings and starts ready settlements. The payment queue exposes this as `process_ready_payouts` through the sync, RQ, or SQS backend.

Transfer webhooks update processing settlements. If a transfer remains in `processing`, reconciliation retrieves the provider transfer and updates the settlement status.

## 7. Status and audit records

### Subscription VAT

| Record | Purpose |
| --- | --- |
| `SubscriptionPayment` | Pending/completed subscription charge, fee, VAT, total, provider reference, and provider payload |
| `SubscriptionVATPayment` | One-to-one completed subscription VAT record for reporting and audit |
| `SubscriptionPayment.provider_payload` | Checkout, split destinations, verification, webhook, and recurring metadata |

### Rental VAT

| Record | Purpose |
| --- | --- |
| `Payment` | Booking charge and Flutterwave provider data |
| `PaymentSettlement` | VAT transfer amount, destination, recipient, transfer reference, status, errors, and timestamps |
| `PaymentSettlement.provider_payload` | Recipient resolution response |
| `PaymentSettlement.transfer_payload` | Bank-transfer request/response and provider status |

The application does not currently create a separate general-ledger journal or FIRS filing record for VAT. The VAT records and provider payloads are the application-level audit trail; tax filing and reconciliation remain an operational/accounting responsibility.

## 8. Required environment configuration

Select the payment API version explicitly:

```text
FLUTTERWAVE_API_VERSION=v3  # or v4
```

Minimum subscription direct-settlement configuration:

```text
RENTDIRECT_OPERATING_BANK_NAME
RENTDIRECT_OPERATING_BANK_CODE
RENTDIRECT_OPERATING_ACCOUNT_NUMBER
RENTDIRECT_OPERATING_ACCOUNT_NAME
RENTDIRECT_OPERATING_BUSINESS_EMAIL
RENTDIRECT_OPERATING_BUSINESS_MOBILE

RENTDIRECT_VAT_HOLDING_BANK_NAME
RENTDIRECT_VAT_HOLDING_BANK_CODE
RENTDIRECT_VAT_HOLDING_ACCOUNT_NUMBER
RENTDIRECT_VAT_HOLDING_ACCOUNT_NAME
RENTDIRECT_VAT_HOLDING_BUSINESS_EMAIL
RENTDIRECT_VAT_HOLDING_BUSINESS_MOBILE

SUBSCRIPTION_VAT_RATE_PERCENT=7.5
```

Optional but recommended after subaccounts are created:

```text
RENTDIRECT_OPERATING_SUBACCOUNT_ID
RENTDIRECT_VAT_HOLDING_SUBACCOUNT_ID
```

The account-number variables must be stored in the deployment secret store or protected environment files. They must not be committed to this document, source code, logs, screenshots, or support tickets.

## 9. Operational verification checklist

Before enabling paid subscriptions or rental payouts in an environment:

- [ ] Confirm the operating account bank name, bank code, and account number belong to the same account.
- [ ] Confirm the VAT holding account bank name, bank code, and account number belong to the same account.
- [ ] Confirm both accounts are valid in the same Flutterwave environment as the API credentials.
- [ ] Use Flutterwave sandbox test accounts when using sandbox credentials; do not use unverified production accounts in sandbox.
- [ ] Confirm business email and mobile values are present for collection subaccount creation.
- [ ] Confirm `SUBSCRIPTION_VAT_RATE_PERCENT` is the intended rate.
- [ ] Confirm the Flutterwave webhook URL is reachable and its signature hash is configured.
- [ ] Confirm `FLUTTERWAVE_PAYOUT_BALANCE_DELAY_MINUTES` matches the required hold policy.
- [ ] Run a low-value paid subscription and verify the checkout payload has both operating and VAT subaccount IDs.
- [ ] Verify the completed subscription creates exactly one `SubscriptionVATPayment`.
- [ ] Run a rental booking through full payment and both-party release confirmation.
- [ ] Run `process_ready_payouts` and verify the VAT `PaymentSettlement` reaches `paid`.
- [ ] Confirm the provider transfer reference and amount match the local settlement record.
- [ ] Re-run verification and payout processing to confirm no duplicate VAT record or transfer is created.

## 10. Troubleshooting

### Flutterwave cannot verify the account number

Check, in order:

1. The account number is valid and has the expected digit length.
2. The bank code matches the bank name used by Flutterwave.
3. The account is available in the configured Flutterwave environment.
4. Sandbox credentials are not being used with a live-only account.
5. The corresponding `*_SUBACCOUNT_ID` is not stale or associated with a different destination.
6. The API is using the intended `FLUTTERWAVE_V3_API_BASE_URL` and v4 credentials.

The subscription checkout creates or reuses collection subaccounts before returning the checkout payload. Therefore an account-validation error at the Continue Payment button is a server/provider configuration failure, not a card-payment failure.

### VAT holding account is not configured

The API raises a VAT holding account configuration error when the VAT bank name, bank code, account number, or business mobile is missing and no VAT subaccount ID is configured. Add the missing values to the protected environment configuration, restart the API, and retry checkout.

### Settlement is stuck in processing

Run:

```text
python manage.py process_ready_payouts
```

Then inspect `PaymentSettlement.transfer_payload`, the provider transfer ID, and `last_error`. The command reconciles processing transfers before starting new eligible payouts.

### VAT appears as 7.50%

The database/API decimal field intentionally retains two monetary-style decimal places. The web payment review display converts the numeric value to a trimmed string so the user sees `7.5%`. Do not change the stored monetary precision solely to change presentation.

## 11. Source map

- VAT pricing: `apps/api/core/pricing.py`
- Subscription VAT calculation and account resolution: `apps/api/core/views.py`
- Subscription and VAT models: `apps/api/core/models.py`
- Flutterwave subaccounts, recipients, transfers, and bank-code aliases: `apps/api/core/flutterwave.py`
- Booking payout scheduler: `apps/api/core/management/commands/process_ready_payouts.py`
- Payment queue tasks: `apps/api/core/payment_queue.py`
- API routes: `apps/api/core/urls.py`
- Environment template: `apps/api/.env.example`
- Backend VAT and payout tests: `apps/api/core/tests.py`
- Subscription payment review page: `apps/web/src/pages/billing/SubscriptionPaymentPage.tsx`
