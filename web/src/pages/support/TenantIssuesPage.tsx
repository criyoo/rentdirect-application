import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'

import { useAuth } from '@/hooks/useAuth'
import { api } from '@/lib/api'
import { landlordIssueTopics, landlordSupportFaqs, tenantIssueTopics, tenantSupportFaqs } from '@/lib/tenantSupport'

function extractErrorMessage(error: any, fallback: string) {
    const detail = error?.response?.data?.detail
    if (detail) return detail
    const firstError = Object.values(error?.response?.data || {}).flat().find(Boolean)
    return typeof firstError === 'string' ? firstError : error?.message || fallback
}

export default function TenantIssuesPage() {
    const { user } = useAuth()
    const navigate = useNavigate()
    const role = user?.role === 'landlord' ? 'landlord' : 'tenant'
    const dashboardPath = user?.id ? `/dashboard/${role}/${user.id}` : '/'
    const issueTopics = role === 'landlord' ? landlordIssueTopics : tenantIssueTopics
    const faqs = role === 'landlord' ? landlordSupportFaqs : tenantSupportFaqs
    const [topic, setTopic] = useState('')
    const [message, setMessage] = useState('')
    const [error, setError] = useState('')

    const submitIssue = useMutation({
        mutationFn: async () => {
            if (!topic.trim() || !message.trim()) {
                throw new Error('Choose a topic and describe the issue.')
            }
            await api.post('/feedback', {
                name: user?.name || '',
                role,
                topic: `Issue: ${topic.trim()}`,
                message: message.trim(),
            })
        },
        onSuccess: () => navigate(dashboardPath),
        onError: (err) => setError(extractErrorMessage(err, 'Unable to submit issue.')),
    })

    return (
        <div className="container-modern py-8">
            <div className="mx-auto max-w-5xl">
                <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
                    <div>
                        <p className="text-sm font-medium uppercase tracking-[0.2em] text-amber-600">Issues</p>
                        <h1 className="text-3xl font-bold text-gray-900">Account and platform issues</h1>
                    </div>
                    <Link to={dashboardPath} className="btn btn-outline">
                        Back to Dashboard
                    </Link>
                </div>

                <div className="mt-6 grid gap-6 lg:grid-cols-[1fr_1.1fr]">
                    <div className="card p-6">
                        <h2 className="text-xl font-semibold text-gray-900">FAQ</h2>
                        <div className="mt-5 space-y-4">
                            {faqs.map((item) => (
                                <div key={item.question} className="rounded-lg border border-gray-200 p-4">
                                    <h3 className="text-sm font-semibold text-gray-900">{item.question}</h3>
                                    <p className="mt-2 text-sm text-gray-600">{item.answer}</p>
                                </div>
                            ))}
                        </div>
                    </div>

                    <div className="card p-6">
                        <h2 className="text-xl font-semibold text-gray-900">Submit an issue</h2>
                        {error && <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">{error}</div>}
                        <div className="mt-5">
                            <label className="form-label">Topic</label>
                            <select className="form-input" value={topic} onChange={(event) => setTopic(event.target.value)}>
                                <option value="">Select topic</option>
                                {issueTopics.map((item) => <option key={item} value={item}>{item}</option>)}
                            </select>
                        </div>
                        <div className="mt-10">
                            <label className="form-label">Message</label>
                            <textarea
                                className="form-input min-h-60"
                                value={message}
                                onChange={(event) => setMessage(event.target.value)}
                                placeholder="Describe the issue with your account or rental workflow."
                            />
                        </div>
                        <div className="mt-6 flex justify-end">
                            <button
                                type="button"
                                onClick={() => submitIssue.mutate()}
                                className="btn btn-primary px-6 py-3"
                                disabled={submitIssue.isPending}
                            >
                                {submitIssue.isPending ? 'Submitting...' : 'Submit Issue'}
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}
