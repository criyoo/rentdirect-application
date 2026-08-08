import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'

import { useAuth } from '@/hooks/useAuth'
import DashboardBackButton from '@/components/DashboardBackButton'
import { api } from '@/lib/api'
import { complaintTopics, landlordComplaintTopics } from '@/lib/tenantSupport'

function extractErrorMessage(error: any, fallback: string) {
    const detail = error?.response?.data?.detail
    if (detail) return detail
    const firstError = Object.values(error?.response?.data || {}).flat().find(Boolean)
    return typeof firstError === 'string' ? firstError : error?.message || fallback
}

export default function TenantComplaintPage() {
    const { user } = useAuth()
    const navigate = useNavigate()
    const role = user?.role === 'landlord' ? 'landlord' : 'tenant'
    const dashboardPath = user?.id ? `/dashboard/${role}/${user.id}` : '/'
    const topics = role === 'landlord' ? landlordComplaintTopics : complaintTopics
    const [name, setName] = useState('')
    const [email, setEmail] = useState('')
    const [topic, setTopic] = useState('')
    const [message, setMessage] = useState('')
    const [error, setError] = useState('')

    useEffect(() => {
        setName(user?.name || '')
    }, [user])

    useEffect(() => {
        setEmail(user?.email || '')
    }, [user])

    const submitComplaint = useMutation({
        mutationFn: async () => {
            if (!topic.trim() || !message.trim()) {
                throw new Error('Choose a complaint topic and describe the complaint.')
            }
            await api.post('/feedback', {
                name: name.trim() || user?.name || '',
                role,
                topic: `Complaint: ${topic.trim()}`,
                message: message.trim(),
            })
        },
        onSuccess: () => {
            navigate(dashboardPath)
        },
        onError: (err) => setError(extractErrorMessage(err, 'Unable to submit complaint.')),
    })

    return (
        <div className="container-modern py-8">
            <div className="mx-auto max-w-3xl">
                <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
                    <div>
                        <p className="text-sm font-medium uppercase tracking-[0.2em] text-red-600">Complaint</p>
                        <h1 className="text-3xl font-bold text-gray-900">Submit a {role} complaint</h1>
                    </div>
                    <DashboardBackButton to={dashboardPath} label="Back to Dashboard" />
                </div>

                {error && <div className="mt-6 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">{error}</div>}

                <div className="card mt-6 p-6">
                    <div className="grid gap-5 md:grid-cols-2">
                        <div>
                            <label className="form-label">Name</label>
                            <input className="form-input" value={name} onChange={(event) => setName(event.target.value)} />
                        </div>
                        <div>
                            <label className="form-label">Email</label>
                            <input className="form-input" value={email} onChange={(event) => setEmail(event.target.value)} />
                        </div>
                    </div>

                    <div className="mt-5 grid gap-5 md:grid-cols-1">
                        <div>
                            <label className="form-label">Complaint topic</label>
                            <select className="form-input" value={topic} onChange={(event) => setTopic(event.target.value)}>
                                <option value="">Select topic</option>
                                {topics.map((item) => <option key={item} value={item}>{item}</option>)}
                            </select>
                        </div>
                    </div>

                    <div className="mt-5">
                        <label className="form-label">Details</label>
                        <textarea
                            className="form-input min-h-44"
                            value={message}
                            onChange={(event) => setMessage(event.target.value)}
                            placeholder="Describe what happened and include any property, booking, or payment reference if available."
                        />
                    </div>

                    <div className="mt-6 flex justify-end">
                        <button
                            type="button"
                            onClick={() => submitComplaint.mutate()}
                            className="btn btn-primary px-6 py-3"
                            disabled={submitComplaint.isPending}
                        >
                            {submitComplaint.isPending ? 'Submitting...' : 'Submit Complaint'}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    )
}
