import { ReactNode } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
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

import { api, resolveMediaUrl } from '@/lib/api'
import { TenantProfileSummary } from '@/types'

type DetailItem = {
    label: string
    value?: unknown
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

function DetailGrid({ items }: { items: DetailItem[] }) {
    return (
        <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {items.map((item) => (
                <div key={item.label} className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3">
                    <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">{item.label}</p>
                    <p className="mt-2 break-words text-sm font-medium text-gray-900">{formatValue(item.value)}</p>
                </div>
            ))}
        </div>
    )
}

function RecordGrid({ value }: { value?: Record<string, any> | null }) {
    const entries = Object.entries(value || {}).filter(([, item]) => item !== null && item !== undefined && item !== '')

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
    const { data, isLoading, isError, error } = useQuery({
        queryKey: ['tenant-profile', tenantId],
        enabled: Boolean(tenantId),
        queryFn: async () => (await api.get<TenantProfileSummary>(`/users/tenants/${tenantId}/profile`)).data,
    })

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

            <div className="rounded-xl border border-gray-200 bg-white p-6">
                <div className="mx-auto flex max-w-3xl flex-col items-center text-center">
                    <div className="w-full max-w-[220px] rounded-xl border border-gray-200 bg-gray-50 p-2 shadow-sm">
                        <img
                            src={displayPhoto}
                            alt={fullName || 'Tenant'}
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
                                { label: 'Date of Birth', value: profile.date_of_birth },
                                { label: 'Gender', value: profile.gender },
                                { label: 'Nationality', value: profile.nationality },
                                { label: 'State of Origin', value: profile.state_of_origin },
                                { label: 'LGA', value: profile.lga },
                                { label: 'Employment Status', value: profile.employment_status },
                            ]}
                        />
                    </Section>

                    <Section title="Current Residence" icon={<HiLocationMarker className="h-5 w-5" />}>
                        <DetailGrid
                            items={[
                                { label: 'Country', value: profile.residence_country },
                                { label: 'State', value: profile.residence_state },
                                { label: 'City', value: profile.residence_city },
                                { label: 'LGA', value: profile.residence_lga },
                                { label: 'Address', value: profile.residence_address },
                                { label: 'Length of Stay', value: profile.length_of_stay },
                                { label: 'Housing Status', value: profile.housing_status },
                            ]}
                        />
                    </Section>

                    <Section title="Employment" icon={<HiBriefcase className="h-5 w-5" />}>
                        <RecordGrid value={profile.employment_info} />
                    </Section>

                    <Section title="Financial Information" icon={<HiCurrencyDollar className="h-5 w-5" />}>
                        <RecordGrid value={profile.financial_info} />
                    </Section>

                    <Section title="Guarantor Details" icon={<HiBadgeCheck className="h-5 w-5" />}>
                        <RecordGrid value={profile.guarantor_details} />
                    </Section>

                    <Section title="Current Landlord" icon={<HiHome className="h-5 w-5" />}>
                        <RecordGrid value={profile.landlord_info} />
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
