import { HiDocumentText, HiShieldCheck } from 'react-icons/hi'
import { Link, useParams } from 'react-router-dom'

import LegalDocumentRenderer from '@/components/LegalDocumentRenderer'
import DashboardBackButton from '@/components/DashboardBackButton'
import { getLegalDocumentBySlug } from '@/lib/legalDocuments'

const audienceLabels = {
    shared: 'For all RentDirect users',
    registration: 'Account creation',
    tenant: 'Tenant document',
    landlord: 'Landlord document',
    agents: 'Agent and lawyer document',
} as const

export default function LegalDocumentPage() {
    const { slug } = useParams<{ slug: string }>()
    const document = getLegalDocumentBySlug(slug)

    if (!document) {
        return (
            <div className="min-h-[70vh] bg-[linear-gradient(180deg,#f8fbff_0%,#eef5ff_48%,#ffffff_100%)] px-4 py-16">
                <div className="mx-auto max-w-2xl rounded-[2rem] border border-slate-200 bg-white p-8 text-center shadow-sm">
                    <HiDocumentText className="mx-auto h-12 w-12 text-blue-600" aria-hidden="true" />
                    <h1 className="mt-5 text-2xl font-bold text-slate-950">Legal document not found</h1>
                    <p className="mt-3 text-slate-600">The document may have been moved or is no longer available.</p>
                    <Link to="/" className="btn btn-primary mt-7 inline-flex">Return home</Link>
                </div>
            </div>
        )
    }

    return (
        <div className="min-h-screen bg-[linear-gradient(180deg,#f8fbff_0%,#eef5ff_42%,#ffffff_100%)] px-4 py-8 sm:px-6 lg:px-8">
            <div className="mx-auto max-w-5xl">
                <DashboardBackButton to="/" label="Back to RentDirect" />

                <article className="mt-6 overflow-hidden rounded-[2rem] border border-slate-200 bg-white shadow-sm">
                    <header className="border-b border-blue-100 bg-[radial-gradient(circle_at_top_right,_rgba(37,99,235,0.16),_transparent_45%),linear-gradient(135deg,#f9fbff_0%,#eef4ff_55%,#ffffff_100%)] px-6 py-10 sm:px-10">
                        <div className="flex flex-wrap items-center gap-3">
                            <span className="inline-flex items-center gap-2 rounded-full bg-blue-100 px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.16em] text-blue-800">
                                <HiShieldCheck className="h-4 w-4" aria-hidden="true" />
                                RentDirect legal
                            </span>
                            <span className="rounded-full bg-white/80 px-3 py-1.5 text-xs font-semibold text-slate-600 ring-1 ring-slate-200">
                                {audienceLabels[document.audience]}
                            </span>
                        </div>
                        <h1 className="mt-6 text-3xl font-bold tracking-tight text-slate-950 sm:text-4xl">{document.title}</h1>
                        <p className="mt-4 max-w-3xl text-base leading-7 text-slate-600 sm:text-lg">{document.description}</p>
                        <div className="mt-6 inline-flex items-center gap-2 text-sm font-medium text-slate-500">
                            <HiDocumentText className="h-5 w-5 text-blue-600" aria-hidden="true" />
                            Review this document before giving your electronic consent.
                        </div>
                    </header>

                    <div className="px-6 py-8 sm:px-10 sm:py-10">
                        <LegalDocumentRenderer content={document.content} />
                    </div>
                </article>
            </div>
        </div>
    )
}
