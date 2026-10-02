import { beforeEach, describe, expect, it, vi } from 'vitest'

const storage = new Map<string, string>()

vi.stubGlobal('window', {
    location: { hostname: 'localhost', protocol: 'http:' },
})
vi.stubGlobal('localStorage', {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => void storage.set(key, String(value)),
    removeItem: (key: string) => void storage.delete(key),
})

const { getStoredUserRole, getWebSocketUrl } = await import('./api')

beforeEach(() => {
    storage.clear()
})

describe('getStoredUserRole', () => {
    it('returns the stored role when it is a valid account role', () => {
        storage.set('user', JSON.stringify({ id: '1', role: 'landlord' }))
        expect(getStoredUserRole()).toBe('landlord')
    })

    it('rejects arbitrary stored text or roles', () => {
        expect(getStoredUserRole()).toBeNull()

        storage.set('user', 'not-json')
        expect(getStoredUserRole()).toBeNull()

        storage.set('user', JSON.stringify({ id: '1', role: 'superuser' }))
        expect(getStoredUserRole()).toBeNull()
    })
})

describe('getWebSocketUrl', () => {
    it('appends the validated active role and preserves existing query params', () => {
        storage.set('user', JSON.stringify({ id: '1', role: 'tenant' }))

        const url = getWebSocketUrl('/ws/messages?listing_id=abc-123')
        const parsed = new URL(url)

        expect(parsed.searchParams.get('listing_id')).toBe('abc-123')
        expect(parsed.searchParams.get('active_role')).toBe('tenant')
    })

    it('omits active_role when there is no valid stored role', () => {
        const url = getWebSocketUrl('/ws/community-chat')
        expect(new URL(url).searchParams.has('active_role')).toBe(false)
    })

    it('replaces an existing active_role parameter with the stored role', () => {
        storage.set('user', JSON.stringify({ id: '1', role: 'landlord' }))

        const url = getWebSocketUrl('/ws/support-chat?active_role=tenant')
        const parsed = new URL(url)

        expect(parsed.searchParams.getAll('active_role')).toEqual(['landlord'])
    })
})
