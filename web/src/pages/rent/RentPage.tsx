import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { useAuth } from '@/hooks/useAuth'
import { api, resolveMediaUrl } from '@/lib/api'
import { HostedCheckoutPayload, launchHostedCheckout } from '@/lib/payments'
import { hasBronzeAccess, SubscriptionPaymentRecord } from '@/lib/subscriptions'
import { Booking, Listing, Payment } from '@/types'
import { formatCurrencyWithSymbol } from '@/utils/currency'
import { calculateRentBreakdown } from '@/utils/rent'

type PaymentCheckoutResponse = {
    payment: Payment
    checkout: HostedCheckoutPayload
}

const CARD_PAYMENT_LIMIT_NGN = 7000000
const CARD_PAYMENT_LIMIT_MESSAGE = 'Flutterwave card payments are limited to ₦7,000,000 per transaction. Please use Bank Transfer for this payment.'

export default function RentPage() {
    const { id } = useParams()
    const { user } = useAuth()
    const navigate = useNavigate()
    const [searchParams, setSearchParams] = useSearchParams()
    const qc = useQueryClient()
    const [selectedPaymentMethod, setSelectedPaymentMethod] = useState<'card' | 'bank'>('bank')
    const [agreeToTerms, setAgreeToTerms] = useState(false)
    const [showPaymentForm, setShowPaymentForm] = useState(false)
    const [paymentAmount, setPaymentAmount] = useState(0)
    const [virtualAccountCheckout, setVirtualAccountCheckout] = useState<HostedCheckoutPayload>(null)
    const [isOpeningCheckout, setIsOpeningCheckout] = useState(false)
    const checkoutReference = (searchParams.get('reference') || searchParams.get('tx_ref') || '').trim()
    const checkoutTransactionId = searchParams.get('transaction_id') || ''
    const checkoutStatus = searchParams.get('status') || ''

    const { data: listing, isLoading } = useQuery({
        queryKey: ['listing', id],
        enabled: !!id,
        queryFn: async () => (await api.get<Listing>(`/listings/${id}`)).data
    })

    const { data: booking } = useQuery({
        queryKey: ['booking', 'listing', id],
        enabled: !!id && !!user,
        queryFn: async () => {
            try {
                return (await api.get<Booking>(`/bookings/listing/${id}`)).data
            } catch (error: any) {
                if (error?.response?.status === 404) {
                    return null
                }
                throw error
            }
        }
    })
    const { data: subscriptionPaymentResponse } = useQuery({
        queryKey: ['subscription-payments', 'rent', user?.id],
        enabled: user?.role === 'tenant',
        queryFn: async () => (await api.get<SubscriptionPaymentRecord[] | { results?: SubscriptionPaymentRecord[] }>('/subscriptions')).data,
    })
    const isBronzeTenant = user?.role === 'tenant' && subscriptionPaymentResponse !== undefined && hasBronzeAccess(subscriptionPaymentResponse)

    const annualRent = Number(listing?.price_per_year || 0)
    const paidAmount = Number(booking?.paid_amount || 0)
    const {
        annualRent: normalizedAnnualRent,
        depositAmount,
        refundableSecurityDeposit,
        administrationFee,
        totalAmount,
        remainingBalance,
    } = calculateRentBreakdown(annualRent, paidAmount)
    const isFullyPaid = remainingBalance <= 0
    const canPayInitialDeposit = Boolean(booking && paidAmount <= 0 && depositAmount > 0 && depositAmount < remainingBalance)

    useEffect(() => {
        if (remainingBalance > 0) {
            setPaymentAmount(remainingBalance)
        }
    }, [remainingBalance])

    useEffect(() => {
        if (!checkoutReference || !user) {
            return
        }

        let cancelled = false
        const verifyReturnedPayment = async () => {
            try {
                const verifiedPayment = (
                    await api.get<Payment>('/payments/flutterwave/verify', {
                        params: {
                            reference: checkoutReference,
                            transaction_id: checkoutTransactionId,
                            status: checkoutStatus,
                        },
                    })
                ).data

                if (cancelled) {
                    return
                }

                qc.invalidateQueries({ queryKey: ['booking', 'listing', id] })
                qc.invalidateQueries({ queryKey: ['bookings'] })
                if (verifiedPayment.status === 'completed') {
                    setShowPaymentForm(false)
                    alert('Payment confirmed successfully.')
                } else if (verifiedPayment.status === 'failed' || verifiedPayment.status === 'cancelled') {
                    alert(`Payment ${verifiedPayment.status}. You can try again.`)
                } else {
                    alert('Payment is still pending confirmation.')
                }
            } catch (error: any) {
                if (!cancelled) {
                    alert(error?.response?.data?.detail || error?.message || 'Unable to verify payment right now.')
                }
            } finally {
                if (!cancelled) {
                    setSearchParams({}, { replace: true })
                }
            }
        }

        verifyReturnedPayment()

        return () => {
            cancelled = true
        }
    }, [checkoutReference, checkoutStatus, checkoutTransactionId, id, qc, setSearchParams, user])

    const createBooking = useMutation({
        mutationFn: async () => {
            if (isBronzeTenant) {
                throw new Error('Renting property is not available on the Bronze free plan.')
            }
            return (await api.post<Booking>('/bookings', {
                listing_id: listing!.id,
                start_date: new Date().toISOString().split('T')[0],
                end_date: new Date(Date.now() + 365 * 24 * 60 * 60 * 1000).toISOString().split('T')[0]
            })).data
        },
        onSuccess: (nextBooking) => {
            qc.setQueryData(['booking', 'listing', id], nextBooking)
            qc.invalidateQueries({ queryKey: ['bookings'] })
            setShowPaymentForm(true)
            alert('Rental application created successfully. You can complete your payment below.')
        },
        onError: (error: any) => {
            alert(error?.response?.data?.detail || error?.message || 'Failed to create booking.')
        }
    })

    const processPayment = useMutation({
        mutationFn: async (amount: number) => {
            return (await api.post<PaymentCheckoutResponse>('/payments', {
                booking_id: booking!.id,
                amount,
                payment_method: selectedPaymentMethod
            })).data
        },
        onSuccess: async ({ checkout }) => {
            qc.invalidateQueries({ queryKey: ['booking', 'listing', id] })
            qc.invalidateQueries({ queryKey: ['bookings'] })
            setShowPaymentForm(false)
            if (checkout?.checkout_mode === 'virtual_account') {
                setVirtualAccountCheckout(checkout)
                return
            }
            try {
                const launched = await launchHostedCheckout(checkout)
                if (!launched) {
                    throw new Error('Unable to start Flutterwave checkout.')
                }
            } catch (error: any) {
                alert(error?.message || 'Unable to open Flutterwave checkout.')
            }
        },
        onError: (error: any) => {
            alert(error?.response?.data?.detail || error?.message || 'Failed to process payment.')
        }
    })

    const continuePendingPayment = useMutation({
        mutationFn: async (paymentId: string) => {
            return (await api.post<PaymentCheckoutResponse>(`/payments/${paymentId}/flutterwave/checkout`)).data
        },
        onSuccess: async ({ checkout }) => {
            if (checkout?.checkout_mode === 'virtual_account') {
                setVirtualAccountCheckout(checkout)
                return
            }
            try {
                const launched = await launchHostedCheckout(checkout)
                if (!launched) {
                    throw new Error('Unable to start Flutterwave checkout.')
                }
            } catch (error: any) {
                alert(error?.message || 'Unable to open Flutterwave checkout.')
            }
        },
        onError: (error: any) => {
            alert(error?.response?.data?.detail || error?.message || 'Unable to continue payment.')
        },
    })

    const generateReceipt = (payment: Payment) => {
        const receipt = `
            DIRECTRENT - PAYMENT RECEIPT
            =============================

            Receipt No: ${payment.id}
            Date: ${new Date(payment.payment_date).toLocaleDateString()}
            Time: ${new Date(payment.payment_date).toLocaleTimeString()}

            PROPERTY DETAILS:
            Property: ${listing?.title}
            Address: ${listing?.address}
            City: ${listing?.city}

            PAYMENT DETAILS:
            Amount Paid: ${formatCurrencyWithSymbol(payment.amount)}
            Payment Method: ${payment.payment_method.toUpperCase()}
            ${payment.bank_name ? `Bank: ${payment.bank_name}` : ''}
            ${payment.card_last4 ? `Card: ****${payment.card_last4}` : ''}
            Transaction ID: ${payment.transaction_id || 'N/A'}

            TENANT DETAILS:
            Name: ${user?.name}
            Email: ${user?.email}

            LANDLORD DETAILS:
            Property Owner

            =============================
            Thank you for using RentDirect!
        `

        const blob = new Blob([receipt], { type: 'text/plain' })
        const url = window.URL.createObjectURL(blob)
        const anchor = document.createElement('a')
        anchor.href = url
        anchor.download = `receipt-${payment.id}-${new Date(payment.payment_date).toISOString().split('T')[0]}.txt`
        document.body.appendChild(anchor)
        anchor.click()
        document.body.removeChild(anchor)
        window.URL.revokeObjectURL(url)
    }

    const handlePayment = () => {
        if (!booking) return
        if (paymentAmount <= 0) {
            alert('Enter a valid payment amount.')
            return
        }
        if (paymentAmount > remainingBalance) {
            alert('Payment amount cannot exceed the remaining balance.')
            return
        }
        if (selectedPaymentMethod === 'card' && paymentAmount > CARD_PAYMENT_LIMIT_NGN) {
            alert(CARD_PAYMENT_LIMIT_MESSAGE)
            setSelectedPaymentMethod('bank')
            return
        }
        processPayment.mutate(paymentAmount)
    }

    const handlePaymentMethodChange = (method: 'card' | 'bank') => {
        if (method === 'card' && paymentAmount > CARD_PAYMENT_LIMIT_NGN) {
            alert(CARD_PAYMENT_LIMIT_MESSAGE)
            setSelectedPaymentMethod('bank')
            return
        }
        setSelectedPaymentMethod(method)
    }

    const selectPaymentAmount = (amount: number) => {
        setPaymentAmount(amount)
        if (selectedPaymentMethod === 'card' && amount > CARD_PAYMENT_LIMIT_NGN) {
            alert(CARD_PAYMENT_LIMIT_MESSAGE)
            setSelectedPaymentMethod('bank')
        }
    }

    const handleVirtualAccountPayment = async () => {
        if (!virtualAccountCheckout) {
            return
        }

        try {
            setIsOpeningCheckout(true)
            const launched = await launchHostedCheckout(virtualAccountCheckout)
            if (!launched) {
                throw new Error('Unable to start Flutterwave checkout.')
            }
        } catch (error: any) {
            alert(error?.message || 'Unable to open Flutterwave checkout.')
        } finally {
            setIsOpeningCheckout(false)
        }
    }

    if (isLoading) {
        return (
            <div className="min-h-[80vh] flex items-center justify-center bg-gray-50">
                <div className="animate-pulse text-gray-500">Loading rental information…</div>
            </div>
        )
    }

    if (!listing) {
        return (
            <div className="min-h-[80vh] flex items-center justify-center bg-gray-50">
                <div className="text-gray-500">Listing not found.</div>
            </div>
        )
    }

    if (isBronzeTenant) {
        return (
            <div className="min-h-[80vh] flex items-center justify-center bg-gray-50 px-4">
                <div className="max-w-md w-full rounded-2xl border bg-white p-8 text-center shadow-lg">
                    <h1 className="text-2xl font-bold text-gray-900">Upgrade Required</h1>
                    <p className="mt-3 text-gray-600">Renting property is not available on the Bronze free plan.</p>
                    <button
                        type="button"
                        onClick={() => navigate('/billing')}
                        className="mt-6 w-full rounded-lg bg-blue-600 px-4 py-3 font-medium text-white hover:bg-blue-700"
                    >
                        View Subscription Plans
                    </button>
                    <button
                        type="button"
                        onClick={() => navigate(`/listings/${listing.id}`)}
                        className="mt-3 w-full rounded-lg bg-gray-100 px-4 py-3 font-medium text-gray-700 hover:bg-gray-200"
                    >
                        Back to Listing
                    </button>
                </div>
            </div>
        )
    }

    return (
        <div className="bg-gray-50 py-10">
            <div className="container-modern">
                <div className="max-w-6xl mx-auto">
                    <div className="mb-8">
                        <h1 className="text-3xl font-bold text-gray-900">Rent This Property</h1>
                        <p className="text-gray-600 mt-2">Complete your rental application and payment</p>
                    </div>

                    <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
                        <div className="lg:col-span-3">
                            <div className="bg-white rounded-2xl p-6 shadow-lg border mb-4">
                                <h2 className="text-xl font-semibold mb-4">Property Details</h2>
                                <div className="flex items-start space-x-4">
                                    <img
                                        src={resolveMediaUrl(listing.cover_image_url)}
                                        alt={listing.title}
                                        className="w-24 h-24 object-cover rounded-lg"
                                        onError={(e) => {
                                            e.currentTarget.src = '/placeholder.jpg'
                                        }}
                                    />
                                    <div className="flex-1">
                                        <h3 className="font-semibold text-lg">{listing.title}</h3>
                                        <p className="text-gray-600">{listing.address || listing.state}</p>
                                        {(listing.city || listing.postal_code) && (
                                            <p className="text-gray-600">{listing.city}, {listing.postal_code}</p>
                                        )}
                                        <div className="flex space-x-4 mt-2 text-sm text-gray-500">
                                            <span>{listing.bedrooms} bedrooms</span>
                                            <span>{listing.bathrooms} bathrooms</span>
                                            <span>{listing.property_type}</span>
                                        </div>
                                    </div>
                                </div>
                            </div>

                            <div className="bg-white rounded-2xl gap-2 p-5 shadow-lg border mb-4">
                                <h2 className="text-xl font-semibold mb-4">Rental Terms</h2>
                                <div className="space-y-4">
                                    <div className="flex justify-between items-center py-2 border-b">
                                        <span className="text-gray-600">Rent:</span>
                                        <span className="font-semibold">{formatCurrencyWithSymbol(normalizedAnnualRent)}</span>
                                    </div>
                                    <div className="rounded-xl bg-blue-50 border border-blue-100 p-4">
                                        <div className="flex items-center justify-between">
                                            <span className="font-medium text-blue-900">Deposit Amount</span>
                                            <span className="font-semibold text-blue-900">{formatCurrencyWithSymbol(depositAmount)}</span>
                                        </div>
                                        <p className="mt-2 text-sm text-blue-800">
                                            The 20% deposit is inclusive of the rental amount and will go towards your annual rent.
                                            This enables the landlord to take the property of the market.
                                        </p>
                                    </div>
                                    <div className="flex justify-between items-center py-2 border-b">
                                        <span className="text-gray-600">Refundable Security Deposit:</span>
                                        <span className="font-semibold">{formatCurrencyWithSymbol(refundableSecurityDeposit)}</span>
                                    </div>
                                    <div className="flex justify-between items-center py-2 border-b">
                                        <span className="text-gray-600">Administration Fee:</span>
                                        <span className="font-semibold">{formatCurrencyWithSymbol(administrationFee)}</span>
                                    </div>
                                    <div className="flex justify-between items-center py-2 border-b">
                                        <span className="text-gray-600">Lease Duration:</span>
                                        <span className="font-semibold">12 months</span>
                                    </div>
                                    <div className="flex justify-between items-center py-2 border-b">
                                        <span className="text-gray-600">Available From:</span>
                                        <span className="font-semibold">Immediate</span>
                                    </div>
                                </div>
                            </div>

                            {showPaymentForm && booking && (
                                <div className="bg-white rounded-2xl p-6 shadow-lg border">
                                    <h2 className="text-xl font-semibold mb-4">Payment Method</h2>
                                    <div className="space-y-3">
                                        <label className="flex items-center space-x-3 cursor-pointer">
                                            <input
                                                type="radio"
                                                name="paymentMethod"
                                                value="card"
                                                checked={selectedPaymentMethod === 'card'}
                                                onChange={() => handlePaymentMethodChange('card')}
                                                className="text-blue-600"
                                            />
                                            <div className="flex items-center space-x-2">
                                                <svg className="w-6 h-6 text-gray-600" fill="currentColor" viewBox="0 0 20 20">
                                                    <path d="M4 4a2 2 0 00-2 2v1h16V6a2 2 0 00-2-2H4zM18 9H2v5a2 2 0 002 2h12a2 2 0 002-2V9zM4 13a1 1 0 011-1h1a1 1 0 110 2H5a1 1 0 01-1-1zm5-1a1 1 0 100 2h1a1 1 0 100-2H9z" />
                                                </svg>
                                                <span>Credit/Debit Card</span>
                                            </div>
                                        </label>
                                        <label className="flex items-center space-x-3 cursor-pointer">
                                            <input
                                                type="radio"
                                                name="paymentMethod"
                                                value="bank"
                                                checked={selectedPaymentMethod === 'bank'}
                                                onChange={() => handlePaymentMethodChange('bank')}
                                                className="text-blue-600"
                                            />
                                            <div className="flex items-center space-x-2">
                                                <svg className="w-6 h-6 text-gray-600" fill="currentColor" viewBox="0 0 20 20">
                                                    <path fillRule="evenodd" d="M4 4a2 2 0 00-2 2v4a2 2 0 002 2V6h10a2 2 0 00-2-2H4zm2 6a2 2 0 012-2h8a2 2 0 012 2v4a2 2 0 01-2 2H8a2 2 0 01-2-2v-4zm6 4a2 2 0 100-4 2 2 0 000 4z" clipRule="evenodd" />
                                                </svg>
                                                <span>Bank Transfer</span>
                                            </div>
                                        </label>
                                    </div>

                                    <div className="mt-5">
                                        <label className="block text-sm font-medium text-gray-700 mb-2">Amount to pay</label>
                                        <div className="mb-3 grid gap-3 sm:grid-cols-2">
                                            {canPayInitialDeposit && (
                                                <button
                                                    type="button"
                                                    onClick={() => selectPaymentAmount(depositAmount)}
                                                    className={`rounded-lg border px-4 py-3 text-left text-sm transition ${paymentAmount === depositAmount ? 'border-blue-600 bg-blue-50 text-blue-900' : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50'}`}
                                                >
                                                    <span className="block font-semibold">Pay 20% Deposit</span>
                                                    <span>{formatCurrencyWithSymbol(depositAmount)}</span>
                                                </button>
                                            )}
                                            <button
                                                type="button"
                                                onClick={() => selectPaymentAmount(remainingBalance)}
                                                className={`rounded-lg border px-4 py-3 text-left text-sm transition ${paymentAmount === remainingBalance ? 'border-blue-600 bg-blue-50 text-blue-900' : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50'}`}
                                            >
                                                <span className="block font-semibold">Pay Full Balance</span>
                                                <span>{formatCurrencyWithSymbol(remainingBalance)}</span>
                                            </button>
                                        </div>
                                        <input
                                            type="number"
                                            min="1"
                                            step="0.01"
                                            max={remainingBalance}
                                            value={paymentAmount}
                                            readOnly
                                            className="w-full rounded-lg border border-gray-200 bg-gray-100 px-4 py-3 text-gray-600"
                                        />
                                        <p className="mt-2 text-sm text-gray-500">
                                            Choose either the 20% deposit or the full remaining balance of {formatCurrencyWithSymbol(remainingBalance)}.
                                        </p>
                                    </div>

                                    {selectedPaymentMethod === 'card' && (
                                        <div className="mt-4 p-4 bg-gray-50 rounded-lg">
                                            <p className="text-sm text-gray-600">
                                                Card payments are collected through Flutterwave checkout into RentDirect&apos;s Flutterwave collection balance.
                                            </p>
                                        </div>
                                    )}

                                    {selectedPaymentMethod === 'bank' && (
                                        <div className="mt-4 p-4 bg-gray-50 rounded-lg">
                                            <p className="text-sm text-gray-600">
                                                A unique Flutterwave virtual account will be generated for this exact amount.
                                            </p>
                                        </div>
                                    )}

                                    <div className="mt-6 flex space-x-3">
                                        <button
                                            onClick={() => setShowPaymentForm(false)}
                                            className="flex-1 px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50"
                                        >
                                            Cancel
                                        </button>
                                        <button
                                            onClick={handlePayment}
                                            disabled={processPayment.isPending}
                                            className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
                                        >
                                            {processPayment.isPending ? 'Processing...' : `Pay ${formatCurrencyWithSymbol(paymentAmount)}`}
                                        </button>
                                    </div>
                                </div>
                            )}
                            {virtualAccountCheckout?.checkout_mode === 'virtual_account' && (
                                <div className="bg-white rounded-2xl p-6 shadow-lg border">
                                    <h2 className="text-xl font-semibold mb-4">Bank Details</h2>
                                    <div className="rounded-xl border border-blue-100 bg-blue-50 p-4">
                                        <div className="grid gap-4 sm:grid-cols-2">
                                            <div>
                                                <p className="text-xs uppercase tracking-[0.18em] text-blue-700">Bank</p>
                                                <p className="mt-1 text-lg font-semibold text-gray-900">
                                                    {virtualAccountCheckout.virtual_account?.bank_name || 'Flutterwave'}
                                                </p>
                                            </div>
                                            <div>
                                                <p className="text-xs uppercase tracking-[0.18em] text-blue-700">Account Number</p>
                                                <p className="mt-1 text-lg font-semibold text-gray-900">
                                                    {virtualAccountCheckout.virtual_account?.account_number || 'Pending'}
                                                </p>
                                            </div>
                                            <div>
                                                <p className="text-xs uppercase tracking-[0.18em] text-blue-700">Amount</p>
                                                <p className="mt-1 text-lg font-semibold text-gray-900">
                                                    {formatCurrencyWithSymbol(Number(virtualAccountCheckout.amount || paymentAmount))}
                                                </p>
                                            </div>
                                            <div>
                                                <p className="text-xs uppercase tracking-[0.18em] text-blue-700">Reference</p>
                                                <p className="mt-1 break-all text-sm font-semibold text-gray-900">
                                                    {virtualAccountCheckout.reference}
                                                </p>
                                            </div>
                                        </div>
                                        <p className="mt-4 text-sm text-blue-800">
                                            Transfer the exact amount to this account. Your booking updates automatically after Flutterwave confirms the payment.
                                        </p>
                                    </div>
                                    <div className="mt-4 flex gap-3">
                                        <button
                                            type="button"
                                            onClick={() => setVirtualAccountCheckout(null)}
                                            className="flex-1 rounded-lg border border-gray-300 px-4 py-2 hover:bg-gray-50"
                                        >
                                            Close
                                        </button>
                                        <button
                                            type="button"
                                            onClick={handleVirtualAccountPayment}
                                            disabled={isOpeningCheckout}
                                            className="flex-1 rounded-lg bg-blue-600 px-4 py-2 text-white hover:bg-blue-700 disabled:opacity-50"
                                        >
                                            {isOpeningCheckout ? 'Opening...' : 'Make Payment'}
                                        </button>
                                    </div>
                                </div>
                            )}
                        </div>

                        <div className="lg:col-span-2">
                            <div className="bg-white rounded-2xl p-12 shadow-lg border top-6">
                                <h2 className="text-xl font-semibold mb-4">Payment Summary</h2>

                                <div className="space-y-3 mb-6">
                                    <div className="flex justify-between">
                                        <span className="text-gray-600">Rent:</span>
                                        <span>{formatCurrencyWithSymbol(normalizedAnnualRent)}</span>
                                    </div>
                                    <div className="flex justify-between">
                                        <span className="text-gray-600">Refundable Security Deposit:</span>
                                        <span>{formatCurrencyWithSymbol(refundableSecurityDeposit)}</span>
                                    </div>
                                    <div className="flex justify-between">
                                        <span className="text-gray-600">Administration Fee:</span>
                                        <span>{formatCurrencyWithSymbol(administrationFee)}</span>
                                    </div>
                                    <div className="rounded-xl bg-blue-50 border border-blue-100 px-4 py-3 text-[0.95rem] text-blue-800">
                                        Deposit Amount: {formatCurrencyWithSymbol(depositAmount)}<br />
                                        <div className="text-xs text-blue-800">
                                            (part of the {formatCurrencyWithSymbol(normalizedAnnualRent)} annual rent)
                                        </div>
                                    </div>
                                    <div className="border-t pt-3">
                                        <div className="flex justify-between font-semibold text-lg">
                                            <span>Total Amount:</span>
                                            <span>{formatCurrencyWithSymbol(totalAmount)}</span>
                                        </div>
                                    </div>
                                    {booking && (
                                        <>
                                            <div className="border-t pt-3">
                                                <div className="flex justify-between text-green-600">
                                                    <span>Amount Paid:</span>
                                                    <span>{formatCurrencyWithSymbol(paidAmount)}</span>
                                                </div>
                                            </div>
                                            <div className="border-t pt-3">
                                                <div className={`flex justify-between font-semibold text-lg ${remainingBalance > 0 ? 'text-red-600' : 'text-green-600'}`}>
                                                    <span>Remaining:</span>
                                                    <span>{formatCurrencyWithSymbol(remainingBalance)}</span>
                                                </div>
                                            </div>
                                        </>
                                    )}
                                </div>

                                <div className="space-y-4">
                                    {!user ? (
                                        <button
                                            onClick={() => navigate('/login')}
                                            className="w-full bg-blue-600 text-white py-3 px-4 rounded-lg font-medium hover:bg-blue-700 transition-colors"
                                        >
                                            Sign In to Continue
                                        </button>
                                    ) : !booking ? (
                                        <>
                                            <label className="flex items-start space-x-3 cursor-pointer">
                                                <input
                                                    type="checkbox"
                                                    checked={agreeToTerms}
                                                    onChange={(event) => setAgreeToTerms(event.target.checked)}
                                                    className="mt-1 text-blue-600"
                                                />
                                                <span className="text-sm text-gray-600">
                                                    I agree to the rental terms and conditions, and authorize payment toward the total amount.
                                                </span>
                                            </label>

                                            <button
                                                onClick={() => createBooking.mutate()}
                                                disabled={createBooking.isPending || !agreeToTerms}
                                                className="w-full bg-green-600 text-white py-3 px-4 rounded-lg font-medium hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                                            >
                                                {createBooking.isPending ? 'Processing...' : 'Confirm Rental Application'}
                                            </button>
                                        </>
                                    ) : isFullyPaid ? (
                                        <div className="text-center">
                                            <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
                                                <svg className="w-8 h-8 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                                                </svg>
                                            </div>
                                            <h3 className="text-lg font-semibold text-green-600 mb-2">Payment Complete!</h3>
                                            <p className="text-sm text-gray-600">Your rental application has been confirmed.</p>
                                        </div>
                                    ) : (
                                        <button
                                            onClick={() => setShowPaymentForm(true)}
                                            className="w-full bg-blue-600 text-white py-3 px-4 rounded-lg font-medium hover:bg-blue-700 transition-colors"
                                        >
                                            Pay Remaining Balance
                                        </button>
                                    )}

                                    <button
                                        onClick={() => navigate(`/listings/${listing.id}`)}
                                        className="w-full border border-gray-300 text-gray-700 py-3 px-4 rounded-lg font-medium hover:bg-gray-50 transition-colors"
                                    >
                                        Back to Property
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                    {booking && (
                        <div className="mb-8 bg-white rounded-2xl p-6 shadow-lg border">
                            <div className="flex items-center justify-between">
                                <div>
                                    <h2 className="text-xl font-semibold text-gray-900">Payment Status</h2>
                                    <p className="text-gray-600">Booking #{booking.id}</p>
                                </div>
                                <div className={`px-4 py-2 rounded-full text-sm font-medium ${isFullyPaid ? 'bg-green-100 text-green-800' : 'bg-yellow-100 text-yellow-800'}`}>
                                    {isFullyPaid ? 'Fully Paid' : 'Balance Outstanding'}
                                </div>
                            </div>

                            <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-4">
                                <div className="text-center">
                                    <div className="text-2xl font-bold text-gray-900">{formatCurrencyWithSymbol(totalAmount)}</div>
                                    <div className="text-sm text-gray-600">Total Amount</div>
                                </div>
                                <div className="text-center">
                                    <div className="text-2xl font-bold text-green-600">{formatCurrencyWithSymbol(paidAmount)}</div>
                                    <div className="text-sm text-gray-600">Amount Paid</div>
                                </div>
                                <div className="text-center">
                                    <div className={`text-2xl font-bold ${remainingBalance > 0 ? 'text-red-600' : 'text-green-600'}`}>
                                        {formatCurrencyWithSymbol(remainingBalance)}
                                    </div>
                                    <div className="text-sm text-gray-600">Remaining Balance</div>
                                </div>
                            </div>

                            {!isFullyPaid && (
                                <div className="mt-4 flex justify-center">
                                    <button
                                        onClick={() => setShowPaymentForm(true)}
                                        className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
                                    >
                                        Pay Remaining Balance
                                    </button>
                                </div>
                            )}
                        </div>
                    )}
                    {booking && booking.payments && booking.payments.length > 0 && (
                        <div className="mb-8 bg-white rounded-2xl p-6 shadow-lg border">
                            <h2 className="text-xl font-semibold text-gray-900 mb-4">Payment History</h2>
                            <div className="space-y-4">
                                {booking.payments.map((payment) => (
                                    <div key={payment.id} className="flex items-center justify-between p-4 border border-gray-200 rounded-lg">
                                        <div>
                                            <div className="font-medium text-gray-900">
                                                {formatCurrencyWithSymbol(Number(payment.amount || 0))} - {payment.payment_method.toUpperCase()}
                                            </div>
                                            <div className="text-sm text-gray-600">
                                                {new Date(payment.payment_date).toLocaleDateString()} at {new Date(payment.payment_date).toLocaleTimeString()}
                                            </div>
                                            {payment.transaction_id && (
                                                <div className="text-xs text-gray-500">
                                                    Transaction ID: {payment.transaction_id}
                                                </div>
                                            )}
                                            {payment.virtual_account_number && (
                                                <div className="text-xs text-gray-500">
                                                    Virtual Account: {payment.virtual_account_bank_name} {payment.virtual_account_number}
                                                </div>
                                            )}
                                        </div>
                                        <div className="flex items-center space-x-2">
                                            <span className={`px-2 py-1 rounded-full text-xs font-medium ${payment.status === 'completed'
                                                ? 'bg-green-100 text-green-800'
                                                : payment.status === 'pending' || payment.status === 'processing'
                                                    ? 'bg-yellow-100 text-yellow-800'
                                                    : 'bg-red-100 text-red-800'
                                                }`}>
                                                {payment.status}
                                            </span>
                                            {(payment.status === 'pending' || payment.status === 'processing') ? (
                                                <button
                                                    onClick={() => continuePendingPayment.mutate(payment.id)}
                                                    disabled={continuePendingPayment.isPending}
                                                    className="px-3 py-1 text-sm text-blue-600 hover:text-blue-800 disabled:opacity-50"
                                                >
                                                    View Account
                                                </button>
                                            ) : (
                                                <button
                                                    onClick={() => generateReceipt(payment)}
                                                    className="px-3 py-1 text-sm text-blue-600 hover:text-blue-800"
                                                >
                                                    Download Receipt
                                                </button>
                                            )}
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                    <div className="mt-4 p-4 bg-blue-50 rounded-lg text-center">
                        <h4 className="font-semibold text-blue-900 mb-2">What's Included:</h4>
                        <ul className="text-sm text-blue-800 space-y-1">
                            <li>Annual rent</li>
                            <li>Refundable security deposit</li>
                            <li>Administration fee</li>
                            <li>Legal fee</li>
                            <li>Verification fee</li>
                            <li>Lease agreement support</li>
                            <li>Viewing fee</li>
                            <li>Tenant support</li>
                        </ul>
                        <br />
                        <p className="text-[14px] font-semibold text-lime-600">10% flat fee covers admin, legal, verification, viewing & agreement costs</p>
                    </div>
                </div>
            </div>
        </div>
    )
}
