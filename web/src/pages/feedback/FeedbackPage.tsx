import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'

import { useAuth } from '@/hooks/useAuth'
import DashboardBackButton from '@/components/DashboardBackButton'
import { api } from '@/lib/api'

function extractErrorMessage(error: any, fallback: string) {
    if (typeof error?.response?.data === 'string') {
        return error.response.data
    }

    const detail = error?.response?.data?.detail
    if (detail) {
        return detail
    }

    const firstError = Object.values(error?.response?.data || {}).flat().find(Boolean)
    return typeof firstError === 'string' ? firstError : error?.message || fallback
}

export default function FeedbackPage() {
    const navigate = useNavigate()
    const { user } = useAuth()
    const [name, setName] = useState('')
    const [role, setRole] = useState<'tenant' | 'landlord' | 'admin'>('tenant')
    const [topic, setTopic] = useState('')
    const [message, setMessage] = useState('')

    useEffect(() => {
        if (!user) return
        setName(user.name || '')
        setRole(user.role)
    }, [user])

    const submitFeedback = useMutation({
        mutationFn: async () => {
            if (!name.trim() || !topic.trim() || !message.trim()) {
                throw new Error('Please complete the required feedback fields.')
            }

            await api.post('/feedback', {
                name: name.trim(),
                role,
                topic: topic.trim(),
                message: message.trim(),
            })
        },
        onSuccess: () => {
            alert('Feedback sent successfully.')
            if (user?.role === 'landlord') {
                navigate(`/dashboard/landlord/${user.id}`)
                return
            }
            if (user?.role === 'tenant') {
                navigate(`/dashboard/tenant/${user.id}`)
                return
            }
            navigate('/')
        },
        onError: (error) => {
            alert(extractErrorMessage(error, 'Unable to send feedback.'))
        },
    })

    const dashboardPath = user?.role === 'landlord'
        ? `/dashboard/landlord/${user.id}`
        : user?.role === 'tenant'
            ? `/dashboard/tenant/${user.id}`
            : '/'

    return (
        <div className="container-modern py-8">
            <div className="mx-auto max-w-3xl">
                <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
                    <div>
                        <p className="text-sm font-medium uppercase tracking-[0.2em] text-blue-600">Feedback</p>
                        <h1 className="text-3xl font-bold text-gray-900">Tell us what to improve</h1>
                        <p className="mt-2 text-gray-600">Share platform issues, ideas, or requests with the RentDirect team.</p>
                    </div>
                    <DashboardBackButton to={dashboardPath} label="Back to Dashboard" />
                </div>

                <div className="card mt-6 p-6">
                    <div className="grid gap-5 md:grid-cols-2">
                        <div>
                            <label className="form-label">Name</label>
                            <input
                                className="form-input cursor-not-allowed bg-gray-100 text-gray-500"
                                value={name || user?.name || ''}
                                readOnly
                                disabled
                                aria-readonly="true"
                                aria-label="Your name"
                            />
                        </div>
                        <div>
                            <label className="form-label">Role</label>
                            <input
                                className="form-input cursor-not-allowed bg-gray-100 text-gray-500 capitalize"
                                value={role}
                                readOnly
                                disabled
                                aria-readonly="true"
                                aria-label="Your role"
                            />
                        </div>
                    </div>

                    <div className="mt-5">
                        <label className="form-label">Feedback topic</label>
                        <input
                            className="form-input"
                            value={topic}
                            onChange={(event) => setTopic(event.target.value)}
                            placeholder="Subject of your feedback"
                        />
                    </div>

                    <div className="mt-5">
                        <label className="form-label">Message</label>
                        <textarea
                            className="form-input min-h-40"
                            value={message}
                            onChange={(event) => setMessage(event.target.value)}
                            placeholder="Describe the issue, idea, or improvement request"
                        />
                    </div>

                    <div className="mt-6 flex justify-end">
                        <button
                            type="button"
                            onClick={() => submitFeedback.mutate()}
                            className="btn btn-primary px-6 py-3"
                            disabled={submitFeedback.isPending}
                        >
                            {submitFeedback.isPending ? 'Sending...' : 'Send Feedback'}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    )
}
