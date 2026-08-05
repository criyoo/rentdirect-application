import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
    HiCash,
    HiChat,
    HiCheckCircle,
    HiClock,
    HiCog,
    HiDocumentText,
    HiExclamationCircle,
    HiHeart,
    HiHome,
    HiQuestionMarkCircle,
    HiScale,
    HiSearch,
    HiShieldCheck,
    HiStar,
    HiSupport,
    HiUser,
    HiUserGroup,
    HiViewGrid,
} from 'react-icons/hi'

import { useAuth } from '@/hooks/useAuth'
import { useAppPopup } from '@/contexts/AppPopupContext'
import DashboardBackButton from '@/components/DashboardBackButton'
import { api, resolveMediaUrl } from '@/lib/api'
import { Booking, Listing, Payment } from '@/types'
import { formatCurrencyWithSymbol } from '@/utils/currency'

type PaginatedResponse<T> = {
    results?: T[]
}

const PENDING_PAYMENT_CANCEL_MESSAGE = 'Are you sure you want to cancel this payment?'
const DELETE_CANCELLED_BOOKING_MESSAGE = 'Are you sure you want to delete this cancelled rental payment history?'

function getBookingFinancials(booking: Booking) {
    const totalAmount = Number(booking.total_amount || 0)
    const paidAmount = Number(booking.paid_amount || 0)
    const remainingAmount = booking.remaining_amount !== undefined
        ? Number(booking.remaining_amount)
        : Math.max(totalAmount - paidAmount, 0)

    return { totalAmount, paidAmount, remainingAmount }
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

function canDeleteBookingFromHistory(booking: Booking) {
    const paymentStatuses = (booking.payments || []).map((payment) => payment.status)
    const hasCancelledPayment = paymentStatuses.some((status) => status === 'cancelled' || status === 'failed')
    const hasOpenPayment = paymentStatuses.some((status) => status === 'pending' || status === 'processing')
    const hasCompletedPayment = paymentStatuses.some((status) => status === 'completed' || status === 'refund_requested')

    return (
        Number(booking.paid_amount || 0) <= 0
        && !hasOpenPayment
        && !hasCompletedPayment
        && (booking.status === 'cancelled' || hasCancelledPayment)
    )
}

export default function TenantDashboardPage() {
    const { user } = useAuth()
    const queryClient = useQueryClient()
    const { confirm } = useAppPopup()
    const { data: featured } = useQuery({
        queryKey: ['listings', 'featured'],
        queryFn: async () => (await api.get<Listing[]>('/featured/listings')).data
    })
    const { data: bookings = [] } = useQuery({
        queryKey: ['bookings', 'tenant', user?.id],
        enabled: !!user,
        queryFn: async () => normalizeResults((await api.get<Booking[] | PaginatedResponse<Booking>>('/bookings')).data)
    })

    const activeBookings = bookings.filter(booking => !['cancelled', 'completed'].includes(booking.status))
    const totalCommitted = activeBookings.reduce((sum, booking) => sum + getBookingFinancials(booking).totalAmount, 0)
    const totalPaid = activeBookings.reduce((sum, booking) => sum + getBookingFinancials(booking).paidAmount, 0)
    const outstandingBalance = activeBookings.reduce((sum, booking) => sum + getBookingFinancials(booking).remainingAmount, 0)
    const tenantFirstName = user?.name?.trim().split(/\s+/)[0] || 'Tenant'
    const dashboardActions = [
        { to: '/search', label: 'Search', Icon: HiSearch, colorClass: 'text-blue-600' },
        { to: '/favourites', label: 'Favourites', Icon: HiHeart, colorClass: 'text-red-600' },
        { to: '/enquiries', label: 'Enquiries', Icon: HiChat, colorClass: 'text-green-600' },
        { to: '/verify', label: 'Verification', Icon: HiShieldCheck, colorClass: 'text-purple-600' },
        { to: user ? `/tenants/${user.id}/profile` : '#', label: 'Profile', Icon: HiUser, colorClass: 'text-orange-600' },
        { to: '/billing', label: 'Billing', Icon: HiCash, colorClass: 'text-emerald-600' },
        { to: '/complaint', label: 'Complaint', Icon: HiExclamationCircle, colorClass: 'text-red-700' },
        { to: '/support', label: 'Support', Icon: HiSupport, colorClass: 'text-blue-700' },
        { to: '/issues', label: 'Issues', Icon: HiQuestionMarkCircle, colorClass: 'text-amber-600' },
        { to: '/community-chat', label: 'Community Chat', Icon: HiUserGroup, colorClass: 'text-indigo-600' },
        { to: '/feedback', label: 'Feedback', Icon: HiDocumentText, colorClass: 'text-cyan-600' },
        { to: '/dashboard/settings', label: 'Settings', Icon: HiCog, colorClass: 'text-slate-600' },
    ]

    const cancelPayment = useMutation({
        mutationFn: async (paymentId: string) => (await api.post<Payment>(`/payments/${paymentId}/cancel`)).data,
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['bookings', 'tenant', user?.id] })
            queryClient.invalidateQueries({ queryKey: ['bookings'] })
            alert('Payment cancelled.')
        },
        onError: (error: any) => {
            alert(error?.response?.data?.detail || error?.message || 'Unable to cancel payment.')
        },
    })

    const deleteCancelledBooking = useMutation({
        mutationFn: async (bookingId: string) => {
            await api.delete(`/bookings/${bookingId}`)
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['bookings', 'tenant', user?.id] })
            queryClient.invalidateQueries({ queryKey: ['bookings'] })
            alert('Rental payment history deleted.')
        },
        onError: (error: any) => {
            alert(error?.response?.data?.detail || error?.message || 'Unable to delete rental payment history.')
        },
    })

    const handleCancelPayment = async (payment: Payment) => {
        const shouldContinue = await confirm(PENDING_PAYMENT_CANCEL_MESSAGE, {
            title: 'Cancel payment?',
            variant: 'warning',
            cancelLabel: 'Cancel',
            confirmLabel: 'Continue',
        })
        if (shouldContinue) {
            cancelPayment.mutate(payment.id)
        }
    }

    const handleDeleteCancelledBooking = async (booking: Booking) => {
        const shouldContinue = await confirm(DELETE_CANCELLED_BOOKING_MESSAGE, {
            title: 'Delete history?',
            variant: 'warning',
            cancelLabel: 'Cancel',
            confirmLabel: 'Delete',
        })
        if (shouldContinue) {
            deleteCancelledBooking.mutate(booking.id)
        }
    }

    return (
        <div className="min-h-screen bg-gray-50">
            <div className="container-modern py-8">
                <div className="mb-8">
                    <div className="mb-5">
                        <DashboardBackButton fallbackTo="/" />
                    </div>
                    <div className="mb-6 flex items-center justify-between">
                        <div>
                            <h1 className="text-4xl font-bold text-gray-900 mb-2">
                                Welcome back, {tenantFirstName}!
                            </h1>
                            <p className="text-sm text-gray-600">
                                Find your perfect home and manage your rental journey
                            </p>
                        </div>
                        <div className="hidden items-center gap-3 md:flex">
                            {/* <Link to="/enquiries" className="btn btn-primary">
                                <HiChat className="w-10 h-10 mr-1" />
                                Enquiries
                            </Link> */}
                            <div className="w-24 h-20 bg-gradient-to-br from-blue-600 to-purple-600 rounded-2xl flex items-center justify-center shadow-lg">
                                <HiHome className="w-12 h-8 text-white" />
                            </div>
                        </div>
                    </div>

                    <div className="grid grid-cols-2 gap-4 mb-8 md:grid-cols-3 lg:grid-cols-6">
                        {dashboardActions.map(({ to, label, Icon, colorClass }) => (
                            <Link key={label} to={to} className="card p-4 text-center hover:shadow-lg transition-all duration-200 group">
                                <Icon className={`w-6 h-6 ${colorClass} mx-auto mb-2 group-hover:scale-110 transition-transform`} />
                                <span className="text-sm font-medium text-gray-700">{label}</span>
                            </Link>
                        ))}
                    </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-6 mb-8">
                    <div className="card p-6">
                        <p className="text-sm font-medium text-gray-600">Active Rentals</p>
                        <p className="mt-3 text-3xl font-bold text-gray-900">{activeBookings.length}</p>
                        <p className="mt-2 text-sm text-gray-500">Bookings in progress</p>
                    </div>

                    <div className="card p-6">
                        <p className="text-sm font-medium text-gray-600">Total Rent Commitment</p>
                        <p className="mt-3 text-3xl font-bold text-gray-900">{formatCurrencyWithSymbol(totalCommitted)}</p>
                        <p className="mt-2 text-sm text-gray-500">Annual rent (plus fees)</p>
                    </div>

                    <div className="card p-6">
                        <p className="text-sm font-medium text-gray-600">Amount Paid</p>
                        <p className="mt-3 text-3xl font-bold text-green-600">{formatCurrencyWithSymbol(totalPaid)}</p>
                        <p className="mt-2 text-sm text-gray-500">Payments made</p>
                    </div>

                    <div className="card p-6">
                        <p className="text-sm font-medium text-gray-600">Outstanding Balance</p>
                        <p className="mt-3 text-3xl font-bold text-red-600">{formatCurrencyWithSymbol(outstandingBalance)}</p>
                        <p className="mt-2 text-sm text-gray-500">Remaining balance</p>
                    </div>
                </div>

                <div className="mb-12">
                    <div className="flex items-center justify-between mb-6">
                        <h2 className="text-2xl font-bold text-gray-900">Rental Payments History</h2>
                        <Link to="/dashboard/settings" className="btn btn-outline">
                            Manage Settings
                        </Link>
                    </div>

                    {bookings.length > 0 ? (
                        <div className="grid gap-4">
                            {bookings.map((booking) => {
                                const { totalAmount, paidAmount, remainingAmount } = getBookingFinancials(booking)
                                const isSettled = remainingAmount <= 0
                                const pendingPayments = (booking.payments || []).filter((payment) => (
                                    payment.status === 'pending' || payment.status === 'processing'
                                ))
                                const showDeleteButton = canDeleteBookingFromHistory(booking)

                                return (
                                    <div key={booking.id} className="card p-6">
                                        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                                            <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
                                                <Link
                                                    to={`/listings/${booking.listing_id}`}
                                                    className="block h-28 w-full shrink-0 overflow-hidden rounded-lg bg-gray-100 sm:w-36"
                                                >
                                                    <img
                                                        src={resolveMediaUrl(booking.listing_cover_image_url)}
                                                        alt={booking.listing_title || 'Rental property'}
                                                        loading="lazy"
                                                        decoding="async"
                                                        className="h-full w-full object-cover"
                                                        onError={(event) => {
                                                            event.currentTarget.src = '/placeholder.jpg'
                                                        }}
                                                    />
                                                </Link>
                                                <div>
                                                    <div className="flex items-center gap-3">
                                                        <h3 className="text-lg font-semibold text-gray-900">
                                                            {booking.listing_title || 'Rental application'}
                                                        </h3>
                                                        <span className={`badge ${booking.status === 'cancelled' ? 'badge-warning' : 'badge-success'}`}>
                                                            {booking.status}
                                                        </span>
                                                    </div>
                                                    <p className="mt-2 text-sm text-gray-600">
                                                        {[booking.listing_address, booking.listing_city].filter(Boolean).join(', ') || 'Property details available on listing page'}
                                                    </p>
                                                    {booking.rental_progress ? (
                                                        <p className="mt-2 text-sm text-gray-500">
                                                            Rental progress: {booking.rental_progress.progress_percent}% complete
                                                        </p>
                                                    ) : null}
                                                </div>
                                            </div>

                                            <div className="grid gap-3 sm:grid-cols-3 lg:min-w-[420px]">
                                                <div className="rounded-xl bg-gray-50 px-4 py-3">
                                                    <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Total</p>
                                                    <p className="mt-2 text-base font-semibold text-gray-900">{formatCurrencyWithSymbol(totalAmount)}</p>
                                                </div>
                                                <div className="rounded-xl bg-green-50 px-4 py-3">
                                                    <p className="text-xs uppercase tracking-[0.2em] text-green-700">Paid</p>
                                                    <p className="mt-2 text-base font-semibold text-green-700">{formatCurrencyWithSymbol(paidAmount)}</p>
                                                </div>
                                                <div className="rounded-xl bg-red-50 px-4 py-3">
                                                    <p className="text-xs uppercase tracking-[0.2em] text-red-700">Balance</p>
                                                    <p className="mt-2 text-base font-semibold text-red-700">{formatCurrencyWithSymbol(remainingAmount)}</p>
                                                </div>
                                            </div>
                                        </div>

                                        <div className="mt-5 flex flex-wrap gap-3">
                                            <Link to={`/listings/${booking.listing_id}`} className="btn btn-outline">
                                                View Property
                                            </Link>
                                            <Link to={`/rental-progress/${booking.id}`} className="btn btn-outline">
                                                Rental Progress
                                            </Link>
                                            <Link
                                                to={`/rent/${booking.listing_id}`}
                                                className={`btn ${isSettled ? 'btn-secondary' : 'btn-primary'}`}
                                            >
                                                {isSettled ? 'Open Rental Details' : 'Pay Balance'}
                                            </Link>
                                            {showDeleteButton && (
                                                <button
                                                    type="button"
                                                    onClick={() => handleDeleteCancelledBooking(booking)}
                                                    disabled={deleteCancelledBooking.isPending}
                                                    className="btn btn-danger disabled:opacity-50"
                                                >
                                                    {deleteCancelledBooking.isPending ? 'Deleting...' : 'Delete'}
                                                </button>
                                            )}
                                            {pendingPayments.map((payment) => (
                                                <button
                                                    key={payment.id}
                                                    type="button"
                                                    onClick={() => handleCancelPayment(payment)}
                                                    disabled={cancelPayment.isPending}
                                                    className="btn btn-danger disabled:opacity-50"
                                                >
                                                    {cancelPayment.isPending ? 'Cancelling...' : 'Cancel Payment'}
                                                </button>
                                            ))}
                                        </div>
                                    </div>
                                )
                            })}
                        </div>
                    ) : (
                        <div className="card p-10 text-center">
                            <div className="w-16 h-16 bg-gray-100 rounded-full flex items-center justify-center mx-auto mb-4">
                                <HiViewGrid className="w-8 h-8 text-gray-400" />
                            </div>
                            <h3 className="text-lg font-medium text-gray-900 mb-2">No rental payments yet</h3>
                            <p className="text-gray-600 mb-6">Once you book a property, your total amount, payments, and balance will appear here.</p>
                            <Link to="/search" className="btn btn-primary">
                                Browse Properties
                            </Link>
                        </div>
                    )}
                </div>

                <div className="mb-12">
                    <div className="flex items-center justify-between mb-6">
                        <h2 className="text-2xl font-bold text-gray-900">Featured Properties</h2>
                        <Link to="/search" className="btn btn-outline">
                            View All Properties
                        </Link>
                    </div>

                    {featured && featured.length > 0 ? (
                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                            {featured.map((property) => (
                                <div key={property.id} className="card card-hover group">
                                    <div className="relative aspect-[4/3] overflow-hidden">
                                        <img
                                            src={resolveMediaUrl(property.cover_image_url)}
                                            alt={property.title}
                                            loading="lazy"
                                            decoding="async"
                                            className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                                            onError={(e) => {
                                                e.currentTarget.src = '/placeholder.jpg'
                                            }}
                                        />

                                        {property.featured && (
                                            <div className="absolute top-3 left-3">
                                                <span className="badge badge-primary">
                                                    <HiStar className="w-3 h-3 mr-1" />
                                                    Featured
                                                </span>
                                            </div>
                                        )}
                                    </div>
                                    <div className="p-6 text-center">
                                        <h3 className="text-lg font-semibold text-gray-900 mb-2 line-clamp-2 group-hover:text-blue-600 transition-colors duration-200">
                                            {property.title}
                                        </h3>
                                        <p className="text-gray-600 text-sm mb-3">{property.city}, {property.state}</p>
                                        <div className="text-[15px] font-semibold text-blue-600 mb-4">
                                            {formatCurrencyWithSymbol(Number(property.price_per_year))}/year
                                        </div>

                                        <div className="flex items-center justify-center space-x-4 mb-4 text-sm text-gray-600">
                                            <div className="flex items-center space-x-1">
                                                <HiHome className="w-4 h-4" />
                                                <span className="font-medium">{property.bedrooms}</span>
                                                <span>bed</span>
                                            </div>
                                            <div className="flex items-center space-x-1">
                                                <HiViewGrid className="w-4 h-4" />
                                                <span className="font-medium">{property.bathrooms}</span>
                                                <span>bath</span>
                                            </div>
                                        </div>

                                        <Link to={`/listings/${property.id}`} className="btn btn-primary w-full">
                                            View Property
                                        </Link>
                                    </div>
                                </div>
                            ))}
                        </div>
                    ) : (
                        <div className="card p-12 text-center">
                            <div className="w-16 h-16 bg-gray-100 rounded-full flex items-center justify-center mx-auto mb-4">
                                <HiStar className="w-8 h-8 text-gray-400" />
                            </div>
                            <h3 className="text-lg font-medium text-gray-900 mb-2">No featured properties</h3>
                            <p className="text-gray-600 mb-6">Check back soon for amazing properties.</p>
                            <Link to="/search" className="btn btn-primary">
                                Browse All Properties
                            </Link>
                        </div>
                    )}
                </div>

                <div className="max-w-4xl mx-auto">
                    <div className="card p-8 text-center">
                        <div className="mb-6">
                            <div className="w-16 h-16 bg-gradient-to-br from-blue-600 to-purple-600 rounded-2xl flex items-center justify-center mx-auto mb-4">
                                <HiStar className="w-8 h-8 text-white" />
                            </div>
                            <h3 className="text-xl font-bold text-gray-900 mb-2">
                                Benefits for tenant on RentDirect
                            </h3>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                            <div className="text-left">
                                <div className="flex items-start space-x-3">
                                    <div className="w-8 h-8 bg-purple-100 rounded-lg flex items-center justify-center flex-shrink-0 mt-1">
                                        <HiCash className="w-4 h-4 text-purple-600" />
                                    </div>
                                    <div>
                                        <h4 className="text-[16px] font-semibold text-gray-900 mb-1">Lower upfront cost</h4>
                                        <p className="text-xs text-gray-600">Eliminate excessive charges & painful cost for property search and rental</p>
                                    </div>
                                </div>
                            </div>

                            <div className="text-left">
                                <div className="flex items-start space-x-3">
                                    <div className="w-8 h-8 bg-red-100 rounded-lg flex items-center justify-center flex-shrink-0 mt-1">
                                        <HiShieldCheck className="w-4 h-4 text-red-600" />
                                    </div>
                                    <div>
                                        <h4 className="text-[16px] font-semibold text-gray-900 mb-1">Prevent rental fraud</h4>
                                        <p className="text-xs text-gray-600">Get verify landlords and properties and avoid scams</p>
                                    </div>
                                </div>
                            </div>
                            <div className="text-left">
                                <div className="flex items-start space-x-3">
                                    <div className="w-8 h-8 bg-purple-100 rounded-lg flex items-center justify-center flex-shrink-0 mt-1">
                                        <HiHome className="w-4 h-4 text-purple-600" />
                                    </div>
                                    <div>
                                        <h4 className="text-[16px] font-semibold text-gray-900 mb-1">Access to verified listings</h4>
                                        <p className="text-xs text-gray-600">No more browsing fake listings or recycled advertisements, tenants see real properties</p>
                                    </div>
                                </div>
                            </div>

                            <div className="text-left">
                                <div className="flex items-start space-x-3">
                                    <div className="w-8 h-8 bg-red-100 rounded-lg flex items-center justify-center flex-shrink-0 mt-1">
                                        <HiScale className="w-4 h-4 text-red-600" />
                                    </div>
                                    <div>
                                        <h4 className="text-[16px] font-semibold text-gray-900 mb-1">Transparent pricing</h4>
                                        <p className="text-xs text-gray-600">No viewing fees, tenants can clearly see all costs upfront, no surprises after inspection</p>
                                    </div>
                                </div>
                            </div>
                            <div className="text-left">
                                <div className="flex items-start space-x-3">
                                    <div className="w-8 h-8 bg-blue-100 rounded-lg flex items-center justify-center flex-shrink-0 mt-1">
                                        <HiSearch className="w-4 h-4 text-blue-600" />
                                    </div>
                                    <div>
                                        <h4 className="text-[16px] font-semibold text-gray-900 mb-1">Faster transparent house search</h4>
                                        <p className="text-xs text-gray-600">No interaction with multiple agents and you save on transportation cost</p>
                                    </div>
                                </div>
                            </div>

                            <div className="text-left">
                                <div className="flex items-start space-x-3">
                                    <div className="w-8 h-8 bg-green-100 rounded-lg flex items-center justify-center flex-shrink-0 mt-1">
                                        <HiUser className="w-4 h-4 text-green-600" />
                                    </div>
                                    <div>
                                        <h4 className="text-[16px] font-semibold text-gray-900 mb-1">Tenant reputation profile</h4>
                                        <p className="text-xs text-gray-600">Build your reputation as a reliable tenant with verified reviews and references</p>
                                    </div>
                                </div>
                            </div>
                            <div className="text-left">
                                <div className="flex items-start space-x-3">
                                    <div className="w-8 h-8 bg-blue-100 rounded-lg flex items-center justify-center flex-shrink-0 mt-1">
                                        <HiChat className="w-4 h-4 text-blue-600" />
                                    </div>
                                    <div>
                                        <h4 className="text-[16px] font-semibold text-gray-900 mb-1">Direct easier communication</h4>
                                        <p className="text-xs text-gray-600">Connect directly with landlords without intermediaries</p>
                                    </div>
                                </div>
                            </div>

                            <div className="text-left">
                                <div className="flex items-start space-x-3">
                                    <div className="w-8 h-8 bg-green-100 rounded-lg flex items-center justify-center flex-shrink-0 mt-1">
                                        <HiCheckCircle className="w-4 h-4 text-green-600" />
                                    </div>
                                    <div>
                                        <h4 className="text-[16px] font-semibold text-gray-900 mb-1">Verified listings</h4>
                                        <p className="text-xs text-gray-600">All properties are verified and listed by trusted landlords</p>
                                    </div>
                                </div>
                            </div>

                            <div className="text-left">
                                <div className="flex items-start space-x-3">
                                    <div className="w-8 h-8 bg-purple-100 rounded-lg flex items-center justify-center flex-shrink-0 mt-1">
                                        <HiClock className="w-4 h-4 text-purple-600" />
                                    </div>
                                    <div>
                                        <h4 className="text-[16px] font-semibold text-gray-900 mb-1">Fast booking</h4>
                                        <p className="text-xs text-gray-600">Quick and transparent booking process</p>
                                    </div>
                                </div>
                            </div>

                            <div className="text-left">
                                <div className="flex items-start space-x-3">
                                    <div className="w-8 h-8 bg-red-100 rounded-lg flex items-center justify-center flex-shrink-0 mt-1">
                                        <HiHeart className="w-4 h-4 text-red-600" />
                                    </div>
                                    <div>
                                        <h4 className="text-[16px] font-semibold text-gray-900 mb-1">Save favourites</h4>
                                        <p className="text-xs text-gray-600">Save and track your favourite properties</p>
                                    </div>
                                </div>
                            </div>

                            <div className="text-left">
                                <div className="flex items-start space-x-3">
                                    <div className="w-8 h-8 bg-purple-100 rounded-lg flex items-center justify-center flex-shrink-0 mt-1">
                                        <HiScale className="w-4 h-4 text-purple-600" />
                                    </div>
                                    <div>
                                        <h4 className="text-[16px] font-semibold text-gray-900 mb-1">Better dispute resolution</h4>
                                        <p className="text-xs text-gray-600">Platform keps record of agreements, payments, messages, and inventory checks etc.</p>
                                    </div>
                                </div>
                            </div>

                            <div className="text-left">
                                <div className="flex items-start space-x-3">
                                    <div className="w-8 h-8 bg-red-100 rounded-lg flex items-center justify-center flex-shrink-0 mt-1">
                                        <HiDocumentText className="w-4 h-4 text-red-600" />
                                    </div>
                                    <div>
                                        <h4 className="text-[16px] font-semibold text-gray-900 mb-1">Digital rental record</h4>
                                        <p className="text-xs text-gray-600">Tenants have access to digital record of previous rentals, payment history etc useful for future rentals</p>
                                    </div>
                                </div>
                            </div>
                        </div>
                        <br />
                        <br />
                        <p className="text-[14px] text-blue-700">
                            Experience the future of property rental with our innovative platform
                        </p>
                    </div>
                </div>
            </div>
        </div>
    )
}
