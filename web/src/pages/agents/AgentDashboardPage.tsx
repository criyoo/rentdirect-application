import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import {
    HiCash,
    HiCheckCircle,
    HiClipboardList,
    HiClock,
    HiCog,
    HiDocumentDownload,
    HiShieldCheck,
    HiSupport,
    HiUser,
    HiUsers,
    HiChatAlt,
    HiChatAlt2,
} from 'react-icons/hi'

import { useAuth } from '@/hooks/useAuth'
import { useAppPopup } from '@/contexts/AppPopupContext'
import DashboardBackButton from '@/components/DashboardBackButton'
import { api, extractApiErrorMessage, resolveMediaUrl } from '@/lib/api'
import { AgentDashboard, PropertyInspection } from '@/types'
import { formatCurrencyWithSymbol } from '@/utils/currency'
import { downloadInspectionPdf } from '@/lib/inspectionReports'

const AGENT_DASHBOARD_ACTIONS = [
    { to: '/agents/profile', label: 'PIO Profile', Icon: HiUser, colorClass: 'text-emerald-600' },
    { to: '/agents/verification', label: 'Verification', Icon: HiShieldCheck, colorClass: 'text-green-600' },
    { to: '/agents/referrals', label: 'Referrals', Icon: HiUsers, colorClass: 'text-teal-600' },
    { to: '/dashboard/settings', label: 'Settings', Icon: HiCog, colorClass: 'text-green-800' },
    { to: '/feedback', label: 'Feedback', Icon: HiChatAlt2, colorClass: 'text-lime-600' },
    { to: '/support', label: 'Support', Icon: HiSupport, colorClass: 'text-emerald-700' },
    { to: '/support-chat', label: 'Support Chat', Icon: HiChatAlt, colorClass: 'text-teal-700' },
] as const

const INSPECTION_STATUS_LABELS: Record<string, string> = {
    claimed: 'Claimed',
    draft: 'Draft',
    submitted: 'Submitted',
}

export default function AgentDashboardPage() {
    const { user } = useAuth()
    const { alert } = useAppPopup()
    const navigate = useNavigate()
    const queryClient = useQueryClient()

    const { data: dashboard, isLoading } = useQuery({
        queryKey: ['agents', 'dashboard'],
        queryFn: async () => (await api.get<AgentDashboard>('/agents/dashboard')).data,
        enabled: Boolean(user),
    })

    const claimInspection = useMutation({
        mutationFn: async (listingId: string) =>
            (await api.post<PropertyInspection>('/agent-inspections/claim', { listing_id: listingId })).data,
        onSuccess: async (inspection) => {
            await queryClient.invalidateQueries({ queryKey: ['agents', 'dashboard'] })
            await alert('Inspection claimed. Open the checklist to start your inspection.', { title: 'Inspection claimed' })
            navigate(`/agents/inspections/${inspection.id}`)
        },
        onError: async (error) => {
            await alert(extractApiErrorMessage(error, 'Unable to claim this inspection.'), { title: 'Claim failed', variant: 'warning' })
        },
    })

    const profile = dashboard?.profile
    const metrics = dashboard?.metrics
    const isVerified = profile?.verification_status === 'verified'
    const verificationPaymentRequired = Boolean(profile?.verification_payment_required)

    const availableListingIds = new Set((dashboard?.available_inspections || []).map((listing) => listing.id))
    const requestsByListing = new Map(
        (dashboard?.inspection_requests || []).map((request) => [request.listing?.id, request] as const),
    )
    const inactiveRequests = (dashboard?.inspection_requests || []).filter(
        (request) => !availableListingIds.has(request.listing?.id),
    )

    const hoursLeft = (expiresAt?: string) => {
        if (!expiresAt) return null
        const ms = new Date(expiresAt).getTime() - Date.now()
        return ms <= 0 ? 0 : Math.ceil(ms / 3_600_000)
    }

    const verificationBanner = () => {
        if (isVerified) return null
        if (!verificationPaymentRequired) {
            return (
                <div className="mb-8 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-emerald-900">
                    <p className="font-semibold">Verification payment received</p>
                    <p className="text-sm">Complete identity verification to start claiming inspections.</p>
                    <Link to="/agents/verification" className="btn btn-primary mt-3 inline-block px-4 py-2 text-sm">
                        Continue verification
                    </Link>
                </div>
            )
        }
        return (
            <div className="mb-8 rounded-xl border border-amber-200 bg-amber-50 p-4 text-amber-900">
                <p className="font-semibold">PIO verification required</p>
                <p className="text-sm">
                    Complete your profile and the one-time ₦500 identity verification payment to unlock inspections. There is no subscription.
                </p>
                <Link to="/agents/verification" className="btn btn-primary mt-3 inline-block px-4 py-2 text-sm">
                    Complete verification
                </Link>
            </div>
        )
    }

    return (
        <div className="agent-theme min-h-screen bg-gradient-to-br from-emerald-50 via-white to-green-50">
            <div className="container-modern py-8">
                <div className="mb-8">
                    <div className="mb-5">
                        <DashboardBackButton fallbackTo="/" />
                    </div>
                    <div className="mb-6">
                        <h1 className="text-4xl font-bold text-gray-900 mb-2">
                            Welcome back, {profile?.first_name || user?.name || 'Officer'}!
                        </h1>
                        <p className="text-sm text-gray-600">
                            Inspect properties for landlords and earn per completed inspection
                        </p>
                    </div>

                    <div className="grid grid-cols-2 gap-4 mb-8 md:grid-cols-3 lg:grid-cols-6">
                        {AGENT_DASHBOARD_ACTIONS.map(({ to, label, Icon, colorClass }) => (
                            <Link key={label} to={to} className="card p-4 text-center hover:shadow-lg transition-all duration-200 group">
                                <Icon className={`w-6 h-6 ${colorClass} mx-auto mb-2 group-hover:scale-110 transition-transform`} />
                                <span className="text-sm font-medium text-gray-700">{label}</span>
                            </Link>
                        ))}
                        <Link to="/agents/checklist" className="card p-4 text-center hover:shadow-lg transition-all duration-200 group">
                            <HiClipboardList className="w-6 h-6 text-teal-600 mx-auto mb-2 group-hover:scale-110 transition-transform" />
                            <span className="text-sm font-medium text-gray-700">Property Inspection Checklist</span>
                        </Link>
                    </div>
                </div>

                {verificationBanner()}

                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-6 mb-8">
                    <div className="card p-6">
                        <p className="text-sm font-medium text-gray-600">Properties Inspected</p>
                        <p className="mt-3 text-3xl font-bold text-gray-900">{metrics?.properties_inspected ?? 0}</p>
                        <p className="mt-2 text-sm text-gray-500">Submitted inspections</p>
                    </div>
                    <div className="card p-6">
                        <p className="text-sm font-medium text-gray-600">Total Earned</p>
                        <p className="mt-3 text-3xl font-bold text-gray-900">{formatCurrencyWithSymbol(Number(metrics?.total_amount_earned || 0))}</p>
                        <p className="mt-2 text-sm text-gray-500">From submitted inspections</p>
                    </div>
                    <div className="card p-6">
                        <p className="text-sm font-medium text-gray-600">Total Paid Out</p>
                        <p className="mt-3 text-3xl font-bold text-green-600">{formatCurrencyWithSymbol(Number(metrics?.total_amount_paid_out || 0))}</p>
                        <p className="mt-2 text-sm text-gray-500">Completed payouts</p>
                    </div>
                    <div className="card p-6">
                        <p className="text-sm font-medium text-gray-600">Pending Payout</p>
                        <p className="mt-3 text-3xl font-bold text-amber-600">{formatCurrencyWithSymbol(Number(metrics?.pending_payout || 0))}</p>
                        <p className="mt-2 text-sm text-gray-500">Awaiting payout</p>
                    </div>
                </div>

                <div className="mb-12" id="property-inspection-checklist">
                    <div className="flex items-center justify-between mb-6">
                        <h2 className="text-2xl font-bold text-gray-900">Available Inspection Requests</h2>
                    </div>
                    {isLoading ? (
                        <div className="card p-6 text-center text-gray-600">Loading inspection requests…</div>
                    ) : (dashboard?.available_inspections?.length ?? 0) + inactiveRequests.length > 0 ? (
                        <div className="grid gap-4">
                            {dashboard!.available_inspections.map((listing) => {
                                const request = requestsByListing.get(listing.id)
                                const remaining = request ? hoursLeft(request.expires_at) : null
                                return (
                                    <div key={listing.id} className="card p-6">
                                        <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
                                            <Link
                                                to={`/listings/${listing.id}`}
                                                className="block h-28 w-full shrink-0 overflow-hidden rounded-lg bg-gray-100 sm:w-36"
                                            >
                                                <img
                                                    src={resolveMediaUrl(listing.cover_image_url)}
                                                    alt={listing.title}
                                                    loading="lazy"
                                                    decoding="async"
                                                    className="h-full w-full object-cover"
                                                    onError={(event) => {
                                                        event.currentTarget.src = '/placeholder.jpg'
                                                    }}
                                                />
                                            </Link>
                                            <div className="min-w-0 flex-1">
                                                <h3 className="text-lg font-semibold text-gray-900">{listing.title}</h3>
                                                <p className="text-sm text-gray-600">
                                                    {[listing.address, listing.city, listing.state].filter(Boolean).join(', ')}
                                                </p>
                                                <p className="mt-1 text-sm text-gray-500">
                                                    {listing.property_type} • Landlord: {listing.landlord_name || '—'}
                                                </p>
                                                {request && remaining !== null && (
                                                    <p className="mt-1 text-xs font-medium text-amber-700">
                                                        First-come-first-served — accept within {remaining}h
                                                    </p>
                                                )}
                                            </div>
                                            <div className="shrink-0">
                                                <button
                                                    type="button"
                                                    disabled={!isVerified || claimInspection.isPending}
                                                    onClick={() => claimInspection.mutate(listing.id)}
                                                    className="btn btn-primary px-4 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-50"
                                                >
                                                    {claimInspection.isPending ? 'Accepting…' : 'Accept Request'}
                                                </button>
                                                {!isVerified && (
                                                    <p className="mt-2 max-w-[180px] text-xs text-gray-500">
                                                        Verify your account to claim inspections.
                                                    </p>
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                )
                            })}
                            {inactiveRequests.map((request) => {
                                const listing = request.listing
                                const label =
                                    request.status === 'accepted'
                                        ? 'Accepted by you'
                                        : request.status === 'taken'
                                            ? 'Request Accepted'
                                            : 'Request Expired'
                                return (
                                    <div key={request.id} className="card p-6 opacity-60 grayscale">
                                        <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
                                            <div className="block h-28 w-full shrink-0 overflow-hidden rounded-lg bg-gray-100 sm:w-36">
                                                <img
                                                    src={resolveMediaUrl(listing.cover_image_url)}
                                                    alt={listing.title}
                                                    loading="lazy"
                                                    decoding="async"
                                                    className="h-full w-full object-cover"
                                                    onError={(event) => {
                                                        event.currentTarget.src = '/placeholder.jpg'
                                                    }}
                                                />
                                            </div>
                                            <div className="min-w-0 flex-1">
                                                <h3 className="text-lg font-semibold text-gray-900">{listing.title}</h3>
                                                <p className="text-sm text-gray-600">
                                                    {[listing.address, listing.city, listing.state].filter(Boolean).join(', ')}
                                                </p>
                                                <p className="mt-1 text-sm text-gray-500">
                                                    {listing.property_type} • Landlord: {listing.landlord_name || '—'}
                                                </p>
                                            </div>
                                            <div className="shrink-0">
                                                <button
                                                    type="button"
                                                    disabled
                                                    className="btn btn-outline px-4 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-50"
                                                >
                                                    {label}
                                                </button>
                                            </div>
                                        </div>
                                    </div>
                                )
                            })}
                        </div>
                    ) : (
                        <div className="card p-6 text-center text-gray-600">
                            No in-person inspection requests are available right now.
                        </div>
                    )}
                </div>

                <div className="mb-12">
                    <div className="flex items-center justify-between mb-6">
                        <h2 className="text-2xl font-bold text-gray-900">My Inspections & Reports</h2>
                    </div>
                    {(dashboard?.inspections?.length ?? 0) > 0 ? (
                        <div className="grid gap-4">
                            {dashboard!.inspections.map((inspection) => (
                                <div key={inspection.id} className="card p-6">
                                    <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                                        <div className="min-w-0 flex-1">
                                            <div className="flex flex-wrap items-center gap-2">
                                                <h3 className="text-lg font-semibold text-gray-900">{inspection.listing_title}</h3>
                                                <span className={`badge ${inspection.status === 'submitted' ? 'badge-success' : 'badge-warning'}`}>
                                                    {inspection.status_display || INSPECTION_STATUS_LABELS[inspection.status] || inspection.status}
                                                </span>
                                                {inspection.overall_status && (
                                                    <span className="badge badge-primary">{inspection.overall_status.replace(/_/g, ' ')}</span>
                                                )}
                                            </div>
                                            <p className="mt-1 text-sm text-gray-600">
                                                {[inspection.listing_address, inspection.listing_city, inspection.listing_state].filter(Boolean).join(', ')}
                                            </p>
                                            <div className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                                                <div>
                                                    <p className="text-gray-500">Earning</p>
                                                    <p className="font-semibold text-gray-900">{formatCurrencyWithSymbol(Number(inspection.earning_amount || 0))}</p>
                                                </div>
                                                <div>
                                                    <p className="text-gray-500">Payout</p>
                                                    <p className="font-semibold text-gray-900">{inspection.payout_status_display || inspection.payout_status}</p>
                                                </div>
                                                <div>
                                                    <p className="text-gray-500">Claimed</p>
                                                    <p className="font-semibold text-gray-900">{inspection.claimed_at ? new Date(inspection.claimed_at).toLocaleDateString() : '—'}</p>
                                                </div>
                                                <div>
                                                    <p className="text-gray-500">{inspection.submission_deadline ? 'Submit by' : 'Submitted'}</p>
                                                    <p className={`font-semibold ${inspection.submission_deadline && new Date(inspection.submission_deadline).getTime() - Date.now() < 6 * 3_600_000 ? 'text-red-600' : 'text-gray-900'}`}>
                                                        {inspection.submission_deadline
                                                            ? new Date(inspection.submission_deadline).toLocaleString()
                                                            : inspection.submitted_at
                                                                ? new Date(inspection.submitted_at).toLocaleDateString()
                                                                : '—'}
                                                    </p>
                                                </div>
                                            </div>
                                        </div>
                                        <div className="flex shrink-0 flex-wrap gap-2">
                                            <Link
                                                to={`/agents/inspections/${inspection.id}`}
                                                className="btn btn-outline px-4 py-2 text-sm"
                                            >
                                                <HiClipboardList className="mr-1 h-4 w-4" />
                                                {inspection.status === 'submitted' ? 'View Report' : 'Open Checklist'}
                                            </Link>
                                            {inspection.status === 'submitted' && (
                                                <button
                                                    type="button"
                                                    onClick={() => downloadInspectionPdf(inspection.id)}
                                                    className="btn btn-primary px-4 py-2 text-sm"
                                                >
                                                    <HiDocumentDownload className="mr-1 h-4 w-4" />
                                                    Download PDF
                                                </button>
                                            )}
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    ) : (
                        <div className="card p-6 text-center text-gray-600">
                            You have not claimed any inspections yet.
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}
