import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { HiCamera, HiCheckCircle, HiShieldCheck, HiUser } from 'react-icons/hi'

import { useAppPopup } from '@/contexts/AppPopupContext'
import DashboardBackButton from '@/components/DashboardBackButton'
import { api, extractApiErrorMessage, resolveMediaUrl } from '@/lib/api'
import { AgentProfile, User } from '@/types'
import { formatCurrencyWithSymbol } from '@/utils/currency'

function maskDigits(value?: string | null): string {
    const digits = String(value || '').trim()
    if (!digits) return '—'
    if (digits.length <= 4) return digits
    return `${'•'.repeat(Math.max(digits.length - 4, 0))}${digits.slice(-4)}`
}

function ProfileRow({ label, value }: { label: string; value?: string | null }) {
    return (
        <div className="flex flex-col gap-1 border-b border-gray-100 py-3 sm:flex-row sm:items-center sm:justify-between">
            <span className="text-sm text-gray-500">{label}</span>
            <span className="font-medium text-gray-900">{value || '—'}</span>
        </div>
    )
}

const VERIFICATION_LABELS: Record<string, string> = {
    incomplete: 'Incomplete',
    payment_required: 'Payment required',
    pending: 'Pending',
    verified: 'Verified',
    rejected: 'Rejected',
}

export default function AgentProfilePage() {
    const { alert } = useAppPopup()
    const queryClient = useQueryClient()
    const fileInputRef = useRef<HTMLInputElement>(null)
    const [photoError, setPhotoError] = useState('')

    const { data: profile, isLoading } = useQuery({
        queryKey: ['agents', 'profile'],
        queryFn: async () => (await api.get<AgentProfile>('/agents/profile')).data,
    })

    const uploadPhoto = useMutation({
        mutationFn: async (file: File) => {
            const formData = new FormData()
            formData.append('file', file)
            return (await api.post<User>('/users/me/photo', formData, {
                headers: { 'Content-Type': 'multipart/form-data' },
            })).data
        },
        onSuccess: async (nextUser) => {
            queryClient.setQueryData(['users', 'me'], nextUser)
            localStorage.setItem('user', JSON.stringify(nextUser))
            window.dispatchEvent(new Event('rentdirect-user-updated'))
            await queryClient.invalidateQueries({ queryKey: ['agents', 'profile'] })
            await alert('Profile photo updated.', { title: 'Profile photo' })
        },
        onError: async (error) => {
            setPhotoError(extractApiErrorMessage(error, 'Unable to upload your profile photo.'))
        },
    })

    const isVerified = profile?.verification_status === 'verified'

    return (
        <div className="agent-theme min-h-screen bg-gradient-to-br from-emerald-50 via-white to-green-50">
            <div className="container-modern py-8">
                <div className="mb-5">
                    <DashboardBackButton to="/agents/dashboard" label="Back to dashboard" />
                </div>

                <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
                    <div className="flex items-center gap-5">
                        <div className="relative shrink-0">
                            {profile?.profile_photo_url ? (
                                <img
                                    src={resolveMediaUrl(profile.profile_photo_url)}
                                    alt={profile.first_name || 'PIO profile photo'}
                                    loading="eager"
                                    decoding="async"
                                    className="h-24 w-24 rounded-2xl object-cover ring-4 ring-emerald-100"
                                />
                            ) : (
                                <div className="flex h-24 w-24 items-center justify-center rounded-2xl bg-gray-100 text-gray-400 ring-4 ring-emerald-100">
                                    <HiUser className="h-10 w-10" />
                                </div>
                            )}
                            <button
                                type="button"
                                onClick={() => fileInputRef.current?.click()}
                                disabled={uploadPhoto.isPending}
                                className="absolute -bottom-2 -right-2 flex h-8 w-8 items-center justify-center rounded-full bg-emerald-600 text-white shadow-md transition-colors hover:bg-emerald-700 disabled:opacity-50"
                                title={uploadPhoto.isPending ? 'Uploading…' : 'Change profile photo'}
                            >
                                <HiCamera className="h-4 w-4" />
                            </button>
                            <input
                                ref={fileInputRef}
                                type="file"
                                accept="image/*"
                                className="hidden"
                                onChange={(e) => {
                                    const file = e.target.files?.[0]
                                    if (file) {
                                        setPhotoError('')
                                        uploadPhoto.mutate(file)
                                    }
                                    e.target.value = ''
                                }}
                            />
                        </div>
                        <div>
                            <h1 className="text-3xl font-bold text-gray-900">PIO Profile</h1>
                            <p className="text-sm text-gray-600">Your verification, identity and payout details</p>
                            {photoError && <p className="mt-1 text-sm text-red-600">{photoError}</p>}
                            {uploadPhoto.isPending && <p className="mt-1 text-sm text-gray-500">Uploading photo…</p>}
                        </div>
                    </div>
                    <Link to="/agents/verification" className="btn btn-outline px-4 py-2 text-sm">
                        {isVerified ? 'View verification' : 'Edit / complete verification'}
                    </Link>
                </div>

                {isLoading ? (
                    <div className="card p-6 text-center text-gray-600">Loading profile…</div>
                ) : (
                    <div className="grid gap-6 lg:grid-cols-2">
                        <div className="card p-6">
                            <div className="mb-4 flex items-center gap-2">
                                <HiShieldCheck className={`h-6 w-6 ${isVerified ? 'text-green-600' : 'text-amber-500'}`} />
                                <h2 className="text-xl font-semibold text-gray-900">Verification</h2>
                            </div>
                            <ProfileRow label="Status" value={VERIFICATION_LABELS[profile?.verification_status || ''] || profile?.verification_status} />
                            <ProfileRow label="Verified at" value={profile?.verified_at ? new Date(profile.verified_at).toLocaleString() : '—'} />
                            <ProfileRow
                                label="Verification fee"
                                value={
                                    profile?.verification_payment
                                        ? `${formatCurrencyWithSymbol(Number(profile.verification_payment.amount))} (${profile.verification_payment.status_display || profile.verification_payment.status})`
                                        : 'Not paid'
                                }
                            />
                            {isVerified && (
                                <div className="mt-4 flex items-center gap-2 rounded-lg bg-green-50 p-3 text-sm text-green-800">
                                    <HiCheckCircle className="h-5 w-5" />
                                    Your PIO identity is verified.
                                </div>
                            )}
                        </div>

                        <div className="card p-6">
                            <h2 className="mb-4 text-xl font-semibold text-gray-900">Personal details</h2>
                            <ProfileRow label="Name" value={[profile?.first_name, profile?.middle_name, profile?.last_name].filter(Boolean).join(' ')} />
                            <ProfileRow label="Email" value={profile?.email} />
                            <ProfileRow label="Date of birth" value={profile?.date_of_birth || '—'} />
                            <ProfileRow label="Gender" value={profile?.gender} />
                            <ProfileRow label="Country of birth" value={profile?.country_of_birth} />
                            <ProfileRow label="Nationality" value={profile?.nationality} />
                            <ProfileRow label="State of origin" value={profile?.state_of_origin} />
                            <ProfileRow label="LGA of origin" value={profile?.lga_of_origin} />
                            <ProfileRow label="Mobile" value={profile?.mobile} />
                            <ProfileRow label="WhatsApp" value={profile?.whatsapp_number} />
                            <ProfileRow label="City" value={profile?.city} />
                            <ProfileRow label="Residential address" value={profile?.residential_address} />
                        </div>

                        <div className="card p-6">
                            <h2 className="mb-4 text-xl font-semibold text-gray-900">Identity</h2>
                            <ProfileRow label="NIN" value={maskDigits(profile?.nin_number)} />
                            <ProfileRow label="BVN" value={maskDigits(profile?.bvn_number)} />
                        </div>

                        <div className="card p-6">
                            <h2 className="mb-4 text-xl font-semibold text-gray-900">Payout bank details</h2>
                            <ProfileRow label="Bank" value={profile?.bank_name} />
                            <ProfileRow label="Account name" value={profile?.account_name} />
                            <ProfileRow label="Account number" value={maskDigits(profile?.account_number)} />
                        </div>
                    </div>
                )}
            </div>
        </div>
    )
}
