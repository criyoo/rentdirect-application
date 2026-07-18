import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'
import { HiEye, HiEyeOff, HiMail, HiLockClosed, HiUser, HiHome, HiUserGroup } from 'react-icons/hi'

export default function RegisterPage()
{
    const [formData, setFormData] = useState({
        name: '',
        email: '',
        password: '',
        role: 'tenant' as 'tenant' | 'landlord'
    })
    const [otpCode, setOtpCode] = useState('')
    const [pendingEmail, setPendingEmail] = useState('')
    const [otpExpiresIn, setOtpExpiresIn] = useState(0)
    const [isOtpStep, setIsOtpStep] = useState(false)
    const [isSubmitting, setIsSubmitting] = useState(false)
    const [showPassword, setShowPassword] = useState(false)
    const [error, setError] = useState('')
    const { register, verifyRegistration } = useAuth()

    const handleSubmit = async (e: React.FormEvent) =>
    {
        e.preventDefault()
        setError('')
        setIsSubmitting(true)

        try
        {
            const result = await register(formData)
            setPendingEmail(result.email)
            setOtpExpiresIn(result.expires_in_seconds)
            setIsOtpStep(true)
        } catch (err: any)
        {
            setError(err.message || 'Registration failed')
        } finally
        {
            setIsSubmitting(false)
        }
    }

    const handleVerifyOtp = async (e: React.FormEvent) =>
    {
        e.preventDefault()
        setError('')
        setIsSubmitting(true)

        try
        {
            await verifyRegistration({
                email: pendingEmail || formData.email,
                otp_code: otpCode
            })
        } catch (err: any)
        {
            setError(err.message || 'Verification failed')
        } finally
        {
            setIsSubmitting(false)
        }
    }

    const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    {
        setFormData(prev => ({
            ...prev,
            [e.target.name]: e.target.value
        }))
    }

    return (
        <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-purple-50 flex items-center justify-center py-12 px-4 sm:px-6 lg:px-8">
            <div className="max-w-md w-full space-y-8">
                {/* Header */}
                <div className="text-center">
                    <div className="flex justify-center mb-6">
                        <div className="w-16 h-16 bg-gradient-to-br from-blue-600 to-blue-700 rounded-2xl flex items-center justify-center shadow-lg">
                            <HiHome className="w-8 h-8 text-white" />
                        </div>
                    </div>
                    <h2 className="text-3xl font-bold text-gray-900 mb-2">
                        {isOtpStep ? 'Verify your email' : 'Create your account'}
                    </h2>
                    <p className="text-gray-600">
                        {isOtpStep ? `Enter the code sent to ${pendingEmail}` : 'Join RentDirect and find your perfect home'}
                    </p>
                </div>

                {/* Registration Form */}
                <div className="card p-8">
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
                        {/* Name Field */}
                        <div>
                            <label htmlFor="name" className="form-label">
                                Full name
                            </label>
                            <div className="relative">
                                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                                    <HiUser className="h-5 w-5 text-gray-400" />
                                </div>
                                <input
                                    id="name"
                                    name="name"
                                    type="text"
                                    autoComplete="name"
                                    required
                                    value={formData.name}
                                    onChange={handleChange}
                                    className="form-input pl-10"
                                    placeholder="Enter your full name"
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
                        <Link to="/terms" className="text-blue-600 hover:text-blue-500 font-medium">
                            Terms of Service
                        </Link>{' '}
                        and{' '}
                        <Link to="/privacy" className="text-blue-600 hover:text-blue-500 font-medium">
                            Privacy Policy
                        </Link>
                    </p>
                </div>
            </div>
        </div>
    )
}
