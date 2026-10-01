import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api, extractApiErrorMessage } from '@/lib/api'
import { HostedCheckoutPayload, launchHostedCheckout } from '@/lib/payments'
import { formatCurrencyWithSymbol } from '@/utils/currency'
import DashboardBackButton from '@/components/DashboardBackButton'
import { ServicePayment } from '@/types'

type ServiceCheckoutResponse = {
    payment: ServicePayment
    checkout: HostedCheckoutPayload
}

export default function ServicePaymentPage() {
    const { paymentId } = useParams()
    const [searchParams] = useSearchParams()
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [payment, setPayment] = useState<ServicePayment | null>(null)
    const [isStarting, setIsStarting] = useState(false)
    const checkoutReference = (searchParams.get('reference') || searchParams.get('tx_ref') || '').trim()
    const checkoutTransactionId = searchParams.get('transaction_id') || ''
    const checkoutStatus = searchParams.get('status') || ''
    const returnPath = payment?.return_path || '/'

    useEffect(() => {
        if (!paymentId) return
        let cancelled = false

        const load = async () => {
            try {
                if (checkoutReference) {
                    const verified = await api.get<ServicePayment>('/service-payments/flutterwave/verify', {
                        params: {
                            reference: checkoutReference,
                            transaction_id: checkoutTransactionId,
                            status: checkoutStatus,
                        },
                    })
                    if (!cancelled) {
                        setPayment(verified.data)
                        window.history.replaceState({}, document.title, window.location.pathname)
                    }
                } else {
                    const response = await api.get<ServicePayment>(`/service-payments/${paymentId}`)
                    if (!cancelled) {
                        setPayment(response.data)
                    }
                }
            } catch (e: any) {
                if (!cancelled) {
                    setError(
                        extractApiErrorMessage(e, checkoutReference ? 'Unable to verify payment' : 'Failed to load payment')
                    )
                }
            } finally {
                if (!cancelled) {
                    setLoading(false)
                }
            }
        }

        load()
        return () => {
            cancelled = true
        }
    }, [paymentId, checkoutReference, checkoutStatus, checkoutTransactionId])

    const startCheckout = async () => {
        if (!paymentId) return
        setIsStarting(true)
        setError(null)
        try {
            const response = await api.post<ServiceCheckoutResponse>(`/service-payments/${paymentId}/flutterwave/checkout`)
            setPayment(response.data.payment)
            const launched = await launchHostedCheckout(response.data.checkout)
            if (!launched) {
                throw new Error('Unable to start Flutterwave checkout')
            }
        } catch (e: any) {
            setError(extractApiErrorMessage(e, 'Failed to start checkout'))
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

    if (error && !payment) return (
        <div className="min-h-screen bg-gray-50 flex items-center justify-center">
            <div className="text-center">
                <div className="mb-5 flex justify-center">
                    <DashboardBackButton fallbackTo="/" />
                </div>
                <div className="text-red-600 text-6xl mb-4">!</div>
                <h1 className="text-2xl font-bold text-gray-900 mb-2">Payment Error</h1>
                <p className="text-gray-600 mb-4">{error}</p>
                <DashboardBackButton to="/" label="Back" />
            </div>
        </div>
    )

    const statusLabel = String(payment?.status || 'pending').toUpperCase()

    return (
        <div className="min-h-screen bg-gray-50 py-8">
            <div className="container-modern">
                <div className="mb-5">
                    <DashboardBackButton to={returnPath} label="Back" />
                </div>
                <div className="max-w-xl mx-auto bg-white rounded-lg shadow-lg p-6">
                    <h1 className="text-2xl font-bold text-gray-900 mb-2">
                        {payment?.purpose_display || 'Service Payment'}
                    </h1>
                    <p className="text-sm text-gray-600 mb-6">
                        This is a one-time service payment{payment?.purpose === 'lawyer_tenancy' ? ' paid by the landlord — it is never added to tenant charges' : ''}.
                    </p>

                    {error && (
                        <div className="p-4 rounded-lg bg-red-50 text-red-800 mb-4">{error}</div>
                    )}

                    <div className="space-y-3 mb-6">
                        <div className="flex items-center justify-between">
                            <span className="text-gray-600">Status</span>
                            <span className="font-medium">{payment?.status_display || statusLabel}</span>
                        </div>
                        <div className="flex items-center justify-between">
                            <span className="text-gray-600">Amount</span>
                            <span className="font-semibold">{formatCurrencyWithSymbol(Number(payment?.amount || 0))} {payment?.currency || 'NGN'}</span>
                        </div>
                        {payment?.transaction_id && (
                            <div className="flex items-center justify-between">
                                <span className="text-gray-600">Reference</span>
                                <span className="font-mono text-sm">{payment.transaction_id}</span>
                            </div>
                        )}
                    </div>

                    {payment?.status === 'completed' ? (
                        <>
                            <div className="p-4 rounded-lg bg-green-50 text-green-800 mb-4">
                                Payment successful.
                            </div>
                            <Link to={returnPath} className="btn btn-primary w-full py-3 text-base font-medium text-center block">
                                Continue
                            </Link>
                        </>
                    ) : payment?.status === 'failed' || payment?.status === 'cancelled' ? (
                        <>
                            <div className="p-4 rounded-lg bg-red-50 text-red-800 mb-4">
                                Payment {payment.status}. You can return and request the service again.
                            </div>
                            <Link to={returnPath} className="btn btn-outline w-full py-3 text-base font-medium text-center block">
                                Go back
                            </Link>
                        </>
                    ) : (
                        <button
                            onClick={startCheckout}
                            disabled={isStarting}
                            className="w-full bg-blue-600 text-white py-3 px-4 rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                        >
                            {isStarting ? 'Redirecting…' : `Pay ${formatCurrencyWithSymbol(Number(payment?.amount || 0))}`}
                        </button>
                    )}
                </div>
            </div>
        </div>
    )
}
