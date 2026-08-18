export const FORM_DRAFT_KEY_PREFIX = 'rentdirect:form-draft:'

const LEGACY_FORM_DRAFT_KEY_PREFIXES = [
    'rentdirect:tenant-profile-draft:',
]

function canUseStorage(storage: Storage | undefined): storage is Storage {
    return typeof window !== 'undefined' && Boolean(storage)
}

export function buildFormDraftKey(formName: string, identity?: string | number | null): string | null {
    if (!identity) return null
    return `${FORM_DRAFT_KEY_PREFIX}${formName}:${encodeURIComponent(String(identity))}`
}

export function readFormDraft<T>(storageKey: string | null): T | null {
    if (!storageKey || typeof window === 'undefined') return null

    try {
        const storedDraft = window.sessionStorage.getItem(storageKey)
        if (!storedDraft) return null
        return JSON.parse(storedDraft) as T
    } catch {
        return null
    }
}

export function writeFormDraft(storageKey: string | null, value: unknown): void {
    if (!storageKey || typeof window === 'undefined') return

    try {
        window.sessionStorage.setItem(storageKey, JSON.stringify(value))
    } catch {
        // Storage can be unavailable or full. Form input should remain usable.
    }
}

export function removeFormDraft(storageKey: string | null): void {
    if (!storageKey || typeof window === 'undefined') return

    try {
        window.sessionStorage.removeItem(storageKey)
        window.localStorage.removeItem(storageKey)
    } catch {
        // Ignore storage privacy-mode errors.
    }
}

export function clearFormDrafts(): void {
    if (typeof window === 'undefined') return

    const prefixes = [FORM_DRAFT_KEY_PREFIX, ...LEGACY_FORM_DRAFT_KEY_PREFIXES]
    for (const storage of [window.sessionStorage, window.localStorage]) {
        if (!canUseStorage(storage)) continue

        try {
            const keysToRemove: string[] = []
            for (let index = 0; index < storage.length; index += 1) {
                const key = storage.key(index)
                if (key && prefixes.some((prefix) => key.startsWith(prefix))) {
                    keysToRemove.push(key)
                }
            }
            keysToRemove.forEach((key) => storage.removeItem(key))
        } catch {
            // Ignore storage privacy-mode errors during logout.
        }
    }
}
