import { Link, useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { LandlordPublicProfile, Listing, NearestAmenitiesResponse, RentalProgress, Review } from '@/types'
import { useEffect, useState, useRef } from 'react'
import { useAuth } from '@/hooks/useAuth'
import { resolveMediaUrl } from '@/lib/api'
import { formatCurrencyWithSymbol } from '@/utils/currency'
import ReviewModal from '@/components/ReviewModal'
import { hasBronzeAccess, hasGoldAccess, hasSilverAccess, SubscriptionPaymentRecord } from '@/lib/subscriptions'

// Icons for property features
const Icons = {
    rooms: () => (
        <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M3 4a1 1 0 011-1h12a1 1 0 011 1v2a1 1 0 01-1 1H4a1 1 0 01-1-1V4zM3 10a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H4a1 1 0 01-1-1v-6zM14 9a1 1 0 00-1 1v6a1 1 0 001 1h2a1 1 0 001-1v-6a1 1 0 00-1-1h-2z" clipRule="evenodd" />
        </svg>
    ),
    bedrooms: () => (
        <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
            <path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
    ),
    bathrooms: () => (
        <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M3 4a1 1 0 011-1h12a1 1 0 011 1v2a1 1 0 01-1 1H4a1 1 0 01-1-1V4zM3 10a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H4a1 1 0 01-1-1v-6zM14 9a1 1 0 00-1 1v6a1 1 0 001 1h2a1 1 0 001-1v-6a1 1 0 00-1-1h-2z" clipRule="evenodd" />
        </svg>
    ),
    toilets: () => (
        <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M3 4a1 1 0 011-1h12a1 1 0 011 1v2a1 1 0 01-1 1H4a1 1 0 01-1-1V4zM3 10a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H4a1 1 0 01-1-1v-6zM14 9a1 1 0 00-1 1v6a1 1 0 001 1h2a1 1 0 001-1v-6a1 1 0 00-1-1h-2z" clipRule="evenodd" />
        </svg>
    )
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

function renderStars(rating: number) {
    return '★'.repeat(rating) + '☆'.repeat(Math.max(5 - rating, 0))
}

const amenityCategoryLabels: Record<string, string> = {
    schools: 'Schools',
    hospitals: 'Hospitals',
    transport_hubs: 'Transport',
    supermarkets: 'Supermarkets',
    other: 'Other',
}

type TenantViewingRequest = {
    tenant_id: string
    tenant_name: string
    tenant_email: string
    tenant_profile_photo_url?: string | null
    listing_id: string
    booking_id?: string
    booking_status?: string
    stage: string
    rental_progress?: RentalProgress | null
    last_message: string
    last_message_time: string
    message_count: number
    has_viewing_requested: boolean
    has_viewing_arranged: boolean
}

function formatStatusLabel(value?: string) {
    return (value || '').replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase())
}

export default function ListingDetailPage() {
    const { id } = useParams()
    const { user } = useAuth()
    const navigate = useNavigate()
    const qc = useQueryClient()
    const canManageFavourites = user?.role === 'tenant'
    const [currentImageIndex, setCurrentImageIndex] = useState(0)
    const imageContainerRef = useRef<HTMLDivElement>(null)
    const thumbnailContainerRef = useRef<HTMLDivElement>(null)
    const thumbnailButtonRefs = useRef<Array<HTMLButtonElement | null>>([])
    const [showMap, setShowMap] = useState(false)
    const [isReviewOpen, setIsReviewOpen] = useState(false)

    const { data: listing, isLoading } = useQuery({
        queryKey: ['listing', id],
        enabled: !!id,
        queryFn: async () => (await api.get<Listing>(`/listings/${id}`)).data
    })
    const isLandlordUser = user?.role === 'landlord'
    const isListingLandlord = isLandlordUser && !!listing && listing.landlord_id === user?.id
    const { data: tenantProfile, isLoading: isTenantProfileLoading } = useQuery({
        queryKey: ['tenant-profile', 'listing-detail', user?.id],
        enabled: user?.role === 'tenant',
        queryFn: async () => {
            try {
                return (await api.get<{ status: string }>('/users/me/tenant-profile')).data
            } catch {
                return null
            }
        },
    })
    const { data: freshUser, isLoading: isFreshUserLoading } = useQuery({
        queryKey: ['me', 'listing-detail', user?.id],
        enabled: !!user,
        queryFn: async () => (await api.get<{ is_verified: boolean }>('/users/me')).data,
    })
    const { data: landlordProfile } = useQuery({
        queryKey: ['landlord', 'public-profile', listing?.landlord_id],
        enabled: !!listing?.landlord_id,
        queryFn: async () => (await api.get<LandlordPublicProfile>(`/users/landlords/${listing!.landlord_id}/public-profile`)).data,
    })
    const { data: propertyReviews = [] } = useQuery({
        queryKey: ['reviews', 'listing', listing?.id, 'property'],
        enabled: !!listing?.id,
        queryFn: async () => (await api.get<Review[]>('/reviews', {
            params: { listing_id: listing!.id, review_type: 'property' },
        })).data,
    })
    const { data: myReviews = [] } = useQuery({
        queryKey: ['reviews', 'mine', 'listing-detail', listing?.id, 'property'],
        enabled: user?.role === 'tenant' && !!listing?.id,
        queryFn: async () => (await api.get<Review[]>('/reviews', {
            params: {
                listing_id: listing!.id,
                review_type: 'property',
                mine: true,
            },
        })).data,
    })
    const { data: subscriptionPaymentResponse, isLoading: isSubscriptionPaymentsLoading } = useQuery({
        queryKey: ['subscription-payments', 'listing-detail', user?.id],
        enabled: user?.role === 'tenant',
        queryFn: async () => (await api.get<SubscriptionPaymentRecord[] | { results?: SubscriptionPaymentRecord[] }>('/subscriptions')).data,
    })
    const { data: viewingRequests = [] } = useQuery({
        queryKey: ['listing', listing?.id, 'viewing-requests'],
        enabled: isListingLandlord,
        queryFn: async () => (await api.get<TenantViewingRequest[]>(`/messages/listing/${listing!.id}/viewing-requests`)).data,
    })

    // Check if this listing is in user's favourites
    const { data: favourites } = useQuery({
        queryKey: ['me', 'favourites'],
        queryFn: async () => (await api.get<Listing[]>('/users/me/favourites')).data,
        enabled: canManageFavourites
    })

    const isFavourite = favourites?.some(f => f.id === listing?.id)
    const existingReview = myReviews[0]
    const landlordProfileHref = listing ? `/landlords/${listing.landlord_id}?listingId=${listing.id}` : '#'
    const isBronzeTenant = user?.role === 'tenant' && subscriptionPaymentResponse !== undefined && hasBronzeAccess(subscriptionPaymentResponse)
    const canSeePreciseLocation = isListingLandlord
        || user?.role === 'admin'
        || (
            user?.role === 'tenant'
            && subscriptionPaymentResponse !== undefined
            && hasSilverAccess(subscriptionPaymentResponse)
        )
    const canReviewAsTenant = user?.role === 'tenant' && subscriptionPaymentResponse !== undefined && hasGoldAccess(subscriptionPaymentResponse)
    const canSeePropertyVerification = isListingLandlord
        || user?.role === 'admin'
        || (
            user?.role === 'tenant'
            && subscriptionPaymentResponse !== undefined
            && hasGoldAccess(subscriptionPaymentResponse)
        )
    const canLoadNearestAmenities = !!listing?.id && canSeePreciseLocation
    const { data: nearestAmenities } = useQuery({
        queryKey: ['listing', listing?.id, 'nearest-amenities'],
        enabled: canLoadNearestAmenities,
        queryFn: async () => (await api.get<NearestAmenitiesResponse>(`/listings/${listing!.id}/nearest-amenities`)).data,
    })
    const amenityGroups = nearestAmenities
        ? Object.entries(nearestAmenities.amenities).filter(([, items]) => items.length > 0)
        : []

    const toggleFavourite = useMutation({
        mutationFn: async () => {
            if (isFavourite) {
                await api.delete(`/users/me/favourites/${listing!.id}`)
            } else {
                await api.post(`/users/me/favourites/${listing!.id}`)
            }
        },
        onMutate: async () => {
            if (!listing) {
                return { previousFavourites: qc.getQueryData<Listing[]>(['me', 'favourites']) || [] }
            }

            await qc.cancelQueries({ queryKey: ['me', 'favourites'] })
            const previousFavourites = qc.getQueryData<Listing[]>(['me', 'favourites']) || []

            qc.setQueryData<Listing[]>(['me', 'favourites'], (current = []) => {
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
                qc.setQueryData(['me', 'favourites'], context.previousFavourites)
            }
            alert(`Failed to ${isFavourite ? 'remove from' : 'add to'} favourites: ${error.message}`)
        },
        onSettled: () => {
            qc.invalidateQueries({ queryKey: ['me', 'favourites'] })
        },
    })

    const submitReview = useMutation({
        mutationFn: async ({ rating, comment }: { rating: number; comment: string }) => {
            if (!listing?.id) {
                throw new Error('Property review is unavailable.')
            }
            if (!canReviewAsTenant) {
                throw new Error('Property reviews are available from the Gold plan.')
            }

            if (existingReview?.id) {
                await api.patch(`/reviews/${existingReview.id}`, {
                    review_type: 'property',
                    listing_id: listing.id,
                    rating,
                    comment,
                })
                return
            }

            await api.post('/reviews', {
                review_type: 'property',
                listing_id: listing.id,
                rating,
                comment,
            })
        },
        onSuccess: async () => {
            setIsReviewOpen(false)
            await Promise.all([
                qc.invalidateQueries({ queryKey: ['reviews', 'listing', listing?.id] }),
                qc.invalidateQueries({ queryKey: ['reviews', 'mine', 'listing-detail', listing?.id] }),
                qc.invalidateQueries({ queryKey: ['landlord', 'public-profile', listing?.landlord_id] }),
            ])
            alert('Review saved successfully.')
        },
        onError: (error) => {
            alert(extractErrorMessage(error, 'Unable to save your review.'))
        },
    })



    const allImages = listing
        ? [...new Set([listing.cover_image_url, ...(listing.image_urls || [])])].filter(Boolean) as string[]
        : []

    useEffect(() => {
        setCurrentImageIndex(0)
        setShowMap(false)
    }, [listing?.id])

    const nextImage = () => {
        setCurrentImageIndex((prev) => (prev + 1) % allImages.length)
    }

    const prevImage = () => {
        setCurrentImageIndex((prev) => (prev - 1 + allImages.length) % allImages.length)
    }

    useEffect(() => {
        const activeThumbnail = thumbnailButtonRefs.current[currentImageIndex]
        activeThumbnail?.scrollIntoView({
            behavior: 'smooth',
            block: 'nearest',
            inline: 'center',
        })
    }, [currentImageIndex])

    const tenantProfileStatus = tenantProfile?.status
    const isVerifiedFresh = freshUser?.is_verified ?? user?.is_verified
    const isTenantVerificationLoading = user?.role === 'tenant' && (isTenantProfileLoading || isFreshUserLoading)
    const tenantIdentityVerified = Boolean(isVerifiedFresh || tenantProfileStatus === 'approved')
    const tenantVerificationStatus = tenantIdentityVerified ? 'approved' : tenantProfileStatus || 'unverified'
    const requiresTenantVerification = user?.role === 'tenant' && !isTenantVerificationLoading && !tenantIdentityVerified
    const isTenantSubscriptionLoading = user?.role === 'tenant' && !requiresTenantVerification && isSubscriptionPaymentsLoading
    const requiresTenantSubscription = user?.role === 'tenant' && !requiresTenantVerification && isBronzeTenant

    const redirectToTenantVerification = () => {
        navigate('/verify')
    }

    const redirectToBilling = () => {
        navigate('/billing')
    }

    const handleArrangeViewing = () => {
        if (!user) {
            alert('Please login to continue')
            navigate('/login')
            return
        }
        if (requiresTenantVerification) {
            redirectToTenantVerification()
            return
        }
        if (isBronzeTenant) {
            alert('Arranging a viewing is not available on the Bronze free plan.')
            navigate('/billing')
            return
        }
        navigate(`/contact-landlord/${listing!.id}`)
    }

    const handleRentNow = () => {
        if (!user) {
            alert('Please login to rent this property')
            navigate('/login')
            return
        }
        if (requiresTenantVerification) {
            redirectToTenantVerification()
            return
        }
        if (isBronzeTenant) {
            alert('Renting property is not available on the Bronze free plan.')
            navigate('/billing')
            return
        }
        navigate(`/rent/${listing!.id}`)
    }

    const listingLocationSummary = listing
        ? !canSeePreciseLocation
            ? listing.state || 'State not provided'
            : `${listing.city}, ${listing.state || ''} ${listing.postal_code}`.trim()
        : ''
    const mapLocationQuery = listing
        ? [listing.city, listing.state, 'Nigeria'].filter(Boolean).join(', ')
        : ''
    const googleMapsUrl = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(mapLocationQuery)}`
    const googleMapEmbedSrc = `https://www.google.com/maps?q=${encodeURIComponent(mapLocationQuery)}&output=embed`

    if (isLoading) {
        return (
            <div className="min-h-[80vh] flex items-center justify-center bg-gray-50">
                <div className="animate-pulse text-gray-500">Loading listing…</div>
            </div>
        )
    }

    if (!listing) {
        return (
            <div className="min-h-[80vh] flex items-center justify-center bg-gray-50">
                <div className="text-gray-500">Listing not found.</div>
            </div>
        )
    }

    return (
        <div className="min-h-screen bg-gray-50 py-8">
            <div className="container-modern">
                {/* Main Image with Horizontal Scrolling */}
                <div className="mb-8">
                    <div className="relative">
                        {/* Main Image */}
                        <div className="relative h-96 max-w-6xl mx-auto rounded-2xl overflow-hidden shadow-lg">
                            <img
                                className="h-full w-full object-cover"
                                src={resolveMediaUrl(allImages[currentImageIndex])}
                                alt={`${listing.title} - Image ${currentImageIndex + 1}`}
                                loading="eager"
                                decoding="async"
                                onError={(e) => {
                                    e.currentTarget.src = '/placeholder.jpg'
                                }}
                            />

                            {/* Navigation Arrows */}
                            {allImages.length > 1 && (
                                <>
                                    <button
                                        onClick={prevImage}
                                        className="absolute left-4 top-1/2 -translate-y-1/2 bg-black/50 hover:bg-black/70 text-white p-2 rounded-full transition-colors"
                                    >
                                        <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                                        </svg>
                                    </button>
                                    <button
                                        onClick={nextImage}
                                        className="absolute right-4 top-1/2 -translate-y-1/2 bg-black/50 hover:bg-black/70 text-white p-2 rounded-full transition-colors"
                                    >
                                        <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                                        </svg>
                                    </button>
                                </>
                            )}

                            {/* Image Counter */}
                            {allImages.length > 1 && (
                                <div className="absolute bottom-4 right-4 bg-black/50 text-white px-3 py-1 rounded-full text-sm">
                                    {currentImageIndex + 1} / {allImages.length}
                                </div>
                            )}
                        </div>

                        {/* Thumbnail Gallery with Horizontal Scroll */}
                        {allImages.length > 1 && (
                            <div className="relative mt-4 max-w-2xl mx-auto">
                                {allImages.length > 4 && (
                                    <button
                                        onClick={prevImage}
                                        className="absolute left-0 top-1/2 -translate-y-1/2 z-10 bg-black/50 hover:bg-black/70 text-white p-1.5 rounded-full transition-colors"
                                    >
                                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                                        </svg>
                                    </button>
                                )}
                                <div
                                    ref={thumbnailContainerRef}
                                    className="flex gap-2 overflow-x-auto scrollbar-hide px-10 py-1"
                                    style={{ scrollBehavior: 'smooth' }}
                                >
                                    {allImages.map((img, idx) => (
                                        <button
                                            key={idx}
                                            onClick={() => setCurrentImageIndex(idx)}
                                            ref={(element) => {
                                                thumbnailButtonRefs.current[idx] = element
                                            }}
                                            className={`flex-shrink-0 w-20 h-20 rounded-lg overflow-hidden border-2 transition ${idx === currentImageIndex
                                                ? 'border-blue-500 ring-2 ring-blue-200'
                                                : 'border-transparent hover:border-gray-300'
                                                }`}
                                        >
                                            <img
                                                src={resolveMediaUrl(img)}
                                                alt={`${listing.title} - thumbnail ${idx + 1}`}
                                                loading="lazy"
                                                decoding="async"
                                                className="w-full h-full object-cover"
                                                onError={(e) => {
                                                    e.currentTarget.src = '/placeholder.jpg'
                                                }}
                                            />
                                        </button>
                                    ))}
                                </div>
                                {allImages.length > 4 && (
                                    <button
                                        onClick={nextImage}
                                        className="absolute right-0 top-1/2 -translate-y-1/2 z-10 bg-black/50 hover:bg-black/70 text-white p-1.5 rounded-full transition-colors"
                                    >
                                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                                        </svg>
                                    </button>
                                )}
                            </div>
                        )}
                    </div>
                </div>

                <div className="max-w-6xl mx-auto">
                    <div className="grid grid-cols-1 gap-3 lg:grid-cols-5">
                        {/* Price + Actions */}
                        <div className="rounded-2xl bg-white px-3 pb-3 pt-6 shadow-lg border">
                            <p className="text-[16px] font-bold text-gray-900 text-center">
                                {isLandlordUser ? 'Property Management' : 'Start Rental Journey'}
                            </p>
                            <div className="mt-6 space-y-3">
                                {isLandlordUser ? (
                                    <>
                                        <div className="rounded-lg bg-slate-50 border border-slate-200 p-3 text-sm text-slate-700">
                                            <div className="flex items-center justify-between">
                                                <span>Status</span>
                                                <span className="font-semibold text-gray-900">{formatStatusLabel(listing.status)}</span>
                                            </div>
                                            <div className="mt-2 flex items-center justify-between">
                                                <span>Tenant requests</span>
                                                <span className="font-semibold text-gray-900">{viewingRequests.length}</span>
                                            </div>
                                        </div>
                                        {isListingLandlord ? (
                                            <>
                                                <button
                                                    onClick={() => navigate(`/listings/${listing.id}/edit`)}
                                                    className="w-full rounded-lg bg-blue-600 px-4 py-3 font-medium text-white hover:bg-blue-700 transition"
                                                >
                                                    Edit Property
                                                </button>
                                                <button
                                                    onClick={() => navigate('/dashboard/landlord/' + user!.id)}
                                                    className="w-full rounded-lg bg-slate-100 px-4 py-3 font-medium text-slate-700 hover:bg-slate-200 transition"
                                                >
                                                    Open Landlord Dashboard
                                                </button>
                                            </>
                                        ) : (
                                            <div className="rounded-lg bg-amber-50 border border-amber-200 p-3 text-sm text-amber-800">
                                                This property belongs to another landlord account.
                                            </div>
                                        )}
                                    </>
                                ) : (
                                    <>
                                        {canManageFavourites && (
                                            <button
                                                onClick={() => toggleFavourite.mutate()}
                                                disabled={toggleFavourite.isPending}
                                                className={`text-sm w-full rounded-lg px-3 py-1.5 font-medium transition ${isFavourite
                                                    ? 'bg-red-100 text-red-700 hover:bg-red-200'
                                                    : 'bg-blue-200 text-black-700 hover:bg-purple-600'
                                                    }`}
                                            >
                                                {toggleFavourite.isPending ? '...' : (
                                                    isFavourite ? '❤️ Remove from Favourites' : '🤍 Add to Favourites'
                                                )}
                                            </button>
                                        )}

                                        {user?.role === 'tenant' && (
                                            <button
                                                onClick={() => {
                                                    if (!canReviewAsTenant) {
                                                        alert('Property reviews are available from the Gold plan.')
                                                        navigate('/billing')
                                                        return
                                                    }
                                                    setIsReviewOpen(true)
                                                }}
                                                className={`text-sm w-full rounded-lg px-3 py-1.5 font-medium transition ${!canReviewAsTenant
                                                    ? 'bg-gray-100 text-gray-500 hover:bg-gray-200'
                                                    : 'bg-amber-400 text-blue-900 hover:bg-amber-600'
                                                    }`}
                                            >
                                                {!canReviewAsTenant ? 'Upgrade to Review' : existingReview ? 'Edit Property Review' : 'Review Property'}
                                            </button>
                                        )}

                                        {isTenantVerificationLoading || isTenantSubscriptionLoading ? (
                                            <div className="rounded-lg bg-slate-50 border border-slate-200 p-3 text-sm text-slate-700">
                                                Checking your account access...
                                            </div>
                                        ) : requiresTenantVerification ? (
                                            <div className="rounded-lg bg-amber-50 border border-amber-200 p-3 text-sm text-amber-800">
                                                <p className="text-sm font-medium">Verification Required</p>
                                                <p className="text-xs mt-1">
                                                    {tenantVerificationStatus === 'pending' || tenantVerificationStatus === 'under_review'
                                                        ? 'Your tenant verification is still pending review. Open the verification page to check status and continue.'
                                                        : 'Please complete your tenant verification before you can contact landlords or rent this property.'}
                                                </p>
                                                <button
                                                    onClick={redirectToTenantVerification}
                                                    className="text-sm mt-2 text-blue-600 hover:text-blue-700 font-medium text-sm underline"
                                                >
                                                    Complete Verification
                                                </button>
                                            </div>
                                        ) : requiresTenantSubscription ? (
                                            <div className="rounded-lg bg-blue-50 border border-blue-200 p-3 text-sm text-blue-800">
                                                <p className="text-sm font-medium">Subscription Required</p>
                                                <p className="mt-1">
                                                    Upgrade your tenant subscription to contact landlords, arrange viewing, or rent this property.
                                                </p>
                                                <button
                                                    onClick={redirectToBilling}
                                                    className="text-sm mt-3 w-full rounded-lg bg-blue-600 px-3 py-1.5 font-medium text-white hover:bg-blue-700 transition"
                                                >
                                                    Upgrade to Continue
                                                </button>
                                            </div>
                                        ) : (
                                            <>
                                                <button
                                                    onClick={handleArrangeViewing}
                                                    className="text-sm w-full rounded-lg bg-blue-500 px-3 py-1.5 font-medium text-white hover:bg-blue-800 transition"
                                                >
                                                    Arrange viewing
                                                </button>

                                                <button
                                                    onClick={handleRentNow}
                                                    className="text-sm w-full rounded-lg bg-green-500 px-3 py-1.5 font-medium text-white hover:bg-green-800 transition"
                                                >
                                                    Rent Now
                                                </button>
                                            </>
                                        )}
                                    </>
                                )}
                            </div>
                        </div>

                        {/* Property Details with Icons */}
                        <div className="rounded-2xl bg-white p-6 shadow-lg border">
                            <p className="text-[16px] font-bold text-gray-900 mb-3 text-center">Property Details</p>
                            <br />
                            <div className="space-y-4">
                                {/* Amount/Duration */}
                                <p className="text-[16px] font-semibold text-gray-900 mb-3">{formatCurrencyWithSymbol(listing.price_per_year)}/year</p>

                                {/* Rooms and Location */}
                                <div className="text-sm text-gray-600">
                                    {listing.bedrooms} Bed {listing.property_type}, {!canSeePreciseLocation ? listing.state || 'State not provided' : `${listing.city}${listing.state ? `, ${listing.state}` : ''}`}
                                </div>

                                {/* Bedroom and Bathroom Icons */}
                                <div className="flex items-center space-x-4">
                                    <div className="flex items-center space-x-2">
                                        <Icons.bedrooms />
                                        <span className="font-medium">{listing.bedrooms}</span>
                                    </div>
                                    <div className="flex items-center space-x-2">
                                        <Icons.bathrooms />
                                        <span className="font-medium">{listing.bathrooms}</span>
                                    </div>
                                    {listing.toilets ? (
                                        <div className="flex items-center space-x-2">
                                            <Icons.toilets />
                                            <span className="font-medium">{listing.toilets}</span>
                                        </div>
                                    ) : null}
                                </div>

                                {listing.deposit_amount && (
                                    <div className="pt-2 border-t border-gray-100">
                                        <div className="flex items-center justify-between">
                                            <span className="text-gray-600">Deposit:</span>
                                            <span className="font-medium">{formatCurrencyWithSymbol(listing.deposit_amount)}</span>
                                        </div>
                                    </div>
                                )}
                            </div>
                        </div>

                        {canSeePropertyVerification && listing.property_document_verification_status === 'verified' && (
                            <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-6 shadow-lg">
                                <p className="text-[16px] font-bold text-emerald-900">Property verification</p>
                                <p className="mt-3 text-sm font-medium text-emerald-800">
                                    ✓ This property has passed RentDirect property verification.
                                </p>
                            </div>
                        )}

                        {/* Features */}
                        <div className="rounded-2xl bg-white p-6 shadow-lg border">
                            <p className="text-[16px] font-bold text-gray-900 mb-3 text-center">Features</p>
                            <br />
                            <div className="flex flex-wrap gap-4 text-sm">
                                <ul className="list-none space-y-4">
                                    <li>{listing.utilities_included && (
                                        <span className="px-2 py-1 bg-green-100 text-green-800 rounded-full">
                                            Utilities Included
                                        </span>
                                    )}
                                    </li>
                                    <li>{listing.pet_friendly && (
                                        <span className="px-2 py-1 bg-blue-100 text-blue-800 rounded-full">
                                            Pet Friendly?
                                        </span>
                                    )}
                                    </li>
                                    <li>{listing.furnished && (
                                        <span className="px-2 py-1 bg-purple-100 text-purple-800 rounded-full">
                                            Furnished
                                        </span>
                                    )}
                                    </li>
                                </ul>
                            </div>
                        </div>

                        {/* Location with Map */}
                        <div className="rounded-2xl bg-white p-6 shadow-lg border text-center">
                            <p className="text-[16px] font-bold text-gray-900 mb-3">Location</p>
                            <br />
                            <p className="text-gray-700 flex flex-col gap-3 text-sm text-center">
                                {listingLocationSummary}
                                {!canSeePreciseLocation ? (
                                    <span className="rounded-lg bg-amber-50 px-3 py-2 text-amber-800">
                                        Sign in with a Silver or higher tenant plan to see the full address and map.
                                    </span>
                                ) : (
                                    <>
                                        {!showMap ? (
                                            <button
                                                type="button"
                                                onClick={() => setShowMap(true)}
                                                className="btn btn-outline p-1"
                                            >
                                                Show in map
                                            </button>
                                        ) : (
                                            <div className="h-72 rounded-lg overflow-hidden border border-gray-200">
                                                <iframe
                                                    title={`${listing.title} map`}
                                                    src={googleMapEmbedSrc}
                                                    className="h-full w-full border-0"
                                                    loading="lazy"
                                                    referrerPolicy="no-referrer-when-downgrade"
                                                />
                                            </div>
                                        )}
                                        <a
                                            className="inline-block mt-1 font-semibold text-[14px] text-blue-800 hover:text-blue-800"
                                            href={googleMapsUrl}
                                            target="_blank"
                                            rel="noreferrer"
                                        >
                                            Open in Google maps
                                        </a>
                                    </>
                                )}
                            </p>

                        </div>
                    </div>

                    {landlordProfile && !isLandlordUser && (
                        <div className="mt-4 rounded-2xl bg-white p-6 shadow-lg border">
                            <div className="flex flex-col gap-5 md:flex-row md:items-center md:justify-between">
                                <div className="flex items-center gap-4">
                                    <img
                                        src={resolveMediaUrl(landlordProfile.profile_photo_url || listing.landlord_profile_photo_url)}
                                        alt={landlordProfile.display_name}
                                        loading="lazy"
                                        decoding="async"
                                        className="h-20 w-20 rounded-2xl object-cover ring-4 ring-slate-100"
                                    />
                                    <div>
                                        <p className="text-[20px] font-bold text-gray-900 mb-3">Landlord</p>
                                        <p className="mt-2 text-base font-semibold text-gray-900">{landlordProfile.display_name}</p>
                                        <p className="mt-1 text-sm text-gray-600">
                                            {landlordProfile.metrics.properties_listed} properties listed
                                        </p>
                                    </div>
                                </div>
                                <div className="flex gap-2">
                                    <Link to={landlordProfileHref} className="btn btn-outline hover:text-white-800">
                                        View Landlord Profile
                                    </Link>
                                    <Link to={`/landlords/${listing.landlord_id}/properties`} className="btn btn-outline hover:text-white-800">
                                        View All Landlord Properties
                                    </Link>
                                </div>
                            </div>
                        </div>
                    )}

                    {isListingLandlord && (
                        <div className="mt-4 rounded-2xl bg-white p-6 shadow-lg border">
                            <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
                                <div>
                                    <h3 className="text-xl font-semibold text-gray-900">Viewing Requests</h3>
                                    <p className="mt-1 text-sm text-gray-600">Tenants who have requested a viewing for this property.</p>
                                </div>
                                <span className="rounded-full bg-blue-50 px-4 py-2 text-sm font-semibold text-blue-700">
                                    {viewingRequests.length} tenant{viewingRequests.length === 1 ? '' : 's'}
                                </span>
                            </div>

                            {viewingRequests.length > 0 ? (
                                <div className="mt-5 overflow-hidden rounded-xl border border-slate-200">
                                    <div className="hidden grid-cols-[1.5fr_1fr_1fr_1fr] gap-4 bg-slate-50 px-4 py-3 text-xs font-semibold uppercase text-slate-500 md:grid">
                                        <span>Tenant</span>
                                        <span>Stage</span>
                                        <span>Progress</span>
                                        <span>Last Message</span>
                                    </div>
                                    <div className="divide-y divide-slate-200">
                                        {viewingRequests.map((request) => (
                                            <div key={request.tenant_id} className="grid gap-4 px-4 py-4 md:grid-cols-[1.5fr_1fr_1fr_1fr] md:items-center">
                                                <div className="flex items-center gap-3">
                                                    <img
                                                        src={resolveMediaUrl(request.tenant_profile_photo_url)}
                                                        alt={request.tenant_name}
                                                        loading="lazy"
                                                        decoding="async"
                                                        className="h-11 w-11 rounded-full object-cover"
                                                        onError={(event) => {
                                                            event.currentTarget.src = '/placeholder.jpg'
                                                        }}
                                                    />
                                                    <div>
                                                        <p className="font-semibold text-gray-900">{request.tenant_name}</p>
                                                        <p className="text-sm text-gray-500">{request.tenant_email}</p>
                                                    </div>
                                                </div>
                                                <div>
                                                    <span className="rounded-full bg-emerald-50 px-3 py-1 text-sm font-semibold text-emerald-700">
                                                        {request.stage}
                                                    </span>
                                                    {request.booking_status ? (
                                                        <p className="mt-2 text-xs text-slate-500">{formatStatusLabel(request.booking_status)}</p>
                                                    ) : null}
                                                </div>
                                                <div>
                                                    <p className="text-sm font-semibold text-gray-900">
                                                        {request.rental_progress ? `${request.rental_progress.progress_percent}%` : 'Not started'}
                                                    </p>
                                                    <p className="mt-1 text-xs text-slate-500">
                                                        {request.rental_progress
                                                            ? `${request.rental_progress.completed_count}/${request.rental_progress.total_count} steps`
                                                            : 'No booking yet'}
                                                    </p>
                                                </div>
                                                <div>
                                                    <p className="line-clamp-2 text-sm text-gray-700">{request.last_message}</p>
                                                    <Link
                                                        to={`/contact-landlord/${listing.id}?tenantId=${request.tenant_id}`}
                                                        className="mt-2 inline-block text-sm font-semibold text-blue-700 hover:text-blue-800"
                                                    >
                                                        Open conversation
                                                    </Link>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            ) : (
                                <div className="mt-5 rounded-xl border border-dashed border-slate-200 p-6 text-center text-slate-500">
                                    No tenant has requested a viewing for this property yet.
                                </div>
                            )}
                        </div>
                    )}

                    {/* Description */}
                    <div className="mt-4 rounded-2xl bg-white p-6 shadow-lg border">
                        <h2 className="text-[20px] font-semibold text-gray-900">{listing.title}</h2>
                        <p className="text-gray-700 leading-relaxed">{listing.description}</p>

                        {listing.amenities && listing.amenities.length > 0 && (
                            <div className="mt-6">
                                <p className="text-[20px] font-semibold text-gray-900">Amenities</p>
                                <div className="flex flex-wrap gap-2">
                                    {listing.amenities.map((amenity, idx) => (
                                        <span key={idx} className="text-[14px] px-3 py-1 bg-gray-100 text-gray-800 rounded-full">
                                            {amenity}
                                        </span>
                                    ))}
                                </div>
                            </div>
                        )}
                    </div>

                    {canSeePreciseLocation && nearestAmenities ? (
                        <div className="mt-4 rounded-2xl bg-white p-6 shadow-lg border">
                            <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
                                <div>
                                    <h3 className="text-xl font-semibold text-gray-900">Nearest Amenities</h3>
                                    <p className="mt-1 text-sm text-gray-600">
                                        Within {nearestAmenities.radius_km || 25} km of {[listing.city, listing.state].filter(Boolean).join(', ') || 'the property'}
                                    </p>
                                </div>
                            </div>

                            {amenityGroups.length > 0 ? (
                                <div className="mt-5 grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
                                    {amenityGroups.map(([category, items]) => (
                                        <div key={category} className="rounded-xl border border-slate-200 p-4">
                                            <h4 className="text-sm font-semibold text-gray-900">
                                                {amenityCategoryLabels[category] || category}
                                            </h4>
                                            <div className="mt-3 space-y-3">
                                                {items.map((amenity) => (
                                                    <div key={`${category}-${amenity.name}`} className="flex items-start justify-between gap-3">
                                                        <div>
                                                            <p className="text-sm font-medium text-gray-900">{amenity.name}</p>
                                                            <p className="text-xs text-gray-500">{amenity.city}, {amenity.state}</p>
                                                        </div>
                                                        <span className="rounded-full bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700">
                                                            {amenity.distance_km.toFixed(1)} km
                                                        </span>
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            ) : (
                                <div className="mt-5 rounded-xl border border-dashed border-slate-200 p-6 text-center text-slate-500">
                                    No nearby amenities found within {nearestAmenities.radius_km || 25} km.
                                </div>
                            )}
                        </div>
                    ) : null}

                    <div className="mt-4 rounded-2xl bg-white p-6 shadow-lg border">
                        <div className="flex items-center justify-between gap-4">
                            <div>
                                <h3 className="text-xl font-semibold text-gray-900">Property Reviews</h3>
                                <p className="mt-2 text-sm text-gray-600">What tenants are saying about this property.</p>
                            </div>
                            <div className="rounded-full bg-slate-100 px-4 py-2 text-sm font-medium text-slate-700">
                                {propertyReviews.length} review{propertyReviews.length === 1 ? '' : 's'}
                            </div>
                        </div>

                        {propertyReviews.length > 0 ? (
                            <div className="mt-4 grid gap-4">
                                {propertyReviews.map((review) => (
                                    <div key={review.id} className="rounded-2xl border border-slate-200 p-4">
                                        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                                            <div>
                                                <p className="text-lg text-amber-500">{renderStars(review.rating)}</p>
                                                <p className="mt-2 text-gray-800">
                                                    {review.comment || 'Tenant left a rating without a written review.'}
                                                </p>
                                            </div>
                                            <p className="text-sm font-medium text-slate-600">{review.tenant_name || 'Tenant'}</p>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        ) : (
                            <div className="mt-4 rounded-2xl border border-dashed border-slate-200 p-6 text-center text-slate-500">
                                No reviews for this property yet.
                            </div>
                        )}
                    </div>


                </div>
            </div>

            <ReviewModal
                isOpen={isReviewOpen}
                title="Review this property"
                initialRating={existingReview?.rating || 5}
                initialComment={existingReview?.comment || ''}
                onClose={() => setIsReviewOpen(false)}
                onSubmit={(payload) => submitReview.mutate(payload)}
                isSubmitting={submitReview.isPending}
            />
        </div>
    )
}
