import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import AiSearchChat from '@/components/AiSearchChat'
import DashboardBackButton from '@/components/DashboardBackButton'
import ListingCard from '@/components/ListingCard'
import { useAppPopup } from '@/contexts/AppPopupContext'
import { useAuth } from '@/hooks/useAuth'
import { api, extractApiErrorMessage } from '@/lib/api'
import { nigeriaStateCitiesMap, nigeriaStateLgaMap, nigerianStates } from '@/lib/locations'
import { Listing, SearchRequirementMatch, TenantSearchRequirement } from '@/types'
import { formatCurrencyWithSymbol } from '@/utils/currency'

const EMPTY_REQUIREMENT: TenantSearchRequirement = {
    preferred_state: '',
    preferred_city: '',
    preferred_lga: '',
    preferred_areas: '',
    min_budget: null,
    max_budget: null,
    max_nightly_budget: null,
    property_type: '',
    min_bedrooms: null,
    max_bedrooms: null,
    min_bathrooms: null,
    min_toilets: null,
    furnishing_level: '',
    power_supply: '',
    water_supply: '',
    preferred_amenities: [],
    move_in_date: null,
    occupants: null,
    notes: '',
}

const PROPERTY_TYPES = ['flat', 'apartment', 'house', 'studio', 'penthouse', 'villa', 'townhouse', 'duplex', 'self-contain']
const ROOM_OPTIONS = [1, 2, 3, 4, 5, 6]
const FURNISHING_OPTIONS = [
    { value: 'unfurnished', label: 'Unfurnished' },
    { value: 'semi_furnished', label: 'Semi-furnished' },
    { value: 'fully_furnished', label: 'Fully furnished' },
]
const POWER_OPTIONS = [
    { value: '24_hours', label: '24-hour supply' },
    { value: 'grid_with_backup', label: 'Grid + inverter/generator backup' },
    { value: 'grid_only', label: 'Grid only' },
    { value: 'limited', label: 'Limited supply' },
]
const WATER_OPTIONS = [
    { value: 'constant', label: 'Constant supply' },
    { value: 'borehole', label: 'Borehole' },
    { value: 'public_mains', label: 'Public mains' },
    { value: 'tanker', label: 'Tanker delivery' },
    { value: 'irregular', label: 'Irregular supply' },
]
const FEATURE_FLAGS: { key: keyof TenantSearchRequirement; label: string }[] = [
    { key: 'pet_friendly', label: 'Pet friendly' },
    { key: 'furnished', label: 'Furnished' },
    { key: 'utilities_included', label: 'Utilities included' },
    { key: 'parking', label: 'Parking' },
    { key: 'garage', label: 'Garage' },
    { key: 'garden', label: 'Garden' },
    { key: 'lift', label: 'Lift / elevator' },
    { key: 'balcony', label: 'Balcony' },
    { key: 'fitted_kitchen', label: 'Fitted kitchen' },
    { key: 'air_conditioning', label: 'Air conditioning' },
    { key: 'internet', label: 'Internet / Wi-Fi' },
    { key: 'boys_quarters', label: 'Boys quarters (BQ)' },
    { key: 'prepaid_meter', label: 'Prepaid meter' },
    { key: 'gated_estate', label: 'Gated estate' },
    { key: 'security_guard', label: 'Security guard' },
    { key: 'cctv', label: 'CCTV' },
    { key: 'wheelchair_accessible', label: 'Wheelchair accessible' },
    { key: 'smoking_allowed', label: 'Smoking allowed' },
    { key: 'short_let_allowed', label: 'Short-let allowed' },
    { key: 'student_tenants_allowed', label: 'Students allowed' },
    { key: 'expatriates_allowed', label: 'Expatriates allowed' },
    { key: 'commercial_activities_allowed', label: 'Commercial use allowed' },
    { key: 'negotiable', label: 'Negotiable rent only' },
]

const inputClass = 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500'
const labelClass = 'block text-sm font-medium text-gray-700 mb-1'

function toNumberOrNull(value: string): number | null {
    const parsed = Number(value)
    return value.trim() !== '' && Number.isFinite(parsed) ? parsed : null
}

export default function PropertySearchRequirementPage() {
    const { user } = useAuth()
    const queryClient = useQueryClient()
    const { alert } = useAppPopup()
    const [form, setForm] = useState<TenantSearchRequirement>(EMPTY_REQUIREMENT)
    const [amenitiesText, setAmenitiesText] = useState('')
    const [matches, setMatches] = useState<SearchRequirementMatch[] | null>(null)
    const [outsideLocationCount, setOutsideLocationCount] = useState(0)
    const [inLocationCount, setInLocationCount] = useState(0)
    const [chatListings, setChatListings] = useState<Listing[]>([])
    const [hasSavedRequirement, setHasSavedRequirement] = useState(false)

    const { isLoading } = useQuery({
        queryKey: ['users', 'me', 'search-requirement'],
        queryFn: async () => {
            try {
                const data = (await api.get<TenantSearchRequirement>('/users/me/search-requirement')).data
                setForm({ ...EMPTY_REQUIREMENT, ...data })
                setAmenitiesText((data.preferred_amenities || []).join(', '))
                setHasSavedRequirement(true)
                return data
            } catch (error: any) {
                if (error?.response?.status === 404) return null
                throw error
            }
        },
    })

    const saveRequirement = useMutation({
        mutationFn: async () => {
            const payload = {
                ...form,
                preferred_amenities: amenitiesText
                    .split(',')
                    .map((item) => item.trim())
                    .filter(Boolean),
            }
            return (await api.put<TenantSearchRequirement>('/users/me/search-requirement', payload)).data
        },
        onSuccess: () => {
            setHasSavedRequirement(true)
            queryClient.invalidateQueries({ queryKey: ['users', 'me', 'search-requirement'] })
            void alert('Search requirement saved. Sally can now use it to recommend matching properties.', { variant: 'success' })
        },
        onError: (error: any) => {
            void alert(extractApiErrorMessage(error, 'Unable to save your search requirement.'), { variant: 'error' })
        },
    })

    const findMatches = useMutation({
        mutationFn: async (limit: number) => (
            await api.get<{
                matches: SearchRequirementMatch[]
                in_location_count: number
                outside_location_count: number
            }>(`/users/me/search-requirement/matches?limit=${limit}`)
        ).data,
        onSuccess: (data) => {
            setMatches(data.matches || [])
            setInLocationCount(data.in_location_count || 0)
            setOutsideLocationCount(data.outside_location_count || 0)
        },
        onError: (error: any) => {
            setMatches(null)
            setInLocationCount(0)
            setOutsideLocationCount(0)
            void alert(extractApiErrorMessage(error, 'Unable to find matches. Save your requirement first.'), { variant: 'error' })
        },
    })

    const setField = <K extends keyof TenantSearchRequirement>(key: K, value: TenantSearchRequirement[K]) => {
        setForm((current) => ({ ...current, [key]: value }))
    }

    const cityOptions = useMemo(
        () => (form.preferred_state ? nigeriaStateCitiesMap[form.preferred_state] || [] : []),
        [form.preferred_state],
    )
    const lgaOptions = useMemo(
        () => (form.preferred_state ? nigeriaStateLgaMap[form.preferred_state] || [] : []),
        [form.preferred_state],
    )

    if (isLoading) {
        return (
            <div className="container-modern py-8">
                <div className="text-center">Loading search requirement...</div>
            </div>
        )
    }

    return (
        <div className="min-h-screen bg-gray-50">
            <div className="container-modern py-8">
                <div className="mb-5">
                    <DashboardBackButton to={user ? `/dashboard/tenant/${user.id}` : '/'} label="Back to dashboard" />
                </div>

                <div className="mb-8">
                    <h1 className="text-3xl font-bold text-gray-900">Property Search Requirement</h1>
                    <p className="mt-2 max-w-2xl text-[16px] text-gray-600">
                        Tell us about the home you're looking for — every field is optional.<br/>
                        Sally, our AI assistant, uses the information to recommend top 3 property that matches your requirement.
                    </p>
                </div>

                <form
                    onSubmit={(event) => {
                        event.preventDefault()
                        saveRequirement.mutate()
                    }}
                    className="space-y-6"
                >
                    <section className="card p-6">
                        <h2 className="text-lg font-semibold text-gray-900">Preferred location & Budget</h2>
                        <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
                            <div>
                                <label className={labelClass}>State</label>
                                <select
                                    className={inputClass}
                                    value={form.preferred_state || ''}
                                    onChange={(event) => setForm((current) => ({
                                        ...current,
                                        preferred_state: event.target.value,
                                        preferred_city: '',
                                        preferred_lga: '',
                                    }))}
                                >
                                    <option value="">Any state</option>
                                    {nigerianStates.map((state) => (
                                        <option key={state} value={state}>{state}</option>
                                    ))}
                                </select>
                            </div>
                            <div>
                                <label className={labelClass}>City</label>
                                {cityOptions.length > 0 ? (
                                    <select
                                        className={inputClass}
                                        value={form.preferred_city || ''}
                                        onChange={(event) => setField('preferred_city', event.target.value)}
                                    >
                                        <option value="">Any city</option>
                                        {cityOptions.map((city) => (
                                            <option key={city} value={city}>{city}</option>
                                        ))}
                                    </select>
                                ) : (
                                    <input
                                        type="text"
                                        className={inputClass}
                                        value={form.preferred_city || ''}
                                        onChange={(event) => setField('preferred_city', event.target.value)}
                                        placeholder="e.g. Lekki, Ikeja"
                                    />
                                )}
                            </div>
                            <div>
                                <label className={labelClass}>LGA</label>
                                {lgaOptions.length > 0 ? (
                                    <select
                                        className={inputClass}
                                        value={form.preferred_lga || ''}
                                        onChange={(event) => setField('preferred_lga', event.target.value)}
                                    >
                                        <option value="">Any LGA</option>
                                        {lgaOptions.map((lga) => (
                                            <option key={lga} value={lga}>{lga}</option>
                                        ))}
                                    </select>
                                ) : (
                                    <input
                                        type="text"
                                        className={inputClass}
                                        value={form.preferred_lga || ''}
                                        onChange={(event) => setField('preferred_lga', event.target.value)}
                                        placeholder="Local Government Area"
                                    />
                                )}
                            </div>
                            <div>
                                <label className={labelClass}>Preferred areas / landmarks</label>
                                <input
                                    type="text"
                                    className={inputClass}
                                    value={form.preferred_areas || ''}
                                    onChange={(event) => setField('preferred_areas', event.target.value)}
                                    placeholder="e.g. Lekki Phase 1, GRA"
                                />
                                <p className="mt-1 text-xs text-gray-500">Separate multiple areas with commas.</p>
                            </div>
                            <div>
                                <label className={labelClass}>Minimum budget (₦ / year)</label>
                                <input
                                    type="number"
                                    min={0}
                                    className={inputClass}
                                    value={form.min_budget ?? ''}
                                    onChange={(event) => setField('min_budget', toNumberOrNull(event.target.value))}
                                    placeholder="e.g. 500000"
                                />
                            </div>
                            <div>
                                <label className={labelClass}>Maximum budget (₦ / year)</label>
                                <input
                                    type="number"
                                    min={0}
                                    className={inputClass}
                                    value={form.max_budget ?? ''}
                                    onChange={(event) => setField('max_budget', toNumberOrNull(event.target.value))}
                                    placeholder="e.g. 2000000"
                                />
                            </div>
                        </div>
                    </section>

                    <section className="card p-6">
                        <h2 className="text-lg font-semibold text-gray-900">Property details</h2>
                        <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
                            <div>
                                <label className={labelClass}>Property type</label>
                                <select
                                    className={inputClass}
                                    value={form.property_type || ''}
                                    onChange={(event) => setField('property_type', event.target.value)}
                                >
                                    <option value="">Any type</option>
                                    {PROPERTY_TYPES.map((type) => (
                                        <option key={type} value={type}>{type.charAt(0).toUpperCase() + type.slice(1)}</option>
                                    ))}
                                </select>
                            </div>
                            <div>
                                <label className={labelClass}>Min bedrooms</label>
                                <select
                                    className={inputClass}
                                    value={form.min_bedrooms ?? ''}
                                    onChange={(event) => setField('min_bedrooms', toNumberOrNull(event.target.value))}
                                >
                                    <option value="">Any</option>
                                    {ROOM_OPTIONS.map((count) => (
                                        <option key={count} value={count}>{count}+</option>
                                    ))}
                                </select>
                            </div>
                            <div>
                                <label className={labelClass}>Max bedrooms</label>
                                <select
                                    className={inputClass}
                                    value={form.max_bedrooms ?? ''}
                                    onChange={(event) => setField('max_bedrooms', toNumberOrNull(event.target.value))}
                                >
                                    <option value="">Any</option>
                                    {ROOM_OPTIONS.map((count) => (
                                        <option key={count} value={count}>{count}</option>
                                    ))}
                                </select>
                            </div>
                            <div>
                                <label className={labelClass}>Occupants</label>
                                <input
                                    type="number"
                                    min={1}
                                    className={inputClass}
                                    value={form.occupants ?? ''}
                                    onChange={(event) => setField('occupants', toNumberOrNull(event.target.value))}
                                    placeholder="People living there"
                                />
                            </div>
                            <div>
                                <label className={labelClass}>Min bathrooms</label>
                                <select
                                    className={inputClass}
                                    value={form.min_bathrooms ?? ''}
                                    onChange={(event) => setField('min_bathrooms', toNumberOrNull(event.target.value))}
                                >
                                    <option value="">Any</option>
                                    {ROOM_OPTIONS.map((count) => (
                                        <option key={count} value={count}>{count}+</option>
                                    ))}
                                </select>
                            </div>
                            <div>
                                <label className={labelClass}>Min toilets</label>
                                <select
                                    className={inputClass}
                                    value={form.min_toilets ?? ''}
                                    onChange={(event) => setField('min_toilets', toNumberOrNull(event.target.value))}
                                >
                                    <option value="">Any</option>
                                    {ROOM_OPTIONS.map((count) => (
                                        <option key={count} value={count}>{count}+</option>
                                    ))}
                                </select>
                            </div>
                            <div>
                                <label className={labelClass}>Furnishing</label>
                                <select
                                    className={inputClass}
                                    value={form.furnishing_level || ''}
                                    onChange={(event) => setField('furnishing_level', event.target.value)}
                                >
                                    <option value="">Any</option>
                                    {FURNISHING_OPTIONS.map((option) => (
                                        <option key={option.value} value={option.value}>{option.label}</option>
                                    ))}
                                </select>
                            </div>
                            <div>
                                <label className={labelClass}>Earliest move-in date</label>
                                <input
                                    type="date"
                                    className={inputClass}
                                    value={form.move_in_date || ''}
                                    onChange={(event) => setField('move_in_date', event.target.value || null)}
                                />
                            </div>
                            <div>
                                <label className={labelClass}>Power supply</label>
                                <select
                                    className={inputClass}
                                    value={form.power_supply || ''}
                                    onChange={(event) => setField('power_supply', event.target.value)}
                                >
                                    <option value="">Any</option>
                                    {POWER_OPTIONS.map((option) => (
                                        <option key={option.value} value={option.value}>{option.label}</option>
                                    ))}
                                </select>
                            </div>
                            <div>
                                <label className={labelClass}>Water supply</label>
                                <select
                                    className={inputClass}
                                    value={form.water_supply || ''}
                                    onChange={(event) => setField('water_supply', event.target.value)}
                                >
                                    <option value="">Any</option>
                                    {WATER_OPTIONS.map((option) => (
                                        <option key={option.value} value={option.value}>{option.label}</option>
                                    ))}
                                </select>
                            </div>
                        </div>
                    </section>

                    <section className="card p-6">
                        <h2 className="text-lg font-semibold text-gray-900">Must-have features</h2>
                        <p className="mt-1 text-xs text-gray-500">Tick only the features the property must provide.</p>
                        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
                            {FEATURE_FLAGS.map(({ key, label }) => (
                                <label key={key} className="flex items-center gap-2 text-sm text-gray-700">
                                    <input
                                        type="checkbox"
                                        className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                                        checked={Boolean(form[key])}
                                        onChange={(event) => setField(key, event.target.checked as never)}
                                    />
                                    {label}
                                </label>
                            ))}
                        </div>
                        <div className="mt-4">
                            <label className={labelClass}>Preferred amenities</label>
                            <input
                                type="text"
                                className={inputClass}
                                value={amenitiesText}
                                onChange={(event) => setAmenitiesText(event.target.value)}
                                placeholder="e.g. swimming pool, gym, inverter"
                            />
                            <p className="mt-1 text-xs text-gray-500">Nice-to-haves — separate with commas.</p>
                        </div>
                        <div className="mt-4">
                            <label className={labelClass}>Anything else Sally should know?</label>
                            <textarea
                                className={inputClass}
                                rows={3}
                                value={form.notes || ''}
                                onChange={(event) => setField('notes', event.target.value)}
                                placeholder="e.g. Quiet neighbourhood, close to my office in Victoria Island, prefer a serviced estate."
                            />
                        </div>
                    </section>


                </form>

                <section className="mt-2">
                    <h2 className="mb-2 text-2xl font-bold text-gray-900">Ask Sally</h2>
                    <p className="mb-4 text-sm text-gray-600">
                        Sally can read your saved requirement — try asking{' '}
                        <span className="italic">"Match properties to my saved search requirement"</span> or{' '}
                        <span className="italic">"What did I save in my search requirement?"</span>
                    </p>
                    <AiSearchChat onListingsFound={(listings) => setChatListings(listings)} />

                    <div className="mt-4 flex flex-wrap items-center justify-end gap-3">
                        <button type="button" className="btn btn-primary" disabled={saveRequirement.isPending} onClick={() => saveRequirement.mutate()}>
                            {saveRequirement.isPending ? 'Saving...' : 'Save Search Requirement'}
                        </button>
                        <button
                            type="button"
                            className="btn btn-outline"
                            disabled={findMatches.isPending || saveRequirement.isPending}
                            onClick={() => {
                                if (!hasSavedRequirement) {
                                    void alert('Save your search requirement first.', { variant: 'info' })
                                    return
                                }
                                findMatches.mutate(3)
                            }}
                        >
                            {findMatches.isPending ? 'Finding matches...' : 'Show My Top 3 Matches'}
                        </button>
                        <button
                            type="button"
                            className="btn btn-outline"
                            onClick={() => {
                                setForm(EMPTY_REQUIREMENT)
                                setAmenitiesText('')
                                setMatches(null)
                                setInLocationCount(0)
                                setOutsideLocationCount(0)
                            }}
                        >
                            Clear Form
                        </button>
                    </div>

                    {chatListings.length > 0 && (
                        <div className="mt-6">
                            <h3 className="mb-4 text-lg font-semibold text-gray-900">Properties Sally found</h3>
                            <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
                                {chatListings.map((listing) => (
                                    <ListingCard key={listing.id} listing={listing} />
                                ))}
                            </div>
                        </div>
                    )}
                </section>

                {matches !== null && (
                    <section className="mt-10">
                        <h2 className="text-2xl font-bold text-gray-900">
                            Your top matches{inLocationCount > 0 ? ` — showing ${matches.length} of ${inLocationCount}` : ''}
                        </h2>
                        {matches.length > 0 ? (
                            <div className="mt-6 grid items-start gap-6 sm:grid-cols-2 lg:grid-cols-3">
                                {matches.map((match) => (
                                    <div key={match.listing.id} className="relative">
                                        <span className="absolute left-3 top-3 z-10 rounded-full bg-indigo-600 px-3 py-1 text-xs font-semibold text-white shadow">
                                            {Math.round(match.match_score)}% match
                                        </span>
                                        <ListingCard listing={match.listing} />
                                        {match.match_reasons.length > 0 && (
                                            <ul className="mt-2 space-y-1 text-xs text-gray-600">
                                                {match.match_reasons.slice(0, 4).map((reason) => (
                                                    <li key={reason} className="flex items-start gap-1.5">
                                                        <span className="mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full bg-green-500" />
                                                        {reason}
                                                    </li>
                                                ))}
                                            </ul>
                                        )}
                                    </div>
                                ))}
                            </div>
                        ) : (
                            <p className="mt-4 text-sm text-gray-600">
                                No matches yet — add a few preferences above, save, and try again.
                            </p>
                        )}
                        {inLocationCount > matches.length && (
                            <button
                                type="button"
                                className="btn btn-outline mt-4"
                                disabled={findMatches.isPending}
                                onClick={() => findMatches.mutate(matches.length + 3)}
                            >
                                {findMatches.isPending ? 'Loading...' : `Show more matches (${inLocationCount - matches.length} more)`}
                            </button>
                        )}
                        {outsideLocationCount > 0 && (
                            <p className="mt-4 text-sm text-gray-700">
                                {outsideLocationCount} other {outsideLocationCount === 1 ? 'property matches' : 'properties match'} your
                                requirement outside your preferred location.{' '}
                                <Link to="/search" className="text-blue-600 underline">Broaden your search</Link> or ask Sally to show them.
                            </p>
                        )}
                        <p className="mt-4 text-sm text-gray-500">
                            Match scores reflect how closely each property fits the preferences you saved.
                            You can also <Link to="/search" className="text-blue-600 underline">browse all properties</Link>.
                        </p>
                    </section>
                )}


            </div>
        </div>
    )
}
