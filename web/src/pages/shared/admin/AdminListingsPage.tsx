import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import AdminLayout from '@/components/admin/AdminLayout'
import DashboardBackButton from '@/components/DashboardBackButton'
import { api, resolveMediaUrl } from '@/lib/api'
import { formatCurrencyWithSymbol } from '@/utils/currency'

interface AdminListing {
    id: string
    title: string
    city?: string
    state?: string
    status?: string
    price_per_year?: number | string
    bedrooms?: number
    property_type?: string
    landlord_name?: string
    landlord?: { name?: string; email?: string } | string
    cover_image_url?: string | null
    images?: { image_url?: string; url?: string }[]
    created_at?: string
}

const STATUS_FILTERS = ['all', 'available', 'pending', 'booked', 'archived'] as const

function statusBadgeClass(status: string) {
    switch (status) {
        case 'available':
            return 'bg-emerald-100 text-emerald-700'
        case 'pending':
            return 'bg-amber-100 text-amber-700'
        case 'archived':
            return 'bg-gray-100 text-gray-600'
        default:
            return 'bg-blue-100 text-blue-700'
    }
}

function landlordLabel(listing: AdminListing) {
    if (!listing.landlord) return listing.landlord_name || '—'
    if (typeof listing.landlord === 'string') return listing.landlord
    return listing.landlord.name || listing.landlord.email || '—'
}

function coverImage(listing: AdminListing) {
    if (listing.cover_image_url) return listing.cover_image_url
    const first = listing.images?.[0]
    return first?.image_url || first?.url || ''
}

export default function AdminListingsPage() {
    const [statusFilter, setStatusFilter] = useState<string>('all')
    const [search, setSearch] = useState('')

    const { data: listings, isLoading } = useQuery({
        queryKey: ['admin', 'listings', statusFilter],
        queryFn: async () =>
            (await api.get<AdminListing[]>('/admin/listings', {
                params: { ...(statusFilter !== 'all' ? { status: statusFilter } : {}), limit: 200 },
            })).data,
    })

    const filtered = (listings || []).filter((listing) => {
        const needle = search.trim().toLowerCase()
        if (!needle) return true
        return (
            listing.title?.toLowerCase().includes(needle) ||
            listing.city?.toLowerCase().includes(needle) ||
            landlordLabel(listing).toLowerCase().includes(needle)
        )
    })

    return (
        <AdminLayout>
            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
                <div className="mb-5">
                    <DashboardBackButton to="/admin/dashboard" label="Back to Dashboard" />
                </div>
                <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
                    <div>
                        <h1 className="text-3xl font-bold text-gray-900">Listings</h1>
                        <p className="text-gray-600 mt-1">{filtered.length} listing{filtered.length === 1 ? '' : 's'}</p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        <input
                            type="search"
                            value={search}
                            onChange={(event) => setSearch(event.target.value)}
                            placeholder="Search title, city or landlord"
                            className="form-input !w-64"
                        />
                        <div className="flex flex-wrap gap-1">
                            {STATUS_FILTERS.map((status) => (
                                <button
                                    key={status}
                                    type="button"
                                    onClick={() => setStatusFilter(status)}
                                    className={`rounded-md px-3 py-1.5 text-xs font-medium capitalize ${statusFilter === status
                                        ? 'bg-purple-600 text-white'
                                        : 'bg-white text-gray-600 border border-gray-200 hover:bg-purple-50'
                                        }`}
                                >
                                    {status}
                                </button>
                            ))}
                        </div>
                    </div>
                </div>

                {isLoading && <p className="text-sm text-gray-500 mb-4">Loading listings…</p>}

                <div className="bg-white rounded-xl border shadow-sm overflow-hidden">
                    <div className="overflow-x-auto">
                        <table className="min-w-full divide-y divide-gray-200 text-sm">
                            <thead className="bg-gray-50">
                                <tr>
                                    <th className="px-4 py-3 text-left font-semibold text-gray-600">Listing</th>
                                    <th className="px-4 py-3 text-left font-semibold text-gray-600">Landlord</th>
                                    <th className="px-4 py-3 text-left font-semibold text-gray-600">Location</th>
                                    <th className="px-4 py-3 text-right font-semibold text-gray-600">Price/year</th>
                                    <th className="px-4 py-3 text-left font-semibold text-gray-600">Status</th>
                                    <th className="px-4 py-3 text-left font-semibold text-gray-600">Created</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-100 bg-white">
                                {filtered.map((listing) => {
                                    const image = coverImage(listing)
                                    return (
                                        <tr key={listing.id} className="hover:bg-gray-50">
                                            <td className="px-4 py-3">
                                                <div className="flex items-center gap-3">
                                                    {image ? (
                                                        <img
                                                            src={resolveMediaUrl(image)}
                                                            alt={listing.title}
                                                            loading="lazy"
                                                            decoding="async"
                                                            className="h-10 w-14 rounded-md object-cover"
                                                        />
                                                    ) : (
                                                        <div className="h-10 w-14 rounded-md bg-gray-100" />
                                                    )}
                                                    <div>
                                                        <p className="font-medium text-gray-900">{listing.title}</p>
                                                        <p className="text-xs text-gray-500 capitalize">
                                                            {[listing.property_type, listing.bedrooms ? `${listing.bedrooms} bed` : ''].filter(Boolean).join(' · ')}
                                                        </p>
                                                    </div>
                                                </div>
                                            </td>
                                            <td className="px-4 py-3 text-gray-700">{landlordLabel(listing)}</td>
                                            <td className="px-4 py-3 text-gray-700">{[listing.city, listing.state].filter(Boolean).join(', ') || '—'}</td>
                                            <td className="px-4 py-3 text-right text-gray-700">
                                                {listing.price_per_year ? formatCurrencyWithSymbol(listing.price_per_year) : '—'}
                                            </td>
                                            <td className="px-4 py-3">
                                                <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${statusBadgeClass(listing.status || '')}`}>
                                                    {listing.status || 'unknown'}
                                                </span>
                                            </td>
                                            <td className="px-4 py-3 text-gray-500">
                                                {listing.created_at ? new Date(listing.created_at).toLocaleDateString() : '—'}
                                            </td>
                                        </tr>
                                    )
                                })}
                                {filtered.length === 0 && !isLoading && (
                                    <tr>
                                        <td colSpan={6} className="px-4 py-10 text-center text-sm text-gray-500">
                                            No listings found.
                                        </td>
                                    </tr>
                                )}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </AdminLayout>
    )
}
