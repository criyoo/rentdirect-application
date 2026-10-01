import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { HiCheckCircle, HiDocumentText, HiDownload, HiExclamation, HiPrinter, HiScale, HiShieldCheck } from 'react-icons/hi'
import { useNavigate, useParams } from 'react-router-dom'

import DashboardBackButton from '@/components/DashboardBackButton'
import LegalDocumentRenderer from '@/components/LegalDocumentRenderer'
import { useAppPopup } from '@/contexts/AppPopupContext'
import { useAuth } from '@/hooks/useAuth'
import { api, extractApiErrorMessage } from '@/lib/api'
import { ServicePayment } from '@/types'
import { formatCurrencyWithSymbol } from '@/utils/currency'

declare global {
    namespace JSX {
        interface IntrinsicElements {
            'docuseal-form': React.DetailedHTMLProps<React.HTMLAttributes<HTMLElement>, HTMLElement> & { 'data-src'?: string }
        }
    }
}

type AgreementFieldOption = { value: string; label: string }

type AgreementField = {
    path: string
    section: string
    label: string
    type: 'text' | 'textarea' | 'number' | 'date' | 'select' | 'checkbox'
    required: boolean
    options?: AgreementFieldOption[]
    help_text?: string
}

type AgreementBooking = {
    id: string
    listing_title: string
    tenant_name: string
    tenant_email: string
    start_date: string | null
    end_date: string | null
    status: string
    rent_amount: number
}

type TenancyAgreementRecord = {
    id: string
    booking_id: string
    version: number
    template_version: string
    status: string
    agreement_data: Record<string, any>
    rendered_content: string
    document_hash: string
    generated_at: string | null
    finalised_at: string | null
}

type AgreementOptions = {
    free: {
        label: string
        amount: number
        landlord_pays: boolean
    }
    lawyer: {
        label: string
        fee_rate: string
        amount: number
        landlord_pays: boolean
        payment: ServicePayment | null
    }
}

type TenancyAgreementWorkspace = {
    booking: AgreementBooking
    data: Record<string, any>
    fields: AgreementField[]
    missing_fields: string[]
    can_generate: boolean
    latest_agreement: TenancyAgreementRecord | null
    agreement_options?: AgreementOptions | null
    viewer_role?: 'landlord' | 'tenant' | null
    docuseal?: {
        enabled?: boolean
        submission_id?: number | null
        status?: string
        embed_src?: string
        documents?: { name?: string; url?: string }[]
    }
    signatures?: Record<string, any>
    signed_by_tenant?: boolean
    signed_by_landlord?: boolean
    can_sign?: boolean
}

function getPathValue(source: any, path: string) {
    return path.split('.').reduce<any>((current, key) => (
        current && typeof current === 'object' ? current[key] : undefined
    ), source)
}

function setPathValue(source: Record<string, any>, path: string, value: unknown): Record<string, any> {
    const keys = path.split('.')
    const clone: Record<string, any> = { ...source }
    let cursor = clone
    keys.slice(0, -1).forEach((key) => {
        const next = cursor[key]
        cursor[key] = next && typeof next === 'object' ? { ...next } : {}
        cursor = cursor[key]
    })
    cursor[keys[keys.length - 1]] = value
    return clone
}

function isBlankValue(value: unknown): boolean {
    if (value === null || value === undefined) return true
    if (typeof value === 'string') return value.trim() === ''
    return false
}

const POSITIVE_NUMBER_PATHS = new Set([
    'property.inspectionNoticeHours',
    'fees.securityDepositRefundDays',
    'maintenance.maximumRestorationDays',
    'dispute.arbitratorCount',
])

const ARBITRATION_REQUIRED_PATHS = new Set([
    'dispute.arbitrationVenue',
    'dispute.arbitratorCount',
    'dispute.appointingAuthority',
])

function isFieldRequired(field: AgreementField, data: Record<string, any>): boolean {
    if (field.required) return true
    if (field.path === 'payments.latePaymentInterestRate') {
        return getPathValue(data, 'payments.latePaymentInterestEnabled') === true
    }
    if (ARBITRATION_REQUIRED_PATHS.has(field.path)) {
        return getPathValue(data, 'dispute.arbitrationEnabled') === true
    }
    if (field.path === 'commercial.businessDescription') {
        return Boolean(getPathValue(data, 'tenancy.isCommercial'))
    }
    return false
}

function isFieldBlank(field: AgreementField, value: unknown): boolean {
    if (field.type === 'number') {
        if (value === null || value === undefined || value === '') return true
        const numeric = Number(value)
        if (Number.isNaN(numeric)) return false
        return POSITIVE_NUMBER_PATHS.has(field.path) && numeric <= 0
    }
    return isBlankValue(value)
}

function unresolvedMissingPaths(fields: AgreementField[], data: Record<string, any>): Set<string> {
    const missing = new Set<string>()
    fields.forEach((field) => {
        if (isFieldRequired(field, data) && isFieldBlank(field, getPathValue(data, field.path))) {
            missing.add(field.path)
        }
    })
    return missing
}

const RENT_FREQUENCY_DIVISORS: Record<string, number> = {
    yearly: 1,
    'half-yearly': 2,
    quarterly: 4,
    monthly: 12,
}

const RENT_FREQUENCY_LABELS: Record<string, string> = {
    yearly: 'per year',
    'half-yearly': 'per half-year',
    quarterly: 'per quarter',
    monthly: 'per month',
}

function formatDateLabel(value?: string | null): string {
    if (!value) return 'Not set'
    const parsed = new Date(value)
    if (Number.isNaN(parsed.getTime())) return value
    return parsed.toLocaleDateString(undefined, { day: 'numeric', month: 'long', year: 'numeric' })
}

function formatTimestampLabel(value?: string | null): string {
    if (!value) return 'Not recorded'
    const parsed = new Date(value)
    if (Number.isNaN(parsed.getTime())) return value
    return parsed.toLocaleString()
}

function DocuSealSigningForm({ src, onCompleted }: { src: string; onCompleted: () => void }) {
    const containerRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        if (!document.querySelector('script[data-docuseal-form="true"]')) {
            const script = document.createElement('script')
            script.src = 'https://cdn.docuseal.com/js/form.js'
            script.async = true
            script.dataset.docusealForm = 'true'
            document.head.appendChild(script)
        }
    }, [])

    useEffect(() => {
        const element = containerRef.current?.querySelector('docuseal-form')
        if (!element) return
        const handler = () => onCompleted()
        element.addEventListener('completed', handler)
        return () => element.removeEventListener('completed', handler)
    }, [src, onCompleted])

    return (
        <div ref={containerRef} className="min-h-[420px]">
            <docuseal-form data-src={src} />
        </div>
    )
}

function extractAgreementFieldErrors(error: any): Record<string, string> {
    const data = error?.response?.data
    const errors = data?.errors
    if (!errors || typeof errors !== 'object' || Array.isArray(errors)) return {}
    return Object.entries(errors).reduce<Record<string, string>>((accumulator, [path, value]) => {
        const message = Array.isArray(value) ? value.find(Boolean) : value
        if (typeof message === 'string' && message.trim()) accumulator[path] = message
        return accumulator
    }, {})
}

export default function TenancyAgreementPage() {
    const { bookingId } = useParams<{ bookingId: string }>()
    const { user } = useAuth()
    const { alert } = useAppPopup()
    const queryClient = useQueryClient()
    const navigate = useNavigate()
    const previewRef = useRef<HTMLDivElement>(null)
    const [formData, setFormData] = useState<Record<string, any>>({})
    const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
    const [selectedOption, setSelectedOption] = useState<'free' | 'lawyer'>('free')
    const [signatoryName, setSignatoryName] = useState('')
    const [signatoryCapacity, setSignatoryCapacity] = useState('')
    const [docusealEmbedSrc, setDocusealEmbedSrc] = useState('')

    const dashboardPath = user?.id
        ? user.role === 'tenant'
            ? `/dashboard/tenant/${user.id}`
            : `/dashboard/landlord/${user.id}`
        : '/'
    const workspaceQueryKey = ['tenancy-agreement', bookingId]

    const { data: workspace, isLoading, error } = useQuery({
        queryKey: workspaceQueryKey,
        enabled: Boolean(bookingId),
        queryFn: async () => (await api.get<TenancyAgreementWorkspace>(`/bookings/${bookingId}/tenancy-agreement`)).data,
    })

    useEffect(() => {
        if (workspace?.data) {
            setFormData(workspace.data)
            setFieldErrors({})
        }
        if (workspace?.agreement_options?.lawyer?.payment) {
            setSelectedOption('lawyer')
        }
    }, [workspace?.data, workspace?.agreement_options])

    const sections = useMemo(() => {
        const grouped = new Map<string, AgreementField[]>()
        ;(workspace?.fields || []).forEach((field) => {
            const existing = grouped.get(field.section)
            if (existing) {
                existing.push(field)
            } else {
                grouped.set(field.section, [field])
            }
        })
        return Array.from(grouped.entries()).map(([name, fields]) => ({ name, fields }))
    }, [workspace?.fields])

    const unresolvedMissingFields = useMemo(
        () => unresolvedMissingPaths(workspace?.fields || [], formData),
        [workspace?.fields, formData],
    )

    const generateAgreement = useMutation({
        mutationFn: async () => (
            await api.post<TenancyAgreementWorkspace>(`/bookings/${bookingId}/tenancy-agreement`, { data: formData })
        ).data,
        onSuccess: async (payload) => {
            queryClient.setQueryData(workspaceQueryKey, payload)
            setFormData(payload.data || {})
            setFieldErrors({})
            await alert(
                `Tenancy agreement version ${payload.latest_agreement?.version || ''} has been generated for review are shown below.`,
                { variant: 'success', title: 'Agreement generated' },
            )
        },
        onError: (mutationError: any) => {
            const nextFieldErrors = extractAgreementFieldErrors(mutationError)
            setFieldErrors(nextFieldErrors)
            void alert(
                extractApiErrorMessage(mutationError, 'The tenancy agreement could not be generated. Check the highlighted fields and try again.'),
                { variant: 'error', title: 'Generation failed' },
            )
        },
    })

    const signAgreement = useMutation({
        mutationFn: async () => (
            await api.post<TenancyAgreementWorkspace>(`/bookings/${bookingId}/tenancy-agreement/sign`, {
                signatory_name: signatoryName.trim() || user?.name || '',
                signatory_capacity: signatoryCapacity.trim(),
            })
        ).data,
        onSuccess: async (payload) => {
            queryClient.setQueryData(workspaceQueryKey, payload)
            setFormData(payload.data || {})
            await alert(
                'Your electronic signature has been recorded and the "Tenancy agreement signed?" step in the rental progress checklist is now complete.',
                { variant: 'success', title: 'Agreement signed' },
            )
        },
        onError: (mutationError: any) => {
            void alert(
                extractApiErrorMessage(mutationError, 'The agreement could not be signed electronically.'),
                { variant: 'error', title: 'Signing failed' },
            )
        },
    })

    const startDocuSealSigning = useMutation({
        mutationFn: async () => (
            await api.post<TenancyAgreementWorkspace>(`/bookings/${bookingId}/tenancy-agreement/docuseal`, {})
        ).data,
        onSuccess: (payload) => {
            queryClient.setQueryData(workspaceQueryKey, payload)
            setDocusealEmbedSrc(payload.docuseal?.embed_src || '')
            if (!payload.docuseal?.embed_src) {
                void alert('The signing session could not be started. Please refresh and try again.', {
                    variant: 'error',
                    title: 'Signing unavailable',
                })
            }
        },
        onError: (mutationError: any) => {
            void alert(
                extractApiErrorMessage(mutationError, 'Electronic signing could not be started.'),
                { variant: 'error', title: 'Signing failed' },
            )
        },
    })

    const requestLawyerService = useMutation({
        mutationFn: async () => (
            await api.post<ServicePayment>('/service-payments/request', {
                purpose: 'lawyer_tenancy',
                booking_id: bookingId,
            })
        ).data,
        onSuccess: (payment) => {
            navigate(`/service-payments/${payment.id}`)
        },
        onError: (mutationError: any) => {
            void alert(
                extractApiErrorMessage(mutationError, 'The lawyer service request could not be started.'),
                { variant: 'error', title: 'Request failed' },
            )
        },
    })

    const updateField = (path: string, value: unknown) => {
        setFormData((current) => setPathValue(current, path, value))
        setFieldErrors((current) => {
            if (!(path in current)) return current
            const next = { ...current }
            delete next[path]
            return next
        })
    }

    if (isLoading) {
        return (
            <div className="container-modern py-8">
                <div className="rounded-2xl border bg-white p-8 text-gray-600 shadow-sm">Loading tenancy agreement workspace...</div>
            </div>
        )
    }

    if (error || !workspace) {
        return (
            <div className="container-modern py-8">
                <div className="rounded-2xl border bg-white p-8 shadow-sm">
                    <h1 className="text-2xl font-semibold text-gray-900">Tenancy Agreement</h1>
                    <p className="mt-3 text-gray-600">
                        {extractApiErrorMessage(error, 'The tenancy agreement workspace could not be loaded.')}
                    </p>
                    <DashboardBackButton to={dashboardPath} label="Back to dashboard" className="mt-6" />
                </div>
            </div>
        )
    }

    const booking = workspace.booking
    const latest = workspace.latest_agreement
    const isTenantViewer = workspace.viewer_role === 'tenant'
    const landlordData = formData.landlord && typeof formData.landlord === 'object' ? formData.landlord : {}
    const tenantData = formData.tenant && typeof formData.tenant === 'object' ? formData.tenant : {}
    const tenancyData = formData.tenancy && typeof formData.tenancy === 'object' ? formData.tenancy : {}
    const selectedFrequency = String(getPathValue(formData, 'payments.rentFrequency') || 'yearly')
    const displayedPeriodRent = booking.rent_amount / (RENT_FREQUENCY_DIVISORS[selectedFrequency] || 1)
    const isCommercial = Boolean(getPathValue(formData, 'tenancy.isCommercial'))

    const downloadMarkdown = () => {
        if (!latest) return
        const blob = new Blob([latest.rendered_content], { type: 'text/markdown;charset=utf-8' })
        const url = URL.createObjectURL(blob)
        const anchor = document.createElement('a')
        anchor.href = url
        anchor.download = `tenancy-agreement-${latest.id}-v${latest.version}.md`
        document.body.appendChild(anchor)
        anchor.click()
        anchor.remove()
        URL.revokeObjectURL(url)
    }

    const printAgreement = () => {
        if (!latest || !previewRef.current) return
        const printWindow = window.open('', '_blank')
        if (!printWindow) {
            void alert('Please allow pop-ups so the agreement can be printed or saved as a PDF.', { variant: 'warning' })
            return
        }
        printWindow.document.write(`<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<title>Tenancy Agreement v${latest.version}</title>
<style>
    body { font-family: Georgia, 'Times New Roman', serif; color: #111827; margin: 48px; line-height: 1.7; font-size: 14px; }
    h1 { font-size: 20px; border-bottom: 1px solid #d1d5db; padding-bottom: 8px; margin-top: 28px; }
    h2 { font-size: 17px; margin-top: 24px; }
    h3, h4 { font-size: 15px; margin-top: 20px; }
    p { margin: 10px 0; }
    ul, ol { margin: 10px 0 10px 24px; }
    li { margin: 4px 0; }
    table { border-collapse: collapse; width: 100%; margin: 16px 0; }
    th, td { border: 1px solid #d1d5db; padding: 8px 10px; text-align: left; vertical-align: top; }
    th { background: #f3f4f6; }
    hr { border: none; border-top: 1px solid #d1d5db; margin: 24px 0; }
    blockquote { border-left: 4px solid #9ca3af; margin: 12px 0; padding: 4px 16px; color: #374151; }
    code { font-family: ui-monospace, monospace; background: #f3f4f6; padding: 1px 4px; border-radius: 4px; }
    .bg-slate-50, .rounded-2xl { background: transparent; padding-left: 0; }
</style>
</head>
<body>${previewRef.current.innerHTML}</body>
</html>`)
        printWindow.document.close()
        printWindow.focus()
        printWindow.print()
    }

    const renderField = (field: AgreementField) => {
        const value = getPathValue(formData, field.path)
        const errorMessage = fieldErrors[field.path]
        const required = isFieldRequired(field, formData)
        const showMissing = unresolvedMissingFields.has(field.path)
        const inputClassName = `form-input w-full ${errorMessage || showMissing ? 'border-red-400 focus:border-red-500 focus:ring-red-500/20' : ''}`

        let control
        if (field.type === 'checkbox') {
            control = (
                <label className="inline-flex items-center gap-3">
                    <input
                        type="checkbox"
                        className="h-5 w-5 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                        checked={Boolean(value)}
                        onChange={(event) => updateField(field.path, event.target.checked)}
                    />
                    <span className="text-sm text-gray-600">Enabled</span>
                </label>
            )
        } else if (field.type === 'select') {
            control = (
                <select
                    className={inputClassName}
                    value={typeof value === 'string' ? value : ''}
                    required={required}
                    onChange={(event) => updateField(field.path, event.target.value)}
                >
                    <option value="">Select an option</option>
                    {(field.options || []).map((option) => (
                        <option key={option.value} value={option.value}>{option.label}</option>
                    ))}
                </select>
            )
        } else if (field.type === 'textarea') {
            control = (
                <textarea
                    className={inputClassName}
                    rows={3}
                    required={required}
                    value={value === null || value === undefined ? '' : String(value)}
                    onChange={(event) => updateField(field.path, event.target.value)}
                />
            )
        } else {
            control = (
                <input
                    type={field.type === 'number' ? 'number' : field.type === 'date' ? 'date' : 'text'}
                    className={inputClassName}
                    min={field.type === 'number' ? 0 : undefined}
                    step={field.type === 'number' ? '0.01' : undefined}
                    required={required}
                    value={value === null || value === undefined ? '' : String(value)}
                    onChange={(event) => updateField(field.path, event.target.value)}
                />
            )
        }

        return (
            <div key={field.path}>
                <label className="mb-1 block text-sm font-medium text-gray-700">
                    {field.label}
                    {required && <span className="ml-1 text-red-500">*</span>}
                </label>
                {control}
                {field.help_text && <p className="mt-1 text-xs text-gray-500">{field.help_text}</p>}
                {showMissing && !errorMessage && <p className="mt-1 text-xs font-medium text-amber-600">This field is required before an agreement can be generated.</p>}
                {errorMessage && <p className="form-error">{errorMessage}</p>}
            </div>
        )
    }

    return (
        <div className="min-h-screen bg-gray-50">
            <div className="container-modern py-8">
                <div className="mx-auto max-w-6xl">
                    <DashboardBackButton to={dashboardPath} label="Back to dashboard" />

                    <header className="mt-6">
                        <div className="flex items-center gap-3">
                            <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-600 to-purple-600 text-white shadow">
                                <HiDocumentText className="h-6 w-6" aria-hidden="true" />
                            </span>
                            <div>
                                <h1 className="text-2xl font-bold text-gray-900 sm:text-3xl">Tenancy Agreement</h1>
                                <p className="mt-1 text-sm text-gray-600 sm:text-base">
                                    {isTenantViewer
                                        ? 'Review and electronically sign the tenancy agreement for this booking.'
                                        : 'Generate a tenancy agreement (Optional).'}
                                </p>
                            </div>
                        </div>
                    </header>

                    <div className="mt-6 grid gap-6">
                        <div className="card p-6">
                            <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Booking summary</p>
                            <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                                <div>
                                    <p className="text-sm text-gray-500">Property</p>
                                    <p className="mt-1 font-semibold text-gray-900">{booking.listing_title || 'Rental property'}</p>
                                </div>
                                <div>
                                    <p className="text-sm text-gray-500">Tenant</p>
                                    <p className="mt-1 font-semibold text-gray-900">{booking.tenant_name || 'Tenant'}</p>
                                    <p className="text-sm text-gray-600">{booking.tenant_email}</p>
                                </div>
                                <div>
                                    <p className="text-sm text-gray-500">Term</p>
                                    <p className="mt-1 font-semibold text-gray-900">
                                        {formatDateLabel(booking.start_date)} – {formatDateLabel(booking.end_date)}
                                    </p>
                                </div>
                                <div>
                                    <p className="text-sm text-gray-500">Annual rent</p>
                                    <p className="mt-1 font-semibold text-gray-900">{formatCurrencyWithSymbol(booking.rent_amount)}</p>
                                </div>
                                <div>
                                    <p className="text-sm text-gray-500">Booking status</p>
                                    <p className="mt-1"><span className={`badge ${booking.status === 'cancelled' ? 'badge-error' : 'badge-success'}`}>{booking.status}</span></p>
                                </div>
                            </div>
                        </div>

                        {workspace.agreement_options && (
                            <div className="card p-6">
                                <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Agreement options</p>
                                <div className="mt-4 grid gap-4 sm:grid-cols-2">
                                    <label
                                        className={`flex cursor-pointer items-start gap-3 rounded-2xl border p-5 transition-all ${selectedOption === 'free'
                                            ? 'border-blue-500 bg-blue-50 shadow-sm'
                                            : 'border-gray-200 bg-white hover:border-blue-200 hover:shadow-sm'
                                            }`}
                                    >
                                        <input
                                            type="radio"
                                            name="agreement-option"
                                            className="mt-1 h-5 w-5 accent-blue-600"
                                            checked={selectedOption === 'free'}
                                            onChange={() => setSelectedOption('free')}
                                        />
                                        <span>
                                            <span className="flex items-center gap-2 text-base font-semibold text-gray-900">
                                                <HiDocumentText className="h-5 w-5 text-blue-600" />
                                                Use RentDirect agreement — Free
                                            </span>
                                            <span className="mt-1 block text-sm text-gray-600">
                                                Generate the RentDirect tenancy agreement now at no cost.
                                            </span>
                                        </span>
                                    </label>
                                    <label
                                        className={`flex cursor-pointer items-start gap-3 rounded-2xl border p-5 transition-all ${selectedOption === 'lawyer'
                                            ? 'border-purple-500 bg-purple-50 shadow-sm'
                                            : 'border-gray-200 bg-white hover:border-purple-200 hover:shadow-sm'
                                            }`}
                                    >
                                        <input
                                            type="radio"
                                            name="agreement-option"
                                            className="mt-1 h-5 w-5 accent-purple-600"
                                            checked={selectedOption === 'lawyer'}
                                            onChange={() => setSelectedOption('lawyer')}
                                        />
                                        <span>
                                            <span className="flex items-center gap-2 text-base font-semibold text-gray-900">
                                                <HiScale className="h-5 w-5 text-purple-600" />
                                                Use a lawyer — 5% of annual rent (paid by landlord)
                                            </span>
                                            <span className="mt-1 block text-sm text-gray-600">
                                                A lawyer prepares the tenancy agreement for this booking. This fee is paid by you as the landlord and is never added to the tenant's charges.
                                            </span>
                                        </span>
                                    </label>
                                </div>

                                {selectedOption === 'lawyer' && (
                                    <div className="mt-5 rounded-2xl border border-purple-200 bg-purple-50/60 p-5">
                                        {workspace.agreement_options.lawyer.payment?.status === 'completed' ? (
                                            <div className="flex items-start gap-3">
                                                <HiCheckCircle className="mt-0.5 h-6 w-6 shrink-0 text-emerald-600" aria-hidden="true" />
                                                <div className="text-sm leading-6 text-gray-800">
                                                    <p className="font-semibold">Lawyer service paid. Your agreement request is awaiting legal preparation.</p>
                                                    <p className="mt-1">
                                                        Paid {formatCurrencyWithSymbol(Number(workspace.agreement_options.lawyer.payment.amount))} on{' '}
                                                        {formatTimestampLabel(workspace.agreement_options.lawyer.payment.payment_date)}.
                                                    </p>
                                                </div>
                                            </div>
                                        ) : (
                                            <div className="flex flex-wrap items-center justify-between gap-4">
                                                <div className="text-sm leading-6 text-gray-800">
                                                    <p className="font-semibold">
                                                        {workspace.agreement_options.lawyer.label}: {formatCurrencyWithSymbol(Number(workspace.agreement_options.lawyer.amount))}
                                                    </p>
                                                    <p className="mt-1">
                                                        This one-time fee is paid by you as the landlord and is never added to the tenant's charges.
                                                        {workspace.agreement_options.lawyer.payment?.status === 'pending' && ' A payment request is already in progress.'}
                                                    </p>
                                                </div>
                                                <button
                                                    type="button"
                                                    className="btn btn-primary"
                                                    disabled={requestLawyerService.isPending}
                                                    onClick={() => {
                                                        const existing = workspace.agreement_options?.lawyer.payment
                                                        if (existing && existing.status === 'pending') {
                                                            navigate(`/service-payments/${existing.id}`)
                                                        } else {
                                                            requestLawyerService.mutate()
                                                        }
                                                    }}
                                                >
                                                    {requestLawyerService.isPending
                                                        ? 'Starting...'
                                                        : workspace.agreement_options.lawyer.payment?.status === 'pending'
                                                            ? 'Continue payment'
                                                            : 'Request lawyer service'}
                                                </button>
                                            </div>
                                        )}
                                    </div>
                                )}
                            </div>
                        )}

                        {!isTenantViewer && selectedOption === 'free' && (
                        <div className="rounded-2xl border border-blue-200 bg-blue-50/70 p-5">
                            <div className="flex items-start gap-3">
                                <HiShieldCheck className="mt-0.5 h-6 w-6 shrink-0 text-blue-600" aria-hidden="true" />
                                <div className="text-sm leading-6 text-blue-900">
                                    <p className="font-semibold">Legal caution</p>
                                    <p className="mt-1">
                                        A generated agreement is a review version only. Have a qualified professional review it before use —
                                        signing, stamping and registration may still be required by law.
                                    </p>
                                </div>
                            </div>
                        </div>
                        )}

                        {!isTenantViewer && selectedOption === 'free' && unresolvedMissingFields.size > 0 && (
                            <div className="rounded-2xl border border-amber-200 bg-amber-50 p-5">
                                <div className="flex items-start gap-3">
                                    <HiExclamation className="mt-0.5 h-6 w-6 shrink-0 text-amber-600" aria-hidden="true" />
                                    <p className="text-sm leading-6 text-amber-900">
                                        <span className="font-semibold">{unresolvedMissingFields.size} required field{unresolvedMissingFields.size === 1 ? ' is' : 's are'} still missing.</span>{' '}
                                        Complete the highlighted fields below before an agreement can be generated.
                                    </p>
                                </div>
                            </div>
                        )}

                        <div className="card p-6">
                            <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Landlord and Tenant Records</p>
                            <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                                <div>
                                    <p className="text-sm text-gray-500">Landlord</p>
                                    <p className="mt-1 font-semibold text-gray-900">{landlordData.name || '—'}</p>
                                    <p className="text-sm text-gray-600">{landlordData.email}</p>
                                </div>
                                <div>
                                    <p className="text-sm text-gray-500">Tenant</p>
                                    <p className="mt-1 font-semibold text-gray-900">{tenantData.name || '—'}</p>
                                    <p className="text-sm text-gray-600">{tenantData.email}</p>
                                </div>
                                <div>
                                    <p className="text-sm text-gray-500">Agreement period &amp; rent</p>
                                    <p className="mt-1 font-semibold text-gray-900">
                                        {tenancyData.startDateFormatted || formatDateLabel(booking.start_date)} – {tenancyData.endDateFormatted || formatDateLabel(booking.end_date)}
                                    </p>
                                    <p className="text-sm text-gray-600">{formatCurrencyWithSymbol(Math.round(displayedPeriodRent * 100) / 100)} {RENT_FREQUENCY_LABELS[selectedFrequency] || 'per period'}</p>
                                </div>
                            </div>
                        </div>

                        <div className="card p-6">
                            <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Electronic signatures</p>
                            <div className="mt-4 grid gap-4 sm:grid-cols-2">
                                {(['landlord', 'tenant'] as const).map((role) => {
                                    const block = workspace.signatures?.[role] || {}
                                    const signed = role === 'landlord' ? workspace.signed_by_landlord : workspace.signed_by_tenant
                                    return (
                                        <div key={role} className={`rounded-2xl border p-4 ${signed ? 'border-emerald-200 bg-emerald-50/60' : 'border-gray-200 bg-gray-50'}`}>
                                            <div className="flex items-center gap-2">
                                                {signed ? (
                                                    <HiCheckCircle className="h-5 w-5 text-emerald-600" aria-hidden="true" />
                                                ) : (
                                                    <HiExclamation className="h-5 w-5 text-amber-500" aria-hidden="true" />
                                                )}
                                                <p className="font-semibold capitalize text-gray-900">{role}</p>
                                            </div>
                                            {signed ? (
                                                <div className="mt-2 text-sm text-gray-700">
                                                    <p className="font-medium">{block.signatoryName || 'Signed'}</p>
                                                    {block.signatoryCapacity ? <p className="text-gray-500">Capacity: {block.signatoryCapacity}</p> : null}
                                                    <p className="text-gray-500">Signed: {block.signedAtFormatted || '—'}</p>
                                                    <p className="mt-1 break-all text-xs text-gray-400">Signature ID: {block.signatureId}</p>
                                                </div>
                                            ) : (
                                                <p className="mt-2 text-sm text-gray-500">Awaiting signature</p>
                                            )}
                                        </div>
                                    )
                                })}
                            </div>

                            {workspace.can_sign && workspace.docuseal?.enabled ? (
                                <div className="mt-5 rounded-2xl border border-blue-200 bg-blue-50/60 p-5">
                                    <p className="text-sm font-semibold text-blue-900">Sign this agreement electronically</p>
                                    <p className="mt-1 text-sm leading-6 text-blue-800">
                                        Sign securely with DocuSeal. A signature box is provided for both the
                                        landlord and the tenant; completing yours marks &quot;Tenancy agreement
                                        signed?&quot; complete in the rental progress checklist.
                                    </p>
                                    {(docusealEmbedSrc || workspace.docuseal?.embed_src) ? (
                                        <div className="mt-4 overflow-hidden rounded-xl border border-gray-200 bg-white">
                                            <DocuSealSigningForm
                                                src={docusealEmbedSrc || workspace.docuseal?.embed_src || ''}
                                                onCompleted={() => {
                                                    void queryClient.invalidateQueries({ queryKey: workspaceQueryKey })
                                                }}
                                            />
                                        </div>
                                    ) : (
                                        <button
                                            type="button"
                                            disabled={startDocuSealSigning.isPending}
                                            onClick={() => startDocuSealSigning.mutate()}
                                            className="btn btn-primary mt-4"
                                        >
                                            {startDocuSealSigning.isPending ? 'Starting signing session…' : 'Sign with DocuSeal'}
                                        </button>
                                    )}
                                </div>
                            ) : workspace.can_sign ? (
                                <form
                                    className="mt-5 rounded-2xl border border-blue-200 bg-blue-50/60 p-5"
                                    onSubmit={(event) => {
                                        event.preventDefault()
                                        signAgreement.mutate()
                                    }}
                                >
                                    <p className="text-sm font-semibold text-blue-900">Sign this agreement electronically</p>
                                    <p className="mt-1 text-sm leading-6 text-blue-800">
                                        Type your legal name to sign. This records your signature and marks
                                        &quot;Tenancy agreement signed?&quot; complete in the rental progress checklist.
                                    </p>
                                    <div className="mt-4 grid gap-4 sm:grid-cols-2">
                                        <div>
                                            <label className="form-label" htmlFor="signatory-name">Full name</label>
                                            <input
                                                id="signatory-name"
                                                className="form-input"
                                                required
                                                value={signatoryName || user?.name || ''}
                                                onChange={(event) => setSignatoryName(event.target.value)}
                                            />
                                        </div>
                                        <div>
                                            <label className="form-label" htmlFor="signatory-capacity">Capacity (optional)</label>
                                            <input
                                                id="signatory-capacity"
                                                className="form-input"
                                                placeholder={workspace.viewer_role === 'tenant' ? 'Tenant' : 'Landlord'}
                                                value={signatoryCapacity}
                                                onChange={(event) => setSignatoryCapacity(event.target.value)}
                                            />
                                        </div>
                                    </div>
                                    <button
                                        type="submit"
                                        disabled={signAgreement.isPending || !(signatoryName || user?.name || '').trim()}
                                        className="btn btn-primary mt-4"
                                    >
                                        {signAgreement.isPending ? 'Signing…' : 'Sign agreement'}
                                    </button>
                                </form>
                            ) : null}

                            {!latest ? (
                                <p className="mt-4 text-sm text-gray-500">
                                    {isTenantViewer
                                        ? 'The landlord has not generated the RentDirect digital tenancy agreement yet. If you already signed offline, you can tick "Tenancy agreement signed?" manually in the rental progress checklist.'
                                        : 'Generate the agreement first — both parties can then sign it electronically here.'}
                                </p>
                            ) : null}
                        </div>

                        {!isTenantViewer && selectedOption === 'free' && (
                        <form
                            className="card p-6"
                            onSubmit={(event) => {
                                event.preventDefault()
                                generateAgreement.mutate()
                            }}
                        >
                            <div className="flex flex-wrap items-center justify-between gap-3">
                                <div>
                                    <h2 className="text-lg font-semibold text-gray-900">Agreement details</h2>
                                    <p className="mt-1 text-sm text-gray-600">
                                        Review the auto-filled values and complete any missing fields. Only the fields below can be edited.
                                    </p>
                                </div>
                                {latest && (
                                    <span className="badge badge-primary">Latest version: v{latest.version}</span>
                                )}
                            </div>

                            <div className="mt-6 space-y-8">
                                {sections.map((section) => {
                                    if (section.name === 'Commercial' && !isCommercial) {
                                        return null
                                    }
                                    return (
                                        <section key={section.name}>
                                            <h3 className="border-b border-gray-100 pb-2 text-sm font-semibold uppercase tracking-[0.14em] text-gray-500">
                                                {section.name}
                                            </h3>
                                            <div className="mt-4 grid gap-4 sm:grid-cols-2">
                                                {section.fields.map((field) => (
                                                    <div key={field.path} className={field.type === 'textarea' || field.type === 'checkbox' ? 'sm:col-span-2' : ''}>
                                                        {renderField(field)}
                                                    </div>
                                                ))}
                                            </div>
                                        </section>
                                    )
                                })}
                            </div>

                            <div className="mt-8 flex flex-wrap items-center gap-3">
                                <button
                                    type="submit"
                                    className="btn btn-primary"
                                    disabled={generateAgreement.isPending || !workspace.can_generate}
                                >
                                    {generateAgreement.isPending ? 'Generating...' : latest ? 'Generate New Version' : 'Generate Agreement'}
                                </button>
                                {!workspace.can_generate && (
                                    <p className="text-sm text-red-600">This booking is cancelled, so a new agreement cannot be generated.</p>
                                )}
                            </div>
                        </form>
                        )}

                        {latest && (
                            <div className="card overflow-hidden">
                                <div className="border-b border-gray-100 px-6 py-5">
                                    <div className="flex flex-wrap items-center justify-between gap-3">
                                        <div>
                                            <h2 className="text-lg font-semibold text-gray-900">Latest generated version</h2>
                                            <p className="mt-1 text-sm text-gray-600">
                                                Version {latest.version} • <span className="capitalize">{latest.status}</span> • generated {formatTimestampLabel(latest.generated_at)}
                                            </p>
                                            <p className="mt-1 break-all text-xs text-gray-500">SHA-256: {latest.document_hash}</p>
                                        </div>
                                        <div className="flex flex-wrap gap-3">
                                            {/* <button type="button" className="btn btn-outline" onClick={downloadMarkdown}>
                                                <HiDownload className="mr-2 h-4 w-4" />
                                                Download Markdown
                                            </button> */}
                                            <button type="button" className="btn btn-outline" onClick={printAgreement}>
                                                <HiPrinter className="mr-2 h-4 w-4" />
                                                Print / Save PDF
                                            </button>
                                        </div>
                                    </div>
                                </div>
                                <div className="px-6 py-6">
                                    <div ref={previewRef} className="rounded-2xl border border-slate-200 bg-white p-6">
                                        <LegalDocumentRenderer content={latest.rendered_content} />
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    )
}
