import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, extractApiErrorMessage } from '@/lib/api'
import BrandLogo from '@/components/BrandLogo'
import { HiCheckCircle, HiIdentification, HiShieldCheck } from 'react-icons/hi'

interface RepresentativeKycContext {
    token: string
    status: 'pending' | 'submitted' | 'verified' | 'rejected'
    ownership_type?: string
    landlord_name?: string
    listing_title?: string
    name?: string
    email?: string
    phone?: string
    return_url?: string
}

export default function RepresentativeKycPage() {
    const { token } = useParams<{ token: string }>()
    const navigate = useNavigate()
    const [context, setContext] = useState<RepresentativeKycContext | null>(null)
    const [loadError, setLoadError] = useState('')
    const [isLoading, setIsLoading] = useState(true)

    const [name, setName] = useState('')
    const [email, setEmail] = useState('')
    const [phone, setPhone] = useState('')
    const [dateOfBirth, setDateOfBirth] = useState('')
    const [ninNumber, setNinNumber] = useState('')
    const [passportPhoto, setPassportPhoto] = useState<File | null>(null)
    const [idDocument, setIdDocument] = useState<File | null>(null)
    const [isSubmitting, setIsSubmitting] = useState(false)
    const [error, setError] = useState('')
    const [resultDetail, setResultDetail] = useState('')

    useEffect(() => {
        if (!token) return
        let cancelled = false
        api.get<RepresentativeKycContext>(`/representative-kyc/${token}`)
            .then((response) => {
                if (cancelled) return
                setContext(response.data)
                setName(response.data.name || '')
                setEmail(response.data.email || '')
                setPhone(response.data.phone || '')
            })
            .catch((err) => {
                if (cancelled) return
                setLoadError(extractApiErrorMessage(err, 'This KYC link is invalid or has expired.'))
            })
            .finally(() => {
                if (!cancelled) setIsLoading(false)
            })
        return () => {
            cancelled = true
        }
    }, [token])

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault()
        if (!token) return
        setError('')
        setIsSubmitting(true)

        try {
            const formData = new FormData()
            formData.append('name', name)
            formData.append('email', email)
            formData.append('phone', phone)
            if (dateOfBirth) formData.append('date_of_birth', dateOfBirth)
            if (ninNumber) formData.append('nin_number', ninNumber)
            if (passportPhoto) formData.append('passport_photo', passportPhoto)
            if (idDocument) formData.append('id_document', idDocument)

            const response = await api.post<{ status: RepresentativeKycContext['status']; detail?: string; return_url?: string }>(
                `/representative-kyc/${token}/submit`,
                formData,
            )
            setContext((current) =>
                current
                    ? { ...current, status: response.data.status, return_url: response.data.return_url || current.return_url }
                    : current,
            )
            setResultDetail(response.data.detail || '')
        } catch (err) {
            setError(extractApiErrorMessage(err, 'Failed to submit KYC. Please try again.'))
        } finally {
            setIsSubmitting(false)
        }
    }

    const returnToListing = () => {
        if (context?.return_url) {
            navigate(context.return_url)
        }
    }

    if (isLoading) {
        return (
            <div className="min-h-screen bg-gray-50 flex items-center justify-center">
                <div className="h-10 w-10 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
            </div>
        )
    }

    if (loadError || !context) {
        return (
            <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
                <div className="max-w-md w-full rounded-2xl bg-white p-8 text-center shadow-lg">
                    <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-red-100">
                        <HiShieldCheck className="h-7 w-7 text-red-600" />
                    </div>
                    <h1 className="text-xl font-semibold text-gray-900">Invalid KYC link</h1>
                    <p className="mt-2 text-sm text-gray-600">{loadError || 'This link could not be loaded.'}</p>
                    <Link to="/" className="mt-6 inline-block rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700">
                        Go to homepage
                    </Link>
                </div>
            </div>
        )
    }

    const isComplete = context.status === 'submitted' || context.status === 'verified'

    if (isComplete) {
        return (
            <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-purple-50 flex items-center justify-center px-4 py-12">
                <div className="max-w-md w-full rounded-2xl bg-white p-8 text-center shadow-lg">
                    <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-600 to-emerald-700 shadow-lg">
                        <HiCheckCircle className="h-8 w-8 text-white" />
                    </div>
                    <h1 className="text-2xl font-bold text-gray-900">
                        {context.status === 'verified' ? 'KYC verified' : 'KYC submitted'}
                    </h1>
                    <p className="mt-2 text-sm text-gray-600">
                        {resultDetail ||
                            (context.status === 'verified'
                                ? 'Your identity has been verified successfully. You can now return to the listing page.'
                                : 'Your details have been submitted and are pending verification. You can now return to the listing page.')}
                    </p>
                    {context.return_url && (
                        <button
                            type="button"
                            onClick={returnToListing}
                            className="mt-6 inline-block rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-blue-700"
                        >
                            Return to the listing page
                        </button>
                    )}
                </div>
            </div>
        )
    }

    return (
        <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-purple-50 px-4 py-10">
            <div className="mx-auto max-w-lg">
                <div className="mb-6 text-center">
                    <div className="mb-4 flex justify-center">
                        <BrandLogo />
                    </div>
                    <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-600 to-indigo-600 shadow-lg">
                        <HiIdentification className="h-7 w-7 text-white" />
                    </div>
                    <h1 className="text-2xl font-bold text-gray-900">Representative KYC Verification</h1>
                    <p className="mt-2 text-sm text-gray-600">
                        {context.landlord_name
                            ? `${context.landlord_name} has listed a property on RentDirect${context.listing_title ? ` (${context.listing_title})` : ''} and named you as the property representative.`
                            : 'You have been named as a property representative on RentDirect.'}{' '}
                        Complete this KYC verification to proceed.
                    </p>
                </div>

                <form onSubmit={handleSubmit} className="space-y-5 rounded-2xl bg-white p-6 shadow-lg sm:p-8">
                    <div>
                        <label className="mb-1 block text-sm font-medium text-gray-700">Full Name *</label>
                        <input
                            type="text"
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                            required
                            className="w-full rounded-lg border border-gray-300 px-4 py-2 outline-none focus:border-blue-500 focus:ring focus:ring-blue-500/20"
                        />
                    </div>
                    <div>
                        <label className="mb-1 block text-sm font-medium text-gray-700">Email</label>
                        <input
                            type="email"
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            className="w-full rounded-lg border border-gray-300 px-4 py-2 outline-none focus:border-blue-500 focus:ring focus:ring-blue-500/20"
                        />
                    </div>
                    <div>
                        <label className="mb-1 block text-sm font-medium text-gray-700">Phone Number *</label>
                        <input
                            type="tel"
                            value={phone}
                            onChange={(e) => setPhone(e.target.value)}
                            required
                            className="w-full rounded-lg border border-gray-300 px-4 py-2 outline-none focus:border-blue-500 focus:ring focus:ring-blue-500/20"
                        />
                    </div>
                    <div>
                        <label className="mb-1 block text-sm font-medium text-gray-700">Date of Birth</label>
                        <input
                            type="date"
                            value={dateOfBirth}
                            onChange={(e) => setDateOfBirth(e.target.value)}
                            className="w-full rounded-lg border border-gray-300 px-4 py-2 outline-none focus:border-blue-500 focus:ring focus:ring-blue-500/20"
                        />
                    </div>
                    <div>
                        <label className="mb-1 block text-sm font-medium text-gray-700">NIN (National Identification Number)</label>
                        <input
                            type="text"
                            inputMode="numeric"
                            maxLength={11}
                            value={ninNumber}
                            onChange={(e) => setNinNumber(e.target.value.replace(/\D/g, ''))}
                            placeholder="11-digit NIN"
                            className="w-full rounded-lg border border-gray-300 px-4 py-2 outline-none focus:border-blue-500 focus:ring focus:ring-blue-500/20"
                        />
                        <p className="mt-1 text-xs text-gray-500">Providing your NIN allows instant identity verification.</p>
                    </div>
                    <div>
                        <label className="mb-1 block text-sm font-medium text-gray-700">Passport Photo</label>
                        <input
                            type="file"
                            accept=".jpg,.jpeg,.png"
                            onChange={(e) => setPassportPhoto(e.target.files?.[0] || null)}
                            className="w-full rounded-lg border border-gray-300 px-4 py-2 outline-none focus:border-blue-500 focus:ring focus:ring-blue-500/20"
                        />
                    </div>
                    <div>
                        <label className="mb-1 block text-sm font-medium text-gray-700">Valid ID Document</label>
                        <input
                            type="file"
                            accept=".pdf,.jpg,.jpeg,.png"
                            onChange={(e) => setIdDocument(e.target.files?.[0] || null)}
                            className="w-full rounded-lg border border-gray-300 px-4 py-2 outline-none focus:border-blue-500 focus:ring focus:ring-blue-500/20"
                        />
                    </div>

                    {error && <p className="text-sm text-red-600">{error}</p>}

                    <button
                        type="submit"
                        disabled={isSubmitting}
                        className="w-full rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                        {isSubmitting ? 'Submitting…' : 'Submit KYC'}
                    </button>
                </form>
            </div>
        </div>
    )
}
