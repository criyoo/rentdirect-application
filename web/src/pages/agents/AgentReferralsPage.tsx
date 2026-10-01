import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
    HiCash,
    HiCheckCircle,
    HiClipboardCopy,
    HiUserGroup,
    HiUsers,
} from 'react-icons/hi'

import { useAuth } from '@/hooks/useAuth'
import { useAppPopup } from '@/contexts/AppPopupContext'
import DashboardBackButton from '@/components/DashboardBackButton'
import { api, resolveMediaUrl } from '@/lib/api'
import { AgentReferralNode, AgentReferralsResponse } from '@/types'
import { formatCurrencyWithSymbol } from '@/utils/currency'

function PioAvatar({ node }: { node: AgentReferralNode }) {
    const initials = node.name
        .split(/\s+/)
        .filter(Boolean)
        .slice(0, 2)
        .map((part) => part[0]?.toUpperCase())
        .join('') || 'P'
    const photoUrl = node.profile_photo_url ? resolveMediaUrl(node.profile_photo_url) : ''
    return (
        <div className="relative">
            {photoUrl ? (
                <img
                    src={photoUrl}
                    alt={node.name}
                    loading="lazy"
                    decoding="async"
                    className="h-20 w-20 rounded-full border-4 border-white object-cover shadow-md"
                />
            ) : (
                <div className="flex h-20 w-20 items-center justify-center rounded-full border-4 border-white bg-emerald-100 text-xl font-bold text-emerald-700 shadow-md">
                    {initials}
                </div>
            )}
            <span
                className="absolute -bottom-1 -right-1 flex h-7 min-w-7 items-center justify-center rounded-full bg-emerald-600 px-1 text-xs font-bold text-white shadow"
                title={`${node.properties_inspected} ${node.properties_inspected === 1 ? 'property' : 'properties'} inspected`}
            >
                {node.properties_inspected}
            </span>
        </div>
    )
}

function ReferralTreeNode({ node, isRoot = false }: { node: AgentReferralNode; isRoot?: boolean }) {
    const earned = Number(node.earned_from_referral || 0)
    return (
        <div className="flex flex-col items-center">
            <PioAvatar node={node} />
            <p className="mt-2 max-w-36 truncate text-sm font-semibold text-gray-900" title={node.name}>
                {isRoot ? `${node.name} (You)` : node.name}
            </p>
            {node.referral_code ? (
                <p className="text-xs font-mono tracking-widest text-gray-500">{node.referral_code}</p>
            ) : null}
            <div className="mt-1 flex items-center gap-1.5">
                <span className={`badge ${node.is_verified ? 'badge-success' : 'badge-warning'}`}>
                    {node.is_verified ? 'Verified' : 'Unverified'}
                </span>
                {!isRoot && earned > 0 && (
                    <span className="badge badge-primary">{formatCurrencyWithSymbol(earned)}</span>
                )}
            </div>
            {node.children.length > 0 && (
                <>
                    <div className="h-6 w-px bg-gray-300" />
                    <div className="flex flex-wrap items-start justify-center gap-x-10 gap-y-6 border-t border-gray-300 pt-6">
                        {node.children.map((child) => (
                            <div key={child.id} className="flex flex-col items-center">
                                <div className="-mt-6 mb-0 h-6 w-px bg-gray-300" />
                                <ReferralTreeNode node={child} />
                            </div>
                        ))}
                    </div>
                </>
            )}
        </div>
    )
}

export default function AgentReferralsPage() {
    const { user } = useAuth()
    const { alert } = useAppPopup()
    const [copied, setCopied] = useState<'code' | 'link' | null>(null)

    const { data, isLoading } = useQuery({
        queryKey: ['agents', 'referrals', user?.id],
        enabled: Boolean(user),
        queryFn: async () => (await api.get<AgentReferralsResponse>('/agents/referrals')).data,
    })

    const referralLink = data?.referral_code
        ? `${window.location.origin}/agents/register?ref=${encodeURIComponent(data.referral_code)}`
        : ''

    const copy = async (value: string, kind: 'code' | 'link') => {
        try {
            await navigator.clipboard.writeText(value)
            setCopied(kind)
            setTimeout(() => setCopied(null), 2000)
        } catch {
            await alert('Could not copy to clipboard.', { variant: 'warning' })
        }
    }

    return (
        <div className="agent-theme min-h-screen bg-gradient-to-br from-emerald-50 via-white to-green-50">
            <div className="container-modern py-8">
                <div className="mb-8">
                    <div className="mb-5">
                        <DashboardBackButton to="/agents/dashboard" label="Back to dashboard" />
                    </div>
                    <h1 className="text-4xl font-bold text-gray-900 mb-2">My PIO Referrals</h1>
                    <p className="text-sm text-gray-600">
                        Share your referral code and earn {formatCurrencyWithSymbol(Number(data?.metrics.referral_earning_per_inspection || 0))} for
                        every property your referred PIOs inspect — up to {formatCurrencyWithSymbol(Number(data?.metrics.referral_earning_cap || 0))} per referral.
                    </p>
                </div>

                {data?.referred_by && (
                    <div className="mb-8 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-emerald-900">
                        <p className="text-sm">
                            You were referred by <span className="font-semibold">{data.referred_by.name}</span>.
                        </p>
                    </div>
                )}

                <div className="card mb-8 p-6">
                    <p className="text-sm font-medium text-gray-600">Your referral code</p>
                    <div className="mt-3 flex flex-wrap items-center gap-3">
                        <span className="rounded-lg bg-emerald-950 px-4 py-2 font-mono text-2xl font-bold tracking-[0.3em] text-emerald-400">
                            {isLoading ? '…' : data?.referral_code || '—'}
                        </span>
                        {data?.referral_code && (
                            <button
                                type="button"
                                onClick={() => void copy(data.referral_code, 'code')}
                                className="btn btn-outline px-4 py-2 text-sm"
                            >
                                <HiClipboardCopy className="mr-1 h-4 w-4" />
                                {copied === 'code' ? 'Copied!' : 'Copy code'}
                            </button>
                        )}
                    </div>
                    {referralLink && (
                        <div className="mt-4">
                            <p className="text-sm font-medium text-gray-600">Your referral link</p>
                            <div className="mt-2 flex flex-wrap items-center gap-3">
                                <code className="max-w-full truncate rounded-lg bg-gray-100 px-3 py-2 text-sm text-gray-700">
                                    {referralLink}
                                </code>
                                <button
                                    type="button"
                                    onClick={() => void copy(referralLink, 'link')}
                                    className="btn btn-primary px-4 py-2 text-sm"
                                >
                                    <HiClipboardCopy className="mr-1 h-4 w-4" />
                                    {copied === 'link' ? 'Copied!' : 'Copy link'}
                                </button>
                            </div>
                        </div>
                    )}
                </div>

                <div className="grid grid-cols-1 gap-6 mb-8 md:grid-cols-3">
                    <div className="card p-6">
                        <div className="flex items-center gap-3">
                            <HiUsers className="h-6 w-6 text-emerald-600" />
                            <p className="text-sm font-medium text-gray-600">PIOs Referred</p>
                        </div>
                        <p className="mt-3 text-3xl font-bold text-gray-900">{data?.metrics.total_referrals ?? 0}</p>
                        <p className="mt-2 text-sm text-gray-500">Signed up with your code</p>
                    </div>
                    <div className="card p-6">
                        <div className="flex items-center gap-3">
                            <HiCash className="h-6 w-6 text-emerald-600" />
                            <p className="text-sm font-medium text-gray-600">Referral Earnings</p>
                        </div>
                        <p className="mt-3 text-3xl font-bold text-gray-900">
                            {formatCurrencyWithSymbol(Number(data?.metrics.total_referral_earned || 0))}
                        </p>
                        <p className="mt-2 text-sm text-gray-500">Total earned from referrals</p>
                    </div>
                    <div className="card p-6">
                        <div className="flex items-center gap-3">
                            <HiCheckCircle className="h-6 w-6 text-green-600" />
                            <p className="text-sm font-medium text-gray-600">Referral Payouts</p>
                        </div>
                        <p className="mt-3 text-3xl font-bold text-green-600">
                            {formatCurrencyWithSymbol(Number(data?.metrics.total_referral_paid || 0))}
                        </p>
                        <p className="mt-2 text-sm text-gray-500">Paid out to you</p>
                    </div>
                </div>

                <div className="mb-12">
                    <div className="mb-6 flex items-center gap-3">
                        <HiUserGroup className="h-6 w-6 text-emerald-600" />
                        <h2 className="text-2xl font-bold text-gray-900">Referral Family Tree</h2>
                    </div>
                    {isLoading ? (
                        <div className="card p-10 text-center text-gray-600">Loading your referral tree…</div>
                    ) : data?.tree ? (
                        <div className="card overflow-x-auto p-8">
                            <div className="flex min-w-max justify-center">
                                <ReferralTreeNode node={data.tree} isRoot />
                            </div>
                            {(data.tree.children?.length ?? 0) === 0 && (
                                <p className="mt-6 text-center text-sm text-gray-500">
                                    No referrals yet — share your code or link to grow your tree.
                                </p>
                            )}
                        </div>
                    ) : null}
                </div>

                <div className="mb-12">
                    <h2 className="mb-6 text-2xl font-bold text-gray-900">Referral Earnings</h2>
                    {(data?.earnings?.length ?? 0) > 0 ? (
                        <div className="card overflow-x-auto p-6">
                            <table className="w-full min-w-[32rem] text-left text-sm">
                                <thead>
                                    <tr className="border-b border-gray-200 text-gray-500">
                                        <th className="pb-3 font-medium">Referred PIO</th>
                                        <th className="pb-3 font-medium">Amount</th>
                                        <th className="pb-3 font-medium">Payout</th>
                                        <th className="pb-3 font-medium">Date</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {data!.earnings.map((earning) => (
                                        <tr key={earning.id} className="border-b border-gray-100 last:border-0">
                                            <td className="py-3 font-medium text-gray-900">{earning.referred_name}</td>
                                            <td className="py-3 text-gray-700">{formatCurrencyWithSymbol(Number(earning.amount))}</td>
                                            <td className="py-3">
                                                <span className={`badge ${earning.payout_status === 'paid' ? 'badge-success' : 'badge-warning'}`}>
                                                    {earning.payout_status === 'paid' ? 'Paid' : 'Pending'}
                                                </span>
                                            </td>
                                            <td className="py-3 text-gray-500">
                                                {new Date(earning.created_at).toLocaleDateString()}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    ) : (
                        <div className="card p-10 text-center text-gray-600">
                            No referral earnings yet. When a PIO you referred completes inspections, earnings appear here.
                        </div>
                    )}
                </div>

                <div className="text-center">
                    <Link to="/agents/dashboard" className="btn btn-outline px-6 py-2 text-sm">
                        Back to dashboard
                    </Link>
                </div>
            </div>
        </div>
    )
}
