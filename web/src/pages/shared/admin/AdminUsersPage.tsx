import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import AdminLayout from '@/components/admin/AdminLayout'
import DashboardBackButton from '@/components/DashboardBackButton'
import { api, resolveMediaUrl } from '@/lib/api'
import { HiUserCircle } from 'react-icons/hi'

interface AdminUser {
    id: string
    name: string
    email: string
    role: string
    mobile?: string
    is_verified?: boolean
    email_verified?: boolean
    account_frozen?: boolean
    profile_photo_url?: string | null
    created_at?: string
}

const ROLE_LABELS: Record<string, string> = {
    tenant: 'Tenants',
    landlord: 'Landlords',
    agent: 'PIOs',
    admin: 'Admins',
}

export default function AdminUsersPage({ role }: { role?: string }) {
    const [search, setSearch] = useState('')
    const title = role ? ROLE_LABELS[role] || 'Users' : 'All Users'

    const { data: users, isLoading } = useQuery({
        queryKey: ['admin', 'users', role],
        queryFn: async () =>
            (await api.get<AdminUser[]>('/admin/users', {
                params: { ...(role ? { role } : {}), limit: 200 },
            })).data,
    })

    const filtered = (users || []).filter((user) => {
        const needle = search.trim().toLowerCase()
        if (!needle) return true
        return user.name?.toLowerCase().includes(needle) || user.email?.toLowerCase().includes(needle)
    })

    return (
        <AdminLayout>
            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
                <div className="mb-5">
                    <DashboardBackButton to="/admin/dashboard" label="Back to Dashboard" />
                </div>
                <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
                    <div>
                        <h1 className="text-3xl font-bold text-gray-900">{title}</h1>
                        <p className="text-gray-600 mt-1">{filtered.length} account{filtered.length === 1 ? '' : 's'}</p>
                    </div>
                    <input
                        type="search"
                        value={search}
                        onChange={(event) => setSearch(event.target.value)}
                        placeholder="Search name or email"
                        className="form-input !w-64"
                    />
                </div>

                {isLoading && <p className="text-sm text-gray-500 mb-4">Loading {title.toLowerCase()}…</p>}

                <div className="bg-white rounded-xl border shadow-sm overflow-hidden">
                    <div className="overflow-x-auto">
                        <table className="min-w-full divide-y divide-gray-200 text-sm">
                            <thead className="bg-gray-50">
                                <tr>
                                    <th className="px-4 py-3 text-left font-semibold text-gray-600">User</th>
                                    <th className="px-4 py-3 text-left font-semibold text-gray-600">Role</th>
                                    <th className="px-4 py-3 text-left font-semibold text-gray-600">Phone</th>
                                    <th className="px-4 py-3 text-left font-semibold text-gray-600">Verified</th>
                                    <th className="px-4 py-3 text-left font-semibold text-gray-600">Status</th>
                                    <th className="px-4 py-3 text-left font-semibold text-gray-600">Joined</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-100 bg-white">
                                {filtered.map((user) => (
                                    <tr key={user.id} className="hover:bg-gray-50">
                                        <td className="px-4 py-3">
                                            <div className="flex items-center gap-3">
                                                {user.profile_photo_url ? (
                                                    <img
                                                        src={resolveMediaUrl(user.profile_photo_url)}
                                                        alt={user.name}
                                                        loading="lazy"
                                                        decoding="async"
                                                        className="h-9 w-9 rounded-full object-cover"
                                                    />
                                                ) : (
                                                    <HiUserCircle className="h-9 w-9 text-gray-300" />
                                                )}
                                                <div>
                                                    <p className="font-medium text-gray-900">{user.name || 'Unnamed'}</p>
                                                    <p className="text-xs text-gray-500">{user.email}</p>
                                                </div>
                                            </div>
                                        </td>
                                        <td className="px-4 py-3 capitalize text-gray-700">{user.role === 'agent' ? 'PIO' : user.role}</td>
                                        <td className="px-4 py-3 text-gray-700">{user.mobile || '—'}</td>
                                        <td className="px-4 py-3">
                                            <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${user.is_verified ? 'bg-emerald-100 text-emerald-700' : 'bg-gray-100 text-gray-600'}`}>
                                                {user.is_verified ? 'Verified' : 'Unverified'}
                                            </span>
                                        </td>
                                        <td className="px-4 py-3">
                                            <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${user.account_frozen ? 'bg-red-100 text-red-700' : 'bg-emerald-100 text-emerald-700'}`}>
                                                {user.account_frozen ? 'Frozen' : 'Active'}
                                            </span>
                                        </td>
                                        <td className="px-4 py-3 text-gray-500">
                                            {user.created_at ? new Date(user.created_at).toLocaleDateString() : '—'}
                                        </td>
                                    </tr>
                                ))}
                                {filtered.length === 0 && !isLoading && (
                                    <tr>
                                        <td colSpan={6} className="px-4 py-10 text-center text-sm text-gray-500">
                                            No users found.
                                        </td>
                                    </tr>
                                )}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </AdminLayout>
    )
}
