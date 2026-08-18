import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { Link } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'
import { resolveMediaUrl } from '@/lib/api'

interface LandlordEnquiry {
    id: string
    listing_id: string
    listing_title: string
    listing_address: string
    listing_city: string
    listing_cover_image_url: string
    tenant_id: string
    tenant_name: string
    tenant_profile_photo_url?: string | null
    tenant_email: string
    last_message: string
    last_message_time: string
    message_count: number
    has_viewing_requested: boolean
    has_viewing_arranged: boolean
    has_rental_agreed: boolean
    viewing_date?: string
    rental_start_date?: string
}

interface Conversation {
    counterpart_profile_photo_url?: string | null
    listing_id: string | null
}

type PaginatedResponse<T> = {
    results?: T[]
}

function normalizeResults<T>(payload: T[] | PaginatedResponse<T> | undefined): T[] {
    if (!payload) {
        return []
    }

    if (Array.isArray(payload)) {
        return payload
    }

    return Array.isArray(payload.results) ? payload.results : []
}

export default function LandlordEnquiriesPage() {
    const { user } = useAuth()

    const { data: enquiries, isLoading, isError } = useQuery({
        queryKey: ['landlord', 'enquiries'],
        queryFn: async () => {
            const response = await api.get<LandlordEnquiry[] | PaginatedResponse<LandlordEnquiry>>('/messages/enquiries')
            return normalizeResults(response.data)
        },
        enabled: !!user,
        retry: false,
    })

    const { data: conversations } = useQuery({
        queryKey: ['messages', 'conversations'],
        queryFn: async () => (await api.get<Conversation[]>('/messages/conversations')).data,
        enabled: !!user,
    })

    const tenantPhotoByListingId = useMemo(
        () => new Map(
            (conversations || [])
                .filter((conversation) => Boolean(conversation.listing_id))
                .map((conversation) => [String(conversation.listing_id), conversation.counterpart_profile_photo_url || null]),
        ),
        [conversations],
    )

    if (isLoading) {
        return (
            <div className="container-modern py-8">
                <div className="text-center">Loading enquiries...</div>
            </div>
        )
    }

    return (
        <div className="container-modern py-8 min-h-[calc(100vh-200px)]">
            <div className="mb-6">
                <h1 className="text-3xl font-bold text-gray-900">Property Enquiries</h1>
                <p className="text-gray-600 mt-2">Tenant enquiries about your properties and viewing arrangements</p>
            </div>

            {isError && (
                <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
                    Unable to load enquiries right now. Please refresh the page.
                </div>
            )}

            {!isError && enquiries && enquiries.length > 0 ? (
                <div className="space-y-6">
                    {enquiries.map((enquiry) => (
                        <div
                            key={enquiry.id}
                            className="bg-white rounded-xl border shadow-sm hover:shadow-md transition-shadow p-6"
                        >
                            <div className="flex gap-6">
                                {/* Property Image */}
                                <div className="flex-shrink-0">
                                    <img
                                        src={resolveMediaUrl(enquiry.listing_cover_image_url)}
                                        alt={enquiry.listing_title}
                                        loading="lazy"
                                        decoding="async"
                                        className="w-24 h-24 object-cover rounded-lg"
                                        onError={(e) => {
                                            e.currentTarget.src = '/placeholder.jpg'
                                        }}
                                    />
                                </div>

                                {/* Enquiry Details */}
                                <div className="flex-1 min-w-0">
                                    <div className="flex items-start justify-between">
                                        <div className="flex-1">
                                            <h3 className="text-lg font-semibold text-gray-900 mb-1">
                                                {enquiry.listing_title}
                                            </h3>
                                            <p className="text-sm text-gray-600 mb-2">
                                                {enquiry.listing_city}
                                            </p>

                                            <div className="flex items-center gap-4 text-sm text-gray-600 mb-3">
                                                <div className="flex items-center gap-2">
                                                    <img
                                                        src={resolveMediaUrl(enquiry.tenant_profile_photo_url || tenantPhotoByListingId.get(String(enquiry.listing_id)))}
                                                        alt={enquiry.tenant_name}
                                                        loading="lazy"
                                                        decoding="async"
                                                        className="h-8 w-8 rounded-full object-cover"
                                                        onError={(e) => {
                                                            e.currentTarget.src = '/placeholder.jpg'
                                                        }}
                                                    />
                                                    <span>Tenant: {enquiry.tenant_name}</span>
                                                </div>
                                                <span>•</span>
                                                <span>{enquiry.message_count} message{enquiry.message_count !== 1 ? 's' : ''}</span>
                                            </div>

                                            {enquiry.last_message && (
                                                <p className="text-sm text-gray-700 mb-3 line-clamp-2">
                                                    "{enquiry.last_message}"
                                                </p>
                                            )}

                                            {/* Status Badges */}
                                            <div className="flex items-center gap-2 mb-3">
                                                {(enquiry.has_viewing_arranged || enquiry.has_viewing_requested) && (
                                                    <span className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${enquiry.has_viewing_arranged ? 'bg-green-100 text-green-800' : 'bg-blue-100 text-blue-800'}`}>
                                                        <svg className="w-3 h-3 mr-1" fill="currentColor" viewBox="0 0 20 20">
                                                            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-12a1 1 0 10-2 0v4a1 1 0 00.293.707l2.828 2.829a1 1 0 101.415-1.415L11 9.586V6z" clipRule="evenodd" />
                                                        </svg>
                                                        {enquiry.has_viewing_arranged ? 'Viewing arranged' : 'Viewing Requested'}
                                                        {enquiry.viewing_date && (
                                                            <span className="ml-1">({new Date(enquiry.viewing_date).toLocaleDateString()})</span>
                                                        )}
                                                    </span>
                                                )}
                                                {enquiry.has_rental_agreed && (
                                                    <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-green-100 text-green-800">
                                                        <svg className="w-3 h-3 mr-1" fill="currentColor" viewBox="0 0 20 20">
                                                            <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                                                        </svg>
                                                        Rental Agreed
                                                        {enquiry.rental_start_date && (
                                                            <span className="ml-1">({new Date(enquiry.rental_start_date).toLocaleDateString()})</span>
                                                        )}
                                                    </span>
                                                )}
                                            </div>

                                            <div className="flex items-center justify-between">
                                                <div className="flex items-center gap-3">
                                                    <Link
                                                        to={`/contact-landlord/${enquiry.listing_id}?tenantId=${encodeURIComponent(enquiry.tenant_id)}`}
                                                        className="inline-flex items-center px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
                                                    >
                                                        <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                                                        </svg>
                                                        Continue Chat
                                                    </Link>

                                                    <Link
                                                        to={`/tenants/${enquiry.tenant_id}`}
                                                        className="inline-flex items-center px-4 py-2 border border-blue-200 text-blue-700 text-sm font-medium rounded-lg hover:bg-blue-50 transition-colors"
                                                    >
                                                        View Tenant Profile
                                                    </Link>

                                                    {/* <Link
                                                        to={`/listings/${enquiry.listing_id}`}
                                                        className="inline-flex items-center px-4 py-2 border border-gray-300 text-gray-700 text-sm font-medium rounded-lg hover:bg-gray-50 transition-colors"
                                                    >
                                                        View Property
                                                    </Link> */}
                                                </div>

                                                <div className="text-right">
                                                    <p className="text-xs text-gray-500">
                                                        {new Date(enquiry.last_message_time).toLocaleDateString()}
                                                    </p>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            ) : !isError ? (
                <div className="text-center py-12">
                    <div className="w-16 h-16 bg-gray-100 rounded-full flex items-center justify-center mx-auto mb-4">
                        <svg className="w-8 h-8 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                        </svg>
                    </div>
                    <h3 className="text-lg font-medium text-gray-900 mb-2">No enquiries yet</h3>
                    <p className="text-gray-600 mb-6">When tenants enquire about your properties, they'll appear here.</p>
                    <Link
                        to="/listings/new"
                        className="inline-flex items-center px-6 py-3 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 transition-colors"
                    >
                        List a Property
                    </Link>
                </div>
            ) : null}
        </div>
    )
}
