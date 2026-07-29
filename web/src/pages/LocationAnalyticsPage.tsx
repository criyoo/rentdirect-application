import { Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { LocationAnalyticsGroup, LocationAnalyticsResponse } from '@/types'
import { api } from '@/lib/api'
import { formatCurrencyWithSymbol } from '@/utils/currency'
import { useAuth } from '@/hooks/useAuth'
import { hasSilverAccess, SubscriptionPaymentRecord } from '@/lib/subscriptions'

function hasLocationSearch(searchParams: URLSearchParams) {
    const hasRadius = Boolean(searchParams.get('radius_km'))
    const hasCoordinates = Boolean(searchParams.get('latitude') && searchParams.get('longitude'))
    const hasArea = Boolean(searchParams.get('city') || searchParams.get('state'))
    return hasRadius && (hasCoordinates || hasArea)
}

function analyticsRequestParams(searchParams: URLSearchParams) {
    const params = new URLSearchParams()
    const state = searchParams.get('state')
    const city = searchParams.get('city')
    const locationSearchActive = hasLocationSearch(searchParams)

    if (state) params.set('state', state)
    if (city && !locationSearchActive) params.set('city', city)

    return params
}

function analyticsSearchPath(searchParams: URLSearchParams) {
    const suffix = searchParams.toString()
    return suffix ? `/search?${suffix}` : '/search'
}

function AnalyticsTable({ title, items }: { title: string; items: LocationAnalyticsGroup[] }) {
    return (
        <section className="rounded-lg border border-gray-200 bg-white">
            <div className="border-b border-gray-200 px-4 py-3">
                <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
            </div>
            <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200 text-sm">
                    <thead className="bg-gray-50">
                        <tr>
                            <th className="px-4 py-3 text-left font-semibold text-gray-700">Name</th>
                            <th className="px-4 py-3 text-right font-semibold text-gray-700">Listings</th>
                            <th className="px-4 py-3 text-right font-semibold text-gray-700">Average Rent</th>
                            <th className="px-4 py-3 text-right font-semibold text-gray-700">Min</th>
                            <th className="px-4 py-3 text-right font-semibold text-gray-700">Max</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100 bg-white">
                        {items.map((item) => (
                            <tr key={`${title}-${item.state || ''}-${item.city || ''}-${item.name}`}>
                                <td className="px-4 py-3 font-medium text-gray-900">{item.name}</td>
                                <td className="px-4 py-3 text-right text-gray-700">{item.listing_count}</td>
                                <td className="px-4 py-3 text-right text-gray-700">{formatCurrencyWithSymbol(item.average_price_per_year)}</td>
                                <td className="px-4 py-3 text-right text-gray-700">{formatCurrencyWithSymbol(item.min_price_per_year)}</td>
                                <td className="px-4 py-3 text-right text-gray-700">{formatCurrencyWithSymbol(item.max_price_per_year)}</td>
                            </tr>
                        ))}
                        {!items.length ? (
                            <tr>
                                <td colSpan={5} className="px-4 py-6 text-center text-gray-500">No data yet</td>
                            </tr>
                        ) : null}
                    </tbody>
                </table>
            </div>
        </section>
    )
}

export default function LocationAnalyticsPage() {
    const { user } = useAuth()
    const [searchParams] = useSearchParams()
    const requestParams = analyticsRequestParams(searchParams)
    const suffix = requestParams.toString()
    const { data: subscriptionPaymentResponse, isLoading: isSubscriptionLoading } = useQuery({
        queryKey: ['subscription-payments', 'location-analytics', user?.id],
        queryFn: async () => (await api.get<SubscriptionPaymentRecord[] | { results?: SubscriptionPaymentRecord[] }>('/subscriptions')).data,
        enabled: user?.role === 'tenant',
    })
    const canViewLocationAnalytics = user?.role === 'landlord'
        || user?.role === 'admin'
        || (
            user?.role === 'tenant'
            && subscriptionPaymentResponse !== undefined
            && hasSilverAccess(subscriptionPaymentResponse)
        )
    const { data: locationAnalytics, isLoading } = useQuery({
        queryKey: ['listings', 'location-analytics-page', suffix],
        queryFn: async () => {
            return (await api.get<LocationAnalyticsResponse>(`/listings/location-analytics${suffix ? `?${suffix}` : ''}`)).data
        },
        enabled: canViewLocationAnalytics,
    })

    if (user?.role === 'tenant' && isSubscriptionLoading) {
        return (
            <div className="container-modern py-8">
                <div className="rounded-lg border border-gray-200 bg-white p-8 text-center text-gray-500">
                    Checking location analytics access...
                </div>
            </div>
        )
    }

    if (!canViewLocationAnalytics) {
        return (
            <div className="container-modern py-8">
                <div className="rounded-lg border border-blue-200 bg-white p-8 text-center">
                    <h1 className="text-2xl font-bold text-gray-900">Location Analytics</h1>
                    <p className="mt-3 text-gray-600">
                        Property location and analytics are available with the Silver tenant plan and every higher plan.
                    </p>
                    <div className="mt-6 flex justify-center gap-3">
                        <Link to={user ? '/billing' : '/login'} className="btn btn-primary">
                            {user ? 'View Plans' : 'Sign In'}
                        </Link>
                        <Link to="/search" className="btn btn-outline">Back to Search</Link>
                    </div>
                </div>
            </div>
        )
    }

    return (
        <div className="min-h-screen bg-gray-50 py-8">
            <div className="container-modern">
                <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
                    <div>
                        <h1 className="text-3xl font-bold text-gray-900">Location Analytics</h1>
                        <p className="mt-1 text-sm text-gray-500">
                            {isLoading ? 'Loading analytics...' : `${locationAnalytics?.total_listings || 0} available listing${locationAnalytics?.total_listings === 1 ? '' : 's'} analysed`}
                        </p>
                    </div>
                    <Link
                        to={analyticsSearchPath(searchParams)}
                        className="inline-flex items-center justify-center rounded-md border border-gray-300 px-4 py-2 text-sm font-semibold text-gray-700 hover:bg-white"
                    >
                        Back to Search
                    </Link>
                </div>

                {isLoading ? (
                    <div className="rounded-lg border border-gray-200 bg-white p-8 text-center text-gray-500">Loading analytics...</div>
                ) : (
                    <div className="space-y-6">
                        <AnalyticsTable title="States" items={locationAnalytics?.states || []} />
                        <AnalyticsTable title="Cities" items={locationAnalytics?.cities || []} />
                        <AnalyticsTable title="Neighbourhoods" items={locationAnalytics?.neighbourhoods || []} />
                    </div>
                )}
            </div>
        </div>
    )
}
