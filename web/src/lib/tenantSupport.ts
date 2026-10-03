export const tenantIssueTopics = [
    'Account access',
    'Tenant verification',
    'Billing or payment',
    'Property enquiry',
    'Booking or rental progress',
    'Profile update',
    'Technical issue',
    'Other',
] as const

export const landlordIssueTopics = [
    'Account access',
    'Landlord verification',
    'Listing management',
    'Tenant enquiry',
    'Billing or payout',
    'Rental progress',
    'Profile update',
    'Technical issue',
    'Other',
] as const

export const complaintTopics = [
    'Landlord conduct',
    'Property condition',
    'Payment concern',
    'Viewing experience',
    'Fraud or suspicious listing',
    'Service experience',
    'Other',
] as const

export const landlordComplaintTopics = [
    'Tenant conduct',
    'Payment concern',
    'Viewing experience',
    'Property listing concern',
    'Fraud or suspicious activity',
    'Service experience',
    'Other',
] as const

export const tenantSupportFaqs = [
    {
        question: 'How do I register as a tenant?',
        answer: 'Choose Find a home in the navigation menu, select the tenant registration option, create your account, and verify your email with the one-time code sent to you.',
    },
    {
        question: 'How do I complete tenant verification?',
        answer: 'Open Verification from your dashboard, complete your personal and identity information, review every legal document, scroll each document to the end, click I have read & consent, and then submit your NIN and BVN details for validation.',
    },
    {
        question: 'Why is my tenant profile asking me to go to Verification?',
        answer: 'A tenant must complete identity verification before the detailed tenant profile can be completed. Select Go to Verification, submit the verification information, and return to Profile afterwards.',
    },
    {
        question: 'How do I find a property and contact a landlord?',
        answer: 'Use Search to filter available listings, open a property to review its details, and send an enquiry when your account is eligible. Complete tenant verification before contacting landlords directly.',
    },
    {
        question: 'Where can I track rent payments and rental progress?',
        answer: 'Billing shows subscription and payment information. Active bookings, balances, and the steps for a rental are available from your dashboard and Rental Progress page.',
    },
    {
        question: 'Can I update my tenant profile after verification?',
        answer: 'Yes. Open Profile from your dashboard to keep your photo, residence, employment, financial, guarantor, and rental history information current. Changes may be reviewed again.',
    },
    {
        question: 'How do I report a suspicious property or landlord?',
        answer: 'Use Complaint for urgent concerns involving suspected fraud, a suspicious listing, landlord conduct, payment concerns, or a viewing experience. Use Issues for account and platform problems.',
    },
    {
        question: 'How do I contact RentDirect support?',
        answer: 'Open Support for the support phone number, email, FAQ, and Support Chat. Open Issues when you need to submit an account, payment, technical, or rental workflow issue.',
    },
    {
        question: 'How do I manage my subscriptions and payments?',
        answer: 'Open Billing from the dashboard to review subscription plans and payment records. Use the relevant rental or payment page to continue an outstanding payment or track its progress.',
    },
] as const

export const landlordSupportFaqs = [
    {
        question: 'How do I register as a landlord?',
        answer: 'Choose List a property in the navigation menu, select the landlord registration option, create your account, and verify your email with the one-time code sent to you.',
    },
    {
        question: 'How do I complete landlord verification?',
        answer: 'Open Verification from your dashboard, select Residential or Commercial Landlord, complete the required identity information, upload the requested identification documents, review every legal document, and click I have read & consent before submitting.',
    },
    {
        question: 'How do I verify property ownership?',
        answer: 'When creating or editing a listing, choose Upload documents or In-person verification. Upload the requested ownership documents or request a physical inspection by an authorised RentDirect property inspection officer or lawyer, then review and consent to the property verification terms.',
    },
    {
        question: 'Why can I not create a listing yet?',
        answer: 'Landlords must complete the required identity verification before creating a property listing. Open Verification from the dashboard, complete the form, upload identification documents, and submit it for review.',
    },
    {
        question: 'How do I manage my properties and featured listings?',
        answer: 'Use the landlord dashboard to add, edit, or manage properties. Use Featured to promote eligible listings and review featured placement payments.',
    },
    {
        question: 'Where can I track tenant payments and payouts?',
        answer: 'Your landlord dashboard shows collected payments, expected payments, outstanding balances, and payment information for active bookings. Billing contains subscription and payment records.',
    },
    {
        question: 'How do I respond to tenant enquiries?',
        answer: 'Open Enquiries from your dashboard to view tenant messages and continue each conversation. You can also use chat when a conversation is available.',
    },
    {
        question: 'How do I report a tenant, listing, or payment issue?',
        answer: 'Use Complaint for urgent concerns involving tenant conduct, suspected fraud, payment concerns, or a property listing. Use Issues for account, listing management, billing, technical, or rental progress problems.',
    },
    {
        question: 'How do I contact RentDirect support?',
        answer: 'Open Support for the support phone number, email, FAQ, and Support Chat. Open Issues when you need to submit a problem for the RentDirect team to investigate.',
    },
] as const

export const agentSupportFaqs = [
    {
        question: 'How do I register as a property inspection officer?',
        answer: 'Choose Become a PIO in the navigation menu, create your free account, and verify your email with the one-time code sent to you. There is no subscription for PIOs.',
    },
    {
        question: 'Why do I pay a ₦500 verification fee?',
        answer: 'A one-time ₦500 payment covers identity verification before you can claim inspection work. It is charged once and is not a subscription or recurring fee.',
    },
    {
        question: 'How do I complete PIO verification?',
        answer: 'Open Verification from your PIO dashboard, complete your personal, identity, and bank details, pay the ₦500 verification fee, review the Physical Inspection and Document Verification Agreement, and submit your NIN and BVN for validation.',
    },
    {
        question: 'How do I claim a property inspection?',
        answer: 'Once verified, open your PIO dashboard to see available in-person inspection requests. Select Claim on a listing to reserve it — each property can only be inspected by one PIO.',
    },
    {
        question: 'How do I earn from referrals?',
        answer: 'Every PIO gets a unique referral code on sign-up. Share it with new PIOs — when a referred PIO completes identity verification and submits inspections, you earn a bonus per inspection up to a cap for each referral. Open Referrals on your dashboard to see your code and referral tree.',
    },
    {
        question: 'How do I submit an inspection report?',
        answer: 'Open the claimed inspection, complete every required checklist section, upload supporting evidence, and choose Submit sign-off. Submitted reports are immutable and cannot be edited afterwards.',
    },
    {
        question: 'When do I get paid for an inspection?',
        answer: 'Your dashboard shows Total Earned, Total Paid Out, and Pending Payout for submitted inspections. RentDirect pays out approved inspection earnings to the bank account saved in your PIO profile.',
    },
    {
        question: 'How do I contact RentDirect support?',
        answer: 'Open Support for the support phone number, email, FAQ, and Support Chat. Your support chat is private to your PIO account.',
    },
] as const

export const tenantSupportContacts = {
    phone: '+2349163046786',
    email: 'support@rentdirect.homes',
    chat: 'Support Chat',
} as const
