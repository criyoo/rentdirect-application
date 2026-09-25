import { useEffect, useRef, useState } from 'react'
import { extractApiErrorMessage, getApiUrl } from '@/lib/api'
import { Listing, SearchFilters } from '@/types'
import { HiOutlineSparkles, HiPaperAirplane } from 'react-icons/hi'

interface ChatMessage {
    role: 'user' | 'assistant'
    content: string
}

interface AiSearchChatProps {
    onListingsFound?: (listings: Listing[], filters: Partial<SearchFilters>, totalCount?: number) => void
}

export default function AiSearchChat({ onListingsFound }: AiSearchChatProps) {
    const [messages, setMessages] = useState<ChatMessage[]>([])
    const [input, setInput] = useState('')
    const [loading, setLoading] = useState(false)
    const [streaming, setStreaming] = useState(false)
    const [limitedMode, setLimitedMode] = useState(false)
    const scrollRef = useRef<HTMLDivElement>(null)
    const sessionIdRef = useRef<string | null>(null)

    useEffect(() => {
        const container = scrollRef.current
        if (container) container.scrollTop = container.scrollHeight
    }, [messages, loading])

    const patchAssistantMessage = (index: number, updater: (content: string) => string) => {
        setMessages((current) => {
            if (index >= current.length) return current
            const next = [...current]
            next[index] = { role: 'assistant', content: updater(next[index].content) }
            return next
        })
    }

    const sendMessage = async (text: string) => {
        const content = text.trim()
        if (!content || loading) return

        const history = [...messages, { role: 'user' as const, content }]
        const replyIndex = history.length
        setMessages([...history, { role: 'assistant', content: '' }])
        setInput('')
        setLoading(true)
        setStreaming(false)

        try {
            const response = await fetch(`${getApiUrl()}/chat/stream`, {
                method: 'POST',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: content,
                    session_id: sessionIdRef.current || undefined,
                }),
            })
            if (!response.ok || !response.body) {
                throw new Error(`Chat request failed (${response.status})`)
            }

            const reader = response.body.getReader()
            const decoder = new TextDecoder()
            let buffer = ''
            for (; ;) {
                const { done, value } = await reader.read()
                if (done) break
                buffer += decoder.decode(value, { stream: true })
                const chunks = buffer.split('\n\n')
                buffer = chunks.pop() || ''
                for (const chunk of chunks) {
                    const line = chunk.trim()
                    if (!line.startsWith('data:')) continue
                    let event: any
                    try {
                        event = JSON.parse(line.slice(5))
                    } catch {
                        continue
                    }
                    if (event.type === 'session' && event.session_id) {
                        sessionIdRef.current = event.session_id
                    } else if (event.type === 'segment') {
                        // A new streamed round replaces any earlier draft text.
                        patchAssistantMessage(replyIndex, () => '')
                    } else if (event.type === 'delta' && event.text) {
                        setStreaming(true)
                        patchAssistantMessage(replyIndex, (current) => current + event.text)
                    } else if (event.type === 'listings') {
                        onListingsFound?.(
                            Array.isArray(event.listings) ? event.listings : [],
                            event.filters || {},
                            event.total_count,
                        )
                    } else if (event.type === 'done') {
                        if (event.session_id) sessionIdRef.current = event.session_id
                        patchAssistantMessage(replyIndex, () => event.reply || 'Here is what I found.')
                        setLimitedMode(event.mode === 'limited')
                        const hasSearch = Object.values(event.filters || {}).some(
                            (v) => v !== undefined && v !== '',
                        )
                        if (hasSearch || (Array.isArray(event.listings) && event.listings.length)) {
                            onListingsFound?.(
                                Array.isArray(event.listings) ? event.listings : [],
                                event.filters || {},
                                event.total_count,
                            )
                        }
                    }
                }
            }
        } catch (error) {
            patchAssistantMessage(replyIndex, () =>
                extractApiErrorMessage(
                    error,
                    'Sorry, I could not process that right now. Please try again.',
                ),
            )
        } finally {
            setLoading(false)
            setStreaming(false)
        }
    }

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault()
        sendMessage(input)
    }

    return (
        <div className="overflow-hidden rounded-2xl border border-indigo-100 bg-white shadow-lg shadow-indigo-950/5">
            {/* Header */}
            <div className="flex items-center gap-3 border-b border-indigo-50 bg-[linear-gradient(112deg,#12296f_0%,#29249b_55%,#5222d1_100%)] px-5 py-4">
                <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-white/15 backdrop-blur">
                    <HiOutlineSparkles className="h-5 w-5 text-white" />
                </div>
                <div>
                    <h2 className="text-lg font-semibold text-white">Sally</h2>
                    <p className="text-sm text-indigo-200">
                        Your RentDirect AI assistant — ask me to find properties, compare prices, or answer any questions
                    </p>
                    {limitedMode ? (
                        <p className="text-xs text-amber-200">
                            Limited mode — I can still search and quote live data, but replies may be less conversational.
                        </p>
                    ) : null}
                </div>
            </div>

            {/* Messages — text only; property results are rendered in the page grid */}
            <div ref={scrollRef} className="max-h-[26rem] space-y-4 overflow-y-auto px-4 py-4 sm:px-5">
                {messages.length === 0 && !loading ? (
                    <div className="space-y-4">
                        <div className="max-w-[40%] rounded-2xl rounded-tl-sm bg-indigo-50 px-4 py-3 text-sm text-gray-700">
                            Hi! I'm Sally, your RentDirect assistant, I am here to assist you.<br /> You can ask me any question about RentDirect.
                        </div>
                    </div>
                ) : null}

                {messages.map((message, index) => (
                    <div key={index} className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                        <div
                            className={`max-w-[90%] rounded-2xl px-4 py-3 text-sm sm:max-w-[55%] ${message.role === 'user'
                                ? 'rounded-tr-sm bg-indigo-600 text-white'
                                : 'rounded-tl-sm bg-orange-200 text-gray-800 ring-1 ring-gray-100'
                                }`}
                        >
                            <p className="whitespace-pre-wrap leading-6">{message.content}</p>
                        </div>
                    </div>
                ))}

                {loading && !streaming ? (
                    <div className="flex justify-start">
                        <div className="flex items-center gap-1.5 rounded-2xl rounded-tl-sm bg-gray-50 px-4 py-3 ring-1 ring-gray-100">
                            <span className="h-2 w-2 animate-bounce rounded-full bg-indigo-400" style={{ animationDelay: '0ms' }} />
                            <span className="h-2 w-2 animate-bounce rounded-full bg-indigo-400" style={{ animationDelay: '150ms' }} />
                            <span className="h-2 w-2 animate-bounce rounded-full bg-indigo-400" style={{ animationDelay: '300ms' }} />
                        </div>
                    </div>
                ) : null}
            </div>

            {/* Input */}
            <form onSubmit={handleSubmit} className="flex items-center gap-2 border-t border-gray-100 bg-gray-50/60 px-4 py-3">
                <input
                    type="text"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    placeholder='Try "Can you show me a list of 3 bedroom properties in Lekki under ₦5m"...'
                    className="flex-1 rounded-xl border border-gray-200 bg-white px-4 py-2.5 text-sm focus:border-indigo-400 focus:outline-none focus:ring-2 focus:ring-indigo-100"
                    maxLength={2000}
                />
                <button
                    type="submit"
                    disabled={loading || !input.trim()}
                    className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-600 text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-40"
                    aria-label="Send message"
                >
                    <HiPaperAirplane className="h-5 w-5 rotate-90" />
                </button>
            </form>
        </div>
    )
}
