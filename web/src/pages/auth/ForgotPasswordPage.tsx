import { useState } from 'react'
import { api } from '@/lib/api'
import BrandLogo from '@/components/BrandLogo'
import { HiMail } from 'react-icons/hi'
import DashboardBackButton from '@/components/DashboardBackButton'

export default function ForgotPasswordPage()
{
    const [email, setEmail] = useState('')
    const [isLoading, setIsLoading] = useState(false)
    const [isSubmitted, setIsSubmitted] = useState(false)
    const [error, setError] = useState('')

    const handleSubmit = async (e: React.FormEvent) =>
    {
        e.preventDefault()
        setError('')
        setIsLoading(true)

        try
        {
            const response = await api.post('/auth/forgot-password', { email })
            console.log('Forgot password response:', response)
            setIsSubmitted(true)
        } catch (err: any)
        {
            console.error('Forgot password error:', err)
            console.error('Error response:', err.response)
            console.error('Error message:', err.message)
            setError(err.response?.data?.detail || 'Failed to send reset email')
        } finally
        {
            setIsLoading(false)
        }
    }

    if (isSubmitted)
    {
        return (
            <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-purple-50 flex items-center justify-center py-12 px-4 sm:px-6 lg:px-8">
                <div className="max-w-md w-full space-y-8">
                    {/* Header */}
                    <div className="text-center">
                        <div className="flex justify-center mb-6">
                            <div className="w-16 h-16 bg-gradient-to-br from-green-600 to-green-700 rounded-2xl flex items-center justify-center shadow-lg">
                                <HiMail className="w-8 h-8 text-white" />
                            </div>
                        </div>
                        <h2 className="text-3xl font-bold text-gray-900 mb-2">
                            Check your email
                        </h2>
                        <p className="text-gray-600">
                            We've sent a password reset link to <strong>{email}</strong>
                        </p>
                    </div>

                    {/* Success Message */}
                    <div className="card p-8">
                        <div className="text-center space-y-4">
                            <div className="w-12 h-12 bg-green-100 rounded-full flex items-center justify-center mx-auto">
                                <svg className="w-6 h-6 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                                </svg>
                            </div>
                            <div>
                                <h3 className="text-lg font-medium text-gray-900 mb-2">Email sent successfully!</h3>
                                <p className="text-sm text-gray-600">
                                    Please check your email and click the reset link to create a new password.
                                </p>
                            </div>
                            <div className="space-y-3">
                                <DashboardBackButton to="/login" label="Back to Login" className="w-full justify-center" />
                                <button
                                    onClick={() =>
                                    {
                                        setIsSubmitted(false)
                                        setEmail('')
                                    }}
                                    className="w-full btn btn-outline py-3 text-base font-medium"
                                >
                                    Try different email
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        )
    }

    return (
        <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-purple-50 flex items-center justify-center py-12 px-4 sm:px-6 lg:px-8">
            <div className="max-w-md w-full space-y-8">
                {/* Header */}
                <div className="text-center">
                    <div className="flex justify-center mb-6">
                        <BrandLogo className="h-24 w-40 rounded-xl bg-white p-2 shadow-lg" />
                    </div>
                    <h2 className="text-3xl font-bold text-gray-900 mb-2">
                        Forgot your password?
                    </h2>
                    <p className="text-gray-600">
                        No worries! Enter your email and we'll send you a reset link.
                    </p>
                </div>

                {/* Reset Form */}
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
                                    placeholder="Enter your email address"
                                />
                            </div>
                        </div>

                        {/* Submit Button */}
                        <button
                            type="submit"
                            disabled={isLoading}
                            className="w-full btn btn-primary py-3 text-base font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            {isLoading ? 'Sending...' : 'Send reset link'}
                        </button>
                    </form>

                    {/* Back to Login */}
                    <div className="mt-6 text-center">
                        <DashboardBackButton to="/login" label="Back to login" />
                    </div>
                </div>
            </div>
        </div>
    )
}
