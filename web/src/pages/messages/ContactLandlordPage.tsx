import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { Listing, User } from '@/types'
import { useState, useEffect } from 'react'
import { useAuth } from '@/hooks/useAuth'
import { resolveMediaUrl } from '@/lib/api'
import { formatCurrencyWithSymbol } from '@/utils/currency'
import { hasBronzeAccess, SubscriptionPaymentRecord } from '@/lib/subscriptions'

interface Message {
    id: string
    sender_id: string
    receiver_id: string
    listing_id: string | null
    content: string
    created_at: string
}

type PublicTenantProfile = {
    id: string
    name: string
    profile_photo_url?: string | null
}

export default function ContactLandlordPage() {
    const { id } = useParams()
    const [searchParams] = useSearchParams()
    const { user } = useAuth()
    const navigate = useNavigate()
    const qc = useQueryClient()
    const [message, setMessage] = useState('')
    const [viewingAvailability, setViewingAvailability] = useState('')
    const [isTyping, setIsTyping] = useState(false)
    const tenantId = searchParams.get('tenantId') || ''
    const isLandlordChat = user?.role === 'landlord' && Boolean(tenantId)

    const { data: listing, isLoading: listingLoading } = useQuery({
        queryKey: ['listing', id],
        enabled: !!id,
        queryFn: async () => (await api.get<Listing>(`/listings/${id}`)).data
    })

    const { data: messages, isLoading: messagesLoading } = useQuery({
        queryKey: ['messages', 'listing', id, tenantId],
        enabled: !!id && !!user,
        queryFn: async () => (await api.get<Message[]>(`/messages/listing/${id}`, {
            params: isLandlordChat ? { counterpart_id: tenantId } : undefined,
        })).data
    })

    const { data: currentUser } = useQuery({
        queryKey: ['users', 'me'],
        enabled: !!user,
        queryFn: async () => (await api.get<User>('/users/me')).data,
    })

    const { data: landlordUser } = useQuery({
        queryKey: ['users', listing?.landlord_id],
        enabled: !!listing?.landlord_id,
        queryFn: async () => (await api.get<User>(`/users/${listing!.landlord_id}`)).data,
    })
    const { data: tenantUser } = useQuery({
        queryKey: ['tenant', 'public-profile', tenantId],
        enabled: isLandlordChat,
        queryFn: async () => (await api.get<PublicTenantProfile>(`/users/tenants/${tenantId}/public-profile`)).data,
    })
    const { data: subscriptionPaymentResponse } = useQuery({
        queryKey: ['subscription-payments', 'contact-landlord', user?.id],
        enabled: user?.role === 'tenant',
        queryFn: async () => (await api.get<SubscriptionPaymentRecord[] | { results?: SubscriptionPaymentRecord[] }>('/subscriptions')).data,
    })
    const isBronzeTenant = user?.role === 'tenant' && subscriptionPaymentResponse !== undefined && hasBronzeAccess(subscriptionPaymentResponse)

    const containsContactInfo = (text: string) => {
        const t = (text || '').toLowerCase()
        if (!t) return false
        if (/[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}/.test(t)) return true
        if (/@[a-z0-9_.]{2,}/.test(t)) return true
        if (/(wa\.me\/|t\.me\/|telegram|whatsapp|instagram|ig\b|facebook|fb\b|snapchat|tiktok|twitter|x\.com|linkedin)/.test(t)) return true
        const m = t.match(/(\+?\d[\d\s().-]{6,}\d)/)
        if (m) {
            const digits = m[1].replace(/\D/g, '')
            if (digits.length >= 8) return true
        }
        const tokens = t.match(/[a-z]+/g) || []
        const words = new Set(['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'oh', 'nil'])
        let run = 0
        for (const tok of tokens) {
            if (words.has(tok)) {
                run += 1
                if (run >= 8) return true
            } else {
                run = 0
            }
        }
        return false
    }

    const sendMessage = useMutation({
        mutationFn: async () => {
            const fullMessage = !isLandlordChat && viewingAvailability.trim()
                ? `Viewing Availability: ${viewingAvailability}\n\n${message}`
                : message
            await api.post('/messages', {
                receiver_id: isLandlordChat ? tenantId : listing!.landlord_id,
                listing_id: listing!.id,
                content: fullMessage
            })
        },
        onSuccess: () => {
            setMessage('')
            setViewingAvailability('')
            qc.invalidateQueries({ queryKey: ['messages', 'listing', id, tenantId] })
        },
        onError: (error) => {
            const detail = (error as any)?.response?.data?.detail
            alert(`Failed to send message: ${typeof detail === 'string' ? detail : error.message}`)
        }
    })

    const handleSendMessage = () => {
        if (!message.trim()) return
        if (isBronzeTenant) {
            alert('Contacting landlords is not available on the Bronze free plan.')
            navigate('/billing')
            return
        }
        if (isLandlordChat && !tenantId) return
        const fullMessage = !isLandlordChat && viewingAvailability.trim()
            ? `Viewing Availability: ${viewingAvailability}\n\n${message}`
            : message
        if (containsContactInfo(fullMessage)) {
            alert('Phone numbers, emails, and social media handles are not allowed. Please use chat only.')
            return
        }
        sendMessage.mutate()
    }

    const handleKeyPress = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            handleSendMessage()
        }
    }

    if (listingLoading) {
        return (
            <div className="min-h-screen bg-gray-50 flex items-center justify-center">
                <div className="animate-pulse text-gray-500">Loading...</div>
            </div>
        )
    }

    if (!listing) {
        return (
            <div className="min-h-screen bg-gray-50 flex items-center justify-center">
                <div className="text-gray-500">Listing not found.</div>
            </div>
        )
    }

    if (user?.role === 'tenant' && !user?.is_verified) {
        return (
            <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
                <div className="max-w-md w-full bg-white rounded-2xl shadow-lg border p-8 text-center">
                    <div className="w-16 h-16 bg-amber-100 rounded-full flex items-center justify-center mx-auto mb-4">
                        <svg className="w-8 h-8 text-amber-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                        </svg>
                    </div>
                    <h2 className="text-xl font-bold text-gray-900 mb-2">Verification Required</h2>
                    <p className="text-gray-600 mb-6">Your NIN must be verified before you can contact landlords. Please complete your verification to continue.</p>
                    <button
                        onClick={() => navigate('/dashboard/tenant/' + user.id)}
                        className="w-full rounded-lg bg-blue-600 px-4 py-3 font-medium text-white hover:bg-blue-700 transition"
                    >
                        Go to Dashboard to Verify
                    </button>
                    <button
                        onClick={() => navigate(`/listings/${listing.id}`)}
                        className="mt-3 w-full rounded-lg bg-gray-100 px-4 py-3 font-medium text-gray-700 hover:bg-gray-200 transition"
                    >
                        Back to Listing
                    </button>
                </div>
            </div>
        )
    }

    if (isBronzeTenant) {
        return (
            <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
                <div className="max-w-md w-full bg-white rounded-2xl shadow-lg border p-8 text-center">
                    <div className="w-16 h-16 bg-blue-100 rounded-full flex items-center justify-center mx-auto mb-4">
                        <svg className="w-8 h-8 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v8m4-4H8" />
                        </svg>
                    </div>
                    <h2 className="text-xl font-bold text-gray-900 mb-2">Upgrade Required</h2>
                    <p className="text-gray-600 mb-6">Contacting landlords and arranging viewings are not available on the Bronze free plan.</p>
                    <button
                        onClick={() => navigate('/billing')}
                        className="w-full rounded-lg bg-blue-600 px-4 py-3 font-medium text-white hover:bg-blue-700 transition"
                    >
                        View Subscription Plans
                    </button>
                    <button
                        onClick={() => navigate(`/listings/${listing.id}`)}
                        className="mt-3 w-full rounded-lg bg-gray-100 px-4 py-3 font-medium text-gray-700 hover:bg-gray-200 transition"
                    >
                        Back to Listing
                    </button>
                </div>
            </div>
        )
    }

    const landlordDisplayName = landlordUser?.name || listing.landlord_name || 'Landlord'
    const landlordFirstName = landlordDisplayName.split(/\s+/)[0] || 'Landlord'
    const landlordPhotoUrl = landlordUser?.profile_photo_url || listing.landlord_profile_photo_url
    const counterpartName = isLandlordChat ? tenantUser?.name || 'Tenant' : landlordDisplayName
    const counterpartPhotoUrl = isLandlordChat ? tenantUser?.profile_photo_url : landlordPhotoUrl
    const counterpartFirstName = counterpartName.split(/\s+/)[0] || (isLandlordChat ? 'Tenant' : 'Landlord')
    const sidebarName = isLandlordChat ? counterpartFirstName : landlordFirstName
    const sidebarPhotoUrl = isLandlordChat ? counterpartPhotoUrl : landlordPhotoUrl

    return (
        <div className="min-h-screen bg-gray-50">
            {/* Header */}
            <div className="bg-white border-b border-gray-200">
                <div className="max-w-4xl mx-auto px-4 py-6">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center space-x-4">
                            <button
                                onClick={() => navigate(`/listings/${listing.id}`)}
                                className="p-2 rounded-full hover:bg-gray-100 transition-colors"
                            >
                                <svg className="w-6 h-6 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                                </svg>
                            </button>
                            <div>
                                <h1 className="text-2xl font-bold text-gray-900">{isLandlordChat ? `Chat with ${counterpartFirstName}` : 'Contact Landlord'}</h1>
                                <p className="text-gray-600">{isLandlordChat ? 'Continue the tenant conversation about this property' : 'Send a message about this property'}</p>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div className="max-w-6xl mx-auto px-4 py-8">
                <div className="grid grid-cols-1 lg:grid-cols-4 gap-4 h-[700px]">
                    {/* Property Details Sidebar */}
                    <div className="lg:col-span-1 h-full">
                        <div className="bg-white rounded-2xl shadow-sm border p-5 h-full overflow-y-auto">
                            <div className="mb-4 flex flex-col items-center text-center">
                                <img
                                    src={resolveMediaUrl(sidebarPhotoUrl)}
                                    alt={sidebarName}
                                    loading="eager"
                                    decoding="async"
                                    className="h-16 w-16 rounded-full object-cover border border-gray-200"
                                    onError={(event) => {
                                        event.currentTarget.src = '/placeholder.jpg'
                                    }}
                                />
                                <p className="mt-2 text-sm font-semibold text-gray-900">
                                    {sidebarName}
                                </p>
                            </div>

                            <h2 className="text-lg font-semibold text-gray-900 mb-3">{listing.property_type} Details</h2>

                            <div className="space-y-3">
                                <button
                                    type="button"
                                    onClick={() => navigate(`/listings/${listing.id}`)}
                                    className="group block w-full overflow-hidden rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
                                    aria-label={`View details for ${listing.title}`}
                                >
                                    <img
                                        src={resolveMediaUrl(listing.cover_image_url)}
                                        alt={listing.title}
                                        loading="lazy"
                                        decoding="async"
                                        className="h-36 w-full object-cover transition-transform duration-200 group-hover:scale-105"
                                        onError={(e) => {
                                            e.currentTarget.src = '/placeholder.jpg'
                                        }}
                                    />
                                </button>

                                <div>
                                    <h3 className="font-bold text-gray-900 text-[20px]">{listing.title}</h3>
                                    <p className="text-gray-600 text-sm">
                                        {isBronzeTenant ? listing.state || 'State not provided' : listing.city}, {listing.state}<br />
                                        <p className="text-xs">Zip Code: {listing.postal_code}</p>
                                    </p>
                                    {/* {!isBronzeTenant && <p className="text-gray-600 text-sm">{listing.city}, {listing.postal_code}</p>} */}
                                </div>

                                <div className="flex items-center justify-between py-2 border-t border-gray-100">
                                    <span className="text-gray-600">Annual Rent:</span>
                                    <span className="font-semibold text-gray-900">
                                        {formatCurrencyWithSymbol(listing.price_per_year)}
                                    </span>
                                </div>

                                <div className="flex items-center justify-between py-2 border-t border-gray-100">
                                    <span className="text-gray-600">Property Type:</span>
                                    <span className="font-semibold text-gray-900">{listing.property_type}</span>
                                </div>

                                <div className="flex items-center justify-between py-2 border-t border-gray-100">
                                    <span className="text-gray-600">Bedrooms:</span>
                                    <span className="font-semibold text-gray-900">{listing.bedrooms}</span>
                                </div>

                                <div className="flex items-center justify-between py-2 border-t border-gray-100">
                                    <span className="text-gray-600">Bathrooms:</span>
                                    <span className="font-semibold text-gray-900">{listing.bathrooms}</span>
                                </div>
                            </div>

                            <div className="mt-6 p-4 bg-blue-50 rounded-lg">
                                <h4 className="font-bold text-blue-900 mb-2 text-[16px]">💡 Message Tips</h4>
                                <ul className="text-sm text-blue-800 space-y-1">
                                    <li>• Introduce yourself</li>
                                    <li>• Mention move-in timeline</li>
                                    <li>• Confirm viewing</li>
                                    <li>• Include requirements</li>
                                </ul>
                            </div>
                        </div>
                    </div>

                    {/* Messages Area */}
                    <div className="lg:col-span-3 h-full">
                        <div className="bg-white rounded-2xl shadow-sm border h-full flex flex-col">
                            {/* Messages Header */}
                            <div className="p-6 border-b border-gray-200">
                                <div className="flex items-center justify-between">
                                    <div>
                                        <h3 className="text-lg font-semibold text-gray-900">Messages</h3>
                                        <p className="text-sm text-gray-600">
                                            {messages?.length || 0} message{messages?.length !== 1 ? 's' : ''}
                                        </p>
                                    </div>
                                    <div className="flex items-center space-x-2">
                                        <div className="w-2 h-2 bg-green-500 rounded-full"></div>
                                        <span className="text-sm text-gray-600">Landlord online</span>
                                    </div>
                                </div>
                            </div>

                            {!isLandlordChat && (
                                <div className="p-6 text-center border-b border-gray-200">
                                    <div className="space-y-3">
                                        <label className="block text-sm font-medium text-gray-700">
                                            When are you available for viewings? <span className="text-gray-500">(max 50 characters)</span>
                                        </label>
                                        <textarea
                                            value={viewingAvailability}
                                            onChange={(e) => setViewingAvailability(e.target.value.slice(0, 50))}
                                            placeholder="e.g., Weekdays after 5pm, weekends anytime..."
                                            className="w-full max-w-xl px-4 py-2 border border-gray-300 rounded-xl resize-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                                            rows={1}
                                            maxLength={100}
                                            disabled={sendMessage.isPending}
                                        />
                                        <div className="flex justify-center text-xs text-gray-500">
                                            <span>This will be included in your message to the landlord</span>
                                            <span>{viewingAvailability.length}/50</span>
                                        </div>
                                    </div>
                                </div>
                            )}

                            {/* Messages List */}
                            <div className="flex-1 overflow-y-auto p-4 space-y-4 flex flex-col justify-end">
                                {messagesLoading ? (
                                    <div className="flex items-center justify-center h-full">
                                        <div className="animate-pulse text-gray-500">Loading messages...</div>
                                    </div>
                                ) : messages && messages.length > 0 ? (
                                    messages.map((msg) => (
                                        <div
                                            key={msg.id}
                                            className={`flex items-end gap-3 ${msg.sender_id === String(user?.id || '') ? 'justify-end' : 'justify-start'}`}
                                        >
                                            {msg.sender_id !== String(user?.id || '') && (
                                                <img
                                                    src={resolveMediaUrl(counterpartPhotoUrl)}
                                                    alt={counterpartFirstName}
                                                    loading="lazy"
                                                    decoding="async"
                                                    className="h-8 w-8 rounded-full object-cover"
                                                    onError={(event) => {
                                                        event.currentTarget.src = '/placeholder.jpg'
                                                    }}
                                                />
                                            )}
                                            <div
                                                className={`max-w-xs lg:max-w-lg xl:max-w-xl px-4 py-3 rounded-2xl ${msg.sender_id === String(user?.id || '')
                                                    ? 'bg-blue-600 text-white'
                                                    : 'bg-gray-100 text-gray-900'
                                                    }`}
                                            >
                                                <p className="text-sm whitespace-pre-wrap">{msg.content}</p>
                                                <p className={`text-xs mt-1 ${msg.sender_id === String(user?.id || '') ? 'text-blue-100' : 'text-gray-500'
                                                    }`}>
                                                    {new Date(msg.created_at).toLocaleTimeString([], {
                                                        hour: '2-digit',
                                                        minute: '2-digit'
                                                    })}
                                                </p>
                                            </div>
                                            {msg.sender_id === String(user?.id || '') && (
                                                <img
                                                    src={resolveMediaUrl(currentUser?.profile_photo_url)}
                                                    alt={currentUser?.name || 'You'}
                                                    loading="lazy"
                                                    decoding="async"
                                                    className="h-8 w-8 rounded-full object-cover"
                                                    onError={(event) => {
                                                        event.currentTarget.src = '/placeholder.jpg'
                                                    }}
                                                />
                                            )}
                                        </div>
                                    ))
                                ) : (
                                    <div className="text-center py-20">
                                        <div className="w-16 h-16 bg-gray-100 rounded-full flex items-center justify-center mx-auto mb-1">
                                            <svg className="w-8 h-8 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                                            </svg>
                                        </div>
                                        <h3 className="text-lg font-medium text-gray-600 mb-2">Start a conversation</h3>
                                        <p className="text-gray-500">Send your first message to the landlord.</p>
                                    </div>
                                )}
                            </div>

                            {/* Message Input */}
                            <div className="p-5 border-t border-gray-200">
                                <div className="flex space-x-4">
                                    <div className="flex-1">
                                        <textarea
                                            value={message}
                                            onChange={(e) => setMessage(e.target.value)}
                                            onKeyPress={handleKeyPress}
                                            placeholder="Type your message here..."
                                            className="w-full px-4 py-4 border border-gray-300 rounded-2xl resize-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                                            rows={3}
                                            disabled={sendMessage.isPending}
                                        />
                                    </div>
                                    <button
                                        onClick={handleSendMessage}
                                        disabled={sendMessage.isPending || !message.trim()}
                                        className="px-6 py-4 bg-blue-600 text-white rounded-2xl hover:bg-blue-700 disabled:opacity-90 disabled:cursor-not-allowed transition-colors flex items-center space-x-2"
                                    >
                                        {sendMessage.isPending ? (
                                            <>
                                                <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                                                <span>Sending...</span>
                                            </>
                                        ) : (
                                            <>
                                                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                                                </svg>
                                                <span>Send</span>
                                            </>
                                        )}
                                    </button>
                                </div>
                                <div className="font-semibold flex items-center justify-between mt-0.5 text-sm text-gray-900">
                                    <span>Press Enter to send, Shift + Enter for new line</span>
                                    <span>{message.length}/1000</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}
