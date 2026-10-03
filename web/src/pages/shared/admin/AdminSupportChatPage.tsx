import { FormEvent, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { HiArrowLeft, HiChatAlt2, HiPaperAirplane, HiSupport, HiUserCircle } from 'react-icons/hi'

import AdminLayout from '@/components/admin/AdminLayout'
import { api, getWebSocketUrl, resolveMediaUrl } from '@/lib/api'

type PaginatedResponse<T> = { results?: T[] }

type SupportThread = {
    thread_user_id: string
    thread_role: string
    user_name: string
    user_email: string
    user_photo_url?: string | null
    last_message: string
    last_message_at: string
    last_sender_role: string
    is_last_from_support: boolean
    message_count: number
}

type SupportChatMessage = {
    id: string
    thread_user_id: string
    sender_id: string
    sender_name: string
    sender_role: string
    thread_role?: string
    sender_photo_url?: string | null
    is_support_message: boolean
    content: string
    created_at: string
}

const ROLE_TABS = [
    { role: 'landlord', label: 'Landlord Support Chat' },
    { role: 'tenant', label: 'Tenant Support Chat' },
    { role: 'agent', label: 'PIO Support Chat' },
] as const

const ROLE_LABELS: Record<string, string> = {
    landlord: 'Landlord',
    tenant: 'Tenant',
    agent: 'PIO',
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

function formatThreadTime(value: string) {
    const date = new Date(value)
    const today = new Date()
    const isSameDay = date.toDateString() === today.toDateString()
    if (isSameDay) {
        return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    }
    return date.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

export default function AdminSupportChatPage() {
    const queryClient = useQueryClient()
    const [activeRole, setActiveRole] = useState<string>('landlord')
    const [selectedThread, setSelectedThread] = useState<SupportThread | null>(null)
    const [messages, setMessages] = useState<SupportChatMessage[]>([])
    const [draft, setDraft] = useState('')
    const [connectionStatus, setConnectionStatus] = useState<'connecting' | 'connected' | 'closed'>('connecting')
    const socketRef = useRef<WebSocket | null>(null)
    const bottomRef = useRef<HTMLDivElement | null>(null)

    const { data: threads } = useQuery({
        queryKey: ['admin', 'support-chat-threads', activeRole],
        queryFn: async () =>
            (await api.get<SupportThread[]>('/support-chat/messages/threads', {
                params: { thread_role: activeRole },
            })).data,
        refetchInterval: 15000,
    })

    const { data: history } = useQuery({
        queryKey: ['admin', 'support-chat-messages', selectedThread?.thread_user_id, selectedThread?.thread_role],
        queryFn: async () =>
            normalizeResults((await api.get<SupportChatMessage[] | PaginatedResponse<SupportChatMessage>>('/support-chat/messages', {
                params: {
                    user_id: selectedThread?.thread_user_id,
                    thread_role: selectedThread?.thread_role,
                    limit: 100,
                },
            })).data),
        enabled: Boolean(selectedThread),
    })

    useEffect(() => {
        if (!history) return
        setMessages([...history].reverse())
    }, [history])

    useEffect(() => {
        if (!selectedThread) return
        const socket = new WebSocket(getWebSocketUrl(`/ws/support-chat?user_id=${selectedThread.thread_user_id}&thread_role=${selectedThread.thread_role}`))
        socketRef.current = socket
        setConnectionStatus('connecting')

        socket.onopen = () => setConnectionStatus('connected')
        socket.onclose = () => setConnectionStatus('closed')
        socket.onerror = () => setConnectionStatus('closed')
        socket.onmessage = (event) => {
            try {
                const nextMessage = JSON.parse(event.data) as SupportChatMessage
                setMessages((current) => mergeMessages(current, nextMessage))
                void queryClient.invalidateQueries({ queryKey: ['admin', 'support-chat-threads'] })
            } catch {
                return
            }
        }

        return () => {
            socket.close()
            socketRef.current = null
        }
    }, [queryClient, selectedThread])

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

    const selectThread = (thread: SupportThread) => {
        setMessages([])
        setDraft('')
        setSelectedThread(thread)
    }

    const switchRole = (role: string) => {
        setActiveRole(role)
        setSelectedThread(null)
        setMessages([])
        setDraft('')
    }

    return (
        <AdminLayout>
            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
                <div className="mb-6">
                    <p className="text-sm font-medium uppercase tracking-[0.2em] text-purple-600">Support</p>
                    <h1 className="text-3xl font-bold text-gray-900">Support chats</h1>
                    <p className="mt-1 text-sm text-gray-500">
                        Reply to support messages from landlords, tenants and PIOs. Each conversation is private to that user.
                    </p>
                </div>

                <div className="mb-6 flex flex-wrap gap-2">
                    {ROLE_TABS.map((tab) => (
                        <button
                            key={tab.role}
                            type="button"
                            onClick={() => switchRole(tab.role)}
                            className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors ${activeRole === tab.role
                                ? 'bg-purple-600 text-white shadow-sm'
                                : 'bg-white text-gray-600 border border-gray-200 hover:bg-purple-50 hover:text-purple-700'
                                }`}
                        >
                            {tab.label}
                        </button>
                    ))}
                </div>

                <div className="grid gap-6 lg:grid-cols-[340px,1fr]">
                    <div className={`card overflow-hidden ${selectedThread ? 'hidden lg:block' : ''}`}>
                        <div className="border-b border-gray-200 bg-gray-50 px-5 py-4">
                            <h2 className="text-base font-semibold text-gray-900">Conversations</h2>
                        </div>
                        <div className="max-h-[65vh] divide-y divide-gray-100 overflow-y-auto">
                            {(threads || []).length > 0 ? (
                                (threads || []).map((thread) => (
                                    <button
                                        key={`${thread.thread_user_id}-${thread.thread_role}`}
                                        type="button"
                                        onClick={() => selectThread(thread)}
                                        className={`flex w-full items-start gap-3 px-4 py-4 text-left transition-colors hover:bg-purple-50 ${selectedThread?.thread_user_id === thread.thread_user_id && selectedThread?.thread_role === thread.thread_role
                                            ? 'bg-purple-50'
                                            : 'bg-white'
                                            }`}
                                    >
                                        {thread.user_photo_url ? (
                                            <img
                                                src={resolveMediaUrl(thread.user_photo_url)}
                                                alt={thread.user_name}
                                                loading="lazy"
                                                decoding="async"
                                                className="h-10 w-10 shrink-0 rounded-full object-cover"
                                            />
                                        ) : (
                                            <HiUserCircle className="h-10 w-10 shrink-0 text-gray-300" />
                                        )}
                                        <div className="min-w-0 flex-1">
                                            <div className="flex items-baseline justify-between gap-2">
                                                <p className="truncate text-sm font-semibold text-gray-900">{thread.user_name || thread.user_email}</p>
                                                <span className="shrink-0 text-xs text-gray-400">{formatThreadTime(thread.last_message_at)}</span>
                                            </div>
                                            <p className="mt-0.5 truncate text-xs text-gray-500">{thread.user_email}</p>
                                            <p className="mt-1 truncate text-sm text-gray-600">
                                                {thread.is_last_from_support ? 'You: ' : ''}{thread.last_message}
                                            </p>
                                        </div>
                                    </button>
                                ))
                            ) : (
                                <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
                                    <HiChatAlt2 className="h-10 w-10 text-gray-300" />
                                    <p className="mt-3 text-sm text-gray-500">No {ROLE_LABELS[activeRole]?.toLowerCase()} support conversations yet.</p>
                                </div>
                            )}
                        </div>
                    </div>

                    <div className={`card overflow-hidden ${selectedThread ? '' : 'hidden lg:block'}`}>
                        {selectedThread ? (
                            <>
                                <div className="flex items-center justify-between border-b border-gray-200 bg-gray-50 px-5 py-4">
                                    <div className="flex items-center gap-3">
                                        <button
                                            type="button"
                                            onClick={() => setSelectedThread(null)}
                                            className="rounded-lg p-2 text-gray-500 hover:bg-gray-200 lg:hidden"
                                            aria-label="Back to conversations"
                                        >
                                            <HiArrowLeft className="h-5 w-5" />
                                        </button>
                                        {selectedThread.user_photo_url ? (
                                            <img
                                                src={resolveMediaUrl(selectedThread.user_photo_url)}
                                                alt={selectedThread.user_name}
                                                className="h-10 w-10 rounded-full object-cover"
                                            />
                                        ) : (
                                            <HiUserCircle className="h-10 w-10 text-gray-300" />
                                        )}
                                        <div>
                                            <h2 className="text-base font-semibold text-gray-900">{selectedThread.user_name || selectedThread.user_email}</h2>
                                            <p className="text-xs text-gray-500">
                                                {ROLE_LABELS[selectedThread.thread_role] || selectedThread.thread_role} · {selectedThread.user_email} · {connectionStatus}
                                            </p>
                                        </div>
                                    </div>
                                </div>

                                <div className="h-[55vh] min-h-[380px] overflow-y-auto bg-white px-4 py-6">
                                    {messages.length > 0 ? (
                                        <div className="space-y-5">
                                            {messages.map((message) => (
                                                <div key={message.id} className={`flex items-end gap-3 ${message.is_support_message ? 'justify-end' : 'justify-start'}`}>
                                                    {!message.is_support_message && (
                                                        selectedThread.user_photo_url ? (
                                                            <img
                                                                src={resolveMediaUrl(selectedThread.user_photo_url)}
                                                                alt={selectedThread.user_name}
                                                                loading="lazy"
                                                                decoding="async"
                                                                className="h-9 w-9 rounded-full object-cover"
                                                            />
                                                        ) : (
                                                            <HiUserCircle className="h-9 w-9 text-gray-300" />
                                                        )
                                                    )}
                                                    <div className={`max-w-[78%] rounded-2xl px-4 py-3 ${message.is_support_message ? 'bg-purple-600 text-white' : 'bg-gray-100 text-gray-900'}`}>
                                                        <div className={`mb-1 text-xs font-semibold ${message.is_support_message ? 'text-purple-100' : 'text-gray-500'}`}>
                                                            {message.is_support_message ? (message.sender_name || 'Support') : (message.sender_name || 'User')}
                                                        </div>
                                                        <p className="whitespace-pre-wrap break-words text-sm">{message.content}</p>
                                                    </div>
                                                    {message.is_support_message && (
                                                        <div className="flex h-9 w-9 items-center justify-center rounded-full bg-purple-100">
                                                            <HiSupport className="h-5 w-5 text-purple-700" />
                                                        </div>
                                                    )}
                                                </div>
                                            ))}
                                            <div ref={bottomRef} />
                                        </div>
                                    ) : (
                                        <div className="flex h-full items-center justify-center text-center text-sm text-gray-500">
                                            No messages in this conversation yet.
                                        </div>
                                    )}
                                </div>

                                <form onSubmit={sendMessage} className="flex items-end gap-3 border-t border-gray-200 bg-gray-50 p-4">
                                    <textarea
                                        className="form-input min-h-12 flex-1 resize-none"
                                        value={draft}
                                        onChange={(event) => setDraft(event.target.value)}
                                        placeholder="Type your reply to the user"
                                        maxLength={2000}
                                    />
                                    <button type="submit" className="btn btn-primary flex h-12 items-center gap-2 px-5" disabled={!canSend}>
                                        <HiPaperAirplane className="h-5 w-5" />
                                        Send
                                    </button>
                                </form>
                            </>
                        ) : (
                            <div className="flex h-[65vh] flex-col items-center justify-center px-6 text-center">
                                <HiChatAlt2 className="h-12 w-12 text-gray-300" />
                                <p className="mt-3 text-sm text-gray-500">Select a conversation to view messages and reply.</p>
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </AdminLayout>
    )
}
