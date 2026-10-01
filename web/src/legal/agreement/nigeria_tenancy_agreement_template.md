# Nigeria Tenancy Agreement Template
## Property-type-specific — Lagos-ready, jurisdiction-aware

> **Template engine:** Handlebars-style placeholders (`{{variable}}`, `{{#if condition}}...{{/if}}`, `{{#each items}}...{{/each}}`).
>
> **Important:** This is an application template, not a substitute for legal review. The platform should select the applicable clauses based on the property's jurisdiction, use type, term, tenancy type and other structured inputs. A Nigerian property lawyer should review the production version before launch.

---

# TENANCY AGREEMENT

**Agreement ID:** {{agreement.id}}  
**Agreement Date:** {{agreement.dateFormatted}}  
**Jurisdiction:** {{property.state}}, Nigeria  
**Agreement Type:** {{tenancy.useTypeLabel}}

## BETWEEN

**LANDLORD / LESSOR**

**Name:** {{landlord.name}}  
**Address:** {{landlord.address}}  
**Email:** {{landlord.email}}  
**Phone:** {{landlord.phone}}

{{#if landlord.isCompany}}
The Landlord is a company/organisation duly incorporated or registered under the laws of the Federal Republic of Nigeria.
{{else}}
An Individual Landlord.
{{/if}}

AND

**TENANT / LESSEE**

**Name:** {{tenant.name}}  
**Address:** {{tenant.address}}  
**Email:** {{tenant.email}}  
**Phone:** {{tenant.phone}}

{{#if tenant.isCompany}}
The Tenant is a company/organisation duly incorporated or registered under the laws of the Federal Republic of Nigeria.
{{else}}
The Tenant is an individual.
{{/if}}

The Landlord and Tenant are each a **“Party”** and together the **“Parties.”**

---

# 1. PROPERTY

1.1 The Landlord lets to the Tenant the property known as:

**{{property.fullAddress}}**

and more particularly described as:

- **Property type:** {{property.type}}
{{#if tenancy.isCommercial}}
- **Unit / Shop / Office:** {{property.unitDescription}}
- **Number of rooms / offices:** {{property.roomsDescription}}
{{else}}
- **Unit / Apartment:** {{property.unitDescription}}
- **Number of bedrooms / rooms:** {{property.roomsDescription}}
{{/if}}
- **Floor:** {{property.floor}}
- **Parking / ancillary areas:** {{property.ancillaryAreas}}
- **Title / property reference (if applicable):** {{property.reference}}

together with the fixtures, fittings, access rights, common areas and appurtenances belonging to or serving the premises, as applicable (the **“Premises”**).

1.2 The Landlord represents, to the extent of the Landlord's knowledge and authority, that the Landlord has the right or authority to grant the tenancy.

1.3 The Tenant confirms that the Tenant has inspected the Premises, or has had a reasonable opportunity to inspect them, before execution of this Agreement, subject to any defects or exceptions expressly recorded in the condition report or handover schedule.

---

# 2. PURPOSE AND PERMITTED USE

2.1 The Premises shall be used only for the following purpose:

**{{tenancy.permittedUse}}**

{{#if tenancy.isCommercial}}
2.2 The Premises shall be used only for the lawful business or activity described above and for no other material purpose without the Landlord's prior written consent and any required governmental or regulatory approval.

2.3 The Tenant shall obtain and maintain all licences, permits and approvals required for the Tenant's business, except those expressly stated to be the Landlord's responsibility.
{{else}}
2.2 The Premises shall be used solely as a private residence by the Tenant and approved occupants recorded for this tenancy.

2.3 The Tenant shall not conduct a business from the Premises or use it for short-let accommodation without the Landlord's prior written consent and all approvals required by law.
{{/if}}

2.4 The Tenant shall not use the Premises for any unlawful purpose, nuisance, activity that materially interferes with neighbouring occupiers, or activity that breaches applicable planning, environmental, health, safety, estate or building-management requirements.

---

# 3. TERM AND POSSESSION

3.1 The tenancy is for a fixed term of **{{tenancy.termValue}} {{tenancy.termUnit}}**, commencing on **{{tenancy.startDateFormatted}}** and ending on **{{tenancy.endDateFormatted}}**, unless earlier determined in accordance with this Agreement or applicable law.

3.2 The Tenant's right to occupy the Premises shall commence upon:

**{{tenancy.possessionTrigger}}**

3.3 Where physical handover occurs on a date different from the contractual commencement date, the platform shall record the actual handover date and retain the signed handover record as part of the tenancy file.

3.4 Unless the Parties expressly agree otherwise in writing, expiry of a fixed term does not automatically create a new tenancy.

---

# 4. RENT

4.1 The rent payable for the tenancy is:

**₦{{money.rentAmount}} ({{money.rentAmountWords}})**

for the agreed rental period.

4.2 **Rent frequency:** {{payments.rentFrequency}}  
4.3 **Rent due date:** {{payments.rentDueDate}}  
4.4 **First rent period:** {{payments.firstRentPeriod}}  
4.5 **Payment method/account:** {{payments.paymentMethodDescription}}

4.6 The Tenant shall pay rent in accordance with the agreed payment schedule. Any rent received shall be acknowledged by a rent receipt or electronic payment record containing the information required by applicable law.

4.7 Nothing in this Agreement authorises either Party to demand, receive, offer or pay advance rent in excess of a limit imposed by applicable law.

{{#if payments.latePaymentInterestEnabled}}
4.8 If rent or another undisputed sum payable under this Agreement remains unpaid after the due date, the overdue amount shall attract interest at **{{payments.latePaymentInterestRate}}** per annum, subject to any statutory restriction and provided that such interest is lawful and enforceable.
{{/if}}

---

# 5. OTHER PAYMENTS AND CHARGES

The Parties agree that the following amounts apply:

| Charge | Amount | Frequency | Payable By | Refundable? |
|---|---:|---|---|---|
| Rent | ₦{{money.rentAmount}} | {{payments.rentFrequency}} | Tenant | No |
| Security / Caution Deposit | ₦{{money.securityDeposit}} | {{fees.securityDepositFrequency}} | Tenant | {{fees.securityDepositRefundable}} |
| Service Charge | ₦{{money.serviceCharge}} | {{fees.serviceChargeFrequency}} | Tenant | {{fees.serviceChargeRefundable}} |
| Facility / Estate Charge | ₦{{money.facilityCharge}} | {{fees.facilityChargeFrequency}} | Tenant | {{fees.facilityChargeRefundable}} |
| Agency / Commission Fee | ₦{{money.agencyFee}} | {{fees.agencyFeeFrequency}} | {{fees.agencyFeePayer}} | No |
| Other agreed charge(s) | ₦{{money.otherFeesTotal}} | {{fees.otherFeesFrequency}} | {{fees.otherFeesPayer}} | {{fees.otherFeesRefundable}} |

5.1 **Security / caution deposit.** Where a security deposit is payable, it shall be held and applied only in accordance with this Agreement and applicable law. Subject to lawful deductions for documented damage beyond fair wear and tear, unpaid sums or other agreed liabilities, the balance shall be returned to the Tenant within **{{fees.securityDepositRefundDays}} days** after vacant possession, final inspection and reconciliation of outstanding charges.

5.2 The Landlord or managing agent shall provide appropriate receipts or records for security deposits, service charges and facility/service payments where required by applicable law.

5.3 Where service charges or facility charges are collected by the Landlord or agent, the Tenant may request or receive an account of how such monies were applied to the extent required by applicable law.

5.4 Utility charges, including electricity, water, waste disposal, gas, diesel, internet and other consumption-based services, shall be paid as follows:

**{{fees.utilitiesResponsibility}}**

5.5 Taxes, statutory charges, levies and rates shall be borne by the Party responsible under applicable law and, where lawfully transferable by agreement, as follows:

**{{fees.taxesAndStatutoryCharges}}**

---

# 6. PROFESSIONAL, AGENCY AND LEGAL FEES

6.1 Each Party shall be responsible for professional fees arising from professionals separately engaged by that Party, except to the extent applicable law or this Agreement provides otherwise.

6.2 Any agency fee, legal fee or other professional charge payable by the Tenant shall be expressly stated in the payment schedule and shall not be implied.

6.3 Where stamping, registration, consent or other perfection of the tenancy/lease is legally required, the responsible Party and the applicable cost allocation shall be:

**{{fees.stampingRegistrationResponsibility}}**

---

# 7. LANDLORD'S COVENANTS

The Landlord covenants that, subject to the Tenant's compliance with this Agreement and applicable law:

7.1 The Tenant shall have quiet and peaceable enjoyment of the Premises during the tenancy without unlawful interruption by the Landlord or anyone claiming through the Landlord.

7.2 The Landlord shall comply with statutory obligations imposed on the Landlord, including applicable obligations relating to rates, insurance, structural/external maintenance and common parts.

7.3 The Landlord shall maintain the structure and external/common parts of the Premises to the extent that responsibility for those matters rests with the Landlord under applicable law or this Agreement.

7.4 The Landlord shall not unlawfully seize, remove or interfere with the Tenant's property or unlawfully restrict the Tenant's access to the Premises or the Tenant's personal property.

7.5 Where the Premises or a material part of the Premises becomes unfit for the permitted use because of an insured or other casualty not caused by the Tenant's breach, the Parties shall apply the rent-abatement, repair, termination and insurance provisions of this Agreement and applicable law.

---

# 8. TENANT'S COVENANTS

The Tenant covenants that the Tenant shall:

8.1 Pay rent and other sums due under this Agreement when due.

8.2 Keep the interior of the Premises in good and tenantable condition, fair wear and tear excepted.

8.3 Keep the Premises reasonably clean and dispose of waste appropriately.

8.4 Promptly notify the Landlord or managing agent of structural, electrical, plumbing, mechanical, water, safety or other material defects or damage.

8.5 Not make structural alterations, additions or material modifications without the Landlord's prior written consent and any required regulatory approval.

8.6 Not damage, obstruct or interfere with building systems, utilities, pipes, drains, conduits, wiring, equipment or installations serving the Premises or other premises.

8.7 Not assign, sublet, license or otherwise part with possession of the Premises or any material part of them without the Landlord's prior written consent, except where applicable law provides otherwise.

8.8 Not use the Premises for any unlawful, hazardous or materially disruptive purpose.

8.9 Comply with reasonable estate, facility-management, building, health and safety rules supplied to the Tenant, provided that such rules do not conflict with this Agreement or applicable law.

8.10 Not store explosives or unlawful or unreasonably hazardous substances at the Premises.

{{#if tenancy.isCommercial}}
8.11 Obtain the Landlord's prior written consent before displaying external signs, advertisements or branding, except for ordinary business signage expressly permitted by the Landlord and applicable planning rules.
{{/if}}

---

# 9. ACCESS, INSPECTION AND REPAIRS

9.1 The Landlord or authorised agent may enter the Premises at reasonable times after reasonable prior written notice to:

(a) inspect the condition of the Premises;  
(b) carry out repairs or maintenance for which the Landlord is responsible;  
(c) address an emergency; or  
(d) comply with a lawful requirement.

9.2 Except in an emergency or where otherwise permitted by law, the Landlord shall give at least **{{property.inspectionNoticeHours}} hours** prior notice of an inspection or non-emergency access.

9.3 The Landlord shall use reasonable efforts to minimise disruption to the Tenant's lawful use of the Premises.

{{#if tenancy.isCommercial}}
9.4 For commercial premises, access for valuation, insurance, prospective purchaser/tenant inspection or other legitimate purposes during the final **{{termination.preExpiryInspectionDays}} days** of the tenancy may be arranged at reasonable times and on reasonable notice, subject to the Tenant's business operations and applicable law.
{{else}}
9.4 For residential premises, access for a final inspection or a prospective purchaser or tenant during the final **{{termination.preExpiryInspectionDays}} days** may be arranged at reasonable times on reasonable notice, subject to the Tenant's privacy and applicable law.
{{/if}}

---

# 10. REPAIRS AND MAINTENANCE

10.1 The Landlord shall be responsible for:

**{{maintenance.landlordResponsibilities}}**

10.2 The Tenant shall be responsible for:

**{{maintenance.tenantResponsibilities}}**

10.3 Neither Party shall be responsible for damage caused solely by the other Party's negligence, wilful misconduct or breach, subject to applicable law.

{{#if tenancy.isCommercial}}
10.4 Where damage is caused by the Tenant, the Tenant's employees, contractors, customers, visitors or invitees, the Tenant shall be responsible for the reasonable cost of repair or reinstatement to the extent permitted by law.
{{else}}
10.4 Where damage is caused by the Tenant, the Tenant's household members, visitors or invitees, the Tenant shall be responsible for the reasonable cost of repair or reinstatement to the extent permitted by law.
{{/if}}

10.5 Where the Tenant makes an improvement with the Landlord's prior written consent, ownership, removal, reinstatement and compensation (if any) shall be governed by the written approval and applicable law.

---

# 11. INSURANCE

11.1 The Landlord shall maintain any insurance required by law or reasonably appropriate for the building and the Landlord's interest in the Premises.

{{#if tenancy.isCommercial}}
11.2 The Tenant shall maintain any insurance required by law and any insurance reasonably appropriate to the Tenant's business, contents, equipment, employees or third-party liabilities.
{{else}}
11.2 The Tenant shall maintain any insurance required by law and is responsible for deciding whether to insure personal belongings and contents kept at the Premises.
{{/if}}

11.3 The Tenant shall not do anything that knowingly invalidates or materially prejudices the Landlord's insurance.

---

# 12. COMPLIANCE WITH LAW

12.1 Each Party shall comply with all laws, regulations, planning requirements, health and safety requirements and lawful governmental directions applicable to that Party's obligations under this Agreement.

12.2 The Tenant shall not use the Premises in a manner that exposes the Landlord to avoidable fines, penalties, claims or regulatory action.

12.3 Nothing in this Agreement shall be interpreted as authorising self-help eviction, unlawful seizure of property, unlawful utility disconnection or any other remedy prohibited by applicable law.

---

# 13. DEFAULT

13.1 A Party is in default where that Party materially breaches this Agreement and, where the breach is capable of remedy, fails to remedy it within a reasonable period after receiving written notice specifying the breach and the required remedy.

13.2 Non-payment of rent or other sums shall be dealt with in accordance with the payment terms, any applicable cure period and the mandatory requirements of applicable law.

13.3 Where a breach is incapable of remedy, or where applicable law permits immediate action, the non-defaulting Party may exercise any lawful contractual or statutory remedy.

13.4 The Landlord's remedies are subject to applicable statutory notice, possession and court procedures.

---

# 14. TERMINATION AND RECOVERY OF POSSESSION

14.1 **Fixed term.** Where this is a fixed-term tenancy, the tenancy expires on the stated end date unless renewed or otherwise determined according to this Agreement and applicable law.

14.2 **Notice.** Where notice is required, the required notice period shall be the period stated below or the longer period required by applicable law:

**{{termination.noticePeriodDescription}}**

14.3 The platform shall not automatically generate a notice period that conflicts with mandatory law applicable to the property.

14.4 Where Lagos State Tenancy Law 2011 applies and the tenancy is a type for which the statute prescribes a notice period in the absence of a contractual stipulation, the statutory period shall be used by the platform unless a lawful alternative has been expressly selected.

14.5 Upon expiry or lawful determination of the tenancy, the Tenant shall give vacant possession of the Premises, return keys/access devices and remove the Tenant's belongings, subject to applicable law.

14.6 If the Tenant remains in possession after the tenancy has lawfully ended, any claim for use and occupation or mesne profits shall be determined in accordance with this Agreement and applicable law.

14.7 The Landlord shall use lawful procedures to recover possession. No provision of this Agreement authorises forcible or unlawful eviction.

---

# 15. RENEWAL

15.1 Renewal is **{{renewal.renewalOption}}**.

15.2 Where renewal is available, the Tenant shall notify the Landlord at least **{{renewal.noticeMonths}} months** before expiry, unless another period is stated here:

**{{renewal.specialRenewalNotice}}**

15.3 Unless expressly stated otherwise, renewal shall be subject to a new written agreement or written renewal instrument setting out the rent and other terms applicable to the renewed period.

---

# 16. HOLDING OVER

16.1 If the Tenant remains in possession after expiry or lawful determination without a new agreement, the Tenant shall be liable for reasonable use and occupation charges at:

**{{termination.holdingOverRateDescription}}**

subject always to applicable law and any order of a competent court.

16.2 Acceptance of any payment after expiry shall not, by itself, constitute a renewal where the Landlord expressly accepts it only as payment for use and occupation and applicable law permits such treatment.

---

# 17. ASSIGNMENT AND SUBLETTING

17.1 The Tenant shall not assign, sublet, license or otherwise transfer possession of the Premises without the Landlord's prior written consent, except to the extent that applicable law provides otherwise.

17.2 Any permitted assignment or subletting shall remain subject to all required approvals, documentation and applicable law.

{{#if tenancy.isCommercial}}
17.3 For commercial premises, any proposed assignment, change of control or sublease shall be handled in accordance with the specific provisions selected in the commercial tenancy schedule, if any.
{{/if}}

---

# 18. DAMAGE, DESTRUCTION AND UNAVAILABILITY

18.1 If the Premises are materially damaged or destroyed by fire, flood, storm, structural failure or another casualty so that they are wholly or materially unfit for the permitted use, the Parties shall promptly assess whether the Premises can reasonably be restored.

18.2 Where the Premises are unavailable for occupation due to a cause not attributable to the Tenant, rent shall be adjusted or suspended to the extent required by applicable law or as expressly agreed below:

**{{maintenance.rentAbatementRule}}**

18.3 If restoration cannot reasonably be completed within **{{maintenance.maximumRestorationDays}} days**, either Party may terminate the tenancy by written notice, subject to applicable law.

---

# 19. INDEMNITY AND LIABILITY

19.1 Each Party shall be responsible for loss, damage, cost or liability caused by that Party's negligence, wilful misconduct or material breach of this Agreement, subject to applicable law.

19.2 The Tenant shall indemnify the Landlord against reasonable third-party claims and direct losses arising from the Tenant's unlawful use of the Premises or material breach of this Agreement, except to the extent caused by the Landlord's negligence, wilful misconduct or breach.

19.3 Nothing in this Agreement excludes or limits liability that cannot lawfully be excluded or limited.

---

# 20. DISPUTE RESOLUTION

20.1 The Parties shall first attempt in good faith to resolve any dispute by direct discussion within **14 days** after written notice of the dispute.

20.2 If the dispute is not resolved, the Parties may refer it to mediation through an appropriate Lagos State mediation/ADR forum or another mutually agreed mediator.

20.3 Subject to the rights of the Parties under applicable law and the jurisdiction of the courts, the Parties may agree to arbitration as follows:

- **Arbitration:** {{dispute.arbitrationEnabled}}
- **Seat / venue:** {{dispute.arbitrationVenue}}
- **Number of arbitrators:** {{dispute.arbitratorCount}}
- **Appointing authority:** {{dispute.appointingAuthority}}

20.4 An arbitration clause shall not be interpreted as excluding the jurisdiction of a competent court where the law preserves that jurisdiction, including proceedings relating to possession, injunctions, enforcement or other statutory remedies.

---

# 21. NOTICES

21.1 Notices under this Agreement shall be in writing and delivered to the contact details recorded for the Parties in this Agreement or through a legally recognised method of service.

21.2 The platform may send ordinary contractual communications electronically to the verified email address, phone number or platform account of a Party.

21.3 **Statutory notices**, including notices relating to termination or recovery of possession, shall be served in the manner required by applicable law. An electronic platform notification shall not replace a statutory service method unless applicable law permits it.

21.4 Each Party shall promptly update the other Party and the platform when its address or contact details change.

---

# 22. ELECTRONIC EXECUTION AND RECORDS

22.1 The Parties agree that this Agreement may be executed electronically where permitted by applicable law.

22.2 Each Party confirms that the electronic signing process is intended to identify the signatory and record the signatory's intention to be bound by this Agreement.

22.3 The platform shall retain an audit trail containing, where available:

- the final agreement version;
- agreement ID;
- timestamp of generation;
- timestamp of each signature;
- signatory name and verified contact details;
- authentication method;
- IP/device/session information where lawfully collected;
- document hash or equivalent tamper-evidence record;
- signature certificate or signing evidence, where provided;
- version history and any subsequent amendment history.

22.4 No Party may amend the signed Agreement without a written amendment or replacement agreement signed/accepted by the Parties in accordance with applicable law.

22.5 Where a wet-ink, notarised, witnessed, stamped, registered or deed-form instrument is legally required for a particular transaction, the Parties shall complete that additional formality.

---

# 23. DATA PROTECTION

23.1 The Parties acknowledge that the platform may process personal data necessary to create, execute, administer, enforce and retain this Agreement and related tenancy records.

23.2 The platform shall process personal data in accordance with applicable Nigerian data-protection law and its privacy notice.

23.3 Personal data shall be limited to information reasonably necessary for the tenancy transaction, legal compliance, fraud prevention, identity verification, electronic signing, payment processing, dispute management and record retention.

23.4 Where third-party processors are used for identity verification, payments, document generation, electronic signatures, hosting or communications, the platform shall apply appropriate contractual and security safeguards.

---

# 24. STAMPING, REGISTRATION AND OTHER FORMALITIES

24.1 The Parties shall cooperate to complete any stamping, registration, consent, perfection or other legal formalities required for this tenancy or lease.

24.2 Responsibility for the cost of those formalities shall be:

**{{fees.stampingRegistrationResponsibility}}**

24.3 The platform shall not represent that this Agreement has been stamped, registered or perfected unless the relevant process has actually been completed and the supporting evidence is retained.

---

# 25. ENTIRE AGREEMENT

25.1 This Agreement, together with any schedules expressly incorporated into it, constitutes the agreement between the Parties concerning the tenancy.

25.2 Any amendment must be made in writing and accepted/executed by the Parties.

25.3 If there is a conflict between this Agreement and a schedule, the following order of precedence applies unless the schedule expressly states otherwise:

1. Mandatory applicable law;
2. Any deed or formally executed instrument required by law;
3. This Agreement;
4. Property/condition/handover schedules;
5. Other attachments or platform records.

---

# 26. SEVERABILITY

If any provision of this Agreement is found to be invalid, unlawful or unenforceable, that provision shall be modified or severed to the minimum extent necessary, and the remaining provisions shall continue to the extent permitted by law.

---

# 27. GOVERNING LAW AND JURISDICTION

27.1 This Agreement shall be governed by the laws applicable to the Premises.

27.2 Where the Premises are in Lagos State, the Parties acknowledge that applicable Lagos State legislation may include the Lagos State Tenancy Law 2011, subject to its scope and statutory exclusions, together with other applicable Nigerian and Lagos State laws.

27.3 The courts or other lawful dispute-resolution bodies having jurisdiction over the Premises shall have jurisdiction to the extent provided by law.

---

# 28. SPECIAL CONDITIONS

{{#if specialConditions}}
{{#each specialConditions}}
**{{this.title}}**

{{this.text}}

{{/each}}
{{else}}
No special conditions have been added.
{{/if}}

---

# 29. SCHEDULE 1 — PROPERTY / INVENTORY / CONDITION

**Property address:** {{property.fullAddress}}

**Handover date:** {{handover.dateFormatted}}

**Meter readings:**

- Electricity: {{handover.electricityMeterReading}}
- Water: {{handover.waterMeterReading}}
- Gas: {{handover.gasMeterReading}}
- Other: {{handover.otherMeterReadings}}

**Keys / access devices provided:** {{handover.keysDescription}}

**Furniture / fixtures / fittings:**  
{{handover.inventoryDescription}}

**Existing defects / exclusions:**  
{{handover.existingDefects}}

The Parties acknowledge that the condition/inventory record forms part of this Agreement where electronically attached or signed.

---

{{#if tenancy.isCommercial}}
# 30. SCHEDULE 2 — COMMERCIAL TENANCY DETAILS

**Business / trade:** {{commercial.businessDescription}}

**Permitted signage:** {{commercial.signageRules}}

**Opening / operating hours:** {{commercial.operatingHours}}

**Customer / public access:** {{commercial.customerAccessRules}}

**Licences / permits:** {{commercial.licensingResponsibilities}}

**Fit-out period:** {{commercial.fitOutPeriod}}

**Fit-out works permitted:** {{commercial.fitOutRules}}

**Restoration obligation at expiry:** {{commercial.reinstatementRules}}

**Service charge mechanism:** {{commercial.serviceChargeMechanism}}

**Insurance requirements:** {{commercial.insuranceRequirements}}

**Assignment / change of control provisions:** {{commercial.assignmentRules}}

---

# 31. SCHEDULE 3 — PAYMENT SUMMARY

| Item | Amount | Due / Frequency |
|---|---:|---|
| Rent | ₦{{money.rentAmount}} | {{payments.rentFrequency}} |
| Security / Caution Deposit | ₦{{money.securityDeposit}} | {{fees.securityDepositFrequency}} |
| Service Charge | ₦{{money.serviceCharge}} | {{fees.serviceChargeFrequency}} |
| Facility Charge | ₦{{money.facilityCharge}} | {{fees.facilityChargeFrequency}} |
| Agency Fee | ₦{{money.agencyFee}} | {{fees.agencyFeeFrequency}} |
| Other Fees | ₦{{money.otherFeesTotal}} | {{fees.otherFeesFrequency}} |
| **Total Initial Amount Payable** | **₦{{money.totalInitialAmount}}** | **{{payments.initialPaymentDueDate}}** |

---

# 32. EXECUTION
{{else}}
# 30. SCHEDULE 2 — PAYMENT SUMMARY

| Item | Amount | Due / Frequency |
|---|---:|---|
| Rent | ₦{{money.rentAmount}} | {{payments.rentFrequency}} |
| Security / Caution Deposit | ₦{{money.securityDeposit}} | {{fees.securityDepositFrequency}} |
| Service Charge | ₦{{money.serviceCharge}} | {{fees.serviceChargeFrequency}} |
| Facility Charge | ₦{{money.facilityCharge}} | {{fees.facilityChargeFrequency}} |
| Agency Fee | ₦{{money.agencyFee}} | {{fees.agencyFeeFrequency}} |
| Other Fees | ₦{{money.otherFeesTotal}} | {{fees.otherFeesFrequency}} |
| **Total Initial Amount Payable** | **₦{{money.totalInitialAmount}}** | **{{payments.initialPaymentDueDate}}** |

---

# 31. EXECUTION
{{/if}}

The Parties confirm that they have read and understood this Agreement and agree to be bound by its terms.

## LANDLORD / LESSOR

**Name:** {{landlord.name}}

**Signature:** ______________________________

**Date:** {{signatures.landlord.signedAtFormatted}}

**Electronic Signature ID:** {{signatures.landlord.signatureId}}

{{#if landlord.isCompany}}
**For and on behalf of:** {{landlord.name}}

**Authorised signatory name:** {{signatures.landlord.signatoryName}}

**Capacity:** {{signatures.landlord.signatoryCapacity}}
{{/if}}

## TENANT / LESSEE

**Name:** {{tenant.name}}

**Signature:** ______________________________

**Date:** {{signatures.tenant.signedAtFormatted}}

**Electronic Signature ID:** {{signatures.tenant.signatureId}}

{{#if tenant.isCompany}}
**For and on behalf of:** {{tenant.name}}

**Authorised signatory name:** {{signatures.tenant.signatoryName}}

**Capacity:** {{signatures.tenant.signatoryCapacity}}
{{/if}}

## WITNESS / WITNESSES

{{#each witnesses}}

**Witness {{@indexPlusOne}}**

Name: {{this.name}}  
Address: {{this.address}}  
Email: {{this.email}}  
Signature: ______________________________  
Date: {{this.signedAtFormatted}}

{{/each}}

---

## PLATFORM EXECUTION RECORD

**Agreement ID:** {{agreement.id}}  
**Template Version:** {{agreement.templateVersion}}  
**Generated At:** {{agreement.generatedAt}}  
**Finalised At:** {{agreement.finalisedAt}}  
**Document Hash:** {{agreement.documentHash}}  
**Signing Provider / Method:** {{agreement.signingProvider}}  
**Status:** {{agreement.status}}

---

## APPLICATION IMPLEMENTATION NOTES

### Recommended rendering

Use this document as a Handlebars-compatible source template. Store the agreement data separately in your application database and render an immutable snapshot when the Parties approve the agreement.

Recommended lifecycle:

`DRAFT → REVIEW → APPROVED → SIGNING → PARTIALLY_SIGNED → FULLY_SIGNED → FINAL`

After the first signature, freeze the agreement content. Any material change should create a new agreement version rather than mutate the signed document.

### Recommended conditional logic

The application should select clauses using structured fields such as:

- `property.state`
- `property.localGovernmentArea`
- `property.isInExcludedLagosTenancyArea`
- `tenancy.isCommercial` = `true | false`
- `tenancy.termValue`
- `tenancy.termUnit`
- `tenancy.rentFrequency`
- `tenancy.isFixedTerm`
- `landlord.entityType`
- `tenant.entityType`
- `fees.*`
- `commercial.*`
- `dispute.*`

### Lagos-specific rule engine

Do not hard-code the Lagos Tenancy Law 2011 as applying to every Lagos property.

For Lagos, calculate:

`lagosTenancyLawApplies = property.state === "Lagos" && !property.isExcludedFromLagosTenancyLaw`

The platform should flag properties in statutory excluded areas/categories for legal review rather than silently applying Lagos Tenancy Law clauses.

### Notice-period rule

Do not simply store a universal `noticePeriod = "1 month"`.

Instead calculate the applicable notice based on:

1. whether the Lagos Tenancy Law applies;
2. tenancy type/frequency;
3. whether the tenancy is fixed-term;
4. the contractual notice provision;
5. any mandatory statutory requirement.

### Rent rule

The application should validate advance-rent inputs before allowing execution. For premises to which section 4 of the Lagos Tenancy Law 2011 applies, the system should prevent configurations that conflict with the statutory limits.

### Payment receipt

After payment, generate a receipt containing at least:

- date received;
- landlord name and address;
- tenant name and address;
- property description/location;
- amount paid;
- period covered.

### Service charges

Where the landlord/agent collects security deposits, service/facility charges or similar amounts, retain separate payment records and support generation of statements/accounting records.

### Electronic signature evidence

Do not store only an image of a signature. Store evidence capable of showing:

- who signed;
- what document/version was signed;
- when it was signed;
- how the signatory was authenticated;
- whether the document was changed after signing.

### Legal review gates

Before production launch, have Nigerian counsel review at minimum:

- residential vs commercial treatment;
- Lagos excluded areas;
- fixed-term recovery/termination language;
- advance-rent validation;
- security/caution deposits;
- agency/legal fees;
- service-charge accounting;
- statutory notice/service;
- stamping;
- registration/perfection for longer leases;
- electronic execution/signature workflow;
- corporate signatory authority;
- dispute-resolution clause;
- data-protection wording.

