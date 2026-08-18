import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useForm, useFieldArray } from 'react-hook-form'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import { api, getApiUrl } from '@/lib/api'
import { buildFormDraftKey, readFormDraft, removeFormDraft, writeFormDraft } from '@/lib/formDrafts'
import LegalConsentCheckbox from '@/components/LegalConsentCheckbox'
import DashboardBackButton from '@/components/DashboardBackButton'
import { useQuery } from '@tanstack/react-query'
import { Listing, User } from '@/types'
import { useAuth } from '@/hooks/useAuth'

const optionalPositiveNumber = z.number().min(1, 'Value must be positive').optional()

const requiredPositiveNumber = (message: string) =>
    z.number({ error: message }).min(1, message)

const schema = z.object({
    title: z.string().min(1, 'Title is required'),
    description: z.string().min(1, 'Description is required'),
    address: z.string().min(1, 'Address is required'),
    city: z.string().min(1, 'City is required'),
    state: z.string().min(1, 'State is required'),
    postal_code: z.string().min(1, 'Postal code is required'),
    property_type: z.string().min(1, 'Property type is required'),
    bedrooms: requiredPositiveNumber('At least 1 bedroom required'),
    bathrooms: requiredPositiveNumber('At least 1 bathroom required'),
    toilets: requiredPositiveNumber('At least 1 toilet required'),
    square_feet: optionalPositiveNumber,
    price_per_year: requiredPositiveNumber('Price is required'),
    deposit_amount: requiredPositiveNumber('Deposit amount is required'),
    utilities_included: z.boolean(),
    pet_friendly: z.boolean(),
    parking: z.boolean(),
    garage: z.boolean(),
    garden: z.boolean(),
    lift: z.boolean(),
    balcony: z.boolean(),
    smart_lock: z.boolean(),
    pop_ceiling: z.boolean(),
    electric_fence: z.boolean(),
    fitted_kitchen: z.boolean(),
    furnished: z.boolean(),
    ownership_types: z.array(z.string()).min(1, 'Select at least one ownership type'),
    property_ownership_documents: z.array(z.string()),
    property_verification_method: z.enum(['documents', 'in_person']),
    minimum_rental_duration: z.string().min(1, 'Minimum rental duration is required'),
    maximum_occupancy: z.string().min(1, 'Maximum occupancy is required'),
    smoking_allowed: z.boolean(),
    commercial_activities_allowed: z.boolean(),
    short_let_allowed: z.boolean(),
    student_tenants_allowed: z.boolean(),
    expatriates_allowed: z.boolean(),
    featured_property: z.boolean(),
    featured_duration: z.number().optional(),
    available_from: z.string().min(1, 'Available date is required'),
    amenities: z.array(z.object({ value: z.string() })),
}).superRefine((data, ctx) => {
    const hasAmenity = data.amenities.some((item) => item.value.trim().length > 0)
    if (!hasAmenity) {
        ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ['amenities'],
            message: 'Add at least one amenity',
        })
    }
    if (data.property_verification_method === 'documents' && data.property_ownership_documents.length === 0) {
        ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ['property_ownership_documents'],
            message: 'Select at least one ownership document type',
        })
    }
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

const ownershipTypeOptions = [
    'Sole Owner',
    'Rental',
    'Joint Owner',
    'Family Property Representative',
    'Attorney/Power of Attorney Holder',
    'Property Manager',
    'Trustee',
    'Mortgage Holder in Possession',
    'Developer-Owned Property',
    'Employer Provider'
] as const

const individualOwnershipDocumentOptions = [
    'Certificate of Occupancy (C of O)',
    'Deed of Assignment',
    "Governor's Consent",
    'Registered Survey',
    'Probate Documentation',
    'Court Vesting Order',
    'Power of Attorney',
    'Land Use Charge Receipt',
    'Property Tax Receipt',
    'Lease Agreement',
    'Trust Deed',
    'Property Management Agreement',
] as const

const corporateOwnershipDocumentOptions = [
    'Deed of Assignment',
    'C of O',
    "Governor's Consent",
    'Property Acquisition Documents',
] as const

const rentalPreferenceOptions = [
    { field: 'smoking_allowed', label: 'Smoking Allowed?' },
    { field: 'commercial_activities_allowed', label: 'Commercial Activities Allowed?' },
    { field: 'short_let_allowed', label: 'Short-let Allowed?' },
    { field: 'student_tenants_allowed', label: 'Student Tenants Allowed?' },
    { field: 'expatriates_allowed', label: 'Expatriates Allowed?' },
] as const

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
    const [propertyDocumentFiles, setPropertyDocumentFiles] = useState<File[]>([])
    const [isSubmitting, setIsSubmitting] = useState(false)
    const [hasAcceptedLegalConsent, setHasAcceptedLegalConsent] = useState(false)
    const [legalConsentError, setLegalConsentError] = useState('')
    const listingDraftStorageKey = useMemo(
        () => buildFormDraftKey(`listing-${isEditMode ? `edit:${id}` : 'new'}`, user?.id || user?.email),
        [id, isEditMode, user?.email, user?.id],
    )
    const [hydratedDraftStorageKey, setHydratedDraftStorageKey] = useState<string | null>(null)
    const [draftPersistenceEnabled, setDraftPersistenceEnabled] = useState(true)

    const {
        register,
        handleSubmit,
        formState: { errors },
        control,
        reset,
        watch,
        setValue,
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
            parking: false,
            garage: false,
            garden: false,
            lift: false,
            balcony: false,
            smart_lock: false,
            pop_ceiling: false,
            electric_fence: false,
            fitted_kitchen: false,
            furnished: false,
            ownership_types: [],
            property_ownership_documents: [],
            property_verification_method: 'documents',
            minimum_rental_duration: '',
            maximum_occupancy: '',
            smoking_allowed: false,
            commercial_activities_allowed: false,
            short_let_allowed: false,
            student_tenants_allowed: false,
            expatriates_allowed: false,
            amenities: [{ value: '' }],
            featured_property: false,
            available_from: '',
        },
    })
    const propertyVerificationMethod = watch('property_verification_method')
    const pricePerYear = watch('price_per_year')
    const watchedFormValues = watch()

    useEffect(() => {
        if (propertyVerificationMethod === 'in_person') {
            setPropertyDocumentFiles([])
        }
        setHasAcceptedLegalConsent(false)
        setLegalConsentError('')
    }, [propertyVerificationMethod])

    useEffect(() => {
        const annualRent = Number(pricePerYear)
        const depositAmount = Number.isFinite(annualRent) && annualRent > 0
            ? Number((annualRent * 0.2).toFixed(2))
            : undefined
        setValue('deposit_amount', depositAmount as ListingFormValues['deposit_amount'], {
            shouldDirty: false,
            shouldTouch: false,
            shouldValidate: Boolean(depositAmount),
        })
    }, [pricePerYear, setValue])

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
        const requirementKeys: Array<keyof VerificationStatusResponse> = ['identification']
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
    const ownershipDocumentOptions = landlordUser?.landlord_verification_type === 'corporate'
        ? corporateOwnershipDocumentOptions
        : individualOwnershipDocumentOptions
    const shouldBlockListingCreation =
        !isEditMode &&
        landlordUser?.role === 'landlord' &&
        pendingVerificationMessages.length > 0

    useEffect(() => {
        if (!listing) {
            return
        }

        const listingDefaults = {
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
            parking: listing.parking,
            garage: listing.garage,
            garden: listing.garden,
            lift: listing.lift,
            balcony: listing.balcony,
            smart_lock: listing.smart_lock,
            pop_ceiling: listing.pop_ceiling,
            electric_fence: listing.electric_fence,
            fitted_kitchen: listing.fitted_kitchen,
            furnished: listing.furnished,
            ownership_types: listing.ownership_types || [],
            property_ownership_documents: listing.property_ownership_documents || [],
            property_verification_method: listing.property_document_submission?.in_person_verification_requested ? 'in_person' as const : 'documents' as const,
            minimum_rental_duration: listing.minimum_rental_duration || '',
            maximum_occupancy: listing.maximum_occupancy ? String(listing.maximum_occupancy) : '',
            smoking_allowed: Boolean(listing.smoking_allowed),
            commercial_activities_allowed: Boolean(listing.commercial_activities_allowed),
            short_let_allowed: Boolean(listing.short_let_allowed),
            student_tenants_allowed: Boolean(listing.student_tenants_allowed),
            expatriates_allowed: Boolean(listing.expatriates_allowed),
            featured_property: listing.featured,
            featured_duration: undefined,
            available_from: listing.available_from || '',
            amenities: listing.amenities && listing.amenities.length > 0
                ? listing.amenities.map((value) => ({ value }))
                : [{ value: '' }],
        }
        const storedDraft = readFormDraft<Partial<ListingFormValues>>(listingDraftStorageKey)
        reset({ ...listingDefaults, ...(storedDraft || {}) })
        setHydratedDraftStorageKey(listingDraftStorageKey)
    }, [isEditMode, listing, listingDraftStorageKey, reset])

    useEffect(() => {
        if (isEditMode || !listingDraftStorageKey) return

        const storedDraft = readFormDraft<Partial<ListingFormValues>>(listingDraftStorageKey)
        if (storedDraft) {
            reset(storedDraft)
        }
        setHydratedDraftStorageKey(listingDraftStorageKey)
    }, [isEditMode, listingDraftStorageKey, reset])

    useEffect(() => {
        if (
            !draftPersistenceEnabled
            || !listingDraftStorageKey
            || hydratedDraftStorageKey !== listingDraftStorageKey
        ) {
            return
        }

        writeFormDraft(listingDraftStorageKey, watchedFormValues)
    }, [draftPersistenceEnabled, hydratedDraftStorageKey, listingDraftStorageKey, watchedFormValues])

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
        if (Number.isFinite(data.deposit_amount)) {
            formData.append('deposit_amount', data.deposit_amount.toString())
        }

        formData.append('utilities_included', data.utilities_included.toString())
        formData.append('pet_friendly', data.pet_friendly.toString())


        formData.append('parking', data.parking.toString())
        formData.append('garage', data.garage.toString())
        formData.append('garden', data.garden.toString())
        formData.append('lift', data.lift.toString())
        formData.append('balcony', data.balcony.toString())
        formData.append('smart_lock', data.smart_lock.toString())
        formData.append('pop_ceiling', data.pop_ceiling.toString())
        formData.append('electric_fence', data.electric_fence.toString())
        formData.append('fitted_kitchen', data.fitted_kitchen.toString())




        formData.append('furnished', data.furnished.toString())
        formData.append('property_verification_method', data.property_verification_method)
        formData.append('minimum_rental_duration', data.minimum_rental_duration)
        formData.append('maximum_occupancy', data.maximum_occupancy)
        formData.append('smoking_allowed', data.smoking_allowed.toString())
        formData.append('commercial_activities_allowed', data.commercial_activities_allowed.toString())
        formData.append('short_let_allowed', data.short_let_allowed.toString())
        formData.append('student_tenants_allowed', data.student_tenants_allowed.toString())
        formData.append('expatriates_allowed', data.expatriates_allowed.toString())

        data.ownership_types.forEach((option) => {
            formData.append('ownership_types', option)
        })
        data.property_ownership_documents.forEach((option) => {
            formData.append('property_ownership_documents', option)
        })

        formData.append('available_from', data.available_from)

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
        propertyDocumentFiles.forEach((file) => {
            formData.append('property_documents', file)
        })

        return formData
    }

    const onSubmit = async (data: ListingFormValues) => {
        if (!hasAcceptedLegalConsent) {
            setLegalConsentError('Review the property verification terms and tick the consent box before submitting this verification request.')
            return
        }
        if (!isEditMode && !coverImage) {
            alert('Please select a cover image')
            return
        }
        if (!isEditMode && additionalImages.length === 0) {
            alert('Please select at least one additional image')
            return
        }
        if (!isEditMode && data.property_verification_method === 'documents' && propertyDocumentFiles.length === 0) {
            alert('Please upload at least one property document or choose in-person verification.')
            return
        }
        if (!isEditMode && data.property_verification_method === 'documents' && data.property_ownership_documents.length === 0) {
            alert('Please select at least one ownership document type.')
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
                    setDraftPersistenceEnabled(false)
                    setHydratedDraftStorageKey(null)
                    removeFormDraft(listingDraftStorageKey)
                    navigate(`/dashboard/featured-properties/pay/${featuredPayment.id}`)
                    return
                }

                const featuredErr = await featuredRes.json().catch(() => ({}))
                alert((featuredErr as { detail?: string }).detail || 'Listing created, but failed to start featured payment.')
            }

            setDraftPersistenceEnabled(false)
            setHydratedDraftStorageKey(null)
            removeFormDraft(listingDraftStorageKey)
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

    const handlePropertyDocumentsChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        setPropertyDocumentFiles(Array.from(e.target.files || []))
    }

    const classNameTitles = "block text-sm font-bold text-gray-700 mb-2"

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
                    <DashboardBackButton to={`/dashboard/landlord/${landlordUser?.id}`} label="Back to Dashboard" className="mt-3 w-full justify-center" />
                </div>
            </div>
        )
    }

    return (
        <div className="min-h-screen bg-gray-90 py-10">
            <div className="max-w-6xl mx-auto px-4">
                <div className="bg-white rounded-lg shadow-lg p-8">
                    <h1 className="text-3xl font-bold text-gray-900 mb-8">
                        {isEditMode ? 'Edit Listing' : 'Create New Listing'}
                    </h1>
                    <h3 className="text-[22px] font-semibold text-gray-900">Property Information</h3><br />

                    <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                            <div>
                                <label className={classNameTitles}>
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
                                <label className={classNameTitles}>
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
                            <label className={classNameTitles}>
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
                                <label className={classNameTitles}>
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
                                <label className={classNameTitles}>
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
                                <label className={classNameTitles}>
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
                                <label className={classNameTitles}>
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
                                <label className={classNameTitles}>
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
                                <label className={classNameTitles}>
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
                                <label className={classNameTitles}>
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
                                <label className={classNameTitles}>
                                    Square Feet
                                </label>
                                <input
                                    {...register('square_feet', {
                                        setValueAs: (value) => value === '' ? undefined : Number(value),
                                    })}
                                    type="number"
                                    min="1"
                                    className="w-full rounded-lg border border-gray-300 px-4 py-3 focus:border-blue-500 focus:ring focus:ring-blue-500/20 outline-none"
                                />
                            </div>

                            <div>
                                <label className={classNameTitles}>
                                    Available From *
                                </label>
                                <input
                                    {...register('available_from')}
                                    type="date"
                                    className="w-full rounded-lg border border-gray-300 px-4 py-3 focus:border-blue-500 focus:ring focus:ring-blue-500/20 outline-none"
                                />
                                {errors.available_from && <p className="mt-1 text-sm text-red-600">{errors.available_from.message}</p>}
                            </div>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                            <div>
                                <label className={classNameTitles}>
                                    Price per year *
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
                                <label className={classNameTitles}>
                                    Deposit Amount (20% of Annual Rent) *
                                </label>
                                <input
                                    {...register('deposit_amount', { valueAsNumber: true })}
                                    type="number"
                                    min="0"
                                    step="0.01"
                                    readOnly
                                    className="w-full rounded-lg border border-gray-300 bg-gray-100 px-4 py-3 text-gray-700 focus:border-blue-500 focus:ring focus:ring-blue-500/20 outline-none"
                                />
                                {errors.deposit_amount && <p className="mt-1 text-sm text-red-600">{errors.deposit_amount.message}</p>}
                            </div>
                        </div><br />
                        <div className="space-y-5 border-t pt-6">
                            <h3 className="text-[22px] font-semibold text-gray-900">Property Ownership Verification</h3>

                            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                                <div>
                                    <label className={classNameTitles}>
                                        Verification Method *
                                    </label>
                                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                                        <label className="flex items-center gap-3 rounded-lg border px-4 py-3">
                                            <input {...register('property_verification_method')} type="radio" value="documents" className="h-4 w-4 border-gray-300 text-blue-600 focus:ring-blue-500" />
                                            <span className="text-sm text-gray-800">Upload documents</span>
                                        </label>
                                        <label className="flex items-center gap-3 rounded-lg border px-4 py-3">
                                            <input {...register('property_verification_method')} type="radio" value="in_person" className="h-4 w-4 border-gray-300 text-blue-600 focus:ring-blue-500" />
                                            <span className="text-sm text-gray-800">In-person verification</span>
                                        </label>
                                    </div>
                                    {errors.property_verification_method && <p className="mt-1 text-sm text-red-600">{errors.property_verification_method.message}</p>}
                                </div>
                            </div>

                            <div>
                                <label className={classNameTitles}>
                                    Ownership Type *
                                </label>
                                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                                    {ownershipTypeOptions.map((option) => (
                                        <label key={option} className="flex items-center gap-3 rounded-lg border px-4 py-3">
                                            <input
                                                {...register('ownership_types')}
                                                type="checkbox"
                                                value={option}
                                                className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                                            />
                                            <span className="text-sm text-gray-800">{option}</span>
                                        </label>
                                    ))}
                                </div>
                                {errors.ownership_types && <p className="mt-1 text-sm text-red-600">{errors.ownership_types.message}</p>}
                            </div>

                            <div>
                                <label className={classNameTitles}>
                                    Ownership Documents {propertyVerificationMethod === 'documents' ? '*' : '(not required for in-person verification)'}
                                </label>
                                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                                    {ownershipDocumentOptions.map((option) => (
                                        <label key={option} className="flex items-center gap-3 rounded-lg border px-4 py-3">
                                            <input
                                                {...register('property_ownership_documents')}
                                                type="checkbox"
                                                value={option}
                                                className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                                            />
                                            <span className="text-sm text-gray-800">{option}</span>
                                        </label>
                                    ))}
                                </div>
                                {errors.property_ownership_documents && (
                                    <p className="mt-1 text-sm text-red-600">{errors.property_ownership_documents.message}</p>
                                )}
                            </div>

                            <div>
                                <label className={`block text-sm font-medium mb-2 ${propertyVerificationMethod === 'in_person' ? 'text-gray-400' : 'text-gray-700'}`}>
                                    <p className={classNameTitles}>
                                        Property Documents {isEditMode || propertyVerificationMethod === 'in_person' ? '(optional)' : '*'}
                                    </p>
                                </label>
                                <input
                                    type="file"
                                    multiple
                                    accept=".pdf,.jpg,.jpeg,.png"
                                    onChange={handlePropertyDocumentsChange}
                                    disabled={propertyVerificationMethod === 'in_person'}
                                    required={!isEditMode && propertyVerificationMethod === 'documents'}
                                    className="w-full rounded-lg border border-gray-300 px-4 py-3 focus:border-blue-500 focus:ring focus:ring-blue-500/20 outline-none disabled:cursor-not-allowed disabled:bg-gray-100 disabled:text-gray-400"
                                />
                                {propertyDocumentFiles.length > 0 && (
                                    <ul className="mt-3 space-y-2 text-sm text-gray-600">
                                        {propertyDocumentFiles.map((file) => (
                                            <li key={`${file.name}-${file.size}`} className="flex items-center justify-between rounded-lg bg-gray-50 px-3 py-2">
                                                <span>{file.name}</span>
                                                <span>{(file.size / 1024 / 1024).toFixed(2)} MB</span>
                                            </li>
                                        ))}
                                    </ul>
                                )}
                            </div>
                        </div><br />

                        <div className="space-y-5 border-t pt-6">
                            <h3 className="text-[22px] font-semibold text-gray-900">Rental Preferences</h3>

                            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                                <div>
                                    <label className={classNameTitles}>
                                        Maximum Occupancy *
                                    </label>
                                    <input
                                        {...register('maximum_occupancy')}
                                        type="number"
                                        min="1"
                                        className="w-full rounded-lg border border-gray-300 px-4 py-3 focus:border-blue-500 focus:ring focus:ring-blue-500/20 outline-none"
                                    />
                                    {errors.maximum_occupancy && <p className="mt-1 text-sm text-red-600">{errors.maximum_occupancy.message}</p>}
                                </div>
                                <div>
                                    <label className={classNameTitles}>
                                        Minimum Rental Duration *
                                    </label>
                                    <input
                                        {...register('minimum_rental_duration')}
                                        className="w-full rounded-lg border border-gray-300 px-4 py-3 focus:border-blue-500 focus:ring focus:ring-blue-500/20 outline-none"
                                        placeholder="e.g., 6 months"
                                    />
                                    {errors.minimum_rental_duration && <p className="mt-1 text-sm text-red-600">{errors.minimum_rental_duration.message}</p>}
                                </div>
                            </div>

                            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                                {rentalPreferenceOptions.map((option) => (
                                    <label key={option.field} className="flex items-center gap-3 rounded-lg border px-4 py-3">
                                        <input
                                            {...register(option.field)}
                                            type="checkbox"
                                            className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                                        />
                                        <span className="text-sm text-gray-800">{option.label}</span>
                                    </label>
                                ))}
                            </div>
                        </div>

                        <div className="space-y-4">
                            {/* <h3 className="text-lg font-semibold text-gray-900">Features</h3> */}
                            <label className={classNameTitles}>Features</label>

                            <div className="grid grid-cols-1 md:grid-cols-6 gap-4">
                                <label className="flex items-center space-x-2">
                                    <input {...register('utilities_included')} type="checkbox" className="rounded border-gray-300 text-blue-600 focus:ring-blue-500" />
                                    <span className="text-sm text-gray-700">Utilities Included</span>
                                </label>

                                <label className="flex items-center space-x-2">
                                    <input {...register('pet_friendly')} type="checkbox" className="rounded border-gray-300 text-blue-600 focus:ring-blue-500" />
                                    <span className="text-sm text-gray-700">Pet Friendly?</span>
                                </label>

                                <label className="flex items-center space-x-2">
                                    <input {...register('furnished')} type="checkbox" className="rounded border-gray-300 text-blue-600 focus:ring-blue-500" />
                                    <span className="text-sm text-gray-700">Furnished</span>
                                </label>

                                <label className="flex items-center space-x-2">
                                    <input {...register('parking')} type="checkbox" className="rounded border-gray-300 text-blue-600 focus:ring-blue-500" />
                                    <span className="text-sm text-gray-700">Parking</span>
                                </label>

                                <label className="flex items-center space-x-2">
                                    <input {...register('garage')} type="checkbox" className="rounded border-gray-300 text-blue-600 focus:ring-blue-500" />
                                    <span className="text-sm text-gray-700">Garage</span>
                                </label>

                                <label className="flex items-center space-x-2">
                                    <input {...register('garden')} type="checkbox" className="rounded border-gray-300 text-blue-600 focus:ring-blue-500" />
                                    <span className="text-sm text-gray-700">Gardens</span>
                                </label>

                                <label className="flex items-center space-x-2">
                                    <input {...register('lift')} type="checkbox" className="rounded border-gray-300 text-blue-600 focus:ring-blue-500" />
                                    <span className="text-sm text-gray-700">Lift</span>
                                </label>

                                <label className="flex items-center space-x-2">
                                    <input {...register('balcony')} type="checkbox" className="rounded border-gray-300 text-blue-600 focus:ring-blue-500" />
                                    <span className="text-sm text-gray-700">Balcony</span>
                                </label>

                                <label className="flex items-center space-x-2">
                                    <input {...register('smart_lock')} type="checkbox" className="rounded border-gray-300 text-blue-600 focus:ring-blue-500" />
                                    <span className="text-sm text-gray-700">Smart Locks</span>
                                </label>

                                <label className="flex items-center space-x-2">
                                    <input {...register('pop_ceiling')} type="checkbox" className="rounded border-gray-300 text-blue-600 focus:ring-blue-500" />
                                    <span className="text-sm text-gray-700">POP Ceiling</span>
                                </label>

                                <label className="flex items-center space-x-2">
                                    <input {...register('electric_fence')} type="checkbox" className="rounded border-gray-300 text-blue-600 focus:ring-blue-500" />
                                    <span className="text-sm text-gray-700">Electric fence</span>
                                </label>

                                <label className="flex items-center space-x-2">
                                    <input {...register('fitted_kitchen')} type="checkbox" className="rounded border-gray-300 text-blue-600 focus:ring-blue-500" />
                                    <span className="text-sm text-gray-700">Fitted kitchen</span>
                                </label>
                            </div>

                            <div>
                                <label className={classNameTitles}>
                                    Amenities *
                                </label>
                                <div className="space-y-2">
                                    {amenityFields.map((field, index) => (
                                        <div key={field.id} className="flex gap-2">
                                            <input
                                                type="text"
                                                {...register(`amenities.${index}.value` as const)}
                                                className="w-full rounded-lg border border-gray-300 px-4 py-1.5 focus:border-blue-500 focus:ring focus:ring-blue-500/20 outline-none"
                                                placeholder={index === 0 ? 'e.g., Swimming pool, Gym, Children\'s playgorund, Nearby shopping mall etc.' : 'Amenity'}
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
                                {errors.amenities?.message && <p className="mt-1 text-sm text-red-600">{errors.amenities.message}</p>}
                            </div>

                            {!isEditMode && (
                                <div className="border-t pt-6">
                                    <h3 className="text-[22px] font-semibold text-gray-900 mb-4">Featured Property</h3>
                                    <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                                        <div className="flex items-start space-x-3">
                                            <div className="flex-shrink-0">
                                                <svg className="h-6 w-6 text-blue-600" fill="none" viewBox="0 0 20 20" stroke="currentColor">
                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                                                </svg>
                                            </div>
                                            <div className="flex-1">
                                                <h4 className="text-[20px] font-bold text-blue-900">Make Your Property Stand Out</h4>
                                                <p className="mt-1 text-sm text-blue-700">
                                                    Featured properties appear at the top of search results and on the home page,<br />
                                                    This giving your property maximum visibility to potential tenants.
                                                </p>
                                                <div className="mt-3">
                                                    <div className="flex items-center justify-between text-sm">
                                                        <span className="text-blue-700">Featured Duration:</span>
                                                        <span className="text-[16px] font-bold text-blue-900">30 days</span>
                                                    </div>
                                                    <div className="flex items-center justify-between text-sm">
                                                        <span className="text-blue-700">Fee:</span>
                                                        <span className="text-[16px] font-bold text-blue-900">₦5,000</span>
                                                    </div>
                                                </div>
                                                <div className="mt-3">
                                                    <label className="flex items-center space-x-3">
                                                        <input
                                                            type="checkbox"
                                                            id="featured_property"
                                                            {...register('featured_property')}
                                                            className="rounded border-blue-500 text-blue-600 focus:ring-blue-600"
                                                        />
                                                        <span className="text-[16px] font-semibold text-blue-700">
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
                                <label className={classNameTitles}>
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
                                <label className={classNameTitles}>
                                    Additional Images {isEditMode ? '(optional to replace current images)' : '(up to 9) *'}
                                </label>
                                <input
                                    type="file"
                                    accept="image/*"
                                    multiple
                                    onChange={handleAdditionalImagesChange}
                                    required={!isEditMode}
                                    className="w-full rounded-lg border border-gray-300 px-4 py-3 focus:border-blue-500 focus:ring focus:ring-blue-500/20 outline-none"
                                />
                                <p className="mt-1 text-sm text-gray-500">
                                    {isEditMode
                                        ? 'Uploading new images will replace the current image set for this listing.'
                                        : 'You can select multiple images. Maximum 9 additional images allowed.'}
                                </p>
                            </div>
                        </div>

                        <LegalConsentCheckbox
                            id="property-verification-legal-consent"
                            documents={[
                                { slug: 'property-ownership-and-listing-terms', title: 'Property Ownership and Listing Terms' },
                                { slug: 'property-verification-and-inspection-terms', title: 'Property Verification and Inspection Terms' },
                                { slug: 'tenant-data-use-terms', title: 'Tenant Data Use Terms' },
                            ]}
                            checked={hasAcceptedLegalConsent}
                            error={legalConsentError}
                            consentContext="listing this property"
                            onChange={(checked) => {
                                setHasAcceptedLegalConsent(checked)
                                if (checked) setLegalConsentError('')
                            }}
                        />

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
