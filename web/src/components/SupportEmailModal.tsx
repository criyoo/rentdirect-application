import { useState } from 'react'
import { HiClipboardCopy, HiMail } from 'react-icons/hi'

interface SupportEmailModalProps {
    isOpen: boolean
    email: string
    onClose: () => void
}

export default function SupportEmailModal({ isOpen, email, onClose }: SupportEmailModalProps) {
    const [copied, setCopied] = useState(false)

    if (!isOpen) return null

    const copyEmail = async () => {
        try {
            await navigator.clipboard.writeText(email)
            setCopied(true)
        } catch {
            setCopied(false)
        }
    }

    return (
        <div
            className="fixed inset-0 z-[200] flex items-center justify-center bg-slate-950/55 p-4 backdrop-blur-sm"
            role="presentation"
            onMouseDown={(event) => {
                if (event.target === event.currentTarget) onClose()
            }}
        >
            <div
                role="dialog"
                aria-modal="true"
                aria-labelledby="support-email-title"
                className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl sm:p-8"
            >
                <div className="flex items-start justify-between gap-4">
                    <div className="flex items-center gap-3">
                        <span className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-emerald-50">
                            <HiMail className="h-6 w-6 text-emerald-600" />
                        </span>
                        <h2 id="support-email-title" className="text-xl font-bold text-slate-950">
                            Email support
                        </h2>
                    </div>
                    <button
                        type="button"
                        aria-label="Close email support"
                        onClick={onClose}
                        className="rounded-lg p-2 text-2xl leading-none text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
                    >
                        ×
                    </button>
                </div>
                <p className="mt-4 text-sm leading-6 text-slate-600">
                    Send us a message and the RentDirect support team will get back to you.
                </p>
                <p className="mt-3 select-all rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-base font-semibold text-slate-900">
                    {email}
                </p>
                <div className="mt-6 flex justify-end gap-3">
                    <button type="button" onClick={onClose} className="btn btn-secondary">
                        Close
                    </button>
                    <button type="button" onClick={copyEmail} className="btn btn-primary inline-flex items-center gap-2">
                        <HiClipboardCopy className="h-5 w-5" />
                        {copied ? 'Copied' : 'Copy email'}
                    </button>
                </div>
            </div>
        </div>
    )
}
