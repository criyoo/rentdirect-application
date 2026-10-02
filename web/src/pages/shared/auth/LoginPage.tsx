import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'
import BrandLogo from '@/components/BrandLogo'
import { buildFormDraftKey, readFormDraft, removeFormDraft, writeFormDraft } from '@/lib/formDrafts'
import { api } from '@/lib/api'
import { requestGoogleAuthorizationCode } from '@/lib/googleAuth'
import { HiEye, HiEyeOff, HiMail, HiLockClosed } from 'react-icons/hi'

interface LoginPageProps {
    lockedRole?: 'tenant' | 'landlord' | 'agent'
}

export default function LoginPage({ lockedRole }: LoginPageProps = {}) {
    const isAgentLogin = lockedRole === 'agent'
    const [email, setEmail] = useState('')
    const [password, setPassword] = useState('')
    const [showPassword, setShowPassword] = useState(false)
    const [error, setError] = useState('')
    const [googleBusy, setGoogleBusy] = useState(false)
    const { login, loginWithGoogle } = useAuth()
    const navigate = useNavigate()
    const draftStorageKey = useMemo(() => buildFormDraftKey('login', 'anonymous'), [])

    useEffect(() => {
        const storedDraft = readFormDraft<{ email?: string }>(draftStorageKey)
        if (storedDraft?.email) setEmail(storedDraft.email)
    }, [draftStorageKey])

    useEffect(() => {
        writeFormDraft(draftStorageKey, { email })
    }, [draftStorageKey, email])

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault()
        setError('')

        try {
            await login({ email, password, role: lockedRole })
            removeFormDraft(draftStorageKey)
        } catch (err: any) {
            setError(err.message || 'Login failed')
        }
    }

    const handleGoogleSignIn = async () => {
        setError('')
        setGoogleBusy(true)
        try {
            const start = await api.get('/auth/google/start')
            const clientId = start.data?.client_id
            if (!clientId) {
                setError('Google sign-in is unavailable right now.')
                return
            }
            const code = await requestGoogleAuthorizationCode(clientId)
            await loginWithGoogle(code, { role: lockedRole })
            removeFormDraft(draftStorageKey)
        } catch (err: any) {
            setError(err.message || 'Google sign-in could not be completed. Please try again.')
        } finally {
            setGoogleBusy(false)
        }
    }

    return (
        <div className={`min-h-screen flex items-center justify-center py-12 px-4 sm:px-6 lg:px-8 ${isAgentLogin
            ? 'agent-theme bg-gradient-to-br from-emerald-50 via-white to-green-50'
            : 'bg-gradient-to-br from-blue-50 via-white to-purple-50'
            }`}>
            <div className="max-w-md w-full space-y-8">
                {/* Header */}
                <div className="text-center">
                    <div className="flex justify-center -mb-14">
                        <BrandLogo className="h-80 w-80 mix-blend-multiply" />
                    </div>
                    <h2 className="text-3xl font-bold text-gray-900">
                        {isAgentLogin ? 'Welcome back, PIO' : 'Welcome back'}
                    </h2>
                    <p className="text-gray-600">
                        {isAgentLogin
                            ? 'Sign in to your Property Inspection Officer account'
                            : 'Sign in to your account to continue'}
                    </p>
                </div>

                {/* Login Form */}
                <div className="card p-8">
                    <form onSubmit={handleSubmit} className="space-y-6">
                        {error && (
                            <div className="bg-red-50 border border-red-200 rounded-lg p-4">
                                <div className="flex">
                                    <div className="flex-shrink-0">
                                        <svg className="h-5 w-5 text-red-400" viewBox="0 0 20 20" fill="currentColor">
                                            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                                        </svg>
                                    </div>
                                    <div className="ml-3">
                                        <p className="text-sm text-red-800">{error}</p>
                                    </div>
                                </div>
                            </div>
                        )}

                        {/* Email Field */}
                        <div>
                            <label htmlFor="email" className="form-label">
                                Email address
                            </label>
                            <div className="relative">
                                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                                    <HiMail className="h-5 w-5 text-gray-400" />
                                </div>
                                <input
                                    id="email"
                                    name="email"
                                    type="email"
                                    autoComplete="email"
                                    required
                                    value={email}
                                    onChange={(e) => setEmail(e.target.value)}
                                    className="form-input pl-10"
                                    placeholder="Enter your email"
                                />
                            </div>
                        </div>

                        {/* Password Field */}
                        <div>
                            <label htmlFor="password" className="form-label">
                                Password
                            </label>
                            <div className="relative">
                                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                                    <HiLockClosed className="h-5 w-5 text-gray-400" />
                                </div>
                                <input
                                    id="password"
                                    name="password"
                                    type={showPassword ? 'text' : 'password'}
                                    autoComplete="current-password"
                                    required
                                    value={password}
                                    onChange={(e) => setPassword(e.target.value)}
                                    className="form-input pl-10 pr-10"
                                    placeholder="Enter your password"
                                />
                                <button
                                    type="button"
                                    className="absolute inset-y-0 right-0 pr-3 flex items-center"
                                    onClick={() => setShowPassword(!showPassword)}
                                >
                                    {showPassword ? (
                                        <HiEyeOff className="h-5 w-5 text-gray-400 hover:text-gray-600" />
                                    ) : (
                                        <HiEye className="h-5 w-5 text-gray-400 hover:text-gray-600" />
                                    )}
                                </button>
                            </div>
                        </div>

                        {/* Submit Button */}
                        <button
                            type="submit"
                            className="w-full btn btn-primary py-3 text-base font-medium"
                        >
                            Sign in
                        </button>
                    </form>

                    {/* Google Sign In */}
                    <div className="mt-4">
                        <div className="relative">
                            <div className="absolute inset-0 flex items-center">
                                <div className="w-full border-t border-gray-300" />
                            </div>
                            <div className="relative flex justify-center text-sm">
                                <span className="px-2 bg-white text-gray-500">or</span>
                            </div>
                        </div>
                        <button
                            type="button"
                            onClick={() => void handleGoogleSignIn()}
                            disabled={googleBusy}
                            className="mt-4 w-full btn btn-outline py-3 text-base font-medium flex items-center justify-center gap-2 disabled:opacity-50"
                        >
                            <svg className="h-5 w-5" viewBox="0 0 24 24" aria-hidden="true">
                                <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
                                <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                                <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
                                <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
                            </svg>
                            {googleBusy ? 'Signing in with Google…' : 'Continue with Google'}
                        </button>
                    </div>

                    {/* Forgot Password Link */}
                    <div className="mt-4 text-center">
                        <Link
                            to="/forgot-password"
                            className={`text-sm font-medium ${isAgentLogin ? 'text-emerald-600 hover:text-emerald-500' : 'text-blue-600 hover:text-blue-500'}`}
                        >
                            Forgot your password?
                        </Link>
                    </div>

                    {/* Divider */}
                    <div className="mt-6">
                        <div className="relative">
                            <div className="absolute inset-0 flex items-center">
                                <div className="w-full border-t border-gray-300" />
                            </div>
                            <div className="relative flex justify-center text-sm">
                                <span className="px-2 bg-white text-gray-500">New to RentDirect?</span>
                            </div>
                        </div>
                    </div>

                    {/* Sign Up Link */}
                    <div className="mt-6 text-center">
                        <Link
                            to={isAgentLogin ? '/agents/register' : '/register'}
                            className="btn btn-outline w-full py-3 text-base font-medium"
                        >
                            {isAgentLogin ? 'Become a PIO' : 'Create an account'}
                        </Link>
                    </div>
                </div>

                {/* Footer */}
                <div className="text-center">
                    <p className="text-sm text-gray-600">
                        By signing in, you agree to our{' '}
                        <Link to="/legal/terms-of-service" className={`font-medium ${isAgentLogin ? 'text-emerald-600 hover:text-emerald-500' : 'text-blue-600 hover:text-blue-500'}`}>
                            Terms of Service
                        </Link>{' '}
                        and{' '}
                        <Link to="/legal/privacy-policy" className={`font-medium ${isAgentLogin ? 'text-emerald-600 hover:text-emerald-500' : 'text-blue-600 hover:text-blue-500'}`}>
                            Privacy Policy
                        </Link>
                    </p>
                </div>
            </div>
        </div>
    )
}
