export type PlanCode = 'bronze' | 'silver' | 'gold' | 'platinum'

export type SubscriptionPaymentRecord = {
    id: string
    role: 'tenant' | 'landlord'
    plan_code: PlanCode
    billing_cycle: 'monthly' | 'yearly'
    amount: number | string
    currency: string
    status: string
    expires_at?: string | null
    payment_date?: string | null
    created_at: string
}

type PaginatedResponse<T> = {
    results?: T[]
}

export function normalizeSubscriptionPayments(
    response?: SubscriptionPaymentRecord[] | PaginatedResponse<SubscriptionPaymentRecord> | null,
) {
    if (Array.isArray(response)) {
        return response
    }
    return response?.results || []
}

export function getActivePlanCode(
    response?: SubscriptionPaymentRecord[] | PaginatedResponse<SubscriptionPaymentRecord> | null,
): PlanCode {
    const now = Date.now()
    const activeSubscriptions = normalizeSubscriptionPayments(response)
        .filter((payment) => {
            if (payment.status !== 'completed' || !payment.expires_at) {
                return false
            }
            return new Date(payment.expires_at).getTime() >= now
        })
        .sort((left, right) => {
            const leftTime = new Date(left.payment_date || left.created_at).getTime()
            const rightTime = new Date(right.payment_date || right.created_at).getTime()
            return rightTime - leftTime
        })

    return activeSubscriptions[0]?.plan_code || 'bronze'
}

export function hasBronzeAccess(
    response?: SubscriptionPaymentRecord[] | PaginatedResponse<SubscriptionPaymentRecord> | null,
) {
    return getActivePlanCode(response) === 'bronze'
}

export function hasCommunityChatAccess(
    response?: SubscriptionPaymentRecord[] | PaginatedResponse<SubscriptionPaymentRecord> | null,
) {
    return ['gold', 'platinum'].includes(getActivePlanCode(response))
}
