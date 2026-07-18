import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { getApiUrl } from '@/lib/api'
import { HostedCheckoutPayload, launchHostedCheckout } from '@/lib/payments'
import { formatCurrencyWithSymbol } from '@/utils/currency'

type FeaturedCheckoutResponse = {
    payment: any
    checkout: HostedCheckoutPayload
}

export default function FeaturedPropertyPaymentPage() {
    const { paymentId } = useParams()
    const [searchParams] = useSearchParams()
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [payment, setPayment] = useState<any>(null)
    const [isStarting, setIsStarting] = useState(false)
    const checkoutReference = (searchParams.get('reference') || searchParams.get('tx_ref') || '').trim()
    const checkoutTransactionId = searchParams.get('transaction_id') || ''
    const checkoutStatus = searchParams.get('status') || ''

    useEffect(() => {
        const load = async () => {
            if (!paymentId) return
            try {
                const res = await fetch(`${getApiUrl()}/featured/payments/${paymentId}`, { credentials: 'include' })
                if (!res.ok) {
                    const err = await res.json().catch(() => ({}))
                    throw new Error(err.detail || 'Failed to load payment')
                }
                const data = await res.json()
                setPayment(data)
            } catch (e: any) {
                setError(e.message || 'Failed to load payment')
            } finally {
                setLoading(false)
            }
        }
        load()
    }, [paymentId])

    useEffect(() => {
        if (!checkoutReference) return

        let cancelled = false
        const verifyPayment = async () => {
            try {
                const res = await fetch(
                    `${getApiUrl()}/featured/flutterwave/verify?reference=${encodeURIComponent(checkoutReference)}&transaction_id=${encodeURIComponent(checkoutTransactionId)}&status=${encodeURIComponent(checkoutStatus)}`,
                    { credentials: 'include' },
                )
                if (!res.ok) {
                    const err = await res.json().catch(() => ({}))
                    throw new Error(err.detail || 'Unable to verify payment')
                }
                const data = await res.json()
                if (!cancelled) {
                    setPayment(data)
                    window.history.replaceState({}, document.title, window.location.pathname)
                }
            } catch (e: any) {
                if (!cancelled) {
                    setError(e.message || 'Unable to verify payment')
                }
            }
        }

        verifyPayment()
        return () => {
            cancelled = true
        }
    }, [checkoutReference, checkoutStatus, checkoutTransactionId])

    const startCheckout = async () => {
        if (!paymentId) return
        setIsStarting(true)
        try {
            const res = await fetch(`${getApiUrl()}/featured/${paymentId}/flutterwave/checkout`, {
                method: 'POST',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' }
            })
            if (!res.ok) {
                const err = await res.json().catch(() => ({}))
                throw new Error(err.detail || 'Failed to start Flutterwave checkout')
            }
            const data: FeaturedCheckoutResponse = await res.json()
            const launched = await launchHostedCheckout(data.checkout)
            if (!launched) {
                throw new Error('Unable to start Flutterwave checkout')
            }
        } catch (e: any) {
            setError(e.message || 'Failed to start checkout')
        } finally {
            setIsStarting(false)
        }
    }

    if (loading) return (
        <div className="min-h-screen bg-gray-50 flex items-center justify-center">
            <div className="text-center">
                <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
                <p className="mt-4 text-gray-600">Loading payment details...</p>
            </div>
        </div>
    )

    if (error) return (
        <div className="min-h-screen bg-gray-50 flex items-center justify-center">
            <div className="text-center">
                <div className="text-red-600 text-6xl mb-4">⚠️</div>
                <h1 className="text-2xl font-bold text-gray-900 mb-2">Payment Error</h1>
                <p className="text-gray-600 mb-4">{error}</p>
                <Link to="/dashboard/featured-properties" className="text-blue-600 hover:underline">Back to Featured Properties</Link>
            </div>
        </div>
    )

    const statusLabel = String(payment?.status || '').toUpperCase()
    const amount = payment?.amount
    const currency = payment?.currency || 'NGN'

    return (
        <div className="min-h-screen bg-gray-50 py-8">
            <div className="container-modern">
                <div className="max-w-xl mx-auto bg-white rounded-lg shadow-lg p-6">
                    <h1 className="text-2xl font-bold text-gray-900 mb-2">Featured Property Payment</h1>
                    <div className="text-sm text-gray-600 mb-6">Payment ID: {paymentId}</div>

                    <div className="space-y-3 mb-6">
                        <div className="flex items-center justify-between">
                            <span className="text-gray-600">Status</span>
                            <span className="font-medium">{statusLabel || 'PENDING'}</span>
                        </div>
                        <div className="flex items-center justify-between">
                            <span className="text-gray-600">Amount</span>
                            <span className="font-semibold">{formatCurrencyWithSymbol(amount || 0)} {currency}</span>
                        </div>
                    </div>

                    {payment?.status === 'completed' ? (
                        <div className="p-4 rounded-lg bg-green-50 text-green-800 mb-4">
                            Payment successful. Your property is now featured.
                        </div>
                    ) : payment?.status === 'failed' || payment?.status === 'cancelled' ? (
                        <div className="p-4 rounded-lg bg-red-50 text-red-800 mb-4">
                            Payment {payment?.status}. You can try again.
                        </div>
                    ) : null}

                    {payment?.status === 'pending' && (
                        <button
                            onClick={startCheckout}
                            disabled={isStarting}
                            className="w-full bg-blue-600 text-white py-3 px-4 rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                        >
                            {isStarting ? 'Redirecting…' : 'Pay'}
                        </button>
                    )}

                    <Link
                        to="/dashboard/featured-properties"
                        className="block text-center mt-4 text-sm text-blue-600 hover:text-blue-800"
                    >
                        Back to Featured Properties
                    </Link>
                </div>
            </div>
        </div>
    )
}
