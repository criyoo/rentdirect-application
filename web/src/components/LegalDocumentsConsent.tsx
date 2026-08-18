import { useEffect, useMemo, useState } from 'react'
import { HiCheckCircle, HiChevronDown, HiDocumentText, HiLockClosed } from 'react-icons/hi'

import LegalDocumentRenderer from '@/components/LegalDocumentRenderer'
import { getLegalDocumentsForAudience, LegalDocumentAudience } from '@/lib/legalDocuments'

type LegalDocumentsConsentProps = {
    id: string
    audience: Extract<LegalDocumentAudience, 'tenant' | 'landlord'>
    signerName?: string
    consented: boolean
    onConsentChange: (consented: boolean) => void
    disabled?: boolean
}

function addToSet(current: Set<string>, value: string): Set<string> {
    const next = new Set(current)
    next.add(value)
    return next
}

export default function LegalDocumentsConsent({ id, audience, signerName = '', consented, onConsentChange, disabled = false }: LegalDocumentsConsentProps) {
    const documents = useMemo(() => getLegalDocumentsForAudience(audience), [audience])
    const [openSlug, setOpenSlug] = useState<string | null>(null)
    const [openedSlugs, setOpenedSlugs] = useState<Set<string>>(new Set())
    const [checkableSlugs, setCheckableSlugs] = useState<Set<string>>(new Set())
    const [readSlugs, setReadSlugs] = useState<Set<string>>(new Set())
    const [consentError, setConsentError] = useState('')
    const [consentDate] = useState(() => new Date().toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
    }))

    const allDocumentsOpened = documents.every((document) => openedSlugs.has(document.slug))
    const allDocumentsRead = documents.every((document) => readSlugs.has(document.slug))
    const canConsent = allDocumentsOpened && allDocumentsRead

    useEffect(() => {
        setOpenSlug(null)
        setOpenedSlugs(new Set())
        setCheckableSlugs(new Set())
        setReadSlugs(new Set())
        setConsentError('')
        onConsentChange(false)
    }, [audience, onConsentChange])

    useEffect(() => {
        if (!openSlug) return

        const contentElement = document.getElementById(`${id}-${openSlug}-content`)
        if (contentElement && contentElement.scrollHeight <= contentElement.clientHeight + 8) {
            setCheckableSlugs((current) => addToSet(current, openSlug))
        }
    }, [id, openSlug])

    const handleDocumentToggle = (slug: string) => {
        setOpenedSlugs((current) => addToSet(current, slug))
        setOpenSlug((current) => current === slug ? null : slug)
        setConsentError('')
    }

    const handleDocumentScroll = (slug: string, scrollTop: number, clientHeight: number, scrollHeight: number) => {
        if (scrollTop + clientHeight >= scrollHeight - 8) {
            setCheckableSlugs((current) => addToSet(current, slug))
        }
    }

    const handleDocumentCheck = (slug: string, checked: boolean) => {
        setReadSlugs((current) => {
            const next = new Set(current)
            if (checked) {
                next.add(slug)
            } else {
                next.delete(slug)
            }
            return next
        })
        setConsentError('')
    }

    const handleConsent = () => {
        if (!canConsent) {
            setConsentError('Scroll through every legal document and tick each document checkbox before giving consent.')
            return
        }
        setConsentError('')
        onConsentChange(true)
    }

    return (
        <section className="rounded-2xl border border-blue-100 bg-blue-50/60 p-5 sm:p-6" aria-labelledby={`${id}-heading`}>
            <div className="flex items-start gap-3">
                <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue-600 text-white shadow-sm">
                    <HiDocumentText className="h-5 w-5" aria-hidden="true" />
                </span>
                <div>
                    <h2 id={`${id}-heading`} className="text-lg font-semibold text-slate-950">Review terms & conditions and give your consent</h2>
                    <p className="mt-1 text-sm leading-6 text-slate-600">
                        Read terms and condition below to mark as read. Then “I have read & consent” before submitting your verification.
                    </p>
                </div>
            </div>

            <div className="mt-5 space-y-3">
                {documents.map((document, index) => {
                    const isOpen = openSlug === document.slug
                    const isRead = readSlugs.has(document.slug)
                    const isOpened = openedSlugs.has(document.slug)
                    const canCheckDocument = checkableSlugs.has(document.slug)
                    const checkboxId = `${id}-${document.slug}-checkbox`

                    return (
                        <div key={document.slug} className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
                            <button
                                type="button"
                                onClick={() => handleDocumentToggle(document.slug)}
                                aria-expanded={isOpen}
                                aria-controls={`${id}-${document.slug}-content`}
                                disabled={disabled}
                                className="flex w-full items-center justify-between gap-4 px-4 py-4 text-left transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
                            >
                                <span className="flex min-w-0 items-center gap-3">
                                    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-50 text-xs font-bold text-blue-700">{index + 1}</span>
                                    <span className="min-w-0">
                                        <span className="block truncate text-sm font-semibold text-slate-900">{document.title}</span>
                                        <span className="mt-0.5 block text-xs text-slate-500">
                                            {isRead ? 'Read to the end' : isOpened ? 'Review document to mark as read.' : 'Open to review'}
                                        </span>
                                    </span>
                                </span>
                                <span className="flex shrink-0 items-center gap-2">
                                    {isRead && <HiCheckCircle className="h-5 w-5 text-emerald-600" aria-label="Document read" />}
                                    <HiChevronDown className={`h-5 w-5 text-slate-500 transition-transform ${isOpen ? 'rotate-180' : ''}`} aria-hidden="true" />
                                </span>
                            </button>

                            {isOpen && (
                                <div
                                    id={`${id}-${document.slug}-content`}
                                    role="region"
                                    aria-label={document.title}
                                    onScroll={(event) => handleDocumentScroll(
                                        document.slug,
                                        event.currentTarget.scrollTop,
                                        event.currentTarget.clientHeight,
                                        event.currentTarget.scrollHeight,
                                    )}
                                    className="max-h-[28rem] overflow-y-auto border-t border-slate-100 px-4 py-5 sm:px-6"
                                >
                                    <LegalDocumentRenderer content={document.content} />
                                    {canCheckDocument ? (
                                        <div className="mt-7 rounded-xl border border-blue-100 bg-blue-50/70 px-4 py-4">
                                            <div className="grid gap-2 text-sm text-slate-700 sm:grid-cols-2">
                                                <p><span className="font-semibold text-slate-900">Name:</span> {signerName || 'Not provided'}</p>
                                                <p><span className="font-semibold text-slate-900">Date:</span> {consentDate}</p>
                                            </div>
                                            <label htmlFor={checkboxId} className="mt-4 flex cursor-pointer items-start gap-3 text-sm leading-6 text-slate-700">
                                                <input
                                                    id={checkboxId}
                                                    type="checkbox"
                                                    checked={isRead}
                                                    disabled={disabled}
                                                    onChange={(event) => handleDocumentCheck(document.slug, event.target.checked)}
                                                    className="mt-1 h-5 w-5 shrink-0 rounded border-slate-300 text-blue-600 accent-blue-600 focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-60"
                                                />
                                                <span className="flex items-start gap-2">
                                                    <span>Ticking this checkbox serves as concent and electronic signature/acceptance of this document.</span>
                                                    {isRead && <HiCheckCircle className="mt-0.5 h-5 w-5 shrink-0 text-emerald-600" aria-label="Document read" />}
                                                </span>
                                            </label>
                                        </div>
                                    ) : (
                                        <div className="mt-7 rounded-xl bg-blue-50 px-4 py-3 text-center text-sm font-medium text-blue-800">
                                            Scroll to the bottom of this document to review and sign it.
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    )
                })}
            </div>

            <div className="mt-5 rounded-xl border border-blue-100 bg-white p-4">
                <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
                    <span className="font-medium text-slate-700">
                        {readSlugs.size} of {documents.length} documents read to the end
                    </span>
                    {consented && (
                        <span className="inline-flex items-center gap-1.5 font-semibold text-emerald-700">
                            <HiCheckCircle className="h-5 w-5" aria-hidden="true" />
                            Consent recorded for this submission
                        </span>
                    )}
                </div>

                <button
                    type="button"
                    onClick={handleConsent}
                    disabled={disabled || consented}
                    className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-blue-600 px-5 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
                >
                    {consented ? <HiCheckCircle className="h-5 w-5" aria-hidden="true" /> : <HiLockClosed className="h-5 w-5" aria-hidden="true" />}
                    {consented ? 'I have read & consented' : 'I have read & consent'}
                </button>

                {consentError && <p className="mt-3 text-sm font-medium text-red-700" role="alert">{consentError}</p>}
            </div>
        </section>
    )
}
