import termsOfService from '@/legal/shared/terms-of-service.md?raw'
import privacyPolicy from '@/legal/shared/privacy-policy.md?raw'
import cookiesPolicy from '@/legal/shared/cookies-policy.md?raw'
import acceptableUsePolicy from '@/legal/shared/acceptable-use-policy.md?raw'
import verificationAndScreeningConsent from '@/legal/shared/verification-and-screening-consent.md?raw'
import marketplaceAndRentalDisclaimer from '@/legal/shared/marketplace-and-rental-disclaimer.md?raw'
import subscriptionAndPaymentPolicy from '@/legal/shared/subscription-and-payment-policy.md?raw'
import tenantRentalAndBookingTerms from '@/legal/tenant/tenant-rental-and-booking-terms.md?raw'
import tenantProfileAndScreeningConsent from '@/legal/tenant/tenant-profile-and-screening-consent.md?raw'
import landlordListingAndPropertyOwnerTerms from '@/legal/landlord/landlord-listing-and-property-owner-terms.md?raw'
import tenantDataUseTerms from '@/legal/landlord/tenant-data-use-terms.md?raw'
import propertyVerificationPhysicalInspectionTerms from '@/legal/landlord/property-verification-physical-inspection-terms.md?raw'
import physicalInspectionAndDocumentVerificationAgreement from '@/legal/agents/physical-inspection-and-document-verification-agreement.md?raw'

export type LegalDocumentAudience = 'shared' | 'tenant' | 'landlord' | 'agents'

export type LegalDocument = {
    slug: string
    title: string
    description: string
    audience: LegalDocumentAudience
    content: string
}

export const LEGAL_DOCUMENTS: LegalDocument[] = [
    {
        slug: 'terms-of-service',
        title: 'Terms of Service',
        description: 'The rules and conditions that apply when you use RentDirect.',
        audience: 'shared',
        content: termsOfService,
    },
    // {
    //     slug: 'privacy-policy',
    //     title: 'Privacy Policy',
    //     description: 'How RentDirect collects, uses, shares, protects, and retains information.',
    //     audience: 'shared',
    //     content: privacyPolicy,
    // },
    // {
    //     slug: 'cookies-policy',
    //     title: 'Cookies Policy',
    //     description: 'How cookies and similar technologies support the RentDirect experience.',
    //     audience: 'shared',
    //     content: cookiesPolicy,
    // },
    // {
    //     slug: 'acceptable-use-policy',
    //     title: 'Acceptable Use Policy',
    //     description: 'The conduct and content standards for RentDirect users.',
    //     audience: 'shared',
    //     content: acceptableUsePolicy,
    // },
    {
        slug: 'verification-and-screening-consent',
        title: 'Verification and Screening Consent',
        description: 'Consent for identity, document, screening, and verification activities.',
        audience: 'shared',
        content: verificationAndScreeningConsent,
    },
    {
        slug: 'marketplace-and-rental-disclaimer',
        title: 'Marketplace and Rental Disclaimer',
        description: 'Important limits on RentDirect’s role in property listings and rentals.',
        audience: 'shared',
        content: marketplaceAndRentalDisclaimer,
    },
    {
        slug: 'subscription-and-payment-policy',
        title: 'Subscription and Payment Policy',
        description: 'The payment, subscription, refund, and featured-property terms.',
        audience: 'shared',
        content: subscriptionAndPaymentPolicy,
    },
    {
        slug: 'tenant-rental-and-booking-terms',
        title: 'Tenant Rental and Booking Terms',
        description: 'Terms for tenant enquiries, applications, bookings, and rental progress.',
        audience: 'tenant',
        content: tenantRentalAndBookingTerms,
    },
    {
        slug: 'tenant-profile-and-screening-consent',
        title: 'Tenant Profile and Screening Consent',
        description: 'How tenant profile and screening information is supplied and used.',
        audience: 'tenant',
        content: tenantProfileAndScreeningConsent,
    },
    {
        slug: 'landlord-listing-and-property-owner-terms',
        title: 'Landlord Listing and Property Owner Terms',
        description: 'The obligations for landlords and property owners who list homes.',
        audience: 'landlord',
        content: landlordListingAndPropertyOwnerTerms,
    },
    {
        slug: 'tenant-data-use-terms',
        title: 'Tenant Data Use Terms',
        description: 'The rules for landlord access to and use of tenant information.',
        audience: 'landlord',
        content: tenantDataUseTerms,
    },
    {
        slug: 'property-verification-physical-inspection-terms',
        title: 'Property Verification and Physical Inspection Terms',
        description: 'Terms for document verification and an optional physical property inspection.',
        audience: 'landlord',
        content: propertyVerificationPhysicalInspectionTerms,
    },
    {
        slug: 'physical-inspection-and-document-verification-agreement',
        title: 'Physical Inspection and Document Verification Agreement',
        description: 'Agreement for RentDirect agents and lawyers conducting inspections.',
        audience: 'agents',
        content: physicalInspectionAndDocumentVerificationAgreement,
    },
]

export function getLegalDocumentBySlug(slug?: string): LegalDocument | undefined {
    return LEGAL_DOCUMENTS.find((document) => document.slug === slug)
}

export function getLegalDocumentsForAudience(audience: 'tenant' | 'landlord'): LegalDocument[] {
    return LEGAL_DOCUMENTS.filter((document) => document.audience === 'shared' || document.audience === audience)
}
