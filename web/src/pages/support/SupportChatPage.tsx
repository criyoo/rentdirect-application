import { FormEvent, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { HiPaperAirplane, HiSupport } from 'react-icons/hi'

import { useAuth } from '@/hooks/useAuth'
import { api, getWebSocketUrl, resolveMediaUrl } from '@/lib/api'

type PaginatedResponse<T> = { results?: T[] }

type SupportChatMessage = {
    id: string
    thread_user_id: string
    sender_id: string
    sender_name: string
    sender_role: string
    sender_photo_url?: string | null
    is_support_message: boolean
    content: string
    created_at: string
}

function normalizeResults<T>(payload: T[] | PaginatedResponse<T> | undefined): T[] {
    if (!payload) return []
    if (Array.isArray(payload)) return payload
    return Array.isArray(payload.results) ? payload.results : []
}

function mergeMessages(current: SupportChatMessage[], nextMessage: SupportChatMessage) {
    if (current.some((message) => message.id === nextMessage.id)) {
        return current
    }
    return [...current, nextMessage].sort((left, right) => new Date(left.created_at).getTime() - new Date(right.created_at).getTime())
}

export default function SupportChatPage() {
    const { user } = useAuth()
    const [messages, setMessages] = useState<SupportChatMessage[]>([])
    const [draft, setDraft] = useState('')
    const [connectionStatus, setConnectionStatus] = useState<'connecting' | 'connected' | 'closed'>('connecting')
    const socketRef = useRef<WebSocket | null>(null)
    const bottomRef = useRef<HTMLDivElement | null>(null)
    const dashboardRole = user?.role === 'landlord' ? 'landlord' : 'tenant'
    const dashboardPath = user?.id ? `/dashboard/${dashboardRole}/${user.id}` : '/'

    const { data: history } = useQuery({
        queryKey: ['support-chat', 'messages'],
        queryFn: async () => normalizeResults((await api.get<SupportChatMessage[] | PaginatedResponse<SupportChatMessage>>('/support-chat/messages', {
            params: { limit: 100 },
        })).data),
        enabled: Boolean(user),
    })

    useEffect(() => {
        if (!history) return
        setMessages([...history].reverse())
    }, [history])

    useEffect(() => {
        if (!user) return
        const socket = new WebSocket(getWebSocketUrl('/ws/support-chat'))
        socketRef.current = socket
        setConnectionStatus('connecting')

        socket.onopen = () => setConnectionStatus('connected')
        socket.onclose = () => setConnectionStatus('closed')
        socket.onerror = () => setConnectionStatus('closed')
        socket.onmessage = (event) => {
            try {
                const nextMessage = JSON.parse(event.data) as SupportChatMessage
                setMessages((current) => mergeMessages(current, nextMessage))
            } catch {
                return
            }
        }

        return () => {
            socket.close()
            socketRef.current = null
        }
    }, [user])

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
        <div className="container-modern py-8">
            <div className="mx-auto max-w-5xl">
                <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
                    <div>
                        <p className="text-sm font-medium uppercase tracking-[0.2em] text-blue-600">Support Chat</p>
                        <h1 className="text-3xl font-bold text-gray-900">RentDirect support team</h1>
                    </div>
                    <Link to={dashboardPath} className="btn btn-outline">
                        Back to Dashboard
                    </Link>
                </div>

                <div className="card mt-6 overflow-hidden">
                    <div className="flex items-center justify-between border-b border-gray-200 bg-gray-50 px-5 py-4">
                        <div className="flex items-center gap-3">
                            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-blue-100">
                                <HiSupport className="h-5 w-5 text-blue-700" />
                            </div>
                            <div>
                                <h2 className="text-base font-semibold text-gray-900">Support team</h2>
                                <p className="text-xs capitalize text-gray-500">{connectionStatus}</p>
                            </div>
                        </div>
                    </div>

                    <div className="h-[60vh] min-h-[420px] overflow-y-auto bg-white px-4 py-6">
                        {messages.length > 0 ? (
                            <div className="space-y-5">
                                {messages.map((message) => {
                                    const isSender = message.sender_id === user?.id
                                    return (
                                        <div key={message.id} className={`flex items-end gap-3 ${isSender ? 'justify-end' : 'justify-start'}`}>
                                            {!isSender && (
                                                <div className="flex h-9 w-9 items-center justify-center rounded-full bg-blue-100">
                                                    <HiSupport className="h-5 w-5 text-blue-700" />
                                                </div>
                                            )}
                                            <div className={`max-w-[78%] rounded-2xl px-4 py-3 ${isSender ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-900'}`}>
                                                <div className={`mb-1 text-xs font-semibold ${isSender ? 'text-blue-100' : 'text-gray-500'}`}>
                                                    {isSender ? 'You' : 'RentDirect Support'}
                                                </div>
                                                <p className="whitespace-pre-wrap break-words text-sm">{message.content}</p>
                                            </div>
                                            {isSender && (
                                                <img
                                                    src={resolveMediaUrl(message.sender_photo_url || user?.profile_photo_url)}
                                                    alt={message.sender_name}
                                                    className="h-9 w-9 rounded-full object-cover"
                                                />
                                            )}
                                        </div>
                                    )
                                })}
                                <div ref={bottomRef} />
                            </div>
                        ) : (
                            <div className="flex h-full items-center justify-center text-center text-sm text-gray-500">
                                No support messages yet.
                            </div>
                        )}
                    </div>

                    <form onSubmit={sendMessage} className="flex items-end gap-3 border-t border-gray-200 bg-gray-50 p-4">
                        <textarea
                            className="form-input min-h-12 flex-1 resize-none"
                            value={draft}
                            onChange={(event) => setDraft(event.target.value)}
                            placeholder="Type your message to support"
                            maxLength={2000}
                        />
                        <button type="submit" className="btn btn-primary flex h-12 items-center gap-2 px-5" disabled={!canSend}>
                            <HiPaperAirplane className="h-5 w-5" />
                            Send
                        </button>
                    </form>
                </div>
            </div>
        </div>
    )
}
