import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { Listing as ListingType } from '@/types'
import { useState } from 'react'
import { resolveMediaUrl } from '@/lib/api'
import { formatCurrencyWithSymbol } from '@/utils/currency'

export default function ListingPage() {
    const { id } = useParams()
    const { data, isLoading } = useQuery({
        queryKey: ['listing', id],
        enabled: !!id,
        queryFn: async () => (await api.get<ListingType>(`/listings/${id}`)).data
    })

    const [selectedImage, setSelectedImage] = useState<string | null>(null)

    if (isLoading) {
        return (
            <div className="min-h-[80vh] flex items-center justify-center bg-gray-50">
                <div className="animate-pulse text-gray-500">Loading listing…</div>
            </div>
        )
    }

    if (!data) {
        return (
            <div className="min-h-[80vh] flex items-center justify-center bg-gray-50">
                <div className="text-gray-500">Listing not found.</div>
            </div>
        )
    }

    return (
        <div className="bg-gray-50 py-10">
            <div className="container-page">
                <div className="grid grid-cols-1 gap-8 md:grid-cols-3">
                    {/* Main Image */}
                    <div className="md:col-span-2 flex flex-col items-center">
                        <img
                            className="h-96 w-full rounded-2xl object-cover shadow-lg mb-4"
                            src={resolveMediaUrl(selectedImage || data.cover_image_url)}
                            alt={data.title}
                            loading="eager"
                            decoding="async"
                        />

                        {/* Thumbnails */}
                        {data.image_urls && data.image_urls.length > 0 && (
                            <div className="flex space-x-2 overflow-x-auto">
                                {[data.cover_image_url, ...data.image_urls].map((img, idx) => (
                                    <img
                                        key={idx}
                                        src={resolveMediaUrl(img)}
                                        alt={`Additional ${idx + 1}`}
                                        loading="lazy"
                                        decoding="async"
                                        className="h-20 w-20 object-cover rounded cursor-pointer border border-gray-300 hover:border-blue-500 transition-colors"
                                        onClick={() => setSelectedImage(img || null)}
                                    />
                                ))}
                            </div>
                        )}
                    </div>

                    {/* Price + Actions */}
                    <div className="rounded-2xl bg-white p-6 shadow-lg border">
                         <div className="text-2xl font-bold text-gray-900">
                             {formatCurrencyWithSymbol(data.price_per_year)}/year
                         </div>
                        <div className="mt-1 text-gray-500">per calendar year</div>

                        <button
                            className="mt-6 w-full rounded-lg bg-blue-600 px-4 py-3 text-white font-medium hover:bg-blue-700 transition"
                        >
                            Request viewing
                        </button>
                        <button
                            className="mt-3 w-full rounded-lg border border-gray-300 px-4 py-3 font-medium hover:bg-gray-100 transition"
                        >
                            Start application
                        </button>
                    </div>
                </div>

                {/* Title + Description */}
                <div className="mt-8 bg-white p-6 rounded-2xl shadow-lg border">
                    <h1 className="text-3xl font-bold text-gray-900">{data.title}</h1>
                    <p className="mt-4 text-gray-700 leading-relaxed">{data.description}</p>

                    {/* Additional Details */}
                    {data.address && (
                        <div className="mt-4">
                            <h3 className="font-semibold text-gray-900">Address</h3>
                            <p className="text-gray-700">{data.address}</p>
                        </div>
                    )}

                    {data.bedrooms && data.bathrooms && (
                        <div className="mt-4 grid grid-cols-2 gap-4">
                            <div>
                                <h3 className="font-semibold text-gray-900">Bedrooms</h3>
                                <p className="text-gray-700">{data.bedrooms}</p>
                            </div>
                            <div>
                                <h3 className="font-semibold text-gray-900">Bathrooms</h3>
                                <p className="text-gray-700">{data.bathrooms}</p>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}
