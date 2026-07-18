# RentDirect Product Requirements Document

**Document status:** Draft for product alignment  
**Product:** RentDirect rental marketplace  
**Primary market:** Nigeria, starting with urban rental markets where direct landlord-tenant trust is a major constraint  
**Prepared date:** 2026-07-17  
**Reviewed sources:** `apps/README.md`, `apps/web/src/App.tsx`, public content pages, frontend user flows, Django models, API viewsets, pricing utilities, payment, verification, subscription, support, and worker code.

---

## 1. Executive Summary

RentDirect is a verified rental marketplace that connects tenants directly with landlords and reduces dependence on fragmented intermediary-led rental processes. The product helps tenants find verified homes, communicate directly with landlords, build a reusable tenant profile, make secure rental payments, and track the move-in process. It helps landlords list properties, verify ownership and identity, review higher-quality tenant profiles, receive structured rental payments, and manage rental progress through a documented workflow.

The core product promise is:

> RentDirect makes renting direct, transparent, verified, and easier to manage for both tenants and landlords.

The product exists to solve three connected problems:

1. Tenants face fake listings, hidden fees, inspection charges, unclear processes, and limited confidence when searching for homes.
2. Landlords struggle to identify trustworthy tenants, reduce vacancy time, and manage applications without relying heavily on third parties.
3. Both sides lack a shared digital system for verification, communication, rental payments, tenancy progress, and records.

RentDirect should prioritize marketplace trust, transaction transparency, and successful tenancy completion over raw listing volume. The near-term product strategy is to grow verified supply, convert serious tenants into verified applicants, and monetize through subscriptions, featured listings, and platform-managed payment flows.

---

## 2. Product Vision

RentDirect should become the trusted digital infrastructure for residential rentals in Nigeria: a place where tenants can search, apply, pay, and move in with confidence, and where landlords can list, verify, screen, communicate, and receive rent with less friction.

### 2.1 Mission

Create the most transparent, trusted, and efficient rental marketplace where verified landlords connect directly with verified tenants.

### 2.2 Product Principles

1. **Trust before scale:** Verification and fraud reduction are more important than maximizing unverified listings.
2. **Direct but protected:** Tenants and landlords should communicate directly, while RentDirect records key interactions and protects users from abuse.
3. **Transparent money movement:** Fees, deposits, rent, payment status, and landlord payouts must be visible and auditable.
4. **Reusable rental identity:** Tenants should build a profile that improves their ability to rent again.
5. **Landlord control:** Landlords should be able to manage listings, applications, tenant review, and rental progress without losing oversight.
6. **Operational accountability:** Admins need review tools, verification queues, metrics, and support visibility to keep the marketplace trustworthy.

---

## 3. Problem Statement

The traditional rental process in Nigeria is often expensive, opaque, and low-trust.

Tenants commonly face:

- Fake or stale listings.
- Multiple agents and duplicate fees.
- Inspection or viewing charges before meaningful qualification.
- Sudden price changes and hidden costs.
- Limited visibility into whether a landlord or property is legitimate.
- Poor recordkeeping for payments, agreements, and communications.

Landlords commonly face:

- Difficulty finding reliable tenants.
- Limited structured tenant information before approving applicants.
- Fraudulent or incomplete applicant details.
- Dependency on intermediaries for discovery and communication.
- Delays in collecting payment and confirming move-in readiness.
- Poor visibility into tenant experience and satisfaction.

RentDirect should reduce these problems by combining verified listings, verified user profiles, direct messaging, structured applications, payment tracking, rental progress workflows, support, and admin oversight.

---

## 4. Target Users

### 4.1 Primary Users

#### Tenants

Tenants are individuals looking for a residential rental property and wanting to avoid scams, unnecessary intermediaries, and unclear payment processes.

Key needs:

- Discover verified rental properties.
- Search by location, budget, type, rooms, and amenities.
- Contact landlords directly.
- Save favorite properties.
- Build a trusted tenant profile.
- Submit a rental application or booking.
- Pay securely through supported methods.
- Track rental progress and maintain digital records.

#### Landlords

Landlords are individual or corporate property owners/managers who want direct access to serious tenants and better control of the rental process.

Key needs:

- Create and manage property listings.
- Upload listing images and property details.
- Complete identity and property document verification.
- Receive tenant enquiries directly.
- Review tenant profiles and screening signals.
- Track rental payment status.
- Confirm rental progress milestones.
- Promote listings with featured placement.

### 4.2 Secondary Users

#### RentDirect Admins and Operations

Admins are internal users responsible for trust, verification, support, payments oversight, and marketplace health.

Key needs:

- View marketplace metrics.
- Review verification requests.
- Approve or reject identity and property document submissions.
- View users and listings.
- Monitor support issues and feedback.
- Ensure payment and payout issues are traceable.

#### Prospective Visitors

Visitors are unauthenticated users who browse public pages and listings before creating an account.

Key needs:

- Understand RentDirect's value proposition.
- Browse public property listings.
- View landlord public profiles.
- Learn how renting works.
- Register or sign in when ready to take action.

---

## 5. Business Goals

### 5.1 Near-Term Goals

1. Increase the number of verified landlord accounts and verified property listings.
2. Increase tenant registration and tenant profile completion.
3. Convert property discovery into enquiries, rental applications, and completed rental payments.
4. Reduce user uncertainty by making fees, verification status, and payment state clear.
5. Establish admin workflows that can support verification and marketplace trust without manual data confusion.

### 5.2 Revenue Goals

RentDirect should support multiple monetization paths:

1. **Tenant and landlord subscriptions:** Bronze, Silver, Gold, and Platinum plans with role-specific monthly and yearly pricing.
2. **Featured listings:** Landlords can pay to promote a listing for a fixed duration.
3. **Rental transaction economics:** The rental checkout flow should clearly show annual rent, refundable security deposit, platform/admin fees, and remaining balance.
4. **Future premium services:** Property verification visits, lease documentation support, tenant screening upgrades, insurance, and credit/rental history products.

### 5.3 Marketplace Health Goals

1. Maintain a high verified-listing ratio.
2. Reduce fraudulent or unresponsive listings.
3. Improve landlord response quality.
4. Improve tenant application completeness.
5. Decrease time from property discovery to completed booking.

---

## 6. Success Metrics

### 6.1 Acquisition

- Visitor-to-registration conversion rate.
- Tenant registrations per week.
- Landlord registrations per week.
- Cost per verified user, if paid acquisition is used.
- Percentage of visitors using search filters.

### 6.2 Activation

- Email verification completion rate.
- Tenant profile completion rate.
- Landlord identity verification submission rate.
- Property document verification submission rate.
- First listing created per verified landlord.
- First enquiry sent per active tenant.

### 6.3 Marketplace Liquidity

- Verified active listings.
- Listings with complete media and location data.
- Search result click-through rate.
- Enquiry rate per listing.
- Average time from listing published to first enquiry.
- Average time from enquiry to booking.

### 6.4 Transaction and Revenue

- Booking creation rate.
- Payment initiation rate.
- Payment completion rate.
- Average paid amount per booking.
- Outstanding balance per active booking.
- Featured listing conversion rate.
- Subscription conversion rate by role and plan.
- Monthly recurring revenue from subscriptions.
- Featured listing revenue.

### 6.5 Trust and Safety

- Verification approval rate.
- Verification rejection rate and top rejection reasons.
- Fraud or scam reports.
- Support tickets per transaction.
- Payment disputes.
- Manual admin review backlog.
- Average verification turnaround time.

### 6.6 Retention

- Returning tenants with saved favourites.
- Repeat landlord listing activity.
- Subscription renewal rate.
- Number of completed tenancies.
- Review submission rate.
- Tenant profile reuse across multiple applications.

---

## 7. Scope

### 7.1 In Scope for Current Product

- Public marketing and education pages.
- Public property search and listing discovery.
- Account registration, OTP email verification, login, logout, and session refresh.
- Role-based tenant, landlord, and admin experiences.
- Tenant profile and verification workflow.
- Landlord individual and corporate identity verification.
- Property document upload and verification.
- Listing creation, editing, viewing, search, and featured listing promotion.
- Favourites for tenants.
- Direct tenant-landlord messaging.
- Rental booking/application creation.
- Rent payment initiation and verification through Flutterwave.
- Bank transfer and hosted checkout payment flows.
- Payment history and receipt generation.
- Rental progress checklists for tenants and landlords.
- Landlord public profiles and landlord property pages.
- Subscription billing by user role and plan.
- Community chat access for eligible subscription plans.
- Support chat, complaint, issues, and feedback workflows.
- Admin dashboard, user/listing visibility, and verification review.
- Background payout readiness processing.

### 7.2 Out of Scope for This PRD Version

- Native mobile applications.
- Full property management accounting.
- Maintenance vendor marketplace.
- Formal credit bureau integration.
- AI-based listing valuation.
- Automated legal document generation beyond current rental support messaging.
- End-to-end dispute arbitration.
- Mortgage, rent-to-own, or property purchase workflows.
- Multi-country expansion.

---

## 8. Product Requirements

Requirement priorities:

- **P0:** Required for a trustworthy launch-grade rental flow.
- **P1:** Important for growth, operational efficiency, or monetization.
- **P2:** Useful enhancement after core marketplace reliability is strong.

### 8.1 Public Experience

| ID | Priority | Requirement |
|----|----------|-------------|
| PUB-001 | P0 | Visitors must be able to view a home page that explains RentDirect's value proposition: verified properties, direct communication, transparent pricing, and secure payments. |
| PUB-002 | P0 | Visitors must be able to browse and search available listings without authentication. |
| PUB-003 | P0 | Visitors must be able to view listing details, including title, description, address area, city, state, property type, bedrooms, bathrooms, toilets, amenities, photos, annual rent, and landlord identity indicators. |
| PUB-004 | P0 | Visitors must be able to register or log in from major public entry points. |
| PUB-005 | P1 | Visitors should be able to view landlord public profiles and public landlord property lists. |
| PUB-006 | P1 | Public pages should explain how RentDirect works for tenants and landlords. |

Acceptance criteria:

- Search results return only listings suitable for public browsing.
- Public pages clearly communicate verification and direct-rental positioning.
- Calls to action route users into registration, login, search, or listing actions.

### 8.2 Authentication and User Accounts

| ID | Priority | Requirement |
|----|----------|-------------|
| AUTH-001 | P0 | Users must be able to register as tenant, landlord, or admin where admin registration is enabled by policy. |
| AUTH-002 | P0 | New users must verify email using an OTP before being treated as verified for account-level workflows. |
| AUTH-003 | P0 | Users must be able to log in, log out, and refresh authenticated sessions. |
| AUTH-004 | P0 | Authenticated users must be authorized by role before accessing protected tenant, landlord, or admin routes. |
| AUTH-005 | P1 | Users must be able to update profile details through a settings workflow protected by OTP where required. |
| AUTH-006 | P1 | Users must be able to upload profile photos. |

Acceptance criteria:

- Unauthenticated users cannot access protected role dashboards.
- Tenant-only, landlord-only, and admin-only workflows enforce role rules at both frontend and API layers.
- OTP attempts and expiry should protect sensitive flows from abuse.

### 8.3 Tenant Profile and Verification

| ID | Priority | Requirement |
|----|----------|-------------|
| TEN-001 | P0 | Tenants must be able to submit a structured tenant profile with biodata, residence, employment, financial details, guarantor details, landlord details, rental history, household information, social presence, and declarations. |
| TEN-002 | P0 | Tenant profile submission must require NIN and BVN where identity verification is needed. |
| TEN-003 | P0 | RentDirect must store tenant verification status as pending, under review, approved, or rejected. |
| TEN-004 | P1 | Landlords with a valid relationship to a tenant through booking activity should be able to view a safe tenant profile summary. |
| TEN-005 | P1 | Sensitive tenant financial fields must be protected and minimized when shown to landlords. |
| TEN-006 | P1 | Tenant profiles should generate category-level screening signals for landlord review. |

Acceptance criteria:

- Tenant profile data persists and can be edited where allowed.
- Tenant identity checks compare submitted profile data with verified identity data.
- Landlord-facing tenant views do not expose unnecessary bank or highly sensitive financial details.

### 8.4 Landlord Verification

| ID | Priority | Requirement |
|----|----------|-------------|
| LAN-001 | P0 | Landlords must select individual or corporate verification type. |
| LAN-002 | P0 | Individual landlords must provide identity data and supporting verification details. |
| LAN-003 | P0 | Corporate landlords must provide company verification details, including CAC-related information where required. |
| LAN-004 | P0 | Landlords must be able to upload identity and property ownership documents. |
| LAN-005 | P0 | Admins must be able to approve or reject landlord verification requests. |
| LAN-006 | P1 | Verification status should be visible to users in relevant dashboards and public trust indicators. |

Acceptance criteria:

- Landlord identity, property document, and physical property verification statuses can be tracked separately.
- Verified landlord state should determine access to trust-sensitive actions where applicable.
- Admin review actions must persist review status and timestamp.

### 8.5 Listings

| ID | Priority | Requirement |
|----|----------|-------------|
| LIS-001 | P0 | Verified or authorized landlords must be able to create property listings. |
| LIS-002 | P0 | Listings must include title, description, address, city, state, property type, bedrooms, bathrooms, toilets, annual rent, deposit information, availability, amenities, and media. |
| LIS-003 | P0 | Landlords must be able to upload a cover image and additional listing gallery images. |
| LIS-004 | P0 | Tenants and visitors must be able to search listings by query, state, city, price range, bedrooms, bathrooms, toilets, property type, pet-friendly, furnished, and utilities-included filters. |
| LIS-005 | P0 | Listing statuses must support available, rented, draft, and archived states. |
| LIS-006 | P1 | Landlords must be able to edit and manage their own listings. |
| LIS-007 | P1 | Tenants must be able to save and remove favourite listings. |
| LIS-008 | P1 | Featured listings must be promoted in discovery areas while their featured period is active. |

Acceptance criteria:

- Search filters map consistently to API query parameters.
- A listing can expose cover and gallery image URLs.
- Only authorized landlords or admins can create or modify listings.

### 8.6 Messaging and Enquiries

| ID | Priority | Requirement |
|----|----------|-------------|
| MSG-001 | P0 | Tenants must be able to contact landlords about a listing through platform messaging. |
| MSG-002 | P0 | Landlords must be able to view tenant enquiries. |
| MSG-003 | P1 | Users must be able to view conversation threads. |
| MSG-004 | P1 | The platform should detect and restrict direct contact information sharing where policy requires. |
| MSG-005 | P2 | Messaging should support notification triggers for unread or important messages. |

Acceptance criteria:

- Messages are linked to sender, receiver, and optionally listing.
- Users can only access conversations they participate in.
- Messaging supports marketplace transparency and recordkeeping.

### 8.7 Rental Application, Booking, and Progress

| ID | Priority | Requirement |
|----|----------|-------------|
| RENT-001 | P0 | Authenticated tenants must be able to start a rental application or booking from a listing. |
| RENT-002 | P0 | Bookings must link tenant, listing, start date, end date, status, total amount, paid amount, and payment history. |
| RENT-003 | P0 | Rental totals must be calculated consistently between frontend and backend. |
| RENT-004 | P0 | Tenants and landlords must be able to view rental progress checklists relevant to their role. |
| RENT-005 | P0 | Rental progress must include milestones for viewing, house viewed, agreement signed, deposit/rent payment, inventory, key collection, and landlord payout confirmation. |
| RENT-006 | P1 | Both parties' progress updates should support operational decisions such as payout readiness. |
| RENT-007 | P1 | Tenants and landlords should be able to view active and historical bookings in their dashboards. |

Acceptance criteria:

- Rental progress updates are role-specific and cannot be edited by unauthorized users.
- Booking status and payment status remain consistent.
- The product clearly distinguishes annual rent, refundable security deposit, administration fee, paid amount, and remaining balance.

### 8.8 Payments, Payouts, and Receipts

| ID | Priority | Requirement |
|----|----------|-------------|
| PAY-001 | P0 | Tenants must be able to initiate rental payments for a booking. |
| PAY-002 | P0 | Supported payment methods must include card and bank transfer where the payment provider supports them. |
| PAY-003 | P0 | Payments must be processed and verified through Flutterwave integration. |
| PAY-004 | P0 | Users must be able to see payment status: pending, processing, completed, failed, or cancelled. |
| PAY-005 | P0 | Tenants must not be allowed to pay more than the remaining balance. |
| PAY-006 | P1 | Tenants should be able to continue pending payments. |
| PAY-007 | P1 | Tenants should be able to generate or download simple receipts for completed payments. |
| PAY-008 | P1 | RentDirect must track settlements by purpose: operations, caution fee, and landlord rent. |
| PAY-009 | P1 | Background workers must process payout-ready settlements after required rental progress conditions are met. |

Acceptance criteria:

- Payment verification updates booking paid amount and payment state safely.
- Webhook and return-url verification should be idempotent.
- Payout processing must avoid duplicate settlement transfers.

### 8.9 Subscriptions and Feature Monetization

| ID | Priority | Requirement |
|----|----------|-------------|
| SUB-001 | P1 | Tenants and landlords must be able to view role-specific subscription plans. |
| SUB-002 | P1 | Plans must support Bronze, Silver, Gold, and Platinum tiers with monthly and yearly billing cycles. |
| SUB-003 | P1 | Users must be able to request and pay for subscription plans. |
| SUB-004 | P1 | The system must track subscription payment status and expiry. |
| SUB-005 | P1 | Bronze/free plan limitations must restrict premium actions where defined. |
| SUB-006 | P1 | Gold and Platinum plans should unlock community chat access. |
| FEAT-001 | P1 | Landlords must be able to request featured placement for a listing. |
| FEAT-002 | P1 | Featured listing payments must activate featured status and expiry on completion. |

Acceptance criteria:

- Current plan state is derived from completed, unexpired subscription payments.
- Featured listing status automatically syncs with completed featured payments and expiry.

### 8.10 Support, Feedback, and Community

| ID | Priority | Requirement |
|----|----------|-------------|
| SUP-001 | P1 | Tenants and landlords must be able to submit feedback. |
| SUP-002 | P1 | Tenants and landlords must be able to access support-related pages for complaints and issues. |
| SUP-003 | P1 | Authenticated users must be able to participate in support chat threads. |
| SUP-004 | P1 | Eligible users must be able to participate in community chat. |
| SUP-005 | P2 | Admins should have a consolidated support queue with ownership, status, and SLA tracking. |

Acceptance criteria:

- Support messages are linked to the thread user and sender.
- Community chat access respects subscription eligibility.
- Feedback entries preserve user, role, topic, message, and timestamps.

### 8.11 Admin and Operations

| ID | Priority | Requirement |
|----|----------|-------------|
| ADM-001 | P0 | Admins must be able to log in through admin routes. |
| ADM-002 | P0 | Admins must be able to view dashboard statistics. |
| ADM-003 | P0 | Admins must be able to review pending verification requests. |
| ADM-004 | P0 | Admins must be able to approve or reject verification requests with notes. |
| ADM-005 | P1 | Admins should be able to view user and listing records. |
| ADM-006 | P1 | Admin metrics should show verification pipeline counts and marketplace health indicators. |
| ADM-007 | P2 | Admins should have operational dashboards for payments, settlement failures, support issues, and suspicious activity. |

Acceptance criteria:

- Admin endpoints require admin role permissions.
- Verification decisions update user-facing status.
- Admin views support pending queues and review history.

---

## 9. User Journeys

### 9.1 Tenant Journey

1. Visitor lands on RentDirect and understands verified direct rentals.
2. Visitor searches listings by location, budget, rooms, and features.
3. Visitor registers as a tenant and verifies email by OTP.
4. Tenant completes profile and verification details.
5. Tenant saves properties and contacts landlords directly.
6. Tenant chooses a property and starts a rental booking.
7. Tenant reviews clear rent breakdown and agrees to terms.
8. Tenant pays deposit, rent, or remaining balance through Flutterwave-supported methods.
9. Tenant tracks rental progress until move-in steps are completed.
10. Tenant maintains records for future rental history and applications.

### 9.2 Landlord Journey

1. Landlord registers and verifies email.
2. Landlord completes individual or corporate verification.
3. Landlord uploads identity and property ownership documents.
4. Admin reviews and approves landlord verification.
5. Landlord creates listings with photos, rent, location, features, and availability.
6. Landlord receives enquiries and communicates with tenants.
7. Landlord reviews tenant profile and screening signals.
8. Landlord monitors payment and booking progress.
9. Landlord completes required rental progress milestones.
10. Landlord receives payout once release conditions are satisfied.

### 9.3 Admin Journey

1. Admin logs in through admin routes.
2. Admin views dashboard statistics and verification queues.
3. Admin reviews submitted documents and identity/property verification evidence.
4. Admin approves or rejects requests with notes.
5. Admin monitors users, listings, support issues, and payment exceptions.
6. Admin escalates fraud, payment, or support issues according to operating policy.

---

## 10. Data Requirements

### 10.1 Core Entities

- **User:** email, name, role, verification status, photo, mobile, NIN/BVN fields, residence, settings OTP metadata, landlord or tenant verification profile.
- **Listing:** landlord, title, description, address, city, state, coordinates, property type, bedroom/bathroom/toilet counts, annual rent, deposit, amenities, status, featured state, media.
- **Document:** owner, title, content type, file, created timestamp.
- **Verification request:** user, documents, request type, status, identity status, property document status, physical property status, method, confidence score, notes, review timestamps.
- **Tenant profile:** biodata, residence, employment, finance, guarantor, landlord, rental history, household, social, criminal declaration, documents, status.
- **Booking:** tenant, listing, dates, status, total amount, paid amount, tenant progress, landlord progress, reminder timestamps.
- **Payment:** booking, amount, provider, method, transaction reference, channel details, virtual account details, status, provider payload, webhook data.
- **Settlement:** payment, purpose, amount, bank destination, transfer recipient, transfer reference, status, provider payload, transfer timestamp.
- **Subscription payment:** user, role, plan, cycle, amount, status, provider data, expiry.
- **Featured payment:** listing, landlord, amount, status, duration, expiry, provider data.
- **Message:** sender, receiver, listing, content, created timestamp.
- **Review, feedback, favourite, community chat, support chat.**

### 10.2 Data Quality Rules

- User email must be unique.
- Listings must belong to a landlord.
- Listing media should maintain a deterministic cover image.
- A tenant can favourite a listing only once.
- A tenant can review a listing only once.
- Verification requests should remain unique per user unless a new versioning model is introduced.
- Payment and settlement references must be idempotent and traceable.
- Sensitive identity and financial fields must not be overexposed in public or landlord-facing views.

---

## 11. Pricing and Money Movement Requirements

### 11.1 Rental Checkout

The rental checkout must show a clear breakdown before payment:

- Annual rent.
- Refundable security deposit.
- Administration/platform fee.
- Total amount due.
- Amount already paid.
- Remaining balance.

The current product calculation uses:

- Refundable security deposit: 10% of annual rent.
- Administration fee: 10% of annual rent.
- Total booking amount: annual rent + refundable security deposit + administration fee.

### 11.2 Subscriptions

The product supports tenant and landlord subscription plans:

| Role | Bronze | Silver | Gold | Platinum |
|------|--------|--------|------|----------|
| Tenant monthly | 0 | 200 | 300 | 500 |
| Tenant yearly | 0 | 2,000 | 3,000 | 5,000 |
| Landlord monthly | 0 | 300 | 400 | 500 |
| Landlord yearly | 0 | 3,000 | 4,000 | 5,000 |

Currency should be presented consistently in the UI according to the product's configured currency rules.

### 11.3 Featured Listings

Landlords should be able to promote properties through featured listing payments. Featured properties should appear in elevated discovery surfaces while active and revert automatically when expired or cancelled.

---

## 12. Non-Functional Requirements

### 12.1 Security

- Use secure authenticated sessions with HTTP-only cookie-based JWT handling.
- Enforce role-based access on frontend routes and backend endpoints.
- Protect OTP flows with expiry and attempt limits.
- Validate payment webhooks and payment provider callbacks.
- Keep sensitive documents and identity data private.
- Minimize sensitive tenant financial data in landlord-facing views.
- Apply rate limiting to authentication, OTP, payment, and messaging endpoints.
- Maintain auditability for verification decisions and payment state changes.

### 12.2 Reliability

- Health checks must report database readiness and pending migration state.
- Payment verification must be idempotent.
- Background payout workers must tolerate retry and avoid duplicate transfers.
- Listing search and public pages should fail gracefully with useful empty states.
- Admin verification queues must remain usable during partial marketplace failure.

### 12.3 Performance

- Public listing search should respond quickly under normal marketplace traffic.
- Listing queries should use indexed fields for status, city, landlord, featured state, and price.
- Media should be served through the configured media delivery path.
- Frontend pages should avoid blocking core search, listing detail, and payment flows on nonessential data.

### 12.4 Compliance and Privacy

- Collect only identity, financial, and document data needed for rental trust and transaction workflows.
- Clearly disclose why NIN, BVN, documents, employment, financial, and guarantor information are collected.
- Retain payment and tenancy records according to legal and operational requirements.
- Allow admins to review sensitive data only under defined operational permissions.
- Establish data deletion, export, and correction policies before scaling.

### 12.5 Accessibility and Usability

- Core flows should be usable on mobile and desktop.
- Forms should provide clear labels, validation, and error feedback.
- Payment and verification states should not rely on color alone.
- Long forms should preserve user progress where practical.

---

## 13. Analytics and Instrumentation

RentDirect should instrument the following events:

- `account_registered`
- `email_otp_verified`
- `tenant_profile_started`
- `tenant_profile_submitted`
- `landlord_verification_started`
- `landlord_verification_submitted`
- `listing_created`
- `listing_published`
- `search_performed`
- `listing_viewed`
- `listing_favourited`
- `message_sent`
- `booking_created`
- `payment_started`
- `payment_completed`
- `payment_failed`
- `rental_progress_updated`
- `subscription_requested`
- `subscription_completed`
- `featured_listing_requested`
- `featured_listing_completed`
- `support_message_sent`
- `verification_approved`
- `verification_rejected`

Each event should include safe metadata such as user role, listing id, booking id, payment id, plan code, city/state, and status, while excluding raw NIN, BVN, bank account numbers, document contents, or sensitive profile details.

---

## 14. Release Strategy

### 14.1 MVP Launch Criteria

The product should be considered MVP-ready when:

- Tenants can register, verify email, search, view listings, contact landlords, create bookings, and pay.
- Landlords can register, verify identity/property, create listings, receive enquiries, view tenant details where authorized, and track bookings.
- Admins can review verification requests and view operational dashboards.
- Payments can be initiated, verified, and reflected in booking balances.
- Rental progress checklists support tenant and landlord milestone updates.
- Sensitive data exposure has been reviewed.
- Support and feedback channels exist for unresolved user issues.

### 14.2 Recommended Phases

#### Phase 1: Trustworthy Marketplace Core

- Public discovery and listing detail.
- Registration, OTP, login, role routing.
- Landlord verification.
- Tenant profile and verification.
- Listing creation and media.
- Messaging and enquiries.
- Booking and payment initiation.
- Admin verification review.

#### Phase 2: Transaction Depth

- Payment retry and virtual account improvements.
- Receipt and payment history polish.
- Rental progress-driven payout readiness.
- Tenant screening summaries.
- Landlord public profile trust signals.
- Support chat and operational issue triage.

#### Phase 3: Monetization and Retention

- Subscription plan packaging and upgrade prompts.
- Featured listings optimization.
- Community chat for premium users.
- Review and reputation loops.
- Renewal reminders.
- Marketplace health analytics.

#### Phase 4: Scale and Risk Controls

- Advanced fraud monitoring.
- Admin payment and settlement dashboards.
- SLA tracking for verification and support.
- Automated landlord and property verification enhancements.
- Data retention and privacy self-service.

---

## 15. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Fake listings or fraudulent landlords | High loss of marketplace trust | Require landlord and property verification before trust-sensitive visibility and transactions. |
| Incomplete tenant profiles | Lower landlord confidence | Use progressive completion, clear prompts, and screening summaries. |
| Payment reconciliation errors | Financial and support risk | Use idempotent provider references, webhook verification, and admin exception views. |
| Sensitive data leakage | Legal and trust risk | Minimize landlord-facing fields, restrict admin access, protect documents, and audit data exposure. |
| Verification backlog | Slower activation | Provide admin queues, metrics, status transparency, and operational SLAs. |
| Low listing supply | Poor tenant conversion | Focus landlord acquisition, verified supply quality, and featured promotion tools. |
| Low tenant demand quality | Poor landlord retention | Strengthen tenant verification, profile completeness, and screening signals. |
| Subscription value unclear | Low conversion | Tie premium plans to concrete capabilities such as community access, visibility, support priority, or richer applicant tools. |

---

## 16. Dependencies

- Django REST Framework API.
- React/Vite frontend.
- PostgreSQL for core transactional data.
- Cache layer for production scalability and rate limiting.
- Media storage and delivery infrastructure.
- Flutterwave for payment checkout, virtual accounts, transaction verification, transfers, and webhooks.
- Dikript or equivalent identity/CAC verification provider.
- Email provider for OTP and transactional notifications.
- Background worker process for payout readiness and scheduled tasks.
- Admin operations team for verification and support workflows.

---

## 17. Open Questions

1. Should standard listings require full landlord and property verification before appearing publicly, or should unverified listings appear with reduced trust indicators?
2. What exact actions should each subscription tier unlock for tenants and landlords?
3. Should the refundable security deposit be held, split, or transferred differently from annual rent?
4. What operating policy determines when a landlord payout is released if tenant and landlord progress disagree?
5. Should direct contact information always be blocked before payment, or only flagged for review?
6. What is the target verification SLA for identity, property documents, and physical property checks?
7. Should tenant screening scores be visible as exact numbers, bands, or qualitative badges?
8. What legal documents should RentDirect generate or store for completed rentals?
9. What data retention policy applies to NIN, BVN, documents, failed verification attempts, and payment provider payloads?
10. Which geographic markets should be prioritized after initial Nigerian city coverage?

---

## 18. Source Traceability

This PRD is based on observed product capabilities and business intent in the application repository:

- Product positioning and mission: `apps/web/src/pages/about/about.md`, `apps/web/src/pages/HomePage.tsx`.
- How-it-works journey: `apps/web/src/pages/how-it-works/how-it-works.md`.
- Routes and product surface: `apps/web/src/App.tsx`.
- Listing, booking, payment, verification, subscription, support, and chat data models: `apps/api/core/models.py`.
- API product capabilities: `apps/api/core/views.py`, `apps/api/core/urls.py`.
- Pricing calculation: `apps/api/core/pricing.py`, `apps/web/src/utils/rent.ts`.
- Subscription plans: `apps/api/core/subscription-pricing.json`.
- Tenant screening logic: `apps/api/core/tenant_scoring.py`.
- Subscription access rules: `apps/api/core/subscription_access.py`.
- Application architecture context: `apps/README.md`, `apps/docs/architectural_review_and_recommendations.md`.
