import { useQuery } from '@tanstack/react-query'
import { api, resolveMediaUrl } from '@/lib/api'
import { Link, useParams } from 'react-router-dom'

type Conversation = {
    counterpart_id: string
    counterpart_name: string
    counterpart_role: string
    counterpart_profile_photo_url?: string | null
    last_message: { id: number; content: string; created_at: string }
    listing_id: string | null
}

export default function EnquiriesPage() {
    const { userId } = useParams()
    const { data, isLoading } = useQuery({
        queryKey: ['messages', 'conversations'],
        queryFn: async () => (await api.get<Conversation[]>('/messages/conversations')).data,
    })

    if (isLoading) return <div className="p-6">Loading...</div>

    return (
        <div className="container-page py-8">
            <h1 className="text-2xl font-bold mb-4">Enquiries</h1>
            {(!data || data.length === 0) ? (
                <p className="text-gray-600">No conversations yet.</p>
            ) : (
                <div className="divide-y bg-white rounded-xl border">
                    {data.map((c) => (
                        <Link key={c.last_message.id} to={`/chat/${c.counterpart_id}`} className="flex items-start gap-4 p-4 hover:bg-gray-50">
                            <img
                                src={resolveMediaUrl(c.counterpart_profile_photo_url)}
                                alt={c.counterpart_name}
                                loading="lazy"
                                decoding="async"
                                className="h-12 w-12 rounded-full object-cover flex-shrink-0"
                                onError={(e) => {
                                    e.currentTarget.src = '/placeholder.jpg'
                                }}
                            />
                            <div className="flex-1">
                                <div className="font-medium">{c.counterpart_name}</div>
                                <div className="text-xs text-gray-500 capitalize">{c.counterpart_role}</div>
                                <div className="text-sm text-gray-600 line-clamp-1">{c.last_message.content}</div>
                            </div>
                            <div className="text-xs text-gray-500">{new Date(c.last_message.created_at).toLocaleString()}</div>
                        </Link>
                    ))}
                </div>
            )}
            <div className="mt-6">
                <Link to={`/dashboard/tenant/${userId}`} className="text-brand">Back to dashboard</Link>
            </div>
        </div>
    )
}
