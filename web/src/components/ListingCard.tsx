import { Link } from 'react-router-dom'
import { Listing } from '@/types'
import { useAuth } from '@/hooks/useAuth'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { resolveMediaUrl } from '@/lib/api'
import { HiHeart, HiOutlineHeart, HiLocationMarker, HiHome, HiViewGrid } from 'react-icons/hi'
import { formatCurrencyWithSymbol } from '@/utils/currency'

interface ListingCardProps {
    listing: Listing
    isFavourite?: boolean
}

export default function ListingCard({ listing, isFavourite = false }: ListingCardProps) {
    const { user } = useAuth()
    const queryClient = useQueryClient()
    const canManageFavourites = user?.role === 'tenant'
    const locationLabel = [listing.city, listing.state].filter(Boolean).join(', ') || listing.state || 'State not provided'
    const distanceKm = typeof listing.distance_km === 'number'
        ? listing.distance_km
        : listing.distance_km == null
            ? Number.NaN
            : Number(listing.distance_km)
    const hasDistance = Number.isFinite(distanceKm)

    const toggleFavourite = useMutation({
        mutationFn: async () => {
            if (isFavourite) {
                await api.delete(`/users/me/favourites/${listing.id}`)
            } else {
                await api.post(`/users/me/favourites/${listing.id}`)
            }
        },
        onMutate: async () => {
            await queryClient.cancelQueries({ queryKey: ['me', 'favourites'] })
            const previousFavourites = queryClient.getQueryData<Listing[]>(['me', 'favourites']) || []

            queryClient.setQueryData<Listing[]>(['me', 'favourites'], (current = []) => {
                if (isFavourite) {
                    return current.filter((item) => item.id !== listing.id)
                }

                if (current.some((item) => item.id === listing.id)) {
                    return current
                }

                return [listing, ...current]
            })

            return { previousFavourites }
        },
        onError: (error, _variables, context) => {
            if (context?.previousFavourites) {
                queryClient.setQueryData(['me', 'favourites'], context.previousFavourites)
            }
            alert(`Failed to ${isFavourite ? 'remove from' : 'add to'} favourites: ${error.message}`)
        },
        onSettled: () => {
            queryClient.invalidateQueries({ queryKey: ['me', 'favourites'] })
            queryClient.invalidateQueries({ queryKey: ['listings', 'featured'] })
        },
    })

    const handleFavouriteClick = (e: React.MouseEvent) => {
        e.preventDefault()
        e.stopPropagation()
        if (canManageFavourites) {
            toggleFavourite.mutate()
        } else {
            alert('Please log in to add favourites')
        }
    }

    return (
        <Link to={`/listings/${listing.id}`} className="group">
            <div className="card card-hover h-full flex flex-col">
                {/* Image Container */}
                <div className="relative aspect-[4/3] overflow-hidden">
                    <img
                        src={resolveMediaUrl(listing.cover_image_url)}
                        alt={listing.title}
                        loading="lazy"
                        decoding="async"
                        className="w-full h-full object-cover group-hover:scale-150 transition-transform duration-300"
                        onError={(e) => {
                            e.currentTarget.src = '/placeholder.jpg'
                        }}
                    />

                    {/* Favourite Button */}
                    {canManageFavourites && (
                        <button
                            onClick={handleFavouriteClick}
                            disabled={toggleFavourite.isPending}
                            className="absolute top-3 right-3 p-2 bg-white/90 backdrop-blur-sm rounded-full shadow-lg hover:bg-white transition-all duration-200 group-hover:scale-110"
                        >
                            {toggleFavourite.isPending ? (
                                <div className="w-4 h-4 border-2 border-red-500 border-t-transparent rounded-full animate-spin"></div>
                            ) : isFavourite ? (
                                <HiHeart className="w-4 h-4 text-red-500" />
                            ) : (
                                <HiOutlineHeart className="w-4 h-4 text-gray-600 group-hover:text-red-500" />
                            )}
                        </button>
                    )}

                    {/* Featured Badge */}
                    {listing.featured && (
                        <div className="absolute top-3 left-3">
                            <span className="badge badge-primary">
                                <HiHome className="w-3 h-3 mr-1" />
                                Featured
                            </span>
                        </div>
                    )}

                    {/* Property Type Badge */}
                    <div className="absolute bottom-3 left-3">
                        <span className="badge bg-black/70 text-white backdrop-blur-sm">
                            {listing.property_type}
                        </span>
                    </div>
                </div>

                {/* Content */}
                <div className="flex flex-1 flex-col items-center p-4 text-center">
                    {/* Title and Location */}
                    <div className="text-center  mb-3">
                        <h3 className="mb-1 text-lg font-semibold text-gray-900 line-clamp-2 group-hover:text-blue-600 transition-colors duration-200">
                            {listing.title}
                        </h3>
                        <div className="flex items-center justify-center text-gray-600 text-sm">
                            <HiLocationMarker className="w-4 h-4 mr-1 flex-shrink-0" />
                            <span className="truncate">{locationLabel}</span>
                        </div>
                        {hasDistance ? (
                            <div className="mt-1 text-sm font-medium text-blue-600">
                                {distanceKm.toFixed(1)} km away
                            </div>
                        ) : null}
                    </div>

                    {/* Property Details */}
                    <div className="mb-1 flex items-center justify-center space-x-4 text-sm text-gray-600">
                        <div className="flex items-center space-x-1">
                            <HiHome className="w-4 h-4" />
                            <span className="font-medium">{listing.bedrooms}</span>
                            <span>bed</span>
                        </div>
                        <div className="flex items-center space-x-1">
                            <HiViewGrid className="w-4 h-4" />
                            <span className="font-medium">{listing.bathrooms}</span>
                            <span>bath</span>
                        </div>
                        {listing.toilets ? (
                            <div className="flex items-center space-x-1">
                                <HiViewGrid className="w-4 h-4" />
                                <span className="font-medium">{listing.toilets}</span>
                                <span>toilet</span>
                            </div>
                        ) : null}
                    </div>

                    {/* Price */}
                    <div className="text-center mt-auto">
                        <div className="text-[16px] text-blue-600">
                            {formatCurrencyWithSymbol(listing.price_per_year)} / year
                        </div>
                    </div>
                </div>
            </div>
        </Link>
    )
}
