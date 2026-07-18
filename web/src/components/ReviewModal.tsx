import { useEffect, useState } from 'react'

type ReviewOption = {
    id: string
    title: string
}

type ReviewModalProps = {
    isOpen: boolean
    title: string
    initialComment?: string
    initialRating?: number
    listingOptions?: ReviewOption[]
    selectedListingId?: string
    onChangeListingId?: (listingId: string) => void
    onClose: () => void
    onSubmit: (payload: { rating: number; comment: string }) => void
    isSubmitting?: boolean
}

export default function ReviewModal({
    isOpen,
    title,
    initialComment = '',
    initialRating = 5,
    listingOptions = [],
    selectedListingId = '',
    onChangeListingId,
    onClose,
    onSubmit,
    isSubmitting = false,
}: ReviewModalProps) {
    const [rating, setRating] = useState(initialRating)
    const [comment, setComment] = useState(initialComment)

    useEffect(() => {
        if (!isOpen) return
        setRating(initialRating)
        setComment(initialComment)
    }, [initialComment, initialRating, isOpen])

    if (!isOpen) {
        return null
    }

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4">
            <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl">
                <div className="flex items-start justify-between gap-4">
                    <div>
                        <h2 className="text-xl font-semibold text-gray-900">{title}</h2>
                        <p className="mt-1 text-sm text-gray-600">Share your experience to help future tenants.</p>
                    </div>
                    <button
                        type="button"
                        onClick={onClose}
                        className="rounded-full p-2 text-gray-500 transition hover:bg-gray-100 hover:text-gray-700"
                    >
                        <span className="sr-only">Close</span>
                        ×
                    </button>
                </div>

                {listingOptions.length > 1 && onChangeListingId ? (
                    <div className="mt-5">
                        <label className="form-label">Property</label>
                        <select
                            className="form-input"
                            value={selectedListingId}
                            onChange={(event) => onChangeListingId(event.target.value)}
                        >
                            <option value="">Select a property</option>
                            {listingOptions.map((listing) => (
                                <option key={listing.id} value={listing.id}>{listing.title}</option>
                            ))}
                        </select>
                    </div>
                ) : null}

                <div className="mt-5">
                    <label className="form-label">Rating</label>
                    <div className="mt-2 flex gap-2">
                        {[1, 2, 3, 4, 5].map((value) => (
                            <button
                                key={value}
                                type="button"
                                onClick={() => setRating(value)}
                                className={`rounded-full px-4 py-2 text-sm font-medium transition ${
                                    value <= rating
                                        ? 'bg-amber-100 text-amber-700'
                                        : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
                                }`}
                            >
                                {value}★
                            </button>
                        ))}
                    </div>
                </div>

                <div className="mt-5">
                    <label className="form-label">Review</label>
                    <textarea
                        className="form-input mt-2 min-h-32"
                        value={comment}
                        onChange={(event) => setComment(event.target.value)}
                        placeholder="Write your review here"
                    />
                </div>

                <div className="mt-6 flex justify-end gap-3">
                    <button
                        type="button"
                        onClick={onClose}
                        className="btn btn-outline"
                        disabled={isSubmitting}
                    >
                        Cancel
                    </button>
                    <button
                        type="button"
                        onClick={() => onSubmit({ rating, comment })}
                        className="btn btn-primary"
                        disabled={isSubmitting || (listingOptions.length > 0 && !selectedListingId)}
                    >
                        {isSubmitting ? 'Saving...' : 'Submit Review'}
                    </button>
                </div>
            </div>
        </div>
    )
}
