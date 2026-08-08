import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { HiCheckCircle, HiClock } from 'react-icons/hi'
import { Link, useParams } from 'react-router-dom'

import { useAuth } from '@/hooks/useAuth'
import { api, resolveMediaUrl } from '@/lib/api'
import { hasPlatinumAccess, hasSilverAccess, SubscriptionPaymentRecord } from '@/lib/subscriptions'
import { Booking, RentalProgressStep } from '@/types'
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

export default function RentalProgressPage() {
    const { bookingId } = useParams()
    const { user } = useAuth()
    const queryClient = useQueryClient()
    const [selectedStepKeys, setSelectedStepKeys] = useState<string[]>([])
    const [selectedStepResponses, setSelectedStepResponses] = useState<Record<string, string>>({})

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
    const dashboardPath = isLandlord ? `/dashboard/landlord/${user?.id}` : `/dashboard/tenant/${user?.id}`

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
                                    Tick each completed stage and save once the step has been confirmed. Great for dispute resolution.<br />
                                    Saved items are locked and shown with the date and time they were completed.
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
                                const unlocked = stepPrerequisitesSatisfied(index, steps)
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
                                                    {step.completed_at ? (
                                                        <p className="mt-2 flex items-center gap-2 text-sm text-gray-500">
                                                            <HiClock className="h-4 w-4" />
                                                            {new Date(step.completed_at).toLocaleString()}
                                                        </p>
                                                    ) : (
                                                        <p className="mt-2 text-sm text-gray-500">
                                                            {unlocked ? 'Pending confirmation' : 'Complete the previous checklist item first.'}
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
                                            <input
                                                type="checkbox"
                                                checked={counterpartCompleted}
                                                disabled
                                                aria-label={`${isLandlord ? 'Tenant' : 'Landlord'} completion for ${step.label}`}
                                                className="h-4 w-4 rounded border-gray-300 accent-gray-400 text-gray-500 disabled:cursor-not-allowed disabled:opacity-100"
                                            />
                                            <span className="text-center text-[10px] font-semibold uppercase tracking-wide text-gray-500 md:hidden">
                                                {isLandlord ? 'Tenant' : 'Landlord'}
                                            </span>
                                        </div>
                                    </div>
                                )
                            })}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}
