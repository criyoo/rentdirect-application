import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useForm, useFieldArray } from 'react-hook-form'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import { api, getApiUrl } from '@/lib/api'
import { useQuery } from '@tanstack/react-query'
import { Listing, User } from '@/types'
import { useAuth } from '@/hooks/useAuth'

const schema = z.object({
    title: z.string().min(1, 'Title is required'),
    description: z.string().min(1, 'Description is required'),
    address: z.string().min(1, 'Address is required'),
    city: z.string().min(1, 'City is required'),
    state: z.string().min(1, 'State is required'),
    postal_code: z.string().min(1, 'Postal code is required'),
    property_type: z.string().min(1, 'Property type is required'),
    bedrooms: z.number().min(1, 'At least 1 bedroom required'),
    bathrooms: z.number().min(1, 'At least 1 bathroom required'),
    toilets: z.number().min(1, 'At least 1 toilet required'),
    square_feet: z.number().optional(),
    price_per_year: z.number().min(1, 'Price is required'),
    deposit_amount: z.number().optional(),
    utilities_included: z.boolean(),
    pet_friendly: z.boolean(),
    furnished: z.boolean(),
    featured_property: z.boolean(),
    featured_duration: z.number().optional(),
    available_from: z.string().optional(),
    amenities: z.array(z.object({ value: z.string() })),
})

type ListingFormValues = z.infer<typeof schema>

type VerificationProgress = {
    status?: string
}

type VerificationStatusResponse = {
    identification?: VerificationProgress
    property_documents?: VerificationProgress
    physical_property?: VerificationProgress
}

function formatVerificationRequirementLabel(key: keyof VerificationStatusResponse) {
    if (key === 'identification') {
        return 'Identification verification'
    }
    if (key === 'property_documents') {
        return 'Property document verification'
    }
    return 'Physical property verification'
}

function formatVerificationRequirementStatus(status?: string) {
    if (status === 'pending') {
        return 'Pending'
    }
    return 'Unverified'
}

export default function ListingFormPage() {
    const navigate = useNavigate()
    const { id } = useParams()
    const { user } = useAuth()
    const isEditMode = Boolean(id)
    const [coverImage, setCoverImage] = useState<File | null>(null)
    const [additionalImages, setAdditionalImages] = useState<File[]>([])
    const [isSubmitting, setIsSubmitting] = useState(false)

    const {
        register,
        handleSubmit,
        formState: { errors },
        control,
        reset,
    } = useForm<ListingFormValues>({
        resolver: zodResolver(schema),
        defaultValues: {
            title: '',
            description: '',
            address: '',
            city: '',
            state: '',
            postal_code: '',
            property_type: '',
            bedrooms: 1,
            bathrooms: 1,
            toilets: 1,
            utilities_included: false,
            pet_friendly: false,
            furnished: false,
            amenities: [{ value: '' }],
            featured_property: false,
            available_from: '',
        },
    })

    const { fields: amenityFields, append: appendAmenity, remove: removeAmenity } = useFieldArray({
        control,
        name: 'amenities',
    })

    const { data: listing, isLoading: isListingLoading } = useQuery({
        queryKey: ['listing', id, 'edit'],
        queryFn: async () => (await api.get<Listing>(`/listings/${id}`)).data,
        enabled: isEditMode,
    })

    const shouldLoadCurrentUser = !isEditMode && user?.role === 'landlord'
    const { data: currentUser, isLoading: isCurrentUserLoading } = useQuery({
        queryKey: ['users', 'me', 'listing-form'],
        queryFn: async () => (await api.get<User>('/users/me')).data,
        enabled: shouldLoadCurrentUser,
    })

    const { data: verificationStatus, isLoading: isVerificationStatusLoading } = useQuery({
        queryKey: ['verification', 'status', 'listing-form'],
        queryFn: async () => (await api.get<VerificationStatusResponse>('/landlord-verification-requests/status')).data,
        enabled: shouldLoadCurrentUser,
    })

    const pendingVerificationMessages = useMemo(() => {
        const requirementKeys: Array<keyof VerificationStatusResponse> = ['identification', 'property_documents', 'physical_property']
        return requirementKeys
            .map((key) => {
                const status = verificationStatus?.[key]?.status
                if (status !== 'pending' && status !== 'unverified') {
                    return null
                }
                return `${formatVerificationRequirementLabel(key)} (${formatVerificationRequirementStatus(status)})`
            })
            .filter((value): value is string => Boolean(value))
    }, [verificationStatus])

    const landlordUser = currentUser ?? user
    const shouldBlockListingCreation =
        !isEditMode &&
        landlordUser?.role === 'landlord' &&
        pendingVerificationMessages.length > 0

    useEffect(() => {
        if (!listing) {
            return
        }

        reset({
            title: listing.title,
            description: listing.description,
            address: listing.address,
            city: listing.city,
            state: listing.state || '',
            postal_code: listing.postal_code,
            property_type: listing.property_type,
            bedrooms: listing.bedrooms,
            bathrooms: listing.bathrooms,
            toilets: listing.toilets || listing.bathrooms,
            square_feet: listing.square_feet,
            price_per_year: Number(listing.price_per_year),
            deposit_amount: listing.deposit_amount,
            utilities_included: listing.utilities_included,
            pet_friendly: listing.pet_friendly,
            furnished: listing.furnished,
            featured_property: listing.featured,
            featured_duration: undefined,
            available_from: listing.available_from || '',
            amenities: listing.amenities && listing.amenities.length > 0
                ? listing.amenities.map((value) => ({ value }))
                : [{ value: '' }],
        })
    }, [listing, reset])

    const buildFormData = (data: ListingFormValues) => {
        const formData = new FormData()
        formData.append('title', data.title)
        formData.append('description', data.description)
        formData.append('address', data.address)
        formData.append('city', data.city)
        formData.append('state', data.state)
        formData.append('postal_code', data.postal_code)
        formData.append('property_type', data.property_type)
        formData.append('bedrooms', data.bedrooms.toString())
        formData.append('bathrooms', data.bathrooms.toString())
        formData.append('toilets', data.toilets.toString())
        formData.append('price_per_year', data.price_per_year.toString())

        if (data.square_feet) {
            formData.append('square_feet', data.square_feet.toString())
        }
        if (data.deposit_amount) {
            formData.append('deposit_amount', data.deposit_amount.toString())
        }

        formData.append('utilities_included', data.utilities_included.toString())
        formData.append('pet_friendly', data.pet_friendly.toString())
        formData.append('furnished', data.furnished.toString())

        if (data.available_from) {
            formData.append('available_from', data.available_from)
        }

        const amenities = (data.amenities || [])
            .map((item) => item.value.trim())
            .filter((value) => value.length > 0)

        amenities.forEach((amenity) => {
            formData.append('amenities', amenity)
        })

        if (coverImage) {
            formData.append('cover_image', coverImage)
        }
        additionalImages.forEach((image) => {
            formData.append('images', image)
        })

        return formData
    }

    const onSubmit = async (data: ListingFormValues) => {
        if (!isEditMode && !coverImage) {
            alert('Please select a cover image')
            return
        }

        setIsSubmitting(true)

        try {
            const formData = buildFormData(data)
            const endpoint = isEditMode ? `${getApiUrl()}/listings/${id}` : `${getApiUrl()}/listings`
            const method = isEditMode ? 'PATCH' : 'POST'

            const response = await fetch(endpoint, {
                method,
                body: formData,
                credentials: 'include',
            })

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}))
                const detail = (errorData as { detail?: unknown }).detail
                const message =
                    typeof detail === 'string'
                        ? detail
                        : detail
                            ? JSON.stringify(detail)
                            : isEditMode
                                ? 'Failed to update listing'
                                : 'Failed to create listing'
                alert(`Error: ${message}`)
                return
            }

            const result = await response.json()

            if (!isEditMode && data.featured_property) {
                const featuredRes = await fetch(`${getApiUrl()}/featured/request`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'include',
                    body: JSON.stringify({
                        listing_id: result.id,
                        featured_duration_days: 30,
                    }),
                })

                if (featuredRes.ok) {
                    const featuredPayment = await featuredRes.json()
                    navigate(`/dashboard/featured-properties/pay/${featuredPayment.id}`)
                    return
                }

                const featuredErr = await featuredRes.json().catch(() => ({}))
                alert((featuredErr as { detail?: string }).detail || 'Listing created, but failed to start featured payment.')
            }

            navigate(`/listings/${result.id}`)
        } catch (error) {
            console.error(`Error ${isEditMode ? 'updating' : 'creating'} listing:`, error)
            alert(`Failed to ${isEditMode ? 'update' : 'create'} listing. Please try again.`)
        } finally {
            setIsSubmitting(false)
        }
    }

    const handleCoverImageChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files && e.target.files[0]) {
            setCoverImage(e.target.files[0])
        }
    }

    const handleAdditionalImagesChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files) {
            const filesArray = Array.from(e.target.files)
            setAdditionalImages((prev) => {
                const merged = [...prev, ...filesArray]
                if (merged.length > 9) {
                    alert('Maximum 9 additional images allowed')
                }
                return merged.slice(0, 9)
            })
        }
    }

    if (isEditMode && isListingLoading) {
        return <div className="p-6">Loading listing...</div>
    }

    if (shouldLoadCurrentUser && (isCurrentUserLoading || isVerificationStatusLoading)) {
        return <div className="p-6">Loading verification status...</div>
    }

    if (shouldBlockListingCreation) {
        return (
            <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
                <div className="max-w-md w-full bg-white rounded-2xl shadow-lg border p-4 text-center">
                    <div className="w-16 h-16 bg-amber-100 rounded-full flex items-center justify-center mx-auto mb-4">
                        <svg className="w-8 h-8 text-amber-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                        </svg>
                    </div>
                    <h2 className="text-xl font-bold text-gray-900 mb-2">Verification Required</h2>
                    <div className="text-gray-600 mb-6">
                        <p>Your account must be verified before listing.</p>
                        {pendingVerificationMessages.length > 0 ? (
                            <div className="mt-2 whitespace-pre-line">
                                {pendingVerificationMessages.map((message) => (
                                    <p key={message}>{message}</p>
                                ))}
                            </div>
                        ) : null}
                    </div>
                    <button
                        onClick={() => navigate('/landlord/verification')}
                        className="w-full rounded-lg bg-blue-600 px-4 py-3 font-medium text-white hover:bg-blue-700 transition"
                    >
                        Go to Verification
                    </button>
                    <button
                        onClick={() => navigate('/dashboard/landlord/' + landlordUser?.id)}
                        className="mt-3 w-full rounded-lg bg-gray-100 px-4 py-3 font-medium text-gray-700 hover:bg-gray-200 transition"
                    >
                        Back to Dashboard
                    </button>
                </div>
            </div>
        )
    }

    return (
        <div className="min-h-screen bg-gray-50 py-8">
            <div className="max-w-4xl mx-auto px-4">
                <div className="bg-white rounded-lg shadow-lg p-8">
                    <h1 className="text-3xl font-bold text-gray-900 mb-8">
                        {isEditMode ? 'Edit Listing' : 'Create New Listing'}
                    </h1>

                    <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-2">
                                    Title *
                                </label>
                                <input
                                    {...register('title')}
                                    className="w-full rounded-lg border border-gray-300 px-4 py-3 focus:border-blue-500 focus:ring focus:ring-blue-500/20 outline-none"
                                    placeholder="e.g., Beautiful 3-bedroom apartment"
                                />
                                {errors.title && <p className="mt-1 text-sm text-red-600">{errors.title.message}</p>}
                            </div>

                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-2">
                                    Property Type *
                                </label>
                                <select
                                    {...register('property_type')}
                                    className="w-full rounded-lg border border-gray-300 px-4 py-3 focus:border-blue-500 focus:ring focus:ring-blue-500/20 outline-none"
                                >
                                    <option value="">Select property type</option>
                                    <option value="Flat">Flat</option>
                                    <option value="Duplex">Duplex</option>
                                    <option value="Apartment">Apartment</option>
                                    <option value="House">House</option>
                                    <option value="Studio">Studio</option>
                                    <option value="Townhouse">Townhouse</option>
                                    <option value="Condo">Condo</option>
                                </select>
                                {errors.property_type && <p className="mt-1 text-sm text-red-600">{errors.property_type.message}</p>}
                            </div>
                        </div>

                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-2">
                                Description *
                            </label>
                            <textarea
                                {...register('description')}
                                rows={4}
                                className="w-full rounded-lg border border-gray-300 px-4 py-3 focus:border-blue-500 focus:ring focus:ring-blue-500/20 outline-none"
                                placeholder="Describe your property in detail..."
                            />
                            {errors.description && <p className="mt-1 text-sm text-red-600">{errors.description.message}</p>}
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-2">
                                    Address *
                                </label>
                                <input
                                    {...register('address')}
                                    className="w-full rounded-lg border border-gray-300 px-4 py-3 focus:border-blue-500 focus:ring focus:ring-blue-500/20 outline-none"
                                    placeholder="Full street address"
                                />
                                {errors.address && <p className="mt-1 text-sm text-red-600">{errors.address.message}</p>}
                            </div>

                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-2">
                                    City *
                                </label>
                                <input
                                    {...register('city')}
                                    className="w-full rounded-lg border border-gray-300 px-4 py-3 focus:border-blue-500 focus:ring focus:ring-blue-500/20 outline-none"
                                    placeholder="City"
                                />
                                {errors.city && <p className="mt-1 text-sm text-red-600">{errors.city.message}</p>}
                            </div>

                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-2">
                                    State *
                                </label>
                                <input
                                    {...register('state')}
                                    className="w-full rounded-lg border border-gray-300 px-4 py-3 focus:border-blue-500 focus:ring focus:ring-blue-500/20 outline-none"
                                    placeholder="State"
                                />
                                {errors.state && <p className="mt-1 text-sm text-red-600">{errors.state.message}</p>}
                            </div>

                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-2">
                                    Postal Code *
                                </label>
                                <input
                                    {...register('postal_code')}
                                    className="w-full rounded-lg border border-gray-300 px-4 py-3 focus:border-blue-500 focus:ring focus:ring-blue-500/20 outline-none"
                                    placeholder="Postal code"
                                />
                                {errors.postal_code && <p className="mt-1 text-sm text-red-600">{errors.postal_code.message}</p>}
                            </div>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-5 gap-6">
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-2">
                                    Bedrooms *
                                </label>
                                <input
                                    {...register('bedrooms', { valueAsNumber: true })}
                                    type="number"
                                    min="1"
                                    className="w-full rounded-lg border border-gray-300 px-4 py-3 focus:border-blue-500 focus:ring focus:ring-blue-500/20 outline-none"
                                />
                                {errors.bedrooms && <p className="mt-1 text-sm text-red-600">{errors.bedrooms.message}</p>}
                            </div>

                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-2">
                                    Bathrooms *
                                </label>
                                <input
                                    {...register('bathrooms', { valueAsNumber: true })}
                                    type="number"
                                    min="1"
                                    className="w-full rounded-lg border border-gray-300 px-4 py-3 focus:border-blue-500 focus:ring focus:ring-blue-500/20 outline-none"
                                />
                                {errors.bathrooms && <p className="mt-1 text-sm text-red-600">{errors.bathrooms.message}</p>}
                            </div>

                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-2">
                                    Toilets *
                                </label>
                                <input
                                    {...register('toilets', { valueAsNumber: true })}
                                    type="number"
                                    min="1"
                                    className="w-full rounded-lg border border-gray-300 px-4 py-3 focus:border-blue-500 focus:ring focus:ring-blue-500/20 outline-none"
                                />
                                {errors.toilets && <p className="mt-1 text-sm text-red-600">{errors.toilets.message}</p>}
                            </div>

                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-2">
                                    Square Feet
                                </label>
                                <input
                                    {...register('square_feet', { valueAsNumber: true })}
                                    type="number"
                                    min="1"
                                    className="w-full rounded-lg border border-gray-300 px-4 py-3 focus:border-blue-500 focus:ring focus:ring-blue-500/20 outline-none"
                                />
                            </div>

                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-2">
                                    Available From
                                </label>
                                <input
                                    {...register('available_from')}
                                    type="date"
                                    className="w-full rounded-lg border border-gray-300 px-4 py-3 focus:border-blue-500 focus:ring focus:ring-blue-500/20 outline-none"
                                />
                            </div>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-2">
                                    Price per Year *
                                </label>
                                <input
                                    {...register('price_per_year', { valueAsNumber: true })}
                                    type="number"
                                    min="1"
                                    step="0.01"
                                    className="w-full rounded-lg border border-gray-300 px-4 py-3 focus:border-blue-500 focus:ring focus:ring-blue-500/20 outline-none"
                                />
                                {errors.price_per_year && <p className="mt-1 text-sm text-red-600">{errors.price_per_year.message}</p>}
                            </div>

                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-2">
                                    Deposit Amount
                                </label>
                                <input
                                    {...register('deposit_amount', { valueAsNumber: true })}
                                    type="number"
                                    min="0"
                                    step="0.01"
                                    className="w-full rounded-lg border border-gray-300 px-4 py-3 focus:border-blue-500 focus:ring focus:ring-blue-500/20 outline-none"
                                />
                            </div>
                        </div>

                        <div className="space-y-4">
                            <h3 className="text-lg font-semibold text-gray-900">Features</h3>

                            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                                <label className="flex items-center space-x-2">
                                    <input {...register('utilities_included')} type="checkbox" className="rounded border-gray-300 text-blue-600 focus:ring-blue-500" />
                                    <span className="text-sm text-gray-700">Utilities Included</span>
                                </label>

                                <label className="flex items-center space-x-2">
                                    <input {...register('pet_friendly')} type="checkbox" className="rounded border-gray-300 text-blue-600 focus:ring-blue-500" />
                                    <span className="text-sm text-gray-700">Pet Friendly</span>
                                </label>

                                <label className="flex items-center space-x-2">
                                    <input {...register('furnished')} type="checkbox" className="rounded border-gray-300 text-blue-600 focus:ring-blue-500" />
                                    <span className="text-sm text-gray-700">Furnished</span>
                                </label>
                            </div>

                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-2">
                                    Amenities
                                </label>
                                <div className="space-y-2">
                                    {amenityFields.map((field, index) => (
                                        <div key={field.id} className="flex gap-2">
                                            <input
                                                type="text"
                                                {...register(`amenities.${index}.value` as const)}
                                                className="w-full rounded-lg border border-gray-300 px-4 py-3 focus:border-blue-500 focus:ring focus:ring-blue-500/20 outline-none"
                                                placeholder={index === 0 ? 'e.g., Swimming pool, Gym, Parking' : 'Amenity'}
                                            />
                                            {amenityFields.length > 1 && (
                                                <button
                                                    type="button"
                                                    onClick={() => removeAmenity(index)}
                                                    className="px-3 rounded-lg border border-gray-300 text-gray-700 hover:bg-gray-50 transition"
                                                >
                                                    Remove
                                                </button>
                                            )}
                                        </div>
                                    ))}
                                </div>
                                <button
                                    type="button"
                                    onClick={() => appendAmenity({ value: '' })}
                                    className="mt-2 text-sm text-blue-600 hover:text-blue-800"
                                >
                                    + Add another amenity
                                </button>
                            </div>

                            {!isEditMode && (
                                <div className="border-t pt-6">
                                    <h3 className="text-lg font-semibold text-gray-900 mb-4">Featured Property</h3>
                                    <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                                        <div className="flex items-start space-x-3">
                                            <div className="flex-shrink-0">
                                                <svg className="h-6 w-6 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                                                </svg>
                                            </div>
                                            <div className="flex-1">
                                                <h4 className="text-sm font-medium text-blue-900">Make Your Property Stand Out</h4>
                                                <p className="mt-1 text-sm text-blue-700">
                                                    Featured properties appear at the top of search results and on the home page,
                                                    giving you maximum visibility to potential tenants.
                                                </p>
                                                <div className="mt-3">
                                                    <div className="flex items-center justify-between text-sm">
                                                        <span className="text-blue-700">Featured Duration:</span>
                                                        <span className="font-medium text-blue-900">30 days</span>
                                                    </div>
                                                    <div className="flex items-center justify-between text-sm">
                                                        <span className="text-blue-700">Fee:</span>
                                                        <span className="font-medium text-blue-900">₦5,000</span>
                                                    </div>
                                                </div>
                                                <div className="mt-3">
                                                    <label className="flex items-center space-x-2">
                                                        <input
                                                            type="checkbox"
                                                            id="featured_property"
                                                            {...register('featured_property')}
                                                            className="rounded border-blue-300 text-blue-600 focus:ring-blue-500"
                                                        />
                                                        <span className="text-sm text-blue-700">
                                                            I want to feature this property (₦5,000 for 30 days)
                                                        </span>
                                                    </label>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            )}
                        </div>

                        <div className="space-y-4">
                            <h3 className="text-lg font-semibold text-gray-900">Images</h3>

                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-2">
                                    Cover Image {isEditMode ? '(optional to replace current images)' : '*'}
                                </label>
                                <input
                                    type="file"
                                    accept="image/*"
                                    onChange={handleCoverImageChange}
                                    className="w-full rounded-lg border border-gray-300 px-4 py-3 focus:border-blue-500 focus:ring focus:ring-blue-500/20 outline-none"
                                    required={!isEditMode}
                                />
                            </div>

                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-2">
                                    Additional Images (up to 9)
                                </label>
                                <input
                                    type="file"
                                    accept="image/*"
                                    multiple
                                    onChange={handleAdditionalImagesChange}
                                    className="w-full rounded-lg border border-gray-300 px-4 py-3 focus:border-blue-500 focus:ring focus:ring-blue-500/20 outline-none"
                                />
                                <p className="mt-1 text-sm text-gray-500">
                                    {isEditMode
                                        ? 'Uploading new images will replace the current image set for this listing.'
                                        : 'You can select multiple images. Maximum 9 additional images allowed.'}
                                </p>
                            </div>
                        </div>

                        <div className="flex justify-end space-x-4">
                            <button
                                type="button"
                                onClick={() => navigate(user ? `/dashboard/landlord/${user.id}` : '/')}
                                className="px-6 py-3 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition"
                            >
                                Cancel
                            </button>
                            <button
                                type="submit"
                                disabled={isSubmitting}
                                className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition"
                            >
                                {isSubmitting ? (isEditMode ? 'Saving...' : 'Creating...') : (isEditMode ? 'Save Changes' : 'Create Listing')}
                            </button>
                        </div>
                    </form>
                </div>
            </div>
        </div>
    )
}
