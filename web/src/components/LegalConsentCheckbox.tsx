import { HiOutlineDocumentText, HiShieldCheck } from 'react-icons/hi'
import { Link } from 'react-router-dom'

type LegalConsentDocument = {
    slug: string
    title: string
}

type LegalConsentCheckboxProps = {
    id: string
    documents: LegalConsentDocument[]
    checked: boolean
    onChange: (checked: boolean) => void
    error?: string
    disabled?: boolean
}

export default function LegalConsentCheckbox({ id, documents, checked, onChange, error, disabled = false }: LegalConsentCheckboxProps) {
    return (
        <div className={`rounded-2xl border p-5 ${error ? 'border-red-300 bg-red-50/60' : 'border-blue-100 bg-blue-50/60'}`}>
            <div className="flex gap-3">
                <HiShieldCheck className="mt-0.5 h-6 w-6 shrink-0 text-blue-700" aria-hidden="true" />
                <div className="min-w-0 flex-1">
                    <div className="flex items-start gap-3">
                        <input
                            id={id}
                            type="checkbox"
                            checked={checked}
                            disabled={disabled}
                            onChange={(event) => onChange(event.target.checked)}
                            aria-invalid={Boolean(error)}
                            aria-describedby={error ? `${id}-error` : undefined}
                            className="mt-1 h-5 w-5 shrink-0 rounded border-slate-300 text-blue-600 accent-blue-600 focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-60"
                        />
                        <label htmlFor={id} className="cursor-pointer text-sm leading-6 text-slate-700">
                            I confirm that I have reviewed the applicable legal document(s) below and agree to them. I understand that ticking this box is my electronic confirmation of consent and signature for this verification submission.
                        </label>
                    </div>

                    <div className="mt-4 flex flex-wrap gap-2 pl-8">
                        {documents.map((document) => (
                            <Link
                                key={document.slug}
                                to={`/legal/${document.slug}`}
                                target="_blank"
                                rel="noreferrer"
                                className="inline-flex items-center gap-2 rounded-full bg-white px-3 py-2 text-xs font-semibold text-blue-700 shadow-sm ring-1 ring-blue-100 transition hover:bg-blue-100 hover:text-blue-900"
                            >
                                <HiOutlineDocumentText className="h-4 w-4" aria-hidden="true" />
                                Review {document.title}
                            </Link>
                        ))}
                    </div>

                    <p className="mt-3 pl-8 text-xs leading-5 text-slate-500">
                        Please open and review the document(s) before checking the box. You can revisit them at any time before submitting.
                    </p>
                    {error && <p id={`${id}-error`} className="mt-2 pl-8 text-sm font-medium text-red-700">{error}</p>}
                </div>
            </div>
        </div>
    )
}
