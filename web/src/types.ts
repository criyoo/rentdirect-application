export type UserResidence = {
    state?: string
    city?: string
    address?: string
    origin_country?: string
    origin_city?: string
}

export type LandlordVerificationType = 'individual' | 'corporate'

export type User = {
    id: string
    name: string
    email: string
    role: 'tenant' | 'landlord' | 'admin'
    token?: string
    email_verified?: boolean
    profile_photo_url?: string | null
    mobile?: string
    nin_number?: string
    bvn_number?: string
    state_of_origin?: string
    residence?: UserResidence | null
    landlord_verification_type?: LandlordVerificationType | ''
    landlord_verification_profile?: Record<string, any> | null
    tenant_verification_profile?: Record<string, any> | null
    is_verified?: boolean
    account_frozen?: boolean
    account_frozen_at?: string | null
    account_frozen_until?: string | null
    account_freeze_fee_percentage?: string | number
}

export type Review = {
    id: string
    review_type?: 'property' | 'landlord'
    listing_id: string
    listing_title?: string
    tenant_id: string
    tenant_name?: string
    landlord_id?: string
    rating: number
    comment: string
    created_at: string
    updated_at?: string
}

export type FeedbackEntry = {
    id: string
    user_id: string
    name: string
    role: 'tenant' | 'landlord' | 'admin'
    topic: string
    message: string
    created_at: string
    updated_at: string
}

export type LandlordVerificationBadges = {
    identity_verified: boolean
    house_ownership_verified: boolean
    phone_verified: boolean
    email_verified: boolean
}

export type LandlordPublicMetrics = {
    total_properties: number
    properties_rented: number
    properties_listed: number
    active_tenancies: number
    completed_tenancies: number
    average_rating: number
    tenant_satisfaction_score: number
    average_response_time: string
    application_approval_rate: number
    years_on_platform: number
    successful_rentals: number
    reviews_count: number
}

export type LandlordPublicListing = {
    id: string
    title: string
    status: string
}

export type LandlordPublicProfile = {
    id: string
    display_name: string
    subtitle: string
    full_name: string
    role: 'landlord'
    landlord_verification_type?: LandlordVerificationType | ''
    profile_photo_url?: string | null
    verification_badges: LandlordVerificationBadges
    verification_score?: number | null
    metrics: LandlordPublicMetrics
    listings: LandlordPublicListing[]
    reviews: Array<{
        id: string
        rating: number
        comment: string
        created_at: string
        tenant_name: string
        listing_id: string
        listing_title: string
    }>
}

export type TenantProfileDetails = {
    id: string
    status: string
    submitted_at?: string
    updated_at?: string
    first_name: string
    middle_name?: string
    last_name: string
    date_of_birth: string
    gender: string
    nationality: string
    state_of_origin: string
    lga: string
    employment_status: string
    residence_country: string
    residence_state: string
    residence_city: string
    residence_lga: string
    residence_address: string
    length_of_stay: string
    housing_status: string
    employment_info?: Record<string, any> | null
    financial_info?: Record<string, any> | null
    guarantor_details?: Record<string, any> | null
    landlord_info?: Record<string, any> | null
    rental_history?: Array<Record<string, any>> | null
    household_info?: Record<string, any> | null
    social_presence?: Record<string, any> | null
    criminal_declaration?: Record<string, any> | null
}

export type TenantProfileSummary = {
    id: string
    name: string
    email?: string
    mobile?: string
    profile_photo_url?: string | null
    state_of_origin?: string
    residence?: UserResidence | null
    is_verified?: boolean
    tenant_profile?: TenantProfileDetails | null
}

export interface Listing {
    id: string
    title: string
    description: string
    address: string
    city: string
    state?: string
    postal_code: string
    latitude?: number
    longitude?: number
    distance_km?: number | null
    location_source?: string | null
    property_type: string
    bedrooms: number
    bathrooms: number
    toilets?: number
    square_feet?: number
    price_per_year: number
    deposit_amount?: number
    utilities_included: boolean
    pet_friendly: boolean
    parking?: boolean
    garage?: boolean
    garden?: boolean
    lift?: boolean
    balcony?: boolean
    smart_lock?: boolean
    pop_ceiling?: boolean
    electric_fence?: boolean
    fitted_kitchen?: boolean
    furnished: boolean
    amenities?: string[]
    ownership_status?: string
    ownership_types?: string[]
    property_ownership_documents?: string[]
    property_documents?: Array<{
        id: string
        title: string
        content_type?: string
        file_url?: string
        created_at?: string
    }>
    property_document_submission?: {
        document_types?: string[]
        ownership_types?: string[]
        in_person_verification_requested?: boolean
        uploaded_document_count?: number
        submitted_at?: string
    } | null
    property_document_verification_status?: string
    physical_property_status?: string
    minimum_rental_duration?: string
    maximum_occupancy?: number | null
    smoking_allowed?: boolean
    commercial_activities_allowed?: boolean
    short_let_allowed?: boolean
    student_tenants_allowed?: boolean
    expatriates_allowed?: boolean
    available_from?: string
    status: string
    cover_image_url?: string
    image_urls?: string[]
    landlord_id: string
    landlord_name?: string
    landlord_email?: string
    landlord_profile_photo_url?: string
    featured: boolean
    created_at: string
    updated_at: string
}

export interface Payment {
    id: string
    booking_id: string
    amount: number
    payment_method: string
    status: 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled' | 'refund_requested'
    transaction_id?: string
    payment_date: string
    created_at: string
    bank_name?: string
    card_last4?: string
    virtual_account_reference?: string
    virtual_account_number?: string
    virtual_account_bank_name?: string
    virtual_account_bank_code?: string
    virtual_account_expiry?: string | null
    currency?: string
    provider?: string
}

export interface RentalProgressStep {
    key: string
    label: string
    kind?: 'boolean' | 'choice'
    options?: Array<{
        value: string
        label: string
    }>
    selected_value?: string | null
    completed: boolean
    completed_at?: string | null
    counterpart_completed?: boolean
    counterpart_completed_at?: string | null
    counterpart_selected_value?: string | null
    counterpart_step_key?: string | null
}

export interface RentalProgress {
    role: 'tenant' | 'landlord'
    rental_deposit_paid: boolean
    full_rental_amount_paid: boolean
    progress_percent: number
    completed_count: number
    total_count: number
    steps: RentalProgressStep[]
}

export interface TenantScreeningCategoryScore {
    key: string
    label: string
    score: number
}

export interface TenantScreeningSummary {
    overall_score: number
    categories: TenantScreeningCategoryScore[]
}

export interface Booking {
    id: string
    tenant_id: string
    tenant_name?: string
    tenant_email?: string
    listing_id: string
    listing_title?: string
    listing_address?: string
    listing_city?: string
    listing_state?: string
    listing_cover_image_url?: string
    landlord_id?: string
    landlord_name?: string
    start_date: string
    end_date: string
    status: 'pending' | 'confirmed' | 'active' | 'completed' | 'cancelled'
    total_amount: number
    paid_amount: number
    remaining_amount?: number
    landlord_rental_amount?: number | null
    landlord_collected_amount?: number | null
    landlord_expecting_payment_amount?: number | null
    landlord_balance_payment_amount?: number | null
    payments?: Payment[]
    rental_progress?: RentalProgress | null
    tenant_key_collection_confirmed?: boolean
    landlord_key_collection_confirmed?: boolean
    keys_collected_confirmed?: boolean
    tenant_screening_summary?: TenantScreeningSummary | null
    created_at: string
    updated_at: string
}

export interface SearchFilters {
    query?: string
    city?: string
    state?: string
    latitude?: number
    longitude?: number
    radius_km?: number
    min_price?: number
    max_price?: number
    bedrooms?: number
    bathrooms?: number
    toilets?: number
    property_type?: string
    pet_friendly?: boolean
    furnished?: boolean
    utilities_included?: boolean
}

export interface LocationAnalyticsGroup {
    name: string
    state?: string
    city?: string
    listing_count: number
    average_price_per_year: number
    min_price_per_year: number
    max_price_per_year: number
}

export interface LocationAnalyticsResponse {
    total_listings: number
    states: LocationAnalyticsGroup[]
    cities: LocationAnalyticsGroup[]
    neighbourhoods: LocationAnalyticsGroup[]
}

export interface NearestAmenity {
    name: string
    category: string
    city: string
    state: string
    latitude: number
    longitude: number
    distance_km: number
}

export interface NearestAmenitiesResponse {
    listing_id: string
    location_available: boolean
    location_source?: string | null
    latitude?: number
    longitude?: number
    radius_km?: number | null
    amenities: Record<string, NearestAmenity[]>
}
