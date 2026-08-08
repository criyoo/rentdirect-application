import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { useAuth } from '@/hooks/useAuth'
import { useAppPopup } from '@/contexts/AppPopupContext'
import { api, resolveMediaUrl } from '@/lib/api'
import { HostedCheckoutPayload, launchHostedCheckout } from '@/lib/payments'
import { hasSilverAccess, SubscriptionPaymentRecord } from '@/lib/subscriptions'
import { Booking, Listing, Payment } from '@/types'
import { formatCurrencyWithSymbol } from '@/utils/currency'
import { calculateRentBreakdown } from '@/utils/rent'
import DashboardBackButton from '@/components/DashboardBackButton'

type PaymentCheckoutResponse = {
    payment: Payment
    checkout: HostedCheckoutPayload
}

const CARD_PAYMENT_LIMIT_NGN = 7000000
const CARD_PAYMENT_LIMIT_MESSAGE = 'Flutterwave card payments are limited to ₦7,000,000 per transaction. Please use Bank Transfer for this payment.'
const PENDING_PAYMENT_CANCEL_MESSAGE = 'Are you sure you want to cancel this payment?'
const COMPLETED_PAYMENT_CANCEL_MESSAGE = 'Are sure you want to cancel payment for this property? Refund will take 3 to 5 working days to the same account used in making payment and a 1% fee will be charged to cover admin fee and bank charges.'
const KEY_COLLECTED_CANCEL_MESSAGE = 'Sorry transaction cannot be cancelled. Landlord will need to approve refund. Status shows Tenant and Landlord have confirmed collection of keys to the property.'

function paymentStatusLabel(status: Payment['status']) {
    if (status === 'refund_requested') return 'Refund Requested'
    return status.charAt(0).toUpperCase() + status.slice(1)
}

function paymentStatusClass(status: Payment['status']) {
    if (status === 'completed') return 'bg-green-100 text-green-800'
    if (status === 'pending' || status === 'processing') return 'bg-yellow-100 text-yellow-800'
    if (status === 'refund_requested') return 'bg-blue-100 text-blue-800'
    return 'bg-red-100 text-red-800'
}

function receiptValue(value?: string | number | null) {
    const normalized = String(value ?? '').normalize('NFKD').replace(/[^\x20-\x7E]/g, ' ').replace(/\s+/g, ' ').trim()
    return normalized || 'N/A'
}

function escapePdfText(value: string) {
    return String(value ?? '')
        .normalize('NFKD')
        .replace(/[^\x20-\x7E]/g, ' ')
        .replace(/\s+/g, ' ')
        .trim()
        .replace(/\\/g, '\\\\')
        .replace(/\(/g, '\\(')
        .replace(/\)/g, '\\)')
}

function formatReceiptDate(date: Date) {
    return new Intl.DateTimeFormat('en-GB', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
    }).format(date)
}

function formatReceiptTime(date: Date) {
    return new Intl.DateTimeFormat('en-GB', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false,
    }).format(date)
}

function formatReceiptCurrency(amount: number | string) {
    return new Intl.NumberFormat('en-NG', {
        style: 'currency',
        currency: 'NGN',
        currencyDisplay: 'code',
    }).format(Number(amount || 0)).replace(/\s+/g, ' ')
}

function buildReceiptPdf(lines: string[]) {
    const stream = [
        'BT',
        '/F1 11 Tf',
        '72 740 Td',
        '15 TL',
        ...lines.map((line) => `(${escapePdfText(line)}) Tj T*`),
        'ET',
    ].join('\n')
    const objects = [
        '1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n',
        '2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n',
        '3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>\nendobj\n',
        `4 0 obj\n<< /Length ${stream.length} >>\nstream\n${stream}\nendstream\nendobj\n`,
        '5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n',
    ]

    let pdf = '%PDF-1.4\n'
    const offsets: number[] = []
    for (const object of objects) {
        offsets.push(pdf.length)
        pdf += object
    }
    const xrefOffset = pdf.length
    pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`
    pdf += offsets.map((offset) => `${String(offset).padStart(10, '0')} 00000 n \n`).join('')
    pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF`

    return new Blob([pdf], { type: 'application/pdf' })
}

export default function RentPage() {
    const { id } = useParams()
    const { user } = useAuth()
    const { confirm, alert: popupAlert } = useAppPopup()
    const navigate = useNavigate()
    const [searchParams, setSearchParams] = useSearchParams()
    const qc = useQueryClient()
    const [selectedPaymentMethod, setSelectedPaymentMethod] = useState<'card' | 'bank'>('bank')
    const [agreeToTerms, setAgreeToTerms] = useState(false)
    const [showPaymentForm, setShowPaymentForm] = useState(false)
    const [paymentAmount, setPaymentAmount] = useState(0)
    const [virtualAccountCheckout, setVirtualAccountCheckout] = useState<HostedCheckoutPayload>(null)
    const [activeCheckoutPayment, setActiveCheckoutPayment] = useState<Payment | null>(null)
    const [cancelledPaymentId, setCancelledPaymentId] = useState<string | null>(null)
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
    const { data: subscriptionPaymentResponse, isLoading: isSubscriptionLoading } = useQuery({
        queryKey: ['subscription-payments', 'rent', user?.id],
        enabled: user?.role === 'tenant',
        queryFn: async () => (await api.get<SubscriptionPaymentRecord[] | { results?: SubscriptionPaymentRecord[] }>('/subscriptions')).data,
    })
    const hasRentAccess = user?.role === 'tenant'
        && (
            subscriptionPaymentResponse !== undefined
            && hasSilverAccess(subscriptionPaymentResponse)
        )

    const isBookingCancelled = booking?.status === 'cancelled'
    const showCancelledPaymentState = isBookingCancelled || Boolean(cancelledPaymentId)
    const annualRent = showCancelledPaymentState ? 0 : Number(listing?.price_per_year || 0)
    const paidAmount = showCancelledPaymentState ? 0 : Number(booking?.paid_amount || 0)
    const {
        annualRent: normalizedAnnualRent,
        depositAmount,
        refundableSecurityDeposit,
        administrationFee,
        totalAmount,
        remainingBalance,
    } = calculateRentBreakdown(annualRent, paidAmount)
    const isFullyPaid = !showCancelledPaymentState && remainingBalance <= 0
    const canPayInitialDeposit = Boolean(booking && paidAmount <= 0 && depositAmount > 0 && depositAmount < remainingBalance)
    const keysCollectedConfirmed = Boolean(booking?.keys_collected_confirmed)
    const openRentalPayments = (booking?.payments || []).filter((payment) => (
        payment.status === 'pending' || payment.status === 'processing'
    ))
    const activeOpenPayment = activeCheckoutPayment && ['pending', 'processing'].includes(activeCheckoutPayment.status)
        ? activeCheckoutPayment
        : null
    const visibleOpenPayments = activeOpenPayment && !openRentalPayments.some((payment) => payment.id === activeOpenPayment.id)
        ? [activeOpenPayment, ...openRentalPayments]
        : openRentalPayments

    useEffect(() => {
        if (remainingBalance > 0) {
            setPaymentAmount(remainingBalance)
        }
    }, [remainingBalance])

    useEffect(() => {
        setCancelledPaymentId(null)
    }, [id])

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
                    qc.invalidateQueries({ queryKey: ['listings'] })
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
            if (!hasRentAccess) {
                throw new Error('Renting property is available from the Silver plan.')
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
        onSuccess: async ({ payment, checkout }) => {
            qc.invalidateQueries({ queryKey: ['booking', 'listing', id] })
            qc.invalidateQueries({ queryKey: ['bookings'] })
            setShowPaymentForm(false)
            setActiveCheckoutPayment(payment)
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
        onSuccess: async ({ payment, checkout }) => {
            setActiveCheckoutPayment(payment)
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

    const cancelPayment = useMutation({
        mutationFn: async (paymentId: string) => (await api.post<Payment>(`/payments/${paymentId}/cancel`)).data,
        onSuccess: async (payment) => {
            if (payment.status === 'cancelled' || payment.status === 'refund_requested') {
                setActiveCheckoutPayment(null)
                setVirtualAccountCheckout(null)
                setShowPaymentForm(false)
                setPaymentAmount(0)
                setCancelledPaymentId(payment.id)
            } else if (activeCheckoutPayment?.id === payment.id) {
                setActiveCheckoutPayment(null)
                setVirtualAccountCheckout(null)
            }
            await Promise.all([
                qc.invalidateQueries({ queryKey: ['booking', 'listing', id] }),
                qc.invalidateQueries({ queryKey: ['bookings'] }),
                qc.invalidateQueries({ queryKey: ['listings'] }),
            ])
            if (payment.status === 'refund_requested') {
                await popupAlert('Refund request submitted. Refund will take 3 to 5 working days and a 1% fee will be charged.', {
                    title: 'Refund Requested',
                    variant: 'success',
                })
            } else {
                await popupAlert('Payment cancelled.', {
                    title: 'Payment Cancelled',
                    variant: 'success',
                })
            }
        },
        onError: (error: any) => {
            alert(error?.response?.data?.detail || error?.message || 'Unable to cancel payment.')
        },
    })

    const generateReceipt = (payment: Payment) => {
        const paymentDate = new Date(payment.payment_date)
        const receiptDate = Number.isNaN(paymentDate.getTime()) ? new Date() : paymentDate
        const propertyOwnershipType = listing?.ownership_types?.length
            ? listing.ownership_types.join(', ')
            : listing?.ownership_status
        const receiptLines = [
            'RENTDIRECT - PAYMENT RECEIPT',
            '=============================',
            '',
            'TRANSACTION DETAILS:',
            `Receipt No: ${receiptValue(payment.id)}`,
            `Transaction ID: ${receiptValue(payment.transaction_id)}`,
            `Date: ${formatReceiptDate(receiptDate)}`,
            `Time: ${formatReceiptTime(receiptDate)}`,
            '',
            'PAYMENT DETAILS:',
            `Amount Paid: ${formatReceiptCurrency(payment.amount)}`,
            `Payment Method: ${receiptValue(payment.payment_method).toUpperCase()}`,
            '',
            'PROPERTY DETAILS:',
            `Property: ${receiptValue(listing?.title)}`,
            `Address: ${receiptValue(listing?.address)}`,
            `City: ${receiptValue(listing?.city)}`,
            '',
            'TENANT DETAILS:',
            `Name: ${receiptValue(user?.name)}`,
            `Email: ${receiptValue(user?.email)}`,
            '',
            'LANDLORD DETAILS:',
            `Name: ${receiptValue(listing?.landlord_name)}`,
            `Email: ${receiptValue(listing?.landlord_email)}`,
            `Property Ownership Type: ${receiptValue(propertyOwnershipType)}`,
            '',
            '=============================',
            'Thank you for using RentDirect!',
        ]

        const blob = buildReceiptPdf(receiptLines)
        const url = window.URL.createObjectURL(blob)
        const anchor = document.createElement('a')
        anchor.href = url
        anchor.download = `receipt-${payment.id}-${receiptDate.toISOString().split('T')[0]}.pdf`
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

    const handleCancelPayment = async (payment: Payment) => {
        if (payment.status === 'pending' || payment.status === 'processing') {
            const shouldContinue = await confirm(PENDING_PAYMENT_CANCEL_MESSAGE, {
                title: 'Cancel payment?',
                variant: 'warning',
                cancelLabel: 'Cancel',
                confirmLabel: 'Continue',
            })
            if (shouldContinue) {
                cancelPayment.mutate(payment.id)
            }
            return
        }

        if (payment.status === 'completed') {
            if (keysCollectedConfirmed) {
                await popupAlert(KEY_COLLECTED_CANCEL_MESSAGE, {
                    title: 'Cancellation unavailable',
                    variant: 'error',
                })
                return
            }

            const shouldContinue = await confirm(COMPLETED_PAYMENT_CANCEL_MESSAGE, {
                title: 'Cancel property payment?',
                variant: 'warning',
                cancelLabel: 'Cancel',
                confirmLabel: 'Continue',
            })
            if (shouldContinue) {
                cancelPayment.mutate(payment.id)
            }
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

    if (isLoading || (user?.role === 'tenant' && isSubscriptionLoading)) {
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

    if (!hasRentAccess) {
        return (
            <div className="min-h-[80vh] flex items-center justify-center bg-gray-50 px-4">
                <div className="max-w-md w-full rounded-2xl border bg-white p-8 text-center shadow-lg">
                    <h1 className="text-2xl font-bold text-gray-900">{user ? 'Upgrade Required' : 'Sign In Required'}</h1>
                    <p className="mt-3 text-gray-600">
                        {user
                            ? 'Renting property is available to tenants from the Silver plan.'
                            : 'Sign in with a Silver or higher tenant plan to rent this property.'}
                    </p>
                    <button
                        type="button"
                        onClick={() => navigate(user?.role === 'tenant' ? '/billing' : '/login')}
                        className="mt-6 w-full rounded-lg bg-blue-600 px-4 py-3 font-medium text-white hover:bg-blue-700"
                    >
                        {user?.role === 'tenant' ? 'View Subscription Plans' : 'Sign In'}
                    </button>
                    <DashboardBackButton to={`/listings/${listing.id}`} label="Back to Listing" className="mt-3 w-full justify-center" />
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

                    <div className="mb-4 grid grid-cols-1 gap-4 lg:grid-cols-5">
                        <div className="space-y-4 lg:col-span-3">
                            <div className="bg-white rounded-2xl p-6 shadow-lg border">
                                <h2 className="text-xl font-semibold mb-3">Property Details</h2>
                                <div className="flex items-start space-x-4">
                                    <img
                                        src={resolveMediaUrl(listing.cover_image_url)}
                                        alt={listing.title}
                                        loading="eager"
                                        decoding="async"
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

                            <div className="bg-white rounded-2xl gap-2 p-5 shadow-lg border">
                                <h2 className="text-xl font-semibold mb-4">Rental Terms</h2>
                                <div className="space-y-4">
                                    <div className="flex justify-between items-center py-2 border-b">
                                        <span className="text-gray-600">Rent:</span>
                                        <span className="font-semibold">{formatCurrencyWithSymbol(normalizedAnnualRent)}</span>
                                    </div>
                                    <div className="rounded-xl bg-blue-50 border border-blue-100 p-4">
                                        <div className="flex items-center justify-between">
                                            <span className="font-medium text-blue-900">Rental Deposit (Optional)</span>
                                            <span className="font-semibold text-blue-900">{formatCurrencyWithSymbol(depositAmount)}</span>
                                        </div>
                                        <p className="mt-2 text-sm text-blue-800">
                                            The 20% deposit amount is inclusive in the rental amount.<br />
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

                            {visibleOpenPayments.length > 0 && !showCancelledPaymentState && (
                                <div className="rounded-2xl border border-amber-200 bg-amber-50 p-5 shadow-lg">
                                    <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                                        <div>
                                            <h2 className="text-lg font-semibold text-amber-900">Payment In Progress</h2>
                                            <p className="mt-1 text-sm text-amber-800">
                                                A payment process has started for this property.<br />
                                                Continue or cancel it to start another payment.
                                            </p>
                                        </div>
                                        <div className="flex flex-col gap-2 sm:flex-row">
                                            {visibleOpenPayments.map((payment) => (
                                                <div key={payment.id} className="flex gap-2">
                                                    <button
                                                        type="button"
                                                        onClick={() => continuePendingPayment.mutate(payment.id)}
                                                        disabled={continuePendingPayment.isPending || cancelPayment.isPending}
                                                        className="rounded-lg bg-blue-600 px-2 py-3 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                                                    >
                                                        Continue
                                                    </button>
                                                    <button
                                                        type="button"
                                                        onClick={() => handleCancelPayment(payment)}
                                                        disabled={cancelPayment.isPending}
                                                        className="rounded-lg border border-red-200 bg-white px-2 py-3 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
                                                    >
                                                        {cancelPayment.isPending ? 'Cancelling...' : 'Cancel'}
                                                    </button>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                </div>
                            )}

                            {showPaymentForm && booking && !showCancelledPaymentState && (
                                <div className="bg-white rounded-2xl p-6 shadow-lg border mb-6">
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
                                                You have chosen card payment, your card details will be required to complete payment.
                                            </p>
                                        </div>
                                    )}

                                    {selectedPaymentMethod === 'bank' && (
                                        <div className="mt-4 p-4 bg-gray-50 rounded-lg">
                                            <p className="text-sm text-gray-600">
                                                You have chosen bank transfer as your payment option, you will receive bank details to complete the payment.
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
                                            Your booking updates automatically after payment is confirmed.<br />
                                            Allow few seconds for confirmation of payment, do not leave the page.
                                        </p>
                                    </div>
                                    <div className="mt-4 flex flex-col gap-3 sm:flex-row">
                                        <button
                                            type="button"
                                            onClick={() => {
                                                setVirtualAccountCheckout(null)
                                                setActiveCheckoutPayment(null)
                                            }}
                                            className="flex-1 rounded-lg border border-gray-300 px-4 py-2 hover:bg-gray-50"
                                        >
                                            Close
                                        </button>
                                        {activeCheckoutPayment && ['pending', 'processing'].includes(activeCheckoutPayment.status) ? (
                                            <button
                                                type="button"
                                                onClick={() => handleCancelPayment(activeCheckoutPayment)}
                                                disabled={cancelPayment.isPending}
                                                className="flex-1 rounded-lg border border-red-200 px-4 py-2 text-red-700 hover:bg-red-50 disabled:opacity-50"
                                            >
                                                {cancelPayment.isPending ? 'Cancelling...' : 'Cancel Payment'}
                                            </button>
                                        ) : null}
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

                        <div className="lg:col-span-2 lg:self-stretch">
                            <div className="h-full bg-white rounded-2xl p-12 shadow-lg border top-6 flex flex-col">
                                <h2 className="text-xl font-semibold mb-2">Payment Summary</h2>

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

                                <div className="mt-auto space-y-4 mb-6">
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
                                    ) : showCancelledPaymentState ? (
                                        <div className="rounded-xl border border-red-100 bg-red-50 p-4 text-center">
                                            <h3 className="text-lg font-semibold text-red-700">Payment Cancelled</h3>
                                            <p className="mt-2 text-sm text-red-700">
                                                Rental payment cancelled. <br />
                                                Eligible refund (if any) will be processed.
                                            </p>
                                        </div>
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

                                    <DashboardBackButton to={`/listings/${listing.id}`} label="Back to Property" className="w-full justify-center" />
                                </div>
                            </div>
                        </div>
                    </div>
                    {booking && (
                        <div className="mb-4 bg-white rounded-2xl p-6 shadow-lg border">
                            <div className="flex items-center justify-between">
                                <div>
                                    <h2 className="text-xl font-semibold text-gray-900">Payment Status</h2>
                                    <p className="text-gray-600">Booking #{booking.id}</p>
                                </div>
                                <div className={`px-4 py-2 rounded-full text-sm font-medium ${showCancelledPaymentState ? 'bg-red-100 text-red-800' : isFullyPaid ? 'bg-green-100 text-green-800' : 'bg-yellow-100 text-yellow-800'}`}>
                                    {showCancelledPaymentState ? 'Cancelled' : isFullyPaid ? 'Fully Paid' : 'Balance Outstanding'}
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

                            {/* {!isFullyPaid && !showCancelledPaymentState && (
                                <div className="mt-4 flex justify-center">
                                    <button
                                        onClick={() => setShowPaymentForm(true)}
                                        className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
                                    >
                                        Pay Remaining Balance
                                    </button>
                                </div>
                            )} */}
                        </div>
                    )}
                    {booking && booking.payments && booking.payments.length > 0 && (
                        <div className="mb-6 bg-white rounded-2xl p-6 shadow-lg border">
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
                                            <span className={`px-2 py-1 rounded-full text-xs font-medium ${paymentStatusClass(payment.status)}`}>
                                                {paymentStatusLabel(payment.status)}
                                            </span>
                                            {(payment.status === 'pending' || payment.status === 'processing') ? (
                                                <>
                                                    <button
                                                        onClick={() => continuePendingPayment.mutate(payment.id)}
                                                        disabled={continuePendingPayment.isPending || cancelPayment.isPending}
                                                        className="px-3 py-1 text-sm text-blue-600 hover:text-blue-800 disabled:opacity-50"
                                                    >
                                                        Continue Payment
                                                    </button>
                                                    <button
                                                        onClick={() => handleCancelPayment(payment)}
                                                        disabled={cancelPayment.isPending}
                                                        className="px-3 py-1 text-sm text-red-600 hover:text-red-800 disabled:opacity-50"
                                                    >
                                                        Cancel Payment
                                                    </button>
                                                </>
                                            ) : payment.status === 'completed' ? (
                                                <>
                                                    <button
                                                        onClick={() => generateReceipt(payment)}
                                                        className="px-3 py-1 text-sm text-blue-600 hover:text-blue-800"
                                                    >
                                                        Download Receipt
                                                    </button>
                                                    <button
                                                        onClick={() => handleCancelPayment(payment)}
                                                        disabled={cancelPayment.isPending}
                                                        className="px-3 py-1 text-sm text-red-600 hover:text-red-800 disabled:opacity-50"
                                                    >
                                                        Cancel Payment
                                                    </button>
                                                </>
                                            ) : null}
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
