import { Link } from 'react-router-dom'
import { HiHome, HiSearch } from 'react-icons/hi'

interface RegistrationOptionsModalProps {
    isOpen: boolean
    onClose: () => void
}

export default function RegistrationOptionsModal({ isOpen, onClose }: RegistrationOptionsModalProps) {
    if (!isOpen) return null

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
                aria-labelledby="registration-options-title"
                className="w-full max-w-2xl rounded-2xl bg-white p-6 shadow-2xl sm:p-8"
            >
                <div className="flex items-start justify-between gap-4">
                    <div>
                        <p className="text-sm font-semibold uppercase tracking-[0.16em] text-blue-600">Join RentDirect</p>
                        <h2 id="registration-options-title" className="mt-2 text-2xl font-bold text-slate-950 sm:text-3xl">
                            How would you like to use RentDirect?
                        </h2>
                        <p className="mt-2 text-slate-600">
                            Choose the account type that best matches what you want to do.
                        </p>
                    </div>
                    <button
                        type="button"
                        aria-label="Close registration options"
                        onClick={onClose}
                        className="rounded-lg p-2 text-2xl leading-none text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
                    >
                        ×
                    </button>
                </div>

                <div className="mt-6 grid gap-4 sm:grid-cols-2">
                    <Link
                        to="/register?role=tenant"
                        onClick={onClose}
                        className="group rounded-xl border border-slate-200 p-5 transition-all hover:-translate-y-0.5 hover:border-blue-400 hover:bg-blue-50 hover:shadow-lg"
                    >
                        <HiSearch className="h-8 w-8 text-blue-600" />
                        <h3 className="mt-4 text-lg font-bold text-slate-950">Register &amp; Find Properties</h3>
                        <p className="mt-2 text-sm leading-6 text-slate-600">
                            Create a tenant account and start searching for verified homes.
                        </p>
                    </Link>
                    <Link
                        to="/register?role=landlord"
                        onClick={onClose}
                        className="group rounded-xl border border-slate-200 p-5 transition-all hover:-translate-y-0.5 hover:border-purple-400 hover:bg-purple-50 hover:shadow-lg"
                    >
                        <HiHome className="h-8 w-8 text-purple-600" />
                        <h3 className="mt-4 text-lg font-bold text-slate-950">Register &amp; List Properties</h3>
                        <p className="mt-2 text-sm leading-6 text-slate-600">
                            Create a landlord account and list properties for verified tenants.
                        </p>
                    </Link>
                </div>
            </div>
        </div>
    )
}
