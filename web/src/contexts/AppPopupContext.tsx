import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import {
    HiCheckCircle,
    HiExclamation,
    HiInformationCircle,
    HiQuestionMarkCircle,
    HiX,
    HiXCircle,
} from 'react-icons/hi'

type PopupVariant = 'info' | 'success' | 'warning' | 'error' | 'confirm'
type PopupMode = 'alert' | 'confirm'

type PopupOptions = {
    title?: string
    variant?: PopupVariant
    confirmLabel?: string
    cancelLabel?: string
    autoConfirmSeconds?: number
}

type PopupRequest = Required<Pick<PopupOptions, 'confirmLabel' | 'cancelLabel'>> & {
    id: number
    mode: PopupMode
    title: string
    message: string
    variant: PopupVariant
    autoConfirmSeconds?: number
    resolve: (value: boolean) => void
}

type AppPopupContextValue = {
    alert: (message: string, options?: PopupOptions) => Promise<void>
    confirm: (message: string, options?: PopupOptions) => Promise<boolean>
}

const AppPopupContext = createContext<AppPopupContextValue | null>(null)

function inferVariant(message: string): PopupVariant {
    const normalized = message.toLowerCase()
    if (/\b(success|successfully|confirmed|updated|saved|sent|complete|uploaded)\b/.test(normalized)) {
        return 'success'
    }
    if (/\b(failed|error|unable|invalid|cannot|not allowed|rejected)\b/.test(normalized)) {
        return 'error'
    }
    if (/\b(please|required|pending|warning|sure)\b/.test(normalized)) {
        return 'warning'
    }
    return 'info'
}

function variantStyles(variant: PopupVariant) {
    switch (variant) {
        case 'success':
            return {
                icon: HiCheckCircle,
                iconClass: 'text-emerald-600',
                accentClass: 'from-emerald-500 via-sky-500 to-blue-600',
                ringClass: 'bg-emerald-50',
            }
        case 'warning':
            return {
                icon: HiExclamation,
                iconClass: 'text-amber-600',
                accentClass: 'from-amber-400 via-sky-500 to-blue-600',
                ringClass: 'bg-amber-50',
            }
        case 'error':
            return {
                icon: HiXCircle,
                iconClass: 'text-red-600',
                accentClass: 'from-red-500 via-rose-500 to-blue-600',
                ringClass: 'bg-red-50',
            }
        case 'confirm':
            return {
                icon: HiQuestionMarkCircle,
                iconClass: 'text-blue-600',
                accentClass: 'from-blue-600 via-sky-500 to-emerald-500',
                ringClass: 'bg-blue-50',
            }
        default:
            return {
                icon: HiInformationCircle,
                iconClass: 'text-blue-600',
                accentClass: 'from-blue-600 via-sky-500 to-emerald-500',
                ringClass: 'bg-blue-50',
            }
    }
}

export function AppPopupProvider({ children }: { children: ReactNode }) {
    const [popup, setPopup] = useState<PopupRequest | null>(null)
    const [countdownSeconds, setCountdownSeconds] = useState<number | null>(null)

    const openPopup = useCallback((mode: PopupMode, message: string, options: PopupOptions = {}) => (
        new Promise<boolean>((resolve) => {
            const variant = options.variant || (mode === 'confirm' ? 'confirm' : inferVariant(message))
            setPopup({
                id: Date.now(),
                mode,
                title: options.title || (mode === 'confirm' ? 'Please confirm' : 'RentDirect'),
                message,
                variant,
                confirmLabel: options.confirmLabel || (mode === 'confirm' ? 'Confirm' : 'OK'),
                cancelLabel: options.cancelLabel || 'Cancel',
                autoConfirmSeconds: options.autoConfirmSeconds,
                resolve,
            })
        })
    ), [])

    const alert = useCallback(async (message: string, options?: PopupOptions) => {
        await openPopup('alert', message, options)
    }, [openPopup])

    const confirm = useCallback((message: string, options?: PopupOptions) => (
        openPopup('confirm', message, options)
    ), [openPopup])

    useEffect(() => {
        const originalAlert = window.alert
        window.alert = (message?: unknown) => {
            void alert(String(message ?? ''))
        }
        return () => {
            window.alert = originalAlert
        }
    }, [alert])

    const closePopup = useCallback((accepted: boolean) => {
        setPopup((current) => {
            if (current) {
                current.resolve(accepted)
            }
            return null
        })
        setCountdownSeconds(null)
    }, [])

    useEffect(() => {
        if (!popup?.autoConfirmSeconds || popup.mode !== 'confirm') {
            setCountdownSeconds(null)
            return
        }

        const deadline = Date.now() + popup.autoConfirmSeconds * 1000
        setCountdownSeconds(popup.autoConfirmSeconds)

        const intervalId = window.setInterval(() => {
            const remainingSeconds = Math.max(0, Math.ceil((deadline - Date.now()) / 1000))
            setCountdownSeconds(remainingSeconds)

            if (remainingSeconds <= 0) {
                window.clearInterval(intervalId)
                closePopup(true)
            }
        }, 250)

        return () => {
            window.clearInterval(intervalId)
        }
    }, [closePopup, popup?.autoConfirmSeconds, popup?.id, popup?.mode])

    const value = useMemo(() => ({ alert, confirm }), [alert, confirm])
    const styles = popup ? variantStyles(popup.variant) : null
    const Icon = styles?.icon

    const countdownLabel = countdownSeconds === 1 ? 'second' : 'seconds'

    const handleClosePopup = (accepted: boolean) => {
        if (!popup) return
        closePopup(accepted)
    }

    return (
        <AppPopupContext.Provider value={value}>
            {children}
            {popup && styles && Icon && (
                <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-gray-950/45 px-4 py-6 backdrop-blur-sm">
                    <div className="w-full max-w-md overflow-hidden rounded-2xl border border-white/60 bg-white shadow-2xl">
                        <div className={`h-1.5 bg-gradient-to-r ${styles.accentClass}`} />
                        <div className="p-6">
                            <div className="flex items-start gap-4">
                                <div className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-full ${styles.ringClass}`}>
                                    <Icon className={`h-7 w-7 ${styles.iconClass}`} />
                                </div>
                                <div className="min-w-0 flex-1">
                                    <div className="flex items-start justify-between gap-3">
                                        <h2 className="text-xl font-semibold text-gray-900">{popup.title}</h2>
                                        {popup.mode === 'alert' && (
                                            <button
                                                type="button"
                                                onClick={() => handleClosePopup(true)}
                                                className="rounded-full p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700"
                                                aria-label="Close"
                                            >
                                                <HiX className="h-5 w-5" />
                                            </button>
                                        )}
                                    </div>
                                    <p className="mt-3 whitespace-pre-line text-sm leading-6 text-gray-600">{popup.message}</p>
                                    {popup.autoConfirmSeconds && countdownSeconds !== null && (
                                        <p className="mt-3 rounded-lg bg-emerald-50 px-3 py-2 text-sm font-medium text-emerald-700">
                                            Redirecting automatically in {countdownSeconds} {countdownLabel}.
                                        </p>
                                    )}
                                </div>
                            </div>
                            <div className="mt-6 flex justify-end gap-3">
                                {popup.mode === 'confirm' && (
                                    <button
                                        type="button"
                                        onClick={() => handleClosePopup(false)}
                                        className="btn btn-secondary"
                                    >
                                        {popup.cancelLabel}
                                    </button>
                                )}
                                <button
                                    type="button"
                                    onClick={() => handleClosePopup(true)}
                                    className={popup.variant === 'error' ? 'btn btn-danger' : 'btn btn-primary'}
                                >
                                    {popup.confirmLabel}
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </AppPopupContext.Provider>
    )
}

export function useAppPopup() {
    const context = useContext(AppPopupContext)
    if (!context) {
        throw new Error('useAppPopup must be used within AppPopupProvider')
    }
    return context
}
