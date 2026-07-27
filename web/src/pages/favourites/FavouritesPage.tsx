import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { Listing } from '@/types'
import { Link } from 'react-router-dom'
import { resolveMediaUrl } from '@/lib/api'
import { formatCurrencyWithSymbol } from '@/utils/currency'

export default function FavouritesPage() {
    const qc = useQueryClient()
    const { data: favourites, isLoading } = useQuery({
        queryKey: ['me', 'favourites'],
        queryFn: async () => (await api.get<Listing[]>('/users/me/favourites')).data
    })

    const removeFavourite = useMutation({
        mutationFn: async (listingId: string) => {
            await api.delete(`/users/me/favourites/${listingId}`)
        },
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['me', 'favourites'] })
        },
        onError: (error) => {
            alert('Failed to remove from favourites: ' + error.message)
        }
    })

    if (isLoading) {
        return (
            <div className="container-modern py-8">
                <div className="text-center">Loading favourites...</div>
            </div>
        )
    }

    return (
        <div className="container-modern py-8">
            <h1 className="text-3xl font-bold mb-6">Your Favourites</h1>

            {favourites && favourites.length > 0 ? (
                <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
                    {favourites.map(f => (
                        <div
                            key={f.id}
                            className="rounded-xl border bg-white shadow-sm hover:shadow-md transition overflow-hidden flex flex-col"
                        >
                            <img
                                src={resolveMediaUrl(f.cover_image_url)}
                                alt={f.title}
                                className="h-60 w-full object-cover"
                                onError={(e) => {
                                    e.currentTarget.src = '/placeholder.jpg'
                                }}
                            />
                            <div className="flex flex-col flex-grow p-4">
                                <h2 className="text-lg font-semibold">{f.title}</h2>
                                <p className="text-sm text-gray-500">{[f.city, f.state].filter(Boolean).join(', ') || 'State not provided'}</p>
                                <p className="mt-2 font-medium text-brand">{formatCurrencyWithSymbol(f.price_per_year)}/year</p>
                                <br />
                                <div className="mt-auto flex gap-2">
                                    <Link
                                        to={`/listings/${f.id}`}
                                        className="flex-1 rounded-lg border border-brand px-1 py-1 text-center text-brand hover:bg-brand hover:text-white transition text-sm"
                                    >
                                        View
                                    </Link>
                                    <button
                                        onClick={() => removeFavourite.mutate(f.id)}
                                        disabled={removeFavourite.isPending}
                                        className="rounded-lg border border-red-900 px-1 py-1 text-red-900 hover:bg-red-200 transition text-sm"
                                    >
                                        {removeFavourite.isPending ? '...' : 'Remove'}
                                    </button>
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            ) : (
                <div className="text-center py-12">
                    <p className="text-gray-600 mb-4">No favourites yet.</p>
                    <Link to="/search" className="rounded-md bg-brand px-4 py-2 text-white">
                        Browse Properties
                    </Link>
                </div>
            )}
        </div>
    )
}
