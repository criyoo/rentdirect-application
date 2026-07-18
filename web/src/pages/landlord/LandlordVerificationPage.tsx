import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
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

const propertyDocumentOptions = [
    'Certificate of Occupancy (C of O)',
    "Governor's Consent",
    'Deed of Assignment',
    'Registered Survey Plan',
    'Deed of Conveyance',
    'Title Document',
    'Property Tax Receipt',
    'Land Use Charge Receipt',
    'Purchase Agreement',
    'Allocation Letter',
    'Mortgage Documents',
] as const

function normalizeResults<T>(payload: T[] | PaginatedResponse<T> | undefined): T[] {
    if (!payload) {
        return []
    }
    if (Array.isArray(payload)) {
        return payload
    }
    return Array.isArray(payload.results) ? payload.results : []
}

function parseErrorMessage(error: any, fallback: string): string {
    if (typeof error?.response?.data === 'string') {
        return error.response.data
    }
    if (error?.response?.data?.detail) {
        return error.response.data.detail
    }
    if (typeof error?.response?.data === 'object') {
        const firstError = Object.values(error.response.data)[0]
        if (Array.isArray(firstError) && firstError[0]) {
            return String(firstError[0])
        }
        if (typeof firstError === 'string') {
            return firstError
        }
    }
    return error?.message || fallback
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
    const queryClient = useQueryClient()
    const [verificationType, setVerificationType] = useState<LandlordVerificationType | ''>('')
    const [propertyFiles, setPropertyFiles] = useState<File[]>([])
    const [selectedPropertyDocumentTypes, setSelectedPropertyDocumentTypes] = useState<string[]>([])
    const [requestInPersonPropertyVerification, setRequestInPersonPropertyVerification] = useState(false)

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

    const documents = normalizeResults(documentResponse)
    const identificationDocuments = useMemo(
        () => documents.filter((document) => document.title.startsWith('Landlord Identification:')),
        [documents],
    )
    const propertyDocuments = useMemo(
        () => documents.filter((document) => document.title.startsWith('Property Document:')),
        [documents],
    )

    const landlordVerificationProfile = useMemo(() => {
        if (me?.landlord_verification_profile && typeof me.landlord_verification_profile === 'object') {
            return me.landlord_verification_profile as Record<string, any>
        }
        return {}
    }, [me?.landlord_verification_profile])

    const storedPropertySubmission = landlordVerificationProfile.property_document_submission
    const submittedVerificationTrack = me?.landlord_verification_type && identificationDocuments.length > 0
        ? me.landlord_verification_type
        : ''
    const isTrackSelectionLocked = Boolean(submittedVerificationTrack)
    const propertyDocumentsSubmitted = propertyDocuments.length > 0 || Boolean(storedPropertySubmission?.submitted_at)
    const isPropertyFileUploadDisabled = propertyDocumentsSubmitted || requestInPersonPropertyVerification
    const inPersonVerificationMessage = 'Verification notification has been sent to Rentdirect, an agent will visit for in-person verification of the property documents'

    useEffect(() => {
        if (me?.landlord_verification_type === 'individual' || me?.landlord_verification_type === 'corporate') {
            setVerificationType(me.landlord_verification_type)
        }
    }, [me?.landlord_verification_type])

    useEffect(() => {
        if (!storedPropertySubmission) {
            return
        }

        const nextSelectedTypes = Array.isArray(storedPropertySubmission.document_types)
            ? storedPropertySubmission.document_types.filter((value: unknown): value is string => typeof value === 'string')
            : []

        setSelectedPropertyDocumentTypes(nextSelectedTypes)
        setRequestInPersonPropertyVerification(Boolean(storedPropertySubmission.in_person_verification_requested))
    }, [storedPropertySubmission])

    const submitPropertyDocuments = useMutation({
        mutationFn: async () => {
            if (propertyDocumentsSubmitted) {
                throw new Error('Property documents have already been submitted.')
            }

            if (!requestInPersonPropertyVerification && selectedPropertyDocumentTypes.length === 0) {
                throw new Error('Select at least one property document option before submitting for verification.')
            }

            if (!requestInPersonPropertyVerification && propertyFiles.length < selectedPropertyDocumentTypes.length) {
                throw new Error('The number of uploaded documents must be equal to or greater than the number of document options selected.')
            }

            const documentIds = propertyDocuments.map((document) => document.id)

            for (const file of propertyFiles) {
                const formData = new FormData()
                const selectedTypesLabel = selectedPropertyDocumentTypes.length > 0
                    ? selectedPropertyDocumentTypes.join(', ')
                    : 'In-Person Verification Request'
                formData.append('title', `Property Document: ${selectedTypesLabel} - ${file.name}`)
                formData.append('file', file)

                const response = await api.post<UploadedDocument>('/documents', formData, {
                    headers: {
                        'Content-Type': 'multipart/form-data',
                    },
                })

                documentIds.push(response.data.id)
            }

            await api.post('/landlord-verification-requests/submit', {
                document_ids: [...new Set(documentIds)],
                request_type: 'property_documents',
                physical_property_status: requestInPersonPropertyVerification ? 'pending' : 'unverified',
            })

            await api.patch('/users/me', {
                landlord_verification_profile: {
                    ...landlordVerificationProfile,
                    property_document_submission: {
                        document_types: selectedPropertyDocumentTypes,
                        in_person_verification_requested: requestInPersonPropertyVerification,
                        submitted_at: new Date().toISOString(),
                        uploaded_document_count: propertyFiles.length,
                    },
                },
            })
        },
        onSuccess: async () => {
            await Promise.all([
                queryClient.invalidateQueries({ queryKey: ['documents', 'me'] }),
                queryClient.invalidateQueries({ queryKey: ['verification', 'status'] }),
                queryClient.invalidateQueries({ queryKey: ['users', 'me'] }),
            ])
            setPropertyFiles([])
            alert('Property documents submitted successfully.')
        },
        onError: (error: any) => {
            alert(parseErrorMessage(error, 'Failed to submit property documents.'))
        },
    })

    const identificationStarted = Boolean(me?.landlord_verification_type || identificationDocuments.length > 0)
    const identificationStatus = verificationStatus?.identification?.status || 'unverified'
    const propertyDocumentStatus = verificationStatus?.property_documents?.status || 'unverified'
    const physicalPropertyStatus = verificationStatus?.physical_property?.status || 'unverified'
    const verificationStatuses = [
        {
            label: 'Identity Verification',
            status: identificationStatus,
            submittedAt: verificationStatus?.identification?.submitted_at,
        },
        {
            label: 'Property Document Verification',
            status: propertyDocumentStatus,
            submittedAt: verificationStatus?.property_documents?.submitted_at,
        },
        {
            label: 'Physical Property Verification',
            status: physicalPropertyStatus,
            submittedAt: verificationStatus?.physical_property?.submitted_at,
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

                <div className="grid gap-8 lg:grid-cols-2">
                    <div className="rounded-2xl border bg-white p-6 shadow-sm">
                        <h2 className="text-xl font-semibold text-gray-900">Landlord Identification</h2>
                        <p className="mt-2 text-sm text-gray-600">
                            Select your landlord type before continuing to the identity verification form.
                        </p>

                        <div className="mt-6 space-y-3">
                            <label className="flex items-start gap-3 rounded-xl border p-4 transition hover:border-blue-300">
                                <input
                                    type="checkbox"
                                    checked={verificationType === 'individual'}
                                    onChange={() => setVerificationType((current) => current === 'individual' ? '' : 'individual')}
                                    className="mt-1 h-4 w-4 rounded border-gray-300 text-blue-600"
                                    disabled={isTrackSelectionLocked}
                                />
                                <div>
                                    <div className="flex items-center gap-2">
                                        <p className="font-medium text-gray-900">Individual Landlord</p>
                                        {submittedVerificationTrack === 'individual' && (
                                            <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-700">Submitted</span>
                                        )}
                                    </div>
                                    <p className="mt-1 text-sm text-gray-600">Use this option if you are verifying as a person who owns or manages property directly.</p>
                                </div>
                            </label>

                            <label className="flex items-start gap-3 rounded-xl border p-4 transition hover:border-blue-300">
                                <input
                                    type="checkbox"
                                    checked={verificationType === 'corporate'}
                                    onChange={() => setVerificationType((current) => current === 'corporate' ? '' : 'corporate')}
                                    className="mt-1 h-4 w-4 rounded border-gray-300 text-blue-600"
                                    disabled={isTrackSelectionLocked}
                                />
                                <div>
                                    <div className="flex items-center gap-2">
                                        <p className="font-medium text-gray-900">Corporate Landlord</p>
                                        {submittedVerificationTrack === 'corporate' && (
                                            <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-700">Submitted</span>
                                        )}
                                    </div>
                                    <p className="mt-1 text-sm text-gray-600">Use this option if the property is managed by a registered company or corporate entity.</p>
                                </div>
                            </label>
                        </div>

                        <button
                            type="button"
                            onClick={() => navigate(`/landlord/verification/identity?type=${verificationType}`)}
                            disabled={!verificationType || isTrackSelectionLocked}
                            className="mt-6 btn btn-primary w-full py-3 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                            {isTrackSelectionLocked ? 'Identification Submitted' : 'Verify Identification'}
                        </button>
                    </div>

                    <div className="rounded-2xl border bg-white p-6 shadow-sm">
                        <div className="flex items-start justify-between gap-3">
                            <div>
                                <h2 className="text-xl font-semibold text-gray-900">Property Documents</h2>
                                <p className="mt-2 text-sm text-gray-600">
                                    Upload one or more title documents, or request in-person verification by a lawyer for a small fee.
                                </p>
                            </div>
                        </div>

                        <div className="mt-6 space-y-3">
                            {propertyDocumentOptions.map((option) => (
                                <label key={option} className="flex items-center gap-3 rounded-xl border px-4 py-2">
                                    <input
                                        type="checkbox"
                                        checked={selectedPropertyDocumentTypes.includes(option)}
                                        disabled={propertyDocumentsSubmitted}
                                        onChange={(event) => {
                                            const checked = event.target.checked
                                            setSelectedPropertyDocumentTypes((current) => {
                                                if (checked) {
                                                    return current.includes(option) ? current : [...current, option]
                                                }
                                                return current.filter((value) => value !== option)
                                            })
                                        }}
                                        className="h-3 w-3 rounded border-gray-300 text-blue-600"
                                    />
                                    <span className="text-[13px] font-medium text-gray-800">{option}</span>
                                </label>
                            ))}

                            <label className="flex items-start gap-3 rounded-xl border border-blue-200 bg-blue-50 px-4 py-3">
                                <input
                                    type="checkbox"
                                    checked={requestInPersonPropertyVerification}
                                    disabled={propertyDocumentsSubmitted}
                                    onChange={(event) => {
                                        const checked = event.target.checked
                                        setRequestInPersonPropertyVerification(checked)
                                        if (checked) {
                                            setPropertyFiles([])
                                        }
                                    }}
                                    className="mt-1 h-4 w-4 rounded border-gray-300 text-blue-600"
                                />
                                <div>
                                    <p className="text-sm font-semibold text-blue-900">Get an agent/lawyer to verify in person</p>
                                    <p className="mt-1 text-sm text-blue-800">
                                        {requestInPersonPropertyVerification
                                            ? inPersonVerificationMessage
                                            : 'Available for a small fee if you prefer in-person property document verification.'}
                                    </p>
                                </div>
                            </label>
                        </div>

                        <div className="mt-6">
                            <label className={`block text-sm font-medium mb-2 ${isPropertyFileUploadDisabled ? 'text-gray-400' : 'text-gray-700'}`}>
                                Choose files
                            </label>
                            <input
                                key={isPropertyFileUploadDisabled ? 'property-file-upload-disabled' : 'property-file-upload-enabled'}
                                type="file"
                                multiple
                                accept=".pdf,.jpg,.jpeg,.png"
                                onChange={(event) => setPropertyFiles(Array.from(event.target.files || []))}
                                disabled={isPropertyFileUploadDisabled}
                                className={`${isPropertyFileUploadDisabled ? 'disabled:file:text-gray-500' : 'file:text-green-700'} block w-full text-sm file:mr-4 file:rounded-full file:border-0 file:bg-green-50 file:px-4 file:py-2 file:font-semibold hover:file:bg-green-100 disabled:cursor-not-allowed disabled:text-gray-400 disabled:file:bg-gray-100 disabled:hover:file:bg-gray-100`}
                            />
                        </div>

                        {propertyFiles.length > 0 && (
                            <ul className="mt-4 space-y-2 text-sm text-gray-600">
                                {propertyFiles.map((file) => (
                                    <li key={`${file.name}-${file.size}`} className="flex items-center justify-between rounded-lg bg-gray-50 px-3 py-2">
                                        <span>{file.name}</span>
                                        <span>{(file.size / 1024 / 1024).toFixed(2)} MB</span>
                                    </li>
                                ))}
                            </ul>
                        )}

                        {propertyDocumentsSubmitted && (
                            <p className="mt-4 text-sm text-green-700">
                                {storedPropertySubmission?.in_person_verification_requested
                                    ? inPersonVerificationMessage
                                    : 'Property verification has already been submitted for this landlord account.'}
                            </p>
                        )}

                        <button
                            type="button"
                            onClick={() => submitPropertyDocuments.mutate()}
                            disabled={propertyDocumentsSubmitted || submitPropertyDocuments.isPending}
                            className="mt-6 btn btn-outline w-full py-3 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                            {propertyDocumentsSubmitted
                                ? 'Property Documents Submitted'
                                : submitPropertyDocuments.isPending
                                    ? 'Submitting...'
                                    : requestInPersonPropertyVerification
                                        ? 'Submit In-Person Verification Request'
                                        : 'Upload Property Documents'}
                        </button>
                    </div>
                </div>

                <div className="mt-10 rounded-2xl bg-blue-50 p-6">
                    <h3 className="text-lg font-semibold text-blue-900">Next Steps</h3>
                    <div className="mt-4 grid gap-4 md:grid-cols-4">
                        <div className="rounded-xl bg-white px-4 py-3 shadow-sm">
                            <p className="text-sm font-medium text-blue-600">1. OTP</p>
                            <p className="mt-1 text-sm text-gray-700">Your email has been verified.</p>
                        </div>
                        <div className="rounded-xl bg-white px-4 py-3 shadow-sm">
                            <p className="text-sm font-medium text-blue-600">2. Verification</p>
                            <p className="mt-1 text-sm text-gray-700">Select your landlord type on this page.</p>
                        </div>
                        <div className="rounded-xl bg-white px-4 py-3 shadow-sm">
                            <p className="text-sm font-medium text-blue-600">3. Identity</p>
                            <p className="mt-1 text-sm text-gray-700">Complete the identification form and upload ID documents.</p>
                        </div>
                        <div className="rounded-xl bg-white px-4 py-3 shadow-sm">
                            <p className="text-sm font-medium text-blue-600">4. Profile</p>
                            <p className="mt-1 text-sm text-gray-700">Finish your profile, then continue to your dashboard.</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}
