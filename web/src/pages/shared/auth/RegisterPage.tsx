import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'
import BrandLogo from '@/components/BrandLogo'
import RegistrationLegalConsentModal from '@/components/RegistrationLegalConsentModal'
import { buildFormDraftKey, readFormDraft, removeFormDraft, writeFormDraft } from '@/lib/formDrafts'
import { HiEye, HiEyeOff, HiMail, HiLockClosed, HiUser, HiUserGroup } from 'react-icons/hi'

function getRegistrationErrorMessage(err: any): string {
    const message = String(err?.message || 'Registration failed').trim()
    const normalizedMessage = message.toLowerCase()

    if (
        normalizedMessage.includes('email already registered') ||
        (normalizedMessage.includes('email') && normalizedMessage.includes('already'))
    ) {
        return 'Email already registered, try sign in'
    }

    return message || 'Registration failed'
}

export default function RegisterPage() {
    const navigate = useNavigate()
    const [searchParams] = useSearchParams()
    const requestedRole = searchParams.get('role')
    const isRoleLocked = requestedRole === 'tenant' || requestedRole === 'landlord'
    const initialRole = requestedRole === 'landlord' ? 'landlord' : 'tenant'
    const [formData, setFormData] = useState({
        firstName: '',
        middleName: '',
        lastName: '',
        email: '',
        password: '',
        role: initialRole as 'tenant' | 'landlord'
    })
    const [otpCode, setOtpCode] = useState('')
    const [pendingEmail, setPendingEmail] = useState('')
    const [otpExpiresIn, setOtpExpiresIn] = useState(0)
    const [isOtpStep, setIsOtpStep] = useState(false)
    const [isSubmitting, setIsSubmitting] = useState(false)
    const [showPassword, setShowPassword] = useState(false)
    const [error, setError] = useState('')
    const [isRegistrationConsentOpen, setIsRegistrationConsentOpen] = useState(false)
    const [verifiedUser, setVerifiedUser] = useState<{ id: string; role: 'tenant' | 'landlord' } | null>(null)
    const { register, verifyRegistration, logout } = useAuth()
    const draftStorageKey = useMemo(() => buildFormDraftKey('registration', 'anonymous'), [])

    useEffect(() => {
        const storedDraft = readFormDraft<{
            firstName?: string
            middleName?: string
            lastName?: string
            email?: string
            role?: 'tenant' | 'landlord'
            pendingEmail?: string
            isOtpStep?: boolean
        }>(draftStorageKey)
        if (!storedDraft) return

        setFormData((current) => ({
            ...current,
            firstName: storedDraft.firstName || '',
            middleName: storedDraft.middleName || '',
            lastName: storedDraft.lastName || '',
            email: storedDraft.email || '',
            role: isRoleLocked ? initialRole : storedDraft.role || current.role,
        }))
        setPendingEmail(storedDraft.pendingEmail || '')
        setIsOtpStep(Boolean(storedDraft.isOtpStep && storedDraft.pendingEmail))
    }, [draftStorageKey, initialRole, isRoleLocked])

    useEffect(() => {
        writeFormDraft(draftStorageKey, {
            firstName: formData.firstName,
            middleName: formData.middleName,
            lastName: formData.lastName,
            email: formData.email,
            role: formData.role,
            pendingEmail,
            isOtpStep,
        })
    }, [
        draftStorageKey,
        formData.email,
        formData.firstName,
        formData.lastName,
        formData.middleName,
        formData.role,
        isOtpStep,
        pendingEmail,
    ])

    // The navbar links can change only the query string while this page is open.
    // Keep the form role and verification step in sync without requiring a refresh.
    useEffect(() => {
        if (!isRoleLocked) return

        setFormData(prev => (prev.role === initialRole ? prev : { ...prev, role: initialRole }))
        setIsOtpStep(false)
        setOtpCode('')
        setPendingEmail('')
        setOtpExpiresIn(0)
        setError('')
    }, [initialRole, isRoleLocked])

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault()
        setError('')
        setIsSubmitting(true)

        try {
            const { firstName, middleName, lastName, ...registrationData } = formData
            const result = await register({
                ...registrationData,
                name: [firstName, middleName, lastName].filter(Boolean).join(' '),
            })
            setPendingEmail(result.email)
            setOtpExpiresIn(result.expires_in_seconds)
            setIsOtpStep(true)
        } catch (err: any) {
            setError(getRegistrationErrorMessage(err))
        } finally {
            setIsSubmitting(false)
        }
    }

    const handleVerifyOtp = async (e: React.FormEvent) => {
        e.preventDefault()
        setError('')
        setIsSubmitting(true)

        try {
            const verifiedUser = await verifyRegistration({
                email: pendingEmail || formData.email,
                otp_code: otpCode
            }, { navigate: false })
            if (verifiedUser.role !== 'tenant' && verifiedUser.role !== 'landlord') {
                throw new Error('This account type cannot complete registration here.')
            }
            removeFormDraft(draftStorageKey)
            setVerifiedUser({ id: verifiedUser.id, role: verifiedUser.role })
            setIsRegistrationConsentOpen(true)
        } catch (err: any) {
            setError(err.message || 'Verification failed')
        } finally {
            setIsSubmitting(false)
        }
    }

    const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
        setFormData(prev => ({
            ...prev,
            [e.target.name]: e.target.value
        }))
    }

    const displayedRole = isRoleLocked ? initialRole : formData.role

    const handleRegistrationConsent = () => {
        if (!verifiedUser) return

        if (verifiedUser.role === 'landlord') {
            localStorage.setItem('landlord_onboarding_pending_identity', '1')
            navigate(`/dashboard/landlord/${verifiedUser.id}`, {
                state: {
                    registrationNotice:
                        'Verification, Profile completion and a subscription plan is required to create listing',
                },
            })
        } else {
            navigate(`/dashboard/tenant/${verifiedUser.id}`, {
                state: {
                    registrationNotice:
                        'Verification, Profile completion and a subscription plan is required to contact landlord and rent a property',
                },
            })
        }
    }

    return (
        <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-purple-50 flex items-center justify-center py-12 px-4 sm:px-6 lg:px-8">
            <div className="max-w-xl w-full space-y-8">
                {/* Header */}
                <div className="text-center">
                    <div
                        className="flex justify-center mb-6 select-none"
                        onContextMenu={(event) => event.preventDefault()}
                    >
                        <BrandLogo className="h-80 w-80 pointer-events-none mix-blend-multiply outline-none focus:outline-none" />
                    </div>
                    <h2 className="text-3xl font-bold text-gray-900">
                        {isOtpStep
                            ? 'Verify your email'
                            : isRoleLocked
                                ? `Create your ${displayedRole} account`
                                : 'Create your account'}
                    </h2>
                    <p className="text-gray-600">
                        {isOtpStep
                            ? `Enter the code sent to ${pendingEmail}`
                            : isRoleLocked
                                ? displayedRole === 'landlord'
                                    ? 'List your properties and connect directly with verified tenants'
                                    : 'Find verified properties and connect directly with landlords'
                                : 'Join RentDirect and choose how you want to use the platform'}
                    </p>
                </div>

                {/* Registration Form */}
                <div className="card p-6">
                    <form onSubmit={isOtpStep ? handleVerifyOtp : handleSubmit} className="space-y-6">
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

                        {isOtpStep ? (
                            <>
                                <div>
                                    <label htmlFor="otp_code" className="form-label">
                                        Verification code
                                    </label>
                                    <div className="relative">
                                        <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                                            <HiLockClosed className="h-5 w-5 text-gray-400" />
                                        </div>
                                        <input
                                            id="otp_code"
                                            name="otp_code"
                                            type="text"
                                            inputMode="text"
                                            autoComplete="one-time-code"
                                            required
                                            maxLength={6}
                                            value={otpCode}
                                            onChange={(event) => setOtpCode(event.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ''))}
                                            className="form-input pl-10 uppercase tracking-widest"
                                            placeholder="A1B2C3"
                                        />
                                    </div>
                                    <p className="mt-2 text-sm text-gray-500">
                                        Expires in {Math.ceil(otpExpiresIn / 60)} minutes.
                                    </p>
                                </div>

                                <button
                                    type="submit"
                                    disabled={isSubmitting || otpCode.length !== 6}
                                    className="w-full btn btn-primary py-3 text-base font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                                >
                                    {isSubmitting ? 'Verifying...' : 'Verify account'}
                                </button>

                                <button
                                    type="button"
                                    disabled={isSubmitting}
                                    className="w-full btn btn-outline py-3 text-base font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                                    onClick={() => {
                                        setIsOtpStep(false)
                                        setOtpCode('')
                                        setError('')
                                    }}
                                >
                                    Edit registration details
                                </button>
                            </>
                        ) : (
                            <>
                                <div className="grid gap-4 sm:grid-cols-3">
                                    <div>
                                        <label htmlFor="firstName" className="form-label">First name</label>
                                        <input
                                            id="firstName"
                                            name="firstName"
                                            type="text"
                                            autoComplete="given-name"
                                            required
                                            value={formData.firstName}
                                            onChange={handleChange}
                                            className="form-input"
                                            placeholder="Enter first name"
                                        />
                                    </div>
                                    <div>
                                        <label htmlFor="middleName" className="form-label">Middle name</label>
                                        <input
                                            id="middleName"
                                            name="middleName"
                                            type="text"
                                            autoComplete="additional-name"
                                            value={formData.middleName}
                                            onChange={handleChange}
                                            className="form-input"
                                            placeholder="Optional - Enter middle name"
                                        />
                                    </div>
                                    <div>
                                        <label htmlFor="lastName" className="form-label">Last name</label>
                                        <input
                                            id="lastName"
                                            name="lastName"
                                            type="text"
                                            autoComplete="family-name"
                                            required
                                            value={formData.lastName}
                                            onChange={handleChange}
                                            className="form-input"
                                            placeholder="Enter last name"
                                        />
                                    </div>
                                </div>

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
                                            value={formData.email}
                                            onChange={handleChange}
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
                                            autoComplete="new-password"
                                            required
                                            value={formData.password}
                                            onChange={handleChange}
                                            className="form-input pl-10 pr-10"
                                            placeholder="Create a password"
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

                                {/* Role Selection */}
                                {!isRoleLocked && (
                                    <div>
                                        <label htmlFor="role" className="form-label">
                                            I am a
                                        </label>
                                        <div className="grid grid-cols-2 gap-3">
                                            <label className="relative">
                                                <input
                                                    type="radio"
                                                    name="role"
                                                    value="tenant"
                                                    checked={formData.role === 'tenant'}
                                                    onChange={handleChange}
                                                    className="sr-only"
                                                />
                                                <div className={`p-4 border-2 rounded-lg cursor-pointer transition-all duration-200 ${formData.role === 'tenant'
                                                    ? 'border-blue-500 bg-blue-50'
                                                    : 'border-gray-200 hover:border-gray-300'
                                                    }`}>
                                                    <div className="flex items-center space-x-3">
                                                        <HiUser className="w-5 h-5 text-gray-600" />
                                                        <div>
                                                            <div className="font-medium text-gray-900">Tenant</div>
                                                            <div className="text-sm text-gray-500">Looking for a home</div>
                                                        </div>
                                                    </div>
                                                </div>
                                            </label>
                                            <label className="relative">
                                                <input
                                                    type="radio"
                                                    name="role"
                                                    value="landlord"
                                                    checked={formData.role === 'landlord'}
                                                    onChange={handleChange}
                                                    className="sr-only"
                                                />
                                                <div className={`p-4 border-2 rounded-lg cursor-pointer transition-all duration-200 ${formData.role === 'landlord'
                                                    ? 'border-blue-500 bg-blue-50'
                                                    : 'border-gray-200 hover:border-gray-300'
                                                    }`}>
                                                    <div className="flex items-center space-x-3">
                                                        <HiUserGroup className="w-5 h-5 text-gray-600" />
                                                        <div>
                                                            <div className="font-medium text-gray-900">Landlord</div>
                                                            <div className="text-sm text-gray-500">Renting out property</div>
                                                        </div>
                                                    </div>
                                                </div>
                                            </label>
                                        </div>
                                    </div>
                                )}

                                {/* Submit Button */}
                                <button
                                    type="submit"
                                    disabled={isSubmitting}
                                    className="w-full btn btn-primary py-3 text-base font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                                >
                                    {isSubmitting ? 'Sending code...' : 'Create account'}
                                </button>
                            </>
                        )}
                    </form>

                    {/* Divider */}
                    <div className="mt-6">
                        <div className="relative">
                            <div className="absolute inset-0 flex items-center">
                                <div className="w-full border-t border-gray-300" />
                            </div>
                            <div className="relative flex justify-center text-sm">
                                <span className="px-2 bg-white text-gray-500">Already have an account?</span>
                            </div>
                        </div>
                    </div>

                    {/* Sign In Link */}
                    <div className="mt-6 text-center">
                        <Link
                            to="/login"
                            className="btn btn-outline w-full py-3 text-base font-medium"
                        >
                            Sign in to your account
                        </Link>
                    </div>
                </div>

                {/* Footer */}
                <div className="text-center">
                    <p className="text-sm text-gray-600">
                        By creating an account, you agree to our{' '}
                        <Link to="/legal/terms-of-service" className="text-blue-600 hover:text-blue-500 font-medium">
                            Terms of Service
                        </Link>{' '}
                        and{' '}
                        <Link to="/legal/privacy-policy" className="text-blue-600 hover:text-blue-500 font-medium">
                            Privacy Policy
                        </Link>
                    </p>
                </div>

                <RegistrationLegalConsentModal
                    isOpen={isRegistrationConsentOpen}
                    role={verifiedUser?.role || displayedRole}
                    onAccept={handleRegistrationConsent}
                    onCancel={() => {
                        setIsRegistrationConsentOpen(false)
                        void logout()
                    }}
                />
            </div>
        </div>
    )
}
