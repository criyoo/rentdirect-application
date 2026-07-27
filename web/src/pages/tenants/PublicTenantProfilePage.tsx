import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ReactNode } from 'react'
import {
    HiBadgeCheck,
    HiBriefcase,
    HiChartBar,
    HiHome,
    HiLocationMarker,
    HiShieldCheck,
    HiUser,
    HiUsers,
} from 'react-icons/hi'

import { api, resolveMediaUrl } from '@/lib/api'

type PublicTenantProfile = {
    id: string
    name: string
    role: string
    profile_photo_url?: string | null
    state_of_origin?: string
    is_verified?: boolean
    email_verified?: boolean
    tenant_profile?: {
        status?: string
        first_name?: string
        middle_name?: string
        last_name?: string
        age?: number | null
        gender?: string
        nationality?: string
        state_of_origin?: string
        lga?: string
        employment_status?: string
        residence_country?: string
        residence_state?: string
        residence_city?: string
        residence_lga?: string
        length_of_stay?: string
        housing_status?: string
        household_info?: Record<string, any> | null
        social_presence?: Record<string, any> | null
        criminal_declaration?: Record<string, any> | null
    } | null
    metrics?: {
        enquiries_sent?: number
        applications_submitted?: number
        completed_tenancies?: number
        years_on_platform?: number
    }
}

function humanizeKey(key: string): string {
    return key
        .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
        .replace(/[_-]+/g, ' ')
        .replace(/\b\w/g, (char) => char.toUpperCase())
}

function formatValue(value: unknown): string {
    if (value === null || value === undefined || value === '') return 'Not provided'
    if (typeof value === 'boolean') return value ? 'Yes' : 'No'
    if (Array.isArray(value)) return value.length ? value.map(formatValue).join(', ') : 'Not provided'
    return String(value)
}

function DetailCard({ label, value }: { label: string; value: unknown }) {
    return (
        <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3">
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">{label}</p>
            <p className="mt-2 break-words text-sm font-medium text-gray-900">{formatValue(value)}</p>
        </div>
    )
}

function RecordGrid({ value }: { value?: Record<string, any> | null }) {
    const entries = Object.entries(value || {}).filter(([, item]) => item !== null && item !== undefined && item !== '')
    if (!entries.length) return <p className="mt-4 text-sm text-gray-500">No details provided.</p>

    return (
        <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {entries.map(([key, item]) => (
                <DetailCard key={key} label={humanizeKey(key)} value={item} />
            ))}
        </div>
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

export default function PublicTenantProfilePage() {
    const { tenantId } = useParams()

    const { data: profile, isLoading, isError } = useQuery({
        queryKey: ['tenant', 'public-profile', tenantId],
        enabled: !!tenantId,
        queryFn: async () => (await api.get<PublicTenantProfile>(`/users/tenants/${tenantId}/public-profile`)).data,
    })

    if (isLoading) {
        return (
            <div className="container-modern py-8">
                <div className="rounded-xl border bg-white p-6 text-gray-600">Loading tenant profile...</div>
            </div>
        )
    }

    if (isError || !profile) {
        return (
            <div className="container-modern py-8">
                <div className="rounded-xl border bg-white p-6">
                    <h1 className="text-xl font-semibold text-gray-900">Tenant profile unavailable</h1>
                    <p className="mt-2 text-gray-600">Please refresh the page and try again.</p>
                    <Link to="/landlord/enquiries" className="btn btn-outline mt-5">
                        Back to enquiries
                    </Link>
                </div>
            </div>
        )
    }

    const tenantProfile = profile.tenant_profile
    const displayName = tenantProfile
        ? [tenantProfile.first_name, tenantProfile.middle_name, tenantProfile.last_name].filter(Boolean).join(' ')
        : profile.name

    return (
        <div className="container-modern py-8">
            <div className="rounded-xl border border-gray-200 bg-white p-6">
                <div className="flex flex-col gap-6 md:flex-row md:items-center md:justify-between">
                    <div className="flex flex-col gap-5 sm:flex-row sm:items-center">
                        <img
                            src={resolveMediaUrl(profile.profile_photo_url)}
                            alt={displayName || 'Tenant'}
                            loading="eager"
                            decoding="async"
                            className="h-28 w-28 rounded-full object-cover ring-4 ring-slate-100"
                            onError={(event) => {
                                event.currentTarget.src = '/placeholder.jpg'
                            }}
                        />
                        <div>
                            <p className="text-sm font-medium uppercase tracking-[0.2em] text-blue-700">Tenant Profile</p>
                            <h1 className="mt-2 text-3xl font-bold text-gray-900">{displayName || 'Tenant'}</h1>
                            <div className="mt-4 flex flex-wrap gap-2">
                                <span className={profile.is_verified ? 'badge badge-success' : 'badge badge-primary'}>
                                    {profile.is_verified ? 'Verified tenant' : 'Verification pending'}
                                </span>
                                {tenantProfile?.status && <span className="badge badge-primary">{humanizeKey(tenantProfile.status)}</span>}
                            </div>
                        </div>
                    </div>
                    <Link to="/landlord/enquiries" className="btn btn-outline">
                        Back to enquiries
                    </Link>
                </div>
            </div>

            <div className="mt-6 grid gap-4 md:grid-cols-4">
                <DetailCard label="Enquiries Sent" value={profile.metrics?.enquiries_sent ?? 0} />
                <DetailCard label="Applications" value={profile.metrics?.applications_submitted ?? 0} />
                <DetailCard label="Completed Tenancies" value={profile.metrics?.completed_tenancies ?? 0} />
                <DetailCard label="Years On Platform" value={profile.metrics?.years_on_platform ?? 0} />
            </div>

            {!tenantProfile ? (
                <div className="mt-6 rounded-xl border bg-white p-6 text-gray-600">
                    This tenant has not submitted a detailed public profile yet.
                </div>
            ) : (
                <div className="mt-6 space-y-6">
                    <Section title="Personal Summary" icon={<HiUser className="h-5 w-5" />}>
                        <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                            <DetailCard label="Gender" value={tenantProfile.gender} />
                            <DetailCard label="Age" value={tenantProfile.age} />
                            <DetailCard label="Nationality" value={tenantProfile.nationality} />
                            <DetailCard label="State of Origin" value={tenantProfile.state_of_origin || profile.state_of_origin} />
                            <DetailCard label="LGA" value={tenantProfile.lga} />
                            <DetailCard label="Employment Status" value={tenantProfile.employment_status} />
                            <DetailCard label="Profile Status" value={tenantProfile.status} />
                        </div>
                    </Section>

                    <Section title="Residence Summary" icon={<HiLocationMarker className="h-5 w-5" />}>
                        <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                            <DetailCard label="Country" value={tenantProfile.residence_country} />
                            <DetailCard label="State" value={tenantProfile.residence_state} />
                            <DetailCard label="City" value={tenantProfile.residence_city} />
                            <DetailCard label="LGA" value={tenantProfile.residence_lga} />
                            <DetailCard label="Length of Stay" value={tenantProfile.length_of_stay} />
                            <DetailCard label="Housing Status" value={tenantProfile.housing_status} />
                        </div>
                    </Section>

                    <Section title="Screening Signals" icon={<HiChartBar className="h-5 w-5" />}>
                        <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                            <DetailCard label="Identity" value={profile.is_verified ? 'Verified' : 'Pending'} />
                            <DetailCard label="Email" value={profile.email_verified ? 'Verified' : 'Pending'} />
                            <DetailCard label="Profile" value={tenantProfile.status || 'Not submitted'} />
                        </div>
                    </Section>

                    <Section title="Household" icon={<HiUsers className="h-5 w-5" />}>
                        <RecordGrid value={tenantProfile.household_info} />
                    </Section>

                    <Section title="Declarations" icon={<HiShieldCheck className="h-5 w-5" />}>
                        <RecordGrid value={tenantProfile.criminal_declaration} />
                    </Section>

                    <Section title="Social Presence" icon={<HiBadgeCheck className="h-5 w-5" />}>
                        <RecordGrid value={tenantProfile.social_presence} />
                    </Section>

                    <Section title="Employment" icon={<HiBriefcase className="h-5 w-5" />}>
                        <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                            <DetailCard label="Employment Status" value={tenantProfile.employment_status} />
                            <DetailCard label="Housing Status" value={tenantProfile.housing_status} />
                            <DetailCard label="Residence City" value={tenantProfile.residence_city} />
                        </div>
                    </Section>

                    <Section title="Current Housing" icon={<HiHome className="h-5 w-5" />}>
                        <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                            <DetailCard label="Housing Status" value={tenantProfile.housing_status} />
                            <DetailCard label="Length of Stay" value={tenantProfile.length_of_stay} />
                            <DetailCard label="Residence State" value={tenantProfile.residence_state} />
                        </div>
                    </Section>
                </div>
            )}
        </div>
    )
}
