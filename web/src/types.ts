export type UserResidence = {
    state?: string
    city?: string
    address?: string
    origin_country?: string
    origin_city?: string
}

export type LandlordVerificationType = 'individual' | 'corporate'

export type AccountRole = 'tenant' | 'landlord' | 'agent' | 'admin'

export type User = {
    id: string
    name: string
    email: string
    role: AccountRole
    available_roles?: AccountRole[]
    token?: string
    email_verified?: boolean
    profile_photo_url?: string | null
    mobile?: string
    whatsapp_number?: string
    nin_number?: string
    bvn_number?: string
    state_of_origin?: string
    residence?: UserResidence | null
    landlord_verification_type?: LandlordVerificationType | ''
    landlord_verification_profile?: Record<string, any> | null
    tenant_verification_profile?: Record<string, any> | null
    is_verified?: boolean
    verification_payment_required?: boolean
    verification_attempts?: number
    verification_badge?: string
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
    role: 'tenant' | 'landlord' | 'agent' | 'admin'
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
    lga?: string
    latitude?: number
    longitude?: number
    distance_km?: number | null
    location_source?: string | null
    property_type: string
    category: 'residential' | 'commercial' | 'shortlet'
    rental_badge?: 'let_agreed' | 'rented' | ''
    is_hidden: boolean
    shortlet_lister_role?: string
    shortlet_check_in_time?: string | null
    shortlet_check_out_time?: string | null
    minimum_stay_nights?: number | null
    maximum_stay_nights?: number | null
    cleaning_fee?: number | null
    bedrooms: number
    bathrooms: number
    toilets?: number
    square_feet?: number
    price_per_year: number
    deposit_amount?: number
    service_charge?: number | null
    caution_fee?: number | null
    nightly_rate?: number | null
    negotiable?: boolean
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
    furnishing_level?: string
    air_conditioning?: boolean
    internet?: boolean
    boys_quarters?: boolean
    prepaid_meter?: boolean
    gated_estate?: boolean
    security_guard?: boolean
    cctv?: boolean
    wheelchair_accessible?: boolean
    power_supply?: string
    water_supply?: string
    floor_number?: number | null
    total_floors?: number | null
    parking_spaces?: number | null
    year_built?: number | null
    pet_policy?: string
    video_tour_url?: string
    area?: string
    nearest_landmark?: string
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
    maximum_rental_duration?: string
    maximum_occupancy?: number | null
    smoking_allowed?: boolean
    party_allowed?: boolean
    commercial_activities_allowed?: boolean
    short_let_allowed?: boolean
    student_tenants_allowed?: boolean
    expatriates_allowed?: boolean
    available_from?: string
    available_until?: string
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

export interface TenantRefund {
    id: string
    booking_id: string
    payment_id: string
    payment_method?: string
    payment_transaction_id?: string
    amount: number
    fee_amount: number
    refund_amount: number
    currency?: string
    reason?: string
    bank_name: string
    account_number: string
    account_name?: string
    status: 'scheduled' | 'recipient_created' | 'ready' | 'processing' | 'paid' | 'failed'
    last_error?: string
    process_at?: string
    transferred_at?: string | null
    created_at: string
    updated_at: string
}

export interface RepresentativeKyc {
    id: string
    token: string
    listing_id?: string | null
    listing_title?: string
    landlord_name?: string
    ownership_type?: string
    name?: string
    email?: string
    phone?: string
    status: 'pending' | 'submitted' | 'verified' | 'rejected'
    kyc_url: string
    return_url?: string
    submitted_at?: string | null
    verified_at?: string | null
    created_at?: string
    updated_at?: string
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
    rental_process_started: boolean
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
    category?: string
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

export interface AiChatMessage {
    role: 'user' | 'assistant'
    content: string
}

export interface AiChatResponse {
    reply: string
    listings: Listing[]
    filters: Partial<SearchFilters>
    total_count?: number
    mode?: 'ai' | 'limited'
    session_id?: string | null
}

export interface TenantSearchRequirement {
    id?: string
    preferred_state?: string
    preferred_city?: string
    preferred_lga?: string
    preferred_areas?: string
    min_budget?: number | null
    max_budget?: number | null
    max_nightly_budget?: number | null
    property_type?: string
    min_bedrooms?: number | null
    max_bedrooms?: number | null
    min_bathrooms?: number | null
    min_toilets?: number | null
    furnishing_level?: string
    power_supply?: string
    water_supply?: string
    pet_friendly?: boolean
    furnished?: boolean
    utilities_included?: boolean
    parking?: boolean
    garage?: boolean
    garden?: boolean
    lift?: boolean
    balcony?: boolean
    fitted_kitchen?: boolean
    air_conditioning?: boolean
    internet?: boolean
    boys_quarters?: boolean
    prepaid_meter?: boolean
    gated_estate?: boolean
    security_guard?: boolean
    cctv?: boolean
    wheelchair_accessible?: boolean
    smoking_allowed?: boolean
    short_let_allowed?: boolean
    student_tenants_allowed?: boolean
    expatriates_allowed?: boolean
    commercial_activities_allowed?: boolean
    negotiable?: boolean
    preferred_amenities?: string[]
    move_in_date?: string | null
    occupants?: number | null
    notes?: string
    created_at?: string
    updated_at?: string
}

export interface SearchRequirementMatch {
    listing: Listing
    match_score: number
    match_reasons: string[]
}

export type ServicePaymentPurpose = 'agent_verification' | 'tenant_verification' | 'landlord_verification' | 'lawyer_tenancy' | 'in_person_verification'
export type ServicePaymentStatus = 'pending' | 'completed' | 'failed' | 'cancelled'

export interface ServicePayment {
    id: string
    user_id: string
    booking_id?: string | null
    listing_id?: string | null
    listing_title?: string
    purpose: ServicePaymentPurpose
    purpose_display?: string
    amount: number
    currency: string
    status: ServicePaymentStatus
    status_display?: string
    provider?: string
    transaction_id?: string
    payment_date?: string | null
    return_path?: string
    created_at: string
    updated_at: string
}

export interface AgentProfile {
    id: string
    email?: string
    profile_photo_url?: string | null
    is_verified?: boolean
    first_name: string
    middle_name?: string
    last_name: string
    date_of_birth?: string | null
    gender?: string
    country_of_birth?: string
    nationality?: string
    state_of_origin?: string
    lga_of_origin?: string
    mobile?: string
    whatsapp_number?: string
    city?: string
    residential_address?: string
    nin_number?: string
    bvn_number?: string
    bank_name?: string
    bank_code?: string
    account_name?: string
    account_number?: string
    verification_status: 'incomplete' | 'payment_required' | 'pending' | 'verified' | 'rejected'
    verified_at?: string | null
    verification_attempts?: number
    verification_payment?: ServicePayment | null
    verification_payment_required?: boolean
    verification_badge?: string
    referral_code?: string
    mobile_warning?: string
    created_at?: string
    updated_at?: string
}

export interface AgentReferralNode {
    id: string
    name: string
    profile_photo_url?: string | null
    referral_code?: string
    is_verified?: boolean
    properties_inspected: number
    earned_from_referral?: string
    children: AgentReferralNode[]
}

export interface AgentReferralEarning {
    id: string
    referred_name: string
    amount: string
    payout_status: 'pending' | 'paid'
    created_at: string
}

export interface AgentReferralsResponse {
    referral_code: string
    referred_by?: { id: string; name: string; profile_photo_url?: string | null } | null
    metrics: {
        total_referrals: number
        total_referral_earned: string
        total_referral_paid: string
        referral_earning_per_inspection: string
        referral_earning_cap: string
    }
    earnings: AgentReferralEarning[]
    tree: AgentReferralNode
}

export interface InspectionFieldOption {
    value: string
    label: string
}

export interface InspectionField {
    key: string
    label: string
    type: 'select' | 'multiselect' | 'text' | 'textarea' | 'number' | 'checkbox'
    required: boolean
    options?: InspectionFieldOption[]
}

export interface InspectionSection {
    key: string
    title: string
    fields: InspectionField[]
}

export interface InspectionChecklistSchema {
    sections: InspectionSection[]
}

export interface PropertyInspection {
    id: string
    listing_id: string
    listing_title?: string
    listing_address?: string
    listing_city?: string
    listing_state?: string
    landlord_name?: string
    agent_id: string
    agent_name?: string
    agent_email?: string
    status: 'claimed' | 'draft' | 'submitted'
    status_display?: string
    responses: Record<string, unknown>
    analysis: Record<string, unknown>
    overall_status?: string
    evidence_documents?: Array<{
        id: string
        title: string
        file_url?: string
        content_type?: string
        created_at?: string
    }>
    earning_amount: number | string
    payout_status: 'pending' | 'paid'
    payout_status_display?: string
    payout_reference?: string
    claimed_at?: string
    submission_deadline?: string | null
    submitted_at?: string | null
    signed_off_at?: string | null
    paid_out_at?: string | null
    created_at: string
    updated_at: string
}

export interface InspectionRequest {
    id: string
    listing: Listing
    status: 'pending' | 'accepted' | 'taken' | 'expired'
    status_display?: string
    round: number
    notified_channels?: string[]
    expires_at: string
    accepted_at?: string | null
    is_expired: boolean
    created_at: string
}

export interface AgentDashboard {
    profile: AgentProfile
    verification_payment?: ServicePayment | null
    available_inspections: Listing[]
    inspection_requests?: InspectionRequest[]
    inspections: PropertyInspection[]
    metrics: {
        properties_inspected: number
        total_amount_earned: number | string
        total_amount_paid_out: number | string
        pending_payout: number | string
    }
}
