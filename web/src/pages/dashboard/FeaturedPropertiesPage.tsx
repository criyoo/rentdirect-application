import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Link } from 'react-router-dom'
import { getApiUrl, resolveMediaUrl } from '@/lib/api'
import { useAppPopup } from '@/contexts/AppPopupContext'
import DashboardBackButton from '@/components/DashboardBackButton'
import { formatCurrencyWithSymbol } from '@/utils/currency'

interface FeaturedPayment
{
    id: string
    listing_id: string
    amount: number | string
    currency: string
    status: 'pending' | 'completed' | 'failed' | 'cancelled'
    payment_date?: string
    expires_at?: string
    created_at: string
    featured_duration_days?: number
}

interface Listing
{
    id: string
    title: string
    city: string
    price_per_year: number | string
    cover_image_url?: string
    featured: boolean
}

const PRICING = {
    30: 5000,   // ₦5,000 for 30 days
    60: 9500,   // ₦9,500 for 60 days
    90: 13500   // ₦13,500 for 90 days
}

export default function FeaturedPropertiesPage()
{
    const navigate = useNavigate()
    const { confirm } = useAppPopup()
    const [listings, setListings] = useState<Listing[]>([])
    const [featuredPayments, setFeaturedPayments] = useState<FeaturedPayment[]>([])
    const [loading, setLoading] = useState(true)
    const [selectedListing, setSelectedListing] = useState<string | null>(null)
    const [featuredDuration, setFeaturedDuration] = useState(30)
    const [currentUserId, setCurrentUserId] = useState<string | null>(null)

    useEffect(() =>
    {
        const init = async () =>
        {
            try
            {
                const meRes = await fetch(`${getApiUrl()}/users/me`, { credentials: 'include' })
                if (meRes.ok)
                {
                    const me = await meRes.json()
                    setCurrentUserId(me.id)
                    await fetchListings(me.id)
                }
            } finally
            {
                await fetchFeaturedPayments()
            }
        }
        init()
    }, [])

    const fetchListings = async (landlordId: string) =>
    {
        try
        {
            const response = await fetch(`${getApiUrl()}/dashboard/landlord/${landlordId}/listings`, {
                credentials: 'include',
            })
            if (response.ok)
            {
                const data = await response.json()
                setListings(data)
            }
        } catch (error)
        {
            console.error('Error fetching listings:', error)
        }
    }

    const fetchFeaturedPayments = async () =>
    {
        try
        {
            // This would be a new endpoint to get featured payments for the current user
            const response = await fetch(`${getApiUrl()}/featured/payments`, {
                credentials: 'include',
            })
            if (response.ok)
            {
                const data = await response.json()
                setFeaturedPayments(data)
            }
        } catch (error)
        {
            console.error('Error fetching featured payments:', error)
        } finally
        {
            setLoading(false)
        }
    }

    const requestFeaturedStatus = async (listingId: string) =>
    {
        try
        {
            const response = await fetch(`${getApiUrl()}/featured/request`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                credentials: 'include',
                body: JSON.stringify({
                    listing_id: listingId,
                    featured_duration_days: featuredDuration
                })
            })

            if (response.ok)
            {
                const payment = await response.json()
                 alert(`Featured property request created! Payment required: ${formatCurrencyWithSymbol(payment.amount)}`)
                fetchFeaturedPayments()
            } else
            {
                const error = await response.json()
                alert(`Error: ${error.detail}`)
            }
        } catch (error)
        {
            console.error('Error requesting featured status:', error)
            alert('Error requesting featured status')
        }
    }

    const processPayment = async (paymentId: string) =>
    {
        navigate(`/dashboard/featured-properties/pay/${paymentId}`)
    }

    const unfeatureProperty = async (listingId: string) =>
    {
        if (!(await confirm('Are you sure you want to remove featured status from this property?')))
        {
            return
        }

        try
        {
            const response = await fetch(`${getApiUrl()}/featured/${listingId}/unfeature`, {
                method: 'DELETE',
                credentials: 'include',
            })

            if (response.ok)
            {
                alert('Property unfeatured successfully')
                if (currentUserId)
                {
                    fetchListings(currentUserId)
                }
                fetchFeaturedPayments()
            } else
            {
                const error = await response.json()
                alert(`Error: ${error.detail}`)
            }
        } catch (error)
        {
            console.error('Error unfeaturing property:', error)
            alert('Error unfeaturing property')
        }
    }

    const handleDurationChange = async (paymentId: string, duration: number) =>
    {
        try
        {
            const response = await fetch(`${getApiUrl()}/featured/payments/${paymentId}/update-duration`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                },
                credentials: 'include',
                body: JSON.stringify({ featured_duration_days: duration })
            });

            if (response.ok)
            {
                alert('Featured duration updated successfully');
                fetchFeaturedPayments();
            } else
            {
                const error = await response.json();
                alert(`Error updating duration: ${error.detail}`);
            }
        } catch (error)
        {
            console.error('Error updating duration:', error);
            alert('Error updating duration');
        }
    };

    if (loading)
    {
        return <div className="p-6">Loading...</div>
    }

    return (
        <div className="container-modern py-8">
            <div className="mb-5">
                <DashboardBackButton fallbackTo={currentUserId ? `/dashboard/landlord/${currentUserId}` : '/'} />
            </div>
            <div className="mb-6">
                <h1 className="text-3xl font-bold text-gray-900">My Featured Properties</h1>
                <p className="text-gray-600 mt-2">
                    View and manage your featured property listings. Featured properties appear at the top of search results and on the home page.
                </p>
            </div>

            {/* Featured Payments History */}
            <div className="bg-white rounded-lg shadow-md p-6">
                <h2 className="text-lg font-semibold text-gray-900 mb-4">Featured Property Payments</h2>

                {featuredPayments.length === 0 ? (
                    <p className="text-gray-500 text-center py-8">No featured property payments yet.</p>
                ) : (
                    <div className="overflow-x-auto">
                        <table className="min-w-full divide-y divide-gray-200">
                            <thead className="bg-gray-50">
                                <tr>
                                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                        Property
                                    </th>
                                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                        Duration
                                    </th>
                                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                        Amount
                                    </th>
                                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                        Status
                                    </th>
                                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                        Date
                                    </th>
                                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                        Actions
                                    </th>
                                </tr>
                            </thead>
                            <tbody className="bg-white divide-y divide-gray-200">
                                {featuredPayments.map((payment) => (
                                    <tr key={payment.id}>
                                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                                            Property #{payment.listing_id}
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                                            {payment.featured_duration_days || 30} days
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                                            <div className="flex items-center space-x-2">
                                                 <span className="font-medium">{formatCurrencyWithSymbol(payment.amount)}</span>
                                                {payment.status === 'pending' && (
                                                    <select
                                                        value={payment.featured_duration_days || 30}
                                                        onChange={(e) => handleDurationChange(payment.id, Number(e.target.value))}
                                                        className="text-xs border border-gray-300 rounded px-2 py-1 bg-white"
                                                    >
                                                        <option value={30}>30 days</option>
                                                        <option value={60}>60 days</option>
                                                        <option value={90}>90 days</option>
                                                    </select>
                                                )}
                                            </div>
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap">
                                            <span className={`inline-flex px-2 py-1 text-xs font-semibold rounded-full ${payment.status === 'completed' ? 'bg-green-100 text-green-800' :
                                                payment.status === 'pending' ? 'bg-yellow-100 text-yellow-800' :
                                                    payment.status === 'failed' ? 'bg-red-100 text-red-800' :
                                                        'bg-gray-100 text-gray-800'
                                                }`}>
                                                {payment.status}
                                            </span>
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                                            {new Date(payment.created_at).toLocaleDateString()}
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap text-sm font-medium">
                                            {payment.status === 'pending' && (
                                                <button
                                                    onClick={() => processPayment(payment.id)}
                                                    className="text-blue-600 hover:text-blue-900"
                                                >
                                                    Process Payment
                                                </button>
                                            )}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>

            {/* Current Featured Properties */}
            <div className="bg-white rounded-lg shadow-md p-6 mb-6">
                <h2 className="text-lg font-semibold text-gray-900 mb-4">Currently Featured Properties</h2>

                {listings.filter(listing => listing.featured).length === 0 ? (
                    <div className="text-center py-12">
                        <div className="w-16 h-16 bg-gray-100 rounded-full flex items-center justify-center mx-auto mb-4">
                            <svg className="w-8 h-8 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
                            </svg>
                        </div>
                        <h3 className="text-lg font-medium text-gray-900 mb-2">No featured properties yet</h3>
                        <p className="text-gray-600 mb-6 max-w-md mx-auto">
                            You haven't featured any properties yet. Featured properties get premium visibility and appear at the top of search results.
                        </p>

                        <div className="space-y-4">
                            <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 max-w-md mx-auto">
                                <h4 className="font-medium text-blue-900 mb-2">How to feature a property:</h4>
                                <ol className="text-sm text-blue-800 space-y-1 list-decimal list-inside">
                                    <li>Go to your property listing</li>
                                    <li>Click "Edit" or "Manage"</li>
                                    <li>Enable the "Featured Property" option</li>
                                    <li>Choose your featured duration (30, 60, or 90 days)</li>
                                    <li>Complete the payment to activate</li>
                                </ol>
                            </div>

                            <div className="flex flex-col sm:flex-row gap-3 justify-center">
                                <Link
                                    to="/listings/new"
                                    className="inline-flex items-center px-6 py-3 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 transition-colors"
                                >
                                    Create New Listing
                                </Link>
                                <Link
                                    to="/search"
                                    className="inline-flex items-center px-6 py-3 border border-gray-300 text-gray-700 font-medium rounded-lg hover:bg-gray-50 transition-colors"
                                >
                                    View All Featured Properties
                                </Link>
                            </div>
                        </div>
                    </div>
                ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                        {listings
                            .filter(listing => listing.featured)
                            .map(listing => (
                                <div key={listing.id} className="border rounded-lg p-4">
                                    {listing.cover_image_url && (
                                        <img
                                            src={resolveMediaUrl(listing.cover_image_url)}
                                            alt={listing.title}
                                            className="w-full h-32 object-cover rounded-lg mb-3"
                                        />
                                    )}
                                    <h5 className="font-semibold text-gray-700">{listing.title}</h5>
                                    <p className="text-gray-600 text-sm">{listing.city}</p>
                                     <p className="text-gray-900 font-medium">{formatCurrencyWithSymbol(Number(listing.price_per_year || 0))}/year</p>

                                    <div className="mt-3">
                                        <button
                                            onClick={() => unfeatureProperty(listing.id)}
                                            className="w-full px-3 py-2 bg-red-600 text-white text-sm rounded-md hover:bg-red-700 transition"
                                        >
                                            Remove Featured Status
                                        </button>
                                    </div>
                                </div>
                            ))
                        }
                    </div>
                )}
            </div>

            {/* Featured Property Request */}
            <div className="bg-white rounded-lg shadow-md p-6 mb-6">
                <h2 className="text-lg font-semibold text-gray-900 mb-4">Request Featured Status</h2>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">Select Property</label>
                        <select
                            value={selectedListing || ''}
                            onChange={(e) => setSelectedListing(e.target.value || null)}
                            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                        >
                            <option value="">Choose a property...</option>
                            {listings
                                .filter(listing => !listing.featured)
                                .map(listing => (
                                    <option key={listing.id} value={listing.id}>
                                        {listing.title} - {listing.city}
                                    </option>
                                ))
                            }
                        </select>
                    </div>

                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">Featured Duration</label>
                        <select
                            value={featuredDuration}
                            onChange={(e) => setFeaturedDuration(Number(e.target.value))}
                            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                        >
                            <option value={30}>30 days</option>
                            <option value={60}>60 days</option>
                            <option value={90}>90 days</option>
                        </select>
                    </div>

                    <div className="flex items-end">
                        <button
                            onClick={() => selectedListing && requestFeaturedStatus(selectedListing)}
                            disabled={!selectedListing}
                            className="w-full px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition"
                        >
                            Request Featured Status
                        </button>
                    </div>
                </div>

                <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                    <div className="flex items-start space-x-3">
                        <svg className="h-6 w-6 text-blue-600 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                        <div>
                            <h4 className="text-sm font-medium text-blue-900">Featured Property Benefits</h4>
                            <ul className="mt-2 text-sm text-blue-700 space-y-1">
                                <li>• Appears at the top of search results</li>
                                <li>• Featured on the home page</li>
                                <li>• Increased visibility to potential tenants</li>
                                <li>• Higher engagement and faster rentals</li>
                            </ul>
                        </div>
                    </div>
                </div>
            </div>



            <div className="mt-6 flex justify-center">
                <Link
                    to={currentUserId ? `/dashboard/landlord/${currentUserId}` : '/dashboard/landlord'}
                    className="px-6 py-3 bg-gray-600 text-white rounded-lg hover:bg-gray-700 transition-colors"
                >
                    Back to Dashboard
                </Link>
            </div>
        </div>
    )
}
