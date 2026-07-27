import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { HiLockClosed, HiShieldCheck } from 'react-icons/hi'

import DashboardBackButton from '@/components/DashboardBackButton'
import { useAuth } from '@/hooks/useAuth'
import { api, resolveMediaUrl } from '@/lib/api'
import { User } from '@/types'

type FieldItem = {
    label: string
    value?: unknown
    multiline?: boolean
}

function asRecord(value: unknown): Record<string, any> {
    if (value && typeof value === 'object' && !Array.isArray(value)) {
        return value as Record<string, any>
    }
    return {}
}

function stringValue(value: unknown): string {
    return String(value || '').trim()
}

function formatValue(value: unknown): string {
    const normalized = stringValue(value)
    return normalized || 'Not provided'
}

function LockedField({ field }: { field: FieldItem }) {
    const commonClassName = 'form-input cursor-not-allowed border-gray-200 bg-gray-100 text-gray-500'

    return (
        <div>
            <label className="form-label">{field.label}</label>
            {field.multiline ? (
                <textarea className={`${commonClassName} min-h-24`} value={formatValue(field.value)} disabled />
            ) : (
                <input className={commonClassName} value={formatValue(field.value)} disabled />
            )}
        </div>
    )
}

function LockedFieldGrid({ fields }: { fields: FieldItem[] }) {
    return (
        <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
            {fields.map((field) => (
                <LockedField key={field.label} field={field} />
            ))}
        </div>
    )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
    return (
        <section className="rounded-xl border border-gray-200 bg-white p-6">
            <h2 className="text-xl font-semibold text-gray-900">{title}</h2>
            <div className="mt-5">{children}</div>
        </section>
    )
}

export default function ProfilePage() {
    const { userId } = useParams()
    const { user } = useAuth()
    const isOwnProfile = String(user?.id || '') === String(userId || '')

    const { data: me, isLoading, isError } = useQuery({
        queryKey: ['users', 'me', 'profile-page'],
        queryFn: async () => (await api.get<User>('/users/me')).data,
    })

    const dashboardPath = me?.role === 'landlord'
        ? `/dashboard/landlord/${me.id}`
        : me?.role === 'tenant'
            ? `/dashboard/tenant/${me.id}`
            : '/'

    if (isLoading) {
        return (
            <div className="container-modern py-8">
                <div className="card p-6 text-gray-600">Loading profile...</div>
            </div>
        )
    }

    if (isError || !me || !isOwnProfile) {
        return (
            <div className="container-modern py-8">
                <div className="card p-6">
                    <h1 className="text-2xl font-bold text-gray-900">Unable to load profile</h1>
                    <p className="mt-2 text-gray-600">Please refresh the page or open your own profile from the dashboard.</p>
                </div>
            </div>
        )
    }

    // if (me.role !== 'landlord') {
    //     return (
    //         <div className="container-modern py-8">
    //             <DashboardBackButton fallbackTo={dashboardPath} />
    //             <div className="card mt-5 p-6">
    //                 <h1 className="text-2xl font-bold text-gray-900">Tenant Profile</h1>
    //                 <p className="mt-2 text-gray-600">Tenant profile details are managed from the tenant profile page.</p>
    //                 <Link to={`/tenants/${me.id}/profile`} className="btn btn-primary mt-5">
    //                     Open Tenant Profile
    //                 </Link>
    //             </div>
    //         </div>
    //     )
    // }

    const profile = asRecord(me.landlord_verification_profile)
    const verificationType = me.landlord_verification_type || ''
    const hasSubmittedProfile = Object.keys(profile).length > 0
    const residentialInformation = asRecord(profile.residential_information)
    const bankingInformation = asRecord(profile.banking_information)
    const corporateBankingInformation = asRecord(profile.corporate_banking_information)

    const lockLabel = hasSubmittedProfile
        ? 'Verification profile submitted and locked'
        : 'Complete verification to populate this profile'

    const individualFields: FieldItem[] = [
        { label: 'First name', value: profile.first_name },
        { label: 'Middle name', value: profile.middle_name },
        { label: 'Last name', value: profile.last_name },
        { label: 'Date of birth', value: profile.date_of_birth },
        { label: 'Country of birth', value: profile.country_of_birth },
        { label: 'State of birth', value: profile.state_of_birth },
        { label: 'Nationality', value: profile.nationality },
        { label: 'State of origin', value: profile.state_of_origin || me.state_of_origin },
        { label: 'LGA of origin', value: profile.lga_of_origin || profile.lga },
        { label: 'Gender', value: profile.gender },
        { label: 'Contact number', value: profile.contact_number || me.mobile },
        { label: 'Email', value: profile.email || me.email },
        { label: 'NIN', value: profile.nin || me.nin_number },
        { label: 'BVN', value: profile.bvn || me.bvn_number },
        { label: 'Bank name', value: profile.bank_name || bankingInformation.bank_name },
        { label: 'Account name', value: profile.account_name || bankingInformation.account_name },
        { label: 'Account number', value: profile.account_number || bankingInformation.account_number },
    ]

    const corporateFields: FieldItem[] = [
        { label: 'Company name', value: profile.company_name },
        { label: 'Business state', value: profile.business_state },
        { label: 'Business city', value: profile.business_city },
        { label: 'Company phone number', value: profile.company_phone_number || me.mobile },
        { label: 'Company email', value: profile.company_email || me.email },
        { label: 'Contact person name', value: profile.contact_person_name },
        { label: 'Contact person position', value: profile.contact_person_position },
        { label: 'CAC registration number', value: profile.cac_registration_number },
        { label: 'CAC registration date', value: profile.cac_registration_date },
        { label: 'Tax identification number', value: profile.tax_identification_number },
        { label: "Director's NIN", value: profile.nin || me.nin_number },
        { label: "Director's BVN", value: profile.bvn || me.bvn_number },
        { label: 'Bank name', value: profile.bank_name || corporateBankingInformation.bank_name },
        { label: 'Account name', value: profile.account_name || corporateBankingInformation.account_name },
        { label: 'Account number', value: profile.account_number || corporateBankingInformation.account_number },
    ]

    return (
        <div className="container-modern py-8">
            <DashboardBackButton fallbackTo={dashboardPath} />

            <div className="mt-5 rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
                <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
                    <div className="flex flex-col gap-5 sm:flex-row sm:items-center">
                        <img
                            src={resolveMediaUrl(me.profile_photo_url)}
                            alt={me.name || 'Landlord'}
                            loading="eager"
                            decoding="async"
                            className="h-28 w-28 rounded-2xl object-cover ring-4 ring-slate-100"
                        />
                        <div>
                            <p className="text-sm font-medium uppercase tracking-[0.2em] text-blue-600">Landlord Profile</p>
                            <h1 className="mt-2 text-3xl font-bold text-gray-900">{me.name}</h1>
                            <p className="mt-2 text-sm text-gray-600">
                                This page mirrors the information submitted on the landlord verification page.
                            </p>
                            <div className="mt-4 flex flex-wrap gap-2">
                                <span className="inline-flex items-center gap-2 rounded-full bg-gray-100 px-3 py-1 text-sm font-medium capitalize text-gray-700">
                                    <HiShieldCheck className="h-4 w-4 text-blue-600" />
                                    {verificationType ? `${verificationType} landlord` : 'Verification not selected'}
                                </span>
                                <span className="inline-flex items-center gap-2 rounded-full bg-amber-100 px-3 py-1 text-sm font-medium text-amber-700">
                                    <HiLockClosed className="h-4 w-4" />
                                    {lockLabel}
                                </span>
                            </div>
                        </div>
                    </div>

                    <Link to="/landlord/verification" className="btn btn-outline">
                        Verification Page
                    </Link>
                </div>
            </div>

            {!hasSubmittedProfile ? (
                <div className="mt-6 rounded-xl border border-amber-200 bg-amber-50 p-6 text-amber-800">
                    Your landlord verification profile has not been submitted yet. Complete landlord verification to populate this locked profile page.
                </div>
            ) : (
                <div className="mt-6 space-y-6">
                    <Section title={verificationType === 'corporate' ? 'Corporate Landlord Verification Details' : 'Individual Landlord Verification Details'}>
                        <LockedFieldGrid fields={verificationType === 'corporate' ? corporateFields : individualFields} />
                    </Section>

                    <Section title={verificationType === 'corporate' ? 'Business Address' : 'Residential Address'}>
                        <LockedField
                            field={{
                                label: verificationType === 'corporate' ? 'Business address' : 'Residential address',
                                value: verificationType === 'corporate'
                                    ? profile.business_address
                                    : profile.residential_address || residentialInformation.address,
                                multiline: true,
                            }}
                        />
                    </Section>

                    <Section title="Verification Status">
                        <LockedFieldGrid
                            fields={[
                                { label: 'Email verification', value: me.email_verified ? 'Verified' : 'Pending' },
                                { label: 'Identity verification', value: me.is_verified ? 'Verified' : 'Awaiting review' },
                                { label: 'Profile lock status', value: 'Locked' },
                            ]}
                        />
                    </Section>
                </div>
            )}
        </div>
    )
}
