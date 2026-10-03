import { useQuery } from '@tanstack/react-query'

import AdminLayout from '@/components/admin/AdminLayout'
import DashboardBackButton from '@/components/DashboardBackButton'
import { api } from '@/lib/api'

interface FinancialConfig {
    refundable_caution_fee_rate: string
    administration_fee_rate: string
    administration_fee_vat_rate: string
    listing_deposit_rate: string
    listing_deposit_hold_days: number
    payment_cancellation_admin_fee_rate: string
    card_payment_limit: string
    account_freeze_fee_percentage: string
    subscription_vat_rate_percent: string
    featured_property_monthly_fee: string
    featured_property_monthly_duration_days: number
    featured_property_min_duration_days: number
    featured_property_max_duration_days: number
}

const CONFIG_LABELS: Record<keyof FinancialConfig, { label: string; format: (value: string | number) => string }> = {
    refundable_caution_fee_rate: { label: 'Refundable caution fee rate', format: (v) => `${Number(v) * 100}%` },
    administration_fee_rate: { label: 'Administration fee rate', format: (v) => `${Number(v) * 100}%` },
    administration_fee_vat_rate: { label: 'VAT on administration fee', format: (v) => `${Number(v) * 100}%` },
    listing_deposit_rate: { label: 'Listing deposit rate', format: (v) => `${Number(v) * 100}%` },
    listing_deposit_hold_days: { label: 'Listing deposit hold (days)', format: (v) => String(v) },
    payment_cancellation_admin_fee_rate: { label: 'Payment cancellation admin fee rate', format: (v) => `${Number(v) * 100}%` },
    card_payment_limit: { label: 'Card payment limit (NGN)', format: (v) => `₦${Number(v).toLocaleString()}` },
    account_freeze_fee_percentage: { label: 'Account freeze fee', format: (v) => `${Number(v) * 100}%` },
    subscription_vat_rate_percent: { label: 'Subscription VAT rate', format: (v) => `${v}%` },
    featured_property_monthly_fee: { label: 'Featured property monthly fee (NGN)', format: (v) => `₦${Number(v).toLocaleString()}` },
    featured_property_monthly_duration_days: { label: 'Featured duration (days)', format: (v) => String(v) },
    featured_property_min_duration_days: { label: 'Featured min duration (days)', format: (v) => String(v) },
    featured_property_max_duration_days: { label: 'Featured max duration (days)', format: (v) => String(v) },
}

export default function AdminSettingsPage() {
    const { data: config, isLoading } = useQuery({
        queryKey: ['admin', 'financial-config'],
        queryFn: async () => (await api.get<FinancialConfig>('/config/financial')).data,
    })

    return (
        <AdminLayout>
            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
                <div className="mb-5">
                    <DashboardBackButton to="/admin/dashboard" label="Back to Dashboard" />
                </div>
                <div className="mb-8">
                    <h1 className="text-3xl font-bold text-gray-900">Settings</h1>
                    <p className="text-gray-600 mt-1">Current platform financial configuration.</p>
                </div>

                {isLoading && <p className="text-sm text-gray-500 mb-4">Loading settings…</p>}

                <div className="bg-white rounded-xl border shadow-sm overflow-hidden">
                    <div className="border-b border-gray-200 bg-gray-50 px-5 py-4">
                        <h2 className="text-base font-semibold text-gray-900">Financial configuration</h2>
                    </div>
                    <dl className="divide-y divide-gray-100">
                        {config && (Object.keys(CONFIG_LABELS) as (keyof FinancialConfig)[]).map((key) => (
                            <div key={key} className="flex items-center justify-between px-5 py-3.5 text-sm">
                                <dt className="text-gray-600">{CONFIG_LABELS[key].label}</dt>
                                <dd className="font-semibold text-gray-900">
                                    {CONFIG_LABELS[key].format(config[key] ?? '')}
                                </dd>
                            </div>
                        ))}
                    </dl>
                </div>
            </div>
        </AdminLayout>
    )
}
