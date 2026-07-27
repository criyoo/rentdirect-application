import { useState, useEffect, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import ListingCard from '@/components/ListingCard'
import { Listing, LocationAnalyticsGroup, LocationAnalyticsResponse, SearchFilters } from '@/types'
import { api, getApiUrl } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { nigeriaStateLgaMap, nigerianStates } from '@/lib/locations'
import { formatCurrencyWithSymbol } from '@/utils/currency'

const OTHER_CITY_OPTION = '__other__'
const radiusOptions = [1, 5, 10, 25, 50, 100]

function numberParam(value: string | null) {
    if (!value) return undefined
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : undefined
}

function AnalyticsColumn({ title, items }: { title: string; items: LocationAnalyticsGroup[] }) {
    return (
        <div className="rounded-lg border border-gray-200 p-4">
            <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
            <div className="mt-3 space-y-3">
                {items.slice(0, 5).map((item) => (
                    <div key={`${title}-${item.state || ''}-${item.city || ''}-${item.name}`} className="flex items-start justify-between gap-3">
                        <div>
                            <p className="text-sm font-medium text-gray-900">{item.name}</p>
                            <p className="text-xs text-gray-500">{item.listing_count} listing{item.listing_count === 1 ? '' : 's'}</p>
                        </div>
                        <p className="text-right text-xs font-medium text-gray-700">
                            {formatCurrencyWithSymbol(item.average_price_per_year)}
                        </p>
                    </div>
                ))}
                {!items.length ? <p className="text-sm text-gray-500">No data yet</p> : null}
            </div>
        </div>
    )
}

export default function SearchPage() {
    const { user } = useAuth()
    const [searchParams, setSearchParams] = useSearchParams()
    const initialLatitude = numberParam(searchParams.get('latitude'))
    const initialLongitude = numberParam(searchParams.get('longitude'))
    const [listings, setListings] = useState<Listing[]>([])
    const [loading, setLoading] = useState(false)
    const [locationStatus, setLocationStatus] = useState('')
    const [selectedCityOption, setSelectedCityOption] = useState(searchParams.get('city') || '')
    const [otherCity, setOtherCity] = useState('')
    const [filters, setFilters] = useState<SearchFilters>({
        query: searchParams.get('q') || '',
        city: searchParams.get('city') || '',
        state: searchParams.get('state') || '',
        latitude: initialLatitude,
        longitude: initialLongitude,
        radius_km: numberParam(searchParams.get('radius_km')) || (initialLatitude !== undefined && initialLongitude !== undefined ? 10 : undefined),
        min_price: searchParams.get('min_price') ? Number(searchParams.get('min_price')) : undefined,
        max_price: searchParams.get('max_price') ? Number(searchParams.get('max_price')) : undefined,
        bedrooms: searchParams.get('bedrooms') ? Number(searchParams.get('bedrooms')) : undefined,
        bathrooms: searchParams.get('bathrooms') ? Number(searchParams.get('bathrooms')) : undefined,
        toilets: searchParams.get('toilets') ? Number(searchParams.get('toilets')) : undefined,
        property_type: searchParams.get('property_type') || '',
        pet_friendly: searchParams.get('pet_friendly') === 'true',
        furnished: searchParams.get('furnished') === 'true',
        utilities_included: searchParams.get('utilities_included') === 'true'
    })

    // Fetch user's favourites
    const { data: favourites } = useQuery({
        queryKey: ['me', 'favourites'],
        queryFn: async () => (await api.get<Listing[]>('/users/me/favourites')).data,
        enabled: user?.role === 'tenant'
    })

    const { data: locationAnalytics } = useQuery({
        queryKey: ['listings', 'location-analytics', filters.state, filters.city],
        queryFn: async () => {
            const params = new URLSearchParams()
            if (filters.state) params.set('state', filters.state)
            if (filters.city) params.set('city', filters.city)
            const suffix = params.toString() ? `?${params.toString()}` : ''
            return (await api.get<LocationAnalyticsResponse>(`/listings/location-analytics${suffix}`)).data
        },
    })

    const propertyTypes = ['flat', 'apartment', 'house', 'studio', 'penthouse', 'villa', 'townhouse']
    const bedroomOptions = [1, 2, 3, 4, 5, 6]
    const bathroomOptions = [1, 2, 3, 4, 5, 6]
    const toiletOptions = [1, 2, 3, 4, 5, 6]
    const availableCities = useMemo(
        () => (filters.state ? (nigeriaStateLgaMap[filters.state] || []) : []),
        [filters.state],
    )

    const normalizeResults = (payload: Listing[] | { results?: Listing[] }) => {
        if (Array.isArray(payload)) {
            return payload
        }
        return Array.isArray(payload.results) ? payload.results : []
    }

    const syncSearchParams = (searchFilters: SearchFilters) => {
        const params = new URLSearchParams()
        const hasLocationSearch = searchFilters.latitude !== undefined
            && searchFilters.longitude !== undefined
            && searchFilters.radius_km !== undefined
        if (searchFilters.query) params.set('q', searchFilters.query)
        if (searchFilters.city) params.set('city', searchFilters.city)
        if (searchFilters.state) params.set('state', searchFilters.state)
        if (hasLocationSearch) {
            params.set('latitude', searchFilters.latitude!.toString())
            params.set('longitude', searchFilters.longitude!.toString())
            params.set('radius_km', searchFilters.radius_km!.toString())
        }
        if (searchFilters.min_price !== undefined) params.set('min_price', searchFilters.min_price.toString())
        if (searchFilters.max_price !== undefined) params.set('max_price', searchFilters.max_price.toString())
        if (searchFilters.bedrooms !== undefined) params.set('bedrooms', searchFilters.bedrooms.toString())
        if (searchFilters.bathrooms !== undefined) params.set('bathrooms', searchFilters.bathrooms.toString())
        if (searchFilters.toilets !== undefined) params.set('toilets', searchFilters.toilets.toString())
        if (searchFilters.property_type) params.set('property_type', searchFilters.property_type)
        if (searchFilters.pet_friendly) params.set('pet_friendly', 'true')
        if (searchFilters.furnished) params.set('furnished', 'true')
        if (searchFilters.utilities_included) params.set('utilities_included', 'true')
        setSearchParams(params, { replace: true })
    }

    useEffect(() => {
        if (!filters.state) {
            setSelectedCityOption('')
            setOtherCity('')
            return
        }

        if (!filters.city) {
            setSelectedCityOption('')
            setOtherCity('')
            return
        }

        if (availableCities.includes(filters.city)) {
            setSelectedCityOption(filters.city)
            setOtherCity('')
            return
        }

        setSelectedCityOption(OTHER_CITY_OPTION)
        setOtherCity(filters.city)
    }, [availableCities, filters.city, filters.state])

    const searchListings = async (searchFilters: SearchFilters) => {
        setLoading(true)
        try {
            // Check if any filters are applied
            const hasLocationSearch = searchFilters.latitude !== undefined
                && searchFilters.longitude !== undefined
                && searchFilters.radius_km !== undefined
            const hasFilters = Object.entries(searchFilters).some(([key, value]) =>
                (!['latitude', 'longitude', 'radius_km'].includes(key) || hasLocationSearch)
                && value !== ''
                && value !== undefined
                && value !== null
                && value !== false
            )

            let url: string
            if (hasFilters) {
                // Use search endpoint with filters
                const params = new URLSearchParams()

                if (searchFilters.query) params.append('query', searchFilters.query)
                if (searchFilters.city) params.append('city', searchFilters.city)
                if (searchFilters.state) params.append('state', searchFilters.state)
                if (hasLocationSearch) {
                    params.append('latitude', searchFilters.latitude!.toString())
                    params.append('longitude', searchFilters.longitude!.toString())
                    params.append('radius_km', searchFilters.radius_km!.toString())
                }
                if (searchFilters.min_price) params.append('min_price', searchFilters.min_price.toString())
                if (searchFilters.max_price) params.append('max_price', searchFilters.max_price.toString())
                if (searchFilters.bedrooms) params.append('bedrooms', searchFilters.bedrooms.toString())
                if (searchFilters.bathrooms) params.append('bathrooms', searchFilters.bathrooms.toString())
                if (searchFilters.toilets) params.append('toilets', searchFilters.toilets.toString())
                if (searchFilters.property_type) params.append('property_type', searchFilters.property_type)
                // Only send boolean parameters if they are true
                if (searchFilters.pet_friendly === true) params.append('pet_friendly', 'true')
                if (searchFilters.furnished === true) params.append('furnished', 'true')
                if (searchFilters.utilities_included === true) params.append('utilities_included', 'true')

                url = `${getApiUrl()}/listings/search?${params.toString()}`
            } else {
                // Use simple listings endpoint for all available listings
                url = `${getApiUrl()}/listings`
            }

            console.log('Searching with URL:', url)
            console.log('Search filters:', searchFilters)

            const response = await fetch(url)
            if (response.ok) {
                const data = await response.json()
                console.log('Search results:', data)
                setListings(normalizeResults(data))
                syncSearchParams(searchFilters)
            } else {
                console.error('Failed to fetch listings:', response.status, response.statusText)
                const errorText = await response.text()
                console.error('Error response:', errorText)
                setListings([])
            }
        } catch (error) {
            console.error('Error searching listings:', error)
            setListings([])
        } finally {
            setLoading(false)
        }
    }

    const handleFilterChange = (key: keyof SearchFilters, value: any) => {
        const newFilters = { ...filters, [key]: value }
        setFilters(newFilters)
    }

    const handleStateChange = (state: string) => {
        setSelectedCityOption('')
        setOtherCity('')
        setFilters((current) => ({
            ...current,
            state,
            city: '',
        }))
    }

    const handleCityOptionChange = (value: string) => {
        setSelectedCityOption(value)

        if (!value) {
            setOtherCity('')
            handleFilterChange('city', '')
            return
        }

        if (value === OTHER_CITY_OPTION) {
            handleFilterChange('city', otherCity)
            return
        }

        setOtherCity('')
        handleFilterChange('city', value)
    }

    const handleOtherCityChange = (value: string) => {
        setOtherCity(value)
        handleFilterChange('city', value)
    }

    const handleUseCurrentLocation = () => {
        if (!('geolocation' in navigator)) {
            setLocationStatus('Location is not available in this browser.')
            return
        }

        setLocationStatus('Detecting location...')
        navigator.geolocation.getCurrentPosition(
            ({ coords }) => {
                const nextFilters = {
                    ...filters,
                    latitude: Number(coords.latitude.toFixed(6)),
                    longitude: Number(coords.longitude.toFixed(6)),
                    radius_km: filters.radius_km || 10,
                }
                setFilters(nextFilters)
                setLocationStatus(`Using current location within ${nextFilters.radius_km} km.`)
                searchListings(nextFilters)
            },
            () => {
                setLocationStatus('Unable to read your location. Check browser location permission.')
            },
            { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 },
        )
    }

    const handleClearLocation = () => {
        const nextFilters = {
            ...filters,
            latitude: undefined,
            longitude: undefined,
            radius_km: undefined,
        }
        setFilters(nextFilters)
        setLocationStatus('')
    }

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault()
        searchListings(filters)
    }

    const clearFilters = () => {
        const clearedFilters: SearchFilters = {
            query: '',
            city: '',
            state: '',
            latitude: undefined,
            longitude: undefined,
            radius_km: undefined,
            min_price: undefined,
            max_price: undefined,
            bedrooms: undefined,
            bathrooms: undefined,
            toilets: undefined,
            property_type: '',
            pet_friendly: false,
            furnished: false,
            utilities_included: false
        }
        setSelectedCityOption('')
        setOtherCity('')
        setLocationStatus('')
        setFilters(clearedFilters)
        searchListings(clearedFilters)
    }

    // Check if a listing is in user's favourites
    const isFavourite = (listingId: string | number) => {
        return favourites?.some(f => f.id === listingId) || false
    }

    // Initial search on component mount
    useEffect(() => {
        searchListings(filters)
    }, [])

    return (
        <div className="bg-gray-50 min-h-screen py-8">
            <div className="container-modern">
                <h1 className="text-3xl font-bold text-gray-900 mb-8">Search Properties</h1>

                {/* Search Form */}
                <form onSubmit={handleSubmit} className="bg-white rounded-lg shadow-md p-6 mb-2">
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                        {/* Search Query */}
                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-1">Search</label>
                            <input
                                type="text"
                                value={filters.query}
                                onChange={(e) => handleFilterChange('query', e.target.value)}
                                placeholder="Search properties..."
                                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                            />
                        </div>

                        {/* State */}
                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-1">State</label>
                            <select
                                value={filters.state || ''}
                                onChange={(e) => handleStateChange(e.target.value)}
                                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                            >
                                <option value="">All States</option>
                                {nigerianStates.map((state) => (
                                    <option key={state} value={state}>{state}</option>
                                ))}
                            </select>
                        </div>

                        {/* City */}
                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-1">City</label>
                            <div className="space-y-2">
                                <select
                                    value={selectedCityOption}
                                    onChange={(e) => handleCityOptionChange(e.target.value)}
                                    disabled={!filters.state}
                                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100 disabled:text-gray-500"
                                >
                                    <option value="">{filters.state ? 'All Cities' : 'Select state first'}</option>
                                    {availableCities.map((city) => (
                                        <option key={city} value={city}>{city}</option>
                                    ))}
                                    {filters.state ? <option value={OTHER_CITY_OPTION}>Other</option> : null}
                                </select>

                                {selectedCityOption === OTHER_CITY_OPTION ? (
                                    <input
                                        type="text"
                                        value={otherCity}
                                        onChange={(e) => handleOtherCityChange(e.target.value)}
                                        placeholder="Enter city"
                                        className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                                    />
                                ) : null}
                            </div>
                        </div>

                        {/* Property Type */}
                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-1">Property Type</label>
                            <select
                                value={filters.property_type}
                                onChange={(e) => handleFilterChange('property_type', e.target.value)}
                                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                            >
                                <option value="">All Types</option>
                                {propertyTypes.map((type) => (
                                    <option key={type} value={type}>{type.charAt(0).toUpperCase() + type.slice(1)}</option>
                                ))}
                            </select>
                        </div>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mt-4">
                        {/* Bedrooms */}
                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-1">Bedrooms</label>
                            <select
                                value={filters.bedrooms || ''}
                                onChange={(e) => handleFilterChange('bedrooms', e.target.value ? Number(e.target.value) : undefined)}
                                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                            >
                                <option value="">Any</option>
                                {bedroomOptions.map((num) => (
                                    <option key={num} value={num}>{num}</option>
                                ))}
                            </select>
                        </div>

                        {/* Bathrooms */}
                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-1">Bathrooms</label>
                            <select
                                value={filters.bathrooms || ''}
                                onChange={(e) => handleFilterChange('bathrooms', e.target.value ? Number(e.target.value) : undefined)}
                                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                            >
                                <option value="">Any</option>
                                {bathroomOptions.map((num) => (
                                    <option key={num} value={num}>{num}</option>
                                ))}
                            </select>
                        </div>

                        {/* Toilets */}
                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-1">Toilets</label>
                            <select
                                value={filters.toilets || ''}
                                onChange={(e) => handleFilterChange('toilets', e.target.value ? Number(e.target.value) : undefined)}
                                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                            >
                                <option value="">Any</option>
                                {toiletOptions.map((num) => (
                                    <option key={num} value={num}>{num}</option>
                                ))}
                            </select>
                        </div>
                        {/* Price Range */}
                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-1">Price Range (₦/year)</label>
                            <div className="flex space-x-2">
                                <input
                                    type="number"
                                    value={filters.min_price || ''}
                                    onChange={(e) => handleFilterChange('min_price', e.target.value ? Number(e.target.value) : undefined)}
                                    placeholder="Min"
                                    className="w-1/2 px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                                />
                                <input
                                    type="number"
                                    value={filters.max_price || ''}
                                    onChange={(e) => handleFilterChange('max_price', e.target.value ? Number(e.target.value) : undefined)}
                                    placeholder="Max"
                                    className="w-1/2 px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                                />
                            </div>
                        </div>

                        {/* Amenities */}
                        <div className="flex items-center space-x-4 lg:col-span-2">
                            <label className="flex items-center">
                                <input
                                    type="checkbox"
                                    checked={filters.pet_friendly || false}
                                    onChange={(e) => handleFilterChange('pet_friendly', e.target.checked)}
                                    className="mr-2 h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
                                />
                                <span className="text-sm text-gray-700">Pet Friendly</span>
                            </label>
                            <label className="flex items-center">
                                <input
                                    type="checkbox"
                                    checked={filters.furnished || false}
                                    onChange={(e) => handleFilterChange('furnished', e.target.checked)}
                                    className="mr-2 h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
                                />
                                <span className="text-sm text-gray-700">Furnished</span>
                            </label>
                            <label className="flex items-center">
                                <input
                                    type="checkbox"
                                    checked={filters.utilities_included || false}
                                    onChange={(e) => handleFilterChange('utilities_included', e.target.checked)}
                                    className="mr-2 h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
                                />
                                <span className="text-sm text-gray-700">Utilities Included</span>
                            </label>
                        </div>

                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-1">Radius</label>
                            <select
                                value={filters.radius_km || ''}
                                onChange={(e) => handleFilterChange('radius_km', e.target.value ? Number(e.target.value) : undefined)}
                                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                            >
                                <option value="">Any distance</option>
                                {radiusOptions.map((radius) => (
                                    <option key={radius} value={radius}>{radius} km</option>
                                ))}
                            </select>
                        </div>

                        <div className="flex flex-col justify-end gap-2">
                            <div className="flex gap-2">
                                <button
                                    type="button"
                                    onClick={handleUseCurrentLocation}
                                    className="flex-1 px-3 py-2 text-sm font-medium text-blue-700 border border-blue-200 rounded-md hover:bg-blue-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
                                >
                                    Use my location
                                </button>
                                {filters.latitude !== undefined && filters.longitude !== undefined ? (
                                    <button
                                        type="button"
                                        onClick={handleClearLocation}
                                        className="px-3 py-2 text-sm font-medium text-gray-600 border border-gray-300 rounded-md hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
                                    >
                                        Clear
                                    </button>
                                ) : null}
                            </div>
                            {locationStatus ? <p className="text-xs text-gray-600">{locationStatus}</p> : null}
                        </div>
                    </div>

                    <div className="flex justify-between items-center mt-6">
                        <button
                            type="button"
                            onClick={clearFilters}
                            className="px-4 py-2 text-gray-600 border border-gray-300 rounded-md hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
                        >
                            Clear Filters
                        </button>
                        <button
                            type="submit"
                            className="px-6 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
                        >
                            Search
                        </button>
                    </div>
                </form>

                {locationAnalytics ? (
                    <section className="bg-white rounded-lg shadow-md p-6 mb-8">
                        <div className="mb-4 flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
                            <div>
                                <h2 className="text-xl font-semibold text-gray-900">Location Analytics</h2>
                                <p className="text-sm text-gray-500">{locationAnalytics.total_listings} available listing{locationAnalytics.total_listings === 1 ? '' : 's'} analysed</p>
                            </div>
                        </div>
                        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                            <AnalyticsColumn title="States" items={locationAnalytics.states} />
                            <AnalyticsColumn title="Cities" items={locationAnalytics.cities} />
                            <AnalyticsColumn title="Neighbourhoods" items={locationAnalytics.neighbourhoods} />
                        </div>
                    </section>
                ) : null}

                {/* Results */}
                <div className="mb-6">
                    <div className="flex justify-between items-center">
                        <h2 className="text-xl font-semibold text-gray-900">
                            {loading ? 'Searching...' : `${listings.length} Properties Found`}
                        </h2>
                    </div>
                    {/* Debug info */}
                    {/*<div className="mt-2 text-sm text-gray-600">
                        <p>Search filters: {JSON.stringify(filters)}</p>
                        <p>Available cities: {availableCities.join(', ')}</p>
                    </div>*/}
                </div>

                {/* Listings Grid */}
                {loading ? (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                        {Array.from({ length: 6 }).map((_, i) => (
                            <div key={i} className="bg-white rounded-lg shadow-md overflow-hidden animate-pulse">
                                <div className="h-48 bg-gray-200"></div>
                                <div className="p-4">
                                    <div className="h-4 bg-gray-200 rounded mb-2"></div>
                                    <div className="h-3 bg-gray-200 rounded mb-2"></div>
                                    <div className="h-4 bg-gray-200 rounded w-1/2"></div>
                                </div>
                            </div>
                        ))}
                    </div>
                ) : listings.length > 0 ? (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                        {listings.map((listing) => (
                            <ListingCard
                                key={listing.id}
                                listing={listing}
                                isFavourite={isFavourite(listing.id)}
                            />
                        ))}
                    </div>
                ) : (
                    <div className="text-center py-12">
                        <div className="text-gray-400 mb-4">
                            <svg className="mx-auto h-12 w-12" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                            </svg>
                        </div>
                        <h3 className="text-lg font-medium text-gray-900 mb-2">No properties found</h3>
                        <p className="text-gray-500">Try adjusting your search criteria or browse all available properties.</p>
                    </div>
                )}
            </div>
        </div>
    )
}
