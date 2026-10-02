import { createContext, useContext, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'

import { ACCOUNT_ROLES, api } from '@/lib/api'
import { clearFormDrafts } from '@/lib/formDrafts'
import type { AccountRole, User } from '@/types'

type CustomerRole = Exclude<AccountRole, 'admin'>

type RegistrationStarted = {
    email: string
    role: CustomerRole
    expires_in_seconds: number
    message: string
}

type LoginForm = {
    email: string
    password: string
    role?: AccountRole
}

type RegisterForm = {
    name: string
    email: string
    password: string
    role: CustomerRole
    referral_code?: string
}

const LANDLORD_IDENTITY_ONBOARDING_KEY = 'landlord_onboarding_pending_identity'

type AuthContextValue = {
    user: User | null
    isRestoring: boolean
    login: (data: LoginForm) => Promise<void>
    loginWithGoogle: (code: string, options?: { role?: CustomerRole; referral_code?: string }) => Promise<void>
    register: (data: RegisterForm) => Promise<RegistrationStarted>
    verifyRegistration: (data: { email: string; otp_code: string }, options?: { navigate?: boolean }) => Promise<User>
    switchRole: (role: AccountRole) => Promise<void>
    activateRole: (role: CustomerRole, referralCode?: string) => Promise<void>
    logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

function getStoredUser(): User | null {
    const stored = localStorage.getItem('user')
    if (!stored) return null

    try {
        const parsedUser = JSON.parse(stored)
        const isValidRole = ACCOUNT_ROLES.includes(parsedUser.role)
        const hasRequiredFields = parsedUser && parsedUser.id && parsedUser.role && parsedUser.name && parsedUser.email

        if (hasRequiredFields && isValidRole) {
            return parsedUser
        }

        localStorage.removeItem('user')
        return null
    } catch {
        localStorage.removeItem('user')
        return null
    }
}

function normalizeAvailableRoles(payload: any): AccountRole[] {
    const raw = Array.isArray(payload?.available_roles)
        ? payload.available_roles
        : payload?.role
            ? [payload.role]
            : []
    return raw.filter(
        (role: unknown): role is AccountRole =>
            typeof role === 'string' && ACCOUNT_ROLES.includes(role as AccountRole),
    )
}

function normalizeUser(payload: any, fallbackEmail?: string): User {
    const rawId = payload?.id ?? payload?.user_id

    if (rawId === undefined || rawId === null) {
        throw new Error('Login response did not include a user id')
    }

    return {
        id: String(rawId),
        role: payload.role,
        available_roles: normalizeAvailableRoles(payload),
        name: payload.name || payload.email?.split('@')[0] || fallbackEmail?.split('@')[0] || 'User',
        email: payload.email || fallbackEmail || '',
        whatsapp_number: payload.whatsapp_number ?? '',
        profile_photo_url: payload.profile_photo_url ?? null,
        is_verified: payload.is_verified ?? false,
        account_frozen: payload.account_frozen ?? false,
        account_frozen_at: payload.account_frozen_at ?? null,
        account_frozen_until: payload.account_frozen_until ?? null,
        account_freeze_fee_percentage: payload.account_freeze_fee_percentage ?? 10,
    }
}

function dashboardPathFor(user: User): string {
    if (user.role === 'landlord') return `/dashboard/landlord/${user.id}`
    if (user.role === 'tenant') return `/dashboard/tenant/${user.id}`
    if (user.role === 'agent') return '/agents/dashboard'
    return '/admin/dashboard'
}

function firstErrorMessage(value: any): string {
    if (typeof value === 'string') {
        return value
    }

    if (Array.isArray(value)) {
        for (const item of value) {
            const message = firstErrorMessage(item)
            if (message) return message
        }
        return ''
    }

    if (value && typeof value === 'object') {
        for (const key of ['detail', 'message', 'error', 'email', 'non_field_errors']) {
            const message = firstErrorMessage(value[key])
            if (message) return message
        }

        for (const item of Object.values(value)) {
            const message = firstErrorMessage(item)
            if (message) return message
        }
    }

    return ''
}

function extractErrorMessage(err: any, fallbackMessage: string): string {
    return firstErrorMessage(err?.response?.data) || err?.message || fallbackMessage
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
    const navigate = useNavigate()
    const queryClient = useQueryClient()
    const [user, setUser] = useState<User | null>(() => getStoredUser())
    const [isRestoring, setIsRestoring] = useState(!getStoredUser())

    useEffect(() => {
        if (user) {
            setIsRestoring(false)
            return
        }

        let active = true
        setIsRestoring(true)

        api.get('/users/me')
            .then((res) => {
                if (!active) return
                const restoredUser = normalizeUser(res.data)
                setUser(restoredUser)
                localStorage.setItem('user', JSON.stringify(restoredUser))
            })
            .catch((err) => {
                if (!active) return
                localStorage.removeItem('user')
                if (err.response?.status !== 401 && err.code !== 'ERR_NETWORK') {
                    console.warn('Failed to restore user session:', err)
                }
            })
            .finally(() => {
                if (active) {
                    setIsRestoring(false)
                }
            })

        return () => {
            active = false
        }
    }, [user])

    useEffect(() => {
        const syncStoredUser = () => {
            setUser(getStoredUser())
        }

        window.addEventListener('rentdirect-user-updated', syncStoredUser)
        return () => window.removeEventListener('rentdirect-user-updated', syncStoredUser)
    }, [])

    function commitUser(payload: any, fallbackEmail?: string): User {
        const nextUser = normalizeUser(payload, fallbackEmail)
        setUser(nextUser)
        localStorage.setItem('user', JSON.stringify(nextUser))
        window.dispatchEvent(new Event('rentdirect-user-updated'))
        // Persona-sensitive caches must not leak between roles.
        queryClient.clear()
        queryClient.setQueryData(['users', 'me'], payload)
        return nextUser
    }

    async function register(data: RegisterForm): Promise<RegistrationStarted> {
        try {
            const response = await api.post<RegistrationStarted>('/auth/register', data)
            return response.data
        } catch (err: any) {
            throw new Error(extractErrorMessage(err, 'Registration failed'))
        }
    }

    async function verifyRegistration(data: { email: string; otp_code: string }, options: { navigate?: boolean } = {}): Promise<User> {
        try {
            const response = await api.post<User>('/auth/register/verify', data)
            const nextUser = commitUser(response.data, data.email)

            if (options.navigate !== false) {
                if (nextUser.role === 'landlord') {
                    localStorage.setItem(LANDLORD_IDENTITY_ONBOARDING_KEY, '1')
                    navigate('/landlord/verification')
                } else if (nextUser.role === 'tenant') {
                    navigate('/verify')
                } else if (nextUser.role === 'agent') {
                    navigate('/agents/verification')
                } else if (nextUser.role === 'admin') {
                    navigate('/admin/dashboard')
                }
            }

            return nextUser
        } catch (err: any) {
            throw new Error(extractErrorMessage(err, 'Verification failed'))
        }
    }

    async function login(data: LoginForm): Promise<void> {
        try {
            const response = await api.post('/auth/login', data)
            const nextUser = commitUser(response.data, data.email)
            const roleActivated = response.data?.role_activated === true
            if (roleActivated && nextUser.role === 'tenant') {
                navigate('/verify')
            } else if (roleActivated && nextUser.role === 'landlord') {
                localStorage.setItem(LANDLORD_IDENTITY_ONBOARDING_KEY, '1')
                navigate('/landlord/verification')
            } else if (roleActivated && nextUser.role === 'agent') {
                navigate('/agents/verification')
            } else {
                navigate(dashboardPathFor(nextUser))
            }
        } catch (err: any) {
            throw new Error(extractErrorMessage(err, 'Login failed'))
        }
    }

    async function loginWithGoogle(code: string, options: { role?: CustomerRole; referral_code?: string } = {}): Promise<void> {
        try {
            const response = await api.post('/auth/google/exchange', { code, role: options.role, referral_code: options.referral_code })
            const nextUser = commitUser(response.data)

            const isNewUser = response.data?.is_new_user === true
            const needsOnboarding = isNewUser || response.data?.role_activated === true
            if (nextUser.role === 'landlord') {
                if (needsOnboarding) {
                    localStorage.setItem(LANDLORD_IDENTITY_ONBOARDING_KEY, '1')
                    navigate('/landlord/verification')
                } else {
                    navigate(`/dashboard/landlord/${nextUser.id}`)
                }
            } else if (nextUser.role === 'tenant') {
                navigate(needsOnboarding ? '/verify' : `/dashboard/tenant/${nextUser.id}`)
            } else if (nextUser.role === 'agent') {
                navigate(needsOnboarding ? '/agents/verification' : '/agents/dashboard')
            } else if (nextUser.role === 'admin') {
                navigate('/admin/dashboard')
            }
        } catch (err: any) {
            throw new Error(extractErrorMessage(err, 'Google sign-in failed'))
        }
    }

    async function switchRole(role: AccountRole): Promise<void> {
        try {
            const response = await api.post('/users/me/active-role', { role })
            const nextUser = commitUser(response.data)
            navigate(dashboardPathFor(nextUser))
        } catch (err: any) {
            throw new Error(extractErrorMessage(err, 'Unable to switch role'))
        }
    }

    async function activateRole(role: CustomerRole, referralCode?: string): Promise<void> {
        try {
            const trimmedCode = referralCode?.trim()
            const response = await api.post('/users/me/roles', {
                role,
                referral_code: trimmedCode ? trimmedCode.toUpperCase() : undefined,
            })
            const nextUser = commitUser(response.data)
            if (nextUser.role === 'tenant') {
                navigate('/verify')
            } else if (nextUser.role === 'landlord') {
                localStorage.setItem(LANDLORD_IDENTITY_ONBOARDING_KEY, '1')
                navigate('/landlord/verification')
            } else if (nextUser.role === 'agent') {
                navigate('/agents/verification')
            }
        } catch (err: any) {
            throw new Error(extractErrorMessage(err, 'Unable to add role'))
        }
    }

    async function logout(): Promise<void> {
        try {
            await api.post('/auth/logout')
        } catch (err) {
            console.error('Logout error:', err)
        }

        setUser(null)
        setIsRestoring(false)
        localStorage.removeItem('user')
        clearFormDrafts()
        queryClient.clear()
        navigate('/login')
    }

    return (
        <AuthContext.Provider value={{ user, isRestoring, login, loginWithGoogle, register, verifyRegistration, switchRole, activateRole, logout }}>
            {children}
        </AuthContext.Provider>
    )
}

export function useAuth() {
    const context = useContext(AuthContext)
    if (!context) {
        throw new Error('useAuth must be used within AuthProvider')
    }
    return context
}
