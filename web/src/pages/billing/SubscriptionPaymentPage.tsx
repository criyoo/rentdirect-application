import { useEffect, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { getApiUrl } from '@/lib/api'
import { HostedCheckoutPayload, launchHostedCheckout } from '@/lib/payments'
import { useAppPopup } from '@/contexts/AppPopupContext'
import { formatCurrencyWithSymbol } from '@/utils/currency'
import DashboardBackButton from '@/components/DashboardBackButton'

type SubscriptionPayment = {
    id: string
    role: 'tenant' | 'landlord'
    plan_code: 'bronze' | 'silver' | 'gold' | 'platinum'
    billing_cycle: 'monthly' | 'yearly'
    amount: number | string
    currency: string
    status: string
    recurring_enabled?: boolean
    next_action_url?: string
    payment_date: string | null
}

type SubscriptionCheckoutResponse = {
    payment: SubscriptionPayment
    checkout: HostedCheckoutPayload
}

function capitalize(value: string) {
    return value.charAt(0).toUpperCase() + value.slice(1)
}

export default function SubscriptionPaymentPage() {
    const { paymentId } = useParams()
    const navigate = useNavigate()
    const { confirm } = useAppPopup()
    const [searchParams] = useSearchParams()
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [payment, setPayment] = useState<SubscriptionPayment | null>(null)
    const [isStarting, setIsStarting] = useState(false)
    const [isCancelling, setIsCancelling] = useState(false)
    const [hasAttemptedAutoStart, setHasAttemptedAutoStart] = useState(false)
    const checkoutReference = (searchParams.get('reference') || searchParams.get('tx_ref') || '').trim()
    const checkoutTransactionId = searchParams.get('transaction_id') || ''
    const checkoutStatus = searchParams.get('status') || ''

    async function startCheckout() {
        if (!paymentId) {
            return
        }

        setIsStarting(true)
        setError(null)

        try {
            const response = await fetch(`${getApiUrl()}/subscriptions/${paymentId}/flutterwave/checkout`, {
                method: 'POST',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
            })
            if (!response.ok) {
                const payload = await response.json().catch(() => ({}))
                throw new Error(payload.detail || 'Failed to start Flutterwave checkout')
            }

            const payload: SubscriptionCheckoutResponse = await response.json()
            setPayment(payload.payment)
            if (payload.payment.next_action_url) {
                window.location.assign(payload.payment.next_action_url)
                return
            }
            const launched = await launchHostedCheckout(payload.checkout)
            if (!launched) {
                throw new Error('Unable to start Flutterwave checkout')
            }
        } catch (caughtError: any) {
            setError(caughtError.message || 'Failed to start checkout')
        } finally {
            setIsStarting(false)
        }
    }

    async function cancelPayment() {
        if (!paymentId || payment?.status !== 'pending') {
            return
        }

        const shouldCancel = await confirm(
            'This will completely cancel this pending subscription payment. Do you want to continue?',
            {
                title: 'Cancel pending payment?',
                variant: 'warning',
                cancelLabel: 'Cancel',
                confirmLabel: 'Continue',
            },
        )
        if (!shouldCancel) {
            return
        }

        setIsCancelling(true)
        setError(null)

        try {
            const response = await fetch(`${getApiUrl()}/subscriptions/${paymentId}/cancel`, {
                method: 'POST',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
            })
            if (!response.ok) {
                const payload = await response.json().catch(() => ({}))
                throw new Error(payload.detail || 'Unable to cancel payment')
            }

            const payload = await response.json()
            setPayment(payload)
        } catch (caughtError: any) {
            setError(caughtError.message || 'Unable to cancel payment')
        } finally {
            setIsCancelling(false)
        }
    }

    useEffect(() => {
        const load = async () => {
            if (!paymentId) {
                setError('Payment not found')
                setLoading(false)
                return
            }

            try {
                const response = await fetch(`${getApiUrl()}/subscriptions/payments/${paymentId}`, {
                    credentials: 'include',
                })
                if (!response.ok) {
                    const payload = await response.json().catch(() => ({}))
                    throw new Error(payload.detail || 'Failed to load payment')
                }

                const payload = await response.json()
                setPayment(payload)
            } catch (caughtError: any) {
                setError(caughtError.message || 'Failed to load payment')
            } finally {
                setLoading(false)
            }
        }

        void load()
    }, [paymentId])

    useEffect(() => {
        if (!checkoutReference) {
            return
        }

        let cancelled = false
        const verifyPayment = async () => {
            try {
                const response = await fetch(
                    `${getApiUrl()}/subscriptions/flutterwave/verify?reference=${encodeURIComponent(checkoutReference)}&transaction_id=${encodeURIComponent(checkoutTransactionId)}&status=${encodeURIComponent(checkoutStatus)}`,
                    { credentials: 'include' },
                )
                if (!response.ok) {
                    const payload = await response.json().catch(() => ({}))
                    throw new Error(payload.detail || 'Unable to verify payment')
                }

                const payload = await response.json()
                if (!cancelled) {
                    setPayment(payload)
                    window.history.replaceState({}, document.title, window.location.pathname)
                }
            } catch (caughtError: any) {
                if (!cancelled) {
                    setError(caughtError.message || 'Unable to verify payment')
                }
            }
        }

        void verifyPayment()
        return () => {
            cancelled = true
        }
    }, [checkoutReference, checkoutStatus, checkoutTransactionId])

    useEffect(() => {
        if (!paymentId || !payment || payment.status !== 'pending' || payment.recurring_enabled || checkoutReference || hasAttemptedAutoStart || isStarting) {
            return
        }

        setHasAttemptedAutoStart(true)
        void startCheckout()
    }, [checkoutReference, hasAttemptedAutoStart, isStarting, payment, paymentId])

    if (loading) {
        return (
            <div className="min-h-screen bg-gray-50 flex items-center justify-center">
                <div className="text-center">
                    <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto" />
                    <p className="mt-4 text-gray-600">Loading payment details...</p>
                </div>
            </div>
        )
    }

    if (error) {
        return (
            <div className="min-h-screen bg-gray-50 flex items-center justify-center">
                <div className="text-center">
                    <div className="text-red-600 text-6xl mb-4">!</div>
                    <h1 className="text-2xl font-bold text-gray-900 mb-2">Payment Error</h1>
                    <p className="text-gray-600 mb-4">{error}</p>
                    <DashboardBackButton to="/billing" label="Back to Billing" />
                </div>
            </div>
        )
    }

    const statusLabel = String(payment?.status || '').toUpperCase()

    return (
        <div className="min-h-screen bg-gray-50 py-8">
            <div className="container-modern">
                <div className="max-w-xl mx-auto bg-white rounded-lg shadow-lg p-6">
                    <h1 className="text-2xl font-bold text-gray-900 mb-2">Subscription Payment</h1>
                    <div className="text-sm text-gray-600 mb-6">Payment ID: {paymentId}</div>

                    <div className="space-y-3 mb-6">
                        <div className="flex items-center justify-between">
                            <span className="text-gray-600">Plan</span>
                            <span className="font-medium">
                                {capitalize(payment?.plan_code || '')} {payment?.billing_cycle ? `(${capitalize(payment.billing_cycle)})` : ''}
                            </span>
                        </div>
                        <div className="flex items-center justify-between">
                            <span className="text-gray-600">Role</span>
                            <span className="font-medium capitalize">{payment?.role || 'user'}</span>
                        </div>
                        <div className="flex items-center justify-between">
                            <span className="text-gray-600">Status</span>
                            <span className="font-medium">{statusLabel || 'PENDING'}</span>
                        </div>
                        <div className="flex items-center justify-between">
                            <span className="text-gray-600">Amount</span>
                            <span className="font-semibold">{formatCurrencyWithSymbol(payment?.amount || 0)} {payment?.currency || 'NGN'}</span>
                        </div>
                    </div>

                    {payment?.status === 'completed' ? (
                        <div className="p-4 rounded-lg bg-green-50 text-green-800 mb-4">
                            Payment successful. Your subscription is active.
                        </div>
                    ) : payment?.status === 'failed' || payment?.status === 'cancelled' ? (
                        <div className="p-4 rounded-lg bg-red-50 text-red-800 mb-4">
                            Payment {payment.status}. You can try again.
                        </div>
                    ) : (
                        <div className="p-4 rounded-lg bg-blue-50 text-blue-800 mb-4">
                            {payment?.recurring_enabled
                                ? 'Recurring card charge is pending provider confirmation.'
                                : 'Redirecting to payment page to complete your subscription payment.'}
                        </div>
                    )}

                    {payment?.status === 'pending' && payment.next_action_url && (
                        <button
                            type="button"
                            onClick={() => window.location.assign(payment.next_action_url || '')}
                            className="w-full bg-blue-600 text-white py-3 px-4 rounded-lg font-medium hover:bg-blue-700 transition-colors"
                        >
                            Complete Authentication
                        </button>
                    )}

                    {payment?.status === 'pending' && !payment.recurring_enabled && !payment.next_action_url && (
                        <div className="grid gap-3 sm:grid-cols-2">
                            <button
                                onClick={() => void startCheckout()}
                                disabled={isStarting || isCancelling}
                                className="w-full bg-blue-600 text-white py-3 px-4 rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                            >
                                {isStarting ? 'Redirecting…' : 'Continue Payment'}
                            </button>
                            <button
                                onClick={() => void cancelPayment()}
                                disabled={isStarting || isCancelling}
                                className="w-full rounded-lg border border-red-200 bg-red-50 px-4 py-3 font-medium text-red-700 transition-colors hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-50"
                            >
                                {isCancelling ? 'Cancelling…' : 'Completely Cancel Payment'}
                            </button>
                        </div>
                    )}

                    {payment?.status === 'cancelled' && (
                        <button
                            type="button"
                            onClick={() => navigate('/billing')}
                            className="w-full rounded-lg bg-blue-600 px-4 py-3 font-medium text-white transition-colors hover:bg-blue-700"
                        >
                            Choose Another Plan
                        </button>
                    )}

                    <div className="mt-4 flex justify-center">
                        <DashboardBackButton to="/billing" label="Back to Billing" />
                    </div>
                </div>
            </div>
        </div>
    )
}
