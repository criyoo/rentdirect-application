import { ChangeEvent, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, resolveMediaUrl } from '@/lib/api'
import { isNigeriaSelection, nigeriaStateLgaMap, nigerianStates, stateOfOriginOptions, worldCountryOptions } from '@/lib/locations'
import { validateMobile, validateNin, validateResidence } from '@/lib/profile'
import { User, UserResidence } from '@/types'
import TenantProfileDetailsForm from '@/components/TenantProfileDetailsForm'

type UploadedDocument = { id: string; title: string; file_url?: string }
type PaginatedResponse<T> = { results?: T[] }

type IndividualLandlordProfileForm = {
    first_name: string
    middle_name: string
    last_name: string
    date_of_birth: string
    gender: string
    nationality: string
    state_of_origin: string
    lga_of_origin: string
    preferred_contact_method: string
    bio: string
    phone_number: string
    whatsapp_number: string
    email_address: string
    id_type: string
    id_number: string
    id_expiry_date: string
    residential_country: string
    residential_state: string
    residential_city: string
    residential_address: string
    proof_of_address: string[]
    ownership_types: string[]
    bank_name: string
    account_name: string
    account_number: string
    minimum_lease_duration: string
    maximum_occupancy: string
    pets_allowed: boolean
    smoking_allowed: boolean
    commercial_activities_allowed: boolean
    short_let_allowed: boolean
    student_tenants_allowed: boolean
    corp_members_allowed: boolean
    expatriates_allowed: boolean
    emergency_first_name: string
    emergency_middle_name: string
    emergency_last_name: string
    emergency_phone_number: string
    emergency_email: string
    emergency_relationship: string
    emergency_address: string
}

type IndividualLandlordBooleanField =
    | 'pets_allowed'
    | 'smoking_allowed'
    | 'commercial_activities_allowed'
    | 'short_let_allowed'
    | 'student_tenants_allowed'
    | 'corp_members_allowed'
    | 'expatriates_allowed'

type IndividualLandlordArrayField = 'proof_of_address' | 'ownership_types'

const rentalPreferenceOptions: Array<{ field: IndividualLandlordBooleanField; label: string }> = [
    { field: 'pets_allowed', label: 'Pets Allowed?' },
    { field: 'smoking_allowed', label: 'Smoking Allowed?' },
    { field: 'commercial_activities_allowed', label: 'Commercial Activities Allowed?' },
    { field: 'short_let_allowed', label: 'Short-let Allowed?' },
    { field: 'student_tenants_allowed', label: 'Student Tenants Allowed?' },
    { field: 'corp_members_allowed', label: 'Corp Members Allowed?' },
    { field: 'expatriates_allowed', label: 'Expatriates Allowed?' },
]

type CorporateLandlordProfileForm = {
    registered_company_name: string
    trading_name: string
    cac_registration_number: string
    tax_identification_number: string
    vat_registration: string
    date_of_incorporation: string
    business_classification: string
    sector: string
    company_type: string
    company_email: string
    support_email: string
    company_phone_number: string
    website: string
    company_state: string
    company_city: string
    office_address: string
    corporate_verification_documents: string[]
    representative_first_name: string
    representative_middle_name: string
    representative_last_name: string
    representative_position: string
    representative_phone_number: string
    representative_email: string
    representative_state_of_origin: string
    representative_lga_of_origin: string
    representative_residence_state: string
    representative_residence_city: string
    representative_residence_address: string
    property_ownership_documents: string[]
    bank_name: string
    account_name: string
    account_number: string
}

type CorporateLandlordArrayField = 'corporate_verification_documents' | 'property_ownership_documents'

const LANDLORD_IDENTITY_ONBOARDING_KEY = 'landlord_onboarding_pending_identity'

const emptyIndividualLandlordProfileForm: IndividualLandlordProfileForm = {
    first_name: '',
    middle_name: '',
    last_name: '',
    date_of_birth: '',
    gender: '',
    nationality: '',
    state_of_origin: '',
    lga_of_origin: '',
    preferred_contact_method: '',
    bio: '',
    phone_number: '',
    whatsapp_number: '',
    email_address: '',
    id_type: '',
    id_number: '',
    id_expiry_date: '',
    residential_country: '',
    residential_state: '',
    residential_city: '',
    residential_address: '',
    proof_of_address: [],
    ownership_types: [],
    bank_name: '',
    account_name: '',
    account_number: '',
    minimum_lease_duration: '',
    maximum_occupancy: '',
    pets_allowed: false,
    smoking_allowed: false,
    commercial_activities_allowed: false,
    short_let_allowed: false,
    student_tenants_allowed: false,
    corp_members_allowed: false,
    expatriates_allowed: false,
    emergency_first_name: '',
    emergency_middle_name: '',
    emergency_last_name: '',
    emergency_phone_number: '',
    emergency_email: '',
    emergency_relationship: '',
    emergency_address: '',
}

const preferredContactMethodOptions = [
    { value: 'email', label: 'Email' },
    { value: 'sms', label: 'SMS' },
    { value: 'call', label: 'Call' },
    { value: 'whatsapp', label: 'Whatsapp' },
] as const

const proofOfAddressOptions = [
    'Utility Bill',
    'Bank Statement',
    'Tenancy Agreement',
] as const

const corporateVerificationDocumentOptions = [
    'CAC Certificate',
    'CAC Status Report',
    'Memorandum & Articles',
] as const

const corporatePropertyOwnershipDocumentOptions = [
    'Deed of Assignment',
    'C of O',
    "Governor's Consent",
    'Property Acquisition Documents',
] as const

const ownershipTypeOptions = [
    'Sole Owner',
    'Joint Owner',
    'Family Property Representative',
    'Attorney/Power of Attorney Holder',
    'Property Manager',
    'Trustee',
    'Mortgage Holder in Possession',
    'Developer-Owned Property',
] as const

const ownershipDocumentOptions = [
    'Certificate of Occupancy (C of O)',
    'Deed of Assignment',
    "Governor's Consent",
    'Registered Survey',
    'Probate Documentation',
    'Court Vesting Order',
    'Power of Attorney',
    'Land Use Charge Receipt',
    'Property Tax Receipt',
    'Lease Agreement',
    'Trust Deed',
    'Property Management Agreement',
] as const

const ownershipDocumentAliases: Record<(typeof ownershipDocumentOptions)[number], string[]> = {
    'Certificate of Occupancy (C of O)': ['Certificate of Occupancy (C of O)'],
    'Deed of Assignment': ['Deed of Assignment'],
    "Governor's Consent": ["Governor's Consent"],
    'Registered Survey': ['Registered Survey', 'Registered Survey Plan'],
    'Probate Documentation': ['Probate Documentation'],
    'Court Vesting Order': ['Court Vesting Order'],
    'Power of Attorney': ['Power of Attorney'],
    'Land Use Charge Receipt': ['Land Use Charge Receipt'],
    'Property Tax Receipt': ['Property Tax Receipt'],
    'Lease Agreement': ['Lease Agreement'],
    'Trust Deed': ['Trust Deed'],
    'Property Management Agreement': ['Property Management Agreement'],
}

const corporatePropertyOwnershipDocumentAliases: Record<(typeof corporatePropertyOwnershipDocumentOptions)[number], string[]> = {
    'Deed of Assignment': ['Deed of Assignment'],
    'C of O': ['C of O', 'Certificate of Occupancy (C of O)'],
    "Governor's Consent": ["Governor's Consent"],
    'Property Acquisition Documents': ['Property Acquisition Documents'],
}

const kycTypeOptions = [
    'National ID (NIN)',
    'International Passport',
    "Driver's License",
    "Voter's Card",
] as const

const emptyCorporateLandlordProfileForm: CorporateLandlordProfileForm = {
    registered_company_name: '',
    trading_name: '',
    cac_registration_number: '',
    tax_identification_number: '',
    vat_registration: '',
    date_of_incorporation: '',
    business_classification: '',
    sector: '',
    company_type: '',
    company_email: '',
    support_email: '',
    company_phone_number: '',
    website: '',
    company_state: '',
    company_city: '',
    office_address: '',
    corporate_verification_documents: [],
    representative_first_name: '',
    representative_middle_name: '',
    representative_last_name: '',
    representative_position: '',
    representative_phone_number: '',
    representative_email: '',
    representative_state_of_origin: '',
    representative_lga_of_origin: '',
    representative_residence_state: '',
    representative_residence_city: '',
    representative_residence_address: '',
    property_ownership_documents: [],
    bank_name: '',
    account_name: '',
    account_number: '',
}

function parseErrorMessage(error: any, fallback: string): string {
    if (typeof error?.response?.data === 'string') {
        return error.response.data
    }
    if (error?.response?.data?.detail) {
        return error.response.data.detail
    }
    if (error?.response?.data?.residence) {
        return error.response.data.residence
    }
    return error?.message || fallback
}

function normalizeResidence(residence?: UserResidence | null): UserResidence {
    return {
        state: residence?.state || '',
        city: residence?.city || '',
        address: residence?.address || '',
        origin_country: residence?.origin_country || '',
        origin_city: residence?.origin_city || '',
    }
}

function normalizeResults<T>(payload: T[] | PaginatedResponse<T> | undefined): T[] {
    if (!payload) {
        return []
    }
    if (Array.isArray(payload)) {
        return payload
    }
    return Array.isArray(payload.results) ? payload.results : []
}

function asRecord(value: unknown): Record<string, any> {
    if (value && typeof value === 'object' && !Array.isArray(value)) {
        return value as Record<string, any>
    }
    return {}
}

function toStringArray(value: unknown): string[] {
    if (!Array.isArray(value)) {
        return []
    }
    return value
        .filter((item): item is string => typeof item === 'string')
        .map((item) => item.trim())
        .filter(Boolean)
}

function toBoolean(value: unknown): boolean {
    if (typeof value === 'boolean') {
        return value
    }
    if (typeof value === 'string') {
        return value.trim().toLowerCase() === 'true'
    }
    return false
}

function uniqueStringValues(values: string[]): string[] {
    return Array.from(new Set(values.map((value) => value.trim()).filter(Boolean)))
}

function filterSelectedOptions(values: string[], options: readonly string[]): string[] {
    return uniqueStringValues(values).filter((value) => options.includes(value))
}

function deriveCorporateOwnershipDocuments(values: string[]): string[] {
    const selectedValues = new Set(uniqueStringValues(values))
    return corporatePropertyOwnershipDocumentOptions.filter((option) =>
        corporatePropertyOwnershipDocumentAliases[option].some((alias) => selectedValues.has(alias)),
    )
}

function splitFullName(value: string) {
    const parts = value.trim().split(/\s+/).filter(Boolean)
    return {
        first_name: parts[0] || '',
        middle_name: parts.slice(1, -1).join(' '),
        last_name: parts.length > 1 ? parts[parts.length - 1] : '',
    }
}

function buildFullName(firstName: string, middleName: string, lastName: string) {
    return [firstName, middleName, lastName].map((part) => part.trim()).filter(Boolean).join(' ')
}

function buildInitialIndividualLandlordProfileForm(profile: Record<string, any>, me: User): IndividualLandlordProfileForm {
    const nameParts = splitFullName(me.name || '')
    const kyc = asRecord(profile.kyc)
    const residentialInformation = asRecord(profile.residential_information)
    const bankingInformation = asRecord(profile.banking_information)
    const rentalPreferences = asRecord(profile.rental_preferences)
    const emergencyContact = asRecord(profile.emergency_contact)
    const residentialCountry = String(
        residentialInformation.country || (me.residence?.state || me.residence?.city ? 'Nigeria' : ''),
    )

    return {
        ...emptyIndividualLandlordProfileForm,
        first_name: String(profile.first_name || nameParts.first_name || ''),
        middle_name: String(profile.middle_name || nameParts.middle_name || ''),
        last_name: String(profile.last_name || nameParts.last_name || ''),
        date_of_birth: String(profile.date_of_birth || ''),
        gender: String(profile.gender || ''),
        nationality: String(profile.nationality || ''),
        state_of_origin: String(profile.state_of_origin || me.state_of_origin || ''),
        lga_of_origin: String(profile.lga_of_origin || ''),
        preferred_contact_method: String(profile.preferred_contact_method || ''),
        bio: String(profile.bio || profile.about_me || ''),
        phone_number: String(profile.contact_number || me.mobile || ''),
        whatsapp_number: String(profile.whatsapp_number || ''),
        email_address: String(profile.email || me.email || ''),
        id_type: String(kyc.id_type || ((profile.nin || me.nin_number) ? 'National ID (NIN)' : '')),
        id_number: String(kyc.id_number || profile.nin || me.nin_number || ''),
        id_expiry_date: String(kyc.expiry_date || ''),
        residential_country: residentialCountry,
        residential_state: String(residentialInformation.state || me.residence?.state || ''),
        residential_city: String(residentialInformation.city || me.residence?.city || ''),
        residential_address: String(residentialInformation.address || me.residence?.address || ''),
        proof_of_address: toStringArray(profile.proof_of_address),
        ownership_types: toStringArray(profile.ownership_types),
        bank_name: String(bankingInformation.bank_name || ''),
        account_name: String(bankingInformation.account_name || ''),
        account_number: String(bankingInformation.account_number || ''),
        minimum_lease_duration: String(rentalPreferences.minimum_lease_duration || ''),
        maximum_occupancy: String(rentalPreferences.maximum_occupancy || ''),
        pets_allowed: toBoolean(rentalPreferences.pets_allowed),
        smoking_allowed: toBoolean(rentalPreferences.smoking_allowed),
        commercial_activities_allowed: toBoolean(rentalPreferences.commercial_activities_allowed),
        short_let_allowed: toBoolean(rentalPreferences.short_let_allowed),
        student_tenants_allowed: toBoolean(rentalPreferences.student_tenants_allowed),
        corp_members_allowed: toBoolean(rentalPreferences.corp_members_allowed),
        expatriates_allowed: toBoolean(rentalPreferences.expatriates_allowed),
        emergency_first_name: String(emergencyContact.first_name || ''),
        emergency_middle_name: String(emergencyContact.middle_name || ''),
        emergency_last_name: String(emergencyContact.last_name || ''),
        emergency_phone_number: String(emergencyContact.phone_number || ''),
        emergency_email: String(emergencyContact.email || ''),
        emergency_relationship: String(emergencyContact.relationship || ''),
        emergency_address: String(emergencyContact.address || ''),
    }
}

function hasSavedLandlordProfileDetails(profile: Record<string, any>, verificationType?: string): boolean {
    if (verificationType === 'corporate') {
        return [
            'company_information',
            'company_contact_information',
            'authorized_representative',
            'property_ownership_verification',
            'banking_information',
        ].some((key) => Object.keys(asRecord(profile[key])).length > 0)
    }

    return [
        'kyc',
        'residential_information',
        'banking_information',
        'rental_preferences',
        'emergency_contact',
    ].some((key) => Object.keys(asRecord(profile[key])).length > 0)
        || toStringArray(profile.proof_of_address).length > 0
        || toStringArray(profile.ownership_types).length > 0
        || Boolean(String(profile.about_me || profile.bio || '').trim())
}

function buildInitialCorporateLandlordProfileForm(
    profile: Record<string, any>,
    me: User,
    uploadedPropertyDocuments: string[],
): CorporateLandlordProfileForm {
    const companyInformation = asRecord(profile.company_information)
    const companyContactInformation = asRecord(profile.company_contact_information)
    const corporateVerification = asRecord(profile.corporate_verification)
    const authorizedRepresentative = asRecord(profile.authorized_representative)
    const representativeResidence = asRecord(authorizedRepresentative.residence)
    const propertyOwnershipVerification = asRecord(profile.property_ownership_verification)
    const bankingInformation = asRecord(profile.banking_information)
    const representativeNameParts = splitFullName(
        String(
            profile.contact_person_name
            || authorizedRepresentative.full_name
            || me.name
            || '',
        ),
    )

    return {
        ...emptyCorporateLandlordProfileForm,
        registered_company_name: String(companyInformation.registered_company_name || profile.company_name || ''),
        trading_name: String(companyInformation.trading_name || ''),
        cac_registration_number: String(companyInformation.cac_registration_number || profile.cac_registration_number || ''),
        tax_identification_number: String(companyInformation.tax_identification_number || profile.tax_identification_number || ''),
        vat_registration: String(companyInformation.vat_registration || ''),
        date_of_incorporation: String(companyInformation.date_of_incorporation || ''),
        business_classification: String(companyInformation.business_classification || ''),
        sector: String(companyInformation.sector || ''),
        company_type: String(companyInformation.company_type || ''),
        company_email: String(companyContactInformation.company_email || profile.company_email || me.email || ''),
        support_email: String(companyContactInformation.support_email || ''),
        company_phone_number: String(companyContactInformation.phone_number || profile.company_phone_number || me.mobile || ''),
        website: String(companyContactInformation.website || ''),
        company_state: String(companyContactInformation.state || profile.business_state || me.residence?.state || ''),
        company_city: String(companyContactInformation.city || profile.business_city || me.residence?.city || ''),
        office_address: String(companyContactInformation.office_address || profile.business_address || me.residence?.address || ''),
        corporate_verification_documents: filterSelectedOptions(
            [
                ...toStringArray(corporateVerification.documents),
                ...toStringArray(profile.corporate_verification_documents),
            ],
            corporateVerificationDocumentOptions,
        ),
        representative_first_name: String(authorizedRepresentative.first_name || representativeNameParts.first_name || ''),
        representative_middle_name: String(authorizedRepresentative.middle_name || representativeNameParts.middle_name || ''),
        representative_last_name: String(authorizedRepresentative.last_name || representativeNameParts.last_name || ''),
        representative_position: String(authorizedRepresentative.position || profile.contact_person_position || ''),
        representative_phone_number: String(authorizedRepresentative.phone_number || me.mobile || ''),
        representative_email: String(authorizedRepresentative.email || me.email || ''),
        representative_state_of_origin: String(authorizedRepresentative.state_of_origin || me.state_of_origin || ''),
        representative_lga_of_origin: String(authorizedRepresentative.lga_of_origin || ''),
        representative_residence_state: String(representativeResidence.state || me.residence?.state || ''),
        representative_residence_city: String(representativeResidence.city || me.residence?.city || ''),
        representative_residence_address: String(representativeResidence.address || me.residence?.address || ''),
        property_ownership_documents: filterSelectedOptions(
            [
                ...toStringArray(propertyOwnershipVerification.documents),
                ...toStringArray(profile.property_ownership_verification_documents),
                ...uploadedPropertyDocuments,
            ],
            corporatePropertyOwnershipDocumentOptions,
        ),
        bank_name: String(bankingInformation.bank_name || ''),
        account_name: String(bankingInformation.account_name || ''),
        account_number: String(bankingInformation.account_number || ''),
    }
}

function buildIndividualLandlordVerificationProfile(
    currentProfile: Record<string, any>,
    form: IndividualLandlordProfileForm,
): Record<string, any> {
    const nextProfile: Record<string, any> = {
        ...currentProfile,
        first_name: form.first_name.trim(),
        middle_name: form.middle_name.trim(),
        last_name: form.last_name.trim(),
        date_of_birth: form.date_of_birth,
        gender: form.gender.trim(),
        nationality: form.nationality.trim(),
        state_of_origin: form.state_of_origin.trim(),
        lga_of_origin: form.lga_of_origin.trim(),
        preferred_contact_method: form.preferred_contact_method.trim(),
        bio: form.bio.trim(),
        about_me: form.bio.trim(),
        contact_number: form.phone_number.trim(),
        whatsapp_number: form.whatsapp_number.trim(),
        email: form.email_address.trim(),
        proof_of_address: form.proof_of_address,
        ownership_types: form.ownership_types,
        kyc: {
            id_type: form.id_type.trim(),
            id_number: form.id_number.trim(),
            expiry_date: form.id_expiry_date,
        },
        residential_information: {
            country: form.residential_country.trim(),
            state: form.residential_state.trim(),
            city: form.residential_city.trim(),
            address: form.residential_address.trim(),
        },
        banking_information: {
            bank_name: form.bank_name.trim(),
            account_name: form.account_name.trim(),
            account_number: form.account_number.trim(),
        },
        rental_preferences: {
            minimum_lease_duration: form.minimum_lease_duration.trim(),
            maximum_occupancy: form.maximum_occupancy.trim(),
            pets_allowed: form.pets_allowed,
            smoking_allowed: form.smoking_allowed,
            commercial_activities_allowed: form.commercial_activities_allowed,
            short_let_allowed: form.short_let_allowed,
            student_tenants_allowed: form.student_tenants_allowed,
            corp_members_allowed: form.corp_members_allowed,
            expatriates_allowed: form.expatriates_allowed,
        },
        emergency_contact: {
            first_name: form.emergency_first_name.trim(),
            middle_name: form.emergency_middle_name.trim(),
            last_name: form.emergency_last_name.trim(),
            phone_number: form.emergency_phone_number.trim(),
            email: form.emergency_email.trim(),
            relationship: form.emergency_relationship.trim(),
            address: form.emergency_address.trim(),
        },
    }

    if (form.id_type === 'National ID (NIN)' && form.id_number.trim()) {
        nextProfile.nin = form.id_number.trim()
    }

    return nextProfile
}

function buildCorporateLandlordVerificationProfile(
    currentProfile: Record<string, any>,
    form: CorporateLandlordProfileForm,
): Record<string, any> {
    const representativeFullName = buildFullName(
        form.representative_first_name,
        form.representative_middle_name,
        form.representative_last_name,
    )

    return {
        ...currentProfile,
        company_name: form.registered_company_name.trim(),
        business_state: form.company_state.trim(),
        business_city: form.company_city.trim(),
        business_address: form.office_address.trim(),
        company_phone_number: form.company_phone_number.trim(),
        company_email: form.company_email.trim(),
        contact_person_name: representativeFullName,
        contact_person_position: form.representative_position.trim(),
        cac_registration_number: form.cac_registration_number.trim(),
        tax_identification_number: form.tax_identification_number.trim(),
        company_information: {
            registered_company_name: form.registered_company_name.trim(),
            trading_name: form.trading_name.trim(),
            cac_registration_number: form.cac_registration_number.trim(),
            tax_identification_number: form.tax_identification_number.trim(),
            vat_registration: form.vat_registration.trim(),
            date_of_incorporation: form.date_of_incorporation,
            business_classification: form.business_classification.trim(),
            sector: form.sector.trim(),
            company_type: form.company_type.trim(),
        },
        company_contact_information: {
            company_email: form.company_email.trim(),
            support_email: form.support_email.trim(),
            phone_number: form.company_phone_number.trim(),
            website: form.website.trim(),
            state: form.company_state.trim(),
            city: form.company_city.trim(),
            office_address: form.office_address.trim(),
        },
        corporate_verification: {
            documents: form.corporate_verification_documents,
        },
        corporate_verification_documents: form.corporate_verification_documents,
        authorized_representative: {
            first_name: form.representative_first_name.trim(),
            middle_name: form.representative_middle_name.trim(),
            last_name: form.representative_last_name.trim(),
            full_name: representativeFullName,
            position: form.representative_position.trim(),
            phone_number: form.representative_phone_number.trim(),
            email: form.representative_email.trim(),
            state_of_origin: form.representative_state_of_origin.trim(),
            lga_of_origin: form.representative_lga_of_origin.trim(),
            residence: {
                state: form.representative_residence_state.trim(),
                city: form.representative_residence_city.trim(),
                address: form.representative_residence_address.trim(),
            },
        },
        property_ownership_verification: {
            documents: form.property_ownership_documents,
        },
        property_ownership_verification_documents: form.property_ownership_documents,
        banking_information: {
            bank_name: form.bank_name.trim(),
            account_name: form.account_name.trim(),
            account_number: form.account_number.trim(),
        },
    }
}

function parsePropertyDocumentTypesFromTitle(title: string): string[] {
    const prefix = 'Property Document:'
    if (!title.startsWith(prefix)) {
        return []
    }

    let selectedTypes = title.slice(prefix.length).trim()
    const fileNameSeparatorIndex = selectedTypes.lastIndexOf(' - ')
    if (fileNameSeparatorIndex >= 0) {
        selectedTypes = selectedTypes.slice(0, fileNameSeparatorIndex).trim()
    }

    return selectedTypes
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean)
}

function extractSelectedPropertyDocumentTypes(profile: Record<string, any>, documents: UploadedDocument[]): string[] {
    const storedSubmission = asRecord(profile.property_document_submission)
    const storedTypes = toStringArray(storedSubmission.document_types)
    const uploadedTypes = documents.flatMap((document) => parsePropertyDocumentTypesFromTitle(document.title))
    return Array.from(new Set([...storedTypes, ...uploadedTypes]))
}

export default function ProfilePage() {
    const formLabelClassName = 'form-label text-[12px]'
    const navigate = useNavigate()
    const [searchParams] = useSearchParams()
    const qc = useQueryClient()
    const { data: me, isLoading: isProfileLoading, isError: isProfileError } = useQuery({
        queryKey: ['users', 'me'],
        queryFn: async () => (await api.get<User>('/users/me')).data,
    })

    const { data: documentResponse } = useQuery({
        queryKey: ['documents', 'me'],
        queryFn: async () => (await api.get<UploadedDocument[] | PaginatedResponse<UploadedDocument>>('/documents')).data,
    })

    const landlordVerificationProfile = useMemo(() => {
        if (me?.landlord_verification_profile && typeof me.landlord_verification_profile === 'object') {
            return me.landlord_verification_profile as Record<string, any>
        }
        return {}
    }, [me?.landlord_verification_profile])

    const documents = useMemo(() => normalizeResults(documentResponse), [documentResponse])

    const [name, setName] = useState('')
    const [email, setEmail] = useState('')
    const [mobile, setMobile] = useState('')
    const [ninNumber, setNinNumber] = useState('')
    const [stateOfOrigin, setStateOfOrigin] = useState('')
    const [residence, setResidence] = useState<UserResidence>(normalizeResidence())
    const [individualLandlordForm, setIndividualLandlordForm] = useState<IndividualLandlordProfileForm>(emptyIndividualLandlordProfileForm)
    const [corporateLandlordForm, setCorporateLandlordForm] = useState<CorporateLandlordProfileForm>(emptyCorporateLandlordProfileForm)
    const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

    useEffect(() => {
        if (!me) {
            return
        }

        setName(me.name)
        setEmail(me.email)
        setMobile(me.mobile || '')
        setNinNumber(me.nin_number || '')
        setStateOfOrigin(me.state_of_origin || '')
        setResidence(normalizeResidence(me.residence))
        setIndividualLandlordForm(buildInitialIndividualLandlordProfileForm(landlordVerificationProfile, me))
        setCorporateLandlordForm(
            buildInitialCorporateLandlordProfileForm(
                landlordVerificationProfile,
                me,
                deriveCorporateOwnershipDocuments(
                    extractSelectedPropertyDocumentTypes(landlordVerificationProfile, documents),
                ),
            ),
        )
    }, [documents, landlordVerificationProfile, me])

    const isIndividualLandlordProfile = me?.role === 'landlord' && me.landlord_verification_type === 'individual'
    const isCorporateLandlordProfile = me?.role === 'landlord' && me.landlord_verification_type === 'corporate'
    const isLandlordOnboarding = searchParams.get('onboarding') === 'landlord'
    const isLandlordProfileLocked = (
        isIndividualLandlordProfile
        || isCorporateLandlordProfile
    ) && !isLandlordOnboarding && hasSavedLandlordProfileDetails(landlordVerificationProfile, me?.landlord_verification_type)
    const landlordProfileFieldsetClassName = [
        'space-y-8',
        isLandlordProfileLocked
            ? 'text-gray-500 [&_button]:cursor-not-allowed [&_input]:cursor-not-allowed [&_input]:bg-gray-100 [&_input]:text-gray-500 [&_select]:cursor-not-allowed [&_select]:bg-gray-100 [&_select]:text-gray-500 [&_textarea]:cursor-not-allowed [&_textarea]:bg-gray-100 [&_textarea]:text-gray-500'
            : '',
    ].filter(Boolean).join(' ')
    const hasPendingLandlordIdentity = localStorage.getItem(LANDLORD_IDENTITY_ONBOARDING_KEY) === '1'
    const individualStateLgaOptions = useMemo(
        () => (individualLandlordForm.state_of_origin ? nigeriaStateLgaMap[individualLandlordForm.state_of_origin] || [] : []),
        [individualLandlordForm.state_of_origin],
    )
    const corporateRepresentativeLgaOptions = useMemo(
        () => (corporateLandlordForm.representative_state_of_origin
            ? nigeriaStateLgaMap[corporateLandlordForm.representative_state_of_origin] || []
            : []),
        [corporateLandlordForm.representative_state_of_origin],
    )
    const residentialCountryIsNigeria = isNigeriaSelection(individualLandlordForm.residential_country)
    const selectedPropertyDocumentTypes = useMemo(
        () => extractSelectedPropertyDocumentTypes(landlordVerificationProfile, documents),
        [documents, landlordVerificationProfile],
    )
    const uploadedOwnershipDocuments = useMemo(() => {
        const selectedTypes = new Set(selectedPropertyDocumentTypes)
        return new Set(
            ownershipDocumentOptions.filter((option) => ownershipDocumentAliases[option].some((alias) => selectedTypes.has(alias))),
        )
    }, [selectedPropertyDocumentTypes])

    const validateProfile = (): boolean => {
        const nextErrors: Record<string, string> = {}

        const mobileError = validateMobile(mobile)
        if (mobileError) {
            nextErrors.mobile = mobileError
        }

        const ninError = validateNin(ninNumber)
        if (ninError) {
            nextErrors.nin_number = ninError
        }

        if (stateOfOrigin && !stateOfOriginOptions.includes(stateOfOrigin)) {
            nextErrors.state_of_origin = 'Choose a valid Nigerian state or Others.'
        }

        Object.assign(nextErrors, validateResidence(stateOfOrigin, residence))
        setFieldErrors(nextErrors)
        return Object.keys(nextErrors).length === 0
    }

    const validateIndividualLandlordProfile = (): boolean => {
        const nextErrors: Record<string, string> = {}

        const phoneError = validateMobile(individualLandlordForm.phone_number)
        if (phoneError) {
            nextErrors.phone_number = phoneError
        }

        const whatsappError = validateMobile(individualLandlordForm.whatsapp_number)
        if (whatsappError) {
            nextErrors.whatsapp_number = whatsappError
        }

        const emergencyPhoneError = validateMobile(individualLandlordForm.emergency_phone_number)
        if (emergencyPhoneError) {
            nextErrors.emergency_phone_number = emergencyPhoneError
        }

        if (individualLandlordForm.state_of_origin && !nigerianStates.includes(individualLandlordForm.state_of_origin)) {
            nextErrors.state_of_origin = 'Choose a valid Nigerian state.'
        }

        if (
            individualLandlordForm.lga_of_origin
            && individualStateLgaOptions.length > 0
            && !individualStateLgaOptions.includes(individualLandlordForm.lga_of_origin)
        ) {
            nextErrors.lga_of_origin = 'Choose a valid LGA.'
        }

        const residentialFields = [
            individualLandlordForm.residential_country.trim(),
            individualLandlordForm.residential_state.trim(),
            individualLandlordForm.residential_city.trim(),
            individualLandlordForm.residential_address.trim(),
        ]
        if (residentialFields.some(Boolean) && !residentialFields.every(Boolean)) {
            nextErrors.residential_information = 'Country, state, city, and address must all be provided together.'
        }

        if (
            residentialCountryIsNigeria
            && individualLandlordForm.residential_state
            && !nigerianStates.includes(individualLandlordForm.residential_state)
        ) {
            nextErrors.residential_state = 'Choose a valid Nigerian state.'
        }

        if (
            (individualLandlordForm.id_type.trim() && !individualLandlordForm.id_number.trim())
            || (individualLandlordForm.id_number.trim() && !individualLandlordForm.id_type.trim())
        ) {
            nextErrors.kyc = 'ID type and ID number must be provided together.'
        }

        if (individualLandlordForm.id_type === 'National ID (NIN)' && individualLandlordForm.id_number.trim()) {
            const idNumberError = validateNin(individualLandlordForm.id_number)
            if (idNumberError) {
                nextErrors.id_number = idNumberError
            }
        }

        const bankFields = [
            individualLandlordForm.bank_name.trim(),
            individualLandlordForm.account_name.trim(),
            individualLandlordForm.account_number.trim(),
        ]
        if (bankFields.some(Boolean) && !bankFields.every(Boolean)) {
            nextErrors.banking_information = 'Bank name, account name, and account number must all be provided together.'
        }

        setFieldErrors(nextErrors)
        return Object.keys(nextErrors).length === 0
    }

    const validateCorporateLandlordProfile = (): boolean => {
        const nextErrors: Record<string, string> = {}

        const companyPhoneError = validateMobile(corporateLandlordForm.company_phone_number)
        if (companyPhoneError) {
            nextErrors.company_phone_number = companyPhoneError
        }

        const representativePhoneError = validateMobile(corporateLandlordForm.representative_phone_number)
        if (representativePhoneError) {
            nextErrors.representative_phone_number = representativePhoneError
        }

        if (corporateLandlordForm.company_state && !nigerianStates.includes(corporateLandlordForm.company_state)) {
            nextErrors.company_state = 'Choose a valid Nigerian state.'
        }

        if (
            corporateLandlordForm.representative_state_of_origin
            && !nigerianStates.includes(corporateLandlordForm.representative_state_of_origin)
        ) {
            nextErrors.representative_state_of_origin = 'Choose a valid Nigerian state.'
        }

        if (
            corporateLandlordForm.representative_lga_of_origin
            && corporateRepresentativeLgaOptions.length > 0
            && !corporateRepresentativeLgaOptions.includes(corporateLandlordForm.representative_lga_of_origin)
        ) {
            nextErrors.representative_lga_of_origin = 'Choose a valid LGA.'
        }

        const representativeResidenceFields = [
            corporateLandlordForm.representative_residence_state.trim(),
            corporateLandlordForm.representative_residence_city.trim(),
            corporateLandlordForm.representative_residence_address.trim(),
        ]
        if (representativeResidenceFields.some(Boolean) && !representativeResidenceFields.every(Boolean)) {
            nextErrors.representative_residence = 'State, city, and address must all be provided together.'
        }

        if (
            corporateLandlordForm.representative_residence_state
            && !nigerianStates.includes(corporateLandlordForm.representative_residence_state)
        ) {
            nextErrors.representative_residence_state = 'Choose a valid Nigerian state.'
        }

        const bankFields = [
            corporateLandlordForm.bank_name.trim(),
            corporateLandlordForm.account_name.trim(),
            corporateLandlordForm.account_number.trim(),
        ]
        if (bankFields.some(Boolean) && !bankFields.every(Boolean)) {
            nextErrors.corporate_banking_information = 'Bank name, account name, and account number must all be provided together.'
        }

        setFieldErrors(nextErrors)
        return Object.keys(nextErrors).length === 0
    }

    const save = useMutation({
        mutationFn: async () => {
            if (isIndividualLandlordProfile) {
                if (!validateIndividualLandlordProfile()) {
                    throw new Error('Please fix the highlighted landlord profile fields.')
                }

                const nextProfile = buildIndividualLandlordVerificationProfile(landlordVerificationProfile, individualLandlordForm)
                const payload: Record<string, any> = {
                    name: buildFullName(
                        individualLandlordForm.first_name,
                        individualLandlordForm.middle_name,
                        individualLandlordForm.last_name,
                    ) || me?.name || '',
                    email: individualLandlordForm.email_address.trim(),
                    mobile: individualLandlordForm.phone_number.trim(),
                    state_of_origin: individualLandlordForm.state_of_origin.trim(),
                    landlord_verification_profile: nextProfile,
                }

                if (individualLandlordForm.id_type === 'National ID (NIN)' && individualLandlordForm.id_number.trim()) {
                    payload.nin_number = individualLandlordForm.id_number.trim()
                }

                await api.patch('/users/me', payload)
                return
            }

            if (isCorporateLandlordProfile) {
                if (!validateCorporateLandlordProfile()) {
                    throw new Error('Please fix the highlighted corporate profile fields.')
                }

                await api.patch('/users/me', {
                    landlord_verification_type: 'corporate',
                    landlord_verification_profile: buildCorporateLandlordVerificationProfile(
                        landlordVerificationProfile,
                        corporateLandlordForm,
                    ),
                })
                return
            }

            if (!validateProfile()) {
                throw new Error('Please fix the highlighted profile fields.')
            }

            await api.patch('/users/me', {
                name,
                email,
                mobile,
                nin_number: ninNumber,
                state_of_origin: stateOfOrigin,
                residence: {
                    state: residence.state?.trim() || '',
                    city: residence.city?.trim() || '',
                    address: residence.address?.trim() || '',
                    origin_country: stateOfOrigin === 'Others' ? residence.origin_country?.trim() || '' : '',
                    origin_city: stateOfOrigin === 'Others' ? residence.origin_city?.trim() || '' : '',
                },
            })
        },
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['users', 'me'] })
            if (isLandlordOnboarding && me?.role === 'landlord') {
                navigate(`/dashboard/landlord/${me.id}`)
                return
            }
            alert('Profile updated successfully!')
        },
        onError: (error) => {
            alert('Failed to update profile: ' + parseErrorMessage(error, 'Profile update failed'))
        },
    })

    const [photo, setPhoto] = useState<File | null>(null)
    const [previewUrl, setPreviewUrl] = useState<string | null>(null)

    useEffect(() => {
        if (!photo) {
            setPreviewUrl(null)
            return
        }

        const url = URL.createObjectURL(photo)
        setPreviewUrl(url)
        return () => URL.revokeObjectURL(url)
    }, [photo])

    const upload = useMutation({
        mutationFn: async () => {
            if (!photo) {
                return
            }
            const form = new FormData()
            form.append('file', photo)
            await api.post('/users/me/photo', form, { headers: { 'Content-Type': 'multipart/form-data' } })
        },
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['users', 'me'] })
            alert('Photo uploaded successfully!')
            setPhoto(null)
            setPreviewUrl(null)
        },
        onError: (error) => {
            alert('Failed to upload photo: ' + parseErrorMessage(error, 'Photo upload failed'))
        },
    })

    useEffect(() => {
        if (isProfileLoading || me?.role !== 'landlord' || !hasPendingLandlordIdentity) {
            return
        }

        if (me.is_verified) {
            localStorage.removeItem(LANDLORD_IDENTITY_ONBOARDING_KEY)
            return
        }

        navigate('/landlord/verification', { replace: true })
    }, [hasPendingLandlordIdentity, isProfileLoading, me?.is_verified, me?.role, navigate])

    const displayPhoto = previewUrl || resolveMediaUrl(me?.profile_photo_url)

    const handleIndividualLandlordChange = (
        event: ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>,
    ) => {
        const { name: fieldName, value } = event.target
        setIndividualLandlordForm((current) => {
            const next = { ...current, [fieldName]: value }

            if (fieldName === 'state_of_origin') {
                next.lga_of_origin = ''
            }

            if (fieldName === 'residential_country' && !isNigeriaSelection(value)) {
                next.residential_state = ''
            }

            return next
        })
        setFieldErrors((current) => {
            const next = { ...current, [fieldName]: '' }
            if (fieldName === 'state_of_origin') {
                next.lga_of_origin = ''
            }
            if (fieldName === 'id_type' || fieldName === 'id_number') {
                next.kyc = ''
            }
            if (fieldName === 'bank_name' || fieldName === 'account_name' || fieldName === 'account_number') {
                next.banking_information = ''
            }
            if (
                fieldName === 'residential_country'
                || fieldName === 'residential_state'
                || fieldName === 'residential_city'
                || fieldName === 'residential_address'
            ) {
                next.residential_information = ''
            }
            return next
        })
    }

    const toggleIndividualLandlordArrayValue = (fieldName: IndividualLandlordArrayField, value: string) => {
        setIndividualLandlordForm((current) => {
            const currentValues = current[fieldName]
            return {
                ...current,
                [fieldName]: currentValues.includes(value)
                    ? currentValues.filter((item) => item !== value)
                    : [...currentValues, value],
            }
        })
    }

    const setIndividualLandlordBooleanValue = (fieldName: IndividualLandlordBooleanField, value: boolean) => {
        setIndividualLandlordForm((current) => ({ ...current, [fieldName]: value }))
    }

    const handleCorporateLandlordChange = (
        event: ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>,
    ) => {
        const { name: fieldName, value } = event.target
        setCorporateLandlordForm((current) => {
            const next = { ...current, [fieldName]: value }

            if (fieldName === 'representative_state_of_origin') {
                next.representative_lga_of_origin = ''
            }

            return next
        })
        setFieldErrors((current) => {
            const next = { ...current, [fieldName]: '' }
            if (fieldName === 'representative_state_of_origin') {
                next.representative_lga_of_origin = ''
            }
            if (
                fieldName === 'representative_residence_state'
                || fieldName === 'representative_residence_city'
                || fieldName === 'representative_residence_address'
            ) {
                next.representative_residence = ''
            }
            if (fieldName === 'bank_name' || fieldName === 'account_name' || fieldName === 'account_number') {
                next.corporate_banking_information = ''
            }
            return next
        })
    }

    const toggleCorporateLandlordArrayValue = (fieldName: CorporateLandlordArrayField, value: string) => {
        setCorporateLandlordForm((current) => {
            const currentValues = current[fieldName]
            return {
                ...current,
                [fieldName]: currentValues.includes(value)
                    ? currentValues.filter((item) => item !== value)
                    : [...currentValues, value],
            }
        })
    }

    if (isProfileLoading) {
        return (
            <div className="container-modern py-8">
                <div className="rounded-xl border bg-white p-6 text-gray-600">Loading profile...</div>
            </div>
        )
    }

    if (isProfileError || !me) {
        return (
            <div className="container-modern py-8">
                <div className="rounded-xl border bg-white p-6">
                    <h1 className="text-xl font-semibold text-gray-900">Unable to load profile</h1>
                    <p className="mt-2 text-gray-600">Please refresh the page or sign in again.</p>
                </div>
            </div>
        )
    }

    if (me.role === 'landlord' && hasPendingLandlordIdentity) {
        return null
    }

    return (
        <div className="container-modern py-8">
            <div className="flex justify-between items-start mb-6">
                <div>
                    <h1 className="text-2xl font-bold">{me.name || 'My Profile'}</h1>
                    {isLandlordOnboarding && me.role === 'landlord' && (
                        <p className="mt-2 text-sm text-gray-600">Complete your profile to finish onboarding and continue to your dashboard.</p>
                    )}
                    {isIndividualLandlordProfile && (
                        <p className="mt-2 text-sm text-gray-600">Individual landlord profile</p>
                    )}
                    {isCorporateLandlordProfile && (
                        <p className="mt-2 text-sm text-gray-600">Corporate landlord profile</p>
                    )}
                </div>
                {displayPhoto && (
                    <img
                        src={displayPhoto}
                        alt="Profile"
                        className="h-20 w-20 rounded-full object-cover border-2 border-gray-200"
                    />
                )}
            </div>

            {isIndividualLandlordProfile ? (
                <>
                    {isLandlordProfileLocked && (
                        <div className="mb-6 rounded-xl border border-gray-200 bg-gray-50 p-4 text-sm text-gray-600">
                            Landlord profile details are locked here. Use <Link to="/dashboard/settings" className="font-semibold text-brand">Settings</Link> to request changes.
                        </div>
                    )}
                    <fieldset disabled={isLandlordProfileLocked} className={landlordProfileFieldsetClassName}>
                        <section className="rounded-xl border bg-white p-6">
                            <div className="flex justify-end">
                                <div className="w-full max-w-[20rem]">
                                    <div className="h-80 overflow-hidden rounded-2xl border border-gray-200 bg-gray-50">
                                        <div className="h-full">
                                            {displayPhoto ? (
                                                <img
                                                    src={displayPhoto}
                                                    alt="Profile Preview"
                                                    className="h-full w-full object-cover"
                                                />
                                            ) : (
                                                <div className="flex h-full w-full items-center justify-center bg-white text-sm text-gray-500">
                                                    No photo uploaded
                                                </div>
                                            )}
                                        </div>
                                    </div>

                                    <div className="mt-4 flex w-full max-w-[20rem] items-center gap-3">
                                        <input className="min-w-0 flex-1 text-sm" type="file" accept="image/*" onChange={(event) => setPhoto(event.target.files?.[0] ?? null)} />
                                        <button
                                            className="min-w-[130px] whitespace-nowrap rounded-md bg-brand px-3 py-2 text-white"
                                            onClick={() => upload.mutate()}
                                            disabled={upload.isPending || !photo}
                                        >
                                            {upload.isPending ? 'Uploading...' : 'Upload Photo'}
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </section>
                        <section className="rounded-xl border bg-white p-6">
                            <div>
                                <h2 className="text-xl font-semibold text-gray-900">Personal Information</h2>
                            </div>
                            <div className="mt-6 grid gap-4 md:grid-cols-3">
                                <div>
                                    <label className={formLabelClassName}>First Name</label>
                                    <input className="form-input" name="first_name" value={individualLandlordForm.first_name} onChange={handleIndividualLandlordChange} />
                                    {fieldErrors.first_name && <p className="form-error">{fieldErrors.first_name}</p>}
                                </div>
                                <div>
                                    <label className={formLabelClassName}>Middle Name</label>
                                    <input className="form-input" name="middle_name" value={individualLandlordForm.middle_name} onChange={handleIndividualLandlordChange} />
                                    {fieldErrors.middle_name && <p className="form-error">{fieldErrors.middle_name}</p>}
                                </div>
                                <div>
                                    <label className={formLabelClassName}>Last Name</label>
                                    <input className="form-input" name="last_name" value={individualLandlordForm.last_name} onChange={handleIndividualLandlordChange} />
                                    {fieldErrors.last_name && <p className="form-error">{fieldErrors.last_name}</p>}
                                </div>
                            </div>

                            <div className="mt-4 grid gap-4 md:grid-cols-3">
                                <div>
                                    <label className={formLabelClassName}>Date of Birth</label>
                                    <input className="form-input" type="date" name="date_of_birth" value={individualLandlordForm.date_of_birth} onChange={handleIndividualLandlordChange} />
                                    {fieldErrors.date_of_birth && <p className="form-error">{fieldErrors.date_of_birth}</p>}
                                </div>
                                <div>
                                    <label className={formLabelClassName}>Gender</label>
                                    <select className="form-input" name="gender" value={individualLandlordForm.gender} onChange={handleIndividualLandlordChange}>
                                        <option value="">Select gender</option>
                                        <option value="Male">Male</option>
                                        <option value="Female">Female</option>
                                        <option value="Other">Other</option>
                                        <option value="Prefer not to say">Prefer not to say</option>
                                    </select>
                                    {fieldErrors.gender && <p className="form-error">{fieldErrors.gender}</p>}
                                </div>
                                <div>
                                    <label className={formLabelClassName}>Preferred Contact Method</label>
                                    <select className="form-input" name="preferred_contact_method" value={individualLandlordForm.preferred_contact_method} onChange={handleIndividualLandlordChange}>
                                        <option value="">Select contact method</option>
                                        {preferredContactMethodOptions.map((option) => (
                                            <option key={option.value} value={option.value}>{option.label}</option>
                                        ))}
                                    </select>
                                    {fieldErrors.preferred_contact_method && <p className="form-error">{fieldErrors.preferred_contact_method}</p>}
                                </div>
                            </div>

                            <div className="mt-6 grid gap-4 md:grid-cols-3">
                                <div>
                                    <label className={formLabelClassName}>Phone Number</label>
                                    <input className="form-input" name="phone_number" value={individualLandlordForm.phone_number} onChange={handleIndividualLandlordChange} />
                                    {fieldErrors.phone_number && <p className="form-error">{fieldErrors.phone_number}</p>}
                                </div>
                                <div>
                                    <label className={formLabelClassName}>WhatsApp Number</label>
                                    <input className="form-input" name="whatsapp_number" value={individualLandlordForm.whatsapp_number} onChange={handleIndividualLandlordChange} />
                                    {fieldErrors.whatsapp_number && <p className="form-error">{fieldErrors.whatsapp_number}</p>}
                                </div>
                                <div>
                                    <label className={formLabelClassName}>Email Address</label>
                                    <input className="form-input" type="email" name="email_address" value={individualLandlordForm.email_address} onChange={handleIndividualLandlordChange} />
                                    {fieldErrors.email_address && <p className="form-error">{fieldErrors.email_address}</p>}
                                </div>
                            </div>

                            <div className="mt-4 grid gap-4 md:grid-cols-3">
                                <div>
                                    <label className={formLabelClassName}>Nationality</label>
                                    <select className="form-input" name="nationality" value={individualLandlordForm.nationality} onChange={handleIndividualLandlordChange}>
                                        <option value="">Select nationality</option>
                                        {worldCountryOptions.map((country) => (
                                            <option key={country} value={country}>{country}</option>
                                        ))}
                                    </select>
                                    {fieldErrors.nationality && <p className="form-error">{fieldErrors.nationality}</p>}
                                </div>
                                <div>
                                    <label className={formLabelClassName}>State of Origin</label>
                                    <select className="form-input" name="state_of_origin" value={individualLandlordForm.state_of_origin} onChange={handleIndividualLandlordChange}>
                                        <option value="">Select state</option>
                                        {nigerianStates.map((state) => (
                                            <option key={state} value={state}>{state}</option>
                                        ))}
                                    </select>
                                    {fieldErrors.state_of_origin && <p className="form-error">{fieldErrors.state_of_origin}</p>}
                                </div>
                                <div>
                                    <label className={formLabelClassName}>LGA</label>
                                    <select
                                        className="form-input"
                                        name="lga_of_origin"
                                        value={individualLandlordForm.lga_of_origin}
                                        onChange={handleIndividualLandlordChange}
                                        disabled={!individualLandlordForm.state_of_origin}
                                    >
                                        <option value="">{individualLandlordForm.state_of_origin ? 'Select LGA' : 'Select state first'}</option>
                                        {individualStateLgaOptions.map((lga) => (
                                            <option key={lga} value={lga}>{lga}</option>
                                        ))}
                                    </select>
                                    {fieldErrors.lga_of_origin && <p className="form-error">{fieldErrors.lga_of_origin}</p>}
                                </div>
                            </div>

                            <div className="mt-4 grid gap-4 md:grid-cols-1">
                                <div>
                                    <label className={formLabelClassName}>Bio/About Me</label>
                                    <textarea className="form-input min-h-28" name="bio" value={individualLandlordForm.bio} onChange={handleIndividualLandlordChange} />
                                    {fieldErrors.bio && <p className="form-error">{fieldErrors.bio}</p>}
                                </div>
                            </div>
                        </section>

                        <section className="rounded-xl border bg-white p-6">
                            <h2 className="text-xl font-semibold text-gray-900">Identity & Bank Verification (KYC)</h2>
                            <div className="mt-6 grid gap-4 md:grid-cols-3">
                                <div>
                                    <label className={formLabelClassName}>ID Type</label>
                                    <select className="form-input" name="id_type" value={individualLandlordForm.id_type} onChange={handleIndividualLandlordChange}>
                                        <option value="">Select ID type</option>
                                        {kycTypeOptions.map((option) => (
                                            <option key={option} value={option}>{option}</option>
                                        ))}
                                    </select>
                                </div>
                                <div>
                                    <label className={formLabelClassName}>ID Number</label>
                                    <input className="form-input" name="id_number" value={individualLandlordForm.id_number} onChange={handleIndividualLandlordChange} />
                                    {fieldErrors.id_number && <p className="form-error">{fieldErrors.id_number}</p>}
                                </div>
                                <div>
                                    <label className={formLabelClassName}>Expiry Date</label>
                                    <input className="form-input" type="date" name="id_expiry_date" value={individualLandlordForm.id_expiry_date} onChange={handleIndividualLandlordChange} />
                                </div>
                            </div>
                            {fieldErrors.kyc && <p className="form-error mt-3">{fieldErrors.kyc}</p>}



                            <div className="mt-6 grid gap-4 md:grid-cols-3">
                                <div>
                                    <label className={formLabelClassName}>Bank Name</label>
                                    <input className="form-input" name="bank_name" value={individualLandlordForm.bank_name} onChange={handleIndividualLandlordChange} />
                                </div>
                                <div>
                                    <label className={formLabelClassName}>Account Name</label>
                                    <input className="form-input" name="account_name" value={individualLandlordForm.account_name} onChange={handleIndividualLandlordChange} />
                                </div>
                                <div>
                                    <label className={formLabelClassName}>Account Number</label>
                                    <input className="form-input" name="account_number" value={individualLandlordForm.account_number} onChange={handleIndividualLandlordChange} />
                                </div>
                            </div>
                            <p className="mt-2 text-sm text-gray-600">For rent collection</p>
                            {fieldErrors.banking_information && <p className="form-error mt-3">{fieldErrors.banking_information}</p>}
                        </section>

                        <section className="rounded-xl border bg-white p-6">
                            <h2 className="text-xl font-semibold text-gray-900">Residential Information</h2>
                            <div className="mt-6 grid gap-4 md:grid-cols-3">
                                <div>
                                    <label className={formLabelClassName}>Country</label>
                                    <select className="form-input" name="residential_country" value={individualLandlordForm.residential_country} onChange={handleIndividualLandlordChange}>
                                        <option value="">Select country</option>
                                        {worldCountryOptions.map((country) => (
                                            <option key={country} value={country}>{country}</option>
                                        ))}
                                    </select>
                                </div>
                                <div>
                                    <label className={formLabelClassName}>State</label>
                                    {residentialCountryIsNigeria ? (
                                        <select className="form-input" name="residential_state" value={individualLandlordForm.residential_state} onChange={handleIndividualLandlordChange}>
                                            <option value="">Select state</option>
                                            {nigerianStates.map((state) => (
                                                <option key={state} value={state}>{state}</option>
                                            ))}
                                        </select>
                                    ) : (
                                        <input className="form-input" name="residential_state" value={individualLandlordForm.residential_state} onChange={handleIndividualLandlordChange} />
                                    )}
                                    {fieldErrors.residential_state && <p className="form-error">{fieldErrors.residential_state}</p>}
                                </div>
                                <div>
                                    <label className={formLabelClassName}>City</label>
                                    <input className="form-input" name="residential_city" value={individualLandlordForm.residential_city} onChange={handleIndividualLandlordChange} />
                                </div>
                            </div>
                            {fieldErrors.residential_information && <p className="form-error mt-3">{fieldErrors.residential_information}</p>}

                            <div className="mt-4 grid gap-4 md:grid-cols-1">
                                <div>
                                    <label className={formLabelClassName}>Address</label>
                                    <textarea className="form-input min-h-28" name="residential_address" value={individualLandlordForm.residential_address} onChange={handleIndividualLandlordChange} />
                                    {fieldErrors.residential_address && <p className="form-error">{fieldErrors.residential_address}</p>}
                                </div>
                            </div>

                            <div className="mt-6">
                                <label className={formLabelClassName}>Proof of Address</label>
                                <div className="mt-3 grid gap-3 md:grid-cols-3">
                                    {proofOfAddressOptions.map((option) => (
                                        <label key={option} className="flex items-center gap-3 rounded-lg border px-4 py-2">
                                            <input
                                                type="checkbox"
                                                checked={individualLandlordForm.proof_of_address.includes(option)}
                                                onChange={() => toggleIndividualLandlordArrayValue('proof_of_address', option)}
                                                className="h-4 w-4 rounded border-gray-300 text-blue-600"
                                            />
                                            <span className="text-sm text-gray-800">{option}</span>
                                        </label>
                                    ))}
                                </div>
                            </div>
                        </section>

                        <section className="rounded-xl border bg-white p-6">
                            <h2 className="text-xl font-semibold text-gray-900">Property Ownership Verification</h2>

                            <div className="mt-6">
                                <h3 className="text-sm font-semibold text-gray-900">Ownership Type</h3>
                                <div className="mt-3 grid gap-3 md:grid-cols-2">
                                    {ownershipTypeOptions.map((option) => (
                                        <label key={option} className="flex items-center gap-3 rounded-lg border px-4 py-3">
                                            <input
                                                type="checkbox"
                                                checked={individualLandlordForm.ownership_types.includes(option)}
                                                onChange={() => toggleIndividualLandlordArrayValue('ownership_types', option)}
                                                className="h-4 w-4 rounded border-gray-300 text-blue-600"
                                            />
                                            <span className="text-sm text-gray-800">{option}</span>
                                        </label>
                                    ))}
                                </div>
                            </div>
                            <br />
                            <div className="mt-6">
                                <div className="flex items-center justify-between gap-3">
                                    <h3 className="text-sm font-semibold text-gray-700">Ownership Documents</h3>
                                </div>
                                <div className="mt-3 grid gap-3 md:grid-cols-2">
                                    {ownershipDocumentOptions.map((option) => (
                                        <label key={option} className="flex items-center gap-3 rounded-lg border px-4 py-3">
                                            <input
                                                type="checkbox"
                                                checked={uploadedOwnershipDocuments.has(option)}
                                                readOnly
                                                disabled
                                                className="h-4 w-4 rounded border-gray-300 text-blue-600"
                                            />
                                            <span className="text-sm text-gray-800">{option}</span>
                                        </label>
                                    ))}
                                </div>
                                {selectedPropertyDocumentTypes.length === 0 && (
                                    <p className="mt-3 text-sm text-gray-500">You have opted in for in-person verification, an agent will visit to verify property documents</p>
                                )}
                            </div>
                        </section>

                        <section className="rounded-xl border bg-white p-6">
                            <h2 className="text-xl font-semibold text-gray-900">Rental Preferences</h2>
                            <div className="mt-6 grid gap-4 md:grid-cols-2">
                                <div>
                                    <label className={formLabelClassName}>Minimum Lease Duration</label>
                                    <input className="form-input" type="number" min="1" name="minimum_lease_duration" value={individualLandlordForm.minimum_lease_duration} onChange={handleIndividualLandlordChange} />
                                </div>
                                <div>
                                    <label className={formLabelClassName}>Maximum Occupancy</label>
                                    <input className="form-input" type="number" min="1" name="maximum_occupancy" value={individualLandlordForm.maximum_occupancy} onChange={handleIndividualLandlordChange} />
                                </div>
                            </div>

                            <div className="mt-6 grid gap-3 md:grid-cols-2">
                                {rentalPreferenceOptions.map((option) => (
                                    <div key={option.field} className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border px-4 py-3">
                                        <span className="text-sm text-gray-800">{option.label}</span>
                                        <div className="flex shrink-0 items-center gap-3">
                                            <label className="inline-flex items-center gap-1.5 text-sm font-medium text-gray-800">
                                                <input
                                                    type="checkbox"
                                                    checked={individualLandlordForm[option.field]}
                                                    onChange={() => setIndividualLandlordBooleanValue(option.field, true)}
                                                    className="h-4 w-4 rounded border-gray-300 text-blue-600"
                                                />
                                                Yes
                                            </label>
                                            <label className="inline-flex items-center gap-1.5 text-sm font-medium text-gray-800">
                                                <input
                                                    type="checkbox"
                                                    checked={!individualLandlordForm[option.field]}
                                                    onChange={() => setIndividualLandlordBooleanValue(option.field, false)}
                                                    className="h-4 w-4 rounded border-gray-300 text-blue-600"
                                                />
                                                No
                                            </label>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </section>

                        <section className="rounded-xl border bg-white p-6">
                            <h2 className="text-xl font-semibold text-gray-900">Emergency Contact</h2>
                            <div className="mt-6 grid gap-4 md:grid-cols-3">
                                <div>
                                    <label className={formLabelClassName}>First Name</label>
                                    <input className="form-input" name="emergency_first_name" value={individualLandlordForm.emergency_first_name} onChange={handleIndividualLandlordChange} />
                                </div>
                                <div>
                                    <label className={formLabelClassName}>Middle Name</label>
                                    <input className="form-input" name="emergency_middle_name" value={individualLandlordForm.emergency_middle_name} onChange={handleIndividualLandlordChange} />
                                </div>
                                <div>
                                    <label className={formLabelClassName}>Last Name</label>
                                    <input className="form-input" name="emergency_last_name" value={individualLandlordForm.emergency_last_name} onChange={handleIndividualLandlordChange} />
                                </div>
                            </div>

                            <div className="mt-4 grid gap-4 md:grid-cols-3">
                                <div>
                                    <label className={formLabelClassName}>Phone Number</label>
                                    <input className="form-input" name="emergency_phone_number" value={individualLandlordForm.emergency_phone_number} onChange={handleIndividualLandlordChange} />
                                    {fieldErrors.emergency_phone_number && <p className="form-error">{fieldErrors.emergency_phone_number}</p>}
                                </div>
                                <div>
                                    <label className={formLabelClassName}>Email</label>
                                    <input className="form-input" type="email" name="emergency_email" value={individualLandlordForm.emergency_email} onChange={handleIndividualLandlordChange} />
                                </div>
                                <div>
                                    <label className={formLabelClassName}>Relationship</label>
                                    <input className="form-input" name="emergency_relationship" value={individualLandlordForm.emergency_relationship} onChange={handleIndividualLandlordChange} />
                                </div>
                            </div>
                            <div className="mt-4 grid gap-4 md:grid-cols-1">
                                <div>
                                    <label className={formLabelClassName}>Address</label>
                                    <textarea className="form-input min-h-28" name="emergency_address" value={individualLandlordForm.emergency_address} onChange={handleIndividualLandlordChange} />
                                    {fieldErrors.emergency_address && <p className="form-error">{fieldErrors.emergency_address}</p>}
                                </div>
                            </div>
                        </section>

                        <div className="flex justify-end">
                            <button className="rounded-md bg-brand px-6 py-2 text-white" onClick={() => save.mutate()} disabled={save.isPending}>
                                {save.isPending ? 'Saving...' : isLandlordOnboarding ? 'Save and Continue' : 'Save Profile'}
                            </button>
                        </div>
                    </fieldset>
                </>
            ) : isCorporateLandlordProfile ? (
                <>
                    {isLandlordProfileLocked && (
                        <div className="mb-6 rounded-xl border border-gray-200 bg-gray-50 p-4 text-sm text-gray-600">
                            Landlord profile details are locked here. Use <Link to="/dashboard/settings" className="font-semibold text-brand">Settings</Link> to request changes.
                        </div>
                    )}
                    <fieldset disabled={isLandlordProfileLocked} className={landlordProfileFieldsetClassName}>
                        <section className="rounded-xl border bg-white p-6">
                            <div className="flex justify-end">
                                <div className="w-full max-w-[20rem]">
                                    <div className="h-80 overflow-hidden rounded-2xl border border-gray-200 bg-gray-50">
                                        <div className="h-full">
                                            {displayPhoto ? (
                                                <img
                                                    src={displayPhoto}
                                                    alt="Profile Preview"
                                                    className="h-full w-full object-cover"
                                                />
                                            ) : (
                                                <div className="flex h-full w-full items-center justify-center bg-white text-sm text-gray-500">
                                                    No photo uploaded
                                                </div>
                                            )}
                                        </div>
                                    </div>

                                    <div className="mt-4 flex w-full max-w-[20rem] items-center gap-3">
                                        <input className="min-w-0 flex-1 text-sm" type="file" accept="image/*" onChange={(event) => setPhoto(event.target.files?.[0] ?? null)} />
                                        <button
                                            className="min-w-[130px] whitespace-nowrap rounded-md bg-brand px-3 py-2 text-white"
                                            onClick={() => upload.mutate()}
                                            disabled={upload.isPending || !photo}
                                        >
                                            {upload.isPending ? 'Uploading...' : 'Upload Photo'}
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </section>

                        <section className="rounded-xl border bg-white p-6">
                            <h2 className="text-xl font-semibold text-gray-900">Company Information</h2>
                            <div className="mt-6 grid gap-4 md:grid-cols-2">
                                <div>
                                    <label className={formLabelClassName}>Registered Company Name</label>
                                    <input className="form-input" name="registered_company_name" value={corporateLandlordForm.registered_company_name} onChange={handleCorporateLandlordChange} />
                                </div>
                                <div>
                                    <label className={formLabelClassName}>Trading Name</label>
                                    <input className="form-input" name="trading_name" value={corporateLandlordForm.trading_name} onChange={handleCorporateLandlordChange} />
                                </div>
                            </div>
                            <div className="mt-4 grid gap-4 md:grid-cols-3">
                                <div>
                                    <label className={formLabelClassName}>CAC Registration Number</label>
                                    <input className="form-input" name="cac_registration_number" value={corporateLandlordForm.cac_registration_number} onChange={handleCorporateLandlordChange} />
                                </div>
                                <div>
                                    <label className={formLabelClassName}>Tax Identification Number</label>
                                    <input className="form-input" name="tax_identification_number" value={corporateLandlordForm.tax_identification_number} onChange={handleCorporateLandlordChange} />
                                </div>
                                <div>
                                    <label className={formLabelClassName}>VAT Registration</label>
                                    <input className="form-input" name="vat_registration" value={corporateLandlordForm.vat_registration} onChange={handleCorporateLandlordChange} />
                                </div>
                            </div>
                            <div className="mt-4 grid gap-4 md:grid-cols-4">
                                <div>
                                    <label className={formLabelClassName}>Date of Incorporation</label>
                                    <input className="form-input" type="date" name="date_of_incorporation" value={corporateLandlordForm.date_of_incorporation} onChange={handleCorporateLandlordChange} />
                                </div>
                                <div>
                                    <label className={formLabelClassName}>Business Classification</label>
                                    <input className="form-input" name="business_classification" value={corporateLandlordForm.business_classification} onChange={handleCorporateLandlordChange} />
                                </div>
                                <div>
                                    <label className={formLabelClassName}>Sector</label>
                                    <input className="form-input" name="sector" value={corporateLandlordForm.sector} onChange={handleCorporateLandlordChange} />
                                </div>
                                <div>
                                    <label className={formLabelClassName}>Company Type</label>
                                    <input className="form-input" name="company_type" value={corporateLandlordForm.company_type} onChange={handleCorporateLandlordChange} />
                                </div>
                            </div>
                        </section>

                        <section className="rounded-xl border bg-white p-6">
                            <h2 className="text-xl font-semibold text-gray-900">Contact Information</h2>
                            <div className="mt-6 grid gap-4 md:grid-cols-2">
                                <div>
                                    <label className={formLabelClassName}>Company Email</label>
                                    <input className="form-input" type="email" name="company_email" value={corporateLandlordForm.company_email} onChange={handleCorporateLandlordChange} />
                                </div>
                                <div>
                                    <label className={formLabelClassName}>Support Email</label>
                                    <input className="form-input" type="email" name="support_email" value={corporateLandlordForm.support_email} onChange={handleCorporateLandlordChange} />
                                </div>
                            </div>
                            <div className="mt-4 grid gap-4 md:grid-cols-2">
                                <div>
                                    <label className={formLabelClassName}>Phone Number</label>
                                    <input className="form-input" name="company_phone_number" value={corporateLandlordForm.company_phone_number} onChange={handleCorporateLandlordChange} />
                                    {fieldErrors.company_phone_number && <p className="form-error">{fieldErrors.company_phone_number}</p>}
                                </div>
                                <div>
                                    <label className={formLabelClassName}>Website</label>
                                    <input className="form-input" type="url" name="website" value={corporateLandlordForm.website} onChange={handleCorporateLandlordChange} placeholder="https://example.com" />
                                </div>
                            </div>
                            <div className="mt-4 grid gap-4 md:grid-cols-2">
                                <div>
                                    <label className={formLabelClassName}>State</label>
                                    <select className="form-input" name="company_state" value={corporateLandlordForm.company_state} onChange={handleCorporateLandlordChange}>
                                        <option value="">Select state</option>
                                        {nigerianStates.map((state) => (
                                            <option key={state} value={state}>{state}</option>
                                        ))}
                                    </select>
                                    {fieldErrors.company_state && <p className="form-error">{fieldErrors.company_state}</p>}
                                </div>
                                <div>
                                    <label className={formLabelClassName}>City</label>
                                    <input className="form-input" name="company_city" value={corporateLandlordForm.company_city} onChange={handleCorporateLandlordChange} />
                                </div>
                            </div>
                            <div className="mt-4">
                                <label className={formLabelClassName}>Office Address</label>
                                <textarea className="form-input min-h-28" name="office_address" value={corporateLandlordForm.office_address} onChange={handleCorporateLandlordChange} />
                            </div>
                        </section>

                        <section className="rounded-xl border bg-white p-6">
                            <h2 className="text-xl font-semibold text-gray-900">Authorized Representative</h2>
                            <div className="mt-6 grid gap-4 md:grid-cols-3">
                                <div>
                                    <label className={formLabelClassName}>First Name</label>
                                    <input className="form-input" name="representative_first_name" value={corporateLandlordForm.representative_first_name} onChange={handleCorporateLandlordChange} />
                                </div>
                                <div>
                                    <label className={formLabelClassName}>Middle Name</label>
                                    <input className="form-input" name="representative_middle_name" value={corporateLandlordForm.representative_middle_name} onChange={handleCorporateLandlordChange} />
                                </div>
                                <div>
                                    <label className={formLabelClassName}>Last Name</label>
                                    <input className="form-input" name="representative_last_name" value={corporateLandlordForm.representative_last_name} onChange={handleCorporateLandlordChange} />
                                </div>
                            </div>
                            <div className="mt-4 grid gap-4 md:grid-cols-3">
                                <div>
                                    <label className={formLabelClassName}>Position</label>
                                    <input className="form-input" name="representative_position" value={corporateLandlordForm.representative_position} onChange={handleCorporateLandlordChange} />
                                </div>
                                <div>
                                    <label className={formLabelClassName}>Phone Number</label>
                                    <input className="form-input" name="representative_phone_number" value={corporateLandlordForm.representative_phone_number} onChange={handleCorporateLandlordChange} />
                                    {fieldErrors.representative_phone_number && <p className="form-error">{fieldErrors.representative_phone_number}</p>}
                                </div>
                                <div>
                                    <label className={formLabelClassName}>Email</label>
                                    <input className="form-input" type="email" name="representative_email" value={corporateLandlordForm.representative_email} onChange={handleCorporateLandlordChange} />
                                </div>
                            </div>
                            <div className="mt-4 grid gap-4 md:grid-cols-2">
                                <div>
                                    <label className={formLabelClassName}>State of Origin</label>
                                    <select className="form-input" name="representative_state_of_origin" value={corporateLandlordForm.representative_state_of_origin} onChange={handleCorporateLandlordChange}>
                                        <option value="">Select state</option>
                                        {nigerianStates.map((state) => (
                                            <option key={state} value={state}>{state}</option>
                                        ))}
                                    </select>
                                    {fieldErrors.representative_state_of_origin && <p className="form-error">{fieldErrors.representative_state_of_origin}</p>}
                                </div>
                                <div>
                                    <label className={formLabelClassName}>LGA</label>
                                    <select
                                        className="form-input"
                                        name="representative_lga_of_origin"
                                        value={corporateLandlordForm.representative_lga_of_origin}
                                        onChange={handleCorporateLandlordChange}
                                        disabled={!corporateLandlordForm.representative_state_of_origin}
                                    >
                                        <option value="">
                                            {corporateLandlordForm.representative_state_of_origin ? 'Select LGA' : 'Select state first'}
                                        </option>
                                        {corporateRepresentativeLgaOptions.map((lga) => (
                                            <option key={lga} value={lga}>{lga}</option>
                                        ))}
                                    </select>
                                    {fieldErrors.representative_lga_of_origin && <p className="form-error">{fieldErrors.representative_lga_of_origin}</p>}
                                </div>
                            </div>

                            <div className="mt-6">
                                <h3 className="text-sm font-semibold text-gray-900">Residence</h3>
                                <div className="mt-3 grid gap-4 md:grid-cols-3">
                                    <div>
                                        <label className={formLabelClassName}>State</label>
                                        <select className="form-input" name="representative_residence_state" value={corporateLandlordForm.representative_residence_state} onChange={handleCorporateLandlordChange}>
                                            <option value="">Select state</option>
                                            {nigerianStates.map((state) => (
                                                <option key={state} value={state}>{state}</option>
                                            ))}
                                        </select>
                                        {fieldErrors.representative_residence_state && <p className="form-error">{fieldErrors.representative_residence_state}</p>}
                                    </div>
                                    <div>
                                        <label className={formLabelClassName}>City</label>
                                        <input className="form-input" name="representative_residence_city" value={corporateLandlordForm.representative_residence_city} onChange={handleCorporateLandlordChange} />
                                    </div>
                                    <div>
                                        <label className={formLabelClassName}>Address</label>
                                        <input className="form-input" name="representative_residence_address" value={corporateLandlordForm.representative_residence_address} onChange={handleCorporateLandlordChange} />
                                    </div>
                                </div>
                                {fieldErrors.representative_residence && <p className="form-error mt-3">{fieldErrors.representative_residence}</p>}
                            </div>
                        </section>

                        <section className="rounded-xl border bg-white p-6">
                            <h2 className="text-xl font-semibold text-gray-900">Property Ownership Verification</h2>
                            <div className="mt-6 grid gap-3 md:grid-cols-2">
                                {corporatePropertyOwnershipDocumentOptions.map((option) => (
                                    <label key={option} className="flex items-center gap-3 rounded-lg border px-4 py-3">
                                        <input
                                            type="checkbox"
                                            checked={corporateLandlordForm.property_ownership_documents.includes(option)}
                                            onChange={() => toggleCorporateLandlordArrayValue('property_ownership_documents', option)}
                                            className="h-4 w-4 rounded border-gray-300 text-blue-600"
                                        />
                                        <span className="text-sm text-gray-800">{option}</span>
                                    </label>
                                ))}
                            </div>
                            <br />
                            <br />
                            <p className="text-[13px]">Company Registration Document Submitted</p>
                            <div className="mt-2 grid gap-3 md:grid-cols-3">
                                {corporateVerificationDocumentOptions.map((option) => (
                                    <label key={option} className="flex items-center gap-3 rounded-lg border px-4 py-3">
                                        <input
                                            type="checkbox"
                                            checked={corporateLandlordForm.corporate_verification_documents.includes(option)}
                                            onChange={() => toggleCorporateLandlordArrayValue('corporate_verification_documents', option)}
                                            className="h-4 w-4 rounded border-gray-300 text-blue-600"
                                        />
                                        <span className="text-sm text-gray-800">{option}</span>
                                    </label>
                                ))}
                            </div>
                        </section>

                        <section className="rounded-xl border bg-white p-6">
                            <h2 className="text-xl font-semibold text-gray-900">Banking Information</h2>
                            <p className="mt-2 text-sm text-gray-600">Corporate account for rent collection</p>
                            <div className="mt-6 grid gap-4 md:grid-cols-3">
                                <div>
                                    <label className={formLabelClassName}>Bank Name</label>
                                    <input className="form-input" name="bank_name" value={corporateLandlordForm.bank_name} onChange={handleCorporateLandlordChange} />
                                </div>
                                <div>
                                    <label className={formLabelClassName}>Account Name</label>
                                    <input className="form-input" name="account_name" value={corporateLandlordForm.account_name} onChange={handleCorporateLandlordChange} />
                                </div>
                                <div>
                                    <label className={formLabelClassName}>Account Number</label>
                                    <input className="form-input" name="account_number" value={corporateLandlordForm.account_number} onChange={handleCorporateLandlordChange} />
                                </div>
                            </div>
                            {fieldErrors.corporate_banking_information && <p className="form-error mt-3">{fieldErrors.corporate_banking_information}</p>}
                        </section>

                        <div className="flex justify-end">
                            <button className="rounded-md bg-brand px-6 py-2 text-white" onClick={() => save.mutate()} disabled={save.isPending}>
                                {save.isPending ? 'Saving...' : isLandlordOnboarding ? 'Save and Continue' : 'Save Profile'}
                            </button>
                        </div>
                    </fieldset>
                </>
            ) : me.role === 'tenant' ? (
                <div className="space-y-8">
                    <div className="grid gap-8 lg:grid-cols-2">
                        <div className="rounded-xl border bg-white p-4">
                            <h4 className="font-semibold mb-3">Edit details</h4>
                            <div className="space-y-3">
                                <input className="w-full rounded-md border px-3 py-2" value={name} onChange={(event) => setName(event.target.value)} placeholder="Name" />
                                <input className="w-full rounded-md border px-3 py-2" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="Email" />
                                <div>
                                    <input className="w-full rounded-md border px-3 py-2" value={mobile} onChange={(event) => setMobile(event.target.value)} placeholder="Mobile number" />
                                    {fieldErrors.mobile && <p className="mt-1 text-sm text-red-600">{fieldErrors.mobile}</p>}
                                </div>
                                <div>
                                    <input className="w-full rounded-md border px-3 py-2" value={ninNumber} onChange={(event) => setNinNumber(event.target.value)} placeholder="NIN number" />
                                    {fieldErrors.nin_number && <p className="mt-1 text-sm text-red-600">{fieldErrors.nin_number}</p>}
                                </div>
                                <div>
                                    <select
                                        className="w-full rounded-md border px-3 py-2"
                                        value={stateOfOrigin}
                                        onChange={(event) => setStateOfOrigin(event.target.value)}
                                    >
                                        <option value="">Select state of origin</option>
                                        {stateOfOriginOptions.map((option) => (
                                            <option key={option} value={option}>{option}</option>
                                        ))}
                                    </select>
                                    {fieldErrors.state_of_origin && <p className="mt-1 text-sm text-red-600">{fieldErrors.state_of_origin}</p>}
                                </div>
                                {stateOfOrigin === 'Others' && (
                                    <div className="grid gap-3 md:grid-cols-2">
                                        <div>
                                            <input
                                                className="w-full rounded-md border px-3 py-2"
                                                value={residence.origin_country || ''}
                                                onChange={(event) => setResidence((current) => ({ ...current, origin_country: event.target.value }))}
                                                placeholder="Country of origin"
                                            />
                                            {fieldErrors.origin_country && <p className="mt-1 text-sm text-red-600">{fieldErrors.origin_country}</p>}
                                        </div>
                                        <div>
                                            <input
                                                className="w-full rounded-md border px-3 py-2"
                                                value={residence.origin_city || ''}
                                                onChange={(event) => setResidence((current) => ({ ...current, origin_city: event.target.value }))}
                                                placeholder="City of origin"
                                            />
                                            {fieldErrors.origin_city && <p className="mt-1 text-sm text-red-600">{fieldErrors.origin_city}</p>}
                                        </div>
                                    </div>
                                )}
                                <div className="rounded-lg border border-gray-200 p-3">
                                    <h5 className="mb-3 text-sm font-semibold text-gray-900">Residency information</h5>
                                    <div className="grid gap-3 md:grid-cols-2">
                                        <input
                                            className="w-full rounded-md border px-3 py-2"
                                            value={residence.state || ''}
                                            onChange={(event) => setResidence((current) => ({ ...current, state: event.target.value }))}
                                            placeholder="Residence state"
                                        />
                                        <input
                                            className="w-full rounded-md border px-3 py-2"
                                            value={residence.city || ''}
                                            onChange={(event) => setResidence((current) => ({ ...current, city: event.target.value }))}
                                            placeholder="City"
                                        />
                                    </div>
                                    <input
                                        className="mt-3 w-full rounded-md border px-3 py-2"
                                        value={residence.address || ''}
                                        onChange={(event) => setResidence((current) => ({ ...current, address: event.target.value }))}
                                        placeholder="Address"
                                    />
                                    {fieldErrors.residence && <p className="mt-2 text-sm text-red-600">{fieldErrors.residence}</p>}
                                </div>
                                <button className="rounded-md bg-brand px-6 py-0.5 text-white" onClick={() => save.mutate()} disabled={save.isPending}>
                                    {save.isPending ? 'Saving...' : 'Save'}
                                </button>
                            </div>
                        </div>

                        <div className="rounded-xl border bg-white p-4">
                            <div className="w-full max-w-[20rem] overflow-hidden rounded-2xl border border-gray-200 bg-gray-50">
                                <div className="mt-4">
                                    {displayPhoto ? (
                                        <img
                                            src={displayPhoto}
                                            alt="Profile Preview"
                                            className="h-80 w-full object-cover"
                                        />
                                    ) : (
                                        <div className="flex h-80 w-full items-center justify-center bg-white text-sm text-gray-500">
                                            No photo uploaded
                                        </div>
                                    )}
                                </div>
                            </div>

                            <div className="mt-4 flex w-full max-w-[20rem] items-center gap-3">
                                <input className="min-w-0 flex-1 text-sm" type="file" accept="image/*" onChange={(event) => setPhoto(event.target.files?.[0] ?? null)} />
                                <button
                                    className="min-w-[130px] whitespace-nowrap rounded-md bg-brand px-3 py-2 text-white"
                                    onClick={() => upload.mutate()}
                                    disabled={upload.isPending || !photo}
                                >
                                    {upload.isPending ? 'Uploading...' : 'Upload Photo'}
                                </button>
                            </div>
                        </div>
                    </div>

                    <TenantProfileDetailsForm />
                </div>
            ) : (
                <div className="grid gap-8 lg:grid-cols-2">
                    <div className="rounded-xl border bg-white p-4">
                        <h4 className="font-semibold mb-3">Edit details</h4>
                        <div className="space-y-3">
                            <input className="w-full rounded-md border px-3 py-2" value={name} onChange={(event) => setName(event.target.value)} placeholder="Name" />
                            <input className="w-full rounded-md border px-3 py-2" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="Email" />
                            <div>
                                <input className="w-full rounded-md border px-3 py-2" value={mobile} onChange={(event) => setMobile(event.target.value)} placeholder="Mobile number" />
                                {fieldErrors.mobile && <p className="mt-1 text-sm text-red-600">{fieldErrors.mobile}</p>}
                            </div>
                            <div>
                                <input className="w-full rounded-md border px-3 py-2" value={ninNumber} onChange={(event) => setNinNumber(event.target.value)} placeholder="NIN number" />
                                {fieldErrors.nin_number && <p className="mt-1 text-sm text-red-600">{fieldErrors.nin_number}</p>}
                            </div>
                            <div>
                                <select
                                    className="w-full rounded-md border px-3 py-2"
                                    value={stateOfOrigin}
                                    onChange={(event) => setStateOfOrigin(event.target.value)}
                                >
                                    <option value="">Select state of origin</option>
                                    {stateOfOriginOptions.map((option) => (
                                        <option key={option} value={option}>{option}</option>
                                    ))}
                                </select>
                                {fieldErrors.state_of_origin && <p className="mt-1 text-sm text-red-600">{fieldErrors.state_of_origin}</p>}
                            </div>
                            {stateOfOrigin === 'Others' && (
                                <div className="grid gap-3 md:grid-cols-2">
                                    <div>
                                        <input
                                            className="w-full rounded-md border px-3 py-2"
                                            value={residence.origin_country || ''}
                                            onChange={(event) => setResidence((current) => ({ ...current, origin_country: event.target.value }))}
                                            placeholder="Country of origin"
                                        />
                                        {fieldErrors.origin_country && <p className="mt-1 text-sm text-red-600">{fieldErrors.origin_country}</p>}
                                    </div>
                                    <div>
                                        <input
                                            className="w-full rounded-md border px-3 py-2"
                                            value={residence.origin_city || ''}
                                            onChange={(event) => setResidence((current) => ({ ...current, origin_city: event.target.value }))}
                                            placeholder="City of origin"
                                        />
                                        {fieldErrors.origin_city && <p className="mt-1 text-sm text-red-600">{fieldErrors.origin_city}</p>}
                                    </div>
                                </div>
                            )}
                            <div className="rounded-lg border border-gray-200 p-3">
                                <h5 className="mb-3 text-sm font-semibold text-gray-900">Residency information</h5>
                                <div className="grid gap-3 md:grid-cols-2">
                                    <input
                                        className="w-full rounded-md border px-3 py-2"
                                        value={residence.state || ''}
                                        onChange={(event) => setResidence((current) => ({ ...current, state: event.target.value }))}
                                        placeholder="Residence state"
                                    />
                                    <input
                                        className="w-full rounded-md border px-3 py-2"
                                        value={residence.city || ''}
                                        onChange={(event) => setResidence((current) => ({ ...current, city: event.target.value }))}
                                        placeholder="City"
                                    />
                                </div>
                                <input
                                    className="mt-3 w-full rounded-md border px-3 py-2"
                                    value={residence.address || ''}
                                    onChange={(event) => setResidence((current) => ({ ...current, address: event.target.value }))}
                                    placeholder="Address"
                                />
                                {fieldErrors.residence && <p className="mt-2 text-sm text-red-600">{fieldErrors.residence}</p>}
                            </div>
                            <button className="rounded-md bg-brand px-6 py-0.5 text-white" onClick={() => save.mutate()} disabled={save.isPending}>
                                {save.isPending ? 'Saving...' : isLandlordOnboarding && me.role === 'landlord' ? 'Save and Continue' : 'Save'}
                            </button>
                        </div>
                    </div>

                    <div className="rounded-xl border bg-white p-4">
                        <div className="w-full max-w-[20rem] overflow-hidden rounded-2xl border border-gray-200 bg-gray-50">
                            <div className="mt-4">
                                {displayPhoto ? (
                                    <img
                                        src={displayPhoto}
                                        alt="Profile Preview"
                                        className="h-120 w-full object-cover"
                                    />
                                ) : (
                                    <div className="flex h-80 w-full items-center justify-center bg-white text-sm text-gray-500">
                                        No photo uploaded
                                    </div>
                                )}
                            </div>
                        </div>
                        <div className="mt-4 flex w-full max-w-[20rem] items-center gap-3">
                            <input className="min-w-0 flex-1 text-sm" type="file" accept="image/*" onChange={(event) => setPhoto(event.target.files?.[0] ?? null)} />
                            <button className="min-w-[130px] whitespace-nowrap rounded-md bg-brand px-3 py-2 text-white" onClick={() => upload.mutate()} disabled={upload.isPending || !photo}>
                                {upload.isPending ? 'Uploading...' : 'Upload Photo'}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {me.role !== 'admin' && (
                <div className="mt-8 rounded-xl border bg-white p-4">
                    <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                        <div>
                            <h4 className="text-xl mb-2">Billing & Subscription</h4>
                            <p className="text-sm text-gray-600">
                                Manage your subscription and review payment history from the billing page.
                            </p>
                        </div>
                        <button
                            type="button"
                            onClick={() => navigate('/billing')}
                            className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50"
                        >
                            Open Billing
                        </button>
                    </div>
                </div>
            )}

        </div>
    )
}
