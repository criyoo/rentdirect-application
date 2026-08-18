import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import {
    HiBadgeCheck,
    HiCash,
    HiChartBar,
    HiChat,
    HiChatAlt2,
    HiClipboardCheck,
    HiCog,
    HiDocumentText,
    HiEye,
    HiExclamationCircle,
    HiHome,
    HiPencil,
    HiPlus,
    HiQuestionMarkCircle,
    HiShieldCheck,
    HiSpeakerphone,
    HiStar,
    HiSupport,
    HiTrash,
    HiTrendingDown,
    HiUser,
    HiUserGroup,
    HiUsers,
} from 'react-icons/hi'

import { useAuth } from '@/hooks/useAuth'
import { useAppPopup } from '@/contexts/AppPopupContext'
import DashboardBackButton from '@/components/DashboardBackButton'
import { api, resolveMediaUrl } from '@/lib/api'
import { hasBronzeAccess, SubscriptionPaymentRecord } from '@/lib/subscriptions'
import { Booking } from '@/types'
import { formatCurrencyWithSymbol } from '@/utils/currency'

type PaginatedResponse<T> = {
    results?: T[]
}

interface ListingSummary {
    id: string
    title: string
    city: string
    price_per_year: number | string
    cover_image_url?: string
    image_urls?: string[]
    featured?: boolean
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

function getBookingFinancials(booking: Booking) {
    const rentalAmount = booking.landlord_rental_amount !== undefined && booking.landlord_rental_amount !== null
        ? Number(booking.landlord_rental_amount)
        : Number(booking.total_amount || 0)
    const paidAmount = Number(booking.paid_amount || 0)
    const collectedAmount = Number(booking.landlord_collected_amount || 0)
    const expectingAmount = Number(booking.landlord_expecting_payment_amount || 0)
    const remainingAmount = booking.landlord_balance_payment_amount !== undefined && booking.landlord_balance_payment_amount !== null
        ? Number(booking.landlord_balance_payment_amount)
        : Math.max(rentalAmount - Math.min(paidAmount, rentalAmount), 0)

    return { rentalAmount, paidAmount, collectedAmount, expectingAmount, remainingAmount }
}

export default function LandlordDashboardPage() {
    const { userId } = useParams()
    const { user } = useAuth()
    const { confirm } = useAppPopup()
    const qc = useQueryClient()
    const { data: listings = [], isLoading } = useQuery({
        queryKey: ['dashboard', 'landlord', 'listings', userId],
        enabled: !!userId,
        queryFn: async () => (await api.get<ListingSummary[]>(`/dashboard/landlord/${userId}/listings`)).data,
    })
    const { data: bookings = [] } = useQuery({
        queryKey: ['bookings', 'landlord', user?.id],
        enabled: !!user,
        queryFn: async () => normalizeResults((await api.get<Booking[] | PaginatedResponse<Booking>>('/bookings')).data),
    })
    const { data: subscriptionPaymentResponse } = useQuery({
        queryKey: ['subscription-payments', 'landlord-dashboard', user?.id],
        enabled: user?.role === 'landlord',
        queryFn: async () => (await api.get<SubscriptionPaymentRecord[] | PaginatedResponse<SubscriptionPaymentRecord>>('/subscriptions')).data,
    })

    const deleteListing = useMutation({
        mutationFn: async (id: string) => {
            await api.delete(`/listings/${id}`)
        },
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['dashboard', 'landlord', 'listings', userId] })
        },
        onError: (error: any) => {
            alert(error?.response?.data?.detail || 'Failed to delete listing.')
        },
    })

    const rentalStatusClass = "text-[16px] font-bold text-gray-600"
    const totalValue = listings.reduce((sum, listing) => sum + Number(listing.price_per_year || 0), 0)
    const activeBookings = bookings.filter(booking => !['cancelled', 'completed'].includes(booking.status))
    const financialBookings = bookings.filter(booking => booking.status !== 'cancelled')
    const totalCollected = financialBookings.reduce((sum, booking) => sum + getBookingFinancials(booking).collectedAmount, 0)
    const totalExpecting = financialBookings.reduce((sum, booking) => sum + getBookingFinancials(booking).expectingAmount, 0)
    const outstandingBalance = financialBookings.reduce((sum, booking) => sum + getBookingFinancials(booking).remainingAmount, 0)
    const isBronzeLandlord = user?.role === 'landlord' && subscriptionPaymentResponse !== undefined && hasBronzeAccess(subscriptionPaymentResponse)
    const landlordFirstName = user?.name?.trim().split(/\s+/)[0] || 'Landlord'
    const landlordProfileId = userId || user?.id
    const landlordProfilePath = landlordProfileId ? `/landlords/${landlordProfileId}` : '#'
    const dashboardActions = [
        { to: '/landlord/enquiries', label: 'Chat (Enquiries)', Icon: HiChat, colorClass: 'text-green-600' },
        { to: '/landlord/verification', label: 'Verification', Icon: HiShieldCheck, colorClass: 'text-purple-600' },
        { to: landlordProfilePath, label: 'Profile', Icon: HiUser, colorClass: 'text-orange-600' },
        { to: '/billing', label: 'Billing', Icon: HiCash, colorClass: 'text-emerald-600' },
        { to: '/complaint', label: 'Complaint', Icon: HiExclamationCircle, colorClass: 'text-red-700' },
        { to: '/support', label: 'Support', Icon: HiSupport, colorClass: 'text-blue-700' },
        { to: '/issues', label: 'Issues', Icon: HiQuestionMarkCircle, colorClass: 'text-amber-600' },
        { to: '/community-chat', label: 'Community Chat', Icon: HiUserGroup, colorClass: 'text-indigo-600' },
        { to: '/feedback', label: 'Feedback', Icon: HiDocumentText, colorClass: 'text-cyan-600' },
        { to: '/dashboard/settings', label: 'Settings', Icon: HiCog, colorClass: 'text-slate-600' },
        { to: '/dashboard/featured-properties', label: 'Featured', Icon: HiStar, colorClass: 'text-yellow-600' },
        { to: '/listings/new', label: listings.length === 0 ? 'First Listing' : 'Add Listing', Icon: HiPlus, colorClass: 'text-white', isPrimary: true },
    ]

    const handleDelete = async (id: string) => {
        if (!(await confirm('Are you sure you want to delete this listing?'))) return
        deleteListing.mutate(id)
    }

    if (isLoading) {
        return (
            <div className="min-h-screen bg-gray-50 flex items-center justify-center">
                <div className="text-center">
                    <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
                    <p className="text-gray-600">Loading your dashboard...</p>
                </div>
            </div>
        )
    }

    return (
        <div className="min-h-screen bg-gray-50">
            <div className="container-modern py-8">
                <div className="mb-8">
                    <div className="mb-5">
                        <DashboardBackButton fallbackTo="/" />
                    </div>
                    <div className="flex items-center justify-between mb-6">
                        <div>
                            <h1 className="text-4xl font-bold text-gray-900 mb-2">
                                Welcome back, {landlordFirstName}
                            </h1>
                            <p className="text-lg text-gray-600">
                                Manage your properties and track your rental business
                            </p>
                        </div>
                    </div>

                    <div className="grid grid-cols-2 gap-4 mb-8 md:grid-cols-3 lg:grid-cols-6">
                        {dashboardActions.map(({ to, label, Icon, colorClass, isPrimary }) => (
                            <Link
                                key={label}
                                to={to}
                                className={`card p-4 text-center hover:shadow-lg transition-all duration-200 group ${isPrimary ? 'bg-gradient-to-br from-blue-600 to-blue-700 text-white' : ''}`}
                            >
                                <Icon className={`w-6 h-6 ${colorClass} mx-auto mb-2 group-hover:scale-110 transition-transform`} />
                                <span className={`text-sm font-medium ${isPrimary ? '' : 'text-gray-700'}`}>{label}</span>
                            </Link>
                        ))}
                    </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-5 gap-6 mb-8">
                    <div className="card p-6">
                        <p className={rentalStatusClass}>Total Properties</p>
                        <p className="mt-3 text-3xl font-bold text-gray-900">{listings.length}</p>
                        <p className="mt-2 text-sm text-gray-500">Available landlord listings</p>
                    </div>

                    <div className="card p-6">
                        <p className={rentalStatusClass}>Rental Requests</p>
                        <p className="mt-3 text-3xl font-bold text-gray-900">{activeBookings.length}</p>
                        <p className="mt-2 text-sm text-gray-500">Bookings tied to your properties</p>
                    </div>

                    <div className="card p-6">
                        <p className={rentalStatusClass}>Collected Payments</p>
                        <p className="mt-3 text-3xl font-bold text-green-600">{formatCurrencyWithSymbol(totalCollected)}</p>
                        <p className="mt-2 text-sm text-gray-500">Transferred to your bank account</p>
                    </div>

                    <div className="card p-6">
                        <p className={rentalStatusClass}>Expected Payment</p>
                        <p className="mt-3 text-3xl font-bold text-blue-600">{formatCurrencyWithSymbol(totalExpecting)}</p>
                        <p className="mt-2 text-sm text-gray-500">Paid by tenant and awaiting payout</p>
                    </div>

                    <div className="card p-6">
                        <p className={rentalStatusClass}>Balance Payment</p>
                        <p className="mt-3 text-3xl font-bold text-red-600">{formatCurrencyWithSymbol(outstandingBalance)}</p>
                        <p className="mt-2 text-sm text-gray-500">Amount still due</p>
                    </div>
                </div>

                <div className="mb-8">
                    <div className="flex items-center justify-between mb-6">
                        <h2 className="text-2xl font-bold text-gray-900">Tenant Payments</h2>
                        <div className="rounded-xl bg-blue-50 px-4 py-3 text-sm text-blue-700">
                            Portfolio value: <span className="font-semibold">{formatCurrencyWithSymbol(totalValue)}</span>
                        </div>
                    </div>

                    {activeBookings.length > 0 ? (
                        <div className="grid gap-4">
                            {activeBookings.map((booking) => {
                                const { rentalAmount, collectedAmount, expectingAmount, remainingAmount } = getBookingFinancials(booking)

                                return (
                                    <div key={booking.id} className="card p-6">
                                        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                                            <div>
                                                <div className="flex items-center gap-3">
                                                    <h3 className="text-lg font-semibold text-gray-900">
                                                        {booking.listing_title || 'Property booking'}
                                                    </h3>
                                                    <span className={`badge ${remainingAmount <= 0 ? 'badge-success' : 'badge-warning'}`}>
                                                        {remainingAmount <= 0 ? 'Paid in Full' : booking.status}
                                                    </span>
                                                </div>
                                                <p className="mt-2 text-sm text-gray-600">
                                                    {[booking.tenant_name, booking.tenant_email].filter(Boolean).join(' • ') || 'Tenant information available on booking'}
                                                </p>
                                                {booking.rental_progress ? (
                                                    <p className="mt-2 text-sm text-gray-500">
                                                        Rental progress: {booking.rental_progress.progress_percent}% complete
                                                    </p>
                                                ) : null}
                                                {booking.tenant_screening_summary ? (
                                                    <p className="mt-2 text-sm font-medium text-blue-700">
                                                        Tenant screening score: {booking.tenant_screening_summary.overall_score.toFixed(1)}/100
                                                    </p>
                                                ) : null}
                                            </div>

                                            <div className="grid gap-3 sm:grid-cols-2 lg:min-w-[560px] xl:grid-cols-4">
                                                <div className="rounded-xl bg-gray-50 px-4 py-3">
                                                    <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Total</p>
                                                    <p className="mt-2 text-base font-semibold text-gray-900">{formatCurrencyWithSymbol(rentalAmount)}</p>
                                                </div>
                                                <div className="rounded-xl bg-green-50 px-4 py-3">
                                                    <p className="text-xs uppercase tracking-[0.2em] text-green-700">Collected</p>
                                                    <p className="mt-2 text-base font-semibold text-green-700">{formatCurrencyWithSymbol(collectedAmount)}</p>
                                                </div>
                                                <div className="rounded-xl bg-blue-50 px-4 py-3">
                                                    <p className="text-xs uppercase tracking-[0.2em] text-blue-700">Expecting</p>
                                                    <p className="mt-2 text-base font-semibold text-blue-700">{formatCurrencyWithSymbol(expectingAmount)}</p>
                                                </div>
                                                <div className="rounded-xl bg-red-50 px-4 py-3">
                                                    <p className="text-xs uppercase tracking-[0.2em] text-red-700">Balance</p>
                                                    <p className="mt-2 text-base font-semibold text-red-700">{formatCurrencyWithSymbol(remainingAmount)}</p>
                                                </div>
                                            </div>
                                        </div>

                                        {booking.tenant_screening_summary ? (
                                            <div className="mt-5 rounded-2xl border border-blue-100 bg-blue-50/60 p-4">
                                                <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                                                    <div>
                                                        <p className="text-xs uppercase tracking-[0.2em] text-blue-700">Tenant Screening</p>
                                                        <p className="mt-1 text-lg font-semibold text-gray-900">
                                                            Overall score: {booking.tenant_screening_summary.overall_score.toFixed(1)}%
                                                        </p>
                                                    </div>
                                                    {/* <p className="text-sm text-gray-600">
                                                        Category scores only. Raw tenant verification data remains hidden.
                                                    </p> */}
                                                </div>

                                                <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-2">
                                                    {booking.tenant_screening_summary.categories.map((category) => (
                                                        <div key={category.key} className="rounded-xl bg-white px-4 py-1 shadow-sm">
                                                            <p className="text-sm text-gray-900">{category.label}: {category.score}%</p>
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>
                                        ) : null}

                                        <div className="mt-5 flex flex-wrap gap-3">
                                            <Link to={`/listings/${booking.listing_id}`} className="btn btn-outline">
                                                View Property
                                            </Link>
                                            <Link to={`/rental-progress/${booking.id}`} className="btn btn-outline">
                                                Rental Progress
                                            </Link>
                                            <Link to={`/tenants/${booking.tenant_id}/profile`} className="btn btn-outline">
                                                View Tenants Profile
                                            </Link>
                                            {isBronzeLandlord ? (
                                                <button
                                                    type="button"
                                                    onClick={() => alert('Contacting tenants is not available on the Bronze free plan.')}
                                                    className="btn btn-outline"
                                                >
                                                    Upgrade to Message Tenant
                                                </button>
                                            ) : (
                                                <Link to="/landlord/enquiries" className="btn btn-primary">
                                                    Message Tenant
                                                </Link>
                                            )}
                                        </div>
                                    </div>
                                )
                            })}
                        </div>
                    ) : (
                        <div className="card p-10 text-center">
                            <div className="w-16 h-16 bg-gray-100 rounded-full flex items-center justify-center mx-auto mb-4">
                                <HiChat className="w-8 h-8 text-gray-400" />
                            </div>
                            <h3 className="text-lg font-medium text-gray-900 mb-2">No tenant payments yet</h3>
                            <p className="text-gray-600">As tenants reserve your properties, paid amounts and outstanding balances will appear here.</p>
                        </div>
                    )}
                </div>

                <div className="mb-8">
                    <div className="flex items-center justify-between mb-6">
                        <h2 className="text-2xl font-bold text-gray-900">My Properties</h2>
                    </div>

                    {listings.length === 0 ? (
                        <div className="card p-12 text-center">
                            <div className="w-16 h-16 bg-gray-100 rounded-full flex items-center justify-center mx-auto mb-4">
                                <HiHome className="w-8 h-8 text-gray-400" />
                            </div>
                            <h3 className="text-lg font-medium text-gray-900 mb-2">No properties yet</h3>
                            <p className="text-gray-600 mb-6 max-w-md mx-auto">
                                Get started by creating your first property listing. Showcase your properties to potential tenants.
                            </p>
                            <Link to="/listings/new" className="btn btn-primary text-lg px-8 py-3">
                                <HiPlus className="w-5 h-5 mr-2" />
                                Create First Listing
                            </Link>
                        </div>
                    ) : (
                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                            {listings.map((listing) => (
                                <div key={listing.id} className="card card-hover group">
                                    <div className="relative aspect-[4/3] overflow-hidden">
                                        <img
                                            src={resolveMediaUrl(listing.cover_image_url)}
                                            alt={listing.title}
                                            loading="lazy"
                                            decoding="async"
                                            className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                                            onError={(e) => {
                                                e.currentTarget.src = '/placeholder.jpg'
                                            }}
                                        />

                                        {listing.featured && (
                                            <div className="absolute top-3 left-3">
                                                <span className="badge badge-primary">
                                                    <HiStar className="w-3 h-3 mr-1" />
                                                    Featured
                                                </span>
                                            </div>
                                        )}

                                        <div className="absolute top-3 right-3 flex space-x-2">
                                            <Link to={`/listings/${listing.id}`} className="p-2 bg-white/90 backdrop-blur-sm rounded-full shadow-lg hover:bg-white transition-all duration-200">
                                                <HiEye className="w-4 h-4 text-gray-600" />
                                            </Link>
                                            <Link to={`/listings/${listing.id}/edit`} className="p-2 bg-blue-500/90 backdrop-blur-sm rounded-full shadow-lg hover:bg-blue-500 transition-all duration-200">
                                                <HiPencil className="w-4 h-4 text-white" />
                                            </Link>
                                            <button
                                                onClick={() => handleDelete(listing.id)}
                                                disabled={deleteListing.isPending}
                                                className="p-2 bg-red-500/90 backdrop-blur-sm rounded-full shadow-lg hover:bg-red-500 transition-all duration-200 disabled:opacity-60"
                                            >
                                                <HiTrash className="w-4 h-4 text-white" />
                                            </button>
                                        </div>
                                    </div>

                                    <div className="p-6">
                                        <h3 className="text-lg font-semibold text-gray-900 mb-2 line-clamp-2 group-hover:text-blue-600 transition-colors duration-200">
                                            {listing.title}
                                        </h3>
                                        <p className="text-gray-600 text-sm mb-3">{listing.city}</p>
                                        <div className="text-2xl font-bold text-blue-600 mb-4">
                                            {formatCurrencyWithSymbol(Number(listing.price_per_year || 0))}
                                        </div>
                                        <div className="text-sm text-gray-500">per year</div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>

                <div className="max-w-4xl mx-auto">
                    <div className="card p-8 text-center">
                        <div className="mb-6">
                            <div className="w-14 h-14 bg-gradient-to-br from-blue-600 to-purple-600 rounded-2xl flex items-center justify-center mx-auto mb-4">
                                <HiStar className="w-6 h-6 text-white" />
                            </div>
                            <h3 className="text-xl font-bold text-gray-900 mb-2">
                                Benefits for Landlord on RentDirect
                            </h3>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                            <div className="text-left">
                                <div className="flex items-start space-x-3">
                                    <div className="w-8 h-8 bg-blue-100 rounded-lg flex items-center justify-center flex-shrink-0 mt-1">
                                        <HiUserGroup className="w-4 h-4 text-blue-600" />
                                    </div>
                                    <div>
                                        <h4 className="text-[16px] font-semibold text-gray-900 mb-1">Access to Verified Tenants</h4>
                                        <p className="text-sm text-gray-600">Connect directly with verified tenants even before rental discussion commence</p>
                                    </div>
                                </div>
                            </div>

                            <div className="text-left">
                                <div className="flex items-start space-x-3">
                                    <div className="w-8 h-8 bg-green-100 rounded-lg flex items-center justify-center flex-shrink-0 mt-1">
                                        <HiTrendingDown className="w-4 h-4 text-green-600" />
                                    </div>
                                    <div>
                                        <h4 className="text-[16px] font-semibold text-gray-900 mb-1">Lower Vacancy Rates</h4>
                                        <p className="text-sm text-gray-600">Properties are easily viewable by verified quality tenants</p>
                                    </div>
                                </div>
                            </div>

                            <div className="text-left">
                                <div className="flex items-start space-x-3">
                                    <div className="w-8 h-8 bg-blue-100 rounded-lg flex items-center justify-center flex-shrink-0 mt-1">
                                        <HiShieldCheck className="w-4 h-4 text-blue-600" />
                                    </div>
                                    <div>
                                        <h4 className="text-[16px] font-semibold text-gray-900 mb-1">Reduced Tenant Fraud</h4>
                                        <p className="text-sm text-gray-600">Fake identities, employment claims, documents, guarantors are identified before signing any agreements</p>
                                    </div>
                                </div>
                            </div>

                            <div className="text-left">
                                <div className="flex items-start space-x-3">
                                    <div className="w-8 h-8 bg-green-100 rounded-lg flex items-center justify-center flex-shrink-0 mt-1">
                                        <HiChartBar className="w-4 h-4 text-green-600" />
                                    </div>
                                    <div>
                                        <h4 className="text-[16px] font-semibold text-gray-900 mb-1">Better tenant matching</h4>
                                        <p className="text-sm text-gray-600">Landlords can see tenants verification score and choose which tenants match their needs</p>
                                    </div>
                                </div>
                            </div>

                            <div className="text-left">
                                <div className="flex items-start space-x-3">
                                    <div className="w-8 h-8 bg-blue-100 rounded-lg flex items-center justify-center flex-shrink-0 mt-1">
                                        <HiChatAlt2 className="w-4 h-4 text-blue-600" />
                                    </div>
                                    <div>
                                        <h4 className="text-[16px] font-semibold text-gray-900 mb-1">Direct Tenant Communication</h4>
                                        <p className="text-sm text-gray-600">Landlords communicate directly with verified potential tenants without any middle man</p>
                                    </div>
                                </div>
                            </div>

                            <div className="text-left">
                                <div className="flex items-start space-x-3">
                                    <div className="w-8 h-8 bg-green-100 rounded-lg flex items-center justify-center flex-shrink-0 mt-1">
                                        <HiCash className="w-4 h-4 text-green-600" />
                                    </div>
                                    <div>
                                        <h4 className="text-[16px] font-semibold text-gray-900 mb-1">Secure and faster rent collection</h4>
                                        <p className="text-sm text-gray-600">Initial payment are made through the platform and support payment tracking, reciepts to reduce payment dispute</p>
                                    </div>
                                </div>
                            </div>

                            <div className="text-left">
                                <div className="flex items-start space-x-3">
                                    <div className="w-8 h-8 bg-blue-100 rounded-lg flex items-center justify-center flex-shrink-0 mt-1">
                                        <HiSpeakerphone className="w-4 h-4 text-blue-600" />
                                    </div>
                                    <div>
                                        <h4 className="text-[16px] font-semibold text-gray-900 mb-1">Property Marketing</h4>
                                        <p className="text-sm text-gray-600">Landlord gain wider audience reach, better property visibility & quality applicant from rentdirect marketing campaigns</p>
                                    </div>
                                </div>
                            </div>

                            <div className="text-left">
                                <div className="flex items-start space-x-3">
                                    <div className="w-8 h-8 bg-green-100 rounded-lg flex items-center justify-center flex-shrink-0 mt-1">
                                        <HiClipboardCheck className="w-4 h-4 text-green-600" />
                                    </div>
                                    <div>
                                        <h4 className="text-[16px] font-semibold text-gray-900 mb-1">Reduced Administrative Work</h4>
                                        <p className="text-sm text-gray-600">Tenantc verification, Payment records, renewal reminders, lease generation etc are automated</p>
                                    </div>
                                </div>
                            </div>

                            <div className="text-left">
                                <div className="flex items-start space-x-3">
                                    <div className="w-8 h-8 bg-blue-100 rounded-lg flex items-center justify-center flex-shrink-0 mt-1">
                                        <HiUsers className="w-4 h-4 text-blue-600" />
                                    </div>
                                    <div>
                                        <h4 className="text-[16px] font-semibold text-gray-900 mb-1">Direct Tenant Access</h4>
                                        <p className="text-sm text-gray-600">Connect directly with verified tenants</p>
                                    </div>
                                </div>
                            </div>

                            <div className="text-left">
                                <div className="flex items-start space-x-3">
                                    <div className="w-8 h-8 bg-green-100 rounded-lg flex items-center justify-center flex-shrink-0 mt-1">
                                        <HiBadgeCheck className="w-4 h-4 text-green-600" />
                                    </div>
                                    <div>
                                        <h4 className="text-[16px] font-semibold text-gray-900 mb-1">Property Verification</h4>
                                        <p className="text-sm text-gray-600">All listings are verified for quality</p>
                                    </div>
                                </div>
                            </div>

                            <div className="text-left">
                                <div className="flex items-start space-x-3">
                                    <div className="w-8 h-8 bg-purple-100 rounded-lg flex items-center justify-center flex-shrink-0 mt-1">
                                        <HiStar className="w-4 h-4 text-purple-600" />
                                    </div>
                                    <div>
                                        <h4 className="text-[16px] font-semibold text-gray-900 mb-1">Featured Listings</h4>
                                        <p className="text-sm text-gray-600">Promote your properties to reach more quality tenants</p>
                                    </div>
                                </div>
                            </div>

                            <div className="text-left">
                                <div className="flex items-start space-x-3">
                                    <div className="w-8 h-8 bg-red-100 rounded-lg flex items-center justify-center flex-shrink-0 mt-1">
                                        <HiCog className="w-4 h-4 text-red-600" />
                                    </div>
                                    <div>
                                        <h4 className="text-[16px] font-semibold text-gray-900 mb-1">Easy Management</h4>
                                        <p className="text-sm text-gray-600">Manage all your properties in one place</p>
                                    </div>
                                </div>
                            </div>
                        </div>
                        <br /><br />
                        <p className="text-[14px] text-blue-600">Get access to quality tenants and grow your rental business with a trusted platform</p>
                    </div>
                </div>
            </div>
        </div>
    )
}
