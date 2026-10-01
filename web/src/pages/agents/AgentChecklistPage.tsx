import { useQuery } from '@tanstack/react-query'
import { Navigate } from 'react-router-dom'
import { HiLockClosed } from 'react-icons/hi'

import DashboardBackButton from '@/components/DashboardBackButton'
import { api } from '@/lib/api'
import { AgentDashboard, InspectionChecklistSchema, InspectionField } from '@/types'

const EDITABLE_INSPECTION_STATUSES = new Set(['claimed', 'draft'])

function LockedField({ field }: { field: InspectionField }) {
    const label = (
        <span className="form-label">
            {field.label}
            {field.required ? ' *' : ''}
        </span>
    )

    if (field.type === 'select') {
        return (
            <div>
                <label>{label}</label>
                <select className="form-input bg-gray-100 text-gray-400" disabled>
                    <option>Select</option>
                </select>
            </div>
        )
    }
    if (field.type === 'multiselect') {
        return (
            <div>
                <span className="form-label">{field.label}{field.required ? ' *' : ''}</span>
                <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
                    {(field.options || []).map((option) => (
                        <label key={option.value} className="flex items-center gap-2 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-400">
                            <input type="checkbox" disabled className="h-4 w-4 rounded border-gray-300" />
                            {option.label}
                        </label>
                    ))}
                </div>
            </div>
        )
    }
    if (field.type === 'textarea') {
        return (
            <div>
                <label>{label}</label>
                <textarea className="form-input bg-gray-100 text-gray-400" rows={3} disabled />
            </div>
        )
    }
    if (field.type === 'checkbox') {
        return (
            <label className="flex items-start gap-3 rounded-lg border border-gray-200 bg-gray-50 p-3 text-gray-400">
                <input type="checkbox" disabled className="mt-1 h-5 w-5 rounded border-gray-300" />
                <span className="text-sm">{field.label}{field.required ? ' *' : ''}</span>
            </label>
        )
    }
    return (
        <div>
            <label>{label}</label>
            <input type={field.type === 'number' ? 'number' : 'text'} className="form-input bg-gray-100 text-gray-400" disabled />
        </div>
    )
}

export default function AgentChecklistPage() {
    const { data: dashboard, isLoading: dashboardLoading } = useQuery({
        queryKey: ['agents', 'dashboard'],
        queryFn: async () => (await api.get<AgentDashboard>('/agents/dashboard')).data,
    })

    const { data: checklist, isLoading: checklistLoading } = useQuery({
        queryKey: ['agent-inspections', 'checklist'],
        queryFn: async () => (await api.get<InspectionChecklistSchema>('/agent-inspections/checklist')).data,
        staleTime: Infinity,
    })

    const activeInspection = (dashboard?.inspections || []).find((inspection) =>
        EDITABLE_INSPECTION_STATUSES.has(inspection.status),
    )

    if (dashboardLoading) {
        return (
            <div className="agent-theme min-h-screen bg-gradient-to-br from-emerald-50 via-white to-green-50 flex items-center justify-center">
                <div className="text-center">
                    <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-emerald-600 mx-auto"></div>
                    <p className="mt-4 text-gray-600">Loading inspection checklist…</p>
                </div>
            </div>
        )
    }

    if (activeInspection) {
        return <Navigate to={`/agents/inspections/${activeInspection.id}`} replace />
    }

    return (
        <div className="agent-theme min-h-screen bg-gradient-to-br from-emerald-50 via-white to-green-50">
            <div className="container-modern py-8">
                <div className="mb-5">
                    <DashboardBackButton to="/agents/dashboard" label="Back to dashboard" />
                </div>

                <div className="mb-6">
                    <h1 className="text-3xl font-bold text-gray-900">Property Inspection Checklist</h1>
                    <p className="mt-1 text-sm text-gray-600">
                        This is the checklist you complete for every in-person property inspection.
                    </p>
                </div>

                <div className="mb-8 flex items-center gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-amber-900">
                    <HiLockClosed className="h-6 w-6 shrink-0" />
                    <p className="text-sm">
                        The checklist is locked. It becomes editable with a submit button once you accept an
                        inspection request from your dashboard.
                    </p>
                </div>

                {checklistLoading ? (
                    <div className="card p-6 text-center text-gray-600">Loading checklist…</div>
                ) : (
                    <div className="space-y-6">
                        {(checklist?.sections || []).map((section) => (
                            <div key={section.key} className="card p-6 opacity-80">
                                <h2 className="mb-4 text-xl font-semibold text-gray-900">{section.title}</h2>
                                <div className="grid gap-4 md:grid-cols-2">
                                    {section.fields.map((field) => (
                                        <div key={field.key} className={field.type === 'textarea' || field.type === 'multiselect' ? 'md:col-span-2' : ''}>
                                            <LockedField field={field} />
                                        </div>
                                    ))}
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    )
}
