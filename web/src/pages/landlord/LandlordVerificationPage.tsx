import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'

import { api } from '@/lib/api'
import { LandlordVerificationType, User } from '@/types'

type VerificationProgress = {
    status?: string
    submitted_at?: string | null
}

type VerificationStatusResponse = {
    status?: string
    submitted_at?: string | null
    identification?: VerificationProgress
    property_documents?: VerificationProgress
    physical_property?: VerificationProgress
}

type UploadedDocument = {
    id: string
    title: string
}

type PaginatedResponse<T> = {
    results?: T[]
}

function normalizeResults<T>(payload: T[] | PaginatedResponse<T> | undefined): T[] {
    if (!payload) {
        return []
    }
    if (Array.isArray(payload)) {
        return payload
    }
    return Array.isArray(payload.results) ? payload.results : []
}

function getProgressStatusLabel(status?: string) {
    if (status === 'verified' || status === 'approved') {
        return 'Verified'
    }
    if (status === 'pending' || status === 'under_review') {
        return 'Pending'
    }
    return 'Unverified'
}

function getProgressStatusClassName(status?: string) {
    if (status === 'verified' || status === 'approved') {
        return 'bg-green-100 text-green-700'
    }
    if (status === 'pending' || status === 'under_review') {
        return 'bg-amber-100 text-amber-700'
    }
    return 'bg-gray-100 text-gray-700'
}

export default function LandlordVerificationPage() {
    const navigate = useNavigate()
    const [verificationType, setVerificationType] = useState<LandlordVerificationType | ''>('')

    const { data: me, isLoading } = useQuery({
        queryKey: ['users', 'me'],
        queryFn: async () => (await api.get<User>('/users/me')).data,
    })

    const { data: verificationStatus } = useQuery({
        queryKey: ['verification', 'status'],
        queryFn: async () => (await api.get<VerificationStatusResponse>('/landlord-verification-requests/status')).data,
    })

    const { data: documentResponse } = useQuery({
        queryKey: ['documents', 'me'],
        queryFn: async () => (await api.get<UploadedDocument[] | PaginatedResponse<UploadedDocument>>('/documents')).data,
    })

    const identificationStatus = verificationStatus?.identification?.status || 'unverified'
    const isVerificationLocked = Boolean(
        me?.is_verified
        || identificationStatus === 'verified'
        || verificationStatus?.status === 'approved',
    )
    const documents = normalizeResults(documentResponse)
    const identificationDocuments = useMemo(
        () => documents.filter((document) => document.title.startsWith('Landlord Identification:')),
        [documents],
    )
    const submittedVerificationTrack = me?.landlord_verification_type && (identificationDocuments.length > 0 || isVerificationLocked)
        ? me.landlord_verification_type
        : ''
    const isTrackSelectionLocked = Boolean(submittedVerificationTrack || isVerificationLocked)

    useEffect(() => {
        if (me?.landlord_verification_type === 'individual' || me?.landlord_verification_type === 'corporate') {
            setVerificationType(me.landlord_verification_type)
        }
    }, [me?.landlord_verification_type])

    const verificationStatuses = [
        {
            label: 'Identity Verification',
            status: identificationStatus,
            submittedAt: verificationStatus?.identification?.submitted_at,
        },
    ]

    if (isLoading) {
        return (
            <div className="container-modern py-8">
                <div className="rounded-xl border bg-white p-6 text-gray-600">Loading verification details...</div>
            </div>
        )
    }

    return (
        <div className="container-modern py-8">
            <div className="mx-auto max-w-6xl">
                <div className="mb-6">
                    <p className="text-sm font-medium uppercase tracking-[0.2em] text-blue-600">Landlord onboarding</p>
                    <h1 className="mt-2 text-3xl font-bold text-gray-900">Landlord Verification</h1>
                    <p className="mt-2 text-gray-600">
                        Complete you identity verification, next complete your profile and go to your dashboard.
                    </p>
                </div>

                <div className="mb-8 grid gap-4 md:grid-cols-1">
                    <div className="rounded-2xl border bg-white p-5 shadow-sm">
                        <p className="text-[24px] font-bold text-lime-700">Verification Status</p>
                        <p className="mt-2 text-sm text-gray-600">
                            The current state of each verification requirement is shown below.
                        </p>
                        <div className="mt-5 space-y-3">
                            {verificationStatuses.map((item) => (
                                <div key={item.label} className="flex items-center justify-between gap-2 rounded-xl bg-gray-50 px-4 py-2">
                                    <div>
                                        <p className="text-[16px] font-medium text-gray-900">
                                            {item.label}
                                            {item.status === 'verified' && item.submittedAt ? (
                                                <span className="ml-2 text-xs text-gray-500">
                                                    {new Date(item.submittedAt).toLocaleString()}
                                                </span>
                                            ) : null}
                                        </p>
                                    </div>
                                    <span className={`rounded-full px-3 py-1 text-[16px] font-bold ${getProgressStatusClassName(item.status)}`}>
                                        {getProgressStatusLabel(item.status)}
                                    </span>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>

                <div className="grid gap-8">
                    <div className="rounded-2xl border bg-white p-6 shadow-sm">
                        <h2 className="text-xl font-semibold text-gray-900">Landlord Identification</h2>
                        <p className="mt-2 text-sm text-gray-600">
                            Select your landlord type before continuing to the identity verification form.
                        </p>

                        <div className="mt-6 space-y-3">
                            <label className={`flex items-start gap-3 rounded-xl border p-4 transition ${isTrackSelectionLocked ? 'cursor-not-allowed bg-gray-50 text-gray-500' : 'hover:border-blue-300'}`}>
                                <input
                                    type="checkbox"
                                    checked={verificationType === 'individual'}
                                    onChange={() => setVerificationType((current) => current === 'individual' ? '' : 'individual')}
                                    className="mt-1 h-4 w-4 rounded border-gray-300 text-blue-600"
                                    disabled={isTrackSelectionLocked}
                                />
                                <div>
                                    <div className="flex items-center gap-2">
                                        <p className={`font-medium ${isTrackSelectionLocked ? 'text-gray-500' : 'text-gray-900'}`}>Individual Landlord</p>
                                        {submittedVerificationTrack === 'individual' && (
                                            <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-700">{isVerificationLocked ? 'Verified' : 'Submitted'}</span>
                                        )}
                                    </div>
                                    <p className={`mt-1 text-sm ${isTrackSelectionLocked ? 'text-gray-500' : 'text-gray-600'}`}>Use this option if you are verifying as a person who owns or manages property directly.</p>
                                </div>
                            </label>

                            <label className={`flex items-start gap-3 rounded-xl border p-4 transition ${isTrackSelectionLocked ? 'cursor-not-allowed bg-gray-50 text-gray-500' : 'hover:border-blue-300'}`}>
                                <input
                                    type="checkbox"
                                    checked={verificationType === 'corporate'}
                                    onChange={() => setVerificationType((current) => current === 'corporate' ? '' : 'corporate')}
                                    className="mt-1 h-4 w-4 rounded border-gray-300 text-blue-600"
                                    disabled={isTrackSelectionLocked}
                                />
                                <div>
                                    <div className="flex items-center gap-2">
                                        <p className={`font-medium ${isTrackSelectionLocked ? 'text-gray-500' : 'text-gray-900'}`}>Corporate Landlord</p>
                                        {submittedVerificationTrack === 'corporate' && (
                                            <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-700">{isVerificationLocked ? 'Verified' : 'Submitted'}</span>
                                        )}
                                    </div>
                                    <p className={`mt-1 text-sm ${isTrackSelectionLocked ? 'text-gray-500' : 'text-gray-600'}`}>Use this option if the property is managed by a registered company or corporate entity.</p>
                                </div>
                            </label>
                        </div>

                        <button
                            type="button"
                            onClick={() => navigate(`/landlord/verification/identity?type=${verificationType}`)}
                            disabled={!verificationType || isTrackSelectionLocked}
                            className="mt-6 btn btn-primary w-full py-3 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                            {isVerificationLocked ? 'Identification Verified' : isTrackSelectionLocked ? 'Identification Submitted' : 'Verify Identification'}
                        </button>
                    </div>
                </div>

                <div className="mt-10 rounded-2xl bg-blue-50 p-6">
                    <h3 className="text-lg font-semibold text-blue-900">Steps</h3>
                    <div className="mt-4 grid gap-4 md:grid-cols-5">
                        <div className="rounded-xl bg-white px-4 py-3 shadow-sm">
                            <p className="text-sm font-medium text-blue-600">1. Verify Email</p>
                            <p className="mt-1 text-sm text-gray-700">Your email has been verified with OTP.</p>
                        </div>
                        <div className="rounded-xl bg-white px-4 py-3 shadow-sm">
                            <p className="text-sm font-medium text-blue-600">2. Select verification type</p>
                            <p className="mt-1 text-sm text-gray-700">Select your landlord type on this page.</p>
                        </div>
                        <div className="rounded-xl bg-white px-4 py-3 shadow-sm">
                            <p className="text-sm font-medium text-blue-600">3. Provide credentials</p>
                            <p className="mt-1 text-sm text-gray-700">Complete identification form and upload ID documents.</p>
                        </div>
                        <div className="rounded-xl bg-white px-4 py-3 shadow-sm">
                            <p className="text-sm font-medium text-blue-600">4. Complete Profile</p>
                            <p className="mt-1 text-sm text-gray-700">Complete your profile, lets get to know you.</p>
                        </div>
                        <div className="rounded-xl bg-white px-4 py-3 shadow-sm">
                            <p className="text-sm font-medium text-blue-600">5. List Property</p>
                            <p className="mt-1 text-sm text-gray-700">Create listings with prove of ownership or right to manage property.</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}
