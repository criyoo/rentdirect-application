import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import AdminLayout from '@/components/admin/AdminLayout'
import DashboardBackButton from '@/components/DashboardBackButton'
import { api } from '@/lib/api'
import { formatCurrencyWithSymbol } from '@/utils/currency'

interface PioRow {
    id: string
    name: string
    email: string
    verification_status: string
    verification_attempts: number
    verified_at: string | null
    verification_fees_paid: number
    referral_code: string
    referred_by: string | null
    inspection_requests_received: number
    inspection_requests_accepted: number
    inspections_claimed: number
    inspections_draft: number
    inspections_submitted: number
    inspections_total: number
    earnings_total: number
    earnings_paid_out: number
    earnings_pending: number
    referral_count: number
    referral_earnings_total: number
    referral_earnings_paid: number
    referral_earnings_pending: number
    created_at: string
}

interface PioAnalytics {
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
        list: PioRow[]
    }
}

const STATUS_FILTERS = ['all', 'verified', 'pending', 'payment_required', 'incomplete', 'rejected'] as const

function statusBadgeClass(status: string) {
    switch (status) {
        case 'verified':
            return 'bg-emerald-100 text-emerald-700'
        case 'pending':
            return 'bg-amber-100 text-amber-700'
        case 'rejected':
            return 'bg-red-100 text-red-700'
        case 'payment_required':
            return 'bg-blue-100 text-blue-700'
        default:
            return 'bg-gray-100 text-gray-600'
    }
}

function TotalsCard({ label, value, accent }: { label: string; value: string | number; accent?: string }) {
    return (
        <div className="bg-white rounded-xl border shadow-sm p-5">
            <p className="text-sm font-medium text-gray-600">{label}</p>
            <p className={`mt-1 text-2xl font-bold ${accent || 'text-gray-900'}`}>{value}</p>
        </div>
    )
}

export default function AdminPioMetricsPage() {
    const [statusFilter, setStatusFilter] = useState<string>('all')
    const [search, setSearch] = useState('')

    const { data, isLoading } = useQuery({
        queryKey: ['admin', 'analytics'],
        queryFn: async () => (await api.get<PioAnalytics>('/admin/analytics')).data,
        refetchInterval: 30000,
    })

    const totals = data?.pios?.totals
    const pios = (data?.pios?.list || []).filter((pio) => {
        if (statusFilter !== 'all' && pio.verification_status !== statusFilter) return false
        const needle = search.trim().toLowerCase()
        if (!needle) return true
        return pio.name.toLowerCase().includes(needle) || pio.email.toLowerCase().includes(needle)
    })

    return (
        <AdminLayout>
            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
                <div className="mb-5">
                    <DashboardBackButton to="/admin/dashboard" label="Back to Dashboard" />
                </div>
                <div className="mb-8">
                    <h1 className="text-3xl font-bold text-gray-900">PIO metrics</h1>
                    <p className="text-gray-600 mt-1">Collective and per-officer metrics for Property Inspection Officers.</p>
                </div>

                {isLoading && <p className="text-sm text-gray-500 mb-6">Loading PIO metrics…</p>}

                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4 mb-6">
                    <TotalsCard label="Total PIOs" value={totals?.total ?? 0} accent="text-teal-700" />
                    <TotalsCard label="Verified" value={totals?.verification_status?.verified ?? 0} accent="text-emerald-700" />
                    <TotalsCard label="Pending" value={totals?.verification_status?.pending ?? 0} accent="text-amber-600" />
                    <TotalsCard label="Payment required" value={totals?.verification_status?.payment_required ?? 0} />
                    <TotalsCard label="Incomplete" value={totals?.verification_status?.incomplete ?? 0} />
                    <TotalsCard label="Rejected" value={totals?.verification_status?.rejected ?? 0} accent="text-red-600" />
                </div>

                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4 mb-8">
                    <TotalsCard label="Inspections submitted" value={totals?.inspections?.submitted ?? 0} />
                    <TotalsCard label="Inspections in progress" value={(totals?.inspections?.claimed ?? 0) + (totals?.inspections?.draft ?? 0)} />
                    <TotalsCard label="Requests accepted" value={(totals?.inspection_requests?.accepted ?? 0) + (totals?.inspection_requests?.taken ?? 0)} />
                    <TotalsCard label="Verification fees collected" value={formatCurrencyWithSymbol(totals?.verification_fees_collected ?? 0)} accent="text-purple-700" />
                    <TotalsCard label="Inspection earnings (paid/pending)" value={`${formatCurrencyWithSymbol(totals?.earnings_paid_out ?? 0)} / ${formatCurrencyWithSymbol(totals?.earnings_pending ?? 0)}`} />
                    <TotalsCard label="Referral earnings (paid/pending)" value={`${formatCurrencyWithSymbol(totals?.referral_earnings_paid ?? 0)} / ${formatCurrencyWithSymbol(totals?.referral_earnings_pending ?? 0)}`} />
                </div>

                <div className="bg-white rounded-xl border shadow-sm overflow-hidden">
                    <div className="flex flex-col gap-3 border-b border-gray-200 bg-gray-50 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
                        <h2 className="text-base font-semibold text-gray-900">Per-PIO metrics ({pios.length})</h2>
                        <div className="flex flex-wrap items-center gap-2">
                            <input
                                type="search"
                                value={search}
                                onChange={(event) => setSearch(event.target.value)}
                                placeholder="Search name or email"
                                className="form-input !w-56"
                            />
                            <div className="flex flex-wrap gap-1">
                                {STATUS_FILTERS.map((status) => (
                                    <button
                                        key={status}
                                        type="button"
                                        onClick={() => setStatusFilter(status)}
                                        className={`rounded-md px-2.5 py-1 text-xs font-medium capitalize ${statusFilter === status
                                            ? 'bg-purple-600 text-white'
                                            : 'bg-white text-gray-600 border border-gray-200 hover:bg-purple-50'
                                            }`}
                                    >
                                        {status.replace(/_/g, ' ')}
                                    </button>
                                ))}
                            </div>
                        </div>
                    </div>
                    <div className="overflow-x-auto">
                        <table className="min-w-full divide-y divide-gray-200 text-sm">
                            <thead className="bg-gray-50">
                                <tr>
                                    <th className="px-4 py-3 text-left font-semibold text-gray-600">PIO</th>
                                    <th className="px-4 py-3 text-left font-semibold text-gray-600">Status</th>
                                    <th className="px-4 py-3 text-right font-semibold text-gray-600">Attempts</th>
                                    <th className="px-4 py-3 text-right font-semibold text-gray-600">Requests</th>
                                    <th className="px-4 py-3 text-right font-semibold text-gray-600">Inspections</th>
                                    <th className="px-4 py-3 text-right font-semibold text-gray-600">Submitted</th>
                                    <th className="px-4 py-3 text-right font-semibold text-gray-600">Earnings</th>
                                    <th className="px-4 py-3 text-right font-semibold text-gray-600">Paid out</th>
                                    <th className="px-4 py-3 text-right font-semibold text-gray-600">Pending</th>
                                    <th className="px-4 py-3 text-right font-semibold text-gray-600">Referrals</th>
                                    <th className="px-4 py-3 text-right font-semibold text-gray-600">Referral ₦</th>
                                    <th className="px-4 py-3 text-left font-semibold text-gray-600">Joined</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-100 bg-white">
                                {pios.map((pio) => (
                                    <tr key={pio.id} className="hover:bg-gray-50">
                                        <td className="px-4 py-3">
                                            <p className="font-medium text-gray-900">{pio.name || 'Unnamed PIO'}</p>
                                            <p className="text-xs text-gray-500">{pio.email}</p>
                                        </td>
                                        <td className="px-4 py-3">
                                            <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${statusBadgeClass(pio.verification_status)}`}>
                                                {pio.verification_status.replace(/_/g, ' ')}
                                            </span>
                                        </td>
                                        <td className="px-4 py-3 text-right text-gray-700">{pio.verification_attempts}</td>
                                        <td className="px-4 py-3 text-right text-gray-700">{pio.inspection_requests_accepted}/{pio.inspection_requests_received}</td>
                                        <td className="px-4 py-3 text-right text-gray-700">{pio.inspections_total}</td>
                                        <td className="px-4 py-3 text-right text-gray-700">{pio.inspections_submitted}</td>
                                        <td className="px-4 py-3 text-right text-gray-700">{formatCurrencyWithSymbol(pio.earnings_total)}</td>
                                        <td className="px-4 py-3 text-right text-gray-700">{formatCurrencyWithSymbol(pio.earnings_paid_out)}</td>
                                        <td className="px-4 py-3 text-right text-gray-700">{formatCurrencyWithSymbol(pio.earnings_pending)}</td>
                                        <td className="px-4 py-3 text-right text-gray-700">{pio.referral_count}</td>
                                        <td className="px-4 py-3 text-right text-gray-700">{formatCurrencyWithSymbol(pio.referral_earnings_total)}</td>
                                        <td className="px-4 py-3 text-left text-gray-500">{new Date(pio.created_at).toLocaleDateString()}</td>
                                    </tr>
                                ))}
                                {pios.length === 0 && !isLoading && (
                                    <tr>
                                        <td colSpan={12} className="px-4 py-10 text-center text-sm text-gray-500">
                                            No PIOs match this filter.
                                        </td>
                                    </tr>
                                )}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </AdminLayout>
    )
}
