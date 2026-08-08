import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'

import { useAuth } from '@/hooks/useAuth'
import { useAppPopup } from '@/contexts/AppPopupContext'
import LegalDocumentsConsent from '@/components/LegalDocumentsConsent'
import { api } from '@/lib/api'
import { isNigeriaSelection, nigeriaStateLgaMap, nigerianStates, worldCountryOptions } from '@/lib/locations'
import {
    BVN_ERROR_MESSAGE,
    BVN_INPUT_PATTERN,
    BVN_INPUT_PLACEHOLDER,
    MOBILE_ERROR_MESSAGE,
    MOBILE_INPUT_PATTERN,
    MOBILE_INPUT_PLACEHOLDER,
    NIN_ERROR_MESSAGE,
    NIN_INPUT_PATTERN,
    NIN_INPUT_PLACEHOLDER,
    formatIdentityNumberInput,
    validateBvn,
    validateMobile,
    validateNin,
} from '@/lib/profile'
import { User } from '@/types'

const schema = z.object({
    first_name: z.string().min(1, 'First name is required'),
    middle_name: z.string().optional(),
    last_name: z.string().min(1, 'Last name is required'),
    country_of_birth: z.string().min(1, 'Country of birth is required'),
    date_of_birth: z.string().min(1, 'Date of birth is required'),
    gender: z.string().min(1, 'Gender is required'),
    nationality: z.string().min(1, 'Nationality is required'),
    state_of_origin: z.string().min(1, 'State of origin is required'),
    lga: z.string().min(1, 'LGA is required'),
    email: z.string().min(1, 'Email is required').email('Enter a valid email address.'),
    mobile: z.string().min(1, 'Mobile number is required').refine((value) => !validateMobile(value), MOBILE_ERROR_MESSAGE),
    employment_status: z.string().min(1, 'Employment status is required'),
    nin_number: z.string().min(1, 'NIN is required').refine((value) => !validateNin(value), NIN_ERROR_MESSAGE),
    bvn_number: z.string().min(1, 'BVN is required').refine((value) => !validateBvn(value), BVN_ERROR_MESSAGE),
})

type VerificationFormValues = z.infer<typeof schema>
type ExistingTenantProfile = Partial<VerificationFormValues> & Record<string, any>

type VerificationProgress = {
    status?: string
    submitted_at?: string | null
}

type VerificationStatusResponse = {
    status?: string
    identification?: VerificationProgress
}

const genderOptions = ['Male', 'Female']
const employmentOptions = ['Employed', 'Self Employed', 'Business Owner', 'Freelancer', 'Retired', 'Unemployed', 'Student']

const emptyProfileDetails = {
    residence_country: '',
    residence_state: '',
    residence_city: '',
    residence_lga: '',
    residence_address: '',
    length_of_stay: '',
    housing_status: '',
    employment_info: {},
    financial_info: {
        current_annual_rent: '',
        current_service_charge: '',
        current_move_in_date: '',
        expected_move_out_date: '',
        reason_for_wanting_to_leave: '',
    },
    guarantor_details: {},
    landlord_info: {},
    rental_history: [],
    household_info: {},
    social_presence: {},
    criminal_declaration: {},
}

function splitName(name?: string) {
    const parts = String(name || '').trim().split(/\s+/).filter(Boolean)
    return {
        first_name: parts[0] || '',
        middle_name: parts.length > 2 ? parts.slice(1, -1).join(' ') : '',
        last_name: parts.length > 1 ? parts[parts.length - 1] : '',
    }
}

function asRecord(value: unknown): Record<string, any> {
    return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, any> : {}
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
    return rawValue
}

function optionValue(value: unknown, options: readonly string[]): string {
    const rawValue = stringValue(value)
    if (!rawValue) return ''
    const match = options.find((option) => option.toLowerCase() === rawValue.toLowerCase())
    return match || rawValue
}

function InputRow({ label, children, error }: { label: string; children: React.ReactNode; error?: string }) {
    return (
        <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">{label}</label>
            {children}
            {error && <p className="mt-1 text-sm text-red-600">{error}</p>}
        </div>
    )
}

function TextInput({
    register,
    name,
    error,
    placeholder,
    type = 'text',
    inputMode,
    pattern,
    maxLength,
    title,
    formatValue,
}: {
    register: any
    name: keyof VerificationFormValues
    error?: string
    placeholder?: string
    type?: string
    inputMode?: React.HTMLAttributes<HTMLInputElement>['inputMode']
    pattern?: string
    maxLength?: number
    title?: string
    formatValue?: (value: string) => string
}) {
    const registerOptions = formatValue
        ? {
            setValueAs: formatValue,
            onChange: (event: React.ChangeEvent<HTMLInputElement>) => {
                event.target.value = formatValue(event.target.value)
            },
        }
        : undefined

    return (
        <input
            {...register(name, registerOptions)}
            type={type}
            inputMode={inputMode}
            pattern={pattern}
            maxLength={maxLength}
            title={title}
            placeholder={placeholder}
            className={`w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${error ? 'border-red-300' : 'border-gray-300'}`}
        />
    )
}

const mobileInputProps = {
    type: 'tel',
    inputMode: 'tel' as const,
    pattern: MOBILE_INPUT_PATTERN,
    maxLength: 14,
    title: MOBILE_ERROR_MESSAGE,
}

const ninInputProps = {
    inputMode: 'numeric' as const,
    pattern: NIN_INPUT_PATTERN,
    maxLength: 11,
    title: NIN_ERROR_MESSAGE,
    formatValue: formatIdentityNumberInput,
}

const bvnInputProps = {
    inputMode: 'numeric' as const,
    pattern: BVN_INPUT_PATTERN,
    maxLength: 11,
    title: BVN_ERROR_MESSAGE,
    formatValue: formatIdentityNumberInput,
}

function SelectInput({ register, name, options, placeholder, error }: { register: any; name: keyof VerificationFormValues; options: string[]; placeholder: string; error?: string }) {
    return (
        <select
            {...register(name)}
            className={`w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${error ? 'border-red-300' : 'border-gray-300'}`}
        >
            <option value="">{placeholder}</option>
            {options.map((option) => (
                <option key={option} value={option}>{option}</option>
            ))}
        </select>
    )
}

export default function VerifyMePage() {
    const { user } = useAuth()
    const { confirm } = useAppPopup()
    const navigate = useNavigate()
    const queryClient = useQueryClient()
    const [submitError, setSubmitError] = useState('')
    const [hasAcceptedLegalConsent, setHasAcceptedLegalConsent] = useState(false)

    const { data: me } = useQuery({
        queryKey: ['users', 'me'],
        queryFn: async () => (await api.get<User>('/users/me')).data,
    })

    const { data: existingProfile } = useQuery({
        queryKey: ['users', 'me', 'tenant-profile'],
        queryFn: async () => {
            try {
                return (await api.get<ExistingTenantProfile>('/users/me/tenant-profile')).data
            } catch {
                return null
            }
        },
        enabled: Boolean(user),
    })

    const { data: verificationStatus } = useQuery({
        queryKey: ['verification', 'status', 'tenant'],
        queryFn: async () => (await api.get<VerificationStatusResponse>('/tenant-verification-requests/status')).data,
        enabled: Boolean(user?.role === 'tenant'),
    })

    const defaultValues = useMemo<VerificationFormValues>(() => {
        const nameParts = splitName(me?.name || user?.name)
        const verificationProfile = asRecord(me?.tenant_verification_profile)
        return {
            first_name: existingProfile?.first_name || stringValue(verificationProfile.first_name) || nameParts.first_name,
            middle_name: existingProfile?.middle_name || stringValue(verificationProfile.middle_name) || nameParts.middle_name,
            last_name: existingProfile?.last_name || stringValue(verificationProfile.last_name) || nameParts.last_name,
            country_of_birth: stringValue(verificationProfile.country_of_birth) || 'Nigeria',
            date_of_birth: existingProfile?.date_of_birth || dateInputValue(verificationProfile.date_of_birth),
            gender: existingProfile?.gender || optionValue(verificationProfile.gender, genderOptions),
            nationality: existingProfile?.nationality || stringValue(verificationProfile.nationality) || 'Nigeria',
            state_of_origin: existingProfile?.state_of_origin || stringValue(verificationProfile.state_of_origin) || me?.state_of_origin || '',
            lga: existingProfile?.lga || stringValue(verificationProfile.lga),
            email: stringValue(verificationProfile.email) || me?.email || user?.email || '',
            mobile: stringValue(verificationProfile.mobile) || me?.mobile || '',
            employment_status: existingProfile?.employment_status || optionValue(verificationProfile.employment_status, employmentOptions),
            nin_number: me?.nin_number || stringValue(verificationProfile.nin_number || verificationProfile.nin),
            bvn_number: me?.bvn_number || stringValue(verificationProfile.bvn_number || verificationProfile.bvn),
        }
    }, [existingProfile, me, user])

    const { register, handleSubmit, watch, reset, setValue, clearErrors, formState: { errors, isSubmitting } } = useForm<VerificationFormValues>({
        resolver: zodResolver(schema),
        defaultValues,
    })

    useEffect(() => {
        reset(defaultValues)
    }, [defaultValues, reset])

    const nationality = watch('nationality')
    const stateOfOrigin = watch('state_of_origin')
    const lga = watch('lga')
    const nationalityIsNigeria = isNigeriaSelection(nationality)
    const lgaOptions = nationalityIsNigeria && stateOfOrigin ? nigeriaStateLgaMap[stateOfOrigin] || [] : []
    const identityVerificationStatus = verificationStatus?.identification?.status
    const isVerificationLocked = Boolean(
        me?.is_verified
        || identityVerificationStatus === 'verified'
        || verificationStatus?.status === 'approved'
        || existingProfile?.status === 'approved',
    )
    const lockedFormClassName = isVerificationLocked
        ? 'text-gray-500 [&_input]:cursor-not-allowed [&_input]:border-gray-200 [&_input]:bg-gray-100 [&_input]:text-gray-500 [&_select]:cursor-not-allowed [&_select]:border-gray-200 [&_select]:bg-gray-100 [&_select]:text-gray-500 [&_label]:text-gray-400'
        : ''

    useEffect(() => {
        if (!nationalityIsNigeria) {
            clearErrors(['state_of_origin', 'lga'])
            return
        }

        if (stateOfOrigin && !nigerianStates.includes(stateOfOrigin)) {
            setValue('state_of_origin', '')
            setValue('lga', '')
        } else if (lga && !lgaOptions.includes(lga)) {
            setValue('lga', '')
        }
    }, [clearErrors, lga, lgaOptions, nationalityIsNigeria, setValue, stateOfOrigin])

    const saveVerification = useMutation({
        mutationFn: async (data: VerificationFormValues) => {
            await api.patch('/users/me', {
                name: [data.first_name, data.middle_name, data.last_name].filter(Boolean).join(' '),
                email: data.email.trim(),
                mobile: data.mobile.trim(),
                state_of_origin: data.state_of_origin,
            })

            const payload = {
                ...emptyProfileDetails,
                ...(existingProfile || {}),
                nin_number: data.nin_number.trim(),
                bvn_number: data.bvn_number.trim(),
                first_name: data.first_name,
                middle_name: data.middle_name || '',
                last_name: data.last_name,
                country_of_birth: data.country_of_birth,
                date_of_birth: data.date_of_birth,
                gender: data.gender,
                nationality: data.nationality,
                state_of_origin: data.state_of_origin,
                lga: data.lga,
                email: data.email.trim(),
                mobile: data.mobile.trim(),
                employment_status: data.employment_status,
            }

            const method = existingProfile ? 'put' : 'post'
            return (await api[method]('/users/me/tenant-profile', payload)).data
        },
        onSuccess: async (profile) => {
            queryClient.invalidateQueries({ queryKey: ['users', 'me'] })
            queryClient.setQueryData(['users', 'me', 'tenant-profile'], profile)
            queryClient.invalidateQueries({ queryKey: ['tenant-profile'] })
            queryClient.invalidateQueries({ queryKey: ['verification', 'status'] })
            setSubmitError('')

            const profilePath = user?.id ? `/tenants/${user.id}/profile?edit=1` : '/search'
            const shouldGoToProfile = await confirm(
                'Tenant verification completed successfully.',
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
            setSubmitError(error?.response?.data?.detail || error?.message || 'Verification failed. Please try again.')
        },
    })

    return (
        <div className="min-h-screen bg-gray-50 py-10">
            <div className="max-w-6xl mx-auto px-2">
                <div className="mb-8">
                    <h1 className="text-3xl font-bold text-gray-900">Tenant Verification</h1>
                    <p className="text-gray-600 mt-2">Complete your biodata and identity numbers to start tenant verification.</p>
                </div>

                {submitError && (
                    <div className="mb-6 rounded-lg bg-red-50 border border-red-200 p-4 text-sm text-red-800">
                        {submitError}
                    </div>
                )}

                <form
                    onSubmit={handleSubmit((data) => {
                        if (isVerificationLocked) return
                        if (!hasAcceptedLegalConsent) {
                            setSubmitError('Review all legal documents and click “I have read & consent” before submitting your verification.')
                            return
                        }
                        saveVerification.mutate(data)
                    })}
                    className={`rounded-xl border bg-white p-6 shadow-sm ${lockedFormClassName}`}
                >
                    <fieldset disabled={isVerificationLocked}>
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                            <InputRow label="First Name" error={errors.first_name?.message}>
                                <TextInput register={register} name="first_name" placeholder="First name" error={errors.first_name?.message} />
                            </InputRow>
                            <InputRow label="Middle Name">
                                <TextInput register={register} name="middle_name" placeholder="Middle name" />
                            </InputRow>
                            <InputRow label="Last Name" error={errors.last_name?.message}>
                                <TextInput register={register} name="last_name" placeholder="Last name" error={errors.last_name?.message} />
                            </InputRow>
                        </div>

                        <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-4">
                            <InputRow label="Country of Birth" error={errors.country_of_birth?.message}>
                                <SelectInput register={register} name="country_of_birth" options={[...worldCountryOptions]} placeholder="Select country of birth" error={errors.country_of_birth?.message} />
                            </InputRow>
                            <InputRow label="Date of Birth" error={errors.date_of_birth?.message}>
                                <TextInput register={register} name="date_of_birth" type="date" error={errors.date_of_birth?.message} />
                            </InputRow>
                            <InputRow label="Gender" error={errors.gender?.message}>
                                <SelectInput register={register} name="gender" options={genderOptions} placeholder="Select gender" error={errors.gender?.message} />
                            </InputRow>
                        </div>

                        <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-4">
                            <InputRow label="Nationality" error={errors.nationality?.message}>
                                <SelectInput register={register} name="nationality" options={[...worldCountryOptions]} placeholder="Select nationality" error={errors.nationality?.message} />
                            </InputRow>
                            <InputRow label="State of Origin" error={errors.state_of_origin?.message}>
                                {nationalityIsNigeria ? (
                                    <SelectInput register={register} name="state_of_origin" options={nigerianStates} placeholder="Select state" error={errors.state_of_origin?.message} />
                                ) : (
                                    <TextInput register={register} name="state_of_origin" placeholder="State of origin" error={errors.state_of_origin?.message} />
                                )}
                            </InputRow>
                            <InputRow label="LGA of Origin" error={errors.lga?.message}>
                                {nationalityIsNigeria ? (
                                    <SelectInput register={register} name="lga" options={lgaOptions} placeholder={stateOfOrigin ? 'Select LGA' : 'Select state first'} error={errors.lga?.message} />
                                ) : (
                                    <TextInput register={register} name="lga" placeholder="Local Government Area" error={errors.lga?.message} />
                                )}
                            </InputRow>
                        </div>

                        <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
                            <InputRow label="National Identification Number (NIN)" error={errors.nin_number?.message}>
                                <TextInput register={register} name="nin_number" placeholder={NIN_INPUT_PLACEHOLDER} error={errors.nin_number?.message} {...ninInputProps} />
                            </InputRow>
                            <InputRow label="Bank Verification Number (BVN)" error={errors.bvn_number?.message}>
                                <TextInput register={register} name="bvn_number" placeholder={BVN_INPUT_PLACEHOLDER} error={errors.bvn_number?.message} {...bvnInputProps} />
                            </InputRow>
                        </div>

                        <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-4">
                            <InputRow label="Email" error={errors.email?.message}>
                                <TextInput register={register} name="email" type="email" placeholder="Email address" error={errors.email?.message} />
                            </InputRow>
                            <InputRow label="Mobile (linked to NIN or BVN)" error={errors.mobile?.message}>
                                <TextInput register={register} name="mobile" placeholder={MOBILE_INPUT_PLACEHOLDER} error={errors.mobile?.message} {...mobileInputProps} />
                            </InputRow>
                            <InputRow label="Employment Status" error={errors.employment_status?.message}>
                                <SelectInput register={register} name="employment_status" options={employmentOptions} placeholder="Select employment status" error={errors.employment_status?.message} />
                            </InputRow>
                        </div>

                    </fieldset>

                    <div className="mt-8">
                        <LegalDocumentsConsent
                            id="tenant-verification-legal-consent"
                            audience="tenant"
                            consented={hasAcceptedLegalConsent}
                            disabled={isVerificationLocked}
                            onConsentChange={setHasAcceptedLegalConsent}
                        />
                    </div>

                    <div className="mt-8 flex justify-end">
                        <button
                            type="submit"
                            disabled={isVerificationLocked || isSubmitting || saveVerification.isPending || !hasAcceptedLegalConsent}
                            className="rounded-lg bg-blue-600 px-8 py-3 text-sm font-medium text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                            {isVerificationLocked ? 'Verified' : isSubmitting || saveVerification.isPending ? 'Saving...' : 'Submit Verification'}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    )
}
