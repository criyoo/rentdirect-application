import { ChangeEvent, useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { useAuth } from '@/hooks/useAuth'
import { useAppPopup } from '@/contexts/AppPopupContext'
import { api } from '@/lib/api'
import { isNigeriaSelection, nigeriaStateLgaMap, nigerianStates, worldCountryOptions } from '@/lib/locations'
import { LandlordVerificationType, User } from '@/types'

type PaginatedResponse<T> = { results?: T[] }

const LANDLORD_IDENTITY_ONBOARDING_KEY = 'landlord_onboarding_pending_identity'
const OTHER_CITY_OPTION = '__other_city__'

const nigerianBanks = [
    'Access Bank Plc',
    'Advans La Fayette Microfinance Bank',
    'Alpha Morgan Bank Limited',
    'Carbon Microfinance Bank',
    'Citibank Nigeria Limited',
    'Coronation Merchant Bank Limited',
    'Dot Microfinance Bank',
    'Ecobank Nigeria Limited',
    'FairMoney Microfinance Bank',
    'FBNQuest Merchant Bank Limited',
    'Fidelity Bank Plc',
    'First Bank of Nigeria Limited',
    'First City Monument Bank (FCMB)',
    'FSDH Merchant Bank Limited',
    'Globus Bank Limited',
    'Greenwich Merchant Bank Limited',
    'Guaranty Trust Bank (GTBank)',
    'Hope Payment Service Bank',
    'Jaiz Bank Plc',
    'Keystone Bank Limited',
    'Kuda Microfinance Bank',
    'Lotus Bank Limited',
    'Mint Microfinance Bank',
    'Mkobo Microfinance Bank',
    'MoMo Payment Service Bank (MTN)',
    'MoneyMaster Payment Service Bank (9mobile)',
    'Moniepoint Microfinance Bank',
    'Nova Merchant Bank Limited',
    'OPay',
    'Optimus Bank Limited',
    'PalmPay',
    'Parallex Bank Limited',
    'Polaris Bank Limited',
    'PremiumTrust Bank Limited',
    'Providus Bank Plc',
    'Rand Merchant Bank Nigeria Limited',
    'Raven Bank',
    'Rubies Microfinance Bank',
    'Signature Bank Limited',
    'SmartCash Payment Service Bank (Airtel)',
    'Sparkle Microfinance Bank',
    'Stanbic IBTC Bank Plc',
    'Standard Chartered Bank Nigeria Limited',
    'Sterling Bank Plc',
    'SunTrust Bank Nigeria Limited',
    'TAJBank Limited',
    'Tatum Bank Limited',
    'The Alternative Bank Limited',
    'Titan Trust Bank Limited',
    'Union Bank of Nigeria Plc',
    'United Bank for Africa (UBA) Plc',
    'Unity Bank Plc',
    'VFD Microfinance Bank',
    'Wema Bank Plc',
    'Zenith Bank Plc',
]

type UploadedDocument = {
    id: string
    title: string
    file_url?: string
}

type VerificationProgress = {
    status?: string
    submitted_at?: string | null
}

type VerificationStatusResponse = {
    status?: string
    identification?: VerificationProgress
}

type IndividualForm = {
    first_name: string
    middle_name: string
    last_name: string
    date_of_birth: string
    country_of_birth: string
    state_of_birth: string
    nationality: string
    state_of_origin: string
    lga_of_origin: string
    gender: string
    contact_number: string
    email: string
    nin: string
    bvn: string
    residential_address: string
    bank_name: string
    account_name: string
    account_number: string
}

type CorporateForm = {
    company_name: string
    business_state: string
    business_city: string
    business_city_other: string
    business_address: string
    company_phone_number: string
    company_email: string
    contact_person_name: string
    contact_person_position: string
    cac_registration_number: string
    cac_registration_date: string
    tax_identification_number: string
    nin: string
    bvn: string
    bank_name: string
    account_name: string
    account_number: string
}

const emptyIndividualForm: IndividualForm = {
    first_name: '',
    middle_name: '',
    last_name: '',
    date_of_birth: '',
    country_of_birth: '',
    state_of_birth: '',
    nationality: '',
    state_of_origin: '',
    lga_of_origin: '',
    gender: '',
    contact_number: '',
    email: '',
    nin: '',
    bvn: '',
    residential_address: '',
    bank_name: '',
    account_name: '',
    account_number: '',
}

const emptyCorporateForm: CorporateForm = {
    company_name: '',
    business_state: '',
    business_city: '',
    business_city_other: '',
    business_address: '',
    company_phone_number: '',
    company_email: '',
    contact_person_name: '',
    contact_person_position: '',
    cac_registration_number: '',
    cac_registration_date: '',
    tax_identification_number: '',
    nin: '',
    bvn: '',
    bank_name: '',
    account_name: '',
    account_number: '',
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

function normalizeVerificationType(value?: string | null): LandlordVerificationType | '' {
    if (value === 'individual' || value === 'corporate') {
        return value
    }
    return ''
}

function parseErrorMessage(error: any, fallback: string): string {
    if (typeof error?.response?.data === 'string') {
        return error.response.data
    }
    if (error?.response?.data?.detail) {
        return error.response.data.detail
    }
    if (typeof error?.response?.data === 'object') {
        const firstError = Object.values(error.response.data)[0]
        if (Array.isArray(firstError) && firstError[0]) {
            return String(firstError[0])
        }
        if (typeof firstError === 'string') {
            return firstError
        }
    }
    return error?.message || fallback
}

function stringValue(value: unknown): string {
    return String(value || '').trim()
}

function dateInputValue(value: unknown): string {
    const rawValue = stringValue(value)
    if (!rawValue) return ''
    if (/^\d{4}-\d{2}-\d{2}$/.test(rawValue)) return rawValue
    const slashMatch = rawValue.match(/^(\d{2})\/(\d{2})\/(\d{4})$/)
    if (slashMatch) return `${slashMatch[3]}-${slashMatch[2]}-${slashMatch[1]}`
    const dashMatch = rawValue.match(/^(\d{2})-(\d{2})-(\d{4})$/)
    if (dashMatch) return `${dashMatch[3]}-${dashMatch[2]}-${dashMatch[1]}`
    return rawValue
}

function isKnownNigerianCity(state: string, city: string): boolean {
    if (!state || !city) {
        return false
    }
    return (nigeriaStateLgaMap[state] || []).includes(city)
}

function buildCorporateProfilePayload(form: CorporateForm) {
    return {
        company_name: form.company_name,
        business_state: form.business_state,
        business_city: form.business_city === OTHER_CITY_OPTION ? form.business_city_other : form.business_city,
        business_address: form.business_address,
        company_phone_number: form.company_phone_number,
        company_email: form.company_email,
        contact_person_name: form.contact_person_name,
        contact_person_position: form.contact_person_position,
        cac_registration_number: form.cac_registration_number,
        cac_registration_date: form.cac_registration_date,
        tax_identification_number: form.tax_identification_number,
        nin: form.nin,
        bvn: form.bvn,
        bank_name: form.bank_name,
        account_name: form.account_name,
        account_number: form.account_number,
        corporate_banking_information: {
            bank_name: form.bank_name,
            account_name: form.account_name,
            account_number: form.account_number,
        },
    }
}

function buildIndividualProfilePayload(form: IndividualForm, savedProfile: Record<string, any> = {}) {
    const savedKyc = savedProfile.kyc && typeof savedProfile.kyc === 'object' ? savedProfile.kyc : {}
    const savedResidentialInformation = savedProfile.residential_information && typeof savedProfile.residential_information === 'object'
        ? savedProfile.residential_information
        : {}
    const savedBankingInformation = savedProfile.banking_information && typeof savedProfile.banking_information === 'object'
        ? savedProfile.banking_information
        : {}

    return {
        ...savedProfile,
        first_name: form.first_name,
        middle_name: form.middle_name,
        last_name: form.last_name,
        date_of_birth: dateInputValue(form.date_of_birth),
        country_of_birth: form.country_of_birth,
        state_of_birth: form.state_of_birth,
        nationality: form.nationality,
        state_of_origin: form.state_of_origin,
        lga_of_origin: form.lga_of_origin,
        gender: form.gender,
        contact_number: form.contact_number,
        email: form.email,
        nin: form.nin,
        bvn: form.bvn,
        residential_address: form.residential_address,
        bank_name: form.bank_name,
        account_name: form.account_name,
        account_number: form.account_number,
        kyc: {
            ...savedKyc,
            id_type: form.nin ? 'National ID (NIN)' : '',
            id_number: form.nin,
            expiry_date: savedKyc.expiry_date || '',
        },
        residential_information: {
            ...savedResidentialInformation,
            address: form.residential_address,
        },
        banking_information: {
            ...savedBankingInformation,
            bank_name: form.bank_name,
            account_name: form.account_name,
            account_number: form.account_number,
        },
    }
}

function buildInitialIndividualForm(me?: User): IndividualForm {
    const savedProfile = me?.landlord_verification_profile || {}
    const nameParts = (me?.name || '').trim().split(/\s+/).filter(Boolean)

    return {
        ...emptyIndividualForm,
        first_name: String(savedProfile.first_name || nameParts[0] || ''),
        middle_name: String(savedProfile.middle_name || nameParts.slice(1, -1).join(' ') || ''),
        last_name: String(savedProfile.last_name || (nameParts.length > 1 ? nameParts[nameParts.length - 1] : '')),
        date_of_birth: dateInputValue(savedProfile.date_of_birth),
        country_of_birth: String(savedProfile.country_of_birth || ''),
        state_of_birth: String(savedProfile.state_of_birth || ''),
        nationality: String(savedProfile.nationality || ''),
        state_of_origin: String(savedProfile.state_of_origin || me?.state_of_origin || ''),
        lga_of_origin: String(savedProfile.lga_of_origin || ''),
        gender: String(savedProfile.gender || ''),
        contact_number: String(savedProfile.contact_number || me?.mobile || ''),
        email: String(savedProfile.email || me?.email || ''),
        nin: String(savedProfile.nin || me?.nin_number || ''),
        bvn: String(savedProfile.bvn || me?.bvn_number || ''),
        residential_address: String(savedProfile.residential_address || me?.residence?.address || ''),
        bank_name: String(savedProfile.bank_name || ''),
        account_name: String(savedProfile.account_name || ''),
        account_number: String(savedProfile.account_number || ''),
    }
}

function buildInitialCorporateForm(me?: User): CorporateForm {
    const savedProfile = me?.landlord_verification_profile || {}
    const corporateBankingInformation = savedProfile.corporate_banking_information || {}
    const businessState = String(savedProfile.business_state || me?.residence?.state || '')
    const savedBusinessCity = String(savedProfile.business_city || me?.residence?.city || '')
    const knownBusinessCity = isKnownNigerianCity(businessState, savedBusinessCity)

    return {
        ...emptyCorporateForm,
        company_name: String(savedProfile.company_name || ''),
        business_state: businessState,
        business_city: knownBusinessCity ? savedBusinessCity : (savedBusinessCity ? OTHER_CITY_OPTION : ''),
        business_city_other: knownBusinessCity ? '' : savedBusinessCity,
        business_address: String(savedProfile.business_address || me?.residence?.address || ''),
        company_phone_number: String(savedProfile.company_phone_number || me?.mobile || ''),
        company_email: String(savedProfile.company_email || me?.email || ''),
        contact_person_name: String(savedProfile.contact_person_name || me?.name || ''),
        contact_person_position: String(savedProfile.contact_person_position || ''),
        cac_registration_number: String(savedProfile.cac_registration_number || ''),
        cac_registration_date: String(savedProfile.cac_registration_date || ''),
        tax_identification_number: String(savedProfile.tax_identification_number || ''),
        nin: String(savedProfile.nin || me?.nin_number || ''),
        bvn: String(savedProfile.bvn || me?.bvn_number || ''),
        bank_name: String(savedProfile.bank_name || corporateBankingInformation.bank_name || ''),
        account_name: String(savedProfile.account_name || corporateBankingInformation.account_name || ''),
        account_number: String(savedProfile.account_number || corporateBankingInformation.account_number || ''),
    }
}

export default function LandlordIdentityVerificationPage() {
    const navigate = useNavigate()
    const queryClient = useQueryClient()
    const [searchParams] = useSearchParams()
    const { user } = useAuth()
    const { confirm } = useAppPopup()
    const [individualForm, setIndividualForm] = useState<IndividualForm>(emptyIndividualForm)
    const [corporateForm, setCorporateForm] = useState<CorporateForm>(emptyCorporateForm)
    const [identificationFiles, setIdentificationFiles] = useState<File[]>([])
    const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

    const { data: me, isLoading } = useQuery({
        queryKey: ['users', 'me'],
        queryFn: async () => (await api.get<User>('/users/me')).data,
    })

    const { data: documentResponse } = useQuery({
        queryKey: ['documents', 'me'],
        queryFn: async () => (await api.get<UploadedDocument[] | PaginatedResponse<UploadedDocument>>('/documents')).data,
    })

    const { data: verificationStatus } = useQuery({
        queryKey: ['verification', 'status'],
        queryFn: async () => (await api.get<VerificationStatusResponse>('/landlord-verification-requests/status')).data,
    })

    const documents = normalizeResults(documentResponse)
    const existingIdentificationDocuments = useMemo(
        () => documents.filter((document) => document.title.startsWith('Landlord Identification:')),
        [documents],
    )

    const routeType = normalizeVerificationType(searchParams.get('type'))
    const savedType = normalizeVerificationType(me?.landlord_verification_type)
    const verificationType = routeType || savedType
    const isVerificationLocked = Boolean(
        me?.is_verified
        || verificationStatus?.identification?.status === 'verified'
        || verificationStatus?.status === 'approved',
    )
    const countryOfBirthIsNigeria = isNigeriaSelection(individualForm.country_of_birth)
    const nationalityIsNigeria = isNigeriaSelection(individualForm.nationality)
    const lgaOfOriginOptions = nationalityIsNigeria && individualForm.state_of_origin
        ? nigeriaStateLgaMap[individualForm.state_of_origin] || []
        : []
    const corporateBusinessCityOptions = useMemo(
        () => (corporateForm.business_state ? nigeriaStateLgaMap[corporateForm.business_state] || [] : []),
        [corporateForm.business_state],
    )

    useEffect(() => {
        if (!me) {
            return
        }
        setIndividualForm(buildInitialIndividualForm(me))
        setCorporateForm(buildInitialCorporateForm(me))
    }, [me])

    useEffect(() => {
        if (isLoading) {
            return
        }
        if (!verificationType) {
            navigate('/landlord/verification', { replace: true })
            return
        }
        if (!routeType) {
            navigate(`/landlord/verification/identity?type=${verificationType}`, { replace: true })
        }
    }, [isLoading, navigate, routeType, verificationType])

    useEffect(() => {
        if (!countryOfBirthIsNigeria) {
            return
        }
        if (individualForm.state_of_birth && !nigerianStates.includes(individualForm.state_of_birth)) {
            setIndividualForm((current) => ({ ...current, state_of_birth: '' }))
        }
    }, [countryOfBirthIsNigeria, individualForm.state_of_birth])

    useEffect(() => {
        if (!nationalityIsNigeria) {
            return
        }
        if (individualForm.state_of_origin && !nigerianStates.includes(individualForm.state_of_origin)) {
            setIndividualForm((current) => ({ ...current, state_of_origin: '', lga_of_origin: '' }))
            return
        }
        if (individualForm.lga_of_origin && !lgaOfOriginOptions.includes(individualForm.lga_of_origin)) {
            setIndividualForm((current) => ({ ...current, lga_of_origin: '' }))
        }
    }, [individualForm.lga_of_origin, individualForm.state_of_origin, lgaOfOriginOptions, nationalityIsNigeria])

    useEffect(() => {
        if (!corporateForm.business_state) {
            if (corporateForm.business_city || corporateForm.business_city_other) {
                setCorporateForm((current) => ({ ...current, business_city: '', business_city_other: '' }))
            }
            return
        }
        if (!nigerianStates.includes(corporateForm.business_state)) {
            setCorporateForm((current) => ({ ...current, business_state: '', business_city: '', business_city_other: '' }))
            return
        }
        if (
            corporateForm.business_city
            && corporateForm.business_city !== OTHER_CITY_OPTION
            && !corporateBusinessCityOptions.includes(corporateForm.business_city)
        ) {
            setCorporateForm((current) => ({ ...current, business_city: '', business_city_other: '' }))
        }
    }, [
        corporateBusinessCityOptions,
        corporateForm.business_city,
        corporateForm.business_city_other,
        corporateForm.business_state,
    ])

    const handleIndividualChange = (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
        const { name, value } = event.target
        setIndividualForm((current) => {
            const nextForm = { ...current, [name]: value }

            if (name === 'country_of_birth') {
                if (!isNigeriaSelection(value) || !nigerianStates.includes(nextForm.state_of_birth)) {
                    nextForm.state_of_birth = ''
                }
            }

            if (name === 'nationality') {
                if (!isNigeriaSelection(value)) {
                    nextForm.state_of_origin = ''
                    nextForm.lga_of_origin = ''
                } else if (!nigerianStates.includes(nextForm.state_of_origin)) {
                    nextForm.state_of_origin = ''
                    nextForm.lga_of_origin = ''
                }
            }

            if (name === 'state_of_origin') {
                nextForm.lga_of_origin = ''
            }

            return nextForm
        })
        setFieldErrors((current) => ({ ...current, [name]: '' }))
    }

    const handleCorporateChange = (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
        const { name, value } = event.target
        setCorporateForm((current) => {
            if (name === 'business_state') {
                return {
                    ...current,
                    business_state: value,
                    business_city: '',
                    business_city_other: '',
                }
            }

            if (name === 'business_city') {
                return {
                    ...current,
                    business_city: value,
                    business_city_other: value === OTHER_CITY_OPTION ? current.business_city_other : '',
                }
            }

            return { ...current, [name]: value }
        })
        setFieldErrors((current) => ({
            ...current,
            [name]: '',
            ...(name === 'business_city_other' ? { business_city: '' } : {}),
            ...(name === 'business_state' ? { business_city: '' } : {}),
        }))
    }

    const validateForm = (): boolean => {
        const nextErrors: Record<string, string> = {}

        if (verificationType === 'individual') {
            const requiredFields: Array<keyof IndividualForm> = [
                'first_name',
                'last_name',
                'date_of_birth',
                'country_of_birth',
                'state_of_birth',
                'nationality',
                'state_of_origin',
                'lga_of_origin',
                'gender',
                'contact_number',
                'email',
                'residential_address',
                'nin',
                'bvn',
            ]

            requiredFields.forEach((field) => {
                if (!individualForm[field].trim()) {
                    nextErrors[field] = 'This field is required.'
                }
            })

            if (individualForm.nin.trim() && !/^\d{11}$/.test(individualForm.nin.trim())) {
                nextErrors.nin = 'NIN must be exactly 11 digits.'
            }
            if (individualForm.bvn.trim() && !/^\d{11}$/.test(individualForm.bvn.trim())) {
                nextErrors.bvn = 'BVN must be exactly 11 digits.'
            }
        }

        if (verificationType === 'corporate') {
            const requiredFields: Array<keyof CorporateForm> = [
                'company_name',
                'business_state',
                'business_address',
                'company_phone_number',
                'company_email',
                'contact_person_name',
                'contact_person_position',
                'cac_registration_number',
                'cac_registration_date',
                'tax_identification_number',
                'nin',
                'bvn',
                'bank_name',
                'account_name',
                'account_number',
            ]

            requiredFields.forEach((field) => {
                if (!corporateForm[field].trim()) {
                    nextErrors[field] = 'This field is required.'
                }
            })

            if (!buildCorporateProfilePayload(corporateForm).business_city.trim()) {
                nextErrors.business_city = 'This field is required.'
            }
            if (corporateForm.nin.trim() && !/^\d{11}$/.test(corporateForm.nin.trim())) {
                nextErrors.nin = 'NIN must be exactly 11 digits.'
            }
            if (corporateForm.bvn.trim() && !/^\d{11}$/.test(corporateForm.bvn.trim())) {
                nextErrors.bvn = 'BVN must be exactly 11 digits.'
            }
        }

        if (identificationFiles.length === 0 && existingIdentificationDocuments.length === 0) {
            nextErrors.identification_files = 'Upload at least one identification document.'
        }

        setFieldErrors(nextErrors)
        return Object.keys(nextErrors).length === 0
    }

    const submitIdentity = useMutation({
        mutationFn: async () => {
            if (!verificationType) {
                throw new Error('Choose an identification type first.')
            }
            if (!validateForm()) {
                throw new Error('Please complete the required identity verification fields.')
            }

            const profilePayload = verificationType === 'individual'
                ? buildIndividualProfilePayload(individualForm, me?.landlord_verification_profile || {})
                : buildCorporateProfilePayload(corporateForm)

            const payload: Record<string, any> = {
                landlord_verification_type: verificationType,
                landlord_verification_profile: profilePayload,
            }
            if (verificationType === 'individual') {
                payload.name = [individualForm.first_name, individualForm.middle_name, individualForm.last_name]
                    .map((part) => part.trim())
                    .filter(Boolean)
                    .join(' ')
                payload.email = individualForm.email.trim()
                payload.mobile = individualForm.contact_number.trim()
                payload.nin_number = individualForm.nin.trim()
                payload.bvn_number = individualForm.bvn.trim()
                payload.state_of_origin = individualForm.state_of_origin.trim()
            }
            if (verificationType === 'corporate') {
                payload.nin_number = corporateForm.nin.trim()
                payload.bvn_number = corporateForm.bvn.trim()
            }

            await api.patch('/users/me', payload)

            const documentIds = existingIdentificationDocuments.map((document) => document.id)

            for (const file of identificationFiles) {
                const formData = new FormData()
                formData.append('title', `Landlord Identification: ${file.name}`)
                formData.append('file', file)

                const response = await api.post<UploadedDocument>('/documents', formData, {
                    headers: {
                        'Content-Type': 'multipart/form-data',
                    },
                })

                documentIds.push(response.data.id)
            }

            await api.post('/landlord-verification-requests/submit', {
                document_ids: [...new Set(documentIds)],
                request_type: 'identification',
            })
        },
        onSuccess: async () => {
            await Promise.all([
                queryClient.invalidateQueries({ queryKey: ['users', 'me'] }),
                queryClient.invalidateQueries({ queryKey: ['verification', 'status'] }),
                queryClient.invalidateQueries({ queryKey: ['documents', 'me'] }),
            ])
            localStorage.removeItem(LANDLORD_IDENTITY_ONBOARDING_KEY)

            const profileUserId = me?.id || user?.id
            const profilePath = profileUserId ? `/profile/${profileUserId}?onboarding=landlord` : '/dashboard/settings'
            const shouldGoToProfile = await confirm(
                'Landlord verification submitted successfully.',
                {
                    title: 'Verification Successful',
                    variant: 'success',
                    confirmLabel: 'Go to Profile',
                    cancelLabel: 'Cancel and Stay',
                    autoConfirmSeconds: 10,
                },
            )

            if (shouldGoToProfile) {
                navigate(profilePath)
            }
        },
        onError: (error: any) => {
            alert(parseErrorMessage(error, 'Unable to submit identification details.'))
        },
    })

    const formLabelDefault = 'form-label text-[13px] text-gray-400'
    const lockedFormClassName = isVerificationLocked
        ? 'text-gray-500 [&_h2]:text-gray-600 [&_input]:cursor-not-allowed [&_input]:border-gray-200 [&_input]:bg-gray-100 [&_input]:text-gray-500 [&_select]:cursor-not-allowed [&_select]:border-gray-200 [&_select]:bg-gray-100 [&_select]:text-gray-500 [&_textarea]:cursor-not-allowed [&_textarea]:border-gray-200 [&_textarea]:bg-gray-100 [&_textarea]:text-gray-500'
        : ''

    if (isLoading) {
        return (
            <div className="container-modern py-8">
                <div className="rounded-xl border bg-white p-6 text-gray-600">Loading identity verification...</div>
            </div>
        )
    }

    return (
        <div className="container-modern py-8">
            <div className="mx-auto max-w-5xl">
                <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
                    <div>
                        <p className="text-sm font-medium uppercase tracking-[0.2em] text-blue-600">Landlord onboarding</p>
                        <h1 className="mt-2 text-3xl font-bold text-gray-900">Identity Verification</h1>
                        <p className="mt-2 text-gray-600">
                            Complete your identity verification now, then proceed to your profile page.
                        </p>
                    </div>
                    <Link to="/landlord/verification" className="btn btn-outline">
                        Back to Verification
                    </Link>
                </div>

                <div className="mb-8 rounded-2xl border bg-blue-50 p-5">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                        <div>
                            <p className="text-sm font-medium text-blue-900">Verification track</p>
                            <p className="text-[24px] font-semibold text-blue-950">
                                {verificationType === 'corporate' ? 'Corporate Landlord' : 'Individual Landlord'}
                            </p>
                            <p className="text-sm text-blue-800">
                                Note: Property and the documents must be verified before listing.
                            </p>
                        </div>

                    </div>
                </div>

                <div className="rounded-2xl border bg-white p-6 shadow-sm">
                    <fieldset disabled={isVerificationLocked} className={lockedFormClassName}>
                        {verificationType === 'individual' ? (
                            <div className="space-y-8">
                            <section className="space-y-6">
                                <label className="form-label text-xl font-semibold">Personal Information</label>
                                <div className="grid gap-4 md:grid-cols-3">
                                    <div>
                                        <label className={formLabelDefault}>Firstname</label>
                                        <input className="form-input" name="first_name" value={individualForm.first_name} onChange={handleIndividualChange} />
                                        {fieldErrors.first_name && <p className="form-error">{fieldErrors.first_name}</p>}
                                    </div>
                                    <div>
                                        <label className={formLabelDefault}>Middlename</label>
                                        <input className="form-input" name="middle_name" value={individualForm.middle_name} onChange={handleIndividualChange} />
                                    </div>
                                    <div>
                                        <label className={formLabelDefault}>Lastname</label>
                                        <input className="form-input" name="last_name" value={individualForm.last_name} onChange={handleIndividualChange} />
                                        {fieldErrors.last_name && <p className="form-error">{fieldErrors.last_name}</p>}
                                    </div>
                                </div>

                                <div className="grid gap-4 md:grid-cols-3">
                                    <div>
                                        <label className={formLabelDefault}>Date of Birth</label>
                                        <input className="form-input" type="date" name="date_of_birth" value={individualForm.date_of_birth} onChange={handleIndividualChange} />
                                        {fieldErrors.date_of_birth && <p className="form-error">{fieldErrors.date_of_birth}</p>}
                                    </div>
                                    <div>
                                        <label className={formLabelDefault}>Country of Birth</label>
                                        <select className="form-input" name="country_of_birth" value={individualForm.country_of_birth} onChange={handleIndividualChange}>
                                            <option value="">Select country of birth</option>
                                            {worldCountryOptions.map((country) => (
                                                <option key={country} value={country}>{country}</option>
                                            ))}
                                        </select>
                                        {fieldErrors.country_of_birth && <p className="form-error">{fieldErrors.country_of_birth}</p>}
                                    </div>
                                    <div>
                                        <label className={formLabelDefault}>State of Birth</label>
                                        {countryOfBirthIsNigeria ? (
                                            <select className="form-input" name="state_of_birth" value={individualForm.state_of_birth} onChange={handleIndividualChange}>
                                                <option value="">Select state of birth</option>
                                                {nigerianStates.map((state) => (
                                                    <option key={state} value={state}>{state}</option>
                                                ))}
                                            </select>
                                        ) : (
                                            <input className="form-input" name="state_of_birth" value={individualForm.state_of_birth} onChange={handleIndividualChange} />
                                        )}
                                        {fieldErrors.state_of_birth && <p className="form-error">{fieldErrors.state_of_birth}</p>}
                                    </div>
                                </div>

                                <div className="grid gap-4 md:grid-cols-3">
                                    <div>
                                        <label className={formLabelDefault}>Nationality</label>
                                        <select className="form-input" name="nationality" value={individualForm.nationality} onChange={handleIndividualChange}>
                                            <option value="">Select nationality</option>
                                            {worldCountryOptions.map((country) => (
                                                <option key={country} value={country}>{country}</option>
                                            ))}
                                        </select>
                                        {fieldErrors.nationality && <p className="form-error">{fieldErrors.nationality}</p>}
                                    </div>
                                    <div>
                                        <label className={formLabelDefault}>State of Origin</label>
                                        {nationalityIsNigeria ? (
                                            <select className="form-input" name="state_of_origin" value={individualForm.state_of_origin} onChange={handleIndividualChange}>
                                                <option value="">Select state of origin</option>
                                                {nigerianStates.map((state) => (
                                                    <option key={state} value={state}>{state}</option>
                                                ))}
                                            </select>
                                        ) : (
                                            <input className="form-input" name="state_of_origin" value={individualForm.state_of_origin} onChange={handleIndividualChange} />
                                        )}
                                        {fieldErrors.state_of_origin && <p className="form-error">{fieldErrors.state_of_origin}</p>}
                                    </div>
                                    <div>
                                        <label className={formLabelDefault}>LGA of Origin</label>
                                        {nationalityIsNigeria ? (
                                            <select
                                                className="form-input"
                                                name="lga_of_origin"
                                                value={individualForm.lga_of_origin}
                                                onChange={handleIndividualChange}
                                                disabled={!individualForm.state_of_origin}
                                            >
                                                <option value="">{individualForm.state_of_origin ? 'Select LGA of origin' : 'Select state first'}</option>
                                                {lgaOfOriginOptions.map((lga) => (
                                                    <option key={lga} value={lga}>{lga}</option>
                                                ))}
                                            </select>
                                        ) : (
                                            <input className="form-input" name="lga_of_origin" value={individualForm.lga_of_origin} onChange={handleIndividualChange} />
                                        )}
                                        {fieldErrors.lga_of_origin && <p className="form-error">{fieldErrors.lga_of_origin}</p>}
                                    </div>
                                </div>

                                <div className="grid gap-4 md:grid-cols-3">
                                    <div>
                                        <label className={formLabelDefault}>Gender</label>
                                        <select className="form-input" name="gender" value={individualForm.gender} onChange={handleIndividualChange}>
                                            <option value="">Select gender</option>
                                            <option value="Male">Male</option>
                                            <option value="Female">Female</option>
                                        </select>
                                        {fieldErrors.gender && <p className="form-error">{fieldErrors.gender}</p>}
                                    </div>
                                    <div>
                                        <label className={formLabelDefault}>Contact Number (linked to NIN)</label>
                                        <input className="form-input" name="contact_number" value={individualForm.contact_number} onChange={handleIndividualChange} />
                                        {fieldErrors.contact_number && <p className="form-error">{fieldErrors.contact_number}</p>}
                                    </div>
                                    <div>
                                        <label className={formLabelDefault}>Email</label>
                                        <input className="form-input" type="email" name="email" value={individualForm.email} onChange={handleIndividualChange} />
                                        {fieldErrors.email && <p className="form-error">{fieldErrors.email}</p>}
                                    </div>
                                </div>

                                <div className="grid gap-4 md:grid-cols-2">
                                    <div>
                                        <label className={formLabelDefault}>National Identification Number (NIN)</label>
                                        <input className="form-input" name="nin" value={individualForm.nin} onChange={handleIndividualChange} />
                                        {fieldErrors.nin && <p className="form-error">{fieldErrors.nin}</p>}
                                    </div>
                                    <div>
                                        <label className={formLabelDefault}>Bank Verification Number (BVN)</label>
                                        <input className="form-input" name="bvn" value={individualForm.bvn} onChange={handleIndividualChange} />
                                        {fieldErrors.bvn && <p className="form-error">{fieldErrors.bvn}</p>}
                                    </div>
                                </div>

                                <div className="grid gap-4 md:grid-cols-3">
                                    <div>
                                        <label className={formLabelDefault}>Bank Name</label>
                                        <select className="form-input" name="bank_name" value={individualForm.bank_name} onChange={handleIndividualChange}>
                                            <option value="">Select bank</option>
                                            {nigerianBanks.map((bank) => (
                                                <option key={bank} value={bank}>{bank}</option>
                                            ))}
                                        </select>
                                        {fieldErrors.bank_name && <p className="form-error">{fieldErrors.bank_name}</p>}
                                    </div>
                                    <div>
                                        <label className={formLabelDefault}>Account Name</label>
                                        <input className="form-input" name="account_name" value={individualForm.account_name} onChange={handleIndividualChange} />
                                        {fieldErrors.account_name && <p className="form-error">{fieldErrors.account_name}</p>}
                                    </div>
                                    <div>
                                        <label className={formLabelDefault}>Account Number</label>
                                        <input className="form-input" name="account_number" value={individualForm.account_number} onChange={handleIndividualChange} />
                                        {fieldErrors.account_number && <p className="form-error">{fieldErrors.account_number}</p>}
                                    </div>
                                </div>

                                <div>
                                    <label className={formLabelDefault}>Residential Address</label>
                                    <textarea
                                        className="form-input min-h-28"
                                        name="residential_address"
                                        value={individualForm.residential_address}
                                        onChange={handleIndividualChange}
                                    />
                                    {fieldErrors.residential_address && <p className="form-error">{fieldErrors.residential_address}</p>}
                                </div>
                            </section>
                            </div>
                        ) : (
                            <div className="space-y-6">
                            <div>
                                <label className={formLabelDefault}>Company Name</label>
                                <input className="form-input" name="company_name" value={corporateForm.company_name} onChange={handleCorporateChange} />
                                {fieldErrors.company_name && <p className="form-error">{fieldErrors.company_name}</p>}
                            </div>

                            <div className="grid gap-4 md:grid-cols-2">
                                <div>
                                    <label className={formLabelDefault}>State</label>
                                    <select className="form-input" name="business_state" value={corporateForm.business_state} onChange={handleCorporateChange}>
                                        <option value="">Select state</option>
                                        {nigerianStates.map((state) => (
                                            <option key={state} value={state}>{state}</option>
                                        ))}
                                    </select>
                                    {fieldErrors.business_state && <p className="form-error">{fieldErrors.business_state}</p>}
                                </div>
                                <div>
                                    <label className={formLabelDefault}>City</label>
                                    <select
                                        className="form-input"
                                        name="business_city"
                                        value={corporateForm.business_city}
                                        onChange={handleCorporateChange}
                                        disabled={!corporateForm.business_state}
                                    >
                                        <option value="">
                                            {corporateForm.business_state ? 'Select city' : 'Select state first'}
                                        </option>
                                        {corporateBusinessCityOptions.map((city) => (
                                            <option key={city} value={city}>{city}</option>
                                        ))}
                                        <option value={OTHER_CITY_OPTION}>Other</option>
                                    </select>
                                    {corporateForm.business_city === OTHER_CITY_OPTION && (
                                        <input
                                            className="form-input mt-3"
                                            name="business_city_other"
                                            placeholder="Enter city"
                                            value={corporateForm.business_city_other}
                                            onChange={handleCorporateChange}
                                        />
                                    )}
                                    {fieldErrors.business_city && <p className="form-error">{fieldErrors.business_city}</p>}
                                </div>
                            </div>

                            <div>
                                <label className={formLabelDefault}>Business Address</label>
                                <textarea
                                    className="form-input min-h-20"
                                    name="business_address"
                                    value={corporateForm.business_address}
                                    onChange={handleCorporateChange}
                                />
                                {fieldErrors.business_address && <p className="form-error">{fieldErrors.business_address}</p>}
                            </div>

                            <div className="grid gap-4 md:grid-cols-2">
                                <div>
                                    <label className={formLabelDefault}>Company Phone Number</label>
                                    <input className="form-input" name="company_phone_number" value={corporateForm.company_phone_number} onChange={handleCorporateChange} />
                                    {fieldErrors.company_phone_number && <p className="form-error">{fieldErrors.company_phone_number}</p>}
                                </div>
                                <div>
                                    <label className={formLabelDefault}>Company Email</label>
                                    <input className="form-input" type="email" name="company_email" value={corporateForm.company_email} onChange={handleCorporateChange} />
                                    {fieldErrors.company_email && <p className="form-error">{fieldErrors.company_email}</p>}
                                </div>
                            </div>

                            <div className="grid gap-4 md:grid-cols-2">
                                <div>
                                    <label className={formLabelDefault}>Contact Person Name</label>
                                    <input className="form-input" name="contact_person_name" value={corporateForm.contact_person_name} onChange={handleCorporateChange} />
                                    {fieldErrors.contact_person_name && <p className="form-error">{fieldErrors.contact_person_name}</p>}
                                </div>
                                <div>
                                    <label className={formLabelDefault}>Contact Person Position</label>
                                    <input className="form-input" name="contact_person_position" value={corporateForm.contact_person_position} onChange={handleCorporateChange} />
                                    {fieldErrors.contact_person_position && <p className="form-error">{fieldErrors.contact_person_position}</p>}
                                </div>
                            </div>

                            <div className="grid gap-4 md:grid-cols-3">
                                <div>
                                    <label className={formLabelDefault}>CAC Registration Number</label>
                                    <input className="form-input" name="cac_registration_number" value={corporateForm.cac_registration_number} onChange={handleCorporateChange} />
                                    {fieldErrors.cac_registration_number && <p className="form-error">{fieldErrors.cac_registration_number}</p>}
                                </div>
                                <div>
                                    <label className={formLabelDefault}>CAC Registration Date</label>
                                    <input className="form-input" type="date" name="cac_registration_date" value={corporateForm.cac_registration_date} onChange={handleCorporateChange} />
                                    {fieldErrors.cac_registration_date && <p className="form-error">{fieldErrors.cac_registration_date}</p>}
                                </div>
                                <div>
                                    <label className={formLabelDefault}>Tax Identification Number (TIN)</label>
                                    <input className="form-input" name="tax_identification_number" value={corporateForm.tax_identification_number} onChange={handleCorporateChange} />
                                    {fieldErrors.tax_identification_number && <p className="form-error">{fieldErrors.tax_identification_number}</p>}
                                </div>
                            </div>

                            <div className="grid gap-4 md:grid-cols-2">
                                <div>
                                    <label className={formLabelDefault}>Director's NIN</label>
                                    <input className="form-input" name="nin" value={corporateForm.nin} onChange={handleCorporateChange} />
                                    {fieldErrors.nin && <p className="form-error">{fieldErrors.nin}</p>}
                                </div>
                                <div>
                                    <label className={formLabelDefault}>Director's BVN</label>
                                    <input className="form-input" name="bvn" value={corporateForm.bvn} onChange={handleCorporateChange} />
                                    {fieldErrors.bvn && <p className="form-error">{fieldErrors.bvn}</p>}
                                </div>
                            </div>

                            <div className="grid gap-4 md:grid-cols-3">
                                <div>
                                    <label className={formLabelDefault}>Bank Name</label>
                                    <select className="form-input" name="bank_name" value={corporateForm.bank_name} onChange={handleCorporateChange}>
                                        <option value="">Select bank</option>
                                        {nigerianBanks.map((bank) => (
                                            <option key={bank} value={bank}>{bank}</option>
                                        ))}
                                    </select>
                                    {fieldErrors.bank_name && <p className="form-error">{fieldErrors.bank_name}</p>}
                                </div>
                                <div>
                                    <label className={formLabelDefault}>Corporate Account Name</label>
                                    <input className="form-input" name="account_name" value={corporateForm.account_name} onChange={handleCorporateChange} />
                                    {fieldErrors.account_name && <p className="form-error">{fieldErrors.account_name}</p>}
                                </div>
                                <div>
                                    <label className={formLabelDefault}>Corporate Account Number</label>
                                    <input className="form-input" name="account_number" value={corporateForm.account_number} onChange={handleCorporateChange} />
                                    {fieldErrors.account_number && <p className="form-error">{fieldErrors.account_number}</p>}
                                </div>
                            </div>
                            </div>
                        )}

                        <div className="mt-8 rounded-2xl border border-dashed border-gray-300 bg-gray-50 p-5">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                            <div>
                                <h2 className="text-lg font-semibold text-gray-900">Upload Identification Documents</h2>
                                <p className="mt-1 text-sm text-gray-600">
                                    Upload government-issued ID<br />
                                    (e.g. NIN Card or Int'l passport for individual Landlords or CAC documents for Corporate Landlords)
                                </p>
                            </div>
                            {existingIdentificationDocuments.length > 0 && (
                                <span className="rounded-full bg-green-100 px-3 py-1 text-sm font-medium text-green-700">
                                    {existingIdentificationDocuments.length} document{existingIdentificationDocuments.length === 1 ? '' : 's'} already on file
                                </span>
                            )}
                        </div>

                        <div className="mt-4">
                            <input
                                type="file"
                                multiple
                                accept=".pdf,.jpg,.jpeg,.png"
                                onChange={(event) => setIdentificationFiles(Array.from(event.target.files || []))}
                                className="block w-full text-sm text-gray-500 file:mr-4 file:rounded-full file:border-0 file:bg-blue-50 file:px-4 file:py-2 file:font-semibold file:text-blue-700 hover:file:bg-blue-100"
                            />
                            {fieldErrors.identification_files && <p className="form-error mt-2">{fieldErrors.identification_files}</p>}
                        </div>

                        {identificationFiles.length > 0 && (
                            <ul className="mt-4 space-y-2 text-sm text-gray-600">
                                {identificationFiles.map((file) => (
                                    <li key={`${file.name}-${file.size}`} className="flex items-center justify-between rounded-lg bg-white px-3 py-2">
                                        <span>{file.name}</span>
                                        <span>{(file.size / 1024 / 1024).toFixed(2)} MB</span>
                                    </li>
                                ))}
                            </ul>
                        )}
                        </div>

                        <div className="mt-8 flex flex-wrap items-center justify-between gap-3">
                        <p className="text-sm text-gray-500">
                            Identification submission is saved for review. Next step is completing your profile page.
                        </p>
                        <button
                            type="button"
                            onClick={() => submitIdentity.mutate()}
                            disabled={isVerificationLocked || submitIdentity.isPending}
                            className="btn btn-primary px-6 py-3 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                            {isVerificationLocked ? 'Identification Verified' : submitIdentity.isPending ? 'Submitting...' : 'Submit Identification and Continue'}
                        </button>
                        </div>
                    </fieldset>
                </div>
            </div>
        </div>
    )
}
