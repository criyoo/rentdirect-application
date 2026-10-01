import { Link } from 'react-router-dom'
import { HiBadgeCheck, HiLocationMarker, HiShieldCheck, HiUserGroup } from 'react-icons/hi'

import AgentPublicHeader from '@/components/agent/AgentPublicHeader'

export default function AgentAboutPage() {
    return (
        <div className="agent-theme min-h-screen bg-gradient-to-br from-emerald-50 via-white to-green-50">
            <AgentPublicHeader current="about" />

            <main className="container-modern pb-16 pt-40">
                <div className="mx-auto max-w-3xl">
                    <p className="text-sm font-semibold uppercase tracking-[0.2em] text-emerald-600">About the PIO Network</p>
                    <h1 className="mt-4 text-4xl font-bold tracking-tight text-gray-900 sm:text-5xl">
                        Property Inspection Officers are the eyes of RentDirect
                    </h1>
                    <p className="mt-6 text-lg leading-8 text-gray-600">
                        RentDirect connects tenants and landlords directly — no middlemen, no inflated fees.
                        To keep listings honest, every property advertised on the platform is physically
                        verified by an independent Property Inspection Officer (PIO). That could be you.
                    </p>
                </div>

                <div className="mx-auto mt-16 grid max-w-5xl gap-6 sm:grid-cols-2">
                    <div className="card p-6">
                        <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-emerald-100 text-emerald-700">
                            <HiShieldCheck className="h-7 w-7" />
                        </div>
                        <h2 className="mt-4 text-lg font-semibold text-gray-900">Trusted verification</h2>
                        <p className="mt-2 text-sm leading-6 text-gray-600">
                            PIOs visit properties in person, follow a structured checklist, and submit a
                            verified report with photos and documents. Their work is what gives tenants the
                            confidence to rent sight-unseen.
                        </p>
                    </div>
                    <div className="card p-6">
                        <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-teal-100 text-teal-700">
                            <HiLocationMarker className="h-7 w-7" />
                        </div>
                        <h2 className="mt-4 text-lg font-semibold text-gray-900">Local and independent</h2>
                        <p className="mt-2 text-sm leading-6 text-gray-600">
                            PIOs are independent officers who work where they live. You claim inspection
                            requests near you, choose when you work, and earn for every completed inspection.
                        </p>
                    </div>
                    <div className="card p-6">
                        <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-green-100 text-green-700">
                            <HiBadgeCheck className="h-7 w-7" />
                        </div>
                        <h2 className="mt-4 text-lg font-semibold text-gray-900">Vetted and accountable</h2>
                        <p className="mt-2 text-sm leading-6 text-gray-600">
                            Every PIO completes identity verification (NIN, BVN and bank details) before
                            claiming inspections, so landlords and tenants can trust the reports they read.
                        </p>
                    </div>
                    <div className="card p-6">
                        <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-lime-100 text-lime-700">
                            <HiUserGroup className="h-7 w-7" />
                        </div>
                        <h2 className="mt-4 text-lg font-semibold text-gray-900">Grow with referrals</h2>
                        <p className="mt-2 text-sm leading-6 text-gray-600">
                            Each PIO gets a unique referral code. Invite other officers, and earn a bonus for
                            every inspection your referred PIOs complete — up to ₦10,000 per referral.
                        </p>
                    </div>
                </div>

                <div className="mx-auto mt-16 max-w-3xl text-center">
                    <h2 className="text-2xl font-bold text-gray-900">Ready to join the network?</h2>
                    <p className="mt-3 text-gray-600">
                        Registration is free. Complete your profile, verify your identity, and start
                        inspecting properties in your area.
                    </p>
                    <div className="mt-8 flex flex-wrap items-center justify-center gap-4">
                        <Link to="/agents/register" className="btn bg-emerald-600 px-8 py-3 text-base font-semibold text-white shadow-sm transition-all hover:-translate-y-0.5 hover:bg-emerald-700 hover:shadow-lg">
                            Become a PIO
                        </Link>
                        <Link to="/agents/how-it-works" className="btn btn-outline px-8 py-3 text-base font-semibold">
                            See how it works
                        </Link>
                    </div>
                </div>
            </main>
        </div>
    )
}
