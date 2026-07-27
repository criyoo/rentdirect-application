import { useState, useCallback, useEffect, useMemo } from 'react'
import { Controller, FieldErrors, useFieldArray, useForm } from 'react-hook-form'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api, resolveMediaUrl } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { isNigeriaSelection, nigeriaStateLgaMap, nigerianStates, worldCountryOptions } from '@/lib/locations'
import { User } from '@/types'

const rentalHistoryItemSchema = z.object({
    property_address: z.string().optional(),
    annual_rent: z.string().optional(),
    service_charge: z.string().optional(),
    move_in_date: z.string().optional(),
    move_out_date: z.string().optional(),
    reason_for_leave: z.string().optional(),
})

const requiredBooleanField = z.boolean({
    required_error: 'Please select Yes or No.',
    invalid_type_error: 'Please select Yes or No.',
})

function parseYearsOfStay(value?: string | null): number {
    const normalizedValue = String(value || '').trim()
    if (!normalizedValue) {
        return 0
    }

    const parsedValue = Number.parseFloat(normalizedValue)
    if (Number.isFinite(parsedValue)) {
        return parsedValue
    }

    const match = normalizedValue.match(/(\d+(?:\.\d+)?)/)
    return match ? Number.parseFloat(match[1]) : 0
}

function rentalHistoryItemHasAnyValue(item?: Record<string, string | undefined>): boolean {
    if (!item) {
        return false
    }

    return Object.values(item).some((value) => String(value || '').trim() !== '')
}

function rentalHistoryItemMissingFields(item?: Record<string, string | undefined>): string[] {
    const requiredKeys = [
        'property_address',
        'annual_rent',
        'service_charge',
        'move_in_date',
        'move_out_date',
        'reason_for_leave',
    ] as const

    return requiredKeys.filter((key) => String(item?.[key] || '').trim() === '')
}

const schema = z.object({
    first_name: z.string().min(1, 'First name is required'),
    middle_name: z.string().optional(),
    last_name: z.string().min(1, 'Last name is required'),
    date_of_birth: z.string().min(1, 'Date of birth is required'),
    gender: z.string().min(1, 'Gender is required'),
    nationality: z.string().min(1, 'Nationality is required'),
    state_of_origin: z.string().min(1, 'State of origin is required'),
    lga: z.string().min(1, 'LGA is required'),
    employment_status: z.string().min(1, 'Employment status is required'),
    residence_country: z.string().min(1, 'Country is required'),
    residence_state: z.string().min(1, 'State is required'),
    residence_city: z.string().min(1, 'City is required'),
    residence_lga: z.string().min(1, 'LGA is required'),
    residence_address: z.string().min(1, 'Address is required'),
    length_of_stay: z.string().min(1, 'Length of stay is required'),
    housing_status: z.string().min(1, 'Housing status is required'),
    employment_info: z.object({
        company_name: z.string().optional(),
        company_contact_number: z.string().optional(),
        industry: z.string().optional(),
        employment_type: z.string().optional(),
        employment_start_date: z.string().optional(),
        position_job_title: z.string().optional(),
        company_address: z.string().optional(),
        company_website: z.string().optional(),
        hr_contact_name: z.string().optional(),
        hr_email: z.string().optional(),
        hr_contact_phone: z.string().optional(),
    }).optional(),
    financial_info: z.object({
        bank_name: z.string().optional(),
        bank_address: z.string().optional(),
        account_name: z.string().optional(),
        account_number: z.string().optional(),
        business_name: z.string().optional(),
        business_address: z.string().optional(),
        business_type: z.string().optional(),
        monthly_income_amount: z.string().optional(),
        monthly_expenses: z.string().optional(),
        current_rent_amount: z.string().min(1, 'Annual rent is required'),
        current_service_charge: z.string().min(1, 'Service charge is required'),
        current_move_in_date: z.string().min(1, 'Move in date is required'),
        expected_move_out_date: z.string().min(1, 'Expected move out date is required'),
        reason_for_wanting_to_leave: z.string().min(1, 'Reason for wanting to leave is required'),
        credit_commitment: z.string().optional(),
        outstanding_loans: z.string().optional(),
    }).optional(),
    guarantor_details: z.object({
        full_name: z.string().optional(),
        relationship: z.string().optional(),
        email: z.string().optional(),
        mobile_number: z.string().optional(),
        occupation: z.string().optional(),
        employer: z.string().optional(),
        residential_address: z.string().optional(),
    }).optional(),
    landlord_info: z.object({
        name: z.string().optional(),
        mobile: z.string().optional(),
        email: z.string().optional(),
        address: z.string().optional(),
        same_as_current_address: z.boolean().optional(),
        property_manager_name: z.string().optional(),
        property_manager_phone: z.string().optional(),
        property_manager_email: z.string().optional(),
        property_manager_address: z.string().optional(),
        property_manager_same_as_landlord_name: z.boolean().optional(),
        property_manager_same_as_landlord_phone: z.boolean().optional(),
        property_manager_same_as_landlord_email: z.boolean().optional(),
        property_manager_same_as_landlord_address: z.boolean().optional(),
    }).optional(),
    rental_history_same_as_current_residence: z.boolean().optional(),
    rental_history: z.array(rentalHistoryItemSchema).optional(),
    household_info: z.object({
        marital_status: z.string().min(1, 'Marital status is required'),
        number_of_adults: z.string().optional(),
        number_of_children: z.string().optional(),
        has_pets: requiredBooleanField,
        number_of_pets: z.string().optional(),
        work_from_home: requiredBooleanField,
        commercial_activities_at_home: requiredBooleanField,
        has_smokers: requiredBooleanField,
    }).optional(),
    social_presence: z.object({
        linkedin_profile: z.string().optional(),
        facebook_profile: z.string().optional(),
        instagram_profile: z.string().optional(),
        x_twitter_profile: z.string().optional(),
        tiktok_profile: z.string().optional(),
        threads_profile: z.string().optional(),
    }).optional(),
    criminal_declaration: z.object({
        convicted_of_crime: requiredBooleanField,
        evicted_from_property: requiredBooleanField,
        ongoing_tenancy_litigation: requiredBooleanField,
        rent_arrears_history: requiredBooleanField,
        legal_dispute_with_landlords: requiredBooleanField,
    }).optional(),
    document_ids: z.array(z.string()).optional(),
}).superRefine((data, ctx) => {
    if (data.household_info?.has_pets && !String(data.household_info.number_of_pets || '').trim()) {
        ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ['household_info', 'number_of_pets'],
            message: 'Number of pets is required when pets are present.',
        })
    }

    const filledRentalHistory = (data.rental_history || []).filter((item) => rentalHistoryItemHasAnyValue(item))

    filledRentalHistory.forEach((item, index) => {
        rentalHistoryItemMissingFields(item).forEach((fieldName) => {
            ctx.addIssue({
                code: z.ZodIssueCode.custom,
                path: ['rental_history', index, fieldName],
                message: 'This field is required.',
            })
        })
    })

    if (data.rental_history_same_as_current_residence) {
        if (parseYearsOfStay(data.length_of_stay) < 5 && filledRentalHistory.length === 0) {
            ctx.addIssue({
                code: z.ZodIssueCode.custom,
                path: ['rental_history', 0, 'property_address'],
                message: 'Add at least one previous rental property because your current residence is less than 5 years.',
            })
        }
        return
    }

    if (filledRentalHistory.length === 0) {
        ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ['rental_history', 0, 'property_address'],
            message: 'Provide at least one rental history address.',
        })
    }
})

type FormValues = z.infer<typeof schema>

const employmentOptions = ['Employed', 'Self Employed', 'Business Owner', 'Freelancer', 'Retired', 'Unemployed', 'Student']
const genderOptions = ['Male', 'Female']
const housingStatusOptions = ['Owned', 'Rented', 'Family Property', 'Employer Provided', 'Other']
const employmentTypeOptions = ['Full-time', 'Part-time', 'Contract', 'Internship']
const maritalStatusOptions = ['Married', 'Single', 'Divorced', 'Separated', 'Widow/Widower']

type FileMap = Record<string, File[]>

type SectionProps = {
    title: string
    children: React.ReactNode
    step: number
    activeStep: number
    setActiveStep: (n: number) => void
}

function SectionCard({ title, children, step, activeStep, setActiveStep }: SectionProps) {
    const isOpen = activeStep === step
    return (
        <div className="bg-white rounded-xl border shadow-sm overflow-hidden">
            <button
                type="button"
                onClick={() => setActiveStep(isOpen ? 0 : step)}
                className="w-full flex items-center justify-between px-6 py-4 bg-gray-50 hover:bg-gray-100 transition-colors text-left"
            >
                <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
                <span className={`text-gray-500 transform transition-transform ${isOpen ? 'rotate-180' : ''}`}>
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                    </svg>
                </span>
            </button>
            {isOpen && <div className="p-6">{children}</div>}
        </div>
    )
}

function InputRow({ label, children, error, action }: { label: string; children: React.ReactNode; error?: string; action?: React.ReactNode }) {
    return (
        <div>
            <div className="mb-1 flex items-center justify-between gap-3">
                <label className="block text-sm font-medium text-gray-700">{label}</label>
                {action}
            </div>
            {children}
            {error && <p className="mt-1 text-sm text-red-600">{error}</p>}
        </div>
    )
}

function TextInput({
    register,
    name,
    placeholder,
    error,
    type = 'text',
    min,
    step,
    disabled = false,
}: {
    register: any
    name: string
    placeholder?: string
    error?: string
    type?: string
    min?: string
    step?: string
    disabled?: boolean
}) {
    return (
        <input
            {...register(name)}
            type={type}
            min={min}
            step={step}
            placeholder={placeholder}
            readOnly={disabled}
            className={`w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${error ? 'border-red-300' : disabled ? 'border-gray-200 bg-gray-100 text-gray-500' : 'border-gray-300'}`}
        />
    )
}

function SameAsLandlordCheckbox({ register, name }: { register: any; name: string }) {
    return (
        <label className="flex items-center gap-2 text-xs text-gray-700">
            <span>Same as landlord&apos;s</span>
            <input
                type="checkbox"
                {...register(name)}
                className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            />
        </label>
    )
}

function SelectInput({ register, name, options, placeholder, error }: { register: any; name: string; options: string[]; placeholder?: string; error?: string }) {
    return (
        <select
            {...register(name)}
            className={`w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${error ? 'border-red-300' : 'border-gray-300'}`}
        >
            {placeholder && <option value="">{placeholder}</option>}
            {options.map(o => <option key={o} value={o}>{o}</option>)}
        </select>
    )
}

function FileUploadBox({ label, files, onChange, accept = '.pdf,.jpg,.jpeg,.png' }: { label: string; files: File[]; onChange: (files: File[]) => void; accept?: string }) {
    const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files) {
            onChange([...files, ...Array.from(e.target.files)])
        }
    }
    const removeFile = (idx: number) => {
        const next = [...files]
        next.splice(idx, 1)
        onChange(next)
    }
    return (
        <div className="border border-dashed border-gray-300 rounded-lg p-4">
            <p className="text-sm font-medium text-gray-700 mb-2">{label}</p>
            <input
                type="file"
                multiple
                accept={accept}
                onChange={handleChange}
                className="block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100"
            />
            {files.length > 0 && (
                <ul className="mt-2 space-y-1">
                    {files.map((f, i) => (
                        <li key={i} className="flex items-center justify-between text-sm text-gray-600 bg-gray-50 rounded px-2 py-1">
                            <span className="truncate">{f.name}</span>
                            <button type="button" onClick={() => removeFile(i)} className="text-red-500 hover:text-red-700 ml-2 text-xs">Remove</button>
                        </li>
                    ))}
                </ul>
            )}
        </div>
    )
}

function BooleanChoiceField({
    control,
    name,
    label,
    error,
}: {
    control: any
    name: any
    label: string
    error?: string
}) {
    return (
        <div className="rounded-lg bg-gray-50 px-4 py-3">
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <span className="text-sm text-gray-700">{label}</span>
                <Controller
                    control={control}
                    name={name}
                    render={({ field }) => (
                        <div className="flex items-center gap-6">
                            <label className="flex items-center gap-2 text-sm text-gray-700">
                                <span>Yes</span>
                                <input
                                    type="checkbox"
                                    checked={field.value === true}
                                    onChange={() => field.onChange(true)}
                                    className="h-4 w-4 rounded border-gray-300 text-blue-600"
                                />
                            </label>
                            <label className="flex items-center gap-2 text-sm text-gray-700">
                                <span>No</span>
                                <input
                                    type="checkbox"
                                    checked={field.value === false}
                                    onChange={() => field.onChange(false)}
                                    className="h-4 w-4 rounded border-gray-300 text-blue-600"
                                />
                            </label>
                        </div>
                    )}
                />
            </div>
            {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
        </div>
    )
}

const defaultFormValues: Partial<FormValues> = {
    first_name: '',
    middle_name: '',
    last_name: '',
    date_of_birth: '',
    gender: '',
    nationality: '',
    state_of_origin: '',
    lga: '',
    employment_status: '',
    residence_country: '',
    residence_state: '',
    residence_city: '',
    residence_lga: '',
    residence_address: '',
    length_of_stay: '',
    housing_status: '',
    employment_info: {},
    financial_info: {
        bank_name: '',
        bank_address: '',
        account_name: '',
        account_number: '',
        business_name: '',
        business_address: '',
        business_type: '',
        monthly_income_amount: '',
        monthly_expenses: '',
        current_rent_amount: '',
        current_service_charge: '',
        current_move_in_date: '',
        expected_move_out_date: '',
        reason_for_wanting_to_leave: '',
        credit_commitment: '',
        outstanding_loans: '',
    },
    guarantor_details: {},
    landlord_info: {},
    rental_history_same_as_current_residence: false,
    rental_history: [{ property_address: '' }],
    household_info: {
        marital_status: '',
        number_of_adults: '',
        number_of_children: '',
        has_pets: undefined as unknown as boolean,
        number_of_pets: '',
        work_from_home: undefined as unknown as boolean,
        commercial_activities_at_home: undefined as unknown as boolean,
        has_smokers: undefined as unknown as boolean,
    },
    social_presence: {},
    criminal_declaration: {
        convicted_of_crime: undefined as unknown as boolean,
        evicted_from_property: undefined as unknown as boolean,
        ongoing_tenancy_litigation: undefined as unknown as boolean,
        rent_arrears_history: undefined as unknown as boolean,
        legal_dispute_with_landlords: undefined as unknown as boolean,
    },
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

function splitName(name?: string) {
    const parts = String(name || '').trim().split(/\s+/).filter(Boolean)
    return {
        first_name: parts[0] || '',
        middle_name: parts.length > 2 ? parts.slice(1, -1).join(' ') : '',
        last_name: parts.length > 1 ? parts[parts.length - 1] : '',
    }
}

function buildVerificationProfileDefaults(me?: User | null): Partial<FormValues> {
    const verificationProfile = asRecord(me?.tenant_verification_profile)
    const nameParts = splitName(me?.name)
    return {
        first_name: stringValue(verificationProfile.first_name) || nameParts.first_name,
        middle_name: stringValue(verificationProfile.middle_name) || nameParts.middle_name,
        last_name: stringValue(verificationProfile.last_name) || nameParts.last_name,
        date_of_birth: dateInputValue(verificationProfile.date_of_birth),
        gender: optionValue(verificationProfile.gender, genderOptions),
        nationality: stringValue(verificationProfile.nationality) || 'Nigeria',
        state_of_origin: stringValue(verificationProfile.state_of_origin || me?.state_of_origin),
        lga: stringValue(verificationProfile.lga),
        employment_status: optionValue(verificationProfile.employment_status, employmentOptions),
    }
}

function collectErrorPaths(errors: FieldErrors<FormValues>, prefix = ''): string[] {
    return Object.entries(errors).flatMap(([key, value]) => {
        if (!value) {
            return []
        }

        const nextPath = prefix ? `${prefix}.${key}` : key
        if (Array.isArray(value)) {
            return value.flatMap((entry, index) => collectErrorPaths((entry || {}) as FieldErrors<FormValues>, `${nextPath}.${index}`))
        }

        if (typeof value === 'object' && 'message' in value && value.message) {
            return [nextPath]
        }

        if (typeof value === 'object') {
            return collectErrorPaths(value as FieldErrors<FormValues>, nextPath)
        }

        return []
    })
}

function getStepForPath(path: string): number {
    if (
        path.startsWith('first_name') ||
        path.startsWith('middle_name') ||
        path.startsWith('last_name') ||
        path.startsWith('date_of_birth') ||
        path.startsWith('gender') ||
        path.startsWith('nationality') ||
        path.startsWith('state_of_origin') ||
        path.startsWith('lga') ||
        path.startsWith('employment_status')
    ) {
        return 1
    }

    if (
        path.startsWith('residence_') ||
        path.startsWith('length_of_stay') ||
        path.startsWith('housing_status') ||
        path.startsWith('financial_info.current_')
    ) {
        return 2
    }

    if (path.startsWith('employment_info.')) {
        return 3
    }

    if (
        path.startsWith('financial_info.') &&
        !path.startsWith('financial_info.current_')
    ) {
        return 4
    }

    if (path.startsWith('guarantor_details.')) {
        return 5
    }

    if (path.startsWith('landlord_info.')) {
        return 6
    }

    if (path.startsWith('rental_history') || path.startsWith('rental_history_same_as_current_residence')) {
        return 7
    }

    if (path.startsWith('household_info.')) {
        return 8
    }

    if (path.startsWith('social_presence.')) {
        return 9
    }

    if (path.startsWith('criminal_declaration.')) {
        return 10
    }

    return 11
}

type TenantProfileDetailsFormProps = {
    onSaved?: (profile: FormValues & { status: string; supporting_document_urls?: string[] }) => void
}

export default function TenantProfileDetailsForm({ onSaved }: TenantProfileDetailsFormProps = {}) {
    const { user } = useAuth()
    const qc = useQueryClient()
    const [activeStep, setActiveStep] = useState(1)
    const [isSubmitting, setIsSubmitting] = useState(false)
    const [submitError, setSubmitError] = useState('')
    const [fileMap, setFileMap] = useState<FileMap>({})
    const [profilePhoto, setProfilePhoto] = useState<File | null>(null)
    const [profilePhotoPreview, setProfilePhotoPreview] = useState('/placeholder.jpg')

    const { data: existingProfile } = useQuery({
        queryKey: ['users', 'me', 'tenant-profile'],
        queryFn: async () => {
            try {
                const res = await api.get('/users/me/tenant-profile')
                return res.data as FormValues & { status: string; supporting_document_urls?: string[] }
            } catch {
                return null
            }
        },
        enabled: !!user,
    })

    const { data: me } = useQuery({
        queryKey: ['users', 'me'],
        queryFn: async () => (await api.get<User>('/users/me')).data,
        enabled: !!user,
    })

    const verificationProfile = useMemo(() => asRecord(me?.tenant_verification_profile), [me?.tenant_verification_profile])
    const verificationProfileDefaults = useMemo(() => buildVerificationProfileDefaults(me), [me])
    const hasVerificationProfileDefaults = Boolean(
        verificationProfileDefaults.first_name
        && verificationProfileDefaults.last_name
        && verificationProfileDefaults.date_of_birth
        && verificationProfileDefaults.gender
        && verificationProfileDefaults.nationality
        && verificationProfileDefaults.state_of_origin
        && verificationProfileDefaults.lga
        && verificationProfileDefaults.employment_status,
    )

    const {
        register,
        handleSubmit,
        watch,
        control,
        formState: { errors },
        reset,
        setValue,
        clearErrors,
    } = useForm<FormValues>({
        resolver: zodResolver(schema),
        defaultValues: defaultFormValues,
    })

    const { fields: rentalFields, append: appendRental, remove: removeRental } = useFieldArray({
        control,
        name: 'rental_history',
    })

    const employmentStatus = watch('employment_status')
    const hasPets = watch('household_info.has_pets')
    const sameAsCurrent = watch('landlord_info.same_as_current_address')
    const landlordName = watch('landlord_info.name')
    const landlordMobile = watch('landlord_info.mobile')
    const landlordEmail = watch('landlord_info.email')
    const landlordAddress = watch('landlord_info.address')
    const propertyManagerSameAsLandlordName = watch('landlord_info.property_manager_same_as_landlord_name')
    const propertyManagerSameAsLandlordPhone = watch('landlord_info.property_manager_same_as_landlord_phone')
    const propertyManagerSameAsLandlordEmail = watch('landlord_info.property_manager_same_as_landlord_email')
    const propertyManagerSameAsLandlordAddress = watch('landlord_info.property_manager_same_as_landlord_address')
    const nationality = watch('nationality')
    const stateOfOrigin = watch('state_of_origin')
    const lgaOfOrigin = watch('lga')
    const residenceCountry = watch('residence_country')
    const residenceState = watch('residence_state')
    const residenceLga = watch('residence_lga')
    const residenceAddress = watch('residence_address')
    const residenceCity = watch('residence_city')
    const residenceLengthOfStay = watch('length_of_stay')
    const residenceAnnualRent = watch('financial_info.current_rent_amount')
    const residenceServiceCharge = watch('financial_info.current_service_charge')
    const residenceMoveInDate = watch('financial_info.current_move_in_date')
    const residenceExpectedMoveOutDate = watch('financial_info.expected_move_out_date')
    const residenceReasonForLeave = watch('financial_info.reason_for_wanting_to_leave')
    const rentalHistorySameAsCurrent = watch('rental_history_same_as_current_residence')
    const residenceCountryIsNigeria = isNigeriaSelection(residenceCountry)
    const nationalityIsNigeria = isNigeriaSelection(nationality)
    const stateOfOriginOptions = nationalityIsNigeria && stateOfOrigin
        ? nigeriaStateLgaMap[stateOfOrigin] || []
        : []
    const residenceLgaOptions = residenceCountryIsNigeria && residenceState
        ? nigeriaStateLgaMap[residenceState] || []
        : []
    const currentResidenceYears = useMemo(
        () => parseYearsOfStay(residenceLengthOfStay),
        [residenceLengthOfStay],
    )
    const requiresAdditionalRentalHistory = Boolean(rentalHistorySameAsCurrent && currentResidenceYears < 5)
    const currentResidenceMeetsMinimumHistory = currentResidenceYears >= 5
    const currentResidenceRentalHistoryPreview = useMemo(() => ({
        property_address: [residenceAddress, residenceCity, residenceState].filter(Boolean).join(', '),
        annual_rent: residenceAnnualRent || '',
        service_charge: residenceServiceCharge || '',
        move_in_date: residenceMoveInDate || '',
        move_out_date: residenceExpectedMoveOutDate || '',
        reason_for_leave: residenceReasonForLeave || '',
    }), [
        residenceAddress,
        residenceAnnualRent,
        residenceCity,
        residenceExpectedMoveOutDate,
        residenceMoveInDate,
        residenceReasonForLeave,
        residenceServiceCharge,
        residenceState,
    ])
    const dashboardPath = user?.id ? `/dashboard/tenant/${user.id}` : '/search'

    useEffect(() => {
        if (!profilePhoto) {
            setProfilePhotoPreview(resolveMediaUrl(me?.profile_photo_url))
            return
        }

        const objectUrl = URL.createObjectURL(profilePhoto)
        setProfilePhotoPreview(objectUrl)
        return () => URL.revokeObjectURL(objectUrl)
    }, [me?.profile_photo_url, profilePhoto])

    useEffect(() => {
        if (!existingProfile) {
            reset({
                ...defaultFormValues,
                ...verificationProfileDefaults,
            })
            return
        }

        reset({
            ...defaultFormValues,
            ...verificationProfileDefaults,
            ...existingProfile,
            employment_info: existingProfile.employment_info || {},
            financial_info: existingProfile.financial_info || {},
            guarantor_details: existingProfile.guarantor_details || {},
            landlord_info: existingProfile.landlord_info || {},
            rental_history_same_as_current_residence: false,
            rental_history: existingProfile.rental_history?.length ? existingProfile.rental_history : [{ property_address: '' }],
            household_info: {
                ...defaultFormValues.household_info,
                ...(existingProfile.household_info || {}),
            },
            social_presence: existingProfile.social_presence || {},
            criminal_declaration: existingProfile.criminal_declaration || {},
        })
    }, [existingProfile, reset, verificationProfileDefaults])

    useEffect(() => {
        if (!nationalityIsNigeria) {
            clearErrors(['state_of_origin', 'lga'])
            return
        }

        if (stateOfOrigin && !nigerianStates.includes(stateOfOrigin)) {
            setValue('state_of_origin', '')
            setValue('lga', '')
        } else if (lgaOfOrigin && !stateOfOriginOptions.includes(lgaOfOrigin)) {
            setValue('lga', '')
        }
    }, [clearErrors, lgaOfOrigin, nationalityIsNigeria, setValue, stateOfOrigin, stateOfOriginOptions])

    useEffect(() => {
        if (!residenceCountryIsNigeria) {
            clearErrors(['residence_state', 'residence_lga'])
            return
        }

        if (residenceState && !nigerianStates.includes(residenceState)) {
            setValue('residence_state', '')
            setValue('residence_lga', '')
        } else if (residenceLga && !residenceLgaOptions.includes(residenceLga)) {
            setValue('residence_lga', '')
        }
    }, [clearErrors, residenceCountryIsNigeria, residenceLga, residenceLgaOptions, residenceState, setValue])

    useEffect(() => {
        if (!sameAsCurrent) {
            return
        }
        setValue('landlord_info.address', residenceAddress || '')
    }, [residenceAddress, sameAsCurrent, setValue])

    useEffect(() => {
        if (!propertyManagerSameAsLandlordName) {
            return
        }
        setValue('landlord_info.property_manager_name', landlordName || '')
    }, [landlordName, propertyManagerSameAsLandlordName, setValue])

    useEffect(() => {
        if (!propertyManagerSameAsLandlordPhone) {
            return
        }
        setValue('landlord_info.property_manager_phone', landlordMobile || '')
    }, [landlordMobile, propertyManagerSameAsLandlordPhone, setValue])

    useEffect(() => {
        if (!propertyManagerSameAsLandlordEmail) {
            return
        }
        setValue('landlord_info.property_manager_email', landlordEmail || '')
    }, [landlordEmail, propertyManagerSameAsLandlordEmail, setValue])

    useEffect(() => {
        if (!propertyManagerSameAsLandlordAddress) {
            return
        }
        setValue('landlord_info.property_manager_address', landlordAddress || '')
    }, [landlordAddress, propertyManagerSameAsLandlordAddress, setValue])

    const uploadFiles = useMutation({
        mutationFn: async (files: File[]) => {
            const ids: string[] = []
            for (const file of files) {
                const formData = new FormData()
                formData.append('file', file)
                formData.append('title', file.name)
                const res = await api.post('/documents', formData, {
                    headers: { 'Content-Type': 'multipart/form-data' },
                })
                ids.push(res.data.id)
            }
            return ids
        },
    })

    const buildCurrentResidenceRentalHistoryEntry = useCallback((data: FormValues) => ({
        property_address: [data.residence_address, data.residence_city, data.residence_state].filter(Boolean).join(', '),
        annual_rent: data.financial_info?.current_rent_amount || '',
        service_charge: data.financial_info?.current_service_charge || '',
        move_in_date: data.financial_info?.current_move_in_date || '',
        move_out_date: data.financial_info?.expected_move_out_date || '',
        reason_for_leave: data.financial_info?.reason_for_wanting_to_leave || '',
    }), [])

    const normalizeRentalHistory = useCallback((data: FormValues) => {
        const manualHistory = (data.rental_history || []).filter((item) => rentalHistoryItemHasAnyValue(item))
        const currentResidenceHistory = buildCurrentResidenceRentalHistoryEntry(data)

        if (data.rental_history_same_as_current_residence) {
            if (parseYearsOfStay(data.length_of_stay) >= 5) {
                return [currentResidenceHistory]
            }
            return [currentResidenceHistory, ...manualHistory]
        }

        return manualHistory
    }, [buildCurrentResidenceRentalHistoryEntry])

    const submitProfile = useMutation({
        mutationFn: async (data: FormValues) => {
            if (!profilePhoto && !me?.profile_photo_url) {
                throw new Error('Profile photo is required.')
            }

            if (profilePhoto) {
                const formData = new FormData()
                formData.append('file', profilePhoto)
                const photoResponse = await api.post<User>('/users/me/photo', formData, {
                    headers: { 'Content-Type': 'multipart/form-data' },
                })
                qc.setQueryData(['users', 'me'], photoResponse.data)
                localStorage.setItem('user', JSON.stringify(photoResponse.data))
            }

            const allFiles = Object.values(fileMap).flat()
            const payload: Record<string, any> = {
                ...data,
                country_of_birth: stringValue(verificationProfile.country_of_birth),
                email: stringValue(verificationProfile.email || me?.email),
                mobile: stringValue(verificationProfile.mobile || me?.mobile),
                nin_number: stringValue(me?.nin_number || verificationProfile.nin_number || verificationProfile.nin),
                bvn_number: stringValue(me?.bvn_number || verificationProfile.bvn_number || verificationProfile.bvn),
                rental_history: normalizeRentalHistory(data),
            }
            delete payload.rental_history_same_as_current_residence
            const landlordInfo = asRecord(payload.landlord_info)
            delete landlordInfo.property_manager_same_as_landlord_name
            delete landlordInfo.property_manager_same_as_landlord_phone
            delete landlordInfo.property_manager_same_as_landlord_email
            delete landlordInfo.property_manager_same_as_landlord_address
            payload.landlord_info = landlordInfo
            if (allFiles.length > 0) {
                const uploaded = await uploadFiles.mutateAsync(allFiles)
                payload.document_ids = uploaded
            }
            const method = existingProfile ? 'put' : 'post'
            const res = await api[method]('/users/me/tenant-profile', payload)
            return res.data
        },
        onSuccess: (profile) => {
            qc.setQueryData(['users', 'me', 'tenant-profile'], profile)
            qc.invalidateQueries({ queryKey: ['tenant-profile'] })
            qc.invalidateQueries({ queryKey: ['users', 'me'] })
            qc.invalidateQueries({ queryKey: ['verification', 'status'] })
            alert('Tenant profile updated successfully.')
            setFileMap({})
            setProfilePhoto(null)
            setSubmitError('')
            onSaved?.(profile)
        },
        onError: (err: any) => {
            setSubmitError(err?.response?.data?.detail || err.message || 'Submission failed. Please try again.')
        },
    })

    const onSubmit = useCallback(async (data: FormValues) => {
        setIsSubmitting(true)
        setSubmitError('')
        try {
            await submitProfile.mutateAsync(data)
        } finally {
            setIsSubmitting(false)
        }
    }, [submitProfile])

    const onInvalid = useCallback((formErrors: FieldErrors<FormValues>) => {
        const errorPaths = collectErrorPaths(formErrors)
        if (errorPaths.length > 0) {
            setActiveStep(Math.min(...errorPaths.map(getStepForPath)))
        }
        setSubmitError('Please complete the required fields before submitting for verification.')
        window.scrollTo({ top: 0, behavior: 'smooth' })
    }, [])

    const setFilesForKey = useCallback((key: string) => (files: File[]) => {
        setFileMap(prev => ({ ...prev, [key]: files }))
    }, [])

    if (!existingProfile && !(me?.is_verified && hasVerificationProfileDefaults)) {
        return (
            <div className="rounded-xl border bg-white p-6 text-gray-600">
                Complete tenant verification before adding the rest of your tenant profile.
                <div className="mt-4">
                    <Link to="/verify" className="btn btn-primary">Go to Verification</Link>
                </div>
            </div>
        )
    }

    return (
        <div className="space-y-6">
            <div>
                <div className="mb-6">
                    <h2 className="text-xl font-semibold text-gray-900">Tenant Profile</h2>
                    <p className="text-gray-600 mt-2">Keep your residence, employment, financial, guarantor, and rental information up to date.</p>
                </div>

                {submitError && (
                    <div className="mb-6 rounded-lg bg-red-50 border border-red-200 p-4 text-sm text-red-800">
                        {submitError}
                    </div>
                )}

                <form onSubmit={handleSubmit(onSubmit, onInvalid)} className="space-y-6">
                    <SectionCard title="Profile Photo" step={1} activeStep={activeStep} setActiveStep={setActiveStep}>
                        <div className="flex flex-col gap-5 md:flex-row md:items-center">
                            <div className="h-28 w-28 overflow-hidden rounded-full border border-gray-200 bg-gray-50">
                                <img
                                    src={profilePhotoPreview}
                                    alt="Tenant profile"
                                    loading="eager"
                                    decoding="async"
                                    className="h-full w-full object-cover"
                                />
                            </div>
                            <div className="flex-1">
                                <label className="form-label">Upload profile photo</label>
                                <input
                                    type="file"
                                    accept=".jpg,.jpeg,.png,.webp"
                                    onChange={(event) => setProfilePhoto(event.target.files?.[0] || null)}
                                    className="block w-full text-sm text-gray-500 file:mr-4 file:rounded-full file:border-0 file:bg-blue-50 file:px-4 file:py-2 file:text-sm file:font-semibold file:text-blue-700 hover:file:bg-blue-100"
                                />
                                <p className="mt-2 text-sm text-gray-500">A clear tenant profile photo is required before saving your profile.</p>
                                {!profilePhoto && !me?.profile_photo_url && (
                                    <p className="mt-2 text-sm font-medium text-red-600">Profile photo is required.</p>
                                )}
                            </div>
                        </div>
                    </SectionCard>

                    <SectionCard title="Personal Information" step={1} activeStep={activeStep} setActiveStep={setActiveStep}>
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
                            <InputRow label="Date of Birth" error={errors.date_of_birth?.message}>
                                <TextInput register={register} name="date_of_birth" type="date" error={errors.date_of_birth?.message} />
                            </InputRow>
                            <InputRow label="Gender" error={errors.gender?.message}>
                                <SelectInput register={register} name="gender" options={genderOptions} placeholder="Select gender" error={errors.gender?.message} />
                            </InputRow>
                            <InputRow label="Employment Status" error={errors.employment_status?.message}>
                                <SelectInput register={register} name="employment_status" options={employmentOptions} placeholder="Select employment status" error={errors.employment_status?.message} />
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
                            <InputRow label="LGA" error={errors.lga?.message}>
                                {nationalityIsNigeria ? (
                                    <SelectInput register={register} name="lga" options={stateOfOriginOptions} placeholder={stateOfOrigin ? 'Select LGA' : 'Select state first'} error={errors.lga?.message} />
                                ) : (
                                    <TextInput register={register} name="lga" placeholder="Local Government Area" error={errors.lga?.message} />
                                )}
                            </InputRow>
                        </div>
                    </SectionCard>

                    {/* 2. Current Residence */}
                    <SectionCard title="Current Residence" step={2} activeStep={activeStep} setActiveStep={setActiveStep}>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <InputRow label="Country" error={errors.residence_country?.message}>
                                <SelectInput register={register} name="residence_country" options={[...worldCountryOptions]} placeholder="Select country" error={errors.residence_country?.message} />
                            </InputRow>
                            <InputRow label="State" error={errors.residence_state?.message}>
                                {residenceCountryIsNigeria ? (
                                    <SelectInput register={register} name="residence_state" options={nigerianStates} placeholder="Select state" error={errors.residence_state?.message} />
                                ) : (
                                    <TextInput register={register} name="residence_state" placeholder="State" error={errors.residence_state?.message} />
                                )}
                            </InputRow>
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
                            <InputRow label="City" error={errors.residence_city?.message}>
                                <TextInput register={register} name="residence_city" placeholder="City" error={errors.residence_city?.message} />
                            </InputRow>
                            <InputRow label="LGA" error={errors.residence_lga?.message}>
                                {residenceCountryIsNigeria ? (
                                    <SelectInput
                                        register={register}
                                        name="residence_lga"
                                        options={residenceLgaOptions}
                                        placeholder={residenceState ? 'Select local government area' : 'Select state first'}
                                        error={errors.residence_lga?.message}
                                    />
                                ) : (
                                    <TextInput register={register} name="residence_lga" placeholder="Local Government Area" error={errors.residence_lga?.message} />
                                )}
                            </InputRow>
                        </div>
                        <div className="mt-4">
                            <InputRow label="Address" error={errors.residence_address?.message}>
                                <textarea
                                    {...register('residence_address')}
                                    placeholder="Current residential address"
                                    rows={3}
                                    className={`w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${errors.residence_address ? 'border-red-300' : 'border-gray-300'}`}
                                />
                            </InputRow>
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
                            <InputRow label="Length of Stay" error={errors.length_of_stay?.message}>
                                <TextInput register={register} name="length_of_stay" type="number" min="0" step="0.1" placeholder="Length of stay in years" error={errors.length_of_stay?.message} />
                            </InputRow>
                            <InputRow label="Housing Status" error={errors.housing_status?.message}>
                                <SelectInput register={register} name="housing_status" options={housingStatusOptions} placeholder="Select housing status" error={errors.housing_status?.message} />
                            </InputRow>
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
                            <InputRow label="Annual Rent" error={errors.financial_info?.current_rent_amount?.message}>
                                <TextInput register={register} name="financial_info.current_rent_amount" placeholder="e.g. 1200000" error={errors.financial_info?.current_rent_amount?.message} />
                            </InputRow>
                            <InputRow label="Service Charge" error={errors.financial_info?.current_service_charge?.message}>
                                <TextInput register={register} name="financial_info.current_service_charge" placeholder="e.g. 150000" error={errors.financial_info?.current_service_charge?.message} />
                            </InputRow>
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
                            <InputRow label="Move In Date" error={errors.financial_info?.current_move_in_date?.message}>
                                <TextInput register={register} name="financial_info.current_move_in_date" type="date" error={errors.financial_info?.current_move_in_date?.message} />
                            </InputRow>
                            <InputRow label="Expected Move Out Date" error={errors.financial_info?.expected_move_out_date?.message}>
                                <TextInput register={register} name="financial_info.expected_move_out_date" type="date" error={errors.financial_info?.expected_move_out_date?.message} />
                            </InputRow>
                        </div>
                        <div className="mt-4">
                            <InputRow label="Reason for Wanting to Leave" error={errors.financial_info?.reason_for_wanting_to_leave?.message}>
                                <textarea
                                    {...register('financial_info.reason_for_wanting_to_leave')}
                                    placeholder="Explain why you intend to leave the current residence"
                                    rows={3}
                                    className={`w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${errors.financial_info?.reason_for_wanting_to_leave ? 'border-red-300' : 'border-gray-300'}`}
                                />
                            </InputRow>
                        </div>
                    </SectionCard>

                    {/* 3. Employment Information (conditional) */}
                    {employmentStatus === 'Employed' && (
                        <SectionCard title="Employment Information" step={3} activeStep={activeStep} setActiveStep={setActiveStep}>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <InputRow label="Company Name">
                                    <TextInput register={register} name="employment_info.company_name" placeholder="Company name" />
                                </InputRow>
                                <InputRow label="Company Contact Number">
                                    <TextInput register={register} name="employment_info.company_contact_number" placeholder="Company phone" />
                                </InputRow>
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-4">
                                <InputRow label="Industry">
                                    <TextInput register={register} name="employment_info.industry" placeholder="Industry" />
                                </InputRow>
                                <InputRow label="Employment Type">
                                    <SelectInput register={register} name="employment_info.employment_type" options={employmentTypeOptions} placeholder="Select type" />
                                </InputRow>
                                <InputRow label="Employment Start Date">
                                    <TextInput register={register} name="employment_info.employment_start_date" type="date" />
                                </InputRow>
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
                                <InputRow label="Position / Job Title">
                                    <TextInput register={register} name="employment_info.position_job_title" placeholder="Job title" />
                                </InputRow>
                                <InputRow label="Company Website">
                                    <TextInput register={register} name="employment_info.company_website" placeholder="www.example.com" />
                                </InputRow>
                            </div>
                            <div className="mt-4">
                                <InputRow label="Company Address">
                                    <textarea
                                        {...register('employment_info.company_address')}
                                        placeholder="Company address"
                                        rows={2}
                                        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                                    />
                                </InputRow>
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-4">
                                <InputRow label="HR Contact Name">
                                    <TextInput register={register} name="employment_info.hr_contact_name" placeholder="HR name" />
                                </InputRow>
                                <InputRow label="HR Email">
                                    <TextInput register={register} name="employment_info.hr_email" placeholder="hr@company.com" />
                                </InputRow>
                                <InputRow label="HR Contact Phone">
                                    <TextInput register={register} name="employment_info.hr_contact_phone" placeholder="HR phone" />
                                </InputRow>
                            </div>
                            <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-4">
                                <FileUploadBox label="Employment Letter" files={fileMap['employment_letter'] || []} onChange={setFilesForKey('employment_letter')} />
                                <FileUploadBox label="Staff ID Card" files={fileMap['staff_id'] || []} onChange={setFilesForKey('staff_id')} />
                                <FileUploadBox label="Payslip (Last 3-6 months)" files={fileMap['payslip'] || []} onChange={setFilesForKey('payslip')} />
                            </div>
                        </SectionCard>
                    )}

                    {/* 4. Financial Verification (conditional) */}
                    {employmentStatus && employmentStatus !== 'Employed' && (
                        <SectionCard title="Financial Verification" step={4} activeStep={activeStep} setActiveStep={setActiveStep}>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <InputRow label="Bank Name">
                                    <TextInput register={register} name="financial_info.bank_name" placeholder="Bank name" />
                                </InputRow>
                                <InputRow label="Bank Address">
                                    <TextInput register={register} name="financial_info.bank_address" placeholder="Bank branch address" />
                                </InputRow>
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
                                <InputRow label="Account Name">
                                    <TextInput register={register} name="financial_info.account_name" placeholder="Account name" />
                                </InputRow>
                                <InputRow label="Account Number">
                                    <TextInput register={register} name="financial_info.account_number" placeholder="Account number" />
                                </InputRow>
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-4">
                                <InputRow label="Business Name">
                                    <TextInput register={register} name="financial_info.business_name" placeholder="Business name" />
                                </InputRow>
                                <InputRow label="Business Address">
                                    <TextInput register={register} name="financial_info.business_address" placeholder="Business address" />
                                </InputRow>
                                <InputRow label="Business Type">
                                    <TextInput register={register} name="financial_info.business_type" placeholder="Business type" />
                                </InputRow>
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
                                <InputRow label="Monthly Income Amount">
                                    <TextInput register={register} name="financial_info.monthly_income_amount" placeholder="e.g. 500000" />
                                </InputRow>
                                <InputRow label="Monthly Expenses">
                                    <TextInput register={register} name="financial_info.monthly_expenses" placeholder="e.g. 200000" />
                                </InputRow>
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
                                <InputRow label="Current Rent Amount">
                                    <TextInput register={register} name="financial_info.current_rent_amount" placeholder="e.g. 1500000/year" />
                                </InputRow>
                                <InputRow label="Current Service Charge">
                                    <TextInput register={register} name="financial_info.current_service_charge" placeholder="e.g. 100000/year" />
                                </InputRow>
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
                                <InputRow label="Credit Commitment">
                                    <TextInput register={register} name="financial_info.credit_commitment" placeholder="e.g. 50000/month" />
                                </InputRow>
                                <InputRow label="Outstanding Loans">
                                    <TextInput register={register} name="financial_info.outstanding_loans" placeholder="e.g. 2000000" />
                                </InputRow>
                            </div>
                            <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-4">
                                <FileUploadBox label="Bank Statement (6 Months)" files={fileMap['bank_statement'] || []} onChange={setFilesForKey('bank_statement')} />
                                <FileUploadBox label="Tax Clearance" files={fileMap['tax_clearance'] || []} onChange={setFilesForKey('tax_clearance')} />
                                <FileUploadBox label="CAC Registration Document" files={fileMap['cac_registration'] || []} onChange={setFilesForKey('cac_registration')} />
                            </div>
                        </SectionCard>
                    )}

                    {/* 5. Guarantor Details */}
                    <SectionCard title="Guarantor Details" step={5} activeStep={activeStep} setActiveStep={setActiveStep}>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <InputRow label="Full Name">
                                <TextInput register={register} name="guarantor_details.full_name" placeholder="Guarantor full name" />
                            </InputRow>
                            <InputRow label="Relationship">
                                <TextInput register={register} name="guarantor_details.relationship" placeholder="e.g. Parent, Sibling, Friend" />
                            </InputRow>
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
                            <InputRow label="Email">
                                <TextInput register={register} name="guarantor_details.email" placeholder="guarantor@email.com" />
                            </InputRow>
                            <InputRow label="Mobile Number">
                                <TextInput register={register} name="guarantor_details.mobile_number" placeholder="Phone number" />
                            </InputRow>
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
                            <InputRow label="Occupation">
                                <TextInput register={register} name="guarantor_details.occupation" placeholder="Occupation" />
                            </InputRow>
                            <InputRow label="Employer">
                                <TextInput register={register} name="guarantor_details.employer" placeholder="Employer name" />
                            </InputRow>
                        </div>
                        <div className="mt-4">
                            <InputRow label="Residential Address">
                                <textarea
                                    {...register('guarantor_details.residential_address')}
                                    placeholder="Guarantor residential address"
                                    rows={2}
                                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                                />
                            </InputRow>
                        </div>
                        <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-4">
                            <FileUploadBox label="Government ID" files={fileMap['guarantor_gov_id'] || []} onChange={setFilesForKey('guarantor_gov_id')} />
                            <FileUploadBox label="Passport Photo" files={fileMap['guarantor_photo'] || []} onChange={setFilesForKey('guarantor_photo')} />
                            <FileUploadBox label="Utility Bill" files={fileMap['guarantor_utility'] || []} onChange={setFilesForKey('guarantor_utility')} />
                        </div>
                    </SectionCard>

                    {/* 6. Landlord Information */}
                    <SectionCard title="Current Landlord Information" step={6} activeStep={activeStep} setActiveStep={setActiveStep}>
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                            <InputRow label="Full Name">
                                <TextInput register={register} name="landlord_info.name" placeholder="Landlord full name" />
                            </InputRow>
                            <InputRow label="Mobile">
                                <TextInput register={register} name="landlord_info.mobile" placeholder="Landlord phone" />
                            </InputRow>
                            <InputRow label="Email">
                                <TextInput register={register} name="landlord_info.email" type="email" placeholder="Landlord email" />
                            </InputRow>
                        </div>
                        <div className="mt-4">
                            <div className="mb-1 flex items-center justify-between gap-4">
                                <label className="block text-sm font-medium text-gray-700">Address</label>
                                <label className="flex items-center gap-2 text-sm text-gray-700">
                                    <span>Same as current address</span>
                                    <input
                                        type="checkbox"
                                        {...register('landlord_info.same_as_current_address')}
                                        className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                                    />
                                </label>
                            </div>
                            <textarea
                                {...register('landlord_info.address')}
                                placeholder="Landlord address"
                                rows={2}
                                readOnly={sameAsCurrent}
                                className={`w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${sameAsCurrent ? 'border-gray-200 bg-gray-100 text-gray-500' : 'border-gray-300'}`}
                            />
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-4">
                            <InputRow
                                label="Property Manager Name"
                                action={<SameAsLandlordCheckbox register={register} name="landlord_info.property_manager_same_as_landlord_name" />}
                            >
                                <TextInput
                                    register={register}
                                    name="landlord_info.property_manager_name"
                                    placeholder="Property manager name"
                                    disabled={propertyManagerSameAsLandlordName}
                                />
                            </InputRow>
                            <InputRow
                                label="Property Manager Phone"
                                action={<SameAsLandlordCheckbox register={register} name="landlord_info.property_manager_same_as_landlord_phone" />}
                            >
                                <TextInput
                                    register={register}
                                    name="landlord_info.property_manager_phone"
                                    placeholder="Property manager phone"
                                    disabled={propertyManagerSameAsLandlordPhone}
                                />
                            </InputRow>
                            <InputRow
                                label="Property Manager Email"
                                action={<SameAsLandlordCheckbox register={register} name="landlord_info.property_manager_same_as_landlord_email" />}
                            >
                                <TextInput
                                    register={register}
                                    name="landlord_info.property_manager_email"
                                    type="email"
                                    placeholder="Property manager email"
                                    disabled={propertyManagerSameAsLandlordEmail}
                                />
                            </InputRow>
                        </div>
                        <div className="mt-4">
                            <InputRow
                                label="Property Manager Address"
                                action={<SameAsLandlordCheckbox register={register} name="landlord_info.property_manager_same_as_landlord_address" />}
                            >
                                <textarea
                                    {...register('landlord_info.property_manager_address')}
                                    placeholder="Property manager address"
                                    rows={2}
                                    readOnly={propertyManagerSameAsLandlordAddress}
                                    className={`w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${propertyManagerSameAsLandlordAddress ? 'border-gray-200 bg-gray-100 text-gray-500' : 'border-gray-300'}`}
                                />
                            </InputRow>
                        </div>
                    </SectionCard>

                    {/* 7. Rental History */}
                    <SectionCard title="Rental History (Not less than 5 Years)" step={7} activeStep={activeStep} setActiveStep={setActiveStep}>
                        <p className="text-sm text-gray-500 mb-4">If less than five years, provide information for all properties you have lived in.</p>
                        <div className="mb-4 flex items-center gap-2">
                            <input
                                type="checkbox"
                                {...register('rental_history_same_as_current_residence')}
                                className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                            />
                            <label className="text-sm text-gray-700">Same as current residence?</label>
                        </div>

                        {rentalHistorySameAsCurrent && (
                            <div className="mb-4 rounded-lg border border-blue-200 bg-blue-50 p-4">
                                <div className="flex items-center justify-between gap-3">
                                    <div>
                                        <h4 className="text-sm font-semibold text-blue-900">Current Residence Rental History</h4>
                                        <p className="mt-1 text-sm text-blue-800">
                                            Your current residence details below will be used as part of your rental history.
                                        </p>
                                    </div>
                                    <span className="rounded-full bg-white px-3 py-1 text-xs font-semibold text-blue-700">
                                        {currentResidenceYears.toFixed(1)} years
                                    </span>
                                </div>

                                <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
                                    <div className="rounded-lg bg-white px-4 py-3">
                                        <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Property Address</p>
                                        <p className="mt-2 text-sm text-gray-900">{currentResidenceRentalHistoryPreview.property_address || 'Complete your current residence address above.'}</p>
                                    </div>
                                    <div className="rounded-lg bg-white px-4 py-3">
                                        <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Annual Rent</p>
                                        <p className="mt-2 text-sm text-gray-900">{currentResidenceRentalHistoryPreview.annual_rent || 'Enter annual rent above.'}</p>
                                    </div>
                                    <div className="rounded-lg bg-white px-4 py-3">
                                        <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Service Charge</p>
                                        <p className="mt-2 text-sm text-gray-900">{currentResidenceRentalHistoryPreview.service_charge || 'Enter service charge above.'}</p>
                                    </div>
                                    <div className="rounded-lg bg-white px-4 py-3">
                                        <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Move In / Expected Move Out</p>
                                        <p className="mt-2 text-sm text-gray-900">
                                            {[currentResidenceRentalHistoryPreview.move_in_date, currentResidenceRentalHistoryPreview.move_out_date].filter(Boolean).join(' to ') || 'Enter move in and move out dates above.'}
                                        </p>
                                    </div>
                                    <div className="rounded-lg bg-white px-4 py-3 md:col-span-2">
                                        <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Reason for Wanting to Leave</p>
                                        <p className="mt-2 text-sm text-gray-900">{currentResidenceRentalHistoryPreview.reason_for_leave || 'Enter your reason for wanting to leave above.'}</p>
                                    </div>
                                </div>
                            </div>
                        )}

                        {rentalHistorySameAsCurrent && !currentResidenceMeetsMinimumHistory && (
                            <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
                                Your current residence covers less than 5 years. Add at least one previous rental property below.
                            </div>
                        )}

                        {(!rentalHistorySameAsCurrent || requiresAdditionalRentalHistory) && rentalFields.map((field, index) => (
                            <div key={field.id} className="border border-gray-200 rounded-lg p-4 mb-4">
                                <div className="flex items-center justify-between mb-3">
                                    <h4 className="text-sm font-semibold text-gray-700">
                                        {rentalHistorySameAsCurrent ? `Previous Property ${index + 1}` : `Property ${index + 1}`}
                                    </h4>
                                    {rentalFields.length > 1 && (
                                        <button
                                            type="button"
                                            onClick={() => removeRental(index)}
                                            className="text-red-500 hover:text-red-700 text-sm"
                                        >
                                            Remove
                                        </button>
                                    )}
                                </div>
                                <div className="grid grid-cols-1 gap-4">
                                    <InputRow label="Property Address" error={errors.rental_history?.[index]?.property_address?.message}>
                                        <TextInput register={register} name={`rental_history.${index}.property_address`} placeholder="Full address" error={errors.rental_history?.[index]?.property_address?.message} />
                                    </InputRow>
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                        <InputRow label="Annual Rent" error={errors.rental_history?.[index]?.annual_rent?.message}>
                                            <TextInput register={register} name={`rental_history.${index}.annual_rent`} placeholder="e.g. 1200000" error={errors.rental_history?.[index]?.annual_rent?.message} />
                                        </InputRow>
                                        <InputRow label="Service Charge" error={errors.rental_history?.[index]?.service_charge?.message}>
                                            <TextInput register={register} name={`rental_history.${index}.service_charge`} placeholder="e.g. 100000" error={errors.rental_history?.[index]?.service_charge?.message} />
                                        </InputRow>
                                    </div>
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                        <InputRow label="Move-In Date" error={errors.rental_history?.[index]?.move_in_date?.message}>
                                            <TextInput register={register} name={`rental_history.${index}.move_in_date`} type="date" error={errors.rental_history?.[index]?.move_in_date?.message} />
                                        </InputRow>
                                        <InputRow label="Move-Out Date" error={errors.rental_history?.[index]?.move_out_date?.message}>
                                            <TextInput register={register} name={`rental_history.${index}.move_out_date`} type="date" error={errors.rental_history?.[index]?.move_out_date?.message} />
                                        </InputRow>
                                    </div>
                                    <InputRow label="Reason for Leave" error={errors.rental_history?.[index]?.reason_for_leave?.message}>
                                        <TextInput register={register} name={`rental_history.${index}.reason_for_leave`} placeholder="e.g. End of lease" error={errors.rental_history?.[index]?.reason_for_leave?.message} />
                                    </InputRow>
                                </div>
                            </div>
                        ))}
                        {(!rentalHistorySameAsCurrent || requiresAdditionalRentalHistory) && rentalFields.length < 5 && (
                            <button
                                type="button"
                                onClick={() => appendRental({ property_address: '' })}
                                className="text-sm text-blue-600 hover:text-blue-700 font-medium"
                            >
                                {rentalHistorySameAsCurrent ? '+ Add Another Previous Property' : '+ Add Another Property'}
                            </button>
                        )}
                    </SectionCard>

                    {/* 8. Household Information */}
                    <SectionCard title="Household Information" step={8} activeStep={activeStep} setActiveStep={setActiveStep}>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <InputRow label="Marital Status" error={errors.household_info?.marital_status?.message}>
                                <SelectInput register={register} name="household_info.marital_status" options={maritalStatusOptions} placeholder="Select marital status" error={errors.household_info?.marital_status?.message} />
                            </InputRow>
                            <InputRow label="Number of Adults">
                                <TextInput register={register} name="household_info.number_of_adults" placeholder="e.g. 2" />
                            </InputRow>
                            <InputRow label="Number of Children">
                                <TextInput register={register} name="household_info.number_of_children" placeholder="e.g. 1" />
                            </InputRow>
                        </div>
                        <div className="mt-4 space-y-4">
                            <BooleanChoiceField
                                control={control}
                                name="household_info.has_pets"
                                label="Any Pets?"
                                error={errors.household_info?.has_pets?.message}
                            />
                            {hasPets && (
                                <InputRow label="Number of Pets" error={errors.household_info?.number_of_pets?.message}>
                                    <TextInput register={register} name="household_info.number_of_pets" placeholder="Number of pets" error={errors.household_info?.number_of_pets?.message} />
                                </InputRow>
                            )}
                            <BooleanChoiceField
                                control={control}
                                name="household_info.work_from_home"
                                label="Work from Home?"
                                error={errors.household_info?.work_from_home?.message}
                            />
                            <BooleanChoiceField
                                control={control}
                                name="household_info.commercial_activities_at_home"
                                label="Commercial Activities at Home?"
                                error={errors.household_info?.commercial_activities_at_home?.message}
                            />
                            <BooleanChoiceField
                                control={control}
                                name="household_info.has_smokers"
                                label="Any Smokers?"
                                error={errors.household_info?.has_smokers?.message}
                            />
                        </div>
                    </SectionCard>

                    {/* 9. Social & Digital Presence */}
                    <SectionCard title="Social & Digital Presence (Optional)" step={9} activeStep={activeStep} setActiveStep={setActiveStep}>
                        <p className="text-sm text-gray-500 mb-4">Optional, but boosts your chances of finding a property.</p>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <InputRow label="LinkedIn Profile">
                                <TextInput register={register} name="social_presence.linkedin_profile" placeholder="https://linkedin.com/in/..." />
                            </InputRow>
                            <InputRow label="Facebook Profile">
                                <TextInput register={register} name="social_presence.facebook_profile" placeholder="https://facebook.com/..." />
                            </InputRow>
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
                            <InputRow label="Instagram Profile">
                                <TextInput register={register} name="social_presence.instagram_profile" placeholder="https://instagram.com/..." />
                            </InputRow>
                            <InputRow label="X (Twitter) Profile">
                                <TextInput register={register} name="social_presence.x_twitter_profile" placeholder="https://x.com/..." />
                            </InputRow>
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
                            <InputRow label="TikTok Profile">
                                <TextInput register={register} name="social_presence.tiktok_profile" placeholder="https://tiktok.com/@..." />
                            </InputRow>
                            <InputRow label="Threads Profile">
                                <TextInput register={register} name="social_presence.threads_profile" placeholder="https://threads.net/@..." />
                            </InputRow>
                        </div>
                    </SectionCard>

                    {/* 10. Criminal & Legal Declaration */}
                    <SectionCard title="Criminal & Legal Declaration" step={10} activeStep={activeStep} setActiveStep={setActiveStep}>
                        <div className="space-y-4">
                            <BooleanChoiceField
                                control={control}
                                name="criminal_declaration.convicted_of_crime"
                                label="Have you ever been convicted of a crime?"
                                error={errors.criminal_declaration?.convicted_of_crime?.message}
                            />
                            <BooleanChoiceField
                                control={control}
                                name="criminal_declaration.evicted_from_property"
                                label="Have you ever been evicted from a property?"
                                error={errors.criminal_declaration?.evicted_from_property?.message}
                            />
                            <BooleanChoiceField
                                control={control}
                                name="criminal_declaration.ongoing_tenancy_litigation"
                                label="Are you involved in on-going tenancy litigation?"
                                error={errors.criminal_declaration?.ongoing_tenancy_litigation?.message}
                            />
                            <BooleanChoiceField
                                control={control}
                                name="criminal_declaration.rent_arrears_history"
                                label="Any rent arrears history?"
                                error={errors.criminal_declaration?.rent_arrears_history?.message}
                            />
                            <BooleanChoiceField
                                control={control}
                                name="criminal_declaration.legal_dispute_with_landlords"
                                label="Any legal dispute with landlords?"
                                error={errors.criminal_declaration?.legal_dispute_with_landlords?.message}
                            />
                        </div>
                    </SectionCard>

                    {/* 11. Supporting Documents if employed (conditional) */}
                    {employmentStatus && employmentStatus === 'Employed' && (
                        <SectionCard title="Supporting Documents" step={11} activeStep={activeStep} setActiveStep={setActiveStep}>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <FileUploadBox label="Staff ID Card" files={fileMap['staff_id'] || []} onChange={setFilesForKey('staff_id')} />
                                <FileUploadBox label="Pay Slip" files={fileMap['utility_bill'] || []} onChange={setFilesForKey('utility_bill')} />
                                <FileUploadBox label="Bank Statement (6 Months)" files={fileMap['bank_statement_6m'] || []} onChange={setFilesForKey('bank_statement_6m')} />
                                <FileUploadBox label="Government ID (NIN Card or Slip/Driver's License/Passport)" files={fileMap['gov_id'] || []} onChange={setFilesForKey('gov_id')} />
                                <FileUploadBox label="Passport Photo" files={fileMap['passport_photo'] || []} onChange={setFilesForKey('passport_photo')} />
                                <FileUploadBox label="Utility Bill (Proof of Address)" files={fileMap['utility_bill'] || []} onChange={setFilesForKey('utility_bill')} />
                            </div>
                        </SectionCard>
                    )}

                    {/* 11. Supporting Documents if self-employed (conditional) */}
                    {employmentStatus && (employmentStatus === 'Self Employed' || employmentStatus === 'Business Owner') && (
                        <SectionCard title="Supporting Documents" step={11} activeStep={activeStep} setActiveStep={setActiveStep}>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <FileUploadBox label="CAC Registration" files={fileMap['cac_doc'] || []} onChange={setFilesForKey('cac_doc')} />
                                <FileUploadBox label="Tax Clearance" files={fileMap['tax_clearance_doc'] || []} onChange={setFilesForKey('tax_clearance_doc')} />
                                <FileUploadBox label="Bank Statement (6 Months)" files={fileMap['bank_statement_6m'] || []} onChange={setFilesForKey('bank_statement_6m')} />
                                <FileUploadBox label="Government ID (NIN Card or Slip/Driver's License/Passport)" files={fileMap['gov_id'] || []} onChange={setFilesForKey('gov_id')} />
                                <FileUploadBox label="Passport Photo" files={fileMap['passport_photo'] || []} onChange={setFilesForKey('passport_photo')} />
                                <FileUploadBox label="Utility Bill (Proof of Address)" files={fileMap['utility_bill'] || []} onChange={setFilesForKey('utility_bill')} />
                            </div>
                        </SectionCard>
                    )}

                    {/* 11. Supporting Documents if student (conditional) */}
                    {employmentStatus && (employmentStatus === 'Freelancer' || employmentStatus === 'Retired' || employmentStatus === 'Student') && (
                        <SectionCard title="Supporting Documents" step={11} activeStep={activeStep} setActiveStep={setActiveStep}>
                            <div>
                                <FileUploadBox label="Payment Slip (Freelancer Only)" files={fileMap['payment_slip'] || []} onChange={setFilesForKey('payment_slip')} />
                                <FileUploadBox label="Student ID Card (Student Only)" files={fileMap['student_id'] || []} onChange={setFilesForKey('student_id')} />
                                <FileUploadBox label="Bank Statement (6 Months)" files={fileMap['bank_statement_6m'] || []} onChange={setFilesForKey('bank_statement_6m')} />
                                <FileUploadBox label="Government ID (NIN Card or Slip/Driver's License/Passport)" files={fileMap['gov_id'] || []} onChange={setFilesForKey('gov_id')} />
                                <FileUploadBox label="Passport Photo" files={fileMap['passport_photo'] || []} onChange={setFilesForKey('passport_photo')} />
                                <FileUploadBox label="Utility Bill (Proof of Address)" files={fileMap['utility_bill'] || []} onChange={setFilesForKey('utility_bill')} />
                            </div>
                        </SectionCard>
                    )}

                    {/* Submit */}
                    <div className="flex items-center justify-between pt-6">
                        <button
                            type="button"
                            onClick={() => setActiveStep(Math.max(2, activeStep - 1))}
                            className="rounded-lg bg-gray-100 px-6 py-3 text-sm font-medium text-gray-700 hover:bg-gray-200 transition"
                        >
                            Previous Section
                        </button>
                        <button
                            type="submit"
                            disabled={isSubmitting}
                            className="rounded-lg bg-blue-600 px-8 py-3 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition"
                        >
                            {isSubmitting ? 'Saving...' : 'Save Profile'}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    )
}
