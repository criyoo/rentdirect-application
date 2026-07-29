import { ReactNode } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
    HiArrowLeft,
    HiBadgeCheck,
    HiBriefcase,
    HiCurrencyDollar,
    HiHome,
    HiIdentification,
    HiLocationMarker,
    HiMail,
    HiPhone,
    HiShieldCheck,
    HiUser,
    HiUsers,
} from 'react-icons/hi'

import TenantProfileDetailsForm from '@/components/TenantProfileDetailsForm'
import { useAuth } from '@/hooks/useAuth'
import { api, resolveMediaUrl } from '@/lib/api'
import { TenantProfileSummary } from '@/types'

type DetailItem = {
    label: string
    value?: unknown
    className?: string
}

function humanizeKey(key: string): string {
    return key
        .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
        .replace(/[_-]+/g, ' ')
        .replace(/\b\w/g, (char) => char.toUpperCase())
}

function formatValue(value: unknown): string {
    if (value === null || value === undefined || value === '') {
        return 'Not provided'
    }
    if (typeof value === 'boolean') {
        return value ? 'Yes' : 'No'
    }
    if (Array.isArray(value)) {
        return value.length ? value.map(formatValue).join(', ') : 'Not provided'
    }
    return String(value)
}

function calculateAge(dateOfBirth?: string): number | undefined {
    if (!dateOfBirth) {
        return undefined
    }

    const birthDate = new Date(dateOfBirth)
    if (Number.isNaN(birthDate.getTime())) {
        return undefined
    }

    const today = new Date()
    let age = today.getFullYear() - birthDate.getFullYear()
    const birthdayThisYearPassed = (
        today.getMonth() > birthDate.getMonth()
        || (today.getMonth() === birthDate.getMonth() && today.getDate() >= birthDate.getDate())
    )

    if (!birthdayThisYearPassed) {
        age -= 1
    }

    return age >= 0 ? age : undefined
}

function currentResidenceMoveInDateIsAtLeastFiveYears(value?: unknown): boolean {
    const rawValue = String(value || '').trim()
    if (!/^\d{4}-\d{2}-\d{2}$/.test(rawValue)) {
        return false
    }

    const moveInDate = new Date(`${rawValue}T00:00:00`)
    if (Number.isNaN(moveInDate.getTime())) {
        return false
    }

    const threshold = new Date()
    threshold.setHours(0, 0, 0, 0)
    threshold.setFullYear(threshold.getFullYear() - 5)
    return moveInDate <= threshold
}

function isEmptyValue(value: unknown): boolean {
    return value === null || value === undefined || value === '' || (Array.isArray(value) && value.length === 0)
}

function DetailCard({ item }: { item: DetailItem }) {
    return (
        <div className={`rounded-lg border border-gray-200 bg-gray-50 px-4 py-3 ${item.className || ''}`}>
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">{item.label}</p>
            <p data-detail-value className="mt-2 break-words text-sm font-medium text-gray-900">{formatValue(item.value)}</p>
        </div>
    )
}

function DetailGrid({ items }: { items: DetailItem[] }) {
    return (
        <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {items.map((item) => (
                <DetailCard key={item.label} item={item} />
            ))}
        </div>
    )
}

function RecordGrid({ value }: { value?: Record<string, any> | null }) {
    const entries = Object.entries(value || {}).filter(([, item]) => !isEmptyValue(item))

    if (entries.length === 0) {
        return <p className="mt-4 text-sm text-gray-500">No details provided.</p>
    }

    return (
        <DetailGrid
            items={entries.map(([key, item]) => ({
                label: humanizeKey(key),
                value: item,
            }))}
        />
    )
}

function getRecordValue(value: Record<string, any>, keys: string[]): unknown {
    for (const key of keys) {
        if (!isEmptyValue(value[key])) {
            return value[key]
        }
    }

    return undefined
}

function EmploymentGrid({ value }: { value?: Record<string, any> | null }) {
    const employmentInfo = value || {}
    const hasDetails = Object.values(employmentInfo).some((item) => !isEmptyValue(item))

    if (!hasDetails) {
        return <p className="mt-4 text-sm text-gray-500">No details provided.</p>
    }

    const rows: DetailItem[][] = [
        [
            { label: 'Company Name', value: getRecordValue(employmentInfo, ['company_name', 'employer_name']) },
            { label: 'Company Contact Number', value: getRecordValue(employmentInfo, ['company_contact_number', 'company_phone_number']) },
        ],
        [
            { label: 'Company Address', value: getRecordValue(employmentInfo, ['company_address', 'work_address', 'business_address']) },
            { label: 'Company Website', value: getRecordValue(employmentInfo, ['company_website', 'business_website']) },
        ],
        [
            { label: 'Employment Type', value: employmentInfo.employment_type },
            { label: 'Employment Start Date', value: employmentInfo.employment_start_date },
            { label: 'Position Job Title', value: getRecordValue(employmentInfo, ['position_job_title', 'job_title']) },
        ],
        [
            { label: 'Hr Contact Name', value: employmentInfo.hr_contact_name },
            { label: 'Hr Contact Phone', value: getRecordValue(employmentInfo, ['hr_contact_phone', 'hr_contact_number', 'hr_phone']) },
            { label: 'Hr Email', value: getRecordValue(employmentInfo, ['hr_email', 'hr_contact_email', 'hr_contact_mail']) },
        ],
    ]

    return (
        <div className="mt-5 space-y-3">
            {rows.map((row, index) => (
                <div key={index} className={`grid gap-3 ${row.length === 2 ? 'md:grid-cols-2' : 'md:grid-cols-2 xl:grid-cols-3'}`}>
                    {row.map((item) => (
                        <DetailCard key={item.label} item={item} />
                    ))}
                </div>
            ))}
        </div>
    )
}

function FinancialGrid({ value }: { value?: Record<string, any> | null }) {
    const financialInfo = value || {}
    const hasDetails = Object.values(financialInfo).some((item) => !isEmptyValue(item))

    if (!hasDetails) {
        return <p className="mt-4 text-sm text-gray-500">No details provided.</p>
    }

    const rows: DetailItem[][] = [
        [
            { label: 'Monthly Income Amount', value: financialInfo.monthly_income_amount },
            { label: 'Monthly Expenses', value: financialInfo.monthly_expenses },
        ],
        [
            { label: 'Current Rent Amount', value: financialInfo.current_rent_amount },
            { label: 'Current Service Charge', value: financialInfo.current_service_charge },
        ],
        [
            { label: 'Credit Commitment', value: financialInfo.credit_commitment },
            { label: 'Outstanding Loans', value: financialInfo.outstanding_loans },
        ],
    ]

    return (
        <div className="mt-5 space-y-3">
            {rows.map((row, index) => (
                <div key={index} className="grid gap-3 md:grid-cols-2">
                    {row.map((item) => (
                        <DetailCard key={item.label} item={item} />
                    ))}
                </div>
            ))}
        </div>
    )
}

function GuarantorGrid({ value }: { value?: Record<string, any> | null }) {
    const guarantorDetails = value || {}
    const hasDetails = Object.values(guarantorDetails).some((item) => !isEmptyValue(item))

    if (!hasDetails) {
        return <p className="mt-4 text-sm text-gray-500">No details provided.</p>
    }

    const rows: DetailItem[][] = [
        [
            { label: 'Full Name', value: guarantorDetails.full_name },
            { label: 'Mobile Number', value: guarantorDetails.mobile_number },
            { label: 'Email', value: guarantorDetails.email },
        ],
        [
            { label: 'Occupation', value: guarantorDetails.occupation },
            { label: 'Employer', value: guarantorDetails.employer },
            { label: 'Relationship', value: guarantorDetails.relationship },
        ],
    ]

    return (
        <div className="mt-5 space-y-3">
            {rows.map((row, index) => (
                <div key={index} className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                    {row.map((item) => (
                        <DetailCard key={item.label} item={item} />
                    ))}
                </div>
            ))}
            <DetailCard item={{ label: 'Residential Address', value: guarantorDetails.residential_address }} />
        </div>
    )
}

function LandlordInfoGrid({ value }: { value?: Record<string, any> | null }) {
    const landlordInfo = value || {}
    const rows: DetailItem[][] = [
        [
            { label: 'Name', value: getRecordValue(landlordInfo, ['name', 'full_name']) },
            { label: 'Email', value: landlordInfo.email },
            { label: 'Mobile', value: getRecordValue(landlordInfo, ['mobile', 'mobile_number', 'phone', 'phone_number']) },
        ],
        [
            { label: 'Property Manager Name', value: landlordInfo.property_manager_name },
            {
                label: 'Property Manager Phone',
                value: getRecordValue(landlordInfo, ['property_manager_phone', 'property_manager_mobile', 'property_manager_phone_number']),
            },
            { label: 'Property Manager Email', value: landlordInfo.property_manager_email },
        ],
    ]
    const fullWidthItems: DetailItem[] = [
        { label: 'Address', value: landlordInfo.address },
        { label: 'Property Manager Address', value: landlordInfo.property_manager_address },
    ]
    const hasDetails = [...rows.flat(), ...fullWidthItems].some((item) => !isEmptyValue(item.value))

    if (!hasDetails) {
        return <p className="mt-4 text-sm text-gray-500">No details provided.</p>
    }

    return (
        <div className="mt-5 space-y-3">
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {rows[0].map((item) => (
                    <DetailCard key={item.label} item={item} />
                ))}
            </div>
            <DetailCard item={fullWidthItems[0]} />
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {rows[1].map((item) => (
                    <DetailCard key={item.label} item={item} />
                ))}
            </div>
            <DetailCard item={fullWidthItems[1]} />
        </div>
    )
}

function tenantProfileNeedsDetails(profile?: TenantProfileSummary['tenant_profile'] | null): boolean {
    if (!profile) {
        return true
    }

    const financialInfo = profile.financial_info || {}
    const householdInfo = profile.household_info || {}
    const criminalDeclaration = profile.criminal_declaration || {}

    const hasMissingDetails = [
        profile.residence_country,
        profile.residence_state,
        profile.residence_city,
        profile.residence_lga,
        profile.residence_address,
        profile.length_of_stay,
        profile.housing_status,
        financialInfo.current_rent_amount,
        financialInfo.current_move_in_date,
        financialInfo.expected_move_out_date,
        financialInfo.reason_for_wanting_to_leave,
        householdInfo.marital_status,
        householdInfo.has_pets,
        householdInfo.work_from_home,
        householdInfo.commercial_activities_at_home,
        householdInfo.has_smokers,
        criminalDeclaration.convicted_of_crime,
        criminalDeclaration.evicted_from_property,
        criminalDeclaration.ongoing_tenancy_litigation,
        criminalDeclaration.rent_arrears_history,
        criminalDeclaration.legal_dispute_with_landlords,
    ].some(isEmptyValue)

    return hasMissingDetails || (
        !currentResidenceMoveInDateIsAtLeastFiveYears(financialInfo.current_move_in_date)
        && isEmptyValue(profile.rental_history)
    )
}

function Section({ title, icon, children }: { title: string; icon: ReactNode; children: ReactNode }) {
    return (
        <section className="rounded-xl border border-gray-200 bg-white p-6">
            <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
                    {icon}
                </div>
                <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
            </div>
            {children}
        </section>
    )
}

export default function TenantProfilePage() {
    const { tenantId } = useParams()
    const navigate = useNavigate()
    const queryClient = useQueryClient()
    const [searchParams] = useSearchParams()
    const { user } = useAuth()
    const isOwnTenantProfile = user?.role === 'tenant' && String(user.id) === String(tenantId)
    const requestedEditMode = ['1', 'true'].includes(String(searchParams.get('edit') || '').toLowerCase())
    const { data, isLoading, isError, error } = useQuery({
        queryKey: ['tenant-profile', tenantId],
        enabled: Boolean(tenantId) && !(isOwnTenantProfile && requestedEditMode),
        queryFn: async () => (await api.get<TenantProfileSummary>(`/users/tenants/${tenantId}/profile`)).data,
    })
    const profileIsApproved = String(data?.tenant_profile?.status || '').trim().toLowerCase() === 'approved'
    const shouldShowEditForm = isOwnTenantProfile && (
        requestedEditMode
        || (!isLoading && !isError && (
            !data?.profile_photo_url
            || (!profileIsApproved && tenantProfileNeedsDetails(data?.tenant_profile))
        ))
    )

    if (shouldShowEditForm) {
        const profilePath = `/tenants/${tenantId}/profile`

        return (
            <div className="container-modern py-8">
                <div className="mb-6">
                    <button
                        type="button"
                        onClick={() => navigate(-1)}
                        className="inline-flex items-center text-sm font-medium text-blue-700 hover:text-blue-800"
                    >
                        <HiArrowLeft className="mr-2 h-5 w-5" />
                        Back
                    </button>
                </div>
                <TenantProfileDetailsForm
                    onSaved={() => {
                        void queryClient.invalidateQueries({ queryKey: ['tenant-profile', tenantId] })
                        navigate(profilePath, { replace: true })
                    }}
                />
            </div>
        )
    }

    if (isLoading) {
        return (
            <div className="container-modern py-8">
                <div className="rounded-xl border bg-white p-6 text-gray-600">Loading tenant profile...</div>
            </div>
        )
    }

    if (isError || !data) {
        const message = (error as any)?.response?.data?.detail || 'Unable to load tenant profile.'
        return (
            <div className="container-modern py-8">
                <div className="rounded-xl border bg-white p-6">
                    <h1 className="text-xl font-semibold text-gray-900">Tenant profile unavailable</h1>
                    <p className="mt-2 text-gray-600">{message}</p>
                    <Link to="/landlord/enquiries" className="btn btn-outline mt-5">
                        <HiArrowLeft className="mr-2 h-5 w-5" />
                        Back
                    </Link>
                </div>
            </div>
        )
    }

    const profile = data.tenant_profile
    const displayPhoto = resolveMediaUrl(data.profile_photo_url)
    const fullName = profile
        ? [profile.first_name, profile.middle_name, profile.last_name].filter(Boolean).join(' ')
        : data.name
    const financialInfo = profile?.financial_info || {}

    return (
        <div className={`container-modern py-8 ${profileIsApproved ? '[&_p[data-detail-value]]:text-gray-500' : ''}`}>
            <div className="mb-6">
                <button
                    type="button"
                    onClick={() => navigate(-1)}
                    className="inline-flex items-center text-sm font-medium text-blue-700 hover:text-blue-800"
                >
                    <HiArrowLeft className="mr-2 h-5 w-5" />
                    Back
                </button>
            </div>

            <div className="rounded-xl border border-gray-200 bg-white p-6">
                <div className="mx-auto flex max-w-3xl flex-col items-center text-center">
                    <div className="w-full max-w-[220px] rounded-xl border border-gray-200 bg-gray-50 p-2 shadow-sm">
                        <img
                            src={displayPhoto}
                            alt={fullName || 'Tenant'}
                            loading="eager"
                            decoding="async"
                            className="aspect-square w-full rounded-lg object-cover"
                        />
                    </div>
                    <p className="mt-5 text-sm font-semibold uppercase tracking-[0.18em] text-blue-700">Tenant Profile</p>
                    <h1 className="mt-2 text-3xl font-bold text-gray-900">{fullName || 'Tenant'}</h1>
                    <div className="mt-3 flex flex-wrap justify-center gap-2">
                        <span className="badge badge-success">
                            {data.is_verified ? 'Verified tenant' : 'Verification pending'}
                        </span>
                        {profile?.status && <span className="badge badge-primary">{humanizeKey(profile.status)}</span>}
                    </div>
                    <div className="mt-5 grid gap-3 text-sm text-gray-700 sm:grid-cols-2">
                        <span className="inline-flex items-center gap-2">
                            <HiMail className="h-5 w-5 text-gray-400" />
                            {data.email}
                        </span>
                        <span className="inline-flex items-center gap-2">
                            <HiPhone className="h-5 w-5 text-gray-400" />
                            {formatValue(data.mobile)}
                        </span>
                    </div>
                </div>
            </div>

            {!profile ? (
                <div className="mt-6 rounded-xl border bg-white p-6 text-gray-600">
                    This tenant has not submitted a detailed profile yet.
                </div>
            ) : (
                <div className="mt-6 space-y-6">
                    <Section title="Personal Information" icon={<HiUser className="h-5 w-5" />}>
                        <DetailGrid
                            items={[
                                { label: 'Age', value: calculateAge(profile.date_of_birth) },
                                { label: 'Gender', value: profile.gender },
                                { label: 'Nationality', value: profile.nationality },
                                { label: 'State of Origin', value: profile.state_of_origin },
                                { label: 'LGA', value: profile.lga },
                                { label: 'Employment Status', value: profile.employment_status },
                            ]}
                        />
                    </Section>

                    <Section title="Current Residence" icon={<HiLocationMarker className="h-5 w-5" />}>
                        <div className="mt-5 space-y-3">
                            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                                {[
                                    { label: 'Country', value: profile.residence_country },
                                    { label: 'State', value: profile.residence_state },
                                    { label: 'City', value: profile.residence_city },
                                    { label: 'LGA', value: profile.residence_lga },
                                    { label: 'Length of Stay', value: profile.length_of_stay },
                                    { label: 'Housing Status', value: profile.housing_status },
                                ].map((item) => (
                                    <DetailCard key={item.label} item={item} />
                                ))}
                            </div>
                            <DetailCard item={{ label: 'Address', value: profile.residence_address }} />
                            <div className="grid gap-3 md:grid-cols-2">
                                {[
                                    { label: 'Move In Date', value: financialInfo.current_move_in_date },
                                    { label: 'Expected Move Out Date', value: financialInfo.expected_move_out_date },
                                ].map((item) => (
                                    <DetailCard key={item.label} item={item} />
                                ))}
                            </div>
                            <DetailCard item={{ label: 'Reason For Wanting To Leave', value: financialInfo.reason_for_wanting_to_leave }} />
                        </div>
                    </Section>

                    <Section title="Employment" icon={<HiBriefcase className="h-5 w-5" />}>
                        <EmploymentGrid value={profile.employment_info} />
                    </Section>

                    <Section title="Financial Information" icon={<HiCurrencyDollar className="h-5 w-5" />}>
                        <FinancialGrid value={profile.financial_info} />
                    </Section>

                    <Section title="Guarantor Details" icon={<HiBadgeCheck className="h-5 w-5" />}>
                        <GuarantorGrid value={profile.guarantor_details} />
                    </Section>

                    <Section title="Current Landlord" icon={<HiHome className="h-5 w-5" />}>
                        <LandlordInfoGrid value={profile.landlord_info} />
                    </Section>

                    <Section title="Rental History" icon={<HiIdentification className="h-5 w-5" />}>
                        {profile.rental_history?.length ? (
                            <div className="mt-5 grid gap-4">
                                {profile.rental_history.map((history, index) => (
                                    <div key={index} className="rounded-lg border border-gray-200 p-4">
                                        <p className="text-sm font-semibold text-gray-900">Rental {index + 1}</p>
                                        <RecordGrid value={history} />
                                    </div>
                                ))}
                            </div>
                        ) : (
                            <p className="mt-4 text-sm text-gray-500">No rental history provided.</p>
                        )}
                    </Section>

                    <Section title="Household" icon={<HiUsers className="h-5 w-5" />}>
                        <RecordGrid value={profile.household_info} />
                    </Section>

                    <Section title="Declarations" icon={<HiShieldCheck className="h-5 w-5" />}>
                        <RecordGrid value={profile.criminal_declaration} />
                    </Section>
                </div>
            )}
        </div>
    )
}
