import { createContext, useContext, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'
import { clearFormDrafts } from '@/lib/formDrafts'
import { User } from '@/types'

type RegistrationStarted = {
    email: string
    role: 'tenant' | 'landlord'
    expires_in_seconds: number
    message: string
}

type LoginForm = {
    email: string
    password: string
}

type RegisterForm = {
    name: string
    email: string
    password: string
    role: 'tenant' | 'landlord'
}

const LANDLORD_IDENTITY_ONBOARDING_KEY = 'landlord_onboarding_pending_identity'

type AuthContextValue = {
    user: User | null
    isRestoring: boolean
    login: (data: LoginForm) => Promise<void>
    register: (data: RegisterForm) => Promise<RegistrationStarted>
    verifyRegistration: (data: { email: string; otp_code: string }, options?: { navigate?: boolean }) => Promise<User>
    logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

function getStoredUser(): User | null {
    const stored = localStorage.getItem('user')
    if (!stored) return null

    try {
        const parsedUser = JSON.parse(stored)
        const isValidRole = ['tenant', 'landlord', 'admin'].includes(parsedUser.role)
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

function normalizeUser(payload: any, fallbackEmail?: string): User {
    const rawId = payload?.id ?? payload?.user_id

    if (rawId === undefined || rawId === null) {
        throw new Error('Login response did not include a user id')
    }

    return {
        id: String(rawId),
        role: payload.role,
        name: payload.name || payload.email?.split('@')[0] || fallbackEmail?.split('@')[0] || 'User',
        email: payload.email || fallbackEmail || '',
        profile_photo_url: payload.profile_photo_url ?? null,
        is_verified: payload.is_verified ?? false,
    }
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
            const nextUser = normalizeUser(response.data, data.email)

            setUser(nextUser)
            localStorage.setItem('user', JSON.stringify(nextUser))
            queryClient.setQueryData(['users', 'me'], response.data)

            if (options.navigate !== false) {
                if (nextUser.role === 'landlord') {
                    localStorage.setItem(LANDLORD_IDENTITY_ONBOARDING_KEY, '1')
                    navigate('/landlord/verification')
                } else if (nextUser.role === 'tenant') {
                    navigate('/verify')
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
            const nextUser = normalizeUser(response.data, data.email)

            setUser(nextUser)
            localStorage.setItem('user', JSON.stringify(nextUser))
            queryClient.setQueryData(['users', 'me'], response.data)

            if (nextUser.role === 'landlord') {
                navigate(`/dashboard/landlord/${nextUser.id}`)
            } else if (nextUser.role === 'tenant') {
                navigate(`/dashboard/tenant/${nextUser.id}`)
            } else if (nextUser.role === 'admin') {
                navigate('/admin/dashboard')
            }
        } catch (err: any) {
            throw new Error(extractErrorMessage(err, 'Login failed'))
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
        queryClient.removeQueries({ queryKey: ['users', 'me'] })
        navigate('/login')
    }

    return (
        <AuthContext.Provider value={{ user, isRestoring, login, register, verifyRegistration, logout }}>
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
