import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useAppPopup } from '@/contexts/AppPopupContext'
import AdminLayout from '@/components/admin/AdminLayout'

interface VerificationRequest {
    id: string
    user_id: string
    user_email: string
    user_name: string
    user_role: 'landlord' | 'tenant'
    status: string
    verification_method: string
    confidence_score: number | null
    automated_decision: string | null
    submitted_at: string
    estimated_completion: string
}

interface VerificationMetrics {
    total_verifications: number
    automated_approvals: number
    manual_reviews: number
    average_processing_time_hours: number
    success_rate: number
    last_updated: string
}

export default function AdminVerificationPage() {
    const queryClient = useQueryClient()
    const { confirm } = useAppPopup()
    const [selectedVerification, setSelectedVerification] = useState<VerificationRequest | null>(null)
    const [rejectReason, setRejectReason] = useState('')
    const [showRejectModal, setShowRejectModal] = useState(false)
    const [currentPage, setCurrentPage] = useState(1)
    const [itemsPerPage] = useState(10)
    const verificationEndpoint = (verification: VerificationRequest) => (
        verification.user_role === 'tenant' ? '/tenant-verification-requests' : '/landlord-verification-requests'
    )

    // Fetch verification metrics
    const { data: metrics, isLoading: metricsLoading } = useQuery({
        queryKey: ['verification-metrics'],
        queryFn: async () => {
            const [landlordResponse, tenantResponse] = await Promise.all([
                api.get<VerificationMetrics>('/landlord-verification-requests/metrics'),
                api.get<VerificationMetrics>('/tenant-verification-requests/metrics'),
            ])
            const landlord = landlordResponse.data
            const tenant = tenantResponse.data
            const total = landlord.total_verifications + tenant.total_verifications
            return {
                total_verifications: total,
                automated_approvals: landlord.automated_approvals + tenant.automated_approvals,
                manual_reviews: landlord.manual_reviews + tenant.manual_reviews,
                average_processing_time_hours: 0,
                success_rate: total
                    ? ((landlord.success_rate * landlord.total_verifications) + (tenant.success_rate * tenant.total_verifications)) / total
                    : 0,
                last_updated: landlord.last_updated || tenant.last_updated,
            } as VerificationMetrics
        },
        refetchInterval: 30000 // Refresh every 30 seconds
    })

    // Fetch pending verifications
    const { data: verifications, isLoading: verificationsLoading } = useQuery({
        queryKey: ['pending-verifications', currentPage],
        queryFn: async () => {
            const offset = (currentPage - 1) * itemsPerPage
            const [landlordResponse, tenantResponse] = await Promise.all([
                api.get<VerificationRequest[]>(`/landlord-verification-requests/pending?limit=${itemsPerPage}&offset=${offset}`),
                api.get<VerificationRequest[]>(`/tenant-verification-requests/pending?limit=${itemsPerPage}&offset=${offset}`),
            ])
            return [...landlordResponse.data, ...tenantResponse.data]
                .sort((left, right) => new Date(right.submitted_at).getTime() - new Date(left.submitted_at).getTime())
                .slice(0, itemsPerPage)
        },
        refetchInterval: 10000 // Refresh every 10 seconds
    })

    // Approve verification mutation
    const approveVerification = useMutation({
        mutationFn: async (verification: VerificationRequest) => {
            await api.post(`${verificationEndpoint(verification)}/${verification.id}/approve`)
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['pending-verifications'] })
            queryClient.invalidateQueries({ queryKey: ['verification-metrics'] })
            setSelectedVerification(null)
        },
        onError: (error) => {
            alert(`Failed to approve verification: ${error.message}`)
        }
    })

    // Reject verification mutation
    const rejectVerification = useMutation({
        mutationFn: async ({ verification, reason }: { verification: VerificationRequest; reason: string }) => {
            await api.post(`${verificationEndpoint(verification)}/${verification.id}/reject`, { reason })
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['pending-verifications'] })
            queryClient.invalidateQueries({ queryKey: ['verification-metrics'] })
            setSelectedVerification(null)
            setShowRejectModal(false)
            setRejectReason('')
        },
        onError: (error) => {
            alert(`Failed to reject verification: ${error.message}`)
        }
    })

    const handleApprove = async (verification: VerificationRequest) => {
        if (await confirm(`Are you sure you want to approve ${verification.user_name}'s verification?`)) {
            approveVerification.mutate(verification)
        }
    }

    const handleReject = (verification: VerificationRequest) => {
        setSelectedVerification(verification)
        setShowRejectModal(true)
    }

    const handleRejectSubmit = () => {
        if (!rejectReason.trim()) {
            alert('Please provide a reason for rejection')
            return
        }
        if (selectedVerification) {
            rejectVerification.mutate({
                verification: selectedVerification,
                reason: rejectReason
            })
        }
    }

    const getStatusBadge = (status: string) => {
        const statusConfig = {
            pending: { color: 'bg-yellow-100 text-yellow-800', text: 'Pending Review' },
            'under_review': { color: 'bg-blue-100 text-blue-800', text: 'Under Review' },
            approved: { color: 'bg-green-100 text-green-800', text: 'Approved' },
            rejected: { color: 'bg-red-100 text-red-800', text: 'Rejected' }
        }

        const config = statusConfig[status as keyof typeof statusConfig] || statusConfig.pending
        return (
            <span className={`px-2 py-1 text-xs font-medium rounded-full ${config.color}`}>
                {config.text}
            </span>
        )
    }

    const getMethodBadge = (method: string) => {
        const methodConfig = {
            manual: { color: 'bg-gray-100 text-gray-800', text: 'Manual' },
            automated: { color: 'bg-green-100 text-green-800', text: 'Automated' },
            hybrid: { color: 'bg-blue-100 text-blue-800', text: 'Hybrid' }
        }

        const config = methodConfig[method as keyof typeof methodConfig] || methodConfig.manual
        return (
            <span className={`px-2 py-1 text-xs font-medium rounded-full ${config.color}`}>
                {config.text}
            </span>
        )
    }

    const formatDate = (dateString: string) => {
        return new Date(dateString).toLocaleDateString('en-US', {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        })
    }

    return (
        <AdminLayout>
            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
                <div className="mb-8">
                    <h1 className="text-3xl font-bold text-gray-900">Verification Management</h1>
                    <p className="text-gray-600 mt-2">Review and manage verification requests from landlords and tenants</p>
                </div>

                {/* Metrics Dashboard */}
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
                    <div className="bg-white rounded-xl border shadow-sm p-6">
                        <div className="flex items-center">
                            <div className="p-2 bg-blue-100 rounded-lg">
                                <svg className="w-6 h-6 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                                </svg>
                            </div>
                            <div className="ml-4">
                                <p className="text-sm font-medium text-gray-600">Total Requests</p>
                                <p className="text-2xl font-bold text-gray-900">
                                    {metricsLoading ? '...' : metrics?.total_verifications || 0}
                                </p>
                            </div>
                        </div>
                    </div>

                    <div className="bg-white rounded-xl border shadow-sm p-6">
                        <div className="flex items-center">
                            <div className="p-2 bg-green-100 rounded-lg">
                                <svg className="w-6 h-6 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                                </svg>
                            </div>
                            <div className="ml-4">
                                <p className="text-sm font-medium text-gray-600">Auto-Approved</p>
                                <p className="text-2xl font-bold text-gray-900">
                                    {metricsLoading ? '...' : metrics?.automated_approvals || 0}
                                </p>
                            </div>
                        </div>
                    </div>

                    <div className="bg-white rounded-xl border shadow-sm p-6">
                        <div className="flex items-center">
                            <div className="p-2 bg-yellow-100 rounded-lg">
                                <svg className="w-6 h-6 text-yellow-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                                </svg>
                            </div>
                            <div className="ml-4">
                                <p className="text-sm font-medium text-gray-600">Manual Reviews</p>
                                <p className="text-2xl font-bold text-gray-900">
                                    {metricsLoading ? '...' : metrics?.manual_reviews || 0}
                                </p>
                            </div>
                        </div>
                    </div>

                    <div className="bg-white rounded-xl border shadow-sm p-6">
                        <div className="flex items-center">
                            <div className="p-2 bg-purple-100 rounded-lg">
                                <svg className="w-6 h-6 text-purple-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                                </svg>
                            </div>
                            <div className="ml-4">
                                <p className="text-sm font-medium text-gray-600">Success Rate</p>
                                <p className="text-2xl font-bold text-gray-900">
                                    {metricsLoading ? '...' : `${Math.round((metrics?.success_rate || 0) * 100)}%`}
                                </p>
                            </div>
                        </div>
                    </div>
                </div>

                {/* Pending Verifications */}
                <div className="bg-white rounded-xl border shadow-sm">
                    <div className="px-6 py-4 border-b border-gray-200">
                        <h2 className="text-xl font-semibold text-gray-900">Pending Verifications</h2>
                        <p className="text-sm text-gray-600 mt-1">Review and process verification requests</p>
                    </div>

                    {verificationsLoading ? (
                        <div className="p-6 text-center">
                            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto"></div>
                            <p className="text-gray-600 mt-2">Loading verifications...</p>
                        </div>
                    ) : verifications && verifications.length > 0 ? (
                        <div className="overflow-x-auto">
                            <table className="min-w-full divide-y divide-gray-200">
                                <thead className="bg-gray-50">
                                    <tr>
                                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                            User
                                        </th>
                                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                            Status
                                        </th>
                                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                            Method
                                        </th>
                                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                            Confidence
                                        </th>
                                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                            Submitted
                                        </th>
                                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                            Actions
                                        </th>
                                    </tr>
                                </thead>
                                <tbody className="bg-white divide-y divide-gray-200">
                                    {verifications.map((verification) => (
                                        <tr key={verification.id} className="hover:bg-gray-50">
                                            <td className="px-6 py-4 whitespace-nowrap">
                                                <div>
                                                    <div className="text-sm font-medium text-gray-900">
                                                        {verification.user_name}
                                                    </div>
                                                    <div className="text-sm text-gray-500">
                                                        {verification.user_email}
                                                    </div>
                                                </div>
                                            </td>
                                            <td className="px-6 py-4 whitespace-nowrap">
                                                {getStatusBadge(verification.status)}
                                            </td>
                                            <td className="px-6 py-4 whitespace-nowrap">
                                                {getMethodBadge(verification.verification_method)}
                                            </td>
                                            <td className="px-6 py-4 whitespace-nowrap">
                                                {verification.confidence_score ? (
                                                    <div className="flex items-center">
                                                        <div className="w-16 bg-gray-200 rounded-full h-2 mr-2">
                                                            <div
                                                                className="bg-blue-600 h-2 rounded-full"
                                                                style={{ width: `${verification.confidence_score * 100}%` }}
                                                            ></div>
                                                        </div>
                                                        <span className="text-sm text-gray-900">
                                                            {Math.round(verification.confidence_score * 100)}%
                                                        </span>
                                                    </div>
                                                ) : (
                                                    <span className="text-sm text-gray-500">N/A</span>
                                                )}
                                            </td>
                                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                                                {formatDate(verification.submitted_at)}
                                            </td>
                                            <td className="px-6 py-4 whitespace-nowrap text-sm font-medium">
                                                <div className="flex space-x-2">
                                                    <button
                                                        onClick={() => handleApprove(verification)}
                                                        disabled={approveVerification.isPending}
                                                        className="inline-flex items-center px-3 py-1 border border-transparent text-xs font-medium rounded-md text-white bg-green-600 hover:bg-green-700 disabled:opacity-50"
                                                    >
                                                        {approveVerification.isPending ? 'Approving...' : 'Approve'}
                                                    </button>
                                                    <button
                                                        onClick={() => handleReject(verification)}
                                                        disabled={rejectVerification.isPending}
                                                        className="inline-flex items-center px-3 py-1 border border-transparent text-xs font-medium rounded-md text-white bg-red-600 hover:bg-red-700 disabled:opacity-50"
                                                    >
                                                        {rejectVerification.isPending ? 'Rejecting...' : 'Reject'}
                                                    </button>
                                                </div>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    ) : (
                        <div className="p-6 text-center">
                            <svg className="mx-auto h-12 w-12 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                            </svg>
                            <h3 className="mt-2 text-sm font-medium text-gray-900">No pending verifications</h3>
                            <p className="mt-1 text-sm text-gray-500">All verification requests have been processed.</p>
                        </div>
                    )}
                </div>

                {/* Pagination */}
                {verifications && verifications.length > 0 && (
                    <div className="mt-6 flex items-center justify-between">
                        <div className="text-sm text-gray-700">
                            Showing page {currentPage} of results
                        </div>
                        <div className="flex space-x-2">
                            <button
                                onClick={() => setCurrentPage(prev => Math.max(1, prev - 1))}
                                disabled={currentPage === 1}
                                className="px-3 py-2 text-sm font-medium text-gray-500 bg-white border border-gray-300 rounded-md hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                                Previous
                            </button>
                            <button
                                onClick={() => setCurrentPage(prev => prev + 1)}
                                disabled={verifications.length < itemsPerPage}
                                className="px-3 py-2 text-sm font-medium text-gray-500 bg-white border border-gray-300 rounded-md hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                                Next
                            </button>
                        </div>
                    </div>
                )}

                {/* Reject Modal */}
                {showRejectModal && (
                    <div className="fixed inset-0 bg-gray-600 bg-opacity-50 overflow-y-auto h-full w-full z-50">
                        <div className="relative top-20 mx-auto p-5 border w-96 shadow-lg rounded-md bg-white">
                            <div className="mt-3">
                                <h3 className="text-lg font-medium text-gray-900 mb-4">Reject Verification</h3>
                                <p className="text-sm text-gray-600 mb-4">
                                    Please provide a reason for rejecting {selectedVerification?.user_name}'s verification request.
                                </p>
                                <textarea
                                    value={rejectReason}
                                    onChange={(e) => setRejectReason(e.target.value)}
                                    placeholder="Enter rejection reason..."
                                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                                    rows={4}
                                />
                                <div className="flex justify-end space-x-3 mt-4">
                                    <button
                                        onClick={() => setShowRejectModal(false)}
                                        className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 border border-gray-300 rounded-md hover:bg-gray-200"
                                    >
                                        Cancel
                                    </button>
                                    <button
                                        onClick={handleRejectSubmit}
                                        disabled={rejectVerification.isPending}
                                        className="px-4 py-2 text-sm font-medium text-white bg-red-600 border border-transparent rounded-md hover:bg-red-700 disabled:opacity-50"
                                    >
                                        {rejectVerification.isPending ? 'Rejecting...' : 'Reject'}
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                )}
            </div>
        </AdminLayout>
    )
}
