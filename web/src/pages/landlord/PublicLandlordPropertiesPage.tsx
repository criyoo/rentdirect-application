import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import ListingCard from '@/components/ListingCard'
import { useAuth } from '@/hooks/useAuth'
import { api } from '@/lib/api'
import { LandlordPublicProfile, Listing } from '@/types'

type PaginatedResponse<T> = { results?: T[] }

function normalizeResults<T>(payload: T[] | PaginatedResponse<T> | undefined): T[] {
    if (!payload) {
        return []
    }
    if (Array.isArray(payload)) {
        return payload
    }
    return Array.isArray(payload.results) ? payload.results : []
}

export default function PublicLandlordPropertiesPage() {
    const { landlordId } = useParams()
    const { user } = useAuth()

    const { data: profile, isLoading: profileLoading } = useQuery({
        queryKey: ['landlord', 'public-profile', landlordId],
        enabled: !!landlordId,
        queryFn: async () => (await api.get<LandlordPublicProfile>(`/users/landlords/${landlordId}/public-profile`)).data,
    })

    const { data: listingsPayload, isLoading: listingsLoading, isError } = useQuery({
        queryKey: ['landlord', 'properties', landlordId],
        enabled: !!landlordId,
        queryFn: async () => (await api.get<Listing[] | PaginatedResponse<Listing>>('/listings', {
            params: { landlord_id: landlordId },
        })).data,
    })

    const { data: favourites = [] } = useQuery({
        queryKey: ['me', 'favourites'],
        queryFn: async () => (await api.get<Listing[]>('/users/me/favourites')).data,
        enabled: user?.role === 'tenant',
    })

    const listings = normalizeResults(listingsPayload).filter((listing) => listing.status === 'available')
    const isLoading = profileLoading || listingsLoading

    if (isLoading) {
        return (
            <div className="min-h-screen bg-gray-50 py-8">
                <div className="container-modern">
                    <div className="card p-6 text-gray-600">Loading landlord properties...</div>
                </div>
            </div>
        )
    }

    if (isError || !profile) {
        return (
            <div className="min-h-screen bg-gray-50 py-8">
                <div className="container-modern">
                    <div className="card p-6">
                        <h1 className="text-2xl font-bold text-gray-900">Unable to load landlord properties</h1>
                        <p className="mt-2 text-gray-600">Please refresh the page and try again.</p>
                        <Link to="/search" className="btn btn-outline mt-4">
                            Browse Properties
                        </Link>
                    </div>
                </div>
            </div>
        )
    }

    return (
        <div className="min-h-screen bg-gray-50 py-8">
            <div className="container-modern">
                <div className="mb-8 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
                    <div>
                        <Link to={`/landlords/${landlordId}`} className="text-sm font-medium text-blue-600 hover:text-blue-700">
                            View landlord profile
                        </Link>
                        <h1 className="mt-2 text-3xl font-bold text-gray-900">{profile.display_name} Properties</h1>
                        <p className="mt-2 text-gray-600">
                            {listings.length} available propert{listings.length === 1 ? 'y' : 'ies'} listed by this landlord.
                        </p>
                    </div>
                    <Link to="/search" className="btn btn-outline">
                        Browse All Properties
                    </Link>
                </div>

                {listings.length > 0 ? (
                    <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
                        {listings.map((listing) => (
                            <ListingCard
                                key={listing.id}
                                listing={listing}
                                isFavourite={favourites.some((favourite) => favourite.id === listing.id)}
                            />
                        ))}
                    </div>
                ) : (
                    <div className="card p-8 text-center">
                        <h2 className="text-xl font-semibold text-gray-900">No available properties</h2>
                        <p className="mt-2 text-gray-600">This landlord does not have any available properties right now.</p>
                        <Link to="/search" className="btn btn-primary mt-5">
                            Browse Other Properties
                        </Link>
                    </div>
                )}
            </div>
        </div>
    )
}
