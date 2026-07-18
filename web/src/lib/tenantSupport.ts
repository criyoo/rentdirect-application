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
        question: 'How do I complete tenant verification?',
        answer: 'Open Verification from your dashboard, complete the identity form, and submit your NIN and BVN details for validation.',
    },
    {
        question: 'Where can I track rent payments?',
        answer: 'Billing shows subscription details, while your dashboard and rental progress page show active rental payments and balances.',
    },
    {
        question: 'Why can I not contact a landlord yet?',
        answer: 'Tenant accounts must complete verification before direct landlord enquiries are enabled.',
    },
    {
        question: 'How do I report a suspicious property?',
        answer: 'Use Complaint for urgent concerns about listings, viewing experiences, landlord conduct, or suspected fraud.',
    },
    {
        question: 'Can I update my tenant profile after verification?',
        answer: 'Yes. Open Profile from your dashboard to keep residence, employment, guarantor, and rental history details current.',
    },
] as const

export const landlordSupportFaqs = [
    {
        question: 'How do I complete landlord verification?',
        answer: 'Open Verification from your dashboard and submit the required identity and property ownership details.',
    },
    {
        question: 'Where can I manage featured listings?',
        answer: 'Use Featured from your dashboard to promote available listings and review featured listing payments.',
    },
    {
        question: 'Where can I track tenant payments?',
        answer: 'Your landlord dashboard shows collected payments, expected payouts, and outstanding balances for active bookings.',
    },
    {
        question: 'How do I respond to tenant enquiries?',
        answer: 'Open Enquiries from your dashboard to view tenant messages and continue each conversation.',
    },
    {
        question: 'How do I report a tenant or payment issue?',
        answer: 'Use Complaint for urgent concerns and Issues for account, listing, payment, or rental progress problems.',
    },
] as const

export const tenantSupportContacts = {
    phone: '+234 800 736 8347',
    email: 'support@rentdirect.homes',
    chat: 'Support Chat',
} as const
