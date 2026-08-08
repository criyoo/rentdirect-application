import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'
import { useAppPopup } from '@/contexts/AppPopupContext'
import { User } from '@/types'
import { formatCurrencyWithSymbol } from '@/utils/currency'
import { EncryptedFlutterwaveCard, encryptFlutterwaveCard, validateCardDetails } from '@/lib/flutterwaveEncryption'
import DashboardBackButton from '@/components/DashboardBackButton'

type Payment = {
    id: string
    booking_id?: string
    amount: number | string
    currency: string
    status: string
    payment_method?: string
    created_at: string
}

type SubscriptionPaymentRecord = {
    id: string
    role: BillingRole
    plan_code: PlanCode
    billing_cycle: BillingCycle
    amount: number | string
    currency: string
    status: string
    expires_at?: string | null
    payment_date?: string | null
    transaction_id?: string | null
    recurring_enabled?: boolean
    next_action_url?: string
    payment_method?: SubscriptionPaymentMethod | null
    created_at: string
}

type SubscriptionPaymentMethod = {
    id: string
    payment_type: string
    status: string
    card_last4?: string
    card_network?: string
    card_expiry_month?: number | null
    card_expiry_year?: number | null
}

type RecurringConfig = {
    enabled: boolean
    encryption_key: string
}

type BillingHistoryRecord = {
    type: 'subscription' | 'rental'
    id: string
    amount: number | string
    currency: string
    status: string
    created_at: string
    title: string
    transaction_id?: string | null
    role?: BillingRole
    plan_code?: PlanCode
    billing_cycle?: BillingCycle
    payment_date?: string | null
    expires_at?: string | null
}

type PaginatedResponse<T> = {
    results?: T[]
}

type BillingCycle = 'monthly' | 'yearly'
type BillingRole = 'tenant' | 'landlord'
type PlanCode = 'bronze' | 'silver' | 'gold' | 'platinum'
type PlanPricing = Record<BillingCycle, number>
type SubscriptionPricingCatalog = Record<BillingRole, Record<PlanCode, PlanPricing>>

type PlanBlueprint = {
    code: PlanCode
    name: string
    badge: string
    summary: string
    audience: string
    highlight?: boolean
    accentClassName: string
    features: string[]
}

const tenantSubscriptionBlueprints: PlanBlueprint[] = [
    {
        code: 'bronze',
        badge: 'Free',
        name: 'Bronze',
        summary: 'Free 14-day access.',
        audience: 'For first-time tenants exploring verified properties.',
        highlight: false,
        accentClassName: 'from-orange-700 to-amber-900',
        features: [
            '14 days free access',
            'Browse all properties',
            'Add properties to favourites',
            'Browse landlord profiles',
            'Browse landlord properties',
            'Send feedback, raise complaints',
            'Raise support tickets',
            'Up to 7 days response time'
        ],
    },
    {
        code: 'silver',
        badge: 'Starter',
        name: 'Silver',
        summary: 'Starter tenant access.',
        audience: 'For tenants ready to contact landlords and inspect homes.',
        accentClassName: 'from-zinc-400 to-zinc-600',
        features: [
            'Everything in bronze plan, plus:',
            'Contact landlords',
            'Arrange property viewing',
            'Rent property through RentDirect',
            'See property location and map',
            'Instant property enquiries',
            'Track rental progress',
            'Up to 3 days response time',
        ],
    },
    {
        code: 'gold',
        badge: 'Most Flexible',
        name: 'Gold',
        summary: 'For stronger rental coordination.',
        audience: 'For tenants who want community and review tools.',
        highlight: true,
        accentClassName: 'from-yellow-400 to-amber-600',
        features: [
            'Everything in silver plan, plus:',
            'Access community chat room',
            'Review landlords',
            'See property verification badge',
            'Priority issue handling',
            'Up to 24hrs response time',
        ],
    },
    {
        code: 'platinum',
        badge: 'Premium',
        name: 'Platinum',
        summary: 'Stronger trust & faster support.',
        audience: 'For tenants who want maximum visibility before renting.',
        accentClassName: 'from-blue-600 to-purple-700',
        features: [
            'Everything in gold plan, plus:',
            'See landlord verification badge',
            'See category verification score ',
            'Premium rental workflow support',
            'Up to 4hrs response time',
        ],
    },
]

const landlordSubscriptionBlueprints: PlanBlueprint[] = [
    {
        code: 'bronze',
        badge: 'Free',
        name: 'Bronze',
        summary: 'Free 14-day access.',
        audience: 'Best for first-time listers to try.',
        accentClassName: 'from-orange-700 to-amber-900',
        features: [
            '14 days free access',
            'List one property',
            'Give feedback, raise complaints',
            'Raise support tickets',
            'See tenant profile',
            'Up to 7 days response time',
        ],
    },
    {
        code: 'silver',
        badge: 'Starter',
        name: 'Silver',
        summary: 'Starter landlord access',
        audience: 'For landlords ready to unboard tenant.',
        accentClassName: 'from-zinc-400 to-zinc-600',
        features: [
            'Everything in free plan, plus:',
            'Create multiple property listings',
            'Receive tenant enquiries',
            'Chat with verified tenants',
            'Track active rental requests',
            'Track end-to-end rental progress',
            'View payment records',
            'Manage booking activity',
            'Up to 5 days response time',
        ],
    },
    {
        code: 'gold',
        badge: 'Most Flexible',
        name: 'Gold',
        summary: 'Landlords with active demand.',
        audience: 'For landlords with growing occupancy.',
        highlight: true,
        accentClassName: 'from-yellow-400 to-amber-600',
        features: [
            'Everything in silver plan, plus:',
            'Access landlord community chat',
            'See tenant verification insights',
            'Feature properties on home page',
            'Property verification workflows',
            'Up to 3 days response time',
        ],
    },
    {
        code: 'platinum',
        badge: 'Premium',
        name: 'Platinum',
        summary: 'Advanced landlord operations.',
        audience: 'For portfolio landlords management',
        accentClassName: 'from-blue-600 to-purple-700',
        features: [
            'Everything in gold plan, plus:',
            'Priority property exposure',
            'Deeper tenant screening visibility',
            'See tenant verification category',
            'High confidence verification',
            '24 hrs turnaround support',
        ],
    },
]
function normalizeResults<T>(payload: T[] | PaginatedResponse<T> | undefined): T[] {
    if (!payload) {
        return []
    }
    if (Array.isArray(payload)) {
        return payload
    }
    return Array.isArray(payload.results) ? payload.results : []
}

function extractErrorMessage(error: any, fallback: string) {
    if (typeof error?.response?.data === 'string') {
        return error.response.data
    }

    const detail = error?.response?.data?.detail
    if (detail) {
        return detail
    }

    const firstError = Object.values(error?.response?.data || {}).flat().find(Boolean)
    return typeof firstError === 'string' ? firstError : error?.message || fallback
}

function capitalizePlanName(planCode: PlanCode) {
    return planCode.charAt(0).toUpperCase() + planCode.slice(1)
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

function formatReceiptCurrency(amount: number | string, currency = 'NGN') {
    const normalizedCurrency = String(currency || 'NGN').toUpperCase()
    try {
        return new Intl.NumberFormat('en-NG', {
            style: 'currency',
            currency: normalizedCurrency,
            currencyDisplay: 'code',
        }).format(Number(amount || 0)).replace(/\s+/g, ' ')
    } catch {
        return `${normalizedCurrency} ${Number(amount || 0).toLocaleString('en-NG')}`
    }
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

export default function BillingPage() {
    const navigate = useNavigate()
    const queryClient = useQueryClient()
    const { confirm } = useAppPopup()
    const [billingCycle, setBillingCycle] = useState<BillingCycle>('monthly')
    const [from, setFrom] = useState('')
    const [to, setTo] = useState('')
    const [autoRenew, setAutoRenew] = useState(false)
    const [selectedPaymentMethodId, setSelectedPaymentMethodId] = useState('')
    const [isPreparingRecurringPayment, setIsPreparingRecurringPayment] = useState(false)
    const [cardForm, setCardForm] = useState({
        cardNumber: '',
        expiryMonth: '',
        expiryYear: '',
        cvv: '',
    })

    const { data: me, isLoading: isUserLoading, isError: isUserError } = useQuery({
        queryKey: ['users', 'me'],
        queryFn: async () => (await api.get<User>('/users/me')).data,
    })
    const { data: subscriptionPricingCatalog, isLoading: isPricingLoading, isError: isPricingError } = useQuery({
        queryKey: ['subscription-pricing'],
        queryFn: async () => (await api.get<SubscriptionPricingCatalog>('/users/subscription-pricing')).data,
    })
    const { data: recurringConfig } = useQuery({
        queryKey: ['subscription-recurring-config'],
        queryFn: async () => (await api.get<RecurringConfig>('/subscriptions/recurring/config')).data,
        enabled: Boolean(me?.role === 'tenant' || me?.role === 'landlord'),
    })
    const { data: paymentMethods = [] } = useQuery({
        queryKey: ['subscription-payment-methods'],
        queryFn: async () => (await api.get<SubscriptionPaymentMethod[]>('/subscriptions/payment-methods')).data,
        enabled: Boolean(me?.role === 'tenant' || me?.role === 'landlord'),
    })

    const { data: paymentResponse, isLoading: isPaymentsLoading } = useQuery({
        queryKey: ['payments'],
        queryFn: async () => (await api.get<Payment[] | PaginatedResponse<Payment>>('/payments')).data,
    })
    const { data: subscriptionPaymentResponse, isLoading: isSubscriptionPaymentsLoading } = useQuery({
        queryKey: ['subscription-payments'],
        queryFn: async () => (await api.get<SubscriptionPaymentRecord[] | PaginatedResponse<SubscriptionPaymentRecord>>('/subscriptions')).data,
    })

    const payments = useMemo(() => normalizeResults(paymentResponse), [paymentResponse])
    const subscriptionPayments = useMemo(
        () => normalizeResults(subscriptionPaymentResponse),
        [subscriptionPaymentResponse],
    )
    const pendingSubscriptionPayments = useMemo(
        () => subscriptionPayments.filter((payment) => payment.status === 'pending'),
        [subscriptionPayments],
    )
    const currentSubscription = useMemo(() => {
        const now = Date.now()
        const completedPayments = subscriptionPayments
            .filter((payment) => payment.status === 'completed')
            .sort((left, right) => {
                const leftTimestamp = new Date(left.payment_date || left.created_at).getTime()
                const rightTimestamp = new Date(right.payment_date || right.created_at).getTime()
                return rightTimestamp - leftTimestamp
            })

        const activePayment = completedPayments.find((payment) => {
            if (!payment.expires_at) {
                return false
            }
            return new Date(payment.expires_at).getTime() >= now
        })

        return activePayment || completedPayments[0] || null
    }, [subscriptionPayments])
    const billingHistory = useMemo<BillingHistoryRecord[]>(
        () => [
            ...subscriptionPayments.map((payment) => ({
                type: 'subscription' as const,
                id: payment.id,
                amount: payment.amount,
                currency: payment.currency,
                status: payment.status,
                created_at: payment.created_at,
                title: `${payment.plan_code.charAt(0).toUpperCase()}${payment.plan_code.slice(1)} ${payment.billing_cycle} subscription`,
                transaction_id: payment.transaction_id,
                role: payment.role,
                plan_code: payment.plan_code,
                billing_cycle: payment.billing_cycle,
                payment_date: payment.payment_date,
                expires_at: payment.expires_at,
            })),
            ...payments.map((payment) => ({
                type: 'rental' as const,
                id: payment.id,
                amount: payment.amount,
                currency: payment.currency,
                status: payment.status,
                created_at: payment.created_at,
                title: 'Rental payment',
            })),
        ].sort((left, right) => new Date(right.created_at).getTime() - new Date(left.created_at).getTime()),
        [payments, subscriptionPayments],
    )
    const filteredPayments = useMemo(() => {
        if (!from && !to) {
            return billingHistory
        }

        const fromTimestamp = from ? new Date(from).getTime() : null
        const toTimestamp = to ? new Date(to).getTime() : null

        return billingHistory.filter((payment) => {
            const createdAt = new Date(payment.created_at).getTime()
            if (fromTimestamp && createdAt < fromTimestamp) {
                return false
            }
            if (toTimestamp) {
                const endOfSelectedDay = new Date(to)
                endOfSelectedDay.setHours(23, 59, 59, 999)
                if (createdAt > endOfSelectedDay.getTime()) {
                    return false
                }
            }
            return true
        })
    }, [billingHistory, from, to])

    const dashboardHref = me?.role === 'landlord'
        ? `/dashboard/landlord/${me.id}`
        : me?.role === 'tenant'
            ? `/dashboard/tenant/${me.id}`
            : '/'
    const profileHref = me?.id ? `/profile/${me.id}` : '/dashboard/settings'
    const activeBillingRole: BillingRole = me?.role === 'landlord' ? 'landlord' : 'tenant'
    const subscriptionBlueprints = activeBillingRole === 'landlord'
        ? landlordSubscriptionBlueprints
        : tenantSubscriptionBlueprints
    const subscriptionPricing = subscriptionPricingCatalog?.[activeBillingRole]
    const startSubscriptionCheckout = useMutation({
        mutationFn: async ({ planCode, cycle, recurring, card, paymentMethodId }: { planCode: PlanCode; cycle: BillingCycle; recurring?: boolean; card?: EncryptedFlutterwaveCard; paymentMethodId?: string }) => {
            const response = await api.post<SubscriptionPaymentRecord>('/subscriptions/request', {
                plan_code: planCode,
                billing_cycle: cycle,
                recurring: Boolean(recurring),
                ...(card ? { card } : {}),
                ...(paymentMethodId ? { payment_method_id: paymentMethodId } : {}),
            })
            return response.data
        },
        onSuccess: (payment) => {
            void queryClient.invalidateQueries({ queryKey: ['subscription-payments'] })
            void queryClient.invalidateQueries({ queryKey: ['subscription-payment-methods'] })
            if (payment.status === 'failed') {
                alert('Recurring subscription payment failed. Check the card details or use standard checkout.')
                return
            }
            if (payment.status === 'completed') {
                return
            }
            if (payment.next_action_url) {
                window.location.assign(payment.next_action_url)
                return
            }
            if (payment.recurring_enabled) {
                alert('Recurring payment was submitted and is pending provider confirmation.')
                return
            }
            navigate(`/billing/subscriptions/pay/${payment.id}`)
        },
        onError: (error) => {
            alert(extractErrorMessage(error, 'Unable to start subscription checkout.'))
        },
    })
    const cancelSubscriptionPayment = useMutation({
        mutationFn: async (paymentId: string) => {
            const response = await api.post<SubscriptionPaymentRecord>(`/subscriptions/${paymentId}/cancel`)
            return response.data
        },
        onSuccess: () => {
            void queryClient.invalidateQueries({ queryKey: ['subscription-payments'] })
        },
        onError: (error) => {
            alert(extractErrorMessage(error, 'Unable to cancel payment.'))
        },
    })
    const retrySubscriptionPayment = useMutation({
        mutationFn: async (payment: SubscriptionPaymentRecord) => {
            await api.post<SubscriptionPaymentRecord>(`/subscriptions/${payment.id}/cancel`)
            const response = await api.post<SubscriptionPaymentRecord>('/subscriptions/request', {
                plan_code: payment.plan_code,
                billing_cycle: payment.billing_cycle,
            })
            return response.data
        },
        onSuccess: (payment) => {
            void queryClient.invalidateQueries({ queryKey: ['subscription-payments'] })
            if (payment.status !== 'completed') {
                navigate(`/billing/subscriptions/pay/${payment.id}`)
            }
        },
        onError: (error) => {
            alert(extractErrorMessage(error, 'Unable to retry payment.'))
        },
    })
    const disableRecurringPayment = useMutation({
        mutationFn: async (paymentId: string) => {
            const response = await api.post<SubscriptionPaymentRecord>(`/subscriptions/${paymentId}/disable-recurring`)
            return response.data
        },
        onSuccess: () => {
            void queryClient.invalidateQueries({ queryKey: ['subscription-payments'] })
        },
        onError: (error) => {
            alert(extractErrorMessage(error, 'Unable to turn off auto-renew.'))
        },
    })
    const isSubscriptionActionPending =
        startSubscriptionCheckout.isPending ||
        isPreparingRecurringPayment ||
        cancelSubscriptionPayment.isPending ||
        retrySubscriptionPayment.isPending ||
        disableRecurringPayment.isPending

    const continueSubscriptionPayment = (payment: SubscriptionPaymentRecord) => {
        if (payment.next_action_url) {
            window.location.assign(payment.next_action_url)
            return
        }
        if (payment.recurring_enabled) {
            void queryClient.invalidateQueries({ queryKey: ['subscription-payments'] })
            return
        }
        navigate(`/billing/subscriptions/pay/${payment.id}`)
    }

    const cancelAndRetrySubscriptionPayment = async (payment: SubscriptionPaymentRecord) => {
        const shouldRetry = await confirm(
            `This will cancel the pending ${capitalizePlanName(payment.plan_code)} payment and start a new payment attempt for the same plan. Do you want to continue?`,
            {
                title: 'Cancel and retry payment?',
                variant: 'warning',
                cancelLabel: 'Cancel',
                confirmLabel: 'Continue',
            },
        )
        if (shouldRetry) {
            retrySubscriptionPayment.mutate(payment)
        }
    }

    const completelyCancelSubscriptionPayment = async (payment: SubscriptionPaymentRecord) => {
        const shouldCancel = await confirm(
            `This will completely cancel the pending ${capitalizePlanName(payment.plan_code)} payment. Do you want to continue?`,
            {
                title: 'Cancel pending payment?',
                variant: 'warning',
                cancelLabel: 'Cancel',
                confirmLabel: 'Continue',
            },
        )
        if (shouldCancel) {
            cancelSubscriptionPayment.mutate(payment.id)
        }
    }

    const turnOffAutoRenew = async (payment: SubscriptionPaymentRecord) => {
        const shouldDisable = await confirm(
            `This will stop automatic renewal for your ${capitalizePlanName(payment.plan_code)} subscription. Your current access remains active until it expires.`,
            {
                title: 'Turn off auto-renew?',
                variant: 'warning',
                cancelLabel: 'Cancel',
                confirmLabel: 'Turn Off',
            },
        )
        if (shouldDisable) {
            disableRecurringPayment.mutate(payment.id)
        }
    }

    const handleChoosePlan = async (plan: PlanBlueprint, cycle: BillingCycle) => {
        const isCurrentPlan =
            currentSubscription?.plan_code === plan.code &&
            currentSubscription?.billing_cycle === cycle &&
            currentSubscription?.status === 'completed'
        if (isCurrentPlan || isSubscriptionActionPending) {
            return
        }

        const pendingForPlan = pendingSubscriptionPayments.find(
            (payment) => payment.plan_code === plan.code && payment.billing_cycle === cycle,
        )
        if (pendingForPlan) {
            continueSubscriptionPayment(pendingForPlan)
            return
        }

        if (pendingSubscriptionPayments.length > 0) {
            alert('You already have a pending payment. Continue it, cancel and retry it, or completely cancel it before choosing another plan.')
            return
        }

        const hasActiveCurrentSubscription = Boolean(
            currentSubscription?.status === 'completed' &&
            currentSubscription?.expires_at &&
            new Date(currentSubscription.expires_at).getTime() >= Date.now(),
        )

        if (hasActiveCurrentSubscription) {
            const currentPlanName = subscriptionBlueprints.find((item) => item.code === currentSubscription?.plan_code)?.name || currentSubscription?.plan_code || 'current'
            const shouldContinue = await confirm(
                `You are about to choose a new plan, your current plan ${currentPlanName} will be automatically cancelled and you will loose any remaining days and money on your current plan. ${plan.name} plan will begin immediately payment is confirmed. Do you want to continue?`,
                {
                    title: 'Change subscription plan?',
                    variant: 'warning',
                    cancelLabel: 'Cancel',
                    confirmLabel: 'Continue',
                },
            )
            if (!shouldContinue) {
                return
            }
        }

        const selectedAmount = Number(subscriptionPricing?.[plan.code]?.[cycle] || 0)
        if (autoRenew && selectedAmount > 0) {
            if (selectedPaymentMethodId) {
                startSubscriptionCheckout.mutate({
                    planCode: plan.code,
                    cycle,
                    recurring: true,
                    paymentMethodId: selectedPaymentMethodId,
                })
                return
            }
            if (!recurringConfig?.enabled || !recurringConfig.encryption_key) {
                alert('Recurring card payments are not configured right now. Use standard checkout for this payment.')
                return
            }
            const validationError = validateCardDetails(cardForm)
            if (validationError) {
                alert(validationError)
                return
            }

            setIsPreparingRecurringPayment(true)
            try {
                const encryptedCard = await encryptFlutterwaveCard(cardForm, recurringConfig.encryption_key)
                startSubscriptionCheckout.mutate({ planCode: plan.code, cycle, recurring: true, card: encryptedCard })
            } catch (error: any) {
                alert(error?.message || 'Unable to encrypt card details.')
            } finally {
                setIsPreparingRecurringPayment(false)
            }
            return
        }

        startSubscriptionCheckout.mutate({ planCode: plan.code, cycle })
    }

    const downloadSubscriptionReceipt = (payment: BillingHistoryRecord) => {
        if (payment.type !== 'subscription') {
            return
        }

        const rawPaymentDate = new Date(payment.payment_date || payment.created_at)
        const receiptDate = Number.isNaN(rawPaymentDate.getTime()) ? new Date() : rawPaymentDate
        const receiptLines = [
            'RENTDIRECT - SUBSCRIPTION RECEIPT',
            '==================================',
            '',
            'TRANSACTION DETAILS:',
            `Receipt No: ${receiptValue(payment.id)}`,
            `Transaction ID: ${receiptValue(payment.transaction_id)}`,
            `Date: ${formatReceiptDate(receiptDate)}`,
            `Time: ${formatReceiptTime(receiptDate)}`,
            '',
            'SUBSCRIPTION DETAILS:',
            `Plan: ${receiptValue(payment.plan_code ? capitalizePlanName(payment.plan_code) : null)}`,
            `Billing Cycle: ${receiptValue(payment.billing_cycle)}`,
            `Role: ${receiptValue(payment.role)}`,
            `Status: ${receiptValue(payment.status).toUpperCase()}`,
            `Expires At: ${payment.expires_at ? receiptValue(new Date(payment.expires_at).toLocaleString()) : 'N/A'}`,
            '',
            'PAYMENT DETAILS:',
            `Amount Paid: ${formatReceiptCurrency(payment.amount, payment.currency)}`,
            `Currency: ${receiptValue(payment.currency).toUpperCase()}`,
            '',
            'CUSTOMER DETAILS:',
            `Name: ${receiptValue(me?.name)}`,
            `Email: ${receiptValue(me?.email)}`,
            '',
            '==================================',
            'Thank you for using RentDirect!',
        ]

        const blob = buildReceiptPdf(receiptLines)
        const url = window.URL.createObjectURL(blob)
        const anchor = document.createElement('a')
        anchor.href = url
        anchor.download = `subscription-receipt-${payment.id}-${receiptDate.toISOString().split('T')[0]}.pdf`
        document.body.appendChild(anchor)
        anchor.click()
        document.body.removeChild(anchor)
        window.URL.revokeObjectURL(url)
    }

    const comparisonRows = useMemo(
        () => {
            if (!subscriptionPricing) {
                return []
            }

            return [
                { label: 'Free plan duration', values: subscriptionBlueprints.map((plan) => plan.code === 'bronze' ? '14 days' : '-') },
                {
                    label: 'Monthly billing',
                    values: subscriptionBlueprints.map((plan) => formatCurrencyWithSymbol(subscriptionPricing[plan.code].monthly)),
                },
                {
                    label: 'Yearly billing',
                    values: subscriptionBlueprints.map((plan) => formatCurrencyWithSymbol(subscriptionPricing[plan.code].yearly)),
                },
                { label: 'Checkout', values: subscriptionBlueprints.map((plan) => plan.code === 'bronze' ? 'Instant activation' : 'Flutterwave checkout') },
                { label: 'Tenant access', values: subscriptionBlueprints.map(() => activeBillingRole === 'tenant' ? 'Yes' : '-') },
                { label: 'Landlord access', values: subscriptionBlueprints.map(() => activeBillingRole === 'landlord' ? 'Yes' : '-') },
            ]
        },
        [activeBillingRole, subscriptionBlueprints, subscriptionPricing],
    )

    if (isUserLoading || isPricingLoading) {
        return (
            <div className="container-modern py-8">
                <div className="rounded-2xl border bg-white p-6 text-gray-600">Loading billing details...</div>
            </div>
        )
    }

    if (isUserError || isPricingError || !me || !subscriptionPricing) {
        return (
            <div className="container-modern py-8">
                <div className="rounded-2xl border bg-white p-6 text-gray-600">Unable to load billing details right now.</div>
            </div>
        )
    }

    return (
        <div className="container-modern py-8">
            <div className="mx-auto max-w-7xl">
                <section className="overflow-hidden rounded-[2rem] border border-slate-200 bg-[radial-gradient(circle_at_top_left,_rgba(59,130,246,0.18),_transparent_35%),linear-gradient(135deg,#f8fbff_0%,#eef4ff_45%,#ffffff_100%)] p-6 shadow-sm md:p-10">
                    <div className="grid gap-8 lg:grid-cols-[1.25fr_0.75fr] lg:items-start">
                        <div>
                            <div className="inline-flex items-center rounded-full border border-blue-200 bg-white/80 px-4 py-2 text-xs font-semibold uppercase tracking-[0.24em] text-blue-700">
                                Shared billing center
                            </div>
                            <h1 className="mt-5 max-w-3xl text-4xl font-bold tracking-tight text-slate-950 md:text-5xl">
                                Subscription Plans
                            </h1>
                            <p className="mt-4 max-w-2xl text-base leading-7 text-slate-600 md:text-lg">
                                Start with 14 days free or subscribe to one of our monthly or yearly plans.
                            </p>

                            <div className="mt-8 flex flex-wrap items-center gap-3">
                                <button
                                    type="button"
                                    onClick={() => setBillingCycle('monthly')}
                                    className={`rounded-full px-4 py-2 text-sm font-medium transition-colors ${billingCycle === 'monthly'
                                        ? 'bg-slate-950 text-white'
                                        : 'bg-white text-slate-700 ring-1 ring-slate-200 hover:bg-slate-50'
                                        }`}
                                >
                                    Monthly billing
                                </button>
                                <button
                                    type="button"
                                    onClick={() => setBillingCycle('yearly')}
                                    className={`rounded-full px-4 py-2 text-sm font-medium transition-colors ${billingCycle === 'yearly'
                                        ? 'bg-slate-950 text-white'
                                        : 'bg-white text-slate-700 ring-1 ring-slate-200 hover:bg-slate-50'
                                        }`}
                                >
                                    Yearly billing
                                </button>
                            </div>

                            <div className="mt-10 grid gap-4 sm:grid-cols-3">
                                <div className="rounded-2xl border border-white/70 bg-white/85 p-4 shadow-sm">
                                    <p className="text-sm font-medium text-slate-500">Free plan</p>
                                    <p className="mt-3 text-3xl font-bold text-slate-950">14 days</p>
                                    <p className="mt-2 text-sm text-slate-600">Start free, then continue on a monthly or yearly plan.</p>
                                </div>
                                <div className="rounded-2xl border border-white/70 bg-white/85 p-4 shadow-sm">
                                    <p className="text-sm font-medium text-slate-500">Billing cycle</p>
                                    <p className="mt-3 text-3xl font-bold capitalize text-slate-950">{billingCycle}</p>
                                    <p className="mt-2 text-sm text-slate-600">Subscription starts today & expires after your billing cycle.</p>
                                </div>
                                <div className="rounded-2xl border border-white/70 bg-white/85 p-4 shadow-sm">
                                    <p className="text-sm font-medium text-slate-500">Account role</p>
                                    <p className="mt-3 text-3xl font-bold capitalize text-slate-950">{me?.role || 'user'}</p>
                                    <p className="mt-2 text-sm text-slate-600">Subscription Plan for {me?.role || 'user'}</p>
                                </div>
                            </div>
                        </div>

                        <div className="rounded-[1.75rem] border border-slate-200 bg-slate-950 p-6 text-white shadow-xl">
                            <p className="text-sm font-medium uppercase tracking-[0.24em] text-sky-300">Launch note</p>
                            <h2 className="mt-4 text-2xl font-semibold">Immediate Account activation</h2>
                            <p className="mt-4 text-sm leading-7 text-slate-300">
                                Your account is activated immediately after payment {me?.role === 'tenant' ? ' and you can start your rental journey right away.' : ' and your property listing can begin enabling.'}
                            </p>

                            <div className="mt-6 space-y-3">
                                <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                                    <p className="text-sm font-semibold text-white">Payments</p>
                                    <p className="mt-3 space-y-2 text-sm text-slate-300">
                                        All payments are process by a payment gateway
                                        and notification are sent immediately rentdirect
                                        receives confirmation of a successful transaction.
                                        Payment history is displayed in your dashboard
                                        with option to download payment receipt
                                    </p>
                                </div>
                                <div className="flex flex-wrap gap-3">
                                    <DashboardBackButton to={profileHref} label="Back to profile" />
                                    <Link to={dashboardHref} className="rounded-full border border-white/20 px-4 py-2 text-sm font-medium text-white transition hover:bg-white/10">
                                        Open dashboard
                                    </Link>
                                </div>
                            </div>
                        </div>
                    </div>
                </section>

                {pendingSubscriptionPayments.length > 0 && (
                    <section className="mt-10 rounded-[1.75rem] border border-amber-200 bg-amber-50 p-6 shadow-sm">
                        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                            <div>
                                <span className="inline-flex rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-amber-800">
                                    Pending payment
                                </span>
                                <h2 className="mt-4 text-2xl font-bold text-slate-950">Complete, retry, or cancel your payment</h2>
                                <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
                                    If payment was delayed or interrupted, continue with the same attempt, cancel and retry, or completely cancel it before choosing another plan.
                                </p>
                            </div>
                        </div>

                        <div className="mt-5 grid gap-4">
                            {pendingSubscriptionPayments.map((payment) => (
                                <div key={payment.id} className="rounded-2xl border border-amber-200 bg-white p-5 shadow-sm">
                                    <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                                        <div>
                                            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-blue-700">
                                                {capitalizePlanName(payment.plan_code)} {payment.billing_cycle} plan
                                            </p>
                                            <p className="mt-2 text-lg font-semibold text-slate-950">
                                                {formatCurrencyWithSymbol(payment.amount)} {payment.currency.toUpperCase()}
                                            </p>
                                            <p className="mt-1 text-sm text-slate-600">
                                                Created {new Date(payment.created_at).toLocaleString()}
                                            </p>
                                            <p className="mt-1 text-xs text-slate-500">Reference: {payment.transaction_id || payment.id}</p>
                                        </div>

                                        <div className="flex flex-wrap gap-3">
                                            <button
                                                type="button"
                                                onClick={() => continueSubscriptionPayment(payment)}
                                                disabled={isSubscriptionActionPending}
                                                className="rounded-full bg-blue-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
                                            >
                                                Continue Payment
                                            </button>
                                            <button
                                                type="button"
                                                onClick={() => {
                                                    void cancelAndRetrySubscriptionPayment(payment)
                                                }}
                                                disabled={isSubscriptionActionPending}
                                                className="rounded-full border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
                                            >
                                                {retrySubscriptionPayment.isPending ? 'Retrying...' : 'Cancel and Retry'}
                                            </button>
                                            <button
                                                type="button"
                                                onClick={() => {
                                                    void completelyCancelSubscriptionPayment(payment)
                                                }}
                                                disabled={isSubscriptionActionPending}
                                                className="rounded-full border border-red-200 bg-red-50 px-4 py-2 text-sm font-semibold text-red-700 transition hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-60"
                                            >
                                                {cancelSubscriptionPayment.isPending ? 'Cancelling...' : 'Completely Cancel Payment'}
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </section>
                )}

                <section className="mt-10 rounded-[1.75rem] border border-slate-200 bg-white p-6 shadow-sm">
                    <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
                        <div>
                            <p className="text-sm font-medium uppercase tracking-[0.24em] text-blue-700">Recurring subscription</p>
                            <h2 className="mt-2 text-2xl font-bold text-slate-950">Auto-renew paid plans</h2>
                            {currentSubscription?.recurring_enabled ? (
                                <p className="mt-2 text-sm text-slate-600">
                                    {capitalizePlanName(currentSubscription.plan_code)} renews with {currentSubscription.payment_method?.card_network || 'card'}
                                    {currentSubscription.payment_method?.card_last4 ? ` ending ${currentSubscription.payment_method.card_last4}` : ''}.
                                </p>
                            ) : (
                                <p className="mt-2 text-[16px] text-slate-600">Save your card for recurring payment.</p>
                            )}
                            <p className="mt-2 text-[12px] text-blue-600">Note: Card details are not saved in our system, only an encrypted hash is used in the payment process.</p>
                        </div>

                        {currentSubscription?.recurring_enabled && (
                            <button
                                type="button"
                                onClick={() => {
                                    void turnOffAutoRenew(currentSubscription)
                                }}
                                disabled={isSubscriptionActionPending}
                                className="rounded-full border border-red-200 bg-red-50 px-4 py-2 text-sm font-semibold text-red-700 transition hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-60"
                            >
                                {disableRecurringPayment.isPending ? 'Turning off...' : 'Turn Off Auto-Renew'}
                            </button>
                        )}
                    </div>

                    <label className="mt-6 flex items-center gap-3 rounded-2xl border border-slate-200 bg-slate-50 p-4">
                        <input
                            type="checkbox"
                            checked={autoRenew}
                            onChange={(event) => setAutoRenew(event.target.checked)}
                            className="h-5 w-5 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                        />
                        <span className="text-sm font-semibold text-slate-800">Save card and auto-renew future subscription payments</span>
                    </label>

                    {autoRenew && (
                        <div className="mt-5 space-y-4">
                            {paymentMethods.filter((method) => method.status === 'active').length > 0 && (
                                <select
                                    value={selectedPaymentMethodId}
                                    onChange={(event) => setSelectedPaymentMethodId(event.target.value)}
                                    className="w-full rounded-2xl border border-slate-300 px-4 py-3 text-sm text-slate-800"
                                >
                                    <option value="">Use a new card</option>
                                    {paymentMethods
                                        .filter((method) => method.status === 'active')
                                        .map((method) => (
                                            <option key={method.id} value={method.id}>
                                                {(method.card_network || method.payment_type || 'Card').toUpperCase()}
                                                {method.card_last4 ? ` ending ${method.card_last4}` : ''}
                                            </option>
                                        ))}
                                </select>
                            )}

                            {!selectedPaymentMethodId && (
                                <div className="grid gap-4 md:grid-cols-4">
                                    <input
                                        type="text"
                                        inputMode="numeric"
                                        autoComplete="cc-number"
                                        value={cardForm.cardNumber}
                                        onChange={(event) => setCardForm((current) => ({ ...current, cardNumber: event.target.value.replace(/\D/g, '').slice(0, 18) }))}
                                        placeholder="Card number"
                                        maxLength={18}
                                        className="rounded-2xl border border-slate-300 px-4 py-3 text-sm text-slate-800 md:col-span-2"
                                    />
                                    <input
                                        type="text"
                                        inputMode="numeric"
                                        autoComplete="cc-exp-month"
                                        value={cardForm.expiryMonth}
                                        onChange={(event) => setCardForm((current) => ({ ...current, expiryMonth: event.target.value.replace(/\D/g, '').slice(0, 2) }))}
                                        placeholder="MM"
                                        className="rounded-2xl border border-slate-300 px-4 py-3 text-sm text-slate-800"
                                    />
                                    <input
                                        type="text"
                                        inputMode="numeric"
                                        autoComplete="cc-exp-year"
                                        value={cardForm.expiryYear}
                                        onChange={(event) => setCardForm((current) => ({ ...current, expiryYear: event.target.value.replace(/\D/g, '').slice(0, 4) }))}
                                        placeholder="YY"
                                        className="rounded-2xl border border-slate-300 px-4 py-3 text-sm text-slate-800"
                                    />
                                    <input
                                        type="password"
                                        inputMode="numeric"
                                        autoComplete="cc-csc"
                                        value={cardForm.cvv}
                                        onChange={(event) => setCardForm((current) => ({ ...current, cvv: event.target.value.replace(/\D/g, '').slice(0, 4) }))}
                                        placeholder="CVV"
                                        className="rounded-2xl border border-slate-300 px-4 py-3 text-sm text-slate-800 md:col-span-1"
                                    />
                                </div>
                            )}
                        </div>
                    )}
                </section>

                <section className="mt-10">
                    <div className="mb-6 flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
                        <div>
                            <p className="text-sm font-medium uppercase tracking-[0.24em] text-blue-700">Subscription blueprint</p>
                            <h2 className="mt-2 text-3xl font-bold text-slate-950 capitalize">{billingCycle} pricing</h2>
                        </div>
                    </div>

                    <div className="grid gap-2 xl:grid-cols-4">
                        {subscriptionBlueprints.map((plan) => {
                            const isCurrentPlan =
                                currentSubscription?.plan_code === plan.code &&
                                currentSubscription?.billing_cycle === billingCycle &&
                                currentSubscription?.status === 'completed'
                            const pendingForPlan = pendingSubscriptionPayments.find(
                                (payment) => payment.plan_code === plan.code && payment.billing_cycle === billingCycle,
                            )
                            const hasOtherPendingPayment = pendingSubscriptionPayments.length > 0 && !pendingForPlan
                            const paidPlanSelected = Number(subscriptionPricing[plan.code][billingCycle]) > 0
                            const planButtonLabel = isCurrentPlan
                                ? 'Current Plan'
                                : startSubscriptionCheckout.isPending
                                    ? 'Redirecting...'
                                    : pendingForPlan
                                        ? 'Continue Payment'
                                        : hasOtherPendingPayment
                                            ? 'Pending payment exists'
                                            : autoRenew && paidPlanSelected
                                                ? 'Subscribe & Save Card'
                                                : 'Choose Plan'

                            return (
                                <article
                                    key={plan.name}
                                    className={`flex h-full flex-col rounded-[1.75rem] border p-6 shadow-sm transition-transform hover:-translate-y-5 ${plan.highlight
                                        ? 'border-blue-300 bg-blue-50/50'
                                        : 'border-slate-200 bg-white'
                                        }`}
                                >
                                    <div className={`inline-flex rounded-full bg-gradient-to-r ${plan.accentClassName} px-3 py-1 text-xs font-semibold uppercase tracking-[0.1em] text-white`}>
                                        {plan.badge}
                                    </div>
                                    <h3 className="mt-5 text-2xl font-semibold text-slate-950">{plan.name}</h3>
                                    <p className="mt-2 text-sm leading-6 text-slate-600">{plan.summary}</p>
                                    <p className="mt-3 text-xs font-medium text-slate-500">{plan.audience}</p>

                                    <div className="mt-8 rounded-2xl border border-slate-200 bg-slate-50 p-4">
                                        <p className="text-xs text-center font-semibold uppercase tracking-[0.18em] text-blue-500">{billingCycle === 'monthly' ? 'Monthly' : 'Yearly'} pricing</p>
                                        <p className="mt-3 text-3xl text-center font-bold text-slate-950">
                                            {formatCurrencyWithSymbol(subscriptionPricing[plan.code][billingCycle])}
                                        </p>
                                        <p className="mt-2 text-sm text-center text-slate-600">
                                            {billingCycle === 'monthly'
                                                ? `${formatCurrencyWithSymbol(subscriptionPricing[plan.code].yearly)} when billed yearly.`
                                                : `${formatCurrencyWithSymbol(subscriptionPricing[plan.code].monthly)} when billed monthly.`}
                                        </p>
                                    </div>

                                    <ul className="mt-6 space-y-3 text-sm text-slate-700">
                                        {plan.features.map((feature) => (
                                            <li key={feature} className="flex gap-3">
                                                <span className="mt-1 h-2.5 w-2.5 rounded-full bg-slate-900" />
                                                <span>{feature}</span>
                                            </li>
                                        ))}
                                    </ul>

                                    <div className="mt-auto pt-8">
                                        <button
                                            type="button"
                                            onClick={() => {
                                                void handleChoosePlan(plan, billingCycle)
                                            }}
                                            disabled={isCurrentPlan || isSubscriptionActionPending || hasOtherPendingPayment}
                                            className={`w-full rounded-full px-4 py-3 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-70 ${isCurrentPlan
                                                ? 'bg-emerald-600 text-white'
                                                : plan.highlight
                                                    ? 'bg-slate-950 text-white hover:bg-slate-800'
                                                    : 'border border-slate-400 bg-white text-slate-700 hover:bg-slate-50'
                                                }`}
                                        >
                                            {planButtonLabel}
                                        </button>
                                    </div>
                                </article>
                            )
                        })}
                    </div>
                </section>

                <section className="mt-10 rounded-[1.75rem] border border-slate-200 bg-white p-6 shadow-sm">
                    <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
                        <div>
                            <p className="text-sm font-medium uppercase tracking-[0.24em] text-blue-700">Billing history</p>
                            <h2 className="mt-2 text-3xl font-bold text-slate-950">Payments and transaction history</h2>
                        </div>
                        <div className="flex flex-wrap items-center gap-3">
                            <input
                                type="date"
                                value={from}
                                onChange={(event) => setFrom(event.target.value)}
                                className="rounded-full border border-slate-300 px-4 py-2 text-sm text-slate-700"
                            />
                            <input
                                type="date"
                                value={to}
                                onChange={(event) => setTo(event.target.value)}
                                className="rounded-full border border-slate-300 px-4 py-2 text-sm text-slate-700"
                            />
                        </div>
                    </div>

                    <div className="mt-6 rounded-3xl border border-slate-200">
                        {isPaymentsLoading || isSubscriptionPaymentsLoading ? (
                            <div className="p-6 text-sm text-slate-600">Loading payment history...</div>
                        ) : filteredPayments.length === 0 ? (
                            <div className="p-6 text-sm text-slate-600">No subscription or payment records yet.</div>
                        ) : (
                            <div className="divide-y divide-slate-200">
                                {filteredPayments.map((payment) => (
                                    <div key={payment.id} className="flex flex-col gap-3 p-5 md:flex-row md:items-center md:justify-between">
                                        <div>
                                            <p className="text-sm font-semibold text-slate-950">{payment.title}</p>
                                            <p className="mt-1 text-xs text-slate-500">#{payment.id}</p>
                                            <p className="mt-1 text-sm text-slate-600">{new Date(payment.created_at).toLocaleString()}</p>
                                        </div>
                                        <div className="flex flex-col gap-3 md:items-end">
                                            <div className="text-sm text-slate-700">{formatCurrencyWithSymbol(payment.amount)} {payment.currency.toUpperCase()}</div>
                                            <div className="flex flex-wrap items-center gap-2 md:justify-end">
                                                <span className="inline-flex rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] text-slate-700">
                                                    {payment.status}
                                                </span>
                                                {payment.type === 'subscription' && payment.status === 'completed' && (
                                                    <button
                                                        type="button"
                                                        onClick={() => downloadSubscriptionReceipt(payment)}
                                                        className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-700 transition hover:bg-blue-100"
                                                    >
                                                        Download Receipt
                                                    </button>
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                </section>
            </div>
        </div>
    )
}
