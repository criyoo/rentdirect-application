import { Link } from 'react-router-dom'
import {
    HiBadgeCheck,
    HiCash,
    HiClipboardCheck,
    HiDocumentText,
    HiLocationMarker,
    HiUserAdd,
} from 'react-icons/hi'

import AgentPublicHeader from '@/components/agent/AgentPublicHeader'

const STEPS = [
    {
        Icon: HiUserAdd,
        shade: 'bg-emerald-100 text-emerald-700',
        title: '1. Create your PIO account',
        body: 'Sign up free as a Property Inspection Officer. You will receive a unique 8-character referral code you can share with other officers.',
    },
    {
        Icon: HiBadgeCheck,
        shade: 'bg-teal-100 text-teal-700',
        title: '2. Verify your identity',
        body: 'Complete your profile and the one-time ₦500 identity verification (NIN, BVN and bank details). Verified PIOs can start claiming inspections.',
    },
    {
        Icon: HiLocationMarker,
        shade: 'bg-green-100 text-green-700',
        title: '3. Claim an inspection request',
        body: 'When a landlord requests physical verification, available requests appear on your dashboard. Claim one that is near you.',
    },
    {
        Icon: HiClipboardCheck,
        shade: 'bg-lime-100 text-lime-700',
        title: '4. Inspect the property',
        body: 'Visit the property and complete the structured checklist — condition, amenities, photos and supporting documents.',
    },
    {
        Icon: HiDocumentText,
        shade: 'bg-emerald-100 text-emerald-800',
        title: '5. Submit your report',
        body: 'Submit the inspection report from your dashboard. A signed PDF report is generated for the landlord and prospective tenants.',
    },
    {
        Icon: HiCash,
        shade: 'bg-teal-100 text-teal-800',
        title: '6. Get paid',
        body: 'Earn ₦10,000 for every completed inspection, paid to your verified bank account. No subscription, no hidden fees.',
    },
] as const

export default function AgentHowItWorksPage() {
    return (
        <div className="agent-theme min-h-screen bg-gradient-to-br from-emerald-50 via-white to-green-50">
            <AgentPublicHeader current="how-it-works" />

            <main className="container-modern pb-16 pt-40">
                <div className="mx-auto max-w-3xl text-center">
                    <p className="text-sm font-semibold uppercase tracking-[0.2em] text-emerald-600">How it works</p>
                    <h1 className="mt-4 text-4xl font-bold tracking-tight text-gray-900 sm:text-5xl">
                        From sign-up to payout in six steps
                    </h1>
                    <p className="mt-6 text-lg leading-8 text-gray-600">
                        The PIO journey is simple: verify once, then earn for every property you inspect.
                    </p>
                </div>

                <div className="mx-auto mt-16 grid max-w-5xl gap-6 sm:grid-cols-2 lg:grid-cols-3">
                    {STEPS.map(({ Icon, shade, title, body }) => (
                        <div key={title} className="card p-6">
                            <div className={`flex h-12 w-12 items-center justify-center rounded-2xl ${shade}`}>
                                <Icon className="h-7 w-7" />
                            </div>
                            <h2 className="mt-4 text-lg font-semibold text-gray-900">{title}</h2>
                            <p className="mt-2 text-sm leading-6 text-gray-600">{body}</p>
                        </div>
                    ))}
                </div>

                <div className="mx-auto mt-16 max-w-4xl">
                    <div className="card border-emerald-200 bg-emerald-50 p-8">
                        <h2 className="text-xl font-bold text-emerald-900">Referral bonuses</h2>
                        <p className="mt-3 text-sm leading-6 text-emerald-900">
                            Share your referral code with other officers. When a PIO who signed up with your
                            code completes a verified inspection, you earn an extra ₦2,000 — up to ₦10,000
                            per referral (their first five inspections). Track your whole referral tree from
                            the Referrals page on your dashboard.
                        </p>
                    </div>
                </div>

                <div className="mx-auto mt-16 max-w-3xl text-center">
                    <div className="flex flex-wrap items-center justify-center gap-4">
                        <Link to="/agents/register" className="btn bg-emerald-600 px-8 py-3 text-base font-semibold text-white shadow-sm transition-all hover:-translate-y-0.5 hover:bg-emerald-700 hover:shadow-lg">
                            Become a PIO
                        </Link>
                        <Link to="/agents/login" className="btn btn-outline px-8 py-3 text-base font-semibold">
                            PIO Login
                        </Link>
                    </div>
                </div>
            </main>
        </div>
    )
}
