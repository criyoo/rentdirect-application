import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'

interface FinancialConfigResponse {
    administration_fee_rate: string
    administration_fee_vat_rate: string
    listing_deposit_rate: string
    listing_deposit_hold_days: number
    refundable_caution_fee_rate: string
    legal_fee_max_rate: string
    payment_cancellation_admin_fee_rate: string
    card_payment_limit: string
    account_freeze_fee_percentage: string
    subscription_vat_rate_percent: string
    featured_property_monthly_fee: string
    featured_property_monthly_duration_days: number
    featured_property_min_duration_days: number
    featured_property_max_duration_days: number
}

export interface FinancialConfig {
    administrationFeeRate: number
    administrationFeeVatRate: number
    listingDepositRate: number
    listingDepositHoldDays: number
    refundableCautionFeeRate: number
    legalFeeMaxRate: number
    paymentCancellationAdminFeeRate: number
    cardPaymentLimit: number
    accountFreezeFeePercentage: number
    subscriptionVatRatePercent: number
    featuredPropertyMonthlyFee: number
    featuredPropertyMonthlyDurationDays: number
    featuredPropertyMinDurationDays: number
    featuredPropertyMaxDurationDays: number
}

function toFinancialConfig(data: FinancialConfigResponse): FinancialConfig {
    return {
        administrationFeeRate: Number(data.administration_fee_rate),
        administrationFeeVatRate: Number(data.administration_fee_vat_rate),
        listingDepositRate: Number(data.listing_deposit_rate),
        listingDepositHoldDays: Number(data.listing_deposit_hold_days),
        refundableCautionFeeRate: Number(data.refundable_caution_fee_rate),
        legalFeeMaxRate: Number(data.legal_fee_max_rate),
        paymentCancellationAdminFeeRate: Number(data.payment_cancellation_admin_fee_rate),
        cardPaymentLimit: Number(data.card_payment_limit),
        accountFreezeFeePercentage: Number(data.account_freeze_fee_percentage),
        subscriptionVatRatePercent: Number(data.subscription_vat_rate_percent),
        featuredPropertyMonthlyFee: Number(data.featured_property_monthly_fee),
        featuredPropertyMonthlyDurationDays: Number(data.featured_property_monthly_duration_days),
        featuredPropertyMinDurationDays: Number(data.featured_property_min_duration_days),
        featuredPropertyMaxDurationDays: Number(data.featured_property_max_duration_days),
    }
}

export function useFinancialConfig() {
    return useQuery({
        queryKey: ['financial-config'],
        queryFn: async () => toFinancialConfig((await api.get<FinancialConfigResponse>('/config/financial')).data),
        staleTime: Infinity,
        gcTime: Infinity,
    })
}

export function formatRatePercent(rate: number | null | undefined): string {
    if (rate === null || rate === undefined || Number.isNaN(rate)) return ''
    const percent = rate * 100
    return `${Number.isInteger(percent) ? percent : Number(percent.toFixed(2))}%`
}

export function formatDays(days: number | null | undefined): string {
    if (days === null || days === undefined || Number.isNaN(days)) return ''
    return `${days} day${days === 1 ? '' : 's'}`
}
