import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import ReviewModal from '@/components/ReviewModal'
import { useAuth } from '@/hooks/useAuth'
import { api, resolveMediaUrl } from '@/lib/api'
import { hasBronzeAccess, SubscriptionPaymentRecord } from '@/lib/subscriptions'
import { LandlordPublicProfile, Review } from '@/types'

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

export default function PublicLandlordProfilePage() {
    const { landlordId } = useParams()
    const [searchParams] = useSearchParams()
    const { user } = useAuth()
    const qc = useQueryClient()
    const initialListingId = searchParams.get('listingId') || ''
    const [selectedListingId, setSelectedListingId] = useState(initialListingId)
    const [isReviewOpen, setIsReviewOpen] = useState(false)

    const { data: profile, isLoading, isError } = useQuery({
        queryKey: ['landlord', 'public-profile', landlordId],
        enabled: !!landlordId,
        queryFn: async () => (await api.get<LandlordPublicProfile>(`/users/landlords/${landlordId}/public-profile`)).data,
    })

    useEffect(() => {
        if (initialListingId) {
            setSelectedListingId(initialListingId)
            return
        }
        if (!selectedListingId && profile?.listings?.length) {
            setSelectedListingId(profile.listings[0].id)
        }
    }, [initialListingId, profile?.listings, selectedListingId])

    const reviewableListings = (profile?.listings || []).map((listing) => ({ id: listing.id, title: listing.title }))

    const { data: myReviews = [] } = useQuery({
        queryKey: ['reviews', 'mine', 'landlord-profile', selectedListingId, 'landlord'],
        enabled: user?.role === 'tenant' && !!selectedListingId,
        queryFn: async () => (await api.get<Review[]>('/reviews', {
            params: {
                listing_id: selectedListingId,
                review_type: 'landlord',
                mine: true,
            },
        })).data,
    })
    const { data: subscriptionPaymentResponse } = useQuery({
        queryKey: ['subscription-payments', 'landlord-profile', user?.id],
        enabled: user?.role === 'tenant',
        queryFn: async () => (await api.get<SubscriptionPaymentRecord[] | { results?: SubscriptionPaymentRecord[] }>('/subscriptions')).data,
    })

    const existingReview = myReviews[0]
    const isBronzeTenant = user?.role === 'tenant' && subscriptionPaymentResponse !== undefined && hasBronzeAccess(subscriptionPaymentResponse)

    const submitReview = useMutation({
        mutationFn: async ({ rating, comment }: { rating: number; comment: string }) => {
            if (!selectedListingId) {
                throw new Error('Select a property before submitting a review.')
            }
            if (isBronzeTenant) {
                throw new Error('Reviews are not available on the Bronze free plan.')
            }

            if (existingReview?.id) {
                await api.patch(`/reviews/${existingReview.id}`, {
                    review_type: 'landlord',
                    listing_id: selectedListingId,
                    rating,
                    comment,
                })
                return
            }

            await api.post('/reviews', {
                review_type: 'landlord',
                listing_id: selectedListingId,
                rating,
                comment,
            })
        },
        onSuccess: async () => {
            setIsReviewOpen(false)
            await Promise.all([
                qc.invalidateQueries({ queryKey: ['landlord', 'public-profile', landlordId] }),
                qc.invalidateQueries({ queryKey: ['reviews', 'mine', 'landlord-profile', selectedListingId] }),
            ])
            alert('Review saved successfully.')
        },
        onError: (error) => {
            alert(extractErrorMessage(error, 'Unable to save your review.'))
        },
    })

    if (isLoading) {
        return (
            <div className="container-modern py-8">
                <div className="card p-6 text-gray-600">Loading landlord profile...</div>
            </div>
        )
    }

    if (isError || !profile) {
        return (
            <div className="container-modern py-8">
                <div className="card p-6">
                    <h1 className="text-2xl font-bold text-gray-900">Unable to load landlord profile</h1>
                    <p className="mt-2 text-gray-600">Please refresh the page and try again.</p>
                </div>
            </div>
        )
    }

    return (
        <div className="container-modern py-8">
            <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
                <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
                    <div className="flex flex-col gap-5 sm:flex-row sm:items-center">
                        <img
                            src={resolveMediaUrl(profile.profile_photo_url)}
                            alt={profile.display_name}
                            className="h-28 w-28 rounded-3xl object-cover ring-4 ring-slate-100"
                        />
                        <div>
                            <p className="text-sm font-medium uppercase tracking-[0.2em] text-emerald-600">Landlord Profile</p>
                            <h1 className="mt-2 text-3xl font-bold text-slate-900">{profile.display_name}</h1>
                            <p className="mt-2 text-sm font-medium text-slate-700">Full Name: {profile.full_name}</p>
                            <p className="mt-2 text-sm text-slate-600">{profile.subtitle}</p>
                            <div className="mt-4 flex flex-wrap gap-2">
                                <span className="rounded-full bg-amber-100 px-3 py-1 text-sm font-medium text-amber-700">
                                    {profile.metrics.average_rating ? `${profile.metrics.average_rating.toFixed(1)} / 5 rating` : 'No rating yet'}
                                </span>
                                <span className="rounded-full bg-slate-100 px-3 py-1 text-sm font-medium text-slate-700">
                                    listed properties: {profile.metrics.properties_listed}
                                </span>
                            </div>
                        </div>
                    </div>

                    <div className="flex flex-wrap gap-3">
                        {user?.role === 'tenant' && reviewableListings.length > 0 ? (
                            <button
                                type="button"
                                onClick={() => {
                                    if (isBronzeTenant) {
                                        alert('Reviews are not available on the Bronze free plan.')
                                        return
                                    }
                                    setIsReviewOpen(true)
                                }}
                                className={isBronzeTenant ? 'btn btn-outline' : 'btn btn-primary'}
                            >
                                {isBronzeTenant ? 'Upgrade to Review' : existingReview ? 'Edit Review' : 'Review Landlord'}
                            </button>
                        ) : null}
                        <Link to="/search" className="btn btn-outline">
                            Browse Properties
                        </Link>
                    </div>
                </div>

                <div className="mt-8 rounded-2xl border border-slate-200 bg-slate-50 p-5">
                    <h2 className="text-2xl font-semibold text-blue-600">Verification Badge</h2>
                    <div className="mt-4 grid gap-3 md:grid-cols-2">
                        {[
                            { label: 'Identity Verified', value: profile.verification_badges.identity_verified },
                            { label: 'House Ownership Verified', value: profile.verification_badges.house_ownership_verified },
                            { label: 'Phone Verified', value: profile.verification_badges.phone_verified },
                            { label: 'Email Verified', value: profile.verification_badges.email_verified },
                        ].map((badge) => (
                            <div key={badge.label} className="rounded-xl bg-white px-4 py-3 text-sm font-medium text-slate-800 shadow-sm">
                                <span className={badge.value ? 'text-emerald-600' : 'text-slate-400'}>{badge.value ? '✓' : '○'}</span> {badge.label}
                            </div>
                        ))}
                    </div>
                </div>
            </div>

            <div className="mt-8 grid gap-6 lg:grid-cols-2">
                <section className="card p-6">
                    <h2 className="text-xl font-bold text-blue-600">Reputation Metrics</h2>
                    <div className="mt-5 grid gap-4 sm:grid-cols-2">
                        <div className="rounded-2xl bg-slate-50 p-4">
                            <p className="text-sm text-slate-500">Properties Listed</p>
                            <p className="mt-2 text-2xl font-bold text-slate-900">{profile.metrics.properties_listed}</p>
                        </div>
                        <div className="rounded-2xl bg-slate-50 p-4">
                            <p className="text-sm text-slate-500">Active Tenancies</p>
                            <p className="mt-2 text-2xl font-bold text-slate-900">{profile.metrics.active_tenancies}</p>
                        </div>
                        <div className="rounded-2xl bg-slate-50 p-4">
                            <p className="text-sm text-slate-500">Completed Tenancies</p>
                            <p className="mt-2 text-2xl font-bold text-slate-900">{profile.metrics.completed_tenancies}</p>
                        </div>
                        <div className="rounded-2xl bg-slate-50 p-4">
                            <p className="text-sm text-slate-500">Average Rating</p>
                            <p className="mt-2 text-2xl font-bold text-slate-900">{profile.metrics.average_rating.toFixed(1)}</p>
                        </div>
                        <div className="rounded-2xl bg-slate-50 p-4">
                            <p className="text-sm text-slate-500">Tenant Satisfaction Score</p>
                            <p className="mt-2 text-2xl font-bold text-slate-900">{profile.metrics.tenant_satisfaction_score.toFixed(1)}%</p>
                        </div>
                        <div className="rounded-2xl bg-slate-50 p-4">
                            <p className="text-sm text-slate-500">Reviews</p>
                            <p className="mt-2 text-2xl font-bold text-slate-900">{profile.metrics.reviews_count}</p>
                        </div>
                    </div>
                </section>

                <section className="card p-6">
                    <h2 className="text-xl font-bold text-blue-600">Response Metrics</h2>
                    <div className="mt-5 grid gap-4 sm:grid-cols-2">
                        <div className="rounded-2xl bg-slate-50 p-4">
                            <p className="text-sm text-slate-500">Average Response Time</p>
                            <p className="mt-2 text-xl font-bold text-slate-900">{profile.metrics.average_response_time}</p>
                        </div>
                        <div className="rounded-2xl bg-slate-50 p-4">
                            <p className="text-sm text-slate-500">Application Approval Rate</p>
                            <p className="mt-2 text-xl font-bold text-slate-900">{profile.metrics.application_approval_rate.toFixed(1)}%</p>
                        </div>
                    </div>

                    <h2 className="mt-8 text-xl font-bold text-blue-600">Rental History Metrics</h2>
                    <div className="mt-5 grid gap-4 sm:grid-cols-2">
                        <div className="rounded-2xl bg-slate-50 p-4">
                            <p className="text-sm text-slate-500">Years on Platform</p>
                            <p className="mt-2 text-xl font-bold text-slate-900">{profile.metrics.years_on_platform.toFixed(1)}</p>
                        </div>
                        <div className="rounded-2xl bg-slate-50 p-4">
                            <p className="text-sm text-slate-500">Number of Successful Rentals</p>
                            <p className="mt-2 text-xl font-bold text-slate-900">{profile.metrics.successful_rentals}</p>
                        </div>
                    </div>
                </section>
            </div>

            <section className="card mt-8 p-6">
                <div className="flex items-center justify-between gap-4">
                    <div>
                        <h2 className="text-2xl font-bold text-slate-900">Landlord Reviews</h2>
                        <p className="mt-2 text-sm text-slate-600">Feedback from tenants who interacted with this landlord through listed properties.</p>
                    </div>
                    {profile.metrics.reviews_count ? (
                        <div className="rounded-full bg-slate-100 px-4 py-2 text-sm font-medium text-slate-700">
                            {profile.metrics.reviews_count} review{profile.metrics.reviews_count === 1 ? '' : 's'}
                        </div>
                    ) : null}
                </div>

                {profile.reviews.length > 0 ? (
                    <div className="mt-6 grid gap-4">
                        {profile.reviews.map((review) => (
                            <div key={review.id} className="rounded-2xl border border-slate-200 p-5">
                                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                                    <div>
                                        <p className="text-lg text-amber-500">{renderStars(review.rating)}</p>
                                        <p className="mt-2 text-gray-800">
                                            {review.comment || 'Tenant left a rating without a written review.'}
                                        </p>
                                    </div>
                                    <div className="text-sm text-slate-600">
                                        <p className="font-semibold text-slate-900">{review.tenant_name || 'Tenant'}</p>
                                        <p className="mt-1">{review.listing_title}</p>
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>
                ) : (
                    <div className="mt-6 rounded-2xl border border-dashed border-slate-200 p-6 text-center text-slate-500">
                        No landlord reviews yet.
                    </div>
                )}
            </section>

            <ReviewModal
                isOpen={isReviewOpen}
                title={existingReview ? 'Edit landlord review' : 'Review this landlord'}
                initialComment={existingReview?.comment || ''}
                initialRating={existingReview?.rating || 5}
                listingOptions={reviewableListings}
                selectedListingId={selectedListingId}
                onChangeListingId={setSelectedListingId}
                onClose={() => setIsReviewOpen(false)}
                onSubmit={(payload) => submitReview.mutate(payload)}
                isSubmitting={submitReview.isPending}
            />
        </div>
    )
}
