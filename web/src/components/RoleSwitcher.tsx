import { useEffect, useRef, useState } from 'react'
import { HiCheck, HiChevronDown, HiPlus, HiUserCircle } from 'react-icons/hi'

import { useAuth } from '@/hooks/useAuth'
import type { AccountRole } from '@/types'

type CustomerRole = Exclude<AccountRole, 'admin'>

const ROLE_LABELS: Record<CustomerRole, string> = {
    tenant: 'Tenant',
    landlord: 'Landlord',
    agent: 'PIO',
}

const CUSTOMER_ROLES: CustomerRole[] = ['tenant', 'landlord', 'agent']

const ADD_ROLE_DESCRIPTIONS: Record<CustomerRole, string> = {
    tenant: 'Browse listings, chat with landlords, and manage your rental.',
    landlord: 'List properties and manage enquiries from tenants.',
    agent: 'Complete property inspections and earn referral rewards.',
}

export default function RoleSwitcher({ onComplete }: { onComplete?: () => void }) {
    const { user, switchRole, activateRole } = useAuth()
    const [isOpen, setIsOpen] = useState(false)
    const [pendingRole, setPendingRole] = useState<CustomerRole | null>(null)
    const [referralCode, setReferralCode] = useState('')
    const [error, setError] = useState('')
    const [busy, setBusy] = useState(false)
    const rootRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        if (!isOpen) return
        const onPointerDown = (event: MouseEvent) => {
            if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
                setIsOpen(false)
            }
        }
        const onEscape = (event: KeyboardEvent) => {
            if (event.key === 'Escape') setIsOpen(false)
        }
        document.addEventListener('mousedown', onPointerDown)
        document.addEventListener('keydown', onEscape)
        return () => {
            document.removeEventListener('mousedown', onPointerDown)
            document.removeEventListener('keydown', onEscape)
        }
    }, [isOpen])

    if (!user || user.role === 'admin') return null

    const activeRoles = (user.available_roles?.length ? user.available_roles : [user.role]).filter(
        (role): role is CustomerRole => role !== 'admin',
    )
    const addableRoles = CUSTOMER_ROLES.filter((role) => !activeRoles.includes(role))
    const currentLabel = ROLE_LABELS[user.role as CustomerRole]

    const handleSwitch = async (role: CustomerRole) => {
        if (busy || role === user.role) return
        setBusy(true)
        setError('')
        try {
            await switchRole(role)
            setIsOpen(false)
            onComplete?.()
        } catch (err: any) {
            setError(err?.message || 'Unable to switch role')
        } finally {
            setBusy(false)
        }
    }

    const handleConfirmActivation = async () => {
        if (!pendingRole || busy) return
        setBusy(true)
        setError('')
        try {
            await activateRole(pendingRole, pendingRole === 'agent' ? referralCode : undefined)
            setPendingRole(null)
            setReferralCode('')
            setIsOpen(false)
            onComplete?.()
        } catch (err: any) {
            setError(err?.message || 'Unable to add role')
        } finally {
            setBusy(false)
        }
    }

    return (
        <div ref={rootRef} className="relative">
            <button
                type="button"
                onClick={() => {
                    setIsOpen((open) => !open)
                    setPendingRole(null)
                    setError('')
                }}
                aria-expanded={isOpen}
                aria-label={`Switch role, currently ${currentLabel}`}
                className="group btn gap-2 bg-indigo-50 text-sm font-semibold text-indigo-700 shadow-sm transition-all duration-300 hover:-translate-y-0.5 hover:bg-indigo-100 hover:shadow-md active:scale-95"
            >
                <HiUserCircle className="h-6 w-6 transition-transform duration-300 group-hover:scale-110" />
                <span>{currentLabel}</span>
                <HiChevronDown className={`h-4 w-4 transition-transform duration-300 ${isOpen ? 'rotate-180' : ''}`} />
            </button>

            {isOpen && (
                <div className="absolute left-0 right-auto z-50 mt-2 w-72 rounded-xl border border-slate-200 bg-white p-2 shadow-lg md:left-auto md:right-0">
                    <p className="px-3 pb-1 pt-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
                        Active roles
                    </p>
                    <div className="flex flex-col gap-1">
                        {activeRoles.map((role) => (
                            <button
                                key={role}
                                type="button"
                                disabled={busy || role === user.role}
                                onClick={() => void handleSwitch(role)}
                                className={`flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm font-semibold transition-colors disabled:opacity-60 ${role === user.role
                                    ? 'bg-indigo-50 text-indigo-700'
                                    : 'text-slate-700 hover:bg-slate-50'
                                    }`}
                            >
                                <span>{ROLE_LABELS[role]}</span>
                                {role === user.role && <HiCheck className="h-4 w-4" />}
                            </button>
                        ))}
                    </div>

                    {addableRoles.length > 0 && (
                        <>
                            <p className="px-3 pb-1 pt-3 text-xs font-semibold uppercase tracking-wide text-slate-400">
                                Add another role
                            </p>
                            <div className="flex flex-col gap-1">
                                {addableRoles.map((role) => (
                                    <button
                                        key={role}
                                        type="button"
                                        disabled={busy}
                                        onClick={() => {
                                            setPendingRole(role)
                                            setReferralCode('')
                                            setError('')
                                        }}
                                        className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm font-semibold text-slate-700 transition-colors hover:bg-slate-50 disabled:opacity-60"
                                    >
                                        <HiPlus className="h-4 w-4 text-indigo-500" />
                                        <span>{ROLE_LABELS[role]}</span>
                                    </button>
                                ))}
                            </div>
                        </>
                    )}

                    {pendingRole && (
                        <div className="mt-2 rounded-lg border border-indigo-100 bg-indigo-50/60 p-3">
                            <p className="text-sm font-semibold text-slate-800">
                                Add {ROLE_LABELS[pendingRole]} role?
                            </p>
                            <p className="mt-1 text-xs text-slate-500">
                                {ADD_ROLE_DESCRIPTIONS[pendingRole]}
                            </p>
                            {pendingRole === 'agent' && (
                                <input
                                    type="text"
                                    value={referralCode}
                                    onChange={(event) => setReferralCode(event.target.value)}
                                    placeholder="Referral code (optional)"
                                    aria-label="PIO referral code"
                                    disabled={busy}
                                    className="form-input mt-2 w-full text-sm"
                                />
                            )}
                            <div className="mt-3 flex items-center gap-2">
                                <button
                                    type="button"
                                    disabled={busy}
                                    onClick={() => void handleConfirmActivation()}
                                    className="btn btn-primary flex-1 px-3 py-1.5 text-sm font-semibold disabled:opacity-60"
                                >
                                    {busy ? 'Please wait...' : 'Confirm'}
                                </button>
                                <button
                                    type="button"
                                    disabled={busy}
                                    onClick={() => {
                                        setPendingRole(null)
                                        setReferralCode('')
                                        setError('')
                                    }}
                                    className="btn btn-outline flex-1 px-3 py-1.5 text-sm font-semibold disabled:opacity-60"
                                >
                                    Cancel
                                </button>
                            </div>
                        </div>
                    )}

                    {error && (
                        <p role="alert" className="mt-2 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">
                            {error}
                        </p>
                    )}
                </div>
            )}
        </div>
    )
}
