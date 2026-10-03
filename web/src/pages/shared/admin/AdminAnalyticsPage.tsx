import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import AdminLayout from '@/components/admin/AdminLayout'
import DashboardBackButton from '@/components/DashboardBackButton'
import { api } from '@/lib/api'
import { formatCurrencyWithSymbol } from '@/utils/currency'

interface AdminAnalytics {
    users: {
        total: number
        tenants: number
        landlords: number
        pios: number
        admins: number
        email_verified: number
        frozen: number
    }
    listings: {
        total: number
        by_status: Record<string, number>
        featured_active: number
    }
    bookings: {
        total: number
        by_status: Record<string, number>
        total_paid: number
    }
    verifications: {
        total: number
        by_status: Record<string, number>
        by_role: Record<string, number>
    }
    revenue: {
        pio_verification_fees: number
        tenant_verification_fees: number
        landlord_verification_fees: number
        lawyer_tenancy_fees: number
        in_person_verification_fees: number
        admin_fees: number
        admin_fee_vat: number
        subscription_revenue: number
        subscription_vat: number
        featured_listing_revenue: number
        rent_collected: number
        caution_fee_collected: number
        landlord_rent_paid_out: number
        landlord_rent_pending_payout: number
        total_platform_revenue: number
    }
    pios: {
        totals: {
            total: number
            verification_status: Record<string, number>
            verification_attempts: number
            inspections: Record<string, number>
            inspection_requests: Record<string, number>
            earnings_total: number
            earnings_paid_out: number
            earnings_pending: number
            referral_earnings_total: number
            referral_earnings_paid: number
            referral_earnings_pending: number
            verification_fees_collected: number
        }
        list: unknown[]
    }
    generated_at: string
}

function StatCard({ label, value, accent }: { label: string; value: string | number; accent?: string }) {
    return (
        <div className="bg-white rounded-xl border shadow-sm p-5">
            <p className="text-sm font-medium text-gray-600">{label}</p>
            <p className={`mt-1 text-2xl font-bold ${accent || 'text-gray-900'}`}>{value}</p>
        </div>
    )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
    return (
        <section className="mb-8">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">{title}</h2>
            {children}
        </section>
    )
}

function BreakdownTable({ title, data }: { title: string; data: Record<string, number> }) {
    const entries = Object.entries(data)
    if (!entries.length) {
        return (
            <div className="bg-white rounded-xl border shadow-sm p-5">
                <p className="text-sm font-medium text-gray-600">{title}</p>
                <p className="mt-2 text-sm text-gray-400">No records</p>
            </div>
        )
    }
    return (
        <div className="bg-white rounded-xl border shadow-sm p-5">
            <p className="text-sm font-medium text-gray-600 mb-3">{title}</p>
            <dl className="space-y-2">
                {entries.map(([key, value]) => (
                    <div key={key} className="flex items-center justify-between text-sm">
                        <dt className="capitalize text-gray-600">{key.replace(/_/g, ' ')}</dt>
                        <dd className="font-semibold text-gray-900">{value}</dd>
                    </div>
                ))}
            </dl>
        </div>
    )
}

export default function AdminAnalyticsPage() {
    const { data: analytics, isLoading } = useQuery({
        queryKey: ['admin', 'analytics'],
        queryFn: async () => (await api.get<AdminAnalytics>('/admin/analytics')).data,
        refetchInterval: 30000,
    })

    const revenue = analytics?.revenue
    const pioTotals = analytics?.pios?.totals

    return (
        <AdminLayout>
            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
                <div className="mb-5">
                    <DashboardBackButton to="/admin/dashboard" label="Back to Dashboard" />
                </div>
                <div className="mb-8 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
                    <div>
                        <h1 className="text-3xl font-bold text-gray-900">Analytics</h1>
                        <p className="text-gray-600 mt-1">Platform-wide metrics across users, revenue, listings, bookings and PIOs.</p>
                    </div>
                    {analytics?.generated_at && (
                        <p className="text-xs text-gray-400">
                            Generated {new Date(analytics.generated_at).toLocaleString()}
                        </p>
                    )}
                </div>

                {isLoading && <p className="text-sm text-gray-500 mb-6">Loading analytics…</p>}

                <Section title="Users">
                    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
                        <StatCard label="Total users" value={analytics?.users.total ?? 0} />
                        <StatCard label="Tenants" value={analytics?.users.tenants ?? 0} />
                        <StatCard label="Landlords" value={analytics?.users.landlords ?? 0} />
                        <StatCard label="PIOs" value={analytics?.users.pios ?? 0} accent="text-teal-700" />
                        <StatCard label="Email verified" value={analytics?.users.email_verified ?? 0} />
                        <StatCard label="Frozen accounts" value={analytics?.users.frozen ?? 0} accent="text-red-600" />
                    </div>
                </Section>

                <Section title="Revenue">
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                        <StatCard
                            label="PIO verification fees"
                            value={formatCurrencyWithSymbol(revenue?.pio_verification_fees ?? 0)}
                            accent="text-teal-700"
                        />
                        <StatCard
                            label="Landlord verification fees"
                            value={formatCurrencyWithSymbol(revenue?.landlord_verification_fees ?? 0)}
                            accent="text-orange-700"
                        />
                        <StatCard
                            label="Tenant verification fees"
                            value={formatCurrencyWithSymbol(revenue?.tenant_verification_fees ?? 0)}
                        />
                        <StatCard
                            label="RentDirect admin fee"
                            value={formatCurrencyWithSymbol(revenue?.admin_fees ?? 0)}
                            accent="text-purple-700"
                        />
                        <StatCard
                            label="Admin fee VAT"
                            value={formatCurrencyWithSymbol(revenue?.admin_fee_vat ?? 0)}
                        />
                        <StatCard
                            label="Subscription revenue"
                            value={formatCurrencyWithSymbol(revenue?.subscription_revenue ?? 0)}
                        />
                        <StatCard
                            label="Featured listing revenue"
                            value={formatCurrencyWithSymbol(revenue?.featured_listing_revenue ?? 0)}
                        />
                        <StatCard
                            label="Other service fees"
                            value={formatCurrencyWithSymbol((revenue?.lawyer_tenancy_fees ?? 0) + (revenue?.in_person_verification_fees ?? 0))}
                        />
                    </div>
                    <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                        <StatCard
                            label="Total platform revenue"
                            value={formatCurrencyWithSymbol(revenue?.total_platform_revenue ?? 0)}
                            accent="text-emerald-700"
                        />
                        <StatCard
                            label="Rent collected"
                            value={formatCurrencyWithSymbol(revenue?.rent_collected ?? 0)}
                        />
                        <StatCard
                            label="Caution fees held"
                            value={formatCurrencyWithSymbol(revenue?.caution_fee_collected ?? 0)}
                        />
                        <StatCard
                            label="Landlord payouts (paid / pending)"
                            value={`${formatCurrencyWithSymbol(revenue?.landlord_rent_paid_out ?? 0)} / ${formatCurrencyWithSymbol(revenue?.landlord_rent_pending_payout ?? 0)}`}
                        />
                    </div>
                </Section>

                <Section title="PIOs (Property Inspection Officers)">
                    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
                        <StatCard label="Total PIOs" value={pioTotals?.total ?? 0} accent="text-teal-700" />
                        <StatCard label="Verified PIOs" value={pioTotals?.verification_status?.verified ?? 0} />
                        <StatCard label="Pending PIOs" value={pioTotals?.verification_status?.pending ?? 0} />
                        <StatCard label="Inspections submitted" value={pioTotals?.inspections?.submitted ?? 0} />
                        <StatCard label="Earnings paid out" value={formatCurrencyWithSymbol(pioTotals?.earnings_paid_out ?? 0)} />
                        <StatCard label="Earnings pending" value={formatCurrencyWithSymbol(pioTotals?.earnings_pending ?? 0)} accent="text-amber-600" />
                    </div>
                    <div className="mt-4">
                        <Link to="/admin/pios" className="inline-flex items-center gap-2 text-sm font-medium text-purple-700 hover:text-purple-900">
                            View per-PIO metrics →
                        </Link>
                    </div>
                </Section>

                <Section title="Listings, bookings & verifications">
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                        <StatCard label="Total listings" value={analytics?.listings.total ?? 0} />
                        <StatCard label="Active featured listings" value={analytics?.listings.featured_active ?? 0} />
                        <StatCard label="Total bookings" value={analytics?.bookings.total ?? 0} />
                        <StatCard label="Rent paid on bookings" value={formatCurrencyWithSymbol(analytics?.bookings.total_paid ?? 0)} />
                    </div>
                    <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                        <BreakdownTable title="Listings by status" data={analytics?.listings.by_status || {}} />
                        <BreakdownTable title="Bookings by status" data={analytics?.bookings.by_status || {}} />
                        <BreakdownTable title="Verifications by status" data={analytics?.verifications.by_status || {}} />
                        <BreakdownTable title="Verifications by role" data={analytics?.verifications.by_role || {}} />
                    </div>
                </Section>
            </div>
        </AdminLayout>
    )
}
