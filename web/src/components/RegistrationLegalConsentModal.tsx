import { useMemo, useState } from 'react'
import { HiCheckCircle, HiDocumentText, HiShieldCheck, HiX } from 'react-icons/hi'

import LegalDocumentRenderer from '@/components/LegalDocumentRenderer'
import { getRegistrationLegalDocuments } from '@/lib/legalDocuments'

type RegistrationLegalConsentModalProps = {
    isOpen: boolean
    role: 'tenant' | 'landlord'
    onAccept: () => void
    onCancel: () => void
}

export default function RegistrationLegalConsentModal({ isOpen, role, onAccept, onCancel }: RegistrationLegalConsentModalProps) {
    const documents = useMemo(() => getRegistrationLegalDocuments(), [])
    const [accepted, setAccepted] = useState(false)

    if (!isOpen) return null

    return (
        <div className="fixed inset-0 z-[300] flex items-center justify-center bg-slate-950/60 p-4 backdrop-blur-sm">
            <div
                role="dialog"
                aria-modal="true"
                aria-labelledby="registration-legal-consent-title"
                className="flex max-h-[92vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"
            >
                <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-6 py-5 sm:px-8">
                    <div className="flex gap-3">
                        <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue-600 text-white">
                            <HiShieldCheck className="h-5 w-5" aria-hidden="true" />
                        </span>
                        <div>
                            <h2 id="registration-legal-consent-title" className="text-xl font-bold text-slate-950 sm:text-2xl">
                                Review account policies
                            </h2>
                            <p className="mt-1 text-sm leading-6 text-slate-600">
                                Your {role} account is email verified. Review these policies before continuing to RentDirect.
                            </p>
                        </div>
                    </div>
                    <button
                        type="button"
                        onClick={onCancel}
                        className="rounded-full p-2 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
                        aria-label="Cancel registration and sign out"
                    >
                        <HiX className="h-5 w-5" aria-hidden="true" />
                    </button>
                </div>

                <div className="min-h-0 overflow-y-auto px-6 py-5 sm:px-8">
                    <div className="space-y-4">
                        {documents.map((document) => (
                            <article key={document.slug} className="overflow-hidden rounded-xl border border-slate-200 bg-slate-50">
                                <div className="flex items-center gap-2 border-b border-slate-200 bg-white px-4 py-3">
                                    <HiDocumentText className="h-5 w-5 text-blue-600" aria-hidden="true" />
                                    <h3 className="font-semibold text-slate-950">{document.title}</h3>
                                </div>
                                <div className="max-h-72 overflow-y-auto px-4 py-5 sm:px-6">
                                    <LegalDocumentRenderer content={document.content} />
                                </div>
                            </article>
                        ))}
                    </div>

                    <label className="mt-5 flex cursor-pointer items-start gap-3 rounded-xl border border-blue-100 bg-blue-50/70 p-4">
                        <input
                            type="checkbox"
                            checked={accepted}
                            onChange={(event) => setAccepted(event.target.checked)}
                            className="mt-1 h-5 w-5 shrink-0 rounded border-slate-300 text-blue-600 accent-blue-600 focus:ring-2 focus:ring-blue-500"
                        />
                        <span className="text-sm leading-6 text-slate-700">
                            I confirm that I have reviewed and agree to the Cookies Policy and Privacy Policy. I understand that ticking this box is my electronic confirmation of consent for creating and using my RentDirect account.
                        </span>
                    </label>
                </div>

                <div className="flex flex-col-reverse gap-3 border-t border-slate-200 bg-white px-6 py-5 sm:flex-row sm:justify-end sm:px-8">
                    <button type="button" onClick={onCancel} className="btn btn-secondary">
                        Cancel and sign out
                    </button>
                    <button type="button" onClick={onAccept} disabled={!accepted} className="btn btn-primary disabled:cursor-not-allowed disabled:opacity-50">
                        <HiCheckCircle className="mr-2 h-5 w-5" aria-hidden="true" />
                        Agree and continue
                    </button>
                </div>
            </div>
        </div>
    )
}
