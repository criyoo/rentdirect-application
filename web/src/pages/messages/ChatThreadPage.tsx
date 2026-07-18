import { useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, resolveMediaUrl } from '@/lib/api'
import { useState } from 'react'
import { User } from '@/types'

type Message = { id: number; content: string; sender_id: string; created_at: string }

export default function ChatThreadPage() {
    const { userId } = useParams()
    const qc = useQueryClient()
    const [text, setText] = useState('')

    const { data: messages } = useQuery({
        queryKey: ['messages', userId],
        queryFn: async () => (await api.get<Message[]>(`/messages/${userId}`)).data,
        enabled: !!userId
    })

    const { data: user } = useQuery({
        queryKey: ['users', userId],
        queryFn: async () => (await api.get<User>(`/users/${userId}`)).data,
        enabled: !!userId
    })

    const { data: currentUser } = useQuery({
        queryKey: ['users', 'me'],
        queryFn: async () => (await api.get<User>('/users/me')).data,
    })

    const send = useMutation({
        mutationFn: async () => {
            await api.post('/messages/send', { recipient_id: userId, content: text })
        },
        onSuccess: () => {
            setText('')
            qc.invalidateQueries({ queryKey: ['messages', userId] })
        },
        onError: (error) => {
            alert('Failed to send message: ' + error.message)
        }
    })

    return (
        <div className="container-page py-8">
            <h1 className="text-2xl font-bold mb-4">Chat with {user?.name}</h1>
            <div className="rounded-xl border bg-white h-96 flex flex-col">
                <div className="flex-1 p-4 overflow-y-auto">
                    {messages?.map(m => (
                        <div key={m.id} className={`mb-4 flex items-end gap-3 ${m.sender_id === currentUser?.id ? 'justify-end' : 'justify-start'}`}>
                            {m.sender_id !== currentUser?.id && (
                                <img
                                    src={resolveMediaUrl(user?.profile_photo_url)}
                                    alt={user?.name || 'User'}
                                    className="h-8 w-8 rounded-full object-cover"
                                    onError={(event) => {
                                        event.currentTarget.src = '/placeholder.jpg'
                                    }}
                                />
                            )}
                            <div>
                                <div className="text-sm text-gray-500">{new Date(m.created_at).toLocaleString()}</div>
                                <div className={`rounded-lg p-3 max-w-xs ${m.sender_id === currentUser?.id ? 'bg-blue-600 text-white' : 'bg-gray-100'}`}>
                                    {m.content}
                                </div>
                            </div>
                            {m.sender_id === currentUser?.id && (
                                <img
                                    src={resolveMediaUrl(currentUser?.profile_photo_url)}
                                    alt={currentUser?.name || 'You'}
                                    className="h-8 w-8 rounded-full object-cover"
                                    onError={(event) => {
                                        event.currentTarget.src = '/placeholder.jpg'
                                    }}
                                />
                            )}
                        </div>
                    ))}
                </div>
                <div className="border-t p-4">
                    <div className="flex gap-2">
                        <input
                            type="text"
                            value={text}
                            onChange={e => setText(e.target.value)}
                            placeholder="Type your message..."
                            className="flex-1 rounded-md border px-3 py-2"
                            onKeyDown={e => e.key === 'Enter' && send.mutate()}
                        />
                        <button className="rounded-md bg-brand px-4 py-2 text-white" onClick={() => send.mutate()} disabled={send.isPending || !text.trim()}>Send</button>
                    </div>
                </div>
            </div>
        </div>
    )
}
