import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { getApiUrl } from '@/lib/api'
import { HostedCheckoutPayload, launchHostedCheckout } from '@/lib/payments'
import { encryptFlutterwaveCard, encryptFlutterwavePin } from '@/lib/flutterwaveEncryption'
import { useAppPopup } from '@/contexts/AppPopupContext'
import { formatCurrencyWithSymbol } from '@/utils/currency'
import DashboardBackButton from '@/components/DashboardBackButton'

type SubscriptionPayment = {
    id: string
    role: 'tenant' | 'landlord'
    plan_code: 'bronze' | 'silver' | 'gold' | 'platinum'
    billing_cycle: 'monthly' | 'yearly'
    amount: number | string
    vat_rate: number | string
    vat_amount: number | string
    total_amount: number | string
    currency: string
    status: string
    provider_charge_id?: string
    recurring_enabled?: boolean
    next_action_url?: string
    next_action?: Record<string, any>
    status_detail?: string
    payment_date: string | null
    checkout_mode?: 'v3' | 'v4'
}

type V4PaymentMethodType = 'card' | 'bank_account' | 'bank_transfer' | 'ussd' | 'opay'

type SubscriptionCheckout = Omit<HostedCheckoutPayload, 'checkout_mode'> & {
    checkout_mode?: 'inline' | 'virtual_account' | 'v4'
    redirect_url?: string
    next_action?: Record<string, any>
    charge?: Record<string, any>
}

type SubscriptionCheckoutResponse = {
    payment: SubscriptionPayment
    checkout: SubscriptionCheckout
}

function capitalize(value: string) {
    return value.charAt(0).toUpperCase() + value.slice(1)
}

function formatVatRate(value: number | string | undefined): string {
    const numericValue = Number(value)
    return Number.isFinite(numericValue) ? String(numericValue) : '0'
}

export default function SubscriptionPaymentPage() {
    const { paymentId } = useParams()
    const navigate = useNavigate()
    const { confirm, alert } = useAppPopup()
    const [searchParams] = useSearchParams()
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [payment, setPayment] = useState<SubscriptionPayment | null>(null)
    const [isStarting, setIsStarting] = useState(false)
    const [isCancelling, setIsCancelling] = useState(false)
    const [v4EncryptionKey, setV4EncryptionKey] = useState('')
    const [v4PaymentMethod, setV4PaymentMethod] = useState<V4PaymentMethodType>('bank_transfer')
    const [v4Card, setV4Card] = useState({ cardNumber: '', expiryMonth: '', expiryYear: '', cvv: '' })
    const v4CardMonthRef = useRef<HTMLInputElement>(null)
    const v4CardYearRef = useRef<HTMLInputElement>(null)
    const v4CardCvvRef = useRef<HTMLInputElement>(null)
    const [v4Pin, setV4Pin] = useState('')
    const [v4Otp, setV4Otp] = useState('')
    const [showV4Authorization, setShowV4Authorization] = useState(false)
    const [isAuthorizing, setIsAuthorizing] = useState(false)
    const [v4NextAction, setV4NextAction] = useState<Record<string, any> | null>(null)
    const [ussdBanks, setUssdBanks] = useState<Array<{ code: string; name: string }>>([])
    const [ussdBankCode, setUssdBankCode] = useState('')
    const successRedirectStarted = useRef(false)
    const checkoutReference = (searchParams.get('reference') || searchParams.get('tx_ref') || '').trim()
    const checkoutTransactionId = searchParams.get('transaction_id') || ''
    const checkoutStatus = searchParams.get('status') || ''

    async function buildV4PaymentMethod() {
        if (v4PaymentMethod === 'bank_transfer') {
            return { type: 'bank_transfer', bank_transfer: { account_type: 'dynamic' } }
        }
        if (v4PaymentMethod === 'bank_account') {
            return { type: 'bank_account', bank_account: {} }
        }
        if (v4PaymentMethod === 'opay') {
            return { type: 'opay', opay: {} }
        }
        if (v4PaymentMethod === 'ussd') {
            if (!ussdBankCode) {
                throw new Error('Select your bank to continue.')
            }
            return { type: 'ussd', ussd: { account_bank: ussdBankCode } }
        }
        if (!v4EncryptionKey) {
            throw new Error('Flutterwave v4 card encryption is not configured.')
        }
        return {
            type: 'card',
            card: await encryptFlutterwaveCard(v4Card, v4EncryptionKey),
        }
    }

    async function authorizeV4Payment() {
        if (!paymentId || !v4NextAction?.type) {
            return
        }
        if (!v4EncryptionKey) {
            setError('Flutterwave v4 encryption is not configured.')
            return
        }
        setIsAuthorizing(true)
        setError(null)
        try {
            const authorization = v4NextAction.type === 'requires_pin'
                ? { type: 'pin', pin: await encryptFlutterwavePin(v4Pin, v4EncryptionKey) }
                : { type: 'otp', otp: { code: v4Otp.trim() } }
            const response = await fetch(`${getApiUrl()}/subscriptions/${paymentId}/flutterwave/authorize`, {
                method: 'POST',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ authorization }),
            })
            const payload = await response.json().catch(() => ({}))
            if (!response.ok) {
                throw new Error(payload.detail || 'Unable to authorize payment')
            }
            setPayment(payload)
            setV4NextAction(payload.next_action || null)
            setV4Pin('')
            setV4Otp('')
            const redirectUrl = payload.next_action_url || ''
            if (redirectUrl) {
                window.location.assign(redirectUrl)
            }
        } catch (caughtError: any) {
            setError(caughtError.message || 'Unable to authorize payment')
        } finally {
            setIsAuthorizing(false)
        }
    }

    async function startCheckout() {
        if (!paymentId) {
            return
        }

        setIsStarting(true)
        setError(null)
        setV4NextAction(null)

        try {
            const requestBody = payment?.checkout_mode === 'v4'
                ? { payment_method: await buildV4PaymentMethod() }
                : {}
            const response = await fetch(`${getApiUrl()}/subscriptions/${paymentId}/flutterwave/checkout`, {
                method: 'POST',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(requestBody),
            })
            if (!response.ok) {
                const payload = await response.json().catch(() => ({}))
                throw new Error(payload.detail || 'Failed to start Flutterwave checkout')
            }

            const payload: SubscriptionCheckoutResponse = await response.json()
            setPayment(payload.payment)
            if (payload.checkout.checkout_mode === 'v4') {
                setV4NextAction(payload.checkout.next_action || null)
                const redirectUrl = payload.checkout.next_action?.type === 'redirect_url'
                    ? payload.checkout.redirect_url || payload.payment.next_action_url
                    : ''
                if (redirectUrl) {
                    window.location.assign(redirectUrl)
                }
                return
            }
            if (payload.payment.next_action_url) {
                window.location.assign(payload.payment.next_action_url)
                return
            }
            const launched = await launchHostedCheckout(payload.checkout as HostedCheckoutPayload)
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
                setV4NextAction(payload.next_action || null)
            } catch (caughtError: any) {
                setError(caughtError.message || 'Failed to load payment')
            } finally {
                setLoading(false)
            }
        }

        void load()
    }, [paymentId])

    useEffect(() => {
        if (payment?.checkout_mode !== 'v4') {
            return
        }

        let cancelled = false
        const loadV4Config = async () => {
            try {
                const response = await fetch(`${getApiUrl()}/subscriptions/recurring/config`, {
                    credentials: 'include',
                })
                if (!response.ok) {
                    return
                }
                const payload = await response.json()
                if (!cancelled) {
                    setV4EncryptionKey(payload.encryption_key || '')
                }
            } catch {
                setV4EncryptionKey('')
            }
        }

        void loadV4Config()
        return () => {
            cancelled = true
        }
    }, [payment?.checkout_mode])

    useEffect(() => {
        const instructions = v4NextAction?.requires_bank_transfer
            || v4NextAction?.payment_instruction
            || v4NextAction?.payment_instructions
        if (!paymentId || payment?.checkout_mode !== 'v4' || payment.status !== 'pending' || !instructions) {
            return
        }

        let cancelled = false
        const poll = async () => {
            try {
                const response = await fetch(`${getApiUrl()}/subscriptions/payments/${paymentId}`, {
                    credentials: 'include',
                })
                if (!response.ok || cancelled) {
                    return
                }
                const payload = await response.json()
                setPayment(payload)
                setV4NextAction(payload.next_action || null)
            } catch {
                // Keep polling; transient errors should not clear the instructions.
            }
        }

        const interval = window.setInterval(() => void poll(), 15000)
        return () => {
            cancelled = true
            window.clearInterval(interval)
        }
    }, [paymentId, payment?.checkout_mode, payment?.status, v4NextAction])

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
                    setV4NextAction(payload.next_action || null)
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
        if (payment?.status !== 'completed' || successRedirectStarted.current) {
            return
        }
        successRedirectStarted.current = true
        void alert(
            'Payment successful. Your subscription is now active.',
            { title: 'Payment successful', variant: 'success', confirmLabel: 'Continue', autoConfirmSeconds: 10 },
        ).then(() => navigate('/search'))
    }, [payment?.status, alert, navigate])

    useEffect(() => {
        if (payment?.checkout_mode !== 'v4' || v4PaymentMethod !== 'ussd' || ussdBanks.length) {
            return
        }
        let cancelled = false
        fetch(`${getApiUrl()}/subscriptions/flutterwave/banks`, { credentials: 'include' })
            .then((response) => (response.ok ? response.json() : { banks: [] }))
            .then((payload) => {
                if (!cancelled) {
                    setUssdBanks(Array.isArray(payload.banks) ? payload.banks : [])
                }
            })
            .catch(() => { })
        return () => {
            cancelled = true
        }
    }, [payment?.checkout_mode, v4PaymentMethod, ussdBanks.length])

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
    const v4PaymentInstructions = v4NextAction?.requires_bank_transfer
        || v4NextAction?.payment_instruction
        || v4NextAction?.payment_instructions
        || null
    const v4AuthorizationType = v4NextAction?.type === 'requires_pin' || v4NextAction?.type === 'requires_otp'
        ? v4NextAction.type
        : null
    const v4RequiresAuthorization = payment?.checkout_mode === 'v4' && Boolean(v4AuthorizationType)
    const v4RequiresFollowUp = payment?.checkout_mode === 'v4'
        && ['requires_pin', 'requires_otp', 'requires_bank_transfer', 'payment_instruction', 'requires_additional_fields', 'requires_requery'].includes(String(v4NextAction?.type || ''))
    const pendingInfoMessage = (() => {
        if (v4PaymentInstructions) {
            return 'Awaiting your payment. This page updates once the payment is confirmed.'
        }
        if (payment?.checkout_mode === 'v4') {
            if (v4PaymentMethod === 'bank_transfer') {
                return 'Bank account details will be generated for your transfer.'
            }
            if (v4PaymentMethod === 'bank_account') {
                return 'You will be redirected to select your bank and provide bank credentials. Ensure your Bank App is updated to the latest version.'
            }
            if (v4PaymentMethod === 'ussd') {
                return 'A USSD code will be generated for you to dial from your registered mobile. Ensure USSD is enabled for your bank account'
            }
            if (v4PaymentMethod === 'opay') {
                return 'You will be redirected to OPay to authorize the payment.'
            }
            if (!payment?.provider_charge_id || v4NextAction?.type === 'requires_pin') {
                return 'Card PIN & OTP will be required for authorization.'
            }
            if (v4NextAction?.type === 'requires_otp') {
                return 'Enter OTP for authorization.'
            }
            return ''
        }
        return payment?.recurring_enabled
            ? 'Recurring card charge is pending provider confirmation.'
            : 'You will be redirected to payment page to complete payment.'
    })()

    return (
        <div className="min-h-screen bg-gray-50 py-8">
            <div className="container-modern">
                <div className="max-w-xl mx-auto bg-white rounded-lg shadow-lg p-6">
                    <h1 className="text-2xl font-bold text-gray-900 mb-2">Subscription Payment Review</h1>
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
                            <span className="font-medium">{statusLabel || 'Pending'}</span>
                        </div>
                        <div className="flex items-center justify-between">
                            <span className="text-gray-600">Subscription fee</span>
                            <span className="font-medium">{formatCurrencyWithSymbol(payment?.amount || 0)} {payment?.currency || 'NGN'}</span>
                        </div>
                        {payment?.status === 'pending' && (
                            <div className="flex items-center justify-between">
                                <span className="text-gray-600">VAT ({formatVatRate(payment?.vat_rate)}%)</span>
                                <span className="font-medium">{formatCurrencyWithSymbol(payment?.vat_amount || 0)} {payment?.currency || 'NGN'}</span>
                            </div>
                        )}
                        <div className="flex items-center justify-between border-t border-gray-200 pt-3">
                            <span className="font-medium text-gray-900">Total amount</span>
                            <span className="font-semibold">{formatCurrencyWithSymbol(payment?.total_amount || 0)} {payment?.currency || 'NGN'}</span>
                        </div>
                    </div>

                    {payment?.checkout_mode === 'v4' && payment.status === 'pending' && (
                        <div className="mb-4 rounded-lg border border-blue-100 bg-blue-50 p-4">
                            <label className="block text-sm font-medium text-gray-700" htmlFor="v4-payment-method">
                                Payment method
                            </label>
                            <select
                                id="v4-payment-method"
                                value={v4PaymentMethod}
                                onChange={(event) => setV4PaymentMethod(event.target.value as V4PaymentMethodType)}
                                className="mt-2 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm"
                            >
                                <option value="bank_transfer">Bank transfer</option>
                                <option value="bank_account">Bank account</option>
                                <option value="card">Card</option>
                                <option value="ussd">USSD</option>
                                <option value="opay">OPay</option>
                            </select>

                            {v4PaymentMethod === 'ussd' && (
                                <select
                                    value={ussdBankCode}
                                    onChange={(event) => setUssdBankCode(event.target.value)}
                                    className="mt-3 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm"
                                >
                                    <option value="">Select your bank</option>
                                    {ussdBanks.map((bank) => (
                                        <option key={bank.code || bank.name} value={bank.code}>{bank.name}</option>
                                    ))}
                                </select>
                            )}

                            {v4PaymentMethod === 'card' && (
                                <div className="mt-3 space-y-3">
                                    <input
                                        value={v4Card.cardNumber}
                                        onChange={(event) => {
                                            const digits = event.target.value.replace(/\D/g, '').slice(0, 19)
                                            const pasted = digits.length - v4Card.cardNumber.length > 1
                                            setV4Card((current) => ({ ...current, cardNumber: digits }))
                                            if (digits.length === 19 || (pasted && digits.length >= 15)) {
                                                v4CardMonthRef.current?.focus()
                                            }
                                        }}
                                        placeholder="Card number"
                                        inputMode="numeric"
                                        maxLength={19}
                                        className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm"
                                    />
                                    <div className="grid gap-3 grid-cols-3">
                                        <input
                                            ref={v4CardMonthRef}
                                            value={v4Card.expiryMonth}
                                            onChange={(event) => {
                                                const digits = event.target.value.replace(/\D/g, '').slice(0, 2)
                                                setV4Card((current) => ({ ...current, expiryMonth: digits }))
                                                if (digits.length === 2) v4CardYearRef.current?.focus()
                                            }}
                                            placeholder="MM"
                                            inputMode="numeric"
                                            maxLength={2}
                                            className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm"
                                        />
                                        <input
                                            ref={v4CardYearRef}
                                            value={v4Card.expiryYear}
                                            onChange={(event) => {
                                                const digits = event.target.value.replace(/\D/g, '').slice(0, 2)
                                                setV4Card((current) => ({ ...current, expiryYear: digits }))
                                                if (digits.length === 2) v4CardCvvRef.current?.focus()
                                            }}
                                            placeholder="YY"
                                            inputMode="numeric"
                                            maxLength={2}
                                            className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm"
                                        />
                                        <input
                                            ref={v4CardCvvRef}
                                            value={v4Card.cvv}
                                            onChange={(event) => setV4Card((current) => ({ ...current, cvv: event.target.value.replace(/\D/g, '').slice(0, 3) }))}
                                            placeholder="CVV"
                                            inputMode="numeric"
                                            maxLength={3}
                                            className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm"
                                        />
                                    </div>
                                </div>
                            )}
                        </div>
                    )}

                    {v4PaymentInstructions && (
                        <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
                            <p className="font-semibold">
                                {v4NextAction?.type === 'requires_bank_transfer'
                                    ? 'Complete your bank transfer'
                                    : 'Complete your payment'}
                            </p>
                            {(v4PaymentInstructions.amount || v4PaymentInstructions.account_number) && (
                                <>
                                    <p className="mt-2">
                                        Transfer exactly {formatCurrencyWithSymbol(v4PaymentInstructions.amount || payment?.total_amount || 0)} {payment?.currency || 'NGN'} to:
                                    </p>
                                    <p className="mt-2">Account: {v4PaymentInstructions.account_number || 'See the payment instructions below'}</p>
                                    <p>Bank: {v4PaymentInstructions.account_bank_name || v4PaymentInstructions.bank_name || 'Flutterwave'}</p>
                                </>
                            )}
                            {(v4PaymentInstructions.account_name || v4PaymentInstructions.account_display_name) && (
                                <p>Account name: {v4PaymentInstructions.account_name || v4PaymentInstructions.account_display_name}</p>
                            )}
                            {v4PaymentInstructions.account_expiration_datetime && (
                                <p className="mt-2">Expires: {new Date(v4PaymentInstructions.account_expiration_datetime).toLocaleString()}</p>
                            )}
                            {v4PaymentInstructions.note && <p className="mt-2">{v4PaymentInstructions.note}</p>}
                            <p className="mt-2">Your subscription activates automatically once the transfer is confirmed.</p>
                        </div>
                    )}

                    {v4RequiresAuthorization
                        && !['completed', 'failed', 'cancelled'].includes(payment?.status || '') && (
                            <div className="mb-4 rounded-lg border border-blue-100 bg-blue-50 p-4">
                                <label className="block text-sm font-medium text-gray-700" htmlFor="v4-authorization">
                                    {v4AuthorizationType === 'requires_pin' ? 'Card Transaction PIN' : 'Bank OTP'}
                                </label>
                                <div className="relative mt-2">
                                    <input
                                        id="v4-authorization"
                                        type={showV4Authorization ? 'text' : 'password'}
                                        inputMode="numeric"
                                        value={v4AuthorizationType === 'requires_pin' ? v4Pin : v4Otp}
                                        onChange={(event) => v4AuthorizationType === 'requires_pin'
                                            ? setV4Pin(event.target.value)
                                            : setV4Otp(event.target.value)}
                                        placeholder={v4AuthorizationType === 'requires_pin' ? 'Enter your card PIN' : 'Enter OTP sent to the registered mobile on your bank account'}
                                        className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 pr-11 text-sm"
                                    />
                                    <button
                                        type="button"
                                        onClick={() => setShowV4Authorization((current) => !current)}
                                        aria-label={showV4Authorization ? 'Hide authorization code' : 'Show authorization code'}
                                        className="absolute inset-y-0 right-0 flex items-center px-3 text-gray-500 hover:text-gray-700"
                                    >
                                        {showV4Authorization ? (
                                            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5">
                                                <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" />
                                                <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
                                                <path d="M14.12 14.12a3 3 0 1 1-4.24-4.24" />
                                                <line x1="1" y1="1" x2="23" y2="23" />
                                            </svg>
                                        ) : (
                                            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5">
                                                <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                                                <circle cx="12" cy="12" r="3" />
                                            </svg>
                                        )}
                                    </button>
                                </div>
                                <button
                                    type="button"
                                    onClick={() => void authorizeV4Payment()}
                                    disabled={isAuthorizing}
                                    className="mt-3 w-full rounded-lg bg-blue-600 px-4 py-3 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                                >
                                    {isAuthorizing ? 'Authorizing…' : 'Authorize Payment'}
                                </button>
                                {v4AuthorizationType === 'requires_otp' && (
                                    <p className="mt-3 text-xs text-gray-600">
                                        Didn&apos;t receive the OTP?{' '}
                                        <button
                                            type="button"
                                            onClick={() => void cancelPayment()}
                                            disabled={isCancelling}
                                            className="font-medium text-blue-700 underline hover:text-blue-800 disabled:opacity-50"
                                        >
                                            {isCancelling ? 'Cancelling…' : 'Cancel this payment'}
                                        </button>
                                        {' '}and start a new card payment to get a fresh OTP.
                                    </p>
                                )}
                            </div>
                        )}

                    {payment?.status === 'completed' ? (
                        <div className="p-4 rounded-lg bg-green-50 text-green-800 mb-4">
                            Payment successful. Your subscription is active.
                        </div>
                    ) : payment?.status === 'failed' || payment?.status === 'cancelled' ? (
                        <div className="p-4 rounded-lg bg-red-50 text-red-800 mb-4">
                            {payment.status_detail || `Payment ${payment.status}. You can try again.`}
                        </div>
                    ) : pendingInfoMessage ? (
                        <div className="p-4 rounded-lg bg-blue-50 text-blue-800 mb-4">
                            {pendingInfoMessage}
                        </div>
                    ) : null}

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
                        <div className={`grid gap-3 ${v4RequiresFollowUp ? '' : 'sm:grid-cols-2'}`}>
                            {!v4RequiresFollowUp && (
                                <button
                                    onClick={() => void startCheckout()}
                                    disabled={isStarting || isCancelling}
                                    className="w-full bg-blue-600 text-white py-3 px-4 rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                                >
                                    {isStarting ? 'Starting…' : 'Continue Payment'}
                                </button>
                            )}
                            <button
                                onClick={() => void cancelPayment()}
                                disabled={isStarting || isCancelling}
                                className="w-full rounded-lg border border-red-200 bg-red-50 px-4 py-3 font-medium text-red-700 transition-colors hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-50"
                            >
                                {isCancelling ? 'Cancelling…' : 'Cancel Payment'}
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
        </div >
    )
}
