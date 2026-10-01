import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { HiCheckCircle, HiDocumentDownload, HiUpload } from 'react-icons/hi'

import { useAppPopup } from '@/contexts/AppPopupContext'
import DashboardBackButton from '@/components/DashboardBackButton'
import { api, extractApiErrorMessage, resolveMediaUrl } from '@/lib/api'
import { downloadInspectionPdf } from '@/lib/inspectionReports'
import { formatCurrencyWithSymbol } from '@/utils/currency'
import { InspectionChecklistSchema, InspectionField, PropertyInspection } from '@/types'

type UploadedDocument = {
    id: string
    title: string
    file_url?: string
}

type ResponsesState = Record<string, unknown>

function formatResponseValue(field: InspectionField, value: unknown): string {
    if (value === undefined || value === null || value === '') return '—'
    if (field.type === 'checkbox') return value ? 'Yes' : 'No'
    if (Array.isArray(value)) {
        const labels = value.map((item) => {
            const option = field.options?.find((candidate) => candidate.value === item)
            return option?.label || String(item).replace(/_/g, ' ')
        })
        return labels.join(', ') || '—'
    }
    const option = field.options?.find((candidate) => candidate.value === value)
    return option?.label || String(value).replace(/_/g, ' ')
}

export default function AgentInspectionPage() {
    const { inspectionId } = useParams()
    const { alert } = useAppPopup()
    const queryClient = useQueryClient()
    const [responses, setResponses] = useState<ResponsesState>({})
    const [evidenceIds, setEvidenceIds] = useState<string[]>([])
    const [error, setError] = useState('')
    const [isUploading, setIsUploading] = useState(false)

    const { data: checklist } = useQuery({
        queryKey: ['agent-inspections', 'checklist'],
        queryFn: async () => (await api.get<InspectionChecklistSchema>('/agent-inspections/checklist')).data,
        staleTime: Infinity,
    })

    const { data: inspection, isLoading } = useQuery({
        queryKey: ['agent-inspections', inspectionId],
        queryFn: async () => (await api.get<PropertyInspection>(`/agent-inspections/${inspectionId}`)).data,
        enabled: Boolean(inspectionId),
    })

    const isSubmitted = inspection?.status === 'submitted'

    useEffect(() => {
        if (!inspection) return
        setResponses((inspection.responses || {}) as ResponsesState)
        setEvidenceIds((inspection.evidence_documents || []).map((document) => document.id))
    }, [inspection])

    const updateInspection = useMutation({
        mutationFn: async (payload: { responses?: ResponsesState; evidence_document_ids?: string[] }) =>
            (await api.patch<PropertyInspection>(`/agent-inspections/${inspectionId}`, payload)).data,
        onSuccess: async (saved) => {
            setResponses((saved.responses || {}) as ResponsesState)
            setEvidenceIds((saved.evidence_documents || []).map((document) => document.id))
            await queryClient.invalidateQueries({ queryKey: ['agent-inspections', inspectionId] })
            await queryClient.invalidateQueries({ queryKey: ['agents', 'dashboard'] })
        },
    })

    const submitInspection = useMutation({
        mutationFn: async () =>
            (await api.post<PropertyInspection>(`/agent-inspections/${inspectionId}/submit`, { responses })).data,
        onSuccess: async () => {
            await queryClient.invalidateQueries({ queryKey: ['agent-inspections', inspectionId] })
            await queryClient.invalidateQueries({ queryKey: ['agents', 'dashboard'] })
            await alert('Inspection submitted and signed off.', { title: 'Inspection complete' })
        },
        onError: async (mutationError) => {
            await alert(extractApiErrorMessage(mutationError, 'Unable to submit this inspection.'), { title: 'Submission failed', variant: 'warning' })
        },
    })

    const setFieldValue = (key: string, value: unknown) => {
        setResponses((current) => ({ ...current, [key]: value }))
    }

    const toggleMultiValue = (key: string, value: string) => {
        const sentinelValues = new Set(['none', 'none_observed'])
        setResponses((current) => {
            const existing = Array.isArray(current[key]) ? (current[key] as string[]) : []
            if (existing.includes(value)) {
                return { ...current, [key]: existing.filter((item) => item !== value) }
            }
            if (sentinelValues.has(value)) {
                return { ...current, [key]: [value] }
            }
            return { ...current, [key]: [...existing.filter((item) => !sentinelValues.has(item)), value] }
        })
    }

    const handleEvidenceUpload = async (files: FileList | null) => {
        if (!files || files.length === 0) return
        setIsUploading(true)
        setError('')
        try {
            const nextIds = [...evidenceIds]
            for (const file of Array.from(files)) {
                const formData = new FormData()
                formData.append('title', `Inspection evidence: ${file.name}`)
                formData.append('file', file)
                const response = await api.post<UploadedDocument>('/documents', formData, {
                    headers: { 'Content-Type': 'multipart/form-data' },
                })
                nextIds.push(response.data.id)
            }
            const saved = await updateInspection.mutateAsync({ evidence_document_ids: nextIds })
            setEvidenceIds((saved.evidence_documents || []).map((document) => document.id))
        } catch (uploadError) {
            setError(extractApiErrorMessage(uploadError, 'Unable to upload evidence.'))
        } finally {
            setIsUploading(false)
        }
    }

    const handleSaveDraft = async () => {
        setError('')
        try {
            await updateInspection.mutateAsync({ responses, evidence_document_ids: evidenceIds })
            await alert('Draft saved.', { title: 'Inspection' })
        } catch (saveError) {
            setError(extractApiErrorMessage(saveError, 'Unable to save draft.'))
        }
    }

    const handleSubmit = async () => {
        setError('')
        try {
            await updateInspection.mutateAsync({ responses, evidence_document_ids: evidenceIds })
            await submitInspection.mutateAsync()
        } catch {
            // Errors are surfaced via popup already.
        }
    }

    const requiredFieldCount = useMemo(
        () => (checklist?.sections || []).flatMap((section) => section.fields).filter((field) => field.required).length,
        [checklist],
    )
    const completedRequiredCount = useMemo(() => {
        if (!checklist) return 0
        return checklist.sections
            .flatMap((section) => section.fields)
            .filter((field) => {
                if (!field.required) return false
                const value = responses[field.key]
                if (field.type === 'checkbox') return value === true
                if (Array.isArray(value)) return value.length > 0
                return value !== undefined && value !== null && String(value).trim() !== ''
            }).length
    }, [checklist, responses])

    if (isLoading || !inspection) {
        return (
            <div className="agent-theme min-h-screen bg-gradient-to-br from-emerald-50 via-white to-green-50 flex items-center justify-center">
                <div className="text-center">
                    <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-emerald-600 mx-auto"></div>
                    <p className="mt-4 text-gray-600">Loading inspection…</p>
                </div>
            </div>
        )
    }

    const analysis = (inspection.analysis || {}) as Record<string, unknown>

    const renderField = (field: InspectionField) => {
        const value = responses[field.key]
        const label = (
            <span className="form-label">
                {field.label}
                {field.required ? ' *' : ''}
            </span>
        )

        if (field.type === 'select') {
            return (
                <div key={field.key}>
                    <label htmlFor={`field-${field.key}`}>{label}</label>
                    <select
                        id={`field-${field.key}`}
                        className="form-input"
                        required={field.required}
                        value={typeof value === 'string' ? value : ''}
                        onChange={(event) => setFieldValue(field.key, event.target.value)}
                        disabled={isSubmitted}
                    >
                        <option value="">Select</option>
                        {(field.options || []).map((option) => (
                            <option key={option.value} value={option.value}>{option.label}</option>
                        ))}
                    </select>
                </div>
            )
        }

        if (field.type === 'multiselect') {
            const selected = Array.isArray(value) ? (value as string[]) : []
            return (
                <div key={field.key}>
                    <span className="form-label">{field.label}{field.required ? ' *' : ''}</span>
                    <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
                        {(field.options || []).map((option) => (
                            <label key={option.value} className="flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-700">
                                <input
                                    type="checkbox"
                                    checked={selected.includes(option.value)}
                                    onChange={() => toggleMultiValue(field.key, option.value)}
                                    disabled={isSubmitted}
                                    className="h-4 w-4 rounded border-gray-300 text-emerald-600 accent-emerald-600"
                                />
                                {option.label}
                            </label>
                        ))}
                    </div>
                </div>
            )
        }

        if (field.type === 'textarea') {
            return (
                <div key={field.key}>
                    <label htmlFor={`field-${field.key}`}>{label}</label>
                    <textarea
                        id={`field-${field.key}`}
                        className="form-input"
                        rows={3}
                        required={field.required}
                        value={typeof value === 'string' ? value : ''}
                        onChange={(event) => setFieldValue(field.key, event.target.value)}
                        disabled={isSubmitted}
                    />
                </div>
            )
        }

        if (field.type === 'number') {
            return (
                <div key={field.key}>
                    <label htmlFor={`field-${field.key}`}>{label}</label>
                    <input
                        id={`field-${field.key}`}
                        type="number"
                        step="any"
                        className="form-input"
                        required={field.required}
                        value={typeof value === 'number' || typeof value === 'string' ? String(value) : ''}
                        onChange={(event) => setFieldValue(field.key, event.target.value === '' ? '' : Number(event.target.value))}
                        disabled={isSubmitted}
                    />
                </div>
            )
        }

        if (field.type === 'checkbox') {
            return (
                <label key={field.key} className="flex items-start gap-3 rounded-lg border border-gray-200 p-3">
                    <input
                        type="checkbox"
                        checked={value === true}
                        onChange={(event) => setFieldValue(field.key, event.target.checked)}
                        disabled={isSubmitted}
                        className="mt-1 h-5 w-5 rounded border-gray-300 text-emerald-600 accent-emerald-600"
                    />
                    <span className="text-sm text-gray-700">
                        {field.label}
                        {field.required ? ' *' : ''}
                    </span>
                </label>
            )
        }

        return (
            <div key={field.key}>
                <label htmlFor={`field-${field.key}`}>{label}</label>
                <input
                    id={`field-${field.key}`}
                    type="text"
                    className="form-input"
                    required={field.required}
                    value={typeof value === 'string' ? value : ''}
                    onChange={(event) => setFieldValue(field.key, event.target.value)}
                    disabled={isSubmitted}
                />
            </div>
        )
    }

    return (
        <div className="agent-theme min-h-screen bg-gradient-to-br from-emerald-50 via-white to-green-50">
            <div className="container-modern py-8">
                <div className="mb-5">
                    <DashboardBackButton to="/agents/dashboard" label="Back to dashboard" />
                </div>

                <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
                    <div>
                        <h1 className="text-3xl font-bold text-gray-900">Property Inspection Checklist</h1>
                        <p className="mt-1 text-sm text-gray-600">
                            {inspection.listing_title} — {[inspection.listing_address, inspection.listing_city, inspection.listing_state].filter(Boolean).join(', ')}
                        </p>
                        <p className="mt-1 text-sm text-gray-500">
                            Landlord: {inspection.landlord_name || '—'} • Earning: {formatCurrencyWithSymbol(Number(inspection.earning_amount || 0))} • Payout: {inspection.payout_status_display || inspection.payout_status}
                        </p>
                    </div>
                    <div className="flex items-center gap-2">
                        <span className={`badge ${isSubmitted ? 'badge-success' : 'badge-warning'}`}>
                            {inspection.status_display || inspection.status}
                        </span>
                        {isSubmitted && (
                            <button type="button" onClick={() => downloadInspectionPdf(inspection.id)} className="btn btn-primary px-4 py-2 text-sm">
                                <HiDocumentDownload className="mr-1 h-4 w-4" />
                                Download PDF
                            </button>
                        )}
                    </div>
                </div>

                {error && (
                    <div className="mb-6 rounded-lg bg-red-50 p-4 text-sm text-red-700">{error}</div>
                )}

                {isSubmitted && (
                    <div className="mb-8 card p-6">
                        <div className="mb-3 flex items-center gap-2">
                            <HiCheckCircle className="h-6 w-6 text-green-600" />
                            <h2 className="text-xl font-semibold text-gray-900">Inspection submitted</h2>
                        </div>
                        <div className="grid gap-2 text-sm sm:grid-cols-2">
                            <p><span className="text-gray-500">Overall status:</span> <span className="font-medium">{String(analysis.overall_status || inspection.overall_status || '—').replace(/_/g, ' ')}</span></p>
                            <p><span className="text-gray-500">Completed items:</span> <span className="font-medium">{String(analysis.completed_item_count ?? '—')} / {String(analysis.total_item_count ?? '—')}</span></p>
                            <p><span className="text-gray-500">Submitted:</span> <span className="font-medium">{inspection.submitted_at ? new Date(inspection.submitted_at).toLocaleString() : '—'}</span></p>
                            <p><span className="text-gray-500">Critical red flags:</span> <span className="font-medium">{Array.isArray(analysis.critical_red_flags) && analysis.critical_red_flags.length ? (analysis.critical_red_flags as string[]).join(', ').replace(/_/g, ' ') : 'None observed'}</span></p>
                        </div>
                        {Boolean(analysis.final_recommendation) && (
                            <p className="mt-3 text-sm"><span className="text-gray-500">Final recommendation:</span> {String(analysis.final_recommendation)}</p>
                        )}
                    </div>
                )}

                {!isSubmitted && (
                    <p className="mb-6 text-sm text-gray-600">
                        Required items completed: {completedRequiredCount} / {requiredFieldCount}
                    </p>
                )}

                <div className="space-y-6">
                    {(checklist?.sections || []).map((section) => (
                        <div key={section.key} className="card p-6">
                            <h2 className="mb-4 text-xl font-semibold text-gray-900">{section.title}</h2>
                            <div className="grid gap-4 md:grid-cols-2">
                                {section.fields.map((field) => (
                                    <div key={field.key} className={field.type === 'textarea' || field.type === 'multiselect' ? 'md:col-span-2' : ''}>
                                        {isSubmitted ? (
                                            <div className="rounded-lg border border-gray-100 bg-gray-50 p-3">
                                                <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">{field.label}</p>
                                                <p className="mt-1 text-sm text-gray-900">{formatResponseValue(field, responses[field.key])}</p>
                                            </div>
                                        ) : (
                                            renderField(field)
                                        )}
                                    </div>
                                ))}
                            </div>
                        </div>
                    ))}

                    <div className="card p-6">
                        <h2 className="mb-4 text-xl font-semibold text-gray-900">Evidence documents</h2>
                        {isSubmitted ? (
                            (inspection.evidence_documents || []).length > 0 ? (
                                <ul className="list-disc space-y-1 pl-5 text-sm text-gray-700">
                                    {(inspection.evidence_documents || []).map((document) => (
                                        <li key={document.id}>
                                            {document.file_url ? (
                                                <a href={resolveMediaUrl(document.file_url)} target="_blank" rel="noreferrer" className="text-emerald-600 hover:underline">
                                                    {document.title}
                                                </a>
                                            ) : (
                                                document.title
                                            )}
                                        </li>
                                    ))}
                                </ul>
                            ) : (
                                <p className="text-sm text-gray-500">No evidence documents uploaded.</p>
                            )
                        ) : (
                            <>
                                <label className="btn btn-outline inline-flex cursor-pointer items-center gap-2 px-4 py-2 text-sm">
                                    <HiUpload className="h-4 w-4" />
                                    {isUploading ? 'Uploading…' : 'Upload evidence'}
                                    <input
                                        type="file"
                                        multiple
                                        className="hidden"
                                        disabled={isUploading}
                                        onChange={(event) => {
                                            void handleEvidenceUpload(event.target.files)
                                            event.target.value = ''
                                        }}
                                    />
                                </label>
                                {(inspection.evidence_documents || []).length > 0 && (
                                    <ul className="mt-4 list-disc space-y-1 pl-5 text-sm text-gray-700">
                                        {(inspection.evidence_documents || []).map((document) => (
                                            <li key={document.id}>{document.title}</li>
                                        ))}
                                    </ul>
                                )}
                            </>
                        )}
                    </div>
                </div>

                {!isSubmitted && (
                    <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:justify-end">
                        <button
                            type="button"
                            onClick={handleSaveDraft}
                            disabled={updateInspection.isPending || isUploading}
                            className="btn btn-outline px-6 py-3 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                            {updateInspection.isPending ? 'Saving…' : 'Save draft'}
                        </button>
                        <button
                            type="button"
                            onClick={handleSubmit}
                            disabled={submitInspection.isPending || updateInspection.isPending || isUploading}
                            className="btn btn-primary px-6 py-3 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                            {submitInspection.isPending ? 'Submitting…' : 'Submit sign-off'}
                        </button>
                    </div>
                )}
            </div>
        </div>
    )
}
