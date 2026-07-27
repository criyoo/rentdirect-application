import { FormEvent, SyntheticEvent, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { HiLockClosed, HiPaperAirplane, HiUserGroup } from 'react-icons/hi'

import { useAuth } from '@/hooks/useAuth'
import { api, getWebSocketUrl, resolveMediaUrl } from '@/lib/api'
import { hasCommunityChatAccess, SubscriptionPaymentRecord } from '@/lib/subscriptions'

type PaginatedResponse<T> = { results?: T[] }

type CommunityChatMessage = {
    id: string
    sender_id: string
    sender_name: string
    sender_photo_url?: string | null
    content: string
    created_at: string
}

function normalizeResults<T>(payload: T[] | PaginatedResponse<T> | undefined): T[] {
    if (!payload) return []
    if (Array.isArray(payload)) return payload
    return Array.isArray(payload.results) ? payload.results : []
}

function mergeMessages(current: CommunityChatMessage[], nextMessage: CommunityChatMessage) {
    if (current.some((message) => message.id === nextMessage.id)) {
        return current
    }
    return [...current, nextMessage].sort((left, right) => new Date(left.created_at).getTime() - new Date(right.created_at).getTime())
}

function handleAvatarError(event: SyntheticEvent<HTMLImageElement>) {
    const image = event.currentTarget
    if (!image.src.endsWith('/placeholder.jpg')) {
        image.src = '/placeholder.jpg'
    }
}

export default function CommunityChatPage() {
    const { user } = useAuth()
    const [messages, setMessages] = useState<CommunityChatMessage[]>([])
    const [draft, setDraft] = useState('')
    const [connectionStatus, setConnectionStatus] = useState<'connecting' | 'connected' | 'closed'>('connecting')
    const socketRef = useRef<WebSocket | null>(null)
    const bottomRef = useRef<HTMLDivElement | null>(null)
    const dashboardRole = user?.role === 'landlord' ? 'landlord' : 'tenant'
    const dashboardPath = user?.id ? `/dashboard/${dashboardRole}/${user.id}` : '/'
    const roomLabel = dashboardRole === 'landlord' ? 'Landlord community' : 'Tenant community'
    const memberLabel = dashboardRole === 'landlord' ? 'Registered landlords' : 'Registered tenants'

    const { data: subscriptionPaymentResponse, isLoading: isSubscriptionsLoading } = useQuery({
        queryKey: ['subscription-payments', 'community-chat'],
        queryFn: async () => (await api.get<SubscriptionPaymentRecord[] | PaginatedResponse<SubscriptionPaymentRecord>>('/subscriptions')).data,
        enabled: Boolean(user),
    })
    const hasGoldSubscription = useMemo(() => hasCommunityChatAccess(subscriptionPaymentResponse), [subscriptionPaymentResponse])

    const { data: history } = useQuery({
        queryKey: ['community-chat', dashboardRole, 'messages'],
        queryFn: async () => normalizeResults((await api.get<CommunityChatMessage[] | PaginatedResponse<CommunityChatMessage>>('/community-chat/messages', {
            params: { limit: 100 },
        })).data),
        enabled: Boolean(user && hasGoldSubscription),
    })

    useEffect(() => {
        if (!history) return
        setMessages([...history].reverse())
    }, [history])

    useEffect(() => {
        if (!hasGoldSubscription) {
            setMessages([])
            setConnectionStatus('closed')
        }
    }, [hasGoldSubscription])

    useEffect(() => {
        if (!user || !hasGoldSubscription) return
        const socket = new WebSocket(getWebSocketUrl('/ws/community-chat'))
        socketRef.current = socket
        setConnectionStatus('connecting')

        socket.onopen = () => setConnectionStatus('connected')
        socket.onclose = () => setConnectionStatus('closed')
        socket.onerror = () => setConnectionStatus('closed')
        socket.onmessage = (event) => {
            try {
                const nextMessage = JSON.parse(event.data) as CommunityChatMessage
                setMessages((current) => mergeMessages(current, nextMessage))
            } catch {
                return
            }
        }

        return () => {
            socket.close()
            socketRef.current = null
        }
    }, [user, hasGoldSubscription])

    useEffect(() => {
        bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }, [messages.length])

    const canSend = useMemo(() => connectionStatus === 'connected' && draft.trim().length > 0, [connectionStatus, draft])

    const sendMessage = (event: FormEvent) => {
        event.preventDefault()
        const content = draft.trim()
        if (!content || socketRef.current?.readyState !== WebSocket.OPEN) return
        socketRef.current.send(JSON.stringify({ content }))
        setDraft('')
    }

    return (
        <div className="w-full px-4 py-8 sm:px-6 lg:px-8">
            <div className="mx-auto w-full max-w-[800px]">
                <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
                    <div>
                        <p className="text-sm font-medium uppercase tracking-[0.2em] text-purple-600">Community Chat</p>
                        <h1 className="text-3xl font-bold text-gray-900">{roomLabel}</h1>
                    </div>
                    <Link to={dashboardPath} className="btn btn-outline">
                        Back to Dashboard
                    </Link>
                </div>

                {isSubscriptionsLoading ? (
                    <div className="card mt-6 p-8 text-center text-sm text-gray-600">
                        Checking subscription...
                    </div>
                ) : !hasGoldSubscription ? (
                    <div className="card mt-6 p-8 text-center">
                        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-amber-100">
                            <HiLockClosed className="h-6 w-6 text-amber-700" />
                        </div>
                        <h2 className="mt-4 text-xl font-semibold text-gray-900">Gold or Platinum subscription required</h2>
                        <p className="mx-auto mt-2 max-w-xl text-sm text-gray-600">
                            {roomLabel} chat is available only to active Gold or Platinum subscription accounts.
                        </p>
                        <div className="mt-6">
                            <Link to="/billing" className="btn btn-primary">
                                Choose Gold Plan
                            </Link>
                        </div>
                    </div>
                ) : (
                    <div className="card mt-6 overflow-hidden">
                        <div className="flex items-center justify-between border-b border-gray-200 bg-gray-50 px-5 py-4">
                            <div className="flex items-center gap-3">
                                <div className="flex h-10 w-10 items-center justify-center rounded-full bg-purple-100">
                                    <HiUserGroup className="h-5 w-5 text-purple-700" />
                                </div>
                                <div>
                                    <h2 className="text-base font-semibold text-gray-900">{memberLabel}</h2>
                                    <p className="text-xs capitalize text-gray-500">{connectionStatus}</p>
                                </div>
                            </div>
                        </div>

                        <div className="h-[55vh] min-h-[420px] overflow-y-auto bg-white px-4 py-6">
                            {messages.length > 0 ? (
                                <div className="space-y-5">
                                    {messages.map((message) => {
                                        const isSender = message.sender_id === user?.id
                                        return (
                                            <div key={message.id} className={`flex items-end gap-3 ${isSender ? 'justify-end' : 'justify-start'}`}>
                                                {!isSender && (
                                                    <img
                                                        src={resolveMediaUrl(message.sender_photo_url)}
                                                        alt={message.sender_name}
                                                        loading="lazy"
                                                        decoding="async"
                                                        className="h-9 w-9 rounded-full object-cover"
                                                        onError={handleAvatarError}
                                                    />
                                                )}
                                                <div className={`max-w-[86%] rounded-2xl px-4 py-3 md:max-w-[82%] ${isSender ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-900'}`}>
                                                    <div className={`mb-1 text-xs font-semibold ${isSender ? 'text-blue-100' : 'text-gray-500'}`}>
                                                        {isSender ? 'You' : message.sender_name}
                                                    </div>
                                                    <p className="whitespace-pre-wrap break-words text-sm">{message.content}</p>
                                                </div>
                                                {isSender && (
                                                    <img
                                                        src={resolveMediaUrl(message.sender_photo_url || user?.profile_photo_url)}
                                                        alt={message.sender_name}
                                                        loading="lazy"
                                                        decoding="async"
                                                        className="h-9 w-9 rounded-full object-cover"
                                                        onError={handleAvatarError}
                                                    />
                                                )}
                                            </div>
                                        )
                                    })}
                                    <div ref={bottomRef} />
                                </div>
                            ) : (
                                <div className="flex h-full items-center justify-center text-center text-sm text-gray-500">
                                    No messages yet.
                                </div>
                            )}
                        </div>

                        <form onSubmit={sendMessage} className="flex items-end gap-3 border-t border-gray-200 bg-gray-50 p-4">
                            <textarea
                                className="form-input min-h-12 flex-1 resize-none"
                                value={draft}
                                onChange={(event) => setDraft(event.target.value)}
                                placeholder="Type a message"
                                maxLength={2000}
                            />
                            <button type="submit" className="btn btn-primary flex h-12 items-center gap-2 px-5" disabled={!canSend}>
                                <HiPaperAirplane className="h-5 w-5" />
                                Send
                            </button>
                        </form>
                    </div>
                )}
            </div>
        </div>
    )
}
