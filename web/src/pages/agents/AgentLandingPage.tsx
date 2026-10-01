import { Link } from 'react-router-dom'
import { HiBadgeCheck, HiCash, HiClipboardCheck } from 'react-icons/hi'

import AgentPublicHeader from '@/components/agent/AgentPublicHeader'

export default function AgentLandingPage() {
    return (
        <div className="agent-theme min-h-screen bg-gradient-to-br from-emerald-50 via-white to-green-50">
            <AgentPublicHeader current="home" />

            <main className="container-modern pb-16 pt-40">
                <div className="mx-auto max-w-3xl text-center">
                    <p className="text-sm font-semibold uppercase tracking-[0.2em] text-emerald-600">RentDirect Inspection Officer Network</p>
                    <h1 className="mt-4 text-4xl font-bold tracking-tight text-gray-900 sm:text-5xl">
                        Earn money verifying properties near you
                    </h1>
                    <p className="mt-6 text-lg leading-8 text-gray-600">
                        Join RentDirect as an independent Property Inspection Officer. Visit properties on behalf of
                        landlords, complete structured inspection reports, and get paid for every verified
                        inspection you complete.
                    </p>
                    <div className="mt-10 flex flex-wrap items-center justify-center gap-4">
                        <Link to="/agents/register" className="btn bg-emerald-600 px-8 py-3 text-base font-semibold text-white shadow-sm transition-all hover:-translate-y-0.5 hover:bg-emerald-700 hover:shadow-lg">
                            Become a PIO
                        </Link>
                        <Link to="/agents/login" className="btn btn-outline px-8 py-3 text-base font-semibold">
                            PIO Login
                        </Link>
                    </div>
                </div>

                <div className="mx-auto mt-16 grid max-w-5xl gap-6 sm:grid-cols-4">
                    <div className="card p-6">
                        <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-teal-100 text-teal-700">
                            <HiBadgeCheck className="h-7 w-7" />
                        </div>
                        <h2 className="mt-4 text-lg font-semibold text-gray-900">Register free</h2>
                        <p className="mt-2 text-sm leading-6 text-gray-600">
                            Create your PIO account and complete your profile. A one-time identity
                            verification confirms you as a trusted inspector.
                        </p>
                    </div>
                    <div className="card p-6">
                        <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-green-100 text-green-700">
                            <HiClipboardCheck className="h-7 w-7" />
                        </div>
                        <h2 className="mt-4 text-lg font-semibold text-gray-900">Inspect properties</h2>
                        <p className="mt-2 text-sm leading-6 text-gray-600">
                            Claim in-person verification requests near you, visit the property, and submit a
                            structured inspection report with photos.
                        </p>
                    </div>
                    <div className="card p-6">
                        <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-lime-100 text-lime-700">
                            <HiCash className="h-7 w-7" />
                        </div>
                        <h2 className="mt-4 text-lg font-semibold text-gray-900">Get paid</h2>
                        <p className="mt-2 text-sm leading-6 text-gray-600">
                            Earn N10,000 for every completed inspection. No subscription required — you work when
                            requests are available in your area.
                        </p>
                    </div>
                    <div className="card p-6">
                        <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-emerald-100 text-emerald-700">
                            <HiClipboardCheck className="h-7 w-7" />
                        </div>
                        <h2 className="mt-4 text-lg font-semibold text-gray-900">Increase your earnings through referals</h2>
                        <p className="mt-2 text-sm leading-6 text-gray-600">
                            Earn additionally up to N10,000 when other PIO use your code to sign up and completes a property verification
                        </p>
                    </div>
                </div>
            </main>
        </div>
    )
}
