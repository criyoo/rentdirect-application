import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { HiCheckCircle, HiClock } from 'react-icons/hi'
import { Link, useParams } from 'react-router-dom'

import { useAuth } from '@/hooks/useAuth'
import { formatRatePercent, useFinancialConfig } from '@/hooks/useFinancialConfig'
import { api, resolveMediaUrl } from '@/lib/api'
import { nigerianBanks } from '@/lib/banks'
import { hasPlatinumAccess, hasSilverAccess, SubscriptionPaymentRecord } from '@/lib/subscriptions'
import { Booking, RentalProgressStep, TenantRefund } from '@/types'
import { formatCurrencyWithSymbol } from '@/utils/currency'
import DashboardBackButton from '@/components/DashboardBackButton'

function parseErrorMessage(error: any, fallback: string): string {
    if (typeof error?.response?.data === 'string') {
        return error.response.data
    }

    if (error?.response?.data?.detail) {
        return error.response.data.detail
    }

    if (typeof error?.response?.data === 'object') {
        const firstError = Object.values(error.response.data)[0]
        if (Array.isArray(firstError) && firstError[0]) {
            return String(firstError[0])
        }
        if (typeof firstError === 'string') {
            return firstError
        }
    }

    return error?.message || fallback
}

function formatProgressPercent(value: number | undefined): string {
    const numericValue = Number(value || 0)
    return Number.isInteger(numericValue) ? `${numericValue}%` : `${numericValue.toFixed(1)}%`
}

const REFUND_FEE_RATE = 0.01
const REFUND_FEE_CAP_NGN = 50000

function refundFeeFor(amount: number): number {
    return Math.min(amount * REFUND_FEE_RATE, REFUND_FEE_CAP_NGN)
}

function normalizeBankKey(value: string | undefined): string {
    return String(value || '').toLowerCase().replace(/[^a-z0-9]/g, '')
}

const OPEN_REFUND_STATUSES = new Set(['scheduled', 'recipient_created', 'ready', 'processing', 'paid'])

function refundStatusLabel(status: string): string {
    switch (status) {
        case 'scheduled':
            return 'Scheduled'
        case 'recipient_created':
            return 'Preparing payout'
        case 'ready':
            return 'Ready'
        case 'processing':
            return 'Processing'
        case 'paid':
            return 'Paid'
        case 'failed':
            return 'Failed'
        default:
            return status
    }
}

export default function RentalProgressPage() {
    const { bookingId } = useParams()
    const { user } = useAuth()
    const queryClient = useQueryClient()
    const { data: financialConfig } = useFinancialConfig()
    const [selectedStepKeys, setSelectedStepKeys] = useState<string[]>([])
    const [selectedStepResponses, setSelectedStepResponses] = useState<Record<string, string>>({})
    const [showRefundForm, setShowRefundForm] = useState(false)
    const [refundPaymentId, setRefundPaymentId] = useState('')
    const [refundBankName, setRefundBankName] = useState('')
    const [refundAccountNumber, setRefundAccountNumber] = useState('')
    const [refundAccountName, setRefundAccountName] = useState('')
    const [refundReason, setRefundReason] = useState('')

    const { data: subscriptionPaymentResponse, isLoading: isSubscriptionLoading } = useQuery({
        queryKey: ['subscription-payments', 'rental-progress', user?.id],
        queryFn: async () => (await api.get<SubscriptionPaymentRecord[] | { results?: SubscriptionPaymentRecord[] }>('/subscriptions')).data,
        enabled: user?.role === 'tenant',
    })
    const hasRentalProgressAccess = user?.role !== 'tenant'
        || (
            subscriptionPaymentResponse !== undefined
            && hasSilverAccess(subscriptionPaymentResponse)
        )
    const hasPremiumRentalSupport = user?.role === 'tenant' && subscriptionPaymentResponse !== undefined && hasPlatinumAccess(subscriptionPaymentResponse)

    const { data: booking, isLoading, error } = useQuery({
        queryKey: ['rental-progress', bookingId],
        enabled: !!bookingId && hasRentalProgressAccess,
        queryFn: async () => (await api.get<Booking>(`/bookings/${bookingId}/rental-progress`)).data,
    })

    const { data: refunds } = useQuery({
        queryKey: ['booking-refunds', bookingId],
        enabled: !!bookingId && hasRentalProgressAccess && user?.role === 'tenant',
        queryFn: async () => (await api.get<TenantRefund[]>(`/bookings/${bookingId}/refunds`)).data,
    })

    useEffect(() => {
        setSelectedStepKeys([])
        setSelectedStepResponses({})
    }, [booking?.updated_at, bookingId])

    const saveProgress = useMutation({
        mutationFn: async () => {
            if (!bookingId) {
                throw new Error('Rental progress record not found.')
            }

            return (
                await api.patch<Booking>(`/bookings/${bookingId}/rental-progress`, {
                    step_keys: selectedStepKeys,
                    step_responses: selectedStepResponses,
                })
            ).data
        },
        onSuccess: async (updatedBooking) => {
            queryClient.setQueryData(['rental-progress', bookingId], updatedBooking)
            await queryClient.invalidateQueries({ queryKey: ['bookings'] })
        },
        onError: (mutationError: any) => {
            alert(parseErrorMessage(mutationError, 'Failed to save rental progress.'))
        },
    })

    const requestRefund = useMutation({
        mutationFn: async () => {
            if (!bookingId || !refundPaymentId) {
                throw new Error('Select the payment to refund.')
            }
            return (
                await api.post<TenantRefund>(`/bookings/${bookingId}/refunds`, {
                    payment_id: refundPaymentId,
                    bank_name: refundBankName,
                    account_number: refundAccountNumber,
                    account_name: refundAccountName,
                    reason: refundReason,
                })
            ).data
        },
        onSuccess: async () => {
            setShowRefundForm(false)
            setRefundPaymentId('')
            setRefundBankName('')
            setRefundAccountNumber('')
            setRefundAccountName('')
            setRefundReason('')
            await queryClient.invalidateQueries({ queryKey: ['booking-refunds', bookingId] })
            await queryClient.invalidateQueries({ queryKey: ['rental-progress', bookingId] })
            await queryClient.invalidateQueries({ queryKey: ['bookings'] })
        },
        onError: (mutationError: any) => {
            alert(parseErrorMessage(mutationError, 'Failed to request refund.'))
        },
    })

    const stepPrerequisitesSatisfied = (index: number, steps: RentalProgressStep[]) => {
        return steps.slice(0, index).every((previousStep) => previousStep.completed)
    }

    const toggleStep = (stepKey: string, completed: boolean, unlocked: boolean) => {
        if (completed || !unlocked) {
            return
        }

        setSelectedStepKeys((current) => (
            current.includes(stepKey)
                ? current.filter((key) => key !== stepKey)
                : [...current, stepKey]
        ))
    }

    const selectStepResponse = (stepKey: string, value: string, completed: boolean, unlocked: boolean) => {
        if (completed || !unlocked) {
            return
        }

        setSelectedStepResponses((current) => (
            current[stepKey] === value
                ? Object.fromEntries(Object.entries(current).filter(([key]) => key !== stepKey))
                : { ...current, [stepKey]: value }
        ))
    }

    if (user?.role === 'tenant' && isSubscriptionLoading) {
        return (
            <div className="container-modern py-8">
                <div className="rounded-2xl border bg-white p-8 text-gray-600 shadow-sm">Checking rental progress access...</div>
            </div>
        )
    }

    if (!hasRentalProgressAccess) {
        return (
            <div className="container-modern py-8">
                <div className="rounded-2xl border bg-white p-8 shadow-sm">
                    <h1 className="text-2xl font-semibold text-gray-900">Rental Progress</h1>
                    <p className="mt-3 text-gray-600">
                        Rental progress tracking is available with the Silver tenant plan and every higher plan.
                    </p>
                    <div className="mt-6 flex flex-wrap gap-3">
                        <Link to="/billing" className="btn btn-primary">Upgrade Plan</Link>
                        <DashboardBackButton to={`/dashboard/tenant/${user?.id}`} label="Back to dashboard" />
                    </div>
                </div>
            </div>
        )
    }

    if (isLoading) {
        return (
            <div className="container-modern py-8">
                <div className="rounded-2xl border bg-white p-8 text-gray-600 shadow-sm">Loading rental progress...</div>
            </div>
        )
    }

    if (!booking || error) {
        return (
            <div className="container-modern py-8">
                <div className="rounded-2xl border bg-white p-8 shadow-sm">
                    <h1 className="text-2xl font-semibold text-gray-900">Rental Progress</h1>
                    <p className="mt-3 text-gray-600">
                        {parseErrorMessage(error, 'Rental progress details could not be loaded.')}
                    </p>
                    <DashboardBackButton
                        to={user?.role === 'landlord' ? `/dashboard/landlord/${user.id}` : `/dashboard/tenant/${user?.id}`}
                        label="Back to dashboard"
                        className="mt-6"
                    />
                </div>
            </div>
        )
    }

    const progress = booking.rental_progress
    const progressPercent = Number(progress?.progress_percent || 0)
    const steps = progress?.steps || []
    const isLandlord = user?.role === 'landlord'
    const tenantDepositStepIndex = steps.findIndex((step) => step.key === 'tenant_paid_deposit')
    const tenantRentStepIndex = steps.findIndex((step) => step.key === 'tenant_paid_rent_in_full')
    const rentalDepositPaid = Boolean(progress?.rental_deposit_paid)
    const fullRentalAmountPaid = Boolean(progress?.full_rental_amount_paid)
    const dashboardPath = isLandlord ? `/dashboard/landlord/${user?.id}` : `/dashboard/tenant/${user?.id}`

    const refundsList = refunds || []
    const keysHandedOver = Boolean(booking.tenant_key_collection_confirmed || booking.landlord_key_collection_confirmed)
    const refundablePayments = (booking.payments || []).filter(
        (payment) =>
            payment.status === 'completed'
            && !refundsList.some((refund) => refund.payment_id === payment.id && OPEN_REFUND_STATUSES.has(refund.status)),
    )
    const selectedRefundPayment = refundablePayments.find((payment) => payment.id === refundPaymentId)
    const recordedBankName = selectedRefundPayment?.bank_name || ''
    const bankOptions = recordedBankName && nigerianBanks.some((bank) => normalizeBankKey(bank) === normalizeBankKey(recordedBankName))
        ? nigerianBanks.filter((bank) => normalizeBankKey(bank) === normalizeBankKey(recordedBankName))
        : nigerianBanks
    const selectedRefundAmount = Number(selectedRefundPayment?.amount || 0)
    const selectedRefundFee = refundFeeFor(selectedRefundAmount)
    const canRequestRefund = !isLandlord && !keysHandedOver && refundablePayments.length > 0

    return (
        <div className="min-h-screen bg-gray-50">
            <div className="container-modern py-8">
                <div className="mx-auto max-w-6xl">
                    <DashboardBackButton to={dashboardPath} label="Back to dashboard" />

                    <div className="mt-4 grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
                        <div className="overflow-hidden rounded-3xl border bg-white shadow-sm">
                            <div className="grid gap-0 md:grid-cols-[280px_1fr]">
                                <div className="h-full min-h-[240px] bg-gray-100">
                                    <img
                                        src={resolveMediaUrl(booking.listing_cover_image_url)}
                                        alt={booking.listing_title || 'Rental property'}
                                        loading="eager"
                                        decoding="async"
                                        className="h-full w-full object-cover"
                                        onError={(event) => {
                                            event.currentTarget.src = '/placeholder.jpg'
                                        }}
                                    />
                                </div>

                                <div className="p-6">
                                    <p className="text-sm font-medium uppercase tracking-[0.2em] text-blue-600">Rental Progress</p>
                                    <h1 className="mt-3 text-3xl font-bold text-gray-900">
                                        {booking.listing_title || 'Rental property'}
                                    </h1>
                                    <p className="mt-3 text-gray-600">
                                        {[booking.listing_address, booking.listing_city, booking.listing_state].filter(Boolean).join(', ')}
                                    </p>

                                    <div className="mt-6 grid gap-4 sm:grid-cols-2">
                                        <div className="rounded-2xl bg-gray-50 p-4">
                                            <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Landlord</p>
                                            <p className="mt-2 text-base font-semibold text-gray-900">{booking.landlord_name || 'RentDirect Landlord'}</p>
                                        </div>
                                        <div className="rounded-2xl bg-gray-50 p-4">
                                            <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Rental Amount</p>
                                            <p className="mt-2 text-base font-semibold text-gray-900">
                                                {formatCurrencyWithSymbol(Number(booking.total_amount || 0))}
                                            </p>
                                        </div>
                                        <div className="rounded-2xl bg-gray-50 p-4">
                                            <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Booking Status</p>
                                            <p className="mt-2 text-base font-semibold capitalize text-gray-900">{booking.status}</p>
                                        </div>
                                        <div className="rounded-2xl bg-gray-50 p-4">
                                            <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Progress</p>
                                            <p className="mt-2 text-base font-semibold text-gray-900">
                                                {progress?.completed_count || 0} of {progress?.total_count || 0} completed
                                            </p>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <div className="rounded-3xl border bg-white p-6 shadow-sm">
                            <div className="flex items-start justify-between gap-4">
                                <div>
                                    <p className="text-sm font-medium uppercase tracking-[0.2em] text-blue-600">
                                        {isLandlord ? 'Landlord workflow' : 'Tenant workflow'}
                                    </p>
                                    <h2 className="mt-2 text-2xl font-semibold text-gray-900">
                                        {formatProgressPercent(progressPercent)} complete
                                    </h2>
                                </div>
                                <div className="rounded-2xl bg-gray-100 px-4 py-3 text-right">
                                    <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Saved steps</p>
                                    <p className="mt-2 text-lg font-semibold text-gray-900">{progress?.completed_count || 0}</p>
                                </div>
                            </div>

                            {hasPremiumRentalSupport && (
                                <div className="mt-5 rounded-2xl border border-purple-200 bg-purple-50 p-4 text-sm text-purple-900">
                                    Premium rental workflow support is active for your Platinum subscription.
                                </div>
                            )}

                            <div className="mt-6">
                                <div className="h-3 overflow-hidden rounded-full bg-gray-200">
                                    <div
                                        className="h-full rounded-full bg-gradient-to-r from-blue-600 via-sky-500 to-emerald-500 transition-[width] duration-500 ease-out"
                                        style={{ width: `${progressPercent}%` }}
                                    />
                                </div>
                                <p className="mt-3 text-sm text-gray-600">
                                    Progress bar of number of rental steps completed.
                                </p>
                            </div>
                        </div>
                    </div>

                    <div className="mt-8 rounded-3xl border bg-white p-6 shadow-sm">
                        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                            <div>
                                <h2 className="text-2xl font-semibold text-gray-900">Checklist</h2>
                                <p className="mt-2 text-gray-600 text-[14px]">
                                    Tick each completed stage and save once the step has been confirmed.<br />
                                    Payments made are only transfered after both parties certify each steps.<br />
                                    This is neccessary for dispute resolution.
                                </p>
                            </div>

                            <button
                                type="button"
                                onClick={() => saveProgress.mutate()}
                                disabled={(selectedStepKeys.length === 0 && Object.keys(selectedStepResponses).length === 0) || saveProgress.isPending}
                                className="btn btn-primary disabled:cursor-not-allowed disabled:opacity-50"
                            >
                                {saveProgress.isPending ? 'Saving...' : 'Save Progress'}
                            </button>
                        </div>

                        <div className="mt-6 grid gap-4">
                            <div className="grid grid-cols-[minmax(0,1fr)_88px_88px] items-center gap-3 px-4 text-xs font-semibold uppercase tracking-[0.12em] text-gray-500">
                                <span>Step</span>
                                <span className="text-center">{isLandlord ? 'Landlord' : 'Tenant'}</span>
                                <span className="text-center">{isLandlord ? 'Tenant' : 'Landlord'}</span>
                            </div>
                            {steps.map((step, index) => {
                                const selected = selectedStepKeys.includes(step.key)
                                const completed = Boolean(step.completed)
                                const counterpartCompleted = Boolean(step.counterpart_completed)
                                const selectedResponse = selectedStepResponses[step.key] || ''
                                const blockedByDepositPayment = !isLandlord
                                    && tenantDepositStepIndex >= 0
                                    && index >= tenantDepositStepIndex
                                    && !rentalDepositPaid
                                const blockedByFullRentalPayment = !isLandlord
                                    && tenantRentStepIndex >= 0
                                    && index >= tenantRentStepIndex
                                    && !fullRentalAmountPaid
                                const unlocked = stepPrerequisitesSatisfied(index, steps)
                                    && !blockedByDepositPayment
                                    && !blockedByFullRentalPayment
                                const isChoiceStep = step.kind === 'choice' && Array.isArray(step.options) && step.options.length > 0

                                return (
                                    <div
                                        key={step.key}
                                        className={`grid grid-cols-[minmax(0,1fr)_88px_88px] items-start gap-3 rounded-2xl border p-4 transition ${completed
                                            ? 'border-gray-200 bg-gray-100 text-gray-500'
                                            : selected || selectedResponse
                                                ? 'border-blue-400 bg-blue-50'
                                                : unlocked
                                                    ? 'border-gray-200 bg-white hover:border-blue-300'
                                                    : 'border-gray-200 bg-gray-50 text-gray-400'
                                            }`}
                                    >
                                        <div className="min-w-0">
                                            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                                                <div>
                                                    <p className={`text-base font-semibold ${completed ? 'text-gray-500' : 'text-gray-900'}`}>
                                                        {step.label}
                                                    </p>
                                                    {step.key === 'tenancy_agreement_signed' && !completed ? (
                                                        <p className="mt-1 text-sm">
                                                            <Link
                                                                to={isLandlord
                                                                    ? `/landlord/tenancy-agreements/${booking.id}`
                                                                    : `/tenant/tenancy-agreements/${booking.id}`}
                                                                className="font-medium text-blue-600 hover:underline"
                                                            >
                                                                Review & sign the digital tenancy agreement
                                                            </Link>
                                                        </p>
                                                    ) : null}
                                                    {step.completed_at ? (
                                                        <p className="mt-2 flex items-center gap-2 text-sm text-gray-500">
                                                            <HiClock className="h-4 w-4" />
                                                            {new Date(step.completed_at).toLocaleString()}
                                                        </p>
                                                    ) : (
                                                        <p className="mt-2 text-sm text-gray-500">
                                                            {blockedByDepositPayment
                                                                ? `Available after payment of the ${formatRatePercent(financialConfig?.listingDepositRate)} deposit or full rental amount (including all fees).`
                                                                : blockedByFullRentalPayment
                                                                    ? 'Available after full rental payment (including all fees).'
                                                                    : unlocked
                                                                        ? 'Pending confirmation'
                                                                        : 'Complete the previous checklist item first.'}
                                                        </p>
                                                    )}
                                                </div>

                                                <span
                                                    className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-sm font-semibold ${completed
                                                        ? 'bg-gray-200 text-gray-600'
                                                        : selected || selectedResponse
                                                            ? 'bg-blue-100 text-blue-700'
                                                            : 'bg-amber-100 text-amber-700'
                                                        }`}
                                                >
                                                    {completed ? <HiCheckCircle className="h-4 w-4" /> : null}
                                                    {completed
                                                        ? step.selected_value
                                                            ? `Saved: ${step.selected_value === 'yes' ? 'Yes' : 'No'}`
                                                            : 'Saved'
                                                        : selected || selectedResponse
                                                            ? 'Ready to save'
                                                            : 'Pending'}
                                                </span>
                                            </div>
                                        </div>

                                        <div className="flex flex-col items-center gap-2 pt-1">
                                            {isChoiceStep ? (
                                                <div className="flex flex-col gap-2">
                                                    {step.options?.map((option) => {
                                                        const isChecked = completed
                                                            ? step.selected_value === option.value
                                                            : selectedResponse === option.value
                                                        return (
                                                            <label key={option.value} className="flex items-center gap-1 text-xs font-medium">
                                                                <input
                                                                    type="checkbox"
                                                                    checked={isChecked}
                                                                    onChange={() => selectStepResponse(step.key, option.value, completed, unlocked)}
                                                                    disabled={completed || saveProgress.isPending || !unlocked}
                                                                    className="h-4 w-4 rounded border-gray-300 text-blue-600 disabled:cursor-not-allowed"
                                                                />
                                                                <span>{option.label}</span>
                                                            </label>
                                                        )
                                                    })}
                                                </div>
                                            ) : (
                                                <input
                                                    type="checkbox"
                                                    checked={completed || selected}
                                                    onChange={() => toggleStep(step.key, completed, unlocked)}
                                                    disabled={completed || saveProgress.isPending || !unlocked}
                                                    className="h-4 w-4 rounded border-gray-300 text-blue-600 disabled:cursor-not-allowed"
                                                />
                                            )}
                                            <span className="text-center text-[10px] font-semibold uppercase tracking-wide text-gray-500 md:hidden">
                                                {isLandlord ? 'Landlord' : 'Tenant'}
                                            </span>
                                        </div>

                                        <div className="flex flex-col items-center gap-2 pt-1">
                                            {isChoiceStep ? (
                                                <div className="flex flex-col gap-2">
                                                    {step.options?.map((option) => (
                                                        <label key={option.value} className="flex items-center gap-1 text-xs font-medium text-gray-500">
                                                            <input
                                                                type="checkbox"
                                                                checked={step.counterpart_selected_value === option.value}
                                                                disabled
                                                                aria-label={`${isLandlord ? 'Tenant' : 'Landlord'} answered ${option.label} for ${step.label}`}
                                                                className="h-4 w-4 rounded border-gray-300 accent-gray-400 disabled:cursor-not-allowed disabled:opacity-100"
                                                            />
                                                            <span>{option.label}</span>
                                                        </label>
                                                    ))}
                                                </div>
                                            ) : (
                                                <input
                                                    type="checkbox"
                                                    checked={counterpartCompleted}
                                                    disabled
                                                    aria-label={`${isLandlord ? 'Tenant' : 'Landlord'} completion for ${step.label}`}
                                                    className="h-4 w-4 rounded border-gray-300 accent-gray-400 text-gray-500 disabled:cursor-not-allowed disabled:opacity-100"
                                                />
                                            )}
                                            <span className="text-center text-[10px] font-semibold uppercase tracking-wide text-gray-500 md:hidden">
                                                {isLandlord ? 'Tenant' : 'Landlord'}
                                            </span>
                                        </div>
                                    </div>
                                )
                            })}
                        </div>
                    </div>

                    {!isLandlord && (
                        <div className="mt-8 rounded-3xl border bg-white p-6 shadow-sm">
                            <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                                <div>
                                    <h2 className="text-2xl font-semibold text-gray-900">Refunds</h2>
                                    <p className="mt-2 text-gray-600 text-[14px]">
                                        Request a refund of a completed payment before the property keys are handed over.<br />
                                        A 1% processing fee (capped at {formatCurrencyWithSymbol(REFUND_FEE_CAP_NGN)}) applies.<br />
                                        Refunds are paid to the bank used for the original payment after 3 working days (72 hours).
                                    </p>
                                </div>
                                {canRequestRefund && !showRefundForm && (
                                    <button
                                        type="button"
                                        onClick={() => setShowRefundForm(true)}
                                        className="btn btn-primary"
                                    >
                                        Request a refund
                                    </button>
                                )}
                            </div>

                            {keysHandedOver && refundsList.length === 0 && (
                                <p className="mt-4 rounded-2xl border border-gray-200 bg-gray-50 p-4 text-sm text-gray-600">
                                    Refunds are no longer available because the property keys have been handed over.
                                </p>
                            )}

                            {showRefundForm && canRequestRefund && (
                                <form
                                    className="mt-6 grid gap-4 rounded-2xl border border-blue-100 bg-blue-50/50 p-5"
                                    onSubmit={(event) => {
                                        event.preventDefault()
                                        requestRefund.mutate()
                                    }}
                                >
                                    <div>
                                        <label className="mb-1 block text-sm font-semibold text-gray-700">Payment to refund</label>
                                        <select
                                            value={refundPaymentId}
                                            onChange={(event) => {
                                                const nextId = event.target.value
                                                setRefundPaymentId(nextId)
                                                const nextPayment = refundablePayments.find((payment) => payment.id === nextId)
                                                if (nextPayment?.bank_name && normalizeBankKey(nextPayment.bank_name) !== normalizeBankKey(refundBankName)) {
                                                    setRefundBankName(nextPayment.bank_name)
                                                }
                                            }}
                                            required
                                            className="form-input w-full"
                                        >
                                            <option value="">Select a payment</option>
                                            {refundablePayments.map((payment) => (
                                                <option key={payment.id} value={payment.id}>
                                                    {formatCurrencyWithSymbol(Number(payment.amount))} — {payment.payment_method === 'bank' ? 'Bank transfer' : 'Card'}
                                                    {payment.card_last4 ? ` (•••• ${payment.card_last4})` : ''}
                                                    {payment.bank_name ? ` — ${payment.bank_name}` : ''}
                                                </option>
                                            ))}
                                        </select>
                                    </div>

                                    <div className="grid gap-4 md:grid-cols-2">
                                        <div>
                                            <label className="mb-1 block text-sm font-semibold text-gray-700">Bank</label>
                                            <select
                                                value={refundBankName}
                                                onChange={(event) => setRefundBankName(event.target.value)}
                                                required
                                                className="form-input w-full"
                                            >
                                                <option value="">Select bank</option>
                                                {bankOptions.map((bank) => (
                                                    <option key={bank} value={bank}>{bank}</option>
                                                ))}
                                            </select>
                                            {recordedBankName && (
                                                <p className="mt-1 text-xs text-gray-500">
                                                    This payment was made from {recordedBankName}; refunds can only go to that bank.
                                                </p>
                                            )}
                                        </div>
                                        <div>
                                            <label className="mb-1 block text-sm font-semibold text-gray-700">Account number</label>
                                            <input
                                                type="text"
                                                inputMode="numeric"
                                                maxLength={10}
                                                value={refundAccountNumber}
                                                onChange={(event) => setRefundAccountNumber(event.target.value.replace(/\D/g, ''))}
                                                required
                                                placeholder="10-digit account number"
                                                className="form-input w-full"
                                            />
                                        </div>
                                    </div>

                                    <div>
                                        <label className="mb-1 block text-sm font-semibold text-gray-700">Account name</label>
                                        <input
                                            type="text"
                                            value={refundAccountName}
                                            onChange={(event) => setRefundAccountName(event.target.value)}
                                            placeholder="Name on the account"
                                            className="form-input w-full"
                                        />
                                    </div>

                                    <div>
                                        <label className="mb-1 block text-sm font-semibold text-gray-700">Reason (optional)</label>
                                        <textarea
                                            value={refundReason}
                                            onChange={(event) => setRefundReason(event.target.value)}
                                            rows={3}
                                            placeholder="Why are you requesting a refund?"
                                            className="form-input w-full"
                                        />
                                    </div>

                                    {selectedRefundPayment && (
                                        <div className="rounded-2xl border border-gray-200 bg-white p-4 text-sm text-gray-700">
                                            <div className="flex justify-between">
                                                <span>Payment amount</span>
                                                <span className="font-semibold">{formatCurrencyWithSymbol(selectedRefundAmount)}</span>
                                            </div>
                                            <div className="mt-1 flex justify-between">
                                                <span>Processing fee (1%, capped at {formatCurrencyWithSymbol(REFUND_FEE_CAP_NGN)})</span>
                                                <span className="font-semibold">-{formatCurrencyWithSymbol(selectedRefundFee)}</span>
                                            </div>
                                            <div className="mt-2 flex justify-between border-t pt-2">
                                                <span>You will receive</span>
                                                <span className="font-bold text-emerald-700">{formatCurrencyWithSymbol(selectedRefundAmount - selectedRefundFee)}</span>
                                            </div>
                                            <p className="mt-2 text-xs text-gray-500">
                                                Payout is processed after 3 working days (72 hours) from the refund request.
                                            </p>
                                        </div>
                                    )}

                                    <div className="flex flex-wrap gap-3">
                                        <button
                                            type="submit"
                                            disabled={requestRefund.isPending || !refundPaymentId || !refundBankName || refundAccountNumber.length < 10}
                                            className="btn btn-primary disabled:cursor-not-allowed disabled:opacity-50"
                                        >
                                            {requestRefund.isPending ? 'Submitting...' : 'Submit refund request'}
                                        </button>
                                        <button
                                            type="button"
                                            onClick={() => setShowRefundForm(false)}
                                            className="btn btn-outline"
                                        >
                                            Cancel
                                        </button>
                                    </div>
                                </form>
                            )}

                            {refundsList.length > 0 && (
                                <div className="mt-6 grid gap-3">
                                    {refundsList.map((refund) => (
                                        <div key={refund.id} className="rounded-2xl border border-gray-200 p-4">
                                            <div className="flex flex-wrap items-start justify-between gap-3">
                                                <div>
                                                    <p className="text-base font-semibold text-gray-900">
                                                        {formatCurrencyWithSymbol(Number(refund.refund_amount))} refund
                                                    </p>
                                                    <p className="mt-1 text-sm text-gray-500">
                                                        {formatCurrencyWithSymbol(Number(refund.amount))} paid — {formatCurrencyWithSymbol(Number(refund.fee_amount))} fee
                                                        {' · '}{refund.bank_name} · {refund.account_number}
                                                    </p>
                                                    {refund.reason && (
                                                        <p className="mt-1 text-sm text-gray-500">Reason: {refund.reason}</p>
                                                    )}
                                                    {refund.status !== 'paid' && refund.process_at && (
                                                        <p className="mt-1 flex items-center gap-1 text-xs text-gray-500">
                                                            <HiClock className="h-4 w-4" />
                                                            Processes after {new Date(refund.process_at).toLocaleString()}
                                                        </p>
                                                    )}
                                                    {refund.status === 'paid' && refund.transferred_at && (
                                                        <p className="mt-1 text-xs text-emerald-600">
                                                            Paid on {new Date(refund.transferred_at).toLocaleString()}
                                                        </p>
                                                    )}
                                                    {refund.status === 'failed' && refund.last_error && (
                                                        <p className="mt-1 text-xs text-red-600">{refund.last_error}</p>
                                                    )}
                                                </div>
                                                <span className={`inline-flex items-center rounded-full px-3 py-1 text-sm font-semibold ${refund.status === 'paid'
                                                    ? 'bg-emerald-100 text-emerald-700'
                                                    : refund.status === 'failed'
                                                        ? 'bg-red-100 text-red-700'
                                                        : 'bg-amber-100 text-amber-700'
                                                    }`}>
                                                    {refundStatusLabel(refund.status)}
                                                </span>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}
